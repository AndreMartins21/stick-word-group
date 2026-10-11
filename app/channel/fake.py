"""FakeChannel (seção 8.4): dublê em memória, para testes — nunca faz chamada de rede."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.channel.base import MidiaGrandeDemais


@dataclass
class FakeChannel:
    textos_enviados: list[tuple[str, str]] = field(default_factory=list)
    arquivos_enviados: list[tuple[str, str, bytes, str]] = field(default_factory=list)
    falha_no_arquivo: bool = False
    vozes_enviadas: list[tuple[str, bytes]] = field(default_factory=list)
    falha_na_voz: bool = False
    ordem: list[str] = field(default_factory=list)  # "texto" | "voz", na ordem em que saíram
    vistos: list[str] = field(default_factory=list)
    digitando: list[tuple[str, bool]] = field(default_factory=list)
    lids_conhecidos: dict[str, str | None] = field(default_factory=dict)
    ids_do_bot: set[str] = field(default_factory=set)  # dígitos do número e do LID do bot
    mencoes_enviadas: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    participantes_de_grupos: dict[str, list[str]] = field(default_factory=dict)
    grupos_deixados: list[str] = field(default_factory=list)
    nomes_de_grupos: dict[str, str] = field(default_factory=dict)
    midias: dict[str, bytes] = field(default_factory=dict)  # url -> conteúdo (M38)
    downloads: list[str] = field(default_factory=list)  # urls baixadas (M41)

    async def send_text(
        self, chat_id: str, text: str, mentions: Sequence[str] | None = None
    ) -> None:
        self.ordem.append("texto")
        self.textos_enviados.append((chat_id, text))
        if mentions:
            self.mencoes_enviadas.append((chat_id, tuple(mentions)))

    async def send_file(
        self,
        chat_id: str,
        nome: str,
        conteudo: bytes,
        tipo: str,  # noqa: ARG002
        legenda: str = "",
    ) -> None:
        if self.falha_no_arquivo:
            raise RuntimeError("falha simulada ao enviar o arquivo")
        self.arquivos_enviados.append((chat_id, nome, conteudo, legenda))

    async def send_voice(self, chat_id: str, conteudo: bytes) -> None:
        if self.falha_na_voz:
            raise RuntimeError("falha simulada ao enviar a voz")
        self.ordem.append("voz")
        self.vozes_enviadas.append((chat_id, conteudo))

    async def send_seen(self, chat_id: str) -> None:
        self.vistos.append(chat_id)

    async def typing(self, chat_id: str, on: bool) -> None:
        self.digitando.append((chat_id, on))

    async def leave_group(self, chat_id: str) -> None:
        self.grupos_deixados.append(chat_id)

    async def group_participants(self, chat_id: str) -> list[str]:
        return list(self.participantes_de_grupos.get(chat_id, []))

    async def group_name(self, chat_id: str) -> str | None:
        return self.nomes_de_grupos.get(chat_id)

    async def resolve_lid(self, lid: str) -> str | None:
        return self.lids_conhecidos.get(lid)

    async def bot_ids(self) -> set[str]:
        return set(self.ids_do_bot)

    async def download_media(self, url: str, max_bytes: int | None = None) -> bytes:
        self.downloads.append(url)
        if url not in self.midias:
            raise RuntimeError(f"mídia inexistente: {url}")
        if max_bytes is not None and len(self.midias[url]) > max_bytes:
            raise MidiaGrandeDemais(url)
        return self.midias[url]
