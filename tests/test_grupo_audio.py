"""M39 (ADR-0037): em grupo o bot entende uma nota de voz, só quando ela cita uma mensagem do bot.
O áudio é transcrito, mostrado como a primeira mensagem e segue como uma mensagem marcada comum."""

from __future__ import annotations

from typing import Any

from app import messages
from app.channel.parser import MessagePayload
from app.services.transcricao import MAX_BYTES_DO_AUDIO
from tests.webhook_helpers import GRUPO_FIXO, Ambiente, _do_grupo

ANA = "5531999998888"
BOT = "5531988887777"
LID_DO_BOT = "119302179033090@lid"
URL = "http://localhost:3000/api/files/voz.oga"


def _citando(texto: str, autor_citado: str | None, *, como: str = "replyTo") -> dict[str, Any]:
    corpo = _do_grupo(GRUPO_FIXO, f"{ANA}@c.us", texto)
    if autor_citado is None:
        return corpo
    if como == "replyTo":
        corpo["payload"]["replyTo"] = {"id": "false_x", "participant": autor_citado, "body": "hi"}
    else:  # o GOWS: contextInfo da mensagem
        corpo["payload"]["_data"] = {
            "Message": {
                "extendedTextMessage": {
                    "text": texto,
                    "contextInfo": {"stanzaID": "ABC", "participant": autor_citado},
                }
            }
        }
    return corpo


def _audio(autor_citado: str | None, *, mimetype: str = "audio/ogg; codecs=opus") -> dict[str, Any]:
    corpo = _citando("", autor_citado)
    corpo["payload"]["hasMedia"] = True
    corpo["payload"]["media"] = {"url": URL, "mimetype": mimetype, "filename": None, "error": None}
    return corpo


# --- parser -----------------------------------------------------------------------------------


def test_parser_reconhece_audio_pelo_mimetype_ou_pelo_audio_message() -> None:
    base = {"id": "1", "from": GRUPO_FIXO, "hasMedia": True}

    assert MessagePayload.model_validate(
        {**base, "media": {"mimetype": "audio/ogg; codecs=opus"}}
    ).eh_audio()
    assert MessagePayload.model_validate(
        {**base, "_data": {"Message": {"audioMessage": {}}}}
    ).eh_audio()
    assert not MessagePayload.model_validate(
        {**base, "media": {"mimetype": "image/jpeg"}}
    ).eh_audio()
    assert not MessagePayload.model_validate({**base}).eh_audio()
    assert not MessagePayload.model_validate(
        {"id": "1", "from": GRUPO_FIXO, "hasMedia": False}
    ).eh_audio()


# --- áudio ------------------------------------------------------------------------------------


def test_audio_em_resposta_ao_bot_vira_a_primeira_mensagem_e_depois_a_resposta(
    ambiente: Ambiente,
) -> None:
    ambiente.transcritor.texto = "furniture"
    ambiente.canal.midias[URL] = b"ogg-bytes"

    ambiente.cliente.post("/waha/webhook", json=_audio(f"{BOT}@c.us"))

    assert ambiente.transcritor.chamadas == [(9, "audio/ogg; codecs=opus")]
    (primeira, segunda) = ambiente.canal.textos_enviados
    assert primeira == (GRUPO_FIXO, messages.audio_transcrito("furniture"))
    assert "*stall*" in segunda[1]
    assert ambiente.tutor.chamadas[0][1][0] == "furniture"
    assert ambiente.canal.vistos == [GRUPO_FIXO]


def test_audio_sem_citar_o_bot_e_ignorado_sem_baixar_nem_transcrever(ambiente: Ambiente) -> None:
    ambiente.canal.midias[URL] = b"ogg-bytes"

    ambiente.cliente.post("/waha/webhook", json=_audio(None))
    ambiente.cliente.post("/waha/webhook", json=_audio("5521977776666@c.us"))

    assert ambiente.transcritor.chamadas == []
    assert ambiente.canal.textos_enviados == [] and ambiente.canal.vistos == []


def test_outra_midia_em_resposta_ao_bot_segue_ignorada(ambiente: Ambiente) -> None:
    corpo = _audio(f"{BOT}@c.us", mimetype="image/jpeg")

    ambiente.cliente.post("/waha/webhook", json=corpo)

    assert ambiente.transcritor.chamadas == []
    assert ambiente.canal.textos_enviados == [] and ambiente.canal.vistos == []


def test_audio_longo_demais_avisa_e_nao_transcreve(ambiente: Ambiente) -> None:
    ambiente.canal.midias[URL] = b"x" * (MAX_BYTES_DO_AUDIO + 1)

    ambiente.cliente.post("/waha/webhook", json=_audio(f"{BOT}@c.us"))

    assert ambiente.transcritor.chamadas == []
    assert ambiente.canal.textos_enviados == [(GRUPO_FIXO, messages.AUDIO_GRANDE_DEMAIS)]


def test_audio_sem_fala_avisa_e_nao_chama_a_ia(ambiente: Ambiente) -> None:
    ambiente.transcritor.texto = ""
    ambiente.canal.midias[URL] = b"ogg"

    ambiente.cliente.post("/waha/webhook", json=_audio(f"{BOT}@c.us"))

    assert ambiente.canal.textos_enviados == [(GRUPO_FIXO, messages.AUDIO_SEM_FALA)]
    assert ambiente.tutor.chamadas == []


def test_falha_da_transcricao_ou_do_download_so_avisa(ambiente: Ambiente) -> None:
    ambiente.transcritor.falha = True
    ambiente.canal.midias[URL] = b"ogg"
    ambiente.cliente.post("/waha/webhook", json=_audio(f"{BOT}@c.us"))

    ambiente.transcritor.falha = False
    ambiente.canal.midias.clear()  # o download falha
    ambiente.cliente.post("/waha/webhook", json=_audio(f"{BOT}@c.us"))

    assert ambiente.canal.textos_enviados == [(GRUPO_FIXO, messages.ERRO_TRANSCRICAO)] * 2
    assert ambiente.tutor.chamadas == []


def test_audio_sem_transcritor_configurado_avisa(ambiente: Ambiente) -> None:
    from app.main import app, get_transcritor

    app.dependency_overrides[get_transcritor] = lambda: None
    ambiente.canal.midias[URL] = b"ogg"

    ambiente.cliente.post("/waha/webhook", json=_audio(f"{BOT}@c.us"))

    assert ambiente.canal.textos_enviados == [(GRUPO_FIXO, messages.ERRO_TRANSCRICAO)]
