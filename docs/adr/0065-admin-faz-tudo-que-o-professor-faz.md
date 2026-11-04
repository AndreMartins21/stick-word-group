# ADR-0065: Admin do bot faz tudo o que um professor faz

- **Status:** Aceito
- **Data:** 2026-11-04

## Contexto

O ADR-0031 deu a mudança do nível da turma (`!level <nível>`) só ao **professor da turma ou ao dono**.
Depois, o M57 (ADR-0055) criou o admin do bot como quem gerencia os papéis (`!teacher`/`!student`,
`/teachers`), e `!daily`/`!weekly` já eram de admin ou dono. Ficou uma inversão: um admin pode tornar
alguém professor, mas não pode, ele mesmo, mudar o nível da turma — teria de se promover a professor
primeiro (o que ainda o faria ser tratado como professor no `!group`).

## Decisão

1. **Admin do bot ⊇ professor.** Toda permissão de professor vale também para admin do bot e para o
   dono. A checagem fica num lugar só, `grupo._pode_gerir` (professor da turma, professor global,
   admin ou dono).
2. **`!level <nível>` no grupo:** professor, admin do bot ou dono mudam; aluno recebe
   `nivel_so_professor` ("Only a teacher or an admin can change the class's level."), e o nível não
   muda. Sem argumento, qualquer membro continua vendo o nível.
3. A parte do ADR-0031 sobre a opção 5 do menu ("Don't save") continua valendo e é reafirmada aqui;
   o ADR-0031 fica como substituído por este.

## Alternativas consideradas

- **Admin se promove a professor com `!teacher`.** Descartada: funciona, mas é um passo a mais sem
  ganho, e mistura os papéis (o admin passaria a aparecer como professor no `!group`).
- **Manter professor e admin como papéis disjuntos.** Descartada: o admin já é quem nomeia os
  professores; não faz sentido ter menos poder que eles.

## Consequências

- Qualquer nova permissão de professor deve passar por `_pode_gerir`, para o admin herdá-la.
- O texto da recusa do `!level` muda (cita admin).
