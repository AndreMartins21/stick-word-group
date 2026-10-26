"""Cache permanente dos áudios de pronúncia (seção 7.4 da spec, ADR-0024): em produção, um bucket
privado do Cloud Storage; em desenvolvimento, uma pasta local ou a memória.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import google.auth
from google.api_core.exceptions import NotFound
from google.cloud.storage import Client as ClienteStorage

_ESCOPO = "https://www.googleapis.com/auth/cloud-platform"


class CacheAudio(Protocol):
    """Guarda o áudio de pronúncia (M23) sem prazo de validade: um objeto por nome."""

    def obter(self, nome: str) -> bytes | None: ...

    def guardar(self, nome: str, conteudo: bytes) -> None: ...

    def uri(self, nome: str) -> str:
        """O link estável do objeto, para gravar no banco (não expira, ao contrário do assinado)."""
        ...


class CacheAudioEmMemoria:
    """Para testes."""

    def __init__(self) -> None:
        self.arquivos: dict[str, bytes] = {}

    def obter(self, nome: str) -> bytes | None:
        return self.arquivos.get(nome)

    def guardar(self, nome: str, conteudo: bytes) -> None:
        self.arquivos[nome] = conteudo

    def uri(self, nome: str) -> str:
        return f"memoria://{nome}"


class CacheAudioLocal:
    """Para o simulador e o desenvolvimento local: arquivos numa pasta."""

    def __init__(self, diretorio: Path) -> None:
        self._diretorio = diretorio

    def obter(self, nome: str) -> bytes | None:
        arquivo = self._diretorio / nome
        return arquivo.read_bytes() if arquivo.is_file() else None

    def guardar(self, nome: str, conteudo: bytes) -> None:
        destino = self._diretorio / nome
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(conteudo)

    def uri(self, nome: str) -> str:
        return (self._diretorio / nome).resolve().as_uri()


class CacheAudioGcs:
    """Bucket próprio, sem regra de expiração (o dos exports apaga tudo em 7 dias)."""

    def __init__(self, *, bucket: Any) -> None:
        self._bucket = bucket

    def obter(self, nome: str) -> bytes | None:
        try:
            conteudo: bytes = self._bucket.blob(nome).download_as_bytes()
        except NotFound:
            return None
        return conteudo

    def guardar(self, nome: str, conteudo: bytes) -> None:
        self._bucket.blob(nome).upload_from_string(conteudo, content_type="audio/ogg")

    def uri(self, nome: str) -> str:
        return f"gs://{self._bucket.name}/{nome}"


def criar_cache_audio_gcs(*, projeto: str, bucket: str) -> CacheAudioGcs:
    credenciais, _ = google.auth.default(scopes=[_ESCOPO])
    cliente = ClienteStorage(project=projeto, credentials=credenciais)
    return CacheAudioGcs(bucket=cliente.bucket(bucket))
