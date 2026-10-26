"""Máquina de estados da conversa (seção 5.1) como função pura (ADR-0004, ADR-0009).

`transicionar` só decide: devolve o próximo estado e a ação que os fluxos (M4/M9/M10) devem
executar. Não chama LLM, repositório nem canal — mesmo o roteamento por IA (`Acao.ROTEAR`), a
revisão diária (`Acao.RESPONDER_REVISAO`) e o desafio semanal (`Acao.RESPONDER_PERGUNTA`) são
decididos aqui como "isto precisa de IA" e executados pelo `Router`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from app.domain.choices import (
    MENU_ACOES,
    eh_pular,
    eh_sair,
    normalizar,
    parse_escolha,
    separar_contexto,
)
from app.domain.models import Estado

SESSAO_EXPIRA_APOS = timedelta(hours=3)


class Acao(StrEnum):
    EXPLICAR = "EXPLICAR"
    EXPLICAR_COM_CONTEXTO = "EXPLICAR_COM_CONTEXTO"
    GERAR_EXEMPLOS = "GERAR_EXEMPLOS"
    GERAR_SINONIMOS = "GERAR_SINONIMOS"
    SALVAR = "SALVAR"
    PULAR = "PULAR"
    IGNORAR = "IGNORAR"
    ROTEAR = "ROTEAR"
    RESPONDER_REVISAO = "RESPONDER_REVISAO"
    ENCERRAR_REVISAO = "ENCERRAR_REVISAO"
    RESPONDER_PERGUNTA = "RESPONDER_PERGUNTA"
    EXPLICAR_PERGUNTA = "EXPLICAR_PERGUNTA"
    OUVIR_PERGUNTA = "OUVIR_PERGUNTA"
    PULAR_PERGUNTA = "PULAR_PERGUNTA"
    ENCERRAR_SEMANAL = "ENCERRAR_SEMANAL"


@dataclass(frozen=True)
class Transicao:
    """`estado` é o estado depois da ação."""

    estado: Estado
    acao: Acao
    argumento: str | None = None


def expirou(atualizado_em: datetime, agora: datetime) -> bool:
    """Sessão parada há mais de 3 horas volta para IDLE (o fluxo salva o que houver)."""
    return agora - atualizado_em > SESSAO_EXPIRA_APOS


_ACAO_DO_MENU = {
    2: Acao.GERAR_EXEMPLOS,
    3: Acao.GERAR_SINONIMOS,
    4: Acao.SALVAR,
    5: Acao.IGNORAR,
}
_ACAO_QUE_ENCERRA = {Acao.SALVAR, Acao.IGNORAR}


def transicionar(estado: Estado, texto: str) -> Transicao:
    texto = texto.strip()
    match estado:
        case Estado.IDLE:
            return Transicao(Estado.AWAIT_ACTION, Acao.EXPLICAR, texto)
        case Estado.AWAIT_ACTION:
            return _await_action(texto)
        case Estado.REVIEWING:
            return _reviewing(texto)
        case Estado.WEEKLY_QUIZ:
            return _weekly_quiz(texto)


def _await_action(texto: str) -> Transicao:
    opcao = parse_escolha(texto, MENU_ACOES)
    if opcao is not None:
        acao = _ACAO_DO_MENU[opcao]
        estado = Estado.IDLE if acao in _ACAO_QUE_ENCERRA else Estado.AWAIT_ACTION
        return Transicao(estado, acao)
    if eh_pular(texto):
        return Transicao(Estado.IDLE, Acao.PULAR)
    termo, contexto = separar_contexto(texto)
    # `palavra | sentido ou frase`: é um pedido de explicação, sem roteamento
    if termo and contexto:
        return Transicao(Estado.AWAIT_ACTION, Acao.EXPLICAR_COM_CONTEXTO, texto)
    return Transicao(Estado.AWAIT_ACTION, Acao.ROTEAR, texto)


def _reviewing(texto: str) -> Transicao:
    """Durante a revisão (seção 5.7), qualquer texto que não seja "sair" é a resposta do aluno
    para a palavra atual — sem roteamento por IA aqui, que só geraria ambiguidade e custo."""
    if eh_sair(texto):
        return Transicao(Estado.IDLE, Acao.ENCERRAR_REVISAO)
    return Transicao(Estado.REVIEWING, Acao.RESPONDER_REVISAO, texto)


def _weekly_quiz(texto: str) -> Transicao:
    """Desafio semanal do grupo (M36, seção 5.2b): `1` explica a pergunta, `2` a lê em voz alta,
    `3`/`skip` a pula, `skipall`/`0`/`stop` encerra; qualquer outro texto é a resposta (só a da
    pessoa marcada avança a pergunta — quem decide é o fluxo)."""
    normal = normalizar(texto)
    if normal == "1":
        return Transicao(Estado.WEEKLY_QUIZ, Acao.EXPLICAR_PERGUNTA)
    if normal == "2":
        return Transicao(Estado.WEEKLY_QUIZ, Acao.OUVIR_PERGUNTA)
    if normal in {"3", "skip"}:
        return Transicao(Estado.WEEKLY_QUIZ, Acao.PULAR_PERGUNTA)
    if normal in {"skip all", "skipall"} or eh_sair(texto):
        return Transicao(Estado.IDLE, Acao.ENCERRAR_SEMANAL)
    return Transicao(Estado.WEEKLY_QUIZ, Acao.RESPONDER_PERGUNTA, texto)
