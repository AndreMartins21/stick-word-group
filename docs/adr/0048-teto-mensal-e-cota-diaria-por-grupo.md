# ADR-0048: Teto mensal de IA e cota diária por grupo, com o custo atribuído ao espaço

- **Status:** Aceito
- **Data:** 2026-10-12

## Contexto

O orçamento diário (ADR-0044) é global: um dia de US$ 5 vira até US$ 150 em 30 dias, e um único grupo
ruidoso (ou abusivo) pode consumir o dia de **todos** os outros. O Budget da GCP (ADR-0043) só avisa,
com atraso. Faltavam um teto por mês e uma divisão por grupo, os dois dentro do bot, sem depender do
faturamento (a alternativa de um gateway LiteLLM foi avaliada e descartada: ver conversa de 2026-10-12).

## Decisão

1. **Atribuição do custo ao espaço:** `custo.no_espaco(chat_id)` (um `ContextVar`) envolve o
   processamento de uma mensagem, os lembretes do agendador e a transcrição; o observador do custo
   recebe `(usd, espaco)`. Threads herdam o contexto, então as chamadas síncronas de IA contam no chat
   certo sem mudar nenhuma assinatura.
2. **Cota diária por grupo** (`COTA_DIARIA_POR_GRUPO_USD`, padrão **US$ 1**, ~20% do dia): ao
   estourar, **só aquele grupo** é pausado até amanhã. O grupo recebe um aviso por dia (`PAUSA_DO_GRUPO`),
   o dono recebe uma DM por grupo por dia (com o id do grupo e a dica de `!deactivate`) e as revisões
   e desafios dele não disparam. Privados não têm cota (já têm o limite por pessoa, ADR-0041). Um grupo
   típico gasta ~US$ 0,03 por dia: a cota só pega abuso ou erro.
3. **Teto mensal** (`ORCAMENTO_MENSAL_USD`, padrão **US$ 50**): a soma dos dias do mês (lida dos
   documentos `uso/{dia}` na virada do dia) mais o dia corrente. Ao atingir, pausa a IA de todos até o
   mês virar, com o aviso `PAUSA_DO_MES` por chat e uma DM ao dono. Tem precedência sobre o diário.
4. **Persistência:** a mesma escrita em lote do total (ADR-0044) leva `espacos.{chat: usd}` no
   documento do dia. O id do chat é gravado sem os pontos (`@g_us`) para não virar separador de
   caminho. Um restart recarrega tudo e **não** reenvia avisos já dados.
5. **Dono isento** como no resto: nunca é pausado, para conseguir diagnosticar.

## Alternativas consideradas

- **LiteLLM como gateway com budgets** — descartada: Postgres e ~1-2 GB de RAM numa VM de 1 GB, mais
  uma superfície de segurança (houve comprometimento do pacote em março de 2026), para um problema que
  um contador de 150 linhas resolve.
- **Cota por pessoa em dólares** — descartada: o limite por pessoa em mensagens (ADR-0041) já cobre,
  e o custo por pessoa em grupo exigiria atribuir ao autor, não ao grupo.
- **Cota proporcional ao número de membros** — descartada: o bot não conhece o tamanho do grupo de
  forma barata e um valor fixo é mais fácil de explicar.

## Consequências

- Na virada do dia o bot lê até 31 documentos pequenos para somar o mês: dentro da cota gratuita.
- O mês é do fuso do aluno; o custo é a mesma estimativa dos ADRs 0043 e 0044.
- Um grupo legítimo muito grande pode precisar de uma cota maior: variável de ambiente, sem código.
- O gasto por espaço fica disponível para o painel (M28/M30) por dia, no mesmo documento.
