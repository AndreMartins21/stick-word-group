"""Os comandos do grupo que leem ou mexem no caderno da turma (seção 5.2b): `!list`, `!practice`,
`!review`, `!delete` e `!level`. Quem decide se o comando vale (e quem pode usá-lo) é
`app/flows/grupo.py`; aqui só a execução."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import get_args

from app import messages
from app.domain.choices import normalizar
from app.domain.models import Entry, NivelUsuario, Profile, Sessao, slugify
from app.flows import capture, review
from app.flows.base import Deps, bloq
from app.repo.base import Repository

_NIVEIS: tuple[str, ...] = get_args(NivelUsuario)
TAMANHO_DA_PAGINA = 20


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
        await d.conversa.enviar(messages.sem_entradas())
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
            pt=d.pt,
        )
    )


async def praticar(d: Deps, sessao: Sessao, perfil: Profile, palavra: str) -> Sessao:
    if palavra:
        entrada = await bloq(_achar_entrada, d.repo, palavra)
        if entrada is None:
            await d.conversa.enviar(messages.palavra_nao_encontrada(palavra, d.p))
            return sessao
    else:
        pendentes = await bloq(d.repo.listar_entradas, "nova")
        if not pendentes:
            await d.conversa.enviar(messages.SEM_PENDENTES)
            return sessao
        entrada = pendentes[0]
    return await capture.explicar(d, perfil, entrada.palavra, entrada_existente=entrada)


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
        await d.conversa.enviar(messages.grupo_delete_uso(d.p))
        return sessao
    entrada = await bloq(_achar_entrada, d.repo, palavra)
    if entrada is None:
        await d.conversa.enviar(messages.palavra_nao_encontrada(palavra, d.p))
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


async def revisar(d: Deps, sessao: Sessao, perfil: Profile) -> Sessao:
    """`/review` começa a sessão de revisão na hora, em vez de esperar o próximo lembrete."""
    entradas = await bloq(d.repo.listar_entradas)
    if not review.montar_fila(entradas, d.agora(), limite=review.limite(d, perfil)):
        await d.conversa.enviar(messages.SEM_NADA_PARA_REVISAR)
        return sessao
    return await review.iniciar(d, perfil)
