#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

SCRIPT_DIRECTORY="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=staging-lib.sh
source "$SCRIPT_DIRECTORY/staging-lib.sh"

skip_backup=false
if [[ "${1:-}" == "--skip-backup" ]]; then
  skip_backup=true
elif [[ $# -gt 0 ]]; then
  die "usage: $0 [--skip-backup]"
fi

require_command curl
require_command docker
require_command git
load_staging_environment
validate_staging_environment

[[ -f "$STAGING_COMPOSE_FILE" ]] || die "staging Compose file not found"
if [[ "${ALLOW_DIRTY_STAGING_DEPLOY:-0}" != "1" ]]; then
  git -C "$REPOSITORY_ROOT" diff --quiet --ignore-submodules -- \
    || die "tracked working tree changes must be committed before staging deployment"
  git -C "$REPOSITORY_ROOT" diff --cached --quiet --ignore-submodules -- \
    || die "staged changes must be committed before staging deployment"
fi

mkdir -p \
  "${STAGING_POSTGRES_DATA_DIR:-$STAGING_ROOT/data/postgres}" \
  "${STAGING_LIBRARY_DATA_DIR:-$STAGING_ROOT/data/library}" \
  "${STAGING_BACKUP_DIR:-$STAGING_ROOT/data/backups}" \
  "${STAGING_REPORT_DIR:-$STAGING_ROOT/reports}" \
  "$STAGING_ROOT/logs"
chmod 700 "${STAGING_BACKUP_DIR:-$STAGING_ROOT/data/backups}"

compose config --quiet
printf 'Building immutable staging images...\n'
compose build migrate server web

printf 'Starting PostgreSQL only...\n'
compose up --detach postgres
wait_for_postgres 180

has_revision_table="$(compose exec -T postgres sh -c \
  'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT to_regclass('\''public.alembic_version'\'') IS NOT NULL"')"
if [[ "$has_revision_table" == "t" && "$skip_backup" == "false" ]]; then
  BACKUP_LEAVE_APPLICATION_STOPPED=1 "$SCRIPT_DIRECTORY/backup-library.sh"
fi

# Ephemeral server tasks share the service's fixed network addresses, so stop the existing
# application before running them. A validation or migration failure intentionally leaves the
# public application stopped.
compose stop web server >/dev/null 2>&1 || true
printf 'Validating private library storage permissions...\n'
compose run --rm --no-deps --entrypoint python server -c \
  'from novel_platform.api.dependencies.storage import get_file_storage; get_file_storage().initialize()'

before_revision="$(database_revision)"
printf 'Database revision before migration: %s\n' "${before_revision:-base}"
printf 'Applying Alembic migrations...\n'
compose up --no-deps --abort-on-container-exit --exit-code-from migrate migrate

head_revision="$(code_head_revision)"
after_revision="$(database_revision)"
[[ -n "$head_revision" ]] || die "could not determine the code Alembic head"
[[ "$after_revision" == "$head_revision" ]] \
  || die "database revision $after_revision does not match code head $head_revision"

initialized_users="$(compose exec -T postgres sh -c \
  'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
    "SELECT count(*) FROM users WHERE status <> '\''pending_setup'\''"')"
migration_completed="$(compose exec -T postgres sh -c \
  'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
    "SELECT migration_completed_at IS NOT NULL FROM site_settings WHERE id=1"')"
preflight_file="${STAGING_REPORT_DIR:-$STAGING_ROOT/reports}/v050-migration-preflight-$(date -u +%Y%m%dT%H%M%SZ).json"
compose run --rm --no-deps --entrypoint novel-platform server auth migration preflight \
  >"$preflight_file"
chmod 600 "$preflight_file"
if (( initialized_users > 0 )) && [[ "$migration_completed" != "t" ]]; then
  conversion=(auth migration convert)
  if [[ -n "${V050_TARGET_ADMIN_ID:-}" ]]; then
    conversion+=(--target-admin-id "$V050_TARGET_ADMIN_ID")
  fi
  if [[ -n "${V050_MAP_ADMIN_TO_READER_IDS:-}" ]]; then
    IFS=',' read -r -a mapped_admins <<<"$V050_MAP_ADMIN_TO_READER_IDS"
    for mapped_admin in "${mapped_admins[@]}"; do
      [[ -n "$mapped_admin" ]] && conversion+=(--map-admin-to-reader "$mapped_admin")
    done
  fi
  compose run --rm --no-deps --entrypoint novel-platform server "${conversion[@]}" >/dev/null
elif (( initialized_users == 0 )); then
  printf 'New database remains pending CLI administrator initialization.\n'
fi
compose run --rm --no-deps --entrypoint novel-platform server auth migration audit >/dev/null

printf 'Starting API and Web...\n'
compose up --detach --no-deps server
server_container="$(compose ps -q server)"
deadline=$((SECONDS + 180))
until [[ "$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$server_container" 2>/dev/null)" == "healthy" ]]; do
  (( SECONDS < deadline )) || die "API container did not become healthy"
  sleep 2
done
compose up --detach --no-deps web
"$SCRIPT_DIRECTORY/healthcheck-staging.sh"

git_commit="$(git -C "$REPOSITORY_ROOT" rev-parse HEAD)"
release_file="${STAGING_REPORT_DIR:-$STAGING_ROOT/reports}/current-release.json"
cat >"$release_file" <<EOF
{
  "environment": "staging",
  "deployed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "git_commit": "$git_commit",
  "alembic_revision": "$after_revision",
  "base_url": "$PUBLIC_BASE_URL"
}
EOF
chmod 600 "$release_file"

printf 'staging deployment PASS\n'
printf 'git_commit=%s\n' "$git_commit"
printf 'alembic_revision=%s\n' "$after_revision"
printf 'base_url=%s\n' "$PUBLIC_BASE_URL"
