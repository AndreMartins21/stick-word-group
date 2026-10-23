# Decisões para revisar (piloto do curso, 2026-10-22/23)

Decisões que tomei sozinho enquanto você estava fora. Cada uma tem ADR; aqui só o resumo e como desfazer.

## Entregue (todo em produção)

| Marco | PR | O quê |
|---|---|---|
| M57 | #54 | Professor global (`professores/`), `!teacher` só de admin/dono, staff fora do weekly, `/teachers` (ADR-0055) |
| M58 | #55 | `/ranking [meses]` para admins (ADR-0056) |
| M59 | #56 | `!teacher` alterna; `/teachers N` e `/teacher N` valem (ADR-0057) |
| M60 | #57 | Bug do `/group`: rebaixar limpa o papel em todos os grupos (ADR-0058) |
| M61 | — | `/group` mostra admin/dono como `admin` (não `teacher`) e `!student` neles avisa que continuam admin (ADR-0059) |

## Decisões minhas (reveja)

1. **Admin do bot é staff** (não é marcado no weekly nem entra no ranking de alunos). Foi sua resposta, mas
   um admin que também é aluno de uma turma fica de fora dela. Para mudar: tirar `eh_admin` de
   `Router._eh_staff` e de `admin._ranking`.
2. **Respostas anteriores ao M58 não têm `tipo`**: entram no total do ranking, mas não na quebra
   "daily X · weekly Y".
3. **Turmas ordenadas por interações por aluno matriculado** (total e `ativos/matriculados` ao lado),
   conforme sua escolha. Matriculado = membro cadastrado que não é staff; quem nunca escreveu no
   grupo não está cadastrado e não conta no denominador.
4. **Dias ativos** usam o fuso de São Paulo.
5. **Rebaixar lê todos os espaços** (`listar_espacos`) para limpar o papel local. Só acontece quando um
   admin rebaixa alguém; o custo é uma leitura da coleção `espacos`.
6. **`!teacher` repetido rebaixa** (ADR-0057). Um engano de digitação tira o professor de todos os grupos.

## Sobre "as outras modificações do ranking"

Reli o que você mencionou para o ranking: top 20 alunos, top 10 turmas, alunos mais engajados por
turma, padrão de 6 meses e `/ranking N`. **Tudo isso já está implementado (M58).** O restante eram
sugestões minhas, que você não pediu, então **não implementei**:

- Top 3 da própria turma postado no grupo uma vez por mês (leaderboard local motiva mais que global).
- Taxa de acerto por aluno (hoje o ranking só tem `aceitas` como desempate).
- Alerta de turma sem resposta há N rodadas (a pausa existe, o aviso ao admin não).
- Incluir `professores/` e `Resposta.tipo` no snapshot de métricas do BigQuery.

Se quiser algum, diga qual e eu faço (cada um vira um marco com ADR).

## Para validar no WhatsApp

1. `!teacher @prof` num grupo; `/group` mostra `teacher`; no privado `/teachers remove N`; `/group`
   em **todos** os grupos mostra `student`.
2. `/ranking`, `/ranking 1`, `/ranking 0` (uso) e `/ranking` de uma conta que não é admin.
3. Se o Firestore pedir índice na primeira consulta do `/ranking`, o erro traz o link para criá-lo.

## Custo estimado (premissa, não medido)

~US$ 0,18 de IA por grupo/mês (faixa 0,10–0,40) mais ~US$ 4 fixos (IP externo e snapshots): ~US$ 5/mês
com 5 grupos, ~US$ 8 com 20, ~US$ 13 com 50. Os tokens por chamada vêm do tamanho dos prompts; confira
com `uso/{dia}.espacos` depois de duas semanas de piloto.
