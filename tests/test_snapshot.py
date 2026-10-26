"""Testes de app/services/snapshot.py (M28, ADR-0029, seção 12 da spec): `montar_snapshot` é
pura sobre o `Banco` — testada só com `MemoryBanco`, sem rede nem GCS."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.domain.models import Entry, Membro, Profile, Resposta, Sentence, SentidoSalvo
from app.logging_config import id_curto, mascarar_numero
from app.repo.memory import MemoryBanco
from app.services.snapshot import (
    AdminLinha,
    EspacoLinha,
    FirestoreUsoLinha,
    GrupoPendenteLinha,
    PessoaLinha,
    TermoLinha,
    montar_snapshot,
    tamanho_estimado_do_documento,
)

RAIZ = Path(__file__).resolve().parent.parent
DIR_BQ = RAIZ / "infra" / "bq"

T0 = datetime(2026, 9, 28, 4, 0, tzinfo=UTC)
PRIVADO = "5531999998888@c.us"
GRUPO = "120363000000000001@g.us"
ANA = "5511988887777"
BIA = "5521977776666"
DONO = "5531990000001"
SENTIDO = SentidoSalvo(traducao="travar", definicao="to stop making progress")


def _entrada(slug: str = "stall", **campos: object) -> Entry:
    base = {
        "slug": slug,
        "palavra": slug,
        "classe": "verb",
        "cefr_estimado": "B2",
        "sentido": SENTIDO,
        "criado_em": T0,
        "atualizado_em": T0,
    }
    return Entry.model_validate(base | campos)


def test_snapshot_vazio_nao_quebra() -> None:
    banco = MemoryBanco()

    snapshot = montar_snapshot(banco, T0)

    assert snapshot.espacos == []
    assert snapshot.pessoas == []
    assert snapshot.admins == []
    assert snapshot.termos == []
    assert snapshot.grupos_pendentes == []
    assert snapshot.firestore_uso == []


def test_espaco_privado_nunca_tocado_nao_aparece() -> None:
    banco = MemoryBanco()
    banco.do_espaco(PRIVADO).obter_perfil()  # só leitura

    snapshot = montar_snapshot(banco, T0)

    assert snapshot.espacos == []


def test_espaco_privado_com_termos_e_frases() -> None:
    banco = MemoryBanco()
    repo = banco.do_espaco(PRIVADO)
    repo.salvar_perfil(Profile(nivel="B1-B2", criado_em=T0, nome="Ana", chat_id=PRIVADO))
    repo.criar_entrada(_entrada("stall", proxima_revisao=T0 - timedelta(days=1)))
    repo.criar_entrada(
        _entrada("hedge", status="praticada", proxima_revisao=T0 + timedelta(days=5))
    )
    repo.adicionar_frase("stall", Sentence(texto="I stalled", autor="usuario", criado_em=T0))
    repo.adicionar_frase("stall", Sentence(texto="ex 1", autor="bot", criado_em=T0))

    snapshot = montar_snapshot(banco, T0)

    (espaco,) = snapshot.espacos
    assert espaco.espaco == id_curto(PRIVADO)
    assert espaco.tipo == "privado"
    assert espaco.nivel == "B1-B2"
    assert espaco.n_termos == 2
    assert espaco.n_termos_nova == 1
    assert espaco.n_termos_praticada == 1
    assert espaco.n_vencidas == 1  # só "stall" já venceu
    assert espaco.n_frases == 2
    assert espaco.n_frases_usuario == 1
    assert espaco.bytes_estimados > 0

    slugs_termos = {t.slug for t in snapshot.termos}
    assert slugs_termos == {"stall", "hedge"}

    (pessoa,) = snapshot.pessoas
    assert pessoa.pessoa == id_curto("5531999998888")
    assert pessoa.numero_mascarado == mascarar_numero("5531999998888")
    assert pessoa.nome == "Ana"
    assert pessoa.tem_privado is True
    assert pessoa.n_termos_privado == 2
    assert pessoa.n_frases == 1  # só a do usuário
    assert pessoa.n_grupos == 0


def test_grupo_agrega_pessoas_por_autor_id() -> None:
    banco = MemoryBanco()
    banco.ativar_grupo(GRUPO, nome="Turma A", por=DONO, agora=T0)
    repo = banco.do_espaco(GRUPO)
    repo.salvar_membro(ANA, Membro(papel="aluno", nome="Ana", entrou_em=T0))
    repo.salvar_membro(BIA, Membro(papel="professor", nome="Bia", entrou_em=T0))
    repo.criar_entrada(_entrada("stall", autor_id=ANA))
    repo.adicionar_frase("stall", Sentence(texto="x", autor="usuario", autor_id=ANA, criado_em=T0))
    repo.registrar_resposta(
        Resposta(entry="stall", autor_id=ANA, marcado=True, qualidade="bom", criado_em=T0)
    )
    repo.registrar_resposta(
        Resposta(entry="stall", autor_id=BIA, marcado=False, qualidade="bom", criado_em=T0)
    )

    snapshot = montar_snapshot(banco, T0)

    (espaco,) = snapshot.espacos
    assert espaco.tipo == "grupo"
    assert espaco.nome == "Turma A"
    assert espaco.ativo is True
    assert espaco.ativado_por == DONO  # 🔒 número completo, só nesta tabela + admins
    assert espaco.n_membros == 2
    assert espaco.n_professores == 1
    assert espaco.n_respostas == 2
    assert espaco.n_respostas_marcadas == 1

    por_numero = {p.pessoa: p for p in snapshot.pessoas}
    ana = por_numero[id_curto(ANA)]
    assert ana.n_termos_em_grupos == 1
    assert ana.n_frases == 1
    assert ana.n_respostas_grupo == 1
    assert ana.n_respondeu_marcada == 1
    assert ana.n_grupos == 1
    assert ana.tem_privado is False
    bia = por_numero[id_curto(BIA)]
    assert bia.n_termos_em_grupos == 0
    assert bia.n_respostas_grupo == 1
    assert bia.n_respondeu_marcada == 0
    # nenhum número completo escapa para a tabela de pessoas (só o hash e o mascarado)
    for p in snapshot.pessoas:
        assert p.pessoa not in (ANA, BIA)


def test_pessoa_com_privado_e_grupo_e_uma_so_linha() -> None:
    banco = MemoryBanco()
    banco.do_espaco(f"{ANA}@c.us").salvar_perfil(Profile(nivel="B1-B2", criado_em=T0))
    banco.ativar_grupo(GRUPO, nome="Turma A", por=DONO, agora=T0)
    banco.do_espaco(GRUPO).salvar_membro(ANA, Membro(papel="aluno", entrou_em=T0))

    snapshot = montar_snapshot(banco, T0)

    (pessoa,) = snapshot.pessoas
    assert pessoa.tem_privado is True
    assert pessoa.n_grupos == 1


def test_admins_agregam_grupos_ativos_e_historico() -> None:
    banco = MemoryBanco()
    banco.adicionar_admin(DONO, por=DONO, agora=T0)
    banco.ativar_grupo(GRUPO, nome="Turma A", por=DONO, agora=T0)
    banco.do_espaco(GRUPO).criar_entrada(_entrada("stall"))
    banco.do_espaco(GRUPO).salvar_membro(ANA, Membro(papel="aluno", entrou_em=T0))
    banco.ativar_grupo("outro@g.us", nome="Turma B", por=DONO, agora=T0)
    banco.desativar_grupo("outro@g.us")

    snapshot = montar_snapshot(banco, T0)

    (admin,) = snapshot.admins
    assert admin.admin_numero == DONO  # 🔒 número completo (decisão do usuário)
    assert admin.admin_mascarado == mascarar_numero(DONO)
    assert admin.n_grupos_ativos == 1  # só "Turma A" continua ativa
    assert admin.n_grupos_ativados_total == 2  # inclui a desativada
    assert admin.grupos == ["Turma A"]
    assert admin.n_termos_nos_grupos == 1
    assert admin.n_membros_nos_grupos == 1


def test_grupos_pendentes_aparecem_no_snapshot() -> None:
    banco = MemoryBanco()
    banco.registrar_grupo_pendente(GRUPO, T0)

    snapshot = montar_snapshot(banco, T0)

    (pendente,) = snapshot.grupos_pendentes
    assert pendente.espaco == id_curto(GRUPO)
    assert pendente.visto_em == T0


def test_firestore_uso_conta_documentos_por_colecao() -> None:
    banco = MemoryBanco()
    repo = banco.do_espaco(PRIVADO)
    repo.salvar_perfil(Profile(nivel="B1-B2", criado_em=T0))
    repo.criar_entrada(_entrada("stall"))
    repo.criar_entrada(_entrada("hedge"))

    snapshot = montar_snapshot(banco, T0)

    por_colecao = {u.colecao: u for u in snapshot.firestore_uso}
    assert por_colecao["espacos"].n_docs == 1
    assert por_colecao["entries"].n_docs == 2
    assert por_colecao["entries"].bytes_estimados > 0


def test_dt_e_a_data_de_agora_em_iso() -> None:
    banco = MemoryBanco()
    banco.do_espaco(PRIVADO).salvar_perfil(Profile(nivel="B1-B2", criado_em=T0))

    snapshot = montar_snapshot(banco, T0)

    assert snapshot.espacos[0].dt == "2026-09-28"


# --- estimativa de bytes (fórmula oficial, ver docstring do módulo) ----------------------------


def test_tamanho_estimado_bate_com_a_conta_a_mao() -> None:
    # caminho: espacos/abc/entries/stall -> "espacos"(7+1) + "abc"(3+1) + "entries"(7+1) +
    # "stall"(5+1) + 16 = 8+4+8+6+16 = 42
    # campo único {"nome": "valor"}: nome "nome"(4+1=5) + valor string "valor"(5+1=6) = 11
    # total = 42 + 11 + 32 = 85
    tamanho = tamanho_estimado_do_documento(
        ("espacos", "abc", "entries", "stall"), {"nome": "valor"}
    )
    assert tamanho == 85


def test_tamanho_cresce_com_mais_campos_e_listas() -> None:
    base = tamanho_estimado_do_documento(("a",), {"x": "y"})
    maior = tamanho_estimado_do_documento(("a",), {"x": "y", "tags": ["trabalho", "phrasal_verb"]})
    assert maior > base


# --- esquema do BigQuery em sincronia com o código (infra/bq/*.json) ---------------------------

_TABELA_PARA_DATACLASS = {
    "espacos": EspacoLinha,
    "pessoas": PessoaLinha,
    "admins": AdminLinha,
    "termos": TermoLinha,
    "grupos_pendentes": GrupoPendenteLinha,
    "firestore_uso": FirestoreUsoLinha,
}


def test_todas_as_tabelas_tem_esquema_versionado() -> None:
    esquemas = {p.stem for p in DIR_BQ.glob("*.json")}
    assert esquemas == set(_TABELA_PARA_DATACLASS)


def test_esquema_do_bigquery_bate_com_os_campos_da_dataclass() -> None:
    for tabela, classe in _TABELA_PARA_DATACLASS.items():
        esquema = json.loads((DIR_BQ / f"{tabela}.json").read_text("utf-8"))
        campos_do_esquema = {c["name"] for c in esquema}
        campos_do_codigo = {f.name for f in dataclasses.fields(classe)}
        assert campos_do_esquema == campos_do_codigo, f"{tabela}: esquema e código divergem"
