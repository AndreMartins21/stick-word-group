"""M49 (ADR-0047): o `deploy.sh` e o `ci.yml` levam os limites ao `.env` com os padrões do código."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.config import Settings

RAIZ = Path(__file__).parent.parent
DEPLOY = (RAIZ / "infra" / "deploy.sh").read_text(encoding="utf-8")
CI = (RAIZ / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

# variável de ambiente -> atributo de Settings
VARIAVEIS = {
    "MAX_CARACTERES": "max_caracteres",
    "MAX_SEGUNDOS_AUDIO": "max_segundos_audio",
    "LIMITE_PESSOA_MINUTO": "limite_pessoa_minuto",
    "LIMITE_PESSOA_DIA": "limite_pessoa_dia",
    "LIMITE_GRUPO_DIA": "limite_grupo_dia",
    "LIMITE_AUDIO_SEGUNDOS_DIA": "limite_audio_segundos_dia",
    "ORCAMENTO_DIARIO_USD": "orcamento_diario_usd",
    "ORCAMENTO_MENSAL_USD": "orcamento_mensal_usd",
    "COTA_DIARIA_POR_GRUPO_USD": "cota_diaria_por_grupo_usd",
    "MAX_FILA_POR_CHAT": "max_fila_por_chat",
    "MAX_PROCESSAMENTOS": "max_processamentos",
    "GEMINI_THINKING_LEVEL": "gemini_thinking_level",
}


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        ALLOWED_NUMBER="5531999998888",
        BOT_NUMBER="5531988887777",
        WAHA_API_KEY="x",
        GCP_PROJECT_ID="p",
    )


@pytest.mark.parametrize(("variavel", "atributo"), VARIAVEIS.items())
def test_deploy_grava_a_variavel_com_o_padrao_do_codigo(variavel: str, atributo: str) -> None:
    achou = re.search(rf"printf '{variavel}=%s\\n' \"\${{{variavel}:-([^}}]+)}}\"", DEPLOY)

    assert achou, f"{variavel} não é renderizada pelo deploy.sh"
    esperado = getattr(_settings(), atributo)
    valor = achou.group(1)
    if isinstance(esperado, int | float):
        assert float(valor) == float(esperado)
    else:
        assert valor == esperado


@pytest.mark.parametrize("variavel", VARIAVEIS)
def test_ci_leva_a_variavel_do_github_ao_deploy(variavel: str) -> None:
    assert f"{variavel}: ${{{{ vars.{variavel} }}}}" in CI
