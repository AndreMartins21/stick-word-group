"""Orçamento diário de IA, o disjuntor global (M46, ADR-0044).

Soma o custo estimado (`services/custo.py`) de cada chamada ao Gemini no dia (fuso do aluno) e diz
quando o teto `ORCAMENTO_DIARIO_USD` foi atingido. O gasto é espelhado no Firestore (`meta/uso_{dia}`,
em lote, no máximo uma escrita por `INTERVALO_DE_GRAVACAO`) para um restart não zerar o dia. Chamado
de threads (as funções de IA são síncronas): tudo aqui é protegido por trava."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain.models import agora_utc
from app.logging_config import registrar_evento
from app.repo.base import Banco

logger = logging.getLogger(__name__)

INTERVALO_DE_GRAVACAO = timedelta(seconds=30)


class Orcamento:
    def __init__(
        self,
        banco: Banco,
        limite_usd: float,
        *,
        fuso: ZoneInfo,
        agora: Callable[[], datetime] = agora_utc,
    ) -> None:
        self._banco = banco
        self._limite = limite_usd
        self._fuso = fuso
        self._agora = agora
        self._trava = threading.Lock()
        self._dia: date | None = None
        self._gasto = 0.0
        self._pendente = 0.0
        self._ultima_gravacao = agora()
        self._esgotou_avisado = False

    # -- API pública -------------------------------------------------------------------------

    def registrar(self, custo_usd: float) -> None:
        """Soma o custo de uma chamada (qualquer thread). Nunca levanta: custo é telemetria."""
        if custo_usd <= 0:
            return
        try:
            with self._trava:
                self._virar_o_dia()
                self._gasto += custo_usd
                self._pendente += custo_usd
                self._gravar_se_for_hora()
        except Exception:  # o disjuntor nunca derruba a chamada de IA
            logger.warning("falha ao registrar o custo no orçamento diário", exc_info=True)

    def esgotado(self) -> bool:
        with self._trava:
            self._virar_o_dia()
            return self._gasto >= self._limite

    def gasto_hoje(self) -> float:
        with self._trava:
            self._virar_o_dia()
            return self._gasto

    def acabou_de_esgotar(self) -> bool:
        """`True` uma única vez por dia, na primeira checagem depois de esgotar: o agendador usa
        isto para avisar o dono sem repetir."""
        with self._trava:
            self._virar_o_dia()
            if self._gasto >= self._limite and not self._esgotou_avisado:
                self._esgotou_avisado = True
                return True
            return False

    @property
    def limite_usd(self) -> float:
        return self._limite

    def gravar(self) -> None:
        """Força a gravação do que ainda está em memória (shutdown)."""
        with self._trava:
            self._gravar()

    # -- internos (sempre com a trava) --------------------------------------------------------

    def _hoje(self) -> date:
        return self._agora().astimezone(self._fuso).date()

    def _virar_o_dia(self) -> None:
        hoje = self._hoje()
        if self._dia == hoje:
            return
        if self._dia is not None:
            self._gravar()  # fecha o dia que acabou
        self._dia = hoje
        self._gasto = self._banco.obter_uso_do_dia(hoje)
        self._pendente = 0.0
        self._esgotou_avisado = self._gasto >= self._limite  # já esgotado antes do restart

    def _gravar_se_for_hora(self) -> None:
        if self._agora() - self._ultima_gravacao >= INTERVALO_DE_GRAVACAO:
            self._gravar()

    def _gravar(self) -> None:
        if self._pendente > 0 and self._dia is not None:
            self._banco.somar_uso_do_dia(self._dia, self._pendente)
            self._pendente = 0.0
        self._ultima_gravacao = self._agora()


def avisar_esgotado(orcamento: Orcamento) -> None:
    registrar_evento(
        logger,
        "orcamento_esgotado",
        n=round(orcamento.gasto_hoje() * 100),  # centavos de dólar gastos hoje
        total=round(orcamento.limite_usd * 100),
        nivel=logging.WARNING,
    )
