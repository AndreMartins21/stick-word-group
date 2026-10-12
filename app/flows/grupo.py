"""O grupo (M16, ADR-0019; marcação no M37, ADR-0035; citação no M38, ADR-0036): o bot só reage a
duas coisas, e o resto é conversa entre pessoas, que ele não lê nem grava:

- **Marcação** (`@bot texto`, ou responder/citar uma mensagem dele): é a conversa com o bot. O texto vai para a mesma máquina de estados do
  privado (`conversar`): dentro de uma atividade é a resposta (`@bot 2`, `@bot a frase`); fora dela
  é uma palavra nova ou um pedido, como no privado. Sem comando.
- **Comandos** com `!` ou `/` (um conjunto FECHADO): `add`, `delete`, `list`, `practice`, `review`,
  `daily`, `weekly`, `reminder`, `group`, `level`, `help`, mais `teacher`/`student` (escondidos do
  `help`). Também valem dentro de uma atividade (`!1`, `!skip`, `/skipall`...).
- **Fora de atividade**, um comando desconhecido recebe a ajuda do grupo, sem chamar a IA.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable

from app import messages
from app.channel.parser import numero_esta_na_lista
from app.domain.agenda_grupo import (
    JITTER_MINUTOS,
    diaria_a_exibir,
    jitter_do_espaco,
    parse_diaria,
    parse_semanal,
    semanal_a_exibir,
)
from app.domain.choices import normalizar
from app.domain.models import Entry, Estado, Membro, Papel, Profile, Sessao
from app.domain.srs import vencida
from app.flows import capture, commands, practice, review, semanal
from app.flows.base import Autor, Deps, bloq

logger = logging.getLogger(__name__)

# Fecha o conjunto: nada além disto é comando no grupo.
COMANDOS = {
    "add",
    "list",
    "practice",
    "review",
    "daily",
    "weekly",
    "reminder",
    "reminders",
    "group",
    "help",
    "delete",
    "level",
}
_PAPEIS = {"teacher": "professor", "student": "aluno"}

Conversar = Callable[[Deps, Sessao, Profile, str], Awaitable[Sessao]]


_PREFIXOS_ALEM_DO_CONFIGURADO = ("/",)  # M37: no grupo valem `!` (configurável) e `/`
_MARCACAO = re.compile(r"@(\d{5,})")
_MARCA_LITERAL = re.compile(
    r"(?<![\w@])@bot\b", re.IGNORECASE
)  # `@bot` digitado, sem escolher o contato


def sem_prefixo(texto: str, prefixo: str) -> str | None:
    """O texto sem o prefixo, ou `None` se a mensagem é conversa: não começa com `!` (o prefixo
    configurado) nem com `/`, ou não tem letra/número logo depois (`!!!`, `! `, `/` sozinho)."""
    limpo = texto.strip()
    for candidato in (prefixo, *_PREFIXOS_ALEM_DO_CONFIGURADO):
        if limpo.startswith(candidato):
            resto = limpo[len(candidato) :]
            return resto.strip() if resto[:1].isalnum() else None
    return None


def numeros_marcados_no_texto(texto: str) -> list[str]:
    """Os dígitos de cada `@123456...` escrito no texto (como o WhatsApp mostra uma marcação)."""
    return _MARCACAO.findall(texto)


def marca_literal_do_bot(texto: str) -> bool:
    """`@bot` escrito no texto (plano B de quem digita em vez de escolher o contato)."""
    return _MARCA_LITERAL.search(texto) is not None


def sem_marcacao(texto: str, ids: set[str]) -> str:
    """O texto sem as marcações cujos dígitos estão em `ids` (as do próprio bot, número ou LID) e
    sem o `@bot` digitado. Marcações de outras pessoas ficam: fazem parte do que foi dito."""
    sobra = _MARCACAO.sub(lambda m: "" if m.group(1) in ids else m.group(0), texto)
    return " ".join(_MARCA_LITERAL.sub("", sobra).split())


def _comando(texto: str) -> tuple[str, str]:
    partes = texto.split(maxsplit=1)
    return (normalizar(partes[0]) if partes else ""), (partes[1].strip() if len(partes) > 1 else "")


async def tratar(
    d: Deps,
    sessao: Sessao,
    perfil: Profile,
    texto: str,
    *,
    autor: Autor,
    conversar: Conversar,
    eh_dono: Callable[[str], bool],
    eh_admin: Callable[[str], bool] | None = None,
    marcado: bool = False,
) -> Sessao:
    """`texto` já vem sem o prefixo. `marcado`: a mensagem marcou o bot e não é um comando (M37),
    então `texto` é conversa com o bot. Devolve a nova sessão."""
    await bloq(registrar_membro, d, autor)
    estado = Estado(sessao.estado)
    comando, argumento = _comando(texto)
    if marcado and argumento:
        comando = ""  # uma frase marcando o bot é conversa, nunca um comando com argumento

    if marcado and (not texto or comando == "help"):  # só marcou, ou pediu ajuda
        await d.conversa.enviar(messages.ajuda_do_grupo(d.p))
        return sessao

    if marcado and estado not in (Estado.WEEKLY_QUIZ, Estado.REVIEWING):
        # Marcou o bot, sem comando: a mesma conversa do privado (IDLE = palavra nova,
        # AWAIT_ACTION = menu ou frase). Dentro do desafio e da revisão a marcação cai nos ramos
        # abaixo, que já tratam `1`/`2`/`3`/`skip`/`stop` e o resto como resposta.
        return await conversar(d, sessao, perfil, texto)

    if comando in _PAPEIS and not marcado:
        return await _papel(d, sessao, autor, comando, argumento, eh_dono)

    if estado == Estado.WEEKLY_QUIZ:
        # No desafio semanal (M36) `1`/`2`/`3`/`skip`/`skipall` são do menu (máquina de estados);
        # o resto é a resposta. Só sair e pedir ajuda escapam disso.
        if comando == "stop":
            return await conversar(d, sessao, perfil, "0")
        if comando == "help":
            await d.conversa.enviar(messages.ajuda_do_grupo(d.p))
            return sessao
        return await conversar(d, sessao, perfil, texto)

    if estado == Estado.REVIEWING:
        # Na revisão o texto é a resposta; só sair e pedir ajuda escapam disso.
        if comando == "stop":
            return await conversar(d, sessao, perfil, "0")
        if comando == "help":
            await d.conversa.enviar(messages.ajuda_do_grupo(d.p))
            return sessao
        if comando == "skip" and not argumento:  # M35: pula a palavra, não encerra a rodada
            return await review.pular(d, sessao)
        if comando in {"skip all", "skipall"}:
            return await conversar(d, sessao, perfil, "0")
        return await conversar(d, sessao, perfil, texto)

    if comando == "level":
        await _nivel(d, perfil, autor, argumento, eh_dono)
        return sessao

    if comando == "daily":
        await _diaria(d, perfil, autor, argumento, eh_admin or eh_dono)
        return sessao

    if comando == "weekly":
        return await _semanal(d, sessao, perfil, autor, argumento, eh_admin or eh_dono)

    if comando in COMANDOS:
        return await _executar(
            d, sessao, perfil, comando, argumento, autor, eh_admin or eh_dono, eh_dono
        )

    if estado == Estado.AWAIT_ACTION:
        return await conversar(d, sessao, perfil, texto)

    await d.conversa.enviar(messages.ajuda_do_grupo(d.p))  # sem atividade: nada de IA
    return sessao


async def _executar(
    d: Deps,
    sessao: Sessao,
    perfil: Profile,
    comando: str,
    argumento: str,
    autor: Autor,
    eh_admin: Callable[[str], bool],
    eh_dono: Callable[[str], bool],
) -> Sessao:
    if comando == "help":
        await d.conversa.enviar(messages.ajuda_do_grupo(d.p))
    elif comando == "list":
        await commands.listar(d, argumento)
    elif comando == "practice":
        return await commands.praticar(d, sessao, perfil, argumento)
    elif comando == "review":
        return await commands.revisar(d, sessao, perfil)
    elif comando in {"reminder", "reminders"}:  # M35: apelido antigo da revisão diária
        await d.conversa.enviar(messages.lembrete_virou_daily(d.p))
    elif comando == "group":
        await _perfil_do_grupo(d, perfil)
    elif comando == "add":
        return await _adicionar(d, sessao, perfil, argumento)
    elif comando == "delete":
        return await commands.apagar(
            d, sessao, argumento, pode_apagar=_pode_apagar(autor, eh_admin, eh_dono)
        )
    return sessao


def _pode_apagar(
    autor: Autor, eh_admin: Callable[[str], bool], eh_dono: Callable[[str], bool]
) -> Callable[[Entry], Awaitable[bool]]:
    """M54 (ADR-0052): `!delete` é de quem adicionou a palavra, de admin do bot ou do dono. Entradas
    sem autor (anteriores ao M28) só os admins apagam."""

    async def permitido(entrada: Entry) -> bool:
        if review.mesma_pessoa(entrada.autor_id, autor.numero):
            return True
        return bool(await bloq(eh_admin, autor.numero) or await bloq(eh_dono, autor.numero))

    return permitido


async def _adicionar(d: Deps, sessao: Sessao, perfil: Profile, palavra: str) -> Sessao:
    """`!add` é a ÚNICA forma de trazer uma palavra nova para o grupo (aceita contexto:
    `!add stall | the talks stalled`). Com outra palavra aberta, salva a anterior antes, como o
    privado faz com uma palavra nova."""
    if not palavra:
        await d.conversa.enviar(messages.grupo_add_uso(d.p))
        return sessao
    if Estado(sessao.estado) == Estado.AWAIT_ACTION and sessao.entry_id:
        if await capture.eh_a_palavra_aberta(d, sessao, palavra) and "|" in palavra:
            return await capture.trocar_sentido(d, sessao, perfil, palavra)  # M31: outro sentido
        await practice.concluir(d, sessao, perfil)
    return await capture.explicar(d, perfil, palavra)


# --- membros e papéis -------------------------------------------------------------------------


def registrar_membro(d: Deps, autor: Autor) -> Membro:
    """Quem manda a primeira mensagem com prefixo entra como aluno; o nome do WhatsApp, quando
    vem, atualiza o cadastro (nunca o telefone)."""
    membro = d.repo.obter_membro(autor.numero)
    if membro is None:
        membro = Membro(nome=autor.nome, entrou_em=d.agora())
        d.repo.salvar_membro(autor.numero, membro)
    elif autor.nome and membro.nome != autor.nome:
        membro = membro.model_copy(update={"nome": autor.nome})
        d.repo.salvar_membro(autor.numero, membro)
    return membro


def _alvos(autor: Autor, argumento: str) -> list[str]:
    """Os números de `!teacher`/`!student`: os mencionados (se o payload os trouxer) ou o número
    escrito no texto (`!teacher 5531999998888`, com ou sem `@`)."""
    if autor.mencionados:
        return list(autor.mencionados)
    digitos = re.sub(r"\D", "", argumento)
    return [digitos] if len(digitos) >= 10 else []


def _achar_membro(d: Deps, numero: str) -> tuple[str, Membro | None]:
    existentes = d.repo.listar_membros()
    for chave, membro in existentes:
        if numero_esta_na_lista(numero, [chave]):  # tolera o nono dígito
            return chave, membro
    return numero, None


def _definir_papel(d: Deps, numero: str, papel: Papel) -> Membro:
    chave, membro = _achar_membro(d, numero)
    novo = (membro or Membro(entrou_em=d.agora())).model_copy(update={"papel": papel})
    d.repo.salvar_membro(chave, novo)
    return novo


def _pode_gerir(autor: Autor, membro: Membro | None, eh_dono: Callable[[str], bool]) -> bool:
    """Professor da turma ou dono: quem muda papéis e o nível."""
    return eh_dono(autor.numero) or (membro is not None and membro.papel == "professor")


async def _nivel(
    d: Deps, perfil: Profile, autor: Autor, argumento: str, eh_dono: Callable[[str], bool]
) -> None:
    """`!level`: qualquer membro vê o nível da turma; só professor ou dono o muda (M33)."""
    if argumento:
        quem = await bloq(d.repo.obter_membro, autor.numero)
        if not _pode_gerir(autor, quem, eh_dono):
            await d.conversa.enviar(messages.nivel_so_professor(d.p))
            return
    await commands.definir_nivel(d, perfil, argumento)


async def _diaria(
    d: Deps,
    perfil: Profile,
    autor: Autor,
    argumento: str,
    eh_admin: Callable[[str], bool],
) -> None:
    """`!daily`: qualquer membro vê a revisão diária; só admin do bot (ou o dono) a muda (M35)."""
    if argumento:
        if not await bloq(eh_admin, autor.numero):
            await d.conversa.enviar(messages.so_admin_configura(d.p))
            return
        mudancas = parse_diaria(argumento)
        if mudancas is None:
            await d.conversa.enviar(messages.diaria_invalida(d.p))
            return
        perfil = perfil.model_copy(update={**mudancas, "proxima_diaria": None})
        await bloq(d.repo.salvar_perfil, perfil)
    entradas = await bloq(d.repo.listar_entradas)
    await d.conversa.enviar(
        messages.diaria_estado(
            perfil,
            diaria_a_exibir(perfil, d.agora(), d.fuso, jitter_do_espaco(d.chat_id, "diaria")),
            d.agora(),
            review.limite(d, perfil, len(entradas)),
            d.p,
            alterada=bool(argumento),
        )
    )


async def _semanal(
    d: Deps,
    sessao: Sessao,
    perfil: Profile,
    autor: Autor,
    argumento: str,
    eh_admin: Callable[[str], bool],
) -> Sessao:
    """`!weekly`: qualquer membro vê o desafio semanal; só admin do bot (ou o dono) o muda ou
    o começa na hora com `!weekly now` (M36)."""
    if argumento:
        if not await bloq(eh_admin, autor.numero):
            await d.conversa.enviar(messages.so_admin_configura(d.p, "weekly"))
            return sessao
        if normalizar(argumento) == "now":
            if Estado(sessao.estado) != Estado.IDLE:
                await d.conversa.enviar(messages.atividade_em_andamento(d.p))
                return sessao
            return await semanal.iniciar(d, perfil, avisar=True)
        mudancas = parse_semanal(argumento)
        if mudancas is None:
            await d.conversa.enviar(messages.semanal_invalida(d.p))
            return sessao
        perfil = perfil.model_copy(update={**mudancas, "proxima_semanal": None})
        await bloq(d.repo.salvar_perfil, perfil)
    await d.conversa.enviar(
        messages.semanal_estado(
            perfil,
            semanal_a_exibir(perfil, d.agora(), d.fuso, jitter_do_espaco(d.chat_id, "semanal")),
            d.agora(),
            d.p,
            alterada=bool(argumento),
        )
    )
    return sessao


async def _papel(
    d: Deps,
    sessao: Sessao,
    autor: Autor,
    comando: str,
    argumento: str,
    eh_dono: Callable[[str], bool],
) -> Sessao:
    """`!teacher`/`!student`: só um professor da turma ou o dono. Para qualquer outra pessoa o
    comando não existe: responde como a qualquer outro texto fora de comando (a ajuda)."""
    quem = await bloq(d.repo.obter_membro, autor.numero)
    if not _pode_gerir(autor, quem, eh_dono):
        await d.conversa.enviar(messages.ajuda_do_grupo(d.p))
        return sessao
    alvos = _alvos(autor, argumento)
    if not alvos:
        await d.conversa.enviar(messages.papel_uso(comando, d.p))
        return sessao
    papel: Papel = "professor" if _PAPEIS[comando] == "professor" else "aluno"
    for numero in alvos:
        membro = await bloq(_definir_papel, d, numero, papel)
        await d.conversa.enviar(messages.papel_alterado(membro.nome, papel))
    return sessao


# --- !group -----------------------------------------------------------------------------------


async def _perfil_do_grupo(d: Deps, perfil: Profile) -> None:
    entradas = await bloq(d.repo.listar_entradas)
    membros = await bloq(d.repo.listar_membros)
    respostas = await bloq(d.repo.listar_respostas)
    por_autor: dict[str, int] = {}
    for r in respostas:
        por_autor[r.autor_id] = por_autor.get(r.autor_id, 0) + 1

    linhas: list[tuple[str, str, int]] = []
    sem_nome = 0
    for numero, membro in membros:
        if membro.nome:
            nome = membro.nome
        else:
            sem_nome += 1
            nome = f"Student {sem_nome}"
        linhas.append((nome, membro.papel, por_autor.get(numero, 0)))

    if not perfil.diaria_ligada:
        lembretes = f"off — turn it on with {d.p}daily on"
    else:
        dias = "every day" if perfil.diaria_fim_de_semana else "every weekday"
        lembretes = (
            f"{dias} around {perfil.diaria_hora:02d}:{perfil.diaria_minuto:02d} "
            f"(up to {JITTER_MINUTOS} min earlier or later)"
        )
        proximo = diaria_a_exibir(perfil, d.agora(), d.fuso, jitter_do_espaco(d.chat_id, "diaria"))
        if proximo is not None:
            lembretes += f"\n⏭️ Next review: {messages._quando(proximo, d.agora())}"
        proxima_semanal = semanal_a_exibir(
            perfil, d.agora(), d.fuso, jitter_do_espaco(d.chat_id, "semanal")
        )
        if proxima_semanal is not None:
            lembretes += f"\n🏆 Weekly challenge: {messages._quando(proxima_semanal, d.agora())}"

    await d.conversa.enviar(
        messages.grupo_perfil(
            nivel=perfil.nivel,
            total=len(entradas),
            praticadas=sum(1 for e in entradas if e.status == "praticada"),
            para_revisar=sum(1 for e in entradas if vencida(e, d.agora())),
            lembretes=lembretes,
            membros=linhas,
        )
    )
