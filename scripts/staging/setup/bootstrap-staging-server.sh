#!/usr/bin/env bash

set -Eeuo pipefail

[[ "$(id -u)" == "0" ]] || { printf 'ERROR: run this script as root\n' >&2; exit 1; }

phase="${1:-all}"
case "$phase" in
  user|system|all) ;;
  *) printf 'usage: %s [user|system|all]\n' "$0" >&2; exit 2 ;;
esac

create_deploy_user() {
  getent passwd deploy >/dev/null || useradd --create-home --shell /bin/bash deploy
  install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
  [[ -s /root/.ssh/authorized_keys ]] \
    || { printf 'ERROR: /root/.ssh/authorized_keys is unavailable\n' >&2; exit 1; }
  install -m 600 -o deploy -g deploy /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
  usermod -aG docker deploy

  cat >/etc/sudoers.d/90-novel-platform-deploy <<'EOF'
deploy ALL=(root) NOPASSWD: /usr/bin/systemctl status docker, /usr/bin/systemctl restart docker, /usr/bin/systemctl reboot, /usr/sbin/reboot
EOF
  chmod 440 /etc/sudoers.d/90-novel-platform-deploy
  visudo -cf /etc/sudoers.d/90-novel-platform-deploy >/dev/null

  stat -c '%U %G %a %n' /home/deploy/.ssh /home/deploy/.ssh/authorized_keys
  id deploy
}

configure_system() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install --yes ca-certificates curl file git jq postgresql-client python3 rsync ufw

  if ! swapon --show=NAME --noheadings | grep -Fxq /swapfile; then
    if [[ ! -f /swapfile ]]; then
      fallocate -l 2G /swapfile
    fi
    chmod 600 /swapfile
    file /swapfile | grep -q 'swap file' || mkswap /swapfile >/dev/null
    swapon /swapfile
  fi
  grep -Eq '^/swapfile[[:space:]]' /etc/fstab \
    || printf '/swapfile none swap sw 0 0\n' >>/etc/fstab
  printf 'vm.swappiness=10\n' >/etc/sysctl.d/99-novel-platform.conf
  sysctl --system >/dev/null

  install -d -m 755 /etc/docker
  python3 - <<'PY'
import json
from pathlib import Path

path = Path("/etc/docker/daemon.json")
configuration = json.loads(path.read_text()) if path.exists() else {}
configuration["log-driver"] = "json-file"
configuration["log-opts"] = {**configuration.get("log-opts", {}), "max-size": "10m", "max-file": "3"}
temporary = path.with_suffix(".json.tmp")
temporary.write_text(json.dumps(configuration, indent=2, sort_keys=True) + "\n")
temporary.chmod(0o644)
temporary.replace(path)
PY
  dockerd --validate --config-file=/etc/docker/daemon.json >/dev/null
  systemctl restart docker
  systemctl enable docker >/dev/null

  install -d -m 755 -o deploy -g deploy /srv/novel-platform
  install -d -m 755 -o deploy -g deploy /srv/novel-platform/app
  install -d -m 750 -o deploy -g deploy /srv/novel-platform/data
  install -d -m 700 -o deploy -g deploy /srv/novel-platform/data/postgres
  install -d -m 700 -o 10001 -g 10001 /srv/novel-platform/data/library
  install -d -m 700 -o deploy -g deploy /srv/novel-platform/data/backups
  install -d -m 700 -o deploy -g deploy /srv/novel-platform/config
  install -d -m 750 -o deploy -g deploy /srv/novel-platform/logs
  install -d -m 750 -o deploy -g deploy /srv/novel-platform/reports

  ssh_port="$(sshd -T | awk '$1 == "port" && !found {port = $2; found = 1} END {if (found) print port}')"
  [[ "$ssh_port" =~ ^[0-9]+$ ]] || { printf 'ERROR: could not determine SSH port\n' >&2; exit 1; }
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow "$ssh_port/tcp" comment 'SSH'
  ufw allow 80/tcp comment 'Novel Platform staging HTTP'
  ufw allow 443/tcp comment 'Novel Platform staging HTTPS pending'
  ufw --force enable

  free -h
  swapon --show
  ufw status verbose
  docker --version
  docker compose version
  psql --version
}

if [[ "$phase" == "user" || "$phase" == "all" ]]; then
  create_deploy_user
fi
if [[ "$phase" == "system" || "$phase" == "all" ]]; then
  getent passwd deploy >/dev/null \
    || { printf 'ERROR: create and verify deploy login before the system phase\n' >&2; exit 1; }
  configure_system
fi
