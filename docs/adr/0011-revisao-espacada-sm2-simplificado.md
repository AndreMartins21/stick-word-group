# ADR-0011: Revisão espaçada com SM-2 simplificado, independente do agendamento do Anki

- **Status:** Substituído por ADR-0064
- **Data:** 2026-09-23

## Contexto

O aluno esquece palavras que já praticou e não tinha um jeito de o bot lembrar disso sozinho — só
o próprio Anki, depois de exportar, faz revisão espaçada de verdade. O pedido do M10 é um sistema
"tipo o do Anki" dentro do próprio WhatsApp: o bot decide quando cada palavra volta, com base em o
aluno lembrar dela ou não, sem exigir que o aluno abra o Anki para isso.

## Decisão

Cada `Entry` ganha os campos de agendamento (`repeticoes`, `intervalo_dias`, `facilidade`,
`lapsos`, `proxima_revisao`) e `app/domain/srs.py:reagendar` implementa uma versão simplificada do
algoritmo SM-2 (o mesmo algoritmo clássico por trás do Anki antigo): a cada revisão, uma nota de 4
níveis (`de_novo`/`dificil`/`bom`/`facil`) ajusta a `facilidade` (limitada a
`[1.3, 2.5]`) e o próximo intervalo cresce (1 dia → 3 dias → `intervalo × facilidade`) ou reseta
(`de_novo`, com o cartão voltando ao fim da fila da própria sessão de revisão). A nota não vem de
4 botões como no Anki — vem do julgamento do `Tutor.review` sobre a resposta em texto livre do
aluno (definição com as próprias palavras, ou uma frase). Por isso "simplificado": a função é
puramente aritmética e testável sem IA (`tests/test_srs.py`), mas a *entrada* dela (a nota) depende
de um LLM.

**O agendamento deste sistema é independente do agendamento do Anki.** Exportar
(`/exportar`) continua gerando o `.txt` normalmente; nada aqui altera o formato fixo (spec §7.3)
nem sincroniza com o histórico de revisão que o Anki mantém depois da importação. São dois
sistemas de repetição espaçada paralelos, cada um cuidando do seu histórico.

## Alternativas consideradas

- **FSRS** (o algoritmo que o Anki moderno usa por padrão) — mais preciso com muitos dados de
  treino por cartão, mas é overkill para um único usuário com um histórico pequeno: exigiria uma
  biblioteca nova ou reimplementar um modelo estatístico bem mais complexo, para um ganho que não
  se sente com poucas dezenas de palavras.
- **Sincronizar com o agendamento do Anki** (ler/escrever o estado de revisão do arquivo do Anki,
  ou pedir que o aluno exporte esse estado de volta) — o WAHA Core não manda nem recebe arquivos
  além do link assinado que o bot já gera; construir uma via de volta só para isso é complexidade
  desproporcional ao ganho, e o Anki já faz sua própria revisão espaçada muito bem sozinho depois
  da importação.
- **Só a mais antiga, sem espaçamento real** (fila = as N palavras com `atualizado_em` mais
  antigo) — mais simples, mas revisaria palavras que o aluno já sabe de cor com a mesma frequência
  das que ele está esquecendo, desperdiçando o tempo da sessão.

## Consequências

- Fácil: a lógica de agendamento é uma função pura, testada com uma tabela de casos, sem custo de
  IA para testar; independe totalmente do formato de export do Anki, que continua "não mude"
  (spec §7.3).
- Difícil: a qualidade do espaçamento depende inteiramente de o LLM julgar bem a resposta do
  aluno — uma nota `bom` generosa demais espaça rápido demais uma palavra que o aluno não sabe de
  verdade. Mitigado por `evals/` (a acrescentar: casos de resposta → qualidade esperada) antes de
  confiar no espaçamento em produção.
- Um aluno com muitas palavras salvas de uma vez (importação em massa, por exemplo) teria todas
  vencidas ao mesmo tempo (`proxima_revisao=None`); o limite de 20 por sessão (`LIMITE_POR_SESSAO`,
  `app/flows/review.py`) evita uma sessão gigante de uma vez só, mas não evita várias sessões
  cheias seguidas até o backlog esvaziar — aceitável para o volume de um usuário só.
- Revisitar se: o volume de palavras crescer o bastante para o SM-2 simplificado parecer
  claramente pior que um algoritmo mais sofisticado, ou se o projeto ganhar mais de um usuário e
  precisar de um agendamento mais preciso por perfil.
