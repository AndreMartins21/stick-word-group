"""Todo texto voltado ao usuário fica neste módulo (M9: em inglês — só a linha 🇧🇷, com a
tradução literal, fica em português do Brasil).

Formatação do WhatsApp (`*bold*`, `_italic_`), emojis com moderação e, sempre que possível, um
único texto por resposta: explicação ou avaliação mais o menu (seção 5.5 da spec), ou feedback
mais o próximo card na revisão espaçada (seção 5.7, M10).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import datetime

from app.domain.agenda_grupo import JITTER_MINUTOS, NOMES_DOS_DIAS
from app.domain.models import (
    AvaliacaoDaPergunta,
    Entry,
    Evaluation,
    Expansion,
    NivelUsuario,
    Profile,
    Revisao,
    Sense,
    Sentence,
    SentidoSalvo,
    Synonym,
    Veredito,
    ordem_do_nivel,
)
from app.domain.ranking import Ranking as RankingGeral

MIDIA_NAO_SUPORTADA = "📎 I can only read *text* for now — can you type the word instead? 🙂"
ERRO_INESPERADO = "⚠️ Something went wrong on my end. Try again in a bit?"
ERRO_IA = "🤖 I couldn't reach the AI right now. Try again in a bit?"
ENCERRADO = "Alright! Send me another word whenever you want. 🙂"
SEM_PENDENTES = "No pending words. 🎉"
AUDIO_SEM_FALA = "🎙️ I couldn't hear any words in that audio. Can you try again?"
ERRO_TRANSCRICAO = "🎙️ I couldn't listen to that audio right now. Try again in a bit?"
ERRO_AUDIO = "🔊 I couldn't make the audio right now. Try again in a bit?"


DEVAGAR = "⏳ Easy there! I can't keep up that fast. Let's continue in a minute."
LIMITE_DO_DIA = "⏳ You've reached today's limit of messages for me. Let's continue tomorrow!"
LIMITE_DO_GRUPO = "⏳ This group has reached today's limit of messages for me. Back tomorrow!"
LIMITE_DE_AUDIO = "🎙️ You've used up today's voice-message time with me. Text still works!"


PAUSA_DE_HOJE = "⏸️ I'm taking a break from thinking for today. See you tomorrow!"


PAUSA_DO_MES = "⏸️ I'm taking a break from thinking until next month. See you then!"
PAUSA_DO_GRUPO = "⏸️ This group used up today's thinking budget. Back tomorrow!"


def orcamento_do_dono(limite_usd: float, *, mensal: bool = False) -> str:
    """O aviso ao dono quando o orçamento de IA esgota (M46, ADR-0044; mensal no M50, ADR-0048)."""
    if mensal:
        return (
            f"⏸️ Monthly AI budget reached (US$ {limite_usd:.2f}). I'm pausing AI replies and "
            "reminders until next month. Raise ORCAMENTO_MENSAL_USD if this was expected."
        )
    return (
        f"⏸️ Daily AI budget reached (US$ {limite_usd:.2f}). I'm pausing AI replies and reminders "
        "until tomorrow. Raise ORCAMENTO_DIARIO_USD if this was expected."
    )


def cota_do_grupo_para_o_dono(grupo_id: str, cota_usd: float) -> str:
    """Um grupo estourou a cota diária de IA (M50, ADR-0048): só ele fica pausado até amanhã."""
    return (
        f"⚠️ Group {grupo_id} used its daily AI quota (US$ {cota_usd:.2f}) and is paused until "
        "tomorrow. If that's abuse, deactivate it with !deactivate."
    )


def texto_longo_demais(maximo: int) -> str:
    """Mensagem acima de `MAX_CARACTERES` (M40, ADR-0038): recusada sem chamar a IA."""
    return f"✂️ That message is too long for me (max {maximo} characters). Can you shorten it?"


def audio_grande_demais(segundos: int) -> str:
    """Áudio acima de `MAX_SEGUNDOS_AUDIO` (ou do teto de bytes): recusado sem baixar (M41)."""
    return f"🎙️ That audio is too long for me (max {segundos} seconds). Can you send a shorter one?"


ECO_MAX_CARACTERES = 300


def audio_transcrito(texto: str) -> str:
    """O que o bot ouviu, mostrado como a primeira mensagem antes da resposta (M38). Cortado em
    `ECO_MAX_CARACTERES` (M41): é só para o aluno conferir, não republica um discurso no grupo."""
    if len(texto) > ECO_MAX_CARACTERES:
        texto = texto[:ECO_MAX_CARACTERES].rstrip() + "…"
    return f"🎙️ _{texto}_"


def pagina_invalida(p: str = "/") -> str:
    return f"That page doesn't exist. Use {p}list to see the first one."


def sem_entradas() -> str:
    return (
        "The class doesn't have any saved words yet. Add one by tagging me with a word, like stall."
    )


_MAX_FRASES_NO_INFO = 5
_MAX_EXEMPLOS_NO_INFO = 3
_NUMEROS = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣"}

_CABECALHO_VEREDITO: dict[Veredito, str] = {
    "correta": "✅ *Perfect!*",
    "correta_pouco_natural": "👍 *Correct, but a bit unnatural.*",
    "quase": "⚠️ *Almost there!*",
    "incorreta": "❌ *Not quite.*",
}


def sem_marcas(frase: str) -> str:
    """Tira os [[ ]] que marcam a palavra-alvo — no WhatsApp a frase vai limpa."""
    return frase.replace("[[", "").replace("]]", "")


def _lista_de_opcoes(opcoes: Sequence[str], *, primeira: int = 1) -> str:
    """`primeira` é o número da 1ª opção: o menu depois do áudio começa no 2 e não renumera."""
    numeradas = list(enumerate(opcoes, start=primeira))
    return "\n".join(f"{_NUMEROS[i]} {texto}" for i, texto in numeradas)


# ---- menu único (M9) -------------------------------------------------------------------------


def convite(palavra: str) -> str:
    return f"Now, tag me with a sentence using *{palavra}*, or tag me with a number:"


def menu_acoes(palavra: str, *, ja_viu_sinonimos: bool = False) -> str:
    """O menu único de ações (M9). Desde o M25 (ADR-0026) não tem mais opção 1 (ouvir): o áudio
    virou automático, já mandado junto da explicação — por isso o menu começa no 2, sem renumerar
    o que a turma já decorou."""
    sinonimos = "See more synonyms" if ja_viu_sinonimos else "Check synonyms"
    opcoes = ["See more examples", sinonimos, "Just save", "Don't save"]
    return convite(palavra) + "\n" + _lista_de_opcoes(opcoes, primeira=2)


# ---- respostas dos fluxos ------------------------------------------------------------------


def _titulo(palavra: str, classe: str, cefr: str) -> str:
    return f"*{palavra}* ({classe}) — {cefr}"


def _outros_sentidos(
    palavra: str, outros: Sequence[Sense | SentidoSalvo], pt: bool = True
) -> list[str]:
    """Os outros sentidos da palavra e como pedir um deles: a mesma palavra com `|` e o sentido,
    marcando o bot (M31, M37). Vazio se a palavra tem um só."""
    if not outros:
        return []
    pedido = f"*{palavra} | {outros[0].definicao}*"
    return [
        "",
        *((f"↔️ {o.traducao} — {o.definicao}" if pt else f"↔️ {o.definicao}") for o in outros),
        f"Want another meaning? Tag me with {pedido}",
    ]


def explicacao(
    palavra: str,
    classe: str,
    cefr: str,
    sentido: Sense | SentidoSalvo,
    dica: str,
    exemplo: str,
    *,
    outros_sentidos: Sequence[Sense | SentidoSalvo] = (),
    ja_viu_sinonimos: bool = False,
    pt: bool = True,
) -> str:
    linhas = [_titulo(palavra, classe, cefr)]
    if pt:  # M34: turma de B1-B2 para cima não vê português
        linhas.append(f"🇧🇷 {sentido.traducao}")
    linhas.append(f"📖 {sentido.definicao}")
    if dica:
        linhas.append(f"💡 {dica}")
    if exemplo:
        linhas.append(f'"{sem_marcas(exemplo)}"')
    linhas += _outros_sentidos(palavra, outros_sentidos, pt)
    return "\n".join(linhas) + "\n\n" + menu_acoes(palavra, ja_viu_sinonimos=ja_viu_sinonimos)


def ja_existe(
    palavra: str,
    classe: str,
    cefr: str,
    sentido: Sense | SentidoSalvo,
    exemplo: str,
    *,
    outros_sentidos: Sequence[Sense | SentidoSalvo] = (),
    pt: bool = True,
    p: str = "!",
) -> str:
    """O aluno mandou uma palavra que já está na lista: avisa, mostra o que já tem e oferece só o
    que faz sentido (frase, exemplos, sinônimos) — salvar já não se aplica, e 0/skip abre caminho
    para outra palavra sem passar pela IA. O áudio (M25) já vai junto, automático, sem opção."""
    linhas = [
        f"📌 You already have *{palavra}* in your list.",
        "",
        _titulo(palavra, classe, cefr),
        *([f"🇧🇷 {sentido.traducao}"] if pt else []),
        f"📖 {sentido.definicao}",
    ]
    if exemplo:
        linhas.append(f'"{sem_marcas(exemplo)}"')
    linhas += _outros_sentidos(palavra, outros_sentidos, pt)
    opcoes = ["See more examples", "Check synonyms"]
    return (
        "\n".join(linhas)
        + "\n\n"
        + convite(palavra)
        + "\n"
        + _lista_de_opcoes(opcoes, primeira=2)
        + f"\n\nTo send another word or command, type {p}0 or {p}skip."
    )


def palavra_descartada(palavra: str) -> str:
    return f"🗑️ Ignored *{palavra}*, it's not in your list. Send me another word whenever you want!"


def palavra_mantida(palavra: str) -> str:
    return f"Alright, *{palavra}* stays in your list. Send me another word whenever you want!"


def avaliacao(
    ev: Evaluation,
    traducao_do_sentido: str,
    palavra: str,
    *,
    ja_viu_sinonimos: bool = False,
) -> str:
    cabecalho = _CABECALHO_VEREDITO[ev.veredito]
    if not ev.sentido_correto:
        cabecalho += f" Here the meaning is *{traducao_do_sentido}*."
    elif ev.veredito in ("quase", "correta_pouco_natural"):
        cabecalho += " The meaning is right."
    linhas = [cabecalho]
    linhas += [f"✏️ {correcao}" for correcao in ev.correcoes]
    linhas.append(f"✨ {sem_marcas(ev.versao_natural)}")
    linhas.append(f"💬 {ev.explicacao}")
    corpo = "\n".join(linhas)
    return f"{corpo}\n\nWant to try another sentence?\n" + menu_acoes(
        palavra, ja_viu_sinonimos=ja_viu_sinonimos
    )


def exemplos(
    palavra: str,
    traducao: str,
    frases: Sequence[str],
    *,
    ja_viu_sinonimos: bool = False,
) -> str:
    numeradas = "\n".join(f"{i}. {sem_marcas(f)}" for i, f in enumerate(frases, start=1))
    return (
        f"📝 *Examples with {palavra}* ({traducao})\n{numeradas}\n\n"
        "Want to try a sentence of your own?\n"
        + menu_acoes(palavra, ja_viu_sinonimos=ja_viu_sinonimos)
    )


def sinonimos(palavra: str, traducao: str, itens: Sequence[Synonym]) -> str:
    linhas: list[str] = []
    for s in itens:
        linhas.append(f"*{s.expressao}* = {s.significado}")
        linhas.append(f'_Example: "{sem_marcas(s.exemplo)}"_')
    corpo = "\n".join(linhas)
    return (
        f"🔄 *Synonyms for {palavra}* ({traducao})\n{corpo}\n\n"
        f"Want to try a sentence with *{palavra}*?\n" + menu_acoes(palavra, ja_viu_sinonimos=True)
    )


def salvo(palavra: str, sugestoes: Sequence[Expansion] = (), *, p: str = "/") -> str:
    linhas = [
        f"✅ Saved: *{palavra}*.",
        f"Practice it any time with {p}practice {palavra}, or see everything with {p}list.",
    ]
    if sugestoes:
        itens = ", ".join(f"*{e.expressao}*" for e in sugestoes)
        linhas.append(f"You might like these too: {itens}.")
    linhas.append("Add another one whenever you want: tag me with a word.")  # M37
    return "\n".join(linhas)


def resposta_livre(resposta: str, palavra: str, *, ja_viu_sinonimos: bool = False) -> str:
    return f"{resposta}\n\n" + menu_acoes(palavra, ja_viu_sinonimos=ja_viu_sinonimos)


def entrada_invalida(motivo: str | None) -> str:
    detalhe = f" {motivo}" if motivo else ""
    return f"🤔 That doesn't look like an English word or expression.{detalhe}"


# ---- comandos --------------------------------------------------------------------------------


_MAX_DEFINICAO_NA_LISTA = 70


def _linha_de_entrada(e: Entry, pt: bool = True) -> str:
    if pt:
        return f"{e.palavra}: {e.sentido.traducao}"
    definicao = e.sentido.definicao
    if len(definicao) > _MAX_DEFINICAO_NA_LISTA:  # M34: a definição é mais longa que a tradução
        definicao = definicao[: _MAX_DEFINICAO_NA_LISTA - 1].rstrip() + "…"
    return f"{e.palavra}: {definicao}"


def lista(
    pagina: Sequence[tuple[int, Entry]],
    *,
    total: int,
    numero: int,
    paginas: int,
    p: str = "!",
    pt: bool = True,
) -> str:
    """Uma página da lista da turma, das mais novas para as mais antigas. Cada palavra leva o seu
    número fixo (1 = a mais antiga), o mesmo que `!practice` e `!delete` aceitam."""
    corpo = "\n".join(f"{n}. {_linha_de_entrada(e, pt)}" for n, e in pagina)
    dica = f"{p}practice {pagina[0][0]} to practice one"
    texto = f"📚 *The class's words* ({total}) — newest first\n{corpo}\n\n💡 {dica}"
    if paginas > 1:
        proxima = f" — {p}list {numero + 1} for more" if numero < paginas else ""
        texto += f"\nPage {numero}/{paginas}{proxima}"
    return texto


def pendentes(entradas: Sequence[Entry]) -> str:
    corpo = "\n".join(f"• {e.palavra} — {e.sentido.traducao}" for e in entradas)
    return f"🆕 *Pending* ({len(entradas)})\n{corpo}\n\nUse /practice to start with the oldest one."


def _data_curta(momento: datetime | None) -> str:
    return f"{momento:%Y-%m-%d}" if momento else "—"


def info(entrada: Entry, numero: int, frases: Sequence[Sentence]) -> str:
    """Tudo o que o bot sabe de uma palavra: sentido, nota, revisão, frases do aluno (já
    corrigidas), exemplos do bot e sinônimos."""
    linhas = [
        f"*{numero}. {entrada.palavra}* ({entrada.classe}) — {entrada.cefr_estimado}",
        f"🇧🇷 {entrada.sentido.traducao}",
        f"📖 {entrada.sentido.definicao}",
    ]
    for outro in entrada.outros_sentidos:
        linhas.append(f"↔️ {outro.traducao} — {outro.definicao}")
    if entrada.nota:
        linhas.append(f"💡 {entrada.nota}")
    situacao = "practiced" if entrada.status == "praticada" else "not practiced yet"
    linhas.append(f"📊 {situacao} · next review: {_data_curta(entrada.proxima_revisao)}")

    do_aluno = _sem_repetir(
        sem_marcas(f.versao_natural or f.texto) for f in reversed(frases) if f.autor == "usuario"
    )
    if do_aluno:
        linhas += ["", "✍️ *Your sentences*", *(f"• {f}" for f in do_aluno[:_MAX_FRASES_NO_INFO])]
    do_bot = _sem_repetir(sem_marcas(f.texto) for f in frases if f.autor == "bot")
    if do_bot:
        linhas += ["", "📝 *Examples*", *(f"• {f}" for f in do_bot[:_MAX_EXEMPLOS_NO_INFO])]
    if entrada.sinonimos:
        linhas += ["", "🔄 *Synonyms*"]
        linhas += [f"• *{s.expressao}* = {s.significado}" for s in entrada.sinonimos]
    return "\n".join(linhas)


def _sem_repetir(frases: Iterable[str]) -> list[str]:
    vistas: set[str] = set()
    unicas: list[str] = []
    for frase in frases:
        chave = frase.strip().casefold()
        if chave and chave not in vistas:
            vistas.add(chave)
            unicas.append(frase.strip())
    return unicas


def _quando(momento: datetime, agora: datetime) -> str:
    """ "today at 14:00", "tomorrow at 08:00" ou "Mon 28 Sep at 08:00" (ambos no fuso do aluno)."""
    dias = (momento.date() - agora.astimezone(momento.tzinfo).date()).days
    dia = "today" if dias == 0 else "tomorrow" if dias == 1 else f"{momento:%a %d %b}"
    return f"{dia} at {momento:%H:%M}"


def pronuncia(palavra: str, exemplo: str | None) -> str:
    """O texto que vai junto das notas de voz: o que o aluno está prestes a ouvir."""
    linhas = [f"🔊 *{palavra}*"]
    if exemplo:
        linhas.append(f'"{sem_marcas(exemplo)}"')
    return "\n".join(linhas)


def palavra_nao_encontrada(palavra: str, p: str = "!") -> str:
    return f"I couldn't find \"{palavra}\" in the class's words. Use {p}list to see what there is."


def apagada(palavra: str) -> str:
    return f"🗑️ *{palavra}* deleted."


def nivel_atual(nivel: NivelUsuario, p: str = "/") -> str:
    return f"Your level is *{nivel}*. To change it: {p}level B1-B2 (options: A1-A2, A2-B1, B1-B2, B2-C1, C1-C2, C2)."


def nivel_so_professor(p: str = "!") -> str:
    return f"Only a teacher can change the class's level. To see it, send {p}level."


def nivel_alterado(nivel: NivelUsuario) -> str:
    return f"✅ Level set to *{nivel}*."


def nivel_invalido() -> str:
    return "Invalid level. Use A1-A2, A2-B1, B1-B2, B2-C1, C1-C2 or C2."


def status(sessao_waha: str, total: int, pendentes_: int) -> str:
    return (
        f"*Status*\n📡 WhatsApp (WAHA): {sessao_waha}\n📚 Words: {total}\n🆕 Pending: {pendentes_}"
    )


# ---- revisão espaçada e lembretes (seção 5.7, M10) ---------------------------------------------

SEM_NADA_PARA_REVISAR = "No pending reviews right now. 🎉"


_QUALIDADE_EMOJI: dict[str, str] = {
    "de_novo": "❌",
    "dificil": "🤔",
    "bom": "✅",
    "facil": "🌟",
}


def hora_da_pratica(total: int) -> str:
    palavra = "word" if total == 1 else "words"
    return f"⏰ *Practice time* — {total} {palavra} to review."


def card_de_revisao(indice: int, total: int, palavra: str) -> str:
    """Ninguém é marcado (M35): qualquer um responde, e `skip` pula a palavra."""
    return (
        f"🔁 {indice}/{total} · *{palavra}*\n"
        "Explain it in English in your own words, or write a sentence using it "
        "(tag me to answer).\n\n"
        "_Anyone can answer · tag me with skip for the next word · skipall to stop the review_"
    )


def feedback_de_revisao(rev: Revisao) -> str:
    linhas = [f"{_QUALIDADE_EMOJI[rev.qualidade]} {rev.feedback}"]
    if rev.correcao:
        linhas.append(f"💬 {rev.correcao}")
    return "\n".join(linhas)


def revisao_encerrada(
    feitas: Sequence[str],
    lapsos: Sequence[str],
    *,
    puladas: Sequence[str] = (),
) -> str:
    if not feitas and not puladas:
        return SEM_NADA_PARA_REVISAR
    solidas = [palavra for palavra in feitas if palavra not in lapsos]
    linhas = [f"🎉 *Practice done* — {len(feitas)} reviewed."]
    if solidas:
        linhas.append(f"✅ Solid: {', '.join(solidas)}")
    if lapsos:
        linhas.append(f"🔁 Coming back soon: {', '.join(lapsos)}")
    if puladas:
        linhas.append(f"⏭️ Skipped: {', '.join(puladas)}")
    linhas.append("Add a new word whenever you want: tag me with a word.")  # M37
    return "\n".join(linhas)


# --- Prática com música (M13, seção 5.8) ---

# --- Controle de acesso (M15, ADR-0018) -------------------------------------------------------


def grupo_ativado(p: str = "!") -> str:
    return (
        f"✅ I'm active in this group now. Send {p}help to see what I can do.\n"
        f"_Admins: {p}activate Class name sets the name shown in the ranking._"
    )


GRUPO_ATIVADO = grupo_ativado()


GRUPO_JA_ATIVO = "I'm already active in this group. 🙂"


def grupo_renomeado(nome: str) -> str:
    return f"✅ Got it, this class is now called *{nome}*."


GRUPO_DESATIVADO = "OK, I'll stay quiet in this group from now on. Your words are still saved."


def grupo_limite(maximo: int) -> str:
    return (
        f"I can be active in up to {maximo} groups at a time, and that limit is reached. "
        "Turn one off first (/groups in a private chat)."
    )


ADMIN_USO = "Use /admin add 5531999998888 or /admin remove 5531999998888 (digits only, with country and area code)."
ADMIN_JA_E_ADMIN = "That number is already an admin."
ADMIN_NAO_E_ADMIN = "That number isn't an admin."
ADMIN_E_O_DONO = "That's the owner — the owner is always an admin."


def admin_adicionado(p: str = "!") -> str:
    return f"✅ Added as an admin. They can activate me in a group with {p}activate."


ADMIN_ADICIONADO = admin_adicionado()


ADMIN_REMOVIDO = "✅ Removed. Groups they already activated stay active."


def admin_lista(numeros: Sequence[str]) -> str:
    linhas = [f"👑 *Admins* ({len(numeros) + 1})", "• you (owner)"]
    linhas += [f"• {n}" for n in numeros]
    linhas.append("Add one with /admin add 5531999998888.")
    return "\n".join(linhas)


# --- /ranking (M58, ADR-0056) -------------------------------------------------------------------

RANKING_USO = "Use /ranking for the last 6 months, or /ranking 3 for the last 3 months (1 to 24)."


def _periodo(meses: int) -> str:
    return "last month" if meses == 1 else f"last {meses} months"


def ranking_vazio(meses: int) -> str:
    return f"📊 No daily or weekly answers in the {_periodo(meses)} yet."


def ranking_legenda(meses: int) -> str:
    return f"📊 Engagement ranking · {_periodo(meses)}"


def ranking_pdf_textos(ranking: RankingGeral, meses: int, gerado_em: datetime) -> dict[str, str]:
    """Os textos fixos do PDF do /ranking (M62, ADR-0060), para o template não ter idioma."""
    return {
        "titulo": "Engagement ranking",
        "periodo": _periodo(meses).capitalize(),
        "gerado": f"Generated on {gerado_em:%Y-%m-%d}",
        "alunos_titulo": f"Top {len(ranking.alunos)} students",
        "col_aluno": "Student",
        "col_numero": "Number",
        "col_turmas": "Class",
        "col_total": "Total",
        "col_dias": "Active days",
        "turmas_titulo": f"Top {len(ranking.turmas)} classes",
        "col_turma": "Class",
        "col_por_aluno": "Per student",
        "col_ativos": "Active",
        "destaques_titulo": "Most engaged in each class",
        "regra": (
            f"How it counts: one answer = one reply a student sent to the daily review or to the "
            f"weekly challenge in the {_periodo(meses)}. Adding words to the vocabulary doesn't "
            "count. Teachers, admins and the owner are left out of every number."
        ),
    }


def ranking_pdf_explicacoes(meses: int) -> dict[str, tuple[str, list[tuple[str, str]]]]:
    """O quadro acima de cada tabela do PDF do /ranking: o que a tabela mostra e cada coluna."""
    periodo = _periodo(meses)
    return {
        "alunos": (
            "The students who answered the most, adding up every class they're in. "
            "Ordered by Total; a tie goes to whoever has more Active days.",
            [
                ("Student", "the name saved on WhatsApp (— if the bot never saw it)."),
                ("Class", "the classes where the student answered."),
                (
                    "Total",
                    f"how many answers the student sent in the {periodo}. "
                    "Example: 25 = 25 replies to the review or the challenge.",
                ),
                (
                    "Active days",
                    "on how many different days the student answered at least once "
                    "(Brazil time). Example: 25 answers in 5 active days = a few big sessions; "
                    "25 in 20 days = a steady habit.",
                ),
            ],
        ),
        "turmas": (
            "The classes compared with each other. Ordered by Per student, not by Total, "
            "so a small class can beat a big one.",
            [
                ("Total", f"all the answers the class's students sent in the {periodo}."),
                (
                    "Per student",
                    "Total divided by the number of students in the class, counting the ones "
                    "who never answered. Example: 120 answers in a class of 10 students = 12.0. "
                    "It's the average effort of the class.",
                ),
                (
                    "Active",
                    "students who answered at least once / students in the class. "
                    "Example: 8/10 = 8 of the 10 students took part; 2 didn't answer at all.",
                ),
            ],
        ),
        "destaques": (
            "The top 3 students inside each class. The last number is how many answers "
            f"the student sent in that class in the {periodo} (their Total there).",
            [],
        ),
    }


PROFESSORES_USO = "Use /teachers 5531999998888 (adds a teacher, or removes one who already is) or /teachers add|remove 5531999998888 (digits only, with country and area code)."
PROFESSOR_JA_E = "That number is already a teacher."
PROFESSOR_NAO_E = "That number isn't a teacher."
PROFESSOR_ADICIONADO = (
    "✅ Added as a teacher in every group. Teachers are never tagged in the weekly challenge."
)
PROFESSOR_REMOVIDO = "✅ Removed. They're a regular student again in every group."


def professores_lista(numeros: Sequence[str]) -> str:
    if not numeros:
        return "🎓 No teachers yet. Add one with /teachers add 5531999998888."
    linhas = [f"🎓 *Teachers* ({len(numeros)})"]
    linhas += [f"• {n}" for n in numeros]
    linhas.append("Add one with /teachers add 5531999998888.")
    return "\n".join(linhas)


GRUPOS_USO = "Use /groups to see the groups, or /groups off 1 to turn one off."
GRUPO_NAO_EXISTE = "There's no active group with that number. Use /groups to see them."


def grupo_desligado(nome: str | None) -> str:
    return f"✅ Turned off: {nome or 'that group'}. Its words are still saved."


_EMOJI_DO_NIVEL = {
    "A1-A2": "🟢",
    "A2-B1": "🟢",
    "B1-B2": "🔵",
    "B2-C1": "🔵",
    "C1-C2": "🟣",
    "C2": "🟣",
}


def _alunos(n: int) -> str:
    return f"{n} student" if n == 1 else f"{n} students"


def grupos(
    ativos: Sequence[tuple[str | None, str | None, int]],
    fixos: Sequence[tuple[str | None, str | None, int]],
    pendentes: Sequence[tuple[str | None, int]],
    maximo: int,
    p: str = "!",
) -> str:
    """`ativos`: (nome, nível, alunos) dos grupos ativados por comando, numerados na ordem dada
    (o chamador já ordena por nível, e `/groups off N` usa a mesma ordem); `fixos`: os de
    ALLOWED_GROUPS; `pendentes`: (nome, horas até eu sair) dos grupos sem !activate. Os ativos
    e fixos aparecem em blocos por nível, do mais básico ao mais avançado."""
    if not ativos and not fixos and not pendentes:
        return f"I'm not in any group yet. Add me to one and send {p}activate there."
    linhas: list[str] = []
    if ativos or fixos:
        linhas.append(f"🏫 *Active groups* ({len(ativos)}/{maximo})")
        itens = [
            (f"{i}.", nome, nivel, alunos, "")
            for i, (nome, nivel, alunos) in enumerate(ativos, start=1)
        ]
        itens += [("•", nome, nivel, alunos, " _(fixed)_") for nome, nivel, alunos in fixos]
        for nivel in sorted({item[2] for item in itens}, key=ordem_do_nivel):
            titulo = (
                f"{_EMOJI_DO_NIVEL[nivel]} *{nivel}*"
                if nivel in _EMOJI_DO_NIVEL
                else "⚪ *No level yet*"
            )
            linhas += ["", titulo]
            linhas += [
                f"{marca} {nome or '(no name)'} — {_alunos(alunos)}{fixo}"
                for marca, nome, nivel_do_item, alunos, fixo in itens
                if nivel_do_item == nivel
            ]
    if pendentes:
        if linhas:
            linhas.append("")
        linhas.append(f"⏳ *Waiting for a {p}activate* (I leave when the time runs out)")
        linhas += [f"• {nome or '(no name)'} — {horas}h left" for nome, horas in pendentes]
    if ativos:
        linhas += ["", "_Turn one off with /groups off 1._"]
    return "\n".join(linhas)


# --- Grupo (M16, ADR-0019) ---------------------------------------------------------------------


def ajuda_do_admin(p: str = "!") -> str:
    """O privado é só dos comandos de admin (ADR-0062): qualquer outro texto do dono ou de um admin
    recebe esta lista, sem IA. Quem não é admin não recebe nada."""
    return (
        f"*Admin commands* 🛠️ (start with / or {p})\n"
        "/groups — active and pending groups (/groups off 1 turns one off)\n"
        "/teachers — the teachers (/teachers 5531999998888 adds or removes one)\n"
        "/ranking [months] — the most engaged students and classes, as a PDF\n"
        "/admin — the bot's admins (owner only)\n\n"
        f"In a group: {p}activate [name] and {p}deactivate. Studying happens in the groups."
    )


def ajuda_do_grupo(p: str = "!") -> str:
    """Só o que vale no grupo: nunca cita os comandos do privado."""
    return (
        "*How I work in this group* 🏫\n"
        "I only read messages that tag me, and the commands below. The rest is your chat, and I "
        "don't read it.\n\n"
        "*Tag me* 💬\n"
        "Tag me with a word or expression to add it (with context: stall | the talks stalled). "
        "While practicing, tag me with an option (2, 3, 4 or 5) or a sentence; in a review, tag me "
        "with your answer, skip for the next word or skipall to stop.\n\n"
        f"*Commands* (start with {p} or /)\n"
        f"{p}list [page] — the class's words, numbered\n"
        f"{p}delete [word or number] — remove a word from the class's list\n"
        f"{p}practice [word or number] — practice one (no word: the oldest pending one)\n"
        f"{p}review — start a review round right now\n"
        f"{p}daily — the daily review, no one tagged (admins: {p}daily 19h, {p}daily off)\n"
        f"{p}weekly — the weekly challenge, one tagged question each (admins: {p}weekly now)\n"
        f"{p}group — the class, its words and reminders\n"
        f"{p}level — the class's level (to change it: {p}level B1-B2)"
    )


def grupo_add_uso(p: str = "!") -> str:
    return (
        f"Tell me which word: {p}add stall — or with the sentence where you saw it: "
        f"{p}add stall | the talks stalled. (Tagging me with the word works too.)"
    )


def grupo_delete_uso(p: str = "!") -> str:
    return f"Tell me which word to remove: {p}delete stall — or its number in {p}list: {p}delete 3."


def so_quem_adicionou_apaga(p: str = "!") -> str:
    return (
        "Only the person who added this word, or the bot's admins, can delete it. "
        f"You can still use {p}add to bring your own."
    )


def papel_alterado(nome: str | None, papel: str) -> str:
    quem = nome or "That person"
    return f"✅ {quem} is now a {'teacher' if papel == 'professor' else 'student'}."


def papel_alterado_admin(nome: str | None) -> str:
    """`!student` em quem é admin do bot: deixa de ser professor, mas admin é staff (M61)."""
    quem = nome or "That person"
    return (
        f"✅ {quem} is no longer a teacher. They are a bot admin, though, so they still skip "
        "the daily and weekly challenges."
    )


def papel_uso(comando: str, p: str = "!") -> str:
    extra = " Repeat it for a teacher to make them a student again." if comando == "teacher" else ""
    return (
        f"Tell me who: {p}{comando} 5531999998888 (digits only, with country and area code)."
        + extra
    )


def grupo_perfil(
    *,
    nivel: str,
    total: int,
    praticadas: int,
    para_revisar: int,
    lembretes: str,
    membros: Sequence[tuple[str, str, int]],
) -> str:
    """`!group`: a turma. `membros` é (nome, papel, respostas na revisão); só nomes, nunca
    telefones, e sem menção (não notifica ninguém)."""
    linhas = [
        "*Your class* 🏫",
        f"🎯 Level: {nivel}",
        f"📚 Words: {total} ({praticadas} practiced, {total - praticadas} pending)",
        f"🔁 Due for review: {para_revisar}",
        f"⏰ Reminders: {lembretes}",
    ]
    if membros:
        linhas.append(f"👥 *Members* ({len(membros)})")
        for nome, papel, respostas in membros:
            rotulo = {"professor": "teacher", "admin": "admin"}.get(papel, "student")
            extra = f" · {respostas} review answers" if respostas else ""
            linhas.append(f"• {nome} ({rotulo}){extra}")
    else:
        linhas.append("👥 Nobody has used me here yet.")
    return "\n".join(linhas)


# --- Revisão em grupo (M17, ADR-0020) ----------------------------------------------------------


def grupo_sem_aluno(p: str = "!") -> str:
    return (
        "I couldn't find anyone to tag for a review. Teachers are never tagged, so I need at "
        f"least one student in the group (they can say {p}help to make sure I know them)."
    )


def feedback_da_diaria(rev: Revisao, nome: str | None) -> str:
    """Resposta aceita na revisão diária: quem acertou e o feedback (sem menção, ninguém é
    notificado)."""
    quem = nome or "Someone"
    return f"👏 *{quem}* answered:\n" + feedback_de_revisao(rev)


def diaria_tente_de_novo(rev: Revisao, nome: str | None, p: str = "!") -> str:
    """Resposta que ainda não está certa: feedback e a palavra continua aberta para outro tentar."""
    quem = nome or "Someone"
    return (
        f"💬 *{quem}* answered:\n{feedback_de_revisao(rev)}\n\n"
        f"The word is still open — anyone can try again, or {p}skip."
    )


def palavra_pulada(palavra: str) -> str:
    return f"⏭️ Skipping *{palavra}*. It'll come back in a future review."


def revisao_inativa(
    feitas: Sequence[str],
    lapsos: Sequence[str],
    *,
    puladas: Sequence[str] = (),
) -> str:
    """A rodada fechou porque o grupo ficou 3 horas sem mensagem."""
    corpo = "😴 Nobody replied for a while, so I closed this review."
    if not feitas and not puladas:
        return corpo + " I'll be back later."
    return corpo + "\n" + revisao_encerrada(feitas, lapsos, puladas=puladas)


# --- Configuração da revisão diária (M35, ADR-0033) -------------------------------------------


def so_admin_configura(p: str = "!", comando: str = "daily") -> str:
    return f"Only the bot's admins can change this. Anyone can see the settings with {p}{comando}."


def atividade_em_andamento(p: str = "!") -> str:
    return f"There's an activity going on right now. Finish it first (or send {p}0)."


def lembrete_virou_daily(p: str = "!") -> str:
    return f"Reminders now work as a daily review. See it with {p}daily."


def diaria_invalida(p: str = "!") -> str:
    return (
        f"I couldn't understand that. Try {p}daily 19h (time), {p}daily weekends on, "
        f"{p}daily size 5 or {p}daily off."
    )


def diaria_estado(
    perfil: Profile,
    proximo: datetime | None,
    agora: datetime,
    tamanho: int,
    p: str = "!",
    *,
    alterada: bool = False,
) -> str:
    abertura = "✅ Daily review updated." if alterada else "⏰ *Daily review*"
    if not perfil.diaria_ligada:
        return f"{abertura}\nIt's off. Turn it on with {p}daily on."
    dias = "every day" if perfil.diaria_fim_de_semana else "every weekday"
    linhas = [
        abertura,
        f"🕖 {dias} around {perfil.diaria_hora:02d}:{perfil.diaria_minuto:02d} "
        f"(may arrive up to {JITTER_MINUTOS} min earlier or later)",
        f"📚 {tamanho} words per review",
    ]
    if proximo is not None:
        linhas.append(f"⏭️ Next one: {_quando(proximo, agora)}")
    linhas.append(f"_Admins can change it: {p}daily 19h · {p}daily weekends on · {p}daily off_")
    return "\n".join(linhas)


# --- Desafio semanal do grupo (M36, ADR-0034) --------------------------------------------------

_MARCA = re.compile(r"\[\[(.+?)\]\]")


def negrito_das_marcas(frase: str) -> str:
    """`[[stalled]]` -> `*stalled*` (negrito do WhatsApp), para destacar o vocabulário."""
    return _MARCA.sub(r"*\1*", frase)


def semanal_abertura(total: int) -> str:
    perguntas = "question" if total == 1 else "questions"
    return (
        f"🏆 *Weekly challenge* — {total} {perguntas}, one student each.\n"
        "I'll tag who answers. Anyone can try, but I only move on when the tagged person "
        "answers, or someone skips."
    )


def pergunta_semanal(indice: int, total: int, marcado: str, pergunta: str) -> str:
    """Sempre começa marcando a pessoa, depois a pergunta e o menu (`/1`, `/2`, `/3`)."""
    return (
        f"@{marcado} {negrito_das_marcas(pergunta)}\n\n"
        "/1 Explain the question\n"
        "/2 Listen to the question\n"
        "/3 Skip this question\n"
        f"_🏆 Weekly challenge · {indice}/{total} — tag me to answer_"
    )


def explicacao_da_pergunta(explicacao_en: str, explicacao_pt: str, *, pt: bool) -> str:
    """Turma iniciante: português primeiro, depois o inglês; de B1-B2 em diante, só inglês."""
    if pt and explicacao_pt.strip():
        return f"🇧🇷 {explicacao_pt.strip()}\n🇺🇸 {explicacao_en.strip()}"
    return f"💡 {explicacao_en.strip()}"


def feedback_semanal(rev: AvaliacaoDaPergunta, nome: str | None) -> str:
    quem = nome or "Someone"
    linhas = [f"{_QUALIDADE_EMOJI[rev.qualidade]} *{quem}*: {rev.feedback}"]
    if rev.correcao:
        linhas.append(f"💬 {rev.correcao}")
    return "\n".join(linhas)


def feedback_semanal_de_outro(rev: AvaliacaoDaPergunta, nome: str | None, marcado: str) -> str:
    """Quem não foi marcado também recebe feedback, mas a pergunta não avança por ele."""
    return (
        feedback_semanal(rev, nome)
        + f"\n⏳ Nice try! I'm still waiting for @{marcado} (or a skip)."
    )


def semanal_encerrada(respondidas: int, puladas: int, total: int) -> str:
    linhas = [f"🏁 *Weekly challenge done* — {respondidas} of {total} answered."]
    if puladas:
        linhas.append(f"⏭️ Skipped: {puladas}")
    linhas.append("Add new words any time: tag me with a word.")
    return "\n".join(linhas)


def semanal_inativa(respondidas: int, puladas: int, total: int) -> str:
    return "😴 Nobody replied for a while, so I closed the challenge.\n" + semanal_encerrada(
        respondidas, puladas, total
    )


def semanal_sem_palavras() -> str:
    return "The weekly challenge needs words from the class. Add some by tagging me with a word."


def semanal_invalida(p: str = "!") -> str:
    return (
        f"I couldn't understand that. Try {p}weekly fri 13h (day and time), {p}weekly size 3, "
        f"{p}weekly off or {p}weekly now."
    )


def semanal_estado(
    perfil: Profile,
    proximo: datetime | None,
    agora: datetime,
    p: str = "!",
    *,
    alterada: bool = False,
) -> str:
    abertura = "✅ Weekly challenge updated." if alterada else "🏆 *Weekly challenge*"
    if not perfil.semanal_ligada:
        return f"{abertura}\nIt's off. Turn it on with {p}weekly on."
    dia = NOMES_DOS_DIAS[perfil.semanal_dia]
    tamanho = (
        f"{perfil.semanal_tamanho} questions"
        if perfil.semanal_tamanho
        else "one question per student"
    )
    linhas = [
        abertura,
        f"🗓️ every {dia} around {perfil.semanal_hora:02d}:{perfil.semanal_minuto:02d} "
        f"(may arrive up to {JITTER_MINUTOS} min earlier or later)",
        f"❓ {tamanho}",
    ]
    if proximo is not None:
        linhas.append(f"⏭️ Next one: {_quando(proximo, agora)}")
    linhas.append(f"_Admins can change it: {p}weekly fri 13h · {p}weekly size 3 · {p}weekly now_")
    return "\n".join(linhas)
