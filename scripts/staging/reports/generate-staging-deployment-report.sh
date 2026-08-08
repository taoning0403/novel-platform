#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

SCRIPT_DIRECTORY="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../staging-lib.sh
source "$SCRIPT_DIRECTORY/../staging-lib.sh"

require_command docker
require_command git
require_command jq
load_staging_environment
validate_staging_environment

report_directory="${STAGING_REPORT_DIR:-$STAGING_ROOT/reports}"
deployment_report="$report_directory/deployment-v050-report.md"
action_log="$report_directory/sanitized-v050-action-log.txt"
local_acceptance_json="${STAGING_LOCAL_ACCEPTANCE_JSON:-$report_directory/acceptance-v050.json}"
persistence_json="$report_directory/persistence-v050.json"
restore_report="$report_directory/restore-v050-test-report.md"
leak_json="$report_directory/leak-scan-v050.json"
resource_report="$report_directory/resource-usage-v050.md"
release_json="$report_directory/current-release.json"
mkdir -p "$report_directory"

json_value() {
  local file="$1"
  local query="$2"
  local fallback="$3"
  if [[ -f "$file" ]]; then
    jq -r "$query // \"$fallback\"" "$file"
  else
    printf '%s\n' "$fallback"
  fi
}

local_acceptance_status="$(json_value "$local_acceptance_json" '.status' 'PENDING')"
unit_tests="$(json_value "$local_acceptance_json" '.results.unit_tests' '0')"
integration_tests="$(json_value "$local_acceptance_json" '.results.integration_tests' '0')"
web_tests="$(json_value "$local_acceptance_json" '.results.web_tests' '0')"
browser_contexts="$(json_value "$local_acceptance_json" '.results.browser_contexts' '0')"

api_restart="$(json_value "$persistence_json" '.api_container_restart' 'PENDING')"
postgres_restart="$(json_value "$persistence_json" '.postgres_container_restart' 'PENDING')"
compose_restart="$(json_value "$persistence_json" '.compose_stop_start' 'PENDING')"
compose_recreate="$(json_value "$persistence_json" '.compose_application_recreate' 'PENDING')"
integrity_status="$(json_value "$persistence_json" '.database_and_library_integrity' 'PENDING')"
persistence_status="PENDING"
if [[ "$api_restart" == "PASS" && "$postgres_restart" == "PASS" \
  && "$compose_restart" == "PASS" && "$compose_recreate" == "PASS" \
  && "$integrity_status" == "PASS" ]]; then
  persistence_status="PASS"
fi

database_head="$(database_revision)"
code_head="$(code_head_revision)"
migration_status="FAIL"
if [[ -n "$database_head" && "$database_head" == "$code_head" ]]; then
  migration_status="PASS"
fi

container_lines=""
container_health_status="PASS"
services=(postgres server web)
if [[ "$LINGUASPINDLE_ENABLED" == "true" ]]; then
  services+=(provider-relay)
fi
for service in "${services[@]}"; do
  container_id="$(compose ps -q "$service")"
  if [[ -z "$container_id" ]]; then
    container_lines+="$service: absent"$'\n'
    container_health_status="FAIL"
    continue
  fi
  state="$(docker inspect --format '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$container_id")"
  container_lines+="$service: $state"$'\n'
  [[ "$state" == "running/healthy" ]] || container_health_status="FAIL"
done

backup_directory="$(find "${STAGING_BACKUP_DIR:-$STAGING_ROOT/data/backups}" \
  -maxdepth 1 -type d -name 'novel-platform-v050-*' ! -name '.*' -print 2>/dev/null \
  | sort | tail -1)"
backup_status="PENDING"
if [[ -n "$backup_directory" && -s "$backup_directory/database.dump" \
  && -s "$backup_directory/library.tar.gz" && -s "$backup_directory/manifest.json" ]]; then
  backup_status="PASS"
fi
backup_name="${backup_directory##*/}"
[[ -n "$backup_name" ]] || backup_name="none"

restore_status="PENDING"
if [[ -f "$restore_report" ]] && grep -q 'Status: \*\*PASS\*\*' "$restore_report"; then
  restore_status="PASS"
fi
leak_status="$(json_value "$leak_json" '.status' 'PENDING')"
resource_status="$([[ -f "$resource_report" ]] && printf PASS || printf PENDING)"
release_status="$([[ -f "$release_json" ]] && printf PASS || printf PENDING)"
passkey_status="${STAGING_PASSKEY_RESULT:-PENDING}"
external_postgres_status="${STAGING_EXTERNAL_POSTGRES_RESULT:-PENDING}"
reboot_status="${STAGING_REBOOT_RESULT:-PENDING}"

overall_status="DEPLOYMENT_PENDING"
if [[ "$local_acceptance_status" == "PASS" && "$migration_status" == "PASS" \
  && "$container_health_status" == "PASS" && "$persistence_status" == "PASS" \
  && "$backup_status" == "PASS" && "$restore_status" == "PASS" \
  && "$leak_status" == "PASS" && "$passkey_status" == "PASS" ]]; then
  overall_status="PASS"
fi

git_commit="$(git -C "$REPOSITORY_ROOT" rev-parse HEAD)"
docker_version="$(docker version --format '{{.Server.Version}}')"
compose_version="$(docker compose version --short)"

cat >"$action_log" <<'EOF'
Novel Platform v0.5.0 staging sanitized action log
No command arguments containing credentials, environment values, tokens, Cookies, request bodies, database URLs, or host paths are recorded.

[ACTION] verify local pnpm acceptance -- v050 report
[ACTION] validate HTTPS staging environment without printing values
[ACTION] build immutable images and apply Alembic migration
[ACTION] run explicit authentication migration preflight/conversion/audit
[ACTION] initialize or recover the administrator only through the server CLI
[ACTION] verify a real staging Passkey flow
[ACTION] verify API, PostgreSQL, Compose, and container-recreate persistence
[ACTION] create a coordinated database and library backup
[ACTION] restore into an isolated database and isolated volume
[ACTION] record sanitized resource snapshots
[ACTION] scan staging reports for credentials, tokens, Cookies, keys, and database URLs
EOF
chmod 600 "$action_log"

cat >"$deployment_report" <<EOF
# Novel Platform v0.5.0 staging deployment report

- Status: **$overall_status**
- Environment: **staging** (not production)
- Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)
- Git commit: \`$git_commit\`
- Public HTTPS URL: $PUBLIC_BASE_URL
- Docker Engine: $docker_version
- Docker Compose: $compose_version

## Release gates

- Local \`pnpm acceptance -- v050\`: $local_acceptance_status
- Python unit tests: $unit_tests
- PostgreSQL integration tests: $integration_tests
- Web tests: $web_tests
- Independent reader browser contexts: $browser_contexts
- Real staging-origin Passkey initialization/login/recovery: $passkey_status
- Current release metadata: $release_status

The deployment remains \`DEPLOYMENT_PENDING\` unless the local 84-item gate, live container and
migration checks, persistence, backup/restore, leak scan, and real staging-origin Passkey check all
pass. A local PASS is not reported as a completed external deployment.

## Topology and security posture

- Public entry: HTTPS reverse proxy only.
- API and PostgreSQL: Compose-private networks; no direct public port is required.
- Provider Relay: database + linguaspindle-private only when enabled; no host/proxy/edge port.
- Provider credentials: AES-256-GCM ciphertext in PostgreSQL; master key remains external.
- Secure, HttpOnly Refresh and device Cookies: required by staging validation.
- WebAuthn RP ID and allowed origin: explicit and HTTPS-bound.
- Anonymous OpenAPI UI: disabled.
- Administrator password and Web Setup Token: absent.
- Administrator recovery material: generated only by server CLI and never stored in this report.
- External PostgreSQL rejection check: $external_postgres_status

## Database and containers

- Alembic database revision: \`$database_head\`
- Alembic code head: \`$code_head\`
- Migration revision match: $migration_status
- Container health: $container_health_status

\`\`\`text
$container_lines\`\`\`

## Persistence, backup, and restore

- API restart persistence: $api_restart
- PostgreSQL restart persistence: $postgres_restart
- Compose stop/start persistence: $compose_restart
- Application container recreation persistence: $compose_recreate
- Database/library state fingerprint and integrity audit: $integrity_status
- Coordinated backup: $backup_status ($backup_name)
- Isolated database and volume restore: $restore_status
- Live staging data overwritten during restore test: no
- Real host reboot recovery: $reboot_status

## Leakage and resources

- Secret/token/Cookie/private-key/database-URL report scan: $leak_status
- Sanitized resource snapshots: $resource_status
- Environment file, raw credentials, database dump contents, library contents, storage keys, IDs,
  and absolute host paths included in this report: no

## Current environment variable names

\`PUBLIC_BASE_URL\`, \`POSTGRES_DB\`, \`POSTGRES_USER\`, \`POSTGRES_PASSWORD\`,
\`CORS_ORIGINS\`, \`TRUSTED_HOSTS\`, \`AUTH_JWT_SECRET\`, \`AUTH_HASH_SECRET\`,
\`AUTH_CREDENTIAL_HASH_SECRET\`, \`AUTH_COOKIE_SECURE\`, \`AUTH_COOKIE_SAMESITE\`,
\`AUTH_COOKIE_DOMAIN\`, \`AUTH_DEVICE_COOKIE_NAME\`, \`ADMIN_RECOVERY_TTL_MINUTES\`,
\`WEBAUTHN_RP_ID\`, \`WEBAUTHN_ORIGINS\`, and \`OPENAPI_ENABLED\`. Values are not recorded.

## Repeatable operations

- Deploy/update: \`./scripts/staging/lifecycle/update-staging.sh\`
- Health check: \`./scripts/staging/lifecycle/healthcheck-staging.sh\`
- Persistence check: \`pnpm acceptance -- staging-persistence\`
- Complete backup: \`./scripts/staging/data/backup-library.sh\`
- Isolated restore test: \`./scripts/staging/data/restore-library.sh --test BACKUP_DIRECTORY\`
- Artifact leak scan: \`./scripts/staging/reports/scan-staging-artifacts.sh\`
- Application-only rollback: \`./scripts/staging/lifecycle/rollback-staging.sh COMMIT\`

Rollback never performs an automatic Alembic downgrade. A real database or library restore requires
separate explicit authorization and must first pass the isolated restore workflow.

## Artifacts

- \`deployment-v050-report.md\`
- \`acceptance-v050.json\` (copied local gate, when available)
- \`persistence-v050.json\`
- \`persistence-v050-state.json\` (counts and hashes only)
- \`restore-v050-test-report.md\`
- \`resource-usage-v050.md\`
- \`leak-scan-v050.json\`
- \`sanitized-v050-action-log.txt\`

## Known limitations

- This is a single-host staging topology, not high availability.
- Backups remain local unless an independently encrypted off-host copy policy is configured.
- DNS, certificates, external firewall behavior, reboot recovery, and a physical Passkey require
  evidence from the target host and cannot be inferred from local acceptance.
EOF
chmod 600 "$deployment_report"

printf 'deployment report generated: %s\n' "$(basename "$deployment_report")"
printf 'sanitized action log generated: %s\n' "$(basename "$action_log")"
