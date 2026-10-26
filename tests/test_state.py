"""Testes de app/domain/state.py — a máquina de estados do M9/M10 (três estados, um único menu
de ações e a revisão espaçada)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.models import Estado
from app.domain.state import Acao, Transicao, expirou, transicionar

# (estado, texto, transição esperada)
TRANSICOES = [
    # IDLE: qualquer texto é uma palavra/expressão a explicar.
    (Estado.IDLE, "stall", Transicao(Estado.AWAIT_ACTION, Acao.EXPLICAR, "stall")),
    (
        Estado.IDLE,
        "stall | the talks stalled",
        Transicao(Estado.AWAIT_ACTION, Acao.EXPLICAR, "stall | the talks stalled"),
    ),
    # AWAIT_ACTION: o menu único, sem opção 1 (M25: o áudio virou automático, não é mais escolha).
    (Estado.AWAIT_ACTION, "1", Transicao(Estado.AWAIT_ACTION, Acao.ROTEAR, "1")),
    (Estado.AWAIT_ACTION, "hear it", Transicao(Estado.AWAIT_ACTION, Acao.ROTEAR, "hear it")),
    (Estado.AWAIT_ACTION, "2", Transicao(Estado.AWAIT_ACTION, Acao.GERAR_EXEMPLOS)),
    (Estado.AWAIT_ACTION, "see more examples", Transicao(Estado.AWAIT_ACTION, Acao.GERAR_EXEMPLOS)),
    (Estado.AWAIT_ACTION, "3", Transicao(Estado.AWAIT_ACTION, Acao.GERAR_SINONIMOS)),
    (Estado.AWAIT_ACTION, "check synonyms", Transicao(Estado.AWAIT_ACTION, Acao.GERAR_SINONIMOS)),
    (Estado.AWAIT_ACTION, "4", Transicao(Estado.IDLE, Acao.SALVAR)),
    (Estado.AWAIT_ACTION, "just save", Transicao(Estado.IDLE, Acao.SALVAR)),
    (Estado.AWAIT_ACTION, "5", Transicao(Estado.IDLE, Acao.IGNORAR)),
    (Estado.AWAIT_ACTION, "ignore this word", Transicao(Estado.IDLE, Acao.IGNORAR)),
    # `palavra | contexto` no meio de uma palavra: a IA de roteamento não entra, é uma explicação.
    (
        Estado.AWAIT_ACTION,
        "stall | to delay on purpose",
        Transicao(Estado.AWAIT_ACTION, Acao.EXPLICAR_COM_CONTEXTO, "stall | to delay on purpose"),
    ),
    (Estado.AWAIT_ACTION, "stall |", Transicao(Estado.AWAIT_ACTION, Acao.ROTEAR, "stall |")),
    (Estado.AWAIT_ACTION, "| stall", Transicao(Estado.AWAIT_ACTION, Acao.ROTEAR, "| stall")),
    # 0/skip abrem caminho para outra palavra ou comando, sem passar pela IA.
    (Estado.AWAIT_ACTION, "0", Transicao(Estado.IDLE, Acao.PULAR)),
    (Estado.AWAIT_ACTION, "skip", Transicao(Estado.IDLE, Acao.PULAR)),
    (Estado.AWAIT_ACTION, "Skip", Transicao(Estado.IDLE, Acao.PULAR)),
    (Estado.AWAIT_ACTION, "stop", Transicao(Estado.AWAIT_ACTION, Acao.ROTEAR, "stop")),
    # Qualquer outro texto (frase, pedido, palavra nova, fora do escopo...) vai para o roteamento.
    (
        Estado.AWAIT_ACTION,
        "the talks stalled last week",
        Transicao(Estado.AWAIT_ACTION, Acao.ROTEAR, "the talks stalled last week"),
    ),
    (
        Estado.AWAIT_ACTION,
        "how do I pronounce it?",
        Transicao(Estado.AWAIT_ACTION, Acao.ROTEAR, "how do I pronounce it?"),
    ),
    (Estado.AWAIT_ACTION, "hedge", Transicao(Estado.AWAIT_ACTION, Acao.ROTEAR, "hedge")),
    (Estado.AWAIT_ACTION, "7", Transicao(Estado.AWAIT_ACTION, Acao.ROTEAR, "7")),
    # REVIEWING (M10): qualquer texto é a resposta do aluno, exceto "sair" (0/stop/quit/...).
    (
        Estado.REVIEWING,
        "to stop making progress",
        Transicao(Estado.REVIEWING, Acao.RESPONDER_REVISAO, "to stop making progress"),
    ),
    (
        Estado.REVIEWING,
        "The talks stalled last week.",
        Transicao(Estado.REVIEWING, Acao.RESPONDER_REVISAO, "The talks stalled last week."),
    ),
    (Estado.REVIEWING, "0", Transicao(Estado.IDLE, Acao.ENCERRAR_REVISAO)),
    (Estado.REVIEWING, "stop", Transicao(Estado.IDLE, Acao.ENCERRAR_REVISAO)),
    (Estado.REVIEWING, "Quit", Transicao(Estado.IDLE, Acao.ENCERRAR_REVISAO)),
]


@pytest.mark.parametrize(("estado", "texto", "esperada"), TRANSICOES)
def test_transicoes(estado: Estado, texto: str, esperada: Transicao) -> None:
    assert transicionar(estado, texto) == esperada


def test_sessao_expira_depois_de_3_horas_parada() -> None:
    agora = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)

    assert expirou(agora - timedelta(hours=3, minutes=1), agora) is True
    assert expirou(agora - timedelta(hours=2, minutes=59), agora) is False
