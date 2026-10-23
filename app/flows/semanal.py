"""Desafio semanal do grupo (M36, ADR-0034): o bot cria perguntas no nível da turma com palavras do
vocabulário do grupo e **marca um aluno** (rodízio, como no ADR-0020) por pergunta. Qualquer um pode
tentar e recebe feedback, mas a pergunta só avança quando a pessoa marcada responde (ou alguém usa
`skip`). Menu: `1` explica a pergunta (PT primeiro em turma iniciante), `2` a lê em voz alta, `3` pula.
Não mexe no SM-2: é conversa, não revisão de cartão. A rodada fecha sozinha após 3 h sem mensagem."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta

from app import messages
from app.domain.agenda_grupo import MAX_PERGUNTAS
from app.domain.models import Entry, Estado, PerguntaSemanal, Profile, Resposta, Sessao, slugify
from app.flows import review
from app.flows.base import Deps, bloq

logger = logging.getLogger(__name__)

MAX_PALAVRAS_NO_VOCABULARIO = 15
_RECENTE = timedelta(days=7)


def escolher_vocabulario(
    entradas: Sequence[Entry], agora: datetime, limite: int = MAX_PALAVRAS_NO_VOCABULARIO
) -> list[tuple[str, str]]:
    """As palavras que a IA pode usar: as criadas ou revisadas nos últimos 7 dias primeiro (mais
    recentes antes), completando com as que vencem mais cedo. `(palavra, definição)`."""

    def ultima_atividade(e: Entry) -> datetime:
        return max(e.criado_em, e.revisada_em or e.criado_em)

    recentes = sorted(
        (e for e in entradas if agora - ultima_atividade(e) <= _RECENTE),
        key=ultima_atividade,
        reverse=True,
    )
    resto = sorted(
        (e for e in entradas if agora - ultima_atividade(e) > _RECENTE),
        key=lambda e: e.proxima_revisao or e.criado_em,
    )
    return [(e.palavra, e.sentido.definicao) for e in (*recentes, *resto)[:limite]]


def quantidade_de_perguntas(perfil: Profile, alunos: int) -> int:
    """`!weekly size N` fixa; sem isso, uma pergunta por aluno elegível (no máximo 10)."""
    return min(perfil.semanal_tamanho or alunos, MAX_PERGUNTAS)


async def iniciar(d: Deps, perfil: Profile, *, avisar: bool = False) -> Sessao:
    """Começa o desafio (agendador ou `!weekly now`). `avisar`: sem palavras ou sem aluno para
    marcar, diz por que não começou; o agendado (`avisar=False`) fica em silêncio."""
    entradas = await bloq(d.repo.listar_entradas)
    if not entradas:
        if avisar:
            await d.conversa.enviar(messages.semanal_sem_palavras())
        return d.sessao_vazia()
    alunos = await review.alunos_elegiveis(d, atualizar=True)
    if not alunos:
        if avisar:
            await d.conversa.enviar(messages.grupo_sem_aluno(d.p))
        return d.sessao_vazia()

    n = quantidade_de_perguntas(perfil, len(alunos))
    vocabulario = escolher_vocabulario(entradas, d.agora())
    async with d.conversa.digitando():
        perguntas = await bloq(d.tutor.weekly_questions, vocabulario, perfil.nivel, n)

    d.conversa.nova_iniciativa()  # o bot está iniciando, não respondendo — reseta o limite de 3
    await d.conversa.enviar(messages.semanal_abertura(len(perguntas)))
    return await _apresentar(d, perguntas, 0, 0, 0, anterior=None)


async def _apresentar(
    d: Deps,
    perguntas: list[PerguntaSemanal],
    indice: int,
    respondidas: int,
    puladas: int,
    *,
    anterior: str | None,
) -> Sessao:
    """Marca o próximo aluno do rodízio e manda a pergunta, começando pela menção."""
    alunos = await review.alunos_elegiveis(d, atualizar=False)
    marcado = await review.marcar(d, alunos, excluir=anterior)
    if marcado is None:  # todos saíram do grupo no meio da rodada
        await d.conversa.enviar(messages.semanal_encerrada(respondidas, puladas, len(perguntas)))
        return d.sessao_vazia()
    texto = messages.pergunta_semanal(
        indice + 1, len(perguntas), marcado, perguntas[indice].pergunta
    )
    await d.conversa.enviar(texto, mentions=[marcado])
    return Sessao(
        estado=Estado.WEEKLY_QUIZ,
        semanal_perguntas=perguntas,
        semanal_indice=indice,
        semanal_respondidas=respondidas,
        semanal_puladas=puladas,
        marcado_id=marcado,
        marcacao_expira_em=d.agora() + d.grupo_cfg.timeout,
        atualizado_em=d.agora(),
    )


async def _avancar(d: Deps, sessao: Sessao, respondidas: int, puladas: int) -> Sessao:
    proximo = sessao.semanal_indice + 1
    if proximo >= len(sessao.semanal_perguntas):
        await d.conversa.enviar(
            messages.semanal_encerrada(respondidas, puladas, len(sessao.semanal_perguntas))
        )
        return d.sessao_vazia()
    return await _apresentar(
        d, sessao.semanal_perguntas, proximo, respondidas, puladas, anterior=sessao.marcado_id
    )


def _atual(sessao: Sessao) -> PerguntaSemanal:
    return sessao.semanal_perguntas[sessao.semanal_indice]


async def responder(d: Deps, sessao: Sessao, perfil: Profile, texto: str) -> Sessao:
    pergunta = _atual(sessao)
    async with d.conversa.digitando():
        avaliacao = await bloq(
            d.tutor.weekly_answer,
            messages.sem_marcas(pergunta.pergunta),
            pergunta.palavras,
            texto,
            perfil.nivel,
        )
    marcado = sessao.marcado_id
    marcada = marcado is None or review.mesma_pessoa(d.autor_id, marcado)
    if d.autor_id:
        await bloq(
            d.repo.registrar_resposta,
            Resposta(
                entry=slugify(pergunta.palavras[0]),
                autor_id=d.autor_id,
                marcado=marcada,
                qualidade=avaliacao.qualidade,
                tipo="semanal",
                criado_em=d.agora(),
            ),
        )
    nome = d.autor.nome if d.autor else None
    if not marcada and marcado is not None:
        # Feedback, mas a pergunta não avança por quem não foi marcado.
        await d.conversa.enviar(messages.feedback_semanal_de_outro(avaliacao, nome, marcado))
        return sessao
    await d.conversa.enviar(messages.feedback_semanal(avaliacao, nome))
    return await _avancar(d, sessao, sessao.semanal_respondidas + 1, sessao.semanal_puladas)


async def pular(d: Deps, sessao: Sessao) -> Sessao:
    """`3`/`skip`: qualquer participante pula a pergunta; o próximo aluno é marcado."""
    return await _avancar(d, sessao, sessao.semanal_respondidas, sessao.semanal_puladas + 1)


async def explicar(d: Deps, sessao: Sessao) -> Sessao:
    pergunta = _atual(sessao)
    await d.conversa.enviar(
        messages.explicacao_da_pergunta(pergunta.explicacao_en, pergunta.explicacao_pt, pt=d.pt)
    )
    return sessao


async def ouvir(d: Deps, sessao: Sessao) -> Sessao:
    """`2`: lê a pergunta em voz alta (mesmo cache de áudio da pronúncia). Pedido explícito: sem
    serviço de áudio ou com falha, avisa."""
    if d.audio is None:
        await d.conversa.enviar(messages.ERRO_AUDIO)
        return sessao
    try:
        async with d.conversa.digitando():
            audio = await bloq(d.audio.obter, messages.sem_marcas(_atual(sessao).pergunta))
        await d.conversa.enviar_voz(audio.conteudo)
    except Exception:
        logger.warning("não consegui mandar o áudio da pergunta", exc_info=True)
        await d.conversa.enviar(messages.ERRO_AUDIO)
    return sessao


async def encerrar(d: Deps, sessao: Sessao) -> Sessao:
    await d.conversa.enviar(
        messages.semanal_encerrada(
            sessao.semanal_respondidas,
            sessao.semanal_puladas,
            len(sessao.semanal_perguntas),
        )
    )
    return d.sessao_vazia()


async def fechar_por_inatividade(d: Deps, sessao: Sessao) -> Sessao:
    d.conversa.nova_iniciativa()
    await d.conversa.enviar(
        messages.semanal_inativa(
            sessao.semanal_respondidas,
            sessao.semanal_puladas,
            len(sessao.semanal_perguntas),
        )
    )
    return d.sessao_vazia()
