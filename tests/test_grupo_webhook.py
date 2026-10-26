"""M16 (ADR-0019) no webhook: em grupo ativo só as mensagens com o prefixo chegam ao bot, e o filtro
vem antes de tudo (deduplicação, `sendSeen`, gravação). Payloads de exemplo em `tests/fixtures/`."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, cast

import pytest

from app import messages
from tests.helpers import eventos, expansoes
from tests.webhook_helpers import (
    ADMIN,
    ALUNO_COMUM,
    DONO,
    GRUPO,
    GRUPO_FIXO,
    Ambiente,
    _do_grupo,
)

FIXTURES = Path(__file__).parent / "fixtures"
ANA = "5531999998888"


def _fixture(nome: str) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads((FIXTURES / f"{nome}.json").read_text("utf-8")))


def test_grupo_ativo_com_prefixo_responde_no_grupo_e_cadastra_quem_escreveu(
    ambiente: Ambiente,
) -> None:
    resposta = ambiente.cliente.post("/waha/webhook", json=_fixture("grupo_ativo_com_prefixo"))

    assert resposta.status_code == 200
    ((chat, texto),) = ambiente.canal.textos_enviados
    assert chat == GRUPO_FIXO and "*stall*" in texto and "2️⃣ See more examples" in texto
    assert ambiente.canal.vistos == [GRUPO_FIXO]
    espaco = ambiente.banco.do_espaco(GRUPO_FIXO)
    assert [e.slug for e in espaco.listar_entradas()] == ["stall"]
    membro = espaco.obter_membro(ANA)
    assert membro is not None and (membro.papel, membro.nome) == ("aluno", "Ana")
    assert ambiente.banco.do_espaco(f"{ANA}@c.us").listar_entradas() == []  # o privado da Ana, não


def test_grupo_ativo_com_prefixo_registra_mensagem_recebida(
    ambiente: Ambiente, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        ambiente.cliente.post("/waha/webhook", json=_fixture("grupo_ativo_com_prefixo"))

    (evento,) = eventos(caplog.records, "mensagem_recebida")
    assert evento.tipo_espaco == "grupo"


def test_grupo_nao_ativo_registra_grupo_pendente_uma_vez(
    ambiente: Ambiente, caplog: pytest.LogCaptureFixture
) -> None:
    corpo = _fixture("grupo_ativo_com_prefixo")
    corpo["payload"]["from"] = GRUPO  # um grupo que ninguém ativou

    with caplog.at_level(logging.INFO):
        ambiente.cliente.post("/waha/webhook", json=corpo)
        ambiente.cliente.post("/waha/webhook", json=corpo)

    assert len(eventos(caplog.records, "grupo_pendente")) == 1  # só na primeira vez


def test_grupo_ativo_sem_prefixo_nada_gravado_nada_enviado_nenhum_sendseen(
    ambiente: Ambiente, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        resposta = ambiente.cliente.post("/waha/webhook", json=_fixture("grupo_ativo_sem_prefixo"))

    assert resposta.status_code == 200
    assert ambiente.canal.textos_enviados == []
    assert ambiente.canal.vistos == []  # nenhum sendSeen
    assert ambiente.banco._processadas == set()  # nem a deduplicação
    assert ambiente.banco.do_espaco(GRUPO_FIXO).listar_membros() == []
    assert ambiente.banco.listar_grupos_pendentes() == []
    assert ambiente.tutor.chamadas == []
    assert not any("aula de hoje" in r.getMessage() for r in caplog.records)  # nunca o conteúdo


def test_grupo_nao_ativo_com_prefixo_nao_e_atendido(ambiente: Ambiente) -> None:
    corpo = _fixture("grupo_ativo_com_prefixo")
    corpo["payload"]["from"] = GRUPO  # um grupo que ninguém ativou

    ambiente.cliente.post("/waha/webhook", json=corpo)

    assert ambiente.canal.textos_enviados == [] and ambiente.canal.vistos == []
    assert ambiente.tutor.chamadas == []
    assert [g for g, _ in ambiente.banco.listar_grupos_pendentes()] == [GRUPO]


def test_grupo_ativado_por_um_admin_passa_a_ser_atendido(ambiente: Ambiente) -> None:
    ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO, f"{ADMIN}@c.us", "!activate"))
    ambiente.canal.textos_enviados.clear()

    ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO, f"{ANA}@c.us", "!add stall"))

    ((chat, texto),) = ambiente.canal.textos_enviados
    assert chat == GRUPO and "*stall*" in texto


def test_participante_lid_e_resolvido_e_atendido(ambiente: Ambiente) -> None:
    ambiente.canal.lids_conhecidos["257161284317237@lid"] = ANA

    ambiente.cliente.post("/waha/webhook", json=_fixture("grupo_participante_lid"))

    ((chat, texto),) = ambiente.canal.textos_enviados
    assert chat == GRUPO_FIXO and texto == messages.ajuda_do_grupo("!")
    assert ambiente.banco.do_espaco(GRUPO_FIXO).obter_membro(ANA) is not None
    assert ambiente.banco.obter_numero_do_lid("257161284317237@lid") == ANA  # ficou em cache


def test_participante_lid_nao_resolvido_e_ignorado(ambiente: Ambiente) -> None:
    ambiente.cliente.post("/waha/webhook", json=_fixture("grupo_participante_lid"))

    assert ambiente.canal.textos_enviados == [] and ambiente.canal.vistos == []


def test_midia_em_grupo_e_ignorada_em_silencio(ambiente: Ambiente) -> None:
    resposta = ambiente.cliente.post("/waha/webhook", json=_fixture("grupo_midia"))

    assert resposta.status_code == 200
    assert ambiente.canal.textos_enviados == [] and ambiente.canal.vistos == []
    assert ambiente.banco._processadas == set()


def test_mensagem_de_grupo_sem_participante_e_ignorada(ambiente: Ambiente) -> None:
    ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO_FIXO, None, "!help"))

    assert ambiente.canal.textos_enviados == []


def test_a_mesma_mensagem_reenviada_pelo_waha_e_tratada_uma_vez(ambiente: Ambiente) -> None:
    corpo = _fixture("grupo_ativo_com_prefixo")

    ambiente.cliente.post("/waha/webhook", json=corpo)
    ambiente.cliente.post("/waha/webhook", json=corpo)

    assert len(ambiente.canal.textos_enviados) == 1
    assert len(ambiente.tutor.chamadas) == 1


def test_o_ciclo_stall_no_grupo_por_dois_alunos_pelo_webhook(ambiente: Ambiente) -> None:
    ambiente.tutor.expansoes.append(expansoes())
    ana, bia = f"{ANA}@c.us", "5511977776666@c.us"

    for participante, texto in [(ana, "!add stall"), (bia, "!4")]:
        ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO_FIXO, participante, texto))

    textos = [t for _, t in ambiente.canal.textos_enviados]
    assert "*stall*" in textos[0] and "Saved: *stall*" in textos[1]
    membros = ambiente.banco.do_espaco(GRUPO_FIXO).listar_membros()
    assert [n for n, _ in membros] == [ANA, "5511977776666"]


def test_teacher_com_a_mencao_do_payload(ambiente: Ambiente) -> None:
    ambiente.canal.lids_conhecidos["888@lid"] = "5511977776666"
    corpo = _do_grupo(GRUPO_FIXO, f"{DONO}@c.us", "!teacher @Bia")
    corpo["payload"]["mentionedIds"] = ["888@lid"]

    ambiente.cliente.post("/waha/webhook", json=corpo)

    bia = ambiente.banco.do_espaco(GRUPO_FIXO).obter_membro("5511977776666")
    assert bia is not None and bia.papel == "professor"


def test_falha_inesperada_no_grupo_avisa_o_grupo(ambiente: Ambiente) -> None:
    ambiente.tutor.explicacoes[:] = [RuntimeError("bug qualquer")]

    resposta = ambiente.cliente.post("/waha/webhook", json=_fixture("grupo_ativo_com_prefixo"))

    assert resposta.status_code == 200
    assert ambiente.canal.textos_enviados == [(GRUPO_FIXO, messages.ERRO_INESPERADO)]


def test_activate_num_grupo_ja_ativo_diz_que_ja_esta(ambiente: Ambiente) -> None:
    ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO_FIXO, f"{ADMIN}@c.us", "!activate"))

    assert ambiente.canal.textos_enviados == [(GRUPO_FIXO, messages.GRUPO_JA_ATIVO)]


def test_activate_de_aluno_num_grupo_ativo_e_silencio_e_nao_vira_comando_desconhecido(
    ambiente: Ambiente,
) -> None:
    ambiente.cliente.post(
        "/waha/webhook", json=_do_grupo(GRUPO_FIXO, f"{ALUNO_COMUM}@c.us", "!deactivate")
    )

    assert ambiente.canal.textos_enviados == []


def test_review_pelo_webhook_nao_marca_ninguem(ambiente: Ambiente) -> None:
    ambiente.tutor.expansoes.append(expansoes())
    for texto in ("!add stall", "!4", "!review"):
        ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO_FIXO, f"{ANA}@c.us", texto))

    texto_do_card = ambiente.canal.textos_enviados[-1][1]
    assert "Anyone can answer" in texto_do_card and "@" not in texto_do_card
    assert not ambiente.canal.mencoes_enviadas or not ambiente.canal.mencoes_enviadas[-1][1]


def test_skip_com_barra_no_grupo_e_lido_mas_barra_sem_comando_nao(
    ambiente: Ambiente,
) -> None:
    ambiente.tutor.expansoes.append(expansoes())
    for texto in ("!add stall", "!4", "!review"):
        ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO_FIXO, f"{ANA}@c.us", texto))
    antes = len(ambiente.canal.textos_enviados)

    ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO_FIXO, f"{ANA}@c.us", "/ oi"))
    assert len(ambiente.canal.textos_enviados) == antes  # barra sem letra depois: é conversa

    ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO_FIXO, f"{ANA}@c.us", "/skip-all"))
    assert ambiente.banco.do_espaco(GRUPO_FIXO).obter_sessao().estado == "IDLE"  # fechou


def test_a_resposta_no_grupo_pelo_webhook_avanca_o_card(ambiente: Ambiente) -> None:
    from app.domain.models import Revisao

    ambiente.tutor.expansoes.append(expansoes())
    ambiente.tutor.revisoes.append(Revisao(tipo="definicao", qualidade="bom", feedback="Nice!"))
    ambiente.canal.participantes_de_grupos[GRUPO_FIXO] = [ANA]
    for texto in ("!add stall", "!4", "!review"):
        ambiente.cliente.post("/waha/webhook", json=_do_grupo(GRUPO_FIXO, f"{ANA}@c.us", texto))

    ambiente.cliente.post(
        "/waha/webhook", json=_do_grupo(GRUPO_FIXO, f"{ANA}@c.us", "!it means to stop")
    )

    assert "Practice done" in ambiente.canal.textos_enviados[-1][1]
    (resposta,) = ambiente.banco.do_espaco(GRUPO_FIXO).listar_respostas()
    assert (resposta.autor_id, resposta.marcado) == (ANA, False)
