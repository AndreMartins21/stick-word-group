# ADR-0044: Orçamento diário de IA como disjuntor global, persistido no Firestore

- **Status:** Aceito
- **Data:** 2026-10-12

## Contexto

Os limites por pessoa e por grupo (ADR-0041) e o teto de tamanho (ADR-0038) reduzem o abuso, mas nenhum
deles dá um **teto de dólares**: muitos grupos legítimos ao mesmo tempo, um bug de laço ou uma
combinação que ninguém previu ainda produzem uma conta sem limite. O Budget da GCP (ADR-0043) avisa por
e-mail, com atraso de horas, e não corta. Falta um disjuntor dentro do bot, que aja em minutos.

## Decisão

1. **`Orcamento`** (`services/orcamento.py`) soma o `custo_usd` estimado (ADR-0043) de cada chamada de
   IA, no dia do fuso do aluno. Ao atingir `ORCAMENTO_DIARIO_USD` (padrão **US$ 10**), o orçamento
   está **esgotado** até a virada do dia.
2. **Efeito de esgotado:** (a) `Router.admitir` recusa tudo que chegaria à IA, com **um** aviso por chat
   por dia (`PAUSA_DE_HOJE`) e o evento `pausa_de_orcamento`; (b) o `Agendador` não dispara lembretes
   nem revisões/desafios (os atrasados viram `lembrete_desistido` ao voltar); (c) **um** aviso ao dono
   (DM) e o evento `orcamento_esgotado`. Comandos do dono seguem atendidos: ele precisa conseguir
   diagnosticar e subir o limite.
3. **Persistência:** o gasto é espelhado em `uso/{AAAA-MM-DD}` (`Banco.somar_uso_do_dia`, incremento
   atômico), em lote de no máximo uma escrita a cada 30 s e no shutdown. Um restart não zera o dia e
   não reenvia o aviso ao dono.
4. **Ligação por observador:** o provider e o transcritor chamam `custo.notificar_gasto` ao terminar;
   o `lifespan` conecta isso a `Orcamento.registrar`. Falha ao registrar nunca derruba a chamada.
5. **Padrão de US$ 10/dia** (~US$ 300/mês de pior caso) para não dar falso positivo em 100 grupos
   (~US$ 4/dia esperados); em pequena escala, ajuste para ~3x o gasto médio diário.

## Alternativas consideradas

- **Cota do Vertex AI (quota override)** — descartada: protege por requisições/tokens por minuto, não
  por dólar por dia, e é por projeto na GCP, fora do código e sem aviso ao aluno.
- **Budget da GCP cortando o faturamento** — descartada (ADR-0043): derruba a VM e o pareamento.
- **Só os limites por pessoa** — insuficiente: não cobre muitos usuários legítimos nem bugs.

## Consequências

- Um dia de uso muito acima do normal pausa a IA para todos até a virada; o aviso ao dono diz como
  subir o limite. É o comportamento desejado de um disjuntor.
- O custo é estimativa com a tabela pública (ADR-0043); a fatura segue como verdade. Modelo novo no
  `GEMINI_MODEL` sem entrada na tabela cai no preço mais alto (conservador).
- Escritas no Firestore: ~2 por minuto sob carga, sempre dentro da cota gratuita.
- O gasto de **TTS** (pronúncia) não entra: é gratuito até 1M de caracteres/mês e tem cache.
