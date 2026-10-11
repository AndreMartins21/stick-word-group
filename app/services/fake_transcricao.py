"""FakeTranscritor (M38): dublê em memória da transcrição, para testes — nunca faz chamada de rede."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.llm import LLMError


@dataclass
class FakeTranscritor:
    texto: str = "I goed to the market yesterday"
    falha: bool = False
    chamadas: list[tuple[int, str]] = field(default_factory=list)

    def transcrever(self, conteudo: bytes, mimetype: str) -> str:
        self.chamadas.append((len(conteudo), mimetype))
        if self.falha:
            raise LLMError("falha simulada da transcrição")
        return self.texto
