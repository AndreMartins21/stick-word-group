"""Modelos de domínio (seções 6 e 7.1 da spec): o que entra no banco ou na sessão, e os
schemas de saída do LLM (`Explanation`, `Evaluation`, `Exemplos`, `Expansoes`, `Sinonimos`,
`Roteamento`, `Revisao`, `PerguntasSemanais`)."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

NivelUsuario = Literal["A1-A2", "A2-B1", "B1-B2", "B2-C1", "C1-C2", "C2"]
NIVEIS: tuple[NivelUsuario, ...] = get_args(NivelUsuario)  # do mais básico ao mais avançado


def ordem_do_nivel(nivel: str | None) -> int:
    """Posição do nível em `NIVEIS`; sem nível (ou desconhecido) vai para o fim."""
    return NIVEIS.index(nivel) if nivel in NIVEIS else len(NIVEIS)


# De B1-B2 para cima a turma não vê português (M34, ADR-0032).
NIVEIS_SO_INGLES: frozenset[str] = frozenset({"B1-B2", "B2-C1", "C1-C2", "C2"})


def nivel_so_ingles(nivel: str) -> bool:
    return nivel in NIVEIS_SO_INGLES


Cefr = Literal["A2", "B1", "B2", "C1", "C2"]
Tag = Literal["trabalho", "phrasal_verb", "expressao"]
Veredito = Literal["correta", "correta_pouco_natural", "quase", "incorreta"]
StatusEntrada = Literal["nova", "praticada"]
TipoExpansao = Literal["colocacao", "familia", "phrasal_verb", "sinonimo", "expressao"]
Intencao = Literal[
    "frase", "exemplos", "sinonimos", "salvar", "nova_palavra", "pedido", "fora_do_escopo"
]
QualidadeRevisao = Literal["de_novo", "dificil", "bom", "facil"]


def agora_utc() -> datetime:
    return datetime.now(UTC)


class Estado(StrEnum):
    """Estados da conversa (seção 5.1, M9/M10): só há uma palavra em foco por vez (`IDLE`) e um
    único menu de ações enquanto ela está em foco (`AWAIT_ACTION`); `REVIEWING` é a sessão de
    revisão diária do grupo (seção 5.2b); `WEEKLY_QUIZ`, o desafio semanal."""

    IDLE = "IDLE"
    AWAIT_ACTION = "AWAIT_ACTION"
    REVIEWING = "REVIEWING"
    WEEKLY_QUIZ = "WEEKLY_QUIZ"  # M36: o desafio semanal do grupo (seção 5.2b)


def _exige_marca(frase: str) -> str:
    if "[[" not in frase or "]]" not in frase:
        raise ValueError(f"a frase deve marcar a palavra-alvo entre [[ ]]: {frase!r}")
    return frase


class Sense(BaseModel):
    id: str
    traducao: str
    definicao: str
    exemplo: str  # frase completa, com o alvo entre [[ ]]

    @model_validator(mode="after")
    def _exemplo_marcado(self) -> Sense:
        _exige_marca(self.exemplo)
        return self


class Expansion(BaseModel):
    expressao: str
    traducao: str
    tipo: TipoExpansao


class Explanation(BaseModel):
    """Saída de `explain` (seção 6). Com `ok=False` só `motivo_erro` importa, então os demais
    campos têm padrão — o modelo não precisa inventar conteúdo para uma entrada inválida."""

    ok: bool
    motivo_erro: str | None = None
    palavra: str = ""  # forma base, minúsculas
    classe: str = ""  # em inglês (verb, noun, adjective, phrasal verb...)
    cefr_estimado: Cefr = "B1"
    sentidos: list[Sense] = Field(default_factory=list, max_length=4)  # só os comuns
    sentido_do_contexto: str | None = None  # id do sentido; a IA sempre escolhe um (M9)
    frase_contexto: str | None = None  # frase do usuário corrigida, alvo entre [[ ]]
    nota: str = ""
    tags: list[Tag] = Field(default_factory=list)

    @model_validator(mode="after")
    def _explicacao_valida_tem_palavra_e_sentidos(self) -> Explanation:
        if self.ok and not (self.palavra.strip() and self.sentidos):
            raise ValueError("ok=true exige `palavra` e ao menos 1 sentido")
        ids = {sentido.id for sentido in self.sentidos}
        if self.sentido_do_contexto is not None and self.sentido_do_contexto not in ids:
            raise ValueError("`sentido_do_contexto` deve ser o id de um dos `sentidos`")
        return self


MAX_LINHAS_EXPLICACAO = 4


class Evaluation(BaseModel):
    """Saída de `evaluate` (seção 6)."""

    usa_palavra_alvo: bool  # considera flexões
    sentido_correto: bool
    veredito: Veredito
    correcoes: list[str]  # "wrong → right"
    versao_natural: str  # alvo entre [[ ]]
    explicacao: str  # em inglês, máx. 4 linhas

    @model_validator(mode="after")
    def _explicacao_curta(self) -> Evaluation:
        if len(self.explicacao.strip().splitlines()) > MAX_LINHAS_EXPLICACAO:
            raise ValueError(f"`explicacao` deve ter no máximo {MAX_LINHAS_EXPLICACAO} linhas")
        return self


class Exemplos(BaseModel):
    """Saída de `examples`: frases com o alvo entre [[ ]]."""

    frases: list[str]

    @model_validator(mode="after")
    def _alvo_marcado(self) -> Exemplos:
        if not all("[[" in frase and "]]" in frase for frase in self.frases):
            raise ValueError("toda frase deve marcar a palavra-alvo entre [[ ]]")
        return self


MAX_PALAVRAS_DA_EXPRESSAO = 6


class Expansoes(BaseModel):
    """Saída de `expansions`: de 3 a 5 expressões relacionadas."""

    itens: list[Expansion] = Field(min_length=3, max_length=5)

    @model_validator(mode="after")
    def _expressoes_curtas_e_sem_marcas(self) -> Expansoes:
        for item in self.itens:
            if "[[" in item.expressao or len(item.expressao.split()) > MAX_PALAVRAS_DA_EXPRESSAO:
                raise ValueError(
                    f"`expressao` deve ser uma expressão curta, não uma frase: {item.expressao!r}"
                )
        return self


class Synonym(BaseModel):
    expressao: str
    significado: str  # em inglês
    exemplo: str  # frase com o SINÔNIMO entre [[ ]]

    @model_validator(mode="after")
    def _exemplo_marcado(self) -> Synonym:
        _exige_marca(self.exemplo)
        return self


class Sinonimos(BaseModel):
    """Saída de `synonyms`: de 1 a 10 sinônimos (a quantidade é pedida pelo aluno)."""

    itens: list[Synonym] = Field(min_length=1, max_length=10)


class Roteamento(BaseModel):
    """Saída de `route` (M9): classifica o texto livre do aluno e já devolve a resposta.

    Achatado de propósito — só primitivos, enums e `list[str]` — para caber bem no
    `response_schema` do Gemini (sem `anyOf`/objeto aninhado opcional). Os campos não usados
    pela intenção escolhida ficam com o padrão, como em `Explanation` com `ok=False`.
    """

    intencao: Intencao
    quantidade: int = 3  # exemplos | sinonimos (o fluxo prende entre 1 e 10)
    palavra: str = ""  # nova_palavra
    resposta: str = ""  # pedido | fora_do_escopo, em inglês
    # frase: os campos abaixo formam a mesma avaliação de `evaluate`.
    usa_palavra_alvo: bool = False
    sentido_correto: bool = False
    veredito: Veredito = "correta"
    correcoes: list[str] = Field(default_factory=list)
    versao_natural: str = ""
    explicacao: str = ""

    @model_validator(mode="after")
    def _campo_da_intencao_preenchido(self) -> Roteamento:
        if self.intencao == "frase" and not self.versao_natural.strip():
            raise ValueError("intenção `frase` exige `versao_natural`")
        if self.intencao == "nova_palavra" and not self.palavra.strip():
            raise ValueError("intenção `nova_palavra` exige `palavra`")
        if self.intencao in ("pedido", "fora_do_escopo") and not self.resposta.strip():
            raise ValueError(f"intenção `{self.intencao}` exige `resposta`")
        return self

    def como_avaliacao(self) -> Evaluation:
        return Evaluation(
            usa_palavra_alvo=self.usa_palavra_alvo,
            sentido_correto=self.sentido_correto,
            veredito=self.veredito,
            correcoes=self.correcoes,
            versao_natural=self.versao_natural,
            explicacao=self.explicacao,
        )


class Revisao(BaseModel):
    """Saída de `review` (M10, seção 5.7): julga a resposta de um turno de revisão espaçada —
    definição com as próprias palavras do aluno, ou uma frase de uso."""

    tipo: Literal["definicao", "frase", "nao_sei", "outro"]
    qualidade: QualidadeRevisao
    feedback: str  # em inglês, curto (máx. 4 linhas, como Evaluation.explicacao)
    correcao: str = ""  # a definição certa ou a frase natural, quando ajuda

    @model_validator(mode="after")
    def _feedback_curto(self) -> Revisao:
        if len(self.feedback.strip().splitlines()) > MAX_LINHAS_EXPLICACAO:
            raise ValueError(f"`feedback` deve ter no máximo {MAX_LINHAS_EXPLICACAO} linhas")
        return self


MAX_PERGUNTAS_SEMANAIS = 10


class PerguntaSemanal(BaseModel):
    """Uma pergunta do desafio semanal (M36, seção 5.2b): escrita no nível da turma, usando uma ou
    mais palavras do vocabulário do grupo (marcadas entre [[ ]]), com a explicação para o botão
    `1`. `explicacao_pt` só existe para turmas iniciantes (A1-A2, A2-B1)."""

    pergunta: str
    palavras: list[str] = Field(min_length=1)
    explicacao_en: str
    explicacao_pt: str = ""

    @model_validator(mode="after")
    def _pergunta_marcada(self) -> PerguntaSemanal:
        _exige_marca(self.pergunta)
        if not self.explicacao_en.strip():
            raise ValueError("`explicacao_en` não pode ser vazia")
        if len(self.explicacao_en.strip().splitlines()) > MAX_LINHAS_EXPLICACAO:
            raise ValueError(f"`explicacao_en` deve ter no máximo {MAX_LINHAS_EXPLICACAO} linhas")
        return self


class PerguntasSemanais(BaseModel):
    """Saída de `weekly_questions`: as perguntas do desafio, todas de uma vez."""

    itens: list[PerguntaSemanal] = Field(min_length=1, max_length=MAX_PERGUNTAS_SEMANAIS)


class AvaliacaoDaPergunta(BaseModel):
    """Saída de `weekly_answer` (M36): feedback real sobre a resposta a uma pergunta do desafio.
    Não gera nota SM-2 — é conversa, não revisão de cartão."""

    qualidade: QualidadeRevisao
    feedback: str  # em inglês, curto (máx. 4 linhas)
    correcao: str = ""  # uma resposta natural de exemplo, quando ajuda

    @model_validator(mode="after")
    def _feedback_curto(self) -> AvaliacaoDaPergunta:
        if len(self.feedback.strip().splitlines()) > MAX_LINHAS_EXPLICACAO:
            raise ValueError(f"`feedback` deve ter no máximo {MAX_LINHAS_EXPLICACAO} linhas")
        return self


class SentidoSalvo(BaseModel):
    traducao: str
    definicao: str


class Sentence(BaseModel):
    """Documento de `entries/{slug}/sentences/{auto}`."""

    texto: str
    autor: Literal["usuario", "bot"]
    veredito: Veredito | None = None
    correcoes: list[str] | None = None
    versao_natural: str | None = None
    explicacao: str | None = None
    # M16: em grupo, o número (só dígitos) de quem escreveu a frase; no privado fica vazio.
    autor_id: str | None = None
    criado_em: datetime = Field(default_factory=agora_utc)


Papel = Literal["aluno", "professor"]


class Membro(BaseModel):
    """Documento de `espacos/{grupo}/membros/{numero}` (M16, ADR-0019). Entra como `aluno` na
    primeira mensagem com prefixo; `!teacher` e `!student` mudam o papel. `marcado_em` é a última
    vez que a revisão em grupo o marcou (M17, o rodízio)."""

    papel: Papel = "aluno"
    nome: str | None = None  # o que o WhatsApp informa no payload; nunca o telefone
    entrou_em: datetime = Field(default_factory=agora_utc)
    marcado_em: datetime | None = None


class Resposta(BaseModel):
    """Documento de `espacos/{grupo}/respostas/{auto}` (M17): quem respondeu a uma revisão do
    grupo. Não entra no agendamento; alimenta o `!group` e as métricas do piloto."""

    entry: str
    autor_id: str
    marcado: bool
    qualidade: Literal["de_novo", "dificil", "bom", "facil"]
    # M58 (ADR-0056): de qual atividade veio; `None` nos documentos anteriores ao M58.
    tipo: Literal["diaria", "semanal"] | None = None
    criado_em: datetime = Field(default_factory=agora_utc)


class Entry(BaseModel):
    """Documento de `entries/{slug}`. O `slug` é o id do documento."""

    model_config = ConfigDict(use_enum_values=True)

    slug: str
    palavra: str
    classe: str
    cefr_estimado: Cefr
    sentido: SentidoSalvo
    outros_sentidos: list[SentidoSalvo] = Field(default_factory=list)
    sinonimos: list[Synonym] = Field(default_factory=list)  # M12: os já mostrados ao aluno
    nota: str = ""
    tags: list[Tag] = Field(default_factory=list)
    origem_texto: str | None = None
    origem: Literal["usuario", "expansao"] = "usuario"
    pai: str | None = None
    # M28 (snapshot de métricas, spec 12): quem salvou, quando a entrada é de um grupo — só assim
    # "termos por pessoa" existe dentro de grupos (frases e respostas já têm autor_id há mais tempo).
    autor_id: str | None = None
    status: StatusEntrada = "nova"
    exportado: bool = False
    criado_em: datetime = Field(default_factory=agora_utc)
    atualizado_em: datetime = Field(default_factory=agora_utc)
    # Revisão espaçada (M10, seção 5.7): SM-2 simplificado (app/domain/srs.py). Independente do
    # agendamento do Anki — ver ADR-0011. `proxima_revisao=None` = cartão novo, vencido desde já.
    repeticoes: int = 0
    intervalo_dias: float = 0.0
    facilidade: float = 2.5
    lapsos: int = 0
    proxima_revisao: datetime | None = None
    revisada_em: datetime | None = None

    # M23 (ADR-0024): onde ficam os áudios de pronúncia no cache (`gs://bucket/audio/...`), do
    # termo e da frase de exemplo do card. Só um registro: o cache por hash é quem manda.
    audio_palavra: str | None = None
    audio_exemplo: str | None = None


class Profile(BaseModel):
    """Documento `profile/me`."""

    nivel: NivelUsuario
    criado_em: datetime = Field(default_factory=agora_utc)
    # M28 (snapshot de métricas, spec 12): o nome que o WhatsApp informa (o "push name"), como já
    # é feito em `Membro`; nunca o telefone. `None` até a primeira mensagem trazer um.
    nome: str | None = None
    chat_id: str | None = None  # destino real do WhatsApp, aprendido de uma mensagem recebida
    # Tamanho da rodada de revisão (M24): `None` = `LIMITE_POR_SESSAO_GRUPO`; um valor fixo
    # (`!daily ... N`) sobrepõe o padrão.
    tamanho_revisao: int | None = None
    # Revisão diária do grupo (M35, ADR-0033). Horário
    # no fuso da turma; fora do fim de semana por padrão. `revisoes_sem_resposta` conta as
    # revisões agendadas seguidas sem nenhuma mensagem do grupo (3 pausam o agendamento).
    diaria_ligada: bool = True
    diaria_hora: int = 19
    diaria_minuto: int = 0
    diaria_fim_de_semana: bool = False
    proxima_diaria: datetime | None = None
    revisoes_sem_resposta: int = 0
    # Desafio semanal do grupo (M36, ADR-0034): padrão sexta 13h; `semanal_tamanho=None` = uma
    # pergunta por aluno elegível (no máximo `MAX_PERGUNTAS_SEMANAIS`).
    semanal_ligada: bool = True
    semanal_dia: int = 4  # 0 = segunda ... 6 = domingo
    semanal_hora: int = 13
    semanal_minuto: int = 0
    semanal_tamanho: int | None = None
    proxima_semanal: datetime | None = None


class Sessao(BaseModel):
    """Documento `session/current`.

    Além dos campos da spec, guarda os sinônimos já mostrados nesta palavra
    (`sinonimos_mostrados`), para "see more synonyms" não repetir e para o menu saber trocar o
    rótulo da opção 3, e a fila de uma sessão de revisão em andamento (M10, `REVIEWING`).
    """

    model_config = ConfigDict(use_enum_values=True)

    estado: Estado = Estado.IDLE
    entry_id: str | None = None
    sentido_id: str | None = None
    sinonimos_mostrados: list[str] = Field(default_factory=list)
    # A entrada aberta foi criada agora, por esta captura: a opção 5 do menu ("ignorar") pode
    # apagá-la. Fica falso para palavra que o aluno já tinha, expansão e prática.
    entrada_criada_agora: bool = False
    atualizado_em: datetime = Field(default_factory=agora_utc)
    # Sessão de revisão (M10): fila de slugs por revisar, o atual, e o resumo ao final.
    revisao_fila: list[str] = Field(default_factory=list)
    revisao_atual: str | None = None
    revisao_feitas: list[str] = Field(default_factory=list)
    revisao_lapsos: list[str] = Field(default_factory=list)
    revisao_total: int = 0
    revisao_puladas: list[str] = Field(default_factory=list)  # M35: `skip` no grupo
    # Desafio semanal (M36): as perguntas da rodada, a atual, quem já foi marcado e o placar.
    semanal_perguntas: list[PerguntaSemanal] = Field(default_factory=list)
    semanal_indice: int = 0
    semanal_respondidas: int = 0
    semanal_puladas: int = 0
    # Revisão em grupo (M17, ADR-0020): quem está marcado para o card atual, até quando, e quantas
    # vezes o card já foi repassado a outro aluno por falta de resposta (no máximo uma).
    marcado_id: str | None = None
    marcacao_expira_em: datetime | None = None
    marcacao_tentativas: int = 0


def slugify(palavra: str) -> str:
    """minúsculas, `[^a-z0-9]+` -> `-` (seção 7.1); acentos são descartados antes."""
    sem_acento = unicodedata.normalize("NFKD", palavra).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")


def _partes_da_traducao(traducao: str) -> set[str]:
    sem_parenteses = re.sub(r"\([^)]*\)", " ", traducao)
    sem_acento = unicodedata.normalize("NFKD", sem_parenteses).encode("ascii", "ignore").decode()
    partes = re.split(r"[,;/]|\bou\b", sem_acento.lower())
    return {" ".join(parte.split()) for parte in partes} - {""}


def mesma_traducao(a: str, b: str) -> bool:
    """Duas traduções são o mesmo sentido se têm alguma opção em comum. A IA reescreve a tradução
    a cada chamada ("avaliador" / "avaliador ou sistema de correção"); comparar o texto inteiro
    tratava essa mudança de redação como um sentido novo e duplicava a palavra."""
    return not _partes_da_traducao(a).isdisjoint(_partes_da_traducao(b))
