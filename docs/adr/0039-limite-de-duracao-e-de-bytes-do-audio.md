# ADR-0039: Áudio recusado pela duração declarada, antes de baixar, e download em streaming com teto de bytes

- **Status:** Aceito
- **Data:** 2026-10-12

## Contexto

O M39 (ADR-0037) recusava áudio acima de 3 MB, mas **depois** de baixar tudo para a memória (o
container do bot tem 300 MB) e sem olhar a duração, que o WhatsApp já informa no payload. Uma hora de
áudio custa pouco para transcrever (~US$ 0,08 com o `gemini-3.1-flash-lite`, 32 tokens por segundo), mas
o download inteiro, a transcrição gigante republicada no grupo e o volume em flood são o problema real.

## Decisão

1. **Duração antes de baixar:** `audioMessage.seconds` do payload (`MessagePayload.segundos_do_audio`)
   acima de `MAX_SEGUNDOS_AUDIO` (padrão **60**) recusa o áudio sem baixá-lo nem chamar o Gemini.
   60 s cabem em ~500 caracteres falados, o mesmo teto do texto (ADR-0038); o plano inicial dizia 90 s,
   mas acima de ~60 s a transcrição quase sempre cairia na recusa por tamanho de texto depois de paga.
2. **Tamanho declarado:** `audioMessage.fileLength` acima do teto de bytes também recusa sem baixar.
3. **Download em streaming com teto:** `Channel.download_media(url, max_bytes)` lê o corpo aos pedaços,
   confere o `Content-Length` e aborta ao passar do limite (`MidiaGrandeDemais`), sem guardar mais que
   `max_bytes` na memória. O teto de bytes cai de 3 MB para **1 MB** (Opus ~16 kbps: ~8 min).
4. **Eco cortado:** a transcrição mostrada como primeira mensagem passa de 300 caracteres só com `…`;
   o texto completo segue para o tutor (sujeito ao ADR-0038).
5. Os campos do payload são opcionais: sem eles vale só o teto de bytes do download. Os nomes seguem o
   protobuf do GOWS (`seconds`, `fileLength`); confirmar com um payload real após o deploy.

## Alternativas consideradas

- **Medir a duração no servidor (ffprobe)** — descartada: dependência nativa na imagem de 300 MB para
  um dado que o payload já traz; o teto de bytes cobre o caso sem payload.
- **Aceitar áudio longo e truncar a transcrição** — descartada: paga a transcrição inteira.

## Consequências

- Áudio legítimo acima de 1 min precisa ser dividido; o aviso diz o máximo.
- Eventos `audio_recusado` (motivo) permitem medir quanto isso acontece.
- Se o GOWS não enviar `seconds`, a proteção cai para o teto de bytes (1 MB) — ainda segura, só menos
  precisa.
