"""Cliente HTTP do WAHA (seção 8.3): send_text, send_file, send_voice, send_seen, typing(on/off), session_status.

Corpos de request confirmados na doc atual do WAHA (waha.devlike.pro/docs/how-to/*):
`{"session": ..., "chatId": ...}` mais o campo específico de cada endpoint.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from collections.abc import Sequence
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from app.channel.base import MidiaGrandeDemais

logger = logging.getLogger(__name__)


class WahaChannel:
    """Implementa `ChannelComLid`. Timeout de 15s, até 2 novas tentativas com backoff para 5xx.

    Os logs nunca incluem a API key (ela só entra no header `X-Api-Key`, nunca é logada).
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: SecretStr,
        session: str,
        timeout: float = 15.0,
        timeout_arquivo: float = 90.0,
        max_tentativas: int = 3,
        backoff_base: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._session = session
        self._max_tentativas = max_tentativas
        self._timeout_arquivo = timeout_arquivo
        self._backoff_base = backoff_base
        self._ids_do_bot: set[str] = set()
        self._cliente = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-Api-Key": api_key.get_secret_value()},
            timeout=timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._cliente.aclose()

    async def send_text(
        self, chat_id: str, text: str, mentions: Sequence[str] | None = None
    ) -> None:
        """Com `mentions`, manda `"mentions": ["NUMERO@c.us"]` (o formato da doc do WAHA; o texto
        precisa conter `@NUMERO`)."""
        corpo: dict[str, object] = {"session": self._session, "chatId": chat_id, "text": text}
        if mentions:
            corpo["mentions"] = [f"{numero}@c.us" for numero in mentions]
        await self._post("/api/sendText", corpo)

    async def send_file(
        self, chat_id: str, nome: str, conteudo: bytes, tipo: str, legenda: str = ""
    ) -> None:
        """`POST /api/sendFile` com o arquivo em base64 (`file.data`). Sem retentativa e com
        timeout maior: reenviar uma resposta lenta duplicaria o arquivo no WhatsApp; se falhar,
        quem chama decide (o `/export` cai no link)."""
        await self._com_retentativas(
            "POST",
            "/api/sendFile",
            json={
                "session": self._session,
                "chatId": chat_id,
                "file": {
                    "mimetype": tipo,
                    "filename": nome,
                    "data": base64.b64encode(conteudo).decode("ascii"),
                },
                "caption": legenda,
            },
            tentativas=1,
            limite_segundos=self._timeout_arquivo,
        )

    async def send_voice(self, chat_id: str, conteudo: bytes) -> None:
        """`POST /api/sendVoice` com OGG/Opus em base64 (`file.data`): o WAHA exige esse formato
        para a nota de voz, e o TTS já o entrega, então não usa `convert`. Sem retentativa, como o
        `send_file`: reenviar uma resposta lenta duplicaria o áudio."""
        await self._com_retentativas(
            "POST",
            "/api/sendVoice",
            json={
                "session": self._session,
                "chatId": chat_id,
                "file": {
                    "mimetype": "audio/ogg; codecs=opus",
                    "data": base64.b64encode(conteudo).decode("ascii"),
                },
                "convert": False,
            },
            tentativas=1,
            limite_segundos=self._timeout_arquivo,
        )

    async def send_seen(self, chat_id: str) -> None:
        await self._post("/api/sendSeen", {"session": self._session, "chatId": chat_id})

    async def typing(self, chat_id: str, on: bool) -> None:
        endpoint = "/api/startTyping" if on else "/api/stopTyping"
        await self._post(endpoint, {"session": self._session, "chatId": chat_id})

    async def leave_group(self, chat_id: str) -> None:
        """`POST /api/{session}/groups/{id}/leave` (GOWS suporta, conferido na doc)."""
        await self._post(f"/api/{self._session}/groups/{chat_id}/leave", {})

    async def group_participants(self, chat_id: str) -> list[str]:
        """`GET /api/{session}/groups/{id}/participants/v2` -> [{"id": "...@c.us|@lid", "role"}].
        LIDs viram número pelo endpoint de LIDs; os que ele não resolve ficam de fora."""
        resposta = await self._get(f"/api/{self._session}/groups/{chat_id}/participants/v2")
        numeros: list[str] = []
        for participante in resposta.json():
            identificador = str(participante["id"])
            numero = (
                await self.resolve_lid(identificador)
                if identificador.endswith("@lid")
                else identificador.split("@", 1)[0]
            )
            if numero:
                numeros.append(numero)
        return numeros

    async def group_name(self, chat_id: str) -> str | None:
        """`GET /api/{session}/groups/{id}`: o campo `subject`. O nome é um enfeite, então uma
        falha (rede, 404, campo ausente) vira `None` em vez de derrubar quem chamou."""
        try:
            resposta = await self._get(f"/api/{self._session}/groups/{chat_id}")
            assunto = resposta.json().get("subject")
        except Exception:
            logger.warning("não consegui ler o nome do grupo", exc_info=True)
            return None
        return str(assunto) if assunto else None

    async def session_status(self) -> str:
        resposta = await self._get(f"/api/sessions/{self._session}")
        status = resposta.json()["status"]
        return str(status)

    async def resolve_lid(self, lid: str) -> str | None:
        """`GET /api/{session}/lids/{lid}` -> {"lid": ..., "pn": "...@c.us" | null}."""
        numero_lid = lid.split("@", 1)[0]
        resposta = await self._get(f"/api/{self._session}/lids/{numero_lid}")
        pn = resposta.json().get("pn")
        return str(pn).split("@", 1)[0] if pn else None

    async def bot_ids(self) -> set[str]:
        """`GET /api/sessions/{session}` -> `me: {id: "...@c.us", lid: "...@lid"}`: os dígitos dos dois
        ids do bot (a marcação dele chega pelo LID). Guardado depois do 1º sucesso; falha vira vazio."""
        if self._ids_do_bot:
            return self._ids_do_bot
        try:
            resposta = await self._get(f"/api/sessions/{self._session}")
            me = resposta.json().get("me") or {}
        except Exception:
            logger.warning("não consegui ler o `me` da sessão", exc_info=True)
            return set()
        ids = {
            re.sub(r"\D", "", str(me[campo]).split("@", 1)[0])
            for campo in ("id", "lid")
            if me.get(campo)
        }
        self._ids_do_bot = {i for i in ids if i}
        return self._ids_do_bot

    async def download_media(self, url: str, max_bytes: int | None = None) -> bytes:
        """`GET` no caminho de `media.url` (`/api/files/...`) pelo host e pela API key do bot: o
        webhook anuncia `http://localhost:3000/...`, que de dentro do compose não é o WAHA. Em
        *streaming*: com `max_bytes` (M41, ADR-0039) o corpo é lido aos pedaços e o download é
        abortado ao passar do limite (`MidiaGrandeDemais`), sem encher a memória do container."""
        partes = urlsplit(url)
        alvo = partes.path + (f"?{partes.query}" if partes.query else "")
        ultimo_erro: Exception | None = None
        for tentativa in range(self._max_tentativas):
            try:
                async with self._cliente.stream(
                    "GET", alvo, timeout=self._timeout_arquivo
                ) as resposta:
                    if resposta.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            f"WAHA respondeu {resposta.status_code}",
                            request=resposta.request,
                            response=resposta,
                        )
                    resposta.raise_for_status()
                    declarado = resposta.headers.get("content-length", "")
                    if max_bytes is not None and declarado.isdigit() and int(declarado) > max_bytes:
                        raise MidiaGrandeDemais(alvo)
                    pedacos: list[bytes] = []
                    total = 0
                    async for pedaco in resposta.aiter_bytes():
                        total += len(pedaco)
                        if max_bytes is not None and total > max_bytes:
                            raise MidiaGrandeDemais(alvo)
                        pedacos.append(pedaco)
                    return b"".join(pedacos)
            except (httpx.TransportError, httpx.HTTPStatusError) as erro:
                if isinstance(erro, httpx.HTTPStatusError) and erro.response.status_code < 500:
                    raise
                ultimo_erro = erro
                logger.warning("falha ao baixar mídia (tentativa %d)", tentativa + 1)
            if tentativa < self._max_tentativas - 1:
                await asyncio.sleep(self._backoff_base * (2**tentativa))
        if ultimo_erro is None:
            raise RuntimeError("download_media terminou sem sucesso nem erro registrado")
        raise ultimo_erro

    async def _get(self, path: str) -> httpx.Response:
        return await self._com_retentativas("GET", path, json=None)

    async def _post(self, path: str, corpo: dict[str, object]) -> httpx.Response:
        return await self._com_retentativas("POST", path, json=corpo)

    async def _com_retentativas(
        self,
        metodo: str,
        path: str,
        *,
        json: dict[str, object] | None,
        tentativas: int | None = None,
        limite_segundos: float | None = None,
    ) -> httpx.Response:
        ultimo_erro: Exception | None = None
        max_tentativas = tentativas or self._max_tentativas
        for tentativa in range(max_tentativas):
            try:
                if limite_segundos is None:
                    resposta = await self._cliente.request(metodo, path, json=json)
                else:
                    resposta = await self._cliente.request(
                        metodo, path, json=json, timeout=limite_segundos
                    )
            except httpx.TransportError as exc:
                ultimo_erro = exc
                logger.warning(
                    "falha de rede ao chamar %s %s (tentativa %d)", metodo, path, tentativa + 1
                )
            else:
                if resposta.status_code < 500:
                    resposta.raise_for_status()
                    return resposta
                ultimo_erro = httpx.HTTPStatusError(
                    f"WAHA respondeu {resposta.status_code}",
                    request=resposta.request,
                    response=resposta,
                )
                logger.warning(
                    "WAHA respondeu %d em %s %s (tentativa %d)",
                    resposta.status_code,
                    metodo,
                    path,
                    tentativa + 1,
                )
            if tentativa < max_tentativas - 1:
                await asyncio.sleep(self._backoff_base * (2**tentativa))
        if ultimo_erro is None:
            raise RuntimeError("_com_retentativas terminou sem sucesso nem erro registrado")
        raise ultimo_erro
