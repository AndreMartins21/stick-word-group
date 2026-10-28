# Plano noturno — stick-word-group para turmas (multiusuário + grupos + revisão com menção)

Leia este arquivo inteiro, depois o `CLAUDE.md` / `spec/spec-inicial.md` e os ADRs em `docs/adr/`.
Este plano estende a spec. Onde ele mudar uma restrição dela, a mudança vira ADR (indicado em cada
marco) e a spec é atualizada no mesmo commit do marco.

## Contexto

O bot funciona bem para um usuário só, no chat privado. O próximo passo é um piloto de cerca de um
mês num cursinho de inglês, com turmas de 2 a 5 alunos que têm aula semanal. Durante a aula aparecem
palavras e expressões novas; a ideia é a turma (alunos e professores) salvá-las num grupo de
WhatsApp com o bot, praticar ali mesmo e receber revisões no grupo, com o bot marcando um aluno por
vez para responder. A discussão entre os alunos no grupo faz parte do objetivo.

Hoje o código assume um único usuário em vários pontos: `session/current` e `profile/me` únicos, um
`ALLOWED_NUMBER`, a trava global do `Router` (ADR-0006) e o `Agendador` lendo um único perfil
(ADR-0012). O parser descarta mensagens de grupo (`@g.us`, spec 8.1).

## 0. Regras desta execução (sem ninguém acordado)

Você vai trabalhar sozinho durante a noite. Por isso, estas regras substituem as da seção 3 da spec
que exigem aprovação:

1. **Nunca faça merge e nunca faça push na `main`.** Merge na `main` dispara o deploy em produção
   (ADR-0013). Trabalhe só na branch `feat/turmas`, criada a partir da `main` atual.
2. **Nunca rode `gcloud`, `ssh`, `infra/*.sh`, `docker compose up` contra a VM, nem nada que toque o
   GCP real.** Pode editar scripts de `infra/`, o compose e o `ci.yml`, mas não executá-los fora de
   `bash -n`, `shellcheck` e `docker compose config`.
3. **Nunca leia, imprima ou grave segredos** (regra 1 da spec continua valendo).
4. **Onde a spec manda perguntar, não pergunte:** escolha a opção mais conservadora, siga em frente e
   registre a dúvida em `docs/noite/PENDENCIAS.md` (o que estava ambíguo, o que você escolheu, por quê).
5. **Um commit ao fim de cada marco**, só com `make check` verde. Se um marco não fechar verde, não
   comece o próximo: registre o estado em `docs/noite/PENDENCIAS.md` e pare.
6. Rode `make test-emulador` se o emulador do Firestore estiver disponível localmente; se não estiver,
   registre isso nas pendências.
7. **O chat privado não pode mudar de comportamento.** No privado, palavras e frases continuam indo
   sem prefixo nenhum e os comandos continuam com `/`, todos os da spec 5.2. Os testes existentes do
   fluxo privado continuam passando; se algum precisar mudar, é só por causa de caminho ou assinatura,
   nunca de texto ou lógica, e isso vai para o relatório.
8. Antes de dormir, o usuário libera as permissões que a noite usa (`make`, `uv`, `git` na branch
   `feat/turmas`, edições de arquivo, o Docker do emulador). Se `git push` ou `gh pr create` for negado,
   não pare: deixe tudo commitado na branch local e registre isso no relatório. Meta da noite: **M14 e
   M15** (acesso); M16 (grupo) só se sobrar tempo, e M17 e M18 ficam para outra rodada.
   Ao terminar (ou parar), faça push da `feat/turmas`, abra um **PR em rascunho** (draft) e escreva
   `docs/noite/RELATORIO.md` (seção 7).
9. Confira na documentação atual do WAHA (waha.devlike.pro), para o engine **GOWS**: o formato do
   evento `message` em grupo (campo do participante que enviou, LID ou número), o campo de menções
   recebidas no payload, o campo de menções no `sendText` (e se o texto precisa conter `@numero`), o
   endpoint que lista os participantes de um grupo e se tudo isso funciona no GOWS. Se algo não
   existir ou não estiver claro, implemente atrás da interface `Channel` com um fake, registre nas
   pendências e siga.
10. Todo texto voltado ao usuário continua em `app/messages.py`, em inglês (ADR-0010).

## 1. Visão geral

O bot passa a atender:

- **Vários alunos no privado**, cada um com as próprias palavras, sessão, perfil e revisões. No
  privado, tudo funciona exatamente como hoje.
- **Grupos de turma** (2 a 5 alunos mais professores), onde o bot só reage a mensagens que começam
  com `!`, e só a um conjunto fechado de comandos (seção 3). Tudo o mais no grupo é conversa entre
  pessoas, e o bot **não lê, não guarda e não processa**.
- **Revisão em grupo**: nos horários combinados, o bot manda poucas palavras vencidas no grupo e
  **marca um aluno** (nunca um professor) para responder, em rodízio.

A unidade central passa a ser o **espaço** (`espaco`): o dono de um caderno de palavras. Um chat
privado é um espaço; um grupo é um espaço. Perfil, sessão, entradas, frases e lembretes pertencem a
um espaço.

## 2. Marco M14 — Multiusuário por espaço

**Entrega:**

- Firestore passa a `espacos/{espaco_id}/...`, com `profile/me`, `session/current`, `entries/...` e
  `entries/{slug}/sentences/...` dentro do espaço. `espaco_id` é o chat id normalizado (privado:
  `NUMERO@c.us`; grupo: `...@g.us`). Documento `espacos/{espaco_id}` com
  `{tipo: "privado"|"grupo", criado_em}`. `processed/` e `lids/` continuam globais.
- A interface `Repository` passa a trabalhar por espaço (por exemplo `repo.do_espaco(espaco_id)`, ou
  o `espaco_id` como parâmetro). Escolha o desenho que menos mexe nos fluxos e registre no ADR.
  `MemoryRepository` e `FirestoreRepository` com paridade; o teste de contrato roda nos dois.
  Desenho recomendado: `repo.do_espaco(espaco_id) -> Repository` (o mesmo Protocol, já escopado), para
  os fluxos continuarem usando `d.repo` sem mudar. O `Router` monta um `Deps` por mensagem, com uma
  `Conversa` por espaço (o limite de "3 seguidas" é por espaço). `Exportador.exportar(repo)` passa a
  receber o repositório do espaço. O tratamento de erro do webhook (`ERRO_INESPERADO`) responde ao
  chat de quem escreveu, não a `ALLOWED_NUMBER`.
- Allowlist:
  - `ALLOWED_NUMBERS`: lista separada por vírgula, com a mesma comparação do nono dígito da spec 8.2.
    `ALLOWED_NUMBER` continua aceito e entra na lista, para não quebrar o `.env` atual.
  - `ALLOWED_GROUPS`: lista de ids `@g.us`.
  - `OWNER_NUMBER`: o dono do bot; padrão = primeiro número de `ALLOWED_NUMBERS`.
  - Mensagem de grupo não autorizado: ignorada, com o id do grupo logado em INFO uma vez por processo
    (para o dono descobrir o id e autorizá-lo). Nada mais é logado sobre ela.
- `Router`: uma `asyncio.Lock` **por espaço** (dicionário de locks), no lugar da trava global.
- `Agendador`: uma consulta só por tick (`repo.listar_espacos_com_lembrete(agora)`, sobre campos
  espelhados em `espacos/{id}`), para não gastar N leituras por minuto no Firestore.
  Percorre todos os espaços com lembretes ligados, cada um com o próprio `chat_id`,
  `proximo_lembrete` e `lembrete_sem_resposta`. As três camadas de segurança do ADR-0012 valem por
  espaço.
- `/export` exporta só o espaço de quem pediu.
- **Migração:** `python -m scripts.migrar_multiusuario` copia os documentos da raiz (`profile/me`,
  `session/current`, `entries/...` com as `sentences`) para `espacos/{chat_id do dono}/...`.
  - Idempotente; o padrão é dry run, e executar de verdade exige `--executar`.
  - Não apaga a origem; a limpeza é um segundo comando, `--limpar-origem`, que só roda se a cópia
    estiver completa.
  - Testada contra o `MemoryRepository` e, se disponível, o emulador. **Não rode contra o Firestore real.**
  - Como o `Dockerfile` só copia `app/`, o comando roda na máquina local com as credenciais padrão
    (ADC), não na VM. Entre a cópia e o deploy o bot antigo ainda grava na raiz: a ordem em produção é
    dry run, executar, merge (deploy), **executar de novo** (só traz o que é novo) e só então
    `--limpar-origem`.
- `infra/.env.infra.example`, `infra/deploy.sh`, `.github/workflows/ci.yml` e README: novas variáveis
  `ALLOWED_NUMBERS`, `ALLOWED_GROUPS` e `OWNER_NUMBER`, todas como GitHub **Secrets** (contêm
  telefones e ids reais). Só editar, nunca executar.
- ADR-0017 "Multiusuário por espaço". Alternativas a registrar: coleções globais com campo `dono`
  (filtros compostos, índice e risco de vazar dado entre usuários) e um banco por usuário
  (desproporcional).

**Critério de aceite:** `make check` verde; testes com dois alunos no privado mostrando isolamento
total (palavras, sessão, `/list`, `/export`, lembretes); testes da migração (dry run não escreve
nada, execução copia tudo, segunda execução não duplica, `--limpar-origem` recusa rodar com cópia
incompleta); todos os testes antigos do fluxo privado passam.

## 2b. Marco M15 — Controle de acesso (grupos só por admins, aviso a quem não tem plano)

Vem antes do grupo: sem isso qualquer pessoa que salve o número do bot cria grupos e ganha um
assistente pessoal de graça. Decisões do usuário: admins ficam no Firestore e o dono os gerencia por
comando no privado; grupo não ativado fica em silêncio e o bot sai dele depois de 24 h.

**Entrega:**

- **Papéis.** Dono (`OWNER_NUMBER`, sempre admin e aluno; único que gerencia admins). Admins:
  `admins/{numero}` na raiz do Firestore. Alunos no privado: `ALLOWED_NUMBERS` (no MVP, só o dono).
  `Banco`: `listar_admins`, `adicionar_admin`, `remover_admin`, `eh_admin` (nono dígito à parte).
- **Grupo ativo** = está em `ALLOWED_GROUPS` (compat do M14; não conta no limite nem se desativa por
  comando) ou tem `ativo: true` em `espacos/{grupo}`. `MAX_GROUPS` (padrão 10) limita os ativados
  por comando. `grupos_pendentes/{grupo}` `{visto_em}` guarda os grupos em que o bot está sem ter sido
  ativado.
- **Ativar.** No grupo, um admin manda `!activate` (o remetente é o participante, com LID resolvido
  pelo cache `lids/`); `!deactivate` desativa (os dados ficam). De não admin, os dois são silêncio
  total. No privado, dono e admins têm `/groups` (ativos e pendentes, com o nome) e `/groups off N`;
  só o dono tem `/admin`, `/admin add N`, `/admin remove N`. Nada disso aparece no `/help` de quem
  não é admin; para os demais, é comando desconhecido.
- **Grupo não ativado.** O evento `group.v2.join` do WAHA (o payload traz `group.id` e `group.subject`,
  e **não diz quem adicionou**) registra o grupo como pendente; mensagem de grupo desconhecido também.
  Enquanto pendente, nada é lido, gravado ou respondido, salvo um `!activate` de admin. O `Agendador`
  sai dos pendentes há mais de 24 h (`POST /api/{session}/groups/{id}/leave`, novo
  `Channel.leave_group`), sem mandar mensagem, e apaga o registro.
- **Número sem plano no privado.** Antes de qualquer chamada ao `Router` e sem `sendSeen`: quem não
  é aluno nem dono recebe `messages.SEM_PLANO` (inglês, ADR-0010, com o e-mail de `CONTACT_EMAIL`)
  **no máximo uma vez a cada 7 dias** por número (marca em `processed/`, com hash do número), e as
  demais mensagens são ignoradas. **A IA nunca é chamada** para esses números. Admin que não é aluno
  só usa `/groups`; o resto recebe o aviso.
- Config: `MAX_GROUPS`, `CONTACT_EMAIL`. Compose: assinar também `group.v2.join`. README: no
  celular do bot, Privacidade → Grupos → "Meus contatos".
- ADR-0018 "Acesso por admins e ativação de grupos". Alternativas: lista fixa `ADMIN_NUMBERS` (mudar
  exige deploy), só o dono (todo grupo passa por ele), sair na hora avisando (mensagem não pedida),
  ficar em silêncio para sempre (acumula grupos).

**Critério de aceite:** `make check` e `make test-emulador` verdes; número fora da lista recebe o
aviso uma vez, a segunda mensagem da semana não recebe nada, `FakeTutor.chamadas == []` e nenhum
`sendSeen`; `!activate` de não admin não grava nem envia nada, de admin ativa, acima de `MAX_GROUPS`
é recusado; `/admin add` por quem não é o dono é comando desconhecido; `group.v2.join` registra o
pendente e o tick 24 h depois (relógio controlado) chama `leave_group` e apaga o registro, salvo se
foi ativado antes; o privado do dono não muda.

## 3. Marco M16 — Bot em grupo com prefixo `!` e comandos limitados

**Entrega:**

- Parser (`app/channel/parser.py`): mensagens de `@g.us` deixam de ser descartadas **se** o grupo
  está **ativo** (`ALLOWED_GROUPS` ou ativado por admin, M15). O remetente real é o participante (confirmar o campo no payload do GOWS);
  resolva LID→número com o cache `lids/` existente.
- **Filtro de prefixo antes de tudo:** em grupo, mensagem que não começa com o prefixo é descartada
  logo no webhook, antes da deduplicação e do `sendSeen`, sem gravar nada e sem logar o conteúdo.
  Prefixo configurável `GROUP_PREFIX` (padrão `!`). Mídia em grupo: ignorada em silêncio.
- **No privado nada muda:** palavras e frases vão sem prefixo, comandos continuam com `/`, e todos os
  comandos da spec 5.2 seguem disponíveis. `!` é aceito como apelido escondido de `/` no privado, para
  o aluno não ter que lembrar de dois símbolos.
- **No grupo, o conjunto de comandos é fechado.** Depois de tirar o prefixo, só isto é aceito:
  - `!list [página]` — palavras do caderno da turma, mesma regra do `/list` (mais novas primeiro, 20
    por página, número fixo por palavra dentro do grupo).
  - `!review` — começa a sessão de revisão em grupo na hora (M17).
  - `!add palavra ou expressão` (com contexto opcional: `!add stall | the talks stalled`) — é a
    **única** forma de trazer uma palavra nova para o grupo: manda o card e entra em `AWAIT_ACTION`.
  - `!practice palavra ou número` — retoma uma palavra do caderno da turma, como o `/practice`.
  - `!help` — ajuda **só com os comandos do grupo**; nunca cita comandos do privado.
  - `!reminder [N [INICIOh-FIMh] | off]` — lembretes do grupo, mesma sintaxe do `/reminders`
    (aceite também `!reminders`).
  - `!group` — o equivalente ao `/profile` para a turma: nível, total de palavras (praticadas e
    pendentes), quantas estão vencidas, lembretes e o próximo horário, e os membros com o papel
    (aluno/professor), pelo nome que o WhatsApp informa, sem telefone e sem menção (não notifica ninguém). O endpoint de
    participantes só devolve `{id, role}`; o nome vem do payload da mensagem quando o membro manda o
    primeiro `!`, e sem nome mostre "Student 1", "Student 2"...
- **Respostas dentro de uma atividade em andamento** também são aceitas, porque sem elas não há
  prática nem revisão:
  - em `AWAIT_ACTION`: `!1`, `!2`, `!3` e `!` + texto (frase de prática ou pedido, via `Tutor.route`,
    como no privado, **exceto** que um `nova_palavra` do roteamento (`app/flows/freeform.py`) no grupo
    responde com a dica de `!add` e não abre palavra nenhuma);
  - em `REVIEWING` (M17): `!` + resposta, e `!0`/`!stop` para sair.
  - Fora dessas atividades, `!` + texto livre não é processado.
- Qualquer outra coisa com `!` no grupo (comando do privado, palavra sem `!add`, texto fora de
  atividade) recebe uma resposta curta com a lista de comandos do grupo, **sem chamar a IA**. Como toda
  palavra nova entra por `!add`, não existe colisão entre palavra e nome de comando.
- **Papéis na turma:** `espacos/{grupo}/membros/{numero}` com `{papel: "aluno"|"professor", nome}`.
  `!teacher @fulano` e `!student @fulano` mudam o papel. Eles **não aparecem no `!help`** e só
  funcionam para um professor da turma ou para o `OWNER_NUMBER`; para qualquer outra pessoa, o bot
  responde como a um comando desconhecido. Os números mencionados vêm do campo de menções do payload, **se o GOWS o trouxer** (a doc do WAHA não
  documenta esse campo); aceite também o número escrito no texto (`!teacher 5531999998888`).
  Quem manda uma mensagem com prefixo e ainda não é membro entra como `aluno`.
- Frases salvas em grupo guardam o autor: `sentences.autor_id` (número do participante), além de
  `autor: "usuario"|"bot"`.
- Mensagens do bot em grupo: os textos de `app/messages.py` que citam comandos usam o prefixo do
  espaço (`/` no privado, `!` no grupo) e, no grupo, só citam comandos do grupo (o card, o menu, o
  Case D e a dica de lembretes incluídos). Nada de texto fixo fora de `messages.py`.
- O limite de "3 mensagens seguidas sem resposta" (spec 5.6) vale por espaço; qualquer mensagem com
  prefixo, de qualquer participante, conta como resposta.
- Simulador: `python -m sim --grupo` simula um grupo com vários participantes. Cada linha digitada é
  `nome: mensagem` (ex.: `ana: !add stall`); linhas sem prefixo aparecem como ignoradas.
- ADR-0019 "Bot em grupo com prefixo `!` e comandos limitados". Alternativas a registrar:
  - desenho híbrido (captura no grupo, prática no privado) — descartado pelo usuário, porque a
    discussão entre os alunos no grupo é o objetivo;
  - resposta citando a mensagem do bot — mais difícil de explicar aos alunos que um prefixo;
  - menção `@bot` — depende de detectar a menção ao próprio bot (LID), mais frágil;
  - prefixo `/` também no grupo — descartado para não confundir com o conjunto de comandos do privado;
  - todos os comandos do privado no grupo — descartado para manter o grupo simples.
  Consequência de privacidade: o bot não processa conversa sem prefixo.

**Critério de aceite:** `make check` verde; fixtures novas em `tests/fixtures/` para grupo autorizado
com prefixo, grupo autorizado sem prefixo (nada gravado, nada enviado, nenhum `sendSeen`), grupo não
autorizado, participante LID e mídia em grupo; testes de cada comando do grupo, de comando do privado
recusado no grupo, de `!` + texto fora de atividade (sem chamar a IA) e de `!teacher` por quem não
pode; ciclo "stall" completo no `sim --grupo` com dois alunos (`!add`, `!2`, frase com `!`, `!3`).

## 4. Marco M17 — Revisão em grupo com menção e rodízio

**Entrega:**

- `Channel.send_text(..., mentions=[...])`: `WahaChannel` manda as menções no formato confirmado na
  documentação; `ConsoleChannel` mostra `@nome`; `FakeChannel` registra as menções para os testes.
- Participantes do grupo: via endpoint do WAHA (confirmar), com cache em `membros/` e atualização no
  início de cada sessão de revisão. Excluir o próprio bot e todos com papel `professor`.
- Sessão de revisão em grupo: mesmo estado `REVIEWING`, mas com `LIMITE_POR_SESSAO_GRUPO = 5`
  (configurável). Cada card marca **um aluno**, escolhido por rodízio: quem foi marcado há mais tempo
  (ou nunca) nesta turma, com desempate aleatório. Ninguém é marcado duas vezes seguidas se houver
  outro aluno. Sem nenhum aluno elegível, a revisão não começa (o agendador fica em silêncio; `!review`
  avisa).
- Respostas em `REVIEWING` no grupo: `!` + texto.
  - Da pessoa marcada: vale a nota. `Tutor.review` julga, `srs.reagendar` atualiza o cartão do grupo,
    e o bot manda o feedback junto com o próximo card, numa mensagem só, como no privado.
  - De outra pessoa: o bot dá feedback, mas **não** muda a nota nem avança o card.
  - `!0` / `!stop` (qualquer participante) fecha a sessão com o resumo.
- Timeout: se a pessoa marcada não responder em `TIMEOUT_MARCACAO_HORAS` (padrão 3), o `Agendador`
  marca o próximo aluno do rodízio para o mesmo card, uma vez; se ninguém responder de novo, fecha a
  sessão com o resumo. O timeout respeita o limite de 3 mensagens seguidas sem resposta.
- Registro de participação: `espacos/{grupo}/respostas/{auto}` com
  `{entry, autor_id, marcado: bool, qualidade, criado_em}`. Não entra no agendamento; serve para o
  `!group` e para as métricas do piloto.
- A revisão do grupo é a "média da turma" no sentido de que o cartão é do grupo e a nota vem de quem
  foi marcado; o rodízio distribui as palavras entre os alunos com o tempo. Documente essa limitação
  no ADR.
- `!reminder` no grupo configura os lembretes do grupo, com a mesma lógica do privado.
- ADR-0020 "Revisão em grupo com menção em rodízio". Alternativas a registrar: sorteio puro (pode
  repetir a mesma pessoa), qualquer um responde (quem é mais rápido responde sempre) e agendamento por
  aluno dentro do grupo (complexo demais para o piloto).

**Critério de aceite:** `make check` verde; testes do rodízio (distribuição justa, professores
excluídos, sem repetição seguida), da resposta de não marcado (feedback sem nota), do timeout com
relógio controlado e das menções no `FakeChannel`; sessão de revisão completa no `sim --grupo`.

## 5. Marco M18 (só se sobrar tempo) — Preparação do piloto

- `/privacy` (e `!privacy` no grupo, escondido do `!help`): texto curto em inglês em `messages.py`
  dizendo o que é guardado (palavras, frases com prefixo, autor), onde (Google Cloud), que conversa sem
  prefixo não é lida, e como pedir remoção.
- `/forget` no privado: apaga o espaço privado de quem pediu e remove o `autor_id` das frases e
  respostas dessa pessoa nos grupos (o conteúdo fica, anônimo). Pede confirmação (`/forget yes`).
- `python -m scripts.metricas`: lê os espaços (Memory ou Firestore, só leitura) e imprime, por semana:
  alunos ativos por espaço, palavras salvas, frases escritas, sessões de revisão concluídas e, nos
  grupos, respostas por aluno (marcado e espontâneo). Sem telefone na saída, só nomes.

## 6. Fora de escopo e decisões em aberto

Não implemente; registre em `docs/noite/PENDENCIAS.md` como decisão do usuário a tomar:

- Apagar uma palavra do grupo adicionada por engano (por exemplo `!delete`, restrito a professores).
- Cancelar no grupo uma palavra aberta sem salvá-la (hoje ela fecha sozinha depois de 3 horas).
- `!export` no grupo.
- Consentimento e menores de idade: a decisão de incluir alunos num bot que grava o que eles escrevem
  com `!` é do cursinho, não do código.
- Risco de bloqueio: bot não oficial (WAHA) em grupos com terceiros aumenta a chance de denúncia.
- Menção a participante que só aparece como `@lid` no grupo: só dá para validar no WhatsApp real.

## 7. Relatório da manhã (`docs/noite/RELATORIO.md`)

Em português, curto:

1. Marcos concluídos, com o hash de cada commit, e o que ficou pela metade.
2. Decisões tomadas sozinho (com link para `PENDENCIAS.md`).
3. O que foi confirmado na documentação do WAHA e o que ficou como suposição (menções no GOWS, campo
   do participante, endpoint de participantes).
4. O que **só dá para validar no WhatsApp real** (lista de testes manuais).
5. Os passos para produção, na ordem, **sem executá-los**: configurar os novos Secrets no GitHub,
   rodar a migração em dry run, rodar de verdade, fazer o merge (que faz o deploy), rodar a migração
   de novo (traz o que o bot antigo gravou na janela), smoke test, e só então `--limpar-origem`.
