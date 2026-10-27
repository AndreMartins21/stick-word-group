# Runbook: sessão do WhatsApp caída ou número banido

O stick-word-group usa o WAHA/GOWS, uma API **não oficial** do WhatsApp (contra os Termos de Serviço): o número
pode ser banido ou deslogado a qualquer momento. Este roteiro diz o que fazer, na ordem. Decisão e
motivos: ADR-0054.

## 1. Sinais

- **E-mail do alerta** `stick-word-group-sessao-whatsapp-caiu` (criado por `infra/setup_alerta_sessao.sh`): o
  `waha_status` chegou a `FAILED`, `STOPPED` ou `SCAN_QR_CODE`.
- Alunos dizem que o bot parou de responder.
- `infra/logs.sh` ou o Cloud Logging mostram `waha_status` com `ok=false`.

Um `STOPPED` isolado logo depois de um deploy é normal (o container reinicia e volta a `WORKING` em
~1 min). Só vale agir se a sessão **não volta a `WORKING`**.

## 2. Diagnóstico rápido (5 min)

1. Veja o estado: `bash infra/logs.sh` (procure `waha_status`) ou abra o painel do WAHA com
   `bash infra/pair.sh` e olhe a sessão `default`.
2. Reinicie só o WAHA: `bash infra/ssh.sh` → `cd /opt/stick-word-group && sudo docker compose restart waha`.
3. Voltou a `WORKING`? Era instabilidade. Pare aqui.
4. Pediu QR (`SCAN_QR_CODE`)? Tente **re-parear o mesmo número** (passo 3A).
5. O WhatsApp no celular do bot mostra "número banido", "conta bloqueada" ou não deixa parear? É ban
   (passo 3B).

## 3A. Sessão deslogada, número ok: re-parear

1. `bash infra/pair.sh` → abra `http://localhost:13000/dashboard` (usuário `admin`; a senha é a do
   Secret Manager, que **você** lê quando precisar).
2. Na sessão `default`, inicie e escaneie o QR com o app **WhatsApp Business** do número do bot.
3. Confirme `WORKING` e mande `!help` num grupo para testar.

Nada mais muda: grupos, caderno e perfis ficam intactos (estão no Firestore, por id de grupo).

## 3B. Número banido: trocar pelo número reserva

**Antes (prevenção, faça já):** tenha um **chip reserva** com o WhatsApp Business instalado e ativo,
usado de verdade de vez em quando (mensagens normais, alguns grupos). Número novo sem histórico é
banido mais rápido.

1. **Atualize o segredo `BOT_NUMBER`** (só dígitos, com 55) nos Secrets do repositório no GitHub
   (`Settings → Secrets and variables → Actions`). Ele é usado para reconhecer a marcação e a citação
   do bot. Se o número novo estiver na allowlist, nada mais muda em `ALLOWED_NUMBERS`.
2. **Remova a sessão antiga** no painel do WAHA (sessão `default` → Logout/Delete) e crie de novo.
3. **Pareie o número reserva**: `bash infra/pair.sh` e escaneie o QR com o WhatsApp Business dele.
4. **Redeploy** para o `BOT_NUMBER` novo valer: em Actions, rode o workflow de deploy (ou faça um merge
   qualquer na `main`).
5. **Adicione o número novo a cada grupo** (um admin do grupo faz isso). O vocabulário, as turmas e as
   configurações continuam, porque ficam no Firestore pelo **id do grupo**, não pelo número.
6. Em cada grupo, mande `!group` para conferir. Se aparecer como pendente, um admin do bot manda
   `!activate` (o bot sai de grupo pendente depois de 24 h).
7. **Avise as turmas** (modelo abaixo) e peça que salvem o número novo.

### Modelo de aviso às turmas

> Olá, turma! O número do stick-word-group mudou: salvem o novo contato (+55 …). Tudo o que vocês já
> estudaram continua salvo. Se não me vir no grupo, me avisem por aqui. 🙌

## 4. Depois

- Registre o incidente (data, sinal, causa provável) em `docs/noite/PENDENCIAS.md` ou no ADR 0054.
- Se foi ban, revise o que pode ter disparado: volume de mensagens, muitos grupos recém-adicionados,
  denúncias, conteúdo ofensivo repetido (a transcrição de áudio é republicada no grupo).
- Providencie um **novo chip reserva** para a próxima vez.

## 5. O que reduz o risco (já em produção)

- Digitação com atraso humano e tamanho máximo de mensagem (M40).
- Limites por pessoa e por grupo, fila por chat e pausa por orçamento (M43, M47, M50).
- Lembretes escalonados entre 18:40 e 19:20 (M55, ADR-0053), para o número não disparar uma rajada
  às 19:00:00.
- Grupos só entram por `!activate` de um admin (M15).

## 6. O que não dá para fazer

- O bot **não consegue avisar você pelo WhatsApp** que o número caiu: quem avisa é o e-mail do alerta.
- Recuperar um número banido: depende de apelo ao WhatsApp, e não há garantia.
