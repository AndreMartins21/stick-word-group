"""M48 (ADR-0046): cache curto das checagens de acesso do `FirestoreBanco`, com um cliente falso
que conta leituras — sem emulador nem rede."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.repo.firestore import FirestoreBanco

AGORA = datetime(2026, 10, 12, tzinfo=UTC)


class _Doc:
    def __init__(self, banco: _Banco, colecao: str, id_: str) -> None:
        self._banco = banco
        self.colecao, self.id = colecao, id_

    def get(self) -> _Doc:
        self._banco.leituras[self.colecao] = self._banco.leituras.get(self.colecao, 0) + 1
        return self

    @property
    def exists(self) -> bool:
        return self.id in self._banco.dados.get(self.colecao, {})

    def to_dict(self) -> dict[str, Any] | None:
        return self._banco.dados.get(self.colecao, {}).get(self.id)

    def set(self, valores: dict[str, Any], merge: bool = False) -> None:
        atual = self._banco.dados.setdefault(self.colecao, {}).setdefault(self.id, {})
        atual.update({k: v for k, v in valores.items() if not k.startswith("__")})

    def create(self, valores: dict[str, Any]) -> None:
        self._banco.dados.setdefault(self.colecao, {})[self.id] = dict(valores)

    def delete(self) -> None:
        self._banco.dados.get(self.colecao, {}).pop(self.id, None)

    def collection(self, nome: str) -> _Colecao:
        return _Colecao(self._banco, f"{self.colecao}/{self.id}/{nome}")


class _Colecao:
    def __init__(self, banco: _Banco, nome: str) -> None:
        self._banco, self._nome = banco, nome

    def document(self, id_: str) -> _Doc:
        return _Doc(self._banco, self._nome, id_)

    def order_by(self, _: str) -> _Colecao:
        return self

    def stream(self) -> list[_Doc]:
        self._banco.leituras[self._nome] = self._banco.leituras.get(self._nome, 0) + 1
        return [_Doc(self._banco, self._nome, i) for i in self._banco.dados.get(self._nome, {})]


class _Banco:
    def __init__(self) -> None:
        self.dados: dict[str, dict[str, dict[str, Any]]] = {}
        self.leituras: dict[str, int] = {}

    def collection(self, nome: str) -> _Colecao:
        return _Colecao(self, nome)


class _Relogio:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _montar() -> tuple[FirestoreBanco, _Banco, _Relogio]:
    falso, relogio = _Banco(), _Relogio()
    return FirestoreBanco(falso, relogio=relogio, validade_do_cache=60.0), falso, relogio  # type: ignore[arg-type]


def test_listar_admins_le_o_banco_uma_vez_por_minuto() -> None:
    banco, falso, relogio = _montar()
    falso.dados["admins"] = {"5511988887777": {}}

    for _ in range(5):
        assert banco.listar_admins() == ["5511988887777"]
    assert falso.leituras["admins"] == 1

    relogio.t = 61
    banco.listar_admins()
    assert falso.leituras["admins"] == 2


def test_adicionar_e_remover_admin_invalidam_o_cache() -> None:
    banco, _, _ = _montar()
    assert banco.listar_admins() == []

    banco.adicionar_admin("5511988887777", por="dono", agora=AGORA)
    assert banco.listar_admins() == ["5511988887777"]

    banco.remover_admin("5511988887777")
    assert banco.listar_admins() == []


def test_grupo_ativo_e_cacheado_e_ativar_desativar_invalidam() -> None:
    banco, falso, _ = _montar()
    grupo = "120363000000000001@g.us"

    assert [banco.grupo_esta_ativo(grupo) for _ in range(4)] == [False] * 4
    assert falso.leituras["espacos"] == 1

    banco.ativar_grupo(grupo, nome="Turma", por="dono", agora=AGORA)
    assert banco.grupo_esta_ativo(grupo) is True

    assert banco.desativar_grupo(grupo) is True
    assert banco.grupo_esta_ativo(grupo) is False


def test_lid_resolvido_fica_em_memoria() -> None:
    banco, falso, _ = _montar()
    falso.dados["lids"] = {"123@lid": {"numero": "5531999998888"}}

    assert banco.obter_numero_do_lid("123@lid") == "5531999998888"
    assert banco.obter_numero_do_lid("123@lid") == "5531999998888"
    assert falso.leituras["lids"] == 1
    assert banco.obter_numero_do_lid("999@lid") is None  # o desconhecido não é cacheado
    assert banco.obter_numero_do_lid("999@lid") is None
    assert falso.leituras["lids"] == 3
