"""M57 (ADR-0055): professor global — `!teacher` (só admin do bot ou dono) vale em todos os grupos,
e professores e admins nunca são marcados no desafio semanal."""

from __future__ import annotations

from app import messages
from app.domain.models import Membro
from app.flows import review
from app.flows.base import Autor
from tests.helpers import ANA, BIA, CAIO, DONO_NUMERO, GRUPO, T0, Montagem
from tests.test_semanal import CARLA, _turma

OUTRO_GRUPO = "120363000000000002@g.us"
DONO = Autor(DONO_NUMERO, "Dono")


async def _elegiveis(m: Montagem, grupo: str = GRUPO) -> list[str]:
    alunos = await review.alunos_elegiveis(m.router._deps(grupo), atualizar=False)
    return [numero for numero, _ in alunos]


async def test_teacher_pelo_dono_grava_no_cadastro_global() -> None:
    m = _turma()

    await m.diz_no_grupo(DONO, f"!teacher {ANA.numero}")

    assert m.banco.listar_professores() == [ANA.numero]


async def test_professor_global_nao_e_marcado_em_outro_grupo() -> None:
    m = _turma()
    repo2 = m.banco.do_espaco(OUTRO_GRUPO)
    for aluno in (ANA, BIA):
        repo2.salvar_membro(aluno.numero, Membro(nome=aluno.nome, entrou_em=T0))
    assert sorted(await _elegiveis(m, OUTRO_GRUPO)) == sorted([ANA.numero, BIA.numero])

    await m.diz_no_grupo(DONO, f"!teacher {ANA.numero}")  # promovida no outro grupo

    assert await _elegiveis(m, OUTRO_GRUPO) == [BIA.numero]


async def test_admin_promove_mas_professor_e_aluno_nao() -> None:
    m = _turma(admins=(BIA.numero,))

    (ok,) = await m.diz_no_grupo(BIA, f"!teacher {CAIO.numero}")
    assert ok == messages.papel_alterado("Caio", "professor")

    # Caio, agora professor, não promove ninguém (só admin do bot ou dono)
    resposta = await m.diz_no_grupo(CAIO, f"!teacher {ANA.numero}")
    assert resposta == [messages.ajuda_do_grupo("!")]
    assert await m.diz_no_grupo(ANA, f"!teacher {ANA.numero}") == [messages.ajuda_do_grupo("!")]
    assert m.banco.listar_professores() == [CAIO.numero]


async def test_student_tira_o_professor_de_todos_os_grupos() -> None:
    m = _turma()
    await m.diz_no_grupo(DONO, f"!teacher {ANA.numero}")

    (resposta,) = await m.diz_no_grupo(DONO, f"!student {ANA.numero}")

    assert resposta == messages.papel_alterado("Ana", "aluno")
    assert m.banco.listar_professores() == []
    assert ANA.numero in await _elegiveis(m)


async def test_professor_global_tolera_o_nono_digito() -> None:
    m = _turma()
    m.banco.adicionar_professor("553199998888", por=DONO_NUMERO, agora=T0)  # sem o 9

    assert ANA.numero not in await _elegiveis(m)  # 5531999998888


async def test_admin_do_bot_nao_e_marcado_no_semanal() -> None:
    m = _turma(admins=(BIA.numero,))

    assert BIA.numero not in await _elegiveis(m)
    assert ANA.numero in await _elegiveis(m)


async def test_professor_local_antigo_continua_fora() -> None:
    m = _turma()

    assert CARLA.numero not in await _elegiveis(m)


async def test_professor_global_ainda_pode_mudar_o_nivel() -> None:
    m = _turma()
    await m.diz_no_grupo(DONO, f"!teacher {ANA.numero}")

    (resposta,) = await m.diz_no_grupo(ANA, "!level C2")

    assert "C2" in resposta


async def test_group_mostra_o_professor_global_como_teacher() -> None:
    m = _turma()
    m.banco.adicionar_professor(CAIO.numero, por=DONO_NUMERO, agora=T0)

    (resposta,) = await m.diz_no_grupo(ANA, "!group")

    assert "• Caio (teacher)" in resposta
    assert "• Ana (student)" in resposta


async def test_teacher_repetido_remove_o_professor_de_todos_os_grupos() -> None:
    m = _turma()

    (promovida,) = await m.diz_no_grupo(DONO, f"!teacher {ANA.numero}")
    (rebaixada,) = await m.diz_no_grupo(DONO, f"!teacher {ANA.numero}")

    assert promovida == messages.papel_alterado("Ana", "professor")
    assert rebaixada == messages.papel_alterado("Ana", "aluno")
    assert m.banco.listar_professores() == []
    assert ANA.numero in await _elegiveis(m)
    await m.diz_no_grupo(DONO, f"!teacher {ANA.numero}")  # e de novo promove
    assert m.banco.listar_professores() == [ANA.numero]


async def test_teacher_repetido_tambem_rebaixa_o_professor_so_local() -> None:
    m = _turma()  # Carla é professora só neste grupo (papel antigo)

    (resposta,) = await m.diz_no_grupo(DONO, f"!teacher {CARLA.numero}")

    assert resposta == messages.papel_alterado("Carla", "aluno")
