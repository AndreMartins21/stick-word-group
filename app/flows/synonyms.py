"""Sinônimos (M9, Case C): sinônimos da palavra em foco, sem repetir os já mostrados nesta
palavra. A opção 3 do menu único vira "See more synonyms" depois da primeira vez."""

from __future__ import annotations

from app import messages
from app.domain.models import Profile, Sessao
from app.flows.base import Deps, bloq
from app.flows.practice import entrada_atual

NUMERO_DE_SINONIMOS = 3


async def gerar(d: Deps, sessao: Sessao, perfil: Profile, n: int = NUMERO_DE_SINONIMOS) -> Sessao:
    entrada = await entrada_atual(d, sessao)
    async with d.conversa.digitando():
        itens = await bloq(
            d.tutor.synonyms,
            entrada.palavra,
            entrada.sentido,
            perfil.nivel,
            n,
            sessao.sinonimos_mostrados,
        )
    await d.conversa.enviar(messages.sinonimos(entrada.palavra, d.rotulo(entrada.sentido), itens))
    # M12: guarda na entrada (sem repetir por expressão) para o /info e o export.
    ja_salvos = {s.expressao.casefold() for s in entrada.sinonimos}
    novos = [s for s in itens if s.expressao.casefold() not in ja_salvos]
    if novos:
        await bloq(
            d.repo.salvar_entrada,
            entrada.model_copy(
                update={"sinonimos": [*entrada.sinonimos, *novos], "atualizado_em": d.agora()}
            ),
        )
    mostrados = [*sessao.sinonimos_mostrados, *(item.expressao for item in itens)]
    return sessao.model_copy(update={"sinonimos_mostrados": mostrados})
