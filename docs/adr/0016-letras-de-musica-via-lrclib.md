# ADR-0016: Letras de música via LRCLIB, atrás de uma interface, com o risco de direito autoral aceito para uso pessoal

- **Status:** Substituído por ADR-0062
- **Data:** 2026-09-24

## Contexto

O M13 adiciona a prática com letra de música (`/song`, seção 5.8): o aluno escolhe uma música, o
bot manda verso a verso e a IA dá feedback sobre a explicação de cada um. O bot precisa da letra
**completa**, buscada pelo nome da música, e vai reenviar os versos pelo WhatsApp. Letra de música
tem direito autoral, e as fontes disponíveis diferem justamente em licença e cobertura:

- **Musixmatch**: licenciado, mas o plano gratuito devolve só ~30% de cada letra (e ~2.000
  chamadas/dia); a letra inteira exige contrato comercial pago. Também pede uma chave de API.
- **Genius**: a API devolve metadados e anotações, não a letra; raspar o site viola os termos.
- **Spotify**: não tem API pública de letras.
- **LRCLIB** (lrclib.net): gratuito, sem chave, ~3 milhões de letras completas, com
  `GET /api/search` (até 20 resultados, sem paginação) e `GET /api/get/{id}`. A base é
  colaborativa: as letras são enviadas por usuários e **não são licenciadas**.

## Decisão

Usar o **LRCLIB** como fonte das letras, atrás da interface `LyricsProvider`
(`app/services/letras.py`, com `LrclibProvider` e o dublê `FakeLyrics`). O risco de direito autoral
fica **aceito enquanto o bot for de uso pessoal** (um usuário, allowlist). Para reduzir o que é
reproduzido:

- o prompt de `song_line` proíbe a IA de repetir o verso inteiro no feedback;
- testes, fixtures, evals e o simulador usam **só letras inventadas**, nunca letra real;
- a letra não é gravada no Firestore além da sessão em andamento (os versos da música atual).

A checagem de idioma é uma heurística sem IA (`eh_ingles`, proporção de palavras comuns do inglês),
calibrada contra resultados reais do LRCLIB: letras em inglês ficam entre ~33% e ~65%, outras
línguas abaixo de 5%, e o corte fica em 20%.

## Alternativas consideradas

- **Musixmatch no plano gratuito** — licenciado, mas a prática cobriria só o trecho inicial da
  música, e traria um segredo novo para o Secret Manager.
- **Musixmatch comercial** — resolve a licença, mas o custo não se justifica para um bot pessoal.
- **O usuário cola a letra** — sem risco nenhum, mas perde a busca e a escolha entre homônimas,
  que são metade da graça.
- **Detectar o idioma com a IA ou com uma biblioteca (`langdetect`, `lingua`)** — a heurística
  acerta com folga nos casos reais, é determinística, não custa nada e não adiciona dependência.

## Consequências

- Fácil: nenhuma chave, nenhum custo, letra completa; trocar de fonte é escrever outra
  implementação de `LyricsProvider`.
- Difícil: a busca do LRCLIB só pelo título ordena mal (covers e coletâneas antes da versão
  conhecida); o bot mitiga buscando por `track_name` (com a busca livre como plano B), ficando com
  uma versão por artista e sugerindo `/song nome - artista`.
- O LRCLIB é um serviço comunitário, sem SLA: fora do ar, o `/song` avisa e o resto do bot segue.
- Revisitar se: o bot deixar de ser pessoal (mais usuários, qualquer uso comercial), o que exige
  uma fonte licenciada; ou se o LRCLIB mudar a API ou a política de uso.
