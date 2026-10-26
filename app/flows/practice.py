"""Prática (M9): exemplos, gravar uma frase já avaliada (o roteamento livre entrega a avaliação
numa única chamada de IA) e concluir a palavra (Case D)."""

from __future__ import annotations

from datetime import timedelta

from app import messages
from app.domain.models import Entry, Evaluation, Profile, Sentence, Sessao
from app.flows import expansion
from app.flows.base import Deps, bloq

NUMERO_DE_EXEMPLOS = 3


async def entrada_atual(d: Deps, sessao: Sessao) -> Entry:
    entrada = await bloq(d.repo.obter_entrada, sessao.entry_id) if sessao.entry_id else None
    if entrada is None:
        raise RuntimeError("sessão sem entrada em andamento")
    return entrada


async def gerar_exemplos(
    d: Deps, sessao: Sessao, perfil: Profile, n: int = NUMERO_DE_EXEMPLOS
) -> Sessao:
    entrada = await entrada_atual(d, sessao)
    ja_mostrados = [
        f.texto for f in await bloq(d.repo.listar_frases, entrada.slug) if f.autor == "bot"
    ]
    palavras_do_aluno = [e.palavra for e in await bloq(d.repo.listar_entradas)]
    async with d.conversa.digitando():
        frases = await bloq(
            d.tutor.examples,
            entrada.palavra,
            entrada.sentido,
            perfil.nivel,
            n,
            ja_mostrados,
            palavras_do_aluno,
        )

    agora = d.agora()
    for posicao, frase in enumerate(frases):
        # microssegundos distintos: as frases voltam em ordem na listagem
        criada_em = agora + timedelta(microseconds=posicao)
        await bloq(
            d.repo.adicionar_frase,
            entrada.slug,
            Sentence(texto=frase, autor="bot", criado_em=criada_em),
        )
    await d.conversa.enviar(
        messages.exemplos(
            entrada.palavra,
            d.rotulo(entrada.sentido),
            frases,
            ja_viu_sinonimos=bool(sessao.sinonimos_mostrados),
        )
    )
    return sessao


async def avaliar_frase(d: Deps, sessao: Sessao, frase: str, avaliacao: Evaluation) -> Sessao:
    entrada = await entrada_atual(d, sessao)
    agora = d.agora()
    await bloq(
        d.repo.adicionar_frase,
        entrada.slug,
        Sentence(
            texto=frase,
            autor="usuario",
            veredito=avaliacao.veredito,
            correcoes=avaliacao.correcoes,
            versao_natural=avaliacao.versao_natural,
            explicacao=avaliacao.explicacao,
            autor_id=d.autor_id,
            criado_em=agora,
        ),
    )
    # Uma entrada vira "praticada" quando tem ao menos uma frase do usuário avaliada (seção 7.2).
    await bloq(
        d.repo.salvar_entrada,
        entrada.model_copy(update={"status": "praticada", "atualizado_em": agora}),
    )
    await d.conversa.enviar(
        messages.avaliacao(
            avaliacao,
            d.rotulo(entrada.sentido),
            entrada.palavra,
            ja_viu_sinonimos=bool(sessao.sinonimos_mostrados),
        )
    )
    return sessao


async def concluir(d: Deps, sessao: Sessao, perfil: Profile) -> Sessao:
    """Fecha a palavra (Case D): confere o status, sugere expressões relacionadas e volta a IDLE.
    Tudo já está no banco (a entrada e as frases são gravadas conforme o aluno avança)."""
    entrada = await entrada_atual(d, sessao)
    frases = await bloq(d.repo.listar_frases, entrada.slug)
    praticada = any(f.autor == "usuario" and f.veredito is not None for f in frases)
    status = "praticada" if praticada else "nova"
    if status != entrada.status:
        await bloq(
            d.repo.salvar_entrada,
            entrada.model_copy(update={"status": status, "atualizado_em": d.agora()}),
        )
    sugestoes = await expansion.sugestoes(d, entrada, perfil)
    texto = messages.salvo(entrada.palavra, sugestoes, p=d.p)
    await d.conversa.enviar(texto)
    return d.sessao_vazia()


async def pular(d: Deps) -> Sessao:
    """0/skip com uma palavra aberta: nada a decidir sobre ela (já está gravada); só libera o
    caminho para a próxima, sem chamar a IA."""
    await d.conversa.enviar(messages.ENCERRADO)
    return d.sessao_vazia()


async def ignorar(d: Deps, sessao: Sessao) -> Sessao:
    """Opção 5: descarta a palavra que acabou de ser criada. Uma palavra que o aluno já tinha, ou
    em que ele já escreveu uma frase, fica na lista — o que já é dele não some por um número."""
    entrada = await entrada_atual(d, sessao)
    frases = await bloq(d.repo.listar_frases, entrada.slug)
    praticada = any(f.autor == "usuario" for f in frases)
    if sessao.entrada_criada_agora and not praticada:
        await bloq(d.repo.apagar_entrada, entrada.slug)
        await d.conversa.enviar(messages.palavra_descartada(entrada.palavra))
    else:
        await d.conversa.enviar(messages.palavra_mantida(entrada.palavra))
    return d.sessao_vazia()
