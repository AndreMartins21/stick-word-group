"""Controle de acesso (M15, ADR-0018): quem pode ativar o bot num grupo e quem gerencia os admins.

Papéis: o **dono** (`OWNER_NUMBER`) é sempre admin e o único que gerencia admins; **admins**
(`admins/{numero}` no Firestore) ativam o bot em grupos. Grupo ativo = em `ALLOWED_GROUPS` (fixo,
M14) ou ativado por um admin com `!activate`, até `MAX_GROUPS`. Grupo em que o bot foi adicionado
sem ativação fica **pendente** em silêncio, e o agendador sai dele depois de 24 h.

Aqui não há IA nem sessão: só regras de acesso, com respostas curtas e fixas.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from app import messages
from app.channel.base import Channel
from app.channel.parser import numero_esta_na_lista
from app.domain.choices import normalizar
from app.domain.ranking import Turma, calcular, meses_atras
from app.flows.base import bloq
from app.flows.papeis import rebaixar_em_todos
from app.logging_config import id_curto, registrar_evento
from app.repo.base import Banco
from app.services.relatorio_ranking import gerar_pdf_ranking

logger = logging.getLogger(__name__)

PRAZO_GRUPO_PENDENTE = timedelta(hours=24)
_MIN_DIGITOS = 10


@dataclass(frozen=True)
class Acesso:
    banco: Banco
    canal: Channel
    eh_dono: Callable[[str], bool]
    grupos_fixos: Sequence[str]  # ALLOWED_GROUPS
    max_grupos: int
    agora: Callable[[], datetime]
    contato: str  # o e-mail que o aviso "sem plano" mostra
    prefixo: str = "!"  # GROUP_PREFIX


class Resultado(StrEnum):
    ATIVADO = "ativado"
    RENOMEADO = "renomeado"
    JA_ATIVO = "ja_ativo"
    LIMITE = "limite"
    NAO_ADMIN = "nao_admin"
    DESATIVADO = "desativado"
    NAO_ESTAVA_ATIVO = "nao_estava_ativo"


def so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto)


def eh_admin(a: Acesso, numero: str) -> bool:
    """Dono ou admin do Firestore, com a variação do nono dígito. Síncrono (lê o banco)."""
    return a.eh_dono(numero) or numero_esta_na_lista(numero, a.banco.listar_admins())


def grupo_autorizado(a: Acesso, grupo_id: str) -> bool:
    return grupo_id in a.grupos_fixos or a.banco.grupo_esta_ativo(grupo_id)


# --- No grupo: !activate / !deactivate --------------------------------------------------------


def eh_comando_de_ativacao(texto: str, prefixo: str = "!") -> str | None:
    """`activate` ou `deactivate` se o texto for exatamente esse comando com o prefixo do grupo;
    qualquer outra coisa (inclusive `!activate` no meio de uma frase) é conversa e devolve None."""
    partes = texto.strip().split()
    if not partes:
        return None
    primeira = partes[0]
    prefixo_usado = next((p for p in (prefixo, "/") if primeira.startswith(p)), None)
    if prefixo_usado is None:
        return None
    comando = normalizar(primeira[len(prefixo_usado) :])
    return comando if comando in {"activate", "deactivate"} else None


NOME_DO_GRUPO_MAXIMO = 80


def nome_da_ativacao(texto: str, prefixo: str = "!") -> str | None:
    """O nome que o admin escreveu depois de `!activate` (M62, ADR-0060), com os espaços
    normalizados e no máximo `NOME_DO_GRUPO_MAXIMO` caracteres; `None` se não escreveu nada."""
    partes = texto.split(maxsplit=1)
    if len(partes) < 2 or eh_comando_de_ativacao(texto, prefixo) != "activate":
        return None
    nome = " ".join(partes[1].split())[:NOME_DO_GRUPO_MAXIMO].strip()
    return nome or None


def ativar_grupo(a: Acesso, grupo_id: str, numero: str, nome: str | None) -> Resultado:
    if not eh_admin(a, numero):
        return Resultado.NAO_ADMIN
    if grupo_autorizado(a, grupo_id):
        if nome and a.banco.renomear_grupo(grupo_id, nome):
            return Resultado.RENOMEADO
        return Resultado.JA_ATIVO
    if len(a.banco.listar_grupos_ativos()) >= a.max_grupos:
        return Resultado.LIMITE
    a.banco.ativar_grupo(grupo_id, nome=nome, por=so_digitos(numero), agora=a.agora())
    registrar_evento(logger, "grupo_ativado", espaco=id_curto(grupo_id))
    return Resultado.ATIVADO


def desativar_grupo(a: Acesso, grupo_id: str, numero: str) -> Resultado:
    if not eh_admin(a, numero):
        return Resultado.NAO_ADMIN
    if a.banco.desativar_grupo(grupo_id):
        registrar_evento(logger, "grupo_desativado", espaco=id_curto(grupo_id))
        return Resultado.DESATIVADO
    return Resultado.NAO_ESTAVA_ATIVO  # inclusive um grupo fixo: esse só sai da configuração


def _resposta_do_grupo(a: Acesso, resultado: Resultado, nome: str | None = None) -> str | None:
    return {
        Resultado.ATIVADO: messages.grupo_ativado(a.prefixo),
        Resultado.JA_ATIVO: messages.GRUPO_JA_ATIVO,
        Resultado.RENOMEADO: messages.grupo_renomeado(nome or ""),
        Resultado.DESATIVADO: messages.GRUPO_DESATIVADO,
    }.get(resultado)


async def tratar_ativacao_no_grupo(
    a: Acesso, comando: str, grupo_id: str, numero: str, nome_digitado: str | None = None
) -> None:
    """Executa `!activate`/`!deactivate` vindo de `numero` e responde no grupo. Quem não é admin
    não recebe nada: o bot não revela que existe. O nome que o admin digitou (`!activate Turma A`)
    vale mais que o do WhatsApp e, num grupo já ativo, renomeia (M62, ADR-0060)."""
    nome: str | None = None
    if comando == "activate":
        e_admin = await bloq(eh_admin, a, numero)
        nome = nome_digitado or (await a.canal.group_name(grupo_id) if e_admin else None)
        resultado = await bloq(ativar_grupo, a, grupo_id, numero, nome)
    else:
        resultado = await bloq(desativar_grupo, a, grupo_id, numero)

    if resultado is Resultado.LIMITE:
        await a.canal.send_text(grupo_id, messages.grupo_limite(a.max_grupos))
    elif (texto := _resposta_do_grupo(a, resultado, nome)) is not None:
        await a.canal.send_text(grupo_id, texto)
    elif resultado is Resultado.NAO_ADMIN:
        logger.info("!%s de quem não é admin ignorado", comando)


# --- No privado: /groups e /admin -------------------------------------------------------------


def _comando_privado(texto: str, prefixo: str = "!") -> tuple[str, list[str]] | None:
    partes = texto.strip().split()
    if not partes:
        return None
    for inicio in ("/", prefixo):
        if partes[0].startswith(inicio):
            comando = normalizar(partes[0][len(inicio) :])
            break
    else:
        return None
    return (
        (comando, partes[1:])
        if comando in {"groups", "grupos", "admin", "teachers", "teacher", "ranking"}
        else None
    )


def eh_comando_de_admin(texto: str, prefixo: str = "!") -> bool:
    return _comando_privado(texto, prefixo) is not None


async def comando_privado(a: Acesso, texto: str, numero: str) -> str | list[str] | Arquivo | None:
    """A resposta a `/groups`, `/admin`, `/teachers` ou `/ranking` (uma lista quando são várias
    mensagens), ou `None` se o texto não é um desses comandos OU quem escreveu não pode usá-lo
    (então o chamador trata como um texto qualquer)."""
    achado = _comando_privado(texto, a.prefixo)
    if achado is None:
        return None
    comando, argumentos = achado
    if comando == "admin":
        if not a.eh_dono(numero):
            return None
        return await bloq(_admin, a, argumentos, so_digitos(numero))
    if not await bloq(eh_admin, a, numero):
        return None
    if comando == "ranking":
        return await _ranking(a, argumentos)
    if comando in {"teachers", "teacher"}:
        return await bloq(_professores, a, argumentos, so_digitos(numero))
    return await _grupos(a, argumentos)


def _admin(a: Acesso, argumentos: list[str], dono: str) -> str:
    if not argumentos:
        return messages.admin_lista(a.banco.listar_admins())
    acao = normalizar(argumentos[0])
    alvo = so_digitos(" ".join(argumentos[1:]))
    if acao not in {"add", "remove"} or len(alvo) < _MIN_DIGITOS:
        return messages.ADMIN_USO
    if a.eh_dono(alvo):
        return messages.ADMIN_E_O_DONO
    if acao == "add":
        if numero_esta_na_lista(alvo, a.banco.listar_admins()):
            return messages.ADMIN_JA_E_ADMIN
        a.banco.adicionar_admin(alvo, por=dono, agora=a.agora())
        return messages.admin_adicionado(a.prefixo)
    existente = next((n for n in a.banco.listar_admins() if numero_esta_na_lista(alvo, [n])), None)
    if existente is None or not a.banco.remover_admin(existente):
        return messages.ADMIN_NAO_E_ADMIN
    return messages.ADMIN_REMOVIDO


def _professores(a: Acesso, argumentos: list[str], por: str) -> str:
    """`/teachers [add|remove NUMERO]` (M57, ADR-0055): os professores valem em todos os grupos,
    nunca são marcados no desafio semanal e não ativam grupos."""
    atuais = a.banco.listar_professores()
    if not argumentos:
        return messages.professores_lista(atuais)
    acao = normalizar(argumentos[0])
    if acao not in {"add", "remove"}:
        texto = " ".join(argumentos)  # `/teachers NUMERO` (M59): só dígitos e formatação
        if re.search(r"[^\d\s+().-]", texto):
            return messages.PROFESSORES_USO
        acao, alvo = "alternar", so_digitos(texto)
    else:
        alvo = so_digitos(" ".join(argumentos[1:]))
    if len(alvo) < _MIN_DIGITOS:
        return messages.PROFESSORES_USO
    if acao == "alternar":
        acao = "remove" if numero_esta_na_lista(alvo, atuais) else "add"
    if acao == "add":
        if numero_esta_na_lista(alvo, atuais):
            return messages.PROFESSOR_JA_E
        a.banco.adicionar_professor(alvo, por=por, agora=a.agora())
        return messages.PROFESSOR_ADICIONADO
    if not rebaixar_em_todos(a.banco, alvo):
        return messages.PROFESSOR_NAO_E
    return messages.PROFESSOR_REMOVIDO


@dataclass(frozen=True)
class Arquivo:
    """Um arquivo a enviar no privado em vez de texto (o PDF do /ranking, M62)."""

    nome: str
    conteudo: bytes
    tipo: str
    legenda: str


RANKING_MESES_PADRAO = 6
RANKING_MESES_MAXIMO = 24


async def _ranking(a: Acesso, argumentos: list[str]) -> str | Arquivo:
    """`/ranking [meses]` (M58, ADR-0056): os alunos e as turmas mais engajados do período."""
    meses = RANKING_MESES_PADRAO
    if argumentos:
        if len(argumentos) != 1 or not argumentos[0].isdigit():
            return messages.RANKING_USO
        meses = int(argumentos[0])
        if not 1 <= meses <= RANKING_MESES_MAXIMO:
            return messages.RANKING_USO
    desde = meses_atras(a.agora(), meses)
    professores = await bloq(a.banco.listar_professores)
    admins = await bloq(a.banco.listar_admins)

    def eh_staff(numero: str) -> bool:
        return (
            a.eh_dono(numero)
            or numero_esta_na_lista(numero, admins)
            or numero_esta_na_lista(numero, professores)
        )

    turmas: list[Turma] = []
    for grupo in await bloq(a.banco.listar_grupos_ativos):
        repo = a.banco.do_espaco(grupo.id)
        nome = grupo.nome or await a.canal.group_name(grupo.id) or "Group"
        turmas.append(
            Turma(
                nome=nome,
                membros=await bloq(repo.listar_membros),
                respostas=await bloq(repo.listar_respostas, desde),
            )
        )
    ranking = calcular(turmas, eh_staff=eh_staff)
    if ranking.vazio:
        return messages.ranking_vazio(meses)
    agora = a.agora()
    pdf = await asyncio.to_thread(gerar_pdf_ranking, ranking, meses, agora)  # CPU: fora do loop
    return Arquivo(
        f"ranking-{agora:%Y-%m-%d}.pdf", pdf, "application/pdf", messages.ranking_legenda(meses)
    )


async def _grupos(a: Acesso, argumentos: list[str]) -> str:
    ativos = await bloq(a.banco.listar_grupos_ativos)
    if argumentos:
        if (
            normalizar(argumentos[0]) != "off"
            or len(argumentos) != 2
            or not argumentos[1].isdigit()
        ):
            return messages.GRUPOS_USO
        indice = int(argumentos[1])
        if not 1 <= indice <= len(ativos):
            return messages.GRUPO_NAO_EXISTE
        grupo = ativos[indice - 1]
        await bloq(a.banco.desativar_grupo, grupo.id)
        return messages.grupo_desligado(grupo.nome)

    pendentes = await bloq(a.banco.listar_grupos_pendentes)
    agora = a.agora()
    return messages.grupos(
        [g.nome for g in ativos],
        [await a.canal.group_name(g) for g in a.grupos_fixos],
        [
            (
                await a.canal.group_name(grupo_id),
                max(0, int((visto + PRAZO_GRUPO_PENDENTE - agora).total_seconds() // 3600)),
            )
            for grupo_id, visto in pendentes
        ],
        a.max_grupos,
        a.prefixo,
    )
