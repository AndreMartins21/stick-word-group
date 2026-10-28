#!/usr/bin/env bash
# Roda como root a cada boot da VM (metadata startup-script). Idempotente.
set -Eeuo pipefail

log() { logger -t stick-word-group-startup "$*"; echo "[stick-word-group-startup] $*"; }

# 1. Swap de 2 GB: a e2-micro tem 1 GB de RAM.
if ! swapon --show=NAME --noheadings | grep -q '/swapfile'; then
  if [[ ! -f /swapfile ]]; then
    log "criando swap de 2 GB"
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
  fi
  swapon /swapfile
fi
grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab

# 2. Docker Engine + plugin do compose (repositório oficial da Docker, Debian 12).
if ! command -v docker >/dev/null 2>&1; then
  log "instalando o Docker"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  # shellcheck source=/dev/null
  codename="$(. /etc/os-release && echo "$VERSION_CODENAME")"
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian ${codename} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

# 3. Rotação dos logs dos containers: o disco é de 30 GB e o log não pode crescer sem limite.
daemon_json='{"log-driver":"json-file","log-opts":{"max-size":"10m","max-file":"3"}}'
if [[ ! -f /etc/docker/daemon.json ]] || [[ "$(cat /etc/docker/daemon.json)" != "$daemon_json" ]]; then
  mkdir -p /etc/docker
  echo "$daemon_json" > /etc/docker/daemon.json
  systemctl restart docker
fi

# 4. Diretório do app e Docker ligado no boot.
mkdir -p /opt/stick-word-group
systemctl enable --now docker
log "pronto"
