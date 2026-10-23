"""M36 (ADR-0034): o desafio semanal do grupo — perguntas da IA com o vocabulário da turma, um aluno
marcado por pergunta (rodízio), feedback para todos, avanço só pelo marcado ou por skip."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import messages
from app.domain.models import (
    AvaliacaoDaPergunta,
    Entry,
    Estado,
    Membro,
    PerguntaSemanal,
    PerguntasSemanais,
    Profile,
    SentidoSalvo,
    Sessao,
)
from app.domain.state import Acao, transicionar
from app.flows.base import Autor
from app.flows.semanal import escolher_vocabulario
from app.services.audio import ServicoAudio
from app.services.fake_llm import FakeLLMProvider, FakeTutor
from app.services.fake_tts import FakeSintetizador
from app.services.lembretes import Agendador
from app.services.llm import LLMError, LLMTutor
from app.services.storage import CacheAudioEmMemoria
from tests.helpers import ANA, BIA, CAIO, DONO_NUMERO, GRUPO, T0, Montagem, montar, sem_jitter

BOT = "5531988887777"
CARLA = Autor("5541900000001", "Carla")  # professora
DONO = Autor(DONO_NUMERO, "Dono")
SENTIDO = SentidoSalvo(traducao="travar", definicao="to stop making progress")
ALUNOS = (ANA, BIA, CAIO)
NUMEROS = [a.numero for a in ALUNOS]


def _pergunta(i: int = 0, *, pt: str = "") -> PerguntaSemanal:
    return PerguntaSemanal(
        pergunta=f"What would you do if a project stopped, like [[w{i}]]?",
        palavras=[f"w{i}"],
        explicacao_en=f"It asks about a stalled project. w{i} = to stop.",
        explicacao_pt=pt,
    )


def _ok(texto: str = "Good answer!") -> AvaliacaoDaPergunta:
    return AvaliacaoDaPergunta(qualidade="bom", feedback=texto)


def _palavras(n: int) -> list[Entry]:
    return [
        Entry(
            slug=f"w{i}",
            palavra=f"w{i}",
            classe="verb",
            cefr_estimado="B2",
            sentido=SENTIDO,
            criado_em=T0 - timedelta(days=2),
            atualizado_em=T0 - timedelta(days=2),
        )
        for i in range(n)
    ]


def _turma(
    *,
    nivel: str = "B1-B2",
    perguntas: int = 3,
    pt: str = "",
    avaliacoes: int = 8,
    audio: ServicoAudio | None = None,
    admins: tuple[str, ...] = (),
    alunos: tuple[Autor, ...] = ALUNOS,
) -> Montagem:
    m = montar(
        tutor=FakeTutor(
            perguntas_semanais=[[_pergunta(i, pt=pt) for i in range(perguntas)]],
            avaliacoes_da_pergunta=[_ok() for _ in range(avaliacoes)],
        ),
        numero_do_bot=BOT,
        sortear=lambda itens: itens[0],
        audio=audio,
        admins=admins,
    )
    m.channel.participantes_de_grupos[GRUPO] = [*(a.numero for a in alunos), CARLA.numero, BOT]
    repo = m.banco.do_espaco(GRUPO)
    for i, aluno in enumerate(alunos):
        repo.salvar_membro(
            aluno.numero, Membro(nome=aluno.nome, entrou_em=T0 + timedelta(minutes=i))
        )
    repo.salvar_membro(CARLA.numero, Membro(papel="professor", nome=CARLA.nome, entrou_em=T0))
    repo.salvar_membro(DONO.numero, Membro(papel="professor", nome=DONO.nome, entrou_em=T0))
    for entrada in _palavras(4):
        repo.criar_entrada(entrada)
    repo.salvar_perfil(Profile(nivel=nivel, chat_id=GRUPO, proxima_diaria=T0 + timedelta(days=9)))
    return m


def _sessao(m: Montagem) -> Sessao:
    return m.banco.do_espaco(GRUPO).obter_sessao()


def _marcado(m: Montagem) -> str:
    marcado = _sessao(m).marcado_id
    assert marcado is not None
    return marcado


def _autor(m: Montagem, numero: str) -> Autor:
    return next(a for a in ALUNOS if a.numero == numero)


async def _comecar(m: Montagem) -> list[str]:
    return await m.diz_no_grupo(DONO, "!weekly now")


# --- começar ----------------------------------------------------------------------------------


async def test_weekly_now_so_admin_do_bot_e_o_dono() -> None:
    m = _turma(admins=(BIA.numero,))

    assert await m.diz_no_grupo(ANA, "!weekly now") == [messages.so_admin_configura("!", "weekly")]
    assert _sessao(m).estado == Estado.IDLE
    abertura, pergunta = await m.diz_no_grupo(BIA, "!weekly now")

    assert "Weekly challenge" in abertura and "3 questions" in abertura
    assert _sessao(m).estado == Estado.WEEKLY_QUIZ
    assert pergunta.startswith("@")


async def test_a_pergunta_comeca_com_a_mencao_e_traz_o_menu() -> None:
    m = _turma()

    _, pergunta = await _comecar(m)

    marcado = _marcado(m)
    assert marcado in NUMEROS
    assert pergunta.startswith(f"@{marcado} What would you do if a project stopped, like *w0*?")
    assert "/1 Explain the question" in pergunta
    assert "/2 Listen to the question" in pergunta
    assert "/3 Skip this question" in pergunta
    assert "1/3" in pergunta
    assert m.channel.mencoes_enviadas[-1][1] == (marcado,)
    assert "[[" not in pergunta


async def test_uma_pergunta_por_aluno_por_padrao_e_professor_e_bot_nunca_sao_marcados() -> None:
    m = _turma()

    await _comecar(m)

    assert m.tutor is not None
    assert m.tutor.chamadas[0][0] == "weekly_questions"
    assert m.tutor.chamadas[0][1][2] == 3  # 3 alunos elegíveis
    marcados = [_marcado(m)]
    for _ in range(2):
        await m.diz_no_grupo(_autor(m, marcados[-1]), "!my answer")
        marcados.append(_marcado(m)) if _sessao(m).estado == Estado.WEEKLY_QUIZ else None
    assert sorted(marcados) == sorted(NUMEROS)  # cada um uma vez
    assert CARLA.numero not in marcados and BOT not in marcados


async def test_weekly_size_fixa_a_quantidade() -> None:
    m = _turma(perguntas=2)
    await m.diz_no_grupo(DONO, "!weekly size 2")

    await _comecar(m)

    assert m.tutor is not None and m.tutor.chamadas[0][1][2] == 2


async def test_sem_palavras_ou_sem_aluno_o_weekly_now_explica() -> None:
    m = _turma(alunos=())
    (sem_aluno,) = await _comecar(m)
    assert sem_aluno == messages.grupo_sem_aluno("!")

    vazia = montar(tutor=FakeTutor())
    (sem_palavras,) = await vazia.diz_no_grupo(DONO, "!weekly now")
    assert sem_palavras == messages.semanal_sem_palavras()


async def test_weekly_now_com_atividade_em_andamento_recusa() -> None:
    m = _turma()
    await _comecar(m)

    (aviso,) = await m.diz_no_grupo(DONO, "!weekly now")  # em WEEKLY_QUIZ vira resposta
    assert _sessao(m).estado == Estado.WEEKLY_QUIZ and aviso  # (não abre outro desafio)
    assert m.tutor is not None
    assert [c[0] for c in m.tutor.chamadas].count("weekly_questions") == 1


# --- responder --------------------------------------------------------------------------------


async def test_o_marcado_responde_recebe_feedback_e_o_proximo_aluno_e_marcado() -> None:
    m = _turma()
    await _comecar(m)
    primeiro = _marcado(m)

    feedback, pergunta = await m.diz_no_grupo(_autor(m, primeiro), "!I would call the client")

    assert "Good answer!" in feedback
    assert pergunta.startswith("@") and "2/3" in pergunta
    segundo = _marcado(m)
    assert segundo != primeiro
    assert m.banco.do_espaco(GRUPO).listar_respostas()[0].marcado is True
    assert _sessao(m).semanal_respondidas == 1


async def test_responder_marcando_o_bot_e_sem_comando() -> None:
    m = _turma()
    await _comecar(m)
    primeiro = _marcado(m)

    feedback, pergunta = await m.marca_no_grupo(
        _autor(m, primeiro), "I would call the client and ask for more time"
    )

    assert "Good answer!" in feedback and "2/3" in pergunta
    assert _marcado(m) != primeiro
    assert m.tutor is not None
    chamada = next(c for c in m.tutor.chamadas if c[0] == "weekly_answer")
    assert chamada[1][2] == "I would call the client and ask for more time"


async def test_marcando_o_bot_o_menu_funciona_com_o_numero_e_com_skip() -> None:
    m = _turma()
    await _comecar(m)
    primeiro = _marcado(m)

    (explicacao,) = await m.marca_no_grupo(ANA, "1")
    assert explicacao and _sessao(m).semanal_indice == 0
    (pergunta,) = await m.marca_no_grupo(BIA, "skip")

    assert "2/3" in pergunta and _marcado(m) != primeiro
    assert _sessao(m).semanal_puladas == 1


async def test_conversa_comum_durante_o_desafio_nao_e_resposta() -> None:
    m = _turma()
    await _comecar(m)

    assert await m.diz_no_grupo(ANA, "kkkk boa pergunta") == []  # sem marcar nem prefixo
    assert m.tutor is not None
    assert "weekly_answer" not in [c[0] for c in m.tutor.chamadas]


async def test_quem_nao_foi_marcado_recebe_feedback_mas_a_pergunta_nao_avanca() -> None:
    m = _turma()
    await _comecar(m)
    marcado = _marcado(m)
    outro = next(a for a in ALUNOS if a.numero != marcado)

    (feedback,) = await m.diz_no_grupo(outro, "!I would wait")

    assert "Good answer!" in feedback and f"waiting for @{marcado}" in feedback
    assert _marcado(m) == marcado and _sessao(m).semanal_indice == 0
    (resposta,) = m.banco.do_espaco(GRUPO).listar_respostas()
    assert resposta.marcado is False


async def test_a_professora_tambem_pode_tentar_sem_avancar() -> None:
    m = _turma()
    await _comecar(m)

    (feedback,) = await m.diz_no_grupo(CARLA, "!I would wait")

    assert "still waiting" in feedback and _sessao(m).semanal_indice == 0


async def test_a_ultima_resposta_fecha_com_o_resumo() -> None:
    m = _turma(perguntas=1)
    await _comecar(m)

    feedback, resumo = await m.diz_no_grupo(_autor(m, _marcado(m)), "!my answer")

    assert "Good answer!" in feedback
    assert "Weekly challenge done" in resumo and "1 of 1 answered" in resumo
    assert _sessao(m).estado == Estado.IDLE


# --- menu 1, 2, 3 -----------------------------------------------------------------------------


@pytest.mark.parametrize("nivel", ["A1-A2", "A2-B1"])
async def test_explicar_em_turma_iniciante_traz_portugues_e_depois_ingles(nivel: str) -> None:
    m = _turma(nivel=nivel, pt="Pergunta sobre um projeto parado.")
    await _comecar(m)

    (explicacao,) = await m.diz_no_grupo(ANA, "!1")

    pt, en = explicacao.split("\n")
    assert pt.startswith("🇧🇷 Pergunta sobre") and en.startswith("🇺🇸 It asks about")


@pytest.mark.parametrize("nivel", ["B1-B2", "B2-C1", "C1-C2", "C2"])
async def test_explicar_de_b1_em_diante_e_so_ingles(nivel: str) -> None:
    m = _turma(nivel=nivel)
    await _comecar(m)

    (explicacao,) = await m.diz_no_grupo(ANA, "/1" if False else "!1")

    assert explicacao.startswith("💡 It asks about") and "🇧🇷" not in explicacao
    assert _sessao(m).semanal_indice == 0  # explicar não avança


async def test_ouvir_manda_a_pergunta_em_voz_sem_os_colchetes() -> None:
    audio = ServicoAudio(FakeSintetizador(), CacheAudioEmMemoria(), "en-US-Neural2-F")
    m = _turma(audio=audio)
    await _comecar(m)

    respostas = await m.diz_no_grupo(ANA, "!2")

    assert respostas == []  # só a voz
    assert len(m.channel.vozes_enviadas) == 1
    assert _sessao(m).semanal_indice == 0


async def test_ouvir_sem_servico_de_audio_avisa() -> None:
    m = _turma()
    await _comecar(m)

    assert await m.diz_no_grupo(ANA, "!2") == [messages.ERRO_AUDIO]


@pytest.mark.parametrize("comando", ["!3", "!skip", "/3", "/skip"])
async def test_pular_passa_para_a_proxima_pergunta_e_outro_aluno(comando: str) -> None:
    m = _turma()
    await _comecar(m)
    primeiro = _marcado(m)

    (pergunta,) = await m.diz_no_grupo(BIA, comando)

    assert "2/3" in pergunta and _marcado(m) != primeiro
    assert _sessao(m).semanal_puladas == 1
    assert m.tutor is not None
    assert "weekly_answer" not in [c[0] for c in m.tutor.chamadas]  # sem IA


@pytest.mark.parametrize("comando", ["!skipall", "!skip-all", "!0", "!stop"])
async def test_skipall_encerra_o_desafio(comando: str) -> None:
    m = _turma()
    await _comecar(m)

    (fim,) = await m.diz_no_grupo(ANA, comando)

    assert "Weekly challenge done" in fim and _sessao(m).estado == Estado.IDLE


async def test_help_escapa_da_resposta() -> None:
    m = _turma()
    await _comecar(m)

    (ajuda,) = await m.diz_no_grupo(ANA, "!help")

    assert ajuda.startswith("*How I work in this group*") and "!weekly" in ajuda
    assert _sessao(m).estado == Estado.WEEKLY_QUIZ


# --- 3 horas parado ---------------------------------------------------------------------------


def _agendador(m: Montagem) -> Agendador:
    async def dormir(_: float) -> None:
        return None

    return Agendador(
        router=m.router,
        banco=m.banco,
        agora=m.relogio.agora,
        fuso=ZoneInfo("America/Sao_Paulo"),
        dormir=dormir,
        jitter_do_grupo=sem_jitter,
    )


async def test_3_horas_sem_mensagem_fecha_o_desafio() -> None:
    m = _turma()
    await _comecar(m)
    m.relogio.avancar(timedelta(hours=3, minutes=1))

    await _agendador(m)._tick()

    assert "closed the challenge" in m.channel.textos_enviados[-1][1]
    assert _sessao(m).estado == Estado.IDLE


async def test_mensagem_adia_o_fechamento() -> None:
    m = _turma()
    await _comecar(m)
    m.relogio.avancar(timedelta(hours=2))
    await m.diz_no_grupo(CARLA, "!I would wait")
    m.relogio.avancar(timedelta(hours=2))

    await _agendador(m)._tick()

    assert _sessao(m).estado == Estado.WEEKLY_QUIZ


# --- agenda -----------------------------------------------------------------------------------

SP = ZoneInfo("America/Sao_Paulo")


def _local(mes: int, dia: int, hora: int, minuto: int = 0) -> datetime:
    return datetime(2026, mes, dia, hora, minuto, tzinfo=SP)  # 25/09/2026 é sexta-feira


def _agendar(m: Montagem, agora: datetime, **perfil: object) -> None:
    m.relogio.agora_ = agora.astimezone(UTC)
    repo = m.banco.do_espaco(GRUPO)
    atual = repo.obter_perfil()
    assert atual is not None
    repo.salvar_perfil(atual.model_copy(update=perfil))


async def test_a_sexta_as_13h_o_agendador_inicia_o_desafio_e_agenda_a_proxima_sexta() -> None:
    m = _turma()
    _agendar(
        m,
        _local(9, 25, 13, 1),
        proxima_semanal=_local(9, 25, 13).astimezone(UTC),
        proxima_diaria=_local(9, 25, 19).astimezone(UTC),
    )

    await _agendador(m)._tick()

    assert "Weekly challenge" in m.channel.textos_enviados[0][1]
    assert _sessao(m).estado == Estado.WEEKLY_QUIZ
    perfil = m.banco.do_espaco(GRUPO).obter_perfil()
    assert perfil is not None
    assert perfil.proxima_semanal == _local(10, 2, 13).astimezone(UTC)
    assert perfil.revisoes_sem_resposta == 1


async def test_outro_dia_nao_dispara_e_o_primeiro_tick_calcula_a_sexta() -> None:
    m = _turma()
    _agendar(m, _local(9, 23, 13, 1), proxima_diaria=_local(9, 23, 19).astimezone(UTC))

    await _agendador(m)._tick()

    assert m.channel.textos_enviados == []
    perfil = m.banco.do_espaco(GRUPO).obter_perfil()
    assert perfil is not None and perfil.proxima_semanal == _local(9, 25, 13).astimezone(UTC)


async def test_weekly_off_nao_dispara() -> None:
    m = _turma()
    _agendar(
        m,
        _local(9, 25, 13, 1),
        proxima_semanal=_local(9, 25, 13).astimezone(UTC),
        proxima_diaria=_local(9, 25, 19).astimezone(UTC),
        semanal_ligada=False,
    )

    await _agendador(m)._tick()

    assert m.channel.textos_enviados == []


async def test_weekly_configura_dia_hora_e_tamanho_so_para_admin() -> None:
    m = _turma()

    (recusa,) = await m.diz_no_grupo(ANA, "!weekly mon 9h")
    (ok,) = await m.diz_no_grupo(DONO, "!weekly monday 9:30 size 2")
    (ver,) = await m.diz_no_grupo(ANA, "!weekly")
    (invalida,) = await m.diz_no_grupo(DONO, "!weekly banana")

    assert recusa == messages.so_admin_configura("!", "weekly")
    assert "every Monday around 09:30" in ok and "2 questions" in ok
    assert "every Monday around 09:30" in ver and "Next one:" in ver
    assert invalida == messages.semanal_invalida("!")
    perfil = m.banco.do_espaco(GRUPO).obter_perfil()
    assert perfil is not None
    assert (perfil.semanal_dia, perfil.semanal_hora, perfil.semanal_tamanho) == (0, 9, 2)


async def test_o_group_mostra_o_proximo_desafio() -> None:
    m = _turma()

    (resposta,) = await m.diz_no_grupo(ANA, "!group")

    assert "Weekly challenge:" in resposta


# --- puro: vocabulário e máquina de estados ---------------------------------------------------


def test_vocabulario_prefere_o_recente_e_completa_com_o_que_vence_antes() -> None:
    antigas = [
        e.model_copy(
            update={"criado_em": T0 - timedelta(days=30 + i), "slug": f"o{i}", "palavra": f"o{i}"}
        )
        for i, e in enumerate(_palavras(3))
    ]
    novas = [
        e.model_copy(
            update={"criado_em": T0 - timedelta(days=i), "slug": f"n{i}", "palavra": f"n{i}"}
        )
        for i, e in enumerate(_palavras(2))
    ]

    vocabulario = escolher_vocabulario([*antigas, *novas], T0, limite=4)

    assert [p for p, _ in vocabulario] == ["n0", "n1", "o2", "o1"]


@pytest.mark.parametrize(
    ("texto", "acao"),
    [
        ("1", Acao.EXPLICAR_PERGUNTA),
        ("2", Acao.OUVIR_PERGUNTA),
        ("3", Acao.PULAR_PERGUNTA),
        ("skip", Acao.PULAR_PERGUNTA),
        ("skip all", Acao.ENCERRAR_SEMANAL),
        ("skipall", Acao.ENCERRAR_SEMANAL),
        ("0", Acao.ENCERRAR_SEMANAL),
        ("I would call them", Acao.RESPONDER_PERGUNTA),
    ],
)
def test_transicoes_do_desafio(texto: str, acao: Acao) -> None:
    assert transicionar(Estado.WEEKLY_QUIZ, texto).acao == acao


# --- contratos de IA --------------------------------------------------------------------------

VOCAB = [("stall", "to stop making progress"), ("deadline", "a date to finish by")]


def _tutor(*respostas: object) -> tuple[LLMTutor, FakeLLMProvider]:
    provider = FakeLLMProvider(list(respostas))  # type: ignore[arg-type]
    return LLMTutor(provider, modelo="rapido", modelo_avaliacao="forte"), provider


def _pergunta_ia(palavra: str = "stall", pt: str = "") -> PerguntaSemanal:
    return PerguntaSemanal(
        pergunta=f"Have you ever missed a [[{palavra}]]?",
        palavras=[palavra],
        explicacao_en="It asks about a past situation.",
        explicacao_pt=pt,
    )


def test_pergunta_exige_palavra_marcada_e_explicacao() -> None:
    with pytest.raises(ValueError):
        PerguntaSemanal(pergunta="No marks here", palavras=["x"], explicacao_en="x")
    with pytest.raises(ValueError):
        PerguntaSemanal(pergunta="A [[x]]", palavras=["x"], explicacao_en="  ")
    with pytest.raises(ValueError):
        PerguntasSemanais(itens=[])


def test_weekly_questions_valida_quantidade_e_vocabulario_e_tenta_de_novo() -> None:
    boa = PerguntasSemanais(itens=[_pergunta_ia("stall"), _pergunta_ia("deadline")])
    fora = PerguntasSemanais(itens=[_pergunta_ia("banana"), _pergunta_ia("deadline")])
    pouca = PerguntasSemanais(itens=[_pergunta_ia("stall")])

    tutor, provider = _tutor(pouca, boa)  # quantidade errada: nova tentativa
    assert [p.palavras for p in tutor.weekly_questions(VOCAB, "B2-C1", 2)] == [
        ["stall"],
        ["deadline"],
    ]
    assert len(provider.chamadas) == 2
    assert "rejeitada" in provider.chamadas[1].usuario

    tutor2, _ = _tutor(fora, boa)  # palavra fora do vocabulário: nova tentativa
    assert len(tutor2.weekly_questions(VOCAB, "B2-C1", 2)) == 2


def test_weekly_questions_turma_iniciante_exige_portugues_e_avancada_o_apaga() -> None:
    sem_pt = PerguntasSemanais(itens=[_pergunta_ia("stall")])
    com_pt = PerguntasSemanais(itens=[_pergunta_ia("stall", pt="Já perdeu um prazo?")])
    tutor, _ = _tutor(sem_pt, com_pt)
    (iniciante,) = tutor.weekly_questions(VOCAB, "A2-B1", 1)
    assert iniciante.explicacao_pt == "Já perdeu um prazo?"

    tutor2, _ = _tutor(com_pt)
    (avancada,) = tutor2.weekly_questions(VOCAB, "C1-C2", 1)
    assert avancada.explicacao_pt == ""  # esta turma não vê português


def test_weekly_questions_que_nunca_valida_vira_llm_error() -> None:
    pouca = PerguntasSemanais(itens=[_pergunta_ia("stall")])
    tutor, _ = _tutor(pouca, pouca)

    with pytest.raises(LLMError):
        tutor.weekly_questions(VOCAB, "B1-B2", 2)


def test_prompt_das_perguntas_cita_o_nivel_o_vocabulario_e_a_regra_do_portugues() -> None:
    tutor, provider = _tutor(PerguntasSemanais(itens=[_pergunta_ia("stall", pt="Oi?")]))
    tutor.weekly_questions(VOCAB, "A1-A2", 1)
    sistema = provider.chamadas[0].sistema
    assert "stall: to stop making progress" in sistema and "muito simples" in sistema
    assert re.search(r"explicacao_pt.*português do Brasil", sistema)

    tutor2, provider2 = _tutor(PerguntasSemanais(itens=[_pergunta_ia("stall")]))
    tutor2.weekly_questions(VOCAB, "C2", 1)
    assert "deixe SEMPRE vazio" in provider2.chamadas[0].sistema


def test_weekly_answer_usa_o_modelo_de_avaliacao() -> None:
    tutor, provider = _tutor(_ok("Nice!"))

    resultado = tutor.weekly_answer("Have you missed a deadline?", ["deadline"], "Yes.", "B1-B2")

    assert resultado.feedback == "Nice!"
    assert provider.chamadas[0].modelo == "forte"


def test_a_avaliacao_pede_coerencia_com_a_pergunta_e_nao_cobra_as_palavras() -> None:
    from app.services.prompts import prompt_weekly_answer

    prompt = prompt_weekly_answer(
        "B1-B2", "What would you do if a project *stalled*?", ["stall"], "x"
    )

    assert "NÃO precisa usá-las" in prompt.sistema
    assert "coerente com a pergunta no geral" in prompt.sistema
    assert "nunca baixe a nota por não usá-las" in prompt.sistema
    assert "ignora o vocabulário" not in prompt.sistema  # o critério antigo caiu


async def test_resposta_do_semanal_registra_o_tipo_para_o_ranking() -> None:
    m = _turma()
    await _comecar(m)

    await m.marca_no_grupo(_autor(m, _marcado(m)), "I would ask for help")

    (resposta, *_) = m.banco.do_espaco(GRUPO).listar_respostas()
    assert resposta.tipo == "semanal"
