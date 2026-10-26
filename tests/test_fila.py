"""M47 (ADR-0045): fila por chat com teto e vagas de processamento globais."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator, Sequence

import pytest

from app.channel.fake import FakeChannel
from app.domain.models import Explanation, NivelUsuario
from app.flows.base import Autor
from app.flows.conversa import Conversa
from app.flows.router import Router
from app.repo.memory import MemoryBanco
from app.services.fake_llm import FakeTutor
from tests.helpers import eventos, explicacao_stall

CHAT_A = "120363000000000001@g.us"
CHAT_B = "120363000000000002@g.us"


async def _sem_espera(_: float) -> None:
    return None


class _TutorLento(FakeTutor):
    """`explain` bloqueia numa thread até o teste liberar; conta quantas chamadas estão abertas."""

    def __init__(self, liberar: asyncio.Event, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__(explicacoes=[explicacao_stall() for _ in range(50)])
        self.liberar = liberar
        self.loop = loop
        self.abertas = 0
        self.pico = 0

    def explain(
        self, texto: str, nivel: NivelUsuario, palavras_do_aluno: Sequence[str] = ()
    ) -> Explanation:
        self.abertas += 1
        self.pico = max(self.pico, self.abertas)
        asyncio.run_coroutine_threadsafe(self.liberar.wait(), self.loop).result(timeout=5)
        self.abertas -= 1
        return super().explain(texto, nivel, palavras_do_aluno)


@pytest.fixture
def canal() -> Iterator[FakeChannel]:
    yield FakeChannel()


def _router(
    canal: FakeChannel,
    tutor: FakeTutor,
    *,
    max_fila_por_chat: int = 3,
    max_processamentos: int = 4,
) -> Router:
    return Router(
        banco=MemoryBanco(),
        tutor=tutor,
        criar_conversa=lambda chat: Conversa(canal, chat, dormir=_sem_espera, atraso=lambda: 0.0),
        nivel_padrao="B1-B2",
        max_fila_por_chat=max_fila_por_chat,
        max_processamentos=max_processamentos,
    )


async def test_fila_cheia_descarta_o_excedente_em_silencio(
    canal: FakeChannel, caplog: pytest.LogCaptureFixture
) -> None:
    liberar = asyncio.Event()
    tutor = _TutorLento(liberar, asyncio.get_running_loop())
    router = _router(canal, tutor, max_fila_por_chat=2)
    autor = Autor(numero="5531999990001")

    with caplog.at_level(logging.INFO):
        tarefas = [
            asyncio.create_task(router.processar(f"!add word{i}", CHAT_A, autor)) for i in range(6)
        ]
        await asyncio.sleep(0.1)  # as duas primeiras entraram; as outras quatro foram descartadas
        liberar.set()
        # a segunda mensagem do chat vira `route` (a palavra já está aberta) e o fake não tem rota:
        # o que importa aqui é quantas foram aceitas, não o desfecho delas.
        await asyncio.gather(*tarefas, return_exceptions=True)

    assert len(eventos(caplog.records, "fila_cheia")) == 4
    assert len(tutor.chamadas) == 2


async def test_chats_diferentes_nao_dividem_a_fila(canal: FakeChannel) -> None:
    liberar = asyncio.Event()
    tutor = _TutorLento(liberar, asyncio.get_running_loop())
    router = _router(canal, tutor, max_fila_por_chat=1, max_processamentos=4)

    tarefas = [
        asyncio.create_task(router.processar("!add stall", CHAT_A, Autor(numero="5531999990001"))),
        asyncio.create_task(router.processar("!add stall", CHAT_B, Autor(numero="5531999990002"))),
    ]
    await asyncio.sleep(0.1)
    liberar.set()
    await asyncio.gather(*tarefas)

    assert len(tutor.chamadas) == 2


async def test_vagas_globais_limitam_chats_processando_ao_mesmo_tempo(canal: FakeChannel) -> None:
    liberar = asyncio.Event()
    tutor = _TutorLento(liberar, asyncio.get_running_loop())
    router = _router(canal, tutor, max_processamentos=2)

    tarefas = [
        asyncio.create_task(
            router.processar(
                "!add stall", f"1203630000000000{i:02d}@g.us", Autor(numero=f"55319999900{i:02d}")
            )
        )
        for i in range(6)
    ]
    await asyncio.sleep(0.2)
    pico_com_todos_esperando = tutor.pico
    liberar.set()
    await asyncio.gather(*tarefas)

    assert pico_com_todos_esperando == 2
    assert len(tutor.chamadas) == 6  # ninguém foi perdido: só esperou a vez


async def test_contador_da_fila_volta_a_zero_inclusive_com_erro(canal: FakeChannel) -> None:
    class _TutorQueFalha(FakeTutor):
        def explain(
            self, texto: str, nivel: NivelUsuario, palavras_do_aluno: Sequence[str] = ()
        ) -> Explanation:
            raise RuntimeError("boom")

    router = _router(canal, _TutorQueFalha(), max_fila_por_chat=1)
    autor = Autor(numero="5531999990001")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            await router.processar("!add stall", CHAT_A, autor)

    assert router._na_fila == {}
