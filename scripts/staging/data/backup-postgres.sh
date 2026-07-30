#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

SCRIPT_DIRECTORY="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../staging-lib.sh
source "$SCRIPT_DIRECTORY/../staging-lib.sh"

require_command docker
load_staging_environment
validate_staging_environment

backup_directory="${STAGING_BACKUP_DIR:-$STAGING_ROOT/data/backups}"
mkdir -p "$backup_directory"
chmod 700 "$backup_directory"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
base_name="novel-platform-v090-${timestamp}"
temporary_file="$backup_directory/.${base_name}.dump.tmp"
backup_file="$backup_directory/${base_name}.dump"
checksum_file="$backup_file.sha256"
metadata_file="$backup_file.meta"

cleanup() {
  rm -f "$temporary_file"
}
trap cleanup EXIT

wait_for_postgres 120
compose exec -T postgres sh -c \
  'exec pg_dump --format=custom --compress=6 --no-owner --no-acl --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
  >"$temporary_file"
[[ -s "$temporary_file" ]] || die "pg_dump produced an empty backup"
compose exec -T postgres pg_restore --list <"$temporary_file" >/dev/null

mv "$temporary_file" "$backup_file"
chmod 600 "$backup_file"
checksum="$(sha256_file "$backup_file")"
printf '%s  %s\n' "$checksum" "$(basename "$backup_file")" >"$checksum_file"
chmod 600 "$checksum_file"

database_version="$(compose exec -T postgres sh -c \
  'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SHOW server_version"')"
revision="$(database_revision)"
git_commit="$(git -C "$REPOSITORY_ROOT" rev-parse HEAD 2>/dev/null || printf 'unknown')"
cat >"$metadata_file" <<EOF
created_at_utc=$timestamp
environment=staging
git_commit=$git_commit
postgresql_version=$database_version
alembic_revision=${revision:-base}
format=pg_dump_custom
sha256=$checksum
EOF
chmod 600 "$metadata_file"

printf 'PostgreSQL backup PASS\n'
printf 'backup=%s\n' "$backup_file"
printf 'checksum=%s\n' "$checksum_file"
printf 'metadata=%s\n' "$metadata_file"
