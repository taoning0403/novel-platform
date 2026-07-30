#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

SCRIPT_DIRECTORY="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../staging-lib.sh
source "$SCRIPT_DIRECTORY/../staging-lib.sh"

require_command docker
load_staging_environment
validate_staging_environment
report_directory="${STAGING_REPORT_DIR:-$STAGING_ROOT/reports}"
mkdir -p "$report_directory"

docker run --rm \
  --user "$(id -u):$(id -g)" \
  -e STAGING_SCAN_REPOSITORY_ROOT=/work \
  -e STAGING_SCAN_REPORT_DIR=/reports \
  -e POSTGRES_PASSWORD \
  -e AUTH_JWT_SECRET \
  -e AUTH_HASH_SECRET \
  -e AUTH_CREDENTIAL_HASH_SECRET \
  -e PROVIDER_CREDENTIAL_MASTER_KEY \
  -e PROVIDER_RELAY_SERVICE_SECRET \
  -v "$REPOSITORY_ROOT:/work:ro" \
  -v "$report_directory:/reports" \
  node:22.17.1-alpine \
  node /work/scripts/staging/reports/scan-staging-artifacts.mjs

printf 'report=%s/leak-scan-v050.json\n' "$report_directory"
