"""Configuração da aplicação (seção 4 da spec).

Valores não secretos vêm do `.env` local ou do ambiente (compose, VM); segredos
(`WAHA_API_KEY`, `ANTHROPIC_API_KEY`) chegam como env var também, mas nunca são lidos,
pedidos ou impressos por este projeto — em produção, o `.env` é renderizado na VM a partir
do Secret Manager (infra/deploy.sh).
"""

from __future__ import annotations

import re
from typing import Any, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.channel.parser import numero_e_permitido

NivelUsuario = Literal["A1-A2", "A2-B1", "B1-B2", "B2-C1", "C1-C2", "C2"]
ProvedorLLM = Literal["vertex_gemini", "anthropic"]
AmbienteApp = Literal["local", "prod"]
CONTATO_PADRAO = "smartins.bot@gmail.com"
_NUMERICOS = {"max_groups", "limite_por_sessao_grupo", "timeout_marcacao_horas", "max_caracteres"}


class Settings(BaseSettings):
    """Config tipada da aplicação, carregada de variáveis de ambiente / `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Aplicação
    app_env: AmbienteApp = "local"
    log_level: str = "INFO"

    # Usuários / canal (M14, ADR-0017). `ALLOWED_NUMBER` (um só) continua aceito e entra na lista.
    # Listas como texto separado por vírgula (o pydantic-settings leria lista como JSON).
    allowed_number: str = ""
    allowed_numbers: str = ""
    allowed_groups: str = ""
    owner_number: str | None = None  # o dono do bot; padrão = o primeiro número permitido
    # Controle de acesso (M15, ADR-0018): teto de grupos ativados por comando e o contato que o
    # aviso "você não tem um plano" mostra.
    max_groups: int = Field(default=10, ge=0)
    contact_email: str = CONTATO_PADRAO
    # Em grupo o bot só reage a mensagens que começam com isto (M16, ADR-0019). Não pode ser a barra
    # (o prefixo do privado), letra ou número (colidiria com o texto normal).
    group_prefix: str = "!"
    # Revisão em grupo (M17, ADR-0020): palavras por rodada e quanto esperar a pessoa marcada.
    limite_por_sessao_grupo: int = Field(default=5, ge=1)
    timeout_marcacao_horas: float = Field(default=3.0, gt=0)
    # Teto de caracteres de uma mensagem que chega à IA (M40, ADR-0038): acima disso o bot recusa
    # sem chamar o modelo. Nenhuma palavra, frase ou resposta de prática passa de algumas centenas.
    max_caracteres: int = Field(default=500, ge=20)
    bot_number: str
    user_level: NivelUsuario = "B1-B2"
    # Fuso do aluno, para distribuir os lembretes de revisão espaçada (seção 5.7, M10).
    timezone: str = "America/Sao_Paulo"

    # WAHA (gateway WhatsApp)
    waha_url: str = "http://waha:3000"
    waha_session: str = "default"
    waha_api_key: SecretStr
    # Assinatura HMAC dos webhooks (seção 8.1: "se o WAHA suportar, configure e valide" — a
    # doc atual confirma suporte via WHATSAPP_HOOK_HMAC_KEY). Opcional: sem ela, confiamos na
    # rede interna isolada do compose, como a spec permite como alternativa.
    waha_hook_hmac_key: SecretStr | None = None

    # IA
    llm_provider: ProvedorLLM = "vertex_gemini"
    gcp_project_id: str
    vertex_location: str = "global"
    gemini_model: str | None = None
    gemini_model_eval: str | None = None
    # M39 (ADR-0037): modelo da transcrição de áudio; vazio usa o `gemini_model`.
    gemini_model_audio: str | None = None
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-haiku-4-5-20251001"

    # Storage
    export_bucket: str

    # Pronúncia em áudio (M23, ADR-0024): Google Cloud TTS + cache num bucket próprio, permanente.
    # Sem `AUDIO_BUCKET` o bot sobe normalmente e só a opção "Hear how it sounds" avisa que falhou.
    audio_bucket: str | None = None
    tts_voice: str = "en-US-Neural2-F"

    # Letras de música do /song (M13, seção 5.8, ADR-0016): API pública do LRCLIB, sem chave.
    lyrics_url: str = "https://lrclib.net"

    # Snapshot diário de métricas (M28, ADR-0029): sem `METRICS_BUCKET` o bot sobe normalmente e
    # o Agendador simplesmente não roda o snapshot (nenhum destino configurado).
    metrics_bucket: str | None = None

    @field_validator(
        "waha_hook_hmac_key",
        "anthropic_api_key",
        "gemini_model",
        "gemini_model_eval",
        "gemini_model_audio",
        "owner_number",
        "audio_bucket",
        "metrics_bucket",
        mode="before",
    )
    @classmethod
    def _vazio_e_nao_configurado(cls, valor: object) -> object:
        """`CHAVE=` no .env chega como texto vazio; para opcionais isso significa "não definido"."""
        if isinstance(valor, str) and not valor.strip():
            return None
        return valor

    @model_validator(mode="before")
    @classmethod
    def _numerico_vazio_e_nao_configurado(cls, dados: Any) -> Any:
        """`CHAVE=` no .env (o `infra/deploy.sh` grava assim as opcionais sem valor) vale "não
        definido" também para os campos numéricos: sem isto, `int("")` derruba o bot na subida."""
        if not isinstance(dados, dict):
            return dados
        return {
            chave: valor
            for chave, valor in dados.items()
            if not (chave in _NUMERICOS and isinstance(valor, str) and not valor.strip())
        }

    @field_validator("tts_voice", mode="before")
    @classmethod
    def _voz_vazia_usa_a_padrao(cls, valor: object) -> object:
        return "en-US-Neural2-F" if isinstance(valor, str) and not valor.strip() else valor

    @field_validator("group_prefix", mode="before")
    @classmethod
    def _prefixo_vazio_usa_o_padrao(cls, valor: object) -> object:
        return "!" if isinstance(valor, str) and not valor.strip() else valor

    @field_validator("group_prefix")
    @classmethod
    def _prefixo_valido(cls, valor: str) -> str:
        valor = valor.strip()
        if not 1 <= len(valor) <= 2 or valor == "/" or any(c.isalnum() for c in valor):
            raise ValueError("GROUP_PREFIX: 1 ou 2 símbolos, sem letras, números nem a barra")
        return valor

    @field_validator("contact_email", mode="before")
    @classmethod
    def _contato_vazio_usa_o_padrao(cls, valor: object) -> object:
        if isinstance(valor, str) and not valor.strip():
            return CONTATO_PADRAO
        return valor

    @model_validator(mode="after")
    def _ao_menos_um_numero(self) -> Self:
        if not self.numeros_permitidos:
            raise ValueError("defina ALLOWED_NUMBERS (ou ALLOWED_NUMBER) com ao menos um número")
        return self

    @property
    def numeros_permitidos(self) -> list[str]:
        """Só dígitos, sem repetir. O `ALLOWED_NUMBER` legado vem primeiro: ele é o número que já
        usava o bot (o dono), e o dono padrão é o primeiro da lista."""
        vistos: dict[str, None] = {}
        for bruto in (self.allowed_number, *self.allowed_numbers.split(",")):
            digitos = re.sub(r"\D", "", bruto)
            if digitos:
                vistos.setdefault(digitos)
        return list(vistos)

    @property
    def grupos_permitidos(self) -> list[str]:
        return [g.strip() for g in self.allowed_groups.split(",") if g.strip()]

    @property
    def dono(self) -> str:
        return re.sub(r"\D", "", self.owner_number or "") or self.numeros_permitidos[0]

    def eh_dono(self, numero: str) -> bool:
        """Compara aceitando a variação do nono dígito (a conta pode estar registrada sem o 9)."""
        return numero_e_permitido(numero, self.dono)
