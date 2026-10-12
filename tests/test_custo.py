"""M45 (ADR-0043): tokens e custo estimado de cada chamada à IA, nos eventos `llm_chamada` e
`transcricao_chamada`."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.custo import Uso, custo_usd, medir, preco_do_modelo, registrar_resposta
from app.services.llm import LLMTutor, VertexGeminiProvider
from app.services.transcricao import GeminiTranscritor
from tests.helpers import eventos


def _resposta(texto: str, entrada: int, saida: int, raciocinio: int = 0) -> SimpleNamespace:
    meta = SimpleNamespace(
        prompt_token_count=entrada,
        candidates_token_count=saida,
        thoughts_token_count=raciocinio,
    )
    return SimpleNamespace(text=texto, usage_metadata=meta)


class _Modelos:
    def __init__(self, *respostas: SimpleNamespace) -> None:
        self.respostas = list(respostas)

    def generate_content(self, **_: Any) -> SimpleNamespace:
        return self.respostas.pop(0)


def test_custo_do_flash_lite_usa_a_tabela_publica() -> None:
    uso = Uso(entrada=1_000_000, audio=1_000_000, saida=1_000_000, raciocinio=1_000_000)

    assert custo_usd("gemini-3.1-flash-lite", uso) == pytest.approx(0.25 + 0.50 + 1.50 * 2)


def test_modelo_desconhecido_usa_o_preco_mais_alto() -> None:
    assert preco_do_modelo("gemini-9-ultra").saida == 3.00
    assert preco_do_modelo("gemini-3.1-flash-lite-preview-0909").saida == 1.50


def test_resposta_sem_usage_metadata_vale_zero() -> None:
    with medir() as uso:
        registrar_resposta(SimpleNamespace(text="x"))

    assert uso == Uso()


def test_llm_chamada_soma_o_uso_de_todas_as_tentativas(
    caplog: pytest.LogCaptureFixture,
) -> None:
    modelos = _Modelos(
        _resposta("não é json", 1000, 20, 5),
        _resposta('{"frases": ["They [[stalled]] again."]}', 1100, 30),
    )
    tutor = LLMTutor(
        VertexGeminiProvider(SimpleNamespace(models=modelos)),
        modelo="gemini-3.1-flash-lite",
        modelo_avaliacao="gemini-3.1-flash-lite",
    )
    # `examples` valida a quantidade: pede n=1 para a segunda tentativa passar.
    with caplog.at_level(logging.INFO):
        assert tutor.examples("stall", _sentido(), "B1-B2", n=1) == ["They [[stalled]] again."]

    (evento,) = eventos(caplog.records, "llm_chamada")
    assert (evento.tokens_entrada, evento.tokens_saida, evento.tokens_thinking) == (2100, 50, 5)
    assert evento.custo_usd == pytest.approx((2100 * 0.25 + 55 * 1.50) / 1_000_000, abs=1e-6)


def _sentido() -> Any:
    from tests.helpers import explicacao_stall

    return explicacao_stall().sentidos[0]


def test_transcricao_chamada_conta_tokens_de_audio(caplog: pytest.LogCaptureFixture) -> None:
    modelos = _Modelos(_resposta("furniture", 640, 4))
    transcritor = GeminiTranscritor(SimpleNamespace(models=modelos), "gemini-3.1-flash-lite")

    with caplog.at_level(logging.INFO):
        assert transcritor.transcrever(b"ogg", "audio/ogg") == "furniture"

    (evento,) = eventos(caplog.records, "transcricao_chamada")
    assert (evento.ok, evento.tokens_audio, evento.tokens_saida) == (True, 640, 4)
    assert evento.custo_usd == pytest.approx((640 * 0.50 + 4 * 1.50) / 1_000_000, abs=1e-6)
