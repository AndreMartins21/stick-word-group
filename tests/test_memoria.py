"""Testes de app/domain/memoria.py — memória por aluno no grupo (M65, ADR-0064), funções puras."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.memoria import (
    TETO_DESCONHECIDO,
    Memoria,
    alunos_ativos,
    cobertura,
    escolher_pergunta,
    necessidades,
)
from app.domain.models import PerguntaSemanal, QualidadeRevisao, Resposta

AGORA = datetime(2026, 10, 28, 19, 0, tzinfo=UTC)
ANA, BIA, CAIO = "5531999998888", "5511988887777", "5521977776666"


def _r(
    autor: str,
    entry: str,
    qualidade: QualidadeRevisao = "bom",
    *,
    dias_atras: float = 0,
    tipo: str | None = "diaria",
) -> Resposta:
    return Resposta.model_validate(
        {
            "entry": entry,
            "autor_id": autor,
            "marcado": False,
            "qualidade": qualidade,
            "tipo": tipo,
            "criado_em": AGORA - timedelta(days=dias_atras),
        }
    )


# --- o estado de cada par (aluno, palavra) ----------------------------------------------------


def test_acerto_sobe_a_caixa_e_erro_volta_para_zero() -> None:
    memoria = Memoria.de(
        [
            _r(ANA, "stall", dias_atras=10),
            _r(ANA, "stall", dias_atras=8),
            _r(BIA, "stall", dias_atras=9),
            _r(BIA, "stall", "de_novo", dias_atras=2),
        ]
    )

    ana = memoria.estado(ANA, "stall")
    bia = memoria.estado(BIA, "stall")
    assert ana is not None and ana.caixa == 2 and ana.acertos == 2 and ana.erros == 0
    assert bia is not None and bia.caixa == 0 and bia.acertos == 1 and bia.erros == 1
    assert memoria.estado(CAIO, "stall") is None


def test_o_semanal_so_consome_nao_entra_na_memoria() -> None:
    """O usuário decidiu: o desafio semanal usa a memória, mas não a alimenta."""
    memoria = Memoria.de(
        [
            _r(ANA, "stall", "de_novo", tipo="semanal"),
            _r(BIA, "stall", tipo=None),  # anterior ao M58: não dá para saber de onde veio
        ]
    )

    assert memoria.estado(ANA, "stall") is None
    assert memoria.estado(BIA, "stall") is None


def test_chance_de_lembrar_cai_com_o_tempo_desde_o_acerto() -> None:
    memoria = Memoria.de([_r(ANA, "stall", dias_atras=0), _r(BIA, "stall", dias_atras=1)])

    assert memoria.chance(ANA, "stall", AGORA) == pytest.approx(1.0)
    # caixa 1 (prazo de 1 dia): um dia depois, 90%.
    assert memoria.chance(BIA, "stall", AGORA) == pytest.approx(0.9)
    assert memoria.chance(BIA, "stall", AGORA + timedelta(days=9)) < 0.5


def test_quem_errou_por_ultimo_tem_chance_zero() -> None:
    memoria = Memoria.de([_r(ANA, "stall", dias_atras=3), _r(ANA, "stall", "de_novo")])

    assert memoria.chance(ANA, "stall", AGORA) == 0.0


def test_silencio_nao_e_erro_mas_nunca_conta_como_sabido() -> None:
    """Quem nunca respondeu a palavra tem uma estimativa — no máximo 50%."""
    memoria = Memoria.de([_r(ANA, "stall"), _r(BIA, "stall")])

    assert memoria.chance(CAIO, "stall", AGORA) == pytest.approx(TETO_DESCONHECIDO)


def test_aluno_fraco_e_palavra_dificil_baixam_a_estimativa_de_quem_nao_respondeu() -> None:
    """A versão caseira da filtragem colaborativa: a taxa de acerto do aluno em outras palavras e a
    da turma nesta palavra estimam o par que ainda não tem dado."""
    respostas = [
        _r(ANA, "stall", "de_novo"),
        _r(BIA, "stall", "de_novo"),
        *(_r(CAIO, f"w{i}", "de_novo") for i in range(4)),
    ]
    memoria = Memoria.de(respostas)

    assert memoria.chance(CAIO, "stall", AGORA) < TETO_DESCONHECIDO


# --- quem conta e a cobertura da turma --------------------------------------------------------


def test_so_conta_quem_respondeu_alguma_diaria() -> None:
    memoria = Memoria.de([_r(ANA, "w1"), _r(BIA, "w2", tipo="semanal")])

    assert alunos_ativos([ANA, BIA, CAIO], memoria) == [ANA]


def test_cobertura_e_a_media_da_chance_dos_alunos_ativos() -> None:
    memoria = Memoria.de(
        [
            _r(ANA, "stall"),  # 1.0
            _r(BIA, "stall", "de_novo"),  # 0.0
            _r(CAIO, "outra"),  # ativo, nunca respondeu stall: 0.5
        ]
    )

    valor = cobertura([ANA, BIA, CAIO], "stall", memoria, AGORA)

    assert valor == pytest.approx((1.0 + 0.0 + 0.5) / 3)


def test_sem_aluno_ativo_nao_ha_cobertura() -> None:
    assert cobertura([ANA], "stall", Memoria.de([]), AGORA) is None


# --- o semanal escolhe pelo aluno -------------------------------------------------------------


def test_necessidade_de_cada_aluno_por_palavra() -> None:
    memoria = Memoria.de([_r(ANA, "stall"), _r(ANA, "cope", "de_novo")])

    foco = necessidades([ANA], ["stall", "cope"], memoria, AGORA)

    assert foco[ANA]["stall"] == pytest.approx(0.0)
    assert foco[ANA]["cope"] == pytest.approx(1.0)


def _pergunta(*palavras: str) -> PerguntaSemanal:
    marcadas = " ".join(f"[[{p}]]" for p in palavras)
    return PerguntaSemanal(pergunta=f"Use {marcadas}?", palavras=list(palavras), explicacao_en="x")


def test_escolhe_a_pergunta_com_as_palavras_que_o_aluno_mais_precisa() -> None:
    perguntas = [_pergunta("stall"), _pergunta("cope", "thrive"), _pergunta("bargain")]

    indice = escolher_pergunta(perguntas, {"stall": 0.1, "cope": 0.6, "thrive": 0.5})

    assert indice == 1


def test_sem_foco_mantem_a_ordem() -> None:
    perguntas = [_pergunta("stall"), _pergunta("cope")]

    assert escolher_pergunta(perguntas, {}) == 0
    assert escolher_pergunta(perguntas, {"stall": 0.5, "cope": 0.5}) == 0
