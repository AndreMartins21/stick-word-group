"""Agenda da revisão diária do grupo (M35, ADR-0033): o próximo horário (dias úteis por padrão) e o
parser dos argumentos de `!daily`. Funções puras, sem fuso: quem converte é o chamador."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain.lembretes import MAX_TAMANHO_REVISAO, MIN_TAMANHO_REVISAO
from app.domain.models import Profile

_HORA = re.compile(r"^(\d{1,2})(?:h|:)?(\d{2})?$")
_LIGAR = {"on", "yes", "sim", "ligar"}
_DESLIGAR = {"off", "no", "nao", "desligar"}
_FIM_DE_SEMANA = {"weekends", "weekend", "fds"}
_TAMANHO = {"size", "tamanho"}
_AUTO = {"auto", "automatic"}
MAX_REVISOES_SEM_RESPOSTA = 3
MAX_PERGUNTAS = 10  # teto do desafio semanal (M36)
_DIAS: dict[str, int] = {}
for _i, _nomes in enumerate(
    [
        ("mon", "monday", "seg", "segunda"),
        ("tue", "tuesday", "ter", "terca"),
        ("wed", "wednesday", "qua", "quarta"),
        ("thu", "thursday", "qui", "quinta"),
        ("fri", "friday", "sex", "sexta"),
        ("sat", "saturday", "sab", "sabado"),
        ("sun", "sunday", "dom", "domingo"),
    ]
):
    _DIAS.update(dict.fromkeys(_nomes, _i))
NOMES_DOS_DIAS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


# M55 (ADR-0053): cada grupo recebe a diária e o desafio semanal um pouco antes ou depois do horário
# configurado (de -20 a +20 min, fixo por grupo), para os grupos não dispararem todos no mesmo minuto.
JITTER_MINUTOS = 20


def jitter_do_espaco(espaco_id: str, tipo: str) -> timedelta:
    """O deslocamento fixo (de -20 a +20 min, em minutos inteiros) de um grupo para `tipo`
    (`diaria`|`semanal`). Determinístico: o mesmo grupo recebe sempre no mesmo minuto."""
    resumo = hashlib.sha256(f"{tipo}:{espaco_id}".encode()).digest()
    faixa = 2 * JITTER_MINUTOS + 1
    return timedelta(minutes=int.from_bytes(resumo[:4], "big") % faixa - JITTER_MINUTOS)


def _dia_aceito(dia: datetime, fim_de_semana: bool) -> bool:
    return fim_de_semana or dia.weekday() < 5


def proxima_diaria(
    agora_local: datetime,
    hora: int,
    minuto: int,
    fim_de_semana: bool,
    jitter: timedelta = timedelta(0),
) -> datetime:
    """O próximo `hora:minuto` (mais `jitter`) depois de `agora_local`, pulando sábado e domingo
    se `fim_de_semana` é falso. O dia é o do horário configurado, o `jitter` só desloca o minuto."""
    candidato = agora_local.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    while not _dia_aceito(candidato, fim_de_semana) or candidato + jitter <= agora_local:
        candidato += timedelta(days=1)
    return candidato + jitter


def parse_horario(texto: str) -> tuple[int, int] | None:
    """`19h`, `19:30`, `19h30` ou `7` -> (hora, minuto); `None` se inválido."""
    casamento = _HORA.match(texto.strip().lower())
    if not casamento:
        return None
    hora, minuto = int(casamento[1]), int(casamento[2] or 0)
    if not (0 <= hora <= 23 and 0 <= minuto <= 59):
        return None
    return hora, minuto


def parse_diaria(argumento: str) -> dict[str, object] | None:
    """Os campos de `Profile` que `!daily ...` muda, ou `None` se algum pedaço é inválido.

    Aceita, em qualquer ordem e combinados: `on`, `off`, um horário (`19h`, `19:30`),
    `weekends on|off` e `size N|auto` (o tamanho da fila é o `tamanho_revisao` do perfil)."""
    partes = argumento.lower().split()
    if not partes:
        return None
    mudancas: dict[str, object] = {}
    i = 0
    while i < len(partes):
        parte = partes[i]
        if parte in _LIGAR:
            mudancas["diaria_ligada"] = True
        elif parte in _DESLIGAR:
            mudancas["diaria_ligada"] = False
        elif parte in _FIM_DE_SEMANA and i + 1 < len(partes):
            i += 1
            if partes[i] in _LIGAR:
                mudancas["diaria_fim_de_semana"] = True
            elif partes[i] in _DESLIGAR:
                mudancas["diaria_fim_de_semana"] = False
            else:
                return None
        elif parte in _TAMANHO and i + 1 < len(partes):
            i += 1
            if partes[i] in _AUTO:
                mudancas["tamanho_revisao"] = None
            elif (
                partes[i].isdigit() and MIN_TAMANHO_REVISAO <= int(partes[i]) <= MAX_TAMANHO_REVISAO
            ):
                mudancas["tamanho_revisao"] = int(partes[i])
            else:
                return None
        else:
            horario = parse_horario(parte)
            if horario is None:
                return None
            mudancas["diaria_hora"], mudancas["diaria_minuto"] = horario
            mudancas["diaria_ligada"] = True
        i += 1
    return mudancas


def diaria_a_exibir(
    perfil: Profile, agora: datetime, fuso: ZoneInfo, jitter: timedelta = timedelta(0)
) -> datetime | None:
    """Quando a próxima revisão diária toca, no fuso da turma; `None` se está desligada. Usa o
    horário já agendado se ainda é futuro; senão calcula a partir de `agora`."""
    if not perfil.diaria_ligada:
        return None
    if perfil.proxima_diaria is not None and perfil.proxima_diaria > agora:
        return perfil.proxima_diaria.astimezone(fuso)
    return proxima_diaria(
        agora.astimezone(fuso),
        perfil.diaria_hora,
        perfil.diaria_minuto,
        perfil.diaria_fim_de_semana,
        jitter,
    )


def proxima_semanal(
    agora_local: datetime, dia: int, hora: int, minuto: int, jitter: timedelta = timedelta(0)
) -> datetime:
    """O próximo `dia` da semana (0 = segunda) às `hora:minuto` (mais `jitter`), depois de
    `agora_local`."""
    candidato = agora_local.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    candidato += timedelta(days=(dia - candidato.weekday()) % 7)
    if candidato + jitter <= agora_local:
        candidato += timedelta(days=7)
    return candidato + jitter


def parse_semanal(argumento: str) -> dict[str, object] | None:
    """Os campos de `Profile` que `!weekly ...` muda, ou `None` se algum pedaço é inválido.

    Aceita, em qualquer ordem e combinados: `on`, `off`, um dia (`fri`, `friday`, `sex`), um
    horário (`13h`, `13:30`) e `size N|auto` (quantas perguntas; `auto` = uma por aluno)."""
    partes = argumento.lower().split()
    if not partes:
        return None
    mudancas: dict[str, object] = {}
    i = 0
    while i < len(partes):
        parte = partes[i]
        if parte in _LIGAR:
            mudancas["semanal_ligada"] = True
        elif parte in _DESLIGAR:
            mudancas["semanal_ligada"] = False
        elif parte in _DIAS:
            mudancas["semanal_dia"] = _DIAS[parte]
            mudancas["semanal_ligada"] = True
        elif parte in _TAMANHO and i + 1 < len(partes):
            i += 1
            if partes[i] in _AUTO:
                mudancas["semanal_tamanho"] = None
            elif partes[i].isdigit() and 1 <= int(partes[i]) <= MAX_PERGUNTAS:
                mudancas["semanal_tamanho"] = int(partes[i])
            else:
                return None
        else:
            horario = parse_horario(parte)
            if horario is None:
                return None
            mudancas["semanal_hora"], mudancas["semanal_minuto"] = horario
            mudancas["semanal_ligada"] = True
        i += 1
    return mudancas


def semanal_a_exibir(
    perfil: Profile, agora: datetime, fuso: ZoneInfo, jitter: timedelta = timedelta(0)
) -> datetime | None:
    """Quando o próximo desafio semanal toca, no fuso da turma; `None` se está desligado."""
    if not perfil.semanal_ligada:
        return None
    if perfil.proxima_semanal is not None and perfil.proxima_semanal > agora:
        return perfil.proxima_semanal.astimezone(fuso)
    return proxima_semanal(
        agora.astimezone(fuso),
        perfil.semanal_dia,
        perfil.semanal_hora,
        perfil.semanal_minuto,
        jitter,
    )
