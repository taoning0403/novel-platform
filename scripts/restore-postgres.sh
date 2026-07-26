#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

SCRIPT_DIRECTORY="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=staging-lib.sh
source "$SCRIPT_DIRECTORY/staging-lib.sh"

usage() {
  cat >&2 <<EOF
usage:
  $0 --test BACKUP_FILE [REPORT_FILE]
  ALLOW_STAGING_RESTORE=1 $0 --staging BACKUP_FILE --confirm DATABASE_NAME

--test restores into a temporary database and always removes that database.
--staging is destructive, creates a safety backup first, never runs Alembic downgrade,
and requires the exact live database name after --confirm.
EOF
  exit 2
}

mode="${1:-}"
backup_file="${2:-}"
[[ "$mode" == "--test" || "$mode" == "--staging" ]] || usage
[[ -n "$backup_file" && -f "$backup_file" ]] || usage

require_command docker
load_staging_environment
validate_staging_environment
wait_for_postgres 120

checksum_file="$backup_file.sha256"
if [[ -f "$checksum_file" ]]; then
  expected="$(awk 'NR == 1 {print $1}' "$checksum_file")"
  actual="$(sha256_file "$backup_file")"
  [[ "$actual" == "$expected" ]] || die "backup checksum mismatch"
fi
compose exec -T postgres pg_restore --list <"$backup_file" >/dev/null

restore_into_database() {
  local database_name="$1"
  compose exec -T postgres sh -c \
    'exec pg_restore --exit-on-error --no-owner --no-acl --username="$POSTGRES_USER" --dbname="$1"' \
    sh "$database_name" <"$backup_file"
}

query_database() {
  local database_name="$1"
  local query="$2"
  compose exec -T postgres sh -c \
    'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atc "$2"' \
    sh "$database_name" "$query"
}

if [[ "$mode" == "--test" ]]; then
  report_file="${3:-${STAGING_REPORT_DIR:-$STAGING_ROOT/reports}/restore-test-report.md}"
  temporary_database="novel_restore_$(date -u +%Y%m%d%H%M%S)_$RANDOM"
  [[ "$temporary_database" =~ ^[a-z0-9_]+$ ]] || die "invalid temporary database name"
  cleanup_database() {
    compose exec -T postgres dropdb --if-exists --force --username="$POSTGRES_USER" "$temporary_database" >/dev/null 2>&1 || true
  }
  trap cleanup_database EXIT
  compose exec -T postgres createdb --username="$POSTGRES_USER" "$temporary_database"
  restore_into_database "$temporary_database"

  users="$(query_database "$temporary_database" 'SELECT count(*) FROM users')"
  books="$(query_database "$temporary_database" 'SELECT count(*) FROM books')"
  editions="$(query_database "$temporary_database" 'SELECT count(*) FROM book_editions')"
  preferences="$(query_database "$temporary_database" 'SELECT count(*) FROM user_book_preferences')"
  revision="$(query_database "$temporary_database" 'SELECT version_num FROM alembic_version')"
  (( users > 0 )) || die "restored database contains no users"
  (( books > 0 )) || die "restored database contains no Books"
  (( editions > 0 )) || die "restored database contains no Editions"
  (( preferences > 0 )) || die "restored database contains no preferences"
  expected_head="$(code_head_revision)"
  [[ "$revision" == "$expected_head" ]] || die "restored revision does not match code head"
  mkdir -p "$(dirname "$report_file")"
  cat >"$report_file" <<EOF
# Novel Platform v0.9.0 temporary restore test

- Status: **PASS**
- Completed: $(date -u +%Y-%m-%dT%H:%M:%SZ)
- Environment: staging restore isolation
- Source backup: $(basename "$backup_file")
- Checksum verified: $([[ -f "$checksum_file" ]] && printf 'yes' || printf 'not provided')
- Temporary database removed after verification: yes
- Alembic revision: $revision
- Users present: $users
- Books present: $books
- Editions present: $editions
- Preferences present: $preferences

The live staging database was not overwritten, dropped, emptied, or downgraded.
EOF
  chmod 600 "$report_file"
  cleanup_database
  trap - EXIT
  printf 'temporary restore test PASS\n'
  printf 'report=%s\n' "$report_file"
  exit 0
fi

[[ "${ALLOW_STAGING_RESTORE:-0}" == "1" ]] \
  || die "set ALLOW_STAGING_RESTORE=1 for an intentional live restore"
[[ "${3:-}" == "--confirm" && "${4:-}" == "$POSTGRES_DB" ]] \
  || die "live restore requires --confirm followed by the exact POSTGRES_DB value"

"$SCRIPT_DIRECTORY/backup-postgres.sh"
restore_services=(web server)
if [[ "$LINGUASPINDLE_ENABLED" == "true" ]]; then
  restore_services+=(provider-relay)
fi
compose stop "${restore_services[@]}"
compose exec -T postgres dropdb --if-exists --force --username="$POSTGRES_USER" "$POSTGRES_DB"
compose exec -T postgres createdb --username="$POSTGRES_USER" "$POSTGRES_DB"
restore_into_database "$POSTGRES_DB"
restored_revision="$(database_revision)"
expected_head="$(code_head_revision)"
[[ "$restored_revision" == "$expected_head" ]] \
  || die "restored database revision differs from code head; application remains stopped"
if [[ "$LINGUASPINDLE_ENABLED" == "true" ]]; then
  compose up --detach --no-deps provider-relay
fi
compose up --detach --no-deps server web
"$SCRIPT_DIRECTORY/healthcheck-staging.sh"
printf 'live staging restore PASS\n'
