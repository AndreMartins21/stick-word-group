"""Interface de canal (seção 8.4 da spec) — a lógica de negócio nunca importa o WAHA direto."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class Channel(Protocol):
    """Enviar texto, arquivo e voz, marcar como lido, digitando. Implementações: WahaChannel, ConsoleChannel,
    FakeChannel — trocável no futuro por Cloud API ou Telegram sem tocar na lógica de negócio."""

    async def send_text(
        self, chat_id: str, text: str, mentions: Sequence[str] | None = None
    ) -> None:
        """`mentions`: números (só dígitos) a marcar num grupo. O `text` precisa conter `@numero`
        de cada um (o WhatsApp mostra o nome no lugar)."""
        ...

    async def send_file(
        self, chat_id: str, nome: str, conteudo: bytes, tipo: str, legenda: str = ""
    ) -> None:
        """Envia um arquivo (documento) para o chat, com legenda opcional."""
        ...

    async def send_voice(self, chat_id: str, conteudo: bytes) -> None:
        """Envia uma nota de voz (áudio OGG/Opus) para o chat (M23)."""
        ...

    async def send_seen(self, chat_id: str) -> None: ...

    async def typing(self, chat_id: str, on: bool) -> None: ...

    async def leave_group(self, chat_id: str) -> None:
        """Sai de um grupo (M15: o bot não fica em grupo que nenhum admin ativou)."""
        ...

    async def group_participants(self, chat_id: str) -> list[str]:
        """Números (só dígitos) de quem está no grupo. Levanta se o canal falhar: quem chama cai
        no cadastro de membros."""
        ...

    async def group_name(self, chat_id: str) -> str | None:
        """O assunto do grupo, só para o dono reconhecê-lo em `/groups`. Nunca levanta: sem nome,
        `None`."""
        ...


class ChannelComLid(Channel, Protocol):
    """Extensão específica do WAHA: resolver @lid para número de telefone (seção 8.2).

    Não faz parte do `Channel` genérico porque é um detalhe do WhatsApp/WAHA — só o
    webhook (app/main.py), que já é a fronteira com o WAHA, depende disto.
    """

    async def resolve_lid(self, lid: str) -> str | None: ...

    async def bot_ids(self) -> set[str]:
        """Os dígitos do número e do LID do próprio bot (`me` da sessão), para reconhecer a marcação
        dele num grupo. Nunca levanta: se o canal falhar, vazio (M37)."""
        ...

    async def download_media(self, url: str) -> bytes:
        """Baixa a mídia que o webhook anunciou em `media.url` (M38). Levanta se falhar: quem chama
        avisa o grupo. O WAHA exige a API key e a URL pode apontar para o host de fora do compose."""
        ...
