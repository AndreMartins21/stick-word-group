"""M44 (ADR-0042): teto de tokens de saída e nível de raciocínio do Gemini, com dublê do cliente."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors as genai_errors
from google.genai import types

from app.config import Settings
from app.domain.models import Exemplos
from app.services.llm import MAX_TOKENS_DE_SAIDA, LLMError, VertexGeminiProvider
from app.services.transcricao import MAX_TOKENS_DA_TRANSCRICAO, GeminiTranscritor


class _Modelos:
    def __init__(self, *respostas: object) -> None:
        self.respostas = list(respostas)
        self.chamadas: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> SimpleNamespace:
        self.chamadas.append(kwargs)
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return SimpleNamespace(text=resposta)


def _recusa_400() -> genai_errors.ClientError:
    return genai_errors.ClientError(
        400, {"error": {"status": "INVALID_ARGUMENT", "message": "thinking level not supported"}}
    )


def _gerar(provider: VertexGeminiProvider) -> str:
    return provider.gerar(sistema="s", usuario="u", schema=Exemplos, modelo="m", temperatura=0.2)


def test_gemini_manda_teto_de_saida_e_nivel_de_raciocinio() -> None:
    modelos = _Modelos('{"frases": []}')

    _gerar(VertexGeminiProvider(SimpleNamespace(models=modelos), thinking_level="minimal"))

    config = modelos.chamadas[0]["config"]
    assert config.max_output_tokens == MAX_TOKENS_DE_SAIDA
    assert config.thinking_config.thinking_level == types.ThinkingLevel.MINIMAL


def test_sem_nivel_configurado_nao_manda_thinking_config() -> None:
    modelos = _Modelos('{"frases": []}')

    _gerar(VertexGeminiProvider(SimpleNamespace(models=modelos)))

    assert modelos.chamadas[0]["config"].thinking_config is None


def test_modelo_que_recusa_o_nivel_refaz_sem_ele_e_nao_tenta_de_novo() -> None:
    modelos = _Modelos(_recusa_400(), '{"frases": []}', '{"frases": []}')
    provider = VertexGeminiProvider(SimpleNamespace(models=modelos), thinking_level="minimal")

    assert _gerar(provider) == '{"frases": []}'
    assert _gerar(provider) == '{"frases": []}'

    configs = [c["config"] for c in modelos.chamadas]
    assert configs[0].thinking_config is not None
    assert configs[1].thinking_config is None and configs[2].thinking_config is None
    assert all(c.max_output_tokens == MAX_TOKENS_DE_SAIDA for c in configs)


def test_erro_400_sem_nivel_configurado_continua_sendo_llm_error() -> None:
    modelos = _Modelos(_recusa_400())

    with pytest.raises(LLMError):
        _gerar(VertexGeminiProvider(SimpleNamespace(models=modelos)))


def test_transcritor_manda_teto_de_saida_e_cai_sem_o_nivel_se_recusado() -> None:
    modelos = _Modelos(_recusa_400(), "furniture")
    transcritor = GeminiTranscritor(
        SimpleNamespace(models=modelos), "gemini-x", thinking_level="minimal"
    )

    assert transcritor.transcrever(b"ogg", "audio/ogg; codecs=opus") == "furniture"

    primeira, segunda = (c["config"] for c in modelos.chamadas)
    assert primeira.max_output_tokens == MAX_TOKENS_DA_TRANSCRICAO
    assert primeira.thinking_config is not None and segunda.thinking_config is None


def _settings(**env: Any) -> Settings:
    return Settings(
        _env_file=None,
        ALLOWED_NUMBER="5531999998888",
        BOT_NUMBER="5531988887777",
        WAHA_API_KEY="x",
        GCP_PROJECT_ID="p",
        EXPORT_BUCKET="b",
        **env,
    )


def test_nivel_de_raciocinio_padrao_e_minimal_e_vazio_usa_o_do_modelo() -> None:
    assert _settings().gemini_thinking_level == "minimal"
    assert _settings(GEMINI_THINKING_LEVEL="").gemini_thinking_level is None
    assert _settings(GEMINI_THINKING_LEVEL="low").gemini_thinking_level == "low"
