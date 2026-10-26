"""M15 (ADR-0018) e ADR-0062 no webhook: no privado só o dono e os admins são atendidos, só com os
comandos de admin (os demais são ignorados em silêncio e a IA nunca é chamada); grupo só é ativado
por admin, e o grupo não ativado fica pendente em silêncio."""

from __future__ import annotations

import logging

import pytest

from app import messages
from tests.helpers import T0
from tests.webhook_helpers import (
    ADMIN,
    ALUNO_COMUM,
    DONO,
    ESTRANHO,
    GRUPO,
    GRUPO_FIXO,
    Ambiente,
    _do_grupo,
    _entrada_no_grupo,
    _privada,
)

# --- privado: só o dono e os admins, só com os comandos de admin (ADR-0062) -------------------


@pytest.mark.parametrize("numero", [ESTRANHO, ALUNO_COMUM])
@pytest.mark.parametrize("texto", ["stall", "oi", "/list", "/groups", "/admin add 5541966665555"])
def test_quem_nao_e_admin_e_ignorado_em_silencio_no_privado(
    ambiente: Ambiente, numero: str, texto: str
) -> None:
    resposta = ambiente.cliente.post("/waha/webhook", json=_privada(numero, texto))

    assert resposta.status_code == 200
    assert ambiente.canal.textos_enviados == []
    assert ambiente.canal.vistos == []  # sem sendSeen
    assert ambiente.tutor.chamadas == []  # a IA nunca é chamada
    assert ambiente.banco.do_espaco(f"{numero}@c.us").obter_perfil() is None  # nada gravado
    assert ambiente.banco._processadas == set()  # nem a deduplicação
    assert ambiente.banco.listar_admins() == [ADMIN]


def test_midia_de_quem_nao_e_admin_tambem_e_ignorada(ambiente: Ambiente) -> None:
    ambiente.cliente.post("/waha/webhook", json=_privada(ESTRANHO, "", midia=True))

    assert ambiente.canal.textos_enviados == []
    assert ambiente.tutor.chamadas == []


def test_admin_usa_groups_sem_chamar_a_ia(ambiente: Ambiente) -> None:
    ambiente.cliente.post("/waha/webhook", json=_privada(ADMIN, "/groups"))

    ((chat, texto),) = ambiente.canal.textos_enviados
    assert chat == f"{ADMIN}@c.us"
    assert "Active groups" in texto
    assert ambiente.tutor.chamadas == []


@pytest.mark.parametrize("numero", [ADMIN, DONO])
def test_admin_ou_dono_que_manda_outra_coisa_recebe_a_lista_de_comandos(
    ambiente: Ambiente, numero: str
) -> None:
    ambiente.cliente.post("/waha/webhook", json=_privada(numero, "stall"))
    ambiente.cliente.post("/waha/webhook", json=_privada(numero, "", midia=True))

    assert ambiente.canal.textos_enviados == [
        (f"{numero}@c.us", messages.ajuda_do_admin("!")),
        (f"{numero}@c.us", messages.ajuda_do_admin("!")),
    ]
    assert ambiente.tutor.chamadas == []


def test_admin_que_nao_e_dono_nao_usa_admin_e_recebe_a_lista(ambiente: Ambiente) -> None:
    ambiente.cliente.post("/waha/webhook", json=_privada(ADMIN, "/admin add 5541966665555"))

    assert [t for _, t in ambiente.canal.textos_enviados] == [messages.ajuda_do_admin("!")]
    assert ambiente.banco.listar_admins() == [ADMIN]


def test_dono_gerencia_admins_pelo_privado(ambiente: Ambiente) -> None:
    ambiente.cliente.post("/waha/webhook", json=_privada(DONO, f"/admin add {ESTRANHO}"))

    assert ambiente.canal.textos_enviados == [(f"{DONO}@c.us", messages.ADMIN_ADICIONADO)]
    assert ESTRANHO in ambiente.banco.listar_admins()
    assert ambiente.tutor.chamadas == []


# --- grupo: ativar ---------------------------------------------------------------------------


def test_admin_ativa_o_grupo_com_activate(ambiente: Ambiente) -> None:
    ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO, f"{ADMIN}@c.us", "!activate"))

    assert ambiente.canal.textos_enviados == [(GRUPO, messages.GRUPO_ATIVADO)]
    assert ambiente.banco.grupo_esta_ativo(GRUPO)
    assert ambiente.banco.listar_grupos_pendentes() == []
    assert ambiente.tutor.chamadas == []


def test_activate_de_quem_nao_e_admin_e_silencio_total_mas_o_grupo_fica_pendente(
    ambiente: Ambiente,
) -> None:
    ambiente.cliente.post(
        "/waha/webhook", json=_do_grupo(GRUPO, f"{ALUNO_COMUM}@c.us", "!activate")
    )

    assert ambiente.canal.textos_enviados == []
    assert ambiente.canal.vistos == []
    assert not ambiente.banco.grupo_esta_ativo(GRUPO)
    assert [g for g, _ in ambiente.banco.listar_grupos_pendentes()] == [GRUPO]


def test_o_dono_tambem_ativa(ambiente: Ambiente) -> None:
    ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO, f"{DONO}@c.us", "!activate"))

    assert ambiente.banco.grupo_esta_ativo(GRUPO)


def test_admin_que_aparece_como_lid_e_resolvido_pelo_cache_de_lids(ambiente: Ambiente) -> None:
    ambiente.canal.lids_conhecidos["777@lid"] = ADMIN

    ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO, "777@lid", "!activate"))

    assert ambiente.banco.grupo_esta_ativo(GRUPO)
    assert ambiente.banco.obter_numero_do_lid("777@lid") == ADMIN


def test_activate_com_lid_nao_resolvido_ou_sem_participante_e_ignorado(ambiente: Ambiente) -> None:
    ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO, "999@lid", "!activate"))
    ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO, None, "!activate"))

    assert ambiente.canal.textos_enviados == []
    assert not ambiente.banco.grupo_esta_ativo(GRUPO)


def test_activate_no_meio_da_conversa_nao_conta(ambiente: Ambiente) -> None:
    ambiente.cliente.post(
        "/waha/webhook", json=_do_grupo(GRUPO, f"{ADMIN}@c.us", "gente, !activate o bot")
    )

    assert not ambiente.banco.grupo_esta_ativo(GRUPO)


def test_o_mesmo_activate_reenviado_pelo_waha_e_tratado_uma_vez(ambiente: Ambiente) -> None:
    corpo = _do_grupo(GRUPO, f"{ADMIN}@c.us", "!activate", id_="false_grupo_ID_FIXO")

    ambiente.cliente.post("/waha/webhook", json=corpo)
    ambiente.cliente.post("/waha/webhook", json=corpo)

    assert len(ambiente.canal.textos_enviados) == 1


def test_o_limite_de_grupos_recusa_e_avisa_no_grupo(ambiente: Ambiente) -> None:
    ambiente.settings.max_groups = 1
    ambiente.cliente.post("/waha/webhook", json=_do_grupo("1@g.us", f"{ADMIN}@c.us", "!activate"))

    ambiente.cliente.post("/waha/webhook", json=_do_grupo("2@g.us", f"{ADMIN}@c.us", "!activate"))

    assert ambiente.canal.textos_enviados[-1] == ("2@g.us", messages.grupo_limite(1))
    assert not ambiente.banco.grupo_esta_ativo("2@g.us")


def test_deactivate_desliga_e_o_bot_volta_ao_silencio(ambiente: Ambiente) -> None:
    ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO, f"{ADMIN}@c.us", "!activate"))
    ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO, f"{ADMIN}@c.us", "!deactivate"))

    assert [t for _, t in ambiente.canal.textos_enviados] == [
        messages.GRUPO_ATIVADO,
        messages.GRUPO_DESATIVADO,
    ]
    assert not ambiente.banco.grupo_esta_ativo(GRUPO)


# --- grupo: pendente e silêncio --------------------------------------------------------------


def test_conversa_em_grupo_nao_ativado_nao_e_lida_e_o_grupo_vira_pendente(
    ambiente: Ambiente, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        ambiente.cliente.post(
            "/waha/webhook",
            json=_do_grupo(GRUPO, f"{ALUNO_COMUM}@c.us", "conversa secreta da turma"),
        )

    assert ambiente.canal.textos_enviados == [] and ambiente.canal.vistos == []
    assert ambiente.tutor.chamadas == []
    assert [g for g, _ in ambiente.banco.listar_grupos_pendentes()] == [GRUPO]
    assert not any("conversa secreta" in r.message for r in caplog.records)  # nunca o conteúdo
    assert ambiente.banco._processadas == set()  # nem a deduplicação grava nada


def test_grupo_pendente_e_registrado_uma_vez_com_o_primeiro_horario(ambiente: Ambiente) -> None:
    for _ in range(3):
        ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO, f"{ALUNO_COMUM}@c.us", "oi"))

    assert len(ambiente.banco.listar_grupos_pendentes()) == 1


def test_grupo_fixo_do_env_e_grupo_ativo_nao_viram_pendentes(ambiente: Ambiente) -> None:
    ambiente.banco.ativar_grupo(GRUPO, nome=None, por=ADMIN, agora=T0)

    ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO_FIXO, f"{ALUNO_COMUM}@c.us", "oi"))
    ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO, f"{ALUNO_COMUM}@c.us", "oi"))

    assert ambiente.banco.listar_grupos_pendentes() == []
    assert ambiente.canal.textos_enviados == []


def test_o_bot_ser_adicionado_a_um_grupo_o_deixa_pendente(ambiente: Ambiente) -> None:
    ambiente.cliente.post("/waha/webhook", json=_entrada_no_grupo(GRUPO))

    assert [g for g, _ in ambiente.banco.listar_grupos_pendentes()] == [GRUPO]
    assert ambiente.canal.textos_enviados == []  # silêncio: nem um "oi"


def test_entrada_em_grupo_ja_autorizado_nao_gera_pendente(ambiente: Ambiente) -> None:
    ambiente.cliente.post("/waha/webhook", json=_entrada_no_grupo(GRUPO_FIXO))

    assert ambiente.banco.listar_grupos_pendentes() == []


def test_o_id_do_grupo_novo_aparece_no_log_uma_vez(
    ambiente: Ambiente, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        ambiente.cliente.post("/waha/webhook", json=_entrada_no_grupo(GRUPO))
        ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO, f"{ALUNO_COMUM}@c.us", "oi"))

    assert len([r for r in caplog.records if GRUPO in r.message]) == 1
