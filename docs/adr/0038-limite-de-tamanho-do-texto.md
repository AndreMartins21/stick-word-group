# ADR-0038: Limite de tamanho do texto que chega à IA: recusar, não truncar

- **Status:** Aceito
- **Data:** 2026-10-12

## Contexto

Nada limitava o tamanho do texto que o bot manda ao Gemini. O WhatsApp aceita mensagens de ~65 mil
caracteres (~16 mil tokens): custa centavos sozinha, mas multiplicada por um flood vira conta sem
teto, e gasta memória e latência na fila do chat (ADR-0006). Nenhuma entrada legítima do bot (palavra,
`palavra | contexto`, frase de prática, resposta de revisão ou do desafio semanal) passa de algumas
centenas de caracteres.

## Decisão

1. **Teto único `MAX_CARACTERES` (padrão 500)** para o texto de uma mensagem que seria entregue à
   máquina de estados / IA, no privado e no grupo. Configurável por variável de ambiente (vazio usa o
   padrão, como os demais numéricos).
2. **Recusar, não truncar:** truncar mudaria a frase que a IA vai julgar e o aluno não saberia. O bot
   responde uma mensagem curta (`messages.texto_longo_demais`) e a sessão fica como estava.
3. **Onde:** no início de `Router.processar`, depois de decidir que a mensagem é para o bot (no grupo,
   conversa entre pessoas continua ignorada, sem resposta) e **antes** de tocar no banco ou na IA. Isso
   cobre o privado, o grupo e a transcrição de áudio (que entra como mensagem marcada).
4. Comandos sem IA (`!list`, `!help`) também ficam sob o teto: são curtos, e uma regra só é mais
   simples de explicar e de testar.

## Alternativas consideradas

- **Truncar em Python e seguir** — descartada: avalia uma frase que o aluno não escreveu.
- **Limite no webhook (`main.py`)** — descartada: o webhook não sabe se a mensagem é para o bot
  (grupo) sem ler o payload inteiro; o roteador já sabe e é onde o aviso sai com o ritmo humano.
- **Limite em tokens** — descartada: exige chamar o tokenizador; caracteres bastam para o fim de
  proteger custo.

## Consequências

- Uma mensagem legítima acima do teto precisa ser dividida; o texto do aviso diz o máximo.
- O teto sozinho **não** limita o volume (flood de mensagens curtas): isso é o rate limit (ADR-0040).
