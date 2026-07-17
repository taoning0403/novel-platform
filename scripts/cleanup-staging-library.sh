#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIRECTORY="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=staging-lib.sh
source "$SCRIPT_DIRECTORY/staging-lib.sh"

require_command docker
load_staging_environment
validate_staging_environment
wait_for_postgres 120

compose run --rm --no-deps server python scripts/cleanup_library_storage.py "$@"
