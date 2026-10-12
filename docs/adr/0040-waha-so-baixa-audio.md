# ADR-0040: WAHA baixa só áudio: filtro de mimetype por prefixo e vida curta dos arquivos

- **Status:** Aceito
- **Data:** 2026-10-12

## Contexto

O WAHA baixa **toda** mídia de **todos** os chats para `/tmp/whatsapp-files` por padrão
(`WAHA_EVENTS_DOWNLOAD_MEDIA=true`, sem filtro). O bot participa de grupos de turma (inclusive
pendentes de ativação, onde fica 24 h) e as pessoas mandam vídeos, fotos e documentos que ele nunca
usa. Com o container do WAHA em 400 MB de memória e disco de 30 GB numa VM e2-micro, um vídeo grande
ou uma enxurrada de mídia é risco de OOM e de disco cheio, derrubando o bot inteiro.

## Decisão

1. `WAHA_EVENTS_DOWNLOAD_MEDIA_MIMETYPES=audio` no compose. A doc do WAHA descreve o filtro como
   **prefixo** ("use a prefix, like `audio,image`"), então `audio` casa `audio/ogg; codecs=opus`
   (nota de voz) sem depender de o WhatsApp mandar o mimetype com ou sem parâmetros. O que não casa
   chega ao webhook com `hasMedia: true` e `media.url` nulo; o bot já ignora mídia que não é áudio no
   grupo e responde "não suportado" no privado, sem tocar na URL.
2. `WHATSAPP_FILES_LIFETIME=180` explícito (era o padrão): o arquivo some em 3 minutos, o bastante
   para o bot baixar e transcrever.
3. A API continua com `WAHA_API_DOWNLOAD_MEDIA` padrão: o bot nunca pede mídia por ela.

## Alternativas consideradas

- **`WAHA_EVENTS_DOWNLOAD_MEDIA=false`** — descartada: quebra a transcrição de áudio (ADR-0037).
- **Filtro exato `audio/ogg,audio/mpeg`** — descartada: a doc não cobre mimetype com parâmetros
  (`; codecs=opus`) nem diz se o casamento é exato; o prefixo é o formato documentado.
- **Limpar `/tmp` por cron** — descartada: o próprio WAHA já faz a limpeza por tempo de vida.

## Consequências

- Se o WAHA aplicar o filtro de modo diferente do documentado, notas de voz chegam com `media.url`
  nulo e o bot responde que não conseguiu ouvir: o smoke manual do M42 (mandar uma nota de voz citando
  o bot) confirma. Reverter é apagar a linha do compose.
- Diferente de áudio, mídia de outros tipos nunca fica no disco da VM.
