# ADR-0063: Infra em Terraform, num projeto GCP próprio (stick-word-group), sem o nome vocabot

- **Status:** Aceito
- **Data:** 2026-10-27

## Contexto

O ADR-0062 separou o código, mas manteve este projeto na produção herdada: projeto GCP
`anki-whatsapp`, recursos `vocabot-*`. Esse projeto acumulou recursos do antigo produto individual
(bucket de export, papéis que só serviam ao export) que nenhum script daqui cria nem remove, e não
havia como saber, só pelo repositório, o que na GCP é deste projeto. A infra era uma sequência de
scripts `infra/setup*.sh` imperativos (criar se não existir): idempotentes, mas sem detectar
desvio, sem apagar o que saiu do código e presos a um projeto por nomes fixos.

O usuário criou um projeto novo, `stick-word-group`, pediu que a infra fosse declarada em Terraform
para facilitar mudanças de projeto como esta, e que os nomes `vocabot` e `anki` saíssem dos
recursos.

## Decisão

- **Toda a infra GCP fica em `infra/terraform/`** (provider `hashicorp/google` 7.x, Terraform
  ≥ 1.11): APIs, Firestore (TTL + PITR), contas de serviço e IAM, buckets e dataset de métricas,
  segredos, firewall, VM com o snapshot diário, WIF do deploy, alerta de sessão e Budget. Os
  `infra/setup.sh`, `setup_cicd.sh`, `setup_backup.sh`, `setup_metricas.sh`, `setup_orcamento.sh`,
  `setup_alerta_sessao.sh` e `lifecycle-metricas.json` foram removidos. Ficam os scripts de
  **operação** (`deploy.sh`, `pair.sh`, `logs.sh`, `ssh.sh`, `smoke_test.sh`, `secrets.sh`, `vm/`).
- **Estado remoto** em `gs://<projeto>-tfstate` (versionado), com o bucket passado no `init`
  (`make tf-bootstrap tf-init`): o mesmo código serve a qualquer projeto trocando só `project_id`.
- **Segredo nenhum no estado:** os valores do WAHA saem de um `ephemeral "random_password"` para o
  argumento write-only `secret_data_wo`. Rotação = aumentar `versao_segredos`.
- **Nomes:** prefixo `stick-word-group` (`stick-word-group-vm`, `stick-word-group-deploy`,
  `/opt/stick-word-group`, log `stick-word-group`); buckets `<projeto>-audio`, `<projeto>-metrics`;
  dataset `stick_word_group_metrics` (BigQuery não aceita hífen). ADRs antigos não foram editados
  (regra do índice) e seguem citando `vocabot`/`anki-whatsapp` como registro histórico. "Anki", o
  aplicativo de flashcards, e "stick-word", o projeto irmão, continuam com esses nomes.
- O projeto `anki-whatsapp` não é tocado por este código; o usuário vai apagá-lo à mão.

## Alternativas consideradas

- **Manter os `.sh` e só trocar os nomes** — resolve o nome, não o desvio: o que o projeto antigo
  acumulou fora do código seria invisível também no novo.
- **Pulumi / Deployment Manager / Infrastructure Manager** — o Deployment Manager está descontinuado;
  Pulumi traria outra linguagem e outro serviço de estado; o Infrastructure Manager roda Terraform
  por baixo e pode ser adotado depois sem reescrever nada.
- **Segredos gerados por `random_password` comum** — o valor ficaria em texto puro no estado (no
  bucket); com `secret_data_wo` ele nunca sai da execução.
- **Gerar os segredos fora do Terraform (openssl por pipe, como antes)** — funciona, mas deixa um
  passo manual na transferência; o write-only alcança o mesmo sigilo sem ele.
- **Importar a infra do `anki-whatsapp` no Terraform** — preservaria a sessão do WAHA e os dados,
  mas levaria junto os nomes e os recursos que o usuário quer descartar.

## Consequências

- Recomeço do zero: Firestore vazio (turmas, palavras, admins e o histórico do ranking ficam no
  `anki-whatsapp` até ele ser apagado) e o número precisa ser pareado de novo no WAHA da VM nova.
  Se os dados importarem, exportar/importar o Firestore **antes** de apagar o projeto antigo.
- O mesmo número não pode ficar com dois WAHA ativos: a VM antiga precisa parar antes do pareamento
  na nova, senão as duas responderiam nas turmas.
- Mudar a infra agora é `make tf-plan` / `make tf-apply`; mexer na GCP pelo console gera desvio que o
  próximo `plan` mostra.
- O deploy contínuo passou a depender das Variables novas no repositório (`GCP_PROJECT_ID`,
  `GCP_WIF_PROVIDER` de `terraform output github_variables`) e dos Secrets `ALLOWED_NUMBER`/
  `BOT_NUMBER`, que no repositório novo ainda não existiam.
- O log do bot muda de nome (`vocabot` → `stick-word-group`): consultas e painéis que filtram por
  `logName` precisam do nome novo.
- Revisitar se: a infra crescer a ponto de pedir mais de um ambiente (aí, módulos ou workspaces).
