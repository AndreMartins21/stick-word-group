"""Testes do fluxo de revisão espaçada (M10, seção 5.7): `montar_fila` (pura) e o ciclo via
`/revisar` com o `Router` + `FakeTutor`."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.domain.models import Entry, Revisao, SentidoSalvo
from app.flows.review import montar_fila
from app.services.audio import ServicoAudio
from app.services.fake_llm import FakeTutor
from app.services.fake_tts import FakeSintetizador
from app.services.storage import CacheAudioEmMemoria
from tests.helpers import T0, Montagem
from tests.helpers import montar as _montar


def montar(**kwargs: Any) -> Montagem:
    """Uma turma A2-B1, que vê a linha 🇧🇷 (ADR-0032)."""
    return _montar(**{"nivel_padrao": "A2-B1", **kwargs})


SENTIDO = SentidoSalvo(traducao="travar", definicao="to stop making progress")


def _entrada(slug: str, *, criado_em: datetime = T0, **campos: object) -> Entry:
    base = {
        "slug": slug,
        "palavra": slug,
        "classe": "verb",
        "cefr_estimado": "B2",
        "sentido": SENTIDO,
        "criado_em": criado_em,
        "atualizado_em": criado_em,
    }
    return Entry.model_validate(base | campos)


# ---- montar_fila (pura) -----------------------------------------------------------------------


def test_montar_fila_vazia_sem_entradas() -> None:
    assert montar_fila([], T0) == []


def test_montar_fila_vencidas_primeiro_mais_antiga_primeiro() -> None:
    recente = _entrada(
        "b", criado_em=T0 + timedelta(minutes=5), proxima_revisao=T0 - timedelta(days=1)
    )
    antiga = _entrada("a", criado_em=T0, proxima_revisao=T0 - timedelta(days=5))
    nunca_revisada = _entrada("c", criado_em=T0 + timedelta(minutes=1))  # proxima_revisao=None

    fila = montar_fila([recente, antiga, nunca_revisada], T0)

    # Ordenado pela data de vencimento: "a" venceu há mais tempo, "c" nunca foi revisada
    # (criado_em vira o critério) mas seu criado_em é mais recente que a data de vencimento de "b".
    assert fila == ["a", "b", "c"]


def test_montar_fila_completa_ate_o_limite_com_as_que_vencem_mais_cedo() -> None:
    vencida = _entrada("v", proxima_revisao=T0 - timedelta(days=1))
    cedo = _entrada("cedo", criado_em=T0, proxima_revisao=T0 + timedelta(days=1))
    tarde = _entrada("tarde", criado_em=T0, proxima_revisao=T0 + timedelta(days=10))

    fila = montar_fila([tarde, cedo, vencida], T0, limite=2)

    assert fila == ["v", "cedo"]


def test_montar_fila_so_as_vencidas_quando_ja_bate_o_limite() -> None:
    entradas = [_entrada(f"e{i}", proxima_revisao=T0 - timedelta(days=i)) for i in range(3)]

    fila = montar_fila(entradas, T0, limite=2)

    assert len(fila) == 2


# ---- ciclo via /revisar -----------------------------------------------------------------------


async def _com_stall_e_hedge_vencidas() -> Montagem:
    m = montar(tutor=FakeTutor())
    m.repo.criar_entrada(_entrada("stall", criado_em=T0))
    m.repo.criar_entrada(_entrada("hedge", criado_em=T0 + timedelta(minutes=1)))
    return m


async def test_frase_da_revisao_guarda_a_versao_corrigida() -> None:
    m = await _com_stall_e_hedge_vencidas()
    await m.diz("/review")
    m.tutor.revisoes.append(
        Revisao(
            tipo="frase",
            qualidade="bom",
            feedback="Nice!",
            correcao="The talks [[stalled]] for weeks.",
        )
    )

    await m.diz("the talks stalled for weeks")

    (frase,) = m.repo.listar_frases("stall")
    assert frase.autor == "usuario"
    assert frase.versao_natural == "The talks [[stalled]] for weeks."


# ---- tamanho da fila (M24, seção 5.7) -----------------------------------------------------------


async def _com_dez_palavras_vencidas() -> Montagem:
    m = montar(tutor=FakeTutor())
    for i in range(10):
        m.repo.criar_entrada(_entrada(f"palavra{i}", criado_em=T0 + timedelta(minutes=i)))
    return m


# ---- pronúncia automática no privado (M26, ADR-0027) --------------------------------------------

VOZ = "en-US-Neural2-F"


async def _com_stall_e_hedge_vencidas_e_audio() -> Montagem:
    sintetizador = FakeSintetizador()
    m = montar(tutor=FakeTutor(), audio=ServicoAudio(sintetizador, CacheAudioEmMemoria(), VOZ))
    m.repo.criar_entrada(_entrada("stall", criado_em=T0))
    m.repo.criar_entrada(_entrada("hedge", criado_em=T0 + timedelta(minutes=1)))
    return m


async def test_o_audio_da_revisao_fica_em_silencio_sem_servico_configurado() -> None:
    m = await _com_stall_e_hedge_vencidas()

    (primeira,) = await m.diz("/revisar")

    assert "🔊" not in primeira
    assert m.channel.vozes_enviadas == []


# --- eventos estruturados (M27, ADR-0028, seção 12 da spec) -------------------------------------
