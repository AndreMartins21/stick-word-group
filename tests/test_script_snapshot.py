"""Teste de ponta a ponta de `python -m scripts.snapshot` (M28, ADR-0029), contra o emulador do
Firestore — só roda com `FIRESTORE_EMULATOR_HOST` definido (`make test-emulador`)."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

PROJETO = "stick-word-group-teste-snapshot"


@pytest.fixture
def emulador() -> Iterator[str]:
    host = os.environ.get("FIRESTORE_EMULATOR_HOST")
    if not host:
        pytest.skip("FIRESTORE_EMULATOR_HOST não definido (emulador do Firestore não está rodando)")
    limpar = f"http://{host}/emulator/v1/projects/{PROJETO}/databases/(default)/documents"
    httpx.delete(limpar)
    yield host
    httpx.delete(limpar)


def test_dry_run_nao_grava_nada(emulador: str, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts.snapshot import main

    codigo = main(["--projeto", PROJETO])

    assert codigo == 0
    assert "DRY RUN" in capsys.readouterr().out


def test_executar_grava_localmente_e_marca_o_snapshot(
    emulador: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from datetime import UTC, datetime

    from google.cloud import firestore

    from app.domain.models import Entry, Profile, SentidoSalvo
    from app.repo.firestore import FirestoreBanco
    from scripts.snapshot import main

    cliente = firestore.Client(project=PROJETO)
    banco = FirestoreBanco(cliente)
    repo = banco.do_espaco("5531999998888@c.us")
    repo.salvar_perfil(Profile(nivel="B1-B2", criado_em=datetime.now(UTC)))
    repo.criar_entrada(
        Entry(
            slug="stall",
            palavra="stall",
            classe="verb",
            cefr_estimado="B2",
            sentido=SentidoSalvo(traducao="travar", definicao="to stop making progress"),
        )
    )

    codigo = main(["--projeto", PROJETO, "--destino", str(tmp_path), "--executar"])

    assert codigo == 0
    assert "gravado em" in capsys.readouterr().out
    hoje = datetime.now(UTC).date().isoformat()
    arquivo = tmp_path / "espacos" / f"dt={hoje}" / "parte-0.json"
    assert arquivo.is_file()
    linha = json.loads(arquivo.read_text("utf-8").strip())
    assert linha["n_termos"] == 1
    assert banco.obter_ultimo_snapshot() is not None
