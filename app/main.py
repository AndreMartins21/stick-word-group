"""Ponto de entrada FastAPI: `/health` e o webhook do WAHA (seção 8.1 da spec).

O webhook só filtra e responde 200 na hora; a conversa (IA, atrasos "humanos") roda em
segundo plano no `Router`, para o WAHA não esperar nem reenviar o evento.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac as hmac_lib
import json
import logging
import os
import re
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from google.cloud import firestore
from pydantic import SecretStr, ValidationError
from starlette.concurrency import run_in_threadpool

from app import messages
from app.channel.base import ChannelComLid, MidiaGrandeDemais
from app.channel.parser import (
    GroupJoinEvent,
    MessageEvent,
    MessagePayload,
    SessionStatusEvent,
    deve_ignorar_chat,
    digitos_do_chat_id,
    eh_lid,
    numero_e_permitido,
    numero_esta_na_lista,
    parse_evento,
)
from app.channel.waha import WahaChannel
from app.config import Settings
from app.domain.models import agora_utc
from app.flows import admin, grupo
from app.flows.base import Autor, ConfigGrupo
from app.flows.conversa import Conversa
from app.flows.router import Router
from app.logging_config import configurar_logs, id_curto, registrar_evento
from app.repo.base import Banco, tipo_do_espaco
from app.repo.firestore import FirestoreBanco
from app.repo.memory import MemoryBanco
from app.services import custo
from app.services.audio import ServicoAudio
from app.services.lembretes import Agendador
from app.services.letras import LrclibProvider
from app.services.llm import criar_tutor
from app.services.log_handler import criar_handler_da_nuvem
from app.services.metricas_destino import DestinoDeMetricas, criar_destino_gcs
from app.services.orcamento import Orcamento
from app.services.planilha import ExportadorExcel
from app.services.storage import (
    Armazenamento,
    ArmazenamentoLocal,
    criar_armazenamento_gcs,
    criar_cache_audio_gcs,
)
from app.services.transcricao import (
    MAX_BYTES_DO_AUDIO,
    Transcritor,
    criar_transcritor_vertex,
)
from app.services.tts import GoogleTts

logger = logging.getLogger(__name__)

SEGUNDOS_ESTIMADOS_DO_AUDIO = 30  # M43: quando o payload não traz `audioMessage.seconds`


def _nome_do_comando(corpo: str, prefixo: str) -> str:
    """Só para o evento `mensagem_recebida` (M27, seção 12 da spec): um rótulo grosseiro, nunca o
    texto do aluno. `"midia"` sem corpo (a mídia em si não é logada), o comando em minúsculas sem
    o prefixo, ou `"texto"` para o resto — não é o parser de comandos de verdade."""
    texto = corpo.strip()
    if not texto:
        return "midia"
    primeira = texto.split(maxsplit=1)[0]
    for candidato in (prefixo, "/"):
        if primeira.startswith(candidato):
            return primeira[len(candidato) :].lower() or "midia"
    return "texto"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # campos obrigatórios vêm do .env/ambiente em runtime


def _criar_banco(settings: Settings) -> Banco:
    """Firestore em produção (ou contra o emulador); em memória no desenvolvimento local,
    para nunca gravar por engano num Firestore real."""
    if settings.app_env == "prod" or os.environ.get("FIRESTORE_EMULATOR_HOST"):
        return FirestoreBanco(firestore.Client(project=settings.gcp_project_id))
    return MemoryBanco()


def _criar_armazenamento(settings: Settings) -> Armazenamento:
    """Cloud Storage em produção; em dev local, uma pasta `exports/` (que o git ignora)."""
    if settings.app_env == "prod":
        return criar_armazenamento_gcs(
            projeto=settings.gcp_project_id, bucket=settings.export_bucket
        )
    return ArmazenamentoLocal(Path("exports"))


def _handler_da_nuvem(settings: Settings) -> logging.Handler | None:
    """M27 (ADR-0028): os mesmos logs também vão ao Cloud Logging, em paralelo ao stdout de
    sempre — o driver do Docker não muda (o `gcplogs` quebraria `docker compose logs`). Só em
    produção: dev/CI nunca falam com a API real."""
    if settings.app_env != "prod":
        return None
    return criar_handler_da_nuvem(settings.gcp_project_id)


def _criar_audio(settings: Settings) -> ServicoAudio | None:
    """Pronúncia só em produção e com o bucket de áudio configurado; fora disso, indisponível
    (o TTS real precisa da conta de serviço da VM)."""
    if settings.app_env != "prod" or not settings.audio_bucket:
        return None
    return ServicoAudio(
        GoogleTts(),
        criar_cache_audio_gcs(projeto=settings.gcp_project_id, bucket=settings.audio_bucket),
        settings.tts_voice,
    )


def _criar_transcritor(settings: Settings) -> Transcritor | None:
    """Transcrição de áudio (M39): o mesmo Gemini do Vertex, só em produção, com
    `GEMINI_MODEL_AUDIO` ou, vazio, o `GEMINI_MODEL`. Com `LLM_PROVIDER=anthropic` (sem áudio) ou
    fora de produção, fica indisponível e o bot avisa."""
    modelo = settings.gemini_model_audio or settings.gemini_model
    if settings.app_env != "prod" or settings.llm_provider != "vertex_gemini" or not modelo:
        return None
    return criar_transcritor_vertex(
        projeto=settings.gcp_project_id,
        localizacao=settings.vertex_location,
        modelo=modelo,
        thinking_level=settings.gemini_thinking_level,
    )


def _criar_destino_metricas(settings: Settings) -> DestinoDeMetricas | None:
    """M28: sem `METRICS_BUCKET` (ou fora de produção), o snapshot diário simplesmente não roda —
    o `Agendador` confere isto sozinho (`destino_de_metricas=None`)."""
    if settings.app_env != "prod" or not settings.metrics_bucket:
        return None
    return criar_destino_gcs(projeto=settings.gcp_project_id, bucket=settings.metrics_bucket)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configurar_logs(settings.log_level, handler_extra=_handler_da_nuvem(settings))
    registrar_evento(logger, "inicio")
    canal = WahaChannel(
        base_url=settings.waha_url,
        api_key=settings.waha_api_key,
        session=settings.waha_session,
    )
    letras = LrclibProvider(base_url=settings.lyrics_url)
    banco = _criar_banco(settings)
    # M46 (ADR-0044): o custo estimado de cada chamada de IA alimenta o orçamento diário.
    orcamento = Orcamento(banco, settings.orcamento_diario_usd, fuso=ZoneInfo(settings.timezone))
    custo.definir_observador(orcamento.registrar)
    app.state.orcamento = orcamento
    app.state.channel = canal
    app.state.banco = banco
    app.state.transcritor = _criar_transcritor(settings)
    router = Router(
        banco=banco,
        tutor=criar_tutor(settings),
        criar_conversa=lambda chat_id: Conversa(canal, chat_id),
        nivel_padrao=settings.user_level,
        status_da_sessao=canal.session_status,
        exportador=ExportadorExcel(_criar_armazenamento(settings)),
        prefixo_do_grupo=settings.group_prefix,
        max_caracteres=settings.max_caracteres,
        limites=settings.limites,
        orcamento=orcamento,
        max_fila_por_chat=settings.max_fila_por_chat,
        max_processamentos=settings.max_processamentos,
        eh_dono=settings.eh_dono,
        eh_admin=lambda numero: admin.eh_admin(_acesso(settings, canal, banco), numero),
        config_grupo=ConfigGrupo(
            limite=settings.limite_por_sessao_grupo,
            timeout=timedelta(hours=settings.timeout_marcacao_horas),
            participantes=canal.group_participants,
            numero_do_bot=settings.bot_number,
        ),
        fuso=ZoneInfo(settings.timezone),
        letras=letras,
        audio=_criar_audio(settings),
    )
    app.state.router = router

    # M10: lembretes de revisão espaçada (seção 5.7, ADR-0012) — laço em segundo plano, um
    # minuto por vez; só dispara com um chat_id real já aprendido de uma mensagem recebida.
    agendador = Agendador(
        router=router,
        banco=banco,
        agora=agora_utc,
        fuso=ZoneInfo(settings.timezone),
        sair_do_grupo=canal.leave_group,
        grupo_autorizado=lambda grupo_id: admin.grupo_autorizado(
            _acesso(settings, canal, banco), grupo_id
        ),
        destino_de_metricas=_criar_destino_metricas(settings),
        orcamento=orcamento,
        avisar_dono=lambda texto: canal.send_text(f"{settings.dono}@c.us", texto),
    )
    app.state.agendador = agendador
    tarefa_do_agendador = asyncio.create_task(agendador.rodar())
    try:
        yield
    finally:
        agendador.parar()
        custo.definir_observador(None)
        await run_in_threadpool(orcamento.gravar)
        tarefa_do_agendador.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tarefa_do_agendador
        await canal.aclose()
        await letras.aclose()


app = FastAPI(title="vocabot", lifespan=_lifespan)


def get_channel(request: Request) -> ChannelComLid:
    channel: ChannelComLid = request.app.state.channel
    return channel


def get_banco(request: Request) -> Banco:
    banco: Banco = request.app.state.banco
    return banco


def get_router(request: Request) -> Router:
    router: Router = request.app.state.router
    return router


def get_transcritor(request: Request) -> Transcritor | None:
    transcritor: Transcritor | None = getattr(request.app.state, "transcritor", None)
    return transcritor


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/waha/webhook")
async def waha_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    channel: Annotated[ChannelComLid, Depends(get_channel)],
    banco: Annotated[Banco, Depends(get_banco)],
    router: Annotated[Router, Depends(get_router)],
    transcritor: Annotated[Transcritor | None, Depends(get_transcritor)],
    tarefas: BackgroundTasks,
) -> dict[str, bool]:
    corpo_bruto = await request.body()

    if settings.waha_hook_hmac_key is not None and not _hmac_valido(
        corpo_bruto, request.headers, settings.waha_hook_hmac_key
    ):
        logger.warning("webhook rejeitado: assinatura HMAC ausente ou inválida")
        raise HTTPException(status_code=401, detail="assinatura inválida")

    try:
        evento = parse_evento(json.loads(corpo_bruto))
    except ValueError as erro:
        # JSON inválido ou payload fora do formato esperado: nunca vira 500 (o WAHA reenviaria o
        # mesmo evento para sempre). Só os campos com problema vão ao log, nunca o conteúdo.
        campos = (
            sorted({".".join(map(str, e["loc"])) for e in erro.errors()})
            if isinstance(erro, ValidationError)
            else []
        )
        logger.warning("payload inválido no webhook (campos: %s)", campos or "json ilegível")
        return {"ok": True}

    if isinstance(evento, SessionStatusEvent):
        _tratar_status_sessao(evento)
        return {"ok": True}

    if isinstance(evento, GroupJoinEvent):
        try:
            await _tratar_entrada_em_grupo(evento, settings, channel, banco)
        except Exception:
            logger.exception("falha ao registrar a entrada em um grupo")
        return {"ok": True}

    if isinstance(evento, MessageEvent):
        try:
            await _tratar_mensagem(
                evento.payload, settings, channel, banco, router, transcritor, tarefas
            )
        except Exception:
            # Antes de saber quem escreveu não há para quem avisar; depois, o aviso vai só ao
            # próprio chat (dentro de `_tratar_mensagem`), nunca a outro aluno.
            logger.exception("falha ao processar mensagem")
        return {"ok": True}

    logger.info("evento sem assinatura ignorado")
    return {"ok": True}


def _hmac_valido(corpo: bytes, cabecalhos: Mapping[str, str], chave: SecretStr) -> bool:
    assinatura_recebida = cabecalhos.get("X-Webhook-Hmac")
    algoritmo = cabecalhos.get("X-Webhook-Hmac-Algorithm", "").lower()
    if not assinatura_recebida or algoritmo != "sha512":
        return False
    esperado = hmac_lib.new(chave.get_secret_value().encode(), corpo, hashlib.sha512).hexdigest()
    return hmac_lib.compare_digest(esperado, assinatura_recebida)


async def _tratar_mensagem(
    payload: MessagePayload,
    settings: Settings,
    channel: ChannelComLid,
    banco: Banco,
    router: Router,
    transcritor: Transcritor | None,
    tarefas: BackgroundTasks,
) -> None:
    if payload.from_me:
        logger.debug("mensagem própria ignorada: %s", id_curto(payload.id))
        return

    if payload.from_.endswith("@g.us"):
        await _tratar_mensagem_de_grupo(
            payload, settings, channel, banco, router, transcritor, tarefas
        )
        return

    if deve_ignorar_chat(payload.from_):
        logger.info("mensagem de status/canal ignorada")
        return

    numero_resolvido = await _numero_do_remetente(payload.from_, channel, banco)
    if numero_resolvido is None:
        logger.warning("LID não resolvido: o WAHA não achou o telefone do remetente; ignorada")
        return

    acesso = _acesso(settings, channel, banco)
    aluno = numero_esta_na_lista(numero_resolvido, settings.numeros_permitidos) or settings.eh_dono(
        numero_resolvido
    )
    e_admin = await run_in_threadpool(admin.eh_admin, acesso, numero_resolvido)

    # Responde ao número REAL do remetente (o que o WhatsApp informa). Ele passou pela allowlist,
    # mas pode diferir do número do .env no nono dígito: a conta pode estar registrada sem o 9, e
    # enviar para o número do .env dá "no LID found" no WAHA.
    chat_destino = f"{numero_resolvido}@c.us"

    if not aluno and not e_admin:
        # Sem plano: a IA nunca é chamada, nada é lido nem gravado, sem `sendSeen`. Só o aviso
        # (no máximo um por semana, ADR-0018) e depois silêncio.
        if payload.has_media or payload.body.strip():
            await _avisar_sem_plano(acesso, numero_resolvido, chat_destino)
        return

    try:
        await _despachar(
            payload, channel, banco, router, tarefas, chat_destino, acesso, numero_resolvido, aluno
        )
    except Exception:
        # Quem escreveu já está autorizado: o aviso vai só ao próprio chat, nunca a outro aluno.
        logger.exception("falha ao processar mensagem")
        with contextlib.suppress(Exception):
            await channel.send_text(chat_destino, messages.ERRO_INESPERADO)


async def _despachar(
    payload: MessagePayload,
    channel: ChannelComLid,
    banco: Banco,
    router: Router,
    tarefas: BackgroundTasks,
    chat_destino: str,
    acesso: admin.Acesso,
    numero: str,
    aluno: bool,
) -> None:
    if not payload.has_media and not payload.body.strip():
        # Sem texto nem mídia: o WAHA não conseguiu decifrar (ou é um tipo que não tratamos).
        logger.info("mensagem sem texto ignorada: %s", id_curto(payload.id))
        return

    if not await run_in_threadpool(banco.marcar_processada, payload.id, agora_utc()):
        logger.info("mensagem duplicada ignorada: %s", id_curto(payload.id))
        return

    registrar_evento(
        logger,
        "mensagem_recebida",
        espaco=id_curto(chat_destino),
        tipo_espaco=tipo_do_espaco(chat_destino),
        comando=_nome_do_comando(payload.body, "/"),
    )
    await channel.send_seen(chat_destino)
    tarefas.add_task(_responder, router, payload, channel, chat_destino, acesso, numero, aluno)


async def _responder(
    router: Router,
    payload: MessagePayload,
    channel: ChannelComLid,
    chat_destino: str,
    acesso: admin.Acesso,
    numero: str,
    aluno: bool,
) -> None:
    """Roda depois do 200. É a fronteira do sistema: nada que aconteça aqui pode escapar."""
    try:
        if not payload.has_media and admin.eh_comando_de_admin(payload.body):
            resposta = await admin.comando_privado(acesso, payload.body, numero)
            if resposta is not None:
                await router.responder_avulso(chat_destino, resposta)
                return
        if not aluno:
            # Um admin que não é aluno só usa os comandos de admin: o resto é "sem plano".
            await _avisar_sem_plano(acesso, numero, chat_destino)
            return
        if payload.has_media:
            await router.midia_nao_suportada(chat_destino)
        else:
            # M28: leva o nome do WhatsApp para o `Profile.nome` (nunca o telefone) — `Autor` num
            # espaço privado não muda o roteamento (só grupo confere `grupo_prefixo`).
            autor = Autor(numero=numero, nome=payload.nome_do_remetente())
            await router.processar(payload.body, chat_destino, autor)
    except Exception:
        logger.exception("falha ao processar mensagem")
        with contextlib.suppress(Exception):
            await channel.send_text(chat_destino, messages.ERRO_INESPERADO)


def _acesso(settings: Settings, channel: ChannelComLid, banco: Banco) -> admin.Acesso:
    return admin.Acesso(
        banco=banco,
        canal=channel,
        eh_dono=settings.eh_dono,
        grupos_fixos=settings.grupos_permitidos,
        max_grupos=settings.max_groups,
        agora=agora_utc,
        contato=settings.contact_email,
        prefixo=settings.group_prefix,
    )


async def _avisar_sem_plano(acesso: admin.Acesso, numero: str, chat_destino: str) -> None:
    """O aviso "você não tem um plano", no máximo uma vez por semana por número: a marca vive em
    `processed/`, então a TTL de 7 dias a expira sozinha."""
    if not await run_in_threadpool(
        acesso.banco.marcar_processada, _chave_do_aviso(numero), agora_utc()
    ):
        return
    registrar_evento(logger, "numero_sem_plano")
    with contextlib.suppress(Exception):
        await acesso.canal.send_text(chat_destino, messages.sem_plano(acesso.contato))


def _chave_do_aviso(numero: str) -> str:
    """A marca do aviso vive em `processed/` (TTL de 7 dias) sem guardar o telefone em claro."""
    return "aviso_" + hashlib.sha256(numero.encode()).hexdigest()[:32]


_GRUPOS_JA_LOGADOS: set[str] = set()
_PENDENTES_JA_REGISTRADOS: set[str] = set()


def _logar_grupo_uma_vez(grupo_id: str) -> None:
    """Grupo que ainda ninguém ativou: o id vai ao log UMA vez por processo, para o dono
    reconhecê-lo. Nada mais sobre a mensagem é logado."""
    if grupo_id not in _GRUPOS_JA_LOGADOS:
        _GRUPOS_JA_LOGADOS.add(grupo_id)
        logger.info(
            "bot em grupo não ativado (grupo %s): ignorando tudo até um admin ativar", grupo_id
        )


async def _registrar_pendente(banco: Banco, grupo_id: str) -> None:
    """Guarda o grupo como pendente (o agendador sai dele depois de 24 h). Uma ida ao banco por
    grupo por processo: um grupo barulhento não gera uma escrita por mensagem."""
    if grupo_id in _PENDENTES_JA_REGISTRADOS:
        return
    if await run_in_threadpool(banco.registrar_grupo_pendente, grupo_id, agora_utc()):
        registrar_evento(logger, "grupo_pendente", espaco=id_curto(grupo_id))
    _PENDENTES_JA_REGISTRADOS.add(grupo_id)


async def _tratar_entrada_em_grupo(
    evento: GroupJoinEvent, settings: Settings, channel: ChannelComLid, banco: Banco
) -> None:
    grupo_id = evento.payload.group.id
    if await run_in_threadpool(admin.grupo_autorizado, _acesso(settings, channel, banco), grupo_id):
        return
    _logar_grupo_uma_vez(grupo_id)
    await _registrar_pendente(banco, grupo_id)


async def _tratar_mensagem_de_grupo(
    payload: MessagePayload,
    settings: Settings,
    channel: ChannelComLid,
    banco: Banco,
    router: Router,
    transcritor: Transcritor | None,
    tarefas: BackgroundTasks,
) -> None:
    """Em grupo o bot só lê três coisas (ADR-0019, ADR-0035, ADR-0036): comandos com `!` ou `/`,
    mensagens que o marcam e respostas (citações) às mensagens dele; só a resposta a uma mensagem
    do bot também vale em áudio (M39, ADR-0037). O filtro vem antes de tudo (deduplicação,
    `sendSeen`): o resto é conversa entre pessoas, que ele não lê nem grava. Grupo não ativado só
    reage a `!activate` de um admin (M15)."""
    grupo_id = payload.from_
    corpo = payload.body
    acesso = _acesso(settings, channel, banco)
    autorizado = await run_in_threadpool(admin.grupo_autorizado, acesso, grupo_id)
    if not autorizado:
        _logar_grupo_uma_vez(grupo_id)
        await _registrar_pendente(banco, grupo_id)

    audio = payload.eh_audio()
    if payload.has_media and not audio:
        return  # mídia que não é áudio: ignorada em silêncio
    marcado = False
    if audio:
        # Áudio não carrega `@bot` nem comando: só a resposta a uma mensagem do bot o chama.
        if not autorizado or not await _responde_ao_bot(payload, settings, channel, banco):
            return
        corpo = ""
        marcado = True
    elif grupo.sem_prefixo(corpo, settings.group_prefix) is None:
        if not autorizado:
            return
        sem_marca = await _sem_marcacao_do_bot(payload, settings, channel, banco)
        if sem_marca is None:
            if not await _responde_ao_bot(payload, settings, channel, banco):
                return  # conversa entre pessoas: o bot não lê
            sem_marca = corpo  # resposta a uma mensagem do bot: é conversa com ele (ADR-0036)
        corpo = sem_marca
        marcado = grupo.sem_prefixo(corpo, settings.group_prefix) is None
    comando = admin.eh_comando_de_ativacao(corpo, settings.group_prefix)
    if not autorizado and comando is None:
        return
    if payload.participant is None:
        logger.info("mensagem de grupo sem participante: ignorada")
        return
    numero = await _numero_do_remetente(payload.participant, channel, banco)
    if numero is None:
        return
    if comando is not None and not await run_in_threadpool(admin.eh_admin, acesso, numero):
        return  # `!activate` de quem não é admin: o bot não revela que existe
    if not await run_in_threadpool(banco.marcar_processada, payload.id, agora_utc()):
        logger.info("mensagem duplicada ignorada: %s", id_curto(payload.id))
        return
    registrar_evento(
        logger,
        "mensagem_recebida",
        espaco=id_curto(grupo_id),
        tipo_espaco="grupo",
        comando=(
            "audio"
            if audio
            else "marcacao"
            if marcado
            else _nome_do_comando(corpo, settings.group_prefix)
        ),
    )
    await channel.send_seen(grupo_id)

    if comando is not None:
        await admin.tratar_ativacao_no_grupo(acesso, comando, grupo_id, numero)
        return
    autor = Autor(
        numero=numero,
        nome=payload.nome_do_remetente(),
        mencionados=await _numeros_mencionados(payload, channel, banco),
    )
    if audio:
        tarefas.add_task(
            _responder_ao_audio_no_grupo,
            router,
            channel,
            transcritor,
            payload,
            grupo_id,
            autor,
            settings.max_segundos_audio,
        )
        return
    tarefas.add_task(_responder_no_grupo, router, channel, grupo_id, corpo, autor, marcado)


def _reconhecedor_do_bot(settings: Settings, do_canal: set[str]) -> Callable[[str], bool]:
    """`True` para os dígitos que são do bot: o `me` da sessão (número e LID) ou o `BOT_NUMBER`
    (nono dígito à parte)."""
    do_bot = do_canal | {re.sub(r"\D", "", settings.bot_number)}

    def eh_o_bot(digitos: str) -> bool:
        return digitos in do_bot or numero_e_permitido(digitos, settings.bot_number)

    return eh_o_bot


async def _responde_ao_bot(
    payload: MessagePayload, settings: Settings, channel: ChannelComLid, banco: Banco
) -> bool:
    """A mensagem cita (responde a) uma mensagem escrita pelo bot (M38, ADR-0036). O autor citado
    vem como número ou LID: reconhece-se como a marcação, pelo `me` da sessão ou, sem ele, pelo
    número que o LID resolve."""
    citados = payload.ids_do_autor_citado()
    if not citados:
        return False
    do_canal = await channel.bot_ids()
    eh_o_bot = _reconhecedor_do_bot(settings, do_canal)
    for citado in citados:
        if eh_o_bot(digitos_do_chat_id(citado)):
            return True
        if not do_canal:
            numero = await _numero_do_remetente(citado, channel, banco)
            if numero is not None and eh_o_bot(numero):
                return True
    return False


async def _sem_marcacao_do_bot(
    payload: MessagePayload, settings: Settings, channel: ChannelComLid, banco: Banco
) -> str | None:
    """`None` se a mensagem não marca o bot; senão, o texto sem a marcação dele (o resto da
    mensagem é o que a pessoa disse ao bot). O bot é reconhecido pelos ids marcados na mensagem
    (`contextInfo.mentionedJID`, que no GOWS vem como o LID dele) contra o `me` da sessão e o
    `BOT_NUMBER`; como plano B, por `@numero` ou `@bot` escritos no texto (ADR-0035)."""
    do_canal = await channel.bot_ids()
    eh_o_bot = _reconhecedor_do_bot(settings, do_canal)

    a_tirar: set[str] = set()
    for mencionado in payload.ids_mencionados():
        digitos = digitos_do_chat_id(mencionado)
        if eh_o_bot(digitos):
            a_tirar.add(digitos)
        elif not do_canal:  # sem o `me`, o LID só se reconhece pelo número que ele resolve
            numero = await _numero_do_remetente(mencionado, channel, banco)
            if numero is not None and eh_o_bot(numero):
                a_tirar.add(digitos)
    a_tirar |= {d for d in grupo.numeros_marcados_no_texto(payload.body) if eh_o_bot(d)}
    if not a_tirar and not grupo.marca_literal_do_bot(payload.body):
        return None
    return grupo.sem_marcacao(payload.body, a_tirar)


async def _numeros_mencionados(
    payload: MessagePayload, channel: ChannelComLid, banco: Banco
) -> tuple[str, ...]:
    """Os números das menções que o payload trouxer (o WAHA não documenta o campo: pode vir
    vazio). LIDs são resolvidos pelo cache `lids/`."""
    numeros: list[str] = []
    for mencionado in payload.ids_mencionados():
        numero = await _numero_do_remetente(mencionado, channel, banco)
        if numero:
            numeros.append(numero)
    return tuple(numeros)


async def _responder_no_grupo(
    router: Router,
    channel: ChannelComLid,
    grupo_id: str,
    texto: str,
    autor: Autor,
    marcado: bool = False,
    admitida: bool = False,
) -> None:
    """Roda depois do 200, como `_responder`: nada que aconteça aqui pode escapar."""
    try:
        await router.processar(texto, grupo_id, autor, marcado=marcado, admitida=admitida)
    except Exception:
        logger.exception("falha ao processar mensagem de grupo")
        with contextlib.suppress(Exception):
            await channel.send_text(grupo_id, messages.ERRO_INESPERADO)


async def _responder_ao_audio_no_grupo(
    router: Router,
    channel: ChannelComLid,
    transcritor: Transcritor | None,
    payload: MessagePayload,
    grupo_id: str,
    autor: Autor,
    max_segundos: int,
) -> None:
    """Roda depois do 200: baixa o áudio, transcreve, mostra o que ouviu como primeira mensagem e
    segue como uma mensagem marcada comum (M38, ADR-0036). O texto transcrito não vai ao log."""
    try:
        # M43 (ADR-0041): o limite de uso vale ANTES de baixar e transcrever (o custo está aí);
        # sem a duração no payload, conta uma estimativa.
        segundos = payload.segundos_do_audio() or SEGUNDOS_ESTIMADOS_DO_AUDIO
        if not await router.admitir(grupo_id, autor, segundos_de_audio=segundos):
            return
        texto = await _transcrever(channel, transcritor, payload, grupo_id, max_segundos)
    except Exception:
        logger.exception("falha ao transcrever o áudio do grupo")
        with contextlib.suppress(Exception):
            await channel.send_text(grupo_id, messages.ERRO_TRANSCRICAO)
        return
    if texto is None:
        return
    await channel.send_text(grupo_id, messages.audio_transcrito(texto))
    await _responder_no_grupo(router, channel, grupo_id, texto, autor, marcado=True, admitida=True)


async def _transcrever(
    channel: ChannelComLid,
    transcritor: Transcritor | None,
    payload: MessagePayload,
    grupo_id: str,
    max_segundos: int,
) -> str | None:
    """O texto falado, ou `None` depois de avisar o grupo (sem serviço, áudio longo, sem fala)."""
    url = payload.url_da_midia()
    if transcritor is None or url is None:
        logger.warning("áudio sem transcritor ou sem url de mídia: ignorado")
        await channel.send_text(grupo_id, messages.ERRO_TRANSCRICAO)
        return None
    # M41 (ADR-0039): duração e tamanho que o WhatsApp declara no payload recusam o áudio ANTES de
    # baixá-lo; o download ainda tem teto de bytes, para o caso de o payload não trazer os campos.
    segundos = payload.segundos_do_audio()
    declarado = payload.bytes_do_audio()
    if (segundos is not None and segundos > max_segundos) or (
        declarado is not None and declarado > MAX_BYTES_DO_AUDIO
    ):
        registrar_evento(logger, "audio_recusado", motivo="duracao_ou_tamanho_declarado")
        await channel.send_text(grupo_id, messages.audio_grande_demais(max_segundos))
        return None
    try:
        conteudo = await channel.download_media(url, max_bytes=MAX_BYTES_DO_AUDIO)
    except MidiaGrandeDemais:
        registrar_evento(logger, "audio_recusado", motivo="tamanho_baixado")
        await channel.send_text(grupo_id, messages.audio_grande_demais(max_segundos))
        return None
    mimetype = payload.mimetype_da_midia() or "audio/ogg"
    texto = await run_in_threadpool(transcritor.transcrever, conteudo, mimetype)
    if not texto:
        await channel.send_text(grupo_id, messages.AUDIO_SEM_FALA)
        return None
    return texto


async def _numero_do_remetente(chat_id: str, channel: ChannelComLid, banco: Banco) -> str | None:
    if not eh_lid(chat_id):
        return digitos_do_chat_id(chat_id)
    em_cache = await run_in_threadpool(banco.obter_numero_do_lid, chat_id)
    if em_cache is not None:
        return em_cache
    numero = await channel.resolve_lid(chat_id)
    if numero is not None:
        await run_in_threadpool(banco.salvar_numero_do_lid, chat_id, numero)
    return numero


def _tratar_status_sessao(evento: SessionStatusEvent) -> None:
    ok = evento.payload.status == "WORKING"
    registrar_evento(
        logger,
        "waha_status",
        nivel=logging.INFO if ok else logging.WARNING,
        ok=ok,
        motivo=evento.payload.status,
    )
