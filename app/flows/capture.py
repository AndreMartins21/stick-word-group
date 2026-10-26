"""Captura: o aluno manda uma palavra, o bot explica e já mostra o card com o menu único (M9).

Desde o M9 a IA sempre escolhe um sentido (`sentido_do_contexto` nunca fica `null`), então não há
mais uma pergunta separada de "qual sentido" — o card já sai pronto numa mensagem só. Desde o M25
(ADR-0026) a pronúncia em áudio vai junto, automática, sem precisar de opção no menu.
"""

from __future__ import annotations

from app import messages
from app.domain.choices import separar_contexto
from app.domain.models import (
    Entry,
    Estado,
    Explanation,
    Profile,
    Sense,
    Sentence,
    SentidoSalvo,
    Sessao,
    slugify,
)
from app.flows import pronuncia
from app.flows.base import Deps, bloq
from app.repo.base import EntradaJaExiste, resolver_slug


async def explicar(
    d: Deps,
    perfil: Profile,
    texto: str,
    entrada_existente: Entry | None = None,
    *,
    substituir: Entry | None = None,
) -> Sessao:
    """Explica `texto`. Com `entrada_existente` (expansões, /praticar), atualiza aquela entrada
    em vez de criar outra. Com `substituir` (M31), apaga aquela entrada, mas só depois que a IA
    respondeu com sucesso: uma falha da IA não perde o card."""
    palavras_do_aluno = [e.palavra for e in await bloq(d.repo.listar_entradas)]
    async with d.conversa.digitando():
        explicacao = await bloq(d.tutor.explain, texto, perfil.nivel, palavras_do_aluno)

    if not explicacao.ok:
        await d.conversa.enviar(messages.entrada_invalida(explicacao.motivo_erro))
        return d.sessao_vazia()

    if substituir is not None:
        await bloq(d.repo.apagar_entrada, substituir.slug)
    sentido_id = explicacao.sentido_do_contexto or explicacao.sentidos[0].id
    sentido = next(s for s in explicacao.sentidos if s.id == sentido_id)
    pediu_sentido = separar_contexto(texto)[1] is not None
    return await _comecar_pratica(d, explicacao, sentido, entrada_existente, pediu_sentido)


async def eh_a_palavra_aberta(d: Deps, sessao: Sessao, texto: str) -> bool:
    """`texto` (`palavra | sentido`) fala da palavra que está aberta na sessão?"""
    if not sessao.entry_id:
        return False
    atual = await bloq(d.repo.obter_entrada, sessao.entry_id)
    termo = separar_contexto(texto)[0]
    return atual is not None and slugify(termo) == slugify(atual.palavra)


async def trocar_sentido(d: Deps, sessao: Sessao, perfil: Profile, texto: str) -> Sessao:
    """`palavra | sentido` sobre a palavra aberta (M31, ADR-0030). Se o card acabou de ser criado
    e o aluno ainda não escreveu frase nele, o novo sentido o substitui; senão vira outro card."""
    atual = await bloq(d.repo.obter_entrada, sessao.entry_id) if sessao.entry_id else None
    if atual is not None and sessao.entrada_criada_agora:
        frases = await bloq(d.repo.listar_frases, atual.slug)
        if not any(f.autor == "usuario" for f in frases):
            return await explicar(d, perfil, texto, substituir=atual)
    return await explicar(d, perfil, texto)


async def _comecar_pratica(
    d: Deps,
    explicacao: Explanation,
    sentido: Sense,
    existente: Entry | None,
    pediu_sentido: bool = False,
) -> Sessao:
    entrada, criada_agora = await bloq(
        gravar_entrada, d, explicacao, sentido, existente, pediu_sentido=pediu_sentido
    )
    if existente is None and not criada_agora:
        return await _avisar_que_ja_existe(d, entrada, sentido)
    await bloq(
        d.repo.adicionar_frase,
        entrada.slug,
        Sentence(texto=sentido.exemplo, autor="bot", criado_em=d.agora()),
    )
    await d.conversa.enviar(
        messages.explicacao(
            entrada.palavra,
            entrada.classe,
            entrada.cefr_estimado,
            sentido,
            entrada.nota,
            sentido.exemplo,
            outros_sentidos=[s for s in explicacao.sentidos if s.id != sentido.id],
            pt=d.pt,
        )
    )
    await pronuncia.ouvir(d, entrada, anunciar=False)  # M25: áudio automático, sem opção no menu
    return d.sessao_vazia().model_copy(
        update={
            "estado": Estado.AWAIT_ACTION,
            "entry_id": entrada.slug,
            "sentido_id": sentido.id,
            "entrada_criada_agora": criada_agora,
        }
    )


async def _avisar_que_ja_existe(d: Deps, entrada: Entry, sentido: Sense) -> Sessao:
    """A palavra já estava na lista: mostra o que o aluno tem (o sentido e o exemplo salvos, não os
    da explicação nova) e segue na mesma palavra, para praticar, sem regravar nada."""
    frases = await bloq(d.repo.listar_frases, entrada.slug)
    exemplo = next((f.texto for f in frases if f.autor == "bot"), sentido.exemplo)
    await d.conversa.enviar(
        messages.ja_existe(
            entrada.palavra,
            entrada.classe,
            entrada.cefr_estimado,
            entrada.sentido,
            exemplo,
            outros_sentidos=entrada.outros_sentidos,
            p=d.p,
            pt=d.pt,
        )
    )
    await pronuncia.ouvir(d, entrada, anunciar=False)  # M25: áudio automático, sem opção no menu
    return d.sessao_vazia().model_copy(
        update={
            "estado": Estado.AWAIT_ACTION,
            "entry_id": entrada.slug,
            "sentido_id": sentido.id,
        }
    )


def _entradas_da_palavra(entradas: list[Entry], palavra: str) -> list[Entry]:
    """Os sentidos salvos da palavra (`stall`, `stall--s2`...), o de slug-base primeiro."""
    base = slugify(palavra)
    dela = [e for e in entradas if e.slug == base or e.slug.startswith(f"{base}--s")]
    return sorted(dela, key=lambda e: e.slug != base)


def gravar_entrada(
    d: Deps,
    explicacao: Explanation,
    sentido: Sense,
    existente: Entry | None,
    *,
    pediu_sentido: bool = False,
) -> tuple[Entry, bool]:
    """A entrada gravada e se foi criada agora (`False`: já existia, ou é a atualização de uma)."""
    agora = d.agora()
    escolhido = SentidoSalvo(traducao=sentido.traducao, definicao=sentido.definicao)
    outros = [
        SentidoSalvo(traducao=s.traducao, definicao=s.definicao)
        for s in explicacao.sentidos
        if s.id != sentido.id
    ]
    if existente is not None:
        # Uma expansão é uma expressão ("mitigate risk"): a IA a explica pela forma base ("mitigate"),
        # mas o cartão continua sendo da expressão que o aluno escolheu, com a classe da sugestão.
        da_expansao = existente.origem == "expansao"
        atualizada = existente.model_copy(
            update={
                "palavra": existente.palavra if da_expansao else explicacao.palavra,
                "classe": existente.classe if da_expansao else explicacao.classe,
                "cefr_estimado": explicacao.cefr_estimado,
                "sentido": escolhido,
                "outros_sentidos": outros,
                "nota": explicacao.nota,
                "tags": explicacao.tags,
                "atualizado_em": agora,
            }
        )
        d.repo.salvar_entrada(atualizada)
        return atualizada, False

    if explicacao.frase_contexto is None and not pediu_sentido:
        # Palavra sozinha, sem frase: não há um sentido escolhido pelo aluno, só o "mais comum" que
        # a IA sorteia a cada chamada. Quem já tem a palavra tem a palavra, qualquer que seja o
        # sentido salvo; só uma frase de contexto (ou um sentido pedido, M31) abre outro sentido.
        da_palavra = _entradas_da_palavra(d.repo.listar_entradas(), explicacao.palavra)
        if da_palavra:
            return da_palavra[0], False

    slug = resolver_slug(d.repo, explicacao.palavra, escolhido.traducao)
    ja_salva = d.repo.obter_entrada(slug)
    if ja_salva is not None:  # o aluno voltou a uma palavra que já tem: mantém as frases dela
        return ja_salva, False

    entrada = Entry(
        slug=slug,
        palavra=explicacao.palavra,
        classe=explicacao.classe,
        cefr_estimado=explicacao.cefr_estimado,
        sentido=escolhido,
        outros_sentidos=outros,
        nota=explicacao.nota,
        tags=explicacao.tags,
        origem_texto=explicacao.frase_contexto,
        autor_id=d.autor_id,  # M28: quem salvou
        criado_em=agora,
        atualizado_em=agora,
    )
    try:
        d.repo.criar_entrada(entrada)
    except EntradaJaExiste:
        return d.repo.obter_entrada(slug) or entrada, False
    return entrada, True
