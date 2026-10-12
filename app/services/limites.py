"""Limite de uso por pessoa e por espaço (M43, ADR-0041): janela deslizante em memória.

Um processo, uma VM: não precisa de Redis. Reiniciar o bot zera os contadores, o que é aceitável (o
teto que importa para a conta é o orçamento diário, ADR-0044). Nada aqui conhece WhatsApp ou IA."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from app.domain.models import agora_utc

Motivo = Literal["minuto", "dia", "grupo", "audio"]
_MINUTO = timedelta(minutes=1)
_DIA = timedelta(days=1)


@dataclass(frozen=True)
class Limites:
    pessoa_por_minuto: int = 6
    pessoa_por_dia: int = 150
    grupo_por_dia: int = 400
    audio_segundos_por_dia: int = 600


@dataclass(frozen=True)
class Decisao:
    permitido: bool
    avisar: bool = False  # só na primeira recusa de uma sequência: as seguintes ficam em silêncio
    motivo: Motivo | None = None


PERMITIDO = Decisao(True)


class _Janela:
    """Eventos `(quando, custo)` dentro de uma janela; soma o custo vivo."""

    def __init__(self, duracao: timedelta) -> None:
        self._duracao = duracao
        self._eventos: deque[tuple[datetime, int]] = deque()
        self._soma = 0

    def total(self, agora: datetime) -> int:
        corte = agora - self._duracao
        while self._eventos and self._eventos[0][0] <= corte:
            self._soma -= self._eventos.popleft()[1]
        return self._soma

    def somar(self, agora: datetime, custo: int) -> None:
        self._eventos.append((agora, custo))
        self._soma += custo

    def vazia(self) -> bool:
        return not self._eventos


class LimitadorDeUso:
    def __init__(self, limites: Limites, agora: Callable[[], datetime] = agora_utc) -> None:
        self._limites = limites
        self._agora = agora
        self._janelas: dict[tuple[str, str], _Janela] = {}
        self._avisados: set[str] = set()

    def _janela(self, chave: str, tipo: str, duracao: timedelta) -> _Janela:
        return self._janelas.setdefault((chave, tipo), _Janela(duracao))

    def admitir(
        self, pessoa: str, espaco: str, *, em_grupo: bool, segundos_de_audio: int = 0
    ) -> Decisao:
        """Confere TODOS os limites antes de gastar qualquer um: uma recusa não consome nada (senão
        quem insiste nunca sairia do bloqueio)."""
        agora = self._agora()
        limites = self._limites
        minuto = self._janela(pessoa, "minuto", _MINUTO)
        dia = self._janela(pessoa, "dia", _DIA)
        grupo = self._janela(espaco, "grupo", _DIA) if em_grupo else None
        audio = self._janela(pessoa, "audio", _DIA) if segundos_de_audio else None

        motivo: Motivo | None = None
        chave_do_aviso = pessoa
        if minuto.total(agora) + 1 > limites.pessoa_por_minuto:
            motivo = "minuto"
        elif dia.total(agora) + 1 > limites.pessoa_por_dia:
            motivo = "dia"
        elif grupo is not None and grupo.total(agora) + 1 > limites.grupo_por_dia:
            motivo, chave_do_aviso = "grupo", espaco
        elif audio is not None and (
            audio.total(agora) + segundos_de_audio > limites.audio_segundos_por_dia
        ):
            motivo = "audio"

        if motivo is not None:
            avisar = chave_do_aviso not in self._avisados
            self._avisados.add(chave_do_aviso)
            self._limpar(pessoa, espaco, agora)
            return Decisao(False, avisar, motivo)

        minuto.somar(agora, 1)
        dia.somar(agora, 1)
        if grupo is not None:
            grupo.somar(agora, 1)
        if audio is not None:
            audio.somar(agora, segundos_de_audio)
        self._avisados.discard(pessoa)
        self._avisados.discard(espaco)
        return PERMITIDO

    def _limpar(self, pessoa: str, espaco: str, agora: datetime) -> None:
        """Janelas vazias saem do dicionário: o mapa não cresce com quem só falou uma vez."""
        for chave in [c for c in self._janelas if c[0] in (pessoa, espaco)]:
            janela = self._janelas[chave]
            janela.total(agora)
            if janela.vazia():
                del self._janelas[chave]
