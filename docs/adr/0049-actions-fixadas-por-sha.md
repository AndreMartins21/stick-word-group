# ADR-0049: GitHub Actions fixadas pelo SHA do commit

- **Status:** Aceito
- **Data:** 2026-10-12

## Contexto

O `ci.yml` referenciava as Actions por tag (`actions/checkout@v7`, `google-github-actions/auth@v3.0.0`
etc.). Uma tag é um ponteiro mutável: quem sequestra o repositório da Action pode mover a tag para um
código malicioso. O job `deploy` roda com Workload Identity Federation e entra como root na VM, então
um sequestro vira acesso à produção (auditoria de 2026-10-12, achado A9).

## Decisão

1. Toda `uses:` dos workflows aponta para o **SHA de 40 caracteres** do commit, com a tag legível num
   comentário: `uses: actions/checkout@<sha> # v7`.
2. O Dependabot (`github-actions`, mensal, já configurado) continua abrindo PR de atualização e sabe
   trocar o SHA e o comentário juntos.
3. `tests/test_actions_por_sha.py` reprova qualquer `uses:` de repositório remoto sem SHA completo, para
   uma Action nova não entrar por tag sem ninguém perceber.

## Alternativas consideradas

- **Manter tags** — descartada: é o risco que motivou o ADR.
- **Copiar as Actions para o repositório (vendoring)** — descartada: o custo de manter cópias supera o
  ganho; o SHA já garante o conteúdo.

## Consequências

- Atualizar uma Action é revisar um diff de SHA (o Dependabot mostra as notas da versão no PR).
- Ações locais (`./.github/actions/...`) ficam isentas, pois estão no próprio repositório.
