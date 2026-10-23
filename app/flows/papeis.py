"""Rebaixar um professor (M60, ADR-0058): `!student` e `/teachers remove` valem para todos os grupos.

`!teacher` grava o papel no cadastro global (`professores/`) **e** no cadastro do grupo em que foi
dito (`Membro.papel`); por isso rebaixar tem de limpar os dois lados, em todos os grupos, senão o
`!group` segue mostrando a pessoa como professor.
"""

from __future__ import annotations

from app.channel.parser import numero_esta_na_lista
from app.repo.base import Banco


def rebaixar_em_todos(banco: Banco, numero: str) -> bool:
    """Tira `numero` do cadastro global e volta o papel local dele a `aluno` em todos os grupos.
    Devolve `True` se algo mudou. Tolera o nono dígito."""
    mudou = False
    for existente in [n for n in banco.listar_professores() if numero_esta_na_lista(numero, [n])]:
        mudou = banco.remover_professor(existente) or mudou
    for espaco in banco.listar_espacos():
        if espaco.tipo != "grupo":
            continue
        repo = banco.do_espaco(espaco.id)
        for chave, membro in repo.listar_membros():
            if membro.papel == "professor" and numero_esta_na_lista(numero, [chave]):
                repo.salvar_membro(chave, membro.model_copy(update={"papel": "aluno"}))
                mudou = True
    return mudou
