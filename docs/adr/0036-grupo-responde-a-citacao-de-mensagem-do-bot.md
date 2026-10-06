# ADR-0036: Grupo responde a quem cita uma mensagem do bot

- **Status:** Aceito
- **Data:** 2026-10-06

## Contexto

O ADR-0035 trocou o prefixo `!` pela marcação (`@bot`) como jeito de conversar com o bot no grupo. Na
prática, o gesto mais natural no WhatsApp é **responder (citar) a mensagem do bot**: quem lê o menu ou
o cartão puxa a mensagem e responde, sem marcar ninguém. O ADR-0035 descartou a citação por depender
de um campo pouco documentado; hoje o payload real já é lido (`contextInfo`, LID do bot via `me`) e a
doc do WAHA descreve `replyTo.participant`.

## Decisão

1. **Citar uma mensagem do bot é marcar o bot.** Em grupo ativo, uma mensagem de texto que **cita uma
   mensagem escrita pelo bot** (`replyTo.participant` ou `_data.Message.<tipo>.contextInfo.participant`
   junto de `stanzaID`/`quotedMessage`) é conversa com ele, igual a `@bot texto`: vai à mesma máquina
   de estados, sem comando.
2. **Reconhecimento da autoria** igual ao da marcação: `me` da sessão (número e LID), `BOT_NUMBER`
   (nono dígito à parte) ou, sem o `me`, o número que o LID resolve (cache `lids/`).
3. **Comando continua comando**: citar o bot e escrever `!list`/`/list` vale como o comando.
4. **Citar outra pessoa não chama o bot**, e citar sem texto (mídia) segue ignorado como antes.
   Sem marcação, comando nem citação ao bot, o grupo continua sendo conversa entre pessoas.

## Alternativas consideradas

- **Só marcação (`@bot`)** — mantida junto, não no lugar: as duas formas valem.
- **Ler toda resposta a qualquer mensagem** — descartada: privacidade; só o que é dirigido ao bot.

## Consequências

- Depende do formato do autor citado que o GOWS manda (`replyTo.participant` / `contextInfo.participant`).
  Se não bater com o `me`/`BOT_NUMBER`/LID, a citação não é reconhecida e o bot fica mudo; validar no
  WhatsApp real, como foi no M37.
- Uma consulta a `bot_ids()` (guardado depois do 1º sucesso) por mensagem citada; sem citação, sem custo.
