"""Testes de app/channel/waha.py, com httpx.MockTransport — nunca toca a rede de verdade."""

from __future__ import annotations

import base64
import json

import httpx
import pytest
from pydantic import SecretStr

from app.channel.waha import WahaChannel


def _canal(handler: httpx.MockTransport, **kwargs: object) -> WahaChannel:
    return WahaChannel(
        base_url="http://waha:3000",
        api_key=SecretStr("segredo-do-teste"),
        session="default",
        transport=handler,
        backoff_base=0.0,  # não esperar de verdade nos testes de retry
        **kwargs,  # type: ignore[arg-type]
    )


async def test_send_text_manda_o_corpo_certo() -> None:
    requisicoes: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requisicoes.append(request)
        return httpx.Response(200, json={"id": "abc"})

    canal = _canal(httpx.MockTransport(handler))
    await canal.send_text("5531999998888@c.us", "oi")
    await canal.aclose()

    assert len(requisicoes) == 1
    requisicao = requisicoes[0]
    assert requisicao.method == "POST"
    assert requisicao.url.path == "/api/sendText"
    assert requisicao.headers["X-Api-Key"] == "segredo-do-teste"
    assert json.loads(requisicao.content) == {
        "session": "default",
        "chatId": "5531999998888@c.us",
        "text": "oi",
    }


async def test_send_seen_manda_session_e_chat_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    canal = _canal(httpx.MockTransport(handler))
    await canal.send_seen("5531999998888@c.us")
    await canal.aclose()


@pytest.mark.parametrize(
    ("ligado", "endpoint"), [(True, "/api/startTyping"), (False, "/api/stopTyping")]
)
async def test_typing_usa_o_endpoint_certo(ligado: bool, endpoint: str) -> None:
    chamado = {}

    def handler(request: httpx.Request) -> httpx.Response:
        chamado["path"] = request.url.path
        return httpx.Response(200, json={})

    canal = _canal(httpx.MockTransport(handler))
    await canal.typing("5531999998888@c.us", ligado)
    await canal.aclose()

    assert chamado["path"] == endpoint


async def test_session_status_le_o_campo_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/sessions/default"
        return httpx.Response(200, json={"name": "default", "status": "WORKING"})

    canal = _canal(httpx.MockTransport(handler))
    status = await canal.session_status()
    await canal.aclose()

    assert status == "WORKING"


async def test_resolve_lid_retorna_o_numero_quando_encontrado() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/default/lids/257161284317237"
        return httpx.Response(200, json={"lid": "257161284317237@lid", "pn": "5531999998888@c.us"})

    canal = _canal(httpx.MockTransport(handler))
    numero = await canal.resolve_lid("257161284317237@lid")
    await canal.aclose()

    assert numero == "5531999998888"


async def test_resolve_lid_retorna_none_quando_nao_encontrado() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"lid": "257161284317237@lid", "pn": None})

    canal = _canal(httpx.MockTransport(handler))
    numero = await canal.resolve_lid("257161284317237@lid")
    await canal.aclose()

    assert numero is None


async def test_tenta_de_novo_em_erro_5xx_e_depois_funciona() -> None:
    respostas = [httpx.Response(503), httpx.Response(200, json={"id": "abc"})]

    def handler(request: httpx.Request) -> httpx.Response:
        return respostas.pop(0)

    canal = _canal(httpx.MockTransport(handler))
    await canal.send_text("5531999998888@c.us", "oi")
    await canal.aclose()

    assert respostas == []


async def test_desiste_apos_esgotar_as_tentativas() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    canal = _canal(httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await canal.send_text("5531999998888@c.us", "oi")
    await canal.aclose()


async def test_erro_4xx_nao_tenta_de_novo() -> None:
    chamadas = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1
        return httpx.Response(401)

    canal = _canal(httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await canal.send_text("5531999998888@c.us", "oi")
    await canal.aclose()

    assert chamadas == 1


async def test_send_file_manda_o_arquivo_em_base64() -> None:
    requisicoes: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requisicoes.append(request)
        return httpx.Response(200, json={"id": "abc"})

    canal = _canal(httpx.MockTransport(handler))
    await canal.send_file(
        "5531999998888@c.us", "vocabot.xlsx", b"conteudo", "application/x-teste", "legenda"
    )
    await canal.aclose()

    (requisicao,) = requisicoes
    assert requisicao.url.path == "/api/sendFile"
    assert json.loads(requisicao.content) == {
        "session": "default",
        "chatId": "5531999998888@c.us",
        "file": {
            "mimetype": "application/x-teste",
            "filename": "vocabot.xlsx",
            "data": base64.b64encode(b"conteudo").decode(),
        },
        "caption": "legenda",
    }


async def test_send_file_nao_tenta_de_novo_para_nao_duplicar_o_arquivo() -> None:
    chamadas = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1
        return httpx.Response(500)

    canal = _canal(httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await canal.send_file("5531999998888@c.us", "a.xlsx", b"x", "application/x-teste")
    await canal.aclose()

    assert chamadas == 1


async def test_send_voice_manda_ogg_opus_em_base64() -> None:
    requisicoes: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requisicoes.append(request)
        return httpx.Response(200, json={"id": "abc"})

    canal = _canal(httpx.MockTransport(handler))
    await canal.send_voice("5531999998888@c.us", b"ogg-bytes")
    await canal.aclose()

    (requisicao,) = requisicoes
    assert requisicao.url.path == "/api/sendVoice"
    assert json.loads(requisicao.content) == {
        "session": "default",
        "chatId": "5531999998888@c.us",
        "file": {
            "mimetype": "audio/ogg; codecs=opus",
            "data": base64.b64encode(b"ogg-bytes").decode(),
        },
        "convert": False,
    }


async def test_send_voice_nao_tenta_de_novo_para_nao_duplicar_o_audio() -> None:
    chamadas = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal chamadas
        chamadas += 1
        return httpx.Response(500)

    canal = _canal(httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await canal.send_voice("5531999998888@c.us", b"x")
    await canal.aclose()

    assert chamadas == 1


async def test_leave_group_usa_o_endpoint_de_sair_do_grupo() -> None:
    vistos: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vistos.append((request.method, request.url.path))
        return httpx.Response(200, json={})

    canal = _canal(httpx.MockTransport(handler))
    await canal.leave_group("120363000000000000@g.us")
    await canal.aclose()

    assert vistos == [("POST", "/api/default/groups/120363000000000000@g.us/leave")]


async def test_group_name_le_o_assunto_do_grupo() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/default/groups/120363000000000000@g.us"
        return httpx.Response(200, json={"id": "120363000000000000@g.us", "subject": "Turma A"})

    canal = _canal(httpx.MockTransport(handler))
    nome = await canal.group_name("120363000000000000@g.us")
    await canal.aclose()

    assert nome == "Turma A"


async def test_group_name_devolve_none_quando_falha_ou_nao_ha_assunto() -> None:
    respostas = iter([httpx.Response(404, json={}), httpx.Response(200, json={"id": "x@g.us"})])

    canal = _canal(httpx.MockTransport(lambda _: next(respostas)))

    assert await canal.group_name("1@g.us") is None  # o nome é só um enfeite: nunca levanta
    assert await canal.group_name("2@g.us") is None
    await canal.aclose()


# --- M17: menções e participantes de grupo ----------------------------------------------------


async def test_send_text_com_mencoes_manda_os_ids_e_o_texto_leva_o_arroba() -> None:
    corpos: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        corpos.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "abc"})

    canal = _canal(httpx.MockTransport(handler))
    await canal.send_text(
        "120363000000000001@g.us", "@5531999998888 your turn", mentions=["5531999998888"]
    )
    await canal.aclose()

    assert corpos == [
        {
            "session": "default",
            "chatId": "120363000000000001@g.us",
            "text": "@5531999998888 your turn",
            "mentions": ["5531999998888@c.us"],  # o formato que a doc do WAHA mostra
        }
    ]


async def test_send_text_sem_mencoes_nao_manda_o_campo() -> None:
    corpos: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        corpos.append(json.loads(request.content))
        return httpx.Response(200, json={})

    canal = _canal(httpx.MockTransport(handler))
    await canal.send_text("5531999998888@c.us", "oi", mentions=[])
    await canal.aclose()

    assert "mentions" not in corpos[0]


async def test_group_participants_devolve_os_numeros_e_resolve_lids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/default/groups/120363000000000001@g.us/participants/v2":
            return httpx.Response(
                200,
                json=[
                    {"id": "5531999998888@c.us", "role": "admin"},
                    {"id": "257161284317237@lid", "role": "participant"},
                    {"id": "999@lid", "role": "participant"},  # sem telefone conhecido
                ],
            )
        if request.url.path == "/api/default/lids/257161284317237":
            return httpx.Response(200, json={"pn": "5511988887777@c.us"})
        return httpx.Response(200, json={"pn": None})

    canal = _canal(httpx.MockTransport(handler))
    numeros = await canal.group_participants("120363000000000001@g.us")
    await canal.aclose()

    assert numeros == ["5531999998888", "5511988887777"]  # o LID sem número é descartado


async def test_group_participants_levanta_quando_o_waha_falha_para_o_chamador_usar_o_cache() -> (
    None
):
    canal = _canal(httpx.MockTransport(lambda _: httpx.Response(404, json={})))

    with pytest.raises(httpx.HTTPStatusError):
        await canal.group_participants("120363000000000001@g.us")
    await canal.aclose()


async def test_bot_ids_le_o_numero_e_o_lid_do_me_e_guarda_o_resultado() -> None:
    chamadas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas.append(request.url.path)
        me = {"id": "553199051491@c.us", "lid": "119302179033090@lid", "pushName": "Anki Zap"}
        return httpx.Response(200, json={"name": "default", "status": "WORKING", "me": me})

    canal = _canal(httpx.MockTransport(handler))
    ids = await canal.bot_ids()
    de_novo = await canal.bot_ids()
    await canal.aclose()

    assert ids == de_novo == {"553199051491", "119302179033090"}
    assert chamadas == ["/api/sessions/default"]  # uma ida só


async def test_bot_ids_falha_do_waha_vira_vazio_sem_levantar() -> None:
    canal = _canal(httpx.MockTransport(lambda _: httpx.Response(404)), max_tentativas=1)

    assert await canal.bot_ids() == set()
    await canal.aclose()


async def test_download_media_usa_o_host_e_a_api_key_do_bot_nao_o_da_url() -> None:
    requisicoes: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requisicoes.append(request)
        return httpx.Response(200, content=b"ogg-bytes")

    canal = _canal(httpx.MockTransport(handler))
    conteudo = await canal.download_media("http://localhost:3000/api/files/voz.oga?x=1")
    await canal.aclose()

    assert conteudo == b"ogg-bytes"
    (requisicao,) = requisicoes
    assert str(requisicao.url) == "http://waha:3000/api/files/voz.oga?x=1"
    assert requisicao.headers["X-Api-Key"] == "segredo-do-teste"
