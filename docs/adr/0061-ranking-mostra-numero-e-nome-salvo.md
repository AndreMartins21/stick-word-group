# ADR-0061: O PDF do ranking mostra o número e o nome salvo do aluno

- **Status:** Aceito
- **Data:** 2026-10-23

## Contexto

O ADR-0056 (decisão 7) mostrava só `…1234` para quem não tinha nome do WhatsApp, "nunca o número
inteiro". Com o PDF (ADR-0060), o admin não consegue saber quem é um aluno sem nome. As colunas
Daily e Weekly também saíam zeradas, porque respostas anteriores ao M58 não têm `tipo`.

## Decisão

1. O PDF do `/ranking` mostra duas colunas por aluno: o **nome salvo** (`Membro.nome`, ou "—" se o bot
   nunca o recebeu) e o **número completo** (`+5531999998888`). Vale na tabela de alunos e nos
   destaques por turma. Quem está em duas turmas fica com o nome que alguma delas conhece.
2. Isso **substitui a decisão 7 do ADR-0056**. O PDF só é enviado ao admin ou ao dono, no privado.
3. O PDF deixa de ter as colunas Daily e Weekly. O Total (daily + weekly) e os dias ativos ficam.
4. Logs continuam sem número completo (CLAUDE.md): a mudança vale só para o arquivo.

## Alternativas consideradas

- **Manter `…1234`** — descartada: não identifica o aluno.
- **Só o número, sem nome** — descartada: o nome ajuda a reconhecer quem tem nome.

## Consequências

- O PDF contém dados pessoais: quem o recebe deve tratá-lo como tal.
- `LinhaAluno.nome` passa a ser vazio (não mais `…1234`) quando não há nome salvo.
