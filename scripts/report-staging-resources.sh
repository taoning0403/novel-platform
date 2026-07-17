#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

SCRIPT_DIRECTORY="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=staging-lib.sh
source "$SCRIPT_DIRECTORY/staging-lib.sh"

load_staging_environment
validate_staging_environment
label="${1:-snapshot}"
[[ "$label" =~ ^[A-Za-z0-9_-]+$ ]] || die "resource snapshot label contains invalid characters"
report="${STAGING_REPORT_DIR:-$STAGING_ROOT/reports}/resource-usage-v050.md"
mkdir -p "$(dirname "$report")"

if [[ ! -f "$report" ]]; then
  cat >"$report" <<'EOF'
# Novel Platform v0.5.0 staging resource usage

Environment: staging. Values below contain no environment variables, credentials, request
headers, Cookies, or database connection strings.
EOF
fi

{
  printf '\n## %s — %s\n\n' "$label" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '### free -h\n\n```text\n'
  free -h
  printf '```\n\n### swapon --show\n\n```text\n'
  swapon --show
  printf '```\n\n### df -h /\n\n```text\n'
  df -h /
  printf '```\n\n### docker stats --no-stream\n\n```text\n'
  docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}\t{{.PIDs}}'
  printf '```\n\n### docker system df\n\n```text\n'
  docker system df
  printf '```\n\n### container health\n\n```text\n'
  for service in postgres server web; do
    container_id="$(compose ps -q "$service")"
    docker inspect --format '{{.Name}} running={{.State.Running}} restart_count={{.RestartCount}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id"
  done
  printf '```\n'
} >>"$report"
chmod 600 "$report"

printf 'resource snapshot recorded\n'
printf 'report=%s\n' "$report"
