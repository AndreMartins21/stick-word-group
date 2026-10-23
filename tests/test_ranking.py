"""M58 (ADR-0056): a lógica pura do ranking — sem banco, sem rede."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from app.domain.models import Membro, Resposta
from app.domain.ranking import Turma, calcular, meses_atras

AGORA = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
ANA, BIA, CAIO, PROF = "5531999998888", "5511988887777", "5521977776666", "5541900000001"


def _r(autor: str, dias_atras: int = 1, *, tipo: str = "diaria", q: str = "bom") -> Resposta:
    return Resposta(
        entry="w",
        autor_id=autor,
        marcado=False,
        qualidade=q,
        tipo=tipo,
        criado_em=AGORA - timedelta(days=dias_atras),
    )


def _turma(nome: str, membros: Mapping[str, str | None], respostas: list[Resposta]) -> Turma:
    return Turma(
        nome=nome,
        membros=[(n, Membro(nome=v, entrou_em=AGORA)) for n, v in membros.items()],
        respostas=respostas,
    )


def _calc(turmas: list[Turma], staff: frozenset[str] = frozenset({PROF})):  # type: ignore[no-untyped-def]
    return calcular(turmas, eh_staff=lambda n: n in staff)


def test_meses_atras_ajusta_o_fim_do_mes() -> None:
    assert meses_atras(datetime(2026, 3, 31, tzinfo=UTC), 1) == datetime(2026, 2, 28, tzinfo=UTC)
    assert meses_atras(AGORA, 6) == datetime(2026, 4, 22, 15, 0, tzinfo=UTC)
    assert meses_atras(AGORA, 12) == datetime(2025, 10, 22, 15, 0, tzinfo=UTC)


def test_alunos_ordenados_por_interacoes_e_desempate_por_dias_ativos() -> None:
    t = _turma(
        "B2 Seg",
        {ANA: "Ana", BIA: "Bia"},
        [_r(ANA, 1), _r(ANA, 1), _r(BIA, 1), _r(BIA, 2)],  # empate em 2; Bia tem 2 dias
    )

    r = _calc([t])

    assert [a.nome for a in r.alunos] == ["Bia", "Ana"]
    assert r.alunos[0].total == 2 and r.alunos[0].dias == 2 and r.alunos[1].dias == 1


def test_conta_daily_e_weekly_separados_e_aceitas_desempatam() -> None:
    t = _turma(
        "T",
        {ANA: "Ana", BIA: "Bia"},
        [
            _r(ANA, 1, tipo="diaria"),
            _r(ANA, 1, tipo="semanal"),
            _r(BIA, 1, tipo="diaria", q="de_novo"),
            _r(BIA, 1, tipo="semanal", q="de_novo"),
        ],
    )

    r = _calc([t])

    ana, bia = r.alunos
    assert (ana.nome, ana.diarias, ana.semanais, ana.aceitas) == ("Ana", 1, 1, 2)
    assert (bia.nome, bia.aceitas) == ("Bia", 0)


def test_staff_fica_fora_de_tudo() -> None:
    t = _turma("T", {ANA: "Ana", PROF: "Prof"}, [_r(ANA), _r(PROF), _r(PROF)])

    r = _calc([t])

    assert [a.nome for a in r.alunos] == ["Ana"]
    assert r.turmas[0].total == 1 and r.turmas[0].alunos == 1


def test_professor_local_do_grupo_tambem_fica_fora() -> None:
    t = Turma(
        nome="T",
        membros=[
            (ANA, Membro(nome="Ana", entrou_em=AGORA)),
            (BIA, Membro(nome="Bia", papel="professor", entrou_em=AGORA)),
        ],
        respostas=[_r(ANA), _r(BIA)],
    )

    r = calcular([t], eh_staff=lambda _n: False)

    assert [a.nome for a in r.alunos] == ["Ana"] and r.turmas[0].alunos == 1


def test_turmas_por_media_por_aluno_matriculado_com_total_e_participacao() -> None:
    grande = _turma(
        "Grande",
        {ANA: "Ana", BIA: "Bia", CAIO: "Caio"},
        [_r(ANA), _r(ANA), _r(ANA), _r(BIA)],  # 4 / 3 alunos
    )
    pequena = _turma("Pequena", {"5531900000009": "Dani", "5531900000008": "Edu"}, [])
    pequena.respostas.extend([_r("5531900000009") for _ in range(3)])  # 3 / 2 alunos

    r = _calc([grande, pequena])

    assert [t.nome for t in r.turmas] == ["Pequena", "Grande"]
    assert r.turmas[0].por_aluno == 1.5 and r.turmas[0].ativos == 1 and r.turmas[0].alunos == 2
    assert r.turmas[1].total == 4 and r.turmas[1].ativos == 2 and r.turmas[1].alunos == 3


def test_aluno_em_duas_turmas_soma_e_lista_as_duas() -> None:
    a = _turma("A", {ANA: "Ana"}, [_r(ANA), _r(ANA)])
    b = _turma("B", {ANA: "Ana", BIA: "Bia"}, [_r(ANA), _r(BIA)])

    r = _calc([a, b])

    ana = next(x for x in r.alunos if x.nome == "Ana")
    assert ana.total == 3 and ana.turmas == ["A", "B"]


def test_top_por_turma_tem_ate_tres_e_turma_sem_resposta_fica_de_fora() -> None:
    membros = {ANA: "Ana", BIA: "Bia", CAIO: "Caio", "5531900000007": "Dani"}
    respostas = [_r(ANA)] * 4 + [_r(BIA)] * 3 + [_r(CAIO)] * 2 + [_r("5531900000007")]
    cheia = _turma("Cheia", membros, respostas)
    vazia = _turma("Vazia", {ANA: "Ana"}, [])

    r = _calc([cheia, vazia])

    assert [nome for nome, _ in r.por_turma] == ["Cheia"]
    assert [a.nome for a in r.por_turma[0][1]] == ["Ana", "Bia", "Caio"]


def test_aluno_leva_o_numero_e_o_nome_salvo_que_pode_faltar() -> None:
    t = _turma("T", {ANA: None, BIA: "Bia"}, [_r(ANA), _r(ANA), _r(BIA)])

    sem_nome, com_nome = _calc([t]).alunos

    assert (sem_nome.numero, sem_nome.nome) == (ANA, "")
    assert (com_nome.numero, com_nome.nome) == (BIA, "Bia")


def test_aluno_em_duas_turmas_fica_com_o_nome_que_alguma_turma_conhece() -> None:
    t1 = _turma("A", {ANA: None}, [_r(ANA)])
    t2 = _turma("B", {ANA: "Ana"}, [_r(ANA)])

    (aluno,) = _calc([t1, t2]).alunos

    assert aluno.nome == "Ana" and aluno.numero == ANA


def test_limites_20_alunos_e_10_turmas() -> None:
    turmas = [
        _turma(f"T{i}", {f"55319000000{i:02d}": f"A{i}"}, [_r(f"55319000000{i:02d}")])
        for i in range(25)
    ]

    r = _calc(turmas)

    assert len(r.alunos) == 20 and len(r.turmas) == 10


def test_sem_nenhuma_interacao_o_ranking_e_vazio() -> None:
    r = _calc([_turma("T", {ANA: "Ana"}, [])])

    assert r.vazio
