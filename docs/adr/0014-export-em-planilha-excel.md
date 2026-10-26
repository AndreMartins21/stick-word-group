# ADR-0014: Export em planilha Excel no lugar do arquivo de importação do Anki

- **Status:** Substituído por ADR-0062
- **Data:** 2026-09-23

## Contexto

Do M5 ao M11, `/export` gerava um `.txt` no formato fixo de importação do Anki (tipo de nota
"Inglês – Vocabulário", spec §7.3), com uma linha por palavra: só a palavra, a melhor frase, a
tradução, a definição e a nota. Desde o M10 o bot faz a própria revisão espaçada (ADR-0011,
independente do agendamento do Anki), e o M12 passa a guardar mais coisas por palavra: sinônimos
mostrados e as frases do aluno já corrigidas pela IA. O pedido do usuário é que o export reúna
"todas as informações possíveis coletadas", em vez de ligar diretamente ao Anki.

## Decisão

`/export` gera um `.xlsx` (biblioteca `openpyxl`) com três abas — `Words`, `Sentences` e
`Synonyms` — cobrindo tudo o que está no banco (sentidos, nota, tags, status, dados de revisão,
todas as frases com veredito e correções, sinônimos). É sempre um retrato completo: `/export all`
continua aceito e faz o mesmo, e o campo `exportado` deixa de ser usado. O `.txt` do Anki, o
`ExportadorAnki` e a seção 7.3 antiga saem do código; o arquivo vai para o mesmo bucket, com o
content-type do xlsx e a mesma URL assinada de 24 h.

## Alternativas consideradas

- **Manter os dois formatos (`/export` em Excel e `/export anki` no `.txt`)** — o `.txt` só serve a
  quem importa no Anki, que o usuário disse não ser o caminho principal; manter o formato fixo e os
  testes byte a byte custa manutenção por um uso que ele não pediu.
- **CSV** — mais simples e sem dependência, mas não guarda várias abas nem formatação, e o
  Excel/Sheets abre CSV UTF-8 com acentos de forma inconsistente.

## Consequências

- Fácil: abrir e filtrar tudo no Excel/Sheets; acrescentar coluna ou aba é uma linha de código.
- Difícil: perde-se a importação direta no Anki (quem quiser precisa montar o cartão a partir da
  planilha). Entradas salvas antes do M12 não têm sinônimos nem `versao_natural` de revisões; as
  colunas ficam vazias para elas.
- Nova dependência de runtime: `openpyxl` (e `types-openpyxl` no desenvolvimento).
- Revisitar se: o usuário voltar a querer importar no Anki (reintroduzir um segundo exportador
  atrás do mesmo `Exportador`).
