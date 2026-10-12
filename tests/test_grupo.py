"""M16 (ADR-0019): o bot no grupo. Só reage ao prefixo, conjunto fechado de comandos, respostas
dentro de uma atividade, papéis, e nunca chama a IA fora de atividade. Sem rede, sem credencial."""

from __future__ import annotations

import re

import pytest

from app import messages
from app.domain.models import Estado, Roteamento
from app.flows.base import Autor
from app.services.fake_llm import FakeTutor
from tests.helpers import (
    ANA,
    BIA,
    CAIO,
    CHAT,
    DONO_NUMERO,
    GRUPO,
    Montagem,
    expansoes,
    explicacao_stall,
    montar,
    sem_jitter,
)
from tests.test_flows import EXEMPLOS, SINONIMOS, _roteamento_frase

# `/comando` colado a uma palavra: um comando do privado citado (URLs e "and/or" não contam).
_CITA_COMANDO_DO_PRIVADO = re.compile(r"(?<![\w/])/[a-z]{3,}")
_COMANDOS_CITADOS = re.compile(r"(?<![\w!])!([a-z]{3,})")
_DO_GRUPO = {
    "add",
    "delete",
    "list",
    "practice",
    "review",
    "daily",
    "weekly",
    "reminder",
    "reminders",
    "group",
    "help",
    "level",
    "skip",  # M35: respostas dentro da revisão
    "skipall",
}


def _tutor() -> FakeTutor:
    return FakeTutor(
        explicacoes=[explicacao_stall(), explicacao_stall()],
        exemplos=[EXEMPLOS],
        sinonimos=[SINONIMOS],
        expansoes=[expansoes()],
        roteamentos=[_roteamento_frase("quase")],
    )


def _sem_comandos_do_privado(textos: list[str]) -> None:
    for texto in textos:
        assert not _CITA_COMANDO_DO_PRIVADO.search(texto), texto
        for comando in _COMANDOS_CITADOS.findall(texto):
            assert comando in _DO_GRUPO | {"activate"}, (comando, texto)


def _grupo() -> Montagem:
    return montar(tutor=_tutor())


# --- só o prefixo é lido ----------------------------------------------------------------------


async def test_mensagem_sem_prefixo_e_conversa_e_nada_acontece() -> None:
    m = _grupo()

    respostas = await m.diz_no_grupo(ANA, "gente, alguém entendeu a aula de hoje?")

    assert respostas == []
    assert m.tutor.chamadas == []
    assert m.banco.do_espaco(GRUPO).listar_membros() == []  # nem o cadastro do autor


async def test_prefixo_configuravel() -> None:
    m = montar(tutor=_tutor(), prefixo_do_grupo="#")

    assert await m.diz_no_grupo(ANA, "!add stall") == []  # o "!" não vale mais
    ajuda = await m.diz_no_grupo(ANA, "#help")

    assert "#list" in ajuda[0] and "!list" not in ajuda[0]


async def test_privado_nao_ve_o_grupo_e_grupo_nao_ve_o_privado() -> None:
    m = _grupo()
    await m.diz_no_grupo(ANA, "!add stall")

    assert m.banco.do_espaco(CHAT).listar_entradas() == []
    assert len(m.banco.do_espaco(GRUPO).listar_entradas()) == 1


@pytest.mark.parametrize("texto", ["!", "!!!", "! add stall", "!?", "!  ", "!!! wow"])
async def test_exclamacao_sem_letra_ou_numero_depois_e_conversa_e_nao_chama_o_bot(
    texto: str,
) -> None:
    m = _grupo()

    assert await m.diz_no_grupo(ANA, texto) == []
    assert m.tutor.chamadas == []
    assert m.banco.do_espaco(GRUPO).listar_membros() == []


# --- !add e o ciclo da palavra ----------------------------------------------------------------


async def test_add_traz_o_card_com_o_menu_no_prefixo_do_grupo() -> None:
    m = _grupo()

    (card,) = await m.diz_no_grupo(ANA, "!add stall | the talks stalled")

    assert "*stall*" in card
    assert "2️⃣ See more examples" in card and "3️⃣ Check synonyms" in card
    assert "4️⃣ Just save" in card
    assert "tag me with a sentence" in card and "!2" not in card
    assert m.banco.do_espaco(GRUPO).obter_sessao().estado == Estado.AWAIT_ACTION
    _sem_comandos_do_privado([card])


async def test_add_de_palavra_que_ja_existe_avisa_com_o_prefixo_e_0_libera() -> None:
    m = _grupo()
    await m.diz_no_grupo(ANA, "!add stall")
    await m.diz_no_grupo(BIA, "!0")

    (aviso,) = await m.diz_no_grupo(BIA, "!add stall")

    assert aviso.startswith("📌 You already have *stall* in your list.")
    assert "2️⃣ See more examples" in aviso and "3️⃣ Check synonyms" in aviso
    assert "4️⃣" not in aviso
    assert "type !0 or !skip" in aviso
    assert m.banco.do_espaco(GRUPO).obter_sessao().estado == Estado.AWAIT_ACTION
    (fim,) = await m.diz_no_grupo(BIA, "!skip")
    assert fim.startswith("Alright!")
    assert m.banco.do_espaco(GRUPO).obter_sessao().estado == Estado.IDLE


async def test_card_do_grupo_ensina_a_pedir_outro_sentido_com_o_add() -> None:
    m = _grupo()

    (card,) = await m.diz_no_grupo(ANA, "!add stall")

    assert "Want another meaning? Tag me with *stall | to delay on purpose*" in card
    _sem_comandos_do_privado([card])


async def test_add_do_mesmo_termo_com_sentido_troca_o_card_sem_salvar() -> None:
    sentido_s2 = explicacao_stall(sentido_do_contexto="s2").model_copy(
        update={"frase_contexto": None}
    )
    m = montar(tutor=FakeTutor(explicacoes=[explicacao_stall(), sentido_s2]))
    await m.diz_no_grupo(ANA, "!add stall")

    (card,) = await m.diz_no_grupo(BIA, "!add stall | to delay on purpose")

    assert "🇧🇷" not in card  # M34: turma B1-B2 não vê português (a tradução segue gravada)
    assert "Saved" not in card
    (entrada,) = m.banco.do_espaco(GRUPO).listar_entradas()
    assert entrada.sentido.traducao == "enrolar"


async def test_outra_palavra_com_contexto_salva_a_aberta_e_abre_a_nova() -> None:
    tutor = _tutor()
    tutor.explicacoes.append(explicacao_stall())
    m = montar(tutor=tutor)
    await m.diz_no_grupo(ANA, "!add stall")

    salvo, card = await m.marca_no_grupo(BIA, "stall2 | to avoid committing")

    assert "Saved: *stall*" in salvo and "tag me" in card
    assert m.banco.do_espaco(GRUPO).obter_sessao().estado == Estado.AWAIT_ACTION


async def test_opcao_4_no_grupo_descarta_a_palavra_recem_criada() -> None:
    m = _grupo()
    await m.diz_no_grupo(ANA, "!add stall")

    (resposta,) = await m.diz_no_grupo(BIA, "!5")

    assert resposta.startswith("🗑️ Ignored *stall*")
    assert m.banco.do_espaco(GRUPO).obter_entrada("stall") is None


async def test_ciclo_completo_stall_com_dois_alunos() -> None:
    m = _grupo()
    await m.diz_no_grupo(ANA, "!add stall | the talks stalled")

    exemplos = await m.diz_no_grupo(BIA, "!2")
    avaliacao = await m.diz_no_grupo(ANA, "!The project stalled because the client didn't send it")
    salvo = await m.diz_no_grupo(BIA, "!4")

    assert "Examples with stall" in exemplos[0]
    assert "Almost there" in avaliacao[0]
    assert "Saved: *stall*" in salvo[0] and "!practice stall" in salvo[0] and "!list" in salvo[0]
    for texto in (*exemplos, *avaliacao, *salvo):
        _sem_comandos_do_privado([texto])
    repo = m.banco.do_espaco(GRUPO)
    assert repo.obter_sessao().estado == Estado.IDLE
    (entrada,) = repo.listar_entradas()
    assert entrada.status == "praticada"


async def test_a_frase_guarda_quem_escreveu() -> None:
    m = _grupo()
    await m.diz_no_grupo(ANA, "!add stall")

    await m.diz_no_grupo(BIA, "!The project stalled because the client didn't send it")

    frases = m.banco.do_espaco(GRUPO).listar_frases("stall")
    do_usuario = [f for f in frases if f.autor == "usuario"]
    assert [f.autor_id for f in do_usuario] == [BIA.numero]
    assert all(f.autor_id is None for f in frases if f.autor == "bot")


async def test_a_entrada_guarda_quem_salvou_no_grupo() -> None:
    """M28 (spec 12): `Entry.autor_id` só existe em grupo (é o que torna "termos por pessoa"
    possível dentro de um grupo)."""
    m = _grupo()

    await m.diz_no_grupo(ANA, "!add stall")

    (entrada,) = m.banco.do_espaco(GRUPO).listar_entradas()
    assert entrada.autor_id == ANA.numero


async def test_sinonimos_pelo_menu_3() -> None:
    m = _grupo()
    await m.diz_no_grupo(ANA, "!add stall")

    (resposta,) = await m.diz_no_grupo(CAIO, "!3")

    assert "Synonyms for stall" in resposta and "4️⃣ Just save" in resposta


async def test_add_sem_palavra_explica_o_uso() -> None:
    m = _grupo()

    assert await m.diz_no_grupo(ANA, "!add") == [messages.grupo_add_uso("!")]
    assert m.tutor.chamadas == []


async def test_add_com_outra_palavra_aberta_salva_a_anterior_antes() -> None:
    m = _grupo()
    await m.diz_no_grupo(ANA, "!add stall")
    m.tutor.explicacoes[:] = [explicacao_stall().model_copy(update={"palavra": "hedge"})]
    m.tutor.expansoes[:] = [expansoes()]

    respostas = await m.diz_no_grupo(BIA, "!add hedge")

    assert "Saved: *stall*" in respostas[0]
    assert "*hedge*" in respostas[-1]
    assert sorted(e.slug for e in m.banco.do_espaco(GRUPO).listar_entradas()) == ["hedge", "stall"]


async def test_palavra_nova_pelo_roteamento_marcando_o_bot_salva_a_aberta_e_abre_a_nova() -> None:
    tutor = _tutor()
    tutor.roteamentos = [Roteamento(intencao="nova_palavra", palavra="hedge")]
    tutor.explicacoes.append(explicacao_stall())
    m = montar(tutor=tutor)
    await m.diz_no_grupo(ANA, "!add stall")

    salvo, card = await m.marca_no_grupo(BIA, "hedge")

    assert "Saved: *stall*" in salvo and "tag me" in card
    assert [e.slug for e in m.banco.do_espaco(GRUPO).listar_entradas()] == ["stall"]
    assert m.banco.do_espaco(GRUPO).obter_sessao().estado == Estado.AWAIT_ACTION


# --- fora de atividade: sem IA ----------------------------------------------------------------


@pytest.mark.parametrize("texto", ["!stall", "!hello there", "!1", "!yes"])
async def test_texto_com_prefixo_fora_de_atividade_recebe_a_ajuda_sem_chamar_a_ia(
    texto: str,
) -> None:
    m = _grupo()

    respostas = await m.diz_no_grupo(ANA, texto)

    assert respostas == [messages.ajuda_do_grupo("!")]
    assert m.tutor.chamadas == []


@pytest.mark.parametrize(
    "comando",
    [
        "!export",
        "!song paper plane",
        "!info 1",
        "!status",
        "!cancel",
        "!pending",
        "!profile",
    ],
)
async def test_comando_do_privado_no_grupo_e_recusado_com_a_ajuda_do_grupo(comando: str) -> None:
    m = _grupo()

    respostas = await m.diz_no_grupo(ANA, comando)

    assert respostas == [messages.ajuda_do_grupo("!")]
    assert m.tutor.chamadas == []
    _sem_comandos_do_privado(respostas)


async def test_a_barra_vale_como_o_exclamacao_no_grupo() -> None:
    m = _grupo()

    assert await m.diz_no_grupo(ANA, "/list") == [messages.sem_entradas("!")]
    assert await m.diz_no_grupo(ANA, "/export") == [messages.ajuda_do_grupo("!")]
    assert await m.diz_no_grupo(ANA, "/") == []  # barra sozinha ainda é conversa


async def test_a_ajuda_do_grupo_so_cita_comandos_do_grupo() -> None:
    m = _grupo()

    (ajuda,) = await m.diz_no_grupo(ANA, "!help")

    _sem_comandos_do_privado([ajuda])
    for comando in ("delete", "list", "practice", "review", "daily", "group", "level"):
        assert f"!{comando}" in ajuda
    for escondido in ("teacher", "student", "activate"):
        assert escondido not in ajuda
    for do_privado in ("export", "song", "cancel", "status", "pending"):
        assert f"!{do_privado}" not in ajuda and f"/{do_privado}" not in ajuda


# --- !list, !practice -------------------------------------------------------------------------


async def test_list_vazio_e_com_palavras_no_titulo_da_turma() -> None:
    m = _grupo()
    assert await m.diz_no_grupo(ANA, "!list") == [messages.sem_entradas("!")]

    await m.diz_no_grupo(ANA, "!add stall")
    await m.diz_no_grupo(ANA, "!4")
    (lista,) = await m.diz_no_grupo(BIA, "!list")

    assert "The class's words" in lista and "1. stall" in lista
    assert "!practice 1 to practice one" in lista
    assert "!info" not in lista
    _sem_comandos_do_privado([lista])


async def test_list_pagina_invalida_cita_o_prefixo_do_grupo() -> None:
    m = _grupo()
    await m.diz_no_grupo(ANA, "!add stall")

    (resposta,) = await m.diz_no_grupo(ANA, "!list 9")

    assert resposta == messages.pagina_invalida("!")


async def test_practice_retoma_uma_palavra_do_caderno_da_turma() -> None:
    m = _grupo()
    await m.diz_no_grupo(ANA, "!add stall")
    await m.diz_no_grupo(ANA, "!4")

    (card,) = await m.diz_no_grupo(BIA, "!practice stall")

    assert "*stall*" in card and "2️⃣ See more examples" in card


async def test_practice_por_numero_e_palavra_inexistente() -> None:
    m = _grupo()
    await m.diz_no_grupo(ANA, "!add stall")
    await m.diz_no_grupo(ANA, "!4")
    m.tutor.explicacoes.append(explicacao_stall())

    assert "*stall*" in (await m.diz_no_grupo(BIA, "!practice 1"))[0]
    nao_achou = (await m.diz_no_grupo(BIA, "!practice zzz"))[0]
    assert "the class's words" in nao_achou and "!list" in nao_achou
    _sem_comandos_do_privado([nao_achou])


# --- !delete ----------------------------------------------------------------------------------


async def test_delete_por_palavra_e_por_numero_remove_da_lista_da_turma() -> None:
    m = _grupo()
    turma = m.banco.do_espaco(GRUPO)
    await m.diz_no_grupo(ANA, "!add stall")
    await m.diz_no_grupo(ANA, "!4")
    m.tutor.explicacoes[:] = [explicacao_stall().model_copy(update={"palavra": "hedge"})]
    await m.diz_no_grupo(ANA, "!add hedge")
    await m.diz_no_grupo(ANA, "!0")

    assert await m.diz_no_grupo(ANA, "!delete stall") == ["🗑️ *stall* deleted."]
    assert [e.slug for e in turma.listar_entradas()] == ["hedge"]
    assert await m.diz_no_grupo(ANA, "!delete 1") == ["🗑️ *hedge* deleted."]
    assert turma.listar_entradas() == []


async def test_delete_de_outra_pessoa_e_recusado_e_a_palavra_fica() -> None:
    """M54 (ADR-0052): só quem adicionou, admin do bot ou o dono apagam."""
    m = _grupo()
    turma = m.banco.do_espaco(GRUPO)
    await m.diz_no_grupo(ANA, "!add stall")
    await m.diz_no_grupo(ANA, "!4")

    (recusa,) = await m.diz_no_grupo(BIA, "!delete stall")

    assert recusa == messages.so_quem_adicionou_apaga("!")
    assert [e.slug for e in turma.listar_entradas()] == ["stall"]
    _sem_comandos_do_privado([recusa])


async def test_admin_do_bot_apaga_palavra_de_qualquer_um() -> None:
    m = montar(tutor=_tutor(), admins=(BIA.numero,))
    await m.diz_no_grupo(ANA, "!add stall")
    await m.diz_no_grupo(ANA, "!4")

    assert await m.diz_no_grupo(BIA, "!delete stall") == ["🗑️ *stall* deleted."]
    assert m.banco.do_espaco(GRUPO).listar_entradas() == []


async def test_dono_apaga_palavra_de_qualquer_um() -> None:
    m = _grupo()
    await m.diz_no_grupo(ANA, "!add stall")
    await m.diz_no_grupo(ANA, "!4")

    dono = Autor(DONO_NUMERO, "Dono")
    assert await m.diz_no_grupo(dono, "!delete 1") == ["🗑️ *stall* deleted."]
    assert m.banco.do_espaco(GRUPO).listar_entradas() == []


async def test_palavra_sem_autor_so_o_admin_apaga() -> None:
    m = montar(tutor=_tutor(), admins=(BIA.numero,))
    turma = m.banco.do_espaco(GRUPO)
    await m.diz_no_grupo(ANA, "!add stall")
    await m.diz_no_grupo(ANA, "!4")
    (entrada,) = turma.listar_entradas()
    turma.salvar_entrada(entrada.model_copy(update={"autor_id": None}))

    (recusa,) = await m.diz_no_grupo(ANA, "!delete stall")
    assert recusa == messages.so_quem_adicionou_apaga("!")

    assert await m.diz_no_grupo(BIA, "!delete stall") == ["🗑️ *stall* deleted."]


async def test_delete_inexistente_e_sem_argumento_citam_o_prefixo_do_grupo() -> None:
    m = _grupo()

    (uso,) = await m.diz_no_grupo(ANA, "!delete")
    (nao_achou,) = await m.diz_no_grupo(ANA, "!delete zzz")

    assert uso == messages.grupo_delete_uso("!")
    assert "the class's words" in nao_achou and "!list" in nao_achou
    _sem_comandos_do_privado([uso, nao_achou])


async def test_delete_da_palavra_aberta_zera_a_sessao() -> None:
    m = _grupo()
    turma = m.banco.do_espaco(GRUPO)
    await m.diz_no_grupo(ANA, "!add stall")

    await m.diz_no_grupo(ANA, "!delete stall")

    assert turma.listar_entradas() == []
    assert Estado(turma.obter_sessao().estado) == Estado.IDLE


# --- !daily (M35, ADR-0033) -------------------------------------------------------------------


async def test_daily_sem_argumento_mostra_a_configuracao_a_qualquer_membro() -> None:
    m = _grupo()

    (resposta,) = await m.diz_no_grupo(ANA, "!daily")

    assert "every weekday around 19:00" in resposta and "Next one:" in resposta
    assert "5 words per review" in resposta
    _sem_comandos_do_privado([resposta])


async def test_daily_so_admin_do_bot_muda_e_aluno_recebe_a_recusa() -> None:
    m = montar(tutor=_tutor(), admins=(BIA.numero,))

    (recusa,) = await m.diz_no_grupo(ANA, "!daily 20h")
    (ok,) = await m.diz_no_grupo(BIA, "!daily 20:30 weekends on size 3")

    assert recusa == messages.so_admin_configura("!")
    assert "Daily review updated" in ok and "every day around 20:30" in ok and "3 words" in ok
    perfil = m.banco.do_espaco(GRUPO).obter_perfil()
    assert perfil is not None
    assert (perfil.diaria_hora, perfil.diaria_minuto) == (20, 30)
    assert perfil.diaria_fim_de_semana is True and perfil.tamanho_revisao == 3


async def test_daily_off_on_e_invalido() -> None:
    m = _grupo()
    dono = Autor(DONO_NUMERO, "Dono")

    (desligada,) = await m.diz_no_grupo(dono, "!daily off")
    (invalida,) = await m.diz_no_grupo(dono, "!daily banana")
    (ligada,) = await m.diz_no_grupo(dono, "!daily on")

    assert "It's off" in desligada
    assert invalida == messages.diaria_invalida("!")
    assert "every weekday around 19:00" in ligada
    _sem_comandos_do_privado([desligada, invalida, ligada])


async def test_reminder_no_grupo_virou_apelido_da_daily() -> None:
    m = _grupo()

    (resposta,) = await m.diz_no_grupo(ANA, "!reminder 3")

    assert resposta == messages.lembrete_virou_daily("!")
    perfil = m.banco.do_espaco(GRUPO).obter_perfil()
    assert perfil is not None and perfil.lembretes_por_dia == 1  # nada mudou


async def test_o_grupo_nao_recebe_a_dica_de_lembretes_do_privado() -> None:
    m = _grupo()
    await m.diz_no_grupo(ANA, "!add stall")

    (salvo,) = await m.diz_no_grupo(ANA, "!4")

    assert "reminder" not in salvo.lower()


# --- membros, papéis e !group -----------------------------------------------------------------


async def test_quem_manda_a_primeira_mensagem_com_prefixo_entra_como_aluno() -> None:
    m = _grupo()

    await m.diz_no_grupo(ANA, "!help")

    membro = m.banco.do_espaco(GRUPO).obter_membro(ANA.numero)
    assert membro is not None and (membro.papel, membro.nome) == ("aluno", "Ana")


async def test_o_nome_do_whatsapp_atualiza_o_cadastro() -> None:
    m = _grupo()
    await m.diz_no_grupo(Autor(ANA.numero, None), "!help")
    await m.diz_no_grupo(ANA, "!help")

    assert m.banco.do_espaco(GRUPO).obter_membro(ANA.numero).nome == "Ana"  # type: ignore[union-attr]


async def test_teacher_pelo_dono_com_o_numero_escrito() -> None:
    m = _grupo()
    dono = Autor(DONO_NUMERO, "Dono")

    (resposta,) = await m.diz_no_grupo(dono, f"!teacher {BIA.numero}")

    assert resposta == messages.papel_alterado(None, "professor")
    assert m.banco.do_espaco(GRUPO).obter_membro(BIA.numero).papel == "professor"  # type: ignore[union-attr]


async def test_teacher_com_mencao_do_payload_e_nome_do_membro_ja_conhecido() -> None:
    m = _grupo()
    await m.diz_no_grupo(BIA, "!help")
    dono = Autor(DONO_NUMERO, "Dono", mencionados=(BIA.numero,))

    (resposta,) = await m.diz_no_grupo(dono, "!teacher @Bia")

    assert resposta == messages.papel_alterado("Bia", "professor")


async def test_um_professor_promove_e_rebaixa_outros() -> None:
    m = _grupo()
    await m.diz_no_grupo(Autor(DONO_NUMERO, "Dono"), f"!teacher {ANA.numero}")

    await m.diz_no_grupo(ANA, f"!teacher {BIA.numero}")
    assert m.banco.do_espaco(GRUPO).obter_membro(BIA.numero).papel == "professor"  # type: ignore[union-attr]

    (resposta,) = await m.diz_no_grupo(ANA, f"!student {BIA.numero}")
    assert resposta == messages.papel_alterado(None, "aluno")
    assert m.banco.do_espaco(GRUPO).obter_membro(BIA.numero).papel == "aluno"  # type: ignore[union-attr]


async def test_aluno_que_tenta_teacher_recebe_a_resposta_de_comando_desconhecido() -> None:
    m = _grupo()
    await m.diz_no_grupo(ANA, "!help")

    respostas = await m.diz_no_grupo(ANA, f"!teacher {ANA.numero}")

    assert respostas == [messages.ajuda_do_grupo("!")]
    assert m.banco.do_espaco(GRUPO).obter_membro(ANA.numero).papel == "aluno"  # type: ignore[union-attr]


async def test_teacher_tolera_o_nono_digito_e_nao_duplica_o_membro() -> None:
    m = _grupo()
    await m.diz_no_grupo(Autor("553199998888", "Ana"), "!help")  # a conta sem o 9
    dono = Autor(DONO_NUMERO, "Dono")

    await m.diz_no_grupo(dono, "!teacher 5531999998888")  # o mesmo número, com o 9

    membros = m.banco.do_espaco(GRUPO).listar_membros()
    da_ana = [(n, mb.papel) for n, mb in membros if n.startswith("55319999")]
    assert da_ana == [("553199998888", "professor")]  # um só cadastro, o do número sem o 9


async def test_teacher_sem_alvo_explica_o_uso_e_os_papeis_nao_aparecem_no_help() -> None:
    m = _grupo()

    (resposta,) = await m.diz_no_grupo(Autor(DONO_NUMERO, "Dono"), "!teacher")

    assert resposta == messages.papel_uso("teacher", "!")


async def test_group_mostra_a_turma_sem_telefone() -> None:
    m = _grupo()
    await m.diz_no_grupo(ANA, "!add stall")
    await m.diz_no_grupo(ANA, "!4")
    await m.diz_no_grupo(BIA, "!help")
    await m.diz_no_grupo(Autor(CAIO.numero, None), "!help")
    await m.diz_no_grupo(Autor(DONO_NUMERO, "Prof"), f"!teacher {BIA.numero}")

    (resposta,) = await m.diz_no_grupo(ANA, "!group")

    assert "Your class" in resposta and "Level: B1-B2" in resposta
    assert "Words: 1" in resposta
    assert "• Ana (student)" in resposta
    assert "• Bia (teacher)" in resposta
    assert "• Student 1 (student)" in resposta  # sem nome: nunca o número
    for telefone in (ANA.numero, BIA.numero, CAIO.numero, DONO_NUMERO):
        assert telefone not in resposta
    assert "@" not in resposta  # sem menção: não notifica ninguém
    _sem_comandos_do_privado([resposta])


async def test_group_mostra_a_revisao_diaria_e_o_proximo_horario() -> None:
    m = _grupo()

    (resposta,) = await m.diz_no_grupo(ANA, "!group")

    assert "every weekday around 19:00" in resposta and "Next review" in resposta


# --- limite de mensagens e privado ------------------------------------------------------------


async def test_qualquer_mensagem_com_prefixo_de_qualquer_participante_conta_como_resposta() -> None:
    m = _grupo()
    conversa = m.router.conversa_do(GRUPO)
    for _ in range(3):
        await conversa.enviar("bot fala sozinho")
    antes = len(m.channel.textos_enviados)
    await conversa.enviar("a quarta seria descartada")
    assert len(m.channel.textos_enviados) == antes

    respostas = await m.diz_no_grupo(CAIO, "!help")  # outro participante fala

    assert respostas == [messages.ajuda_do_grupo("!")]


async def test_o_apelido_exclamacao_no_privado_vale_a_barra() -> None:
    m = _grupo()
    await m.diz("stall")
    await m.diz("4")

    lista_com_barra = await m.diz("/list")
    lista_com_exclamacao = await m.diz("!list")

    assert lista_com_exclamacao == lista_com_barra
    assert "Your words" in lista_com_exclamacao[0]  # o título do privado, não o da turma


async def test_no_privado_exclamacao_sem_letra_continua_sendo_texto() -> None:
    m = _grupo()
    await m.diz("stall")

    await m.diz("!!! wow")  # não é comando: vai para a IA como a frase de sempre

    assert m.tutor.chamadas[-1][0] == "route"


async def test_o_privado_segue_sem_prefixo_e_com_a_barra() -> None:
    m = _grupo()

    (card,) = await m.diz("stall")

    assert "Now, you can write one or more sentences using *stall*" in card
    assert "!1" not in card


# --- lembretes do grupo (o agendador) ---------------------------------------------------------


def _agendador_do_grupo(m: Montagem, *, autorizado: bool = True):  # type: ignore[no-untyped-def]
    from zoneinfo import ZoneInfo

    from app.services.lembretes import Agendador

    async def dormir(_: float) -> None:
        return None

    return Agendador(
        router=m.router,
        banco=m.banco,
        agora=m.relogio.agora,
        fuso=ZoneInfo("UTC"),
        dormir=dormir,
        grupo_autorizado=lambda _grupo: autorizado,
        jitter_do_grupo=sem_jitter,
    )


def _grupo_com_diaria_e_palavra_vencida(m: Montagem) -> None:
    from datetime import timedelta

    from app.domain.models import Membro, Profile
    from tests.helpers import T0
    from tests.test_agendador import _entrada_vencida

    espaco = m.banco.do_espaco(GRUPO)
    espaco.salvar_membro(ANA.numero, Membro(nome="Ana", entrou_em=T0))
    espaco.criar_entrada(_entrada_vencida())
    espaco.salvar_perfil(Profile(nivel="B1-B2", chat_id=GRUPO, proxima_diaria=T0))
    m.relogio.avancar(timedelta(seconds=1))


async def test_a_diaria_do_grupo_inicia_a_revisao_sem_marcar_ninguem() -> None:
    m = _grupo()
    _grupo_com_diaria_e_palavra_vencida(m)

    await _agendador_do_grupo(m)._tick()

    ((chat, texto),) = m.channel.textos_enviados
    assert chat == GRUPO
    assert "Practice time" in texto and "Anyone can answer" in texto
    assert m.channel.mencoes_enviadas == [] or not m.channel.mencoes_enviadas[-1][1]
    _sem_comandos_do_privado([texto])
    assert m.banco.do_espaco(GRUPO).obter_sessao().estado == Estado.REVIEWING


async def test_grupo_desativado_nao_recebe_lembrete() -> None:
    m = _grupo()
    _grupo_com_diaria_e_palavra_vencida(m)

    await _agendador_do_grupo(m, autorizado=False)._tick()

    assert m.channel.textos_enviados == []


async def test_o_lembrete_de_um_aluno_no_privado_continua_igual() -> None:
    from app.domain.models import Profile
    from tests.helpers import T0
    from tests.test_agendador import _entrada_vencida

    m = _grupo()
    m.repo.criar_entrada(_entrada_vencida())
    m.repo.salvar_perfil(
        Profile(nivel="B1-B2", chat_id=CHAT, lembretes_por_dia=3, proximo_lembrete=T0)
    )

    await _agendador_do_grupo(m, autorizado=False)._tick()  # o filtro é só de grupos

    ((chat, texto),) = m.channel.textos_enviados
    assert chat == CHAT and "Type 0 to leave the practice" in texto


# --- !level (M33, ADR-0031) -------------------------------------------------------------------


async def test_level_sem_argumento_mostra_o_nivel_da_turma_para_qualquer_membro() -> None:
    m = _grupo()

    (resposta,) = await m.diz_no_grupo(ANA, "!level")

    nivel = m.banco.do_espaco(GRUPO).obter_perfil().nivel  # type: ignore[union-attr]
    assert resposta == messages.nivel_atual(nivel, "!")
    assert m.tutor.chamadas == []
    _sem_comandos_do_privado([resposta])


async def test_level_pelo_dono_muda_o_nivel_so_da_turma() -> None:
    m = _grupo()
    dono = Autor(DONO_NUMERO, "Dono")

    (resposta,) = await m.diz_no_grupo(dono, "!level b2-c1")

    assert resposta == messages.nivel_alterado("B2-C1")
    assert m.banco.do_espaco(GRUPO).obter_perfil().nivel == "B2-C1"  # type: ignore[union-attr]
    assert m.banco.do_espaco(CHAT).obter_perfil() is None  # o privado de ninguém mudou


async def test_level_por_professor_da_turma_muda_o_nivel() -> None:
    m = _grupo()
    await m.diz_no_grupo(Autor(DONO_NUMERO, "Dono"), f"!teacher {BIA.numero}")

    (resposta,) = await m.diz_no_grupo(BIA, "!level A2-B1")

    assert resposta == messages.nivel_alterado("A2-B1")
    assert m.banco.do_espaco(GRUPO).obter_perfil().nivel == "A2-B1"  # type: ignore[union-attr]


async def test_aluno_nao_muda_o_nivel_e_o_nivel_fica_como_estava() -> None:
    m = _grupo()
    await m.diz_no_grupo(ANA, "!help")
    antes = m.banco.do_espaco(GRUPO).obter_perfil().nivel  # type: ignore[union-attr]
    outro = "B2-C1" if antes != "B2-C1" else "A2-B1"

    (resposta,) = await m.diz_no_grupo(ANA, f"!level {outro}")

    assert resposta == messages.nivel_so_professor("!")
    assert m.banco.do_espaco(GRUPO).obter_perfil().nivel == antes  # type: ignore[union-attr]
    _sem_comandos_do_privado([resposta])


async def test_level_invalido_pelo_professor_cita_o_prefixo_do_grupo() -> None:
    m = _grupo()

    (resposta,) = await m.diz_no_grupo(Autor(DONO_NUMERO, "Dono"), "!level C3")

    assert resposta == messages.nivel_invalido()
