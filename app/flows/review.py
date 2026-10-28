"""Revisão espaçada (M10, seção 5.7, ADR-0011): monta a fila de palavras vencidas, faz um turno
por vez (pergunta → resposta → feedback + próxima) e fecha com o resumo. `montar_fila` é pura
(testável sem repo); `iniciar`/`responder`/`encerrar` fazem I/O, como os demais fluxos. Cada card
vem seguido da pronúncia automática do termo, sem a frase (M26, ADR-0027).

Em grupo (M35, ADR-0033) é a revisão diária: ninguém é marcado, qualquer um responde e recebe
feedback; a primeira resposta aceitável (qualidade != `de_novo`) avança; `skip` pula a palavra e
`skipall` encerra. Desde o M65 (ADR-0064), quem decide quando a palavra volta é a cobertura da turma
(`domain/memoria.py`), não a nota de quem acertou primeiro. Sem mensagem por 3 horas, a rodada fecha sozinha. Os ajudantes de
marcação (`alunos_elegiveis`, `marcar`) são do desafio semanal (`flows/semanal.py`, ADR-0034).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime

from app import messages
from app.channel.parser import numero_esta_na_lista
from app.domain.memoria import JANELA, Memoria, cobertura
from app.domain.models import Entry, Estado, Membro, Profile, Resposta, Sentence, Sessao
from app.domain.rodizio import Candidato, escolher
from app.domain.srs import reagendar, vencida
from app.flows.base import Deps, bloq
from app.logging_config import id_curto, registrar_evento
from app.repo.base import tipo_do_espaco

logger = logging.getLogger(__name__)

LIMITE_POR_SESSAO = 20


def montar_fila(
    entradas: Sequence[Entry], agora: datetime, limite: int = LIMITE_POR_SESSAO
) -> list[str]:
    """Vencidas primeiro (mais antiga primeiro), até `limite`. Sem vencidas suficientes, completa
    com as que vencem mais cedo. Sem nenhuma entrada, devolve a fila vazia (sem revisão)."""
    vencidas = sorted(
        (e for e in entradas if vencida(e, agora)), key=lambda e: e.proxima_revisao or e.criado_em
    )
    if len(vencidas) >= limite:
        return [e.slug for e in vencidas[:limite]]

    restantes = sorted(
        (e for e in entradas if not vencida(e, agora)),
        key=lambda e: e.proxima_revisao or e.criado_em,
    )
    completar = restantes[: limite - len(vencidas)]
    return [e.slug for e in (*vencidas, *completar)]


def limite(d: Deps, perfil: Profile) -> int:
    """Palavras por rodada (M24): um `tamanho_revisao` fixo (`!daily ... size N`) sobrepõe o
    padrão, `LIMITE_POR_SESSAO_GRUPO` (5)."""
    if perfil.tamanho_revisao is not None:
        return perfil.tamanho_revisao
    return d.grupo_cfg.limite


# --- quem é marcado (grupo) -------------------------------------------------------------------


def eh_o_bot(d: Deps, numero: str) -> bool:
    bot = d.grupo_cfg.numero_do_bot
    return bot is not None and numero_esta_na_lista(numero, [bot])


async def alunos_elegiveis(d: Deps, *, atualizar: bool) -> list[tuple[str, Membro]]:
    """Os alunos que podem ser marcados: quem está no grupo (o endpoint do WAHA, atualizado no
    início de cada rodada), sem o bot e sem professores. Sem a lista de participantes (o WAHA
    falhou), vale o cadastro de membros. Quem está no grupo e nunca escreveu com prefixo entra no
    cadastro como aluno."""
    cfg = d.grupo_cfg
    presentes: list[str] | None = None
    if atualizar and cfg.participantes is not None:
        try:
            numeros = await cfg.participantes(d.chat_id)
        except Exception:
            logger.warning("não consegui listar os participantes do grupo; uso o cadastro")
        else:
            # Uma lista vazia não é confiável (o próprio bot deveria estar nela): usa o cadastro.
            if numeros:
                presentes = [n for n in numeros if not eh_o_bot(d, n)]
                await bloq(cadastrar_novos, d, presentes)
    membros = await bloq(d.repo.listar_membros)
    staff = await bloq(lambda: {n for n, _ in membros if d.eh_staff(n)})
    return [
        (numero, membro)
        for numero, membro in membros
        if membro.papel == "aluno"
        and numero not in staff
        and not eh_o_bot(d, numero)
        and (presentes is None or numero_esta_na_lista(numero, presentes))
    ]


def cadastrar_novos(d: Deps, presentes: Sequence[str]) -> None:
    conhecidos = [numero for numero, _ in d.repo.listar_membros()]
    for numero in presentes:
        if not numero_esta_na_lista(numero, conhecidos):
            d.repo.salvar_membro(numero, Membro(entrou_em=d.agora()))


async def marcar(
    d: Deps, alunos: Sequence[tuple[str, Membro]], *, excluir: str | None
) -> str | None:
    """Escolhe quem marcar pelo rodízio e anota a marcação. `None` se não há aluno."""
    candidatos = [Candidato(numero, membro.marcado_em) for numero, membro in alunos]
    escolhido = escolher(candidatos, excluir=excluir, sortear=d.grupo_cfg.sortear)
    if escolhido is None:
        return None
    membro = next(m for n, m in alunos if n == escolhido)
    await bloq(d.repo.salvar_membro, escolhido, membro.model_copy(update={"marcado_em": d.agora()}))
    return escolhido


async def memoria_da_turma(d: Deps) -> Memoria:
    """A memória por aluno (M65), das respostas da diária dentro da `JANELA`."""
    return Memoria.de(await bloq(d.repo.listar_respostas, d.agora() - JANELA))


# --- a rodada ---------------------------------------------------------------------------------


async def iniciar(d: Deps, perfil: Profile) -> Sessao:
    """Começa a rodada (o `/review`, o `!review` ou o agendador)."""
    entradas = await bloq(d.repo.listar_entradas)
    fila = montar_fila(entradas, d.agora(), limite=limite(d, perfil))
    if not fila:
        return d.sessao_vazia()
    d.conversa.nova_iniciativa()  # o bot está iniciando, não respondendo — reseta o limite de 3
    total = len(fila)
    return await _mostrar_proxima(d, messages.hora_da_pratica(total), fila, [], [], total)


def mesma_pessoa(a: str | None, b: str | None) -> bool:
    return a is not None and b is not None and numero_esta_na_lista(a, [b])


async def responder(d: Deps, sessao: Sessao, perfil: Profile, texto: str) -> Sessao:
    entrada = (
        await bloq(d.repo.obter_entrada, sessao.revisao_atual) if sessao.revisao_atual else None
    )
    if entrada is None:  # apagada no meio da revisão (ex.: /apagar): pula sem feedback
        return await _mostrar_proxima(
            d,
            "",
            sessao.revisao_fila,
            sessao.revisao_feitas,
            sessao.revisao_lapsos,
            sessao.revisao_total,
            puladas=sessao.revisao_puladas,
        )

    async with d.conversa.digitando():
        revisao = await bloq(d.tutor.review, entrada.palavra, entrada.sentido, texto, perfil.nivel)

    agora = d.agora()
    registrar_evento(
        logger,
        "revisao_resposta",
        espaco=id_curto(d.chat_id),
        tipo_espaco=tipo_do_espaco(d.chat_id),
        qualidade=revisao.qualidade,
        marcado=False,
    )
    if revisao.tipo == "frase":
        await bloq(
            d.repo.adicionar_frase,
            entrada.slug,
            Sentence(
                texto=texto,
                autor="usuario",
                autor_id=d.autor_id,
                versao_natural=revisao.correcao or None,
                criado_em=agora,
            ),
        )
    if d.autor_id:
        await bloq(
            d.repo.registrar_resposta,
            Resposta(
                entry=entrada.slug,
                autor_id=d.autor_id,
                marcado=False,
                qualidade=revisao.qualidade,
                tipo="diaria",
                criado_em=agora,
            ),
        )
    nome = d.autor.nome if d.autor else None
    if revisao.qualidade == "de_novo":
        # Ainda não está certo: feedback, e a palavra segue aberta para outro tentar (ou `skip`).
        await d.conversa.enviar(messages.diaria_tente_de_novo(revisao, nome, d.p))
        return sessao

    alunos = [numero for numero, _ in await alunos_elegiveis(d, atualizar=False)]
    memoria = await memoria_da_turma(d)
    agendamento = reagendar(entrada, cobertura(alunos, entrada.slug, memoria, agora), agora)
    await bloq(
        d.repo.salvar_entrada,
        entrada.model_copy(
            update={
                "repeticoes": agendamento.repeticoes,
                "intervalo_dias": agendamento.intervalo_dias,
                "proxima_revisao": agendamento.proxima_revisao,
                "lapsos": agendamento.lapsos,
                "revisada_em": agora,
                "atualizado_em": agora,
            }
        ),
    )

    feitas = [*sessao.revisao_feitas, entrada.palavra]
    feedback = messages.feedback_da_diaria(revisao, nome)
    return await _mostrar_proxima(
        d,
        feedback,
        list(sessao.revisao_fila),
        feitas,
        list(sessao.revisao_lapsos),
        sessao.revisao_total,
        puladas=sessao.revisao_puladas,
    )


async def pular(d: Deps, sessao: Sessao) -> Sessao:
    """`skip` na revisão do grupo (M35): passa para a próxima palavra sem mudar a nota — ela
    continua vencida e volta numa revisão futura."""
    entrada = (
        await bloq(d.repo.obter_entrada, sessao.revisao_atual) if sessao.revisao_atual else None
    )
    puladas = list(sessao.revisao_puladas)
    aviso = ""
    if entrada is not None:
        puladas.append(entrada.palavra)
        aviso = messages.palavra_pulada(entrada.palavra)
    return await _mostrar_proxima(
        d,
        aviso,
        sessao.revisao_fila,
        sessao.revisao_feitas,
        sessao.revisao_lapsos,
        sessao.revisao_total,
        puladas=puladas,
    )


def _registrar_conclusao(
    d: Deps, feitas: Sequence[str], lapsos: Sequence[str], total: int, motivo: str
) -> None:
    registrar_evento(
        logger,
        "revisao_concluida",
        espaco=id_curto(d.chat_id),
        tipo_espaco=tipo_do_espaco(d.chat_id),
        n=len(feitas),
        total=total,
        lapsos=len(lapsos),
        motivo=motivo,
    )


async def encerrar(d: Deps, sessao: Sessao) -> Sessao:
    _registrar_conclusao(
        d, sessao.revisao_feitas, sessao.revisao_lapsos, sessao.revisao_total, "manual"
    )
    await d.conversa.enviar(
        messages.revisao_encerrada(
            sessao.revisao_feitas, sessao.revisao_lapsos, puladas=sessao.revisao_puladas
        )
    )
    return d.sessao_vazia()


async def fechar_por_inatividade(d: Deps, sessao: Sessao) -> Sessao:
    """O grupo ficou 3 horas sem mensagem na rodada (chamado pelo agendador): fecha com o resumo."""
    _registrar_conclusao(
        d, sessao.revisao_feitas, sessao.revisao_lapsos, sessao.revisao_total, "timeout"
    )
    d.conversa.nova_iniciativa()
    await d.conversa.enviar(
        messages.revisao_inativa(
            sessao.revisao_feitas, sessao.revisao_lapsos, puladas=sessao.revisao_puladas
        )
    )
    return d.sessao_vazia()


async def _mostrar_proxima(
    d: Deps,
    feedback: str,
    fila: list[str],
    feitas: list[str],
    lapsos: list[str],
    total: int,
    *,
    puladas: Sequence[str] = (),
) -> Sessao:
    """Mostra a próxima palavra da fila (pulando entradas apagadas no meio da revisão) numa
    mensagem só com o feedback, ou encerra com o resumo se a fila acabou."""
    restante = list(fila)
    while restante:
        slug = restante.pop(0)
        entrada = await bloq(d.repo.obter_entrada, slug)
        if entrada is None:
            continue
        indice = min(len(feitas) + len(puladas) + 1, total)
        card = messages.card_de_revisao(indice, total, entrada.palavra)
        await d.conversa.enviar(f"{feedback}\n\n{card}" if feedback else card)
        return Sessao(
            estado=Estado.REVIEWING,
            revisao_fila=restante,
            revisao_atual=slug,
            revisao_feitas=feitas,
            revisao_lapsos=lapsos,
            revisao_total=total,
            revisao_puladas=list(puladas),
            marcacao_expira_em=d.agora() + d.grupo_cfg.timeout,
            atualizado_em=d.agora(),
        )

    _registrar_conclusao(d, feitas, lapsos, total, "fila_vazia")
    resumo = messages.revisao_encerrada(feitas, lapsos, puladas=puladas)
    await d.conversa.enviar(f"{feedback}\n\n{resumo}" if feedback else resumo)
    return d.sessao_vazia()
