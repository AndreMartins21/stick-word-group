# ADR-0031: `!level` no grupo (só professor ou dono muda) e opção 5 do menu renomeada para "Don't save"

- **Status:** Substituído por ADR-0065
- **Data:** 2026-09-29

## Contexto

1. **Nível da turma sem dono.** O perfil do grupo nasce na primeira mensagem com o nível padrão da
   configuração (`USER_LEVEL`), e o ADR-0019 deixou `!level` fora do conjunto fechado de comandos do
   grupo. Resultado: não havia como acertar o nível de uma turma sem mexer no banco, e o nível
   alimenta todos os prompts da turma (explicação, sinônimos, prática, revisão).
2. **Nome da opção 5.** "Ignore this word, try another" (ADR-0021) descrevia mal o que a opção faz
   — descarta a palavra sem salvar — e o "try another" sugeria uma troca que o bot não faz.

## Decisão

1. **`!level` entra no conjunto fechado do grupo.** Sem argumento, qualquer membro vê o nível da
   turma; com argumento (`!level B1-B2`), só um **professor da turma ou o dono** (a mesma regra do
   `!teacher`/`!student`) o muda. Para um aluno a resposta é `nivel_so_professor`, e o nível não
   muda. Como o comando aparece no `!help`, a recusa é explícita (diferente de `!teacher`, que é
   escondido e responde com a ajuda).
2. **Um só código para privado e grupo.** `commands.definir_nivel` (antes `_nivel`) atende `/level` e
   `!level`; a autorização fica em `grupo._nivel`, e as mensagens citam o prefixo do espaço.
3. **A opção 5 do menu passa a se chamar "Don't save"** (`Acao.IGNORAR`, comportamento do ADR-0021
   inalterado: apaga a entrada só se ela ainda é o rascunho desta captura).

## Alternativas consideradas

- **Só o dono muda o nível.** Descartada: o professor é quem conhece a turma, e o dono nem sempre
  está no grupo.
- **Qualquer membro muda.** Descartada: um aluno poderia baixar ou subir o nível de todos.
- **Esconder `!level` do `!help`, como `!teacher`.** Descartada: ver o nível é útil a todos e o
  comando de mudança se descobre pela própria resposta de `!level`.
- **Nível por aluno dentro do grupo.** Descartada: o perfil é por espaço (ADR-0017); mudaria o
  modelo de dados por um ganho pequeno.

## Consequências

- Complementa o ADR-0019 (o conjunto fechado ganha `level`) e ajusta o texto do ADR-0021 (só o rótulo
  da opção; a regra segue valendo). Ambos seguem Aceitos.
- A ajuda do grupo cita `!level` mas não o papel de professor, para manter `!teacher` escondido.
- O nível vale para as próximas chamadas de IA; cards já gerados não são refeitos.
