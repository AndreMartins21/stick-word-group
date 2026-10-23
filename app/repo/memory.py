"""MemoryBanco / MemoryRepository: implementação em memória, para testes e para o simulador
(`make sim`).

Guarda cópias, como um banco de verdade: alterar o objeto que você passou (ou recebeu) depois de
salvar não muda o que está guardado.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime

from app.domain.models import (
    Entry,
    Estado,
    Membro,
    Profile,
    Resposta,
    Sentence,
    Sessao,
    StatusEntrada,
)
from app.repo.base import (
    AdminDetalhado,
    EntradaJaExiste,
    EspacoResumo,
    GrupoAtivo,
    Repository,
    proximo_tick,
    tipo_do_espaco,
)


@dataclass
class _EspacoMeta:
    """O espelho mutável de `espacos/{id}` (M28): como o `_espaco` (DocumentReference) que
    `FirestoreRepository` recebe, mas em memória. Só existe de verdade (aparece em
    `listar_espacos`) depois de uma escrita real — `salvar_perfil` ou `ativar_grupo`."""

    tipo: str
    criado_em: datetime | None = None
    ativo: bool = False
    nome: str | None = None
    ativado_por: str | None = None
    ativado_em: datetime | None = None

    def escrita(self) -> bool:
        return self.criado_em is not None or self.ativado_em is not None


class MemoryRepository:
    """O caderno de um espaço. Sozinho (`MemoryRepository()`) serve de origem dos scripts."""

    def __init__(self, *, espaco: _EspacoMeta | None = None) -> None:
        self._perfil: Profile | None = None
        self._sessao: Sessao | None = None
        self._entradas: dict[str, Entry] = {}
        self._frases: dict[str, list[Sentence]] = {}
        self._membros: dict[str, Membro] = {}
        self._respostas: list[Resposta] = []
        self._espaco = espaco  # M28: espelho para `Banco.listar_espacos`

    def obter_perfil(self) -> Profile | None:
        return self._perfil.model_copy(deep=True) if self._perfil else None

    def salvar_perfil(self, perfil: Profile) -> None:
        self._perfil = perfil.model_copy(deep=True)
        if self._espaco is not None:
            self._espaco.criado_em = perfil.criado_em

    def obter_sessao(self) -> Sessao:
        return self._sessao.model_copy(deep=True) if self._sessao else Sessao()

    def salvar_sessao(self, sessao: Sessao) -> None:
        self._sessao = sessao.model_copy(deep=True)

    def obter_entrada(self, slug: str) -> Entry | None:
        entrada = self._entradas.get(slug)
        return entrada.model_copy(deep=True) if entrada else None

    def criar_entrada(self, entrada: Entry) -> None:
        if entrada.slug in self._entradas:
            raise EntradaJaExiste(entrada.slug)
        self._entradas[entrada.slug] = entrada.model_copy(deep=True)

    def salvar_entrada(self, entrada: Entry) -> None:
        self._entradas[entrada.slug] = entrada.model_copy(deep=True)

    def listar_entradas(self, status: StatusEntrada | None = None) -> list[Entry]:
        entradas = [e for e in self._entradas.values() if status is None or e.status == status]
        entradas.sort(key=lambda e: (e.criado_em, e.slug))
        return [e.model_copy(deep=True) for e in entradas]

    def apagar_entrada(self, slug: str) -> bool:
        existia = self._entradas.pop(slug, None) is not None
        self._frases.pop(slug, None)
        return existia

    def adicionar_frase(self, slug: str, frase: Sentence) -> None:
        self._frases.setdefault(slug, []).append(frase.model_copy(deep=True))

    def listar_frases(self, slug: str) -> list[Sentence]:
        frases = sorted(self._frases.get(slug, []), key=lambda f: f.criado_em)
        return [f.model_copy(deep=True) for f in frases]

    def obter_membro(self, numero: str) -> Membro | None:
        membro = self._membros.get(numero)
        return membro.model_copy(deep=True) if membro else None

    def salvar_membro(self, numero: str, membro: Membro) -> None:
        self._membros[numero] = membro.model_copy(deep=True)

    def listar_membros(self) -> list[tuple[str, Membro]]:
        ordenados = sorted(self._membros.items(), key=lambda par: (par[1].entrou_em, par[0]))
        return [(n, m.model_copy(deep=True)) for n, m in ordenados]

    def registrar_resposta(self, resposta: Resposta) -> None:
        self._respostas.append(resposta.model_copy(deep=True))

    def listar_respostas(self, desde: datetime | None = None) -> list[Resposta]:
        return [
            r.model_copy(deep=True)
            for r in sorted(self._respostas, key=lambda r: r.criado_em)
            if desde is None or r.criado_em >= desde
        ]

    def apagar_tudo(self) -> None:
        self._perfil = None
        self._sessao = None
        self._entradas.clear()
        self._frases.clear()
        self._membros.clear()
        self._respostas.clear()


class MemoryBanco:
    def __init__(self) -> None:
        self._espacos: dict[str, MemoryRepository] = {}
        self._espacos_meta: dict[str, _EspacoMeta] = {}  # M28: espelho de `espacos/{id}`
        self._processadas: set[str] = set()
        self._lids: dict[str, str] = {}
        self._admins: dict[str, tuple[str, datetime]] = {}  # numero -> (por, agora)
        self._professores: dict[str, tuple[str, datetime]] = {}  # M57: numero -> (por, agora)
        self._grupos_ativos: dict[str, GrupoAtivo] = {}
        self._pendentes: dict[str, datetime] = {}
        self._grupos_sem_lembrete: set[str] = set()  # desativados: o agendador os ignora
        self._ultimo_snapshot: date | None = None  # M28
        self._uso_por_dia: dict[date, float] = {}  # M46
        self._uso_por_espaco: dict[date, dict[str, float]] = {}  # M50

    def _meta_do_espaco(self, espaco_id: str) -> _EspacoMeta:
        return self._espacos_meta.setdefault(espaco_id, _EspacoMeta(tipo=tipo_do_espaco(espaco_id)))

    def do_espaco(self, espaco_id: str) -> Repository:
        if espaco_id not in self._espacos:
            self._espacos[espaco_id] = MemoryRepository(espaco=self._meta_do_espaco(espaco_id))
        return self._espacos[espaco_id]

    def listar_espacos_com_lembrete(self, agora: datetime) -> list[str]:
        vencidos: list[str] = []
        for espaco_id, repo in self._espacos.items():
            if espaco_id in self._grupos_sem_lembrete:
                continue
            perfil = repo.obter_perfil()
            tick = (
                proximo_tick(perfil, grupo=tipo_do_espaco(espaco_id) == "grupo") if perfil else None
            )
            if tick is not None and tick <= agora:
                vencidos.append(espaco_id)
        return vencidos

    def listar_grupos_com_timeout(self, agora: datetime) -> list[str]:
        vencidos: list[str] = []
        for espaco_id, repo in self._espacos.items():
            if not espaco_id.endswith("@g.us"):
                continue
            sessao = repo.obter_sessao()
            prazo = sessao.marcacao_expira_em
            if (
                sessao.estado in (Estado.REVIEWING, Estado.WEEKLY_QUIZ)
                and prazo is not None
                and prazo <= agora
            ):
                vencidos.append(espaco_id)
        return vencidos

    def marcar_processada(self, message_id: str, agora: datetime) -> bool:  # noqa: ARG002
        if message_id in self._processadas:
            return False
        self._processadas.add(message_id)
        return True

    def obter_numero_do_lid(self, lid: str) -> str | None:
        return self._lids.get(lid)

    def salvar_numero_do_lid(self, lid: str, numero: str) -> None:
        self._lids[lid] = numero

    def listar_admins(self) -> list[str]:
        return [n for n, _ in sorted(self._admins.items(), key=lambda par: par[1][1])]

    def adicionar_admin(self, numero: str, *, por: str, agora: datetime) -> bool:
        if numero in self._admins:
            return False
        self._admins[numero] = (por, agora)
        return True

    def remover_admin(self, numero: str) -> bool:
        return self._admins.pop(numero, None) is not None

    def listar_professores(self) -> list[str]:
        return [n for n, _ in sorted(self._professores.items(), key=lambda par: par[1][1])]

    def adicionar_professor(self, numero: str, *, por: str, agora: datetime) -> bool:
        if numero in self._professores:
            return False
        self._professores[numero] = (por, agora)
        return True

    def remover_professor(self, numero: str) -> bool:
        return self._professores.pop(numero, None) is not None

    def grupo_esta_ativo(self, grupo_id: str) -> bool:
        return grupo_id in self._grupos_ativos

    def ativar_grupo(self, grupo_id: str, *, nome: str | None, por: str, agora: datetime) -> None:
        self._grupos_ativos[grupo_id] = GrupoAtivo(grupo_id, nome, por, agora)
        meta = self._meta_do_espaco(grupo_id)
        meta.ativo, meta.nome, meta.ativado_por, meta.ativado_em = True, nome, por, agora
        self._pendentes.pop(grupo_id, None)
        self._grupos_sem_lembrete.discard(grupo_id)

    def renomear_grupo(self, grupo_id: str, nome: str) -> bool:
        atual = self._grupos_ativos.get(grupo_id)
        if atual is None:
            return False
        self._grupos_ativos[grupo_id] = replace(atual, nome=nome)
        self._meta_do_espaco(grupo_id).nome = nome
        return True

    def desativar_grupo(self, grupo_id: str) -> bool:
        if self._grupos_ativos.pop(grupo_id, None) is None:
            return False
        meta = self._espacos_meta.get(grupo_id)
        if meta is not None:
            meta.ativo = False
        self._grupos_sem_lembrete.add(grupo_id)
        return True

    def listar_grupos_ativos(self) -> list[GrupoAtivo]:
        return sorted(self._grupos_ativos.values(), key=lambda g: (g.ativado_em, g.id))

    def registrar_grupo_pendente(self, grupo_id: str, agora: datetime) -> bool:
        if grupo_id in self._pendentes:
            return False
        self._pendentes[grupo_id] = agora
        return True

    def listar_grupos_pendentes(self) -> list[tuple[str, datetime]]:
        return sorted(self._pendentes.items(), key=lambda par: (par[1], par[0]))

    def remover_grupo_pendente(self, grupo_id: str) -> None:
        self._pendentes.pop(grupo_id, None)

    # --- Snapshot de métricas (M28, seção 12) -----------------------------------------------

    def listar_espacos(self) -> list[EspacoResumo]:
        resumos = [
            EspacoResumo(
                id=espaco_id,
                tipo=meta.tipo,
                criado_em=meta.criado_em,
                ativo=meta.ativo,
                nome=meta.nome,
                ativado_por=meta.ativado_por,
                ativado_em=meta.ativado_em,
            )
            for espaco_id, meta in self._espacos_meta.items()
            if meta.escrita()
        ]
        return sorted(resumos, key=lambda e: e.id)

    def listar_admins_detalhado(self) -> list[AdminDetalhado]:
        itens = [
            AdminDetalhado(numero=numero, adicionado_por=por, adicionado_em=agora)
            for numero, (por, agora) in self._admins.items()
        ]
        return sorted(itens, key=lambda a: (a.adicionado_em, a.numero))

    def obter_ultimo_snapshot(self) -> date | None:
        return self._ultimo_snapshot

    def marcar_snapshot(self, dia: date) -> None:
        self._ultimo_snapshot = dia

    def obter_uso_do_dia(self, dia: date) -> float:
        return self._uso_por_dia.get(dia, 0.0)

    def somar_uso_do_dia(
        self, dia: date, usd: float, por_espaco: Mapping[str, float] | None = None
    ) -> None:
        self._uso_por_dia[dia] = self._uso_por_dia.get(dia, 0.0) + usd
        gasto = self._uso_por_espaco.setdefault(dia, {})
        for espaco, valor in (por_espaco or {}).items():
            gasto[espaco] = gasto.get(espaco, 0.0) + valor

    def obter_uso_por_espaco_do_dia(self, dia: date) -> dict[str, float]:
        return dict(self._uso_por_espaco.get(dia, {}))
