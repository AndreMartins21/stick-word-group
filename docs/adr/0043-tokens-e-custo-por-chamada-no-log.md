# ADR-0043: Tokens e custo estimado por chamada de IA nos logs, e Budget da GCP só para alertar

- **Status:** Aceito
- **Data:** 2026-10-12

## Contexto

Até aqui o custo da IA era uma estimativa de cabeça. O evento `llm_chamada` (ADR-0028) tinha só método,
modelo, ok e latência; a transcrição (ADR-0037) não emitia nada. Sem tokens por chamada não há como
saber quanto cada grupo custa, nem como calibrar o orçamento diário (ADR-0044) ou os limites (ADR-0041).
Do lado da GCP, nada avisava de um gasto fora do esperado.

## Decisão

1. **Uso por chamada:** o provider soma o `usage_metadata` de cada resposta (entrada, saída,
   raciocínio) num acumulador da chamada em curso (`services/custo.py`, um `ContextVar`: não muda o
   `Protocol` do provider e não mistura chamadas de threads diferentes). `llm_chamada` passa a levar
   `tokens_entrada`, `tokens_saida`, `tokens_thinking` e `custo_usd`, **somando as tentativas** (a
   nova tentativa por validação também custa).
2. **Transcrição:** novo evento `transcricao_chamada` (`ok`, `modelo`, `tokens_audio`, `tokens_saida`,
   `tokens_thinking`, `custo_usd`, `latencia_ms`).
3. **Preço:** tabela pública do Gemini em USD por 1M de tokens (flash-lite: 0,25 entrada, 0,50 áudio,
   1,50 saída; raciocínio cobrado como saída). Modelo desconhecido usa o preço mais alto da família:
   errar para cima mantém o orçamento diário conservador. A tabela fica em código porque preço de
   modelo muda por troca de modelo, que já é um deploy de configuração.
4. **Sem texto nem número no evento:** só contagens (lista branca do ADR-0028).
5. **Budget da GCP:** `infra/setup_orcamento.sh` (idempotente, `DRY_RUN`, pergunta antes) cria o
   Budget `vocabot-mensal` (padrão US$ 30/mês, `ORCAMENTO_MENSAL_USD`) com alertas em 50%, 90% e
   100%. **Só alerta**: o corte do gasto da IA é o orçamento diário do bot (ADR-0044); o Budget cobre o
   projeto inteiro (VM, IP, Firestore, TTS). Quem roda o script é o dono (CLAUDE.md, regra 2).

## Alternativas consideradas

- **Pegar o custo do export de billing no BigQuery** — complementar, não substituto: chega com atraso
  de horas e não separa por grupo; o log tem tokens por chamada e o `espaco` do evento.
- **Mudar o retorno de `LLMProvider.gerar` para `(texto, uso)`** — descartada: quebra o `Protocol`, os
  fakes e os testes para ganhar o que o `ContextVar` já dá.
- **Budget que desliga o faturamento** — descartada: desligar o faturamento derruba o projeto
  inteiro (VM, WhatsApp pareado); o corte fino é dentro do bot.

## Consequências

- O painel do M28/M30 pode somar `custo_usd` por dia e por `espaco` (quando o evento passar a levar o
  espaço) para substituir a estimativa por dado real.
- O custo logado é uma **estimativa** com a tabela pública; a fatura da GCP é a verdade.
- Trocar de modelo exige conferir `_PRECOS` em `services/custo.py` (modelo novo cai no preço alto).
