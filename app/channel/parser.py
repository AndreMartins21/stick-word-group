"""Parser dos eventos do webhook do WAHA (seção 8.1) e regras de allowlist (seção 8.2).

Fica isolado em `app/channel/` porque é específico do formato de payload do WAHA — a
lógica de negócio (fora de `channel/`) nunca deve depender destes tipos diretamente.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SUFIXOS_IGNORADOS = ("@g.us", "@newsletter")
_CHAT_STATUS = "status@broadcast"


class MessagePayload(BaseModel):
    """Corpo de `payload` no evento `message` (confirmado na doc do WAHA)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    timestamp: int = 0
    from_: str = Field(alias="from")
    from_me: bool = Field(default=False, alias="fromMe")
    # O GOWS manda `to` e `body` nulos quando não consegue decifrar a mensagem.
    to: str | None = None
    body: str = ""
    has_media: bool = Field(default=False, alias="hasMedia")
    # Em grupo, quem escreveu (o `from` é o grupo). Formato confirmado na doc do WAHA; se vem como
    # @c.us ou @lid no GOWS só se vê no WhatsApp real (ver docs/noite/PENDENCIAS.md).
    participant: str | None = None
    # O WAHA não documenta o nome de quem escreveu nem os ids mencionados no payload de um grupo:
    # lemos o que der (vários formatos, ver `nome_do_remetente`) e o resto vira `None`/vazio.
    data: dict[str, Any] = Field(default_factory=dict, alias="_data")
    mentioned_ids: list[str] = Field(default_factory=list, alias="mentionedIds")
    notify_name: str | None = Field(default=None, alias="notifyName")
    # M38 (ADR-0036): a mensagem citada (`replyTo`, doc do WAHA) e a mídia baixada (`media.url`).
    reply_to: dict[str, Any] | None = Field(default=None, alias="replyTo")
    media: dict[str, Any] | None = None

    def nome_do_remetente(self) -> str | None:
        """O nome que o WhatsApp informa (o "push name"), nunca o telefone. `None` se o payload
        não trouxer nenhum dos formatos conhecidos (GOWS: `_data.Info.PushName`)."""
        info = self.data.get("Info")
        candidatos = [
            self.notify_name,
            self.data.get("pushName"),
            self.data.get("notifyName"),
            info.get("PushName") if isinstance(info, dict) else None,
        ]
        return next((c.strip() for c in candidatos if isinstance(c, str) and c.strip()), None)

    def ids_mencionados(self) -> list[str]:
        """Os ids marcados na mensagem. O WAHA/GOWS deixa `mentionedIds` vazio: a marcação vem em
        `_data.Message.<tipo>.contextInfo.mentionedJID` (confirmado no WhatsApp real, M37)."""
        ids = list(self.mentioned_ids)
        mensagem = self.data.get("Message")
        if isinstance(mensagem, dict):
            for conteudo in mensagem.values():
                contexto = conteudo.get("contextInfo") if isinstance(conteudo, dict) else None
                if not isinstance(contexto, dict):
                    continue
                for chave in ("mentionedJID", "mentionedJid"):
                    marcados = contexto.get(chave)
                    if isinstance(marcados, list):
                        ids += [m for m in marcados if isinstance(m, str)]
        return list(dict.fromkeys(ids))

    def ids_do_autor_citado(self) -> list[str]:
        """Quem escreveu a mensagem que esta responde (citação). O WAHA expõe `replyTo.participant`;
        o GOWS também traz `_data.Message.<tipo>.contextInfo.participant` (só vale com citação).
        Vazio se a mensagem não cita nada (M38, ADR-0036)."""
        ids: list[str] = []
        if isinstance(self.reply_to, dict) and isinstance(self.reply_to.get("participant"), str):
            ids.append(self.reply_to["participant"])
        mensagem = self.data.get("Message")
        if isinstance(mensagem, dict):
            for conteudo in mensagem.values():
                contexto = conteudo.get("contextInfo") if isinstance(conteudo, dict) else None
                if not isinstance(contexto, dict):
                    continue
                autor = contexto.get("participant")
                if isinstance(autor, str) and (
                    contexto.get("stanzaID") or contexto.get("quotedMessage")
                ):
                    ids.append(autor)
        return [i for i in dict.fromkeys(ids) if i]

    def mimetype_da_midia(self) -> str | None:
        mimetype = self.media.get("mimetype") if isinstance(self.media, dict) else None
        return mimetype if isinstance(mimetype, str) and mimetype else None

    def url_da_midia(self) -> str | None:
        url = self.media.get("url") if isinstance(self.media, dict) else None
        return url if isinstance(url, str) and url else None

    def eh_audio(self) -> bool:
        """Nota de voz ou áudio (M38): pelo mimetype da mídia ou, sem ele, pelo `audioMessage` do GOWS."""
        if not self.has_media:
            return False
        mimetype = self.mimetype_da_midia()
        if mimetype is not None:
            return mimetype.startswith("audio/")
        mensagem = self.data.get("Message")
        return isinstance(mensagem, dict) and "audioMessage" in mensagem

    @field_validator("body", mode="before")
    @classmethod
    def _sem_texto_e_string_vazia(cls, valor: object) -> object:
        return "" if valor is None else valor


class MessageEvent(BaseModel):
    event: Literal["message"]
    session: str
    payload: MessagePayload


class GrupoDoEvento(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    subject: str | None = None


class GroupJoinPayload(BaseModel):
    """`group.v2.join`: o bot entrou (ou foi adicionado) num grupo. O payload não diz QUEM
    adicionou (confirmado na doc do WAHA), então nada aqui autoriza o grupo."""

    model_config = ConfigDict(extra="ignore")

    group: GrupoDoEvento


class GroupJoinEvent(BaseModel):
    event: Literal["group.v2.join"]
    session: str
    payload: GroupJoinPayload


class SessionStatusPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    status: str


class SessionStatusEvent(BaseModel):
    event: Literal["session.status"]
    session: str
    payload: SessionStatusPayload


def parse_evento(
    bruto: dict[str, Any],
) -> MessageEvent | SessionStatusEvent | GroupJoinEvent | None:
    """Interpreta o corpo do webhook. `None` para eventos que não assinamos (seção 8.1)."""
    tipo = bruto.get("event")
    if tipo == "message":
        return MessageEvent.model_validate(bruto)
    if tipo == "session.status":
        return SessionStatusEvent.model_validate(bruto)
    if tipo == "group.v2.join":
        return GroupJoinEvent.model_validate(bruto)
    return None


def deve_ignorar_chat(chat_id: str) -> bool:
    """Grupos, canais e status/broadcast (seção 8.1, passo 2) — nunca respondemos a eles."""
    return chat_id == _CHAT_STATUS or chat_id.endswith(_SUFIXOS_IGNORADOS)


def eh_lid(chat_id: str) -> bool:
    return chat_id.endswith("@lid")


def digitos_do_chat_id(chat_id: str) -> str:
    """Extrai só os dígitos de um chatId (`5531999998888@c.us` -> `5531999998888`)."""
    return re.sub(r"\D", "", chat_id.split("@", 1)[0])


def _variantes_com_e_sem_nono_digito(numero: str) -> set[str]:
    """Número de celular brasileiro: 55 + DDD (2) + [9] + linha (8). Aceita as duas formas."""
    digitos = re.sub(r"\D", "", numero)
    variantes = {digitos}
    if len(digitos) == 13 and digitos[4] == "9":
        variantes.add(digitos[:4] + digitos[5:])
    elif len(digitos) == 12:
        variantes.add(digitos[:4] + "9" + digitos[4:])
    return variantes


def numero_e_permitido(numero_resolvido: str, allowed_number: str) -> bool:
    """Compara aceitando a variação do nono dígito em ambos os lados (seção 8.2)."""
    return bool(
        _variantes_com_e_sem_nono_digito(numero_resolvido)
        & _variantes_com_e_sem_nono_digito(allowed_number)
    )


def numero_esta_na_lista(numero_resolvido: str, permitidos: Iterable[str]) -> bool:
    """A allowlist do M14 (ADR-0017): o número bate com algum dos permitidos (nono dígito à parte)."""
    return any(numero_e_permitido(numero_resolvido, permitido) for permitido in permitidos)
