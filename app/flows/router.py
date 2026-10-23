"""Roteador: recebe o texto do aluno, decide (máquina de estados pura, ADR-0004/ADR-0009),
executa a ação com os fluxos e guarda a sessão.

Multiusuário (ADR-0017): cada chat é um espaço, com o próprio caderno (`Banco.do_espaco`), a
própria `Conversa` (e o limite de 3 mensagens seguidas) e a própria trava. Duas mensagens do mesmo
chat andam uma por vez; chats diferentes andam em paralelo."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app import messages
from app.channel.parser import numero_esta_na_lista
from app.domain.models import (
    Estado,
    NivelUsuario,
    Profile,
    Sessao,
    agora_utc,
    nivel_so_ingles,
)
from app.domain.state import Acao, Transicao, expirou, transicionar
from app.flows import (
    capture,
    commands,
    freeform,
    grupo,
    practice,
    review,
    semanal,
    song,
    synonyms,
)
from app.flows.base import FUSO_PADRAO, Autor, ConfigGrupo, Deps, bloq
from app.flows.commands import Exportador, StatusDaSessao
from app.flows.conversa import Conversa
from app.logging_config import id_curto, registrar_evento
from app.repo.base import Banco
from app.services import custo
from app.services.audio import ServicoAudio
from app.services.letras import LyricsProvider
from app.services.limites import Decisao, LimitadorDeUso, Limites
from app.services.llm import LLMError, Tutor
from app.services.orcamento import Orcamento

logger = logging.getLogger(__name__)

MAX_CARACTERES_PADRAO = 500  # M40, ADR-0038
# M47 (ADR-0045): mensagens de um chat esperando a vez (a trava serializa o chat) e chats
# processando ao mesmo tempo (as threads do pool são poucas na e2-micro e também servem o Firestore).
MAX_FILA_POR_CHAT_PADRAO = 3
MAX_PROCESSAMENTOS_PADRAO = 4


@asynccontextmanager
async def _custo_no_espaco(chat_id: str) -> AsyncIterator[None]:
    with custo.no_espaco(chat_id):
        yield


class Router:
    def __init__(
        self,
        *,
        banco: Banco,
        tutor: Tutor,
        criar_conversa: Callable[[str], Conversa],
        nivel_padrao: NivelUsuario,
        agora: Callable[[], datetime] = agora_utc,
        status_da_sessao: StatusDaSessao | None = None,
        exportador: Exportador | None = None,
        fuso: ZoneInfo = FUSO_PADRAO,
        letras: LyricsProvider | None = None,
        audio: ServicoAudio | None = None,
        prefixo_do_grupo: str = "!",
        max_caracteres: int = MAX_CARACTERES_PADRAO,
        limites: Limites | None = None,
        orcamento: Orcamento | None = None,
        max_fila_por_chat: int = MAX_FILA_POR_CHAT_PADRAO,
        max_processamentos: int = MAX_PROCESSAMENTOS_PADRAO,
        eh_dono: Callable[[str], bool] = lambda _numero: False,
        eh_admin: Callable[[str], bool] | None = None,
        config_grupo: ConfigGrupo | None = None,
    ) -> None:
        self._banco = banco
        self._tutor = tutor
        self._criar_conversa = criar_conversa
        self._agora = agora
        self._fuso = fuso
        self._letras = letras
        self._audio = audio
        self._prefixo_do_grupo = prefixo_do_grupo
        self._max_caracteres = max_caracteres
        # M43 (ADR-0041): sem `limites` não há teto (testes e simulador); a produção passa os do
        # `Settings`.
        self._limitador = LimitadorDeUso(limites, agora) if limites is not None else None
        # M46 (ADR-0044): esgotado o orçamento diário de IA, nada chega ao modelo até amanhã.
        self._orcamento = orcamento
        self._pausa_avisada: dict[tuple[str, str], date] = {}  # (chat, motivo) -> dia do aviso
        # M47 (ADR-0045): fila por chat com teto e vagas de processamento globais.
        self._max_fila_por_chat = max_fila_por_chat
        self._na_fila: dict[str, int] = {}
        self._vagas = asyncio.Semaphore(max_processamentos)
        self._eh_dono = eh_dono
        self._eh_admin = eh_admin
        self._config_grupo = config_grupo or ConfigGrupo()
        self._nivel_padrao = nivel_padrao
        self._status_da_sessao = status_da_sessao
        self._exportador = exportador
        self._conversas: dict[str, Conversa] = {}
        # O webhook pode chegar em duas mensagens seguidas do mesmo chat: uma por vez.
        self._travas: dict[str, asyncio.Lock] = {}

    def conversa_do(self, chat_id: str) -> Conversa:
        if chat_id not in self._conversas:
            self._conversas[chat_id] = self._criar_conversa(chat_id)
        return self._conversas[chat_id]

    def _trava(self, chat_id: str) -> asyncio.Lock:
        return self._travas.setdefault(chat_id, asyncio.Lock())

    def _deps(self, chat_id: str, autor: Autor | None = None) -> Deps:
        return Deps(
            repo=self._banco.do_espaco(chat_id),
            tutor=self._tutor,
            conversa=self.conversa_do(chat_id),
            agora=self._agora,
            fuso=self._fuso,
            letras=self._letras,
            audio=self._audio,
            grupo_prefixo=self._prefixo_do_grupo if chat_id.endswith("@g.us") else None,
            autor=autor,
            chat_id=chat_id,
            grupo_cfg=self._config_grupo,
            eh_staff=self._eh_staff,
            eh_admin=self._eh_dono_ou_admin,
            banco=self._banco,
        )

    def _eh_dono_ou_admin(self, numero: str) -> bool:
        return self._eh_dono(numero) or (self._eh_admin is not None and self._eh_admin(numero))

    def _eh_staff(self, numero: str) -> bool:
        """Dono, admin do bot ou professor global (M57, ADR-0055). Síncrono (lê o banco, com o
        cache curto do ADR-0046)."""
        if self._eh_dono_ou_admin(numero):
            return True
        return numero_esta_na_lista(numero, self._banco.listar_professores())

    async def responder_avulso(self, chat_id: str, texto: str) -> None:
        """Uma resposta fixa (sem IA e sem mexer na sessão), com o mesmo ritmo humano e o mesmo
        limite de mensagens seguidas das demais: usado pelos comandos de admin (M15)."""
        async with self._trava(chat_id):
            conversa = self.conversa_do(chat_id)
            conversa.usuario_falou()
            await conversa.enviar(texto)

    async def midia_nao_suportada(self, chat_id: str) -> None:
        async with self._trava(chat_id):
            conversa = self.conversa_do(chat_id)
            conversa.usuario_falou()
            await conversa.enviar(messages.MIDIA_NAO_SUPORTADA)

    async def admitir(
        self, chat_id: str, autor: Autor | None, *, segundos_de_audio: int = 0
    ) -> bool:
        """Limite de uso por pessoa e por grupo (M43, ADR-0041): gasta uma mensagem (e, para áudio,
        os segundos) da janela. Na primeira recusa de uma sequência avisa uma vez; depois, silêncio.
        O dono nunca é limitado. Chamado por `processar` e, para áudio, antes de transcrever."""
        if autor is not None and self._eh_dono(autor.numero):
            return True
        if self._orcamento is not None:
            pausa: str | None = await bloq(self._orcamento.pausa)
            if pausa is None and await bloq(self._orcamento.espaco_esgotado, chat_id):
                pausa = "grupo"
            if pausa is not None:
                await self._avisar_pausa(chat_id, pausa)
                return False
        if self._limitador is None:
            return True
        em_grupo = chat_id.endswith("@g.us")
        pessoa = autor.numero if autor is not None else chat_id
        decisao = self._limitador.admitir(
            pessoa, chat_id, em_grupo=em_grupo, segundos_de_audio=segundos_de_audio
        )
        if decisao.permitido:
            return True
        registrar_evento(
            logger,
            "limite_atingido",
            espaco=id_curto(chat_id),
            tipo_espaco="grupo" if em_grupo else "privado",
            motivo=decisao.motivo,
            avisou=decisao.avisar,
        )
        if decisao.avisar:
            await self._avisar_limite(chat_id, decisao)
        return False

    async def _avisar_pausa(self, chat_id: str, pausa: str) -> None:
        """Um aviso por chat por dia e por motivo (`dia`, `mes` ou `grupo`, a cota do grupo)."""
        registrar_evento(logger, "pausa_de_orcamento", espaco=id_curto(chat_id), motivo=pausa)
        hoje = self._agora().astimezone(self._fuso).date()
        if self._pausa_avisada.get((chat_id, pausa)) == hoje:
            return
        self._pausa_avisada[(chat_id, pausa)] = hoje
        texto = {
            "mes": messages.PAUSA_DO_MES,
            "grupo": messages.PAUSA_DO_GRUPO,
        }.get(pausa, messages.PAUSA_DE_HOJE)
        async with self._trava(chat_id):
            conversa = self.conversa_do(chat_id)
            conversa.usuario_falou()
            await conversa.enviar(texto)

    async def _avisar_limite(self, chat_id: str, decisao: Decisao) -> None:
        texto = {
            "minuto": messages.DEVAGAR,
            "dia": messages.LIMITE_DO_DIA,
            "grupo": messages.LIMITE_DO_GRUPO,
            "audio": messages.LIMITE_DE_AUDIO,
        }[decisao.motivo or "minuto"]
        async with self._trava(chat_id):
            conversa = self.conversa_do(chat_id)
            conversa.usuario_falou()
            await conversa.enviar(texto)

    async def processar(
        self,
        texto: str,
        chat_id: str,
        autor: Autor | None = None,
        *,
        marcado: bool = False,
        admitida: bool = False,
    ) -> None:
        """`chat_id` é o espaço E o destino das respostas: o chat de onde a mensagem veio. Em
        grupo (M16) `autor` é quem escreveu e `texto` vem COM o prefixo (`!` ou `/`, um comando)
        ou, com `marcado` (M37, ADR-0035), sem a marcação do bot (conversa com ele). Sem uma coisa
        nem outra é conversa entre pessoas e nada acontece."""
        if not admitida and not self._eh_para_o_bot(texto, chat_id, autor, marcado):
            return
        if self._na_fila.get(chat_id, 0) >= self._max_fila_por_chat:
            # Um flood não vira uma fila de tarefas gastando IA depois do ataque: descarta em
            # silêncio (responder também é carga) e só registra.
            registrar_evento(logger, "fila_cheia", espaco=id_curto(chat_id))
            return
        if not admitida and not await self.admitir(chat_id, autor):
            return
        self._na_fila[chat_id] = self._na_fila.get(chat_id, 0) + 1
        try:
            await self._processar_na_vez(texto, chat_id, autor, marcado)
        finally:
            restantes = self._na_fila[chat_id] - 1
            if restantes > 0:
                self._na_fila[chat_id] = restantes
            else:
                del self._na_fila[chat_id]

    async def _processar_na_vez(
        self, texto: str, chat_id: str, autor: Autor | None, marcado: bool
    ) -> None:
        async with self._trava(chat_id), self._vagas, _custo_no_espaco(chat_id):
            d = self._deps(chat_id, autor)
            de_grupo: tuple[Autor, str, bool] | None = None
            if d.em_grupo:
                if autor is None:
                    return
                resto = grupo.sem_prefixo(texto, d.p)
                if resto is not None:
                    de_grupo = (autor, resto, False)
                elif marcado:
                    de_grupo = (autor, texto.strip(), True)
                else:
                    return
            d.conversa.usuario_falou()
            if len(texto.strip()) > self._max_caracteres:
                # M40 (ADR-0038): recusa antes de tocar no banco ou na IA; a sessão fica como estava.
                await d.conversa.enviar(messages.texto_longo_demais(self._max_caracteres))
                return
            perfil = await bloq(self._perfil, d)
            d = self._com_idioma(d, perfil)
            if (
                perfil.chat_id != chat_id
                or perfil.lembrete_sem_resposta
                or (d.em_grupo and (perfil.revisoes_sem_resposta or perfil.proxima_diaria is None))
            ):
                # M10: guarda o destino real (para o agendador saber para onde mandar os
                # lembretes) e limpa o backoff — o aluno acabou de falar. No grupo (M35) isso
                # também zera as revisões seguidas sem resposta e reescreve o espelho do tick.
                perfil = perfil.model_copy(
                    update={
                        "chat_id": chat_id,
                        "lembrete_sem_resposta": False,
                        "revisoes_sem_resposta": 0,
                    }
                )
                await bloq(d.repo.salvar_perfil, perfil)
            sessao = await bloq(d.repo.obter_sessao)
            if sessao.estado != Estado.IDLE and expirou(sessao.atualizado_em, d.agora()):
                # Parada há mais de 3 horas: volta para IDLE. O que havia já está salvo.
                sessao = d.sessao_vazia()

            try:
                if de_grupo is not None:
                    nova = await grupo.tratar(
                        d,
                        sessao,
                        perfil,
                        de_grupo[1],
                        autor=de_grupo[0],
                        conversar=self._conversar,
                        eh_dono=self._eh_dono,
                        eh_admin=self._eh_admin,
                        marcado=de_grupo[2],
                    )
                elif self._como_comando(texto).startswith("/"):
                    nova = await commands.executar(
                        d,
                        sessao,
                        perfil,
                        self._como_comando(texto),
                        status_da_sessao=self._status_da_sessao,
                        exportador=self._exportador,
                    )
                else:
                    nova = await self._conversar(d, sessao, perfil, texto)
            except LLMError:
                logger.warning("falha da IA; sessão mantida como estava", exc_info=True)
                await d.conversa.enviar(messages.ERRO_IA)
                return

            await bloq(d.repo.salvar_sessao, self._com_prazo(d, nova))

    def _eh_para_o_bot(self, texto: str, chat_id: str, autor: Autor | None, marcado: bool) -> bool:
        """Em grupo, conversa entre pessoas não é do bot: nem gasta o limite nem recebe aviso."""
        if not chat_id.endswith("@g.us"):
            return True
        return autor is not None and (
            marcado or grupo.sem_prefixo(texto, self._prefixo_do_grupo) is not None
        )

    @staticmethod
    def _com_prazo(d: Deps, sessao: Sessao) -> Sessao:
        """Todo ato no grupo adia o fechamento por inatividade da rodada em andamento (M35)."""
        atualizacoes: dict[str, object] = {"atualizado_em": d.agora()}
        if d.em_grupo and Estado(sessao.estado) in (Estado.REVIEWING, Estado.WEEKLY_QUIZ):
            atualizacoes["marcacao_expira_em"] = d.agora() + d.grupo_cfg.timeout
        return sessao.model_copy(update=atualizacoes)

    @staticmethod
    def _com_idioma(d: Deps, perfil: Profile) -> Deps:
        """M34 (ADR-0032): grupo de B1-B2 para cima não vê português; o privado nunca muda."""
        return replace(d, so_ingles=d.em_grupo and nivel_so_ingles(perfil.nivel))

    def _como_comando(self, texto: str) -> str:
        """No privado, o prefixo do grupo (`!`) é um apelido escondido da barra: `!list` vale
        `/list`. Só vale se uma letra vem logo depois; `!!!` ou `!1` seguem como texto."""
        limpo = texto.strip()
        p = self._prefixo_do_grupo
        if limpo.startswith(p) and len(limpo) > len(p) and limpo[len(p)].isalpha():
            return "/" + limpo[len(p) :]
        return limpo

    def _perfil(self, d: Deps) -> Profile:
        # M28: só no privado — em grupo, `d.autor` é quem escreveu a mensagem, não o espaço.
        nome = d.autor.nome if (d.autor is not None and not d.em_grupo) else None
        perfil = d.repo.obter_perfil()
        if perfil is None:
            perfil = Profile(nivel=self._nivel_padrao, criado_em=d.agora(), nome=nome)
            d.repo.salvar_perfil(perfil)
        elif nome and perfil.nome != nome:
            perfil = perfil.model_copy(update={"nome": nome})
            d.repo.salvar_perfil(perfil)
        return perfil

    async def _conversar(self, d: Deps, sessao: Sessao, perfil: Profile, texto: str) -> Sessao:
        transicao = transicionar(Estado(sessao.estado), texto)
        sessao = sessao.model_copy(update={"estado": transicao.estado})
        return await self._executar(d, transicao, sessao, perfil)

    async def _executar(self, d: Deps, t: Transicao, sessao: Sessao, perfil: Profile) -> Sessao:
        argumento = t.argumento
        match t.acao:
            case Acao.EXPLICAR:
                return await capture.explicar(d, perfil, str(argumento))
            case Acao.GERAR_EXEMPLOS:
                return await practice.gerar_exemplos(d, sessao, perfil)
            case Acao.GERAR_SINONIMOS:
                return await synonyms.gerar(d, sessao, perfil)
            case Acao.SALVAR:
                return await practice.concluir(d, sessao, perfil)
            case Acao.PULAR:
                return await practice.pular(d)
            case Acao.IGNORAR:
                return await practice.ignorar(d, sessao)
            case Acao.ROTEAR:
                return await freeform.rotear(d, sessao, perfil, str(argumento))
            case Acao.EXPLICAR_COM_CONTEXTO:
                return await freeform.palavra_com_contexto(d, sessao, perfil, str(argumento))
            case Acao.RESPONDER_REVISAO:
                return await review.responder(d, sessao, perfil, str(argumento))
            case Acao.ENCERRAR_REVISAO:
                return await review.encerrar(d, sessao)
            case Acao.BUSCAR_MUSICA:
                return await song.buscar(d, sessao, str(argumento))
            case Acao.ESCOLHER_MUSICA:
                return await song.escolher(d, sessao, str(argumento))
            case Acao.CANCELAR_MUSICA:
                return await song.cancelar(d)
            case Acao.RESPONDER_VERSO:
                return await song.responder(d, sessao, perfil, str(argumento))
            case Acao.ENCERRAR_MUSICA:
                return await song.encerrar(d, sessao)
            case Acao.SALVAR_EXPRESSOES:
                return await song.salvar(d, sessao, perfil, str(argumento))
            case Acao.DESCARTAR_EXPRESSOES:
                return await song.descartar(d)
            case Acao.RESPONDER_PERGUNTA:
                return await semanal.responder(d, sessao, perfil, str(argumento))
            case Acao.EXPLICAR_PERGUNTA:
                return await semanal.explicar(d, sessao)
            case Acao.OUVIR_PERGUNTA:
                return await semanal.ouvir(d, sessao)
            case Acao.PULAR_PERGUNTA:
                return await semanal.pular(d, sessao)
            case Acao.ENCERRAR_SEMANAL:
                return await semanal.encerrar(d, sessao)

    async def iniciar_revisao(self, chat_id: str) -> None:
        """Chamado pelo agendador (M10, `app/services/lembretes.py`): o bot inicia a conversa,
        não responde a uma. Mesma trava do resto (não pode correr junto de uma mensagem
        chegando). Nunca dispara sem um destino real já aprendido, e nunca interrompe uma
        conversa em andamento — quem decide isso é o próprio agendador, antes de chamar."""
        async with self._trava(chat_id), self._vagas, _custo_no_espaco(chat_id):
            d = self._deps(chat_id)
            perfil = await bloq(self._perfil, d)
            d = self._com_idioma(d, perfil)
            if perfil.chat_id is None:
                return
            sessao = await bloq(d.repo.obter_sessao)
            if sessao.estado != Estado.IDLE and not expirou(sessao.atualizado_em, d.agora()):
                return
            nova = await review.iniciar(d, perfil)
            await bloq(d.repo.salvar_sessao, nova.model_copy(update={"atualizado_em": d.agora()}))

    async def iniciar_semanal(self, chat_id: str) -> None:
        """Chamado pelo agendador (M36): o bot inicia o desafio semanal do grupo. Mesma trava do
        resto; nunca interrompe uma atividade em andamento (sessão não expirada)."""
        async with self._trava(chat_id), self._vagas, _custo_no_espaco(chat_id):
            d = self._deps(chat_id)
            perfil = await bloq(self._perfil, d)
            d = self._com_idioma(d, perfil)
            if perfil.chat_id is None:
                return
            sessao = await bloq(d.repo.obter_sessao)
            if sessao.estado != Estado.IDLE and not expirou(sessao.atualizado_em, d.agora()):
                return
            nova = await semanal.iniciar(d, perfil)
            await bloq(d.repo.salvar_sessao, self._com_prazo(d, nova))

    async def expirar_marcacao(self, chat_id: str, forcar: bool = False) -> None:
        """M35: chamado pelo agendador quando o grupo ficou 3 horas sem mensagem numa revisão
        (`forcar` ignora o prazo, para o simulador). Sem revisão em andamento, ou já
        respondida a tempo, não faz nada. Mesma trava do resto; não conta como fala do aluno."""
        async with self._trava(chat_id):
            d = self._deps(chat_id)
            sessao = await bloq(d.repo.obter_sessao)
            prazo = sessao.marcacao_expira_em
            estado = Estado(sessao.estado)
            if estado not in (Estado.REVIEWING, Estado.WEEKLY_QUIZ) or prazo is None:
                return
            if not forcar and prazo > d.agora():
                return
            if estado == Estado.WEEKLY_QUIZ:
                nova = await semanal.fechar_por_inatividade(d, sessao)
            else:
                nova = await review.fechar_por_inatividade(d, sessao)
            await bloq(d.repo.salvar_sessao, nova.model_copy(update={"atualizado_em": d.agora()}))
