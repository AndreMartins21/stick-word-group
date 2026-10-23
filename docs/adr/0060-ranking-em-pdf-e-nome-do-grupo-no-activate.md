# ADR-0060: Ranking em PDF (Jinja2 + WeasyPrint) e nome do grupo no `!activate`

- **Status:** Aceito
- **Data:** 2026-10-23

## Contexto

O `/ranking` (ADR-0056) respondia com três mensagens de texto. Os admins querem um arquivo para
guardar e compartilhar, e as turmas apareciam como "Group": o nome do grupo vinha só do
`GET /groups/{id}` do WAHA, lido do campo `subject`, e o engine GOWS (whatsmeow) pode devolver `Name`.

## Decisão

1. **`/ranking [meses]` devolve um PDF** (`ranking-AAAA-MM-DD.pdf`, legenda curta) no privado. Os
   números e a ordem não mudam: a lógica continua em `app/domain/ranking.py`.
2. **Sem IA:** `app/services/relatorio_ranking.py` renderiza o template
   `app/services/templates/ranking.html.j2` com **Jinja2** (autoescape ligado, pois nome de aluno e de
   grupo vêm do WhatsApp) e converte para PDF com **WeasyPrint**. Os textos fixos vêm de
   `messages.ranking_pdf_textos`, em inglês.
3. **Top fixo** 20 alunos, 10 turmas e 3 por turma. Sem ranking (nenhuma resposta), a resposta
   continua sendo texto.
4. **Nome do grupo:** `WahaChannel.group_name` tenta `subject`, `Subject`, `Name` e `name`. Além disso,
   `!activate Nome da turma` grava o nome digitado, que vale mais que o do WhatsApp, e num grupo já
   ativo **renomeia** (`Repository.renomear_grupo`). O nome tem no máximo 80 caracteres.
5. A imagem Docker ganha `libpango-1.0-0`, `libpangoft2-1.0-0` e `fonts-dejavu-core`.

## Alternativas consideradas

- **xhtml2pdf** — Python puro, mas com suporte fraco a CSS; descartada pelo visual.
- **fpdf2** — leve, mas a tabela seria montada em código, sem template HTML.
- **Gerar o relatório com IA** — descartada pelo usuário: custo e variação desnecessários para algo
  determinístico.
- **Medalhas 🥇 no PDF** — descartadas: as fontes do container não têm emoji; usamos números.

## Consequências

- A imagem cresce algumas dezenas de MB por causa do pango e do WeasyPrint.
- A geração é CPU e roda em `asyncio.to_thread`; para o volume do piloto é irrelevante.
- Turmas já ativas com "Group" são consertadas com `!activate Nome` no próprio grupo.
- O formato real da resposta do GOWS ainda não foi conferido no servidor: se nenhum dos quatro campos
  vier, o nome digitado no `!activate` é o caminho.
