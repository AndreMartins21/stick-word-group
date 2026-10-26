"""SimTutor: respostas de IA fabricadas, para o simulador rodar o ciclo sem rede nem credencial.

Não avalia inglês de verdade — só o bastante para percorrer o fluxo (M9). Use `--real-llm` para
conversar com o Gemini.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.choices import contem_palavra_alvo, marcar_alvo
from app.domain.models import (
    AvaliacaoDaPergunta,
    Evaluation,
    Expansion,
    Explanation,
    NivelUsuario,
    PerguntaSemanal,
    Revisao,
    Roteamento,
    Sense,
    SentidoSalvo,
    Synonym,
)

_NOTA_DO_SIMULADOR = "Simulated response — use --real-llm for real feedback."


class SimTutor:
    def explain(
        self, texto: str, nivel: NivelUsuario, palavras_do_aluno: Sequence[str] = ()
    ) -> Explanation:
        palavra_bruta, _, frase = texto.partition("|")
        palavra = palavra_bruta.strip().lower()
        if not palavra:
            return Explanation(ok=False, motivo_erro="Send me a word in English.")

        frase = frase.strip()
        if palavra == "stall":
            sentidos = [
                Sense(
                    id="s1",
                    traducao="travar, emperrar",
                    definicao="to stop making progress",
                    exemplo="The [[talks]] stalled last week.",
                ),
                Sense(
                    id="s2",
                    traducao="enrolar",
                    definicao="to delay on purpose",
                    exemplo="Stop [[stalling]] and answer me.",
                ),
            ]
        else:
            sentidos = [
                Sense(
                    id="s1",
                    traducao=f"significado de {palavra} (simulado)",
                    definicao=f"the meaning of {palavra}",
                    exemplo=f"This is an example with [[{palavra}]].",
                )
            ]
        return Explanation(
            ok=True,
            palavra=palavra,
            classe="verb",
            cefr_estimado="B2",
            sentidos=sentidos,
            sentido_do_contexto=sentidos[0].id,
            frase_contexto=(marcar_alvo(frase, palavra) or frase) if frase else None,
            nota=_NOTA_DO_SIMULADOR,
            tags=["trabalho"],
        )

    def evaluate(
        self, palavra: str, sentido: SentidoSalvo | Sense, frase: str, nivel: NivelUsuario
    ) -> Evaluation:
        usa = contem_palavra_alvo(frase, palavra)
        return Evaluation(
            usa_palavra_alvo=usa,
            sentido_correto=usa,
            veredito="correta" if usa else "incorreta",
            correcoes=[],
            versao_natural=marcar_alvo(frase, palavra) or f"[[{palavra}]]",
            explicacao=_NOTA_DO_SIMULADOR,
        )

    def examples(
        self,
        palavra: str,
        sentido: SentidoSalvo | Sense,
        nivel: NivelUsuario,
        n: int = 3,
        ja_mostrados: Sequence[str] = (),
        palavras_do_aluno: Sequence[str] = (),
    ) -> list[str]:
        modelos = [
            "We had to [[{p}]] before the deadline.",
            "She didn't want to [[{p}]] in front of the client.",
            "It's easy to [[{p}]] when nobody is watching.",
            "They tend to [[{p}]] every Monday.",
            "I try not to [[{p}]] during meetings.",
            "He might [[{p}]] if we push too hard.",
            "We rarely [[{p}]] on short projects.",
            "Could you [[{p}]] for a moment?",
            "It's normal to [[{p}]] under pressure.",
            "Let's not [[{p}]] this time.",
        ]
        return [modelo.format(p=palavra) for modelo in modelos[:n]]

    def expansions(
        self,
        palavra: str,
        sentido: SentidoSalvo | Sense,
        nivel: NivelUsuario,
        ja_existentes: Sequence[str],
    ) -> list[Expansion]:
        candidatas = [
            Expansion(expressao=f"{palavra} for time", traducao="ganhar tempo", tipo="colocacao"),
            Expansion(expressao=f"{palavra} out", traducao="parar de vez", tipo="phrasal_verb"),
            Expansion(expressao=f"a big {palavra}", traducao="um grande exemplo", tipo="colocacao"),
            Expansion(expressao=f"{palavra} again", traducao="de novo", tipo="expressao"),
        ]
        existentes = {e.lower() for e in ja_existentes}
        return [c for c in candidatas if c.expressao.lower() not in existentes]

    def synonyms(
        self,
        palavra: str,
        sentido: SentidoSalvo | Sense,
        nivel: NivelUsuario,
        n: int = 3,
        ja_mostrados: Sequence[str] = (),
    ) -> list[Synonym]:
        candidatos = [
            Synonym(
                expressao=f"{palavra}-synonym-{i}",
                significado=f"similar to {palavra}",
                exemplo=f"This is like [[{palavra}-synonym-{i}]].",
            )
            for i in range(1, 6)
        ]
        vistos = {v.lower() for v in ja_mostrados}
        disponiveis = [c for c in candidatos if c.expressao.lower() not in vistos]
        return disponiveis[:n]

    def route(
        self, palavra: str, sentido: SentidoSalvo | Sense, texto: str, nivel: NivelUsuario
    ) -> Roteamento:
        normalizado = texto.strip().lower()
        if normalizado in {"see more examples", "examples"}:
            return Roteamento(intencao="exemplos")
        if normalizado in {"check synonyms", "synonyms"}:
            return Roteamento(intencao="sinonimos")
        if normalizado in {"just save", "save"}:
            return Roteamento(intencao="salvar")
        if contem_palavra_alvo(texto, palavra):
            usa = True
            return Roteamento(
                intencao="frase",
                usa_palavra_alvo=usa,
                sentido_correto=usa,
                veredito="correta",
                correcoes=[],
                versao_natural=marcar_alvo(texto, palavra) or f"[[{palavra}]]",
                explicacao=_NOTA_DO_SIMULADOR,
            )
        if len(normalizado.split()) <= 4:
            return Roteamento(intencao="nova_palavra", palavra=texto.strip())
        return Roteamento(intencao="pedido", resposta=_NOTA_DO_SIMULADOR)

    def review(
        self,
        palavra: str,
        sentido: SentidoSalvo | Sense,
        resposta: str,
        nivel: NivelUsuario,
    ) -> Revisao:
        normalizado = resposta.strip().lower()
        if normalizado in {"", "i don't know", "no idea", "idk"}:
            return Revisao(tipo="nao_sei", qualidade="de_novo", feedback=_NOTA_DO_SIMULADOR)
        if contem_palavra_alvo(resposta, palavra):
            return Revisao(tipo="frase", qualidade="bom", feedback=_NOTA_DO_SIMULADOR)
        return Revisao(tipo="definicao", qualidade="bom", feedback=_NOTA_DO_SIMULADOR)

    def weekly_questions(
        self, vocabulario: Sequence[tuple[str, str]], nivel: NivelUsuario, n: int
    ) -> list[PerguntaSemanal]:
        """Sem IA: uma pergunta fixa por palavra do vocabulário (cíclica), só para percorrer o fluxo."""
        perguntas = []
        for i in range(n):
            palavra, definicao = vocabulario[i % len(vocabulario)]
            perguntas.append(
                PerguntaSemanal(
                    pergunta=f"When did you last use [[{palavra}]] in real life?",
                    palavras=[palavra],
                    explicacao_en=f"It asks about a real moment. {palavra} = {definicao}.",
                    explicacao_pt=f"Pergunta sobre um momento real. ({palavra})"
                    if nivel in {"A1-A2", "A2-B1"}
                    else "",
                )
            )
        return perguntas

    def weekly_answer(
        self, pergunta: str, palavras: Sequence[str], resposta: str, nivel: NivelUsuario
    ) -> AvaliacaoDaPergunta:
        if resposta.strip().lower() in {"", "i don't know", "no idea", "idk"}:
            return AvaliacaoDaPergunta(qualidade="de_novo", feedback=_NOTA_DO_SIMULADOR)
        return AvaliacaoDaPergunta(qualidade="bom", feedback=_NOTA_DO_SIMULADOR)
