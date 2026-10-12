"""M43 (ADR-0041): limite de uso por pessoa e por grupo, em janela deslizante e em memória."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app import messages
from app.services.limites import LimitadorDeUso, Limites
from tests.helpers import eventos
from tests.webhook_helpers import (
    ALUNO_COMUM,
    DONO,
    GRUPO_FIXO,
    Ambiente,
    _do_grupo,
    _privada,
    criar_ambiente,
)

T0 = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
ANA = "5531999990001"


class _Relogio:
    def __init__(self) -> None:
        self.agora = T0

    def __call__(self) -> datetime:
        return self.agora

    def avancar(self, **kwargs: float) -> None:
        self.agora += timedelta(**kwargs)


def _limitador(relogio: _Relogio, **limites: int) -> LimitadorDeUso:
    return LimitadorDeUso(Limites(**limites), relogio)


# --- o limitador ------------------------------------------------------------------------------


def test_sexta_mensagem_passa_e_a_setima_no_mesmo_minuto_e_recusada() -> None:
    relogio = _Relogio()
    limitador = _limitador(relogio, pessoa_por_minuto=6)

    decisoes = [limitador.admitir(ANA, "g@g.us", em_grupo=True) for _ in range(7)]

    assert [d.permitido for d in decisoes] == [True] * 6 + [False]
    assert decisoes[6].motivo == "minuto" and decisoes[6].avisar


def test_so_a_primeira_recusa_avisa_e_depois_a_janela_reabre() -> None:
    relogio = _Relogio()
    limitador = _limitador(relogio, pessoa_por_minuto=2)
    for _ in range(2):
        limitador.admitir(ANA, "g@g.us", em_grupo=True)

    primeira = limitador.admitir(ANA, "g@g.us", em_grupo=True)
    segunda = limitador.admitir(ANA, "g@g.us", em_grupo=True)
    relogio.avancar(seconds=61)
    depois = limitador.admitir(ANA, "g@g.us", em_grupo=True)

    assert (primeira.avisar, segunda.avisar) == (True, False)
    assert depois.permitido


def test_recusa_nao_consome_a_janela() -> None:
    relogio = _Relogio()
    limitador = _limitador(relogio, pessoa_por_minuto=1)
    limitador.admitir(ANA, "g@g.us", em_grupo=True)
    for _ in range(50):  # insistir não prolonga o bloqueio
        limitador.admitir(ANA, "g@g.us", em_grupo=True)

    relogio.avancar(seconds=61)

    assert limitador.admitir(ANA, "g@g.us", em_grupo=True).permitido


def test_limite_do_dia_por_pessoa_e_do_grupo_inteiro() -> None:
    relogio = _Relogio()
    limitador = _limitador(relogio, pessoa_por_minuto=100, pessoa_por_dia=3, grupo_por_dia=4)

    ana = [limitador.admitir(ANA, "g@g.us", em_grupo=True) for _ in range(4)]
    bia = [limitador.admitir("5531999990002", "g@g.us", em_grupo=True) for _ in range(3)]

    assert [d.motivo for d in ana] == [None, None, None, "dia"]
    assert [d.permitido for d in bia] == [True, False, False]
    assert bia[1].motivo == "grupo" and bia[1].avisar and not bia[2].avisar
    relogio.avancar(hours=25)
    assert limitador.admitir(ANA, "g@g.us", em_grupo=True).permitido


def test_audio_tem_orcamento_de_segundos_por_dia() -> None:
    relogio = _Relogio()
    limitador = _limitador(relogio, audio_segundos_por_dia=100)

    primeiro = limitador.admitir(ANA, "g@g.us", em_grupo=True, segundos_de_audio=60)
    segundo = limitador.admitir(ANA, "g@g.us", em_grupo=True, segundos_de_audio=60)
    texto = limitador.admitir(ANA, "g@g.us", em_grupo=True)

    assert (primeiro.permitido, segundo.permitido, segundo.motivo) == (True, False, "audio")
    assert texto.permitido  # a recusa do áudio não bloqueia o texto


def test_o_mapa_nao_cresce_com_quem_so_falou_uma_vez() -> None:
    relogio = _Relogio()
    limitador = _limitador(relogio, pessoa_por_minuto=1)
    limitador.admitir(ANA, "g@g.us", em_grupo=True)
    limitador.admitir(ANA, "g@g.us", em_grupo=True)  # recusada: dispara a limpeza
    relogio.avancar(days=2)

    limitador.admitir(ANA, "g@g.us", em_grupo=True)
    limitador.admitir(ANA, "g@g.us", em_grupo=True)

    assert len(limitador._janelas) <= 3


# --- no webhook -------------------------------------------------------------------------------


def _marcada(texto: str, numero: str = ALUNO_COMUM) -> dict[str, Any]:
    return _do_grupo(GRUPO_FIXO, f"{numero}@c.us", f"!add {texto}")


def test_flood_no_privado_avisa_uma_vez_e_o_resto_nao_chega_a_ia() -> None:
    with criar_ambiente(Limites(pessoa_por_minuto=3)) as a:
        for _ in range(10):
            a.cliente.post("/waha/webhook", json=_privada(ALUNO_COMUM, "stall"))

        avisos = [t for _, t in a.canal.textos_enviados if t == messages.DEVAGAR]
        assert len(avisos) == 1
        assert len(a.tutor.chamadas) <= 3


def test_conversa_entre_pessoas_no_grupo_nao_gasta_nem_avisa() -> None:
    with criar_ambiente(Limites(pessoa_por_minuto=1)) as a:
        for _ in range(5):
            a.cliente.post(
                "/waha/webhook", json=_do_grupo(GRUPO_FIXO, f"{ANA}@c.us", "bom dia, pessoal")
            )

        assert a.canal.textos_enviados == []


def test_comandos_no_grupo_respeitam_o_limite_por_pessoa() -> None:
    with criar_ambiente(Limites(pessoa_por_minuto=2)) as a:
        for _ in range(5):
            a.cliente.post("/waha/webhook", json=_marcada("stall"))

        assert [t for _, t in a.canal.textos_enviados].count(messages.DEVAGAR) == 1


def test_o_dono_nao_e_limitado() -> None:
    with criar_ambiente(Limites(pessoa_por_minuto=1)) as a:
        for _ in range(4):
            a.cliente.post("/waha/webhook", json=_privada(DONO, "/help"))

        assert messages.DEVAGAR not in [t for _, t in a.canal.textos_enviados]


def test_audio_acima_do_orcamento_diario_nao_e_baixado(ambiente: Ambiente) -> None:
    from tests.test_grupo_audio import BOT, URL, _audio_com

    with criar_ambiente(Limites(audio_segundos_por_dia=100)) as a:
        a.canal.midias[URL] = b"ogg"
        a.transcritor.texto = "stall"
        corpos = [_audio_com(f"{BOT}@c.us", seconds=50) for _ in range(3)]
        for corpo in corpos:
            corpo["payload"]["participant"] = f"{ANA}@c.us"
            a.cliente.post("/waha/webhook", json=corpo)

        assert len(a.canal.downloads) == 2
        assert messages.LIMITE_DE_AUDIO in [t for _, t in a.canal.textos_enviados]


def test_recusa_registra_limite_atingido_com_motivo(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO), criar_ambiente(Limites(pessoa_por_minuto=1)) as a:
        for _ in range(3):
            a.cliente.post("/waha/webhook", json=_privada(ALUNO_COMUM, "stall"))

    primeiro, segundo = eventos(caplog.records, "limite_atingido")
    assert (primeiro.motivo, primeiro.avisou, segundo.avisou) == ("minuto", True, False)
