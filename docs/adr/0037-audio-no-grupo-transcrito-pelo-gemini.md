# ADR-0037: Nota de voz no grupo, transcrita pelo Gemini, só quando cita uma mensagem do bot

- **Status:** Aceito
- **Data:** 2026-10-12

## Contexto

O ADR-0036 fez do citar uma mensagem do bot um jeito de chamá-lo. Mídia seguia ignorada no grupo, mas a
nota de voz é a prática mais útil para quem aprende inglês (falar a frase). Ela não carrega `@bot` nem
texto, então só a citação mostra a quem se dirige; e ouvir todo áudio do grupo seria invasivo e caro.

## Decisão

1. **Áudio só com citação.** Uma nota de voz (`hasMedia` com mimetype `audio/*`, ou `audioMessage`) é
   lida **apenas** se citar uma mensagem do bot (ADR-0036). Sem citação, ou citando outra pessoa, é
   ignorada como qualquer mídia: nada lido, gravado nem marcado como lido.
2. **Fluxo** (depois do 200, em segundo plano): baixa a mídia pelo caminho de `media.url` com o host e a
   API key do bot (`ChannelComLid.download_media`); recusa acima de 3 MB; transcreve com o Gemini do
   Vertex AI atrás de uma interface (`Transcritor`), pedindo a fala como dita, sem corrigir; manda a
   transcrição como a **primeira mensagem** (`🎙️ _texto_`) e então trata o texto como uma mensagem
   marcada comum (`Router.processar(marcado=True)`): feedback, explicação, resposta da atividade.
3. **Modelo:** `GEMINI_MODEL_AUDIO` (opcional); vazio usa o `GEMINI_MODEL`. Só com
   `LLM_PROVIDER=vertex_gemini` e em produção; fora disso o bot avisa que não consegue ouvir.
4. **Falhas só avisam** (sem transcritor, áudio longo, sem fala, erro de download ou da IA) e não
   chamam o tutor. O texto transcrito não vai ao log.
5. **Privado não muda** (mídia segue recusada); o escopo é o grupo.

## Alternativas consideradas

- **Cloud Speech-to-Text** — descartada por ora: um serviço, uma API e uma permissão a mais; o Gemini
  já está autenticado pela conta da VM. Plano B se o Gemini "corrigir" demais o erro do aluno.
- **Ouvir todo áudio do grupo** — descartada: privacidade e custo.
- **Marcação do bot na legenda** — impossível: nota de voz não tem legenda.

## Consequências

- Depende de o WAHA baixar o áudio (`media.url`); o padrão é baixar tudo. `WAHA_EVENTS_DOWNLOAD_MEDIA_MIMETYPES`
  pode limitar a áudio se o disco incomodar.
- Cada áudio custa uma chamada multimodal (centavos, ~25 tokens por segundo de entrada); o teto de
  3 MB limita o pior caso.
- Um LLM pode normalizar a fala do aprendiz (omitir o erro) ou inventar texto em áudio ruim; sem
  medição ainda. Validar com áudios reais e, se preciso, trocar o modelo por `GEMINI_MODEL_AUDIO`.
