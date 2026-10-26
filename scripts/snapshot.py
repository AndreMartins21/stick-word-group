"""Roda o snapshot diário de métricas sob demanda (M28, ADR-0029, seção 12 da spec), sem esperar
o `Agendador`. Usado para a primeira carga e para conferir o orçamento de leituras do Firestore
antes de ligar em produção (a cota grátis é 50.000 leituras/dia — seção 3.4 do plano).

    python -m scripts.snapshot --projeto ID                       # dry run (padrão): só conta
    python -m scripts.snapshot --projeto ID --destino ./local --executar
    python -m scripts.snapshot --projeto ID --bucket BUCKET --executar

- Roda na máquina local, com as credenciais padrão (ADC).
- O dry run já faz as leituras (não tem como contar sem ler); só não grava nem marca o dia como
  feito, então pode ser repetido à vontade sem afetar o `Agendador` em produção.
- Com `--destino PASTA` grava localmente, no mesmo layout Hive do GCS — útil para inspecionar o
  NDJSON antes de apontar para o bucket de verdade.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from app.services.metricas_destino import DestinoDeMetricas, DestinoLocal, criar_destino_gcs
from app.services.snapshot import montar_snapshot, tabelas


def _argumentos(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--projeto", required=True, help="ID do projeto GCP (o do Firestore)")
    ap.add_argument(
        "--bucket", help="bucket de métricas em produção (com --executar, sem --destino)"
    )
    ap.add_argument("--destino", type=Path, help="grava localmente nesta pasta, em vez do GCS")
    ap.add_argument(
        "--executar", action="store_true", help="grava de verdade (padrão: dry run, só conta)"
    )
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _argumentos(argv)

    from google.cloud import firestore

    from app.repo.firestore import FirestoreBanco

    banco = FirestoreBanco(firestore.Client(project=args.projeto))
    agora = datetime.now(UTC)
    dia = agora.date()
    snapshot = montar_snapshot(banco, agora)

    print(f"projeto: {args.projeto}  dia: {dia.isoformat()}")
    print(
        f"espaços={len(snapshot.espacos)} pessoas={len(snapshot.pessoas)} "
        f"admins={len(snapshot.admins)} termos={len(snapshot.termos)} "
        f"grupos_pendentes={len(snapshot.grupos_pendentes)}"
    )
    total_docs = 0
    for uso in snapshot.firestore_uso:
        print(f"  {uso.colecao}: {uso.n_docs} docs, ~{uso.bytes_estimados} bytes (estimados)")
        total_docs += uso.n_docs
    print(f"leituras do Firestore nesta execução: ~{total_docs} (cota grátis: 50.000/dia)")

    if not args.executar:
        print("DRY RUN: nada foi gravado nem marcado. Rode de novo com --executar para gravar.")
        return 0

    destino: DestinoDeMetricas
    if args.destino is not None:
        destino = DestinoLocal(args.destino)
    elif args.bucket:
        destino = criar_destino_gcs(projeto=args.projeto, bucket=args.bucket)
    else:
        print("erro: informe --bucket (produção) ou --destino PASTA (local)", file=sys.stderr)
        return 2

    for tabela, linhas in tabelas(snapshot):
        destino.gravar(tabela, dia, linhas)
    banco.marcar_snapshot(dia)
    print(f"gravado em {args.destino or ('gs://' + str(args.bucket))}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
