"""M51 (ADR-0049): toda Action dos workflows é fixada pelo SHA do commit, não por tag mutável."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOWS = sorted((Path(__file__).parent.parent / ".github" / "workflows").glob("*.y*ml"))
_USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)", re.MULTILINE)
_SHA = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def test_ha_workflows() -> None:
    assert WORKFLOWS


@pytest.mark.parametrize("arquivo", WORKFLOWS, ids=lambda p: p.name)
def test_toda_action_remota_usa_sha(arquivo: Path) -> None:
    usos = _USES.findall(arquivo.read_text(encoding="utf-8"))
    remotos = [u for u in usos if not u.startswith("./")]
    assert remotos, "o workflow deveria usar ao menos uma Action"
    assert [u for u in remotos if not _SHA.match(u)] == []
