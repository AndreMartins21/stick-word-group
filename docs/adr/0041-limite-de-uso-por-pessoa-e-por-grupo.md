# ADR-0041: Limite de uso por pessoa e por grupo, em memória, com aviso único

- **Status:** Aceito
- **Data:** 2026-10-12

## Contexto

Qualquer membro de um grupo ativado (não precisa estar na allowlist) pode chamar o bot, e cada mensagem
é uma ou duas chamadas de IA. Nada limitava o volume: o limite de 3 mensagens seguidas (seção 5.6) é do
que o bot **envia**, não do que ele aceita. Um script em loop vira uma conta sem teto, e a fila por chat
(ADR-0006) segura as tarefas gastando IA por minutos depois do ataque. O ADR-0038 limita o tamanho; falta
o volume.

## Decisão

1. **`LimitadorDeUso`** (`app/services/limites.py`): janela deslizante em memória, sem Redis (um
   processo, uma VM). Limites padrão, todos configuráveis por variável de ambiente:
   - por **pessoa**: 6 mensagens por minuto e 150 por dia (`LIMITE_PESSOA_MINUTO`, `LIMITE_PESSOA_DIA`);
   - por **grupo**: 400 mensagens por dia somando todos (`LIMITE_GRUPO_DIA`);
   - por pessoa, **600 segundos de áudio por dia** (`LIMITE_AUDIO_SEGUNDOS_DIA`), conferidos
     **antes** de baixar e transcrever.
   O plano inicial dizia 60 mensagens por dia; subiu para 150 porque uma sessão de `/song` (até 40
   versos) ou uma revisão longa estouraria 60 sem ser abuso. 150 mensagens custam ~US$ 0,15.
2. **Recusa não consome**: confere todos os limites antes de gastar qualquer um, senão quem insiste
   nunca sairia do bloqueio.
3. **Aviso único**: a primeira recusa de uma sequência manda uma mensagem curta (`DEVAGAR`,
   `LIMITE_DO_DIA`, `LIMITE_DO_GRUPO`, `LIMITE_DE_AUDIO`); as seguintes ficam em silêncio até a pessoa
   voltar a ser admitida. Evento `limite_atingido` (motivo, espaço) para medir.
4. **Onde:** `Router.admitir`, chamado no começo de `processar`, **antes da trava do chat** (a trava
   serializa e enfileiraria o flood) e só para o que o bot lê: conversa entre pessoas no grupo não gasta
   limite nem recebe aviso. O áudio chama `admitir` antes de transcrever e passa `admitida=True`.
5. **O dono não é limitado.** Sem `limites` no `Router` (testes, simulador) não há teto.

## Alternativas consideradas

- **Redis ou o Firestore para contar** — descartada: custo e latência numa VM e2-micro; reiniciar zera
  os contadores e isso é aceitável, porque o teto que protege a conta é o orçamento diário (ADR-0044).
- **Limite só global** — descartada: um abusador esgotaria o limite de todos.
- **Banir quem estoura** — descartada: o bloqueio expira sozinho, sem ação do dono.

## Consequências

- Um aluno muito ativo pode bater nos 150/dia; o aviso diz para voltar amanhã e o valor é configurável.
- Os contadores vivem num processo: um deploy ou restart zera. Um atacante que force restarts não
  consegue (não controla a VM), mas é por isso que o orçamento diário vive no Firestore.
- Membros de um mesmo grupo compartilham os 400/dia: uma turma muito grande precisa subir o valor.
