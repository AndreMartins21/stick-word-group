"""M34 (ADR-0032): turma de B1-B2 para cima não vê português; o privado e as turmas iniciantes
seguem com a linha 🇧🇷. A tradução continua gerada e gravada (identidade do sentido, planilha)."""

from __future__ import annotations

from typing import get_args

import pytest

from app import messages
from app.domain.models import NivelUsuario, nivel_so_ingles
from app.flows.base import Autor
from app.services.fake_llm import FakeTutor
from app.services.prompts import _CALIBRACAO_POR_NIVEL
from tests.helpers import ANA, DONO_NUMERO, GRUPO, Montagem, explicacao_stall, montar
from tests.test_flows import EXEMPLOS, SINONIMOS

DONO = Autor(DONO_NUMERO, "Dono")


def _turma(nivel: str) -> Montagem:
    m = montar(
        tutor=FakeTutor(
            explicacoes=[explicacao_stall()], exemplos=[EXEMPLOS], sinonimos=[SINONIMOS]
        )
    )
    return m


async def _com_nivel(nivel: str) -> Montagem:
    m = _turma(nivel)
    await m.diz_no_grupo(DONO, f"!level {nivel}")
    return m


@pytest.mark.parametrize("nivel", ["A1-A2", "A2-B1"])
async def test_turma_iniciante_ve_o_portugues(nivel: str) -> None:
    m = await _com_nivel(nivel)

    (card,) = await m.diz_no_grupo(ANA, "!add stall")
    (lista,) = await m.diz_no_grupo(ANA, "!list")

    assert "🇧🇷 travar, emperrar" in card
    assert "1. stall: travar, emperrar" in lista


@pytest.mark.parametrize("nivel", ["B1-B2", "B2-C1", "C1-C2", "C2"])
async def test_turma_avancada_so_ve_ingles(nivel: str) -> None:
    m = await _com_nivel(nivel)

    (card,) = await m.diz_no_grupo(ANA, "!add stall")
    (exemplos,) = await m.diz_no_grupo(ANA, "!2")
    (sinonimos,) = await m.diz_no_grupo(ANA, "!3")
    (lista,) = await m.diz_no_grupo(ANA, "!list")

    for texto in (card, exemplos, sinonimos, lista):
        assert "travar" not in texto and "enrolar" not in texto and "🇧🇷" not in texto
    assert "📖 to stop making progress" in card
    assert "↔️ to delay on purpose" in card
    assert "Examples with stall* (to stop making progress)" in exemplos
    assert "1. stall: to stop making progress" in lista
    (entrada,) = m.banco.do_espaco(GRUPO).listar_entradas()
    assert entrada.sentido.traducao == "travar, emperrar"  # segue gravada


def test_lista_corta_definicao_longa_so_em_ingles() -> None:
    from app.domain.models import Entry, SentidoSalvo

    longa = "a very long definition " * 8
    e = Entry(
        slug="x",
        palavra="x",
        classe="noun",
        cefr_estimado="B2",
        sentido=SentidoSalvo(traducao="x", definicao=longa),
    )

    linha = messages._linha_de_entrada(e, pt=False)

    assert linha.endswith("…") and len(linha) < 90


def test_so_a1_a2_e_a2_b1_mostram_portugues() -> None:
    assert [n for n in get_args(NivelUsuario) if not nivel_so_ingles(n)] == ["A1-A2", "A2-B1"]


def test_todo_nivel_tem_calibracao_no_prompt() -> None:
    assert set(get_args(NivelUsuario)) == set(_CALIBRACAO_POR_NIVEL)
