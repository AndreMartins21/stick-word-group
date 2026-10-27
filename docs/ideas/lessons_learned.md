# Lições aprendidas

O que só apareceu ao rodar de verdade (Gemini real, compose local, VM, WhatsApp pareado) e que os
testes com fakes não pegavam. Cada item tem o sintoma, a causa e o que ficou no código. Serve para não
redescobrir a mesma coisa e para orientar melhorias futuras.

Decisões com consequência duradoura ficam em [`docs/adr/`](../adr/README.md); este arquivo é o diário
do "o que deu errado e por quê".

## WhatsApp e WAHA

### O número real da conta pode não ter o nono dígito
- **Sintoma:** o bot recebia a mensagem, marcava como lida, mas a resposta nunca chegava. No WAHA:
  `no LID found for <número com 9>@s.whatsapp.net from server`.
- **Causa:** contas brasileiras antigas são registradas **sem** o 9 depois do DDD (12 dígitos), mas o
  `ALLOWED_NUMBER` foi escrito com o 9 (13 dígitos). A allowlist tolerava a variação ao *comparar*, mas o
  envio usava o número do `.env`.
- **Correção:** responder ao número **real** do remetente já autorizado (o `pn` que o WAHA devolve para o
  LID, ou o `from` quando vem como `@c.us`). `Conversa.definir_destino` e `Router.processar(destino=...)`;
  spec 8.2 atualizada.
- **Lição:** tolerar uma variação ao comparar não basta; o valor que vai para a API externa tem que ser o
  que o serviço reconhece. Conferir com dados reais (aqui, comparando só os *tamanhos* dos números, sem
  imprimi-los).

### O remetente chega como LID, e o WAHA sabe traduzir
- `GET /api/{session}/lids/{lid}` devolve `{"lid": ..., "pn": "<número>@c.us"}`. Funcionou de primeira no
  GOWS, então o risco de LID que ficou em aberto desde o M1 se resolveu com um teste real. O cache
  LID→número (no `Repository`) evita consultar o WAHA a cada mensagem.

### O GOWS manda `to` e `body` nulos quando não decifra a mensagem
- **Sintoma:** primeiro `/ajuda` após parear: o bot respondia **HTTP 500**, e o WAHA reenviava o mesmo evento
  a cada 2 segundos, sem parar. Nos logs do WAHA: `Undecryptable message ... content lost unless the sender
  answers the retry receipt`.
- **Causa:** `MessagePayload` exigia `to: str`, e o parse ficava fora do `try`.
- **Correção:** `to` opcional, `body` nulo vira `""`; JSON ilegível ou payload fora do formato vira **200** e um
  log só com os *nomes* dos campos problemáticos; mensagem sem texto e sem mídia é ignorada.
- **Lição:** para um webhook, "sempre 200" não é enfeite: um 500 vira laço de reenvio. E logo depois de
  parear é normal perder as primeiras mensagens (sessão de criptografia ainda se estabelecendo).

### O painel do WAHA precisa da API key
- Com `WAHA_API_KEY` definida, o dashboard mostra "Server connection failed" até você colar a chave nas
  configurações de conexão dele (a chave é diferente da senha do painel).

### A sessão expira se ninguém escaneia o QR
- O QR vale poucos minutos; sem scan a sessão vira `FAILED`. Basta **Restart** na sessão `default`.
- A sequência saudável nos logs do bot: `STOPPED → STARTING → SCAN_QR_CODE → WORKING`.

## Infraestrutura e operação

### A porta 3000 da sua máquina já estava ocupada
- **Sintoma:** "Invalid credentials" no painel, com a senha certa.
- **Causa:** outro container Docker escutava em `0.0.0.0:3000`; o navegador falava com ele, não com o túnel.
- **Correção:** `pair.sh` usa a porta local **13000** (`PORTA_LOCAL` para trocar) e recusa subir se a porta
  estiver em uso.
- **Como diagnosticar sem adivinhar:** comparar o hash da senha do container com a do Secret Manager (mesmo
  hash), testar o login de dentro da VM (funcionou) e ver quem escuta na porta local (`ss -ltnp`).

### `/opt/stick-word-group` é modo 700
- O render do `.env` roda com `umask 077`, então só root entra no diretório. `cd` sem `sudo` falhava
  ("Permission denied"). Comandos remotos rodam inteiros sob `sudo bash -s`.

### `docker compose exec` consome o stdin
- Dentro de um script mandado por `bash -s`, o `exec` lia o resto do script e o cortava no meio; o script
  saía com 0. Corrigido com `</dev/null`.

### Smoke test que dá falso positivo é pior que nenhum
- O primeiro `smoke_test.sh` imprimiu "ok" sem ter checado a sessão do WAHA. Agora o script remoto imprime um
  marcador (`SMOKE_OK`) no fim e o local só declara sucesso se o vir. **Um `exit 0` sozinho não prova nada.**

### `CHAVE=   # comentário` vira valor
- O parser de `.env` do Docker Compose lê o comentário depois de um valor **vazio** como se fosse o valor
  (`WHATSAPP_HOOK_HMAC_KEY` virava `# opcional...`). Comentário só em linha própria; há um teste de higiene.
- Consequência relacionada: `CHAVE=` vazio num `.env` chegava ao `Settings` como texto vazio e uma HMAC vazia
  faria o webhook exigir uma assinatura que o WAHA não envia. Hoje, texto vazio em opcional = "não definido".

### O que o `DRY_RUN=1` já evitou
- Rodar `setup.sh` em modo ensaio mostrou o plano completo antes de qualquer criação e pegou um prompt do
  `gcloud` ("ativar a API? y/N") que teria travado uma leitura. Os scripts rodam com os prompts desligados.

## IA (Gemini)

### Rodar o fluxo com o modelo real achou o que os fakes não achavam
- As **expansões** vinham como frases inteiras com `[[ ]]`: a instrução de marcar o alvo estava no prompt de
  sistema de *todas* as tarefas. Hoje só entra onde há frases, o prompt de expansões pede expressão curta
  (1 a 4 palavras) e o schema rejeita frase/marcação (com nova tentativa automática).
- **Praticar uma expansão** trocava `mitigate risk` por `mitigate` (a IA normaliza para a forma base). A
  entrada da expansão mantém a expressão e a classe da sugestão; o prompt proíbe trocar a palavra digitada.
- O SDK avisava sobre "function calling automático" a cada chamada; desligado na configuração, já que não
  usamos ferramentas.
- **Lição:** testes com `FakeTutor` validam a lógica, não o prompt. Uma corrida com o modelo real (poucos
  centavos) vale antes de cada mudança de prompt: `make sim ARGS=--real-llm` e `make evals`.

### A IA é uma fronteira que precisa de validação própria
- Toda resposta passa por Pydantic e por regras extras (nº de exemplos, expressões sem repetir), com uma nova
  tentativa que devolve o erro ao modelo. Erros de rede/cota não são repetidos: sobem para o webhook.

## M10: o bot iniciando a conversa

### Mandar a primeira mensagem é o risco real, não o de responder
- Até o M9 o bot só falava depois de receber uma mensagem — o padrão que mais preocupa o WhatsApp
  em termos de bloqueio é justamente **iniciar** contato sem o outro lado ter pedido. O agendador
  de lembretes (M10, ADR-0012) é a primeira peça do bot que faz isso.
- Mitigação em três camadas, todas antes de mandar qualquer coisa: só dispara com o `chat_id`
  **real** (aprendido de uma mensagem recebida, nunca o `ALLOWED_NUMBER` do `.env` — mesma lição de
  `b141c39`), nunca sem fila (silêncio em vez de mensagem vazia) e nunca dois lembretes seguidos
  sem resposta ao anterior.
- **Ainda não testado com o WhatsApp de verdade** (só no `sim` e com testes de `_tick` isolados).
  Antes de deixar `/lembretes` ligado por dias seguidos em produção, vale observar um ou dois
  disparos reais e confirmar que a sessão do WAHA continua em `WORKING`.

### `python:3.12-slim` não tem o banco de fusos horários
- `ZoneInfo("America/Sao_Paulo")` funciona local (o SO tem o banco), mas estouraria na imagem
  Docker sem o pacote `tzdata` do PyPI — adicionado às dependências (`pyproject.toml`) antes de
  precisar descobrir isso em produção. Conferir com
  `docker compose run --rm bot python -c "from zoneinfo import ZoneInfo; ZoneInfo('America/Sao_Paulo')"`
  antes do primeiro deploy com lembretes ligados.

## Processo

- **Ler a fonte, não a memória:** a tag do WAHA (`gows-2026.8.2`), os nomes das variáveis e o endpoint de LID
  foram conferidos na documentação e no Docker Hub antes de usar; a doc do Google, por outro lado, é ambígua
  sobre o IP externo no free tier, e só a fatura resolve (ADR-0008).
- **Medir em vez de supor recursos:** o WAHA usa ~270 MiB de 400 e o bot ~55 a 85 MiB de 300 numa VM de 1 GB.
- **Corrigir a causa, e travar com teste:** cada bug de produção virou um teste que falhava antes (fixtures com
  os payloads reais em `tests/fixtures/`).
- **Não ler segredos, nunca:** todos os diagnósticos acima foram feitos comparando hashes, tamanhos ou
  "bate / não bate", sem imprimir senha, chave ou número de telefone.

## Ideias para depois

- Conferir na fatura o SKU "External IP Charge on a Standard VM" e **revisitar a hospedagem antes do fim dos
  créditos do trial** (ADR-0008).
- Exercitar o `/exportar` em produção (upload no bucket e URL assinada via IAM `signBlob`): até aqui só rodou
  com dublês.
- Se o WAHA passar a permitir `sendFile`, mandar o `.txt` como anexo e dispensar o bucket.
- Alerta de orçamento em Billing → Budgets.
- Se o WAHA passar de ~350 MiB depois de dias de uso, subir o `mem_limit` ou reavaliar a VM.
- Medir a qualidade das notas de revisão espaçada (M10) contra a API real — hoje só há testes com
  `FakeTutor`; uma nota `bom` generosa demais espaça rápido demais uma palavra que o aluno não sabe.
  Um `evals/revisao.yaml` (resposta → qualidade esperada), no molde de `evals/roteamento.yaml`.
- Observar os primeiros disparos reais do agendador de lembretes (M10) no WhatsApp de verdade antes
  de deixar `/lembretes` ligado por vários dias seguidos.
