"""Teste de contrato do `Repository` (seção 7.1): o mesmo teste vale para todas as implementações.

`MemoryRepository` sempre roda. `FirestoreRepository` só roda contra o emulador
(`FIRESTORE_EMULATOR_HOST` definido) — nunca contra o Firestore de verdade (ADR-0003).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from app.domain.models import (
    Entry,
    Estado,
    Membro,
    Profile,
    Resposta,
    Sentence,
    SentidoSalvo,
    Sessao,
    Synonym,
    mesma_traducao,
)
from app.repo.base import Banco, EntradaJaExiste, Repository, resolver_slug
from app.repo.memory import MemoryBanco

T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
PROJETO_TESTE = "stick-word-group-teste"


def _entrada(
    palavra: str = "stall", *, traducao: str = "travar", criado_em: datetime = T0
) -> Entry:
    return Entry(
        slug=palavra,
        palavra=palavra,
        classe="verb",
        cefr_estimado="B2",
        sentido=SentidoSalvo(traducao=traducao, definicao="to stop making progress"),
        outros_sentidos=[SentidoSalvo(traducao="enrolar", definicao="to delay")],
        sinonimos=[
            Synonym(expressao="stumble", significado="to lose momentum", exemplo="It [[stumbled]].")
        ],
        nota="phrasal em contexto de trabalho",
        tags=["trabalho"],
        origem_texto="stall | the talks stalled",
        criado_em=criado_em,
        atualizado_em=criado_em,
    )


ALUNO_A = "5531999998888@c.us"
ALUNO_B = "5511988887777@c.us"
GRUPO = "120363000000000000@g.us"


@pytest.fixture(params=["memory", "firestore"])
def banco(request: pytest.FixtureRequest) -> Iterator[Banco]:
    if request.param == "memory":
        yield MemoryBanco()
        return

    host = os.environ.get("FIRESTORE_EMULATOR_HOST")
    if not host:
        pytest.skip("FIRESTORE_EMULATOR_HOST não definido (emulador do Firestore não está rodando)")

    from google.cloud import firestore

    from app.repo.firestore import FirestoreBanco

    limpar = f"http://{host}/emulator/v1/projects/{PROJETO_TESTE}/databases/(default)/documents"
    httpx.delete(limpar)
    yield FirestoreBanco(firestore.Client(project=PROJETO_TESTE))
    httpx.delete(limpar)


@pytest.fixture
def repo(banco: Banco) -> Repository:
    """O caderno de um espaço (o do primeiro aluno): os testes de contrato antigos usam este."""
    return banco.do_espaco(ALUNO_A)


def test_perfil_ausente_e_none_e_depois_persiste(repo: Repository) -> None:
    assert repo.obter_perfil() is None

    repo.salvar_perfil(Profile(nivel="B1-B2", criado_em=T0))

    assert repo.obter_perfil() == Profile(nivel="B1-B2", criado_em=T0)


def test_sessao_ausente_comeca_em_idle(repo: Repository) -> None:
    sessao = repo.obter_sessao()

    assert sessao.estado == Estado.IDLE
    assert sessao.entry_id is None


def test_sessao_persiste_estado_e_sinonimos_mostrados(repo: Repository) -> None:
    sessao = Sessao(
        estado=Estado.AWAIT_ACTION,
        entry_id="stall",
        sentido_id="s1",
        sinonimos_mostrados=["stumble", "grind to a halt"],
        atualizado_em=T0,
    )

    repo.salvar_sessao(sessao)

    assert repo.obter_sessao() == sessao


def test_sessao_persiste_a_fila_de_revisao(repo: Repository) -> None:
    sessao = Sessao(
        estado=Estado.REVIEWING,
        revisao_fila=["hedge", "deadline"],
        revisao_atual="stall",
        revisao_feitas=["reluctant"],
        revisao_lapsos=["reluctant"],
        revisao_total=4,
        atualizado_em=T0,
    )

    repo.salvar_sessao(sessao)

    assert repo.obter_sessao() == sessao


def test_perfil_persiste_os_campos_da_agenda(repo: Repository) -> None:
    perfil = Profile(
        nivel="B1-B2",
        criado_em=T0,
        chat_id="120363000000000000@g.us",
        diaria_hora=9,
        diaria_minuto=30,
        diaria_fim_de_semana=True,
        proxima_diaria=T0 + timedelta(hours=3),
        revisoes_sem_resposta=2,
        semanal_dia=1,
        proxima_semanal=T0 + timedelta(days=2),
        tamanho_revisao=8,
    )

    repo.salvar_perfil(perfil)

    assert repo.obter_perfil() == perfil


def test_entrada_criada_pode_ser_lida(repo: Repository) -> None:
    repo.criar_entrada(_entrada())

    assert repo.obter_entrada("stall") == _entrada()
    assert repo.obter_entrada("outra") is None


def test_entrada_persiste_os_campos_de_revisao_espacada(repo: Repository) -> None:
    entrada = _entrada().model_copy(
        update={
            "repeticoes": 3,
            "intervalo_dias": 7.5,
            "facilidade": 2.3,
            "lapsos": 1,
            "proxima_revisao": T0 + timedelta(days=7),
            "revisada_em": T0,
        }
    )
    repo.criar_entrada(entrada)

    assert repo.obter_entrada("stall") == entrada


def test_entrada_persiste_os_links_do_audio_de_pronuncia(repo: Repository) -> None:
    repo.criar_entrada(_entrada())
    assert _entrada().audio_palavra is None  # entrada antiga, sem áudio, segue válida

    com_audio = _entrada().model_copy(
        update={
            "audio_palavra": "gs://proj-audio/audio/en-US-Neural2-F/a.ogg",
            "audio_exemplo": "gs://proj-audio/audio/en-US-Neural2-F/b.ogg",
        }
    )
    repo.salvar_entrada(com_audio)

    assert repo.obter_entrada("stall") == com_audio


def test_criar_entrada_com_slug_existente_falha_sem_sobrescrever(repo: Repository) -> None:
    repo.criar_entrada(_entrada())

    with pytest.raises(EntradaJaExiste):
        repo.criar_entrada(_entrada(traducao="outra coisa"))

    entrada = repo.obter_entrada("stall")
    assert entrada is not None
    assert entrada.sentido.traducao == "travar"


def test_salvar_entrada_atualiza(repo: Repository) -> None:
    repo.criar_entrada(_entrada())
    atualizada = _entrada().model_copy(update={"status": "praticada", "exportado": True})

    repo.salvar_entrada(atualizada)

    assert repo.obter_entrada("stall") == atualizada


def test_listar_entradas_em_ordem_de_criacao_e_filtra_por_status(repo: Repository) -> None:
    repo.criar_entrada(_entrada("beta", criado_em=T0 + timedelta(minutes=2)))
    repo.criar_entrada(_entrada("alfa", criado_em=T0 + timedelta(minutes=1)))
    repo.criar_entrada(
        _entrada("gama", criado_em=T0 + timedelta(minutes=3)).model_copy(
            update={"status": "praticada"}
        )
    )

    todas = [e.slug for e in repo.listar_entradas()]
    novas = [e.slug for e in repo.listar_entradas("nova")]
    praticadas = [e.slug for e in repo.listar_entradas("praticada")]

    assert todas == ["alfa", "beta", "gama"]
    assert novas == ["alfa", "beta"]
    assert praticadas == ["gama"]


def test_frases_sao_guardadas_por_entrada_em_ordem(repo: Repository) -> None:
    repo.criar_entrada(_entrada())
    segunda = Sentence(texto="segunda", autor="usuario", criado_em=T0 + timedelta(minutes=1))
    primeira = Sentence(
        texto="primeira",
        autor="usuario",
        veredito="quase",
        correcoes=["didn't sent → didn't send"],
        versao_natural="The project [[stalled]].",
        explicacao="Depois de didn't, o verbo fica na forma base.",
        criado_em=T0,
    )

    repo.adicionar_frase("stall", segunda)
    repo.adicionar_frase("stall", primeira)

    assert repo.listar_frases("stall") == [primeira, segunda]
    assert repo.listar_frases("outra") == []


def test_apagar_entrada_remove_tambem_as_frases(repo: Repository) -> None:
    repo.criar_entrada(_entrada())
    repo.adicionar_frase("stall", Sentence(texto="x", autor="bot", criado_em=T0))

    assert repo.apagar_entrada("stall") is True

    assert repo.obter_entrada("stall") is None
    assert repo.listar_frases("stall") == []
    assert repo.apagar_entrada("stall") is False


def test_mensagem_so_e_marcada_como_processada_uma_vez(banco: Banco) -> None:
    assert banco.marcar_processada("true_5531@c.us_ABC", T0) is True
    assert banco.marcar_processada("true_5531@c.us_ABC", T0) is False
    assert banco.marcar_processada("true_5531@c.us_OUTRA", T0) is True


def test_cache_de_lid(banco: Banco) -> None:
    assert banco.obter_numero_do_lid("257161284317237@lid") is None

    banco.salvar_numero_do_lid("257161284317237@lid", "5531999998888")

    assert banco.obter_numero_do_lid("257161284317237@lid") == "5531999998888"


def test_resolver_slug_usa_a_palavra_quando_esta_livre(repo: Repository) -> None:
    assert resolver_slug(repo, "Stall", "travar") == "stall"
    assert resolver_slug(repo, "give up", "desistir") == "give-up"


def test_resolver_slug_reaproveita_o_slug_do_mesmo_sentido(repo: Repository) -> None:
    repo.criar_entrada(_entrada())

    assert resolver_slug(repo, "stall", "travar") == "stall"


def test_resolver_slug_sufixa_quando_o_sentido_e_outro(repo: Repository) -> None:
    repo.criar_entrada(_entrada())

    assert resolver_slug(repo, "stall", "barraca") == "stall--s2"

    repo.criar_entrada(
        _entrada().model_copy(
            update={
                "slug": "stall--s2",
                "sentido": SentidoSalvo(traducao="barraca", definicao="a stand"),
            }
        )
    )

    assert resolver_slug(repo, "stall", "barraca") == "stall--s2"
    assert resolver_slug(repo, "stall", "baia") == "stall--s3"


# --- M14: multiusuário por espaço (ADR-0017) --------------------------------------------------


def test_espacos_sao_isolados_perfil_sessao_entradas_e_frases(banco: Banco) -> None:
    a, b = banco.do_espaco(ALUNO_A), banco.do_espaco(ALUNO_B)
    a.salvar_perfil(Profile(nivel="B2-C1", criado_em=T0))
    a.salvar_sessao(Sessao(estado=Estado.AWAIT_ACTION))
    a.criar_entrada(_entrada("stall"))
    a.adicionar_frase("stall", Sentence(texto="It stalled.", autor="usuario", criado_em=T0))

    assert b.obter_perfil() is None
    assert b.obter_sessao().estado == Estado.IDLE
    assert b.obter_entrada("stall") is None
    assert b.listar_entradas() == []
    assert b.listar_frases("stall") == []


def test_mesmo_slug_pode_existir_em_espacos_diferentes(banco: Banco) -> None:
    banco.do_espaco(ALUNO_A).criar_entrada(_entrada("stall", traducao="travar"))
    banco.do_espaco(ALUNO_B).criar_entrada(_entrada("stall", traducao="enrolar"))

    assert banco.do_espaco(ALUNO_A).obter_entrada("stall").sentido.traducao == "travar"  # type: ignore[union-attr]
    assert banco.do_espaco(ALUNO_B).obter_entrada("stall").sentido.traducao == "enrolar"  # type: ignore[union-attr]


def test_apagar_entrada_de_um_espaco_nao_mexe_no_outro(banco: Banco) -> None:
    banco.do_espaco(ALUNO_A).criar_entrada(_entrada("stall"))
    banco.do_espaco(ALUNO_B).criar_entrada(_entrada("stall"))

    assert banco.do_espaco(ALUNO_A).apagar_entrada("stall") is True

    assert banco.do_espaco(ALUNO_B).obter_entrada("stall") is not None


def test_apagar_tudo_limpa_so_o_espaco_pedido(banco: Banco) -> None:
    a, b = banco.do_espaco(ALUNO_A), banco.do_espaco(ALUNO_B)
    for espaco in (a, b):
        espaco.salvar_perfil(Profile(nivel="B1-B2", criado_em=T0))
        espaco.salvar_sessao(Sessao(estado=Estado.AWAIT_ACTION))
        espaco.criar_entrada(_entrada("stall"))
        espaco.adicionar_frase("stall", Sentence(texto="x", autor="usuario", criado_em=T0))

    a.apagar_tudo()

    assert a.obter_perfil() is None
    assert a.obter_sessao().estado == Estado.IDLE
    assert a.listar_entradas() == []
    assert a.listar_frases("stall") == []
    assert b.obter_perfil() is not None
    assert len(b.listar_entradas()) == 1
    assert len(b.listar_frases("stall")) == 1


GRUPO_B = "120363000000000002@g.us"


def _agenda(chat: str, proxima: datetime | None, *, ligada: bool = True) -> Profile:
    """Um grupo só com a revisão diária (o semanal desligado), com destino conhecido."""
    return Profile(
        nivel="B1-B2",
        chat_id=chat,
        diaria_ligada=ligada,
        proxima_diaria=proxima,
        semanal_ligada=False,
    )


def test_espacos_com_lembrete_devolve_so_os_grupos_vencidos(banco: Banco) -> None:
    banco.do_espaco(GRUPO).salvar_perfil(_agenda(GRUPO, T0 - timedelta(minutes=5)))
    banco.do_espaco(GRUPO_B).salvar_perfil(_agenda(GRUPO_B, T0 + timedelta(hours=1)))

    assert banco.listar_espacos_com_lembrete(T0) == [GRUPO]


def test_grupo_com_diaria_ligada_mas_sem_horario_ainda_conta_como_vencido(banco: Banco) -> None:
    banco.do_espaco(GRUPO).salvar_perfil(_agenda(GRUPO, None))

    assert banco.listar_espacos_com_lembrete(T0) == [GRUPO]


def test_espaco_privado_sem_agenda_ou_sem_destino_nunca_aparece(banco: Banco) -> None:
    """ADR-0062: um espaço privado de antes da separação nunca entra na consulta."""
    banco.do_espaco(ALUNO_A).salvar_perfil(_agenda(ALUNO_A, T0 - timedelta(days=1)))
    banco.do_espaco(GRUPO).salvar_perfil(_agenda(GRUPO, None, ligada=False))
    banco.do_espaco(GRUPO_B).salvar_perfil(Profile(nivel="B1-B2", chat_id=None))

    assert banco.listar_espacos_com_lembrete(T0) == []


def test_desligar_a_diaria_tira_o_grupo_da_consulta(banco: Banco) -> None:
    espaco = banco.do_espaco(GRUPO)
    espaco.salvar_perfil(_agenda(GRUPO, T0))
    assert banco.listar_espacos_com_lembrete(T0) == [GRUPO]

    espaco.salvar_perfil(_agenda(GRUPO, T0, ligada=False))

    assert banco.listar_espacos_com_lembrete(T0) == []


# --- M15: admins, grupos ativos e pendentes (ADR-0018) ----------------------------------------

T1 = T0 + timedelta(hours=1)


def test_admins_adicionar_listar_e_remover(banco: Banco) -> None:
    assert banco.listar_admins() == []

    assert banco.adicionar_admin("5531999998888", por="5511988887777", agora=T0) is True
    assert banco.adicionar_admin("5521977776666", por="5511988887777", agora=T1) is True

    assert banco.listar_admins() == ["5531999998888", "5521977776666"]  # na ordem em que entraram
    assert banco.remover_admin("5531999998888") is True
    assert banco.listar_admins() == ["5521977776666"]


def test_adicionar_admin_repetido_nao_duplica_e_avisa(banco: Banco) -> None:
    banco.adicionar_admin("5531999998888", por="5511988887777", agora=T0)

    assert banco.adicionar_admin("5531999998888", por="5511988887777", agora=T1) is False
    assert banco.listar_admins() == ["5531999998888"]


def test_remover_admin_que_nao_existe_devolve_falso(banco: Banco) -> None:
    assert banco.remover_admin("5531999998888") is False


def test_listar_admins_detalhado_traz_quem_adicionou_e_quando(banco: Banco) -> None:
    banco.adicionar_admin("5531999998888", por="5511988887777", agora=T0)
    banco.adicionar_admin("5521977776666", por="5531999998888", agora=T1)

    detalhado = banco.listar_admins_detalhado()

    assert [(a.numero, a.adicionado_por, a.adicionado_em) for a in detalhado] == [
        ("5531999998888", "5511988887777", T0),
        ("5521977776666", "5531999998888", T1),
    ]


def test_grupo_comeca_inativo_e_ativar_desativar(banco: Banco) -> None:
    assert banco.grupo_esta_ativo(GRUPO) is False

    banco.ativar_grupo(GRUPO, nome="Turma A", por="5531999998888", agora=T0)

    assert banco.grupo_esta_ativo(GRUPO) is True
    (grupo,) = banco.listar_grupos_ativos()
    assert (grupo.id, grupo.nome, grupo.ativado_por, grupo.ativado_em) == (
        GRUPO,
        "Turma A",
        "5531999998888",
        T0,
    )
    assert banco.desativar_grupo(GRUPO) is True
    assert banco.grupo_esta_ativo(GRUPO) is False
    assert banco.listar_grupos_ativos() == []


def test_renomear_grupo_ativo_muda_so_o_nome(banco: Banco) -> None:
    banco.ativar_grupo(GRUPO, nome="Group", por="5531999998888", agora=T0)

    assert banco.renomear_grupo(GRUPO, "Turma A") is True

    (grupo,) = banco.listar_grupos_ativos()
    assert (grupo.nome, grupo.ativado_por, grupo.ativado_em) == ("Turma A", "5531999998888", T0)


def test_renomear_grupo_que_nao_esta_ativo_devolve_falso(banco: Banco) -> None:
    assert banco.renomear_grupo(GRUPO, "Turma A") is False
    assert banco.listar_grupos_ativos() == []


def test_desativar_grupo_que_nao_esta_ativo_devolve_falso(banco: Banco) -> None:
    assert banco.desativar_grupo(GRUPO) is False


def test_desativar_grupo_mantem_o_caderno_da_turma(banco: Banco) -> None:
    banco.ativar_grupo(GRUPO, nome=None, por="5531999998888", agora=T0)
    banco.do_espaco(GRUPO).criar_entrada(_entrada("stall"))

    banco.desativar_grupo(GRUPO)

    assert banco.do_espaco(GRUPO).obter_entrada("stall") is not None


def test_ativar_de_novo_um_grupo_desativado_volta_a_valer(banco: Banco) -> None:
    banco.ativar_grupo(GRUPO, nome="A", por="5531999998888", agora=T0)
    banco.desativar_grupo(GRUPO)

    banco.ativar_grupo(GRUPO, nome="A", por="5531999998888", agora=T1)

    assert banco.grupo_esta_ativo(GRUPO) is True
    assert len(banco.listar_grupos_ativos()) == 1


def test_grupo_ativado_com_perfil_nao_perde_o_espelho_dos_lembretes(banco: Banco) -> None:
    """A ativação e o `salvar_perfil` escrevem no mesmo documento do espaço: um não apaga o outro."""
    espaco = banco.do_espaco(GRUPO)
    espaco.salvar_perfil(_agenda(GRUPO, T0))
    banco.ativar_grupo(GRUPO, nome=None, por="5531999998888", agora=T0)

    assert banco.listar_espacos_com_lembrete(T0) == [GRUPO]
    assert banco.grupo_esta_ativo(GRUPO) is True
    espaco.salvar_perfil(_agenda(GRUPO, T1))
    assert banco.grupo_esta_ativo(GRUPO) is True


def test_listar_espacos_ignora_o_que_nunca_foi_escrito(banco: Banco) -> None:
    banco.do_espaco(ALUNO_A).obter_perfil()  # só leitura: não deveria criar nada

    assert banco.listar_espacos() == []


def test_listar_espacos_traz_privado_e_grupo(banco: Banco) -> None:
    banco.do_espaco(ALUNO_A).salvar_perfil(Profile(nivel="B1-B2", criado_em=T0))
    banco.ativar_grupo(GRUPO, nome="Turma A", por="5531999998888", agora=T1)

    espacos = {e.id: e for e in banco.listar_espacos()}

    assert espacos[ALUNO_A].tipo == "privado"
    assert espacos[ALUNO_A].criado_em == T0
    assert espacos[ALUNO_A].ativo is False
    assert espacos[GRUPO].tipo == "grupo"
    assert espacos[GRUPO].ativo is True
    assert (espacos[GRUPO].nome, espacos[GRUPO].ativado_por, espacos[GRUPO].ativado_em) == (
        "Turma A",
        "5531999998888",
        T1,
    )


def test_listar_espacos_mantem_o_grupo_desativado_visivel(banco: Banco) -> None:
    """Ao contrário de `listar_grupos_ativos`: o snapshot (M28) precisa ver os desativados
    também, para o painel mostrar o histórico completo, não só quem está ativo agora."""
    banco.ativar_grupo(GRUPO, nome="Turma A", por="5531999998888", agora=T0)

    banco.desativar_grupo(GRUPO)

    (espaco,) = banco.listar_espacos()
    assert espaco.ativo is False
    assert espaco.nome == "Turma A"  # o histórico não some


def test_ultimo_snapshot_e_none_e_depois_persiste(banco: Banco) -> None:
    assert banco.obter_ultimo_snapshot() is None

    banco.marcar_snapshot(date(2026, 9, 28))

    assert banco.obter_ultimo_snapshot() == date(2026, 9, 28)

    banco.marcar_snapshot(date(2026, 9, 29))

    assert banco.obter_ultimo_snapshot() == date(2026, 9, 29)


def test_uso_do_dia_comeca_em_zero_e_soma(banco: Banco) -> None:
    """M46 (ADR-0044): o orçamento diário de IA persiste o gasto por dia, somando."""
    dia = date(2026, 10, 12)
    assert banco.obter_uso_do_dia(dia) == 0

    banco.somar_uso_do_dia(dia, 0.25)
    banco.somar_uso_do_dia(dia, 0.5)

    assert banco.obter_uso_do_dia(dia) == pytest.approx(0.75)
    assert banco.obter_uso_do_dia(date(2026, 10, 13)) == 0


def test_uso_por_espaco_do_dia_soma_junto_com_o_total(banco: Banco) -> None:
    """M50 (ADR-0048): o gasto de cada espaço vai na mesma escrita do total do dia."""
    dia = date(2026, 10, 12)
    assert banco.obter_uso_por_espaco_do_dia(dia) == {}

    banco.somar_uso_do_dia(dia, 0.3, {"120363000000000001@g_us": 0.2, "5531999998888@c_us": 0.1})
    banco.somar_uso_do_dia(dia, 0.4, {"120363000000000001@g_us": 0.4})
    banco.somar_uso_do_dia(dia, 0.1)  # sem espaço: só o total

    assert banco.obter_uso_do_dia(dia) == pytest.approx(0.8)
    assert banco.obter_uso_por_espaco_do_dia(dia) == pytest.approx(
        {"120363000000000001@g_us": 0.6, "5531999998888@c_us": 0.1}
    )
    assert banco.obter_uso_por_espaco_do_dia(date(2026, 10, 13)) == {}


def test_grupo_pendente_registra_uma_vez_e_guarda_o_primeiro_horario(banco: Banco) -> None:
    assert banco.registrar_grupo_pendente(GRUPO, T0) is True
    assert banco.registrar_grupo_pendente(GRUPO, T1) is False  # o relógio de 24h não reinicia

    assert banco.listar_grupos_pendentes() == [(GRUPO, T0)]


def test_ativar_tira_o_grupo_dos_pendentes(banco: Banco) -> None:
    banco.registrar_grupo_pendente(GRUPO, T0)

    banco.ativar_grupo(GRUPO, nome=None, por="5531999998888", agora=T1)

    assert banco.listar_grupos_pendentes() == []


def test_remover_grupo_pendente(banco: Banco) -> None:
    banco.registrar_grupo_pendente(GRUPO, T0)

    banco.remover_grupo_pendente(GRUPO)

    assert banco.listar_grupos_pendentes() == []
    banco.remover_grupo_pendente(GRUPO)  # remover de novo não é erro


# --- M16/M17: membros da turma, respostas e autor das frases (ADR-0019, ADR-0020) -------------


def test_membro_ausente_e_none_e_depois_persiste(repo: Repository) -> None:
    assert repo.obter_membro("5531999998888") is None

    repo.salvar_membro("5531999998888", Membro(papel="professor", nome="Ana", entrou_em=T0))

    membro = repo.obter_membro("5531999998888")
    assert membro is not None
    assert (membro.papel, membro.nome, membro.entrou_em) == ("professor", "Ana", T0)
    assert membro.marcado_em is None


def test_listar_membros_devolve_numero_e_membro_em_ordem_de_entrada(repo: Repository) -> None:
    repo.salvar_membro("5511988887777", Membro(nome="Bia", entrou_em=T1))
    repo.salvar_membro("5531999998888", Membro(nome="Ana", entrou_em=T0))

    assert [(n, m.nome) for n, m in repo.listar_membros()] == [
        ("5531999998888", "Ana"),
        ("5511988887777", "Bia"),
    ]


def test_salvar_membro_atualiza_sem_duplicar(repo: Repository) -> None:
    repo.salvar_membro("5531999998888", Membro(nome=None, entrou_em=T0))
    repo.salvar_membro("5531999998888", Membro(nome="Ana", entrou_em=T0, marcado_em=T1))

    ((_, membro),) = repo.listar_membros()
    assert (membro.nome, membro.marcado_em) == ("Ana", T1)


def test_membros_sao_isolados_por_espaco(banco: Banco) -> None:
    banco.do_espaco(GRUPO).salvar_membro("5531999998888", Membro(entrou_em=T0))

    assert banco.do_espaco("120363000000000002@g.us").listar_membros() == []


def test_respostas_registram_quem_respondeu_e_se_era_o_marcado(repo: Repository) -> None:
    repo.registrar_resposta(
        Resposta(
            entry="stall", autor_id="5531999998888", marcado=True, qualidade="bom", criado_em=T0
        )
    )
    repo.registrar_resposta(
        Resposta(
            entry="stall", autor_id="5511988887777", marcado=False, qualidade="facil", criado_em=T1
        )
    )

    respostas = repo.listar_respostas()

    assert [(r.autor_id, r.marcado, r.qualidade) for r in respostas] == [
        ("5531999998888", True, "bom"),
        ("5511988887777", False, "facil"),
    ]


def test_frase_guarda_o_autor_quando_veio_de_um_grupo(repo: Repository) -> None:
    repo.criar_entrada(_entrada("stall"))
    repo.adicionar_frase(
        "stall",
        Sentence(texto="It stalled.", autor="usuario", autor_id="5531999998888", criado_em=T0),
    )
    repo.adicionar_frase("stall", Sentence(texto="No author.", autor="usuario", criado_em=T1))

    assert [f.autor_id for f in repo.listar_frases("stall")] == ["5531999998888", None]


def test_apagar_tudo_leva_membros_e_respostas(repo: Repository) -> None:
    repo.salvar_membro("5531999998888", Membro(entrou_em=T0))
    repo.registrar_resposta(
        Resposta(
            entry="stall", autor_id="5531999998888", marcado=True, qualidade="bom", criado_em=T0
        )
    )

    repo.apagar_tudo()

    assert repo.listar_membros() == []
    assert repo.listar_respostas() == []


def test_desativar_o_grupo_tira_os_lembretes_dele_da_consulta_e_reativar_devolve(
    banco: Banco,
) -> None:
    banco.ativar_grupo(GRUPO, nome=None, por="5531999998888", agora=T0)
    banco.do_espaco(GRUPO).salvar_perfil(_agenda(GRUPO, T0))
    assert banco.listar_espacos_com_lembrete(T0) == [GRUPO]

    banco.desativar_grupo(GRUPO)
    assert banco.listar_espacos_com_lembrete(T0) == []

    banco.ativar_grupo(GRUPO, nome=None, por="5531999998888", agora=T1)
    assert banco.listar_espacos_com_lembrete(T1) == [GRUPO]


def _revisao_marcada(quem: str, expira: datetime | None) -> Sessao:
    return Sessao(estado=Estado.REVIEWING, marcado_id=quem, marcacao_expira_em=expira)


def test_grupo_com_marcacao_vencida_aparece_na_consulta_de_timeout(banco: Banco) -> None:
    banco.do_espaco(GRUPO).salvar_sessao(_revisao_marcada("5531999998888", T0))

    assert banco.listar_grupos_com_timeout(T0) == [GRUPO]
    assert banco.listar_grupos_com_timeout(T0 - timedelta(minutes=1)) == []


def test_a_sessao_da_marcacao_persiste_os_campos_novos(repo: Repository) -> None:
    repo.salvar_sessao(
        Sessao(
            estado=Estado.REVIEWING,
            marcado_id="5531999998888",
            marcacao_expira_em=T1,
            marcacao_tentativas=1,
        )
    )

    sessao = repo.obter_sessao()

    assert (sessao.marcado_id, sessao.marcacao_expira_em, sessao.marcacao_tentativas) == (
        "5531999998888",
        T1,
        1,
    )


def test_marcacao_respondida_ou_sessao_fechada_sai_da_consulta_de_timeout(banco: Banco) -> None:
    espaco = banco.do_espaco(GRUPO)
    espaco.salvar_sessao(_revisao_marcada("5531999998888", T0))
    assert banco.listar_grupos_com_timeout(T0) == [GRUPO]

    espaco.salvar_sessao(_revisao_marcada("5511988887777", T1))  # o card andou: novo prazo
    assert banco.listar_grupos_com_timeout(T0) == []
    assert banco.listar_grupos_com_timeout(T1) == [GRUPO]

    espaco.salvar_sessao(Sessao())  # a sessão fechou
    assert banco.listar_grupos_com_timeout(T1 + timedelta(days=1)) == []


def test_espaco_privado_nunca_entra_na_consulta_de_timeout(banco: Banco) -> None:
    banco.do_espaco(ALUNO_A).salvar_sessao(_revisao_marcada("5531999998888", T0))

    assert banco.listar_grupos_com_timeout(T1) == []


def test_resolver_slug_reaproveita_o_slug_quando_a_traducao_so_muda_de_redacao(
    repo: Repository,
) -> None:
    repo.criar_entrada(_entrada("grader", traducao="avaliador"))

    assert resolver_slug(repo, "grader", "avaliador ou sistema de correção") == "grader"


@pytest.mark.parametrize(
    ("a", "b", "esperado"),
    [
        ("avaliador", "avaliador ou sistema de correção", True),
        ("travar, emperrar", "travar", True),
        ("Travar", "travar, emperrar", True),
        ("tratar (alguém ou algo de uma certa maneira)", "tratar", True),
        ("parar / interromper", "interromper", True),
        ("domar, controlar", "aproveitar, utilizar", False),
        ("travar", "barraca", False),
        ("", "travar", False),
    ],
)
def test_mesma_traducao_ignora_redacao_mas_nao_o_sentido(a: str, b: str, esperado: bool) -> None:
    assert mesma_traducao(a, b) is esperado


# --- M57: professores globais (ADR-0055) -------------------------------------------------------


def test_professores_adicionar_listar_e_remover(banco: Banco) -> None:
    assert banco.listar_professores() == []

    assert banco.adicionar_professor("5531999998888", por="5511988887777", agora=T0) is True
    assert banco.adicionar_professor("5521977776666", por="5511988887777", agora=T1) is True
    assert banco.adicionar_professor("5531999998888", por="5511988887777", agora=T1) is False

    assert banco.listar_professores() == ["5531999998888", "5521977776666"]
    assert banco.remover_professor("5531999998888") is True
    assert banco.remover_professor("5531999998888") is False
    assert banco.listar_professores() == ["5521977776666"]


def test_listar_respostas_desde_corta_as_antigas_e_guarda_o_tipo(repo: Repository) -> None:
    for quando, tipo in ((T0, "diaria"), (T1, "semanal")):
        repo.registrar_resposta(
            Resposta(
                entry="stall",
                autor_id="5531999998888",
                marcado=False,
                qualidade="bom",
                tipo=tipo,
                criado_em=quando,
            )
        )

    assert [r.tipo for r in repo.listar_respostas(desde=T1)] == ["semanal"]
    assert [r.tipo for r in repo.listar_respostas(desde=T0)] == ["diaria", "semanal"]
    assert len(repo.listar_respostas()) == 2
