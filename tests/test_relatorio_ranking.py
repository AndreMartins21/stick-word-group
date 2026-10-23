"""M62 (ADR-0060): o PDF do /ranking sai de um template Jinja2, sem IA e sem rede."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

from pypdf import PdfReader

from app.domain.ranking import LinhaAluno, LinhaTurma, Ranking
from app.services.relatorio_ranking import gerar_pdf_ranking

AGORA = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def _texto(pdf: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)


def _ranking() -> Ranking:
    ana = LinhaAluno(
        "Ana", "5531999998888", 30, 20, 10, 25, 12, ["Middle-earth, Midnights & Mountains"]
    )
    bia = LinhaAluno("", "5521977776666", 12, 12, 0, 10, 5, ["Turma B"])
    return Ranking(
        alunos=[ana, bia],
        turmas=[
            LinhaTurma("Middle-earth, Midnights & Mountains", 30, 3, 1),
            LinhaTurma("Turma B", 12, 4, 1),
        ],
        por_turma=[("Middle-earth, Midnights & Mountains", [ana]), ("Turma B", [bia])],
    )


def test_pdf_tem_as_tres_secoes_com_nomes_e_numeros() -> None:
    pdf = gerar_pdf_ranking(_ranking(), 6, AGORA)

    assert pdf.startswith(b"%PDF")
    texto = _texto(pdf)
    assert "Last 6 months" in texto
    assert "Top 2 students" in texto and "Top 2 classes" in texto
    assert "Middle-earth, Midnights & Mountains" in texto  # o nome do grupo, não "Group"
    assert "Ana" in texto and "+5531999998888" in texto
    assert "+5521977776666" in texto  # sem nome salvo: aparece o número e um traço no nome
    assert "10.0" in texto  # 30 respostas / 3 alunos matriculados
    assert "1/3" in texto  # participação
    assert "Daily" not in texto and "Weekly" not in texto


def test_nome_com_html_e_escapado_e_nao_vira_marcacao() -> None:
    r = _ranking()
    r.turmas[0] = LinhaTurma("<b>Evil</b> & Co", 30, 3, 1)

    texto = _texto(gerar_pdf_ranking(r, 1, AGORA))

    assert "<b>Evil</b> & Co" in texto
    assert "Last month" in texto
