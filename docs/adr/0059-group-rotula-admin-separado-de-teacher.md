# ADR-0059: `!group` mostra o admin como `admin`, não como `teacher`

- **Status:** Aceito
- **Data:** 2026-10-23

## Contexto

Admin e dono são staff (ADR-0055): nunca são marcados no desafio semanal. O `!group` rotulava todo
staff como `teacher`. Quem testou `!teacher` seguido de `!student` num número que também era admin do
bot via a resposta "is now a student" e, logo depois, o `!group` ainda dizendo `teacher`: o rebaixamento
(ADR-0058) funcionava, mas o papel de admin não é algo que `!student` possa tirar, e o rótulo
escondia isso.

## Decisão

1. `Deps.eh_admin` (dono ou admin do bot) é passado pelo `Router`; o `!group` rotula esses números como
   `admin`. Professor (global ou local) segue como `teacher`; o resto, `student`.
2. `!student` em quem é admin responde que a pessoa deixou de ser professor mas continua admin (e por
   isso continua fora da diária e do semanal), em vez de "is now a student".
3. Nada muda em quem é staff: admin segue fora do semanal e do ranking de alunos.

## Alternativas consideradas

- **Deixar o admin como `teacher`** — descartada: foi o que causou a confusão relatada.
- **Admin que vira aluno de uma turma passa a ser marcado no semanal** — descartada: contraria a
  decisão do ADR-0055 (admin é staff); fica registrado em `docs/decisoes-para-revisar.md`.

## Consequências

- O `!group` mostra três rótulos (`admin`, `teacher`, `student`); é o único lugar que os exibe.
- Para tirar alguém do papel de admin continua valendo `/admin remove` no privado.
