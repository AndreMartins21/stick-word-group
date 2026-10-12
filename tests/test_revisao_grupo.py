"""M35 (ADR-0033): a revisão diária do grupo. Ninguém é marcado, qualquer um responde e recebe
feedback; a primeira resposta aceitável vale a nota e avança; `skip` pula, `skipall` encerra; sem
mensagem por 3 horas a rodada fecha sozinha. Sem rede, sem credencial, com o relógio controlado."""

from __future__ import annotations

import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest

from app import messages
from app.domain.models import Entry, Estado, Profile, Revisao, SentidoSalvo
from app.services.audio import ServicoAudio
from app.services.fake_llm import FakeTutor
from app.services.fake_tts import FakeSintetizador
from app.services.lembretes import Agendador
from app.services.storage import CacheAudioEmMemoria
from tests.helpers import ANA, BIA, CAIO, GRUPO, T0, Montagem, eventos, montar, sem_jitter

SENTIDO = SentidoSalvo(traducao="travar", definicao="to stop making progress")


def _bom(feedback: str = "Nice!") -> Revisao:
    return Revisao(tipo="definicao", qualidade="bom", feedback=feedback)


def _de_novo() -> Revisao:
    return Revisao(tipo="frase", qualidade="de_novo", feedback="Not quite.", correcao="It stalled.")


def _palavras(n: int) -> list[Entry]:
    return [
        Entry(
            slug=f"w{i}",
            palavra=f"w{i}",
            classe="verb",
            cefr_estimado="B2",
            sentido=SENTIDO,
            criado_em=T0 - timedelta(days=30 - i),
            atualizado_em=T0 - timedelta(days=30 - i),
            proxima_revisao=T0 - timedelta(days=10 - i),
        )
        for i in range(n)
    ]


def _turma(
    *,
    palavras: int = 3,
    revisoes: list[Revisao | Exception] | None = None,
    limite: int = 5,
    audio: ServicoAudio | None = None,
) -> Montagem:
    m = montar(
        tutor=FakeTutor(revisoes=revisoes if revisoes is not None else [_bom() for _ in range(8)]),
        grupo_limite=limite,
        audio=audio,
    )
    repo = m.banco.do_espaco(GRUPO)
    for entrada in _palavras(palavras):
        repo.criar_entrada(entrada)
    return m


def _sessao(m: Montagem):  # type: ignore[no-untyped-def]
    return m.banco.do_espaco(GRUPO).obter_sessao()


def _sem_mencao(m: Montagem) -> bool:
    return all(not mencoes for _, mencoes in m.channel.mencoes_enviadas)


# --- começar ----------------------------------------------------------------------------------


async def test_review_nao_marca_ninguem_e_o_card_convida_todo_mundo() -> None:
    m = _turma()

    (card,) = await m.diz_no_grupo(ANA, "!review")

    assert "Practice time" in card and "1/3" in card
    assert "Anyone can answer" in card and "tag me" in card and "skipall" in card
    assert "@" not in card and _sem_mencao(m)
    assert _sessao(m).estado == Estado.REVIEWING


async def test_revisao_em_grupo_nao_manda_audio_automatico() -> None:
    """M26 (ADR-0027): a pronúncia automática do termo é só no privado."""
    m = _turma(audio=ServicoAudio(FakeSintetizador(), CacheAudioEmMemoria(), "en-US-Neural2-F"))

    await m.diz_no_grupo(ANA, "!review")

    assert m.channel.vozes_enviadas == []


async def test_review_sem_palavras_avisa() -> None:
    m = _turma(palavras=0)

    (resposta,) = await m.diz_no_grupo(ANA, "!review")

    assert resposta == messages.SEM_NADA_PARA_REVISAR


# --- responder --------------------------------------------------------------------------------


async def test_qualquer_aluno_responde_e_a_resposta_aceitavel_vale_a_nota_e_avanca() -> None:
    m = _turma()
    await m.diz_no_grupo(ANA, "!review")

    (avanco,) = await m.diz_no_grupo(BIA, "!it means to stop")

    assert "*Bia* answered" in avanco and "Nice!" in avanco
    assert "2/3" in avanco and "@" not in avanco
    repo = m.banco.do_espaco(GRUPO)
    reagendada = repo.obter_entrada("w0")
    assert reagendada is not None and reagendada.proxima_revisao is not None
    assert reagendada.proxima_revisao > T0
    (resposta,) = repo.listar_respostas()
    assert (resposta.autor_id, resposta.marcado, resposta.qualidade) == (BIA.numero, False, "bom")


async def test_resposta_errada_da_feedback_e_deixa_a_palavra_aberta_para_outro() -> None:
    m = _turma(revisoes=[_de_novo(), _bom()])
    await m.diz_no_grupo(ANA, "!review")
    antes = m.banco.do_espaco(GRUPO).obter_entrada("w0")

    (feedback,) = await m.diz_no_grupo(ANA, "!w0 is a color")

    assert "*Ana* answered" in feedback and "Not quite." in feedback
    assert "still open" in feedback
    sessao = _sessao(m)
    assert sessao.revisao_atual == "w0" and sessao.revisao_feitas == []
    assert m.banco.do_espaco(GRUPO).obter_entrada("w0") == antes  # SM-2 intacto

    (avanco,) = await m.diz_no_grupo(CAIO, "!it means to stop")  # outro acerta: avança

    assert "2/3" in avanco and _sessao(m).revisao_feitas == ["w0"]


async def test_a_frase_do_aluno_fica_salva_com_o_autor() -> None:
    m = _turma(revisoes=[_de_novo()])
    await m.diz_no_grupo(ANA, "!review")

    await m.diz_no_grupo(BIA, "!the w0 stalled")

    (frase,) = m.banco.do_espaco(GRUPO).listar_frases("w0")
    assert frase.autor_id == BIA.numero


async def test_o_ultimo_card_fecha_a_rodada_com_o_resumo() -> None:
    m = _turma(palavras=1)
    await m.diz_no_grupo(ANA, "!review")

    (fim,) = await m.diz_no_grupo(ANA, "!it means to stop")

    assert "Practice done" in fim and "Add a new word whenever you want: tag me with a word." in fim
    assert _sessao(m).estado == Estado.IDLE


# --- skip e skipall ---------------------------------------------------------------------------


@pytest.mark.parametrize("comando", ["!skip", "/skip"])
async def test_skip_pula_a_palavra_sem_mexer_na_nota(comando: str) -> None:
    m = _turma()
    await m.diz_no_grupo(ANA, "!review")
    antes = m.banco.do_espaco(GRUPO).obter_entrada("w0")

    (pulo,) = await m.diz_no_grupo(BIA, comando)

    assert "Skipping *w0*" in pulo and "2/3" in pulo
    assert m.banco.do_espaco(GRUPO).obter_entrada("w0") == antes
    assert _sessao(m).revisao_puladas == ["w0"]
    assert m.tutor is not None and m.tutor.chamadas == []  # sem IA


async def test_skip_na_ultima_palavra_fecha_com_as_puladas_no_resumo() -> None:
    m = _turma(palavras=1)
    await m.diz_no_grupo(ANA, "!review")

    (fim,) = await m.diz_no_grupo(ANA, "!skip")

    assert "⏭️ Skipped: w0" in fim and _sessao(m).estado == Estado.IDLE


@pytest.mark.parametrize("comando", ["!skipall", "!skip-all"])
async def test_skipall_encerra_a_revisao(comando: str) -> None:
    m = _turma()
    await m.diz_no_grupo(ANA, "!review")
    await m.diz_no_grupo(ANA, "!it means to stop")

    (fim,) = await m.diz_no_grupo(BIA, comando)

    assert "Practice done" in fim and _sessao(m).estado == Estado.IDLE


async def test_help_e_stop_escapam_da_resposta() -> None:
    m = _turma()
    await m.diz_no_grupo(ANA, "!review")

    (ajuda,) = await m.diz_no_grupo(ANA, "!help")
    await m.diz_no_grupo(ANA, "!stop")

    assert ajuda.startswith("*How I work in this group*")
    assert _sessao(m).estado == Estado.IDLE


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


async def test_a_rodada_parada_por_3_horas_fecha_sozinha() -> None:
    m = _turma()
    await m.diz_no_grupo(ANA, "!review")
    m.relogio.avancar(timedelta(hours=3, minutes=1))

    await _agendador(m)._tick()

    assert "Nobody replied for a while" in m.channel.textos_enviados[-1][1]
    assert _sessao(m).estado == Estado.IDLE


async def test_toda_mensagem_adia_o_fechamento() -> None:
    m = _turma()
    await m.diz_no_grupo(ANA, "!review")
    m.relogio.avancar(timedelta(hours=2))
    await m.diz_no_grupo(BIA, "!it means to stop")
    m.relogio.avancar(timedelta(hours=2))  # 4h desde o início, mas só 2h desde a última mensagem

    await _agendador(m)._tick()

    assert _sessao(m).estado == Estado.REVIEWING


async def test_o_fechamento_por_inatividade_respeita_o_limite_de_tres_mensagens() -> None:
    m = _turma()
    await m.diz_no_grupo(ANA, "!review")
    m.relogio.avancar(timedelta(hours=3, minutes=1))

    await _agendador(m)._tick()

    assert len(m.channel.textos_enviados) == 2  # card + fechamento


# --- eventos e !group -------------------------------------------------------------------------


async def test_resposta_registra_revisao_resposta_sem_marcado_true(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    m = _turma()
    await m.diz_no_grupo(ANA, "!review")

    await m.diz_no_grupo(BIA, "!it means to stop")

    (evento,) = eventos(caplog.records, "revisao_resposta")
    assert evento.marcado is False


async def test_o_group_conta_as_respostas_de_cada_um() -> None:
    m = _turma()
    await m.diz_no_grupo(ANA, "!review")
    await m.diz_no_grupo(ANA, "!it means to stop")
    await m.diz_no_grupo(BIA, "!it means to stop")
    await m.diz_no_grupo(CAIO, "!stop")

    (resposta,) = await m.diz_no_grupo(CAIO, "!group")

    assert "Ana (student) · 1 review answers" in resposta
    assert "Bia (student) · 1 review answers" in resposta


async def test_perfil_do_grupo_novo_tem_a_diaria_padrao() -> None:
    m = _turma()
    await m.diz_no_grupo(ANA, "!daily")

    perfil = m.banco.do_espaco(GRUPO).obter_perfil()

    assert isinstance(perfil, Profile)
    assert (perfil.diaria_ligada, perfil.diaria_hora, perfil.diaria_fim_de_semana) == (
        True,
        19,
        False,
    )
