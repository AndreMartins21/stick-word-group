"""Testes do áudio de pronúncia (M23): cache por hash, síntese só no miss, GCS e TTS com dublês."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest
from google.api_core.exceptions import NotFound

from app.services.audio import ServicoAudio
from app.services.fake_tts import FakeSintetizador
from app.services.storage import CacheAudioEmMemoria, CacheAudioGcs
from app.services.tts import GoogleTts
from tests.helpers import eventos

VOZ = "en-US-Neural2-F"


def _servico(
    sintetizador: FakeSintetizador | None = None, cache: CacheAudioEmMemoria | None = None
) -> tuple[ServicoAudio, FakeSintetizador, CacheAudioEmMemoria]:
    sintetizador = sintetizador or FakeSintetizador()
    cache = cache or CacheAudioEmMemoria()
    return ServicoAudio(sintetizador, cache, VOZ), sintetizador, cache


def test_miss_sintetiza_e_guarda_no_cache() -> None:
    servico, sintetizador, cache = _servico()

    audio = servico.obter("stall")

    assert sintetizador.chamadas == [("stall", VOZ)]
    assert audio.conteudo == b"ogg:stall"
    assert audio.uri == f"memoria://{audio.nome}"
    assert cache.arquivos[audio.nome] == b"ogg:stall"
    assert audio.nome.startswith(f"audio/{VOZ}/") and audio.nome.endswith(".ogg")


def test_hit_nao_chama_o_sintetizador() -> None:
    servico, sintetizador, _ = _servico()
    primeiro = servico.obter("stall")

    segundo = servico.obter("stall")

    assert len(sintetizador.chamadas) == 1
    assert segundo == primeiro


def test_espacos_extras_dao_o_mesmo_arquivo_mas_caixa_e_voz_nao() -> None:
    servico, sintetizador, cache = _servico()
    a = servico.obter("stall for  time")
    b = servico.obter("  stall for time ")
    c = servico.obter("Stall for time")
    outra_voz = ServicoAudio(sintetizador, cache, "en-US-Neural2-D").obter("stall for time")

    assert a.nome == b.nome
    assert len({a.nome, c.nome, outra_voz.nome}) == 3
    assert len(sintetizador.chamadas) == 3


def test_falha_do_tts_nao_grava_nada() -> None:
    servico, _, cache = _servico(FakeSintetizador(falha=True))

    with pytest.raises(RuntimeError):
        servico.obter("stall")

    assert cache.arquivos == {}


# --- eventos estruturados (M27, ADR-0028, seção 12 da spec) -------------------------------------


def test_miss_registra_tts_chamada_ok_true_e_cache_miss(caplog: pytest.LogCaptureFixture) -> None:
    servico, _, _ = _servico()

    with caplog.at_level(logging.INFO):
        servico.obter("stall")

    (evento,) = eventos(caplog.records, "tts_chamada")
    assert evento.ok is True
    assert evento.cache == "miss"
    assert evento.caracteres == len("stall")


def test_hit_registra_tts_chamada_cache_hit(caplog: pytest.LogCaptureFixture) -> None:
    servico, _, _ = _servico()
    servico.obter("stall")

    with caplog.at_level(logging.INFO):
        servico.obter("stall")

    (evento,) = eventos(caplog.records, "tts_chamada")
    assert evento.cache == "hit"


def test_falha_do_tts_registra_ok_false(caplog: pytest.LogCaptureFixture) -> None:
    servico, _, _ = _servico(FakeSintetizador(falha=True))

    with caplog.at_level(logging.INFO), pytest.raises(RuntimeError):
        servico.obter("stall")

    (evento,) = eventos(caplog.records, "tts_chamada")
    assert evento.ok is False
    assert evento.cache == "miss"


def test_texto_vazio_e_recusado() -> None:
    servico, sintetizador, _ = _servico()

    with pytest.raises(ValueError, match="vazio"):
        servico.obter("   ")

    assert sintetizador.chamadas == []


class _BlobFalso:
    def __init__(self, guardados: dict[str, bytes], nome: str) -> None:
        self._guardados = guardados
        self._nome = nome

    def download_as_bytes(self) -> bytes:
        if self._nome not in self._guardados:
            raise NotFound("não existe")  # type: ignore[no-untyped-call]
        return self._guardados[self._nome]

    def upload_from_string(self, conteudo: bytes, content_type: str) -> None:
        assert content_type == "audio/ogg"
        self._guardados[self._nome] = conteudo


def test_cache_gcs_devolve_none_no_miss_e_guarda_ogg() -> None:
    guardados: dict[str, bytes] = {}
    bucket = SimpleNamespace(name="proj-audio", blob=lambda n: _BlobFalso(guardados, n))
    cache = CacheAudioGcs(bucket=bucket)

    assert cache.obter("audio/a.ogg") is None
    cache.guardar("audio/a.ogg", b"xyz")

    assert cache.obter("audio/a.ogg") == b"xyz"
    assert cache.uri("audio/a.ogg") == "gs://proj-audio/audio/a.ogg"


def test_google_tts_pede_ogg_opus_com_a_voz_e_o_idioma_dela() -> None:
    pedidos: list[dict[str, Any]] = []

    class _Cliente:
        def synthesize_speech(self, **kwargs: Any) -> Any:
            pedidos.append(kwargs)
            return SimpleNamespace(audio_content=b"audio-real")

    tts = GoogleTts(cliente=_Cliente())

    assert tts.sintetizar("stall", VOZ) == b"audio-real"
    (pedido,) = pedidos
    assert pedido["input"].text == "stall"
    assert pedido["voice"].name == VOZ
    assert pedido["voice"].language_code == "en-US"
    assert pedido["audio_config"].audio_encoding.name == "OGG_OPUS"
