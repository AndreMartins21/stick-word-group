"""Montagem compartilhada dos testes de fluxo: roteador com fakes, relógio controlável e as
respostas de IA do ciclo "stall" (M9: interface em inglês, menu único)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.channel.fake import FakeChannel
from app.domain.models import (
    Evaluation,
    Expansion,
    Explanation,
    Sense,
)
from app.domain.rodizio import Candidato
from app.flows.base import Autor, ConfigGrupo, Participantes
from app.flows.commands import Exportador, StatusDaSessao
from app.flows.conversa import Conversa
from app.flows.router import Router
from app.repo.base import Repository
from app.repo.memory import MemoryBanco
from app.services.audio import ServicoAudio
from app.services.fake_llm import FakeTutor
from app.services.letras import LyricsProvider

CHAT = "5531999998888@c.us"
GRUPO = "120363000000000001@g.us"
DONO_NUMERO = "5531990000001"
ANA = Autor("5531999998888", "Ana")
BIA = Autor("5511988887777", "Bia")
CAIO = Autor("5521977776666", "Caio")
T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)

S1 = Sense(
    id="s1",
    traducao="travar, emperrar",
    definicao="to stop making progress",
    exemplo="The [[talks]] stalled.",
)
S2 = Sense(
    id="s2",
    traducao="enrolar",
    definicao="to delay on purpose",
    exemplo="Stop [[stalling]] and answer me.",
)


def explicacao_stall(*, sentido_do_contexto: str = "s1", dois_sentidos: bool = True) -> Explanation:
    return Explanation(
        ok=True,
        palavra="stall",
        classe="verb",
        cefr_estimado="B2",
        sentidos=[S1, S2] if dois_sentidos else [S1],
        sentido_do_contexto=sentido_do_contexto,
        frase_contexto="The talks [[stalled]].",
        nota='"the car stalled" = the car died',
        tags=["trabalho"],
    )


def avaliacao(veredito: str = "quase") -> Evaluation:
    return Evaluation(
        usa_palavra_alvo=True,
        sentido_correto=True,
        veredito=veredito,
        correcoes=["didn't sent → didn't send"],
        versao_natural="The project [[stalled]] because the client didn't send the documents.",
        explicacao='After "didn\'t", the verb stays in the base form.',
    )


def expansoes() -> list[Expansion]:
    return [
        Expansion(expressao="stall for time", traducao="enrolar", tipo="colocacao"),
        Expansion(expressao="stall out", traducao="pifar", tipo="phrasal_verb"),
        Expansion(expressao="stalled talks", traducao="negociações paradas", tipo="colocacao"),
        Expansion(expressao="grind to a halt", traducao="parar aos poucos", tipo="expressao"),
    ]


class Relogio:
    def __init__(self) -> None:
        self.agora_ = T0

    def agora(self) -> datetime:
        return self.agora_

    def avancar(self, delta: timedelta) -> None:
        self.agora_ += delta


@dataclass
class Montagem:
    router: Router
    channel: FakeChannel
    banco: MemoryBanco
    repo: Repository  # o caderno do aluno de `CHAT`
    tutor: FakeTutor
    relogio: Relogio
    conversa: Conversa
    esperas: list[float] = field(default_factory=list)

    async def diz(self, texto: str) -> list[str]:
        """Manda `texto` como o aluno e devolve o que o bot respondeu (só os textos)."""
        antes = len(self.channel.textos_enviados)
        await self.router.processar(texto, CHAT)
        return [t for _, t in self.channel.textos_enviados[antes:]]

    async def diz_no_grupo(self, autor: Autor, texto: str, *, chat: str = GRUPO) -> list[str]:
        """Manda `texto` (com o prefixo, se for o caso) como `autor` no grupo e devolve o que o
        bot respondeu no grupo."""
        antes = len(self.channel.textos_enviados)
        await self.router.processar(texto, chat, autor)
        return [t for c, t in self.channel.textos_enviados[antes:] if c == chat]

    async def marca_no_grupo(self, autor: Autor, texto: str, *, chat: str = GRUPO) -> list[str]:
        """Manda `texto` marcando o bot (M37; o webhook já tirou a marcação) como `autor` no grupo
        e devolve o que o bot respondeu no grupo."""
        antes = len(self.channel.textos_enviados)
        await self.router.processar(texto, chat, autor, marcado=True)
        return [t for c, t in self.channel.textos_enviados[antes:] if c == chat]


def montar(
    *,
    tutor: FakeTutor | None = None,
    exportador: Exportador | None = None,
    status_da_sessao: StatusDaSessao | None = None,
    letras: LyricsProvider | None = None,
    audio: ServicoAudio | None = None,
    prefixo_do_grupo: str = "!",
    grupo_limite: int = 5,
    grupo_timeout: timedelta = timedelta(hours=3),
    numero_do_bot: str | None = None,
    sortear: Callable[[Sequence[Candidato]], Candidato] | None = None,
    participantes: Participantes | None = None,
    admins: tuple[str, ...] = (),
) -> Montagem:
    channel = FakeChannel()
    banco = MemoryBanco()
    tutor = tutor or FakeTutor()
    relogio = Relogio()
    esperas: list[float] = []

    async def dormir(segundos: float) -> None:
        esperas.append(segundos)

    def criar_conversa(chat_id: str) -> Conversa:
        return Conversa(channel, chat_id, dormir=dormir, atraso=lambda: 1.5)

    router = Router(
        banco=banco,
        tutor=tutor,
        criar_conversa=criar_conversa,
        nivel_padrao="B1-B2",
        agora=relogio.agora,
        status_da_sessao=status_da_sessao,
        exportador=exportador,
        letras=letras,
        audio=audio,
        prefixo_do_grupo=prefixo_do_grupo,
        eh_dono=lambda numero: numero == DONO_NUMERO,
        eh_admin=lambda numero: numero == DONO_NUMERO or numero in admins,
        config_grupo=ConfigGrupo(
            limite=grupo_limite,
            timeout=grupo_timeout,
            participantes=participantes or channel.group_participants,
            numero_do_bot=numero_do_bot,
            **({"sortear": sortear} if sortear else {}),
        ),
    )
    return Montagem(
        router,
        channel,
        banco,
        banco.do_espaco(CHAT),
        tutor,
        relogio,
        router.conversa_do(CHAT),
        esperas,
    )


def eventos(caplog_records: Sequence[logging.LogRecord], nome: str | None = None) -> list[Any]:
    """Os registros de `registrar_evento` (M27, ADR-0028) capturados por `caplog`, como uma lista
    de objetos com os campos extras acessíveis por atributo (`evento.motivo`, `evento.n`...).

    `getattr`/`SimpleNamespace` em vez do `LogRecord` bruto: os campos de `extra=` só existem em
    tempo de execução, e o mypy reprova acessá-los como atributo de `LogRecord`."""
    from types import SimpleNamespace

    campos_padrao = set(vars(logging.LogRecord("x", logging.INFO, "x", 0, "x", (), None)))
    achados = [
        SimpleNamespace(**{k: v for k, v in vars(r).items() if k not in campos_padrao})
        for r in caplog_records
        if hasattr(r, "evento")
    ]
    return [a for a in achados if nome is None or a.evento == nome]


def sem_jitter(_espaco_id: str, _tipo: str) -> timedelta:
    """Fixa o deslocamento dos lembretes de grupo (M55) em zero, para testar o horário configurado."""
    return timedelta(0)
