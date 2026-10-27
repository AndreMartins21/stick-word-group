# CLAUDE.md — stick-word-group

Bot de WhatsApp para **turmas de inglês em grupo**: vocabulário da turma, revisão diária e desafio
semanal. No privado, só o dono e os admins, e só com os comandos de admin; qualquer outro número é
ignorado sem gastar IA. O estudo individual é o projeto irmão **stick-word** (ADR-0062).

Instruções para o Claude Code trabalhar neste repositório. Responda sempre em **PT-BR**.

## Fonte da verdade

A especificação completa do projeto está em **[`spec/spec-inicial.md`](spec/spec-inicial.md)** — escopo,
stack, máquina de estados, contratos de dados, infraestrutura e a tabela de marcos. **Leia a seção relevante antes de escrever código.** Código que contraria a spec é bug.

Trabalhe **marco a marco** (seção 9 da spec): pare ao fim de cada um, relate e espere aprovação.

## Regras de ouro

1. **Nunca** peça, leia, imprima ou grave valores de segredos. Não há chave de IA (Vertex AI usa a
   conta de serviço da VM). Segredos vivem no Secret Manager; o `.env` local tem valores falsos.
2. Antes de qualquer comando `gcloud`/`ssh` que **crie, altere ou apague** algo: mostre o comando e
   espere aprovação. Leitura pode rodar direto.
3. Se a spec estiver ambígua ou parecer errada, **pergunte** — não invente.
4. Todo texto voltado ao usuário fica em `app/messages.py`, **em inglês** (curto e amigável) —
   só a linha 🇧🇷, com a tradução literal, fica em PT-BR (M9) — exceções: turma iniciante (A1-A2, A2-B1) vê a 🇧🇷 e a explicação da pergunta do desafio semanal em PT antes do inglês (ADR-0032, ADR-0034).
5. Confirme na documentação oficial atual (WAHA, Vertex AI, SDK `google-genai`) nomes de endpoints,
   variáveis e IDs de modelo antes de usá-los. Fixe versões de imagem Docker (nunca `latest`).
6. Um commit ao fim de cada marco.
7. Decisão de arquitetura, escolha entre alternativas reais ou mudança de uma decisão já
   registrada: escreva um ADR em `docs/adr/` (ver a skill `adr`) no mesmo commit que a implementa.

## Skills

Estas skills carregam sozinhas quando o contexto pede; invoque explicitamente se precisar:

| Skill | Quando |
|---|---|
| `sdd` | implementar qualquer parte do projeto, começar/fechar marco, divergência com a spec |
| `adr` | decidir entre alternativas técnicas, mudar/substituir uma decisão, registrar o porquê |
| `tdd` | nova lógica de negócio, correção de bug (teste que reproduz primeiro) |
| `python-best-practices` | escrever/revisar código Python |
| `gcp-best-practices` | Terraform e scripts em `infra/`, comandos `gcloud`, IAM, custos, deploy |
| `git-workflow` | commits, branches, PRs, limpeza de histórico |
| `git-deploy-workflow` | commit/PR/merge neste repo (main protegida), `ci.yml`, `infra/terraform/cicd.tf`, depurar o deploy automático |

`sdd`, `adr`, `gcp-best-practices` e `git-deploy-workflow` são do projeto (`.claude/skills/`); as
demais são globais do usuário.

## Comandos

```bash
make setup    # venv (Python 3.12) + dependências + hooks de pre-commit
make check    # o que a CI roda: ruff + mypy + pytest
make test     # pytest
make test-emulador  # contrato do Repository também contra o emulador do Firestore (Docker)
make evals    # taxa de acerto da avaliação de frases contra a API real (custa centavos)
make fmt      # formata e corrige lint
make run      # API local em :8000
make sim      # simulador de terminal (sem WhatsApp)
make tf-plan  # infra (infra/terraform): tf-bootstrap, tf-init, tf-plan, tf-apply
```

O gerenciador de pacotes é o **uv**. Não use `pip install` direto nem crie `requirements.txt`:
dependências entram no `pyproject.toml` (`uv add <pacote>`).

## Estrutura

```
app/       código da aplicação (main, channel/, domain/, flows/, services/, repo/)
sim/       simulador de terminal
evals/     avaliação de qualidade dos modelos (fora do pytest)
infra/     terraform/ (toda a infra GCP, ADR-0063) + scripts de operação (shellcheck limpo)
tests/     pytest + fixtures de payloads
docs/adr/  decisões arquiteturais
spec/      especificação do projeto
```

O layout esperado completo está na seção 11 da spec.

## Convenções

- **Testes nunca dependem de credencial ou rede.** Cada dependência externa (WAHA, Firestore,
  Storage, LLM) tem um fake em memória por trás de uma interface (`Channel`, `Repository`,
  `LLMProvider`). A lógica de negócio não importa nada do WAHA diretamente.
- O PDF do `/ranking` é testado relendo o arquivo gerado (pypdf).
- Decisões com consequência duradoura viram ADR em `docs/adr/` — numeração `NNNN-titulo-curto.md`,
  índice e regras em `docs/adr/README.md`. `make test` reprova ADR malformado ou fora do índice.
- Mudou um contrato? Atualize a spec **no mesmo commit** que muda o código.
- Logs estruturados, sem segredo, sem número de telefone completo, sem corpo de resposta inteiro.
