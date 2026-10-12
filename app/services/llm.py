"""IA (seção 6 da spec): `LLMProvider` (Gemini no Vertex AI ou Anthropic) e `Tutor`, as funções
de negócio — `explain`, `evaluate`, `examples`, `expansions`, `synonyms`, `route`, `review`,
`song_line` — que não sabem
qual provedor está por baixo (ADR-0005).
"""

from __future__ import annotations

import json
import logging
import time
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from app.config import Settings
from app.domain.models import (
    AvaliacaoDaPergunta,
    Evaluation,
    Exemplos,
    Expansion,
    Expansoes,
    Explanation,
    LinhaDaMusica,
    NivelUsuario,
    PerguntaSemanal,
    PerguntasSemanais,
    Revisao,
    Roteamento,
    Sense,
    SentidoSalvo,
    Sinonimos,
    Synonym,
    nivel_so_ingles,
)
from app.logging_config import registrar_evento
from app.services import custo, prompts
from app.services.prompts import Prompt

logger = logging.getLogger(__name__)

TEMPERATURA_PRECISA = 0.2  # explicar e avaliar: queremos consistência
TEMPERATURA_CRIATIVA = 0.3  # exemplos e expansões: um pouco de variedade
MAX_TENTATIVAS = 2  # a original + 1 nova tentativa (seção 6)
_MAX_TOKENS_ANTHROPIC = 2048
# M44 (ADR-0042): teto de saída (inclui o "thinking" nos modelos 3.x). As maiores respostas do bot
# (10 perguntas do desafio semanal, 4 sentidos com exemplos) cabem folgadas em 2.048 tokens.
MAX_TOKENS_DE_SAIDA = 2048
_NOME_DA_FERRAMENTA = "responder"

# Vertex AI responde 429 (RESOURCE_EXHAUSTED) quando a capacidade compartilhada do modelo aperta,
# mesmo com o nosso volume minúsculo; costuma passar em segundos. Sem retentativa, cada 429 virava
# um "algo deu errado" para o aluno. 4 tentativas com espera 1 s, 2 s, 4 s (+ jitter).
_RETENTATIVA_GEMINI = types.HttpRetryOptions(
    attempts=4,
    initial_delay=1.0,
    max_delay=8.0,
    exp_base=2.0,
    http_status_codes=[408, 429, 500, 502, 503, 504],
)


class LLMError(Exception):
    """A IA não devolveu uma resposta utilizável."""


class LLMProvider(Protocol):
    """Devolve o JSON (texto) que respeita o `schema`. A validação e a nova tentativa ficam
    fora, iguais para qualquer provedor."""

    def gerar(
        self,
        *,
        sistema: str,
        usuario: str,
        schema: type[BaseModel],
        modelo: str,
        temperatura: float,
    ) -> str: ...


class Tutor(Protocol):
    def explain(
        self, texto: str, nivel: NivelUsuario, palavras_do_aluno: Sequence[str] = ()
    ) -> Explanation: ...

    def evaluate(
        self, palavra: str, sentido: SentidoSalvo | Sense, frase: str, nivel: NivelUsuario
    ) -> Evaluation: ...

    def examples(
        self,
        palavra: str,
        sentido: SentidoSalvo | Sense,
        nivel: NivelUsuario,
        n: int = 3,
        ja_mostrados: Sequence[str] = (),
        palavras_do_aluno: Sequence[str] = (),
    ) -> list[str]: ...

    def expansions(
        self,
        palavra: str,
        sentido: SentidoSalvo | Sense,
        nivel: NivelUsuario,
        ja_existentes: Sequence[str],
    ) -> list[Expansion]: ...

    def synonyms(
        self,
        palavra: str,
        sentido: SentidoSalvo | Sense,
        nivel: NivelUsuario,
        n: int = 3,
        ja_mostrados: Sequence[str] = (),
    ) -> list[Synonym]: ...

    def route(
        self, palavra: str, sentido: SentidoSalvo | Sense, texto: str, nivel: NivelUsuario
    ) -> Roteamento: ...

    def review(
        self,
        palavra: str,
        sentido: SentidoSalvo | Sense,
        resposta: str,
        nivel: NivelUsuario,
    ) -> Revisao: ...

    def song_line(
        self,
        titulo: str,
        artista: str,
        verso: str,
        verso_anterior: str | None,
        resposta: str,
        nivel: NivelUsuario,
    ) -> LinhaDaMusica: ...

    def weekly_questions(
        self, vocabulario: Sequence[tuple[str, str]], nivel: NivelUsuario, n: int
    ) -> list[PerguntaSemanal]: ...

    def weekly_answer(
        self, pergunta: str, palavras: Sequence[str], resposta: str, nivel: NivelUsuario
    ) -> AvaliacaoDaPergunta: ...


class VertexGeminiProvider:
    """`google-genai` no Vertex AI: autenticação pela conta de serviço da VM, sem chave."""

    def __init__(
        self, client: Any, *, thinking_level: str | None = None
    ) -> None:  # genai.Client, ou um dublê nos testes
        self._client = client
        self._thinking_level = thinking_level

    def gerar(
        self,
        *,
        sistema: str,
        usuario: str,
        schema: type[BaseModel],
        modelo: str,
        temperatura: float,
    ) -> str:
        try:
            resposta = self._chamar(modelo, usuario, sistema, schema, temperatura)
        except genai_errors.APIError as erro:
            # Só o código e o status: o corpo da resposta não vai para o log nem para a mensagem.
            raise LLMError(f"o Gemini recusou a chamada ({erro.code} {erro.status})") from erro
        except httpx.HTTPError as erro:
            raise LLMError(f"sem resposta do Gemini ({type(erro).__name__})") from erro
        custo.registrar_resposta(resposta)
        texto: str | None = resposta.text
        if not texto:
            raise LLMError("o Gemini não devolveu texto (resposta vazia ou bloqueada)")
        return texto

    def _config(
        self, sistema: str, schema: type[BaseModel], temperatura: float
    ) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=sistema,
            temperature=temperatura,
            response_mime_type="application/json",
            response_schema=schema,
            max_output_tokens=MAX_TOKENS_DE_SAIDA,
            thinking_config=nivel_de_raciocinio(self._thinking_level),
            # Não usamos ferramentas; sem isto o SDK entra no caminho de "function calling
            # automático" e avisa que ele não é recomendado em generate_content.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    def _chamar(
        self, modelo: str, usuario: str, sistema: str, schema: type[BaseModel], temperatura: float
    ) -> Any:
        config = self._config(sistema, schema, temperatura)
        try:
            return self._client.models.generate_content(
                model=modelo, contents=usuario, config=config
            )
        except genai_errors.ClientError as erro:
            if self._thinking_level is None or erro.code != 400:
                raise
            # O modelo recusou o nível de raciocínio (cada modelo 3.x aceita um conjunto): desliga o
            # ajuste neste processo e refaz a chamada, para a IA nunca cair por causa dele.
            logger.warning(
                "o modelo recusou thinking_level=%s; seguindo com o padrão do modelo",
                self._thinking_level,
            )
            self._thinking_level = None
            return self._client.models.generate_content(
                model=modelo, contents=usuario, config=self._config(sistema, schema, temperatura)
            )


def nivel_de_raciocinio(nivel: str | None) -> types.ThinkingConfig | None:
    """`minimal`/`low`/`medium`/`high` (M44, ADR-0042) ou `None` para o padrão do modelo."""
    if not nivel:
        return None
    return types.ThinkingConfig(thinking_level=types.ThinkingLevel(nivel.upper()))


class AnthropicProvider:
    """Opcional (`LLM_PROVIDER=anthropic`): uma única ferramenta por tarefa, com o schema
    Pydantic como `input_schema`, e `tool_choice` forçando essa ferramenta."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def gerar(
        self,
        *,
        sistema: str,
        usuario: str,
        schema: type[BaseModel],
        modelo: str,
        temperatura: float,
    ) -> str:
        resposta = self._client.messages.create(
            model=modelo,
            max_tokens=_MAX_TOKENS_ANTHROPIC,
            temperature=temperatura,
            system=sistema,
            messages=[{"role": "user", "content": usuario}],
            tools=[
                {
                    "name": _NOME_DA_FERRAMENTA,
                    "description": f"Devolve a resposta no formato {schema.__name__}.",
                    "input_schema": schema.model_json_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": _NOME_DA_FERRAMENTA},
        )
        for bloco in resposta.content:
            if bloco.type == "tool_use":
                return json.dumps(bloco.input)
        raise LLMError("a Anthropic não devolveu a ferramenta esperada")


# M27 (ADR-0028): nome do método para o evento `llm_chamada` (seção 12 da spec) — cada schema de
# saída corresponde a uma única tarefa do `Tutor`.
_METODO_POR_SCHEMA: dict[type[BaseModel], str] = {
    Explanation: "explain",
    Evaluation: "evaluate",
    Exemplos: "examples",
    Expansoes: "expansions",
    Sinonimos: "synonyms",
    Roteamento: "route",
    Revisao: "review",
    LinhaDaMusica: "song_line",
    PerguntasSemanais: "weekly_questions",
    AvaliacaoDaPergunta: "weekly_answer",
}


def _chave(expressao: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", expressao).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


def _gerar_validado[T: BaseModel](
    provider: LLMProvider,
    prompt: Prompt,
    schema: type[T],
    *,
    modelo: str,
    temperatura: float,
    validar: Callable[[T], None] | None = None,
) -> T:
    """Valida com Pydantic (e com `validar`, para regras que o schema não expressa); em caso de
    erro, uma nova tentativa avisando o modelo do que estava errado.

    Emite `llm_chamada` (M27, ADR-0028, seção 12 da spec) uma vez por chamada, cobrindo todas as
    tentativas: `ok=False` tanto para uma falha de transporte (`LLMError` do provider) quanto para
    todas as tentativas rejeitadas na validação."""
    inicio = time.monotonic()
    with custo.medir() as uso:
        return _gerar_com_retentativa(
            provider, prompt, schema, modelo, temperatura, validar, inicio, uso
        )


def _gerar_com_retentativa[T: BaseModel](
    provider: LLMProvider,
    prompt: Prompt,
    schema: type[T],
    modelo: str,
    temperatura: float,
    validar: Callable[[T], None] | None,
    inicio: float,
    uso: custo.Uso,
) -> T:
    ok = False
    try:
        usuario = prompt.usuario
        ultimo_erro: ValueError | None = None
        for _ in range(MAX_TENTATIVAS):
            bruto = provider.gerar(
                sistema=prompt.sistema,
                usuario=usuario,
                schema=schema,
                modelo=modelo,
                temperatura=temperatura,
            )
            try:
                resultado = schema.model_validate_json(bruto)
                if validar is not None:
                    validar(resultado)
            except ValueError as erro:  # ValidationError (JSON ou schema) é um ValueError
                ultimo_erro = erro
                logger.warning("resposta da IA rejeitada (%s)", type(erro).__name__)
                usuario = (
                    f"{prompt.usuario}\n\nSua resposta anterior foi rejeitada: {str(erro)[:400]}\n"
                    "Responda de novo, seguindo exatamente o schema e as regras."
                )
            else:
                ok = True
                return resultado
        raise LLMError(
            f"a IA não devolveu uma resposta válida ({schema.__name__})"
        ) from ultimo_erro
    finally:
        custo.notificar_gasto(custo.custo_usd(modelo, uso))
        registrar_evento(
            logger,
            "llm_chamada",
            metodo=_METODO_POR_SCHEMA.get(schema, schema.__name__),
            modelo=modelo,
            ok=ok,
            latencia_ms=round((time.monotonic() - inicio) * 1000),
            tokens_entrada=uso.entrada,
            tokens_saida=uso.saida,
            tokens_thinking=uso.raciocinio,
            custo_usd=round(custo.custo_usd(modelo, uso), 6),
        )


class LLMTutor:
    """As quatro tarefas de IA. `modelo_avaliacao` pode ser um modelo maior (seção 4)."""

    def __init__(self, provider: LLMProvider, *, modelo: str, modelo_avaliacao: str) -> None:
        self._provider = provider
        self._modelo = modelo
        self._modelo_avaliacao = modelo_avaliacao

    def explain(
        self, texto: str, nivel: NivelUsuario, palavras_do_aluno: Sequence[str] = ()
    ) -> Explanation:
        return _gerar_validado(
            self._provider,
            prompts.prompt_explain(nivel, texto, palavras_do_aluno),
            Explanation,
            modelo=self._modelo,
            temperatura=TEMPERATURA_PRECISA,
        )

    def evaluate(
        self, palavra: str, sentido: SentidoSalvo | Sense, frase: str, nivel: NivelUsuario
    ) -> Evaluation:
        return _gerar_validado(
            self._provider,
            prompts.prompt_evaluate(nivel, palavra, sentido, frase),
            Evaluation,
            modelo=self._modelo_avaliacao,
            temperatura=TEMPERATURA_PRECISA,
        )

    def examples(
        self,
        palavra: str,
        sentido: SentidoSalvo | Sense,
        nivel: NivelUsuario,
        n: int = 3,
        ja_mostrados: Sequence[str] = (),
        palavras_do_aluno: Sequence[str] = (),
    ) -> list[str]:
        def quantidade_certa(exemplos: Exemplos) -> None:
            if len(exemplos.frases) != n:
                raise ValueError(f"esperava {n} frases, vieram {len(exemplos.frases)}")

        resultado = _gerar_validado(
            self._provider,
            prompts.prompt_examples(nivel, palavra, sentido, n, ja_mostrados, palavras_do_aluno),
            Exemplos,
            modelo=self._modelo,
            temperatura=TEMPERATURA_CRIATIVA,
            validar=quantidade_certa,
        )
        return resultado.frases

    def expansions(
        self,
        palavra: str,
        sentido: SentidoSalvo | Sense,
        nivel: NivelUsuario,
        ja_existentes: Sequence[str],
    ) -> list[Expansion]:
        proibidas = {_chave(e) for e in ja_existentes} | {_chave(palavra)}

        def sem_repeticao(expansoes: Expansoes) -> None:
            vistas: set[str] = set()
            for item in expansoes.itens:
                chave = _chave(item.expressao)
                if chave in proibidas or chave in vistas:
                    raise ValueError(f"expressão repetida ou já existente: {item.expressao!r}")
                vistas.add(chave)

        resultado = _gerar_validado(
            self._provider,
            prompts.prompt_expansions(nivel, palavra, sentido, ja_existentes),
            Expansoes,
            modelo=self._modelo,
            temperatura=TEMPERATURA_CRIATIVA,
            validar=sem_repeticao,
        )
        return resultado.itens

    def synonyms(
        self,
        palavra: str,
        sentido: SentidoSalvo | Sense,
        nivel: NivelUsuario,
        n: int = 3,
        ja_mostrados: Sequence[str] = (),
    ) -> list[Synonym]:
        proibidos = {_chave(e) for e in ja_mostrados} | {_chave(palavra)}

        def sem_repeticao(sinonimos: Sinonimos) -> None:
            vistos: set[str] = set()
            for item in sinonimos.itens:
                chave = _chave(item.expressao)
                if chave in proibidos or chave in vistos:
                    raise ValueError(f"sinônimo repetido ou já mostrado: {item.expressao!r}")
                vistos.add(chave)

        resultado = _gerar_validado(
            self._provider,
            prompts.prompt_synonyms(nivel, palavra, sentido, n, ja_mostrados),
            Sinonimos,
            modelo=self._modelo,
            temperatura=TEMPERATURA_CRIATIVA,
            validar=sem_repeticao,
        )
        return resultado.itens

    def route(
        self, palavra: str, sentido: SentidoSalvo | Sense, texto: str, nivel: NivelUsuario
    ) -> Roteamento:
        return _gerar_validado(
            self._provider,
            prompts.prompt_route(nivel, palavra, sentido, texto),
            Roteamento,
            modelo=self._modelo_avaliacao,
            temperatura=TEMPERATURA_PRECISA,
        )

    def review(
        self,
        palavra: str,
        sentido: SentidoSalvo | Sense,
        resposta: str,
        nivel: NivelUsuario,
    ) -> Revisao:
        return _gerar_validado(
            self._provider,
            prompts.prompt_review(nivel, palavra, sentido, resposta),
            Revisao,
            modelo=self._modelo_avaliacao,
            temperatura=TEMPERATURA_PRECISA,
        )

    def song_line(
        self,
        titulo: str,
        artista: str,
        verso: str,
        verso_anterior: str | None,
        resposta: str,
        nivel: NivelUsuario,
    ) -> LinhaDaMusica:
        return _gerar_validado(
            self._provider,
            prompts.prompt_song_line(nivel, titulo, artista, verso, verso_anterior, resposta),
            LinhaDaMusica,
            modelo=self._modelo_avaliacao,
            temperatura=TEMPERATURA_PRECISA,
        )

    def weekly_questions(
        self, vocabulario: Sequence[tuple[str, str]], nivel: NivelUsuario, n: int
    ) -> list[PerguntaSemanal]:
        """`n` perguntas no nível da turma com palavras do vocabulário (M36). Valida a quantidade e
        que `palavras` vêm da lista; `explicacao_pt` só existe em turma iniciante."""
        com_portugues = not nivel_so_ingles(nivel)
        permitidas = {_chave(palavra) for palavra, _ in vocabulario}

        def regras(perguntas: PerguntasSemanais) -> None:
            if len(perguntas.itens) != n:
                raise ValueError(f"esperava {n} perguntas, vieram {len(perguntas.itens)}")
            for item in perguntas.itens:
                fora = [p for p in item.palavras if _chave(p) not in permitidas]
                if fora:
                    raise ValueError(f"palavras fora do vocabulário da turma: {fora}")
                if com_portugues and not item.explicacao_pt.strip():
                    raise ValueError("turma iniciante: `explicacao_pt` é obrigatória")

        resultado = _gerar_validado(
            self._provider,
            prompts.prompt_weekly_questions(nivel, vocabulario, n, com_portugues=com_portugues),
            PerguntasSemanais,
            modelo=self._modelo,
            temperatura=TEMPERATURA_CRIATIVA,
            validar=regras,
        )
        if com_portugues:
            return resultado.itens
        return [item.model_copy(update={"explicacao_pt": ""}) for item in resultado.itens]

    def weekly_answer(
        self, pergunta: str, palavras: Sequence[str], resposta: str, nivel: NivelUsuario
    ) -> AvaliacaoDaPergunta:
        return _gerar_validado(
            self._provider,
            prompts.prompt_weekly_answer(nivel, pergunta, palavras, resposta),
            AvaliacaoDaPergunta,
            modelo=self._modelo_avaliacao,
            temperatura=TEMPERATURA_PRECISA,
        )


def criar_cliente_vertex(*, projeto: str, localizacao: str) -> genai.Client:
    # `vertexai=True` é o nome que funciona em todas as versões do SDK (nas recentes é o apelido
    # legado de `enterprise=True`).
    return genai.Client(
        vertexai=True,
        project=projeto,
        location=localizacao,
        http_options=types.HttpOptions(retry_options=_RETENTATIVA_GEMINI),
    )


def criar_provider_vertex(
    *, projeto: str, localizacao: str, thinking_level: str | None = None
) -> VertexGeminiProvider:
    return VertexGeminiProvider(
        criar_cliente_vertex(projeto=projeto, localizacao=localizacao),
        thinking_level=thinking_level,
    )


def criar_provider_anthropic(*, api_key: str) -> AnthropicProvider:
    try:
        import anthropic
    except ImportError as erro:
        raise LLMError(
            "LLM_PROVIDER=anthropic exige o pacote `anthropic` (uv sync --group evals)"
        ) from erro
    return AnthropicProvider(anthropic.Anthropic(api_key=api_key))


def criar_tutor(settings: Settings) -> LLMTutor:
    if settings.llm_provider == "anthropic":
        if settings.anthropic_api_key is None:
            raise LLMError("LLM_PROVIDER=anthropic exige ANTHROPIC_API_KEY")
        provider: LLMProvider = criar_provider_anthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )
        return LLMTutor(
            provider, modelo=settings.anthropic_model, modelo_avaliacao=settings.anthropic_model
        )
    if not settings.gemini_model:
        raise LLMError("LLM_PROVIDER=vertex_gemini exige GEMINI_MODEL")
    provider = criar_provider_vertex(
        projeto=settings.gcp_project_id,
        localizacao=settings.vertex_location,
        thinking_level=settings.gemini_thinking_level,
    )
    return LLMTutor(
        provider,
        modelo=settings.gemini_model,
        modelo_avaliacao=settings.gemini_model_eval or settings.gemini_model,
    )


MODELO_ANTHROPIC_PADRAO = "claude-haiku-4-5-20251001"


def tutor_do_ambiente(
    provider: str, modelo: str | None, env: Mapping[str, str]
) -> tuple[LLMTutor, str]:
    """Monta um tutor a partir de variáveis de ambiente, sem passar pelo `Settings` (que exige
    a configuração inteira do bot). Usado pelos evals e pelo simulador; devolve também o ID do
    modelo escolhido. Levanta `LLMError` se faltar configuração."""
    if provider == "anthropic":
        chave = env.get("ANTHROPIC_API_KEY")
        if not chave:
            raise LLMError("defina ANTHROPIC_API_KEY no ambiente")
        escolhido = modelo or env.get("ANTHROPIC_MODEL") or MODELO_ANTHROPIC_PADRAO
        api: LLMProvider = criar_provider_anthropic(api_key=chave)
    else:
        projeto = env.get("GCP_PROJECT_ID")
        if not projeto:
            raise LLMError("defina GCP_PROJECT_ID no ambiente")
        escolhido = modelo or env.get("GEMINI_MODEL_EVAL") or env.get("GEMINI_MODEL") or ""
        if not escolhido:
            raise LLMError("informe o modelo com --model ou GEMINI_MODEL no ambiente")
        api = criar_provider_vertex(
            projeto=projeto, localizacao=env.get("VERTEX_LOCATION", "global")
        )
    return LLMTutor(api, modelo=escolhido, modelo_avaliacao=escolhido), escolhido
