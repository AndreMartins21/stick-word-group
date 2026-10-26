# ADR-0062: Separar o projeto em stick-word (individual) e stick-word-group (turmas)

- **Status:** Aceito
- **Data:** 2026-10-26

## Contexto

O Vocabot (repositório `anki-whatsapp`) atendia, com um só número e um só código, dois produtos
diferentes: o estudo **individual** no privado (captura, prática, revisão espaçada no estilo Anki,
música, `/export`) e as **turmas** em grupo (palavras da turma, revisão diária sem marcação,
desafio semanal, professores, admins, `/ranking`). Cada funcionalidade de grupo somava regras ao
privado (prefixo, marcação, quem pode o quê) e vice-versa, e o número do bot acumulava restrições
dos dois usos. Agora os admins também recebem relatórios, e o grupo deve evoluir para um sistema de
dinâmicas coletivas de vocabulário — não um "Anki compartilhado", porque cada participante entende
ou não uma palavra.

## Decisão

O código foi separado em dois repositórios independentes, ambos com o histórico completo do
`anki-whatsapp`:

- **stick-word-group** (este): só **grupos**, com o modelo atual de turma (palavras da turma,
  `!add`/`!list`/`!practice`/`!review`/`!delete`/`!level`, revisão diária, desafio semanal,
  professores, ativação por admin, nota de voz transcrita, limites e cota por grupo). No **privado**,
  só o dono e os admins são atendidos, e só com os comandos de admin (`/groups`, `/teachers`,
  `/ranking`, `/admin`); qualquer outro texto deles recebe a lista fixa desses comandos. **Qualquer
  outro número é ignorado por uma regra fixa no webhook**: sem resposta, sem `sendSeen`, sem gravar
  nada (nem a deduplicação) e sem nunca chamar a IA. O `Router` só atende chats `@g.us` e o
  agendador nunca dispara para um espaço privado (dados antigos de antes da separação).
- **stick-word**: só o privado, o estudo individual no estilo Anki.

Sai daqui o que era só do privado: `/song` (LRCLIB), `/export` (planilha e bucket de export), os
lembretes N vezes por dia do privado (`/reminders`, `/reviewsize`), `/info`, `/listen`, `/profile`,
`/pending`, `/status`, `/cancel`, a allowlist de alunos (`ALLOWED_NUMBERS`) e o aviso "sem plano"
(`CONTACT_EMAIL`). O dono continua vindo de `OWNER_NUMBER` ou, legado, `ALLOWED_NUMBER`.

Os dois **não compartilham** número, VM, projeto GCP nem Firestore. Este projeto herda a produção
atual (número do bot, `vocabot-vm`, Firestore com os dados, deploy pelo GitHub Actions), então os
nomes de recursos da infra não mudam; só o repositório do WIF passa a ser
`AndreMartins21/stick-word-group`.

Deixam de valer aqui (status "Substituído por ADR-0062"): ADR-0014, 0015, 0016 e 0027.
Valem em parte: ADR-0017 (o espaço privado não é mais usado), ADR-0018 (sai a allowlist de alunos e
o aviso "sem plano"; ficam admins e ativação), ADR-0025 (saem os lembretes do privado; fica o
tamanho da rodada configurável, hoje em `!daily ... size N`) e ADR-0024/0026 (a pronúncia segue só
onde o grupo já a usava).

## Alternativas consideradas

- **Manter o estudo individual também no privado deste projeto** — duplicaria o produto
  individual nos dois repositórios e manteria as regras cruzadas que motivaram a separação.
- **Ignorar o privado por completo, inclusive para admins** — os comandos de admin (`/groups`,
  `/ranking`, `/teachers`) precisam de um canal fora do grupo; o privado do admin é esse canal.
- **Responder "sem plano" a quem não é admin** — gasta uma escrita por número e uma mensagem do
  número do bot para ninguém; o silêncio é mais barato e expõe menos o número.
- **Monorepo ou feature flag** — mesmas razões do stick-word: o objetivo é deixar os modelos
  divergirem sem uma regra vazar no outro.

## Consequências

- O privado deixa de ser porta de entrada: alunos que estudavam no privado com este número precisam
  do stick-word (outro número). Os cadernos privados antigos continuam no Firestore, sem uso; o
  snapshot de métricas ainda os conta.
- Os buckets de export (`…-vocabot-exports`) e o papel `serviceAccountTokenCreator` da `vocabot-vm`
  sobre ela mesma (que só servia para assinar o link do export) deixam de ser usados; o
  `infra/setup.sh` não os cria mais, mas nada foi apagado na GCP — remover é um passo manual.
- O deploy precisa do WIF confiando no repositório novo (`infra/setup_cicd.sh`) e das mesmas
  Variables/Secrets no GitHub, menos `ALLOWED_NUMBERS` e `CONTACT_EMAIL`.
- Correções no núcleo comum (captura, prompts, canal WAHA) precisam ser portadas à mão entre os
  dois repositórios, se fizerem sentido nos dois.
