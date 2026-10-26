"""Parser de escolhas numéricas (seção 5.1) e detecção heurística da palavra-alvo.

Todas as escolhas são por número, mas aceitamos variações (`1`, `1.`, apelidos em inglês). Desde o
M9 há um único menu de ações (`MENU_ACOES`); os apelidos ficam em inglês porque a conversa toda é.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping

Menu = Mapping[int, tuple[str, ...]]

MENU_ACOES: Menu = {
    # M25 (ADR-0026): a opção 1 (ouvir) some daqui — o áudio virou automático, não é mais escolha
    # do menu. Os números 2-5 ficam como sempre foram, para não mudar o que o aluno já decorou.
    2: ("see more examples", "examples", "more examples", "more"),
    3: (
        "check synonyms",
        "synonyms",
        "see more synonyms",
        "more synonyms",
        "check synonym",
        "synonym",
    ),
    4: ("just save", "save", "done", "only save"),
    # Só frases inteiras: "ignore" e "drop" sozinhas podem ser a palavra que o aluno quer aprender.
    5: ("ignore this word", "ignore it", "discard it", "discard this word"),
}

_NUMEROS_POR_EXTENSO = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
}
_SAIR = {"0", "zero", "skip", "leave", "quit", "exit", "stop"}
# Sair de uma palavra já aberta (AWAIT_ACTION), para mandar outra: só o que o bot anuncia. "stop",
# "leave" etc. seguem sendo palavras que o aluno pode querer aprender.
_PULAR = {"0", "zero", "skip"}


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento, emoji-teclado ou pontuação; espaços colapsados."""
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_marcas = "".join(c for c in decomposto if not unicodedata.category(c).startswith("M"))
    so_palavras = re.sub(r"[^\w\s]", " ", sem_marcas.lower())
    return " ".join(so_palavras.split())


def separar_contexto(texto: str) -> tuple[str, str | None]:
    """`palavra | contexto` → (`palavra`, `contexto`). O contexto é a frase onde o aluno viu a
    palavra ou o sentido que ele quer; sem `|`, ou com o lado direito vazio, é `None`."""
    termo, barra, contexto = texto.partition("|")
    contexto = contexto.strip()
    return termo.strip(), (contexto if barra and contexto else None)


def _como_numero(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _NUMEROS_POR_EXTENSO.get(token)


def parse_escolha(texto: str, menu: Menu) -> int | None:
    """Número (ou apelido) -> opção do menu; `None` se não for uma opção válida."""
    normalizado = normalizar(texto)
    numero = _como_numero(normalizado)
    if numero is not None:
        return numero if numero in menu else None
    for opcao, apelidos in menu.items():
        if normalizado in apelidos:
            return opcao
    return None


def parse_numero(texto: str, maximo: int) -> int | None:
    """Um número de 1 a `maximo`."""
    numero = _como_numero(normalizar(texto))
    return numero if numero is not None and 1 <= numero <= maximo else None


def eh_sair(texto: str) -> bool:
    return normalizar(texto) in _SAIR


def eh_pular(texto: str) -> bool:
    return normalizar(texto) in _PULAR


def _flexoes(palavra: str) -> set[str]:
    formas = {
        palavra,
        palavra + "s",
        palavra + "es",
        palavra + "ed",
        palavra + "ing",
        palavra + "ly",
    }
    if palavra.endswith("e"):
        formas |= {palavra + "d", palavra[:-1] + "ing"}
    if len(palavra) > 1 and palavra.endswith("y") and palavra[-2] not in "aeiou":
        radical = palavra[:-1]
        formas |= {radical + "ies", radical + "ied", radical + "ily"}
    if len(palavra) > 1 and palavra[-1] not in "aeiouwxy":
        formas |= {palavra + palavra[-1] + "ed", palavra + palavra[-1] + "ing"}
    return formas


def contem_palavra_alvo(texto: str, palavra: str) -> bool:
    """Heurística: a palavra (ou expressão, com as palavras em ordem) aparece, com flexões regulares.

    Formas irregulares (`gave`/`give`) não são reconhecidas aqui — a avaliação do LLM
    (`usa_palavra_alvo`) é quem decide de fato (ver ADR-0004).
    """
    tokens = normalizar(texto).split()
    posicao = 0
    for parte in normalizar(palavra).split():
        formas = _flexoes(parte)
        try:
            achado = next(i for i in range(posicao, len(tokens)) if tokens[i] in formas)
        except StopIteration:
            return False
        posicao = achado + 1
    return bool(normalizar(palavra))


_PALAVRA = re.compile(r"[^\W_]+(?:'[^\W_]+)*")


def marcar_alvo(frase: str, palavra: str) -> str | None:
    """Coloca [[ ]] na palavra-alvo (com flexões regulares) de uma frase que veio sem marcação.
    Para expressões, marca do primeiro ao último termo achado. `None` se não a encontra."""
    tokens = list(_PALAVRA.finditer(frase))
    posicao = 0
    achados: list[re.Match[str]] = []
    for parte in normalizar(palavra).split():
        formas = _flexoes(parte)
        indice = next(
            (i for i in range(posicao, len(tokens)) if normalizar(tokens[i].group()) in formas),
            None,
        )
        if indice is None:
            return None
        achados.append(tokens[indice])
        posicao = indice + 1
    if not achados:
        return None
    inicio, fim = achados[0].start(), achados[-1].end()
    return f"{frase[:inicio]}[[{frase[inicio:fim]}]]{frase[fim:]}"
