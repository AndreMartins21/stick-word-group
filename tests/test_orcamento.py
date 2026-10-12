"""M46 (ADR-0044): orçamento diário de IA — soma o custo, persiste, pausa o bot e avisa o dono."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import messages
from app.domain.models import Entry, Profile, SentidoSalvo
from app.repo.memory import MemoryBanco
from app.services import custo
from app.services.fake_llm import FakeTutor
from app.services.lembretes import Agendador
from app.services.orcamento import INTERVALO_DE_GRAVACAO, Orcamento
from tests.helpers import CHAT, T0, eventos, montar
from tests.webhook_helpers import ALUNO_COMUM, DONO, Ambiente, _privada, criar_ambiente

FUSO = ZoneInfo("America/Sao_Paulo")
MEIO_DIA = datetime(2026, 10, 12, 15, 0, tzinfo=UTC)  # 12h em São Paulo


class _Relogio:
    def __init__(self, inicio: datetime = MEIO_DIA) -> None:
        self.agora = inicio

    def __call__(self) -> datetime:
        return self.agora

    def avancar(self, **kwargs: float) -> None:
        self.agora += timedelta(**kwargs)


def _orcamento(
    limite: float = 1.0, banco: MemoryBanco | None = None, relogio: _Relogio | None = None
) -> tuple[Orcamento, MemoryBanco, _Relogio]:
    banco = banco or MemoryBanco()
    relogio = relogio or _Relogio()
    return Orcamento(banco, limite, fuso=FUSO, agora=relogio), banco, relogio


# --- o orçamento ------------------------------------------------------------------------------


def test_esgota_ao_somar_o_limite() -> None:
    orcamento, _, _ = _orcamento(limite=1.0)

    orcamento.registrar(0.6)
    assert not orcamento.esgotado()
    orcamento.registrar(0.4)

    assert orcamento.esgotado()


def test_grava_em_lote_e_um_novo_processo_continua_de_onde_parou() -> None:
    orcamento, banco, relogio = _orcamento()
    orcamento.registrar(0.3)
    assert banco.obter_uso_do_dia(relogio().astimezone(FUSO).date()) == 0  # ainda em memória

    relogio.avancar(seconds=INTERVALO_DE_GRAVACAO.total_seconds() + 1)
    orcamento.registrar(0.2)

    outro, _, _ = _orcamento(banco=banco, relogio=relogio)
    assert outro.gasto_hoje() == pytest.approx(0.5)


def test_gravar_forca_o_que_falta_no_shutdown() -> None:
    orcamento, banco, relogio = _orcamento()
    orcamento.registrar(0.25)

    orcamento.gravar()

    assert banco.obter_uso_do_dia(relogio().astimezone(FUSO).date()) == pytest.approx(0.25)


def test_o_dia_vira_no_fuso_do_aluno_e_zera_o_gasto() -> None:
    orcamento, _, relogio = _orcamento(limite=1.0)
    orcamento.registrar(2.0)
    assert orcamento.esgotado()

    relogio.avancar(hours=10)  # 22h em São Paulo: mesmo dia
    assert orcamento.esgotado()
    relogio.avancar(hours=3)  # 01h do dia seguinte

    assert not orcamento.esgotado()
    assert orcamento.gasto_hoje() == 0


def test_acabou_de_esgotar_so_diz_sim_uma_vez_por_dia() -> None:
    orcamento, _, _ = _orcamento(limite=1.0)

    assert orcamento.acabou_de_esgotar() is False
    orcamento.registrar(1.5)

    assert orcamento.acabou_de_esgotar() is True
    assert orcamento.acabou_de_esgotar() is False


def test_restart_com_o_dia_ja_esgotado_nao_avisa_o_dono_de_novo() -> None:
    orcamento, banco, relogio = _orcamento(limite=1.0)
    orcamento.registrar(2.0)
    orcamento.gravar()

    reiniciado, _, _ = _orcamento(limite=1.0, banco=banco, relogio=relogio)

    assert reiniciado.esgotado()
    assert reiniciado.acabou_de_esgotar() is False


def test_custo_da_chamada_chega_ao_orcamento_pelo_observador() -> None:
    orcamento, _, _ = _orcamento()
    custo.definir_observador(orcamento.registrar)
    try:
        custo.notificar_gasto(0.42)
    finally:
        custo.definir_observador(None)

    assert orcamento.gasto_hoje() == pytest.approx(0.42)


# --- no webhook -------------------------------------------------------------------------------


def test_orcamento_esgotado_pausa_a_ia_e_avisa_o_chat_uma_vez(ambiente: Ambiente) -> None:
    orcamento, _, _ = _orcamento(limite=1.0)
    orcamento.registrar(5.0)
    with criar_ambiente(orcamento=orcamento) as a:
        for _ in range(3):
            a.cliente.post("/waha/webhook", json=_privada(ALUNO_COMUM, "stall"))

        textos = [t for _, t in a.canal.textos_enviados]
        assert textos == [messages.PAUSA_DE_HOJE]
        assert a.tutor.chamadas == []


def test_o_dono_segue_atendido_com_o_orcamento_esgotado() -> None:
    orcamento, _, _ = _orcamento(limite=1.0)
    orcamento.registrar(5.0)
    with criar_ambiente(orcamento=orcamento) as a:
        a.cliente.post("/waha/webhook", json=_privada(DONO, "stall"))

        assert messages.PAUSA_DE_HOJE not in [t for _, t in a.canal.textos_enviados]
        assert a.tutor.chamadas != []


# --- no agendador -----------------------------------------------------------------------------


def _entrada_vencida() -> Entry:
    sentido = SentidoSalvo(traducao="travar", definicao="to stop making progress")
    return Entry(
        slug="stall",
        palavra="stall",
        classe="verb",
        cefr_estimado="B2",
        sentido=sentido,
        criado_em=T0 - timedelta(days=10),
        atualizado_em=T0 - timedelta(days=10),
    )


async def test_agendador_nao_dispara_lembrete_e_avisa_o_dono_uma_vez(
    caplog: pytest.LogCaptureFixture,
) -> None:
    m = montar(tutor=FakeTutor())
    m.repo.criar_entrada(_entrada_vencida())
    m.repo.salvar_perfil(
        Profile(nivel="B1-B2", chat_id=CHAT, lembretes_por_dia=3, proximo_lembrete=T0)
    )
    orcamento = Orcamento(m.banco, 1.0, fuso=ZoneInfo("UTC"), agora=m.relogio.agora)
    orcamento.registrar(2.0)
    avisos: list[str] = []

    async def avisar(texto: str) -> None:
        avisos.append(texto)

    async def dormir(_: float) -> None:
        return None

    agendador = Agendador(
        router=m.router,
        banco=m.banco,
        agora=m.relogio.agora,
        fuso=ZoneInfo("UTC"),
        dormir=dormir,
        orcamento=orcamento,
        avisar_dono=avisar,
    )

    with caplog.at_level(logging.INFO):
        await agendador._tick()
        await agendador._tick()

    assert m.channel.textos_enviados == []
    assert avisos == [messages.orcamento_do_dono(1.0)]
    assert len(eventos(caplog.records, "orcamento_esgotado")) == 1
