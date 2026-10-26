"""Testes de app/domain/choices.py: parser de escolhas numéricas e detecção da palavra-alvo."""

from __future__ import annotations

import pytest

from app.domain.choices import (
    MENU_ACOES,
    contem_palavra_alvo,
    eh_pular,
    eh_sair,
    marcar_alvo,
    normalizar,
    parse_escolha,
    parse_numero,
    separar_contexto,
)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        (" 2 ", 2),
        # M25: a opção 1 (ouvir) some do menu — o áudio virou automático.
        ("1", None),
        ("1.", None),
        ("1)", None),
        ("1️⃣", None),
        ("hear it", None),
        ("Hear the pronunciation", None),
        ("see more examples", 2),
        ("See More Examples", 2),
        ("examples", 2),
        ("check synonyms", 3),
        ("synonyms", 3),
        ("see more synonyms", 3),
        ("just save", 4),
        ("save", 4),
        ("done", 4),
        ("5", 5),
        ("five", 5),
        ("ignore this word", 5),
        ("Ignore it", 5),
        ("6", None),
        ("hear", None),  # sozinhas podem ser a palavra que o aluno quer aprender
        ("listen", None),
        ("ignore", None),
        ("drop", None),
        ("stall", None),
        ("", None),
    ],
)
def test_menu_acoes_aceita_numero_e_variacoes(texto: str, esperado: int | None) -> None:
    assert parse_escolha(texto, MENU_ACOES) == esperado


@pytest.mark.parametrize(
    ("texto", "maximo", "esperado"),
    [("1", 3, 1), ("3", 3, 3), ("4", 3, None), ("0", 3, None), ("x", 3, None)],
)
def test_parse_numero_respeita_o_maximo(texto: str, maximo: int, esperado: int | None) -> None:
    assert parse_numero(texto, maximo) == esperado


@pytest.mark.parametrize("texto", ["0", "stop", "Stop", "quit", "exit", "leave"])
def test_eh_sair(texto: str) -> None:
    assert eh_sair(texto) is True


@pytest.mark.parametrize("texto", ["0", "zero", "skip", "Skip", " 0 "])
def test_eh_pular(texto: str) -> None:
    assert eh_pular(texto) is True


@pytest.mark.parametrize("texto", ["1", "stop", "leave", "quit", "skipping", "stall", ""])
def test_eh_pular_rejeita_o_resto(texto: str) -> None:
    # "stop"/"leave" podem ser a palavra a aprender: só o que o bot anuncia (0/skip) sai.
    assert eh_pular(texto) is False


def test_eh_sair_rejeita_o_resto() -> None:
    assert eh_sair("1") is False
    assert eh_sair("stall") is False


def test_normalizar_tira_acento_pontuacao_e_maiuscula() -> None:
    assert normalizar("Ver Exemplos!") == "ver exemplos"
    assert normalizar("  três   ") == "tres"


@pytest.mark.parametrize(
    ("texto", "palavra"),
    [
        ("the talks stalled", "stall"),
        ("The talks STALLED.", "stall"),
        ("stalling again", "stall"),
        ("two stalls", "stall"),
        ("he stopped talking", "stop"),
        ("she is studying", "study"),
        ("it studies well", "study"),
        ("we decided to leave", "decide"),
        ("it's a lovely day", "love"),
        ("we are giving up early", "give up"),
        ("do not give it up", "give up"),
        ("she gives up easily", "give up"),
    ],
)
def test_contem_palavra_alvo_reconhece_flexoes_regulares(texto: str, palavra: str) -> None:
    assert contem_palavra_alvo(texto, palavra) is True


@pytest.mark.parametrize(
    ("texto", "palavra"),
    [
        ("I like coffee", "stall"),
        ("the installation failed", "stall"),  # substring não conta
        ("up we gave", "give up"),  # ordem importa
        ("just give", "give up"),
        ("", "stall"),
    ],
)
def test_contem_palavra_alvo_rejeita_o_que_nao_e_a_palavra(texto: str, palavra: str) -> None:
    assert contem_palavra_alvo(texto, palavra) is False


@pytest.mark.parametrize(
    ("frase", "palavra", "esperado"),
    [
        (
            "The negotiations stalled after the meeting.",
            "stall",
            "The negotiations [[stalled]] after the meeting.",
        ),
        ("Stalling again.", "stall", "[[Stalling]] again."),
        ("We had to give up early.", "give up", "We had to [[give up]] early."),
        ("Don't give it up now.", "give up", "Don't [[give it up]] now."),
        ("She is studying hard.", "study", "She is [[studying]] hard."),
        ("I like coffee.", "stall", None),
        ("The installation failed.", "stall", None),
        ("", "stall", None),
    ],
)
def test_marcar_alvo(frase: str, palavra: str, esperado: str | None) -> None:
    assert marcar_alvo(frase, palavra) == esperado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("stall", ("stall", None)),
        ("stall | the talks stalled", ("stall", "the talks stalled")),
        ("  stall|to delay on purpose ", ("stall", "to delay on purpose")),
        ("stall |", ("stall", None)),
        ("stall | a | b", ("stall", "a | b")),
        ("| stall", ("", "stall")),
    ],
)
def test_separar_contexto(texto: str, esperado: tuple[str, str | None]) -> None:
    assert separar_contexto(texto) == esperado
