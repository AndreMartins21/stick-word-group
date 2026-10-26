# stick-word-group

Bot de WhatsApp para **turmas de inglês em grupo**: a turma junta vocabulário (`!add`, ou marcando o
bot com a palavra), pratica com o menu de exemplos e sinônimos, faz a **revisão diária** sem marcar
ninguém e o **desafio semanal** com perguntas da IA. Admins ativam o bot nos grupos e recebem o
`/ranking` de engajamento em PDF.

No **privado**, o bot só atende o dono e os admins, e só com os comandos de admin; qualquer outro
número é ignorado por uma regra fixa no webhook, sem gastar IA (ADR-0062). O estudo individual, no
estilo do Anki, é o projeto irmão **stick-word**.

> A especificação está em [`spec/spec-inicial.md`](spec/spec-inicial.md); o trabalho anda marco a
> marco (seção 9 da spec). A separação dos dois projetos está no
> [ADR-0062](docs/adr/0062-separacao-em-stick-word-e-stick-word-group.md).

## Stack

| Item | Escolha |
|---|---|
| Linguagem | Python 3.12 |
| Web | FastAPI + Uvicorn |
| Canal WhatsApp | WAHA Core (self-hosted, engine GOWS) |
| IA | Gemini no Vertex AI (SDK `google-genai`), sem chave de API |
| Banco | Firestore (modo nativo) |
| Pronúncia | Google Cloud Text-to-Speech (voz Neural2, OGG/Opus) + cache no Cloud Storage |
| Hospedagem | 1 VM `e2-micro` (nível gratuito) com Docker Compose |
| Ferramentas | uv, ruff, mypy, pytest, pre-commit |

O porquê de cada escolha está em [`docs/adr/0001-stack-do-mvp.md`](docs/adr/0001-stack-do-mvp.md).

## Começando

Requer [uv](https://docs.astral.sh/uv/) (ele instala o Python 3.12 sozinho):

```bash
make setup     # venv + dependências + hooks de pre-commit + .env a partir do .env.example
make check     # ruff + mypy + pytest
```

Edite o `.env` com **valores falsos** para desenvolvimento local — ele nunca é versionado, e os
testes não dependem de credencial nem de rede.

```bash
make sim       # um grupo no terminal, sem WhatsApp (linhas `ana: !add stall`)
make run       # sobe a API em http://localhost:8000 (webhook do WAHA)
make help      # todos os alvos
```

## Comandos do bot

**No grupo** (só mensagens que começam com `!` ou `/`, ou que marcam/citam o bot; o resto é a
conversa da turma e o bot não lê): `!add palavra` (ou `@bot palavra`), `!list [página]`,
`!practice [N|palavra]`, `!review`, `!delete N|palavra`, `!daily`, `!weekly`, `!group`, `!level`,
`!help`. Durante a prática, `!2`…`!5` ou `@bot` + a frase. Admins: `!activate [nome]`,
`!deactivate`, `!teacher`/`!student`, `!daily 19h`, `!weekly now`.

**No privado** (só dono e admins): `/groups` (e `/groups off N`), `/teachers [NÚMERO]`,
`/ranking [meses]` (PDF) e, só o dono, `/admin add|remove NÚMERO`. Qualquer outro texto de um admin
recebe essa lista; de qualquer outro número, silêncio.

## Pronúncia em áudio (M23)

Automática (M25, ADR-0026): ao explicar uma palavra o bot manda **duas notas de voz**, na ordem, o
termo e a frase de exemplo do card. No desafio semanal, `2` lê a pergunta em voz alta.

Como o áudio é gerado:

1. O bot normaliza o texto (sem os `[[ ]]` que marcam a palavra-alvo, espaços colapsados, caixa mantida)
   e calcula o nome do arquivo: `audio/<voz>/<sha256 de voz + texto>.ogg`.
2. **Cache hit:** lê esse objeto do bucket `${PROJECT_ID}-vocabot-audio` e não chama o TTS.
   **Cache miss:** sintetiza no Google Cloud Text-to-Speech (voz `en-US-Neural2-F`, formato OGG/Opus),
   grava no bucket e devolve o áudio. O cache é compartilhado entre alunos: um termo é sintetizado uma vez só.
3. O áudio segue para o WhatsApp como nota de voz (`POST /api/sendVoice` do WAHA, base64, sem
   retentativa, para não duplicar). O link `gs://` fica em `Entry.audio_palavra` / `audio_exemplo`.
4. Qualquer falha (TTS, Storage ou envio) só gera um aviso curto; a conversa nunca cai.

Operação:

- **Configuração:** `AUDIO_BUCKET` (padrão `${PROJECT_ID}-vocabot-audio`; vazio ou fora de
  `APP_ENV=prod`, a pronúncia fica indisponível) e `TTS_VOICE` (padrão `en-US-Neural2-F`). Trocar a voz
  gera arquivos novos no cache; os antigos ficam no bucket.
- **Ativar num projeto novo:** `infra/setup.sh` habilita `texttospeech.googleapis.com`, cria o bucket
  (privado, **sem** ciclo de vida) e dá `objectAdmin` só nele à conta da VM.
  Sem isso, o log do bot mostra `403 SERVICE_DISABLED` ou erro de bucket e o aluno vê "I couldn't make
  the audio right now".
- **Custo:** cota gratuita mensal de 1M de caracteres em Neural2 (4M em Standard/WaveNet). Um termo ou
  frase tem dezenas de caracteres, e o cache evita repetir a chamada.
- **Localmente:** `make sim` usa um dublê do TTS e grava `exports/voz_NNN.ogg` (não toca); com
  `python -m sim --tts-real` e credenciais do Google, o áudio é de verdade.

Decisão e alternativas descartadas (TTS local, dicionários): [`ADR-0024`](docs/adr/0024-pronuncia-em-audio-com-google-cloud-tts.md).
Contrato: seção 7.4 da spec.

## Deploy (runbook)

Pré-requisitos: `gcloud` autenticado, projeto com faturamento, papel de Owner, e o número do bot
(chip com WhatsApp Business) à mão. **Nada abaixo roda sozinho:** cada script que cria algo pergunta
antes, e `DRY_RUN=1` só mostra os comandos.

```bash
cp infra/.env.infra.example infra/.env.infra   # preencha GCP_PROJECT_ID, ALLOWED_NUMBER, BOT_NUMBER
DRY_RUN=1 bash infra/setup.sh   # revisar o que será criado (só as leituras rodam)
bash infra/setup.sh             # APIs, Firestore + TTL, conta de serviço, bucket de áudio, segredos, firewall, VM
bash infra/deploy.sh            # empacota, copia via IAP, renderiza o .env na VM e sobe o compose
bash infra/pair.sh              # túnel (porta local 13000) p/ o painel do WAHA: escaneie o QR com o número do bot
bash infra/smoke_test.sh        # bot em /health e sessão do WAHA em WORKING
```

Depois: mande `/ajuda` do seu WhatsApp pessoal para o número do bot.

| Preciso de… | Comando |
|---|---|
| ver logs | `bash infra/logs.sh [waha\|bot]` |
| entrar na VM | `bash infra/ssh.sh` |
| atualizar o código | `bash infra/deploy.sh` (o WAHA e a sessão não são recriados) |
| ver a senha do painel | `gcloud secrets versions access latest --secret=WAHA_DASHBOARD_PASSWORD` (só quando você quiser) |
| chave da Anthropic (opcional) | `LLM_PROVIDER=anthropic bash infra/setup.sh` e depois `bash infra/secrets.sh` |

Notas de operação:

- **Custo:** `e2-micro` + disco standard de 30 GB em `us-central1` são gratuitos; o IP externo
  efêmero custa até ~US$ 3,60/mês (confira na fatura, SKU "External IP Charge on a Standard VM") e o
  Gemini é pago por uso (centavos neste volume). Crie um alerta de orçamento em Billing → Budgets
  antes do primeiro deploy. O IP existe só para a VM **sair** para a internet — nada entra nela.
  Alternativas gratuitas (casa, Oracle) e o porquê de ficarmos na GCP estão no
  [ADR-0008](docs/adr/0008-continuar-na-gcp-e-manter-a-saida-portavel.md); **revisitar antes de os
  créditos do trial acabarem**.
- **Memória (1 GB):** swap de 2 GB criado no boot, `mem_limit` de 400 MB no WAHA (engine GOWS, sem
  Chromium) e 300 MB no bot (medido: ~80 MB em repouso).
- **QR expira:** o QR vale por poucos minutos. Se a sessão aparecer como `FAILED`/`STOPPED` no painel
  (ninguém escaneou a tempo), clique em *Restart* na sessão `default` para gerar um QR novo.
- **Sessão do WhatsApp:** fica no volume `waha_sessions`; recriar o container não pede QR de novo.
  Só pode haver uma sessão ativa por número: não pareie o mesmo número em outro WAHA ao mesmo tempo.
- **Logs:** JSON, uma linha por evento, sem segredo e sem número de telefone completo. Se o bot não
  responder depois do pareamento, procure nos logs do bot por `LID não resolvido` (o WhatsApp às vezes
  identifica o remetente por um LID que o WAHA não consegue traduzir para o telefone) ou por
  `número não autorizado` (confira `ALLOWED_NUMBER`).
- **Imagem do WAHA:** tag fixada em `docker-compose.yml` (`gows-...`); para atualizar, troque a tag
  depois de ler as notas de versão em hub.docker.com/r/devlikeapro/waha.
- **Testar localmente:** `make sim` (sem WhatsApp, IA fabricada) ou `make sim ARGS=--real-llm`
  (Gemini de verdade, com `gcloud auth application-default login`); `make evals` mede a avaliação
  de frases; `make test-emulador` roda o contrato do `Repository` contra o emulador do Firestore.

## Grupos e acesso (M15-M17, ADR-0018, ADR-0062)

Cada grupo é um espaço (`espacos/{grupo}` no Firestore), com o próprio caderno da turma. O bot só
trabalha num grupo depois que um **admin** (o dono, `OWNER_NUMBER` ou o legado `ALLOWED_NUMBER`, ou
alguém em `/admin add NUMERO`) escrever `!activate` nele; `MAX_GROUPS` limita quantos e
`ALLOWED_GROUPS` autoriza grupos fixos. Um grupo em que o bot foi adicionado e ninguém ativou fica em
silêncio, e o bot **sai dele depois de 24 h**. No celular do bot, configure Privacidade → Grupos →
"Meus contatos", para só quem o salvou poder adicioná-lo.

## Deploy contínuo (M11, ADR-0013)

Depois do `infra/setup.sh` inicial, `infra/deploy.sh` também roda sozinho: todo merge na `main`
(que só acontece via PR com o CI verde — branch protection) dispara o job `deploy` do
`.github/workflows/ci.yml`, que faz o deploy e roda o smoke test. Sem chave de conta de serviço:
autenticação por Workload Identity Federation.

```bash
DRY_RUN=1 bash infra/setup_cicd.sh   # revisar o que será criado
bash infra/setup_cicd.sh             # WIF pool/provider + conta de serviço vocabot-deploy
```

O próprio script imprime, no fim, o que configurar no GitHub (Settings → Secrets and variables →
Actions: `ALLOWED_NUMBER`/`BOT_NUMBER` e, opcionais, `ALLOWED_NUMBERS`/`ALLOWED_GROUPS`/`OWNER_NUMBER` como Secrets, o resto como Variables) e lembra de ativar a
branch protection da `main`.

## Segurança

- Segredos vivem no **Secret Manager**; na VM o `.env` é renderizado no deploy com permissão 600.
- Nenhuma chave de conta de serviço em arquivo: autenticação por ADC / identidade da VM.
- `gitleaks` roda no pre-commit e na CI; `.env`, `.env.infra` e chaves estão no `.gitignore` e há
  teste de higiene que falha se algum deles for versionado.
- Acesso à VM só por **IAP**; nenhuma porta pública.

Se um segredo vazar para um commit, ele é considerado comprometido: **rotacione primeiro**, depois
limpe o histórico.

## Estrutura

```
app/        aplicação          sim/    simulador de terminal
tests/      pytest + fixtures  evals/  qualidade dos modelos (fora do pytest)
infra/      scripts de GCP     docs/   ADRs
Dockerfile, docker-compose.yml  bot + WAHA na VM
spec/       especificação      .claude/skills/  skills do projeto (sdd, gcp-best-practices)
```

## Contribuindo (ou voltando aqui em três meses)

- Commits atômicos, mensagem no imperativo, um commit por marco.
- Lógica de negócio nova entra por TDD (teste primeiro).
- Decisão com consequência duradoura vira ADR em `docs/adr/` — ver o
  [índice](docs/adr/README.md).
- Mudou um contrato? A spec é atualizada no mesmo commit.
