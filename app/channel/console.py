"""ConsoleChannel (seção 8.4): o canal do simulador — a conversa aparece no terminal."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path


class ConsoleChannel:
    """Com `pasta`, os arquivos "enviados" são gravados lá (o simulador não tem WhatsApp)."""

    def __init__(
        self,
        saida: Callable[[str], None] = print,
        pasta: Path | None = None,
        nomes: Mapping[str, str] | None = None,
    ) -> None:
        self._saida = saida
        self._pasta = pasta
        # número -> nome, para mostrar a menção como no WhatsApp (o simulador vai preenchendo)
        self._nomes = nomes if nomes is not None else {}
        self._contador_de_vozes = 0

    async def send_file(
        self,
        chat_id: str,  # noqa: ARG002
        nome: str,
        conteudo: bytes,
        tipo: str,  # noqa: ARG002
        legenda: str = "",
    ) -> None:
        onde = ""
        if self._pasta is not None:
            self._pasta.mkdir(parents=True, exist_ok=True)
            destino = self._pasta / Path(nome).name
            destino.write_bytes(conteudo)
            onde = f"\n{destino.resolve()}"
        await self.send_text("", f"📎 {Path(nome).name} ({len(conteudo)} bytes)\n{legenda}{onde}")

    async def send_voice(self, chat_id: str, conteudo: bytes) -> None:  # noqa: ARG002
        """Sem WhatsApp, a nota de voz vira um `.ogg` na pasta (para ouvir) e uma linha no terminal."""
        onde = ""
        if self._pasta is not None:
            self._pasta.mkdir(parents=True, exist_ok=True)
            self._contador_de_vozes += 1
            destino = self._pasta / f"voz_{self._contador_de_vozes:03d}.ogg"
            destino.write_bytes(conteudo)
            onde = f"\n{destino.resolve()}"
        await self.send_text("", f"🔊 (nota de voz, {len(conteudo)} bytes){onde}")

    async def send_text(
        self,
        chat_id: str,  # noqa: ARG002
        text: str,
        mentions: Sequence[str] | None = None,
    ) -> None:
        for numero in mentions or ():
            if numero in self._nomes:
                text = text.replace(f"@{numero}", f"@{self._nomes[numero]}")
        corpo = "\n".join(f"│ {linha}" if linha else "│" for linha in text.splitlines())
        self._saida(f"┌─ 🤖 stick-word-group\n{corpo}\n└─")

    async def send_seen(self, chat_id: str) -> None:  # noqa: ARG002
        return None

    async def leave_group(self, chat_id: str) -> None:  # noqa: ARG002
        self._saida("  (o bot saiu do grupo)")

    async def group_participants(self, chat_id: str) -> list[str]:  # noqa: ARG002
        return list(self._nomes)

    async def group_name(self, chat_id: str) -> str | None:  # noqa: ARG002
        return None

    async def typing(self, chat_id: str, on: bool) -> None:  # noqa: ARG002
        if on:
            self._saida("  … digitando")
