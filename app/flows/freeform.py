"""Roteamento de texto livre (M9, ADR-0009): uma única chamada de IA que já classifica a
intenção do aluno e devolve a resposta (frase para avaliar, pedido de exemplos/sinônimos,
"salvar", palavra nova, pedido de ajuda ou fora do escopo)."""

from __future__ import annotations

from app import messages
from app.domain.models import Profile, Sessao
from app.flows import capture, practice, synonyms
from app.flows.base import Deps, bloq
from app.flows.practice import entrada_atual

_MIN_QUANTIDADE = 1
_MAX_QUANTIDADE = 10


def _quantidade(n: int) -> int:
    return max(_MIN_QUANTIDADE, min(_MAX_QUANTIDADE, n))


async def _nova_palavra(d: Deps, sessao: Sessao, perfil: Profile, texto: str) -> Sessao:
    # M37: no grupo isto só é alcançado por uma marcação ao bot (ou por `!texto` numa atividade),
    # então a palavra nova é salva como no privado.
    await practice.concluir(d, sessao, perfil)
    return await capture.explicar(d, perfil, texto)


async def palavra_com_contexto(d: Deps, sessao: Sessao, perfil: Profile, texto: str) -> Sessao:
    """`palavra | frase ou sentido` com uma palavra aberta (M31, ADR-0030), sem passar pela IA de
    roteamento: a mesma palavra pede outro sentido; outra palavra é uma palavra nova."""
    if await capture.eh_a_palavra_aberta(d, sessao, texto):
        return await capture.trocar_sentido(d, sessao, perfil, texto)
    return await _nova_palavra(d, sessao, perfil, texto)


async def rotear(d: Deps, sessao: Sessao, perfil: Profile, texto: str) -> Sessao:
    entrada = await entrada_atual(d, sessao)
    async with d.conversa.digitando():
        roteamento = await bloq(
            d.tutor.route, entrada.palavra, entrada.sentido, texto, perfil.nivel
        )

    match roteamento.intencao:
        case "frase":
            return await practice.avaliar_frase(d, sessao, texto, roteamento.como_avaliacao())
        case "exemplos":
            return await practice.gerar_exemplos(
                d, sessao, perfil, _quantidade(roteamento.quantidade)
            )
        case "sinonimos":
            return await synonyms.gerar(d, sessao, perfil, _quantidade(roteamento.quantidade))
        case "salvar":
            return await practice.concluir(d, sessao, perfil)
        case "nova_palavra":
            return await _nova_palavra(d, sessao, perfil, roteamento.palavra)
        case "pedido" | "fora_do_escopo":
            await d.conversa.enviar(
                messages.resposta_livre(
                    roteamento.resposta,
                    entrada.palavra,
                    ja_viu_sinonimos=bool(sessao.sinonimos_mostrados),
                )
            )
            return sessao
        case _:  # inalcançável: `Intencao` só tem os 7 valores acima (garantia para o mypy)
            raise AssertionError(f"intenção desconhecida: {roteamento.intencao!r}")
