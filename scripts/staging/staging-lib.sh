#!/usr/bin/env bash

set -Eeuo pipefail

STAGING_LIB_DIRECTORY="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(CDPATH= cd -- "$STAGING_LIB_DIRECTORY/../.." && pwd)"
STAGING_ROOT="${STAGING_ROOT:-/srv/novel-platform}"
STAGING_ENV_FILE="${STAGING_ENV_FILE:-$STAGING_ROOT/config/.env.staging}"
STAGING_COMPOSE_FILE="${STAGING_COMPOSE_FILE:-$REPOSITORY_ROOT/compose.staging.yml}"
STAGING_TRANSLATION_COMPOSE_FILE="${STAGING_TRANSLATION_COMPOSE_FILE:-$REPOSITORY_ROOT/compose.translation.yml}"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command is unavailable: $1"
}

load_staging_environment() {
  [[ -f "$STAGING_ENV_FILE" ]] || die "staging environment file not found: $STAGING_ENV_FILE"
  local mode
  mode="$(stat -c '%a' "$STAGING_ENV_FILE" 2>/dev/null || stat -f '%Lp' "$STAGING_ENV_FILE")"
  [[ "$mode" == "600" || "$mode" == "400" ]] || die "staging environment file must have mode 600 or 400"
  set -a
  # shellcheck disable=SC1090
  source "$STAGING_ENV_FILE"
  set +a
  export PROVIDER_RELAY_CUSTOM_ALLOWED_BASE_URLS="${PROVIDER_RELAY_CUSTOM_ALLOWED_BASE_URLS:-[]}"
}

require_environment_value() {
  local name="$1"
  [[ -n "${!name:-}" ]] || die "required environment value is empty: $name"
}

validate_secret() {
  local name="$1"
  local value="${!name:-}"
  local lower_value
  require_environment_value "$name"
  (( ${#value} >= 32 )) || die "$name must contain at least 32 characters"
  lower_value="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"
  case "$lower_value" in
    *change-me*|*placeholder*|*replace-with*|*example*) die "$name still contains a placeholder" ;;
  esac
}

validate_base64_32_secret() {
  local name="$1"
  require_environment_value "$name"
  command -v python3 >/dev/null 2>&1 || die "required command is unavailable: python3"
  python3 - "$name" <<'PY' \
    || die "$name must be strict base64 decoding to exactly 32 bytes" \
      "and cannot use the known development key in staging/production"
import base64
import binascii
import os
import sys

try:
    value = base64.b64decode(os.environ[sys.argv[1]], validate=True)
except (binascii.Error, KeyError, ValueError):
    raise SystemExit(1)
protected = os.environ.get("ENVIRONMENT", "").lower() in {"staging", "production"}
raise SystemExit(0 if len(value) == 32 and not (protected and value == bytes(32)) else 1)
PY
}

validate_model_allowlist() {
  require_environment_value PROVIDER_RELAY_ALLOWED_MODELS
  command -v python3 >/dev/null 2>&1 || die "required command is unavailable: python3"
  python3 <<'PY' || die "PROVIDER_RELAY_ALLOWED_MODELS must be a non-empty JSON string list"
import json
import os

value = json.loads(os.environ["PROVIDER_RELAY_ALLOWED_MODELS"])
if (
    not isinstance(value, list)
    or not value
    or any(not isinstance(item, str) or not item.strip() or len(item) > 120 for item in value)
):
    raise SystemExit(1)
models = [item.strip() for item in value]
if len(models) != len(set(models)):
    raise SystemExit(1)
PY
}

validate_custom_provider_base_url_allowlist() {
  command -v python3 >/dev/null 2>&1 || die "required command is unavailable: python3"
  python3 <<'PY' \
    || die "PROVIDER_RELAY_CUSTOM_ALLOWED_BASE_URLS must be a JSON list of at most" \
      "100 unique valid HTTP(S) base URLs (HTTPS in staging/production)"
import json
import os
from urllib.parse import urlsplit

try:
    values = json.loads(os.environ["PROVIDER_RELAY_CUSTOM_ALLOWED_BASE_URLS"])
except (KeyError, TypeError, ValueError):
    raise SystemExit(1)
if not isinstance(values, list) or len(values) > 100:
    raise SystemExit(1)

protected = os.environ.get("ENVIRONMENT", "").lower() in {"staging", "production"}
normalized_values = []
for value in values:
    if not isinstance(value, str) or not value or not value.isprintable():
        raise SystemExit(1)
    normalized = value.strip().rstrip("/")
    try:
        parsed = urlsplit(normalized)
        invalid = (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or bool(parsed.query)
            or bool(parsed.fragment)
            or ".." in parsed.path.split("/")
            or (protected and parsed.scheme != "https")
        )
    except (TypeError, ValueError):
        raise SystemExit(1)
    if invalid:
        raise SystemExit(1)
    normalized_values.append(normalized)
if len(normalized_values) != len(set(normalized_values)):
    raise SystemExit(1)
PY
}

validate_staging_environment() {
  local name
  for name in PUBLIC_BASE_URL POSTGRES_DB POSTGRES_USER CORS_ORIGINS TRUSTED_HOSTS \
    AUTH_COOKIE_SECURE AUTH_CREDENTIAL_HASH_SECRET WEBAUTHN_RP_ID WEBAUTHN_ORIGINS \
    OPENAPI_ENABLED LINGUASPINDLE_ENABLED LINGUASPINDLE_BASE_URL \
    LINGUASPINDLE_VERSION_RANGE LINGUASPINDLE_PROVIDER_ID \
    LINGUASPINDLE_MAX_DOWNLOAD_BYTES MAX_UPLOAD_BYTES \
    PROVIDER_CREDENTIAL_MASTER_KEY PROVIDER_RELAY_INTERNAL_URL \
    PROVIDER_RELAY_UPSTREAM_BASE_URL PROVIDER_RELAY_ALLOWED_MODELS; do
    require_environment_value "$name"
  done
  if [[ "${NOVEL_ACCEPTANCE_LOCAL:-0}" == "1" ]]; then
    [[ "${ENVIRONMENT:-}" == "development" ]] \
      || die "local acceptance operations require ENVIRONMENT=development"
    [[ "$PUBLIC_BASE_URL" == http://localhost:* ]] \
      || die "local acceptance operations require an HTTP localhost URL"
    [[ "$STAGING_ROOT" != "/srv/novel-platform" ]] \
      || die "local acceptance operations cannot use the default staging root"
    [[ "$AUTH_COOKIE_SECURE" == "false" ]] \
      || die "local acceptance operations require the isolated HTTP cookie setting"
    [[ "$OPENAPI_ENABLED" == "false" ]] \
      || die "local acceptance operations must keep anonymous OpenAPI disabled"
  else
    [[ "${ENVIRONMENT:-}" == "staging" ]] || die "ENVIRONMENT must be staging"
  fi
  validate_secret POSTGRES_PASSWORD
  validate_secret AUTH_JWT_SECRET
  validate_secret AUTH_HASH_SECRET
  validate_secret AUTH_CREDENTIAL_HASH_SECRET
  validate_base64_32_secret PROVIDER_CREDENTIAL_MASTER_KEY
  [[ "$AUTH_JWT_SECRET" != "$AUTH_HASH_SECRET" \
    && "$AUTH_JWT_SECRET" != "$AUTH_CREDENTIAL_HASH_SECRET" \
    && "$AUTH_HASH_SECRET" != "$AUTH_CREDENTIAL_HASH_SECRET" ]] \
    || die "authentication secrets must be independent"
  [[ "$CORS_ORIGINS" == *"$PUBLIC_BASE_URL"* ]] || die "CORS_ORIGINS must contain PUBLIC_BASE_URL"
  [[ "$WEBAUTHN_ORIGINS" == *"$PUBLIC_BASE_URL"* ]] \
    || die "WEBAUTHN_ORIGINS must contain PUBLIC_BASE_URL"
  [[ "$TRUSTED_HOSTS" != *'"*"'* ]] || die "TRUSTED_HOSTS must not contain a wildcard"
  if [[ "${NOVEL_ACCEPTANCE_LOCAL:-0}" != "1" ]]; then
    [[ "$PUBLIC_BASE_URL" == https://* ]] || die "v0.5.0 staging requires HTTPS"
    [[ "$AUTH_COOKIE_SECURE" == "true" ]] || die "v0.5.0 staging requires Secure cookies"
  fi
  [[ "$OPENAPI_ENABLED" == "false" ]] || die "staging must disable anonymous OpenAPI UI"
  [[ "$LINGUASPINDLE_ENABLED" == "true" || "$LINGUASPINDLE_ENABLED" == "false" ]] \
    || die "LINGUASPINDLE_ENABLED must be true or false"
  [[ "$LINGUASPINDLE_VERSION_RANGE" == ">=0.3.2,<0.4.0" ]] \
    || die "LINGUASPINDLE_VERSION_RANGE must be >=0.3.2,<0.4.0"
  [[ "$LINGUASPINDLE_BASE_URL" =~ ^https?://[A-Za-z0-9._-]+(:[0-9]+)?$ ]] \
    || die "LINGUASPINDLE_BASE_URL must be one fixed HTTP(S) origin"
  [[ "$LINGUASPINDLE_MAX_DOWNLOAD_BYTES" =~ ^[0-9]+$ ]] \
    || die "LINGUASPINDLE_MAX_DOWNLOAD_BYTES must be a positive integer"
  [[ "$MAX_UPLOAD_BYTES" =~ ^[0-9]+$ ]] || die "MAX_UPLOAD_BYTES must be a positive integer"
  (( LINGUASPINDLE_MAX_DOWNLOAD_BYTES > 0 )) \
    || die "LINGUASPINDLE_MAX_DOWNLOAD_BYTES must be positive"
  (( LINGUASPINDLE_MAX_DOWNLOAD_BYTES <= MAX_UPLOAD_BYTES )) \
    || die "LINGUASPINDLE_MAX_DOWNLOAD_BYTES cannot exceed MAX_UPLOAD_BYTES"
  [[ "$PROVIDER_RELAY_INTERNAL_URL" =~ ^https?://[A-Za-z0-9._-]+(:[0-9]+)?$ ]] \
    || die "PROVIDER_RELAY_INTERNAL_URL must be one fixed HTTP(S) origin"
  validate_model_allowlist
  validate_custom_provider_base_url_allowlist
  [[ "$PROVIDER_RELAY_UPSTREAM_BASE_URL" =~ ^https://[A-Za-z0-9._-]+(:[0-9]+)?(/[^?#]*)?$ ]] \
    || die "staging Provider relay legacy upstream must be one fixed HTTPS base URL"
  if [[ "$LINGUASPINDLE_ENABLED" == "true" ]]; then
    for name in PROVIDER_RELAY_SERVICE_SECRET; do
      require_environment_value "$name"
    done
    validate_secret PROVIDER_RELAY_SERVICE_SECRET
    [[ "$PROVIDER_RELAY_SERVICE_SECRET" != "$AUTH_JWT_SECRET" \
      && "$PROVIDER_RELAY_SERVICE_SECRET" != "$AUTH_HASH_SECRET" \
      && "$PROVIDER_RELAY_SERVICE_SECRET" != "$AUTH_CREDENTIAL_HASH_SECRET" \
      && "$PROVIDER_RELAY_SERVICE_SECRET" != "$PROVIDER_CREDENTIAL_MASTER_KEY" ]] \
      || die "Provider vault/relay and authentication secrets must be independent"
    [[ "$PROVIDER_RELAY_INTERNAL_URL" == "http://novel-provider-relay:8790" ]] \
      || die "enabled Provider Relay must use the fixed private origin"
    [[ "$LINGUASPINDLE_PROVIDER_ID" == "openai-compatible" ]] \
      || die "scoped translation requires LINGUASPINDLE_PROVIDER_ID=openai-compatible"
    [[ "$LINGUASPINDLE_BASE_URL" != "http://localhost:"* \
      && "$LINGUASPINDLE_BASE_URL" != "http://127.0.0.1:"* \
      && "$LINGUASPINDLE_BASE_URL" != "http://[::1]:"* ]] \
      || die "enabled LinguaSpindle cannot use a loopback origin"
  fi
}

compose() {
  local compose_files=(-f "$STAGING_COMPOSE_FILE")
  if [[ "${LINGUASPINDLE_ENABLED:-false}" == "true" ]]; then
    [[ -f "$STAGING_TRANSLATION_COMPOSE_FILE" ]] \
      || die "translation Compose overlay not found: $STAGING_TRANSLATION_COMPOSE_FILE"
    compose_files+=(-f "$STAGING_TRANSLATION_COMPOSE_FILE")
  fi
  docker compose --env-file "$STAGING_ENV_FILE" "${compose_files[@]}" "$@"
}

staging_provider_relay_container_ids() {
  docker ps \
    --all \
    --quiet \
    --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME:-novel-platform-staging}" \
    --filter "label=com.docker.compose.service=provider-relay"
}

wait_for_postgres() {
  local deadline=$((SECONDS + ${1:-120}))
  until compose exec -T postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; do
    (( SECONDS < deadline )) || die "PostgreSQL did not become healthy before the deadline"
    sleep 2
  done
}

wait_for_url() {
  local url="$1"
  local deadline=$((SECONDS + ${2:-120}))
  until curl --fail --silent --show-error --max-time 5 "$url" >/dev/null 2>&1; do
    (( SECONDS < deadline )) || die "$url did not become ready before the deadline"
    sleep 2
  done
}

database_revision() {
  compose exec -T postgres sh -c \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT version_num FROM alembic_version"' \
    2>/dev/null || true
}

code_head_revision() {
  compose run --rm --no-deps migrate alembic heads 2>/dev/null | awk 'NF {print $1; exit}'
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

validate_library_archive() {
  local archive="$1"
  python3 - "$archive" <<'PY'
import re
import sys
import tarfile
from pathlib import PurePosixPath

key_pattern = re.compile(r"^[0-9a-f]{64}$")
seen = set()
with tarfile.open(sys.argv[1], mode="r:gz") as archive:
    for member in archive:
        path = PurePosixPath(member.name)
        parts = path.parts
        normalized_name = str(path)
        valid_type = member.isdir() or member.isfile()
        if (
            not valid_type
            or path.is_absolute()
            or ".." in parts
            or normalized_name in seen
            or (parts and parts[0] not in {"files", "tmp"})
        ):
            raise SystemExit("invalid library archive member")
        seen.add(normalized_name)
        if not member.isfile():
            continue
        if parts[0] == "tmp":
            valid_path = len(parts) == 2 and key_pattern.fullmatch(parts[1])
        else:
            valid_path = (
                len(parts) == 4
                and key_pattern.fullmatch(parts[3])
                and parts[1] == parts[3][:2]
                and parts[2] == parts[3][2:4]
            )
        if not valid_path:
            raise SystemExit("invalid library archive object path")
PY
}
