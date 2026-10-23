# ADR-0056: Ranking de engajamento para admins (`/ranking`)

- **Status:** Aceito
- **Data:** 2026-10-22

## Contexto

No piloto do curso, os admins precisam saber quais alunos e quais turmas estão mais engajados, e
tirar feedback disso. O bot já guarda cada resposta da revisão diária e do desafio semanal em
`espacos/{grupo}/respostas/` (`autor_id`, `qualidade`, `criado_em`), mas só o `!group` as lia.

## Decisão

1. **Interação** = uma resposta registrada na revisão diária ou no desafio semanal. Adicionar palavra
   não conta. `Resposta` ganha `tipo: "diaria" | "semanal" | None` (documentos antigos ficam `None`).
2. **`/ranking [meses]`** no privado, só para admin do bot e dono (para os demais vale como comando
   desconhecido, como `/groups`). Padrão 6 meses; aceita 1 a 24.
3. Três mensagens: **top 20 alunos** (todas as turmas), **top 10 turmas** e **top 3 de cada turma**.
4. **Alunos:** ordenados por interações; desempate por dias ativos e depois por respostas aceitas
   (`qualidade != de_novo`). Quem está em duas turmas soma. A linha mostra daily, weekly e dias ativos.
5. **Turmas:** ordenadas por **interações por aluno matriculado** (membros que não são staff), com o
   total e a participação (`ativos/matriculados`) ao lado, para turma pequena e grande competirem
   de forma justa.
6. **Staff** (dono, admins, professores globais ou locais) fica fora de tudo (ADR-0055).
7. Sem nome do WhatsApp, a pessoa aparece como `…1234` (4 últimos dígitos); nunca o número inteiro.
8. A lógica é pura (`app/domain/ranking.py`); `Repository.listar_respostas(desde=)` filtra pelo
   período no Firestore (índice de campo único, automático).

## Alternativas consideradas

- **Pontos ponderados por tipo de ação** — descartada pelo usuário: "interação" é só daily/weekly;
  fica fácil de explicar e de auditar.
- **Ordenar turmas pelo total** — descartada: favorece turma grande.
- **Mostrar o ranking aos alunos** — descartada para o piloto: o ranking é ferramenta de
  acompanhamento do admin; exposição geral pode desmotivar quem está embaixo.

## Consequências

- Respostas anteriores ao M58 contam, mas sem a quebra daily/weekly (`tipo=None`): aparecem no total.
- Cada `/ranking` lê as respostas do período de todos os grupos ativos; no volume do piloto é
  irrisório, mas cresce com o número de turmas e meses.
- Dias ativos usam o fuso de São Paulo.
