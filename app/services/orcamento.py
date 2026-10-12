"""Orçamento de IA, o disjuntor global (M46, ADR-0044; teto mensal e cota por grupo no M50,
ADR-0048).

Soma o custo estimado (`services/custo.py`) de cada chamada ao Gemini e diz quando um teto foi
atingido: o **diário** (`ORCAMENTO_DIARIO_USD`), o **mensal** (`ORCAMENTO_MENSAL_USD`) e a **cota
diária de cada grupo** (`COTA_DIARIA_POR_GRUPO_USD`). O gasto do dia (total e por espaço) é espelhado
no Firestore (`uso/{dia}`, em lote, no máximo uma escrita por `INTERVALO_DE_GRAVACAO`) para um
restart não zerar nada; o do mês é a soma dos dias do mês. Chamado de threads (as funções de IA são
síncronas): tudo aqui é protegido por trava."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from app.domain.models import agora_utc
from app.logging_config import registrar_evento
from app.repo.base import Banco

logger = logging.getLogger(__name__)

INTERVALO_DE_GRAVACAO = timedelta(seconds=30)

Pausa = Literal["dia", "mes"]
_PAUSAS: tuple[Pausa, Pausa] = ("mes", "dia")


def chave_do_espaco(espaco: str) -> str:
    """O id do chat como nome de campo do Firestore (`@g.us` tem ponto, que vira separador de
    caminho em alguns clientes)."""
    return espaco.replace(".", "_")


class Orcamento:
    def __init__(
        self,
        banco: Banco,
        limite_usd: float,
        *,
        fuso: ZoneInfo,
        agora: Callable[[], datetime] = agora_utc,
        limite_mensal_usd: float | None = None,
        cota_por_grupo_usd: float | None = None,
    ) -> None:
        self._banco = banco
        self._limite = limite_usd
        self._limite_mensal = limite_mensal_usd
        self._cota_grupo = cota_por_grupo_usd
        self._fuso = fuso
        self._agora = agora
        self._trava = threading.Lock()
        self._dia: date | None = None
        self._gasto = 0.0  # hoje
        self._mes_anterior = 0.0  # dias anteriores do mês corrente
        self._por_espaco: dict[str, float] = {}  # hoje, por chave_do_espaco
        self._pendente = 0.0
        self._pendente_por_espaco: dict[str, float] = {}
        self._ultima_gravacao = agora()
        self._pausa_avisada: set[Pausa] = set()
        self._grupos_avisados: set[str] = set()  # chaves (chave_do_espaco)
        self._grupos_novos: list[str] = []  # ids crus, ainda não avisados ao dono

    # -- API pública -------------------------------------------------------------------------

    def registrar(self, custo_usd: float, espaco: str | None = None) -> None:
        """Soma o custo de uma chamada (qualquer thread), atribuído a `espaco` quando conhecido.
        Nunca levanta: custo é telemetria."""
        if custo_usd <= 0:
            return
        try:
            with self._trava:
                self._virar_o_dia()
                self._gasto += custo_usd
                self._pendente += custo_usd
                if espaco is not None:
                    chave = chave_do_espaco(espaco)
                    self._por_espaco[chave] = self._por_espaco.get(chave, 0.0) + custo_usd
                    self._pendente_por_espaco[chave] = (
                        self._pendente_por_espaco.get(chave, 0.0) + custo_usd
                    )
                    self._conferir_cota(espaco)
                self._gravar_se_for_hora()
        except Exception:  # o disjuntor nunca derruba a chamada de IA
            logger.warning("falha ao registrar o custo no orçamento", exc_info=True)

    def pausa(self) -> Pausa | None:
        """Por que a IA está pausada para todos: o teto do mês (vale até o mês virar) ou o do dia."""
        with self._trava:
            self._virar_o_dia()
            return self._pausa()

    def esgotado(self) -> bool:
        return self.pausa() is not None

    def espaco_esgotado(self, espaco: str) -> bool:
        """A cota diária do grupo acabou (só grupos têm cota; sem `cota_por_grupo_usd`, nunca)."""
        if self._cota_grupo is None or not espaco.endswith("@g.us"):
            return False
        with self._trava:
            self._virar_o_dia()
            return self._por_espaco.get(chave_do_espaco(espaco), 0.0) >= self._cota_grupo

    def gasto_hoje(self) -> float:
        with self._trava:
            self._virar_o_dia()
            return self._gasto

    def gasto_do_mes(self) -> float:
        with self._trava:
            self._virar_o_dia()
            return self._mes_anterior + self._gasto

    def acabou_de_esgotar(self) -> Pausa | None:
        """O motivo, uma única vez por dia (e por motivo), na primeira checagem depois de esgotar:
        o agendador usa isto para avisar o dono sem repetir."""
        with self._trava:
            self._virar_o_dia()
            motivo = self._pausa()
            if motivo is not None and motivo not in self._pausa_avisada:
                self._pausa_avisada.add(motivo)
                return motivo
            return None

    def grupos_recem_esgotados(self) -> list[str]:
        """Os grupos que estouraram a cota desde a última chamada (ids de chat), uma vez por dia."""
        with self._trava:
            novos, self._grupos_novos = self._grupos_novos, []
            return novos

    @property
    def limite_usd(self) -> float:
        return self._limite

    @property
    def limite_mensal_usd(self) -> float | None:
        return self._limite_mensal

    @property
    def cota_por_grupo_usd(self) -> float | None:
        return self._cota_grupo

    def gravar(self) -> None:
        """Força a gravação do que ainda está em memória (shutdown)."""
        with self._trava:
            self._gravar()

    # -- internos (sempre com a trava) --------------------------------------------------------

    def _pausa(self) -> Pausa | None:
        if (
            self._limite_mensal is not None
            and self._mes_anterior + self._gasto >= self._limite_mensal
        ):
            return "mes"
        if self._gasto >= self._limite:
            return "dia"
        return None

    def _conferir_cota(self, espaco: str) -> None:
        if (
            self._cota_grupo is not None
            and espaco.endswith("@g.us")
            and self._por_espaco.get(chave_do_espaco(espaco), 0.0) >= self._cota_grupo
            and chave_do_espaco(espaco) not in self._grupos_avisados
        ):
            self._grupos_avisados.add(chave_do_espaco(espaco))
            self._grupos_novos.append(espaco)

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
        self._por_espaco = self._banco.obter_uso_por_espaco_do_dia(hoje)
        self._mes_anterior = sum(
            self._banco.obter_uso_do_dia(date(hoje.year, hoje.month, d)) for d in range(1, hoje.day)
        )
        self._pendente = 0.0
        self._pendente_por_espaco = {}
        # o que já estava esgotado antes de um restart não é avisado de novo ao dono
        self._pausa_avisada = {p for p in _PAUSAS if self._ja_esgotado(p)}
        self._grupos_avisados = set()
        self._grupos_novos = []
        if self._cota_grupo is not None:
            self._grupos_avisados = {
                chave for chave, v in self._por_espaco.items() if v >= self._cota_grupo
            }

    def _ja_esgotado(self, motivo: Pausa) -> bool:
        if motivo == "mes":
            return (
                self._limite_mensal is not None
                and self._mes_anterior + self._gasto >= self._limite_mensal
            )
        return self._gasto >= self._limite

    def _gravar_se_for_hora(self) -> None:
        if self._agora() - self._ultima_gravacao >= INTERVALO_DE_GRAVACAO:
            self._gravar()

    def _gravar(self) -> None:
        if self._pendente > 0 and self._dia is not None:
            self._banco.somar_uso_do_dia(self._dia, self._pendente, self._pendente_por_espaco)
            self._pendente = 0.0
            self._pendente_por_espaco = {}
        self._ultima_gravacao = self._agora()


def avisar_esgotado(orcamento: Orcamento, motivo: Pausa = "dia") -> None:
    mensal = motivo == "mes"
    registrar_evento(
        logger,
        "orcamento_esgotado",
        motivo=motivo,
        n=round((orcamento.gasto_do_mes() if mensal else orcamento.gasto_hoje()) * 100),
        total=round(
            (orcamento.limite_mensal_usd or 0 if mensal else orcamento.limite_usd) * 100
        ),  # centavos de dólar
        nivel=logging.WARNING,
    )
