# ADR-0045: Fila por chat com teto e vagas globais de processamento

- **Status:** Aceito
- **Data:** 2026-10-12

## Contexto

O webhook responde 200 na hora e leva a conversa para uma tarefa em segundo plano (ADR-0006); a trava
por chat serializa as mensagens do mesmo chat. Sem teto, 1.000 mensagens de um flood viram 1.000
tarefas presas na trava, segurando memória e **continuando a gastar IA por minutos depois do ataque**.
Além disso, a VM e2-micro tem uma thread-pool pequena (`min(32, CPUs + 4)` = 5) que também serve o
Firestore: chats demais chamando a IA ao mesmo tempo podem deixar até as leituras do banco esperando.

## Decisão

1. **Fila por chat com teto** (`MAX_FILA_POR_CHAT`, padrão 3): o `Router` conta as mensagens de um chat
   que já passaram pelos limites e esperam a vez (ou estão em processamento). A 4ª em diante é
   **descartada em silêncio** (responder também é carga) com o evento `fila_cheia`. A conversa humana
   normal nunca enfileira 3 mensagens num mesmo chat.
2. **Vagas globais** (`MAX_PROCESSAMENTOS`, padrão 4): um `asyncio.Semaphore` limita quantos chats
   processam ao mesmo tempo (mensagens, lembretes e desafios do agendador). Os demais esperam como
   corrotinas (baratas), sem ocupar threads; sobra uma thread do pool para o Firestore. Ordem fixa
   trava-do-chat → vaga, para nunca haver deadlock.
3. **Descartar antes de gastar:** o teto da fila é conferido **antes** do limite de uso (ADR-0041): uma
   mensagem descartada não consome a janela da pessoa.
4. Quem passa pela fila não perde mensagem: só espera a vez.

## Alternativas consideradas

- **Fila persistente (Cloud Tasks, Pub/Sub)** — descartada: infra e custo para um problema que um teto
  em memória resolve; as mensagens de um flood não precisam ser entregues depois.
- **Semáforo dentro do provider (threads)** — descartada: as threads esperando na vaga ocupariam o
  pool, o oposto do objetivo.
- **Responder "fila cheia" ao aluno** — descartada: com flood, vira mais carga; o aviso de limite de
  uso (ADR-0041) já cobre o aluno legítimo que passou da conta.

## Consequências

- Em picos legítimos (uma turma inteira respondendo a um card ao mesmo tempo), mensagens além da
  terceira na fila do grupo são descartadas; o limite é configurável.
- Os contadores vivem no processo (ADR-0041): um restart zera, o que também esvazia a fila.
