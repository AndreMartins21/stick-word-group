"""Interface de persistência (seção 7.1 da spec, ADR-0003, ADR-0017).

Duas peças: o `Banco` (a raiz: deduplicação do webhook, cache de LIDs e a lista dos espaços) e o
`Repository`, o caderno de UM espaço (um chat privado ou um grupo), que o banco entrega em
`do_espaco`. Os fluxos só conhecem o `Repository`, então não sabem quantos espaços existem.

Síncrona de propósito: a lógica de negócio é síncrona e roda em threadpool (seção 8.1); o
cliente do Firestore também é síncrono.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from app.domain.models import (
    Entry,
    Membro,
    Profile,
    Resposta,
    Sentence,
    Sessao,
    StatusEntrada,
    mesma_traducao,
    slugify,
)

PROCESSED_TTL = timedelta(days=7)
# Espaço com lembretes ligados e ainda sem próximo horário: "vencido desde sempre", para o
# agendador calcular o primeiro horário no próximo tick.
SEM_HORARIO_AINDA = datetime(1970, 1, 1, tzinfo=UTC)
_MAX_SLUGS_POR_PALAVRA = 50


class EntradaJaExiste(Exception):
    """`criar_entrada` com um slug que já está no banco."""


class Repository(Protocol):
    def obter_perfil(self) -> Profile | None: ...

    def salvar_perfil(self, perfil: Profile) -> None: ...

    def obter_sessao(self) -> Sessao:
        """A sessão atual; sem documento ainda, uma sessão nova em `IDLE`."""
        ...

    def salvar_sessao(self, sessao: Sessao) -> None: ...

    def obter_entrada(self, slug: str) -> Entry | None: ...

    def criar_entrada(self, entrada: Entry) -> None:
        """Falha com `EntradaJaExiste` se o slug já existe (semântica de `create()`)."""
        ...

    def salvar_entrada(self, entrada: Entry) -> None:
        """Grava por cima (atualização)."""
        ...

    def listar_entradas(self, status: StatusEntrada | None = None) -> list[Entry]:
        """Em ordem de criação; `status` opcional filtra."""
        ...

    def apagar_entrada(self, slug: str) -> bool:
        """Apaga a entrada e suas frases; `False` se ela não existia."""
        ...

    def adicionar_frase(self, slug: str, frase: Sentence) -> None: ...

    def listar_frases(self, slug: str) -> list[Sentence]:
        """Em ordem de criação."""
        ...

    def obter_membro(self, numero: str) -> Membro | None: ...

    def salvar_membro(self, numero: str, membro: Membro) -> None: ...

    def listar_membros(self) -> list[tuple[str, Membro]]:
        """(número, membro), em ordem de entrada. Só grupos têm membros."""
        ...

    def registrar_resposta(self, resposta: Resposta) -> None: ...

    def listar_respostas(self) -> list[Resposta]:
        """Em ordem de criação."""
        ...

    def apagar_tudo(self) -> None:
        """Apaga o espaço inteiro: perfil, sessão, entradas, frases, membros e respostas."""
        ...


@dataclass(frozen=True)
class GrupoAtivo:
    id: str
    nome: str | None
    ativado_por: str  # número (só dígitos) do admin que ativou
    ativado_em: datetime


@dataclass(frozen=True)
class EspacoResumo:
    """Uma linha de `espacos/{id}` (seção 7.1), para o snapshot de métricas (M28, seção 12) —
    não passa pelo `Repository` porque é sobre TODOS os espaços, não sobre um só. `criado_em` só
    existe depois da primeira `salvar_perfil` (ex.: um grupo recém-`!activate`d, sem ninguém
    tendo escrito ainda, ainda não tem); os campos de ativação só existem em grupo."""

    id: str
    tipo: str  # "privado" | "grupo" (tipo_do_espaco)
    criado_em: datetime | None
    ativo: bool = False
    nome: str | None = None
    ativado_por: str | None = None  # número (só dígitos) do admin que ativou por último
    ativado_em: datetime | None = None


@dataclass(frozen=True)
class AdminDetalhado:
    """Uma linha de `admins/{numero}` (M15, ADR-0018), com quem adicionou e quando — para o
    snapshot de métricas (M28, seção 12): `Banco.listar_admins` só devolve os números."""

    numero: str
    adicionado_por: str
    adicionado_em: datetime


class Banco(Protocol):
    def do_espaco(self, espaco_id: str) -> Repository:
        """O caderno do espaço (`NUMERO@c.us` no privado, `...@g.us` no grupo). Nada é lido nem
        gravado até o primeiro uso, e um espaço nunca enxerga os dados de outro."""
        ...

    def listar_espacos_com_lembrete(self, agora: datetime) -> list[str]:
        """Espaços com lembretes ligados e destino conhecido cujo próximo horário já chegou (ou
        ainda não foi calculado). Uma consulta só por tick do agendador, sem ler os demais."""
        ...

    def listar_grupos_com_timeout(self, agora: datetime) -> list[str]:
        """Grupos com uma revisão em andamento cuja marcação já passou do prazo (M17). Uma
        consulta por tick do agendador, sem ler os demais grupos."""
        ...

    def marcar_processada(self, message_id: str, agora: datetime) -> bool:
        """Deduplicação do webhook: `True` na primeira vez que vê o id, `False` depois."""
        ...

    def obter_numero_do_lid(self, lid: str) -> str | None: ...

    def salvar_numero_do_lid(self, lid: str, numero: str) -> None: ...

    # --- Controle de acesso (M15, ADR-0018) -------------------------------------------------

    def listar_admins(self) -> list[str]:
        """Números (só dígitos) dos admins, na ordem em que entraram."""
        ...

    def adicionar_admin(self, numero: str, *, por: str, agora: datetime) -> bool:
        """`False` se já era admin (não duplica)."""
        ...

    def remover_admin(self, numero: str) -> bool: ...

    def grupo_esta_ativo(self, grupo_id: str) -> bool:
        """Só o que foi ativado por admin; quem confere `ALLOWED_GROUPS` é o webhook."""
        ...

    def ativar_grupo(self, grupo_id: str, *, nome: str | None, por: str, agora: datetime) -> None:
        """Ativa (ou reativa) e tira o grupo dos pendentes. O caderno da turma não é tocado."""
        ...

    def desativar_grupo(self, grupo_id: str) -> bool:
        """`False` se não estava ativo. Os dados do espaço ficam."""
        ...

    def listar_grupos_ativos(self) -> list[GrupoAtivo]: ...

    def registrar_grupo_pendente(self, grupo_id: str, agora: datetime) -> bool:
        """Grupo em que o bot está sem ter sido ativado. `True` só na primeira vez: o horário
        guardado é o do primeiro encontro, então o prazo de 24h para sair não reinicia."""
        ...

    def listar_grupos_pendentes(self) -> list[tuple[str, datetime]]: ...

    def remover_grupo_pendente(self, grupo_id: str) -> None: ...

    # --- Snapshot de métricas (M28, seção 12) -----------------------------------------------

    def listar_espacos(self) -> list[EspacoResumo]:
        """Todos os espaços que já tiveram alguma escrita (perfil salvo ou grupo ativado),
        privados e grupos, ativos e desativados — para o snapshot diário, não para o webhook."""
        ...

    def listar_admins_detalhado(self) -> list[AdminDetalhado]:
        """Como `listar_admins`, mas com quem adicionou e quando."""
        ...

    def obter_ultimo_snapshot(self) -> date | None:
        """O dia (UTC) do último snapshot que terminou — para o `Agendador` não repetir depois
        de um restart (M28)."""
        ...

    def marcar_snapshot(self, dia: date) -> None: ...

    def obter_uso_do_dia(self, dia: date) -> float:
        """O custo estimado de IA (USD) já gasto em `dia` (fuso do aluno); 0 se não houver (M46)."""
        ...

    def somar_uso_do_dia(
        self, dia: date, usd: float, por_espaco: Mapping[str, float] | None = None
    ) -> None:
        """Soma `usd` ao gasto de `dia`, de forma atômica (M46, orçamento diário). `por_espaco`
        (M50) soma, na mesma escrita, o gasto de cada espaço (chave = id do chat, sem pontos)."""
        ...

    def obter_uso_por_espaco_do_dia(self, dia: date) -> dict[str, float]:
        """O gasto de IA de cada espaço em `dia` (M50, cota por grupo); vazio se não houver."""
        ...


def tipo_do_espaco(espaco_id: str) -> str:
    return "grupo" if espaco_id.endswith("@g.us") else "privado"


def proximo_tick(perfil: Profile, *, grupo: bool = False) -> datetime | None:
    """O que o `Banco` espelha do perfil no documento do espaço para a consulta dos lembretes:
    quando o agendador deve olhar este espaço de novo, ou `None` se ele não deve olhar nunca.
    No grupo (M35/M36) vale o menor entre a revisão diária e o desafio semanal, não os
    lembretes N vezes por dia."""
    if perfil.chat_id is None:
        return None
    if grupo:
        ticks = []
        if perfil.diaria_ligada:
            ticks.append(perfil.proxima_diaria or SEM_HORARIO_AINDA)
        if perfil.semanal_ligada:
            ticks.append(perfil.proxima_semanal or SEM_HORARIO_AINDA)
        return min(ticks) if ticks else None
    if perfil.lembretes_por_dia == 0:
        return None
    return perfil.proximo_lembrete or SEM_HORARIO_AINDA


def resolver_slug(repo: Repository, palavra: str, traducao_do_sentido: str) -> str:
    """`slug` livre para a palavra (seção 7.1): o da própria palavra, o mesmo se o sentido já
    é o que está salvo, ou `--s2`, `--s3`... quando a palavra existe com outro sentido."""
    base = slugify(palavra)
    for numero in range(1, _MAX_SLUGS_POR_PALAVRA + 1):
        candidato = base if numero == 1 else f"{base}--s{numero}"
        existente = repo.obter_entrada(candidato)
        if existente is None or mesma_traducao(existente.sentido.traducao, traducao_do_sentido):
            return candidato
    raise RuntimeError(f"palavras demais com o slug {base!r}")
