"""Testes de app/services/lembretes.py (M10, ADR-0012): espaço privado antigo nunca recebe nada
(ADR-0062) e o snapshot diário de métricas. A diária e o semanal dos grupos estão em
`test_revisao_grupo.py` e `test_semanal.py`."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.domain.models import Entry, Estado, Profile, SentidoSalvo
from app.services.lembretes import Agendador
from app.services.metricas_destino import DestinoEmMemoria
from tests.helpers import T0, Montagem, eventos, montar

UTC = ZoneInfo("UTC")
SENTIDO = SentidoSalvo(traducao="travar", definicao="to stop making progress")


def _entrada_vencida(slug: str = "stall") -> Entry:
    return Entry(
        slug=slug,
        palavra=slug,
        classe="verb",
        cefr_estimado="B2",
        sentido=SENTIDO,
        criado_em=T0 - timedelta(days=10),
        atualizado_em=T0 - timedelta(days=10),
    )


def _agendador(m: Montagem) -> Agendador:
    async def dormir(_: float) -> None:
        return None

    return Agendador(router=m.router, banco=m.banco, agora=m.relogio.agora, fuso=UTC, dormir=dormir)


async def test_espaco_privado_antigo_nunca_recebe_nada() -> None:
    """ADR-0062: um espaço privado de antes da separação, com destino e palavra vencida, não entra
    na consulta do agendador nem é tratado se aparecer nela."""
    m = montar()
    privado = "5531999998888@c.us"
    repo = m.banco.do_espaco(privado)
    repo.salvar_perfil(Profile(nivel="B1-B2", criado_em=T0, chat_id=privado))
    repo.criar_entrada(_entrada_vencida())

    assert privado not in m.banco.listar_espacos_com_lembrete(T0 + timedelta(days=30))
    await _agendador(m)._tick_espaco(privado)

    assert m.channel.textos_enviados == []
    assert repo.obter_sessao().estado == Estado.IDLE


# --- snapshot diário de métricas (M28, ADR-0029, seção 12 da spec) -----------------------------


def _agendador_com_destino(
    m: Montagem, *, destino: DestinoEmMemoria | None, hora: int = 4
) -> Agendador:
    async def dormir(_: float) -> None:
        return None

    return Agendador(
        router=m.router,
        banco=m.banco,
        agora=m.relogio.agora,
        fuso=UTC,
        dormir=dormir,
        destino_de_metricas=destino,
        hora_do_snapshot=hora,
    )


async def test_snapshot_desligado_sem_destino_configurado() -> None:
    m = montar()
    m.relogio.agora_ = datetime(2026, 9, 20, 4, 0, tzinfo=UTC)
    agendador = _agendador_com_destino(m, destino=None)

    await agendador._tick()

    assert m.banco.obter_ultimo_snapshot() is None


async def test_snapshot_fora_da_hora_nao_roda(caplog: pytest.LogCaptureFixture) -> None:
    m = montar()
    m.relogio.agora_ = datetime(2026, 9, 20, 5, 0, tzinfo=UTC)
    destino = DestinoEmMemoria()
    agendador = _agendador_com_destino(m, destino=destino)

    with caplog.at_level(logging.INFO):
        await agendador._tick()

    assert m.banco.obter_ultimo_snapshot() is None
    assert destino.gravados == {}
    assert eventos(caplog.records, "snapshot_ok") == []


async def test_snapshot_roda_na_hora_e_grava_todas_as_tabelas(
    caplog: pytest.LogCaptureFixture,
) -> None:
    m = montar()
    m.relogio.agora_ = datetime(2026, 9, 20, 4, 0, tzinfo=UTC)
    m.repo.salvar_perfil(Profile(nivel="B1-B2", criado_em=m.relogio.agora_))
    destino = DestinoEmMemoria()
    agendador = _agendador_com_destino(m, destino=destino)

    with caplog.at_level(logging.INFO):
        await agendador._tick()

    assert m.banco.obter_ultimo_snapshot() == date(2026, 9, 20)
    assert set(destino.gravados) == {
        ("espacos", date(2026, 9, 20)),
        ("pessoas", date(2026, 9, 20)),
        ("admins", date(2026, 9, 20)),
        ("termos", date(2026, 9, 20)),
        ("grupos_pendentes", date(2026, 9, 20)),
        ("firestore_uso", date(2026, 9, 20)),
    }
    assert destino.gravados[("espacos", date(2026, 9, 20))] != b""
    (evento,) = eventos(caplog.records, "snapshot_ok")
    assert evento.n >= 1


async def test_snapshot_nao_roda_duas_vezes_no_mesmo_dia() -> None:
    m = montar()
    m.relogio.agora_ = datetime(2026, 9, 20, 4, 0, tzinfo=UTC)
    destino = DestinoEmMemoria()
    agendador = _agendador_com_destino(m, destino=destino)
    await agendador._tick()
    destino.gravados.clear()

    m.relogio.avancar(timedelta(minutes=1))
    await agendador._tick()

    assert destino.gravados == {}  # não gravou de novo


async def test_snapshot_do_dia_seguinte_roda_de_novo() -> None:
    m = montar()
    m.relogio.agora_ = datetime(2026, 9, 20, 4, 0, tzinfo=UTC)
    destino = DestinoEmMemoria()
    agendador = _agendador_com_destino(m, destino=destino)
    await agendador._tick()

    m.relogio.agora_ = datetime(2026, 9, 21, 4, 0, tzinfo=UTC)
    await agendador._tick()

    assert m.banco.obter_ultimo_snapshot() == date(2026, 9, 21)


async def test_snapshot_com_falha_registra_evento_e_nao_marca(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _DestinoQueFalha:
        def gravar(self, tabela: str, dia: date, linhas: list[object]) -> None:
            raise RuntimeError("GCS fora do ar")

    m = montar()
    m.relogio.agora_ = datetime(2026, 9, 20, 4, 0, tzinfo=UTC)
    agendador = _agendador_com_destino(m, destino=_DestinoQueFalha())  # type: ignore[arg-type]

    with caplog.at_level(logging.INFO):
        await agendador._tick()  # não pode levantar: o tick engole a falha (como os demais passos)

    assert m.banco.obter_ultimo_snapshot() is None
    assert eventos(caplog.records, "snapshot_falhou") != []
    assert eventos(caplog.records, "snapshot_ok") == []
