# ADR-0047: Orçamento diário padrão de US$ 5 e limites de uso renderizados pelo deploy

- **Status:** Aceito
- **Data:** 2026-10-12

## Contexto

Com os ADR-0038 a ADR-0046 no ar, o primeiro teste em produção confirmou texto e áudio acima do
limite sendo recusados. Duas coisas ficaram: (1) as variáveis dos limites existiam no código mas o
`deploy.sh` e o `ci.yml` não as levavam ao `.env` da VM, então só os padrões valiam e não havia como
ajustá-las sem editar o código; (2) o padrão de US$ 10/dia do orçamento (ADR-0044) é alto para a
escala atual (poucos grupos, ~US$ 0,50 por dia de uso real).

## Decisão

1. **Orçamento diário padrão: US$ 5** (era US$ 10). Em 100 grupos de uso médio (~US$ 4/dia) ele ainda
   cabe; acima disso, o dono sobe `ORCAMENTO_DIARIO_USD`, e o aviso de DM já diz como.
2. **Variáveis no pipeline:** `MAX_CARACTERES`, `MAX_SEGUNDOS_AUDIO`, `LIMITE_PESSOA_MINUTO`,
   `LIMITE_PESSOA_DIA`, `LIMITE_GRUPO_DIA`, `LIMITE_AUDIO_SEGUNDOS_DIA`, `ORCAMENTO_DIARIO_USD`,
   `MAX_FILA_POR_CHAT`, `MAX_PROCESSAMENTOS` e `GEMINI_THINKING_LEVEL` passam a vir de GitHub
   **Variables** homônimas (não secretas) pelo `ci.yml`, e o `deploy.sh` as grava no `.env` com o
   mesmo padrão do código quando vazias. Mudar um limite vira: editar a Variable e reexecutar o deploy.
3. `GEMINI_THINKING_LEVEL` vazio no código significa "padrão do modelo"; por isso o `deploy.sh` grava
   `minimal` quando a Variable está vazia, para um valor vazio nunca desligar o ajuste do ADR-0042.

## Alternativas consideradas

- **Só mudar o padrão no código** — insuficiente: o próximo ajuste exigiria outro PR.
- **Segredos do Secret Manager** — descartada: não são sensíveis.

## Consequências

- Os padrões ficam em dois lugares (código e `deploy.sh`); um teste confere que o `deploy.sh` grava
  cada variável com o padrão de `Settings`.
- Trocar o orçamento exige deploy (a VM lê o `.env` ao subir), não alteração em tempo de execução.
