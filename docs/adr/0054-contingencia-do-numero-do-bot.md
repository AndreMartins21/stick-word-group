# ADR-0054: Contingência para sessão caída ou número banido

- **Status:** Aceito
- **Data:** 2026-10-12

## Contexto

O WAHA/GOWS é uma API não oficial do WhatsApp (contra os Termos): o número do bot pode ser banido ou
deslogado sem aviso, e o bot, sem sessão, não consegue nem avisar o dono pelo próprio WhatsApp. A
auditoria de 2026-10-12 (achado A7) apontou a ausência de plano de resposta. O bot já registra
`waha_status` (WARNING quando não está `WORKING`), mas ninguém é avisado.

## Decisão

1. **Detecção:** alerta no Cloud Monitoring, baseado em log (`conditionMatchedLog`), para
   `waha_status` com `motivo` em `FAILED`, `STOPPED` ou `SCAN_QR_CODE`, enviado por **e-mail** (o
   canal não depende do WhatsApp). Limite de uma notificação por hora; fecha sozinho em 30 min.
   Criado por `infra/setup_alerta_sessao.sh` (idempotente, `DRY_RUN=1`).
2. **Resposta:** um runbook em `docs/runbooks/banimento-do-numero.md` separa sessão deslogada (re-parear
   o mesmo número) de ban (número reserva), com os passos, comandos e o modelo de aviso às turmas.
3. **Dados:** nada a migrar na troca de número. O caderno é por id de grupo/pessoa no Firestore, e o
   disco e o banco têm backup (ADR-0051). Só o segredo `BOT_NUMBER` muda.
4. **Prevenção:** manter um chip reserva com WhatsApp Business ativo (fora do código) e as defesas já
   existentes (limites, fila, orçamento, jitter dos lembretes, ADR-0053).
5. Nenhuma troca automática de número: parear exige o QR, que é uma ação humana.

## Alternativas consideradas

- **API oficial (WhatsApp Cloud API)** — descartada por ora: exige verificação de empresa, templates
  e custo por conversa, e muda o produto; fica como evolução se o volume justificar.
- **Segundo número pareado em paralelo (hot standby)** — descartada: dobra o risco de ban (dois
  números não oficiais) e o consumo de memória do WAHA, no e2-micro de 1 GB.
- **Aviso ao dono pelo próprio bot** — descartada: com a sessão caída, o bot não envia nada.

## Consequências

- O alerta pode disparar um `STOPPED` falso num deploy; o runbook diz como reconhecê-lo. A taxa
  observada é de ~1 por semana.
- A troca de número tem custo humano (adicionar o número em cada grupo): o runbook lista o modelo de
  aviso, mas o tempo de resposta depende de quem administra cada grupo.
- Um ban continua sendo uma indisponibilidade de horas ou dias; o plano a reduz, não a elimina.
