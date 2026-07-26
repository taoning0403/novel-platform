#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

base_url="${1:-}"
[[ "$base_url" =~ ^https://[^/]+$ ]] \
  || { printf 'usage: %s HTTPS_BASE_URL\n' "$0" >&2; exit 2; }

staging_root="${STAGING_ROOT:-/srv/novel-platform}"
output="${STAGING_ENV_FILE:-$staging_root/config/.env.staging}"
[[ ! -e "$output" ]] || { printf 'ERROR: refusing to overwrite %s\n' "$output" >&2; exit 1; }

random_value() {
  python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
}

base64_32_value() {
  python3 -c 'import base64, secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())'
}

postgres_password="$(random_value)"
jwt_secret="$(random_value)"
hash_secret="$(random_value)"
credential_hash_secret="$(random_value)"
provider_credential_master_key="$(base64_32_value)"
provider_relay_service_secret="$(random_value)"
trusted_host="$(python3 -c 'import sys; from urllib.parse import urlsplit; print(urlsplit(sys.argv[1]).hostname)' "$base_url")"

mkdir -p "$(dirname "$output")"
cat >"$output" <<EOF
ENVIRONMENT=staging
PUBLIC_BASE_URL=$base_url
STAGING_HTTP_PORT=8080
STAGING_POSTGRES_DATA_DIR=$staging_root/data/postgres
STAGING_LIBRARY_DATA_DIR=$staging_root/data/library
STAGING_BACKUP_DIR=$staging_root/data/backups
STAGING_REPORT_DIR=$staging_root/reports
POSTGRES_DB=novel_platform
POSTGRES_USER=novel_platform
POSTGRES_PASSWORD=$postgres_password
CORS_ORIGINS='["$base_url"]'
TRUSTED_HOSTS='["$trusted_host","127.0.0.1"]'
LOG_LEVEL=INFO
AUTH_JWT_SECRET=$jwt_secret
AUTH_HASH_SECRET=$hash_secret
AUTH_CREDENTIAL_HASH_SECRET=$credential_hash_secret
AUTH_ACCESS_TOKEN_TTL_SECONDS=900
AUTH_REFRESH_TOKEN_TTL_DAYS=30
AUTH_COOKIE_NAME=novel_refresh
AUTH_DEVICE_COOKIE_NAME=novel_device
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=strict
AUTH_DEVICE_COOKIE_TTL_DAYS=365
AUTH_COOKIE_DOMAIN=
AUTH_ISSUER=novel-platform-staging
AUTH_AUDIENCE=novel-platform-staging-client
AUTH_LOGIN_MAX_FAILURES=5
AUTH_LOGIN_WINDOW_SECONDS=600
AUTH_LOGIN_BLOCK_SECONDS=900
ADMIN_RECOVERY_TTL_MINUTES=15
WEBAUTHN_RP_ID=$trusted_host
WEBAUTHN_RP_NAME='个人数字阅读与藏书整理'
WEBAUTHN_ORIGINS='["$base_url"]'
WEBAUTHN_CHALLENGE_TTL_SECONDS=300
OPENAPI_ENABLED=false
LIBRARY_STORAGE_ROOT=/data/library
MAX_UPLOAD_BYTES=104857600
MAX_EPUB_UNCOMPRESSED_BYTES=524288000
MAX_EPUB_ENTRY_COUNT=10000
MAX_COVER_BYTES=20971520
MAX_COVER_PIXELS=40000000
LINGUASPINDLE_ENABLED=false
LINGUASPINDLE_BASE_URL=http://linguaspindle:8765
LINGUASPINDLE_VERSION_RANGE='>=0.3.2,<0.4.0'
LINGUASPINDLE_PROVIDER_ID=openai-compatible
LINGUASPINDLE_PROFILE_ID=
LINGUASPINDLE_CONNECT_TIMEOUT_SECONDS=3
LINGUASPINDLE_READ_TIMEOUT_SECONDS=30
LINGUASPINDLE_MAX_DOWNLOAD_BYTES=104857600
PROVIDER_CREDENTIAL_MASTER_KEY=$provider_credential_master_key
PROVIDER_RELAY_SERVICE_SECRET=$provider_relay_service_secret
PROVIDER_RELAY_INTERNAL_URL=http://novel-provider-relay:8790
PROVIDER_RELAY_UPSTREAM_BASE_URL=https://api.openai.com/v1
PROVIDER_RELAY_ALLOWED_MODELS='["gpt-4.1-mini"]'
PROVIDER_RELAY_CONNECT_TIMEOUT_SECONDS=5
PROVIDER_RELAY_READ_TIMEOUT_SECONDS=120
PROVIDER_RELAY_MAX_REQUEST_BYTES=1048576
PROVIDER_RELAY_MAX_RESPONSE_BYTES=4194304
EOF
chmod 600 "$output"
unset postgres_password jwt_secret hash_secret credential_hash_secret \
  provider_credential_master_key provider_relay_service_secret trusted_host

printf 'staging environment created without printing secret values\n'
printf 'Administrator initialization and recovery credentials must be generated with the server CLI.\n'
