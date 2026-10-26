# ADR-0015: Enviar a planilha direto pelo WhatsApp, com o link do bucket só como plano B

- **Status:** Substituído por ADR-0062
- **Data:** 2026-09-24

## Contexto

Até aqui o `/export` subia o arquivo num bucket do Cloud Storage e mandava uma URL assinada de
24 h. A spec dizia "o WAHA Core não envia arquivos", e foi isso que justificou o link (ADR-0014
manteve o mecanismo). Na documentação atual do WAHA, `POST /api/sendFile` aceita o arquivo em
base64 (`file.data`, com `mimetype` e `filename`) e o engine GOWS aparece como suportado; e desde
a 2026.6.1 "os recursos do WAHA Plus fazem parte da imagem Core" (changelog do WAHA). A imagem
fixada no projeto é `gows-2026.8.2`, posterior à mudança.

## Decisão

O bot envia o `.xlsx` direto no chat, como documento com legenda (`Channel.send_file`,
`Conversa.enviar_arquivo`). Se o envio falhar, o `/export` cai no plano B: sobe o mesmo arquivo no
bucket e manda o link, como antes. `WahaChannel.send_file` usa timeout de 90 s e não tenta de novo
(reenviar uma resposta lenta duplicaria o arquivo). O envio só conta no limite de mensagens
seguidas se der certo.

## Alternativas consideradas

- **Só o arquivo, sem plano B (remover o bucket e o `signBlob`)** — simplifica a infra, mas um
  envio recusado pelo WhatsApp deixaria o usuário sem o export. Além disso, mexer em bucket e IAM
  exige `gcloud` com aprovação. Pode virar um ADR próprio depois de o envio direto provar que
  funciona em produção.
- **Manter só o link** — o comportamento anterior; obriga a abrir o navegador e o link expira.

## Consequências

- Fácil: o usuário recebe a planilha no próprio chat, sem link que expira.
- Difícil: o envio direto só foi validado com testes (`MockTransport`) e no simulador; o primeiro
  envio real pelo GOWS ainda não foi visto. O plano B existe justamente para esse risco.
- O bucket, a URL assinada e o papel `serviceAccountTokenCreator` continuam necessários.
- Revisitar se: o plano B nunca disparar em produção (remover o bucket) ou se o WAHA voltar a
  restringir `sendFile`.
