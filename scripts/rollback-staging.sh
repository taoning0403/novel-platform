#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIRECTORY="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(CDPATH= cd -- "$SCRIPT_DIRECTORY/.." && pwd)"
target_ref="${1:-}"
[[ -n "$target_ref" ]] || { printf 'usage: %s TARGET_COMMIT\n' "$0" >&2; exit 2; }

# shellcheck source=staging-lib.sh
source "$SCRIPT_DIRECTORY/staging-lib.sh"
load_staging_environment
validate_staging_environment

git -C "$REPOSITORY_ROOT" diff --quiet --ignore-submodules -- \
  || die "tracked working tree is dirty"
target_commit="$(git -C "$REPOSITORY_ROOT" rev-parse --verify "$target_ref^{commit}")"
current_commit="$(git -C "$REPOSITORY_ROOT" rev-parse HEAD)"

"$SCRIPT_DIRECTORY/backup-library.sh"
git -C "$REPOSITORY_ROOT" switch --detach "$target_commit"
compose build migrate server web
target_head="$(code_head_revision)"
current_database_revision="$(database_revision)"
if [[ "$target_head" != "$current_database_revision" ]]; then
  git -C "$REPOSITORY_ROOT" switch --detach "$current_commit"
  die "application rollback refused: target schema head differs from the live database; no automatic Alembic downgrade is safe"
fi

exec "$SCRIPT_DIRECTORY/deploy-staging.sh" --skip-backup
