"""Simulador de terminal: um grupo de turma inteiro, sem WhatsApp (seção 9, M6/M16).

    python -m sim [--real-llm] [--tts-real] [--nivel B1-B2] [--professor NOME]...

Simula um grupo de turma com vários participantes: cada linha é
`nome: mensagem` (ex.: `ana: @bot stall`). Só chegam ao bot as linhas que marcam o bot (`@bot` em
qualquer lugar da linha) e as que começam com um comando (`!` ou `/`); as outras aparecem como
ignoradas, como no WhatsApp real. O participante `dono` é o dono do
bot (pode usar `!teacher`); `--professor NOME` cadastra professores de saída. Na revisão diária
do grupo (`ana: !review`, ou `~daily` para o bot começar sozinho) ninguém é marcado; `/skip` e
`/skip-all` valem com a barra; `~weekly` começa o desafio semanal (um aluno marcado por
pergunta; `/1`, `/2`, `/3` com barra); `~timeout` fecha a rodada parada sem esperar as 3 horas.

Usa `ConsoleChannel` e `MemoryRepository` (nada é gravado; ao sair, tudo some), e o mesmo
`Router` do bot. Sem `--real-llm`, as respostas de IA são fabricadas (`SimTutor`); com ele, usa o
Gemini com as credenciais locais do Google (`gcloud auth application-default login`), lendo
GCP_PROJECT_ID e GEMINI_MODEL do ambiente (`make sim` carrega o `.env`). A pronúncia grava `.ogg`
em `exports/audio/` e `exports/voz_NNN.ogg`; sem `--tts-real` o áudio é um dublê (não toca).
Digite `sair` para terminar.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import zlib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from app.channel.console import ConsoleChannel
from app.domain.models import Membro, NivelUsuario, agora_utc
from app.flows import grupo as flows_grupo
from app.flows.base import Autor, ConfigGrupo
from app.flows.conversa import Conversa
from app.flows.router import Router
from app.repo.memory import MemoryBanco
from app.services.audio import ServicoAudio
from app.services.fake_tts import FakeSintetizador
from app.services.llm import LLMError, Tutor, tutor_do_ambiente
from app.services.storage import CacheAudioLocal
from app.services.tts import GoogleTts, Sintetizador
from sim.tutor import SimTutor

GRUPO_DO_SIMULADOR = "120363000000000001@g.us"
PREFIXO_DO_SIMULADOR = "!"
VOZ_DO_SIMULADOR = "en-US-Neural2-F"
NOME_DO_DONO = "dono"
_SAIDAS = {"sair", "exit", "quit", ":q"}


async def _sem_espera(_: float) -> None:
    return None


def numero_do_participante(nome: str) -> str:
    """Um número de mentira e estável para cada nome (o simulador não tem WhatsApp)."""
    if nome == NOME_DO_DONO:
        return "5531990000000"
    return "55319" + f"{zlib.crc32(nome.encode()) % 10**8:08d}"


_MARCA_DO_BOT = re.compile(r"@bot\b", re.IGNORECASE)


async def _conversar_no_grupo(
    router: Router,
    entrada: Callable[[str], str],
    saida: Callable[[str], None],
    nomes: dict[str, str],
) -> None:
    saida(
        "Simulador do grupo — uma linha por mensagem: `nome: mensagem` (ex.: `ana: @bot stall`).\n"
        f"Só chega ao bot o que marca `@bot` ou começa com {PREFIXO_DO_SIMULADOR} (ou /). "
        "Digite 'sair' para terminar.\n"
    )
    while True:
        try:
            linha = await asyncio.to_thread(entrada, "grupo> ")
        except EOFError:
            return
        linha = linha.strip()
        if linha.lower() in _SAIDAS:
            return
        if not linha:
            continue
        if linha.lower() in {"~timeout", "timeout"}:
            await router.expirar_marcacao(GRUPO_DO_SIMULADOR, forcar=True)
            continue
        if linha.lower() in {"~weekly", "weekly"}:
            await router.iniciar_semanal(GRUPO_DO_SIMULADOR)
            continue
        if linha.lower() in {"~daily", "daily"}:
            await router.iniciar_revisao(GRUPO_DO_SIMULADOR)
            continue
        nome, separador, texto = linha.partition(":")
        if not separador or not nome.strip() or not texto.strip():
            saida("  (use `nome: mensagem`)")
            continue
        nome, texto = nome.strip(), texto.strip()
        saida(f"[{nome}] {texto}")
        marcado = False
        if flows_grupo.sem_prefixo(texto, PREFIXO_DO_SIMULADOR) is None:
            sem_marca = _MARCA_DO_BOT.sub(" ", texto)
            if sem_marca == texto:
                saida("  (ignorado: não marcou o bot nem usou um comando, o bot não lê)")
                continue
            texto = " ".join(sem_marca.split())
            marcado = flows_grupo.sem_prefixo(texto, PREFIXO_DO_SIMULADOR) is None
        autor = Autor(numero_do_participante(nome), nome)
        nomes[autor.numero] = nome
        await router.processar(texto, GRUPO_DO_SIMULADOR, autor, marcado=marcado)


def main(
    argv: Sequence[str] | None = None,
    *,
    entrada: Callable[[str], str] = input,
    saida: Callable[[str], None] = print,
    env: Mapping[str, str] | None = None,
    exports: Path = Path("exports"),
) -> int:
    parser = argparse.ArgumentParser(prog="python -m sim", description=__doc__)
    parser.add_argument("--real-llm", action="store_true", help="usa o Gemini de verdade")
    parser.add_argument(
        "--provider", choices=["vertex_gemini", "anthropic"], default="vertex_gemini"
    )
    parser.add_argument("--model", help="ID do modelo (com --real-llm)")
    parser.add_argument(
        "--tts-real",
        action="store_true",
        help="fala com o Google Cloud TTS de verdade (precisa de credencial); sem isto, o áudio é um dublê",
    )
    parser.add_argument(
        "--nivel", choices=["A1-A2", "A2-B1", "B1-B2", "B2-C1", "C1-C2", "C2"], default="B1-B2"
    )
    parser.add_argument(
        "--grupo",
        action="store_true",
        help="aceito por compatibilidade: o simulador é sempre um grupo",
    )
    parser.add_argument("--professor", action="append", default=[], help="cadastra um professor")
    parser.add_argument(
        "--atraso", action="store_true", help="mantém a espera de 1-2 s antes de cada resposta"
    )
    args = parser.parse_args(argv)

    tutor: Tutor = SimTutor()
    if args.real_llm:
        try:
            tutor, _ = tutor_do_ambiente(
                args.provider, args.model, os.environ if env is None else env
            )
        except LLMError as erro:
            print(f"erro de configuração: {erro}", file=sys.stderr)
            return 2

    banco = MemoryBanco()
    nomes: dict[str, str] = {}  # número -> nome dos participantes do grupo (para as menções)
    canal = ConsoleChannel(saida, exports, nomes=nomes)

    def criar_conversa(chat_id: str) -> Conversa:
        if args.atraso:
            return Conversa(canal, chat_id)
        return Conversa(canal, chat_id, dormir=_sem_espera)

    nivel: NivelUsuario = args.nivel
    sintetizador: Sintetizador = GoogleTts() if args.tts_real else FakeSintetizador()
    router = Router(
        banco=banco,
        tutor=tutor,
        criar_conversa=criar_conversa,
        nivel_padrao=nivel,
        audio=ServicoAudio(sintetizador, CacheAudioLocal(exports / "audio"), VOZ_DO_SIMULADOR),
        prefixo_do_grupo=PREFIXO_DO_SIMULADOR,
        config_grupo=ConfigGrupo(participantes=canal.group_participants),
        eh_dono=lambda numero: numero == numero_do_participante(NOME_DO_DONO),
    )
    espaco = banco.do_espaco(GRUPO_DO_SIMULADOR)
    for nome in args.professor:
        espaco.salvar_membro(
            numero_do_participante(nome),
            Membro(papel="professor", nome=nome, entrou_em=agora_utc()),
        )
        nomes[numero_do_participante(nome)] = nome
    asyncio.run(_conversar_no_grupo(router, entrada, saida, nomes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
