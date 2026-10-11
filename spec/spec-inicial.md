# CLAUDE.md — Vocabot (MVP, versão WAHA + Gemini no Vertex AI)

Este arquivo é a especificação do projeto. Leia-o inteiro antes de escrever código. Trabalhe **marco a marco** (seção 9), pare ao fim de cada um para eu revisar e só avance quando eu aprovar.

---

## 1. O que estamos construindo

Um bot de WhatsApp, de uso pessoal e com um único usuário, para praticar vocabulário de inglês. O nível do usuário é **B1 indo para B2**, e ele é brasileiro. **M9:** a conversa do bot com o aluno é em inglês (imersão) — só a tradução literal do termo fica em PT-BR; esta especificação e o código continuam em PT-BR.

**Canal:** o bot tem um número próprio (chip Vivo) com o app **WhatsApp Business** instalado num celular. O servidor se conecta a esse número como **aparelho conectado** (linked device) usando o **WAHA Core** (WhatsApp HTTP API, self-hosted e gratuito). O usuário conversa com o bot a partir do WhatsApp pessoal dele. **Não** usamos a Cloud API oficial da Meta.

Ciclo principal:

1. O usuário manda uma palavra ou expressão em inglês, opcionalmente com a frase onde a viu (`stall | the talks stalled`) **ou com o sentido que quer aprender** (`stall | to delay on purpose`, M31). Qualquer palavra vale, de qualquer nível, inclusive gíria e inglês de rua.
2. O bot explica a palavra numa única mensagem (o "card"): tradução, definição curta, uma dica e uma frase de exemplo — a IA já escolhe o sentido mais provável, sem perguntar, e o card avisa quando a palavra tem outros sentidos e como pedir um deles (M31).
3. O card termina no **menu único**: 1 ver mais exemplos, 2 ver sinônimos, 3 só salvar, 4 ignorar a palavra e seguir com outra — sempre com o convite a já escrever uma frase. Se a palavra **já está na lista**, o bot avisa, mostra o que o aluno já tem (sentido e exemplo salvos) e oferece só 1, 2 e a frase, além de `0`/`skip` para mandar outra palavra ou comando (seção 5.1).
4. Texto livre (frase, pedido de ajuda, palavra nova, ou fora do escopo) é roteado por uma única chamada de IA (seção 5.1) que classifica e já responde. Frase de prática: avalia se usa a palavra corretamente, naquele sentido, e se é natural; o usuário pode tentar de novo.
5. Ao concluir, tudo fica salvo no Firestore: a palavra, o sentido, as frases do usuário com as avaliações e os exemplos.
6. Ao salvar ("4" ou pedido livre), o bot sugere até 3 **expressões relacionadas** como texto — sem menu; o usuário só manda a que quiser como qualquer palavra nova.
7. `/export` gera uma **planilha Excel** (`.xlsx`) com tudo o que foi coletado e **envia o arquivo direto no chat** (seção 7.3); só se o WhatsApp não aceitar, manda um **link temporário**. (Até o M11 era um `.txt` para o Anki; ver ADR-0014. O envio direto vem da ADR-0015: desde a 2026.6.1 o WAHA Core inclui os recursos do Plus, e o `/api/sendFile` deixou de ser exclusivo do Plus.)

**M10:** o bot também faz revisão espaçada com lembretes agendados (seção 5.7) — deixou de ser fora de escopo.

**M14:** o bot atende **vários alunos no privado**, cada um com o próprio caderno (o **espaço**, ADR-0017) — deixou de ser fora de escopo. **M15:** controle de acesso — quem não tem plano só recebe um aviso, e grupos só entram por um admin (ADR-0018). Os comandos de grupo (`!add`, `!list`...) são o M16 e a revisão em grupo com menção o M17 (`spec/plano-turmas.md`).

**M23:** o bot também **envia** a pronúncia em áudio, sob demanda (seção 7.4, ADR-0024). Receber áudio do aluno continua fora de escopo. **M25:** o áudio virou automático, junto da explicação, e a opção 1 (ouvir) saiu do menu (ADR-0026).

Fora de escopo no MVP: áudio recebido do aluno, painel web e conversa livre com IA sem relação a inglês.

## 2. Stack e decisões fixas

| Item | Decisão |
|---|---|
| Linguagem | Python 3.12 |
| Web | FastAPI + Uvicorn (recebe webhooks do WAHA pela rede interna do Docker) |
| Validação/config | Pydantic v2 + pydantic-settings |
| HTTP | httpx |
| IA | **Gemini no Vertex AI** (padrão): SDK `google-genai` com `vertexai=True`, `location=global`, autenticação pela conta de serviço da VM (sem chave de API). Alternativa opcional: API da Anthropic, via `LLM_PROVIDER=anthropic` |
| Gateway WhatsApp | **WAHA Core** (`devlikeapro/waha`), engine **GOWS** (sem navegador, leve), 1 sessão chamada `default` |
| Banco | Firestore (modo nativo), banco `(default)` |
| Arquivos exportados | Cloud Storage (bucket privado) + URL assinada V4 de 24 h |
| Hospedagem | **1 VM Compute Engine `e2-micro`** (nível gratuito), `us-central1`, Debian 12, disco *standard* de 30 GB, **Docker Compose** com 2 serviços: `waha` e `bot` |
| Segredos | Secret Manager → arquivo `.env` renderizado na VM no deploy (permissão 600) |
| Acesso à VM | SSH via **IAP** (`gcloud compute ssh --tunnel-through-iap`). Nenhuma porta pública além disso |
| Testes | pytest com fakes em memória para Firestore, WAHA e IA |
| Lint/format | ruff |

A VM tem só 1 GB de RAM. Crie um **swap de 2 GB**, limite a memória dos containers no compose e não use a engine WEBJS (Chromium). Não introduza outros serviços sem me perguntar.

## 3. Regras de trabalho para você (Claude Code)

1. **Nunca peça, leia, imprima ou grave valores de segredos.** Com o Vertex AI, não há chave de IA. Se um dia eu usar a Anthropic, a chave entra pelo `infra/secrets.sh`, que eu rodo em outro terminal. Os segredos internos (API key e senha do painel do WAHA) são gerados pelo `setup.sh` com `openssl rand` e vão direto para o Secret Manager, **sem** aparecer na tela.
2. Antes de rodar qualquer comando `gcloud` ou `ssh` que **crie, altere ou apague** algo, mostre o comando e espere eu aprovar. Comandos de leitura podem rodar direto.
3. Scripts de `infra/` precisam ser **idempotentes**.
4. Confira na documentação atual do WAHA (waha.devlike.pro) os nomes exatos de: variáveis de ambiente (API key, painel, webhook, engine, reinício automático de sessões), endpoints (`sendText`, `sendSeen`, `startTyping`/`stopTyping`, status da sessão, QR) e o formato do payload do evento `message`. Fixe a **versão da imagem** (tag) no compose, sem usar `latest`. Confira também, na documentação do Vertex AI e do SDK `google-genai`: o **ID do modelo Gemini Flash (ou Flash-Lite) atual e GA**, se ele exige `location=global`, qual método da SDK usar (`generate_content` ou a Interactions API, conforme o modelo) e como pedir saída estruturada (JSON com schema). **Não use a família Gemini 2.5**, que está com aposentadoria marcada para outubro/2026. Deixe o que puder configurável.
5. Todo texto voltado ao usuário fica em `app/messages.py`, **em inglês**, tom amigável e curto — só a linha 🇧🇷 (tradução literal) fica em PT-BR (M9).
6. Faça um commit ao fim de cada marco.
7. Se algo nesta especificação estiver ambíguo ou parecer errado, pergunte antes de inventar.

## 4. Configuração

| Nome | Origem | Descrição |
|---|---|---|
| `LLM_PROVIDER` | `.env.infra` | `vertex_gemini` (padrão) ou `anthropic` |
| `GEMINI_MODEL` / `GEMINI_MODEL_EVAL` | `.env.infra` | ID do modelo Gemini (confirmar o atual); o de avaliação pode ser igual ou maior |
| `VERTEX_LOCATION` | `.env.infra` | Padrão `global` |
| `GCP_PROJECT_ID` | `.env.infra` | Projeto do Google Cloud (usado pelo Vertex AI e pelos scripts) |
| `ANTHROPIC_API_KEY` | Secret Manager (opcional) | Só se `LLM_PROVIDER=anthropic` |
| `WAHA_API_KEY` | Secret Manager (gerado) | Chave que o bot usa para chamar o WAHA; o WAHA exige essa chave |
| `WAHA_DASHBOARD_PASSWORD` | Secret Manager (gerado) | Senha do painel/Swagger do WAHA (usuário `admin`) |
| `WAHA_HOOK_HMAC_KEY` | Secret Manager (gerado) | Chave da assinatura HMAC dos webhooks (seção 8.1); opcional para o bot |
| `ALLOWED_NUMBER` | `.env.infra` | Número **pessoal** do usuário, só dígitos (ex.: `5531999998888`). Desde o M14 (ADR-0017) entra na lista de números permitidos, e é o dono do bot por padrão |
| `ALLOWED_NUMBERS` | `.env.infra` (opcional) | Lista de números permitidos separados por vírgula, mesma comparação do nono dígito (seção 8.2). Cada número é um aluno, com o próprio caderno |
| `ALLOWED_GROUPS` | `.env.infra` (opcional) | Lista de ids `@g.us` de grupos autorizados (o id de um grupo novo aparece uma vez no log) |
| `OWNER_NUMBER` | `.env.infra` (opcional) | O dono do bot; padrão o primeiro número da lista (o `ALLOWED_NUMBER`, se definido) |
| `MAX_GROUPS` | `.env.infra` (opcional) | Padrão `10`: teto de grupos ativados por admin (M15, ADR-0018); os de `ALLOWED_GROUPS` não contam |
| `GROUP_PREFIX` | `.env.infra` (opcional) | Padrão `!`: em grupo o bot só lê mensagens que começam com isto (M16, ADR-0019); 1 ou 2 símbolos, sem letras, números nem a barra |
| `LIMITE_POR_SESSAO_GRUPO` | `.env.infra` (opcional) | Padrão `5`: palavras por rodada de revisão em grupo (M17, ADR-0020); no privado é dinâmico, `MIN(palavras do aluno, 7)` (M24), a menos que `/reviewsize`/`/reminders` fixe outro valor |
| `TIMEOUT_MARCACAO_HORAS` | `.env.infra` (opcional) | Padrão `3`: quanto esperar a pessoa marcada numa revisão em grupo antes de passar o card ao próximo aluno |
| `MAX_CARACTERES` | `.env.infra` (opcional) | Padrão `500` (M40, ADR-0038): acima disso a mensagem é recusada sem chamar a IA |
| `MAX_SEGUNDOS_AUDIO` | `.env.infra` (opcional) | Padrão `60` (M41, ADR-0039): nota de voz acima disso é recusada pela duração do payload, sem baixar |
| `CONTACT_EMAIL` | `.env.infra` (opcional) | E-mail que o aviso "você não tem um plano" mostra a quem não está na lista (M15) |
| `BOT_NUMBER` | `.env.infra` | Número Vivo do bot, só dígitos (informativo/logs) |
| `WAHA_URL` | compose | `http://waha:3000` |
| `WAHA_SESSION` | compose | `default` |
| `EXPORT_BUCKET` | `.env.infra` | Nome do bucket de exportações |
| `AUDIO_BUCKET` | `.env.infra` (opcional) | Bucket do cache de áudio de pronúncia (M23). Padrão `${PROJECT_ID}-vocabot-audio`; vazio ou fora de `APP_ENV=prod`, a pronúncia fica indisponível |
| `TTS_VOICE` | `.env.infra` (opcional) | Voz do Cloud TTS (M23). Padrão `en-US-Neural2-F` |
| `ANTHROPIC_MODEL` | `.env.infra` (opcional) | Padrão `claude-haiku-4-5-20251001` |
| `USER_LEVEL` | `.env.infra` | Padrão `B1-B2` |
| `TIMEZONE` | `.env.infra` | Padrão `America/Sao_Paulo`; fuso para distribuir os lembretes (M10, seção 5.7) |
| `APP_ENV` | compose | `local` ou `prod` |
| `LYRICS_URL` | `.env.infra` (opcional) | Padrão `https://lrclib.net`; API pública de letras do `/song` (M13, ADR-0016), sem chave |

Para desenvolvimento local, use um `.env` (no `.gitignore`) com valores falsos. Os testes nunca dependem de credenciais reais. Para o simulador com IA real (`--real-llm`), use as credenciais locais do Google (`gcloud auth application-default login`), sem chave em arquivo.

## 5. Especificação funcional

### 5.1 Máquina de estados

A sessão fica num único documento `session/current`. Desde o M9 há só **dois estados e um único
menu de ações**: a IA assume o papel das heurísticas antigas (sentido ambíguo, "isso é uma frase
ou uma palavra nova?", menu de expansões numerado). As escolhas do menu continuam por **número**;
aceite também variações (`1`, `1.`, apelidos em inglês como `examples`, `save`).

```
IDLE          ── texto (não comando) ──▶ explicar + notas de voz automáticas (M25) ──▶ AWAIT_ACTION
AWAIT_ACTION  ── 2 "see more examples" ──▶ gerar exemplos   ──▶ AWAIT_ACTION
              ── 3 "check synonyms"    ──▶ gerar sinônimos  ──▶ AWAIT_ACTION
              ── 4 "just save"         ──▶ salvar e sugerir ──▶ IDLE
              ── 5 "ignore this word"  ──▶ descartar a palavra recém-criada ──▶ IDLE
              ── 0 / skip              ──▶ sair da palavra (fica salva), sem IA ──▶ IDLE
              ── `palavra | algo`      ──▶ (M31) sem IA de roteamento: mesma palavra = outro sentido; outra = palavra nova ──▶ AWAIT_ACTION
              ── qualquer outro texto  ──▶ rotear pela IA (abaixo) ──▶ AWAIT_ACTION (ou IDLE)
```

O menu começa no **2** (não tem opção 1) desde o M25 (ADR-0026): a pronúncia em áudio virou
automática, junto da explicação, então deixou de ser uma escolha — e os números 2-5 continuam os
mesmos de sempre, para não mudar o que o aluno já decorou.

A revisão espaçada (`REVIEWING`, seção 5.7) e a prática com música (`SONG_PICKING`,
`SONG_PRACTICE`, `SONG_SAVING`, seção 5.8) são sessões à parte, iniciadas por comando (ou pelo
agendador), com transições próprias descritas nas suas seções.

**Roteamento por IA (`Tutor.route`, ADR-0009):** todo texto livre em `AWAIT_ACTION` que não é uma
opção do menu vira **uma única chamada de IA** que classifica a intenção e já devolve a resposta
(nunca uma segunda chamada separada para avaliar/gerar):

- `frase` — o aluno tentou usar a palavra-alvo numa frase (mesmo com erro ou flexão diferente):
  avalia, com os mesmos campos de `evaluate`.
- `exemplos` / `sinonimos` — pedido de mais exemplos/sinônimos, com quantidade opcional (1 a 10,
  padrão 3; fora do intervalo é limitado pelo fluxo, nunca pela IA).
- `salvar` — equivalente a digitar "4".
- `nova_palavra` — o texto não é sobre a palavra-alvo atual e parece uma nova palavra/expressão em
  inglês: salva a atual silenciosamente (como em "4") e explica a nova, numa segunda mensagem.
- `pedido` — qualquer outro pedido sobre aprender inglês (pronúncia, outro sentido da palavra,
  exemplos numa área específica, dúvida de gramática...): a IA já escreve a resposta, em inglês.
- `fora_do_escopo` — nada relacionado a aprender inglês (small talk, outro assunto): a IA recusa
  gentilmente, em inglês.

Regras:

- **Sessão parada há mais de 3 horas** volta para IDLE, salvando o que houver.
- `/cancel` (ou `/cancelar`) volta a IDLE sem apagar o que já foi salvo.
- **Opção 5 (ignorar):** apaga a entrada **só se** ela foi criada por esta captura
  (`Sessao.entrada_criada_agora`) e o aluno ainda não escreveu nenhuma frase nela; caso contrário
  (palavra que já estava na lista, ou já praticada) a entrada fica e o bot avisa que ela continua
  na lista. Em ambos os casos volta a IDLE. Os apelidos de texto são só frases inteiras
  (`ignore this word`, `ignore it`, `discard it`...): `ignore`/`drop` sozinhas podem ser a palavra
  que o aluno quer aprender.
- **Pronúncia automática (M25, ADR-0026, seção 7.4):** logo depois de explicar a palavra (nova ou já
  existente), o bot manda **duas notas de voz** (o termo e a frase do card, a do bot mais antiga da
  entrada), sem precisar de nenhuma escolha do menu. Se o serviço de áudio não está configurado
  neste ambiente, fica em silêncio (ninguém pediu, a explicação já dita basta); uma falha de
  verdade (TTS, Storage, WhatsApp) avisa em uma linha, sem derrubar a conversa. `/listen` continua
  existindo à parte, para tocar de novo qualquer palavra já salva.
- **`0` / `skip` em `AWAIT_ACTION`** (e só eles: `stop`, `leave` etc. seguem indo para o roteamento,
  pois podem ser a palavra a aprender) saem da palavra aberta sem chamar a IA e sem apagar nada.
- **`palavra | frase ou sentido` em `AWAIT_ACTION` (M31, ADR-0030):** texto com `|` e algo dos dois
  lados **não** passa pelo roteamento de IA. Se o termo é o da palavra aberta, é um **pedido de outro
  sentido**: se a entrada foi criada por esta captura e o aluno ainda não escreveu frase nela, o novo
  card **substitui** o anterior (a IA responde primeiro; se falhar, nada é apagado); caso contrário o
  novo sentido vira outra entrada (`--sN`), sem "Saved" no meio. Se o termo é outro, é uma palavra
  nova (salva a atual e explica a nova; no grupo, igual ao privado: M37, a palavra só chega aqui marcando o bot).
- **Palavra que já existe** (ADR-0023: palavra sem frase de contexto **nem sentido pedido** já salva, em qualquer sentido; com
  frase ou sentido pedido, mesmo `slug` e mesmo sentido — traduções com alguma opção em comum contam como o mesmo): em vez do card completo,
  o bot manda `📌 You already have *X* in your list.` com título, 🇧🇷, 📖 e o exemplo **salvos**,
  os outros sentidos (`↔️`) com a dica de como pedi-los, o convite a escrever uma frase, as opções 1 a 3 (ouvir, exemplos e sinônimos) e a linha
  `To send another word or command, type 0 or skip.` (no grupo, `!0 or !skip`). Nada é regravado;
  a sessão fica em `AWAIT_ACTION` sobre aquela entrada (`entrada_criada_agora=false`).
- **Sempre** reenvie o menu de ações ao final de cada resposta em `AWAIT_ACTION` — inclusive nas
  respostas do roteamento livre (`pedido`, `fora_do_escopo`, avaliação de `frase`), exceto quando a
  resposta já é o card de uma palavra nova (`nova_palavra`).

### 5.2 Comandos

`/help`, `/list [página]`, `/info N|palavra`, `/pending`, `/practice [N|palavra]`, `/review`,
`/reviewsize [N|auto]`, `/listen N|palavra`, `/song nome [- artista]`,
`/reminders [N [INICIOh-FIMh] [TAMANHO] | off]`, `/profile`, `/export`, `/delete N|palavra`,
`/level A1-A2|A2-B1|B1-B2|B2-C1|C1-C2|C2`, `/cancel`, `/status`. Todos os nomes são em inglês (M12, ADR-0014). Os
apelidos em PT-BR que a spec sempre teve (`/ajuda`, `/lista`, `/pendentes`, `/praticar`,
`/exportar [tudo]`, `/apagar`, `/nivel`, `/cancelar`, `/reminders`, `/review`, `/perfil`, `/musica`)
**continuam funcionando, mas nenhuma mensagem do bot os divulga**.

- `/list` mostra as palavras **das mais novas para as mais antigas**, 20 por página: as mais
  novas ficam sempre na página 1, e `/list 2` é a página 2. Uma página inexistente responde com um
  aviso. Cada linha é `N. termo: tradução em PT-BR`, sem emoji de status (use `/pending` para ver as
  ainda não praticadas). O número de cada palavra é **fixo** (1 = a mais antiga, na ordem de criação), então
  `/info 7` e `/delete 7` continuam apontando para a mesma palavra quando entram palavras novas.
- `/info N` (número da `/list`) ou `/info palavra` mostra tudo de uma entrada: tradução, definição,
  outros sentidos, nota, status e próxima revisão, as frases do aluno **já corrigidas** (a
  `versao_natural`, sem `[[ ]]`, até 5, sem repetir), até 3 exemplos do bot e os sinônimos salvos.
  `/practice` e `/delete` também aceitam o número.
- `/pending` lista as entradas com status `nova`.
- `/export` gera a planilha com **todas** as palavras (ver 7.3); `/export all` (e `/exportar tudo`)
  é aceito e faz o mesmo. Sem nenhuma palavra, o bot avisa que não há o que exportar.
- `/practice` sem argumento pega a pendente mais antiga.
- `/level` aceita A1-A2, A2-B1, B1-B2, B2-C1, C1-C2 e C2 (M34, ADR-0032).
- `/reminders`, `/review` e `/reviewsize`: ver seção 5.7.
- `/song`: ver seção 5.8. Sem argumento, mostra como usar.
- `/profile` mostra o nível, o total de palavras (praticadas e pendentes), quantas estão vencidas
  para revisão e os lembretes (`every day, 3x between 9h and 21h` ou `off`) e, com os lembretes ligados, **quando o
  próximo toca** (`Next reminder: today at 14:00`, `tomorrow at 08:00` ou `Mon 28 Sep at 08:00`, no
  fuso do aluno). `/reminders` (consulta e ao ligar/mudar) mostra o mesmo horário. O horário vem de
  `profile/me.proximo_lembrete` se ainda está no futuro; senão é calculado da janela
  (`app/domain/lembretes.py:proximo_a_exibir`). Os lembretes rodam todos os dias; não há escolha de
  dias da semana.
- `/status` mostra o status da sessão do WAHA, o total de palavras e as pendentes.
- **Comandos de acesso (M15, ADR-0018), escondidos do `/help`:** `/groups` (dono e admins) lista os grupos
  ativos e os pendentes, com o nome e as horas que faltam para o bot sair, e `/groups off N` desativa o
  grupo N da lista; `/admin`, `/admin add NUMERO` e `/admin remove NUMERO` (só o dono) gerenciam os
  admins. Para quem não pode usá-los, valem como qualquer comando desconhecido.

### 5.2b Grupos de turma (M16, ADR-0019)

Em grupo ativo (5.6, ADR-0018) o bot **só lê três coisas** (M37/M38, ADR-0035/ADR-0036, que mudam a regra do
ADR-0019): **mensagens que o marcam** (`@bot ...`, conversa com ele, sem comando), **respostas (citações) a uma mensagem do bot** (M38, valem como a marcação) e **comandos** com
o prefixo (`GROUP_PREFIX`, padrão `!`) **ou `/`**, com uma letra ou número logo depois. O resto é
conversa entre pessoas e não é lido, gravado nem marcado como lido (o filtro vem antes da
deduplicação e do `sendSeen`). Mídia é ignorada, **exceto nota de voz que cita uma mensagem do bot** (M39, abaixo). Marcar ou citar outra pessoa não chama o bot.

- **Citação (M38, ADR-0036):** a mensagem cujo autor citado (`replyTo.participant` ou `_data.Message.<tipo>.contextInfo.participant` com `stanzaID`/`quotedMessage`) é o bot (mesmo reconhecimento da marcação: `me`, `BOT_NUMBER`, LID resolvido) é conversa com ele, sem `@bot` nem comando; com `!`/`/` vale como o comando.
- **Áudio (M39, ADR-0037):** nota de voz (`audio/*`) só é lida se citar uma mensagem do bot; sem citação é ignorada. Em segundo plano: `ChannelComLid.download_media(media.url)` (caminho da URL, host e API key do bot), recusa pela duração (`audioMessage.seconds` > `MAX_SEGUNDOS_AUDIO`, M41) ou tamanho declarado antes de baixar, baixa em streaming com teto de 1 MB (`MidiaGrandeDemais`), `Transcritor` (Gemini no Vertex; modelo `GEMINI_MODEL_AUDIO` ou `GEMINI_MODEL`; fala como dita, sem corrigir), manda `🎙️ _transcrição_` (cortada em 300 caracteres) como primeira mensagem e segue como mensagem marcada comum (`Router.processar(marcado=True)`). Sem fala, áudio longo, sem transcritor ou falha de download/IA: aviso curto, sem chamar o tutor. A transcrição não vai ao log.

- **Marcação (M37):** o webhook reconhece o bot pelos ids marcados na mensagem — no GOWS o campo
  `mentionedIds` vem vazio e a marcação está em `_data.Message.<tipo>.contextInfo.mentionedJID`, com o
  **LID** do bot (o texto traz `@<LID>`) — comparados com o `me` da sessão (`GET /api/sessions/{session}`:
  `id` e `lid`) e com `BOT_NUMBER` (nono dígito à parte; sem o `me`, o LID resolve pelo cache `lids/`);
  como plano B, `@numero` ou `@bot` digitados no texto. Tira a marcação do bot e entrega o resto à
  mesma máquina de estados do privado: dentro de uma atividade é a resposta (`@bot 2`, `@bot a frase`,
  `@bot skip`, `@bot stop`); fora dela `@bot stall` / `@bot stall | contexto` adiciona a palavra e
  `@bot` sozinho ou `@bot help` mostra a ajuda. `@bot !list` vale como o comando.

- **Comandos (conjunto fechado):** `!delete palavra|número` (M32: remove um termo da lista da turma, igual ao `/delete` do privado; o número é o do `!list`; qualquer membro pode, como no `!add`), `!add palavra [| contexto ou sentido]` (M37: apelido escondido da ajuda; a forma normal é marcar o
  bot com a palavra; com a palavra aberta, o mesmo termo com `|` troca o sentido, como no privado — M31), `!list [página]` (palavras da turma, mesma regra do `/list`), `!practice [palavra|número]`,
  `!review` (M35: começa uma revisão diária na hora), `!daily [19h | on | off | weekends on|off | size N|auto]`, (M35, ADR-0033: qualquer membro vê; só admin do bot ou o dono muda; `!reminder` virou apelido que aponta para ele), `!weekly [fri 13h | on | off | size N|auto | now]` (M36, ADR-0034: mesma permissão; `now` começa o desafio na hora), `!level [A1-A2|A2-B1|B1-B2|B2-C1|C1-C2|C2]` (M33, ADR-0031: sem argumento qualquer membro vê o nível da turma; com argumento só professor ou dono muda, e aluno recebe a recusa), `!group` (nível, palavras,
  vencidas, lembretes e os membros com o papel, só nomes e sem menção) e `!help` (só os comandos do
  grupo). `!teacher`/`!student` (um professor da turma ou o dono) mudam o papel, escondidos do `!help`;
  os alvos vêm das menções do payload ou do número escrito no texto.
- **Dentro de uma atividade:** marcar o bot com `2`, `3`, a frase etc. responde, pela mesma máquina de
  estados do privado; `!1`, `!2`, `!3` e `!texto` (e com `/`) continuam valendo. Na revisão, a marcação
  responde, `skip` pula a palavra, `skipall` (ou `0`/`stop`) encerra.
  **Barra (M37, ADR-0035):** qualquer comando vale com `/` no grupo (no M35 eram só `/skip`, `/skip-all`,
  `/skipall`, `/1`, `/2` e `/3`); `/` sozinha ou seguida de espaço é conversa.
- **Fora de atividade**, um comando com o prefixo que não existe, inclusive comando do privado
  (`!export`, `!song`...), recebe a ajuda do grupo, **sem chamar a IA**.
- Os textos que citam comandos usam o prefixo do espaço e, no grupo, só citam comandos do grupo.
- **Turma só em inglês (M34, ADR-0032):** no grupo, de B1-B2 para cima, nada aparece em português (sem a
  linha 🇧🇷, sem a tradução nos cabeçalhos e nos `↔️`; o `!list` mostra a definição, cortada em 70
  caracteres). A1-A2 e A2-B1 mantêm a 🇧🇷. A `traducao` segue gerada e gravada. O privado não muda.
- `espacos/{grupo}/membros/{numero}` guarda `{papel: aluno|professor, nome}` (quem manda a primeira
  mensagem com prefixo entra como aluno); `sentences.autor_id` guarda quem escreveu a frase.
- No privado nada muda; o prefixo do grupo é aceito como apelido escondido da barra (`!list` vale
  `/list`, se uma letra vem logo depois).
- `python -m sim --grupo`: uma linha `nome: mensagem` por participante; linhas sem prefixo aparecem
  como ignoradas.

**Revisão diária do grupo (M35, ADR-0033; substitui o M17/ADR-0020).** Uma por dia, às 19h (fuso da
turma), de segunda a sexta (`Profile.diaria_*`; `!daily 20h`, `!daily weekends on`, `!daily off`,
`!daily size 3`). `!review` começa uma na hora. **Ninguém é marcado**: o card convida todo mundo, e
qualquer participante responde com `!texto`, recebendo feedback da IA (`Tutor.review`). A **primeira
resposta aceitável** (`qualidade != de_novo`) vale a nota (`srs.reagendar` no cartão do grupo) e o bot
manda o feedback com o nome de quem respondeu e o próximo card numa mensagem só; resposta `de_novo`
recebe feedback e a palavra segue aberta (cartão intacto). `!skip` (ou `/skip`) pula a palavra sem
mexer na nota; `!skipall` (`/skip-all`, `!0`, `!stop`) encerra com o resumo (`Skipped:` lista as puladas).
`LIMITE_POR_SESSAO_GRUPO` (5) palavras por rodada, ou o `tamanho_revisao` do `!daily size`.

- **Fecha sozinha** após `TIMEOUT_MARCACAO_HORAS` (3h) sem mensagem do grupo; toda mensagem adia o
  prazo. O prazo vai para `espacos/{grupo}.timeout_em` e o agendador acha as vencidas com uma consulta
  por tick, **antes** dos lembretes (a sessão libera no mesmo tick).
- **Agendador** (`services/lembretes.py:_tick_grupo`): `proximo_tick` do grupo é a `proxima_diaria`;
  atraso > 2h desiste do horário; sessão ocupada e não expirada adia; sem palavras fica em silêncio.
  **Pausa** depois de 3 revisões agendadas seguidas sem nenhuma mensagem do grupo
  (`Profile.revisoes_sem_resposta`); qualquer mensagem do grupo zera o contador.
- `respostas/{auto}` registra `{entry, autor_id, marcado=false, qualidade}` de cada resposta.

**Desafio semanal do grupo (M36, ADR-0034).** Uma vez por semana (padrão **sexta 13h**, fuso da turma;
`!weekly mon 9h`, `!weekly size 3`, `!weekly off`; `!weekly now` começa na hora; ver: todos, mudar: admins
do bot e o dono). O bot cria perguntas abertas **no nível da turma** com palavras do vocabulário do grupo
(`Tutor.weekly_questions`, uma chamada; `escolher_vocabulario`: as da última semana primeiro, até 15) e
**marca um aluno por pergunta** (rodízio do ADR-0020; professores e o bot nunca; uma pergunta por aluno
elegível por padrão, até 10, ou `size N`). Estado `WEEKLY_QUIZ`. Cada pergunta **começa pela menção**:
```
@5531999998888 What would you do if a project you care about *stalled* for weeks?

/1 Explain the question
/2 Listen to the question
/3 Skip this question
_🏆 Weekly challenge · 1/3 — tag me to answer_
```
- Qualquer um pode tentar (marcando o bot com a resposta; `!texto` também vale) e recebe feedback
  (`Tutor.weekly_answer`), que julga se a resposta é **coerente com a pergunta no geral** (M37: usar as
  palavras do vocabulário não é exigido nem pesa contra; usá-las só melhora); a pergunta **só avança
  quando a pessoa marcada responde** ou alguém pula (`3`/`skip`); `skipall`/`0`/`stop` encerra com o
  resumo. Sem nota SM-2. `respostas/` registra a participação.
- `1`: turma A1-A2/A2-B1 vê **🇧🇷 português e depois 🇺🇸 inglês**; de B1-B2 em diante, só inglês. `2`: a
  pergunta em voz (Cloud TTS, cache existente). `/1`, `/2`, `/3` (ou marcar o bot com `1`, `2`, `3`) valem no grupo.
- Fecha sozinho após 3 h sem mensagem; o semanal tem precedência sobre a diária no mesmo tick.

### 5.3 Calibração pelo nível (B1-B2)

- **Exemplos:** vocabulário de apoio no máximo B2 (a palavra-alvo pode ser de qualquer nível), 8 a 18 palavras por frase, contextos variados (empresa internacional, dia a dia, informal).
- **Níveis (M34):** A1-A2, A2-B1, B1-B2, B2-C1, C1-C2 e C2, cada um com calibração própria no prompt (`_CALIBRACAO_POR_NIVEL`).
- **Avaliação:** tolerante com frases simples e corretas. Prioridade: sentido, depois gramática e colocação, depois naturalidade. Explicação em inglês, com no máximo 4 linhas (M9: só a linha 🇧🇷 do card fica em PT-BR).
- **Palavra-alvo de qualquer nível (M31, ADR-0030):** o nível do espaço calibra só o vocabulário de apoio (definições, dicas, exemplos). Nenhum nível é motivo de recusar uma palavra: raras, técnicas, gírias, inglês de rua, abreviações (`gonna`, `ain't`, `no cap`) e palavrões entram, com a `nota` avisando o registro. A IA só devolve `ok=false` para o que não é inglês.
- **Expansões:** colocações e expressões frequentes de nível B1-B2, ligadas ao sentido escolhido. Evite idiomatismos raros (C2).
- Cada entrada guarda `cefr_estimado`.

### 5.4 Menu único de prática (M9)

Não há mais modos (`guiado` / `producao_primeiro`): toda palavra cai no mesmo menu de ações
(seção 5.1), sempre com o convite a escrever uma frase junto — `Profile` não guarda mais `modo`.

### 5.5 Formato das mensagens

Use a formatação do WhatsApp (`*negrito*`, `_itálico_`) e emojis com moderação. Um único texto por
resposta sempre que possível. Desde o M9, **tudo em inglês** — só a linha 🇧🇷 (tradução literal)
fica em PT-BR (exceto em turmas de B1-B2 para cima, M34) — e o menu de ações (seção 5.1) termina praticamente toda resposta.

**Card inicial** (o aluno manda uma palavra; a IA já escolhe um sentido e gera uma frase de
exemplo calibrada, reaproveitando palavras que o aluno já salvou quando der):
```
*stall* (verb) — B2
🇧🇷 travar, emperrar
📖 to stop making progress
💡 Think of a car engine that dies in traffic.
"The project stalled because the client didn't send the documents."

↔️ enrolar — to delay on purpose
Want another meaning? Send *stall | to delay on purpose*

Now, you can write one or more sentences using *stall*, or type:
2️⃣ See more examples
3️⃣ Check synonyms
4️⃣ Just save
5️⃣ Don't save
```
Os outros sentidos (`Explanation.sentidos` menos o escolhido, no mesmo formato do `/info`) aparecem
depois do exemplo; sem outros sentidos, o card não muda. A dica usa a definição do primeiro outro
sentido (no grupo, "Tag me with *stall | to delay on purpose*"). Mandar `stall | to delay on purpose`
(ou `stall | enrolar`) faz a IA explicar **aquele** sentido, em vez do mais popular.

**Case A — texto livre** (roteado pela IA, seção 5.1). Frase de prática avaliada:
```
⚠️ *Almost there!* The meaning is right.
✏️ didn't sent → didn't send
✨ The project stalled because the client didn't send the documents.
💬 After "didn't", the verb stays in the base form.

Want to try another sentence?
Now, you can write one or more sentences using *stall*, or type:
1️⃣ Hear how it sounds 🔊
2️⃣ See more examples
3️⃣ See more synonyms
4️⃣ Just save
5️⃣ Don't save
```
Pedido de ajuda ou palavra fora do escopo: a resposta da IA (ou, fora do escopo, uma recusa
gentil) seguida do mesmo menu. Palavra nova: salva a atual silenciosamente e manda o card da nova,
como se fosse `IDLE`.

**Case B — "2" / "see more examples"** (padrão 3, máximo 10, sem repetir os já mostrados):
```
📝 *Examples with stall* (travar, emperrar)
1. We had to stall before the deadline.
2. She didn't want to stall in front of the client.
3. It's easy to stall when nobody is watching.

Want to try a sentence of your own?
Now, you can write one or more sentences using *stall*, or type:
1️⃣ Hear how it sounds 🔊
2️⃣ See more examples
3️⃣ Check synonyms
4️⃣ Just save
5️⃣ Don't save
```

**Case C — "3" / "check synonyms"** (padrão 3, máximo 10, sem repetir os já mostrados; a partir
daqui a opção 3 do menu vira "See more synonyms"):
```
🔄 *Synonyms for stall* (travar, emperrar)
*stumble* = to almost fail or lose momentum
_Example: "The talks stumbled early on."_

Want to try a sentence with *stall*?
Now, you can write one or more sentences using *stall*, or type:
1️⃣ Hear how it sounds 🔊
2️⃣ See more examples
3️⃣ See more synonyms
4️⃣ Just save
5️⃣ Don't save
```

**Case D — "4" / "just save"** (fecha a palavra; sugere até 3 expressões relacionadas só como
texto, sem criar entradas nem menu — se o aluno quiser uma, é só mandá-la como qualquer palavra
nova):
```
✅ Saved: *stall*.
Practice it any time with /practice stall, or see everything with /list.
You might like these too: *stall for time*, *grind to a halt*, *drag on*.
Send me another word or expression whenever you want.
```

### 5.6 Comportamento "humano" (reduz o risco de bloqueio)

- Marque as mensagens recebidas como lidas (`sendSeen`).
- Mostre "digitando…" (`startTyping`) enquanto chama a IA e pare antes de enviar.
- Espere de 1 a 2 s (aleatório) antes de cada envio.
- **Nunca** envie mensagem para um número fora da allowlist (`ALLOWED_NUMBER`/`ALLOWED_NUMBERS`, seção 8.2): só ao chat de quem escreveu.
- Nunca mande mais de 3 mensagens seguidas sem uma resposta do usuário (o limite vale por espaço, M14).
- **Texto acima de `MAX_CARACTERES` (500) é recusado** (M40, ADR-0038) com um aviso curto, antes do banco e da IA; no grupo só vale para o que o bot lê (marcação, citação, comando).
- **A IA nunca é chamada para quem não tem plano** (M15): número fora da lista só recebe o aviso "você
  não tem um plano" (texto em inglês com a linha 🇧🇷, e o e-mail de `CONTACT_EMAIL`), no máximo uma
  vez a cada 7 dias por número, e depois silêncio, sem `sendSeen`, sem ler nem gravar nada.
- **Grupos só entram por um admin** (M15): o bot ativado num grupo por `!activate` de um admin (dono ou
  `admins/`), até `MAX_GROUPS`. Grupo em que foi adicionado sem ativação fica pendente em silêncio e o
  bot **sai dele depois de 24 h**, sem mandar mensagem. Configure no celular do bot: Privacidade →
  Grupos → "Meus contatos".

### 5.7 Revisão espaçada e lembretes (M10, ADR-0011, ADR-0012, ADR-0025)

O bot também **inicia** conversas: no horário combinado, faz uma sessão de revisão com as palavras
vencidas. Espaçamento estilo Anki (SM-2 simplificado, `app/domain/srs.py`), mas a nota vem do
julgamento da IA sobre a resposta em texto livre do aluno, não de 4 botões.

**Configuração:** `/reminders` mostra o estado; `/reminders N` liga N vezes por dia na janela
padrão (9h–21h); `/reminders N INICIOh-FIMh` usa uma janela própria (N de 1 a 8, `0 <= início <
fim <= 23`); `/reminders off` desliga. `/reminders` aceita um último parâmetro opcional, o tamanho
da fila de revisão (ver abaixo) — **omitido, não mexe no que já estava configurado** (nunca reseta
um `/reviewsize` anterior sem a pessoa pedir). **Ligado por padrão (M24, ADR-0025): 1x por dia,
às 12h** — só para perfil novo; quem já tinha conta antes do M24 não muda sozinho. Quando os
lembretes estão desligados, a primeira palavra salva mostra uma dica de uma linha sobre o comando,
uma única vez. Os horários se distribuem igualmente dentro da janela
(`app/domain/lembretes.py:horarios_do_dia`).

**Tamanho da fila (M24):** por padrão, dinâmico — `MIN(palavras do aluno, 7)`. `/reviewsize N` fixa
um valor (1 a 20); `/reviewsize auto` volta ao dinâmico; `/reviewsize` sozinho mostra o atual. O
último parâmetro de `/reminders`, **quando dado**, faz a mesma coisa, para configurar tudo de uma
vez; omitido, o `/reminders` mexe só nos lembretes, sem tocar no tamanho da fila. Um valor fixo
vale tanto no privado quanto no grupo (que por padrão usa `LIMITE_POR_SESSAO_GRUPO`, 5). `/profile`
mostra o tamanho efetivo da sessão.

**Máquina de estados:** um novo estado, `REVIEWING`. Durante ele, qualquer texto que não seja
"sair" (`0`, `stop`, `quit`, `exit`, `leave`) é a resposta à palavra atual — sem roteamento por IA
aqui (seria ambiguidade e custo à toa). Comandos (`/`) continuam funcionando; `/cancelar` fecha a
sessão com o resumo, como `0` faria.

**Pronúncia automática do termo (M26, ADR-0027, seção 7.4):** no privado, cada card vem seguido da
voz do termo (sem a frase — é sobre lembrar o som, não reouvir o exemplo). No grupo não: o
orçamento de 3 mensagens seguidas já é disputado pelo repasse e pelo fechamento da rodada
(ADR-0020), e áudio ali arriscaria derrubar um dos dois em silêncio.

```
⏰ *Practice time* — 12 words to review.

🔁 1/12 · *stall*
Explain it in English in your own words, or write a sentence using it.

_Type 0 to leave the practice._
```
Cada turno seguinte é **uma mensagem só**, com o feedback da resposta anterior e o próximo card
juntos (respeita o limite de 3 mensagens seguidas, seção 5.6):
```
✅ That's it — you clearly remember this one.
💬 "to stop making progress" is exactly the idea.

🔁 2/12 · *deadline*
Explain it in English in your own words, or write a sentence using it.

_Type 0 to leave the practice._
```
Ao acabar a fila, digitar `0` ou `/cancelar`:
```
🎉 *Practice done* — 9 of 12 reviewed.
✅ Solid: stall, deadline, overwhelmed
🔁 Coming back soon: reluctant, mitigate
Send me a new word or expression whenever you want.
```

**Fila de uma sessão** (`app/flows/review.py:montar_fila`): as vencidas primeiro (mais antiga
primeiro; `proxima_revisao=None` = cartão novo, vencido desde já), completando até o tamanho da
fila (`app/flows/review.py:limite`, M24: ver seção 5.7 acima) com as que vencem mais cedo entre as
que ainda não venceram. Sem nada vencido, o agendador fica em silêncio —
nunca manda "nada para revisar" sem o aluno pedir (só `/review`, chamado explicitamente, avisa).
Uma resposta `de_novo` volta a palavra para o **fim da fila desta sessão** (como no Anki) e conta
um lapso; as demais notas (`dificil`/`bom`/`facil`) avançam o agendamento.

**Disparo, com três camadas de segurança** (seção 5.6, ADR-0012): um agendador em segundo plano
(`app/services/lembretes.py:Agendador`), acordando a cada minuto. Desde o M14 (ADR-0017) ele olha todos os espaços com lembretes ligados (uma consulta por tick, só os vencidos) e cada espaço tem o próprio `chat_id`, `proximo_lembrete` e `lembrete_sem_resposta`; as três camadas valem por espaço. Só dispara com um `chat_id` real
— o número que o WhatsApp de fato usa para esse aluno, aprendido de uma mensagem recebida (nunca o
`ALLOWED_NUMBER` do `.env` direto: pode diferir no nono dígito, seção 8.2). Nunca dois lembretes
seguidos sem resposta ao anterior (`lembrete_sem_resposta`, limpo na próxima mensagem do aluno,
qualquer que seja). Se a conversa está aberta (`sessao.estado != IDLE`), adia para o próximo tick,
e desiste (recalculando o próximo horário) se o atraso passar de 2 horas.

`/review` começa a sessão na hora, sem esperar o próximo horário.

### 5.8 Prática com letra de música (M13, ADR-0016)

`/song nome` (ou `/song nome - artista`) pratica a compreensão de uma música, verso a verso. A
letra vem do LRCLIB (`app/services/letras.py`, atrás da interface `LyricsProvider`); as regras
sobre a letra são funções puras em `app/domain/musica.py`, e o fluxo em `app/flows/song.py`.

```
IDLE / qualquer ── /song nome ──▶ buscar ──▶ 0 músicas: avisa  ──▶ IDLE
                                          ──▶ 1 música: começa ──▶ SONG_PRACTICE
                                          ──▶ 2 a 5: lista     ──▶ SONG_PICKING
SONG_PICKING  ── número da lista   ──▶ começa           ──▶ SONG_PRACTICE
              ── 0 / stop / quit   ──▶ cancela          ──▶ IDLE
              ── outro texto       ──▶ nova busca       ──▶ (como /song)
SONG_PRACTICE ── 0 / stop / quit   ──▶ resumo           ──▶ SONG_SAVING (ou IDLE sem expressões)
              ── qualquer texto    ──▶ feedback + próximo verso ──▶ SONG_PRACTICE
                                       (no último verso: feedback + resumo ──▶ SONG_SAVING ou IDLE)
SONG_SAVING   ── números / all     ──▶ salva as escolhidas ──▶ IDLE
              ── 0 / stop / quit   ──▶ descarta            ──▶ IDLE
              ── outro texto       ──▶ é uma palavra nova  ──▶ explicar ──▶ AWAIT_ACTION
```

**Busca.** Com `- artista` (hífen, meia-risca ou travessão; "by" não separa, porque aparece em
títulos), busca por `track_name` + `artist_name`; se nada vier, repete a busca livre com o texto
inteiro. Sem artista, busca por `track_name` e, se nada vier, pela busca livre `q`. Dos resultados,
ficam só as músicas **com letra** (instrumentais saem), **em inglês** e **uma por artista** (a
fonte repete a mesma música em coletâneas, com o título sujo), com o título exato na frente, até
5. Uma candidata só: começa direto. Duas ou mais: lista numerada `N. *Título* — Artista`, com a
dica de mandar o nome com o artista se a certa não estiver lá. Número fora da lista repete a lista.

**Idioma** (`eh_ingles`): heurística sem IA — a proporção de palavras muito comuns do inglês (sem
as ambíguas com o português/espanhol, como "a", "no", "me") precisa ser de pelo menos 20%. Letras
em inglês ficam entre ~33% e ~65%; em português, espanhol, alemão ou coreano, abaixo de 5%. Se a
busca só achou versões em outro idioma, o bot explica que não dá para praticar inglês com uma
letra em outra língua e pede outra música.

**Versos** (`extrair_versos`): as linhas com conteúdo, na ordem, sem marcações (`[Chorus]`,
`(x2)`), sem as de uma palavra só ou só de interjeições (`oh oh`, `yeah yeah`) e **sem repetição**
(o refrão aparece uma vez). No máximo 40 versos por música.

**Turno** (como a revisão, seção 5.7): qualquer texto em `SONG_PRACTICE` é a explicação do verso
atual, em inglês ou português — sem roteamento por IA. Uma chamada de `Tutor.song_line` julga o
sentido (não a gramática) e aponta até 3 palavras/expressões do verso que o aluno não pegou; o
fluxo descarta as que não estão de fato no verso. A resposta é **uma mensagem só**: feedback e o
próximo verso, que sempre termina com `Type 0 to leave the practice.`:

```
🤔 Close! "Hold on" here means "wait / don't give up", not "hold something".
💬 The city is always awake and busy.

🎵 Line 4/6
_I wrote your name on a paper plane_
What does it mean? Explain in English or Portuguese.
_Type 0 to leave the practice._
```

**Fim** (último verso, `0` ou `/cancel`): o resumo diz quantos versos foram feitos e lista até 10
expressões acumuladas (sem repetir), oferecendo salvá-las: `1 3`, `1 and 3`, `all` ou `0`. Cada
escolhida é explicada por `Tutor.explain` com o verso como contexto (`expressão | verso`, o mesmo
formato da captura) e gravada como uma entrada `nova` com o exemplo do bot — todas as explicações
vêm antes de gravar qualquer uma, então uma falha da IA não deixa nada pela metade e a sessão
continua em `SONG_SAVING`. Sem expressões, o resumo não oferece nada e a sessão volta a IDLE.

**Direito autoral** (ADR-0016): as letras do LRCLIB não são licenciadas; o risco está aceito
enquanto o bot for de uso pessoal. Testes, fixtures, evals e o simulador usam **só letras
inventadas**; o prompt proíbe a IA de repetir o verso inteiro no feedback.

## 6. Contratos com a IA

Implemente em `app/services/llm.py` uma interface `LLMProvider` com duas implementações:

- `VertexGeminiProvider` (padrão): `google-genai` com `vertexai=True`, `project=GCP_PROJECT_ID` e `location=VERTEX_LOCATION`. Peça **saída estruturada** com o schema derivado do modelo Pydantic (JSON mode com schema), conforme a documentação atual da SDK para o modelo escolhido.
- `AnthropicProvider` (opcional): *tool use* com uma única ferramenta por tarefa (`input_schema` = schema Pydantic) e `tool_choice` forçando essa ferramenta.

As funções de negócio (`explain`, `evaluate`, `examples`, `expansions`, `synonyms`, `route`) não sabem qual provedor está em uso. Valide sempre com Pydantic, com 1 nova tentativa em caso de erro. No Vertex, o cliente `google-genai` retenta sozinho (4 tentativas, espera 1 s/2 s/4 s) os status 408, 429 e 5xx: o `429 RESOURCE_EXHAUSTED` acontece quando a capacidade compartilhada do modelo aperta, mesmo com volume baixo. O que sobrar de erro do provedor (`APIError`, falha de rede) vira `LLMError` (sem o corpo da resposta), e o aluno recebe "I couldn't reach the AI right now", não o aviso genérico de erro inesperado. Temperatura 0.2 a 0.3. Prompts em `app/services/prompts.py`, com o nível e o contexto do usuário ("brasileiro, trabalha numa empresa internacional, usa inglês técnico no dia a dia"). **M9:** toda saída voltada ao aluno é pedida em inglês — só `traducao` continua em português do Brasil.

```python
class Sense(BaseModel):
    id: str; traducao: str; definicao: str; exemplo: str  # exemplo: frase completa, alvo entre [[ ]]

class Explanation(BaseModel):
    ok: bool
    motivo_erro: str | None
    palavra: str                    # forma base, minúsculas
    classe: str                     # em inglês (verb, noun, adjective...)
    cefr_estimado: Literal["A2","B1","B2","C1","C2"]
    sentidos: list[Sense]           # 1 a 4, só os comuns, do mais popular ao menos (M31); um sentido pedido fora dos comuns entra na lista
    sentido_do_contexto: str | None # M9: a IA sempre escolhe um id (nunca null): o da frase, o pedido ou o mais popular
    frase_contexto: str | None      # frase do usuário corrigida, alvo entre [[ ]]; null se não houve frase (M31: também quando o que veio após `|` foi um pedido de sentido)
    nota: str                       # em inglês
    tags: list[Literal["trabalho","phrasal_verb","expressao"]]

class Evaluation(BaseModel):
    usa_palavra_alvo: bool          # considera flexões
    sentido_correto: bool
    veredito: Literal["correta","correta_pouco_natural","quase","incorreta"]
    correcoes: list[str]            # "wrong → right"
    versao_natural: str             # alvo entre [[ ]]
    explicacao: str                 # em inglês, máx. 4 linhas

# examples(palavra, sentido, nivel, n=3, ja_mostrados, palavras_do_aluno) -> list[str]  (alvo entre [[ ]])

class Expansion(BaseModel):
    expressao: str; traducao: str
    tipo: Literal["colocacao","familia","phrasal_verb","sinonimo","expressao"]
# expansions(palavra, sentido, nivel, ja_existentes) -> list[Expansion]  (3 a 5, sem repetir o que já existe)
# Case D (seção 5.5) usa só as 3 primeiras, como sugestão em texto — não cria entradas.

class Synonym(BaseModel):
    expressao: str; significado: str; exemplo: str  # exemplo com o SINÔNIMO marcado entre [[ ]]
# synonyms(palavra, sentido, nivel, n=3, ja_mostrados) -> list[Synonym]  (1 a 10, sem repetir)

# Roteamento de texto livre (M9, ADR-0009): uma única chamada que classifica e já responde.
# Achatado de propósito (sem objeto aninhado opcional) para caber bem no response_schema do Gemini.
class Roteamento(BaseModel):
    intencao: Literal["frase","exemplos","sinonimos","salvar","nova_palavra","pedido","fora_do_escopo"]
    quantidade: int              # exemplos | sinonimos, padrão 3 (o fluxo limita a 1-10)
    palavra: str                 # nova_palavra
    resposta: str                # pedido | fora_do_escopo, em inglês
    # frase: os campos abaixo formam a mesma Evaluation de cima
    usa_palavra_alvo: bool; sentido_correto: bool; veredito: str
    correcoes: list[str]; versao_natural: str; explicacao: str
# route(palavra, sentido, texto, nivel) -> Roteamento

# Desafio semanal (M36, seção 5.2b, ADR-0034): perguntas no nível da turma com palavras do vocabulário.
class PerguntaSemanal(BaseModel):
    pergunta: str          # inglês, com as palavras do vocabulário entre [[ ]]
    palavras: list[str]    # >= 1, só do vocabulário enviado
    explicacao_en: str     # máx. 4 linhas
    explicacao_pt: str     # só A1-A2/A2-B1 (obrigatória); vazia nos demais
# weekly_questions(vocabulario: [(palavra, definicao)], nivel, n) -> list[PerguntaSemanal]  (exatamente n)

class AvaliacaoDaPergunta(BaseModel):
    qualidade: Literal["de_novo","dificil","bom","facil"]; feedback: str; correcao: str  # feedback em inglês, máx. 4 linhas
# weekly_answer(pergunta, palavras, resposta, nivel) -> AvaliacaoDaPergunta  (modelo de avaliação)

# Revisão espaçada (M10, seção 5.7, ADR-0011): julga a resposta livre do aluno numa revisão.
class Revisao(BaseModel):
    tipo: Literal["definicao","frase","nao_sei","outro"]
    qualidade: Literal["de_novo","dificil","bom","facil"]
    feedback: str        # em inglês, máx. 4 linhas
    correcao: str         # só quando ajuda (qualidade != "facil"); vazio senão
# review(palavra, sentido, resposta, nivel) -> Revisao

# Prática com música (M13, seção 5.8, ADR-0016): julga a explicação de um verso (EN ou PT).
class LinhaDaMusica(BaseModel):
    compreensao: Literal["entendeu","parcial","nao_entendeu"]
    feedback: str           # em inglês, máx. 4 linhas; nunca repete o verso inteiro
    significado: str        # o sentido do verso em inglês simples, quando não entendeu; vazio senão
    expressoes: list[str]   # até 3, copiadas do verso: o que o aluno não pegou
# song_line(titulo, artista, verso, verso_anterior, resposta, nivel) -> LinhaDaMusica  (modelo de avaliação)
```

**Qualidade:** `evals/sentencas.yaml` (~15 casos de frase + veredito esperado) e `evals/roteamento.yaml`
(um caso por intenção do `Roteamento`), medidos com `python -m evals.run [--tarefa avaliacao|roteamento] [--provider vertex_gemini|anthropic] [--model ID]` contra a API real. Assim comparo modelos antes de escolher. Fica fora do pytest.

## 7. Dados

### 7.1 Firestore
Desde o M14 (ADR-0017) tudo abaixo de `profile/me` até `entries/{slug}/sentences` vive dentro de um
**espaço**, `espacos/{espaco_id}/...`, com `espaco_id` o chat id (`NUMERO@c.us` no privado). O
documento `espacos/{espaco_id}` guarda `{tipo:"privado"|"grupo", criado_em, proximo_tick?}`, em que
`proximo_tick` espelha o perfil para o agendador achar os lembretes vencidos com uma consulta só.
`processed/` e `lids/` continuam globais. Os caminhos abaixo são relativos ao espaço.
```
profile/me                 { nivel, criado_em, nome?,
                             lembretes_por_dia, janela_inicio, janela_fim, chat_id?,
                             proximo_lembrete?, lembrete_sem_resposta, avisou_lembretes }
                           # M10 (seção 5.7): lembretes_por_dia=0 é desligado (padrão); chat_id é o
                           # destino real, aprendido de uma mensagem recebida (nunca o .env direto)
                           # M28 (seção 12): nome é o "push name" do WhatsApp, só no privado
session/current            { estado, entry_id, sentido_id, sinonimos_mostrados, entrada_criada_agora, atualizado_em,
                             revisao_fila, revisao_atual?, revisao_feitas, revisao_lapsos, revisao_total,
                             musica_opcoes, musica_titulo?, musica_artista?, musica_versos,
                             musica_indice, musica_expressoes }
                           # entrada_criada_agora: a opção 5 do menu só apaga entrada criada nesta captura
                           # M9: sinonimos_mostrados evita repetir e troca o rótulo do menu
                           # ("Check synonyms" -> "See more synonyms") depois da 1ª vez
                           # M10: os 5 campos de revisao_* só valem com estado=REVIEWING
                           # M13 (seção 5.8): musica_opcoes = [{id, titulo, artista}] em SONG_PICKING;
                           # musica_versos/indice em SONG_PRACTICE; musica_expressoes =
                           # [{texto, verso}] acumuladas e oferecidas para salvar em SONG_SAVING
entries/{slug}             { palavra, classe, cefr_estimado, sentido:{traducao,definicao}, outros_sentidos,
                             sinonimos, nota, tags, origem_texto, origem:"usuario"|"expansao", pai?, autor_id?,
                             status:"nova"|"praticada", exportado, criado_em, atualizado_em,
                             repeticoes, intervalo_dias, facilidade, lapsos, proxima_revisao?, revisada_em?,
                             audio_palavra?, audio_exemplo? }
                           # M23: links (gs://) dos áudios de pronúncia; só registro, o cache por hash manda
                           # M12: sinonimos = [{expressao, significado, exemplo}] já mostrados ao aluno
                           # M10: campos de SM-2 simplificado (ADR-0011); proxima_revisao=None
                           # é um cartão novo, vencido desde já
                           # M28 (seção 12): autor_id é quem salvou, só em grupo (None no privado)
entries/{slug}/sentences/{auto}  { texto, autor:"usuario"|"bot", autor_id?, veredito?, correcoes?, versao_natural?, explicacao?, criado_em }
                           # M12: versao_natural é a frase do aluno já corrigida pela IA (também nas revisões)
processed/{message_id}     { criado_em, expira_em }     # deduplicação; política de TTL de 7 dias
                           # M15: `processed/aviso_{sha256(numero)}` é a marca do aviso "sem plano" (1 por semana)
admins/{numero}            { adicionado_em, adicionado_por }          # M15 (ADR-0018): os admins, além do dono
grupos_pendentes/{grupo}   { visto_em }   # M15: grupo em que o bot está sem ativação; sai depois de 24h
                           # espacos/{grupo} ganha, ao ativar: ativo, nome?, ativado_por, ativado_em
espacos/{grupo}/membros/{numero}  { papel:"aluno"|"professor", nome?, entrou_em, marcado_em? }   # M16 (marcado_em: M17)
espacos/{grupo}/respostas/{auto}  { entry, autor_id, marcado, qualidade, criado_em }              # M17 (marcado é sempre false desde o M35)
                           # M17: session/current ganha marcado_id, marcacao_expira_em, marcacao_tentativas; espacos/{grupo}
                           # ganha timeout_em (espelho do prazo, para o agendador)
                           # M36: profile/me ganha semanal_ligada, semanal_dia (0=segunda), semanal_hora, semanal_minuto,
                           # semanal_tamanho?, proxima_semanal; session/current ganha semanal_perguntas, semanal_indice,
                           # semanal_respondidas, semanal_puladas (estado WEEKLY_QUIZ; marcado_id/marcacao_expira_em reaproveitados);
                           # no grupo `proximo_tick` espelha o menor entre proxima_diaria e proxima_semanal
                           # M35: profile/me ganha diaria_ligada, diaria_hora, diaria_minuto, diaria_fim_de_semana,
                           # proxima_diaria, revisoes_sem_resposta; session/current ganha revisao_puladas;
                           # no grupo `proximo_tick` espelha `proxima_diaria`; marcacao_expira_em = fechamento por inatividade (3h)
lids/{lid}                 { numero }                   # cache LID -> número (seção 8.2), evita consultar o WAHA a cada mensagem
meta/snapshot               { ultimo_dia }              # M28: último dia (AAAA-MM-DD) do snapshot diário de métricas
```
- `slug`: minúsculas, `[^a-z0-9]+` → `-`. Se o mesmo slug surgir com outro sentido, use o sufixo `--s2`. "Outro sentido" só vale com frase de contexto e com traduções sem nenhuma opção em comum (separadas por `,`, `;`, `/` ou `ou`, ignorando acento e o que está entre parênteses); a IA reescreve a tradução a cada chamada, e a palavra sozinha, sem frase, nunca abre um sentido novo (ADR-0023).
- Duas interfaces (Protocol): o `Repository`, o caderno de um espaço, e o `Banco`, a raiz, que entrega o caderno em `do_espaco(espaco_id)` e guarda a deduplicação (`create()`, que falha se o ID já existe), o cache de LIDs, `listar_espacos_com_lembrete` e, para o snapshot de métricas (M28, seção 12), `listar_espacos` (todos os espaços já escritos, ativos e desativados), `listar_admins_detalhado` e `obter_ultimo_snapshot`/`marcar_snapshot`. Implementações: `FirestoreBanco`/`FirestoreRepository` e `MemoryBanco`/`MemoryRepository`, com o mesmo teste de contrato.
- Migração do formato antigo (raiz do banco): `python -m scripts.migrar_multiusuario` (dry run por padrão, `--executar`, `--limpar-origem`), roda na máquina local com as credenciais padrão.

### 7.2 Status e frase do cartão
- Uma entrada fica `praticada` quando tem ao menos uma frase do usuário avaliada; senão, é `nova`.
- A frase do cartão é a melhor frase **do usuário** (`correta`, senão a `versao_natural` mais recente). Se não houver, use o primeiro exemplo do bot.

### 7.3 Export em planilha Excel (M12, ADR-0014)
`/export` gera um `.xlsx` (openpyxl) com **todas** as palavras, em três abas. Cabeçalho em negrito e
congelado; datas em UTC, sem fuso (o Excel não guarda fuso).
- **Words** (uma linha por entrada): `#`, `Word`, `Class`, `CEFR`, `Translation`, `Definition`,
  `Other senses`, `Note`, `Tags`, `Status`, `Source text`, `Best sentence`, `Created`, `Last review`,
  `Next review`, `Repetitions`, `Lapses`, `Ease`. `Best sentence` segue a regra da seção 7.2, sem `[[ ]]`.
- **Sentences** (uma linha por frase, do aluno e do bot): `#`, `Word`, `Author` (`you`|`bot`),
  `Sentence`, `Corrected version`, `Verdict`, `Corrections`, `Explanation`, `Date`.
- **Synonyms**: `#`, `Word`, `Synonym`, `Meaning`, `Example`.

O campo `exportado` das entradas deixou de ser usado (a planilha é sempre um retrato completo).

**Entrega (ADR-0015):** o bot envia o `.xlsx` direto no chat, como documento, com uma legenda curta
(`Channel.send_file`, `POST /api/sendFile` com o arquivo em base64). Sem texto separado e sem link.
**Plano B:** se o envio falhar, o bot sobe o mesmo arquivo no bucket e manda o link. O upload em `gs://$EXPORT_BUCKET/exports/vocabot_AAAA-MM-DD_HHMM.xlsx` (hora em UTC), com
content-type `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, e **URL assinada V4
válida por 24 h**. Na VM não há chave privada, então assine via IAM `signBlob`: a conta de serviço da
VM precisa do papel `roles/iam.serviceAccountTokenCreator` **sobre ela mesma**, e use
`service_account_email` + `access_token` no `generate_signed_url`. O bucket tem uma regra de ciclo de
vida que apaga objetos após 7 dias.

### 7.4 Pronúncia em áudio (M23/M25/M26, ADR-0024, ADR-0026, ADR-0027)

`app/flows/pronuncia.py:ouvir` manda a voz do termo e, com `com_frase=True` (padrão), a da frase do
card (a do bot mais antiga da entrada, sem os `[[ ]]`). Entrada sem frase do bot recebe só a voz do
termo. Três formas de chamar, pelos parâmetros `anunciar`/`com_frase`:

- **Automático ao explicar** (M25, `anunciar=False, com_frase=True`, logo depois de explicar a
  palavra — nova ou já existente, seção 5.1): as duas vozes, sem texto antes nem depois (a
  explicação + o menu, já mandados, bastam). Sem serviço de áudio configurado neste ambiente, fica
  **em silêncio** — ninguém pediu áudio explicitamente. Uma falha de verdade (TTS, Storage,
  WhatsApp) ainda avisa (`ERRO_AUDIO`): quebrar em silêncio pareceria o bot ignorando o aluno.
- **Automático na revisão** (M26, `anunciar=False, com_frase=False`, seção 5.7, só no privado):
  cada card vem seguido só da voz do termo — a frase de exemplo não repete, o objetivo é lembrar o
  som, não reouvir o card inteiro. Mesma regra de silêncio/aviso do automático ao explicar. No
  grupo não roda: o orçamento de 3 mensagens já é disputado pelo repasse e pelo fechamento da
  rodada (ADR-0020).
- **Sob demanda** (`/listen N|palavra`, `anunciar=True, com_frase=True`, não abre a palavra): um
  texto antes, `🔊 *termo*` com a frase de exemplo, e as duas vozes. Sem serviço de áudio
  configurado, avisa (`ERRO_AUDIO`) — aqui a pessoa pediu explicitamente, então o silêncio seria
  confuso.

**Síntese:** interface `Sintetizador` (`app/services/tts.py`), implementada por `GoogleTts`
(Cloud Text-to-Speech, `AudioEncoding.OGG_OPUS`, voz de `TTS_VOICE`, conta de serviço da VM) e por
`FakeSintetizador` (testes e simulador).

**Cache:** `ServicoAudio` (`app/services/audio.py`) grava em `gs://$AUDIO_BUCKET/audio/<voz>/<sha256[:32]>.ogg`,
com o hash de `voz + texto` (espaços normalizados, caixa mantida). O bucket é privado e **sem** ciclo de
vida; é compartilhado entre espaços. Hit lê o objeto; miss sintetiza, grava e devolve. O link `gs://`
vai para `Entry.audio_palavra` / `Entry.audio_exemplo` quando muda.

**Envio:** `Channel.send_voice` (`POST /api/sendVoice`, `mimetype: audio/ogg; codecs=opus`, base64,
`convert: false`), com timeout de 90 s e **sem** retentativa. `Conversa.enviar_voz` respeita o limite
de 3 mensagens seguidas (a explicação/menu + as duas vozes, ou o texto do `/listen` + as duas vozes,
usam os 3). Qualquer falha de verdade (TTS, Storage, WhatsApp) vira `ERRO_AUDIO`, sem derrubar a
conversa (ver seção 5.1 sobre o caso de áudio não configurado).

## 8. Canal: WAHA

### 8.1 Recebimento (`app/main.py`)
- O WAHA envia webhooks para `http://bot:8000/waha/webhook`, pela rede interna do compose; a porta do bot **não** é publicada. Assine só os eventos `message`, `session.status` e `group.v2.join` (M15: o bot foi adicionado a um grupo; o payload traz `group.id`/`group.subject` e **não** diz quem adicionou).
- Se o WAHA suportar HMAC de webhook, configure e valide. Se não, confie na rede interna, que fica isolada.
- Para cada evento `message`:
  1. **Ignore `fromMe == true`**, para o bot não responder a si mesmo e não entrar em loop.
  2. Ignore grupos (`@g.us`), status/broadcast e canais. Grupo não autorizado (fora de `ALLOWED_GROUPS`): o id vai ao log em INFO uma vez por processo, para o dono descobri-lo e autorizá-lo; nada mais sobre a mensagem é logado.
  3. Aplique a allowlist (8.2). Número fora da lista, no privado, recebe só o aviso de "sem plano" (no máximo 1 por semana) e a IA nunca é chamada; admin que não é aluno só usa `/groups`. Em `@g.us` (M15/M16): grupo não ativado só reage a `!activate` de um admin e fica pendente; grupo ativo só lê comandos (`!` ou `/`) e mensagens que marcam o bot (5.2b, M37), depois da resolução do participante (LID pelo cache `lids/`), da deduplicação e do `sendSeen`. O resto é ignorado sem ler, gravar nem marcar como lido.
  4. Deduplique pelo `id` da mensagem.
  5. Faça `sendSeen` e despache ao roteador, com a lógica síncrona em threadpool. A conversa (IA, atrasos "humanos") roda em segundo plano, depois do 200 (M4, ADR-0006).
  6. **Sempre** devolva 200. Registre as exceções e mande ao usuário uma mensagem curta de erro.
- Mídia (`hasMedia`, áudio, figurinha etc.): no privado, responda que o MVP só entende texto (o M23 só **envia** áudio). No grupo (M39, 5.2b) só a nota de voz que cita uma mensagem do bot é lida; o resto é ignorado.
- `session.status`: registre no log. Se o status sair de `WORKING`, registre em nível WARNING.
- `GET /health`: `{"ok": true}`, usado pelo healthcheck do compose.

### 8.2 Allowlist e identificadores
- Em conversas 1:1, o `from` costuma vir como `NUMERO@c.us`, mas o WhatsApp também usa **LIDs** (`...@lid`). Aceite a mensagem se o número extraído bater com algum de `ALLOWED_NUMBERS` (ou o `ALLOWED_NUMBER` legado; M14), comparando as variantes com e sem o 9 depois do DDD. Cada número é um espaço. Se vier um LID, resolva o número usando o endpoint de LIDs do WAHA (confira na documentação) e guarde o mapeamento em cache no Firestore.
- **Envie sempre para o chatId do remetente autorizado**: o número que o WhatsApp informa (`NUMERO@c.us`, ou o `pn` resolvido do LID), nunca para outro chat. Ele bate com o número da allowlist a menos do nono dígito brasileiro: contas antigas são registradas **sem** o 9, e enviar para o número com o 9 falha no WAHA com "no LID found" (visto no deploy real).

### 8.3 Cliente (`app/channel/waha.py`)
Implemente `send_text`, `send_file`, `send_voice`, `send_seen`, `typing(on/off)`, `session_status` e `download_media` (M39: baixa `media.url` pelo caminho, com o host e a API key do bot), com o header `X-Api-Key` (ou o nome atual segundo a documentação). Timeouts de 15 s, até 2 novas tentativas com backoff para 5xx, logs **sem** a API key. `send_file` e `send_voice` são a exceção: timeout de 90 s e **sem** retentativa (reenviar uma resposta lenta duplicaria o arquivo ou o áudio; quem chama decide o plano B).

### 8.4 Adaptador de canal
Crie a interface `Channel` (enviar texto, enviar arquivo, enviar voz, marcar como lido, digitando) com as implementações `WahaChannel`, `ConsoleChannel` (simulador) e `FakeChannel` (testes). A lógica de negócio **não** pode importar nada do WAHA diretamente, para que seja possível trocar por Cloud API ou Telegram no futuro.

## 9. Marcos (pare ao fim de cada um)

| # | Entrega | Critério de aceite |
|---|---|---|
| M0 | Estrutura do repo, dependências, ruff, pytest, `.gitignore`, `.dockerignore`, `Dockerfile` do bot, `.env.example` | `pytest` e `ruff check` passam |
| M1 | `main.py` (webhook do WAHA, health), parser de eventos, allowlist com LID, deduplicação, cliente WAHA, interface `Channel` | Testes com payloads de exemplo em `tests/fixtures/`: texto, `fromMe`, grupo, mídia, número não autorizado, LID, duplicado, `session.status` |
| M2 | Modelos, `Repository` (memória e Firestore), máquina de estados, parser de escolhas numéricas | Testes de todas as transições da seção 5.1, incluindo os atalhos |
| M3 | `llm.py`, `prompts.py`, schemas, `FakeLLM`, `evals/` | Testes com o fake; `python -m evals.run` funciona se houver chave |
| M4 | Fluxos e comandos completos | Teste de ponta a ponta do ciclo "stall" com fakes |
| M5 | Export para o Anki + upload e URL assinada (com fake de storage nos testes) | O `.txt` bate byte a byte com o arquivo esperado (substituído pelo Excel no M12) |
| M6 | **Simulador de terminal** `python -m sim` (`ConsoleChannel` + `MemoryRepository`; `--real-llm` opcional) | Consigo fazer o ciclo completo no terminal |
| M7 | `docker-compose.yml` (waha + bot), `infra/` (seção 10), README com o runbook | `docker compose config` válido; scripts passam em `bash -n` e `shellcheck`; nenhum segredo versionado |
| M8 | Provisionar e fazer o deploy na VM, comigo aprovando cada comando; parear o WhatsApp; smoke test | O WAHA está em `WORKING` e o bot responde `/ajuda` no WhatsApp |
| M9 | Interface em inglês (só 🇧🇷 em PT-BR), máquina de estados reduzida a `IDLE`/`AWAIT_ACTION` com um único menu de ações, roteamento de texto livre por uma chamada de IA (`Tutor.route`, ADR-0009), sinônimos (`Tutor.synonyms`), expansões viram sugestão em texto (sem menu) | `make check` passa; ciclo completo no `sim` bate a seção 5.5; `python -m evals.run --tarefa roteamento` roda contra a API real |
| M10 | Revisão espaçada (SM-2 simplificado, ADR-0011) com sessão `REVIEWING`, `/reminders` e `/review`, agendador em segundo plano (`Agendador`, ADR-0012) | `make check` passa; `make test-emulador` valida os campos novos no Firestore real; ciclo completo de revisão no `sim`; nenhum lembrete dispara sem `chat_id` conhecido |
| M12 | Comandos em inglês (apelidos PT escondidos), `/list` numerado e paginado, `/info`, `/profile`, sinônimos e frases corrigidas persistidos na entrada, `/export` em planilha Excel no lugar do arquivo do Anki (ADR-0014) | `make check` passa; `make test-emulador` valida `sinonimos` no Firestore real; `/export` no `sim` gera um `.xlsx` com as 3 abas |
| M13 | Prática com letra de música (seção 5.8, ADR-0016): `/song nome [- artista]`, busca no LRCLIB atrás de `LyricsProvider`, escolha entre homônimas (`SONG_PICKING`), recusa de letra fora do inglês, verso a verso com `Tutor.song_line` (`SONG_PRACTICE`), oferta de salvar as expressões não entendidas (`SONG_SAVING`) | `make check` passa; ciclo completo de `/song` no `sim` (escolha, prática, `0`, salvar e a recusa em português); nenhuma letra real em testes, fixtures ou evals |
| M14 | Multiusuário por espaço (ADR-0017, `spec/plano-turmas.md`): `espacos/{chat}/...`, `Banco` + `Repository`, `ALLOWED_NUMBERS`/`ALLOWED_GROUPS`/`OWNER_NUMBER`, trava e `Conversa` por espaço, agendador por espaço, `scripts.migrar_multiusuario` | Dois alunos no privado isolados (palavras, sessão, `/list`, `/export`, lembretes); migração com dry run, idempotente e `--limpar-origem` seguro; testes antigos do privado passam |
| M15 | Controle de acesso (ADR-0018): admins no Firestore (`/admin`), grupo ativado só por `!activate` de um admin (`/groups`, `MAX_GROUPS`), grupo não ativado sai em 24 h (`group.v2.join`, `Channel.leave_group`), aviso "sem plano" a número fora da lista sem chamar a IA | Estranho recebe 1 aviso por semana e `FakeTutor.chamadas == []`; `!activate` de não admin não grava nem envia nada; limite respeitado; pendente sai em 24 h (relógio controlado) e ativado antes não sai |
| M16 | Bot em grupo com prefixo `!` (ADR-0019, seção 5.2b): filtro de prefixo antes de tudo, conjunto fechado de comandos, `!teacher`/`!student`, `membros/`, `autor_id`, textos com o prefixo do espaço, `sim --grupo` | Grupo ativo com/sem prefixo (nada gravado, nenhum `sendSeen`), participante LID, mídia; cada comando; comando do privado recusado; `!` fora de atividade sem IA; ciclo "stall" com dois alunos no `sim --grupo` |
| M17 | Revisão em grupo com menção em rodízio (ADR-0020, seção 5.2b): `send_text(mentions=)`, participantes do grupo, `domain/rodizio.py`, marcação por card, resposta do marcado vs. de outro, timeout no agendador (uma consulta por tick), `respostas/` | Rodízio (distribuição justa, professores excluídos, sem repetição seguida); resposta de não marcado sem nota; timeout com relógio controlado; menções no `FakeChannel`; rodada completa no `sim --grupo` |
| M11 | Deploy contínuo via GitHub Actions (seção 10.9, ADR-0013): branch protection na `main` (PR + checks obrigatórios), job `deploy` automático no merge, autenticado por Workload Identity Federation | Push direto na `main` é bloqueado pelo GitHub; um PR com CI verde, ao ser mergeado, dispara o job `deploy` e o bot responde `/help` depois do smoke test |
| M23 | Pronúncia em áudio sob demanda (seção 7.4, ADR-0024): opção 1 e `/listen`, `Sintetizador` (Google Cloud TTS) atrás de interface, cache por hash em bucket permanente, `Channel.send_voice` | Cache miss sintetiza e grava, hit não chama o TTS; duas vozes (termo e frase) na ordem; falha do TTS/envio só avisa; `send_voice` sem retentativa; `Entry` persiste os links; `make check` verde; `sim` grava os `.ogg` |
| M24 | Lembretes ligados por padrão, 1x às 12h, só para perfil novo (seção 5.7, ADR-0025); tamanho da fila de revisão configurável (`/reviewsize`, ou o último parâmetro de `/reminders`), padrão dinâmico `MIN(palavras do aluno, 7)` | `make check` passa; perfil novo nasce com lembrete ligado, perfil existente não muda sozinho; `/reviewsize`/`/reminders` fixam e resetam o tamanho da fila; `/profile` mostra o tamanho efetivo |
| M25 | Pronúncia automática ao explicar a palavra, nova ou já existente (seção 5.1/7.4, ADR-0026): sai a opção 1 (ouvir) do menu, que passa a começar no 2 sem renumerar as demais; `/listen` continua sob demanda | `make check` passa; explicar uma palavra manda a explicação/menu e, na sequência, as duas vozes (sem serviço de áudio configurado, fica em silêncio); `/listen` continua avisando se não há áudio; nenhuma opção "1" sobra no menu |
| M26 | Pronúncia automática do termo em cada card de revisão, só no privado (seção 5.7/7.4, ADR-0027) | `make check` passa; cada card no privado manda a voz do termo, sem a frase; o grupo não manda áudio na revisão (orçamento de 3 mensagens preservado para repasse/fechamento) |
| M27 | Eventos estruturados nos logs e handler para o Cloud Logging (seção 12, ADR-0028, `spec/plano-dashboard.md`) | `make check` passa; catálogo de eventos emitido nos pontos da seção 12; nenhum evento carrega número completo nem texto do aluno; `configurar_logs` sem `handler_extra` continua igual (dev/CI nunca falam com a nuvem) |
| M28 | Snapshot diário de métricas em NDJSON no GCS (seção 7.1/12, ADR-0029, `spec/plano-dashboard.md`): `Entry.autor_id`, `Profile.nome`, `Banco.listar_espacos`/`listar_admins_detalhado`/`obter_ultimo_snapshot`, `services/snapshot.py`, `services/metricas_destino.py`, `python -m scripts.snapshot`, `infra/bq/*.json`, `infra/setup_metricas.sh` | `make check` e `make test-emulador` passam; `montar_snapshot` testado com `MemoryBanco` (espaço vazio, privado com termos/frases, grupo com autor_id, admins × grupos); esquema de `infra/bq/*.json` bate com as dataclasses (teste reprova divergência); `scripts.snapshot --dry-run` só lê, `--executar` grava e marca o dia; snapshot falhando nunca derruba os lembretes |
| M31 | Palavra de qualquer nível/gíria e pedido de sentido `palavra | sentido` (seções 5.1/5.2b/5.3/5.5, ADR-0030): prompt de `explain` sem recusa por nível, card com `↔️` e dica, `Acao.EXPLICAR_COM_CONTEXTO` sem IA de roteamento, troca do card recém-criado, `!add` do mesmo termo com `|` | `make check` passa; card com outros sentidos lista `↔️` e a dica (com `!add` no grupo), com um sentido só não muda; `palavra | sentido` logo após o card troca o card (só depois de a IA responder; com frase do aluno vira `--s2`); em `IDLE`, pedido de sentido de palavra já salva abre outro card em vez de "já existe"; `palavra | x` com outra palavra salva a atual e explica a nova, sem `route` |
| M32 | `!delete palavra\|número` no grupo (seção 5.2b): reaproveita `commands.apagar` do privado | `make check` passa; `!delete` por palavra e por número apaga a entrada e as frases da turma; inexistente e sem argumento respondem com o prefixo do grupo; apagar a palavra aberta zera a sessão; a ajuda do grupo lista `!delete` |
| M33 | `!level` no grupo (seção 5.2b, ADR-0031) e opção 5 do menu renomeada para "Don't save" | `make check` passa; `!level` sem argumento mostra o nível a qualquer membro; com argumento, professor e dono mudam só o perfil da turma, aluno recebe `nivel_so_professor` e nada muda; nível inválido recusa; a ajuda do grupo lista `!level`; o menu mostra `5️⃣ Don't save` |
| M34 | Seis níveis (A1-A2 a C2) e turma só em inglês de B1-B2 para cima (seções 5.2b/5.3/5.5, ADR-0032): `nivel_so_ingles`, `Deps.so_ingles`, formatadores com `pt` | `make check` passa; grupo A1-A2/A2-B1 mostra 🇧🇷 e `!list` com tradução; grupo B1-B2 em diante não mostra 🇧🇷 nem tradução em card, exemplos, sinônimos e `!list`; privado B1-B2 segue com 🇧🇷; todo nível tem calibração no prompt |
| M35 | Revisão diária do grupo sem marcar ninguém (seções 5.2b/5.7/7.1, ADR-0033, substitui o ADR-0020): `!daily`, `Profile.diaria_*`, `domain/agenda_grupo.py`, `!skip`/`!skipall` (e `/skip`, `/skip-all`, `/1`-`/3` com barra), fechamento após 3h parado, pausa após 3 revisões sem resposta | `make check` e `make test-emulador` passam; diária às 19h em dia útil (sexta à noite agenda segunda; `weekends on` agenda sábado); qualquer aluno responde e a 1ª resposta aceitável avança, a errada deixa a palavra aberta; `skip` não mexe na nota; `skipall` resume; 3h parado fecha; 3 revisões sem mensagem pausam e uma mensagem volta; só admin do bot muda `!daily`; `/skip` lido no grupo e `/list` não |
| M36 | Desafio semanal do grupo (seção 5.2b/6/7.1, ADR-0034): `!weekly`, `Profile.semanal_*`, estado `WEEKLY_QUIZ`, `Tutor.weekly_questions`/`weekly_answer`, marcação em rodízio, menu `/1` explicar (PT→EN em turma iniciante, só EN de B1-B2), `/2` ouvir, `/3` pular | `make check` e `make test-emulador` passam; sexta 13h dispara (outro dia não; `off` não); uma pergunta por aluno, mensagem começa pela menção; só o marcado avança, outro recebe feedback; `1` PT+EN em A1-A2/A2-B1 e só EN em B2; `2` manda voz e sem áudio avisa; `3`/`skip` pulam, `skipall` encerra; 3h parado fecha; só admin do bot muda `!weekly`; perguntas com o Gemini real conferidas em A1-A2, B1-B2 e C2 |
| M37 | Grupo responde a quem marca o bot e comandos valem com `!` ou `/` (seções 5.2b/8.1, ADR-0035, muda a regra do ADR-0019): filtro do webhook por marcação (`mentionedIds` número/LID ou `@numero`), `Router.processar(marcado=)`, `grupo.tratar(marcado=)`, menus e cartões do grupo com "tag me", `!add` escondido da ajuda, `weekly_answer` julga coerência com a pergunta sem cobrar o vocabulário | `make check` passa; `@bot stall` num grupo ativo adiciona a palavra; `@bot 4`/`@bot a frase` respondem menu, revisão e desafio; marcar outra pessoa ou conversar não chama o bot (nada gravado, sem `sendSeen`); marcação por LID resolvida; `@bot !help` é comando; `/help` e `/list` valem; `@bot` sozinho mostra a ajuda; a avaliação do desafio não exige as palavras (prompt) |
| M38 | Grupo responde a quem cita uma mensagem do bot (seções 5.2b/8.1, ADR-0036): `MessagePayload.reply_to`/`ids_do_autor_citado`, `_responde_ao_bot` no webhook | `make check` passa; citar o bot (replyTo/contextInfo, número/LID) responde sem marcar; citar outra pessoa não; citar o bot com `!cmd` vale como o comando; mídia citando o bot segue ignorada |
| M39 | Nota de voz no grupo, transcrita pelo Gemini, só quando cita uma mensagem do bot (seções 5.2b/8.1/8.3, ADR-0037): `MessagePayload.media`/`eh_audio`, `ChannelComLid.download_media`, `Transcritor` + `FakeTranscritor`, `GEMINI_MODEL_AUDIO`, `messages.audio_transcrito` | `make check` passa; áudio citando o bot vira `🎙️ _texto_` + resposta comum; áudio sem citação, citando outra pessoa ou outra mídia: nada lido, gravado nem marcado como lido; longo, sem fala, sem transcritor e falhas só avisam; `download_media` usa o host e a API key do bot |
| M40 | Limite de caracteres por mensagem (seções 4/5.6): `MAX_CARACTERES` (padrão 500), checado no `Router.processar` antes do banco e da IA (ADR-0038) | `make check` passa; texto de 501 caracteres recebe `texto_longo_demais` sem chamar o tutor, no privado e no grupo; 500 passa; conversa entre pessoas no grupo segue ignorada |
| M41 | Limite de duração e de bytes do áudio (seções 5.2b/8.3): `MAX_SEGUNDOS_AUDIO` (padrão 60) lido do `audioMessage.seconds`, `download_media(max_bytes)` em streaming, teto de 1 MB, eco da transcrição cortado em 300 caracteres (ADR-0039) | `make check` passa; áudio com `seconds` acima do teto ou `fileLength` acima de 1 MB é recusado sem baixar; sem os campos, o download aborta ao passar de 1 MB sem ler o resto; o eco da transcrição passa de 300 caracteres só com `…` |

**Opcional antes do M8:** subir o compose localmente (`docker compose up`) e parear um teste no próprio computador. Se fizer isso, use um volume de sessão separado, porque o número só pode ter uma sessão do WAHA ativa por vez.

## 10. Infraestrutura (GCP)

Pré-requisitos, que eu garanto: `gcloud` autenticado, projeto definido, faturamento ativo (trial) e papel de Owner.

### 10.1 `infra/config.sh` + `infra/.env.infra` (no `.gitignore`, com `.env.infra.example`)
Contém `GCP_PROJECT_ID` (lido do `.env.infra`; se vazio, de `gcloud config get-value project`), `REGION=us-central1`, `ZONE=us-central1-a`, `VM_NAME=vocabot-vm`, `SA_NAME=vocabot-vm`, `EXPORT_BUCKET=${PROJECT_ID}-vocabot-exports`, `AUDIO_BUCKET=${PROJECT_ID}-vocabot-audio`, `TTS_VOICE` e os valores não secretos da seção 4.

Exemplo de `infra/.env.infra.example`:
```dotenv
GCP_PROJECT_ID=
ALLOWED_NUMBER=      # número pessoal do usuário (o dono), só dígitos
ALLOWED_NUMBERS=     # opcional (M14): alunos, separados por vírgula
ALLOWED_GROUPS=      # opcional (M14): ids @g.us autorizados, separados por vírgula
OWNER_NUMBER=        # opcional (M14): o dono; padrão o ALLOWED_NUMBER
BOT_NUMBER=          # número Vivo do bot, só dígitos
LLM_PROVIDER=vertex_gemini
GEMINI_MODEL=        # preencher com o ID confirmado na documentação
GEMINI_MODEL_EVAL=
VERTEX_LOCATION=global
USER_LEVEL=B1-B2
```

### 10.2 `infra/setup.sh` (idempotente)
1. Ativar as APIs `compute`, `firestore`, `secretmanager`, `storage`, `iap`, `iamcredentials`, `logging`, **`aiplatform`** (Vertex AI) e **`texttospeech`** (M23).
2. Criar o Firestore nativo em `us-central1` e a política de TTL em `processed.expira_em`.
3. Criar a conta de serviço `vocabot-vm` com os papéis `roles/datastore.user`, `roles/secretmanager.secretAccessor`, `roles/logging.logWriter` e **`roles/aiplatform.user`**. Adicionar `roles/iam.serviceAccountTokenCreator` **na própria SA** (ADR-0007: o `secretAccessor` é concedido em cada segredo, não no projeto) e `roles/storage.objectAdmin` **só no bucket**.
4. Criar o bucket (`us-central1`, *uniform access*, prevenção de acesso público) com ciclo de vida de 7 dias. **4b (M23):** criar também `$AUDIO_BUCKET` (mesmas proteções, **sem** ciclo de vida) com `roles/storage.objectAdmin` só nele para a SA da VM.
5. Criar os segredos. `WAHA_API_KEY` e `WAHA_DASHBOARD_PASSWORD` são gerados com `openssl rand -hex 24` e enviados por pipe, sem ecoar na tela. `ANTHROPIC_API_KEY` só é criado (sem versão) se `LLM_PROVIDER=anthropic`.
6. Criar a regra de firewall `allow-iap-ssh` (tcp:22 a partir de `35.235.240.0/20`, só para a tag `vocabot`). **Não** abrir as portas 3000 ou 8000.
7. Criar a VM, se não existir:
   - `e2-micro`, `us-central1-a`, Debian 12;
   - boot disk `pd-standard` de 30 GB;
   - SA `vocabot-vm` com escopo `cloud-platform`, tag `vocabot`;
   - IP externo efêmero (necessário para saída à internet) e network tier `STANDARD`;
   - `--metadata-from-file startup-script=infra/vm/startup.sh`.
8. `infra/vm/startup.sh` (idempotente, roda a cada boot): instala o Docker Engine e o plugin compose (se faltar), cria o swap de 2 GB (se faltar), cria `/opt/vocabot` e ativa o Docker no boot.

### 10.3 `infra/secrets.sh` (opcional; quem roda sou eu, em outro terminal)
Só é necessário com `LLM_PROVIDER=anthropic`. Pergunta `ANTHROPIC_API_KEY` com `read -rsp` e adiciona uma versão (`printf '%s' | gcloud secrets versions add --data-file=-`). Oferece pular se já existir.

### 10.4 `infra/deploy.sh`
1. Empacotar o repo (`git archive` ou `tar`, sem `.git`, `.env*`, `tests/` e `evals/`) e copiar para a VM (`gcloud compute scp --tunnel-through-iap`).
2. Na VM, por ssh:
   - extrair em `/opt/vocabot/app`;
   - **renderizar `/opt/vocabot/.env`** com `gcloud secrets versions access latest` para cada segredo, mais os valores não secretos, com `umask 077`;
   - rodar `docker compose up -d --build`.
3. Mostrar `docker compose ps` e as últimas linhas de log (filtrando nada sensível).

### 10.5 `infra/pair.sh`
Abre um túnel `gcloud compute ssh ... --tunnel-through-iap -- -N -L 3000:localhost:3000` e mostra as instruções:
1. abrir `http://localhost:3000/dashboard`;
2. entrar com `admin` e a senha do painel;
3. iniciar ou abrir a sessão `default` e escanear o QR com o app **WhatsApp Business** do número Vivo (Aparelhos conectados → Conectar um aparelho).

Mostre também como ver a senha do painel **localmente e só quando eu pedir** (`gcloud secrets versions access latest --secret=WAHA_DASHBOARD_PASSWORD`), rodado por mim.

### 10.6 Utilitários
- `infra/logs.sh`: `docker compose logs -f --tail=200`.
- `infra/ssh.sh`: abre um ssh via IAP.
- `infra/smoke_test.sh`: pela VM (via `infra/vm/smoke_remoto.sh`), testa `GET /health` do bot e verifica se a sessão do WAHA está `WORKING`, **esperando** até 3 minutos por cada um: depois de um deploy que recria o WAHA, o GOWS demora para subir e reinicia algumas vezes.

### 10.7 `docker-compose.yml`
- `waha`:
  - imagem com **tag fixada**, engine `GOWS` (hoje `devlikeapro/waha:gows-2026.8.2`; desde a 2026.6.1 o WAHA não separa mais Core/Plus);
  - volume `waha_sessions` na pasta de sessões;
  - API key e credenciais do painel vindas do `.env`;
  - webhook para `http://bot:8000/waha/webhook` com os eventos `message` e `session.status`;
  - reinício automático das sessões ao subir;
  - porta publicada **só em `127.0.0.1:3000`** (para o túnel);
  - `restart: unless-stopped`, `mem_limit: 400m`.
- `bot`:
  - build local, `env_file: /opt/vocabot/.env`, sem portas publicadas;
  - healthcheck em `/health`;
  - `restart: unless-stopped`, `mem_limit: 300m`.

### 10.8 Custos (para você respeitar)
A VM `e2-micro` com disco standard de 30 GB em `us-central1` está no nível gratuito. O Gemini no Vertex AI é pago por uso (centavos neste volume), coberto pelos créditos do trial. Os créditos do trial **não** pagam modelos de parceiros (ex.: Claude no Vertex), por isso ele não é opção aqui. O IP externo **não** está: custa alguns dólares por mês, coberto pelos créditos do trial. Firestore, Storage e Secret Manager ficam nas cotas gratuitas. O Cloud Text-to-Speech (M23) também: 1M de caracteres por mês em Neural2 (4M em Standard/WaveNet), e o cache evita sintetizar o mesmo texto duas vezes. Não crie Cloud NAT, balanceador, IP estático reservado nem máquinas maiores.

### 10.9 Deploy contínuo via GitHub Actions (M11, ADR-0013)

O repositório é público: `pull_request` de fora roda sem segredo (padrão do GitHub), e log de
Action é visível a qualquer pessoa — nada sensível pode aparecer em log.

- **Branch protection na `main`:** exige PR (sem push direto) e os checks `checks`, `test` e
  `compose` do `ci.yml` como obrigatórios.
- **`infra/setup_cicd.sh`** (idempotente, mesmo padrão de `setup.sh`): cria o Workload Identity
  Pool (`github-pool`) e o provider OIDC (`github-provider`, emissor
  `token.actions.githubusercontent.com`, *attribute condition* travada em
  `assertion.repository == 'AndreMartins21/anki-whatsapp' && assertion.ref == 'refs/heads/main'`);
  cria a conta de serviço `vocabot-deploy` e concede `roles/compute.osAdminLogin` **só na instância
  da VM**, mais `roles/iap.tunnelResourceAccessor` e `roles/compute.viewer` **no projeto** (nenhum
  dos dois funciona só na instância — `gcloud` rejeita o primeiro e o segundo falha o deploy real
  porque `compute.projects.get` só existe no escopo do projeto; como só existe uma VM neste
  projeto, na prática já fica restrito a ela — ver ADR-0013) e `roles/iam.serviceAccountUser` só
  sobre a `vocabot-vm` (sem ele o SSH falha com `actAs`). Não concede nada direto em Secret
  Manager, Firestore, Storage ou Vertex — quem lê segredo continua sendo a VM —, mas root na VM
  mais `serviceAccountUser` alcançam tudo que a `vocabot-vm` alcança: a proteção da `main` e a
  attribute condition são a defesa real (ADR-0013).
- **Job `deploy` em `.github/workflows/ci.yml`:** `needs: [checks, test, compose]`, só roda em
  `push` para `main`; autentica via `google-github-actions/auth` (WIF, sem chave), roda
  `infra/deploy.sh` e depois `infra/smoke_test.sh` — se o smoke test falhar, o workflow fica
  vermelho.
- **Configuração no GitHub** (Settings → Secrets and variables → Actions): `ALLOWED_NUMBER`,
  `ALLOWED_NUMBERS`, `ALLOWED_GROUPS`, `OWNER_NUMBER` e `BOT_NUMBER` como **Secrets** (e `MAX_GROUPS`,
  `CONTACT_EMAIL`, `GROUP_PREFIX`, públicos, como Variables) (são telefone real, mascarados em log mesmo não sendo credencial);
  `GCP_PROJECT_ID`, `GCP_WIF_PROVIDER`, `LLM_PROVIDER`, `GEMINI_MODEL`, `GEMINI_MODEL_EVAL`,
  `USER_LEVEL`, `TIMEZONE` como **Variables**.
- Decisão do usuário (2026-09-23): sem gate de aprovação manual entre o merge e o deploy — o CI é a
  barreira de qualidade. Ver ADR-0013 para as alternativas descartadas.

## 11. Estrutura esperada
```
vocabot/
  CLAUDE.md  README.md  pyproject.toml  Dockerfile  docker-compose.yml
  .dockerignore  .gitignore  .env.example
  app/
    main.py  config.py  messages.py
    channel/  base.py  waha.py  console.py  parser.py
    domain/   models.py  state.py  choices.py  srs.py  lembretes.py  musica.py
    flows/    router.py  capture.py  practice.py  pronuncia.py  expansion.py  synonyms.py  freeform.py  review.py  song.py  commands.py
    services/ llm.py  prompts.py  planilha.py  storage.py  lembretes.py  letras.py  tts.py  audio.py  transcricao.py  fake_transcricao.py   # M39
              log_handler.py  snapshot.py  metricas_destino.py   # M27/M28
    repo/     base.py  memory.py  firestore.py   # Banco (a raiz) + Repository (um espaço), M14
  sim/        __main__.py  tutor.py  letras.py
  scripts/    migrar_multiusuario.py   # M14: raiz antiga -> espacos/{chat}
              snapshot.py                        # M28: snapshot de métricas sob demanda
  evals/      sentencas.yaml  roteamento.yaml  run.py
  infra/      config.sh  setup.sh  secrets.sh  deploy.sh  pair.sh  logs.sh  ssh.sh  smoke_test.sh
              setup_metricas.sh  lifecycle-metricas.json   # M28
              .env.infra.example  vm/startup.sh
              bq/  espacos.json  pessoas.json  admins.json  termos.json
                   grupos_pendentes.json  firestore_uso.json  views/*.sql  # M28/M30
  tests/      fixtures/*.json  test_*.py
  docs/adr/   README.md  0000-template.md  NNNN-*.md
```
Se existir `referencia/`, ela contém um MVP anterior, feito para a Cloud API oficial (webhook da Meta, export etc.). Use-a só como consulta: o canal agora é o WAHA.

## 12. Observabilidade (M27/M28, ADR-0028/ADR-0029, `spec/plano-dashboard.md`)

Base do dashboard de saúde e uso (`spec/plano-dashboard.md`, M27–M30): pontos de negócio
importantes chamam `registrar_evento(logger, nome, **campos)` (`app/logging_config.py`), que grava
o campo `evento` no log JSON, mais uma **lista branca** de campos (`CAMPOS_DE_EVENTO`) — nunca
texto do aluno, número completo ou payload. `espaco` é sempre `id_curto(espaco_id)` (o mesmo hash
curto já usado nos logs): é a chave de junção com o snapshot do M28.

Em produção (`app_env == "prod"`), o processo do bot manda esses mesmos registros também ao Cloud
Logging por um segundo handler (`google-cloud-logging`, montado em `app/main.py` e passado a
`configurar_logs(handler_extra=...)`) — o driver de log do Docker **não muda** (ADR-0028 descartou
o `gcplogs`: quebraria `docker compose logs`/`infra/logs.sh`/`infra/smoke_test.sh`). O `waha`
continua só no `json-file` local.

Catálogo de eventos:

| `evento` | Onde | Campos | Serve para |
|---|---|---|---|
| `mensagem_recebida` | `main.py` (privado e grupo, após deduplicar) | `espaco`, `tipo_espaco`, `comando` | mensagens/dia, espaços ativos, uso por comando |
| `lembrete_enviado` | `Agendador._tick_espaco` | `espaco`, `tipo_espaco`, `n` (cartões na fila) | lembretes por pessoa/grupo |
| `lembrete_adiado` | `Agendador._tick_espaco` | `espaco`, `tipo_espaco`, `motivo` (`conversa_em_andamento`\|`nada_vencido`) | saúde do agendador |
| `lembrete_desistido` | `Agendador._tick_espaco` | `espaco`, `tipo_espaco`, `motivo` (`atraso`\|`sem_resposta_anterior`) | saúde do agendador |
| `revisao_concluida` | `flows/review.py` (fim da rodada) | `espaco`, `tipo_espaco`, `n` (feitas), `total`, `lapsos`, `motivo` (`manual`\|`fila_vazia`\|`timeout`) | taxa de conclusão das revisões |
| `revisao_resposta` | `flows/review.py:responder` | `espaco`, `tipo_espaco`, `qualidade`, `marcado` (só em grupo) | distribuição de qualidade, taxa de acerto |
| `marcacao_expirada` | `Agendador._expirar_marcacoes` | `espaco` | engajamento nos grupos |
| `llm_chamada` | `services/llm.py:_gerar_validado` | `metodo`, `modelo`, `ok`, `latencia_ms` | volume, latência, falhas da IA |
| `tts_chamada` | `services/audio.py:ServicoAudio.obter` | `ok`, `cache` (`hit`\|`miss`), `caracteres`, `latencia_ms` (só no miss) | volume e custo do Cloud TTS, taxa de acerto do cache |
| `grupo_ativado` / `grupo_desativado` | `flows/admin.py` | `espaco` | funil de ativação de grupos |
| `grupo_pendente` | `main.py:_registrar_pendente` | `espaco` | funil de ativação de grupos |
| `saiu_de_grupo` | `Agendador._sair_de_grupos_pendentes` | `espaco` | grupos abandonados em 24h |
| `numero_sem_plano` | `main.py:_avisar_sem_plano` | — | demanda reprimida |
| `waha_status` | `main.py:_tratar_status_sessao` | `ok`, `motivo` (o status) | disponibilidade do WhatsApp |
| `inicio` | `main.py:_lifespan` | — | reinícios/crash loop |
| `snapshot_ok` | `Agendador._rodar_snapshot_se_for_a_hora` | `n` (linhas gravadas), `latencia_ms` | o painel sabe se o próprio dado está fresco |
| `snapshot_falhou` | `Agendador._rodar_snapshot_se_for_a_hora` | `latencia_ms` | snapshot desatualizado (`METRICS_BUCKET` inexistente, Firestore fora do ar...) |

**Snapshot diário de métricas (M28, ADR-0029):** uma vez por dia às 04:00 no fuso configurado, o
`Agendador` chama `montar_snapshot(banco, agora)` (`app/services/snapshot.py`, função pura) e grava
NDJSON particionado por dia (`services/metricas_destino.py`) em `METRICS_BUCKET` — sem esse
`.env`, o passo fica desligado (nenhum ambiente de dev/CI fala com o GCS). `Banco.obter_ultimo_
snapshot`/`marcar_snapshot` (`meta/snapshot`, seção 7.1) garante uma execução por dia mesmo com
restart. `python -m scripts.snapshot` roda o mesmo snapshot sob demanda (`--dry-run` só conta).
Tabelas (`espacos`, `pessoas`, `admins`, `termos`, `grupos_pendentes`, `firestore_uso`), com o
esquema de cada uma versionado em `infra/bq/*.json` — um teste reprova se o código e o esquema
divergirem. Número completo só nas tabelas `espacos`/`admins` (admins); alunos só como
`id_curto`/mascarado (decisão do usuário, seção 7 do plano).
