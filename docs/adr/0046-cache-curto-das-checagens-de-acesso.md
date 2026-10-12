# ADR-0046: Cache curto em memória das checagens de acesso do Firestore (admin, grupo ativo, LID)

- **Status:** Aceito
- **Data:** 2026-10-12

## Contexto

Duas consultas ao Firestore rodam a **cada mensagem** que chega ao webhook: `grupo_autorizado` (leitura
de `espacos/{grupo}`), antes do filtro de marcação/prefixo — ou seja, também na conversa entre pessoas
que o bot ignora —, e `eh_admin`, que lista todos os `admins/` a cada mensagem do privado. Mais a
resolução de LID para número. Com dezenas de grupos ativos e conversa humana, isso é o grosso das
leituras do dia e come a cota gratuita (50 mil leituras/dia), sem entregar nada ao aluno.

## Decisão

1. **`FirestoreBanco` guarda em memória**, com validade de **60 s**: a lista de admins e o estado
   ativo/inativo de cada grupo (inclusive o negativo, que é o caso comum de grupo ignorado).
2. **Invalidação pelas mutações do próprio processo:** `adicionar_admin`, `remover_admin`,
   `ativar_grupo` e `desativar_grupo` derrubam a entrada **depois** da escrita (nenhuma leitura no meio
   re-cacheia o valor antigo). Há um só processo, então o cache é coerente; uma edição manual no
   console vale em até 60 s.
3. **LID → número** (um LID de uma pessoa não muda) fica em memória pelo processo, limitado a 5.000
   entradas; só resolvidos são cacheados.
4. O cache vive no adaptador do Firestore, não na camada de negócio: `MemoryBanco` (testes, simulador)
   não precisa dele e a interface `Banco` não muda.
5. O mapa de grupos é limpo ao passar de 500 entradas, para grupos desconhecidos (flood de convites)
   não o fazerem crescer sem limite.

## Alternativas consideradas

- **Cache na camada de negócio (`Acesso`)** — descartada: `Acesso` é recriado a cada mensagem em
  `main.py`; o cache teria de viver num singleton à parte, longe de quem sabe invalidar.
- **Escutar o Firestore com `on_snapshot`** — descartada: conexão longa e threads extras na e2-micro
  por um ganho que 60 s de validade já dão.
- **Validade maior** — descartada: 60 s é imperceptível para quem ativa um grupo (a ativação invalida
  na hora) e limita o erro de edições manuais.

## Consequências

- Leituras de acesso caem de "uma por mensagem" para "uma por minuto por grupo/lista".
- Se o bot passar a ter **mais de um processo**, este cache precisa ser repensado (invalidação entre
  processos); registrado aqui porque ADR-0008 mantém a VM única.
