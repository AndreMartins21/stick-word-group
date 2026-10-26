"""Snapshot diário do Firestore (M28, ADR-0029, seção 12 da spec): uma foto do estado de todos
os espaços, virada em linhas para o BigQuery. `montar_snapshot` é **pura** sobre o `Banco` — sem
rede, sem GCS — para ser testável com `MemoryBanco` (TDD) e reutilizável pelo `Agendador` e por
`python -m scripts.snapshot`.

Cada linha usa `espaco`/`pessoa` = `id_curto(...)` (o mesmo hash já usado nos logs, M27): é a
chave de junção entre o snapshot e os eventos. Números completos só aparecem nas tabelas de
`admins` (decisão do usuário, 2026-09-27) — nunca na de `pessoas` (alunos).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.channel.parser import digitos_do_chat_id
from app.domain.models import Entry, Membro, Profile, Resposta, Sessao
from app.domain.srs import vencida
from app.logging_config import id_curto, mascarar_numero
from app.repo.base import Banco, EspacoResumo, Repository

# --- estimativa de tamanho (seção 3.5 do plano: "Storage size calculations" oficial) -----------


def _tamanho_string(texto: str) -> int:
    return len(texto.encode("utf-8")) + 1


def _tamanho_valor(valor: object) -> int:
    if valor is None or isinstance(valor, bool):
        return 1
    if isinstance(valor, int | float):
        return 8
    if isinstance(valor, str):
        return _tamanho_string(valor)
    if isinstance(valor, datetime):
        return 8
    if isinstance(valor, dict):
        return sum(_tamanho_campo(k, v) for k, v in valor.items()) + 32
    if isinstance(valor, list | tuple):
        return sum(_tamanho_valor(v) for v in valor) + 16
    return 8  # nunca deveria chegar aqui (campos de um model_dump são só os tipos acima)


def _tamanho_campo(nome: str, valor: object) -> int:
    return _tamanho_string(nome) + _tamanho_valor(valor)


def tamanho_estimado_do_documento(caminho: tuple[str, ...], campos: dict[str, Any]) -> int:
    """Aproximação da fórmula oficial (nome do documento + campos + 32 bytes extras); índices
    automáticos não entram na conta — quem usa este número trata como estimativa (seção 3.5)."""
    nome = sum(_tamanho_string(parte) for parte in caminho) + 16
    return nome + sum(_tamanho_campo(k, v) for k, v in campos.items()) + 32


def _bytes_do_model(caminho: tuple[str, ...], modelo: Any) -> int:
    return tamanho_estimado_do_documento(caminho, modelo.model_dump(mode="python"))


# --- as linhas de cada tabela -------------------------------------------------------------------


@dataclass(frozen=True)
class EspacoLinha:
    dt: str
    espaco: str
    tipo: str
    nome: str | None
    ativo: bool
    ativado_por: str | None  # 🔒 número completo (ver seção 7 do plano)
    ativado_em: datetime | None
    criado_em: datetime | None
    nivel: str | None
    estado_sessao: str
    n_termos: int
    n_termos_nova: int
    n_termos_praticada: int
    n_vencidas: int
    n_frases: int
    n_frases_usuario: int
    n_membros: int
    n_professores: int
    n_respostas: int
    n_respostas_marcadas: int
    bytes_estimados: int


@dataclass(frozen=True)
class PessoaLinha:
    dt: str
    pessoa: str  # id_curto(numero) — nunca o número completo (ver seção 7 do plano)
    numero_mascarado: str
    nome: str | None
    tem_privado: bool
    n_termos_privado: int
    n_termos_em_grupos: int
    n_frases: int
    n_respostas_grupo: int
    n_respondeu_marcada: int
    n_grupos: int


@dataclass(frozen=True)
class AdminLinha:
    dt: str
    admin_numero: str  # 🔒 número completo (decisão do usuário, 2026-09-27)
    admin_mascarado: str
    adicionado_em: datetime
    adicionado_por_mascarado: str
    n_grupos_ativos: int
    n_grupos_ativados_total: int
    grupos: list[str]
    n_termos_nos_grupos: int
    n_membros_nos_grupos: int


@dataclass(frozen=True)
class TermoLinha:
    dt: str
    espaco: str
    slug: str
    palavra: str
    classe: str
    cefr_estimado: str
    tags: list[str]
    origem: str
    status: str
    criado_em: datetime
    repeticoes: int
    intervalo_dias: float
    facilidade: float
    lapsos: int
    proxima_revisao: datetime | None
    revisada_em: datetime | None
    n_frases: int


@dataclass(frozen=True)
class GrupoPendenteLinha:
    dt: str
    espaco: str
    visto_em: datetime


@dataclass(frozen=True)
class FirestoreUsoLinha:
    dt: str
    colecao: str
    n_docs: int
    bytes_estimados: int


@dataclass(frozen=True)
class Snapshot:
    espacos: list[EspacoLinha]
    pessoas: list[PessoaLinha]
    admins: list[AdminLinha]
    termos: list[TermoLinha]
    grupos_pendentes: list[GrupoPendenteLinha]
    firestore_uso: list[FirestoreUsoLinha]


def tabelas(snapshot: Snapshot) -> list[tuple[str, list[Any]]]:
    """`(nome da tabela, linhas)`, na ordem em que `DestinoDeMetricas.gravar` deveria escrever —
    usado pelo `Agendador` e por `scripts/snapshot.py`, para os dois nunca divergirem."""
    return [
        ("espacos", list(snapshot.espacos)),
        ("pessoas", list(snapshot.pessoas)),
        ("admins", list(snapshot.admins)),
        ("termos", list(snapshot.termos)),
        ("grupos_pendentes", list(snapshot.grupos_pendentes)),
        ("firestore_uso", list(snapshot.firestore_uso)),
    ]


# --- acumulador interno de pessoas (uma por número, juntando privado + participação em grupos) --


@dataclass
class _Pessoa:
    numero: str
    nome: str | None = None
    tem_privado: bool = False
    n_termos_privado: int = 0
    n_termos_em_grupos: int = 0
    n_frases: int = 0
    n_respostas_grupo: int = 0
    n_respondeu_marcada: int = 0
    grupos: set[str] = field(default_factory=set)


def _dados_do_espaco(
    repo: Repository,
) -> tuple[Profile | None, Sessao, list[Entry], list[tuple[str, Membro]], list[Resposta]]:
    return (
        repo.obter_perfil(),
        repo.obter_sessao(),
        repo.listar_entradas(),
        repo.listar_membros(),
        repo.listar_respostas(),
    )


def montar_snapshot(banco: Banco, agora: datetime) -> Snapshot:
    """Uma passada por espaço (uma leitura de cada coleção, nunca duas): monta as linhas do dia,
    junta as pessoas que aparecem em mais de um espaço, e estima bytes por coleção. Não faz
    nenhuma chamada de rede além do que `banco` já faz — GCS e WAHA ficam por conta de quem chama.
    """
    dt = agora.date().isoformat()
    pessoas: dict[str, _Pessoa] = {}
    n_docs: defaultdict[str, int] = defaultdict(int)
    bytes_por_colecao: defaultdict[str, int] = defaultdict(int)

    def pessoa(numero: str) -> _Pessoa:
        return pessoas.setdefault(numero, _Pessoa(numero=numero))

    linhas_espacos: list[EspacoLinha] = []
    linhas_termos: list[TermoLinha] = []
    # (id do espaço) -> (nº de termos, nº de membros): reaproveitado pela tabela de admins, para
    # não ler `entries`/`membros` de um grupo duas vezes.
    contagens_por_espaco: dict[str, tuple[int, int]] = {}

    espacos_resumo = banco.listar_espacos()
    for resumo in espacos_resumo:
        repo = banco.do_espaco(resumo.id)
        perfil, sessao, entradas, membros, respostas = _dados_do_espaco(repo)
        espaco_hash = id_curto(resumo.id)
        n_docs["espacos"] += 1

        frases_por_entrada = {e.slug: repo.listar_frases(e.slug) for e in entradas}
        todas_as_frases = [f for fs in frases_por_entrada.values() for f in fs]
        n_docs["entries"] += len(entradas)
        n_docs["sentences"] += len(todas_as_frases)
        n_docs["membros"] += len(membros)
        n_docs["respostas"] += len(respostas)

        for slug, frases in frases_por_entrada.items():
            for i, frase in enumerate(frases):
                bytes_por_colecao["sentences"] += _bytes_do_model(
                    ("espacos", resumo.id, "entries", slug, "sentences", str(i)), frase
                )
        for membro_numero, membro in membros:
            bytes_por_colecao["membros"] += _bytes_do_model(
                ("espacos", resumo.id, "membros", membro_numero), membro
            )
        for i, resposta in enumerate(respostas):
            bytes_por_colecao["respostas"] += _bytes_do_model(
                ("espacos", resumo.id, "respostas", str(i)), resposta
            )
        if perfil is not None:
            bytes_por_colecao["profile"] += _bytes_do_model(
                ("espacos", resumo.id, "profile", "me"), perfil
            )

        bytes_do_espaco = 0
        for entrada in entradas:
            tamanho = _bytes_do_model(("espacos", resumo.id, "entries", entrada.slug), entrada)
            bytes_por_colecao["entries"] += tamanho
            bytes_do_espaco += tamanho
            linhas_termos.append(
                TermoLinha(
                    dt=dt,
                    espaco=espaco_hash,
                    slug=entrada.slug,
                    palavra=entrada.palavra,
                    classe=entrada.classe,
                    cefr_estimado=entrada.cefr_estimado,
                    tags=list(entrada.tags),
                    origem=entrada.origem,
                    status=entrada.status,
                    criado_em=entrada.criado_em,
                    repeticoes=entrada.repeticoes,
                    intervalo_dias=entrada.intervalo_dias,
                    facilidade=entrada.facilidade,
                    lapsos=entrada.lapsos,
                    proxima_revisao=entrada.proxima_revisao,
                    revisada_em=entrada.revisada_em,
                    n_frases=len(frases_por_entrada[entrada.slug]),
                )
            )

        contagens_por_espaco[resumo.id] = (len(entradas), len(membros))
        professores = sum(1 for _, m in membros if m.papel == "professor")
        n_frases_usuario = sum(1 for f in todas_as_frases if f.autor == "usuario")
        n_respostas_marcadas = sum(1 for r in respostas if r.marcado)

        linhas_espacos.append(
            EspacoLinha(
                dt=dt,
                espaco=espaco_hash,
                tipo=resumo.tipo,
                nome=resumo.nome,
                ativo=resumo.ativo,
                ativado_por=resumo.ativado_por,
                ativado_em=resumo.ativado_em,
                criado_em=resumo.criado_em,
                nivel=perfil.nivel if perfil else None,
                estado_sessao=str(sessao.estado),
                n_termos=len(entradas),
                n_termos_nova=sum(1 for e in entradas if e.status == "nova"),
                n_termos_praticada=sum(1 for e in entradas if e.status == "praticada"),
                n_vencidas=sum(1 for e in entradas if vencida(e, agora)),
                n_frases=len(todas_as_frases),
                n_frases_usuario=n_frases_usuario,
                n_membros=len(membros),
                n_professores=professores,
                n_respostas=len(respostas),
                n_respostas_marcadas=n_respostas_marcadas,
                bytes_estimados=bytes_do_espaco,
            )
        )

        if resumo.tipo == "privado":
            numero = digitos_do_chat_id(resumo.id)
            p = pessoa(numero)
            p.tem_privado = True
            p.nome = perfil.nome if perfil and perfil.nome else p.nome
            p.n_termos_privado = len(entradas)
            p.n_frases += n_frases_usuario
        else:
            for numero, membro in membros:
                p = pessoa(numero)
                p.nome = p.nome or membro.nome
                p.grupos.add(espaco_hash)
            for entrada in entradas:
                if entrada.autor_id:
                    p = pessoa(entrada.autor_id)
                    p.n_termos_em_grupos += 1
                    p.grupos.add(espaco_hash)
            for frase in todas_as_frases:
                if frase.autor_id:
                    pessoa(frase.autor_id).n_frases += 1
            for resposta in respostas:
                p = pessoa(resposta.autor_id)
                p.n_respostas_grupo += 1
                if resposta.marcado:
                    p.n_respondeu_marcada += 1

    linhas_pessoas = [
        PessoaLinha(
            dt=dt,
            pessoa=id_curto(p.numero),
            numero_mascarado=mascarar_numero(p.numero),
            nome=p.nome,
            tem_privado=p.tem_privado,
            n_termos_privado=p.n_termos_privado,
            n_termos_em_grupos=p.n_termos_em_grupos,
            n_frases=p.n_frases,
            n_respostas_grupo=p.n_respostas_grupo,
            n_respondeu_marcada=p.n_respondeu_marcada,
            n_grupos=len(p.grupos),
        )
        for p in sorted(pessoas.values(), key=lambda p: p.numero)
    ]

    grupos_por_admin: defaultdict[str, list[EspacoResumo]] = defaultdict(list)
    for resumo in espacos_resumo:
        if resumo.tipo == "grupo" and resumo.ativado_por:
            grupos_por_admin[resumo.ativado_por].append(resumo)

    linhas_admins: list[AdminLinha] = []
    for admin in banco.listar_admins_detalhado():
        n_docs["admins"] += 1
        grupos_do_admin = grupos_por_admin.get(admin.numero, [])
        ativos = [g for g in grupos_do_admin if g.ativo]
        n_termos = sum(contagens_por_espaco.get(g.id, (0, 0))[0] for g in ativos)
        n_membros = sum(contagens_por_espaco.get(g.id, (0, 0))[1] for g in ativos)
        linhas_admins.append(
            AdminLinha(
                dt=dt,
                admin_numero=admin.numero,
                admin_mascarado=mascarar_numero(admin.numero),
                adicionado_em=admin.adicionado_em,
                adicionado_por_mascarado=mascarar_numero(admin.adicionado_por),
                n_grupos_ativos=len(ativos),
                n_grupos_ativados_total=len(grupos_do_admin),
                grupos=[g.nome for g in ativos if g.nome],
                n_termos_nos_grupos=n_termos,
                n_membros_nos_grupos=n_membros,
            )
        )

    linhas_pendentes = [
        GrupoPendenteLinha(dt=dt, espaco=id_curto(grupo_id), visto_em=visto_em)
        for grupo_id, visto_em in banco.listar_grupos_pendentes()
    ]
    if linhas_pendentes:
        n_docs["grupos_pendentes"] += len(linhas_pendentes)

    linhas_uso = [
        FirestoreUsoLinha(
            dt=dt,
            colecao=colecao,
            n_docs=n_docs[colecao],
            bytes_estimados=bytes_por_colecao[colecao],
        )
        for colecao in sorted(n_docs)
    ]

    return Snapshot(
        espacos=linhas_espacos,
        pessoas=linhas_pessoas,
        admins=linhas_admins,
        termos=linhas_termos,
        grupos_pendentes=linhas_pendentes,
        firestore_uso=linhas_uso,
    )
