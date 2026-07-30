#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

ACCEPTANCE_DIRECTORY="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
STAGING_DIRECTORY="$(CDPATH= cd -- "$ACCEPTANCE_DIRECTORY/../staging" && pwd)"
# shellcheck source=../staging/staging-lib.sh
source "$STAGING_DIRECTORY/staging-lib.sh"

load_staging_environment
validate_staging_environment

report_directory="${STAGING_REPORT_DIR:-$STAGING_ROOT/reports}"
report_file="$report_directory/persistence-v050.json"
state_file="$report_directory/persistence-v050-state.json"
mkdir -p "$report_directory"

verify_state() {
  "$STAGING_DIRECTORY/reports/verify-staging-persistence-state.sh" --verify "$state_file"
}

wait_for_stack() {
  wait_for_postgres 180
  wait_for_url "$PUBLIC_BASE_URL/healthz" 180
  verify_state
}

"$STAGING_DIRECTORY/reports/verify-staging-persistence-state.sh" --capture "$state_file"
verify_state
compose restart server
wait_for_stack
api_restart="PASS"

if [[ "$LINGUASPINDLE_ENABLED" == "true" ]]; then
  compose restart provider-relay
  wait_for_stack
fi

compose restart postgres
wait_for_stack
postgres_restart="PASS"

compose stop
compose start
wait_for_stack
compose_restart="PASS"

recreate_services=(server web)
if [[ "$LINGUASPINDLE_ENABLED" == "true" ]]; then
  recreate_services+=(provider-relay)
fi
compose up --detach --force-recreate --no-deps "${recreate_services[@]}"
wait_for_stack
compose_recreate="PASS"

cat >"$report_file" <<EOF
{
  "completed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "api_container_restart": "$api_restart",
  "postgres_container_restart": "$postgres_restart",
  "compose_stop_start": "$compose_restart",
  "compose_application_recreate": "$compose_recreate",
  "database_and_library_integrity": "PASS",
  "state_fingerprint_file": "persistence-v050-state.json",
  "volume_deleted": false
}
EOF
chmod 600 "$report_file"

printf 'staging persistence acceptance PASS\n'
printf 'report=%s\n' "$report_file"
