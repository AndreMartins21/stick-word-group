"""Testes de ponta a ponta dos fluxos (M9): interface em inglês, menu único, roteamento por IA."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.domain.models import Estado, Explanation, Roteamento, Sense, Synonym
from app.services.fake_llm import FakeTutor
from app.services.llm import LLMError
from tests.helpers import CHAT, Montagem, avaliacao, expansoes, explicacao_stall
from tests.helpers import montar as _montar


def montar(**kwargs: Any) -> Montagem:
    """Uma turma A2-B1, que vê a linha 🇧🇷 (ADR-0032)."""
    return _montar(**{"nivel_padrao": "A2-B1", **kwargs})


EXEMPLOS = ["The talks [[stalled]] again.", "My car [[stalled]].", "Don't [[stall]] me."]
SINONIMOS = [
    Synonym(
        expressao="stumble",
        significado="to almost fail or lose momentum",
        exemplo="The talks [[stumbled]] early on.",
    ),
    Synonym(
        expressao="grind to a halt",
        significado="to slow down until it stops completely",
        exemplo="Production [[ground to a halt]] last week.",
    ),
]


def _roteamento_frase(veredito: str = "quase") -> Roteamento:
    av = avaliacao(veredito)
    return Roteamento(
        intencao="frase",
        usa_palavra_alvo=av.usa_palavra_alvo,
        sentido_correto=av.sentido_correto,
        veredito=av.veredito,
        correcoes=av.correcoes,
        versao_natural=av.versao_natural,
        explicacao=av.explicacao,
    )


def _tutor_completo() -> FakeTutor:
    return FakeTutor(
        explicacoes=[explicacao_stall()],
        exemplos=[EXEMPLOS],
        sinonimos=[SINONIMOS],
        roteamentos=[_roteamento_frase("quase")],
        expansoes=[expansoes()],
    )


# ---- o ciclo "stall", do começo ao fim -------------------------------------------------------


async def test_ciclo_completo_do_stall() -> None:
    m = montar(tutor=_tutor_completo())

    # 1. O aluno manda a palavra com a frase; o card sai numa mensagem só, com o menu único.
    (card,) = await m.diz("stall | the talks stalled")
    assert card == (
        "*stall* (verb) — B2\n"
        "🇧🇷 travar, emperrar\n"
        "📖 to stop making progress\n"
        '💡 "the car stalled" = the car died\n'
        '"The talks stalled."\n'
        "\n"
        "↔️ enrolar — to delay on purpose\n"
        "Want another meaning? Tag me with *stall | to delay on purpose*\n"
        "\n"
        "Now, tag me with a sentence using *stall*, or tag me with a number:\n"
        "2️⃣ See more examples\n"
        "3️⃣ Check synonyms\n"
        "4️⃣ Just save\n"
        "5️⃣ Don't save"
    )
    assert m.repo.obter_sessao().estado == Estado.AWAIT_ACTION

    # 2. Pede exemplos.
    (exemplos,) = await m.diz("2")
    assert exemplos.startswith("📝 *Examples with stall*")
    assert "1. The talks stalled again." in exemplos
    assert "[[" not in exemplos
    assert "Want to try a sentence of your own?" in exemplos

    # 3. Pede sinônimos: a partir daqui a opção 2 do menu vira "See more synonyms".
    (sinonimos,) = await m.diz("3")
    assert sinonimos.startswith("🔄 *Synonyms for stall*")
    assert "*stumble* = to almost fail or lose momentum" in sinonimos
    assert '_Example: "The talks stumbled early on."_' in sinonimos
    assert "3️⃣ See more synonyms" in sinonimos

    # 4. Manda uma frase de prática (texto livre, roteado pela IA numa única chamada).
    (avaliada,) = await m.diz("The project stalled because the client didn't sent the documents.")
    assert avaliada == (
        "⚠️ *Almost there!* The meaning is right.\n"
        "✏️ didn't sent → didn't send\n"
        "✨ The project stalled because the client didn't send the documents.\n"
        '💬 After "didn\'t", the verb stays in the base form.\n'
        "\n"
        "Want to try another sentence?\n"
        "Now, tag me with a sentence using *stall*, or tag me with a number:\n"
        "2️⃣ See more examples\n"
        "3️⃣ See more synonyms\n"
        "4️⃣ Just save\n"
        "5️⃣ Don't save"
    )
    entrada = m.repo.obter_entrada("stall")
    assert entrada is not None
    assert entrada.status == "praticada"

    # 5. Salva: o card fecha e sugere expressões relacionadas, sem menu.
    (salvo,) = await m.diz("4")
    assert salvo == (
        "✅ Saved: *stall*.\n"
        "Practice it any time with !practice stall, or see everything with !list.\n"
        "You might like these too: *stall for time*, *stall out*, *stalled talks*.\n"
        "Add another one whenever you want: tag me with a word."
    )
    assert m.repo.obter_sessao().estado == Estado.IDLE
    # Nenhuma entrada de expansão foi criada sozinha (M9: é só sugestão em texto).
    assert len(m.repo.listar_entradas()) == 1

    chamadas = dict(m.tutor.chamadas)
    assert chamadas["explain"] == ("stall | the talks stalled", "A2-B1")


async def test_frase_logo_apos_o_card_e_roteada_sem_passar_pelo_menu() -> None:
    tutor = FakeTutor(explicacoes=[explicacao_stall()], roteamentos=[_roteamento_frase("correta")])
    m = montar(tutor=tutor)
    await m.diz("stall")

    (resposta,) = await m.diz("the project stalled last week")

    assert resposta.startswith("✅ *Perfect!*")
    assert m.repo.obter_sessao().estado == Estado.AWAIT_ACTION


async def test_so_salvar_sem_praticar_deixa_a_entrada_como_nova() -> None:
    m = montar(tutor=FakeTutor(explicacoes=[explicacao_stall()], expansoes=[expansoes()]))
    await m.diz("stall")

    (resposta,) = await m.diz("4")

    assert resposta.startswith("✅ Saved: *stall*.")
    entrada = m.repo.obter_entrada("stall")
    assert entrada is not None
    assert entrada.status == "nova"


# ---- quantidade pedida em texto livre (Case B/C) ---------------------------------------------


async def test_quantidade_personalizada_de_exemplos() -> None:
    tutor = FakeTutor(
        explicacoes=[explicacao_stall()],
        exemplos=[EXEMPLOS],
        roteamentos=[Roteamento(intencao="exemplos", quantidade=5)],
    )
    m = montar(tutor=tutor)
    await m.diz("stall")

    await m.diz("can you show me 5 examples?")

    chamada = next(c for c in m.tutor.chamadas if c[0] == "examples")
    assert chamada[1][3] == 5  # (palavra, traducao, nivel, n)


async def test_quantidade_fora_do_intervalo_e_limitada_entre_1_e_10() -> None:
    tutor = FakeTutor(
        explicacoes=[explicacao_stall()],
        sinonimos=[SINONIMOS],
        roteamentos=[Roteamento(intencao="sinonimos", quantidade=99)],
    )
    m = montar(tutor=tutor)
    await m.diz("stall")

    await m.diz("give me tons of synonyms")

    chamada = next(c for c in m.tutor.chamadas if c[0] == "synonyms")
    assert chamada[1][3] == 10


async def test_sinonimos_nao_repetidos_entre_chamadas() -> None:
    tutor = FakeTutor(
        explicacoes=[explicacao_stall()],
        sinonimos=[SINONIMOS[:1], SINONIMOS[1:]],
    )
    m = montar(tutor=tutor)
    await m.diz("stall")
    await m.diz("3")

    await m.diz("3")

    chamadas = [c for c in m.tutor.chamadas if c[0] == "synonyms"]
    assert len(chamadas) == 2
    # a 2ª chamada recebe o sinônimo já mostrado, para o tutor não repeti-lo
    assert chamadas[1][1] == ("stall", "travar, emperrar", "A2-B1", 3)


# ---- outras intenções do roteamento -----------------------------------------------------------


async def test_pedido_de_ajuda_livre_responde_e_reenvia_o_menu() -> None:
    tutor = FakeTutor(
        explicacoes=[explicacao_stall()],
        roteamentos=[Roteamento(intencao="pedido", resposta="It's pronounced /stawl/.")],
    )
    m = montar(tutor=tutor)
    await m.diz("stall")

    (resposta,) = await m.diz("how do I pronounce it?")

    assert resposta.startswith("It's pronounced /stawl/.")
    assert "Just save" in resposta
    assert m.repo.obter_sessao().estado == Estado.AWAIT_ACTION


async def test_fora_do_escopo_nao_quebra_a_sessao() -> None:
    tutor = FakeTutor(
        explicacoes=[explicacao_stall()],
        roteamentos=[
            Roteamento(
                intencao="fora_do_escopo",
                resposta="I can only help with English — send me a word, an expression or a sentence.",
            )
        ],
    )
    m = montar(tutor=tutor)
    await m.diz("stall")

    (resposta,) = await m.diz("what's the capital of France?")

    assert "I can only help with English" in resposta
    assert m.repo.obter_sessao().estado == Estado.AWAIT_ACTION


async def test_salvar_por_texto_livre_funciona_como_o_menu() -> None:
    tutor = FakeTutor(
        explicacoes=[explicacao_stall()],
        expansoes=[expansoes()],
        roteamentos=[Roteamento(intencao="salvar")],
    )
    m = montar(tutor=tutor)
    await m.diz("stall")

    (resposta,) = await m.diz("let's just save it")

    assert resposta.startswith("✅ Saved: *stall*.")
    assert m.repo.obter_sessao().estado == Estado.IDLE


async def test_palavra_nova_no_meio_do_fluxo_salva_a_anterior_e_explica_a_nova() -> None:
    nova = explicacao_stall().model_copy(update={"palavra": "hedge", "sentido_do_contexto": "s1"})
    tutor = FakeTutor(
        explicacoes=[explicacao_stall(), nova],
        expansoes=[expansoes()],
        roteamentos=[Roteamento(intencao="nova_palavra", palavra="hedge")],
    )
    m = montar(tutor=tutor)
    await m.diz("stall")

    salvo, novo_card = await m.diz("hedge")

    assert salvo.startswith("✅ Saved: *stall*.")
    assert novo_card.startswith("*hedge*")
    assert m.repo.obter_entrada("stall") is not None
    assert m.repo.obter_entrada("hedge") is not None
    assert m.repo.obter_sessao().entry_id == "hedge"


# ---- erros, expiração e limites ---------------------------------------------------------------


async def test_falha_da_ia_avisa_e_mantem_a_sessao() -> None:
    tutor = FakeTutor(explicacoes=[explicacao_stall()], roteamentos=[LLMError("boom")])
    m = montar(tutor=tutor)
    await m.diz("stall")

    (resposta,) = await m.diz("the talks stalled")

    assert "I couldn't reach the AI" in resposta
    assert m.repo.obter_sessao().estado == Estado.AWAIT_ACTION
    assert [f for f in m.repo.listar_frases("stall") if f.autor == "usuario"] == []


async def test_entrada_que_nao_e_ingles_explica_o_motivo_e_volta_para_idle() -> None:
    from app.domain.models import Explanation

    invalida = Explanation(ok=False, motivo_erro="This looks like Portuguese.")
    m = montar(tutor=FakeTutor(explicacoes=[invalida]))

    (resposta,) = await m.diz("obrigado")

    assert "doesn't look like an English word" in resposta
    assert "Portuguese" in resposta
    assert m.repo.listar_entradas() == []
    assert m.repo.obter_sessao().estado == Estado.IDLE


async def test_sessao_parada_por_mais_de_3_horas_volta_para_idle() -> None:
    outra = explicacao_stall().model_copy(update={"palavra": "hedge"})
    m = montar(tutor=FakeTutor(explicacoes=[explicacao_stall(), outra]))
    await m.diz("stall")
    m.relogio.avancar(timedelta(hours=3, minutes=1))

    (resposta,) = await m.diz("1")  # em AWAIT_ACTION seria "hear it"

    assert resposta.startswith("*hedge*")  # tratou "1" como texto novo, em IDLE
    assert m.repo.obter_entrada("stall") is not None  # o que havia continua salvo


async def test_sessao_dentro_das_3_horas_continua() -> None:
    tutor = FakeTutor(explicacoes=[explicacao_stall()], exemplos=[EXEMPLOS])
    m = montar(tutor=tutor)
    await m.diz("stall")
    m.relogio.avancar(timedelta(hours=2, minutes=59))

    (resposta,) = await m.diz("2")

    assert resposta.startswith("📝 *Examples with stall*")


async def test_cada_envio_espera_de_1_a_2_segundos_e_o_digitando_liga_e_desliga() -> None:
    m = montar(tutor=FakeTutor(explicacoes=[explicacao_stall()]))

    await m.diz("stall")

    assert m.esperas == [1.5]
    assert m.channel.digitando == [(CHAT, True), (CHAT, False)]


async def test_nunca_manda_mais_de_3_mensagens_sem_resposta_do_aluno() -> None:
    m = montar()
    for _ in range(5):
        await m.conversa.enviar("oi")

    assert len(m.channel.textos_enviados) == 3

    m.conversa.usuario_falou()
    await m.conversa.enviar("de novo")

    assert len(m.channel.textos_enviados) == 4


async def test_falha_no_digitando_nao_derruba_a_resposta() -> None:
    m = montar(tutor=FakeTutor(explicacoes=[explicacao_stall()]))

    async def quebrado(chat_id: str, on: bool) -> None:
        raise ConnectionError("WAHA fora do ar")

    m.channel.typing = quebrado  # type: ignore[method-assign]

    (resposta,) = await m.diz("stall")

    assert resposta.startswith("*stall*")


async def test_midia_responde_que_so_entende_texto() -> None:
    m = montar()

    await m.router.midia_nao_suportada(CHAT)

    assert "only read *text*" in m.channel.textos_enviados[0][1]


async def test_o_nivel_do_perfil_vai_para_a_ia() -> None:
    m = montar(tutor=FakeTutor(explicacoes=[explicacao_stall()]))
    await m.diz("/nivel A2-B1")

    await m.diz("stall")

    assert m.tutor.chamadas[0] == ("explain", ("stall", "A2-B1"))


async def test_sinonimos_ficam_salvos_na_entrada_sem_duplicar() -> None:
    m = montar(
        tutor=FakeTutor(
            explicacoes=[explicacao_stall()],
            sinonimos=[SINONIMOS[:1], SINONIMOS],  # o 2º pedido repete "stumble"
        )
    )
    await m.diz("stall | the talks stalled")

    await m.diz("3")
    await m.diz("3")

    entrada = m.repo.obter_entrada("stall")
    assert entrada is not None
    assert [s.expressao for s in entrada.sinonimos] == ["stumble", "grind to a halt"]


# ---- palavra que já está na lista, 0/skip e opção 4 -------------------------------------------


async def test_palavra_que_ja_existe_avisa_e_mostra_o_que_o_aluno_tem() -> None:
    m = montar(tutor=FakeTutor(explicacoes=[explicacao_stall(), explicacao_stall()]))
    await m.diz("stall")
    await m.diz("0")

    (resposta,) = await m.diz("stall")

    assert resposta == (
        "📌 You already have *stall* in your list.\n"
        "\n"
        "*stall* (verb) — B2\n"
        "🇧🇷 travar, emperrar\n"
        "📖 to stop making progress\n"
        '"The talks stalled."\n'
        "\n"
        "↔️ enrolar — to delay on purpose\n"
        "Want another meaning? Tag me with *stall | to delay on purpose*\n"
        "\n"
        "Now, tag me with a sentence using *stall*, or tag me with a number:\n"
        "2️⃣ See more examples\n"
        "3️⃣ Check synonyms\n"
        "\n"
        "To send another word or command, type !0 or !skip."
    )
    sessao = m.repo.obter_sessao()
    assert (sessao.estado, sessao.entry_id) == (Estado.AWAIT_ACTION, "stall")
    assert len(m.repo.listar_frases("stall")) == 1  # o exemplo não foi gravado de novo


async def test_palavra_que_ja_existe_segue_para_exemplos_e_frases() -> None:
    tutor = FakeTutor(
        explicacoes=[explicacao_stall(), explicacao_stall()],
        exemplos=[EXEMPLOS],
        roteamentos=[_roteamento_frase("correta")],
    )
    m = montar(tutor=tutor)
    await m.diz("stall")
    await m.diz("0")
    await m.diz("stall")

    (exemplos,) = await m.diz("2")
    (avaliada,) = await m.diz("the project stalled last week")

    assert exemplos.startswith("📝 *Examples with stall*")
    assert avaliada.startswith("✅ *Perfect!*")


async def test_zero_e_skip_saem_da_palavra_sem_chamar_a_ia_e_mantem_a_entrada() -> None:
    tutor = FakeTutor(explicacoes=[explicacao_stall()])  # sem roteamentos: rotear levantaria erro
    m = montar(tutor=tutor)
    await m.diz("stall")

    (resposta,) = await m.diz("skip")

    assert resposta == "Alright! Send me another word whenever you want. 🙂"
    assert m.repo.obter_sessao().estado == Estado.IDLE
    assert m.repo.obter_entrada("stall") is not None
    assert [nome for nome, _ in tutor.chamadas] == ["explain"]


async def test_opcao_4_descarta_a_palavra_recem_criada() -> None:
    m = montar(tutor=FakeTutor(explicacoes=[explicacao_stall()]))
    await m.diz("stall")

    (resposta,) = await m.diz("5")

    assert resposta == (
        "🗑️ Ignored *stall*, it's not in your list. Send me another word whenever you want!"
    )
    assert m.repo.obter_entrada("stall") is None
    assert m.repo.obter_sessao().estado == Estado.IDLE


async def test_opcao_4_nao_apaga_palavra_que_o_aluno_ja_tinha() -> None:
    m = montar(tutor=FakeTutor(explicacoes=[explicacao_stall(), explicacao_stall()]))
    await m.diz("stall")
    await m.diz("0")
    await m.diz("stall")  # já existia

    (resposta,) = await m.diz("5")

    assert resposta.startswith("Alright, *stall* stays in your list.")
    assert m.repo.obter_entrada("stall") is not None
    assert m.repo.obter_sessao().estado == Estado.IDLE


async def test_opcao_4_nao_apaga_palavra_em_que_o_aluno_ja_escreveu_uma_frase() -> None:
    tutor = FakeTutor(explicacoes=[explicacao_stall()], roteamentos=[_roteamento_frase("correta")])
    m = montar(tutor=tutor)
    await m.diz("stall")
    await m.diz("the project stalled last week")

    (resposta,) = await m.diz("5")

    assert resposta.startswith("Alright, *stall* stays in your list.")
    assert [f.autor for f in m.repo.listar_frases("stall")] == ["bot", "usuario"]


# ---- a mesma palavra com a tradução escrita de outro jeito pela IA ---------------------------


def _stall_com(traducao: str, *, frase_contexto: str | None) -> Explanation:
    """Uma nova explicação de `stall`, como a IA a devolveria de novo: mesma palavra, mas o texto
    da tradução (e a frase de contexto) mudam de uma chamada para outra."""
    sentido = Sense(
        id="s1", traducao=traducao, definicao="to stop", exemplo="The [[talks]] stalled."
    )
    return explicacao_stall().model_copy(
        update={
            "sentidos": [sentido],
            "sentido_do_contexto": "s1",
            "frase_contexto": frase_contexto,
        }
    )


async def test_palavra_sem_frase_ja_existe_mesmo_que_a_ia_traduza_diferente() -> None:
    """Regressão (produção, 2026-09-25): `grader` → `grader--s2` porque a IA devolveu
    "avaliador ou sistema de correção" em vez de "avaliador"."""
    outra = _stall_com("parar de funcionar", frase_contexto=None)
    m = montar(tutor=FakeTutor(explicacoes=[explicacao_stall(), outra]))
    await m.diz("stall")
    await m.diz("0")

    (resposta,) = await m.diz("stall")

    assert resposta.startswith("📌 You already have *stall* in your list.")
    assert "🇧🇷 travar, emperrar" in resposta  # o que está salvo, não a tradução nova
    assert [e.slug for e in m.repo.listar_entradas()] == ["stall"]


async def test_palavra_com_frase_e_traducao_parecida_ja_existe() -> None:
    parecida = _stall_com("travar", frase_contexto="The [[talks]] stalled.")
    m = montar(tutor=FakeTutor(explicacoes=[explicacao_stall(), parecida]))
    await m.diz("stall")
    await m.diz("0")

    (resposta,) = await m.diz("stall | the talks stalled")

    assert resposta.startswith("📌 You already have *stall* in your list.")
    assert [e.slug for e in m.repo.listar_entradas()] == ["stall"]


async def test_palavra_com_frase_e_outro_sentido_de_verdade_vira_um_novo_cartao() -> None:
    outro_sentido = _stall_com("barraca", frase_contexto="I bought it at a [[stall]].")
    m = montar(tutor=FakeTutor(explicacoes=[explicacao_stall(), outro_sentido]))
    await m.diz("stall")
    await m.diz("0")

    (resposta,) = await m.diz("stall | I bought it at a stall")

    assert resposta.startswith("*stall*")  # card novo, não o aviso
    assert [e.slug for e in m.repo.listar_entradas()] == ["stall", "stall--s2"]


# ---- M31: outro sentido da mesma palavra (`palavra | sentido`) -------------------------------


def _stall_no_sentido_s2() -> Explanation:
    """A IA respondendo a `stall | to delay on purpose`: o sentido pedido, sem frase de contexto."""
    return explicacao_stall(sentido_do_contexto="s2").model_copy(update={"frase_contexto": None})


async def test_card_de_palavra_com_um_so_sentido_nao_lista_outros() -> None:
    m = montar(tutor=FakeTutor(explicacoes=[explicacao_stall(dois_sentidos=False)]))

    (card,) = await m.diz("stall")

    assert "↔️" not in card
    assert "another meaning" not in card


async def test_pedir_outro_sentido_troca_o_card_recem_criado() -> None:
    m = montar(tutor=FakeTutor(explicacoes=[explicacao_stall(), _stall_no_sentido_s2()]))
    await m.diz("stall")

    (card,) = await m.diz("stall | to delay on purpose")

    assert card.startswith("*stall* (verb) — B2\n🇧🇷 enrolar\n📖 to delay on purpose")
    assert "↔️ travar, emperrar — to stop making progress" in card
    assert "Saved" not in card
    (entrada,) = m.repo.listar_entradas()
    assert entrada.slug == "stall" and entrada.sentido.traducao == "enrolar"
    assert [c[0] for c in m.tutor.chamadas] == ["explain", "explain"]  # nada de roteamento
    assert m.repo.obter_sessao().estado == Estado.AWAIT_ACTION


async def test_pedir_outro_sentido_depois_de_escrever_frase_mantem_o_primeiro() -> None:
    tutor = FakeTutor(
        explicacoes=[explicacao_stall(), _stall_no_sentido_s2()],
        roteamentos=[_roteamento_frase("quase")],
    )
    m = montar(tutor=tutor)
    await m.diz("stall")
    await m.diz("the project stalled last week")

    (card,) = await m.diz("stall | to delay on purpose")

    assert card.startswith("*stall* (verb) — B2\n🇧🇷 enrolar")
    assert [e.slug for e in m.repo.listar_entradas()] == ["stall", "stall--s2"]


async def test_pedir_outro_sentido_com_a_ia_fora_do_ar_nao_perde_o_card() -> None:
    m = montar(tutor=FakeTutor(explicacoes=[explicacao_stall(), LLMError("fora do ar")]))
    await m.diz("stall")

    (resposta,) = await m.diz("stall | to delay on purpose")

    assert "I couldn't reach the AI" in resposta
    assert [e.slug for e in m.repo.listar_entradas()] == ["stall"]
    assert m.repo.obter_sessao().estado == Estado.AWAIT_ACTION


async def test_pedir_outro_sentido_de_palavra_ja_salva_abre_um_novo_cartao() -> None:
    """Regressão: sem frase de contexto o ADR-0023 tratava o pedido como "a palavra de novo" e
    devolvia o aviso de que já existe, com o sentido antigo."""
    m = montar(tutor=FakeTutor(explicacoes=[explicacao_stall(), _stall_no_sentido_s2()]))
    await m.diz("stall")
    await m.diz("0")

    (card,) = await m.diz("stall | to delay on purpose")

    assert card.startswith("*stall*") and "🇧🇷 enrolar" in card
    assert [e.slug for e in m.repo.listar_entradas()] == ["stall", "stall--s2"]


async def test_palavra_diferente_com_contexto_no_meio_da_pratica_salva_e_explica_a_nova() -> None:
    hedge = explicacao_stall().model_copy(update={"palavra": "hedge"})
    m = montar(tutor=FakeTutor(explicacoes=[explicacao_stall(), hedge], expansoes=[expansoes()]))
    await m.diz("stall")

    salvo, card = await m.diz("hedge | to avoid committing")

    assert salvo.startswith("✅ Saved: *stall*")
    assert card.startswith("*hedge*")
    assert "route" not in [c[0] for c in m.tutor.chamadas]


async def test_aviso_de_palavra_que_ja_existe_lista_os_outros_sentidos() -> None:
    sem_frase = explicacao_stall().model_copy(update={"frase_contexto": None})
    m = montar(tutor=FakeTutor(explicacoes=[explicacao_stall(), sem_frase]))
    await m.diz("stall")
    await m.diz("0")

    (resposta,) = await m.diz("stall")

    assert resposta.startswith("📌 You already have *stall* in your list.")
    assert "↔️ enrolar — to delay on purpose" in resposta
    assert "Want another meaning? Tag me with *stall | to delay on purpose*" in resposta
