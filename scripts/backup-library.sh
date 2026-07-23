#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

SCRIPT_DIRECTORY="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=staging-lib.sh
source "$SCRIPT_DIRECTORY/staging-lib.sh"

require_command docker
require_command python3
load_staging_environment
validate_staging_environment

backup_root="${1:-${STAGING_BACKUP_DIR:-$STAGING_ROOT/data/backups}}"
mkdir -p "$backup_root"
chmod 700 "$backup_root"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
base_name="novel-platform-v090-${timestamp}"
temporary_directory="$backup_root/.${base_name}.tmp"
backup_directory="$backup_root/$base_name"
database_file="$temporary_directory/database.dump"
library_file="$temporary_directory/library.tar.gz"
manifest_file="$temporary_directory/manifest.json"
expected_permanent_files="$temporary_directory/.expected-permanent-files"
expected_temporary_files="$temporary_directory/.expected-temporary-files"
application_stopped=0
server_was_running=0
web_was_running=0

[[ -n "$(compose ps --status running -q server 2>/dev/null)" ]] && server_was_running=1
[[ -n "$(compose ps --status running -q web 2>/dev/null)" ]] && web_was_running=1

restart_previous_application() {
  local services=()
  (( server_was_running )) && services+=(server)
  (( web_was_running )) && services+=(web)
  if (( ${#services[@]} )); then
    compose up --detach --no-deps "${services[@]}" >/dev/null
  fi
}

cleanup() {
  rm -rf "$temporary_directory"
  if (( application_stopped )) && [[ "${BACKUP_LEAVE_APPLICATION_STOPPED:-0}" != "1" ]]; then
    restart_previous_application >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

[[ ! -e "$temporary_directory" && ! -e "$backup_directory" ]] \
  || die "backup destination already exists"
mkdir -p "$temporary_directory"
chmod 700 "$temporary_directory"

wait_for_postgres 120
application_stopped=1
compose stop web server >/dev/null

compose exec -T postgres sh -c \
  'exec pg_dump --format=custom --compress=6 --no-owner --no-acl --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
  >"$database_file"
[[ -s "$database_file" ]] || die "pg_dump produced an empty backup"
compose exec -T postgres pg_restore --list <"$database_file" >/dev/null

compose run --rm --no-deps --entrypoint tar server -C /data/library -czf - . \
  >"$library_file"
[[ -s "$library_file" ]] || die "library archive is empty"
tar -tzf "$library_file" >/dev/null
validate_library_archive "$library_file"

has_stored_files="$(compose exec -T postgres sh -c \
  'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
    "SELECT to_regclass('\''public.stored_files'\'') IS NOT NULL"')"
if [[ "$has_stored_files" == "t" ]]; then
  compose exec -T postgres sh -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -AtF "|" -c \
      "SELECT storage_key, sha256 FROM stored_files ORDER BY storage_key"' \
    >"$expected_permanent_files"
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
    >"$expected_temporary_files"
else
  : >"$expected_permanent_files"
  : >"$expected_temporary_files"
fi

python3 - "$library_file" "$expected_permanent_files" "$expected_temporary_files" <<'PY'
import hashlib
import sys
import tarfile
from pathlib import Path, PurePosixPath


def expected(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        key, checksum = line.split("|", 1)
        if key in values and values[key] != (checksum or None):
            raise SystemExit("database contains conflicting library object references")
        values[key] = checksum or None
    return values


permanent = {}
temporary = {}
with tarfile.open(sys.argv[1], mode="r:gz") as archive:
    for member in archive:
        if not member.isfile():
            continue
        parts = PurePosixPath(member.name).parts
        source = archive.extractfile(member)
        if source is None:
            raise SystemExit("library archive object cannot be read")
        digest = hashlib.sha256()
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
        checksum = digest.hexdigest()
        if len(parts) == 4 and parts[0] == "files":
            permanent[parts[3]] = checksum
        elif len(parts) == 2 and parts[0] == "tmp":
            temporary[parts[1]] = checksum

expected_permanent = expected(sys.argv[2])
expected_temporary = expected(sys.argv[3])
if permanent != expected_permanent:
    raise SystemExit("library archive permanent files differ from the database")
for key, checksum in expected_temporary.items():
    actual = temporary.get(key)
    if actual is None or (checksum is not None and actual != checksum):
        raise SystemExit("library archive is missing a referenced temporary file")
PY
rm -f "$expected_permanent_files" "$expected_temporary_files"

database_sha256="$(sha256_file "$database_file")"
library_sha256="$(sha256_file "$library_file")"
database_version="$(compose exec -T postgres sh -c \
  'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SHOW server_version"')"
revision="$(database_revision)"
git_commit="$(git -C "$REPOSITORY_ROOT" rev-parse HEAD 2>/dev/null || printf 'unknown')"
application_version="$(python3 - "$REPOSITORY_ROOT/apps/server/pyproject.toml" <<'PY'
import sys
import re
from pathlib import Path

content = Path(sys.argv[1]).read_text()
project = content.split("[project]", 1)[1].split("\n[", 1)[0]
match = re.search(r'^version\s*=\s*"([^"]+)"\s*$', project, re.MULTILINE)
if match is None:
    raise SystemExit("project version is missing")
print(match.group(1))
PY
)"

python3 - "$manifest_file" "$application_version" "$timestamp" "$git_commit" \
  "$database_version" "$revision" "$database_sha256" "$library_sha256" <<'PY'
import json
import sys
from pathlib import Path

(
    manifest_path,
    application_version,
    created_at,
    git_commit,
    postgresql_version,
    alembic_revision,
    database_sha256,
    library_sha256,
) = sys.argv[1:]
manifest = {
    "application_version": application_version,
    "created_at_utc": created_at,
    "git_commit": git_commit,
    "postgresql_version": postgresql_version,
    "alembic_revision": alembic_revision,
    "scope": {
        "included": ["novel_platform_postgresql", "novel_platform_library"],
        "excluded": [
            "linguaspindle_sqlite",
            "linguaspindle_artifacts",
            "linguaspindle_containers",
            "linguaspindle_networks",
        ],
    },
    "database": {"filename": "database.dump", "sha256": database_sha256},
    "library": {"filename": "library.tar.gz", "sha256": library_sha256},
}
Path(manifest_path).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
PY

chmod 600 "$database_file" "$library_file" "$manifest_file"
mv "$temporary_directory" "$backup_directory"
if [[ "${BACKUP_LEAVE_APPLICATION_STOPPED:-0}" != "1" ]]; then
  restart_previous_application
fi
application_stopped=0
trap - EXIT

printf 'Library backup PASS\n'
printf 'backup=%s\n' "$backup_directory"
printf 'manifest=%s\n' "$backup_directory/manifest.json"
