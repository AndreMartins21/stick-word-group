"""Testes da validação HMAC do webhook (seção 8.1: "se o WAHA suportar, configure e valide").

Só entra em vigor quando `WAHA_HOOK_HMAC_KEY` está configurada — sem ela, confiamos na rede
interna isolada do compose, como a spec permite.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.channel.fake import FakeChannel
from app.config import Settings
from app.flows.conversa import Conversa
from app.flows.router import Router
from app.main import app, get_banco, get_channel, get_router, get_settings
from app.repo.memory import MemoryBanco
from app.services.fake_llm import FakeTutor
from tests.helpers import explicacao_stall

FIXTURES = Path(__file__).parent / "fixtures"
CHAVE_HMAC = "chave-secreta-de-teste"


async def _sem_espera(_: float) -> None:
    return None


def _router(canal: FakeChannel) -> Router:
    return Router(
        banco=MemoryBanco(),
        tutor=FakeTutor(explicacoes=[explicacao_stall()]),
        criar_conversa=lambda chat_id: Conversa(
            canal, chat_id, dormir=_sem_espera, atraso=lambda: 0.0
        ),
        nivel_padrao="B1-B2",
    )


def _fixture_bruta(nome: str) -> bytes:
    return (FIXTURES / f"{nome}.json").read_bytes()


def _assinar(corpo: bytes) -> str:
    return hmac.new(CHAVE_HMAC.encode(), corpo, hashlib.sha512).hexdigest()


@pytest.fixture
def fake_channel() -> FakeChannel:
    return FakeChannel()


@pytest.fixture
def cliente(fake_channel: FakeChannel) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        ALLOWED_NUMBER="5531999998888",
        BOT_NUMBER="5531988887777",
        WAHA_API_KEY="fake-local-key",
        GCP_PROJECT_ID="meu-projeto-local",
        WAHA_HOOK_HMAC_KEY=CHAVE_HMAC,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_channel] = lambda: fake_channel
    app.dependency_overrides[get_banco] = lambda: MemoryBanco()
    app.dependency_overrides[get_router] = lambda: _router(fake_channel)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_rejeita_sem_assinatura(cliente: TestClient) -> None:
    corpo = _fixture_bruta("texto")

    resposta = cliente.post(
        "/waha/webhook", content=corpo, headers={"Content-Type": "application/json"}
    )

    assert resposta.status_code == 401


def test_rejeita_assinatura_errada(cliente: TestClient) -> None:
    corpo = _fixture_bruta("texto")

    resposta = cliente.post(
        "/waha/webhook",
        content=corpo,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Hmac": "0" * 128,
            "X-Webhook-Hmac-Algorithm": "sha512",
        },
    )

    assert resposta.status_code == 401


def test_aceita_assinatura_correta(cliente: TestClient, fake_channel: FakeChannel) -> None:
    corpo = _fixture_bruta("texto")

    resposta = cliente.post(
        "/waha/webhook",
        content=corpo,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Hmac": _assinar(corpo),
            "X-Webhook-Hmac-Algorithm": "sha512",
        },
    )

    assert resposta.status_code == 200
    assert fake_channel.vistos == ["5531999998888@c.us"]


def test_sem_chave_configurada_nao_exige_assinatura(fake_channel: FakeChannel) -> None:
    settings_sem_hmac = Settings(
        _env_file=None,
        ALLOWED_NUMBER="5531999998888",
        BOT_NUMBER="5531988887777",
        WAHA_API_KEY="fake-local-key",
        GCP_PROJECT_ID="meu-projeto-local",
    )
    app.dependency_overrides[get_settings] = lambda: settings_sem_hmac
    app.dependency_overrides[get_channel] = lambda: fake_channel
    app.dependency_overrides[get_banco] = lambda: MemoryBanco()
    app.dependency_overrides[get_router] = lambda: _router(fake_channel)
    try:
        cliente = TestClient(app)
        resposta = cliente.post("/waha/webhook", json=json.loads(_fixture_bruta("texto")))
    finally:
        app.dependency_overrides.clear()

    assert resposta.status_code == 200
