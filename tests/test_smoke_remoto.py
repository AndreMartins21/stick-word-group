"""O script que o smoke test roda NA VM (`infra/vm/smoke_remoto.sh`) espera o bot e a sessão do WAHA
em vez de falhar na primeira tentativa: depois de um deploy que recria o WAHA, o GOWS demora mais
de 10 s para subir e reinicia algumas vezes ("Connection reset by peer"). Aqui o script roda de
verdade, com `docker`, `curl` e `sleep` falsos no PATH — sem VM, sem rede."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("infra/vm/smoke_remoto.sh").resolve()
CHAVE = "chave-secreta-do-teste"

_DOCKER = """#!/usr/bin/env bash
falhas="$FAKE/bot_falhas"
case "$*" in
  *" exec "*)
    restantes="$(cat "$falhas")"
    if (( restantes > 0 )); then echo $((restantes - 1)) > "$falhas"; exit 1; fi
    echo '{"ok":true}' ;;
  *" ps"*) echo "NAME  STATUS"; echo "stick-word-group-bot-1  Up (healthy)" ;;
esac
"""

_CURL = """#!/usr/bin/env bash
falhas="$FAKE/waha_falhas"
restantes="$(cat "$falhas")"
if (( restantes > 0 )); then echo $((restantes - 1)) > "$falhas"; exit 56; fi
printf '{"name": "default", "status": "%s"}' "$(cat "$FAKE/waha_status")"
"""


def _executavel(caminho: Path, conteudo: str) -> None:
    caminho.write_text(conteudo, encoding="utf-8")
    caminho.chmod(caminho.stat().st_mode | stat.S_IXUSR)


# O prazo do script é em `$SECONDS` (relógio real, inteiro), e o `sleep` aqui é falso. Um prazo de
# 1 s vale de 0 a 1 s reais: numa máquina lenta (o runner do CI) estoura antes das tentativas que o
# teste espera. Por isso quem deve ter sucesso ganha folga (sem custo: sai ao primeiro sucesso), e
# só quem deve desistir usa um prazo curto.
_PRAZO_FOLGADO = 60
_PRAZO_CURTO = 1


def _rodar(
    tmp_path: Path,
    *,
    bot_falhas: int = 0,
    waha_falhas: int = 0,
    status: str = "WORKING",
    espera: int = _PRAZO_FOLGADO,
) -> subprocess.CompletedProcess[str]:
    fake = tmp_path / "fake"
    raiz = tmp_path / "stick-word-group"
    (fake / "bin").mkdir(parents=True)
    (raiz / "app").mkdir(parents=True)
    (raiz / ".env").write_text(f"WAHA_API_KEY={CHAVE}\nOUTRA=x\n", encoding="utf-8")
    (fake / "bot_falhas").write_text(str(bot_falhas))
    (fake / "waha_falhas").write_text(str(waha_falhas))
    (fake / "waha_status").write_text(status)
    _executavel(fake / "bin" / "docker", _DOCKER)
    _executavel(fake / "bin" / "curl", _CURL)
    _executavel(fake / "bin" / "sleep", "#!/usr/bin/env bash\nexit 0\n")  # sem esperar de verdade
    env = {
        **os.environ,
        "PATH": f"{fake / 'bin'}:{os.environ['PATH']}",
        "FAKE": str(fake),
        "STICK_WORD_GROUP_DIR": str(raiz),
        "ESPERA_MAXIMA": str(espera),
    }
    # roda o script FIXO do próprio repositório, com binários falsos: nada de entrada não confiável
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT)],  # noqa: S607
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_bot_e_waha_prontos_de_primeira(tmp_path: Path) -> None:
    resultado = _rodar(tmp_path)

    assert resultado.returncode == 0
    assert "SMOKE_OK" in resultado.stdout
    assert 'bot /health: {"ok":true}' in resultado.stdout
    assert "sessão do WAHA: WORKING" in resultado.stdout


def test_waha_que_recusa_conexao_no_comeco_e_esperado_ate_subir(tmp_path: Path) -> None:
    """A falha real do deploy: `curl: (56) Recv failure: Connection reset by peer`."""
    resultado = _rodar(tmp_path, waha_falhas=3)

    assert resultado.returncode == 0
    assert "SMOKE_OK" in resultado.stdout
    assert resultado.stdout.count("aguardando a sessão do WAHA") == 3


def test_bot_que_ainda_esta_reiniciando_e_esperado(tmp_path: Path) -> None:
    resultado = _rodar(tmp_path, bot_falhas=2)

    assert resultado.returncode == 0 and "SMOKE_OK" in resultado.stdout
    assert resultado.stdout.count("aguardando o bot") == 2


def test_waha_que_nunca_chega_a_working_falha_depois_do_prazo(tmp_path: Path) -> None:
    resultado = _rodar(tmp_path, status="SCAN_QR_CODE", espera=_PRAZO_CURTO)

    assert resultado.returncode != 0
    assert "SMOKE_OK" not in resultado.stdout
    assert "sessão do WAHA: SCAN_QR_CODE" in resultado.stdout


def test_waha_que_nunca_responde_falha_depois_do_prazo(tmp_path: Path) -> None:
    resultado = _rodar(tmp_path, waha_falhas=10**6, espera=_PRAZO_CURTO)

    assert resultado.returncode != 0
    assert "SMOKE_OK" not in resultado.stdout
    assert "sessão do WAHA: indisponível" in resultado.stdout


def test_bot_que_nunca_sobe_falha_depois_do_prazo(tmp_path: Path) -> None:
    resultado = _rodar(tmp_path, bot_falhas=10**6, espera=_PRAZO_CURTO)

    assert resultado.returncode != 0
    assert "SMOKE_OK" not in resultado.stdout


def test_a_chave_do_waha_nunca_aparece_na_saida(tmp_path: Path) -> None:
    for i, kwargs in enumerate(
        ({}, {"waha_falhas": 2}, {"status": "STOPPED", "espera": _PRAZO_CURTO})
    ):
        resultado = _rodar(tmp_path / str(i), **kwargs)  # type: ignore[arg-type]

        assert CHAVE not in resultado.stdout + resultado.stderr


@pytest.mark.parametrize("script", ["infra/smoke_test.sh"])
def test_o_smoke_test_local_envia_o_script_remoto_por_stdin(script: str) -> None:
    fonte = Path(script).read_text(encoding="utf-8")

    assert "vm/smoke_remoto.sh" in fonte
    assert "SMOKE_OK" in fonte  # só o marcador prova que o script remoto chegou ao fim
