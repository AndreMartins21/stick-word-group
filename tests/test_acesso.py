"""M15 (ADR-0018): quem pode ativar o bot num grupo e quem gerencia os admins. Sem IA, sem rede."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest

from app import messages
from app.channel.fake import FakeChannel
from app.config import Settings
from app.flows.admin import (
    Acesso,
    Resultado,
    ativar_grupo,
    comando_privado,
    desativar_grupo,
    eh_admin,
    eh_comando_de_admin,
    eh_comando_de_ativacao,
    grupo_autorizado,
    tratar_ativacao_no_grupo,
)
from app.repo.memory import MemoryBanco
from tests.helpers import T0, eventos

DONO = "5531999998888"
ADMIN = "5511988887777"
ALUNO = "5521977776666"
GRUPO = "120363000000000001@g.us"
GRUPO_FIXO = "120363000000000099@g.us"


def _acesso(
    *, max_grupos: int = 10, fixos: tuple[str, ...] = (GRUPO_FIXO,)
) -> tuple[Acesso, MemoryBanco, FakeChannel]:
    settings = Settings(
        _env_file=None,
        ALLOWED_NUMBER=DONO,
        BOT_NUMBER="5531988887777",
        WAHA_API_KEY="x",
        GCP_PROJECT_ID="p",
        EXPORT_BUCKET="b",
    )
    banco, canal = MemoryBanco(), FakeChannel()
    banco.adicionar_admin(ADMIN, por=DONO, agora=T0)
    acesso = Acesso(
        banco=banco,
        canal=canal,
        eh_dono=settings.eh_dono,
        grupos_fixos=fixos,
        max_grupos=max_grupos,
        agora=lambda: T0,
        contato=settings.contact_email,
    )
    return acesso, banco, canal


# --- papéis --------------------------------------------------------------------------------


def test_dono_e_admins_sao_admin_e_aluno_comum_nao() -> None:
    a, _, _ = _acesso()

    assert eh_admin(a, DONO)
    assert eh_admin(a, ADMIN)
    assert not eh_admin(a, ALUNO)


def test_admin_aceita_a_variacao_do_nono_digito() -> None:
    a, _, _ = _acesso()

    assert eh_admin(a, "551188887777")  # o mesmo ADMIN, conta registrada sem o 9


def test_grupo_fixo_ou_ativado_e_autorizado() -> None:
    a, banco, _ = _acesso()
    assert grupo_autorizado(a, GRUPO_FIXO)
    assert not grupo_autorizado(a, GRUPO)

    banco.ativar_grupo(GRUPO, nome=None, por=DONO, agora=T0)

    assert grupo_autorizado(a, GRUPO)


# --- reconhecer o comando ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("!activate", "activate"),
        ("  !ACTIVATE  ", "activate"),
        ("!deactivate", "deactivate"),
        ("!activate agora", "activate"),
        ("activate", None),  # sem o prefixo é conversa
        ("vamos !activate", None),  # o comando é a primeira palavra
        ("!help", None),
        ("", None),
    ],
)
def test_reconhece_o_comando_de_ativacao(texto: str, esperado: str | None) -> None:
    assert eh_comando_de_ativacao(texto) == esperado


# --- ativar / desativar --------------------------------------------------------------------


def test_admin_ativa_o_grupo_e_fica_registrado_quem_ativou() -> None:
    a, banco, _ = _acesso()

    assert ativar_grupo(a, GRUPO, ADMIN, "Turma A") is Resultado.ATIVADO

    (grupo,) = banco.listar_grupos_ativos()
    assert (grupo.id, grupo.nome, grupo.ativado_por) == (GRUPO, "Turma A", ADMIN)


def test_quem_nao_e_admin_nao_ativa_e_nada_e_gravado() -> None:
    a, banco, _ = _acesso()

    assert ativar_grupo(a, GRUPO, ALUNO, None) is Resultado.NAO_ADMIN

    assert banco.listar_grupos_ativos() == []
    assert not banco.grupo_esta_ativo(GRUPO)


def test_ativar_de_novo_ou_um_grupo_fixo_diz_que_ja_esta_ativo() -> None:
    a, _, _ = _acesso()
    ativar_grupo(a, GRUPO, ADMIN, None)

    assert ativar_grupo(a, GRUPO, ADMIN, None) is Resultado.JA_ATIVO
    assert ativar_grupo(a, GRUPO_FIXO, ADMIN, None) is Resultado.JA_ATIVO


def test_limite_de_grupos_recusa_a_ativacao_de_um_novo() -> None:
    a, banco, _ = _acesso(max_grupos=2)
    ativar_grupo(a, "1@g.us", ADMIN, None)
    ativar_grupo(a, "2@g.us", ADMIN, None)

    assert ativar_grupo(a, "3@g.us", ADMIN, None) is Resultado.LIMITE

    assert [g.id for g in banco.listar_grupos_ativos()] == ["1@g.us", "2@g.us"]


def test_o_limite_nao_conta_os_grupos_fixos_do_env() -> None:
    a, _, _ = _acesso(max_grupos=1, fixos=(GRUPO_FIXO, "2@g.us"))

    assert ativar_grupo(a, GRUPO, ADMIN, None) is Resultado.ATIVADO


def test_desativar_um_grupo_e_so_de_admin() -> None:
    a, banco, _ = _acesso()
    ativar_grupo(a, GRUPO, ADMIN, None)

    assert desativar_grupo(a, GRUPO, ALUNO) is Resultado.NAO_ADMIN
    assert banco.grupo_esta_ativo(GRUPO)
    assert desativar_grupo(a, GRUPO, ADMIN) is Resultado.DESATIVADO
    assert desativar_grupo(a, GRUPO, ADMIN) is Resultado.NAO_ESTAVA_ATIVO


# --- a conversa no grupo -------------------------------------------------------------------


async def test_admin_manda_activate_o_bot_responde_no_grupo_e_grava_o_nome() -> None:
    a, banco, canal = _acesso()
    canal.nomes_de_grupos[GRUPO] = "Turma A"

    await tratar_ativacao_no_grupo(a, "activate", GRUPO, ADMIN)

    assert canal.textos_enviados == [(GRUPO, messages.GRUPO_ATIVADO)]
    assert banco.listar_grupos_ativos()[0].nome == "Turma A"


async def test_activate_de_quem_nao_e_admin_e_silencio_total() -> None:
    a, banco, canal = _acesso()

    await tratar_ativacao_no_grupo(a, "activate", GRUPO, ALUNO)
    await tratar_ativacao_no_grupo(a, "deactivate", GRUPO, ALUNO)

    assert canal.textos_enviados == []
    assert banco.listar_grupos_ativos() == []


async def test_activate_acima_do_limite_avisa_no_grupo() -> None:
    a, _, canal = _acesso(max_grupos=0)

    await tratar_ativacao_no_grupo(a, "activate", GRUPO, ADMIN)

    assert canal.textos_enviados == [(GRUPO, messages.grupo_limite(0))]


async def test_deactivate_desliga_e_ja_ativo_avisa() -> None:
    a, banco, canal = _acesso()
    await tratar_ativacao_no_grupo(a, "activate", GRUPO, ADMIN)
    await tratar_ativacao_no_grupo(a, "activate", GRUPO, ADMIN)
    await tratar_ativacao_no_grupo(a, "deactivate", GRUPO, ADMIN)

    assert [t for _, t in canal.textos_enviados] == [
        messages.GRUPO_ATIVADO,
        messages.GRUPO_JA_ATIVO,
        messages.GRUPO_DESATIVADO,
    ]
    assert not banco.grupo_esta_ativo(GRUPO)


# --- /admin (só o dono) --------------------------------------------------------------------


def test_reconhece_os_comandos_de_admin_no_privado() -> None:
    assert eh_comando_de_admin("/admin")
    assert eh_comando_de_admin("/groups off 1")
    assert eh_comando_de_admin("/grupos")
    assert eh_comando_de_admin("!groups")
    assert not eh_comando_de_admin("/list")
    assert not eh_comando_de_admin("groups")


async def test_admin_que_nao_e_o_dono_nao_usa_o_comando_admin() -> None:
    a, banco, _ = _acesso()

    assert await comando_privado(a, "/admin add 5521977776666", ADMIN) is None
    assert await comando_privado(a, "/admin", ALUNO) is None

    assert banco.listar_admins() == [ADMIN]


async def test_dono_lista_adiciona_e_remove_admins() -> None:
    a, banco, _ = _acesso()

    lista = await comando_privado(a, "/admin", DONO)
    assert lista is not None and ADMIN in lista

    assert await comando_privado(a, f"/admin add {ALUNO}", DONO) == messages.ADMIN_ADICIONADO
    assert banco.listar_admins() == [ADMIN, ALUNO]
    assert await comando_privado(a, f"/admin add {ALUNO}", DONO) == messages.ADMIN_JA_E_ADMIN
    assert await comando_privado(a, f"/admin remove {ALUNO}", DONO) == messages.ADMIN_REMOVIDO
    assert banco.listar_admins() == [ADMIN]
    assert await comando_privado(a, f"/admin remove {ALUNO}", DONO) == messages.ADMIN_NAO_E_ADMIN


async def test_admin_novo_passa_a_poder_ativar_grupos() -> None:
    a, banco, _ = _acesso()
    assert ativar_grupo(a, GRUPO, ALUNO, None) is Resultado.NAO_ADMIN

    await comando_privado(a, f"/admin add {ALUNO}", DONO)

    assert ativar_grupo(a, GRUPO, ALUNO, None) is Resultado.ATIVADO
    assert banco.grupo_esta_ativo(GRUPO)


async def test_admin_add_aceita_formatacao_e_rejeita_lixo() -> None:
    a, banco, _ = _acesso()

    assert (
        await comando_privado(a, "/admin add +55 (21) 97777-6666", DONO)
        == messages.ADMIN_ADICIONADO
    )
    assert "5521977776666" in banco.listar_admins()
    assert await comando_privado(a, "/admin add 123", DONO) == messages.ADMIN_USO
    assert await comando_privado(a, "/admin add", DONO) == messages.ADMIN_USO
    assert await comando_privado(a, "/admin fly 5521977776666", DONO) == messages.ADMIN_USO


async def test_o_dono_nao_entra_nem_sai_da_lista_de_admins() -> None:
    a, banco, _ = _acesso()

    assert await comando_privado(a, f"/admin add {DONO}", DONO) == messages.ADMIN_E_O_DONO
    assert await comando_privado(a, f"/admin remove {DONO}", DONO) == messages.ADMIN_E_O_DONO
    assert banco.listar_admins() == [ADMIN]


async def test_remover_admin_tolera_o_nono_digito() -> None:
    a, banco, _ = _acesso()

    resposta = await comando_privado(a, "/admin remove 551188887777", DONO)

    assert resposta == messages.ADMIN_REMOVIDO
    assert banco.listar_admins() == []


# --- /groups (dono e admins) ---------------------------------------------------------------


async def test_quem_nao_e_admin_nao_usa_groups() -> None:
    a, _, _ = _acesso()

    assert await comando_privado(a, "/groups", ALUNO) is None
    assert await comando_privado(a, "/groups off 1", ALUNO) is None


async def test_groups_lista_ativos_fixos_e_pendentes_com_o_prazo() -> None:
    a, banco, canal = _acesso()
    canal.nomes_de_grupos |= {GRUPO: "Turma A", GRUPO_FIXO: "Turma Fixa", "9@g.us": "Turma C"}
    banco.ativar_grupo(GRUPO, nome="Turma A", por=ADMIN, agora=T0)
    banco.registrar_grupo_pendente("9@g.us", T0 - timedelta(hours=19))

    resposta = await comando_privado(a, "/groups", ADMIN)

    assert resposta is not None
    assert "1. Turma A" in resposta
    assert "Turma Fixa (fixed in the config)" in resposta
    assert "Turma C — 5h left" in resposta
    assert "(1/10)" in resposta


async def test_groups_sem_nenhum_grupo() -> None:
    a, _, _ = _acesso(fixos=())

    resposta = await comando_privado(a, "/groups", DONO)

    assert resposta is not None and "not in any group yet" in resposta


async def test_groups_off_desativa_pelo_numero_da_lista() -> None:
    a, banco, _ = _acesso()
    banco.ativar_grupo("1@g.us", nome="A", por=ADMIN, agora=T0)
    banco.ativar_grupo("2@g.us", nome="B", por=ADMIN, agora=T0 + timedelta(minutes=1))

    resposta = await comando_privado(a, "/groups off 2", ADMIN)

    assert resposta == messages.grupo_desligado("B")
    assert [g.id for g in banco.listar_grupos_ativos()] == ["1@g.us"]


async def test_groups_off_com_numero_invalido_ou_uso_errado() -> None:
    a, banco, _ = _acesso()
    banco.ativar_grupo("1@g.us", nome="A", por=ADMIN, agora=T0)

    assert await comando_privado(a, "/groups off 5", ADMIN) == messages.GRUPO_NAO_EXISTE
    assert await comando_privado(a, "/groups off 0", ADMIN) == messages.GRUPO_NAO_EXISTE
    assert await comando_privado(a, "/groups off", ADMIN) == messages.GRUPOS_USO
    assert await comando_privado(a, "/groups on 1", ADMIN) == messages.GRUPOS_USO
    assert banco.grupo_esta_ativo("1@g.us")


# --- eventos estruturados (M27, ADR-0028, seção 12 da spec) ---------------------------------


def test_ativar_e_desativar_grupo_registram_eventos(caplog: pytest.LogCaptureFixture) -> None:
    a, _, _ = _acesso()

    with caplog.at_level(logging.INFO):
        ativar_grupo(a, GRUPO, ADMIN, None)
        desativar_grupo(a, GRUPO, ADMIN)

    nomes = [e.evento for e in eventos(caplog.records)]
    assert nomes == ["grupo_ativado", "grupo_desativado"]


def test_ativar_grupo_ja_ativo_ou_negado_nao_registra_evento(
    caplog: pytest.LogCaptureFixture,
) -> None:
    a, _, _ = _acesso()
    ativar_grupo(a, GRUPO, ADMIN, None)

    with caplog.at_level(logging.INFO):
        assert ativar_grupo(a, GRUPO, ADMIN, None) is Resultado.JA_ATIVO
        assert ativar_grupo(a, GRUPO, ALUNO, None) is Resultado.NAO_ADMIN

    assert eventos(caplog.records) == []


# --- /teachers (admin ou dono; M57, ADR-0055) -------------------------------------------------


async def test_admin_lista_adiciona_e_remove_professores() -> None:
    a, banco, _ = _acesso()

    assert await comando_privado(a, "/teachers", ADMIN) == messages.professores_lista([])
    assert (
        await comando_privado(a, f"/teachers add {ALUNO}", ADMIN) == messages.PROFESSOR_ADICIONADO
    )
    assert banco.listar_professores() == [ALUNO]
    assert await comando_privado(a, f"/teachers add {ALUNO}", DONO) == messages.PROFESSOR_JA_E
    lista = await comando_privado(a, "/teachers", DONO)
    assert lista is not None and ALUNO in lista
    assert (
        await comando_privado(a, f"/teachers remove {ALUNO}", ADMIN) == messages.PROFESSOR_REMOVIDO
    )
    assert await comando_privado(a, f"/teachers remove {ALUNO}", ADMIN) == messages.PROFESSOR_NAO_E
    assert banco.listar_professores() == []


async def test_teachers_rejeita_lixo_e_nao_admin_nao_usa() -> None:
    a, banco, _ = _acesso()

    assert await comando_privado(a, "/teachers add 123", ADMIN) == messages.PROFESSORES_USO
    assert (
        await comando_privado(a, "/teachers fly 5521977776666", ADMIN) == messages.PROFESSORES_USO
    )
    assert await comando_privado(a, f"/teachers add {ALUNO}", ALUNO) is None
    assert banco.listar_professores() == []
    assert eh_comando_de_admin("/teachers")


# --- /ranking (admin ou dono; M58, ADR-0056) --------------------------------------------------


def _com_respostas() -> tuple[Acesso, MemoryBanco]:
    from app.domain.models import Membro, Resposta

    a, banco, _ = _acesso()
    banco.ativar_grupo(GRUPO, nome="Turma B2", por=DONO, agora=T0)
    repo = banco.do_espaco(GRUPO)
    repo.salvar_membro(ALUNO, Membro(nome="Caio", entrou_em=T0))
    repo.salvar_membro(ADMIN, Membro(nome="Adm", entrou_em=T0))
    for autor, quando in ((ALUNO, T0), (ALUNO, T0), (ADMIN, T0)):
        repo.registrar_resposta(
            Resposta(
                entry="w",
                autor_id=autor,
                marcado=False,
                qualidade="bom",
                tipo="diaria",
                criado_em=quando,
            )
        )
    repo.registrar_resposta(  # fora da janela de 1 mês
        Resposta(
            entry="w",
            autor_id=ALUNO,
            marcado=False,
            qualidade="bom",
            tipo="semanal",
            criado_em=T0 - timedelta(days=90),
        )
    )
    return a, banco


async def test_ranking_manda_tres_mensagens_sem_staff_e_sem_telefone() -> None:
    a, _ = _com_respostas()

    r = await comando_privado(a, "/ranking", ADMIN)

    assert isinstance(r, list) and len(r) == 3
    assert "Caio" in r[0] and "Turma B2" in r[0] and "Adm" not in r[0]
    assert "Turma B2" in r[1] and "1/1 active" in r[1]
    assert "*Turma B2*" in r[2]
    assert all(ALUNO not in parte for parte in r)


async def test_ranking_respeita_os_meses_pedidos() -> None:
    a, _ = _com_respostas()

    r1 = await comando_privado(a, "/ranking 1", ADMIN)
    r6 = await comando_privado(a, "/ranking 6", ADMIN)

    assert isinstance(r1, list) and "— 2 (daily 2 · weekly 0)" in r1[0]
    assert isinstance(r6, list) and "— 3 (daily 2 · weekly 1)" in r6[0]


async def test_ranking_uso_invalido_vazio_e_nao_admin() -> None:
    a, _ = _com_respostas()

    for ruim in ("/ranking 0", "/ranking 25", "/ranking abc", "/ranking 1 2"):
        assert await comando_privado(a, ruim, ADMIN) == messages.RANKING_USO
    assert await comando_privado(a, "/ranking", ALUNO) is None
    sem, _, _ = _acesso()
    assert await comando_privado(sem, "/ranking 3", DONO) == messages.ranking_vazio(3)
    assert eh_comando_de_admin("/ranking")
