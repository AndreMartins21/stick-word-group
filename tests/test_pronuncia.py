"""Pronúncia em áudio (M23/M25, ADR-0024/ADR-0026): duas notas de voz — o termo e a frase de
exemplo —, automáticas desde o M25 (logo depois de explicar a palavra) e sob demanda no /listen,
com o áudio vindo do cache depois da 1ª vez."""

from __future__ import annotations

from typing import Any

from app.domain.models import Estado
from app.services.audio import ServicoAudio
from app.services.fake_llm import FakeTutor
from app.services.fake_tts import FakeSintetizador
from app.services.storage import CacheAudioEmMemoria
from tests.helpers import CHAT, GRUPO, Montagem, expansoes, explicacao_stall
from tests.helpers import montar as _montar


def montar(**kwargs: Any) -> Montagem:
    """Uma turma A2-B1, que vê a linha 🇧🇷 (ADR-0032)."""
    return _montar(**{"nivel_padrao": "A2-B1", **kwargs})


VOZ = "en-US-Neural2-F"
ERRO = "🔊 I couldn't make the audio right now. Try again in a bit?"


def _com_audio(
    *, sintetizador: FakeSintetizador | None = None
) -> tuple[Montagem, FakeSintetizador, CacheAudioEmMemoria]:
    sintetizador = sintetizador or FakeSintetizador()
    cache = CacheAudioEmMemoria()
    m = montar(
        tutor=FakeTutor(explicacoes=[explicacao_stall()], expansoes=[expansoes()]),
        audio=ServicoAudio(sintetizador, cache, VOZ),
    )
    return m, sintetizador, cache


# ---- automático, ao explicar a palavra (M25) -------------------------------------------------


async def test_a_palavra_nova_manda_o_termo_e_a_frase_de_exemplo_automaticamente() -> None:
    m, sintetizador, _ = _com_audio()

    (card,) = await m.diz("stall | the talks stalled")

    assert "*stall*" in card
    assert m.channel.vozes_enviadas == [(CHAT, b"ogg:stall"), (CHAT, b"ogg:The talks stalled.")]
    assert sintetizador.chamadas == [("stall", VOZ), ("The talks stalled.", VOZ)]


async def test_o_menu_nao_tem_mais_opcao_de_ouvir() -> None:
    m, _, _ = _com_audio()

    (card,) = await m.diz("stall | the talks stalled")

    assert "1️⃣" not in card and "Hear" not in card
    assert "2️⃣ See more examples" in card and "5️⃣ Don't save" in card


async def test_a_ordem_e_o_texto_antes_das_duas_vozes() -> None:
    m, _, _ = _com_audio()

    await m.diz("stall | the talks stalled")

    # 3 mensagens: cabe no limite de 3 seguidas sem resposta (seção 5.6)
    assert m.channel.ordem == ["texto", "voz", "voz"]


async def test_a_conversa_continua_na_mesma_palavra_depois_do_audio_automatico() -> None:
    m, _, _ = _com_audio()

    await m.diz("stall | the talks stalled")

    sessao = m.repo.obter_sessao()
    assert sessao.estado == Estado.AWAIT_ACTION and sessao.entry_id == "stall"
    (fim,) = await m.diz("4")
    assert fim.startswith("✅")  # "Just save" segue funcionando


async def test_o_link_dos_audios_fica_na_entrada() -> None:
    m, _, cache = _com_audio()

    await m.diz("stall | the talks stalled")

    entrada = m.repo.obter_entrada("stall")
    assert entrada is not None
    assert entrada.audio_palavra in {f"memoria://{n}" for n in cache.arquivos}
    assert entrada.audio_exemplo in {f"memoria://{n}" for n in cache.arquivos}
    assert entrada.audio_palavra != entrada.audio_exemplo


async def test_falha_do_tts_avisa_sem_derrubar_a_conversa() -> None:
    m, _, _ = _com_audio(sintetizador=FakeSintetizador(falha=True))

    textos = await m.diz("stall | the talks stalled")

    assert textos[-1] == ERRO
    assert m.channel.vozes_enviadas == []
    assert m.repo.obter_sessao().estado == Estado.AWAIT_ACTION


async def test_falha_ao_enviar_a_voz_avisa_sem_derrubar_a_conversa() -> None:
    m, _, _ = _com_audio()
    m.channel.falha_na_voz = True

    textos = await m.diz("stall | the talks stalled")

    assert textos[-1] == ERRO
    assert m.repo.obter_sessao().estado == Estado.AWAIT_ACTION


async def test_sem_servico_de_audio_fica_em_silencio() -> None:
    """M25: automático não avisa se o áudio não está configurado neste ambiente — ninguém pediu
    áudio explicitamente, e a explicação já dita basta (diferente do /listen, que avisa)."""
    m = montar(tutor=FakeTutor(explicacoes=[explicacao_stall()], expansoes=[expansoes()]))

    (resposta,) = await m.diz("stall | the talks stalled")

    assert ERRO not in resposta
    assert m.channel.vozes_enviadas == []


async def test_no_grupo_o_audio_tambem_e_automatico() -> None:
    from tests.helpers import ANA

    m, _, _ = _com_audio()

    (card,) = await m.diz_no_grupo(ANA, "!add stall | the talks stalled")

    assert "1️⃣" not in card and "2️⃣ See more examples" in card
    assert [c for c, _ in m.channel.vozes_enviadas] == [GRUPO, GRUPO]


# ---- /listen: sob demanda, como sempre ---------------------------------------------------------


async def test_listen_aceita_o_numero_da_lista() -> None:
    m, _, _ = _com_audio()
    await m.diz("stall | the talks stalled")
    await m.diz("4")

    await m.diz("/listen 1")

    assert m.channel.vozes_enviadas[-2] == (CHAT, b"ogg:stall")
