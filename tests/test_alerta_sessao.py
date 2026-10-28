"""M56 (ADR-0054): o alerta da sessão do WhatsApp casa com o que o bot realmente registra."""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).parent.parent
ALERTA = (RAIZ / "infra" / "terraform" / "monitoring.tf").read_text(encoding="utf-8")
MAIN = (RAIZ / "app" / "main.py").read_text(encoding="utf-8")
RUNBOOK = RAIZ / "docs" / "runbooks" / "banimento-do-numero.md"


def _filtro() -> str:
    achado = re.search(r"filtro_sessao_caiu = <<-EOT\n\s*(.+)\n", ALERTA)
    assert achado, "o monitoring.tf precisa definir local.filtro_sessao_caiu"
    return achado[1]


def test_o_filtro_usa_o_evento_que_o_bot_registra() -> None:
    assert 'jsonPayload.evento="waha_status"' in _filtro()
    assert '"waha_status"' in MAIN  # o evento existe em app/main.py


def test_o_filtro_cobre_os_estados_de_sessao_caida_e_ignora_starting() -> None:
    motivos = set(re.findall(r'"([A-Z_]+)"', _filtro().split("jsonPayload.motivo=")[1]))

    assert motivos == {"FAILED", "STOPPED", "SCAN_QR_CODE"}
    assert "STARTING" not in motivos and "WORKING" not in motivos  # normais num deploy


def test_o_runbook_existe_e_cobre_os_dois_casos() -> None:
    texto = RUNBOOK.read_text(encoding="utf-8")

    for trecho in ("BOT_NUMBER", "infra/pair.sh", "número reserva", "!activate", "Modelo de aviso"):
        assert trecho in texto, trecho
    assert "banimento-do-numero.md" in ALERTA  # o alerta aponta para o runbook
