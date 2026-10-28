"""Revisão espaçada do grupo (M65, seção 5.7, ADR-0064): caixas fixas pela cobertura da turma,
como função pura.

Igual à máquina de estados (ADR-0004), `reagendar` só decide: não lê nem grava nada. Substitui o
SM-2 simplificado do ADR-0011, cuja nota vinha só da primeira resposta aceitável — a do aluno mais
rápido. Agora a palavra muda de caixa pela **cobertura** (`domain/memoria.py`): a média da chance de
lembrar entre os alunos ativos. `repeticoes` guarda a caixa do grupo; `facilidade` fica sem uso.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.models import Entry

PRAZOS_DO_GRUPO = (1, 3, 7, 14, 30)  # dias, caixa 0..4
CAIXA_MAXIMA = len(PRAZOS_DO_GRUPO) - 1
LIMIAR_SOBE = 0.75
LIMIAR_DESCE = 0.5


@dataclass(frozen=True)
class Agendamento:
    repeticoes: int
    intervalo_dias: float
    proxima_revisao: datetime
    lapsos: int


def reagendar(entrada: Entry, cobertura: float | None, agora: datetime) -> Agendamento:
    """O próximo agendamento de `entrada` depois que a turma a respondeu na diária.

    Cobertura de ao menos `LIMIAR_SOBE`: sobe uma caixa. Abaixo de `LIMIAR_DESCE`: desce uma e conta
    um lapso. Entre os dois (ou `None`, sem aluno ativo): fica, e o prazo da caixa se repete.
    """
    caixa = min(entrada.repeticoes, CAIXA_MAXIMA)
    lapsos = entrada.lapsos
    if cobertura is not None and cobertura >= LIMIAR_SOBE:
        caixa = min(caixa + 1, CAIXA_MAXIMA)
    elif cobertura is not None and cobertura < LIMIAR_DESCE:
        caixa = max(caixa - 1, 0)
        lapsos += 1
    prazo = float(PRAZOS_DO_GRUPO[caixa])
    return Agendamento(
        repeticoes=caixa,
        intervalo_dias=prazo,
        proxima_revisao=agora + timedelta(days=prazo),
        lapsos=lapsos,
    )


def vencida(entrada: Entry, agora: datetime) -> bool:
    """Cartão novo (nunca revisado) ou cuja `proxima_revisao` já passou."""
    return entrada.proxima_revisao is None or entrada.proxima_revisao <= agora
