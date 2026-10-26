"""Testes de ponta a ponta do webhook `/waha/webhook` (seção 8.1), com payloads reais de
`tests/fixtures/`. Usa FakeChannel e um MemoryRepository — nunca toca a rede.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app import messages
from app.channel.fake import FakeChannel
from app.config import Settings
from app.flows.conversa import Conversa
from app.flows.router import Router
from app.main import app, get_banco, get_channel, get_router, get_settings
from app.repo.memory import MemoryBanco
from app.services.fake_llm import FakeTutor
from tests.helpers import eventos, explicacao_stall

FIXTURES = Path(__file__).parent / "fixtures"
CHAT_ALLOWED = "5531999998888@c.us"


async def _sem_espera(_: float) -> None:
    return None


def _fixture(nome: str) -> dict[str, Any]:
    return cast(
        "dict[str, Any]", json.loads((FIXTURES / f"{nome}.json").read_text(encoding="utf-8"))
    )


@pytest.fixture
def fake_channel() -> FakeChannel:
    return FakeChannel()


@pytest.fixture
def cliente(fake_channel: FakeChannel) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        ALLOWED_NUMBER="5531999998888",
        ALLOWED_GROUPS="120363000000000099@g.us",
        BOT_NUMBER="5531988887777",
        WAHA_API_KEY="fake-local-key",
        GCP_PROJECT_ID="meu-projeto-local",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_channel] = lambda: fake_channel
    banco = MemoryBanco()
    router = Router(
        banco=banco,
        tutor=FakeTutor(explicacoes=[explicacao_stall(), explicacao_stall()]),
        criar_conversa=lambda chat_id: Conversa(
            fake_channel, chat_id, dormir=_sem_espera, atraso=lambda: 0.0
        ),
        nivel_padrao="B1-B2",
    )
    app.dependency_overrides[get_banco] = lambda: banco
    app.dependency_overrides[get_router] = lambda: router
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_mensagem_de_texto_marca_como_lida_e_e_recebida(
    cliente: TestClient, fake_channel: FakeChannel
) -> None:
    resposta = cliente.post("/waha/webhook", json=_fixture("texto"))

    assert resposta.status_code == 200
    assert fake_channel.vistos == [CHAT_ALLOWED]
    assert len(fake_channel.textos_enviados) == 1
    chat_id, texto = fake_channel.textos_enviados[0]
    assert chat_id == CHAT_ALLOWED
    assert "Admin commands" in texto  # o dono no privado: só os comandos de admin (ADR-0062)


def test_mensagem_de_texto_registra_mensagem_recebida_sem_o_numero(
    cliente: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        cliente.post("/waha/webhook", json=_fixture("texto"))

    (evento,) = eventos(caplog.records, "mensagem_recebida")
    assert evento.tipo_espaco == "privado"
    assert evento.comando == "texto"
    assert "5531999998888" not in json.dumps(vars(evento))


def test_from_me_e_ignorada(cliente: TestClient, fake_channel: FakeChannel) -> None:
    resposta = cliente.post("/waha/webhook", json=_fixture("from_me"))

    assert resposta.status_code == 200
    assert fake_channel.vistos == []
    assert fake_channel.textos_enviados == []


def test_mensagem_de_grupo_e_ignorada(cliente: TestClient, fake_channel: FakeChannel) -> None:
    resposta = cliente.post("/waha/webhook", json=_fixture("grupo"))

    assert resposta.status_code == 200
    assert fake_channel.vistos == []


def test_midia_do_dono_recebe_a_lista_de_comandos_de_admin(
    cliente: TestClient, fake_channel: FakeChannel
) -> None:
    resposta = cliente.post("/waha/webhook", json=_fixture("midia"))

    assert resposta.status_code == 200
    assert fake_channel.vistos == [CHAT_ALLOWED]
    assert len(fake_channel.textos_enviados) == 1
    chat_id, texto = fake_channel.textos_enviados[0]
    assert chat_id == CHAT_ALLOWED
    assert "Admin commands" in texto


def test_numero_que_nao_e_admin_e_ignorado_em_silencio(
    cliente: TestClient, fake_channel: FakeChannel
) -> None:
    resposta = cliente.post("/waha/webhook", json=_fixture("numero_nao_autorizado"))

    assert resposta.status_code == 200
    assert fake_channel.vistos == []
    assert fake_channel.textos_enviados == []


def test_lid_resolvido_para_numero_permitido_e_processado(
    cliente: TestClient, fake_channel: FakeChannel
) -> None:
    fake_channel.lids_conhecidos["257161284317237@lid"] = "5531999998888"

    resposta = cliente.post("/waha/webhook", json=_fixture("lid"))

    assert resposta.status_code == 200
    assert fake_channel.vistos == [CHAT_ALLOWED]


def test_lid_resolvido_fica_em_cache_e_nao_consulta_o_waha_de_novo(
    cliente: TestClient, fake_channel: FakeChannel
) -> None:
    fake_channel.lids_conhecidos["257161284317237@lid"] = "5531999998888"
    cliente.post("/waha/webhook", json=_fixture("lid"))
    fake_channel.lids_conhecidos.clear()  # o WAHA "esqueceu" o mapeamento
    outra = _fixture("lid")
    outra["payload"]["id"] = "true_257161284317237@lid_LID00002"

    resposta = cliente.post("/waha/webhook", json=outra)

    assert resposta.status_code == 200
    assert fake_channel.vistos == [CHAT_ALLOWED, CHAT_ALLOWED]


def test_responde_ao_numero_real_do_whatsapp_quando_difere_do_allowed_no_nono_digito(
    cliente: TestClient, fake_channel: FakeChannel
) -> None:
    """Bug real (deploy): o WhatsApp registrou a conta SEM o 9 depois do DDD, mas o ALLOWED_NUMBER
    tem o 9. Enviar para o número do .env dava "no LID found ... from server" e o usuário ficava
    sem resposta. O destino é o número que o WhatsApp informa (o pn resolvido do LID)."""
    fake_channel.lids_conhecidos["257161284317237@lid"] = "553199998888"  # sem o 9

    resposta = cliente.post("/waha/webhook", json=_fixture("lid_sem_destino_com_texto"))

    assert resposta.status_code == 200
    assert fake_channel.vistos == ["553199998888@c.us"]
    destinos = {chat_id for chat_id, _ in fake_channel.textos_enviados}
    assert destinos == {"553199998888@c.us"}


def test_lid_resolvido_para_numero_nao_permitido_e_ignorado(
    cliente: TestClient, fake_channel: FakeChannel
) -> None:
    fake_channel.lids_conhecidos["257161284317237@lid"] = "5511888887777"

    resposta = cliente.post("/waha/webhook", json=_fixture("lid"))

    assert resposta.status_code == 200
    assert fake_channel.vistos == []


def test_lid_nao_encontrado_e_ignorado_com_um_log_que_diz_o_motivo(
    cliente: TestClient, fake_channel: FakeChannel, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        resposta = cliente.post("/waha/webhook", json=_fixture("lid"))

    assert resposta.status_code == 200
    assert fake_channel.vistos == []
    assert any("LID não resolvido" in registro.message for registro in caplog.records)


def test_mensagem_sem_destino_e_sem_texto_e_ignorada_com_200(
    cliente: TestClient, fake_channel: FakeChannel
) -> None:
    """O WAHA manda `to` e `body` nulos quando não consegue decifrar a mensagem (log real do
    WAHA: "Undecryptable message"). Antes isso virava HTTP 500 e o WAHA reenviava para sempre."""
    fake_channel.lids_conhecidos["257161284317237@lid"] = "5531999998888"

    resposta = cliente.post("/waha/webhook", json=_fixture("lid_sem_destino_sem_texto"))

    assert resposta.status_code == 200
    assert fake_channel.vistos == []
    assert fake_channel.textos_enviados == []


def test_mensagem_com_destino_nulo_mas_com_texto_e_processada(
    cliente: TestClient, fake_channel: FakeChannel
) -> None:
    fake_channel.lids_conhecidos["257161284317237@lid"] = "5531999998888"

    resposta = cliente.post("/waha/webhook", json=_fixture("lid_sem_destino_com_texto"))

    assert resposta.status_code == 200
    assert fake_channel.vistos == [CHAT_ALLOWED]
    assert "Admin commands" in fake_channel.textos_enviados[0][1]  # respondeu ao /ajuda


def test_payload_malformado_devolve_200_e_registra_o_motivo(
    cliente: TestClient, fake_channel: FakeChannel, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        resposta = cliente.post("/waha/webhook", json=_fixture("message_malformada"))

    assert resposta.status_code == 200
    assert fake_channel.textos_enviados == []
    assert any("payload inválido" in registro.message for registro in caplog.records)


def test_corpo_que_nao_e_json_devolve_200(cliente: TestClient) -> None:
    resposta = cliente.post(
        "/waha/webhook", content=b"isto nao e json", headers={"Content-Type": "application/json"}
    )

    assert resposta.status_code == 200


def test_mensagem_duplicada_e_processada_so_uma_vez(
    cliente: TestClient, fake_channel: FakeChannel
) -> None:
    primeira = cliente.post("/waha/webhook", json=_fixture("texto"))
    segunda = cliente.post("/waha/webhook", json=_fixture("duplicado"))

    assert primeira.status_code == 200
    assert segunda.status_code == 200
    assert fake_channel.vistos == [CHAT_ALLOWED]  # sendSeen só rodou na primeira vez


def test_session_status_working_e_so_logado(
    cliente: TestClient, fake_channel: FakeChannel, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        resposta = cliente.post("/waha/webhook", json=_fixture("session_status"))

    assert resposta.status_code == 200
    assert fake_channel.vistos == []
    (evento,) = eventos(caplog.records, "waha_status")
    assert evento.ok is True
    assert evento.motivo == "WORKING"


def test_session_status_fora_de_working_gera_warning(
    cliente: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    evento = _fixture("session_status")
    payload = evento["payload"]
    assert isinstance(payload, dict)
    payload["status"] = "FAILED"

    with caplog.at_level(logging.WARNING):
        resposta = cliente.post("/waha/webhook", json=evento)

    assert resposta.status_code == 200
    assert any(registro.levelno == logging.WARNING for registro in caplog.records)


def test_health_continua_respondendo_sem_dependencias(cliente: TestClient) -> None:
    resposta = cliente.get("/health")

    assert resposta.status_code == 200
    assert resposta.json() == {"ok": True}


# --- M14: vários alunos, grupo não autorizado, aviso de erro só para quem escreveu -------------


def test_grupo_nao_autorizado_tem_o_id_logado_uma_vez_por_processo(
    cliente: TestClient, fake_channel: FakeChannel, caplog: pytest.LogCaptureFixture
) -> None:
    from app import main

    main._GRUPOS_JA_LOGADOS.clear()
    segunda = _fixture("grupo")
    segunda["payload"]["id"] = "true_120363000000000000@g.us_GRUPO0002"

    with caplog.at_level(logging.INFO):
        cliente.post("/waha/webhook", json=_fixture("grupo"))
        cliente.post("/waha/webhook", json=segunda)

    avisos = [r.message for r in caplog.records if "120363000000000000@g.us" in r.message]
    assert len(avisos) == 1
    assert fake_channel.vistos == [] and fake_channel.textos_enviados == []
    assert not any("mensagem de um grupo" in r.message for r in caplog.records)  # nunca o conteúdo


def test_falha_ao_processar_avisa_so_o_chat_de_quem_escreveu(
    cliente: TestClient, fake_channel: FakeChannel, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def quebra(chat_id: str) -> None:
        raise RuntimeError("falha simulada no send_seen")

    monkeypatch.setattr(fake_channel, "send_seen", quebra)

    resposta = cliente.post("/waha/webhook", json=_fixture("texto"))

    assert resposta.status_code == 200
    assert fake_channel.textos_enviados == [(CHAT_ALLOWED, messages.ERRO_INESPERADO)]
