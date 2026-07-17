#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

SCRIPT_DIRECTORY="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=staging-lib.sh
source "$SCRIPT_DIRECTORY/staging-lib.sh"

require_command docker
require_command jq
load_staging_environment
validate_staging_environment

mode="${1:-}"
state_file="${2:-}"
[[ "$mode" == "--capture" || "$mode" == "--verify" ]] \
  || die "usage: $0 --capture|--verify STATE_FILE"
[[ -n "$state_file" ]] || die "a persistence state file is required"

state_sql="$(cat <<'SQL'
SELECT json_build_object(
  'alembic_revision', (SELECT version_num FROM alembic_version),
  'users', (SELECT count(*) FROM users),
  'books', (SELECT count(*) FROM books),
  'editions', (SELECT count(*) FROM book_editions),
  'edition_files', (SELECT count(*) FROM edition_files),
  'stored_files', (SELECT count(*) FROM stored_files),
  'series', (SELECT count(*) FROM book_series),
  'series_memberships', (SELECT count(*) FROM series_memberships),
  'reading_progresses', (SELECT count(*) FROM reading_progresses),
  'reader_settings', (SELECT count(*) FROM reader_settings),
  'preferences', (SELECT count(*) FROM user_book_preferences),
  'reader_credentials', (SELECT count(*) FROM reader_access_credentials),
  'admin_passkeys', (SELECT count(*) FROM admin_passkeys),
  'devices', (SELECT count(*) FROM devices),
  'sessions', (SELECT count(*) FROM auth_sessions),
  'site_settings', (SELECT count(*) FROM site_settings),
  'audit_events', (SELECT count(*) FROM auth_audit_events),
  'identity_fingerprint', md5(
    coalesce((SELECT string_agg(id::text || ':' || role::text || ':' || status::text,
      ',' ORDER BY id) FROM users), '') || '|' ||
    coalesce((SELECT string_agg(id::text || ':' || status::text || ':' || user_id::text,
      ',' ORDER BY id) FROM reader_access_credentials), '') || '|' ||
    coalesce((SELECT string_agg(id::text || ':' || user_id::text || ':' ||
      (revoked_at IS NOT NULL)::text, ',' ORDER BY id) FROM admin_passkeys), '')
  ),
  'library_fingerprint', md5(
    coalesce((SELECT string_agg(id::text || ':' || owner_user_id::text || ':' || sha256,
      ',' ORDER BY id) FROM stored_files), '') || '|' ||
    coalesce((SELECT string_agg(id::text || ':' || owner_user_id::text,
      ',' ORDER BY id) FROM books), '') || '|' ||
    coalesce((SELECT string_agg(id::text || ':' || book_id::text || ':' || status::text,
      ',' ORDER BY id) FROM book_editions), '')
  ),
  'reader_state_fingerprint', md5(
    coalesce((SELECT string_agg(user_id::text || ':' || edition_id::text || ':' || version::text ||
      ':' || overall_progress::text, ',' ORDER BY user_id, edition_id)
      FROM reading_progresses), '') || '|' ||
    coalesce((SELECT string_agg(user_id::text || ':' || font_size::text || ':' || theme::text,
      ',' ORDER BY user_id) FROM reader_settings), '') || '|' ||
    coalesce((SELECT string_agg(user_id::text || ':' || book_id::text || ':' ||
      coalesce(preferred_edition_id::text, '') || ':' ||
      coalesce(last_opened_edition_id::text, ''), ',' ORDER BY user_id, book_id)
      FROM user_book_preferences), '')
  )
)::text;
SQL
)"

current_state="$(compose exec -T postgres sh -c \
  'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"' \
  sh "$state_sql")"
jq -e . >/dev/null <<<"$current_state" || die "database persistence state is invalid"

if [[ "$mode" == "--capture" ]]; then
  mkdir -p "$(dirname "$state_file")"
  jq -S . <<<"$current_state" >"$state_file"
  chmod 600 "$state_file"
  printf 'staging persistence baseline captured\n'
  exit 0
fi

[[ -f "$state_file" ]] || die "staging persistence baseline is unavailable"
expected_state="$(jq -S -c . "$state_file")"
actual_state="$(jq -S -c . <<<"$current_state")"
[[ "$actual_state" == "$expected_state" ]] || die "staging persistence fingerprint changed"
compose exec -T server novel-platform auth migration audit >/dev/null
printf 'staging persistence fingerprint PASS\n'
