# ADR-0050: Assinatura HMAC do webhook obrigatória em produção

- **Status:** Aceito
- **Data:** 2026-10-12

## Contexto

O bot valida a assinatura HMAC (SHA-512) do webhook do WAHA só se `WAHA_HOOK_HMAC_KEY` existir. Sem
ela, aceita qualquer corpo, e o próprio compose só protege o caminho por estar numa rede interna
(auditoria de 2026-10-12, achado A12). Um segredo vazio por engano (secret apagado, deploy mal
renderizado) desligaria a validação em silêncio.

## Decisão

1. Com `APP_ENV=prod`, `Settings` **falha na subida** se `WAHA_HOOK_HMAC_KEY` estiver ausente ou em
   branco. O container reinicia em loop e o smoke test do deploy acusa o problema, em vez de a
   validação ficar desligada sem aviso.
2. Fora de produção (`local`) a chave segue opcional, para o simulador e os testes.
3. A chave já é gerada pelo `infra/setup.sh` e renderizada na VM a partir do Secret Manager
   (`infra/vm/render_e_subir.sh`); nada muda no deploy.

## Alternativas consideradas

- **Só registrar um aviso** — descartada: um aviso num log que ninguém lê não protege.
- **Recusar todo webhook quando a chave falta, mas subir** — descartada: o bot ficaria no ar e mudo, o
  que é mais difícil de diagnosticar do que não subir.

## Consequências

- Um deploy sem o segredo falha de forma visível. Recuperação: criar a versão do secret e redeployar.
- A validação do HMAC no endpoint continua igual (só passa a valer sempre em produção).
