# ADR-0053: Jitter de -20 a +20 min nos lembretes do grupo

- **Status:** Aceito
- **Data:** 2026-10-12

## Contexto

A revisão diária (padrão 19h) e o desafio semanal têm hora fixa por grupo. Com dezenas de grupos, todos
disparam no mesmo minuto: o número do bot manda uma rajada de mensagens e faz muitas chamadas de IA
ao mesmo tempo. A rajada é o padrão típico de automação que o WhatsApp penaliza, e o número não tem
plano B (auditoria de 2026-10-12, achado A7).

## Decisão

1. Cada grupo recebe a diária e o semanal de **-20 a +20 minutos** do horário configurado (em 19h,
   entre 18:40 e 19:20).
2. O deslocamento é **fixo por grupo e por tipo**: `SHA-256("{tipo}:{id do grupo}") % 41 - 20`, em
   minutos inteiros. O mesmo grupo recebe sempre no mesmo minuto, e a diária e o semanal de um grupo
   não andam juntos. (Não se usa `hash()`: ele muda a cada execução do Python.)
3. O jitter só desloca o minuto: o **dia** continua sendo o do horário configurado (dias úteis,
   `weekends on`, dia do semanal).
4. **Aviso ao usuário:** `!daily`, `!weekly` (inclusive na confirmação ao admin que muda o horário) e
   `!group` mostram "around 19:00 (may arrive up to 20 min earlier or later)". O "próximo horário"
   exibido já inclui o deslocamento.
5. `Agendador` recebe `jitter_do_grupo` (padrão `jitter_do_espaco`); os testes o fixam em zero.
6. O privado não muda: são lembretes de uma pessoa só.

## Alternativas consideradas

- **Aleatório a cada dia** — descartada: o horário "pularia" e ninguém saberia quando esperar; o fixo
  espalha igual.
- **Fila com espaçamento entre grupos (rate limit de saída)** — descartada: cobre só a rajada, não os
  picos de IA, e adiciona estado; o jitter resolve os dois sem estado.
- **Só espalhar quando houver muitos grupos** — descartada: uma regra única é mais simples e previsível.

## Consequências

- Quem vê a mensagem às 18:47 ou 19:12 não é um defeito: o aviso diz isso.
- Se o admin configura 19h às 18:50 e o deslocamento do grupo é -15, a primeira diária cai no dia
  seguinte (o horário de hoje já passou).
- Os horários já gravados em `proxima_diaria`/`proxima_semanal` mudam só no próximo cálculo; nenhuma
  migração.
