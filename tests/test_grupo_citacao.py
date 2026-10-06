"""M38 (ADR-0036): em grupo o bot também responde a quem responde (cita) uma mensagem dele, sem
marcar nem comando."""

from __future__ import annotations

from typing import Any

from app.channel.parser import MessagePayload
from tests.webhook_helpers import GRUPO_FIXO, Ambiente, _do_grupo

ANA = "5531999998888"
BOT = "5531988887777"
LID_DO_BOT = "119302179033090@lid"


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


# --- parser -----------------------------------------------------------------------------------


def test_parser_le_o_autor_citado_do_reply_to_e_do_context_info() -> None:
    base = {"id": "1", "from": GRUPO_FIXO}

    a = MessagePayload.model_validate({**base, "replyTo": {"participant": f"{BOT}@c.us"}})
    b = MessagePayload.model_validate(
        {
            **base,
            "_data": {
                "Message": {
                    "extendedTextMessage": {
                        "contextInfo": {"stanzaID": "S", "participant": LID_DO_BOT}
                    }
                }
            },
        }
    )
    sem_citacao = MessagePayload.model_validate(
        {
            **base,
            "_data": {
                "Message": {"extendedTextMessage": {"contextInfo": {"participant": "x@c.us"}}}
            },
        }
    )

    assert a.ids_do_autor_citado() == [f"{BOT}@c.us"]
    assert b.ids_do_autor_citado() == [LID_DO_BOT]
    assert sem_citacao.ids_do_autor_citado() == []


# --- responder a uma mensagem do bot ---------------------------------------------------------


def test_resposta_a_mensagem_do_bot_sem_marcar_o_bot_responde(ambiente: Ambiente) -> None:
    ambiente.cliente.post("/waha/webhook", json=_citando("furniture", f"{BOT}@c.us"))

    ((chat, texto),) = ambiente.canal.textos_enviados
    assert chat == GRUPO_FIXO and "*stall*" in texto
    assert ambiente.tutor.chamadas[0][1][0] == "furniture"
    assert ambiente.canal.vistos == [GRUPO_FIXO]


def test_resposta_a_mensagem_do_bot_pelo_context_info_e_pelo_lid(ambiente: Ambiente) -> None:
    ambiente.canal.ids_do_bot = {"553198887777", "119302179033090"}

    ambiente.cliente.post(
        "/waha/webhook", json=_citando("furniture", LID_DO_BOT, como="contextInfo")
    )

    assert len(ambiente.canal.textos_enviados) == 1


def test_sem_o_me_do_canal_o_lid_citado_se_reconhece_pelo_numero_resolvido(
    ambiente: Ambiente,
) -> None:
    ambiente.canal.lids_conhecidos[LID_DO_BOT] = BOT

    ambiente.cliente.post("/waha/webhook", json=_citando("furniture", LID_DO_BOT))

    assert len(ambiente.canal.textos_enviados) == 1


def test_resposta_a_outra_pessoa_nao_chama_o_bot(ambiente: Ambiente) -> None:
    ambiente.cliente.post("/waha/webhook", json=_citando("furniture", "5521977776666@c.us"))

    assert ambiente.canal.textos_enviados == [] and ambiente.canal.vistos == []
    assert ambiente.tutor.chamadas == []


def test_resposta_ao_bot_com_comando_vale_como_o_comando(ambiente: Ambiente) -> None:
    ambiente.cliente.post("/waha/webhook", json=_citando("!help", f"{BOT}@c.us"))

    ((_, texto),) = ambiente.canal.textos_enviados
    assert "tag me" in texto and ambiente.tutor.chamadas == []


def test_mensagem_com_midia_citando_o_bot_segue_ignorada(ambiente: Ambiente) -> None:
    corpo = _citando("", f"{BOT}@c.us")
    corpo["payload"]["hasMedia"] = True

    ambiente.cliente.post("/waha/webhook", json=corpo)

    assert ambiente.canal.textos_enviados == [] and ambiente.canal.vistos == []
