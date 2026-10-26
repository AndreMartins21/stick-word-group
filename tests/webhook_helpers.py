"""Ambiente compartilhado dos testes de webhook do controle de acesso (M15) e do grupo (M16): o
mesmo cabeamento do `app/main.py` (Router com prefixo e dono, allowlist, grupo fixo, um admin)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient

from app.channel.fake import FakeChannel
from app.config import Settings
from app.flows.base import ConfigGrupo
from app.flows.conversa import Conversa
from app.flows.router import Router
from app.main import app, get_banco, get_channel, get_router, get_settings, get_transcritor
from app.repo.memory import MemoryBanco
from app.services.fake_llm import FakeTutor
from app.services.fake_transcricao import FakeTranscritor
from app.services.limites import Limites
from app.services.orcamento import Orcamento
from tests.helpers import T0, explicacao_stall

DONO = "5531999998888"
ADMIN = "5511988887777"
ALUNO_COMUM = "5521977776666"
ESTRANHO = "5541966665555"
GRUPO = "120363000000000001@g.us"
GRUPO_FIXO = "120363000000000099@g.us"


async def _sem_espera(_: float) -> None:
    return None


@dataclass
class Ambiente:
    cliente: TestClient
    canal: FakeChannel
    banco: MemoryBanco
    tutor: FakeTutor
    settings: Settings
    transcritor: FakeTranscritor


@contextmanager
def criar_ambiente(
    limites: Limites | None = None, orcamento: Orcamento | None = None
) -> Iterator[Ambiente]:
    canal = FakeChannel()
    settings = Settings(
        _env_file=None,
        ALLOWED_NUMBER=DONO,
        ALLOWED_GROUPS=GRUPO_FIXO,
        BOT_NUMBER="5531988887777",
        WAHA_API_KEY="fake-local-key",
        GCP_PROJECT_ID="meu-projeto-local",
    )
    banco = MemoryBanco()
    banco.adicionar_admin(ADMIN, por=DONO, agora=T0)
    tutor = FakeTutor(explicacoes=[explicacao_stall() for _ in range(4)])
    router = Router(
        banco=banco,
        tutor=tutor,
        criar_conversa=lambda chat: Conversa(canal, chat, dormir=_sem_espera, atraso=lambda: 0.0),
        nivel_padrao="B1-B2",
        prefixo_do_grupo=settings.group_prefix,
        limites=limites,
        orcamento=orcamento,
        eh_dono=settings.eh_dono,
        config_grupo=ConfigGrupo(
            limite=settings.limite_por_sessao_grupo,
            timeout=timedelta(hours=settings.timeout_marcacao_horas),
            participantes=canal.group_participants,
            numero_do_bot=settings.bot_number,
        ),
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_channel] = lambda: canal
    app.dependency_overrides[get_banco] = lambda: banco
    app.dependency_overrides[get_router] = lambda: router
    transcritor = FakeTranscritor()
    app.dependency_overrides[get_transcritor] = lambda: transcritor
    try:
        yield Ambiente(TestClient(app), canal, banco, tutor, settings, transcritor)
    finally:
        app.dependency_overrides.clear()


_contador = iter(range(10_000))


def _privada(numero: str, texto: str, *, midia: bool = False) -> dict[str, Any]:
    return {
        "event": "message",
        "session": "default",
        "payload": {
            "id": f"true_{numero}@c.us_{next(_contador)}",
            "from": f"{numero}@c.us",
            "fromMe": False,
            "body": texto,
            "hasMedia": midia,
        },
    }


def _do_grupo(
    grupo: str, participante: str | None, texto: str, *, id_: str | None = None
) -> dict[str, Any]:
    return {
        "event": "message",
        "session": "default",
        "payload": {
            "id": id_ or f"false_{grupo}_{next(_contador)}",
            "from": grupo,
            "fromMe": False,
            "participant": participante,
            "body": texto,
            "hasMedia": False,
        },
    }


def _entrada_no_grupo(grupo: str) -> dict[str, Any]:
    return {
        "event": "group.v2.join",
        "session": "default",
        "payload": {"group": {"id": grupo, "subject": "Turma A"}, "timestamp": 1},
    }
