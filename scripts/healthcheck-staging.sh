#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIRECTORY="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=staging-lib.sh
source "$SCRIPT_DIRECTORY/staging-lib.sh"

require_command curl
require_command docker
require_command grep
load_staging_environment
validate_staging_environment

healthcheck_base_url="${STAGING_HEALTHCHECK_BASE_URL:-http://127.0.0.1:${STAGING_HTTP_PORT:-8080}}"
wait_for_url "$healthcheck_base_url/healthz" "${STAGING_HEALTH_TIMEOUT_SECONDS:-120}"
wait_for_url "$healthcheck_base_url/api/v1/health/live" "${STAGING_HEALTH_TIMEOUT_SECONDS:-120}"
wait_for_url "$healthcheck_base_url/api/v1/health/ready" "${STAGING_HEALTH_TIMEOUT_SECONDS:-120}"
wait_for_url "$healthcheck_base_url/" "${STAGING_HEALTH_TIMEOUT_SECONDS:-120}"

for service in postgres server web; do
  container_id="$(compose ps -q "$service")"
  [[ -n "$container_id" ]] || die "$service container is missing"
  deadline=$((SECONDS + ${STAGING_HEALTH_TIMEOUT_SECONDS:-120}))
  while true; do
    running="$(docker inspect --format '{{.State.Running}}' "$container_id")"
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id")"
    [[ "$running" == "true" ]] || die "$service container is not running"
    [[ "$health" == "healthy" ]] && break
    [[ "$health" != "unhealthy" ]] || die "$service container is unhealthy"
    (( SECONDS < deadline )) || die "$service container health remained $health"
    sleep 2
  done
done

for private_service in postgres server; do
  container_id="$(compose ps -q "$private_service")"
  published="$(docker inspect --format '{{json .HostConfig.PortBindings}}' "$container_id")"
  [[ "$published" == "null" || "$published" == "{}" ]] || die "$private_service publishes a host port"
done

translation_network="linguaspindle-private"
server_networks="$(docker inspect --format '{{json .NetworkSettings.Networks}}' "$(compose ps -q server)")"
if [[ "$LINGUASPINDLE_ENABLED" == "true" ]]; then
  docker network inspect "$translation_network" >/dev/null
  grep -Fq "\"$translation_network\"" <<<"$server_networks" \
    || die "enabled Server is not attached to linguaspindle-private"
  for excluded_service in postgres web; do
    excluded_networks="$(docker inspect --format '{{json .NetworkSettings.Networks}}' "$(compose ps -q "$excluded_service")")"
    if grep -Fq "\"$translation_network\"" <<<"$excluded_networks"; then
      die "$excluded_service must not join linguaspindle-private"
    fi
  done
else
  if grep -Fq "\"$translation_network\"" <<<"$server_networks"; then
    die "disabled Server unexpectedly remains attached to linguaspindle-private"
  fi
fi

revision="$(database_revision)"
[[ -n "$revision" ]] || die "Alembic revision is unavailable"

printf 'staging healthcheck PASS\n'
printf 'environment=staging\n'
printf 'base_url=%s\n' "$PUBLIC_BASE_URL"
printf 'server_probe_url=%s\n' "$healthcheck_base_url"
printf 'alembic_revision=%s\n' "$revision"
printf 'public_services=web\n'
printf 'private_services=server,postgres\n'
printf 'translation_enabled=%s\n' "$LINGUASPINDLE_ENABLED"
