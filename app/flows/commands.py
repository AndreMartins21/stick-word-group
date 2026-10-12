"""Comandos (seção 5.2): /help /list /info /listen /pending /practice /review /reviewsize /song
/reminders /profile /export /delete /level /cancel /status.

Os nomes são em inglês (M12). Os apelidos em PT-BR que a spec sempre teve (`/praticar`, `/lista`,
`/lembretes`...) continuam funcionando, mas nenhuma mensagem os divulga."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Protocol, get_args

from app import messages
from app.domain.choices import normalizar
from app.domain.lembretes import parse_lembretes, parse_tamanho_revisao, proximo_a_exibir
from app.domain.models import Entry, Estado, NivelUsuario, Profile, Sessao, slugify
from app.domain.srs import vencida
from app.flows import capture, pronuncia, review, song
from app.flows.base import Deps, bloq
from app.repo.base import Repository
from app.services.planilha import TIPO_XLSX, ResultadoExportacao

logger = logging.getLogger(__name__)

_NIVEIS: tuple[str, ...] = get_args(NivelUsuario)
TAMANHO_DA_PAGINA = 20

_AJUDA = {"ajuda", "help"}
_LISTA = {"lista", "list"}
_PENDENTES = {"pendentes", "pending"}
_PRATICAR = {"praticar", "practice"}
_EXPORTAR = {"exportar", "export"}
_APAGAR = {"apagar", "delete"}
_NIVEL = {"nivel", "level"}
_CANCELAR = {"cancelar", "cancel"}
_STATUS = {"status"}
_INFO = {"info"}
_OUVIR = {"listen", "ouvir"}
_PERFIL = {"profile", "perfil"}
_LEMBRETES = {"lembretes", "reminders"}
_REVISAR = {"revisar", "review"}
_TAMANHO_DE_REVISAO = {"reviewsize", "tamanhorevisao"}
_MUSICA = {"song", "musica", "music"}
_DESLIGAR = {"off", "desligar", "0"}
_AUTOMATICO = {"auto", "default", "padrao"}


class Exportador(Protocol):
    """Gera a planilha Excel do espaço `repo` (só o de quem pediu, ADR-0017) e devolve o resultado;
    `None` se não há nada a exportar. Síncrono, como o resto do acesso a Firestore/Storage."""

    def exportar(self, repo: Repository) -> ResultadoExportacao | None: ...


StatusDaSessao = Callable[[], Awaitable[str]]


async def executar(
    d: Deps,
    sessao: Sessao,
    perfil: Profile,
    texto: str,
    *,
    status_da_sessao: StatusDaSessao | None,
    exportador: Exportador | None,
) -> Sessao:
    partes = texto.strip()[1:].split(maxsplit=1)
    comando = normalizar(partes[0]) if partes else ""
    argumento = partes[1].strip() if len(partes) > 1 else ""
    conversa = d.conversa

    if comando in _AJUDA:
        await conversa.enviar(messages.AJUDA)
    elif comando in _LISTA:
        await listar(d, argumento)
    elif comando in _INFO:
        await _info(d, argumento)
    elif comando in _OUVIR:
        await _ouvir(d, argumento)
    elif comando in _PERFIL:
        await _perfil(d, perfil)
    elif comando in _PENDENTES:
        pendentes = await bloq(d.repo.listar_entradas, "nova")
        await conversa.enviar(
            messages.pendentes(pendentes) if pendentes else messages.SEM_PENDENTES
        )
    elif comando in _PRATICAR:
        return await praticar(d, sessao, perfil, argumento)
    elif comando in _EXPORTAR:
        await _exportar(d, exportador)
    elif comando in _APAGAR:
        return await apagar(d, sessao, argumento)
    elif comando in _NIVEL:
        await definir_nivel(d, perfil, argumento)
    elif comando in _CANCELAR:
        if Estado(sessao.estado) == Estado.REVIEWING:
            # M10: cancelar no meio de uma revisão fecha com o resumo, não o texto genérico.
            return await review.encerrar(d, sessao)
        if Estado(sessao.estado) == Estado.SONG_PRACTICE:
            # M13: igual ao 0 — resumo e oferta de salvar o que o aluno não pegou.
            return await song.encerrar(d, sessao)
        await conversa.enviar(messages.CANCELADO)
        return d.sessao_vazia()
    elif comando in _STATUS:
        await _status(d, status_da_sessao)
    elif comando in _LEMBRETES:
        await lembretes(d, perfil, argumento)
    elif comando in _REVISAR:
        return await revisar(d, sessao, perfil)
    elif comando in _TAMANHO_DE_REVISAO:
        await tamanho_de_revisao(d, perfil, argumento)
    elif comando in _MUSICA:
        if not argumento:
            await conversa.enviar(messages.SONG_USO)
            return sessao
        return await song.buscar(d, sessao, argumento)
    else:
        await conversa.enviar(messages.COMANDO_DESCONHECIDO)
    return sessao


def _achar_entrada(repo: Repository, palavra: str) -> Entry | None:
    """Acha por número (o da `/list`), slug ou palavra."""
    if palavra.isdigit():
        entradas = repo.listar_entradas()
        numero = int(palavra)
        return entradas[numero - 1] if 1 <= numero <= len(entradas) else None
    direta = repo.obter_entrada(slugify(palavra))
    if direta is not None:
        return direta
    alvo = normalizar(palavra)
    return next((e for e in repo.listar_entradas() if normalizar(e.palavra) == alvo), None)


async def listar(d: Deps, argumento: str) -> None:
    """`/list` mostra a página 1; `/list 2`, a página 2 (20 palavras por página)."""
    entradas = await bloq(d.repo.listar_entradas)
    if not entradas:
        await d.conversa.enviar(messages.sem_entradas(d.p))
        return
    paginas = -(-len(entradas) // TAMANHO_DA_PAGINA)
    if argumento and not argumento.isdigit():
        await d.conversa.enviar(messages.pagina_invalida(d.p))
        return
    numero = int(argumento) if argumento else 1
    if not 1 <= numero <= paginas:
        await d.conversa.enviar(messages.pagina_invalida(d.p))
        return
    # Das mais novas para as mais antigas; o número de cada palavra é fixo (1 = a mais antiga),
    # então `/info 7` e `/delete 7` continuam apontando para a mesma palavra quando entram novas.
    numeradas = list(reversed(list(enumerate(entradas, start=1))))
    inicio = (numero - 1) * TAMANHO_DA_PAGINA
    fatia = [(n, e) for n, e in numeradas[inicio : inicio + TAMANHO_DA_PAGINA]]
    await d.conversa.enviar(
        messages.lista(
            fatia,
            total=len(entradas),
            numero=numero,
            paginas=paginas,
            p=d.p,
            grupo=d.em_grupo,
            pt=d.pt,
        )
    )


async def _info(d: Deps, argumento: str) -> None:
    if not argumento:
        await d.conversa.enviar(messages.USO_DO_INFO)
        return
    entrada = await bloq(_achar_entrada, d.repo, argumento)
    if entrada is None:
        await d.conversa.enviar(messages.palavra_nao_encontrada(argumento))
        return
    entradas = await bloq(d.repo.listar_entradas)
    numero = next(i for i, e in enumerate(entradas, start=1) if e.slug == entrada.slug)
    frases = await bloq(d.repo.listar_frases, entrada.slug)
    await d.conversa.enviar(messages.info(entrada, numero, frases))


async def _ouvir(d: Deps, argumento: str) -> None:
    """`/listen N|palavra`: a pronúncia de uma palavra já salva (a da conversa aberta é a opção 1)."""
    if not argumento:
        await d.conversa.enviar(messages.USO_DO_LISTEN)
        return
    entrada = await bloq(_achar_entrada, d.repo, argumento)
    if entrada is None:
        await d.conversa.enviar(messages.palavra_nao_encontrada(argumento))
        return
    await pronuncia.ouvir(d, entrada)


async def _perfil(d: Deps, perfil: Profile) -> None:
    entradas = await bloq(d.repo.listar_entradas)
    praticadas = sum(1 for e in entradas if e.status == "praticada")
    para_revisar = sum(1 for e in entradas if vencida(e, d.agora()))
    await d.conversa.enviar(
        messages.perfil_do_aluno(
            perfil,
            total=len(entradas),
            praticadas=praticadas,
            para_revisar=para_revisar,
            proximo=proximo_a_exibir(perfil, d.agora(), d.fuso),
            agora=d.agora(),
        )
    )


async def praticar(d: Deps, sessao: Sessao, perfil: Profile, palavra: str) -> Sessao:
    if palavra:
        entrada = await bloq(_achar_entrada, d.repo, palavra)
        if entrada is None:
            await d.conversa.enviar(messages.palavra_nao_encontrada(palavra, d.p, grupo=d.em_grupo))
            return sessao
    else:
        pendentes = await bloq(d.repo.listar_entradas, "nova")
        if not pendentes:
            await d.conversa.enviar(messages.SEM_PENDENTES)
            return sessao
        entrada = pendentes[0]
    return await capture.explicar(d, perfil, entrada.palavra, entrada_existente=entrada)


async def _exportar(d: Deps, exportador: Exportador | None) -> None:
    if exportador is None:
        await d.conversa.enviar(messages.EXPORTACAO_INDISPONIVEL)
        return
    async with d.conversa.digitando():
        resultado = await bloq(exportador.exportar, d.repo)
    if resultado is None:
        await d.conversa.enviar(messages.SEM_EXPORTAVEIS)
        return
    try:
        await d.conversa.enviar_arquivo(
            resultado.nome,
            resultado.conteudo,
            TIPO_XLSX,
            messages.exportacao(resultado.quantidade),
        )
    except Exception:  # plano B: o WhatsApp recusou/demorou — manda o link do bucket
        logger.warning(
            "não consegui enviar a planilha pelo WhatsApp; mandando o link", exc_info=True
        )
        link = await bloq(resultado.gerar_link)
        await d.conversa.enviar(messages.exportacao_com_link(link, resultado.quantidade))


async def apagar(
    d: Deps,
    sessao: Sessao,
    palavra: str,
    *,
    pode_apagar: Callable[[Entry], Awaitable[bool]] | None = None,
) -> Sessao:
    """`/delete N|palavra` (no grupo, `!delete`, M32): o número é o da lista do espaço.
    `pode_apagar` (M54, ADR-0052): no grupo, quem decide se esta pessoa pode apagar esta entrada."""
    if not palavra:
        await d.conversa.enviar(
            messages.grupo_delete_uso(d.p) if d.em_grupo else messages.COMANDO_DESCONHECIDO
        )
        return sessao
    entrada = await bloq(_achar_entrada, d.repo, palavra)
    if entrada is None:
        await d.conversa.enviar(messages.palavra_nao_encontrada(palavra, d.p, grupo=d.em_grupo))
        return sessao
    if pode_apagar is not None and not await pode_apagar(entrada):
        await d.conversa.enviar(messages.so_quem_adicionou_apaga(d.p))
        return sessao
    await bloq(d.repo.apagar_entrada, entrada.slug)
    await d.conversa.enviar(messages.apagada(entrada.palavra))
    # Se era a palavra em andamento, a conversa não pode continuar apontando para o nada.
    return d.sessao_vazia() if sessao.entry_id == entrada.slug else sessao


async def definir_nivel(d: Deps, perfil: Profile, argumento: str) -> None:
    """`/level` no privado e `!level` no grupo (quem pode mudar é decidido por quem chama)."""
    if not argumento:
        await d.conversa.enviar(messages.nivel_atual(perfil.nivel, d.p))
        return
    escolhido = argumento.strip().upper()
    if escolhido not in _NIVEIS:
        await d.conversa.enviar(messages.nivel_invalido())
        return
    novo = perfil.model_copy(update={"nivel": escolhido})
    await bloq(d.repo.salvar_perfil, novo)
    await d.conversa.enviar(messages.nivel_alterado(novo.nivel))


async def _status(d: Deps, status_da_sessao: StatusDaSessao | None) -> None:
    try:
        sessao_waha = await status_da_sessao() if status_da_sessao else "unknown"
    except Exception:  # o /status existe justamente para funcionar quando algo está quebrado
        logger.warning("não consegui consultar a sessão do WAHA", exc_info=True)
        sessao_waha = "unavailable"
    entradas = await bloq(d.repo.listar_entradas)
    pendentes = sum(1 for e in entradas if e.status == "nova")
    await d.conversa.enviar(messages.status(sessao_waha, len(entradas), pendentes))


async def lembretes(d: Deps, perfil: Profile, argumento: str) -> None:
    """`/reminders` mostra o estado atual; `/reminders off` desliga; `/reminders 3` ou
    `/reminders 3 9h-22h` liga/muda (seção 5.7, M10). O último parâmetro (M24), quando dado, fixa
    o tamanho da fila de revisão; omitido, não mexe no que já estava (`/reviewsize` cuida só disso,
    sem precisar repetir a cada `/reminders`)."""
    if not argumento:
        proximo = proximo_a_exibir(perfil, d.agora(), d.fuso)
        await d.conversa.enviar(
            messages.lembretes_atuais(perfil, proximo, d.agora(), d.cmd_lembretes)
        )
        return
    if normalizar(argumento) in _DESLIGAR:
        if perfil.lembretes_por_dia != 0:
            desligado = perfil.model_copy(update={"lembretes_por_dia": 0, "proximo_lembrete": None})
            await bloq(d.repo.salvar_perfil, desligado)
        await d.conversa.enviar(messages.lembretes_desligados())
        return
    analisado = parse_lembretes(argumento)
    if analisado is None:
        await d.conversa.enviar(messages.lembretes_invalidos(d.cmd_lembretes))
        return
    quantidade, inicio, fim, tamanho_revisao = analisado
    atualizacoes: dict[str, object] = {
        "lembretes_por_dia": quantidade,
        "janela_inicio": inicio,
        "janela_fim": fim,
        "proximo_lembrete": None,  # o agendador recalcula no próximo tick
    }
    if tamanho_revisao is not None:
        atualizacoes["tamanho_revisao"] = tamanho_revisao
    novo = perfil.model_copy(update=atualizacoes)
    await bloq(d.repo.salvar_perfil, novo)
    proximo = proximo_a_exibir(novo, d.agora(), d.fuso)
    await d.conversa.enviar(messages.lembretes_alterados(novo, proximo, d.agora()))


async def tamanho_de_revisao(d: Deps, perfil: Profile, argumento: str) -> None:
    """`/reviewsize` mostra o tamanho atual da fila; `/reviewsize N` fixa um valor (1-20);
    `/reviewsize auto` volta ao dinâmico (`MIN(palavras do aluno, 7)`, seção 5.7, M24)."""
    if not argumento:
        entradas = await bloq(d.repo.listar_entradas)
        await d.conversa.enviar(messages.tamanho_de_revisao_atual(perfil, len(entradas)))
        return
    if normalizar(argumento) in _AUTOMATICO:
        if perfil.tamanho_revisao is not None:
            await bloq(d.repo.salvar_perfil, perfil.model_copy(update={"tamanho_revisao": None}))
        await d.conversa.enviar(messages.tamanho_de_revisao_automatico())
        return
    tamanho = parse_tamanho_revisao(argumento)
    if tamanho is None:
        await d.conversa.enviar(messages.tamanho_de_revisao_invalido())
        return
    await bloq(d.repo.salvar_perfil, perfil.model_copy(update={"tamanho_revisao": tamanho}))
    await d.conversa.enviar(messages.tamanho_de_revisao_alterado(tamanho))


async def revisar(d: Deps, sessao: Sessao, perfil: Profile) -> Sessao:
    """`/review` começa a sessão de revisão na hora, em vez de esperar o próximo lembrete."""
    entradas = await bloq(d.repo.listar_entradas)
    if not review.montar_fila(entradas, d.agora(), limite=review.limite(d, perfil, len(entradas))):
        await d.conversa.enviar(messages.SEM_NADA_PARA_REVISAR)
        return sessao
    return await review.iniciar(d, perfil)
