# ADR-0027: Pronúncia automática do termo em cada card de revisão, só no privado

- **Status:** Substituído por ADR-0062
- **Data:** 2026-09-27

## Contexto

A ADR-0026 (M25) tornou automática a pronúncia ao explicar uma palavra. O pedido seguinte foi
estender o mesmo princípio à revisão espaçada (seção 5.7): já que o áudio de cada termo já é
sintetizado e cacheado desde a primeira vez que a palavra foi explicada, mandar a voz do termo em
cada card de revisão custa pouco e ajuda a fixar a pronúncia bem na hora em que o aluno está
tentando lembrar da palavra — sem a frase de exemplo, porque ali o objetivo é o som do termo, não
reler o card inteiro de novo.

Implementar isso ingenuamente em `_mostrar_proxima` (chamado tanto no privado quanto no grupo)
quebrou um teste do simulador de grupo: `test_timeout_no_simulador_repassa_o_card_e_depois_fecha`.
A causa é o orçamento de "3 mensagens seguidas sem resposta" (seção 5.6, `Conversa`, por espaço):
num cenário de repasse por timeout, o grupo já soma **card (1) + repasse (2) + resumo de
fechamento (3)** — exatamente o teto. Um áudio a mais nesse caminho estoura para 4, e a `Conversa`
descarta o envio excedente **em silêncio** — nesse caso, justo o resumo que fecha a rodada.

## Decisão

**A pronúncia automática do termo em cada card só roda no privado.** No grupo, `_mostrar_proxima`
não chama `pronuncia.ouvir` — o card, o repasse (quando a pessoa marcada não responde a tempo) e o
resumo de fechamento continuam sendo as únicas três mensagens possíveis por rodízio, como antes
desta mudança.

`pronuncia.ouvir` ganha o parâmetro `com_frase` (`True` por padrão): `com_frase=False` pula a busca
da frase e manda só a voz do termo. A chamada da revisão usa `anunciar=False, com_frase=False`.

## Alternativas consideradas

- **Mandar áudio também no grupo** — foi a primeira tentativa; um teste do simulador (relógio
  controlado, sem depender de sorte) pegou o resumo de fechamento sendo descartado em silêncio
  depois de um repasse por timeout. É exatamente o tipo de falha silenciosa que a spec (seção 5.6)
  tenta evitar ao existir o limite de mensagens — não dá pra "gastar" um dos três slots com um
  extra opcional (áudio) que pode custar um obrigatório (o fechamento da rodada).
- **Aumentar `MAX_MENSAGENS_SEGUIDAS` para caber o áudio** — mexeria numa proteção geral (spec
  §5.6) por causa de um caso específico (revisão em grupo), com efeito colateral em todo o resto do
  bot que depende desse limite para não se comportar como spam.
- **Áudio só no card, nunca no repasse/fechamento** (differenciar por tipo de mensagem) — resolveria
  o estouro específico do timeout, mas ainda deixaria o caso comum (grupo sem timeout: card + card
  seguinte, sem folga nenhuma) mais apertado, por um ganho que já existe no privado; não parecia
  valer a complexidade.

## Consequências

- Fácil: nenhuma mudança em `Conversa` nem no limite de mensagens; o comportamento de grupo (já
  testado e em produção desde o M17) fica intacto.
- Difícil: a experiência de revisão fica diferente entre privado (com áudio automático) e grupo
  (sem) — aceitável, já que o grupo tem seu próprio ritmo (rodízio, menções, timeout) bem mais
  apertado no orçamento de mensagens do que uma conversa a sós.
- Revisitar se: o grupo ganhar um jeito de mandar mensagens fora do limite de 3 (por exemplo, um
  canal separado só para áudio) ou se o limite em si for revisto.
