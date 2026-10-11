"""Transcrição de áudio (M38, ADR-0036): a nota de voz de quem responde ao bot no grupo vira texto
e segue como mensagem comum. Em produção, o mesmo Gemini do Vertex AI (multimodal), com a conta de
serviço da VM — sem chave nem serviço novo."""

from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx
from google.genai import errors as genai_errors
from google.genai import types

from app.services.llm import LLMError, criar_cliente_vertex

logger = logging.getLogger(__name__)

# Nota de voz de WhatsApp tem ~16 kHz em Opus: 3 MB passam de 10 minutos. Mais que isso é custo sem
# ganho para uma frase de prática.
MAX_BYTES_DO_AUDIO = 3 * 1024 * 1024

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
    def __init__(self, client: Any, modelo: str) -> None:  # genai.Client, ou um dublê nos testes
        self._client = client
        self._modelo = modelo

    def transcrever(self, conteudo: bytes, mimetype: str) -> str:
        audio = types.Part.from_bytes(data=conteudo, mime_type=_sem_parametros(mimetype))
        config = types.GenerateContentConfig(temperature=0.0)
        try:
            resposta = self._client.models.generate_content(
                model=self._modelo, contents=[_PROMPT, audio], config=config
            )
        except genai_errors.APIError as erro:
            raise LLMError(f"o Gemini recusou o áudio ({erro.code} {erro.status})") from erro
        except httpx.HTTPError as erro:
            raise LLMError(f"sem resposta do Gemini ({type(erro).__name__})") from erro
        return (resposta.text or "").strip()


def criar_transcritor_vertex(*, projeto: str, localizacao: str, modelo: str) -> GeminiTranscritor:
    return GeminiTranscritor(criar_cliente_vertex(projeto=projeto, localizacao=localizacao), modelo)
