# ADR-0058: Rebaixar um professor limpa o papel em todos os grupos

- **Status:** Aceito
- **Data:** 2026-10-23

## Contexto

O `!teacher` (ADR-0055) grava o papel em dois lugares: o cadastro global `professores/` e o
`Membro.papel` do grupo em que foi dito. Rebaixar só limpava o global e o grupo atual: `/teachers
remove` no privado (e `!student` em outro grupo) deixavam `Membro.papel = "professor"` nos grupos, e o
`!group` seguia mostrando a pessoa como `teacher`.

## Decisão

1. `app/flows/papeis.py:rebaixar_em_todos(banco, numero)` tira o número de `professores/` e volta o
   `Membro.papel` a `aluno` em **todos os grupos** (`Banco.listar_espacos`, tipo `grupo`), tolerando o
   nono dígito.
2. É usado por `!student`, por `!teacher` em quem já é professor (ADR-0057) e por `/teachers remove`
   e `/teachers N` no privado.

## Alternativas consideradas

- **Não gravar o papel local ao promover (só o global)** — descartada: o papel local do ADR-0019
  existe em dados antigos e continuaria a aparecer; limpar dos dois lados resolve ambos.
- **`!group` ignorar o papel local** — descartada: esconderia dado inconsistente em vez de corrigi-lo.

## Consequências

- Rebaixar lê a lista de espaços (uma consulta, como o snapshot de métricas); só acontece quando um
  admin rebaixa alguém.
- Só enxerga grupos cujo documento `espacos/{id}` tem campos (todo grupo que já usou o bot).
