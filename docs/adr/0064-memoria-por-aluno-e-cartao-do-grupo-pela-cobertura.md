# ADR-0064: Memória por aluno no grupo e cartão da turma pela cobertura, no lugar do SM-2

- **Status:** Aceito
- **Data:** 2026-10-28

## Contexto

Desde a separação dos projetos (ADR-0062) a revisão espaçada só existe em grupo, mas continuava sendo
o SM-2 de um aluno só (ADR-0011): um cartão por palavra, e a nota da **primeira resposta aceitável**
da diária (ADR-0033) decidia o próximo intervalo para a turma inteira. Na prática isso mede o aluno
mais rápido: ele acerta, o intervalo cresce, e quem esqueceu (ou errou na mesma rodada) não pesa — os
erros nem eram contados. O próprio ADR-0011 pedia revisão "se o projeto ganhar mais de um usuário".

A pesquisa levantada com o usuário (2026-10-28) indica que o grosso do ganho vem de espaçar e
recuperar da memória, não do ajuste fino do intervalo (Kim & Webb 2022: espaçamento igual e
crescente têm efeito parecido em L2); que personalizar ainda acrescenta (Lindsey et al. 2014: +10%
sobre um cronograma único, usando dados da turma para estimar cada aluno); e que quem só ouve a
resposta do colega aprende bem menos que quem responde (Abel & Roediger). `respostas/` já guardava
cada resposta da diária com autor e qualidade, inclusive as erradas.

## Decisão

1. **Memória por aluno** (`domain/memoria.py`, puro, sem IA nem coleção nova): calculada de
   `respostas/` da diária dos últimos 90 dias. Cada par (aluno, palavra) é uma caixa de Leitner
   (acerto sobe até 5, erro volta a 0); a chance de lembrar cai como `0.9 ** (dias / prazo)`, prazos
   1, 3, 7, 14, 30 dias. Quem nunca respondeu a palavra tem uma estimativa pela taxa dele e da palavra,
   nunca acima de 50% — silêncio não é erro, mas também não é prática.
2. **Cartão do grupo pela cobertura** (`srs.reagendar`): ao avançar uma palavra na diária, a média da
   chance entre os **alunos ativos** (com alguma resposta da diária) decide: `>= 0.75` sobe uma caixa,
   `< 0.5` desce e conta lapso, entre os dois fica. Prazos do grupo 1, 3, 7, 14, 30 dias. O fluxo da
   diária (primeiro acerto avança, `skip` não mexe) não muda.
3. **O semanal só consome** (decisão do usuário): o vocabulário começa pelo que a turma mais esquece, e
   quem é marcado recebe, das perguntas que faltam, a das palavras de que ele mais precisa
   (`session.semanal_foco`). As respostas do semanal não entram na memória — a avaliação dele julga a
   coerência com a pergunta, não o uso da palavra (M37).

## Alternativas consideradas

- **Manter o SM-2 só trocando a nota** (a pior das respostas da rodada, ou a média) — continua sem
  saber quem não respondeu, e a "facilidade" do SM-2 descreve uma memória, não uma turma.
- **SRS individual completo dentro do grupo** (FSRS por aluno) — não cabe numa mensagem que todos veem
  ao mesmo tempo, e o estudo individual é o papel do stick-word (ADR-0062).
- **Caixas fixas sem olhar os alunos** — simples e com apoio na pesquisa, mas joga fora os dados por
  aluno que já existem e não ajuda o semanal a cobrar cada um no que ele esquece.
- **O semanal também avaliar o uso da palavra e alimentar a memória** — descartada pelo usuário.
- **Persistir a memória numa coleção** — desnecessário no volume de uma turma; recalcular de
  `respostas/` evita migração e fica coerente com o histórico.

## Consequências

- Uma palavra só se espaça quando a maioria dos alunos ativos mostrou que lembra; erros de qualquer
  aluno derrubam. Quem só lê o grupo não conta (senão toda palavra ficaria presa).
- Cada palavra avançada na diária lê `respostas/` dos últimos 90 dias e os membros (centenas de
  leituras por dia por grupo, centavos); o semanal lê uma vez por desafio.
- Cartões antigos mantêm `repeticoes` do SM-2; acima de 4 são lidos como a caixa máxima.
  `facilidade` fica sem uso (o snapshot continua exportando o campo).
- Os limiares (0.75 / 0.5), os prazos e o teto de 50% são palpites razoáveis, não calibrados.
  Revisitar com os dados do piloto (taxa de acerto por caixa no BigQuery), ou se as leituras de
  `respostas/` pesarem.
