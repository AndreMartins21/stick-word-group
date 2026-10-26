"""M40 (ADR-0038): texto acima de `MAX_CARACTERES` é recusado antes da IA, no privado e no grupo."""

from __future__ import annotations

from app import messages
from app.config import Settings
from tests.webhook_helpers import ALUNO_COMUM, GRUPO_FIXO, Ambiente, _do_grupo

LONGO = "stall " * 100  # 600 caracteres


def test_grupo_com_comando_longo_recusa_sem_chamar_a_ia(ambiente: Ambiente) -> None:
    ambiente.cliente.post(
        "/waha/webhook", json=_do_grupo(GRUPO_FIXO, f"{ALUNO_COMUM}@c.us", f"!add {LONGO}")
    )

    assert ambiente.canal.textos_enviados == [(GRUPO_FIXO, messages.texto_longo_demais(500))]
    assert ambiente.tutor.chamadas == []


def test_conversa_entre_pessoas_longa_no_grupo_continua_ignorada(ambiente: Ambiente) -> None:
    ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO_FIXO, f"{ALUNO_COMUM}@c.us", LONGO))

    assert ambiente.canal.textos_enviados == []


def test_max_caracteres_vazio_no_env_usa_o_padrao() -> None:
    settings = Settings(
        _env_file=None,
        ALLOWED_NUMBER="5531999998888",
        BOT_NUMBER="5531988887777",
        WAHA_API_KEY="x",
        GCP_PROJECT_ID="p",
        MAX_CARACTERES="",
    )

    assert settings.max_caracteres == 500
