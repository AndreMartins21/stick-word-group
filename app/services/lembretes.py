"""Agendador de lembretes de revisão espaçada (M10, seção 5.7, ADR-0012).

Um laço no próprio processo, acordando a cada minuto (`_tick`, testável isolado de `rodar`), com
o próximo horário persistido em `profile/me` de cada espaço — sobrevive a um restart do container.
Três camadas de segurança contra mandar mensagem sem o aluno pedir (seção 5.6), valendo por espaço
(ADR-0017): só dispara com um `chat_id` real já aprendido de uma mensagem recebida, nunca sem fila
(silêncio em vez de spam) e nunca dois lembretes seguidos sem resposta (`lembrete_sem_resposta`).
Uma consulta por tick devolve só os espaços vencidos, então o custo não cresce com o número de
alunos parados.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app import messages
from app.domain.agenda_grupo import (
    MAX_REVISOES_SEM_RESPOSTA,
    jitter_do_espaco,
    proxima_diaria,
    proxima_semanal,
)
from app.domain.lembretes import proximo_horario
from app.domain.models import Estado, Profile
from app.domain.state import expirou
from app.flows import review
from app.flows.admin import PRAZO_GRUPO_PENDENTE
from app.flows.base import bloq
from app.flows.router import Router
from app.logging_config import id_curto, registrar_evento
from app.repo.base import Banco, Repository, tipo_do_espaco
from app.services.metricas_destino import DestinoDeMetricas
from app.services.orcamento import Orcamento, avisar_esgotado
from app.services.snapshot import montar_snapshot, tabelas

logger = logging.getLogger(__name__)

INTERVALO_PADRAO_SEGUNDOS = 60
LIMITE_DE_ATRASO = timedelta(hours=2)
# Se o `leave` continua falhando (o bot já foi removido do grupo), para de tentar depois disto.
DESISTIR_DE_SAIR_APOS = timedelta(hours=72)
HORA_PADRAO_DO_SNAPSHOT = 4  # 04:00 no fuso do aluno (M28, seção 12 da spec)


class Agendador:
    def __init__(
        self,
        *,
        router: Router,
        banco: Banco,
        agora: Callable[[], datetime],
        fuso: ZoneInfo,
        dormir: Callable[[float], Awaitable[None]] = asyncio.sleep,
        intervalo_segundos: float = INTERVALO_PADRAO_SEGUNDOS,
        sair_do_grupo: Callable[[str], Awaitable[None]] | None = None,
        grupo_autorizado: Callable[[str], bool] | None = None,
        destino_de_metricas: DestinoDeMetricas | None = None,
        hora_do_snapshot: int = HORA_PADRAO_DO_SNAPSHOT,
        orcamento: Orcamento | None = None,
        avisar_dono: Callable[[str], Awaitable[None]] | None = None,
        jitter_do_grupo: Callable[[str, str], timedelta] = jitter_do_espaco,
    ) -> None:
        self._router = router
        self._banco = banco
        self._agora = agora
        self._fuso = fuso
        self._dormir = dormir
        self._intervalo = intervalo_segundos
        self._sair_do_grupo = sair_do_grupo
        # M16: grupo desativado por um admin não recebe lembrete (None = não confere).
        self._grupo_autorizado = grupo_autorizado
        # M28: `None` (padrão) desliga o snapshot — nenhum ambiente manda métricas sem um destino
        # explícito (o `dev`/CI nunca configuram um).
        self._destino_de_metricas = destino_de_metricas
        self._hora_do_snapshot = hora_do_snapshot
        # M46 (ADR-0044): orçamento diário esgotado pausa os lembretes e avisa o dono uma vez.
        self._orcamento = orcamento
        self._avisar_dono = avisar_dono
        # M55 (ADR-0053): deslocamento fixo de cada grupo (os testes fixam em zero).
        self._jitter = jitter_do_grupo
        self._parar = False

    def parar(self) -> None:
        self._parar = True

    async def rodar(self) -> None:
        """Laço principal; roda até `parar()` ser chamado (o `_lifespan` do FastAPI cancela a
        task no shutdown, o que já interrompe o `dormir` — `parar()` é o caminho ordenado)."""
        while not self._parar:
            try:
                await self._tick()
            except Exception:  # o agendador nunca pode derrubar o processo
                logger.exception("falha no tick do agendador de lembretes")
            await self._dormir(self._intervalo)

    async def _tick(self) -> None:
        agora_utc = self._agora()
        try:  # antes dos lembretes: uma rodada vencida fecha e libera a sessão no mesmo tick
            await self._expirar_marcacoes(agora_utc)
        except Exception:  # o Firestore falhando aqui não pode calar os lembretes do próximo tick
            logger.exception("falha ao fechar revisões de grupo paradas")
        try:
            pausado = await self._orcamento_pausado()
        except Exception:  # o orçamento falhando não pode calar o resto do tick
            logger.exception("falha ao conferir o orçamento diário")
            pausado = False
        for espaco_id in (
            [] if pausado else await bloq(self._banco.listar_espacos_com_lembrete, agora_utc)
        ):
            try:
                await self._tick_espaco(espaco_id)
            except Exception:  # um espaço com problema não pode calar os outros
                logger.exception("falha no lembrete de um espaço; os demais seguem")
        try:
            await self._sair_de_grupos_pendentes()
        except Exception:  # o Firestore falhando aqui não pode calar os lembretes do próximo tick
            logger.exception("falha ao sair de grupos pendentes")
        try:
            await self._rodar_snapshot_se_for_a_hora(agora_utc)
        except Exception:  # o snapshot nunca pode calar os lembretes (M28)
            logger.exception("falha no snapshot diário; os lembretes seguem")

    async def _orcamento_pausado(self) -> bool:
        """Orçamento diário de IA esgotado (M46): nenhum lembrete sai (os atrasados viram
        `lembrete_desistido` quando o dia virar). Na primeira vez do dia, avisa o dono."""
        if self._orcamento is None:
            return False
        await self._avisar_cotas_de_grupo()
        if not await bloq(self._orcamento.esgotado):
            return False
        motivo = await bloq(self._orcamento.acabou_de_esgotar)
        if motivo is not None:
            avisar_esgotado(self._orcamento, motivo)
            if self._avisar_dono is not None:
                mensal = motivo == "mes"
                limite = (
                    (self._orcamento.limite_mensal_usd or 0)
                    if mensal
                    else (self._orcamento.limite_usd)
                )
                with contextlib.suppress(Exception):
                    await self._avisar_dono(messages.orcamento_do_dono(limite, mensal=mensal))
        return True

    async def _avisar_cotas_de_grupo(self) -> None:
        """Grupo que estourou a cota diária (M50, ADR-0048): um aviso ao dono por grupo por dia."""
        orcamento = self._orcamento
        if orcamento is None:
            return
        for grupo_id in await bloq(orcamento.grupos_recem_esgotados):
            registrar_evento(logger, "cota_do_grupo_esgotada", espaco=id_curto(grupo_id))
            if self._avisar_dono is not None:
                cota = orcamento.cota_por_grupo_usd or 0.0
                with contextlib.suppress(Exception):
                    await self._avisar_dono(messages.cota_do_grupo_para_o_dono(grupo_id, cota))

    async def _rodar_snapshot_se_for_a_hora(self, agora_utc: datetime) -> None:
        """Uma vez por dia, na janela de `_hora_do_snapshot` (M28, seção 12 da spec): sem
        destino configurado, fica desligado. `obter_ultimo_snapshot` sobrevive a um restart do
        container, então um tick perdido não faz o snapshot rodar duas vezes no mesmo dia."""
        if self._destino_de_metricas is None:
            return
        agora_local = agora_utc.astimezone(self._fuso)
        if agora_local.hour != self._hora_do_snapshot:
            return
        hoje = agora_local.date()
        ultimo = await bloq(self._banco.obter_ultimo_snapshot)
        if ultimo is not None and ultimo >= hoje:
            return

        inicio = time.monotonic()
        try:
            snapshot = await bloq(montar_snapshot, self._banco, agora_utc)
            total = 0
            for tabela, linhas in tabelas(snapshot):
                await bloq(self._destino_de_metricas.gravar, tabela, hoje, linhas)
                total += len(linhas)
        except Exception:
            registrar_evento(
                logger,
                "snapshot_falhou",
                latencia_ms=round((time.monotonic() - inicio) * 1000),
            )
            raise

        await bloq(self._banco.marcar_snapshot, hoje)
        registrar_evento(
            logger, "snapshot_ok", n=total, latencia_ms=round((time.monotonic() - inicio) * 1000)
        )

    async def _tick_espaco(self, espaco_id: str) -> None:
        if (
            espaco_id.endswith("@g.us")
            and self._grupo_autorizado is not None
            and not await bloq(self._grupo_autorizado, espaco_id)
        ):
            return
        if (
            self._orcamento is not None
            and espaco_id.endswith("@g.us")
            and await bloq(self._orcamento.espaco_esgotado, espaco_id)
        ):
            return  # cota diária do grupo esgotada (M50): sem revisão nem desafio até amanhã
        repo = self._banco.do_espaco(espaco_id)
        perfil = await bloq(repo.obter_perfil)
        if perfil is not None and perfil.chat_id is not None and espaco_id.endswith("@g.us"):
            await self._tick_grupo(repo, espaco_id, perfil)
            return
        if perfil is None or perfil.lembretes_por_dia == 0 or perfil.chat_id is None:
            return

        agora_utc = self._agora()
        agora_local = agora_utc.astimezone(self._fuso)

        if perfil.proximo_lembrete is None:
            await self._agendar_proximo(repo, perfil, agora_local)
            return
        if agora_utc < perfil.proximo_lembrete:
            return  # ainda não deu a hora

        tipo_espaco = tipo_do_espaco(espaco_id)
        espaco = id_curto(espaco_id)

        atrasado_demais = agora_utc - perfil.proximo_lembrete > LIMITE_DE_ATRASO
        if atrasado_demais or perfil.lembrete_sem_resposta:
            # desiste deste horário (atraso grande, ou o aluno não respondeu ao lembrete
            # anterior): recalcula o próximo, sem disparar de novo.
            motivo = "atraso" if atrasado_demais else "sem_resposta_anterior"
            registrar_evento(
                logger, "lembrete_desistido", espaco=espaco, tipo_espaco=tipo_espaco, motivo=motivo
            )
            await self._agendar_proximo(repo, perfil, agora_local)
            return

        sessao = await bloq(repo.obter_sessao)
        if sessao.estado != Estado.IDLE:
            registrar_evento(
                logger,
                "lembrete_adiado",
                espaco=espaco,
                tipo_espaco=tipo_espaco,
                motivo="conversa_em_andamento",
            )
            return  # conversa em andamento: tenta de novo no próximo tick

        entradas = await bloq(repo.listar_entradas)
        fila = review.montar_fila(entradas, agora_utc)
        if not fila:
            # nada vencido agora: recalcula o próximo horário, sem marcar backoff nem mandar nada.
            registrar_evento(
                logger,
                "lembrete_adiado",
                espaco=espaco,
                tipo_espaco=tipo_espaco,
                motivo="nada_vencido",
            )
            await self._agendar_proximo(repo, perfil, agora_local)
            return

        await bloq(repo.salvar_perfil, perfil.model_copy(update={"lembrete_sem_resposta": True}))
        registrar_evento(
            logger, "lembrete_enviado", espaco=espaco, tipo_espaco=tipo_espaco, n=len(fila)
        )
        await self._router.iniciar_revisao(perfil.chat_id)

        perfil_apos = await bloq(repo.obter_perfil)
        if perfil_apos is not None:
            await self._agendar_proximo(repo, perfil_apos, agora_local)

    async def _tick_grupo(self, repo: Repository, espaco_id: str, perfil: Profile) -> None:
        """Revisão diária e desafio semanal do grupo (M35/M36, ADR-0033/ADR-0034), no horário e
        nos dias da turma. Pausa depois de 3 revisões seguidas sem nenhuma mensagem do grupo (volta
        na próxima mensagem). O semanal tem precedência se os dois vencem no mesmo tick."""
        agora_utc = self._agora()
        agora_local = agora_utc.astimezone(self._fuso)
        calcular = [
            tipo
            for tipo in ("semanal", "diaria")
            if getattr(perfil, f"{tipo}_ligada") and getattr(perfil, f"proxima_{tipo}") is None
        ]
        if calcular:
            for tipo in calcular:
                perfil = self._com_horario(perfil, tipo, agora_local, espaco_id)
            await bloq(repo.salvar_perfil, perfil)
        for tipo in ("semanal", "diaria"):
            proximo = getattr(perfil, f"proxima_{tipo}")
            if getattr(perfil, f"{tipo}_ligada") and agora_utc >= proximo:
                await self._disparar_grupo(repo, espaco_id, perfil, tipo)
                return

    def _com_horario(
        self, perfil: Profile, tipo: str, agora_local: datetime, espaco_id: str
    ) -> Profile:
        """O próximo horário do grupo, com o `jitter` fixo dele (M55, ADR-0053)."""
        jitter = self._jitter(espaco_id, tipo)
        if tipo == "semanal":
            novo = proxima_semanal(
                agora_local,
                perfil.semanal_dia,
                perfil.semanal_hora,
                perfil.semanal_minuto,
                jitter,
            )
        else:
            novo = proxima_diaria(
                agora_local,
                perfil.diaria_hora,
                perfil.diaria_minuto,
                perfil.diaria_fim_de_semana,
                jitter,
            )
        return perfil.model_copy(update={f"proxima_{tipo}": novo.astimezone(UTC)})

    async def _disparar_grupo(
        self, repo: Repository, espaco_id: str, perfil: Profile, tipo: str
    ) -> None:
        agora_utc = self._agora()
        agora_local = agora_utc.astimezone(self._fuso)
        espaco = id_curto(espaco_id)
        horario: datetime = getattr(perfil, f"proxima_{tipo}")

        motivo: str | None = None
        if agora_utc - horario > LIMITE_DE_ATRASO:
            motivo = "atraso"
        elif perfil.revisoes_sem_resposta >= MAX_REVISOES_SEM_RESPOSTA:
            motivo = "pausado"
        if motivo is not None:
            registrar_evento(
                logger, "lembrete_desistido", espaco=espaco, tipo_espaco="grupo", motivo=motivo
            )
            await bloq(repo.salvar_perfil, self._com_horario(perfil, tipo, agora_local, espaco_id))
            return

        sessao = await bloq(repo.obter_sessao)
        if sessao.estado != Estado.IDLE and not expirou(sessao.atualizado_em, agora_utc):
            registrar_evento(
                logger,
                "lembrete_adiado",
                espaco=espaco,
                tipo_espaco="grupo",
                motivo="conversa_em_andamento",
            )
            return  # conversa em andamento: tenta de novo no próximo tick

        entradas = await bloq(repo.listar_entradas)
        # A diária só vale com algo para revisar; o desafio semanal, com qualquer palavra da turma.
        fila = review.montar_fila(entradas, agora_utc) if tipo == "diaria" else entradas
        if not fila:
            registrar_evento(
                logger, "lembrete_adiado", espaco=espaco, tipo_espaco="grupo", motivo="nada_vencido"
            )
            await bloq(repo.salvar_perfil, self._com_horario(perfil, tipo, agora_local, espaco_id))
            return

        await bloq(
            repo.salvar_perfil,
            perfil.model_copy(update={"revisoes_sem_resposta": perfil.revisoes_sem_resposta + 1}),
        )
        registrar_evento(
            logger, "lembrete_enviado", espaco=espaco, tipo_espaco="grupo", n=len(fila)
        )
        if tipo == "semanal":
            await self._router.iniciar_semanal(espaco_id)
        else:
            await self._router.iniciar_revisao(espaco_id)

        perfil_apos = await bloq(repo.obter_perfil)
        if perfil_apos is not None:
            await bloq(
                repo.salvar_perfil, self._com_horario(perfil_apos, tipo, agora_local, espaco_id)
            )

    async def _agendar_proximo(
        self, repo: Repository, perfil: Profile, agora_local: datetime
    ) -> None:
        novo = proximo_horario(
            agora_local, perfil.lembretes_por_dia, perfil.janela_inicio, perfil.janela_fim
        )
        await bloq(
            repo.salvar_perfil,
            perfil.model_copy(update={"proximo_lembrete": novo.astimezone(UTC)}),
        )

    async def _expirar_marcacoes(self, agora: datetime) -> None:
        """M35 (ADR-0033): revisão em grupo parada por 3 horas fecha com o resumo. Uma consulta por
        tick devolve só os grupos vencidos; cada um é tratado à parte."""
        for grupo_id in await bloq(self._banco.listar_grupos_com_timeout, agora):
            try:
                await self._router.expirar_marcacao(grupo_id)
                registrar_evento(logger, "marcacao_expirada", espaco=id_curto(grupo_id))
            except Exception:  # um grupo com problema não pode calar os outros
                logger.exception("falha ao expirar a marcação de um grupo; os demais seguem")

    async def _sair_de_grupos_pendentes(self) -> None:
        """M15 (ADR-0018): o bot não fica em grupo que nenhum admin ativou em 24 h. Sai em
        silêncio e apaga o registro; se a saída falha, tenta de novo no próximo tick, até desistir
        (o bot pode já ter sido removido do grupo)."""
        if self._sair_do_grupo is None:
            return
        agora = self._agora()
        for grupo_id, visto_em in await bloq(self._banco.listar_grupos_pendentes):
            idade = agora - visto_em
            if idade <= PRAZO_GRUPO_PENDENTE:
                continue
            try:
                await self._sair_do_grupo(grupo_id)
            except Exception:
                if idade <= DESISTIR_DE_SAIR_APOS:
                    logger.warning("não consegui sair de um grupo pendente; tento de novo")
                    continue
                logger.warning("desisti de sair de um grupo pendente (falha por muito tempo)")
            await bloq(self._banco.remover_grupo_pendente, grupo_id)
            registrar_evento(logger, "saiu_de_grupo", espaco=id_curto(grupo_id))
