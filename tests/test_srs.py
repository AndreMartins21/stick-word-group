"""Testes de app/domain/srs.py — caixas do grupo pela cobertura da turma (M65, ADR-0064), função
pura."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.models import Entry, SentidoSalvo
from app.domain.srs import CAIXA_MAXIMA, PRAZOS_DO_GRUPO, reagendar, vencida

AGORA = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


def _entrada(**campos: object) -> Entry:
    base = {
        "slug": "stall",
        "palavra": "stall",
        "classe": "verb",
        "cefr_estimado": "B2",
        "sentido": SentidoSalvo(traducao="travar", definicao="to stop making progress"),
    }
    return Entry.model_validate(base | campos)


def test_turma_cobrindo_a_palavra_sobe_uma_caixa() -> None:
    agendamento = reagendar(_entrada(repeticoes=1), 0.8, AGORA)

    assert agendamento.repeticoes == 2
    assert agendamento.intervalo_dias == pytest.approx(PRAZOS_DO_GRUPO[2])
    assert agendamento.proxima_revisao == AGORA + timedelta(days=PRAZOS_DO_GRUPO[2])
    assert agendamento.lapsos == 0


def test_cobertura_media_mantem_a_caixa_e_repete_o_prazo() -> None:
    agendamento = reagendar(_entrada(repeticoes=2), 0.6, AGORA)

    assert agendamento.repeticoes == 2
    assert agendamento.intervalo_dias == pytest.approx(PRAZOS_DO_GRUPO[2])


def test_cobertura_baixa_desce_uma_caixa_e_conta_lapso() -> None:
    agendamento = reagendar(_entrada(repeticoes=3, lapsos=1), 0.3, AGORA)

    assert agendamento.repeticoes == 2
    assert agendamento.lapsos == 2


def test_a_caixa_nao_passa_dos_limites() -> None:
    assert reagendar(_entrada(repeticoes=CAIXA_MAXIMA), 1.0, AGORA).repeticoes == CAIXA_MAXIMA
    assert reagendar(_entrada(repeticoes=0), 0.0, AGORA).repeticoes == 0


def test_caixa_fora_da_escala_de_um_cartao_antigo_e_limitada() -> None:
    """Cartões do SM-2 (ADR-0011) podem ter `repeticoes` maior que a escala nova."""
    agendamento = reagendar(_entrada(repeticoes=9), 0.6, AGORA)

    assert agendamento.repeticoes == CAIXA_MAXIMA


def test_sem_cobertura_mantem_a_caixa() -> None:
    """Nenhum aluno ativo (só o professor respondeu): sem sinal da turma, a caixa fica."""
    agendamento = reagendar(_entrada(repeticoes=1), None, AGORA)

    assert agendamento.repeticoes == 1


def test_vencida_cartao_novo_ou_com_proxima_revisao_no_passado() -> None:
    assert vencida(_entrada(), AGORA)
    assert vencida(_entrada(proxima_revisao=AGORA - timedelta(hours=1)), AGORA)
    assert vencida(_entrada(proxima_revisao=AGORA), AGORA)
    assert not vencida(_entrada(proxima_revisao=AGORA + timedelta(hours=1)), AGORA)
