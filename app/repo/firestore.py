"""Firestore (ADR-0003, ADR-0017): Cloud Firestore em modo nativo, esquema da seção 7.1.

    espacos/{espaco_id}                               {tipo, criado_em, proximo_tick?}
    espacos/{espaco_id}/profile/me                    espacos/{espaco_id}/session/current
    espacos/{espaco_id}/entries/{slug}                espacos/{espaco_id}/entries/{slug}/sentences/{auto}
    processed/{message_id}                            lids/{lid}

`processed.expira_em` é o campo da política de TTL de 7 dias (criada no `infra/setup.sh`).
`proximo_tick` espelha o perfil (ver `proximo_tick` em `repo/base.py`): a consulta dos lembretes
usa só esse campo, então não exige índice composto e só lê os espaços que já venceram.

Antes do M14 (multiusuário) `profile`, `session` e `entries` ficavam na raiz do banco.
`FirestoreRepository(client)` ainda lê esse formato antigo: é a origem do script de migração.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Any

from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

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
    PROCESSED_TTL,
    AdminDetalhado,
    EntradaJaExiste,
    EspacoResumo,
    GrupoAtivo,
    Repository,
    proximo_tick,
    tipo_do_espaco,
)

VALIDADE_DO_CACHE_DE_ACESSO = 60.0  # segundos (M48, ADR-0046)
TAMANHO_MAXIMO_DO_CACHE_DE_GRUPOS = 500
TAMANHO_MAXIMO_DO_CACHE_DE_LIDS = 5000


class FirestoreRepository:
    """O caderno de um espaço. `raiz` é qualquer coisa com `.collection(...)`: o `Client` (formato
    antigo, sem espaço) ou o documento `espacos/{id}` (e então `espaco` o aponta, para o espelho)."""

    def __init__(self, raiz: Any, espaco: firestore.DocumentReference | None = None) -> None:
        self._raiz = raiz
        self._espaco = espaco

    def obter_perfil(self) -> Profile | None:
        dados = self._raiz.collection("profile").document("me").get().to_dict()
        return Profile.model_validate(dados) if dados else None

    def salvar_perfil(self, perfil: Profile) -> None:
        self._raiz.collection("profile").document("me").set(perfil.model_dump())
        if self._espaco is not None:
            tick = proximo_tick(perfil, grupo=tipo_do_espaco(self._espaco.id) == "grupo")
            self._espaco.set(
                {
                    "tipo": tipo_do_espaco(self._espaco.id),
                    "criado_em": perfil.criado_em,
                    "proximo_tick": tick if tick is not None else firestore.DELETE_FIELD,
                },
                merge=True,
            )

    def obter_sessao(self) -> Sessao:
        dados = self._raiz.collection("session").document("current").get().to_dict()
        return Sessao.model_validate(dados) if dados else Sessao()

    def salvar_sessao(self, sessao: Sessao) -> None:
        self._raiz.collection("session").document("current").set(sessao.model_dump())
        if self._espaco is not None and tipo_do_espaco(self._espaco.id) == "grupo":
            # Espelha o prazo da marcação (M17) para o agendador achar as vencidas com uma
            # consulta só, sem ler os demais grupos.
            prazo = (
                sessao.marcacao_expira_em
                if sessao.estado in (Estado.REVIEWING, Estado.WEEKLY_QUIZ)
                else None
            )
            self._espaco.set(
                {"timeout_em": prazo if prazo is not None else firestore.DELETE_FIELD},
                merge=True,
            )

    def obter_entrada(self, slug: str) -> Entry | None:
        dados = self._raiz.collection("entries").document(slug).get().to_dict()
        return Entry.model_validate(dados) if dados else None

    def criar_entrada(self, entrada: Entry) -> None:
        try:
            self._raiz.collection("entries").document(entrada.slug).create(entrada.model_dump())
        except AlreadyExists as erro:
            raise EntradaJaExiste(entrada.slug) from erro

    def salvar_entrada(self, entrada: Entry) -> None:
        self._raiz.collection("entries").document(entrada.slug).set(entrada.model_dump())

    def listar_entradas(self, status: StatusEntrada | None = None) -> list[Entry]:
        # Filtrar por status no servidor E ordenar por data exigiria um índice composto;
        # o volume é pequeno, então a ordenação é em Python (ADR-0003).
        consulta = self._raiz.collection("entries")
        if status is not None:
            documentos = consulta.where(filter=FieldFilter("status", "==", status)).stream()
        else:
            documentos = consulta.stream()
        entradas = [Entry.model_validate(d.to_dict()) for d in documentos]
        entradas.sort(key=lambda e: (e.criado_em, e.slug))
        return entradas

    def apagar_entrada(self, slug: str) -> bool:
        documento = self._raiz.collection("entries").document(slug)
        if not documento.get().exists:
            return False
        for frase in documento.collection("sentences").stream():
            frase.reference.delete()
        documento.delete()
        return True

    def adicionar_frase(self, slug: str, frase: Sentence) -> None:
        self._raiz.collection("entries").document(slug).collection("sentences").add(
            frase.model_dump()
        )

    def listar_frases(self, slug: str) -> list[Sentence]:
        documentos = (
            self._raiz.collection("entries")
            .document(slug)
            .collection("sentences")
            .order_by("criado_em")
            .stream()
        )
        return [Sentence.model_validate(d.to_dict()) for d in documentos]

    def obter_membro(self, numero: str) -> Membro | None:
        dados = self._raiz.collection("membros").document(numero).get().to_dict()
        return Membro.model_validate(dados) if dados else None

    def salvar_membro(self, numero: str, membro: Membro) -> None:
        self._raiz.collection("membros").document(numero).set(membro.model_dump())

    def listar_membros(self) -> list[tuple[str, Membro]]:
        membros = [
            (d.id, Membro.model_validate(dados))
            for d in self._raiz.collection("membros").stream()
            if (dados := d.to_dict())
        ]
        return sorted(membros, key=lambda par: (par[1].entrou_em, par[0]))

    def registrar_resposta(self, resposta: Resposta) -> None:
        self._raiz.collection("respostas").add(resposta.model_dump())

    def listar_respostas(self) -> list[Resposta]:
        documentos = self._raiz.collection("respostas").order_by("criado_em").stream()
        return [Resposta.model_validate(d.to_dict()) for d in documentos]

    def apagar_tudo(self) -> None:
        for colecao in ("membros", "respostas"):
            for documento in self._raiz.collection(colecao).stream():
                documento.reference.delete()
        for entrada in self._raiz.collection("entries").stream():
            self.apagar_entrada(entrada.id)
        self._raiz.collection("profile").document("me").delete()
        self._raiz.collection("session").document("current").delete()
        if self._espaco is not None:
            self._espaco.delete()


class FirestoreBanco:
    def __init__(
        self,
        client: firestore.Client,
        *,
        relogio: Callable[[], float] = time.monotonic,
        validade_do_cache: float = VALIDADE_DO_CACHE_DE_ACESSO,
    ) -> None:
        self._db = client
        # M48 (ADR-0046): a checagem de acesso (admin? grupo ativo?) roda a CADA mensagem, inclusive
        # a conversa entre pessoas que o bot ignora. Cache curto em memória, invalidado pelas
        # próprias mutações deste processo (um só); edição manual no console vale em ≤ 60 s.
        self._relogio = relogio
        self._validade = validade_do_cache
        self._cache_admins: tuple[float, list[str]] | None = None
        self._cache_grupos: dict[str, tuple[float, bool]] = {}
        self._cache_lids: dict[str, str] = {}

    def do_espaco(self, espaco_id: str) -> Repository:
        documento = self._db.collection("espacos").document(espaco_id)
        return FirestoreRepository(documento, espaco=documento)

    def listar_espacos_com_lembrete(self, agora: datetime) -> list[str]:
        consulta = self._db.collection("espacos").where(
            filter=FieldFilter("proximo_tick", "<=", agora)
        )
        return [d.id for d in consulta.stream()]

    def listar_grupos_com_timeout(self, agora: datetime) -> list[str]:
        consulta = self._db.collection("espacos").where(
            filter=FieldFilter("timeout_em", "<=", agora)
        )
        return [d.id for d in consulta.stream()]

    def marcar_processada(self, message_id: str, agora: datetime) -> bool:
        documento = self._db.collection("processed").document(message_id.replace("/", "_"))
        try:
            documento.create({"criado_em": agora, "expira_em": agora + PROCESSED_TTL})
        except AlreadyExists:
            return False
        return True

    def obter_numero_do_lid(self, lid: str) -> str | None:
        if lid in self._cache_lids:
            return self._cache_lids[lid]
        dados = self._db.collection("lids").document(lid).get().to_dict()
        numero = str(dados["numero"]) if dados else None
        if numero is not None and len(self._cache_lids) < TAMANHO_MAXIMO_DO_CACHE_DE_LIDS:
            self._cache_lids[lid] = numero  # o LID de uma pessoa não muda: vale pelo processo
        return numero

    def salvar_numero_do_lid(self, lid: str, numero: str) -> None:
        self._db.collection("lids").document(lid).set({"numero": numero})
        self._cache_lids.pop(lid, None)

    # --- Controle de acesso (M15, ADR-0018) -----------------------------------------------------

    def listar_admins(self) -> list[str]:
        agora = self._relogio()
        if self._cache_admins is not None and agora - self._cache_admins[0] < self._validade:
            return list(self._cache_admins[1])
        documentos = self._db.collection("admins").order_by("adicionado_em").stream()
        admins = [d.id for d in documentos]
        self._cache_admins = (agora, admins)
        return list(admins)

    def adicionar_admin(self, numero: str, *, por: str, agora: datetime) -> bool:
        try:
            self._db.collection("admins").document(numero).create(
                {"adicionado_em": agora, "adicionado_por": por}
            )
        except AlreadyExists:
            return False
        self._cache_admins = None
        return True

    def remover_admin(self, numero: str) -> bool:
        documento = self._db.collection("admins").document(numero)
        if not documento.get().exists:
            return False
        documento.delete()
        self._cache_admins = None
        return True

    def _ler_grupo_ativo(self, grupo_id: str) -> bool:
        dados = self._db.collection("espacos").document(grupo_id).get().to_dict()
        return bool(dados and dados.get("ativo"))

    def grupo_esta_ativo(self, grupo_id: str) -> bool:
        agora = self._relogio()
        em_cache = self._cache_grupos.get(grupo_id)
        if em_cache is not None and agora - em_cache[0] < self._validade:
            return em_cache[1]
        ativo = self._ler_grupo_ativo(grupo_id)
        if len(self._cache_grupos) >= TAMANHO_MAXIMO_DO_CACHE_DE_GRUPOS:
            self._cache_grupos.clear()  # grupos desconhecidos não crescem o mapa sem limite
        self._cache_grupos[grupo_id] = (agora, ativo)
        return ativo

    def ativar_grupo(self, grupo_id: str, *, nome: str | None, por: str, agora: datetime) -> None:
        try:
            self._gravar_ativacao(grupo_id, nome=nome, por=por, agora=agora)
        finally:
            self._cache_grupos.pop(grupo_id, None)  # depois da escrita: nada re-cacheia o antigo

    def _gravar_ativacao(
        self, grupo_id: str, *, nome: str | None, por: str, agora: datetime
    ) -> None:
        self._db.collection("espacos").document(grupo_id).set(
            {
                "tipo": "grupo",
                "ativo": True,
                "nome": nome,
                "ativado_por": por,
                "ativado_em": agora,
            },
            merge=True,
        )
        self._db.collection("grupos_pendentes").document(grupo_id).delete()
        # Reativar devolve os lembretes do grupo (a desativação os tirou da consulta do agendador).
        perfil = self.do_espaco(grupo_id).obter_perfil()
        tick = proximo_tick(perfil, grupo=True) if perfil else None
        if tick is not None:
            self._db.collection("espacos").document(grupo_id).set(
                {"proximo_tick": tick}, merge=True
            )

    def desativar_grupo(self, grupo_id: str) -> bool:
        try:
            if not self._ler_grupo_ativo(grupo_id):
                return False
            self._db.collection("espacos").document(grupo_id).set(
                {"ativo": False, "proximo_tick": firestore.DELETE_FIELD}, merge=True
            )
            return True
        finally:
            self._cache_grupos.pop(grupo_id, None)

    def listar_grupos_ativos(self) -> list[GrupoAtivo]:
        consulta = self._db.collection("espacos").where(filter=FieldFilter("ativo", "==", True))
        grupos = [
            GrupoAtivo(d.id, dados.get("nome"), dados["ativado_por"], dados["ativado_em"])
            for d in consulta.stream()
            if (dados := d.to_dict())
        ]
        return sorted(grupos, key=lambda g: (g.ativado_em, g.id))

    def registrar_grupo_pendente(self, grupo_id: str, agora: datetime) -> bool:
        try:
            self._db.collection("grupos_pendentes").document(grupo_id).create({"visto_em": agora})
        except AlreadyExists:
            return False
        return True

    def listar_grupos_pendentes(self) -> list[tuple[str, datetime]]:
        documentos = self._db.collection("grupos_pendentes").stream()
        pendentes = [(d.id, dados["visto_em"]) for d in documentos if (dados := d.to_dict())]
        return sorted(pendentes, key=lambda par: (par[1], par[0]))

    def remover_grupo_pendente(self, grupo_id: str) -> None:
        self._db.collection("grupos_pendentes").document(grupo_id).delete()

    # --- Snapshot de métricas (M28, seção 12) -----------------------------------------------

    def listar_espacos(self) -> list[EspacoResumo]:
        resumos = [
            EspacoResumo(
                id=d.id,
                tipo=dados.get("tipo", tipo_do_espaco(d.id)),
                criado_em=dados.get("criado_em"),
                ativo=bool(dados.get("ativo", False)),
                nome=dados.get("nome"),
                ativado_por=dados.get("ativado_por"),
                ativado_em=dados.get("ativado_em"),
            )
            for d in self._db.collection("espacos").stream()
            if (dados := d.to_dict())
        ]
        return sorted(resumos, key=lambda e: e.id)

    def listar_admins_detalhado(self) -> list[AdminDetalhado]:
        documentos = self._db.collection("admins").order_by("adicionado_em").stream()
        return [
            AdminDetalhado(
                numero=d.id,
                adicionado_por=dados["adicionado_por"],
                adicionado_em=dados["adicionado_em"],
            )
            for d in documentos
            if (dados := d.to_dict())
        ]

    def obter_ultimo_snapshot(self) -> date | None:
        dados = self._db.collection("meta").document("snapshot").get().to_dict()
        return date.fromisoformat(dados["ultimo_dia"]) if dados else None

    def marcar_snapshot(self, dia: date) -> None:
        self._db.collection("meta").document("snapshot").set({"ultimo_dia": dia.isoformat()})

    def obter_uso_do_dia(self, dia: date) -> float:
        dados = self._db.collection("uso").document(dia.isoformat()).get().to_dict()
        return float(dados.get("usd", 0.0)) if dados else 0.0

    def somar_uso_do_dia(
        self, dia: date, usd: float, por_espaco: Mapping[str, float] | None = None
    ) -> None:
        corpo: dict[str, Any] = {"usd": firestore.Increment(usd)}
        if por_espaco:
            corpo["espacos"] = {e: firestore.Increment(v) for e, v in por_espaco.items()}
        self._db.collection("uso").document(dia.isoformat()).set(corpo, merge=True)

    def obter_uso_por_espaco_do_dia(self, dia: date) -> dict[str, float]:
        dados = self._db.collection("uso").document(dia.isoformat()).get().to_dict() or {}
        return {e: float(v) for e, v in (dados.get("espacos") or {}).items()}
