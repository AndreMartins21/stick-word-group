# Architecture Decision Records (ADR)

Registro curto de decisões técnicas com consequência duradoura: **o que** foi decidido, **por quê**,
e o que foi descartado. Um ADR evita que a mesma discussão volte daqui a três meses sem contexto.

A skill `adr` (em `.claude/skills/adr/`) descreve o processo completo. Este arquivo é a referência
operacional: numeração, status e o índice.

## Índice

| ADR | Título | Status | Data |
|---|---|---|---|
| [0001](0001-stack-do-mvp.md) | Stack do MVP (WAHA + Gemini no Vertex AI + VM e2-micro) | Aceito | 2026-09-20 |
| [0002](0002-gestao-de-mudancas-por-adr.md) | Gestão de mudanças por ADR | Aceito | 2026-09-20 |
| [0003](0003-firestore-como-banco-atras-de-repository.md) | Firestore (modo nativo) como banco, atrás de uma interface Repository | Aceito | 2026-09-20 |
| [0004](0004-maquina-de-estados-pura.md) | Máquina de estados como função pura que devolve uma ação | Aceito | 2026-09-20 |
| [0005](0005-llm-atras-de-provider-com-validacao-propria.md) | IA atrás de um provedor que devolve JSON, com validação e nova tentativa próprias | Aceito | 2026-09-20 |
| [0006](0006-conversa-em-segundo-plano-e-serializada.md) | Conversa em segundo plano, serializada, com código bloqueante em threads | Aceito | 2026-09-20 |
| [0007](0007-infra-menor-privilegio-e-acesso-por-iap.md) | Infra no menor privilégio, segredos gerados no Secret Manager e SSH só por IAP com OS Login | Aceito | 2026-09-20 |
| [0008](0008-continuar-na-gcp-e-manter-a-saida-portavel.md) | Continuar na GCP e manter a saída portátil (casa ou Oracle) para depois do trial | Aceito | 2026-09-20 |
| [0009](0009-roteamento-de-texto-livre-pela-ia.md) | Roteamento de texto livre por uma chamada de IA, máquina de estados reduzida a dois estados | Aceito | 2026-09-22 |
| [0010](0010-interface-em-ingles.md) | Interface do bot em inglês, com a tradução como única exceção | Aceito | 2026-09-22 |
| [0011](0011-revisao-espacada-sm2-simplificado.md) | Revisão espaçada com SM-2 simplificado, independente do agendamento do Anki | Aceito | 2026-09-23 |
| [0012](0012-agendador-no-processo-com-destino-persistido.md) | Agendador de lembretes no próprio processo, com destino persistido e trava de iniciativa | Aceito | 2026-09-23 |
| [0013](0013-deploy-continuo-via-github-actions.md) | Deploy contínuo via GitHub Actions, autenticado por Workload Identity Federation | Aceito | 2026-09-23 |
| [0014](0014-export-em-planilha-excel.md) | Export em planilha Excel no lugar do arquivo de importação do Anki | Aceito | 2026-09-23 |
| [0015](0015-enviar-a-planilha-direto-pelo-whatsapp.md) | Enviar a planilha direto pelo WhatsApp, com o link do bucket só como plano B | Aceito | 2026-09-24 |
| [0016](0016-letras-de-musica-via-lrclib.md) | Letras de música via LRCLIB, atrás de uma interface, com o risco de direito autoral aceito para uso pessoal | Aceito | 2026-09-24 |
| [0017](0017-multiusuario-por-espaco.md) | Multiusuário por espaço | Aceito | 2026-09-24 |
| [0018](0018-acesso-por-admins-e-ativacao-de-grupos.md) | Acesso por admins e ativação de grupos | Aceito | 2026-09-24 |
| [0019](0019-bot-em-grupo-com-prefixo-e-comandos-limitados.md) | Bot em grupo com prefixo `!` e comandos limitados | Aceito | 2026-09-24 |
| [0020](0020-revisao-em-grupo-com-mencao-em-rodizio.md) | Revisão em grupo com menção em rodízio | Substituído por ADR-0033 | 2026-09-24 |
| [0021](0021-palavra-repetida-pular-e-ignorar-no-menu.md) | Palavra repetida avisa e mostra o que já existe; `0`/`skip` saem da palavra e a opção 4 a descarta | Aceito | 2026-09-25 |
| [0022](0022-retentativa-do-gemini-e-erro-de-provedor-como-llmerror.md) | Retentativa do Gemini no próprio SDK e erro do provedor tratado como `LLMError` | Aceito | 2026-09-25 |
| [0023](0023-identidade-da-palavra-nao-depende-do-texto-da-traducao.md) | A identidade da palavra não depende do texto da tradução que a IA devolve | Aceito | 2026-09-25 |
| [0024](0024-pronuncia-em-audio-com-google-cloud-tts.md) | Pronúncia em áudio sob demanda, com Google Cloud TTS e cache permanente no GCS | Aceito | 2026-09-26 |
| [0025](0025-lembretes-ligados-por-padrao-e-fila-de-revisao-configuravel.md) | Lembretes ligados por padrão (1x às 12h, só perfil novo) e tamanho da fila de revisão configurável | Aceito | 2026-09-27 |
| [0026](0026-pronuncia-automatica-substitui-a-opcao-de-ouvir.md) | Pronúncia automática ao explicar a palavra, substituindo a opção de ouvir no menu | Aceito | 2026-09-27 |
| [0027](0027-pronuncia-automatica-na-revisao-so-no-privado.md) | Pronúncia automática do termo em cada card de revisão, só no privado | Aceito | 2026-09-27 |
| [0028](0028-logs-estruturados-com-eventos-e-handler-para-o-cloud-logging.md) | Logs estruturados com eventos e um handler para o Cloud Logging (não o driver `gcplogs`) | Aceito | 2026-09-27 |
| [0029](0029-snapshot-diario-do-firestore-em-ndjson-no-gcs-lido-pelo-bigquery.md) | Snapshot diário do Firestore em NDJSON no GCS, lido pelo BigQuery como tabela externa | Aceito | 2026-09-28 |
| [0030](0030-pedido-de-sentido-e-palavra-de-qualquer-nivel.md) | Pedido de sentido (`palavra \| sentido`) e palavra de qualquer nível | Aceito | 2026-09-28 |
| [0031](0031-level-no-grupo-so-professor-ou-dono-e-opcao-5-dont-save.md) | `!level` no grupo (só professor ou dono muda) e opção 5 do menu renomeada para "Don't save" | Aceito | 2026-09-29 |
| [0032](0032-seis-niveis-e-turma-so-em-ingles-a-partir-do-b1-b2.md) | Seis níveis e turma só em inglês a partir de B1-B2 | Aceito | 2026-10-01 |
| [0033](0033-revisao-diaria-no-grupo-sem-marcacao.md) | Revisão diária no grupo, sem marcar ninguém | Aceito | 2026-10-01 |
| [0034](0034-desafio-semanal-com-perguntas-da-ia-e-marcacao.md) | Desafio semanal do grupo, com perguntas da IA e marcação em rodízio | Aceito | 2026-10-01 |
| [0035](0035-grupo-responde-a-marcacao-e-comandos-seguem.md) | No grupo o bot responde a quem o marca; comandos seguem com `!` ou `/` | Aceito | 2026-10-02 |
| [0036](0036-grupo-responde-a-citacao-de-mensagem-do-bot.md) | Grupo responde a quem cita uma mensagem do bot | Aceito | 2026-10-06 |
| [0037](0037-audio-no-grupo-transcrito-pelo-gemini.md) | Nota de voz no grupo, transcrita pelo Gemini, só quando cita uma mensagem do bot | Aceito | 2026-10-12 |
| [0038](0038-limite-de-tamanho-do-texto.md) | Limite de tamanho do texto que chega à IA: recusar, não truncar | Aceito | 2026-10-12 |
| [0039](0039-limite-de-duracao-e-de-bytes-do-audio.md) | Áudio recusado pela duração declarada, antes de baixar, e download em streaming com teto de bytes | Aceito | 2026-10-12 |
| [0040](0040-waha-so-baixa-audio.md) | WAHA baixa só áudio: filtro de mimetype por prefixo e vida curta dos arquivos | Aceito | 2026-10-12 |
| [0041](0041-limite-de-uso-por-pessoa-e-por-grupo.md) | Limite de uso por pessoa e por grupo, em memória, com aviso único | Aceito | 2026-10-12 |
| [0042](0042-teto-de-saida-e-nivel-de-raciocinio-do-gemini.md) | Teto de tokens de saída e nível de raciocínio mínimo no Gemini, com recuo automático | Aceito | 2026-10-12 |

## Quando escrever um

Escreva um ADR quando a decisão:

- é difícil de reverter (banco, hospedagem, provedor de IA, formato de dados exportado);
- restringe o trabalho futuro (limite de memória da VM, "não usar engine WEBJS");
- foi tomada entre alternativas reais, e alguém razoável escolheria diferente.

Não escreva para escolhas triviais ou facilmente reversíveis (nome de variável, ordem de funções,
refatoração local, bump de dependência).

## Numeração

Arquivos seguem `NNNN-titulo-curto.md`, com quatro dígitos e zeros à esquerda — `0001`, `0002`,
... `0042`. O zero-padding mantém a ordenação alfabética igual à ordem cronológica em qualquer
ferramenta (`ls`, GitHub, editor). `0000-template.md` é o molde e não conta como decisão.

O próximo número sai de:

```bash
ls docs/adr/ | grep -E '^[0-9]{4}-' | sort | tail -1
```

Números nunca são reaproveitados, nem quando um ADR é descartado.

## Status

| Status | Significado |
|---|---|
| `Proposto` | Escrito, ainda não aprovado nem implementado. |
| `Aceito` | Vale agora. |
| `Substituído por ADR-NNNN` | Não vale mais; o ADR indicado explica o que vale. |
| `Descartado` | Considerado e rejeitado; fica registrado para não ser reproposto. |

## Como

1. Copie `0000-template.md` para `NNNN-titulo-curto.md` (número sequencial).
2. Preencha. Seja breve: uma página basta.
3. Acrescente a linha no índice acima.
4. Commite o ADR junto com o código que o implementa.
5. ADR aceito **não se edita** — se a decisão mudar, crie um novo ADR e marque o antigo como
   `Substituído por ADR-NNNN`.

`tests/test_adr.py` verifica o que é mecânico: numeração, título, status, seções obrigatórias e se o
índice está completo. `make test` reprova um ADR malformado.
