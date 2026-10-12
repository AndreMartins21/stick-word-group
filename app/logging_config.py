"""Logs estruturados: uma linha JSON por evento, no stdout (o Docker/Cloud Logging coletam).

Sem segredo e sem número de telefone completo nos logs: use `mascarar_numero` e `id_curto`.

Observabilidade (M27, ADR-0028, seção 12 da spec): pontos de negócio importantes (lembrete
enviado, chamada à IA, ativação de grupo...) chamam `registrar_evento`, que grava o campo
`evento` e uma lista branca de campos (`CAMPOS_DE_EVENTO`) — nunca texto do aluno, número
completo ou payload. Em produção, um segundo handler manda os mesmos registros ao Cloud Logging
(`handler_extra`), sem tocar no formato do stdout que `docker compose logs` já lê.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from datetime import UTC, datetime

_LOGGERS_DO_UVICORN = ("uvicorn", "uvicorn.error", "uvicorn.access")

# Lista branca de campos que um evento pode carregar (seção 12 da spec). Qualquer outro atributo
# extra passado via `extra=` a um `logger.*` comum é ignorado pelo formatter — só quem passa por
# `registrar_evento` com um destes nomes aparece no JSON.
CAMPOS_DE_EVENTO = (
    "evento",
    "espaco",
    "tipo_espaco",
    "comando",
    "metodo",
    "modelo",
    "ok",
    "latencia_ms",
    "tokens_entrada",
    "tokens_saida",
    "tokens_thinking",
    "tokens_audio",
    "custo_usd",
    "caracteres",
    "cache",
    "n",
    "total",
    "lapsos",
    "qualidade",
    "marcado",
    "motivo",
    "avisou",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        evento: dict[str, object] = {
            "severity": record.levelname,
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for campo in CAMPOS_DE_EVENTO:
            valor = getattr(record, campo, None)
            if valor is not None:
                evento[campo] = valor
        if record.exc_info:
            evento["exception"] = self.formatException(record.exc_info)
        return json.dumps(evento, ensure_ascii=False)


def configurar_logs(nivel: str = "INFO", *, handler_extra: logging.Handler | None = None) -> None:
    """Idempotente: troca os handlers do logger raiz e faz o uvicorn usar o mesmo formato.

    `handler_extra` (M27): um segundo handler para mandar os mesmos registros à nuvem (o
    `CloudLoggingHandler` da lib `google-cloud-logging`, montado por quem chama — nunca aqui, para
    este módulo continuar sem rede nem credencial nos testes). Leva o mesmo `JsonFormatter`: o
    `CloudLoggingHandler` só produz `jsonPayload` estruturado (campo `evento` etc.) quando a
    mensagem formatada já chega como uma string JSON — sem isto, vira `textPayload` só com a
    mensagem, e os campos extras (`espaco`, `motivo`...) se perdem (visto em produção, M27)."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    if handler_extra is not None:
        handler_extra.setFormatter(JsonFormatter())
    raiz = logging.getLogger()
    raiz.handlers[:] = [handler, *([handler_extra] if handler_extra is not None else [])]
    raiz.setLevel(nivel.upper())
    for nome in _LOGGERS_DO_UVICORN:
        logger = logging.getLogger(nome)
        logger.handlers.clear()
        logger.propagate = True


def registrar_evento(
    logger: logging.Logger, evento: str, *, nivel: int = logging.INFO, **campos: object
) -> None:
    """Emite uma linha estruturada com o campo `evento` (catálogo na seção 12 da spec). Só os
    campos de `CAMPOS_DE_EVENTO` chegam ao JSON — passar qualquer outra chave aqui é um bug (o
    formatter descarta em silêncio, então prefira `CAMPOS_DE_EVENTO` a inventar um nome novo)."""
    logger.log(nivel, evento, extra={"evento": evento, **campos})


def mascarar_numero(numero: str) -> str:
    """`5531999998888` -> `55*******8888`: dá para reconhecer sem expor o número."""
    if len(numero) <= 6:
        return "*" * len(numero)
    return f"{numero[:2]}{'*' * (len(numero) - 6)}{numero[-4:]}"


def id_curto(identificador: str) -> str:
    """O id de mensagem do WhatsApp contém o número; para log, só um resumo estável dele."""
    return hashlib.sha256(identificador.encode()).hexdigest()[:8]
