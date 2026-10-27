---
name: git-deploy-workflow
description: Fluxo de Git e deploy específico deste repositório desde o M11 — a main é protegida (PR obrigatório, sem push direto), o merge dispara o deploy sozinho via GitHub Actions com Workload Identity Federation, e há armadilhas já descobertas na configuração desse pipeline (papel do túnel IAP, nome dos status checks, versão do gh, classificador de permissão do Claude Code). Use SEMPRE que for commitar, abrir PR, mergear, mexer em .github/workflows/ci.yml, em infra/terraform/cicd.tf, na branch protection da main, ou depurar por que um deploy automático não disparou.
---

# Git e deploy contínuo — stick-word-group

## O fluxo, desde o M11 (ADR-0013)

A `main` tem branch protection: **PR obrigatório** (sem push direto, `enforce_admins: true` — nem o
dono do repo escapa) e três checks obrigatórios (`checks`, `test`, `compose` do `ci.yml`). Mergear um
PR com CI verde **já é publicar**: o job `deploy` dispara sozinho, sem gate de aprovação manual (foi
decisão explícita do usuário — ver ADR-0013 e as alternativas descartadas).

Sequência normal de trabalho:
1. `git checkout -b feature/<intenção>` (nunca commitar direto na `main` — o GitHub bloqueia mesmo).
2. Commit(s) atômicos (ver a skill global `git-workflow` para mensagem/granularidade); ADR no mesmo
   commit se a mudança for uma decisão de arquitetura (CLAUDE.md regra 7).
3. `git push -u origin <branch>` + `gh pr create`.
4. Esperar os três checks (`gh pr checks <n>`) — o job `deploy` aparece como `skipping` num PR, é
   esperado, ele só roda em `push` para `main`.
5. `gh pr merge <n> --squash --delete-branch` → dispara o `deploy` de verdade contra a VM de
   produção. Acompanhar (`gh run watch` ou poll) até o `smoke_test.sh` confirmar.

## Armadilhas já descobertas (não repetir)

- **Nem todo papel de IAM aceita binding por instância, mesmo quando `gcloud` aceita a sintaxe.**
  Dois casos reais neste projeto, ambos resolvidos concedendo **no projeto**
  (`gcloud projects add-iam-policy-binding`) em vez de só na instância — como este projeto nunca
  tem mais de uma VM (spec 10.8), na prática o binding no projeto já fica restrito a ela:
  - `roles/iap.tunnelResourceAccessor`: `gcloud compute instances add-iam-policy-binding VM
    --role=roles/iap.tunnelResourceAccessor` dá `HTTPError 400: Role ... is not supported for this
    resource`. Não existe `gcloud iap tunnel-instances add-iam-policy-binding`; o caminho por
    instância que a Google documenta é uma chamada crua à API REST (`setIamPolicy` em
    `iap.googleapis.com/.../iap_tunnel/.../instances/NAME`).
  - `roles/compute.viewer`: o binding por instância **aceita** sem erro, mas não é suficiente — só
    aparece o problema no deploy de verdade: `gcloud compute scp`/`ssh` chamam
    `compute.projects.get` antes de conectar, e essa permissão só existe no escopo do projeto. Sem
    isso o deploy falha com `Required 'compute.projects.get' permission for 'projects/...'`.
  `compute.osAdminLogin` continua por instância sem problema
  (`gcloud compute instances add-iam-policy-binding`).
- **SSH numa VM que roda como conta de serviço exige `roles/iam.serviceAccountUser` sobre essa
  conta** (`gcloud iam service-accounts add-iam-policy-binding`, só sobre a `stick-word-group-vm`). Sem isso:
  `User does not have iam.serviceAccounts.actAs permission on the instance's service account`.
  Consequência de segurança: `osAdminLogin` (root) + `serviceAccountUser` fazem a `stick-word-group-deploy`
  alcançar tudo que a `stick-word-group-vm` alcança — a defesa é a attribute condition do provider WIF e a
  branch protection da `main`, então nunca afrouxe nenhuma das duas.
- **Cada permissão que falta só aparece rodando o deploy de verdade**, uma por vez (`compute.projects.get`,
  depois `actAs`, ...). Não dá para validar o IAM só lendo: depois de mexer em `infra/terraform/cicd.tf`,
  re-execute só o job falho com `gh api --method POST repos/OWNER/REPO/actions/runs/<id>/rerun-failed-jobs`.
- **`required_status_checks.contexts` da branch protection precisa do *nome de exibição* do job**
  (o campo `name:` dentro do job no YAML), não da chave do job. Configurar `contexts: [checks, test,
  compose]` (as chaves) nunca bate com o que a Actions reporta de verdade (ex.: "Lint, formatação,
  tipagem e segredos"), e o PR fica com `mergeStateStatus: BLOCKED` para sempre, mesmo com os três
  checks verdes. Confira com `gh pr checks <n>` os nomes reais antes de configurar a proteção, ou
  compare com `gh api repos/OWNER/REPO/branches/main/protection --jq .required_status_checks`.
- **`gh variable set` exige gh ≥ 2.31.** Num gh antigo, use a API:
  `gh api --method POST repos/OWNER/REPO/actions/variables -f name=NOME -f value=VALOR` (cai para
  `--method PATCH .../actions/variables/NOME` se já existir).
- **Comandos `gcloud` e `gh pr merge` às vezes precisam ser rodados pelo próprio usuário**, mesmo
  read-only, dependendo da configuração de permissão da sessão — é esperado, não um erro a
  contornar. Peça para o usuário rodar com o prefixo `!` (ex.: `! gh pr merge 3 ...`) ou no terminal
  dele; ver golden rule 2 do CLAUDE.md sobre aprovação antes de comando que cria/altera/apaga algo.
- **Um script com `read -r -p` (confirmação interativa) rodado via `!` não fica interativo** — ele
  captura a saída e some no prompt, deixando o script pendurado. Peça para o usuário rodar com a
  resposta já encanada (ex.: `! printf 's\n' | bash infra/secrets.sh`).
- **Nunca leia `infra/.env.infra` diretamente** (além de ser a regra de ouro 1, o próprio sistema de
  permissão bloqueia `grep`/`cat` nesse arquivo). Para levar valores dele até o GitHub sem que a
  Claude os veja, peça para o usuário rodar um comando que faz `source` do arquivo localmente e
  chama `gh secret set` / `gh api .../actions/variables` na mesma linha — os valores nunca aparecem
  no texto do comando nem na resposta.

## Onde cada coisa mora

- Pipeline: `.github/workflows/ci.yml` (jobs `checks`, `test`, `compose`, `deploy`).
- Provisionamento do CI/CD: `infra/terraform/cicd.tf` (WIF pool/provider + SA
  `stick-word-group-deploy`; o repositório confiável é `var.github_repo`). Os valores de
  `GCP_PROJECT_ID`/`GCP_WIF_PROVIDER` saem de `terraform output github_variables` (ADR-0063).
- Decisão e alternativas descartadas: `docs/adr/0013-deploy-continuo-via-github-actions.md`.
- Contrato/critério de aceite: spec `10.9` e marco `M11`.
