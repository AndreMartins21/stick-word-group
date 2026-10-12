"""Transcrição de áudio (M38, ADR-0036): a nota de voz de quem responde ao bot no grupo vira texto
e segue como mensagem comum. Em produção, o mesmo Gemini do Vertex AI (multimodal), com a conta de
serviço da VM — sem chave nem serviço novo."""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

import httpx
from google.genai import errors as genai_errors
from google.genai import types

from app.logging_config import registrar_evento
from app.services import custo
from app.services.llm import LLMError, criar_cliente_vertex, nivel_de_raciocinio

logger = logging.getLogger(__name__)

# Nota de voz de WhatsApp é Opus a ~16 kbps: 1 MB são ~8 minutos, bem acima do teto de duração
# (`MAX_SEGUNDOS_AUDIO`, M41, ADR-0039). Mais que isso é custo e memória sem ganho para uma frase.
MAX_BYTES_DO_AUDIO = 1024 * 1024

# M44 (ADR-0042): 60 s de fala são ~250 tokens de texto; o teto cobre com folga e limita um
# áudio que a IA "continue" inventando.
MAX_TOKENS_DA_TRANSCRICAO = 1024

_PROMPT = (
    "Transcribe this voice message exactly as spoken, in the language spoken (usually English from "
    "an English learner, sometimes Portuguese). Keep hesitations, grammar mistakes and repetitions: "
    "do NOT correct, translate, summarize or add anything. Reply with the transcript only. If there "
    "is no intelligible speech, reply with an empty string."
)


class AudioGrandeDemais(Exception):
    """O áudio passa de `MAX_BYTES_DO_AUDIO`."""


class Transcritor(Protocol):
    def transcrever(self, conteudo: bytes, mimetype: str) -> str:
        """O texto falado em `conteudo` (vazio se não há fala). Síncrono; levanta `LLMError`."""
        ...


def _sem_parametros(mimetype: str) -> str:
    """`audio/ogg; codecs=opus` -> `audio/ogg`: a API só aceita o tipo."""
    return mimetype.split(";", 1)[0].strip().lower()


class GeminiTranscritor:
    def __init__(
        self, client: Any, modelo: str, *, thinking_level: str | None = None
    ) -> None:  # genai.Client, ou um dublê nos testes
        self._client = client
        self._modelo = modelo
        self._thinking_level = thinking_level

    def transcrever(self, conteudo: bytes, mimetype: str) -> str:
        """Emite `transcricao_chamada` (M45, ADR-0043) com os tokens de áudio e o custo estimado."""
        inicio = time.monotonic()
        ok = False
        with custo.medir() as uso:
            try:
                texto = self._transcrever(conteudo, mimetype)
                ok = True
                return texto
            finally:
                custo.notificar_gasto(custo.custo_usd(self._modelo, uso))
                registrar_evento(
                    logger,
                    "transcricao_chamada",
                    modelo=self._modelo,
                    ok=ok,
                    latencia_ms=round((time.monotonic() - inicio) * 1000),
                    tokens_audio=uso.audio,
                    tokens_saida=uso.saida,
                    tokens_thinking=uso.raciocinio,
                    custo_usd=round(custo.custo_usd(self._modelo, uso), 6),
                )

    def _transcrever(self, conteudo: bytes, mimetype: str) -> str:
        audio = types.Part.from_bytes(data=conteudo, mime_type=_sem_parametros(mimetype))
        try:
            resposta = self._gerar(audio, com_raciocinio=True)
        except genai_errors.ClientError as erro:
            if self._thinking_level is None or erro.code != 400:
                raise LLMError(f"o Gemini recusou o áudio ({erro.code} {erro.status})") from erro
            logger.warning("o modelo recusou thinking_level na transcrição; seguindo sem ele")
            self._thinking_level = None
            try:
                resposta = self._gerar(audio, com_raciocinio=False)
            except genai_errors.APIError as erro2:
                raise LLMError(f"o Gemini recusou o áudio ({erro2.code} {erro2.status})") from erro2
        except genai_errors.APIError as erro:
            raise LLMError(f"o Gemini recusou o áudio ({erro.code} {erro.status})") from erro
        except httpx.HTTPError as erro:
            raise LLMError(f"sem resposta do Gemini ({type(erro).__name__})") from erro
        custo.registrar_resposta(resposta, audio=True)
        return (resposta.text or "").strip()

    def _gerar(self, audio: types.Part, *, com_raciocinio: bool) -> Any:
        config = types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=MAX_TOKENS_DA_TRANSCRICAO,
            thinking_config=nivel_de_raciocinio(self._thinking_level) if com_raciocinio else None,
        )
        return self._client.models.generate_content(
            model=self._modelo, contents=[_PROMPT, audio], config=config
        )


def criar_transcritor_vertex(
    *, projeto: str, localizacao: str, modelo: str, thinking_level: str | None = None
) -> GeminiTranscritor:
    return GeminiTranscritor(
        criar_cliente_vertex(projeto=projeto, localizacao=localizacao),
        modelo,
        thinking_level=thinking_level,
    )
