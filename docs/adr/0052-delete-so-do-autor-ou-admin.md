# ADR-0052: `!delete` no grupo só para quem adicionou a palavra, admin do bot ou dono

- **Status:** Aceito
- **Data:** 2026-10-12

## Contexto

No M32 qualquer membro do grupo podia apagar uma palavra da turma, como no `!add`. A auditoria de
2026-10-12 (achado A8) apontou o risco: um membro mal-intencionado ou desastrado apaga o vocabulário
da turma, junto com as frases, em poucas mensagens. O `Entry.autor_id` já guarda quem salvou a palavra
em grupo desde o M28 (snapshot de métricas), então a regra não exige dado novo.

## Decisão

1. No grupo, `!delete` só funciona para: (a) quem **adicionou** a palavra (`Entry.autor_id`, comparado
   com a variação do nono dígito), (b) **admin do bot** ou (c) o **dono**.
2. Entrada sem `autor_id` (anterior ao M28) só admin ou dono apagam.
3. Quem não pode recebe `so_quem_adicionou_apaga` e a palavra fica; nada é apagado.
4. O privado não muda: o espaço é de uma pessoa só. `!add` continua aberto a todos.
5. A checagem entra em `commands.apagar` como um callback opcional (`pode_apagar`), para o privado e o
   grupo compartilharem a mesma função.

## Alternativas consideradas

- **Só professor/dono** — descartada: tira dos alunos o controle das próprias palavras.
- **Qualquer um apaga, com `!undo`** — descartada: exige guardar a exclusão e um prazo de desfazer;
  mais código para um problema que a regra do autor resolve.
- **Manter aberto** — descartada: é o risco que motivou o ADR.

## Consequências

- Uma palavra adicionada por alguém que saiu do grupo só um admin remove.
- Sem migração: entradas antigas sem autor caem na regra 2.
- `!add` aberto a todos ainda permite encher a lista de lixo; o autor da entrada, agora, pode ser
  identificado e um admin remove.
