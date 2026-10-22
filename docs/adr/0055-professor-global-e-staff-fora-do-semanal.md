# ADR-0055: Professor global e staff fora do desafio semanal

- **Status:** Aceito
- **Data:** 2026-10-22

## Contexto

O piloto no curso de inglês terá professores que usam o bot (adicionam palavras, pulam perguntas) mas
não participam das dinâmicas e não devem ser marcados no desafio semanal. Até aqui o papel era por
grupo (`espacos/{grupo}/membros/{numero}.papel`, ADR-0019): um professor em 5 turmas precisava ser
marcado nas 5, e qualquer professor da turma podia promover outros. Os admins do bot (quem ativa os
grupos) também eram marcados como alunos.

## Decisão

1. **Professor global:** nova coleção raiz `professores/{numero}` (`adicionado_em`, `adicionado_por`),
   no molde de `admins/`. `!teacher` grava nela e o papel vale em **todos** os grupos, sem repetir o
   comando; `!student` remove dela (e volta o papel local para `aluno`).
2. **Quem promove:** só **admin do bot ou o dono** (era "qualquer professor da turma ou o dono").
   Professor e aluno recebem a ajuda do grupo, como qualquer comando desconhecido.
3. **Staff** = dono, admin do bot, professor global ou `Membro.papel == "professor"` (o papel local
   antigo continua valendo, sem migração). Staff **nunca é marcado** no desafio semanal
   (`review.alunos_elegiveis`) e aparece como `teacher` no `!group`.
4. **O que o professor continua podendo:** tudo que o aluno faz, mais `!level` (professor da turma ou
   global, ou o dono). Não ativa grupos nem muda `!daily`/`!weekly` (continuam de admin e dono).
5. **Privado:** `/teachers`, `/teachers add N` e `/teachers remove N` (admin e dono), escondidos do
   `/help`, para cadastrar um professor antes de ele escrever em algum grupo.
6. `Banco` ganha `listar_professores`/`adicionar_professor`/`remover_professor`; o Firestore usa o
   cache curto de 60 s do ADR-0046, invalidado nas mutações. `Deps` ganha `eh_staff` e `banco`.

## Alternativas consideradas

- **Só o papel por grupo (status quo)** — descartada: o professor teria de ser marcado em cada turma.
- **Campo `professor` no perfil de usuário** — descartada: não existe perfil global de pessoa em
  grupo; a coleção por número é o que `admins/` já faz.
- **Admin como `aluno` quando for aluno de alguma turma** — descartada: admin do bot é staff; quem for
  aluno e admin ao mesmo tempo é um caso que o piloto não tem.

## Consequências

- Um professor promovido em uma turma deixa de ser marcado em todas as outras, de imediato.
- `!student` num grupo tira o professor de todos os grupos (é o mesmo cadastro).
- Professor global não aparece como membro de um grupo até escrever nele; a exclusão do semanal vale
  desde já porque `alunos_elegiveis` checa o cadastro global pelo número.
- Nova coleção `professores/` no Firestore (spec 7.1) e no snapshot de métricas fica para depois.
