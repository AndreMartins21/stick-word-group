"""M14 (ADR-0017): duas turmas, isolamento total. Cada grupo é um espaço: palavras, sessão e
`!list` de um nunca aparecem no outro, e as travas e o limite de "3 mensagens seguidas" são por
espaço."""

from __future__ import annotations

import asyncio

from app.domain.models import Estado
from app.services.fake_llm import FakeTutor
from tests.helpers import ANA, GRUPO, Montagem, expansoes, explicacao_stall, montar

CHAT = GRUPO
CHAT_B = "120363000000000002@g.us"


def _explicacao(palavra: str):  # type: ignore[no-untyped-def]
    return explicacao_stall().model_copy(update={"palavra": palavra})


async def _diz(m: Montagem, chat: str, texto: str) -> list[str]:
    antes = len(m.channel.textos_enviados)
    await m.router.processar(texto, chat, ANA)
    return [t for c, t in m.channel.textos_enviados[antes:] if c == chat]


def _dois_alunos(**kwargs: object) -> Montagem:
    tutor = FakeTutor(
        explicacoes=[_explicacao("stall"), _explicacao("hedge")],
        expansoes=[expansoes(), expansoes()],
    )
    return montar(tutor=tutor, **kwargs)  # type: ignore[arg-type]


async def test_a_sessao_de_um_aluno_nao_aparece_no_outro() -> None:
    m = _dois_alunos()

    await _diz(m, CHAT, "!add stall")

    assert m.banco.do_espaco(CHAT).obter_sessao().estado == Estado.AWAIT_ACTION
    assert m.banco.do_espaco(CHAT_B).obter_sessao().estado == Estado.IDLE


async def test_palavras_e_list_sao_de_cada_aluno() -> None:
    m = _dois_alunos()
    await _diz(m, CHAT, "!add stall")
    await _diz(m, CHAT, "!4")  # salva
    await _diz(m, CHAT_B, "!add hedge")
    await _diz(m, CHAT_B, "!4")

    lista_a = "\n".join(await _diz(m, CHAT, "/list"))
    lista_b = "\n".join(await _diz(m, CHAT_B, "/list"))

    assert "stall" in lista_a
    assert "hedge" not in lista_a
    assert "hedge" in lista_b
    assert "stall" not in lista_b
    assert [e.slug for e in m.banco.do_espaco(CHAT).listar_entradas()] == ["stall"]
    assert [e.slug for e in m.banco.do_espaco(CHAT_B).listar_entradas()] == ["hedge"]


async def test_aluno_sem_palavras_nao_ve_as_do_outro() -> None:
    m = _dois_alunos()
    await _diz(m, CHAT, "!add stall")
    await _diz(m, CHAT, "!4")

    resposta = "\n".join(await _diz(m, CHAT_B, "/list"))

    assert "*stall*" not in resposta
    assert "doesn't have any saved words" in resposta


async def test_o_mesmo_slug_pode_existir_nos_dois_espacos() -> None:
    m = montar(
        tutor=FakeTutor(
            explicacoes=[_explicacao("stall"), _explicacao("stall")],
            expansoes=[expansoes(), expansoes()],
        )
    )
    await _diz(m, CHAT, "!add stall")
    await _diz(m, CHAT, "!4")

    await _diz(m, CHAT_B, "!add stall")
    resposta = await _diz(m, CHAT_B, "!4")

    assert resposta  # o B salvou sem esbarrar na palavra do A
    assert len(m.banco.do_espaco(CHAT_B).listar_entradas()) == 1


async def test_o_limite_de_tres_mensagens_seguidas_e_por_espaco() -> None:
    m = montar()
    for _ in range(3):
        await m.router.conversa_do(CHAT).enviar("oi")
    antes = len(m.channel.textos_enviados)

    await m.router.conversa_do(CHAT).enviar("quarta: descartada")
    await m.router.conversa_do(CHAT_B).enviar("primeira do outro aluno")

    novos = m.channel.textos_enviados[antes:]
    assert novos == [(CHAT_B, "primeira do outro aluno")]


async def test_chats_diferentes_andam_em_paralelo_e_o_mesmo_chat_um_por_vez() -> None:
    m = montar()
    liberar = asyncio.Event()
    entrou: list[str] = []

    async def presa(chat: str) -> None:
        async with m.router._trava(chat):
            entrou.append(chat)
            await liberar.wait()

    a1 = asyncio.create_task(presa(CHAT))
    b1 = asyncio.create_task(presa(CHAT_B))
    a2 = asyncio.create_task(presa(CHAT))
    await asyncio.sleep(0.01)

    # A e B entram juntos; a segunda tarefa do A espera a primeira terminar.
    assert sorted(entrou) == sorted([CHAT, CHAT_B])

    liberar.set()
    await asyncio.gather(a1, b1, a2)
    assert entrou.count(CHAT) == 2
