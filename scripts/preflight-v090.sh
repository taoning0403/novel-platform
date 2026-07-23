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
wait_for_postgres 120

report_file="${1:-${STAGING_REPORT_DIR:-$STAGING_ROOT/reports}/v090-migration-preflight-$(date -u +%Y%m%dT%H%M%SZ).json}"
mkdir -p "$(dirname "$report_file")"

read_only_counts_sql="
WITH counts AS (
  SELECT
    (SELECT version_num FROM alembic_version) AS revision,
    (SELECT count(*) FROM site_settings) AS site_count,
    (SELECT count(*) FROM users WHERE role = 'admin') AS admin_count,
    (SELECT count(*) FROM site_settings
      WHERE id = 1 AND library_owner_user_id IS NOT NULL) AS owner_present,
    (SELECT count(*) FROM site_settings
      WHERE id = 1 AND migration_completed_at IS NOT NULL) AS conversion_complete,
    (SELECT count(*) FROM users u JOIN site_settings s ON s.library_owner_user_id = u.id
      WHERE s.id = 1 AND u.role = 'admin') AS owner_is_admin,
    (SELECT count(*) FROM books) AS books_total,
    (SELECT count(*) FROM book_editions) AS editions_total,
    (SELECT count(*) FROM book_editions be
      WHERE NOT EXISTS (SELECT 1 FROM edition_files ef WHERE ef.edition_id = be.id))
      AS fileless_editions_to_delete,
    (SELECT count(*) FROM books b
      WHERE NOT EXISTS (
        SELECT 1 FROM book_editions be
        JOIN edition_files ef ON ef.edition_id = be.id
        WHERE be.book_id = b.id
      )) AS books_to_delete,
    (SELECT count(*) FROM stored_files) AS stored_files_total,
    (SELECT count(*) FROM library_imports) AS imports_total,
    (SELECT count(*) FROM library_imports WHERE status IN ('pending', 'processing', 'ready'))
      AS active_imports,
    (SELECT count(*) FROM reader_access_credentials) AS credentials_to_backfill_read,
    (SELECT count(*) FROM reading_progresses rp
      WHERE NOT EXISTS (SELECT 1 FROM edition_files ef WHERE ef.edition_id = rp.edition_id))
      AS progresses_to_delete,
    (SELECT count(*) FROM user_book_preferences ubp
      WHERE ubp.preferred_edition_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM edition_files ef WHERE ef.edition_id = ubp.preferred_edition_id))
      AS preferred_links_to_clear,
    (SELECT count(*) FROM user_book_preferences ubp
      WHERE ubp.last_opened_edition_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM edition_files ef WHERE ef.edition_id = ubp.last_opened_edition_id))
      AS last_opened_links_to_clear,
    (SELECT
       (SELECT count(*) FROM books b, site_settings s
         WHERE s.id = 1 AND b.owner_user_id <> s.library_owner_user_id)
       + (SELECT count(*) FROM stored_files sf, site_settings s
         WHERE s.id = 1 AND sf.owner_user_id <> s.library_owner_user_id)
       + (SELECT count(*) FROM library_imports li, site_settings s
         WHERE s.id = 1 AND li.owner_user_id <> s.library_owner_user_id)
       + (SELECT count(*) FROM book_series bs, site_settings s
         WHERE s.id = 1 AND bs.owner_user_id <> s.library_owner_user_id)) AS owner_mismatches,
    (SELECT count(*)
      FROM edition_files ef
      LEFT JOIN stored_files sf ON sf.id = ef.stored_file_id
      LEFT JOIN stored_files nf ON nf.id = ef.normalized_stored_file_id
      LEFT JOIN site_settings s ON s.id = 1
      WHERE sf.id IS NULL OR sf.owner_user_id <> s.library_owner_user_id
        OR (ef.normalized_stored_file_id IS NOT NULL AND nf.id IS NULL)
        OR (nf.id IS NOT NULL AND nf.owner_user_id <> s.library_owner_user_id))
      AS file_reference_anomalies,
    (SELECT count(*) FROM (
      SELECT ef.edition_id FROM edition_files ef GROUP BY ef.edition_id
      HAVING count(*) FILTER (WHERE ef.is_current) <> 1
    ) invalid) AS current_file_anomalies
)
SELECT jsonb_pretty(jsonb_build_object(
  'version', '0.9.0',
  'generated_at_utc', to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'),
  'alembic_revision', revision,
  'site_settings_rows', site_count,
  'administrator_rows', admin_count,
  'library_owner_present', owner_present = 1,
  'v050_conversion_complete', conversion_complete = 1,
  'library_owner_is_unique_admin', owner_is_admin = 1 AND admin_count = 1,
  'books_total', books_total,
  'editions_total', editions_total,
  'fileless_editions_to_delete', fileless_editions_to_delete,
  'books_to_delete', books_to_delete,
  'stored_files_total', stored_files_total,
  'imports_total', imports_total,
  'active_imports', active_imports,
  'credentials_to_backfill_library_read', credentials_to_backfill_read,
  'reading_progress_rows_to_delete', progresses_to_delete,
  'preferred_links_to_clear', preferred_links_to_clear,
  'last_opened_links_to_clear', last_opened_links_to_clear,
  'owner_mismatches', owner_mismatches,
  'file_reference_anomalies', file_reference_anomalies,
  'current_file_anomalies', current_file_anomalies,
  'safe_to_migrate', revision = '20260715_0005'
    AND site_count = 1 AND admin_count = 1 AND owner_present = 1
    AND conversion_complete = 1 AND owner_is_admin = 1
    AND active_imports = 0 AND owner_mismatches = 0
    AND file_reference_anomalies = 0 AND current_file_anomalies = 0
)) FROM counts
"

compose exec -T postgres sh -c \
  'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"' \
  sh "$read_only_counts_sql" >"$report_file"
[[ -s "$report_file" ]] || die "v0.9 preflight produced an empty report"
chmod 600 "$report_file"

safe_to_migrate="$(python3 - "$report_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    report = json.load(source)
print("true" if report.get("safe_to_migrate") is True else "false")
PY
)"
[[ "$safe_to_migrate" == "true" ]] \
  || die "v0.9 migration preflight failed; inspect the restricted count-only report"

printf 'v0.9 migration preflight PASS\n'
printf 'report=%s\n' "$report_file"
