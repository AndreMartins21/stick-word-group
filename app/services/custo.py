"""Uso de tokens e custo estimado das chamadas à IA (M45, ADR-0043).

O provider soma o `usage_metadata` de cada resposta num acumulador da chamada atual (um
`ContextVar`, para não mudar o `Protocol` do provider nem misturar chamadas de threads diferentes);
quem mede (`_gerar_validado`, o transcritor) lê o total e registra no evento. Preços em USD por 1M de
tokens, da tabela pública do Gemini (confirmados em 2026-10-12)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


@dataclass
class Uso:
    entrada: int = 0  # tokens de texto/imagem da entrada
    audio: int = 0  # tokens de áudio da entrada
    saida: int = 0  # tokens da resposta
    raciocinio: int = 0  # tokens de "thinking", cobrados como saída

    def somar(self, outro: Uso) -> None:
        self.entrada += outro.entrada
        self.audio += outro.audio
        self.saida += outro.saida
        self.raciocinio += outro.raciocinio


@dataclass(frozen=True)
class Preco:
    entrada: float
    audio: float
    saida: float


# USD por 1M de tokens. Modelo desconhecido usa o preço do `gemini-3-flash` (o maior da família
# usada aqui): errar para cima mantém o orçamento diário (ADR-0044) conservador.
_PRECOS: dict[str, Preco] = {
    "gemini-3.1-flash-lite": Preco(0.25, 0.50, 1.50),
    "gemini-3.5-flash-lite": Preco(0.25, 0.50, 1.50),
    "gemini-3-flash": Preco(0.50, 1.00, 3.00),
}
_PRECO_PADRAO = Preco(0.50, 1.00, 3.00)


def preco_do_modelo(modelo: str) -> Preco:
    candidatos = [p for p in _PRECOS if modelo.startswith(p)]
    return _PRECOS[max(candidatos, key=len)] if candidatos else _PRECO_PADRAO


def custo_usd(modelo: str, uso: Uso) -> float:
    preco = preco_do_modelo(modelo)
    return (
        uso.entrada * preco.entrada
        + uso.audio * preco.audio
        + (uso.saida + uso.raciocinio) * preco.saida
    ) / 1_000_000


_ATUAL: ContextVar[Uso | None] = ContextVar("uso_da_chamada", default=None)


@contextmanager
def medir() -> Iterator[Uso]:
    """Acumula o uso de tudo que for registrado dentro do bloco (todas as tentativas)."""
    uso = Uso()
    token = _ATUAL.set(uso)
    try:
        yield uso
    finally:
        _ATUAL.reset(token)


def uso_da_resposta(resposta: Any, *, audio: bool = False) -> Uso:
    """Lê `usage_metadata` de uma resposta do Gemini; resposta sem ele (dublês) vale zero."""
    meta = getattr(resposta, "usage_metadata", None)
    if meta is None:
        return Uso()
    entrada = int(getattr(meta, "prompt_token_count", 0) or 0)
    return Uso(
        entrada=0 if audio else entrada,
        audio=entrada if audio else 0,
        saida=int(getattr(meta, "candidates_token_count", 0) or 0),
        raciocinio=int(getattr(meta, "thoughts_token_count", 0) or 0),
    )


_OBSERVADOR: Callable[[float, str | None], None] | None = None
_ESPACO: ContextVar[str | None] = ContextVar("espaco_da_chamada", default=None)


def definir_observador(observador: Callable[[float, str | None], None] | None) -> None:
    """Quem recebe o custo (USD) de cada chamada concluída, com o espaço (chat) que a causou: o
    orçamento (M46/M50, ADR-0044/ADR-0048). Um só, definido na subida do app; `None` desliga."""
    global _OBSERVADOR
    _OBSERVADOR = observador


@contextmanager
def no_espaco(espaco: str) -> Iterator[None]:
    """As chamadas de IA feitas dentro do bloco (inclusive em threads, que herdam o contexto) são
    atribuídas a `espaco` (M50, cota por grupo)."""
    token = _ESPACO.set(espaco)
    try:
        yield
    finally:
        _ESPACO.reset(token)


def notificar_gasto(usd: float) -> None:
    if _OBSERVADOR is not None:
        _OBSERVADOR(usd, _ESPACO.get())


def registrar_resposta(resposta: Any, *, audio: bool = False) -> Uso:
    """Soma o uso da resposta no acumulador atual (se houver um `medir()` aberto)."""
    uso = uso_da_resposta(resposta, audio=audio)
    atual = _ATUAL.get()
    if atual is not None:
        atual.somar(uso)
    return uso
