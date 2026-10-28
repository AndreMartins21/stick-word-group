"""Destino do snapshot de métricas (M28, ADR-0029, seção 12 da spec): NDJSON particionado por
dia (`tabela/dt=AAAA-MM-DD/parte-0.json`), o formato que o BigQuery lê como tabela externa
`NEWLINE_DELIMITED_JSON` com particionamento Hive. Mesmo padrão de `services/storage.py`: uma
interface, um destino em memória (testes), um local (scripts/`sim`) e um no GCS (produção).
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

import google.auth
from google.cloud.storage import Client as ClienteStorage

_ESCOPO = "https://www.googleapis.com/auth/cloud-platform"


def _serializar(valor: object) -> str:
    if isinstance(valor, datetime | date):
        return valor.isoformat()
    raise TypeError(f"não sei serializar {type(valor)} para o snapshot")


def linhas_para_ndjson(linhas: Sequence[Any]) -> bytes:
    """Uma linha JSON por linha da tabela (uma dataclass de `services/snapshot.py`), separadas
    por `\\n`. Lista vazia vira bytes vazios (sobrescreve o dia com "nada aconteceu")."""
    if not linhas:
        return b""
    texto = "\n".join(
        json.dumps(dataclasses.asdict(linha), default=_serializar, ensure_ascii=False)
        for linha in linhas
    )
    return (texto + "\n").encode("utf-8")


class DestinoDeMetricas(Protocol):
    def gravar(self, tabela: str, dia: date, linhas: Sequence[Any]) -> None:
        """Grava as linhas de uma tabela para um dia; idempotente (sobrescreve)."""
        ...


class DestinoEmMemoria:
    """Para testes: guarda os bytes já serializados, por (tabela, dia)."""

    def __init__(self) -> None:
        self.gravados: dict[tuple[str, date], bytes] = {}

    def gravar(self, tabela: str, dia: date, linhas: Sequence[Any]) -> None:
        self.gravados[(tabela, dia)] = linhas_para_ndjson(linhas)


class DestinoLocal:
    """Para `scripts/snapshot.py --dry-run` e o simulador: uma pasta local, com o mesmo layout
    Hive (`tabela/dt=.../parte-0.json`) que o bucket do GCS teria."""

    def __init__(self, diretorio: Path) -> None:
        self._diretorio = diretorio

    def gravar(self, tabela: str, dia: date, linhas: Sequence[Any]) -> None:
        destino = self._diretorio / tabela / f"dt={dia.isoformat()}" / "parte-0.json"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(linhas_para_ndjson(linhas))


class DestinoGcs:
    """O bucket de métricas em produção (`infra/terraform/storage.tf`): só a SA da VM escreve nele,
    sem leitura de outros buckets nem acesso ao BigQuery (ver ADR-0029)."""

    def __init__(self, *, bucket: Any) -> None:
        self._bucket = bucket

    def gravar(self, tabela: str, dia: date, linhas: Sequence[Any]) -> None:
        nome = f"snapshot/{tabela}/dt={dia.isoformat()}/parte-0.json"
        self._bucket.blob(nome).upload_from_string(
            linhas_para_ndjson(linhas), content_type="application/x-ndjson"
        )


def criar_destino_gcs(*, projeto: str, bucket: str) -> DestinoGcs:
    credenciais, _ = google.auth.default(scopes=[_ESCOPO])
    cliente = ClienteStorage(project=projeto, credentials=credenciais)
    return DestinoGcs(bucket=cliente.bucket(bucket))
