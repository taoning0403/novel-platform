#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

SCRIPT_DIRECTORY="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=staging-lib.sh
source "$SCRIPT_DIRECTORY/staging-lib.sh"

usage() {
  cat >&2 <<EOF
usage:
  $0 --test BACKUP_DIRECTORY [REPORT_FILE]
  ALLOW_STAGING_RESTORE=1 $0 --staging BACKUP_DIRECTORY --confirm DATABASE_NAME

--test restores into a temporary database and temporary Docker volume, verifies every
database-referenced file checksum, and removes both isolated resources.
--staging is destructive, creates a complete safety backup first, and requires the exact
live database name after --confirm. It never runs an automatic Alembic downgrade.
EOF
  exit 2
}

mode="${1:-}"
backup_directory="${2:-}"
[[ "$mode" == "--test" || "$mode" == "--staging" ]] || usage
[[ -d "$backup_directory" ]] || usage

database_file="$backup_directory/database.dump"
library_file="$backup_directory/library.tar.gz"
manifest_file="$backup_directory/manifest.json"
[[ -s "$database_file" && -s "$library_file" && -s "$manifest_file" ]] || usage

require_command docker
require_command python3
require_command sort
load_staging_environment
validate_staging_environment
wait_for_postgres 120

manifest_line="$(python3 - "$manifest_file" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text())
print("|".join((
    manifest["database"]["sha256"],
    manifest["library"]["sha256"],
    manifest["alembic_revision"],
)))
PY
)"
IFS='|' read -r database_sha256 library_sha256 manifest_revision <<<"$manifest_line"
[[ -n "$database_sha256" && -n "$library_sha256" && -n "$manifest_revision" ]] \
  || die "backup manifest is incomplete"
[[ "$(sha256_file "$database_file")" == "$database_sha256" ]] \
  || die "database backup checksum mismatch"
[[ "$(sha256_file "$library_file")" == "$library_sha256" ]] \
  || die "library archive checksum mismatch"
compose exec -T postgres pg_restore --list <"$database_file" >/dev/null
tar -tzf "$library_file" >/dev/null
validate_library_archive "$library_file"

restore_database() {
  local database_name="$1"
  compose exec -T postgres sh -c \
    'exec pg_restore --exit-on-error --no-owner --no-acl --username="$POSTGRES_USER" --dbname="$1"' \
    sh "$database_name" <"$database_file"
}

verify_temporary_references() {
  local expected_file="$1"
  local actual_file="$2"
  python3 - "$expected_file" "$actual_file" <<'PY'
import sys
from pathlib import Path


def records(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        key, checksum = line.split("|", 1)
        value = checksum or None
        if key in values and values[key] != value:
            raise SystemExit("restored database contains conflicting temporary file references")
        values[key] = value
    return values


expected = records(sys.argv[1])
actual = records(sys.argv[2])
for key, checksum in expected.items():
    restored_checksum = actual.get(key)
    if restored_checksum is None or (checksum is not None and restored_checksum != checksum):
        raise SystemExit("restored library is missing a referenced temporary file")
PY
}

if [[ "$mode" == "--test" ]]; then
  report_file="${3:-${STAGING_REPORT_DIR:-$STAGING_ROOT/reports}/restore-v090-test-report.md}"
  temporary_database="novel_restore_$(date -u +%Y%m%d%H%M%S)_$RANDOM"
  temporary_volume="novel_restore_${RANDOM}_$(date -u +%s)"
  expected_files="$(mktemp)"
  actual_files="$(mktemp)"
  expected_temporary_files="$(mktemp)"
  actual_temporary_files="$(mktemp)"
  [[ "$temporary_database" =~ ^[a-z0-9_]+$ ]] || die "invalid temporary database name"
  [[ "$temporary_volume" =~ ^[a-z0-9_]+$ ]] || die "invalid temporary volume name"
  cleanup_test_best_effort() {
    compose exec -T postgres dropdb --if-exists --force --username="$POSTGRES_USER" \
      "$temporary_database" >/dev/null 2>&1 || true
    docker volume rm --force "$temporary_volume" >/dev/null 2>&1 || true
    rm -f "$expected_files" "$actual_files" \
      "$expected_temporary_files" "$actual_temporary_files"
  }
  cleanup_test_verified() {
    compose exec -T postgres dropdb --if-exists --force --username="$POSTGRES_USER" \
      "$temporary_database" >/dev/null
    docker volume rm --force "$temporary_volume" >/dev/null
    if docker volume inspect "$temporary_volume" >/dev/null 2>&1; then
      die "temporary restore volume still exists after cleanup"
    fi
    rm -f "$expected_files" "$actual_files" \
      "$expected_temporary_files" "$actual_temporary_files"
  }
  trap cleanup_test_best_effort EXIT

  compose exec -T postgres createdb --username="$POSTGRES_USER" "$temporary_database"
  restore_database "$temporary_database"
  docker volume create "$temporary_volume" >/dev/null
  server_image="$(compose images -q server | head -n 1)"
  [[ -n "$server_image" ]] || die "server image is unavailable"
  docker run --rm --user 0:0 -i -v "$temporary_volume:/restore" "$server_image" \
    tar -C /restore -xzf - <"$library_file"

  compose exec -T postgres sh -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atc \
      "SELECT storage_key || '\'' '\'' || sha256 FROM stored_files ORDER BY storage_key"' \
    sh "$temporary_database" >"$expected_files"
  docker run --rm --user 0:0 -v "$temporary_volume:/restore:ro" "$server_image" \
    python -c 'import hashlib, pathlib; root=pathlib.Path("/restore/files");
def checksum(path):
 digest=hashlib.sha256()
 with path.open("rb") as source:
  for chunk in iter(lambda: source.read(1024 * 1024), b""):
   digest.update(chunk)
 return digest.hexdigest()
for path in sorted(p for p in root.rglob("*") if p.is_file()):
 print(path.name, checksum(path))' \
    >"$actual_files"
  sort -o "$expected_files" "$expected_files"
  sort -o "$actual_files" "$actual_files"
  cmp -s "$expected_files" "$actual_files" || die "restored library checksum set differs"

  compose exec -T postgres sh -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -AtF "|" -c \
      "SELECT value.storage_key, value.sha256
       FROM library_imports AS library_import
       CROSS JOIN LATERAL (VALUES
         (library_import.temporary_storage_key, library_import.sha256),
         (library_import.normalized_temporary_storage_key, NULL::varchar),
         (library_import.cover_temporary_storage_key, NULL::varchar),
         (library_import.cover_thumbnail_temporary_storage_key, NULL::varchar)
       ) AS value(storage_key, sha256)
       WHERE value.storage_key IS NOT NULL
       ORDER BY value.storage_key"' \
    sh "$temporary_database" >"$expected_temporary_files"
  docker run --rm --user 0:0 -v "$temporary_volume:/restore:ro" "$server_image" \
    python -c 'import hashlib, pathlib; root=pathlib.Path("/restore/tmp");
def checksum(path):
 digest=hashlib.sha256()
 with path.open("rb") as source:
  for chunk in iter(lambda: source.read(1024 * 1024), b""):
   digest.update(chunk)
 return digest.hexdigest()
for path in sorted(p for p in root.iterdir() if p.is_file()):
 print(f"{path.name}|{checksum(path)}")' \
    >"$actual_temporary_files"
  verify_temporary_references "$expected_temporary_files" "$actual_temporary_files"

  revision="$(compose exec -T postgres sh -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atc "SELECT version_num FROM alembic_version"' \
    sh "$temporary_database")"
  [[ "$revision" == "$manifest_revision" ]] || die "restored revision differs from manifest"
  users="$(compose exec -T postgres sh -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atc "SELECT count(*) FROM users"' \
    sh "$temporary_database")"
  books="$(compose exec -T postgres sh -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atc "SELECT count(*) FROM books"' \
    sh "$temporary_database")"
  series="$(compose exec -T postgres sh -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atc "SELECT count(*) FROM book_series"' \
    sh "$temporary_database")"
  memberships="$(compose exec -T postgres sh -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atc "SELECT count(*) FROM series_memberships"' \
    sh "$temporary_database")"
  progresses="$(compose exec -T postgres sh -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atc "SELECT count(*) FROM reading_progresses"' \
    sh "$temporary_database")"
  reader_settings="$(compose exec -T postgres sh -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atc "SELECT count(*) FROM reader_settings"' \
    sh "$temporary_database")"
  credentials="$(compose exec -T postgres sh -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atc "SELECT count(*) FROM reader_access_credentials"' \
    sh "$temporary_database")"
  passkeys="$(compose exec -T postgres sh -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atc "SELECT count(*) FROM admin_passkeys"' \
    sh "$temporary_database")"
  devices="$(compose exec -T postgres sh -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atc "SELECT count(*) FROM devices"' \
    sh "$temporary_database")"
  sessions="$(compose exec -T postgres sh -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atc "SELECT count(*) FROM auth_sessions"' \
    sh "$temporary_database")"
  site_settings="$(compose exec -T postgres sh -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atc "SELECT count(*) FROM site_settings"' \
    sh "$temporary_database")"
  audit_events="$(compose exec -T postgres sh -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atc "SELECT count(*) FROM auth_audit_events"' \
    sh "$temporary_database")"
  credential_capabilities="$(compose exec -T postgres sh -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atc "SELECT count(*) FROM reader_credential_capabilities"' \
    sh "$temporary_database")"
  translation_runs="$(compose exec -T postgres sh -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atc "SELECT count(*) FROM edition_translation_runs"' \
    sh "$temporary_database")"
  missing_attribution="$(compose exec -T postgres sh -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atc \
      "SELECT (SELECT count(*) FROM books WHERE created_by_user_id IS NULL) +
              (SELECT count(*) FROM book_editions WHERE created_by_user_id IS NULL) +
              (SELECT count(*) FROM stored_files WHERE created_by_user_id IS NULL) +
              (SELECT count(*) FROM library_imports WHERE requested_by_user_id IS NULL)"' \
    sh "$temporary_database")"
  credentials_without_read="$(compose exec -T postgres sh -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -Atc \
      "SELECT count(*) FROM reader_access_credentials rac
       WHERE NOT EXISTS (
         SELECT 1 FROM reader_credential_capabilities rcc
         WHERE rcc.credential_id = rac.id AND rcc.capability = '\''library.read'\''
       )"' \
    sh "$temporary_database")"
  (( missing_attribution == 0 )) || die "restored v0.9 content contains missing contributor attribution"
  (( credentials_without_read == 0 )) || die "restored credential is missing library.read"
  stored_files="$(wc -l <"$expected_files" | tr -d ' ')"
  temporary_files="$(wc -l <"$expected_temporary_files" | tr -d ' ')"
  cleanup_test_verified
  trap - EXIT
  mkdir -p "$(dirname "$report_file")"
  cat >"$report_file" <<EOF
# Novel Platform v0.9.0 isolated restore test

- Status: **PASS**
- Completed: $(date -u +%Y-%m-%dT%H:%M:%SZ)
- Source backup: $(basename "$backup_directory")
- Temporary database removed after verification: yes
- Temporary storage volume removed after verification: yes
- Database and archive checksums verified: yes
- Every database-referenced stored file checksum verified: yes
- Every database-referenced temporary file restored: yes
- Alembic revision: $revision
- Users present: $users
- Books present: $books
- Series present: $series
- Series memberships present: $memberships
- Reading progresses present: $progresses
- Reader settings present: $reader_settings
- Reader credentials present: $credentials
- Administrator Passkeys present: $passkeys
- Device authorizations present: $devices
- Authentication sessions present: $sessions
- Site settings rows present: $site_settings
- Security audit events present: $audit_events
- Credential capability rows present: $credential_capabilities
- Translation runs present: $translation_runs
- Missing contributor attribution rows: $missing_attribution
- Credentials missing library.read: $credentials_without_read
- Stored files verified: $stored_files
- Referenced temporary files verified: $temporary_files

The live staging database and library directory were not overwritten, emptied, or downgraded.
EOF
  chmod 600 "$report_file"
  printf 'isolated database and library restore PASS\n'
  printf 'report=%s\n' "$report_file"
  exit 0
fi

[[ "${ALLOW_STAGING_RESTORE:-0}" == "1" ]] \
  || die "set ALLOW_STAGING_RESTORE=1 for an intentional live restore"
[[ "${3:-}" == "--confirm" && "${4:-}" == "$POSTGRES_DB" ]] \
  || die "live restore requires --confirm followed by the exact POSTGRES_DB value"

expected_head="$(code_head_revision)"
[[ -n "$expected_head" ]] || die "could not determine the code Alembic head"
[[ "$manifest_revision" == "$expected_head" ]] \
  || die "backup revision differs from code head; live restore was not started"

preflight_report="${STAGING_REPORT_DIR:-$STAGING_ROOT/reports}/restore-preflight-$(date -u +%Y%m%dT%H%M%SZ).md"
"$SCRIPT_DIRECTORY/restore-library.sh" --test "$backup_directory" "$preflight_report"
BACKUP_LEAVE_APPLICATION_STOPPED=1 "$SCRIPT_DIRECTORY/backup-library.sh"
compose exec -T postgres dropdb --if-exists --force --username="$POSTGRES_USER" "$POSTGRES_DB"
compose exec -T postgres createdb --username="$POSTGRES_USER" "$POSTGRES_DB"
restore_database "$POSTGRES_DB"
restored_revision="$(database_revision)"
[[ "$restored_revision" == "$expected_head" ]] \
  || die "restored database revision differs from code head; application remains stopped"
compose run --rm --no-deps --entrypoint python server -c \
  'import pathlib, shutil; root=pathlib.Path("/data/library");
[shutil.rmtree(path) if path.is_dir() else path.unlink() for path in list(root.iterdir())]'
compose run --rm --no-deps --entrypoint tar server -C /data/library -xzf - <"$library_file"

live_expected_files="$(mktemp)"
live_actual_files="$(mktemp)"
live_expected_temporary_files="$(mktemp)"
live_actual_temporary_files="$(mktemp)"
cleanup_live_verification() {
  rm -f "$live_expected_files" "$live_actual_files" \
    "$live_expected_temporary_files" "$live_actual_temporary_files"
}
trap cleanup_live_verification EXIT
compose exec -T postgres sh -c \
  'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
    "SELECT storage_key || '\'' '\'' || sha256 FROM stored_files ORDER BY storage_key"' \
  >"$live_expected_files"
compose run --rm --no-deps --entrypoint python server -c \
  'import hashlib, pathlib; root=pathlib.Path("/data/library/files");
def checksum(path):
 digest=hashlib.sha256()
 with path.open("rb") as source:
  for chunk in iter(lambda: source.read(1024 * 1024), b""):
   digest.update(chunk)
 return digest.hexdigest()
for path in sorted(p for p in root.rglob("*") if p.is_file()):
 print(path.name, checksum(path))' \
  >"$live_actual_files"
sort -o "$live_expected_files" "$live_expected_files"
sort -o "$live_actual_files" "$live_actual_files"
cmp -s "$live_expected_files" "$live_actual_files" \
  || die "live restored library checksum set differs; application remains stopped"
compose exec -T postgres sh -c \
  'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -AtF "|" -c \
    "SELECT value.storage_key, value.sha256
     FROM library_imports AS library_import
     CROSS JOIN LATERAL (VALUES
       (library_import.temporary_storage_key, library_import.sha256),
       (library_import.normalized_temporary_storage_key, NULL::varchar),
       (library_import.cover_temporary_storage_key, NULL::varchar),
       (library_import.cover_thumbnail_temporary_storage_key, NULL::varchar)
     ) AS value(storage_key, sha256)
     WHERE value.storage_key IS NOT NULL
     ORDER BY value.storage_key"' \
  >"$live_expected_temporary_files"
compose run --rm --no-deps --entrypoint python server -c \
  'import hashlib, pathlib; root=pathlib.Path("/data/library/tmp");
def checksum(path):
 digest=hashlib.sha256()
 with path.open("rb") as source:
  for chunk in iter(lambda: source.read(1024 * 1024), b""):
   digest.update(chunk)
 return digest.hexdigest()
for path in sorted(p for p in root.iterdir() if p.is_file()):
 print(f"{path.name}|{checksum(path)}")' \
  >"$live_actual_temporary_files"
verify_temporary_references "$live_expected_temporary_files" "$live_actual_temporary_files"
cleanup_live_verification
trap - EXIT

compose up --detach --no-deps server web
"$SCRIPT_DIRECTORY/healthcheck-staging.sh"
printf 'live database and library restore PASS\n'
