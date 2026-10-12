# ADR-0042: Teto de tokens de saída e nível de raciocínio mínimo no Gemini, com recuo automático

- **Status:** Aceito
- **Data:** 2026-10-12

## Contexto

As chamadas ao Gemini não tinham `max_output_tokens` nem `thinking_config`. Nos modelos 3.x o raciocínio
("thinking") vem ligado por padrão, com nível que depende do modelo, e **é cobrado como saída**
(US$ 1,50 por 1M no `gemini-3.1-flash-lite`). Uma tarefa que precisa de 300 tokens de resposta pode
gastar vários milhares pensando, e uma injeção de prompt ("escreva 5.000 palavras no feedback") inflava a
saída sem teto. A resposta de todas as tarefas é um JSON pequeno com schema.

## Decisão

1. **Teto de saída:** `max_output_tokens=2048` nas tarefas do tutor (o maior caso, 10 perguntas do
   desafio semanal com explicação em português, cabe com folga) e `1024` na transcrição (60 s de fala
   são ~250 tokens). O teto inclui o raciocínio. Resposta cortada vira JSON inválido, cai na validação
   existente (uma nova tentativa, depois `LLMError`).
2. **Raciocínio mínimo:** `GEMINI_THINKING_LEVEL`, padrão `minimal` (`low`/`medium`/`high` também
   valem; vazio deixa o padrão do modelo). As tarefas são extração/classificação/avaliação curtas com
   schema; não precisam de raciocínio longo. **Ainda não medido:** rodar `make evals` (custa centavos)
   com e sem o nível, para confirmar que a qualidade da avaliação de frases se mantém.
3. **Recuo automático:** cada modelo 3.x aceita um conjunto de níveis e o ID do modelo é configurável.
   Se a API responder 400 com o nível configurado, o provider refaz a chamada sem `thinking_config`,
   desliga o ajuste naquele processo e registra um aviso. A IA nunca cai por causa deste ajuste.
4. Vale para o tutor e para o transcritor; o provedor Anthropic já tinha `max_tokens`.

## Alternativas consideradas

- **`thinking_budget=0`** — descartada: nos Gemini 3 o controle é `thinking_level`, e a doc não
  garante desligar o raciocínio.
- **Teto único menor (512)** — descartada: cortaria o desafio semanal e os cartões com 4 sentidos.
- **Nível fixo no código, sem recuo** — descartada: uma troca de `GEMINI_MODEL` para um modelo que não
  aceite `minimal` derrubaria todo o bot.

## Consequências

- O custo de saída fica previsível: no pior caso 2.048 tokens por chamada (US$ 0,003).
- Qualidade de avaliação pode mudar com `minimal`; o ajuste é por variável de ambiente, sem deploy de
  código.
