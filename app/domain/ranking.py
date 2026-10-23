"""Ranking de engajamento (M58, ADR-0056): lógica pura, sem banco.

Uma *interação* é uma resposta registrada na revisão diária ou no desafio semanal
(`espacos/{grupo}/respostas/`). Adicionar palavra não conta. Staff (dono, admin do bot e
professores) fica fora de todas as contagens.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.domain.models import Membro, Resposta

TOP_ALUNOS = 20
TOP_TURMAS = 10
TOP_POR_TURMA = 3
FUSO_PADRAO = ZoneInfo("America/Sao_Paulo")


def meses_atras(agora: datetime, meses: int) -> datetime:
    """`agora` menos `meses` meses de calendário (dia ajustado ao fim do mês menor)."""
    indice = agora.year * 12 + (agora.month - 1) - meses
    ano, mes = divmod(indice, 12)
    mes += 1
    dia = min(agora.day, calendar.monthrange(ano, mes)[1])
    return agora.replace(year=ano, month=mes, day=dia)


@dataclass
class Turma:
    """Os dados de um grupo ativo no período."""

    nome: str
    membros: list[tuple[str, Membro]]
    respostas: list[Resposta] = field(default_factory=list)


@dataclass
class LinhaAluno:
    nome: str  # o nome salvo do WhatsApp; vazio se o bot nunca o recebeu
    numero: str = ""
    total: int = 0
    diarias: int = 0
    semanais: int = 0
    aceitas: int = 0  # respostas com qualidade != de_novo
    dias: int = 0  # dias distintos com interação
    turmas: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LinhaTurma:
    nome: str
    total: int
    alunos: int  # matriculados (membros que não são staff)
    ativos: int  # quantos deles interagiram no período

    @property
    def por_aluno(self) -> float:
        return self.total / self.alunos if self.alunos else 0.0


@dataclass(frozen=True)
class Ranking:
    alunos: list[LinhaAluno]
    turmas: list[LinhaTurma]
    por_turma: list[tuple[str, list[LinhaAluno]]]

    @property
    def vazio(self) -> bool:
        return not self.alunos


def _contar(
    respostas: list[Resposta], nomes: dict[str, str], fuso: ZoneInfo
) -> dict[str, LinhaAluno]:
    por: dict[str, list[Resposta]] = defaultdict(list)
    for r in respostas:
        por[r.autor_id].append(r)
    return {
        autor: LinhaAluno(
            nome=nomes.get(autor, ""),
            numero=autor,
            total=len(rs),
            diarias=sum(1 for r in rs if r.tipo == "diaria"),
            semanais=sum(1 for r in rs if r.tipo == "semanal"),
            aceitas=sum(1 for r in rs if r.qualidade != "de_novo"),
            dias=len({r.criado_em.astimezone(fuso).date() for r in rs}),
        )
        for autor, rs in por.items()
    }


def _chave(a: LinhaAluno) -> tuple[int, int, int, str, str]:
    return (-a.total, -a.dias, -a.aceitas, a.nome, a.numero)


def calcular(
    turmas: list[Turma],
    *,
    eh_staff: Callable[[str], bool],
    fuso: ZoneInfo = FUSO_PADRAO,
) -> Ranking:
    globais: dict[str, LinhaAluno] = {}
    dias_globais: dict[str, set[date]] = defaultdict(set)
    linhas_turma: list[LinhaTurma] = []
    por_turma: list[tuple[str, list[LinhaAluno]]] = []

    for turma in turmas:
        nomes = {n: m.nome or "" for n, m in turma.membros}
        locais = {n for n, m in turma.membros if m.papel == "professor"}  # papel antigo, por grupo

        def staff(numero: str, locais: set[str] = locais) -> bool:
            return numero in locais or eh_staff(numero)

        respostas = [r for r in turma.respostas if not staff(r.autor_id)]
        contagem = _contar(respostas, nomes, fuso)
        matriculados = {n for n, _ in turma.membros if not staff(n)} | set(contagem)
        total = sum(c.total for c in contagem.values())
        if total:
            linhas_turma.append(LinhaTurma(turma.nome, total, len(matriculados), len(contagem)))
            top = sorted(contagem.values(), key=_chave)[:TOP_POR_TURMA]
            por_turma.append((turma.nome, top))
        for autor, linha in contagem.items():
            g = globais.setdefault(autor, LinhaAluno(nome=linha.nome, numero=autor))
            g.nome = g.nome or linha.nome
            g.total += linha.total
            g.diarias += linha.diarias
            g.semanais += linha.semanais
            g.aceitas += linha.aceitas
            g.turmas.append(turma.nome)
        for r in respostas:
            dias_globais[r.autor_id].add(r.criado_em.astimezone(fuso).date())

    for autor, g in globais.items():
        g.dias = len(dias_globais[autor])
    alunos = sorted(globais.values(), key=_chave)[:TOP_ALUNOS]
    turmas_ordenadas = sorted(linhas_turma, key=lambda t: (-t.por_aluno, -t.total, t.nome))
    return Ranking(alunos, turmas_ordenadas[:TOP_TURMAS], por_turma)
