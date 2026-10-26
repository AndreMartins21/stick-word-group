"""Testes do simulador de terminal (M6/M9): o ciclo completo, sem WhatsApp nem IA de verdade."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from sim.__main__ import main


def _executar(falas: list[str], tmp_path: Path, *argv: str) -> tuple[int, str]:
    fila: Iterator[str] = iter(falas)
    saida: list[str] = []
    codigo = main(list(argv), entrada=lambda _: next(fila), saida=saida.append, exports=tmp_path)
    return codigo, "\n".join(saida)


def test_fim_da_entrada_encerra_sem_erro(tmp_path: Path) -> None:
    def acabou(_: str) -> str:
        raise EOFError

    codigo = main([], entrada=acabou, saida=lambda _: None, exports=tmp_path)

    assert codigo == 0


def test_real_llm_sem_configuracao_sai_com_erro(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    codigo = main(["--real-llm"], entrada=input, saida=lambda _: None, env={}, exports=tmp_path)

    assert codigo == 2
    assert "GCP_PROJECT_ID" in capsys.readouterr().err


# --- M16: `python -m sim --grupo` --------------------------------------------------------------


def test_ciclo_stall_no_grupo_com_dois_alunos(tmp_path: Path) -> None:
    codigo, tela = _executar(
        [
            "ana: !add stall | the talks stalled",
            "bia: !2",  # see more examples
            "ana: !The negotiations stalled after the first meeting.",
            "bia: !4",  # just save
            "ana: !list",
            "sair",
        ],
        tmp_path,
        "--grupo",
    )

    assert codigo == 0
    assert "*stall* (verb) — B2" in tela
    assert "2️⃣ See more examples" in tela
    assert "📝 *Examples with stall*" in tela
    assert "✅ *Perfect!*" in tela
    assert "✅ Saved: *stall*." in tela
    assert "The class's words" in tela and "1. stall: to stop making progress" in tela


def test_no_grupo_linha_sem_prefixo_e_ignorada_e_nao_chega_ao_bot(tmp_path: Path) -> None:
    _, tela = _executar(
        ["ana: gente, alguém entendeu a aula?", "bia: !help", "sair"], tmp_path, "--grupo"
    )

    assert "(ignorado: não marcou o bot nem usou um comando, o bot não lê)" in tela
    assert tela.count("How I work in this group") == 1  # só o `!help` da Bia foi respondido


def test_no_grupo_linha_fora_do_formato_explica_o_uso(tmp_path: Path) -> None:
    _, tela = _executar(["!add stall", ": !help", "sair"], tmp_path, "--grupo")

    assert tela.count("(use `nome: mensagem`)") == 2


def test_no_grupo_o_dono_promove_um_professor_e_o_group_mostra_os_papeis(tmp_path: Path) -> None:
    _, tela = _executar(
        [
            "bia: !help",
            f"dono: !teacher {'5531990000001'}",
            "ana: !group",
            "sair",
        ],
        tmp_path,
        "--grupo",
        "--professor",
        "carla",
    )

    assert "• carla (teacher)" in tela
    assert "• bia (student)" in tela


# --- M17: revisão em grupo no simulador --------------------------------------------------------


def test_revisao_diaria_em_grupo_nao_marca_ninguem_e_fecha_a_rodada(tmp_path: Path) -> None:
    _, tela = _executar(
        [
            "ana: !add stall | the talks stalled",
            "ana: !4",  # just save: a palavra vira um card da turma
            "carla: !help",  # a professora aparece, mas nunca é marcada
            "ana: !review",
            "ana: !it means to stop making progress",
            "sair",
        ],
        tmp_path,
        "--grupo",
        "--professor",
        "carla",
    )

    assert "Anyone can answer" in tela and "@" not in tela.split("Practice time", 1)[1]
    assert "Practice done" in tela


def test_timeout_no_simulador_fecha_a_rodada_parada_e_skip_com_barra(tmp_path: Path) -> None:
    _, tela = _executar(
        [
            "ana: !add stall",
            "ana: !4",
            "ana: !review",
            "bia: /skip",
            "~daily",
            "~timeout",
            "sair",
        ],
        tmp_path,
        "--grupo",
    )

    assert "Skipping *stall*" in tela
    assert "Nobody replied for a while" in tela or "Practice done" in tela


def test_desafio_semanal_no_simulador_marca_um_aluno_por_pergunta(tmp_path: Path) -> None:
    _, tela = _executar(
        [
            "ana: !add stall",
            "ana: !4",
            "bia: !add deadline",
            "bia: !4",
            "~weekly",
            "ana: /1",
            "ana: !I would call the client",
            "bia: /skip-all",
            "sair",
        ],
        tmp_path,
        "--grupo",
    )

    assert "Weekly challenge" in tela and "Explain the question" in tela
    assert "Weekly challenge done" in tela


def test_no_grupo_marcar_o_bot_com_uma_palavra_a_adiciona(tmp_path: Path) -> None:
    _, tela = _executar(
        ["ana: @bot stall | the talks stalled", "bia: @bot 4", "sair"], tmp_path, "--grupo"
    )

    assert "*stall* (verb) — B2" in tela
    assert "✅ Saved: *stall*." in tela
    assert "(ignorado" not in tela
