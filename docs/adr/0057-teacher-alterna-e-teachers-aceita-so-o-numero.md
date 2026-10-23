# ADR-0057: `!teacher` alterna o papel e `/teachers NÚMERO` basta

- **Status:** Aceito
- **Data:** 2026-10-23

## Contexto

No ADR-0055 o `!teacher` só promovia e o `!student` rebaixava. No uso real, o admin espera repetir o
mesmo comando para desfazer. No privado, `/teachers` só funcionava com `add`/`remove`, e quem digitava
`/teacher` (singular) ou `/teachers NÚMERO` recebia a resposta de comando desconhecido ou o uso.

## Decisão

1. `!teacher N` **alterna**: se a pessoa já é professor (global ou só deste grupo), vira aluno em
   todos os grupos; se não, vira professor em todos. `!student N` continua rebaixando sempre.
2. No privado, `/teachers N` e `/teacher N` (sem `add`/`remove`) alternam do mesmo jeito; `add` e
   `remove` seguem valendo. Texto com letras depois do comando (`/teachers fly 55...`) mostra o uso.
3. A permissão não muda: só admin do bot e dono (ADR-0055).

## Alternativas consideradas

- **Manter `!teacher` só promovendo** — descartada: obriga a lembrar de outro comando para desfazer.
- **Alternar também o `!student`** — descartada: `!student` em quem já é aluno não deveria promover.

## Consequências

- Repetir `!teacher` por engano rebaixa o professor; a resposta ("is now a student") deixa isso claro.
- O ADR-0055 continua valendo para o resto (cadastro global, staff fora do semanal).
