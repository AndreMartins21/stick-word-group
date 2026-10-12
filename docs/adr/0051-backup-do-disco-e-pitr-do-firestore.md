# ADR-0051: Backup do disco da VM e Point-in-Time Recovery do Firestore

- **Status:** Aceito
- **Data:** 2026-10-12

## Contexto

Nada do Vocabot tinha backup (auditoria de 2026-10-12, achado A10). A sessão do WhatsApp mora num
volume do WAHA no disco da VM: perder o disco significa re-parear o QR e ficar fora do ar. O Firestore
guarda o caderno de todos os alunos; o snapshot NDJSON do M28 é de métricas e não restaura nada.

## Decisão

1. **Snapshot diário do disco** da VM por uma *snapshot schedule* nativa do Compute Engine
   (`vocabot-snapshot-diario`, 06:00 UTC = 03:00 em Brasília, retenção de **7 dias**, snapshots
   mantidos se o disco for apagado). Snapshots são incrementais: o custo fica em ~US$ 0,5-1,5/mês.
2. **Point-in-Time Recovery** do Firestore (`--enable-pitr`): restaura o banco de qualquer instante dos
   últimos 7 dias, com granularidade de minuto.
3. Tudo criado por `infra/setup_backup.sh` (idempotente, `DRY_RUN=1`, mostra o comando antes de
   alterar). Roda uma vez; não entra no deploy automático.

## Alternativas consideradas

- **Export agendado do Firestore** (Cloud Scheduler + `gcloud firestore export` + bucket) — descartada:
  três recursos novos para manter, e restaurar por export é mais lento e menos preciso que o PITR.
- **Backup do volume do WAHA para o Cloud Storage por cron na VM** — descartada: o snapshot do disco
  já cobre a sessão, sem processo extra no e2-micro de 1 GB.
- **Não fazer backup** — descartada: o ban do número já é um risco aceito; perder também o caderno ou
  a sessão por falha de disco não precisa ser.

## Consequências

- Restaurar o disco: criar um disco a partir do snapshot e trocar na VM (a sessão do WAHA volta junto,
  sem QR). Restaurar o Firestore: `gcloud firestore databases clone` a partir de um instante dentro
  dos 7 dias, para um banco novo, e apontar o bot para ele.
- O PITR retém versões antigas dos documentos: custo de armazenamento pequeno para o volume atual.
- Um ataque que corrompa o dado e só seja notado depois de 7 dias não é recuperável; aceito.
