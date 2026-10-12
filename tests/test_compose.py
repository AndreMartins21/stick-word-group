"""M42 (ADR-0040): o compose limita o que o WAHA baixa, sem precisar do Docker para conferir."""

from __future__ import annotations

from pathlib import Path

import yaml

COMPOSE = Path(__file__).parent.parent / "docker-compose.yml"


def _ambiente_do_waha() -> dict[str, str]:
    servicos = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    return {chave: str(valor) for chave, valor in servicos["waha"]["environment"].items()}


def test_waha_so_baixa_audio_dos_eventos() -> None:
    assert _ambiente_do_waha()["WAHA_EVENTS_DOWNLOAD_MEDIA_MIMETYPES"] == "audio"


def test_waha_apaga_os_arquivos_baixados_em_poucos_minutos() -> None:
    assert int(_ambiente_do_waha()["WHATSAPP_FILES_LIFETIME"]) <= 600
