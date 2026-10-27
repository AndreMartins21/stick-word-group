# Plano — Dashboard de saúde e uso do stick-word-group (observabilidade)

> **ADR-0062:** este projeto é só de grupos. As colunas de lembrete do privado saíram do snapshot
> (ver `infra/bq/*.json`); espaços privados antigos ainda aparecem, mas não recebem mais nada.

> Status: **plano, nada implementado** (2026-09-25). Estende a spec (`spec/spec-inicial.md`) com uma
> seção nova de observabilidade. Os marcos daqui (M27–M30) vêm depois do M18 (piloto), mas não
> dependem dele. Os pontos marcados com **[confirmar]** devem ser checados na documentação oficial
> antes de escrever código (regra de ouro 5).

## Contexto

Queremos um painel único para saber se o sistema está saudável e como ele está sendo usado:
grupos, termos salvos, admins, falhas, armazenamento, custo e lembretes. Restrição: **custo zero ou
praticamente zero**, sem inflar a complexidade do projeto além do necessário.

Hoje o que existe para observar o sistema:

- **Dados de negócio** só no Firestore (`espacos/*`, `admins`, `grupos_pendentes`, `lids`,
  `processed`), sem histórico: o Firestore guarda o estado atual, não a evolução.
- **Logs** em JSON no stdout, mas eles **não saem da VM**: o Docker usa o driver `json-file`
  (`infra/vm/startup.sh`) e não há Ops Agent. Ou seja, hoje **não existe nenhuma falha visível na
  GCP** — elas só aparecem em `infra/logs.sh`. A SA `stick-word-group-vm` já tem `roles/logging.logWriter`.
- **Nenhum evento** de uso é registrado de forma contável (lembrete enviado, chamada à IA, comando
  usado...). Os logs atuais são mensagens em texto livre, sem um campo de evento.
- **Custo**: só no console de Billing.

Conclusão: sim, é preciso uma camada analítica. O caminho mais simples que atende tudo é **juntar
todas as fontes no BigQuery** e pôr um visualizador por cima. O "ETL" fica pequeno: um snapshot diário
feito pelo próprio bot, sem serviço novo.

## 1. Arquitetura proposta

```
                    ┌─────────────────────────── VM (e2-micro) ──────────────────────────┐
                    │  bot (FastAPI)                                                     │
 Firestore ◄──────► │   ├─ fluxos (como hoje)                                            │
                    │   ├─ logs JSON com campo `evento` ── driver gcplogs ──┐            │
                    │   └─ Agendador: snapshot diário ── NDJSON ──┐          │            │
                    │  waha ── logs ── driver gcplogs ─────────────┼──────────┤            │
                    └──────────────────────────────────────────────┼──────────┼────────────┘
                                                                   ▼          ▼
                                            gs://…-metrics/    Cloud Logging (_Default)
                                            snapshot/tabela/dt=…/        │ Log Analytics (grátis)
                                                   │                     │
                                                   ▼                     ▼
   Cloud Billing ── export ──► BigQuery: `billing_export`   `stick_word_group_metrics` (tabelas externas +
                                           │                 views)   `stick_word_group_logs` (dataset linkado)
                                           └──────────────┬─────────────┘
                                                          ▼
                              Grafana OSS no Cloud Run (min 0, IAP, sem chave)
                                 ├─ datasource BigQuery (auth "gce" = SA do Cloud Run)
                                 └─ datasource Cloud Monitoring (Firestore reads/writes, CPU da VM)
```

Quatro fontes, um destino (BigQuery), um visualizador:

| Fonte | Como chega ao BigQuery | O que responde |
|---|---|---|
| Firestore (estado) | snapshot diário do bot → NDJSON no GCS → **tabelas externas** | grupos, termos, pessoas, admins, lembretes configurados, backlog de revisão, armazenamento estimado |
| Logs (eventos e falhas) | driver `gcplogs` → Cloud Logging → **Log Analytics + dataset linkado** | falhas, lembretes enviados, chamadas à IA, comandos, mensagens/dia, sessão do WAHA |
| Billing | **export do Cloud Billing** para BigQuery | gasto do mês, por serviço, créditos |
| Cloud Monitoring | datasource direto no Grafana (não passa pelo BQ) | leituras/escritas no Firestore vs cota grátis, CPU da VM |

### 1.1 Por que snapshot no próprio bot (e não outro "ETL")

Alternativas avaliadas para levar o Firestore ao BigQuery:

| Opção | Prós | Contras | Decisão |
|---|---|---|---|
| **A. Snapshot diário no `Agendador` do bot → NDJSON no GCS → tabela externa** | nenhum serviço novo; reusa `Banco`/`Repository` (testável com `MemoryBanco`); o bot alcança o WAHA (conta os grupos reais); a SA da VM não ganha permissão no BigQuery; `google-cloud-storage` já é dependência; NDJSON é portátil (ADR-0008) | um pouco de trabalho a mais no processo do bot (1×/dia, alguns segundos) | **escolhida** |
| B. Cloud Run Job + Cloud Scheduler | isolado do bot | imagem nova, Artifact Registry, SA com leitura no Firestore, não enxerga o WAHA (loopback da VM), outro pipeline de deploy | descartada |
| C. `gcloud firestore export` gerenciado → load no BQ | nativo | export por coleção com esquema aninhado ruim de consultar; mesma cobrança de leituras; precisa de orquestração | descartada |
| D. Extensão "Stream Firestore to BigQuery" (Firebase) | tempo real | Cloud Functions por coleção, gatilhos em toda escrita, acoplamento forte | descartada |
| E. Bot gravando direto no BigQuery (`load_table_from_json`) | tabela nativa | dependência nova e pesada na imagem de 300 MB de RAM; SA da VM com escrita no BQ | descartada (fica como plano B se tabela externa for lenta) |

Snapshot **diário** basta: o painel é de saúde e tendência, não de tempo real. O que precisa ser
quase em tempo real (falhas, sessão do WAHA) vem dos **logs**, que chegam em segundos.

### 1.2 Por que Grafana no Cloud Run (e não Looker Studio)

| Opção | Custo | Prós | Contras |
|---|---|---|---|
| **Grafana OSS no Cloud Run + IAP** | ~0 (free tier do Cloud Run; imagem no Artifact Registry ~centavos) | dashboards como código no repo (revisados em PR, como o resto); lê BigQuery **e** Cloud Monitoring; auth sem chave (SA do Cloud Run); percentis e tabelas livres em SQL | peças novas: imagem, serviço, SA, IAP; cold start de alguns segundos |
| Looker Studio | 0 | zero infraestrutura; conector nativo de BigQuery | não lê Cloud Monitoring; dashboard fica fora do repo (clicado à mão, sem revisão); controle de acesso por compartilhamento de Google Doc |
| Grafana Cloud (free) | 0 | sem hospedar nada | exige **chave JSON** de conta de serviço guardada num terceiro (contraria ADR-0007); retenção/limites do plano grátis |
| Painel nativo do Cloud Monitoring | 0 | já existe | não consulta BigQuery (sem as métricas de negócio nem billing) |

**Recomendação: Grafana no Cloud Run.** Como tudo converge no BigQuery, trocar para Looker Studio
depois é barato (as views SQL são as mesmas) — fica registrado no ADR como plano B.

### 1.3 Estimativa de custo mensal

| Item | Cota grátis relevante | Uso esperado | Custo |
|---|---|---|---|
| Cloud Logging (ingestão) | 50 GiB/projeto/mês, retenção de 30 dias | poucos MB/mês (bot + WAHA) | 0 |
| Log Analytics + dataset linkado | sem custo de upgrade nem de armazenamento no BQ; só a consulta no BQ | — | 0 |
| BigQuery (consultas) | 1 TiB/mês | painel inteiro < 1 GB por abertura (mínimo cobrado: 10 MB por tabela por consulta) | 0 |
| BigQuery (armazenamento) | 10 GiB/mês | export de billing: MBs | 0 |
| GCS (snapshots) | 5 GB-mês em regiões US | KB–MB/dia, lifecycle de 400 dias | 0 |
| Cloud Run | 180k vCPU-s, 360k GiB-s, 2M req/mês | algumas aberturas por dia, min-instances 0 | 0 |
| Artifact Registry | 0,5 GB | imagem do Grafana ~0,4–0,5 GB | 0 a ~US$ 0,05 |
| Cloud Build (`run deploy --source`) | 2.500 min/mês **[confirmar a cota atual]** | 1–2 builds/mês | 0 |
| Leituras extras no Firestore | 50k leituras/dia | 1 snapshot/dia ≈ nº de documentos (ver 3.4) | 0 enquanto couber |
| Métricas baseadas em log | 150 MiB/mês de métricas cobráveis | 2–3 contadores | 0 |

**[confirmar]** todas as cotas na página de preços de cada serviço antes do marco de infra.

## 2. Marco M27 — Eventos estruturados e logs na GCP (falhas visíveis)

Sem isto não existe "quantidade de falhas" nem "lembretes enviados": é o primeiro passo.

### 2.1 Campo `evento` nos logs (`app/logging_config.py`)

- O `JsonFormatter` passa a copiar campos extras do `LogRecord` (via `extra={"evento": ..., ...}`)
  para o JSON. Só uma lista branca de chaves (`evento`, `espaco`, `tipo_espaco`, `comando`, `metodo`,
  `modelo`, `ok`, `latencia_ms`, `tokens_entrada`, `tokens_saida`, `caracteres`, `cache`, `n`,
  `qualidade`, `motivo`) — nada de texto do aluno, número ou payload.
- `espaco` é sempre `id_curto(espaco_id)` (sha256[:8], já usado nos logs): é a **chave de junção**
  entre logs e snapshot. O snapshot grava a mesma coluna.
- Função utilitária `registrar_evento(nome, **campos)` para não espalhar `extra=` pelo código.

### 2.2 Eventos a emitir (catálogo — vira tabela na spec)

| `evento` | Onde | Campos | Serve para |
|---|---|---|---|
| `mensagem_recebida` | `main.py`, depois da allowlist | `espaco`, `tipo_espaco`, `comando` (`/list`, `!review`… ou `texto`) | mensagens/dia, espaços ativos (DAU/WAU), uso por comando |
| `lembrete_enviado` | `Agendador._tick_espaco` | `espaco`, `tipo_espaco`, `n` (cartões na fila) | **lembretes por pessoa/grupo** (distribuição) |
| `lembrete_adiado` / `lembrete_desistido` | `Agendador` | `espaco`, `motivo` | saúde do agendador |
| `revisao_concluida` | fluxo de revisão, no resumo | `espaco`, `n` (feitas), `total`, `lapsos` | taxa de conclusão das revisões |
| `revisao_resposta` | revisão privada e em grupo | `espaco`, `qualidade`, `marcado` (grupo) | distribuição de qualidade, taxa de acerto |
| `marcacao_expirada` | `_expirar_marcacoes` | `espaco` | engajamento nos grupos |
| `llm_chamada` | `_gerar_validado` / providers | `metodo` (`explain`, `route`…), `modelo`, `ok`, `latencia_ms`, `tokens_entrada`, `tokens_saida` | volume, latência p50/p95, falhas da IA, **custo estimado do Vertex** |
| `tts_chamada` | `ServicoAudio` (M23–M26, ADR-0024/0026/0027) | `ok`, `latencia_ms`, `caracteres`, `cache` (`hit`/`miss`) | volume e **custo estimado do Cloud TTS**; taxa de acerto do cache (cache miss é o único que gera custo) |
| `grupo_ativado` / `grupo_desativado` / `grupo_pendente` / `saiu_de_grupo` | `admin.py`, `main.py`, `Agendador` | `espaco` | funil de ativação de grupos |
| `numero_sem_plano` | `main.py:356` (já existe o log) | — | demanda reprimida |
| `waha_status` | `main.py:485/487` | `ok`, `motivo` (status) | disponibilidade do WhatsApp |
| `snapshot_ok` / `snapshot_falhou` | snapshot diário (M28) | `n` (docs lidos), `latencia_ms` | o painel sabe se o próprio dado está fresco |
| `inicio` | lifespan do FastAPI | versão (sha do commit, se o deploy passar) | reinícios/crash loop |

Os `logger.exception`/`logger.warning` atuais continuam; "falha" no painel = `severity >= ERROR`
do bot + `llm_chamada ok=false` + `waha_status ok=false` + webhook rejeitado.

**[confirmar]** que o `google-genai` expõe `usage_metadata` (`prompt_token_count`,
`candidates_token_count`) na resposta do Vertex, e o preço por token do modelo em uso, para a coluna
de custo estimado.

### 2.3 Enviar os logs ao Cloud Logging — **revisado**: não é o driver `gcplogs`

O plano original propunha o driver `logging: {driver: gcplogs}` do Docker nos dois serviços. Ao
implementar (2026-09-27), a pesquisa confirmou um problema real: **o driver `gcplogs` não
implementa leitura** ("this log driver does not implement a reader so it is incompatible with
`docker logs`" — doc oficial). Trocar o driver quebraria `docker compose logs`, `infra/logs.sh` e
`infra/smoke_test.sh` na única VM de produção — o item "[confirmar] dual logging" do rascunho
original teria dado errado. Descartado.

**Escolha revisada:** o processo do bot manda seus próprios logs à API do Cloud Logging por um
**segundo handler** (biblioteca `google-cloud-logging`, `uv add`), **em paralelo** ao
`StreamHandler` de stdout — que continua exatamente como hoje, então nada muda para
`docker compose logs`/`infra/logs.sh`/`infra/smoke_test.sh`. Só o processo `bot` (Python) manda
logs à nuvem; o `waha` continua só no `json-file` local — suas falhas relevantes já chegam via
`waha_status` (o bot loga a mudança de status da própria sessão) e via as exceções que o bot
registra ao redor de cada chamada ao canal.

- `configurar_logs(nivel, handler_extra=None)`: parâmetro opcional para o handler da nuvem, para os
  testes nunca precisarem de credencial nem rede (convenção do projeto). Handler extra usa o mesmo
  `JsonFormatter`? **Sim** — confirmado em produção no dia do deploy (2026-09-27): sem isso, o
  `CloudLoggingHandler` manda só `textPayload: "lembrete_adiado"` (a mensagem sem os campos extras).
  O motivo: ele monta o `jsonPayload` chamando `self.format(record)` (o formatter do próprio
  handler) e, se o resultado começar com `{`, tenta decodificar como JSON
  (`google.cloud.logging_v2.handlers.handlers._format_and_parse_message`) — não lê os atributos do
  `LogRecord` diretamente. Com o mesmo `JsonFormatter` no handler extra, a string que ele formata já
  é o JSON de sempre, e vira `jsonPayload` estruturado de graça, sem precisar do parâmetro
  `json_fields` da biblioteca. Teste de regressão simula exatamente esse caminho (chama
  `handler.format(record)`, não `record.getMessage()`).
- `google.cloud.logging.Client().get_default_handler()` usa `BackgroundThreadTransport` por padrão:
  não bloqueia a resposta ao WAHA esperando a rede.
- Credencial: a mesma conta de serviço da VM (`stick-word-group-vm`, já tem `roles/logging.logWriter`),
  sem segredo novo.
- Só liga com `app_env == "prod"` (dev/CI nunca tentam falar com a API real).
- `docker-compose.yml` e `startup.sh` **não mudam** nesta revisão.

### 2.4 Log Analytics (SQL sobre logs, grátis)

```bash
# criam/alteram: mostrar e aguardar aprovação (regra de ouro 2)
gcloud logging buckets update _Default --location=global --enable-analytics --project=stick-word-group
gcloud logging links create stick_word_group_logs --bucket=_Default --location=global --project=stick-word-group
```

O dataset linkado `stick_word_group_logs` aparece no BigQuery sem cópia nem armazenamento cobrado; o Grafana
consulta a view `_AllLogs`. **[confirmar]** a localização do dataset linkado de um bucket `global`
(precisa casar com a dos outros datasets, ver 3.5).

### 2.5 Testes e ADR

- `tests/test_logging.py` (já existe, ADR-0024 em diante): extras na lista branca aparecem; qualquer outro campo é descartado;
  nenhum evento carrega número completo (teste varre os eventos emitidos num fluxo do `sim`).
- Testes dos pontos de emissão com `caplog` (lembrete enviado, `llm_chamada` com dublê do provider).
- **ADR-0028 — Logs estruturados com eventos e envio ao Cloud Logging** (`gcplogs` descartado por
  quebrar `docker logs`; Ops Agent pesado demais para a e2-micro; escolhido: handler da biblioteca
  `google-cloud-logging` em paralelo ao stdout, só em produção).
- Spec: nova **seção 12 "Observabilidade"** com o catálogo de eventos (contrato).

## 3. Marco M28 — Snapshot diário do Firestore (o "ETL")

> **Implementado em 2026-09-28** (ADR-0029). Diferenças do rascunho abaixo, descobertas na
> implementação: a tabela `whatsapp` (contagem de grupos pelo WAHA) e o campo `n_marcada` da
> tabela de pessoas **não entraram** — o primeiro precisaria de uma chamada assíncrona ao canal
> dentro de uma função que é deliberadamente pura e síncrona; o segundo não tem de onde vir (só
> existe `Membro.marcado_em`, a última vez, não uma contagem). `n_respondeu_marcada` (via
> `Resposta.marcado`) cobre a métrica de engajamento equivalente. As tabelas externas do BigQuery
> e as views (3.6) ainda **não foram criadas** — só o bucket/dataset (`infra/terraform/storage.tf`,
> ainda não executado) e o esquema versionado (`infra/bq/*.json`, já com teste de sincronia).

### 3.1 Onde roda

Nova tarefa no `Agendador` (mesmo laço, ADR-0012): uma vez por dia, às **04:00 de
`TIMEZONE`**. Para não repetir depois de um restart, grava `meta/snapshot {ultimo_dia}` no
Firestore e só roda se `ultimo_dia < hoje`. Falha é logada (`snapshot_falhou`) e **nunca** afeta os
lembretes (mesmo `try/except` dos outros passos do tick). Roda em `bloq` (threadpool), espaço a
espaço, para não segurar memória.

Código novo, separado da regra de negócio:

- `app/services/snapshot.py` — `montar_snapshot(banco, agora, grupos_no_whatsapp) -> Snapshot`:
  **função pura sobre o `Banco`**, testada com `MemoryBanco` (TDD). Devolve listas de linhas por
  tabela (dataclasses/pydantic).
- `app/services/metricas_destino.py` — interface `DestinoDeMetricas.gravar(tabela, dia, linhas)`
  com duas implementações: GCS (NDJSON em `snapshot/{tabela}/dt=YYYY-MM-DD/parte-0.json`) e
  diretório local (dev/`sim`). Reusa o padrão de `app/services/storage.py`.
- `python -m scripts.snapshot [--dry-run]` — roda o mesmo snapshot sob demanda, local com ADC (como
  o `scripts.migrar_multiusuario`); o `--dry-run` imprime contagens e **o nº de leituras** que
  custaria. Isso também cobre o `scripts.metricas` previsto no M18.

### 3.2 Mudanças no `Banco`/`Repository` (contrato → spec 7.1 no mesmo commit)

- `Banco.listar_espacos() -> list[EspacoResumo]` — todos os documentos de `espacos/` com `tipo`,
  `ativo`, `nome`, `ativado_por`, `ativado_em`, `criado_em` (hoje só existem consultas filtradas).
- `Banco.listar_admins_detalhado()` — número + `adicionado_em` + `adicionado_por` (hoje só o número).
- Contrato do Repository também contra o emulador (`make test-emulador`).
- **Lacunas de dado que valem a pena fechar** (mudança pequena, vale a partir do deploy, sem
  retroativo):
  - `Entry.autor_id: str | None` — quem salvou a palavra num grupo. Sem isso, "termos por pessoa"
    dentro de grupos não existe (hoje só frases e respostas têm autor).
  - `Profile.nome: str | None` — o nome do WhatsApp (`pushName`) no privado, como já é feito no
    `Membro`. Sem isso, a tabela por pessoa só mostra número mascarado.

### 3.3 Tabelas do snapshot (uma pasta por tabela, partição `dt`)

`espaco` = `id_curto(espaco_id)` em todas (junta com os logs). Colunas com número de telefone são
marcadas 🔒 (ver 6. Privacidade).

**`espacos`** — uma linha por espaço por dia
`dt, espaco, tipo (privado|grupo), nome (grupo), ativo, ativado_por 🔒, ativado_em, criado_em,
nivel, lembretes_por_dia, janela_inicio, janela_fim, lembrete_sem_resposta, proximo_lembrete,
estado_sessao, ultima_atividade, n_termos, n_termos_nova, n_termos_praticada, n_termos_expansao,
n_termos_musica?, n_vencidas, n_vencidas_7d (vencem na próxima semana), n_frases, n_frases_usuario,
n_frases_corretas, n_membros, n_professores, n_respostas, n_respostas_marcadas, bytes_estimados`

**`pessoas`** — uma linha por pessoa (número) por dia, juntando o espaço privado dela e a
participação nos grupos
`dt, pessoa (id_curto do número), numero_mascarado, nome, tem_privado, n_termos_privado,
n_termos_em_grupos (via Entry.autor_id), n_frases (todas, via autor_id), n_respostas_grupo,
n_marcada, n_respondeu_marcada, n_grupos, papeis (aluno/professor), lembretes_por_dia_privado,
ultima_atividade`

**`admins`** — uma linha por admin por dia
`dt, admin_numero 🔒, admin_mascarado, adicionado_em, adicionado_por_mascarado,
n_grupos_ativos, n_grupos_ativados_total (inclui desativados), grupos (array de nomes),
n_termos_nos_grupos, n_membros_nos_grupos`

**`termos`** — estado atual de cada termo (partição diária, **lifecycle de 30 dias** para não
acumular cópias inúteis; a tendência vem das contagens de `espacos`)
`dt, espaco, slug, palavra, classe, cefr_estimado, tags, origem, status, criado_em,
primeira_pratica?, repeticoes, intervalo_dias, facilidade, lapsos, proxima_revisao, revisada_em,
n_frases`

**`grupos_pendentes`** — `dt, espaco, visto_em`

**`firestore_uso`** — por coleção: `dt, colecao, n_docs, bytes_estimados`

**`whatsapp`** — `dt, grupos_no_whatsapp` (contagem pelo WAHA), `sessao_status`.
**[confirmar]** o endpoint: `GET /api/{session}/groups` (com `limit`/`offset`) existe, mas há
issues abertas com o GOWS; checar se há `/groups/count` e se responde bem na versão fixada
`gows-2026.8.2`. Se não responder, a coluna fica nula e o painel mostra só ativos + pendentes.

### 3.4 Orçamento de leituras do Firestore

O snapshot lê cada documento uma vez (espaços, perfis, sessões, termos, frases, membros,
respostas). A cota grátis é **50k leituras/dia** — e o bot também lê. Regras:

- O `--dry-run` do M28 mede o total antes de ligar em produção.
- Frases: usar **agregação `count()`** por termo em vez de ler as frases, se o volume crescer
  (agregação cobra 1 leitura por até 1.000 entradas de índice) **[confirmar]** preço da agregação.
- Se o total passar de ~20k, o snapshot de `termos` passa a ser semanal e o diário fica só com
  contagens.
- O painel mostra "leituras do dia vs 50k" (Cloud Monitoring) para ver isso acontecendo.

### 3.5 Armazenamento do Firestore (% dos 1 GiB grátis)

O Cloud Monitoring expõe leituras/escritas/deletes do Firestore, mas **não encontrei uma métrica de
bytes armazenados** na documentação atual. Plano:

1. **Estimativa no snapshot**: o snapshot já tem os documentos em mãos, então calcula o tamanho de
   cada um pela fórmula oficial ("Storage size calculations": nome do documento + campos + 32 bytes,
   strings = bytes UTF-8 + 1). Soma por coleção e por espaço → `bytes_estimados`. Índices
   automáticos não entram na conta exata; o painel aplica um fator (ex.: ×2) e mostra como
   "estimativa". Útil também para ver **qual espaço mais ocupa**.
2. **Conferência pelo billing**: o export do Billing traz o `usage.amount` do SKU de armazenamento
   do Firestore (em GiB-mês) mesmo quando o custo é zero **[confirmar]** que o uso dentro da cota
   grátis aparece no export. Se aparecer, é o número "oficial" e a estimativa vira detalhe.
3. **[confirmar]** no Metrics Explorer se existe alguma métrica `firestore.googleapis.com/...storage...`
   (a lista de métricas da GCP é longa e a busca não achou); se existir, ela ganha.

### 3.6 BigQuery: dataset e tabelas externas

```bash
# criam/alteram: mostrar e aguardar aprovação
gcloud services enable bigquery.googleapis.com --project=stick-word-group
gcloud storage buckets create gs://stick-word-group-metrics --location=us-central1 \
  --uniform-bucket-level-access --public-access-prevention --project=stick-word-group
# SA da VM só escreve NESTE bucket (sem leitura de outros, sem BigQuery)
gcloud storage buckets add-iam-policy-binding gs://stick-word-group-metrics \
  --member=serviceAccount:stick-word-group-vm@stick-word-group.iam.gserviceaccount.com \
  --role=roles/storage.objectCreator
bq --location=US mk --dataset stick-word-group:stick_word_group_metrics
```

- Uma **tabela externa** por pasta, com particionamento Hive (`dt`) e esquema declarado em
  `infra/bq/*.json` (versionado; nada de autodetect). Definidas por um script idempotente
  `infra/terraform/storage.tf` (Terraform, ADR-0063).
- **Views** em `infra/bq/views/*.sql` com a lógica do painel (o Grafana só faz `SELECT * FROM view`):
  `v_ultimo_dia_*`, `v_distribuicoes`, `v_falhas_diarias`, `v_lembretes_por_espaco`,
  `v_custo_mes`… Views versionadas = a consulta passa por PR e pode ser testada.
- **Localização**: datasets precisam estar na mesma localização para uma view juntar dados.
  Proposta: **tudo em `US` multi-região** (o export de Billing em multi-região ainda ganha backfill
  do mês atual e do anterior). **[confirmar]** que um dataset `US` lê tabela externa em bucket
  `us-central1` e onde fica o dataset linkado do Log Analytics.
- Lifecycle do bucket: `termos/` 30 dias; demais 400 dias.

### 3.7 Testes e ADR

- `tests/test_snapshot.py` (TDD, `MemoryBanco` com 2 grupos, 3 privados, 1 pendente, 2 admins):
  contagens por espaço, agregação por pessoa (inclui quem só aparece em grupo), admins × grupos,
  bytes estimados de um documento conhecido (caso do exemplo da doc oficial: 147 bytes), nenhuma
  coluna 🔒 fora das tabelas previstas, espaço vazio não quebra.
- Destino local: relê o NDJSON e confere com o esquema de `infra/bq/*.json` (esquema e código não
  podem divergir — o teste falha se uma coluna faltar ou sobrar).
- Agendador: roda uma vez por dia, não roda de novo depois de restart, falha não derruba o tick.
- **ADR-0029 — Snapshot diário do Firestore em NDJSON no GCS lido pelo BigQuery** (tabela 1.1).

## 4. Marco M29 — Custo (Billing export + orçamento)

Passos no console (o export de Billing **não** se configura por `gcloud`; exige papel de Billing
Account Administrator — quem faz é o usuário):

1. `bq --location=US mk --dataset stick-word-group:billing_export`.
2. Console → Billing → *Billing export* → **Standard usage cost** → projeto `stick-word-group`,
   dataset `billing_export`. Com dataset multi-região, os dados do mês atual e do anterior chegam
   retroativos (o backfill pode levar até 5 dias). O export atualiza várias vezes ao dia, com
   atraso de horas — o painel diz "atualizado até ...".
3. **Orçamento** (grátis): Budget de US$ 5/mês com alertas por e-mail em 50/90/100% — é o alarme
   de custo que o painel sozinho não dá.
   ```bash
   # cria: mostrar e aguardar aprovação
   gcloud billing budgets create --billing-account=<ID> --display-name=stick-word-group \
     --budget-amount=5USD --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 \
     --threshold-rule=percent=1.0
   ```

Views: `v_custo_mes` (bruto, créditos, líquido = `cost + SUM(credits.amount)`, por serviço),
`v_custo_diario`, `v_previsao_mes` (líquido do mês ÷ dias corridos × dias do mês). O saldo de
créditos do trial **não** está no export: vira uma variável constante no Grafana (valor do trial
menos créditos consumidos desde o início), se o usuário quiser.

**Sem ADR dedicado** (é configuração pelo console, não uma decisão com alternativa real): registra
só na spec (seção 12).

## 5. Marco M30 — Grafana no Cloud Run

### 5.1 Artefatos no repo

```
dash/
  Dockerfile                      FROM grafana/grafana-oss:<tag fixada [confirmar]>
                                  + plugin grafana-bigquery-datasource (versão fixada) instalado no build
  provisioning/datasources/*.yaml BigQuery (authenticationType: gce) + Cloud Monitoring (gce)
  provisioning/dashboards/*.yaml  aponta para /var/lib/grafana/dashboards
  dashboards/stick-word-group.json         o painel (editado na UI → exportado → PR)
infra/deploy_dash.sh              build + deploy + IAP (idempotente, DRY_RUN)
```

- **Sem estado**: o SQLite do Grafana é descartável; tudo (datasources, painéis) vem do
  provisioning. `allowUiUpdates: false` nos painéis provisionados — a verdade é o JSON do repo.
- **Sem senha**: IAP na frente; Grafana com `auth.anonymous` (papel Viewer) e login desabilitado
  **ou** `auth.proxy` lendo o cabeçalho `X-Goog-Authenticated-User-Email` do IAP (melhor: mostra
  quem entrou). Decidir no ADR; nenhum segredo novo em qualquer caso.
- Cloud Run: `us-central1`, `--min-instances=0 --max-instances=1 --memory=512Mi --cpu=1`,
  cobrança por requisição, SA própria.

### 5.2 Conta de serviço `stick-word-group-dash` (menor privilégio, ADR-0007)

| Papel | Escopo |
|---|---|
| `roles/bigquery.dataViewer` | datasets `stick_word_group_metrics`, `billing_export`, `stick_word_group_logs` |
| `roles/bigquery.jobUser` | projeto (necessário para rodar consulta) |
| `roles/storage.objectViewer` | só o bucket `…-metrics` (tabela externa lê o GCS com a credencial de quem consulta) |
| `roles/monitoring.viewer` | projeto |
| `roles/logging.viewAccessor` **[confirmar]** | view `_AllLogs` do bucket `_Default` (leitura do dataset linkado) |

### 5.3 Deploy e acesso (comandos para o usuário aprovar e rodar com `!`)

```bash
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com iap.googleapis.com --project=stick-word-group
gcloud run deploy stick-word-group-dash --source=dash --region=us-central1 --project=stick-word-group \
  --service-account=stick-word-group-dash@stick-word-group.iam.gserviceaccount.com \
  --no-allow-unauthenticated --iap --min-instances=0 --max-instances=1 --memory=512Mi
gcloud run services add-iam-policy-binding stick-word-group-dash --region=us-central1 \
  --member=serviceAccount:service-<PROJECT_NUMBER>@gcp-sa-iap.iam.gserviceaccount.com \
  --role=roles/run.invoker --project=stick-word-group
gcloud iap web add-iam-policy-binding --resource-type=cloud-run --service=stick-word-group-dash \
  --region=us-central1 --member=user:<email do usuário> \
  --role=roles/iap.httpsResourceAccessor --project=stick-word-group
```

IAP direto no Cloud Run (sem load balancer) funciona em projeto **sem organização**; para contas
fora de uma organização (Gmail) é preciso configurar uma vez a tela de consentimento OAuth externa
e, pela CLI, possivelmente um cliente OAuth próprio **[confirmar]** no primeiro deploy.
Política de limpeza no Artifact Registry: manter as 2 imagens mais recentes (fica na cota de 0,5 GB).

CI: primeiro deploy manual pelo `infra/deploy_dash.sh`. Depois, opcional, um job no `ci.yml` só
quando `dash/**` ou `infra/bq/**` mudar (exige papéis novos na `stick-word-group-deploy` — decidir depois).
A CI já pode validar: JSON dos painéis parseia, `uid` únicos, toda view referenciada existe em
`infra/bq/views/`, nenhum número de telefone literal nos arquivos (repo é público).

**ADR-0031 — Painel no Grafana OSS em Cloud Run com IAP** (tabela 1.2; auth anônima vs auth.proxy).

## 6. O painel (`dash/dashboards/stick-word-group.json`)

Variáveis no topo: intervalo de tempo, `tipo` (privado/grupo/todos), `grupo`. Linhas na ordem de
"olhar primeiro":

### Linha 1 — Saúde agora (stat tiles, verde/amarelo/vermelho)
- **Sessão do WhatsApp** (último `waha_status`) · **Falhas nas últimas 24 h** (vs média de 7 dias)
- **Último snapshot** (horas desde `snapshot_ok`; vermelho > 30 h) · **Reinícios do bot em 24 h**
  (eventos `inicio`; crash loop aparece aqui)
- **Firestore: % dos 1 GiB** (estimado) · **Leituras hoje vs 50k** (Cloud Monitoring)
- **Gasto líquido no mês** e previsão de fechamento

### Linha 2 — Alcance
- **Grupos**: ativos · pendentes · desativados · no WhatsApp (WAHA). Divergência entre "no
  WhatsApp" e "ativos + pendentes" = sinal de problema
- Espaços privados · pessoas distintas · **ativos em 1/7/30 dias** (DAU/WAU/MAU por `mensagem_recebida`)
- Série: mensagens/dia por tipo de espaço; novos espaços/semana
- **Números sem plano que tentaram usar** por dia (demanda)

### Linha 3 — Conteúdo (`/list`)
- **Tabela: termos por grupo** (desc) — grupo, admin que ativou (mascarado), membros, termos,
  novos na semana, % praticados, vencidas, última atividade
- **Tabela: termos por pessoa** (desc) — nome, número mascarado, termos no privado, termos em
  grupos, frases, respostas em grupo, nº de grupos, lembretes/dia, última atividade
- **Distribuição de termos por espaço**: mín, média, p50, p75, p90, máx (privados e grupos
  separados) + histograma
- Crescimento acumulado de termos (série diária do snapshot)
- Termos por CEFR, por classe, por tag; origem (usuário vs expansão vs música)
- **Top palavras salvas em mais espaços** (o que os alunos mais pesquisam — insight de conteúdo)

### Linha 4 — Lembretes e revisão
- **Distribuição de lembretes por espaço** (mín, média, p75, p90, máx), em duas medidas:
  **configurados** (`lembretes_por_dia` entre quem ligou, do snapshot) e **enviados** nos últimos
  7/30 dias (`lembrete_enviado`, dos logs) — separado por privado/grupo
- % de espaços com lembrete ligado; % com `lembrete_sem_resposta = true` (ignoram o bot)
- Lembretes enviados vs revisões concluídas (taxa de conversão do lembrete)
- **Backlog**: vencidas por espaço (top 10) — espaço com backlog crescendo tende a abandonar
- Qualidade das respostas (de_novo/difícil/bom/fácil) por semana; lapsos médios por termo
- Grupos: taxa de resposta de quem foi marcado, marcações expiradas, respostas espontâneas

### Linha 5 — Admins e acesso
- **Tabela: admin × grupos** — número do admin (🔒, ver 7), adicionado em, grupos ativos,
  grupos já ativados, nomes dos grupos, termos e membros somados
- Grupos pendentes (há quanto tempo; o bot sai em 24 h)
- Funil: bot adicionado → ativado → primeiro termo salvo → primeira revisão (por grupo)

### Linha 6 — IA (Vertex/Gemini) e voz (Cloud TTS)
- Chamadas/dia por método (`route`, `explain`, `evaluate`, `review`, `song_line`…)
- Latência p50/p95 por método · taxa de falha/rejeição (`ok=false`)
- Tokens/dia e **custo estimado** (tokens × preço), para comparar com o billing
- **Pronúncia (M23–M26)**: caracteres sintetizados/dia, **taxa de acerto do cache** (só o *miss*
  custa), custo estimado do Cloud TTS

### Linha 7 — Falhas e infraestrutura
- **Falhas por dia**, empilhadas por origem (bot ERROR, IA, WAHA fora de WORKING, webhook
  rejeitado, LID não resolvido, agendador)
- **Top mensagens de erro** (tabela, contagem, último visto) — a lista de "o que consertar"
- Firestore: leituras/escritas/deletes por dia vs cotas (50k/20k/20k) — Cloud Monitoring
- VM: CPU (`compute.googleapis.com/instance/cpu/utilization`, grátis e sem agente); RAM e disco
  exigiriam o Ops Agent — fora do escopo (a RAM já é o gargalo da e2-micro)
- Armazenamento estimado por coleção e **top espaços por bytes**

### Linha 8 — Custo
- Gasto líquido do mês, bruto, créditos, previsão de fechamento
- Por serviço (Compute/IP externo, Vertex AI, Firestore, Storage, Logging, BigQuery, Cloud Run)
- Série diária · custo por pessoa ativa (líquido ÷ MAU) — métrica útil para o piloto

Exemplo de consulta de distribuição (view `v_distribuicoes`):

```sql
SELECT tipo,
       MIN(n_termos) AS minimo, AVG(n_termos) AS media,
       APPROX_QUANTILES(n_termos, 100)[OFFSET(75)] AS p75,
       APPROX_QUANTILES(n_termos, 100)[OFFSET(90)] AS p90,
       MAX(n_termos) AS maximo
FROM stick_word_group_metrics.espacos
WHERE dt = (SELECT MAX(dt) FROM stick_word_group_metrics.espacos)
GROUP BY tipo
```

Com poucos espaços, `APPROX_QUANTILES` é exato o bastante; p90 de 5 valores é quase o máximo —
o painel mostra o `n` ao lado para não enganar.

### Alertas (opcional, fora do MVP do painel)
Métrica baseada em log "erros do bot" + política de alerta por e-mail no Cloud Monitoring
("> 5 erros em 10 min" e "nenhum `snapshot_ok` em 30 h"). **[confirmar]** se políticas de alerta
passaram a ser cobradas antes de criar.

## 7. Privacidade e segurança

- **Repo público**: nenhum número, nome de grupo ou dado real em `dash/`, `infra/bq/` ou testes.
  Só consultas e esquemas. Teste na CI procura sequências de 10+ dígitos nesses arquivos.
- **Logs**: nunca número completo nem texto do aluno (regra atual, reforçada pela lista branca de
  campos do M27).
- **Colunas 🔒** (`ativado_por`, `admin_numero`): o pedido é ver "os números dos admins". Eles são
  poucos e conhecidos (equipe do cursinho), mas é dado pessoal. **Decisão do usuário**: (a) gravar o
  número completo só na tabela `admins`/`espacos`, com o bucket e o dataset restritos à SA do
  painel e ao dono; ou (b) só mascarado + um apelido do admin guardado no Firestore (`!admin add
  NUM apelido`). Recomendação: **(a)** para admins, **mascarado** para alunos.
- `id_curto` (sha256[:8] sem sal) de telefone é reversível por força bruta; serve para juntar dados
  dentro do projeto, não é anonimização. Não expor fora do painel.
- O `/forget` do M18 precisa também apagar a pessoa dos snapshots (ou os snapshots têm retenção
  curta o bastante). Anotar em `docs/noite/PENDENCIAS.md`.
- Acesso ao painel: só as contas liberadas no IAP.

## 8. Ordem de implementação e o que o usuário faz

| Marco | Entrega | Comandos de GCP (usuário aprova e roda com `!`) | Commit/ADR |
|---|---|---|---|
| **M27** | ✅ eventos estruturados, handler do bot para o Cloud Logging — **pendente:** Log Analytics | `logging buckets update --enable-analytics`, `logging links create` | ADR-0028, spec seção 12 |
| **M28** | ✅ `Banco.listar_espacos`, `autor_id`/`nome`, `montar_snapshot`, `scripts.snapshot` — **pendente:** bucket + dataset + tabelas externas + views | `infra/terraform/storage.tf` (bucket + dataset), `bq mk --external_table_definition` × 6, views | ADR-0029, spec 7.1 e 12 |
| **M29** | export de Billing, orçamento, views de custo | console de Billing; `billing budgets create` | spec 12 |
| **M30** | `dash/`, SA `stick-word-group-dash`, Cloud Run + IAP, painel completo | `services enable run/artifactregistry/cloudbuild`, SA + papéis, `run deploy --iap`, `iap web add-iam-policy-binding` | ADR-0031 |

Dá para ter valor cedo: ao fim do **M27** já se vê falhas no Log Analytics da própria GCP (sem
painel); ao fim do **M28**, as tabelas de grupos/pessoas/admins podem ser consultadas no BigQuery
Studio; o M30 só coloca a vitrine.

Cada marco: `make check` verde, `make test-emulador` quando mexer no `Repository`, branch + PR,
parar e relatar (regras do `CLAUDE.md`).

## 9. Itens a confirmar antes de começar (resumo dos [confirmar])

1. ~~Formato do `gcplogs`~~ — **descartado** (não implementa leitura, quebraria `docker logs`); ver
   2.3. ~~Formato do `jsonPayload` do `CloudLoggingHandler`~~ — **confirmado e corrigido** em
   produção (2026-09-27): precisa do mesmo `JsonFormatter` no handler extra, ver 2.3.
2. `usage_metadata` do `google-genai` no Vertex e preço por token do modelo em uso.
3. Endpoint de listagem/contagem de grupos no WAHA GOWS `2026.8.2`.
4. Existência de métrica de armazenamento do Firestore no Cloud Monitoring; se o uso dentro da
   cota aparece no export de Billing.
5. Localização: dataset `US` lendo bucket `us-central1`; localização do dataset linkado do
   bucket `_Default` (global).
6. Papel exato para ler o dataset linkado do Log Analytics.
7. Tag atual do `grafana/grafana-oss` e versão do plugin `grafana-bigquery-datasource`.
8. IAP em Cloud Run com conta Gmail sem organização (tela de consentimento externa / cliente OAuth).
9. Cotas grátis atuais (Cloud Build, Cloud Run, Logging, BigQuery, GCS, Firestore) e cobrança de
   políticas de alerta.

## 10. Decisões em aberto (do usuário)

1. ~~Número completo dos admins no BigQuery~~ — **decidido (2026-09-27): completo** (opção a).
2. Grafana com acesso anônimo atrás do IAP ou `auth.proxy` com o e-mail do IAP.
3. ~~Adicionar `Entry.autor_id` e `Profile.nome`~~ — **feito no M28.**
4. Alertas por e-mail agora ou depois.
5. Deploy do painel pela CI ou só manual.

## Fontes consultadas

- [IAP direto no Cloud Run (sem load balancer)](https://docs.cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run)
- [Grafana — configurar o datasource BigQuery (auth `gce`)](https://grafana.com/docs/plugins/grafana-bigquery-datasource/latest/configure/)
- [Export do Cloud Billing para BigQuery](https://docs.cloud.google.com/billing/docs/how-to/export-data-bigquery-setup) · [estrutura do export padrão](https://docs.cloud.google.com/billing/docs/how-to/export-data-bigquery-tables/standard-usage) · [consultas de exemplo](https://docs.cloud.google.com/billing/docs/how-to/bq-examples)
- [Log Analytics](https://docs.cloud.google.com/logging/docs/log-analytics) · [dataset linkado no BigQuery](https://docs.cloud.google.com/logging/docs/analyze/query-linked-dataset)
- [Firestore — monitorar uso](https://docs.cloud.google.com/firestore/native/docs/monitor-usage) · [cálculo de tamanho de armazenamento](https://cloud.google.com/firestore/native/docs/storage-size)
- [Driver `gcplogs` do Docker](https://github.com/GoogleCloudPlatform/community/blob/master/archived/docker-gcplogs-driver/index.md)
- [WAHA — grupos](https://waha.devlike.pro/docs/how-to/groups/) · [issue do GOWS em `GET /groups`](https://github.com/devlikeapro/waha/issues/1962)
