"""Handler de logging para o Cloud Logging (M27, ADR-0028, seção 12 da spec).

Isolado num módulo próprio (como `services/storage.py`/`services/tts.py` fazem com outros
clientes do GCP): o `Client` da lib `google-cloud-logging` não tem o `__init__` tipado, e aqui é
o único lugar do projeto que precisa afrouxar essa checagem (ver override em `pyproject.toml`).
"""

from __future__ import annotations

import logging

from google.cloud import logging as cloud_logging


def criar_handler_da_nuvem(projeto: str) -> logging.Handler:
    """`BackgroundThreadTransport` (padrão da lib): não bloqueia quem chama esperando rede."""
    cliente = cloud_logging.Client(project=projeto)
    return cloud_logging.handlers.CloudLoggingHandler(cliente, name="stick-word-group")
