#!/usr/bin/env bash
# Roda NA VM, como root (o /opt/stick-word-group é modo 700); o infra/smoke_test.sh o envia por stdin.
# Confere que o bot responde no /health e que a sessão do WAHA está WORKING, **esperando** os dois:
# depois de um deploy que recria o WAHA, o GOWS demora mais de 10 s para subir e reinicia algumas
# vezes ("Connection reset by peer"), e o bot pode ainda estar reiniciando. Falhar na primeira
# tentativa dava alarme falso; agora espera até ESPERA_MAXIMA segundos por cada um.
#
# Lê a API key do .env da VM sem nunca imprimi-la. O sucesso só vale com o marcador SMOKE_OK.
set -Eeuo pipefail

DIR="${STICK_WORD_GROUP_DIR:-/opt/stick-word-group}"
ESPERA_MAXIMA="${ESPERA_MAXIMA:-180}"
INTERVALO="${INTERVALO:-5}"

cd "$DIR/app"

# --- o bot ---
prazo=$((SECONDS + ESPERA_MAXIMA))
bot=""
# O `</dev/null` é porque o `docker compose exec` lê o stdin, que aqui é este próprio script.
until bot="$(docker compose --env-file "$DIR/.env" exec -T bot python -c \
  "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).read().decode())" \
  </dev/null 2>/dev/null)"; do
  if ((SECONDS >= prazo)); then
    break
  fi
  echo "aguardando o bot..."
  sleep "$INTERVALO"
done
docker compose --env-file "$DIR/.env" ps
echo "bot /health: ${bot:-indisponível}"
[[ -n "$bot" ]]

# --- a sessão do WAHA ---
chave="$(grep '^WAHA_API_KEY=' "$DIR/.env" | cut -d= -f2-)"
prazo=$((SECONDS + ESPERA_MAXIMA))
status=""
while :; do
  status="$(curl -fsS -H "X-Api-Key: $chave" http://127.0.0.1:3000/api/sessions/default 2>/dev/null |
    python3 -c 'import sys, json; print(json.load(sys.stdin)["status"])' 2>/dev/null)" || status="indisponível"
  if [[ "$status" == "WORKING" ]] || ((SECONDS >= prazo)); then
    break
  fi
  echo "aguardando a sessão do WAHA ($status)..."
  sleep "$INTERVALO"
done
echo "sessão do WAHA: $status"
[[ "$status" == "WORKING" ]]
echo SMOKE_OK
