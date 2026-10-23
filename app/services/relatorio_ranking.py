"""PDF do /ranking (M62, ADR-0060): template Jinja2 + WeasyPrint, sem IA e sem rede."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from app import messages
from app.domain.ranking import Ranking

# Autoescape ligado: nome de aluno e de grupo vem do WhatsApp e não pode virar marcação.
_AMBIENTE = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html", "j2"]),
)


def gerar_pdf_ranking(ranking: Ranking, meses: int, gerado_em: datetime) -> bytes:
    html = _AMBIENTE.get_template("ranking.html.j2").render(
        ranking=ranking,
        t=messages.ranking_pdf_textos(ranking, meses, gerado_em),
    )
    pdf: bytes = HTML(string=html).write_pdf()  # sem stubs: o mypy vê Any
    return pdf
