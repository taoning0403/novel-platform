#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIRECTORY="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(CDPATH= cd -- "$SCRIPT_DIRECTORY/../../.." && pwd)"
target_ref="${1:-${STAGING_GIT_REF:-origin/main}}"

git -C "$REPOSITORY_ROOT" diff --quiet --ignore-submodules -- \
  || { printf 'ERROR: tracked working tree is dirty\n' >&2; exit 1; }
git -C "$REPOSITORY_ROOT" diff --cached --quiet --ignore-submodules -- \
  || { printf 'ERROR: index is dirty\n' >&2; exit 1; }

git -C "$REPOSITORY_ROOT" fetch --prune origin
target_commit="$(git -C "$REPOSITORY_ROOT" rev-parse --verify "$target_ref^{commit}")"
git -C "$REPOSITORY_ROOT" switch --detach "$target_commit"
exec "$SCRIPT_DIRECTORY/deploy-staging.sh"
