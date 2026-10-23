"""O que os fluxos compartilham: dependências e a ponte para o código síncrono."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain.models import Sense, SentidoSalvo, Sessao
from app.domain.rodizio import Candidato
from app.flows.conversa import Conversa
from app.repo.base import Banco, Repository
from app.services.audio import ServicoAudio
from app.services.letras import LyricsProvider
from app.services.llm import Tutor

FUSO_PADRAO = ZoneInfo("America/Sao_Paulo")  # o mesmo padrão de `Settings.timezone`


@dataclass(frozen=True)
class Autor:
    """Quem escreveu a mensagem de um grupo (M16): o número (só dígitos), o nome que o WhatsApp
    informa (nunca o telefone) e os números mencionados na mensagem (para `!teacher`)."""

    numero: str
    nome: str | None = None
    mencionados: tuple[str, ...] = ()


Participantes = Callable[[str], Awaitable[list[str]]]  # chat_id do grupo -> números


def _sortear(itens: Sequence[Candidato]) -> Candidato:
    return random.choice(itens)  # noqa: S311 — só um desempate, sem fim criptográfico


@dataclass(frozen=True)
class ConfigGrupo:
    """A revisão em grupo (M17, ADR-0020): quantas palavras por rodada, quanto esperar a pessoa
    marcada, de onde vem a lista de participantes, quem é o bot (nunca é marcado) e o sorteio."""

    limite: int = 5
    timeout: timedelta = timedelta(hours=3)
    participantes: Participantes | None = None
    numero_do_bot: str | None = None
    sortear: Callable[[Sequence[Candidato]], Candidato] = field(default=_sortear)


@dataclass(frozen=True)
class Deps:
    repo: Repository
    tutor: Tutor
    conversa: Conversa
    agora: Callable[[], datetime]
    fuso: ZoneInfo = FUSO_PADRAO  # fuso do aluno, para mostrar horários de lembrete
    letras: LyricsProvider | None = None  # M13: fonte das letras do /song (None = indisponível)
    audio: ServicoAudio | None = None  # M23: pronúncia em áudio (None = indisponível)
    grupo_prefixo: str | None = None  # M16: o prefixo do grupo (`!`); `None` no privado
    autor: Autor | None = None  # M16: quem escreveu, em grupo
    chat_id: str = ""  # o espaço desta mensagem
    grupo_cfg: ConfigGrupo = field(default_factory=ConfigGrupo)  # M17
    so_ingles: bool = False  # M34: grupo de B1-B2 para cima não vê português
    # M57 (ADR-0055): dono, admin do bot ou professor global — nunca marcado no desafio semanal.
    eh_staff: Callable[[str], bool] = lambda _numero: False
    # M61: dono ou admin do bot (staff que não é "professor"): o `!group` o rotula como admin.
    eh_admin: Callable[[str], bool] = lambda _numero: False
    banco: Banco | None = None  # M57: a raiz, para os professores globais (`!teacher`/`!student`)

    @property
    def em_grupo(self) -> bool:
        return self.grupo_prefixo is not None

    @property
    def p(self) -> str:
        """O prefixo dos comandos que os textos citam: o do grupo, ou `/` no privado."""
        return self.grupo_prefixo or "/"

    @property
    def autor_id(self) -> str | None:
        return self.autor.numero if self.autor else None

    @property
    def cmd_lembretes(self) -> str:
        return f"{self.grupo_prefixo}reminder" if self.em_grupo else "/reminders"

    @property
    def pt(self) -> bool:
        return not self.so_ingles

    def rotulo(self, sentido: SentidoSalvo | Sense) -> str:
        """O que acompanha a palavra em cabeçalhos: a tradução, ou a definição se não há PT."""
        return sentido.definicao if self.so_ingles else sentido.traducao

    def sessao_vazia(self) -> Sessao:
        return Sessao(atualizado_em=self.agora())


async def bloq[**P, R](funcao: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    """Roda em thread código síncrono e bloqueante (Firestore, IA) sem travar o event loop."""
    return await asyncio.to_thread(funcao, *args, **kwargs)
