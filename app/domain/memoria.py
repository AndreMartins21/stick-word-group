"""Memória por aluno no grupo (M65, ADR-0064): funções puras, sem I/O.

O cartão da revisão diária é da turma, mas cada aluno lembra no seu tempo. Aqui cada par (aluno,
palavra) ganha um estado de Leitner calculado só a partir de `respostas/` da **diária** — o desafio
semanal consome esta memória, mas não a alimenta (decisão do usuário). Nenhuma IA: contas simples.

- Acerto (`qualidade != de_novo`) sobe a caixa do aluno (até 5); erro volta para 0.
- A chance de lembrar cai com o tempo desde o último acerto: 90% quando passa o prazo da caixa
  (1, 3, 7, 14, 30 dias). Quem errou por último tem chance 0.
- Silêncio não é erro: quem nunca respondeu a palavra recebe uma estimativa pela taxa de acerto
  dele (em outras palavras) e da turma (nesta palavra), nunca acima de `TETO_DESCONHECIDO` — sem
  ter praticado, a palavra nunca conta como sabida.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.models import PerguntaSemanal, Resposta, slugify

PRAZOS_DO_ALUNO = (1, 3, 7, 14, 30)  # dias, caixa 1..5
RETENCAO_NO_PRAZO = 0.9
TETO_DESCONHECIDO = 0.5
JANELA = timedelta(days=90)  # quanto de `respostas/` ler: limita as leituras do Firestore


@dataclass(frozen=True)
class EstadoDoAluno:
    caixa: int  # 0 = errou por último (ou nunca acertou)
    ultimo_acerto: datetime | None
    acertos: int
    erros: int


def _taxa(acertos: int, total: int) -> float:
    """Taxa de acerto suavizada (Laplace): sem dado nenhum, 50%."""
    return (acertos + 1) / (total + 2)


@dataclass(frozen=True)
class Memoria:
    estados: Mapping[tuple[str, str], EstadoDoAluno]

    @classmethod
    def de(cls, respostas: Iterable[Resposta]) -> Memoria:
        estados: dict[tuple[str, str], EstadoDoAluno] = {}
        for r in sorted(respostas, key=lambda r: r.criado_em):
            if r.tipo != "diaria":
                continue
            chave = (r.autor_id, r.entry)
            antes = estados.get(chave, EstadoDoAluno(0, None, 0, 0))
            if r.qualidade == "de_novo":
                estados[chave] = EstadoDoAluno(
                    0, antes.ultimo_acerto, antes.acertos, antes.erros + 1
                )
            else:
                caixa = min(antes.caixa + 1, len(PRAZOS_DO_ALUNO))
                estados[chave] = EstadoDoAluno(caixa, r.criado_em, antes.acertos + 1, antes.erros)
        return cls(estados)

    def estado(self, aluno: str, entry: str) -> EstadoDoAluno | None:
        return self.estados.get((aluno, entry))

    def respondeu_alguma(self, aluno: str) -> bool:
        return any(autor == aluno for autor, _ in self.estados)

    def _taxa_de(self, estados: Iterable[EstadoDoAluno]) -> float:
        lista = list(estados)
        acertos = sum(e.acertos for e in lista)
        return _taxa(acertos, acertos + sum(e.erros for e in lista))

    def chance(self, aluno: str, entry: str, agora: datetime) -> float:
        """A chance estimada de `aluno` lembrar `entry` agora, entre 0 e 1."""
        estado = self.estado(aluno, entry)
        if estado is None:
            do_aluno = self._taxa_de(e for (a, _), e in self.estados.items() if a == aluno)
            da_palavra = self._taxa_de(e for (_, p), e in self.estados.items() if p == entry)
            return min(TETO_DESCONHECIDO, (do_aluno + da_palavra) / 2)
        if estado.caixa == 0 or estado.ultimo_acerto is None:
            return 0.0
        dias = max(0.0, (agora - estado.ultimo_acerto).total_seconds() / 86400)
        prazo = PRAZOS_DO_ALUNO[estado.caixa - 1]
        return float(RETENCAO_NO_PRAZO ** (dias / prazo))


def alunos_ativos(alunos: Iterable[str], memoria: Memoria) -> list[str]:
    """Quem conta na cobertura: os alunos com ao menos uma resposta na diária. Quem só lê o grupo
    não pratica, e deixaria toda palavra presa para sempre."""
    return [a for a in alunos if memoria.respondeu_alguma(a)]


def cobertura(alunos: Iterable[str], entry: str, memoria: Memoria, agora: datetime) -> float | None:
    """A média da chance de lembrar `entry` entre os alunos ativos; `None` sem aluno ativo."""
    ativos = alunos_ativos(alunos, memoria)
    if not ativos:
        return None
    return sum(memoria.chance(a, entry, agora) for a in ativos) / len(ativos)


def necessidades(
    alunos: Iterable[str], entries: Sequence[str], memoria: Memoria, agora: datetime
) -> dict[str, dict[str, float]]:
    """Para cada aluno, o quanto ele precisa de cada palavra (1 - chance de lembrar)."""
    return {
        aluno: {entry: 1.0 - memoria.chance(aluno, entry, agora) for entry in entries}
        for aluno in alunos
    }


def necessidade_da_turma(
    alunos: Iterable[str], entries: Sequence[str], memoria: Memoria, agora: datetime
) -> dict[str, float] | None:
    """Para cada palavra, 1 - a cobertura dos alunos ativos; `None` sem aluno ativo."""
    ativos = alunos_ativos(alunos, memoria)
    if not ativos:
        return None
    return {
        entry: 1.0 - sum(memoria.chance(a, entry, agora) for a in ativos) / len(ativos)
        for entry in entries
    }


def escolher_pergunta(perguntas: Sequence[PerguntaSemanal], foco: Mapping[str, float]) -> int:
    """O índice (em `perguntas`) da pergunta cujas palavras o aluno mais precisa. Empate, ou sem
    foco, fica a primeira — a ordem da IA."""
    melhor, maior = 0, -1.0
    for indice, pergunta in enumerate(perguntas):
        valor = sum(foco.get(slugify(p), 0.0) for p in pergunta.palavras)
        if valor > maior:
            melhor, maior = indice, valor
    return melhor
