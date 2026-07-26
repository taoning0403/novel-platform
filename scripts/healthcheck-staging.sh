#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIRECTORY="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=staging-lib.sh
source "$SCRIPT_DIRECTORY/staging-lib.sh"

require_command curl
require_command docker
require_command grep
require_command python3
load_staging_environment
validate_staging_environment

host_secret_proof() {
  local environment_name="$1"
  local encoding="$2"
  local challenge="$3"
  python3 - "$environment_name" "$encoding" "$challenge" <<'PY'
import base64
import hashlib
import hmac
import os
import sys

try:
    environment_name, encoding, challenge_text = sys.argv[1:]
    raw_value = os.environ[environment_name]
    if encoding == "base64-32":
        material = base64.b64decode(raw_value, validate=True)
        if len(material) != 32:
            raise ValueError
    elif encoding == "utf8":
        material = raw_value.encode()
        if len(material) < 32:
            raise ValueError
    else:
        raise ValueError
    challenge = bytes.fromhex(challenge_text)
    if len(challenge) != 32:
        raise ValueError
except Exception:
    raise SystemExit(1)
print(hmac.new(material, challenge, hashlib.sha256).hexdigest())
PY
}

container_secret_proof() {
  local container_id="$1"
  local environment_name="$2"
  local encoding="$3"
  local challenge="$4"
  docker exec -i "$container_id" python - "$environment_name" "$encoding" "$challenge" <<'PY'
import base64
import hashlib
import hmac
import os
import sys

try:
    environment_name, encoding, challenge_text = sys.argv[1:]
    raw_value = os.environ[environment_name]
    if encoding == "base64-32":
        material = base64.b64decode(raw_value, validate=True)
        if len(material) != 32:
            raise ValueError
    elif encoding == "utf8":
        material = raw_value.encode()
        if len(material) < 32:
            raise ValueError
    else:
        raise ValueError
    challenge = bytes.fromhex(challenge_text)
    if len(challenge) != 32:
        raise ValueError
except Exception:
    raise SystemExit(1)
print(hmac.new(material, challenge, hashlib.sha256).hexdigest())
PY
}

healthcheck_base_url="${STAGING_HEALTHCHECK_BASE_URL:-http://127.0.0.1:${STAGING_HTTP_PORT:-8080}}"
wait_for_url "$healthcheck_base_url/healthz" "${STAGING_HEALTH_TIMEOUT_SECONDS:-120}"
wait_for_url "$healthcheck_base_url/api/v1/health/live" "${STAGING_HEALTH_TIMEOUT_SECONDS:-120}"
wait_for_url "$healthcheck_base_url/api/v1/health/ready" "${STAGING_HEALTH_TIMEOUT_SECONDS:-120}"
wait_for_url "$healthcheck_base_url/" "${STAGING_HEALTH_TIMEOUT_SECONDS:-120}"

health_services=(postgres server web)
if [[ "$LINGUASPINDLE_ENABLED" == "true" ]]; then
  health_services+=(provider-relay)
fi
for service in "${health_services[@]}"; do
  container_id="$(compose ps -q "$service")"
  [[ -n "$container_id" ]] || die "$service container is missing"
  deadline=$((SECONDS + ${STAGING_HEALTH_TIMEOUT_SECONDS:-120}))
  while true; do
    running="$(docker inspect --format '{{.State.Running}}' "$container_id")"
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id")"
    [[ "$running" == "true" ]] || die "$service container is not running"
    [[ "$health" == "healthy" ]] && break
    [[ "$health" != "unhealthy" ]] || die "$service container is unhealthy"
    (( SECONDS < deadline )) || die "$service container health remained $health"
    sleep 2
  done
done

private_services=(postgres server)
if [[ "$LINGUASPINDLE_ENABLED" == "true" ]]; then
  private_services+=(provider-relay)
fi
for private_service in "${private_services[@]}"; do
  container_id="$(compose ps -q "$private_service")"
  published="$(docker inspect --format '{{json .HostConfig.PortBindings}}' "$container_id")"
  [[ "$published" == "null" || "$published" == "{}" ]] || die "$private_service publishes a host port"
done

translation_network="linguaspindle-private"
server_networks="$(docker inspect --format '{{json .NetworkSettings.Networks}}' "$(compose ps -q server)")"
if [[ "$LINGUASPINDLE_ENABLED" == "true" ]]; then
  docker network inspect "$translation_network" >/dev/null
  grep -Fq "\"$translation_network\"" <<<"$server_networks" \
    || die "enabled Server is not attached to linguaspindle-private"

  linguaspindle_origin_parts="$(
    python3 - "$LINGUASPINDLE_BASE_URL" <<'PY'
import ipaddress
import sys
from urllib.parse import urlsplit

try:
    parsed = urlsplit(sys.argv[1])
    hostname = parsed.hostname
    port = parsed.port
except ValueError:
    raise SystemExit(1)
if (
    parsed.scheme not in {"http", "https"}
    or not hostname
    or parsed.username is not None
    or parsed.password is not None
    or parsed.query
    or parsed.fragment
    or parsed.path not in {"", "/"}
    or hostname.endswith(".")
):
    raise SystemExit(1)
try:
    ipaddress.ip_address(hostname)
except ValueError:
    pass
else:
    raise SystemExit(1)
print(parsed.scheme, hostname.lower(), port or (443 if parsed.scheme == "https" else 80), sep="\t")
PY
  )" || die "enabled LinguaSpindle origin must use a DNS hostname"
  IFS=$'\t' read -r linguaspindle_scheme linguaspindle_hostname linguaspindle_port \
    <<<"$linguaspindle_origin_parts"
  [[ -n "$linguaspindle_scheme" && -n "$linguaspindle_hostname" \
    && -n "$linguaspindle_port" ]] \
    || die "enabled LinguaSpindle origin could not be parsed"

  network_container_ids="$(
    docker network inspect \
      --format '{{range $id, $container := .Containers}}{{println $id}}{{end}}' \
      "$translation_network"
  )" || die "could not enumerate linguaspindle-private containers"
  linguaspindle_candidates=()
  while IFS= read -r candidate_container; do
    [[ -n "$candidate_container" ]] || continue
    candidate_networks="$(
      docker inspect --format '{{json .NetworkSettings.Networks}}' "$candidate_container"
    )" || die "could not inspect a linguaspindle-private container"
    if python3 - "$candidate_networks" "$translation_network" "$linguaspindle_hostname" <<'PY'
import json
import sys

try:
    networks = json.loads(sys.argv[1])
    endpoint = networks[sys.argv[2]]
except (KeyError, TypeError, ValueError):
    raise SystemExit(1)
names = {
    str(name).lower().rstrip(".")
    for name in [*(endpoint.get("Aliases") or []), *(endpoint.get("DNSNames") or [])]
    if isinstance(name, str) and name
}
raise SystemExit(0 if sys.argv[3] in names else 1)
PY
    then
      linguaspindle_candidates+=("$candidate_container")
    fi
  done <<<"$network_container_ids"
  (( ${#linguaspindle_candidates[@]} == 1 )) \
    || die "linguaspindle-private must have exactly one container for the configured LinguaSpindle DNS alias"
  linguaspindle_container="${linguaspindle_candidates[0]}"

  linguaspindle_deadline=$((SECONDS + ${STAGING_HEALTH_TIMEOUT_SECONDS:-120}))
  while true; do
    linguaspindle_running="$(
      docker inspect --format '{{.State.Running}}' "$linguaspindle_container"
    )"
    linguaspindle_health="$(
      docker inspect \
        --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
        "$linguaspindle_container"
    )"
    [[ "$linguaspindle_running" == "true" ]] \
      || die "LinguaSpindle container is not running"
    [[ "$linguaspindle_health" != "none" ]] \
      || die "LinguaSpindle container has no healthcheck"
    [[ "$linguaspindle_health" == "healthy" ]] && break
    [[ "$linguaspindle_health" != "unhealthy" ]] \
      || die "LinguaSpindle container is unhealthy"
    (( SECONDS < linguaspindle_deadline )) \
      || die "LinguaSpindle container health remained $linguaspindle_health"
    sleep 2
  done

  linguaspindle_port_bindings="$(
    docker inspect --format '{{json .HostConfig.PortBindings}}' "$linguaspindle_container"
  )"
  linguaspindle_network_ports="$(
    docker inspect --format '{{json .NetworkSettings.Ports}}' "$linguaspindle_container"
  )"
  python3 - "$linguaspindle_port_bindings" "$linguaspindle_network_ports" <<'PY' \
    || die "LinguaSpindle publishes a host port"
import json
import sys

try:
    bindings = json.loads(sys.argv[1])
    ports = json.loads(sys.argv[2])
except (TypeError, ValueError):
    raise SystemExit(1)
if bindings not in (None, {}):
    raise SystemExit(1)
if not isinstance(ports, (dict, type(None))):
    raise SystemExit(1)
if isinstance(ports, dict) and any(value not in (None, []) for value in ports.values()):
    raise SystemExit(1)
PY

  docker exec -i "$linguaspindle_container" python - <<'PY' \
    || die "LinguaSpindle database is not at schema 5"
import sqlite3

try:
    connection = sqlite3.connect(
        "file:/data/database/linguaspindle.sqlite3?mode=ro",
        uri=True,
    )
    try:
        connection.execute("PRAGMA query_only=ON")
        versions = [
            int(row[0])
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
    finally:
        connection.close()
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if versions == [1, 2, 3, 4, 5] else 1)
PY

  linguaspindle_networks="$(
    docker inspect --format '{{json .NetworkSettings.Networks}}' "$linguaspindle_container"
  )"
  compose exec -T server python - "$LINGUASPINDLE_BASE_URL" "$linguaspindle_hostname" \
    "$linguaspindle_port" "$linguaspindle_networks" "$translation_network" <<'PY' \
    || die "LinguaSpindle private DNS or compatible health response is invalid"
import ipaddress
import json
import re
import socket
import sys
import urllib.request


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


try:
    origin, hostname, port_text, networks_json, network_name = sys.argv[1:]
    port = int(port_text)
    endpoint = json.loads(networks_json)[network_name]
    expected_addresses = {
        str(ipaddress.ip_address(value.split("/", 1)[0]))
        for value in (
            endpoint.get("IPAddress"),
            endpoint.get("GlobalIPv6Address"),
        )
        if isinstance(value, str) and value
    }
    resolved_addresses = {
        str(ipaddress.ip_address(item[4][0]))
        for item in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    }
    if (
        not expected_addresses
        or not resolved_addresses
        or not resolved_addresses.issubset(expected_addresses)
    ):
        raise ValueError

    request = urllib.request.Request(
        f"{origin.rstrip('/')}/health",
        headers={"Accept": "application/json"},
        method="GET",
    )
    with urllib.request.build_opener(NoRedirectHandler()).open(request, timeout=5) as response:
        if response.status != 200 or response.headers.get_content_type() != "application/json":
            raise ValueError
        body = response.read(65_537)
    if len(body) > 65_536:
        raise ValueError
    payload = json.loads(body)
    version = payload.get("version") if isinstance(payload, dict) else None
    match = (
        re.fullmatch(
            r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
            r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?",
            version,
        )
        if isinstance(version, str)
        else None
    )
    compatible = (
        match is not None
        and (0, 3, 2) <= tuple(int(part) for part in match.groups()) < (0, 4, 0)
    )
    if (
        payload.get("status") != "ok"
        or payload.get("database") != "ok"
        or not compatible
    ):
        raise ValueError
except Exception:
    raise SystemExit(1)
PY

  relay_container="$(compose ps -q provider-relay)"
  relay_networks="$(docker inspect --format '{{json .NetworkSettings.Networks}}' "$relay_container")"
  postgres_networks="$(docker inspect --format '{{json .NetworkSettings.Networks}}' "$(compose ps -q postgres)")"
  python3 - "$relay_networks" "$postgres_networks" "$translation_network" <<'PY' \
    || die "Provider Relay must join only the database and linguaspindle-private networks"
import json
import sys

relay = set(json.loads(sys.argv[1]))
postgres = set(json.loads(sys.argv[2]))
translation = sys.argv[3]
expected_relay = postgres | {translation}
if (
    len(postgres) != 1
    or translation in postgres
    or len(relay) != 2
    or relay != expected_relay
):
    raise SystemExit(1)
PY
  compose exec -T provider-relay python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8790/health', timeout=2)" \
    >/dev/null

  server_container="$(compose ps -q server)"
  secret_probe_challenge="$(
    python3 - <<'PY'
import secrets

print(secrets.token_hex(32))
PY
  )" || die "could not create a runtime secret proof challenge"
  host_master_proof="$(
    host_secret_proof \
      PROVIDER_CREDENTIAL_MASTER_KEY \
      base64-32 \
      "$secret_probe_challenge"
  )" || die "host Provider master key could not be validated"
  server_master_proof="$(
    container_secret_proof \
      "$server_container" \
      PROVIDER_CREDENTIAL_MASTER_KEY \
      base64-32 \
      "$secret_probe_challenge"
  )" || die "Server Provider master key could not be validated"
  relay_master_proof="$(
    container_secret_proof \
      "$relay_container" \
      PROVIDER_CREDENTIAL_MASTER_KEY \
      base64-32 \
      "$secret_probe_challenge"
  )" || die "Provider Relay master key could not be validated"
  [[ "$host_master_proof" == "$server_master_proof" \
    && "$host_master_proof" == "$relay_master_proof" ]] \
    || die "Server and Provider Relay master keys do not match the protected host configuration"

  host_bearer_proof="$(
    host_secret_proof \
      PROVIDER_RELAY_SERVICE_SECRET \
      utf8 \
      "$secret_probe_challenge"
  )" || die "host Provider Relay service secret could not be validated"
  relay_bearer_proof="$(
    container_secret_proof \
      "$relay_container" \
      PROVIDER_RELAY_SERVICE_SECRET \
      utf8 \
      "$secret_probe_challenge"
  )" || die "Provider Relay service secret could not be validated"
  linguaspindle_bearer_proof="$(
    container_secret_proof \
      "$linguaspindle_container" \
      LINGUASPINDLE_OPENAI_API_KEY \
      utf8 \
      "$secret_probe_challenge"
  )" || die "LinguaSpindle service Bearer could not be validated"
  [[ "$host_bearer_proof" == "$relay_bearer_proof" \
    && "$host_bearer_proof" == "$linguaspindle_bearer_proof" ]] \
    || die "LinguaSpindle and Provider Relay service Bearers do not match"
  unset \
    secret_probe_challenge \
    host_master_proof \
    server_master_proof \
    relay_master_proof \
    host_bearer_proof \
    relay_bearer_proof \
    linguaspindle_bearer_proof

  docker exec -i "$server_container" python - \
    "$LINGUASPINDLE_BASE_URL" \
    "$PROVIDER_RELAY_INTERNAL_URL" \
    "$PROVIDER_RELAY_UPSTREAM_BASE_URL" \
    "$PROVIDER_RELAY_ALLOWED_MODELS" \
    "$PROVIDER_RELAY_CUSTOM_ALLOWED_BASE_URLS" <<'PY' \
    || die "Server translation runtime configuration differs from the protected host configuration"
import json
import sys

try:
    from novel_platform.config import Settings

    (
        expected_lingua,
        expected_relay,
        expected_upstream,
        expected_models_json,
        expected_custom_json,
    ) = sys.argv[1:]
    expected_models = [item.strip() for item in json.loads(expected_models_json)]
    expected_custom = [
        item.strip().rstrip("/") for item in json.loads(expected_custom_json)
    ]
    settings = Settings()
    valid = (
        settings.linguaspindle_enabled
        and settings.linguaspindle_base_url == expected_lingua.rstrip("/")
        and settings.linguaspindle_version_range == ">=0.3.2,<0.4.0"
        and settings.linguaspindle_provider_id == "openai-compatible"
        and settings.provider_relay_internal_url == expected_relay.rstrip("/")
        and settings.provider_relay_upstream_base_url == expected_upstream.rstrip("/")
        and settings.provider_relay_allowed_models == expected_models
        and settings.provider_relay_custom_allowed_base_urls == expected_custom
    )
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if valid else 1)
PY

  docker exec -i "$relay_container" python - \
    "$PROVIDER_RELAY_UPSTREAM_BASE_URL" \
    "$PROVIDER_RELAY_ALLOWED_MODELS" \
    "$PROVIDER_RELAY_CUSTOM_ALLOWED_BASE_URLS" <<'PY' \
    || die "Provider Relay runtime configuration differs from the protected host configuration"
import json
import sys

try:
    from novel_platform.config import ProviderRelaySettings

    expected_upstream, expected_models_json, expected_custom_json = sys.argv[1:]
    expected_models = [item.strip() for item in json.loads(expected_models_json)]
    expected_custom = [
        item.strip().rstrip("/") for item in json.loads(expected_custom_json)
    ]
    settings = ProviderRelaySettings()
    valid = (
        settings.provider_relay_upstream_base_url == expected_upstream.rstrip("/")
        and settings.provider_relay_allowed_models == expected_models
        and settings.provider_relay_custom_allowed_base_urls == expected_custom
    )
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if valid else 1)
PY

  synthetic_scope="00000000-0000-0000-0000-000000000000"
  synthetic_scope_count="$(
    compose exec -T postgres \
      psql \
      -X \
      -v ON_ERROR_STOP=1 \
      -U "$POSTGRES_USER" \
      -d "$POSTGRES_DB" \
      -Atc \
      "SELECT count(*) FROM provider_credential_versions WHERE id = '$synthetic_scope'"
  )" || die "could not reserve the synthetic Relay probe scope"
  [[ "$synthetic_scope_count" == "0" ]] \
    || die "the reserved synthetic Relay probe scope unexpectedly exists"

  docker exec -i "$linguaspindle_container" python - \
    "$synthetic_scope" \
    "$relay_networks" \
    "$translation_network" <<'PY' \
    || die "LinguaSpindle-to-Relay configuration or authenticated no-upstream probe failed"
import ipaddress
import json
import os
import socket
import sys
import urllib.error
import urllib.request


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


try:
    scope, relay_networks_json, translation_network = sys.argv[1:]
    base_url = os.environ["LINGUASPINDLE_OPENAI_BASE_URL"]
    api_key = os.environ["LINGUASPINDLE_OPENAI_API_KEY"]
    model = os.environ["LINGUASPINDLE_OPENAI_MODEL"].strip()
    if base_url != "http://novel-provider-relay:8790/v1" or not model:
        raise ValueError

    relay_endpoint = json.loads(relay_networks_json)[translation_network]
    expected_addresses = {
        str(ipaddress.ip_address(value.split("/", 1)[0]))
        for value in (
            relay_endpoint.get("IPAddress"),
            relay_endpoint.get("GlobalIPv6Address"),
        )
        if isinstance(value, str) and value
    }
    resolved_addresses = {
        str(ipaddress.ip_address(item[4][0]))
        for item in socket.getaddrinfo(
            "novel-provider-relay",
            8790,
            type=socket.SOCK_STREAM,
        )
    }
    if (
        not expected_addresses
        or not resolved_addresses
        or not resolved_addresses.issubset(expected_addresses)
    ):
        raise ValueError

    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": "healthcheck"}],
            "stream": False,
        },
        separators=(",", ":"),
    ).encode()
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-LinguaSpindle-Credential-Scope": scope,
            "X-LinguaSpindle-Job-ID": "healthcheck-no-upstream",
        },
        method="POST",
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        NoRedirectHandler(),
    )
    try:
        opener.open(request, timeout=5)
    except urllib.error.HTTPError as error:
        response_body = error.read(65_537)
        status_code = error.code
        error.close()
    else:
        raise ValueError
    if len(response_body) > 65_536 or status_code != 404:
        raise ValueError
    payload = json.loads(response_body)
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("error"), dict)
        or payload["error"].get("code") != "provider_credential_unavailable"
    ):
        raise ValueError
except Exception:
    raise SystemExit(1)
PY

  for excluded_service in postgres web; do
    excluded_networks="$(docker inspect --format '{{json .NetworkSettings.Networks}}' "$(compose ps -q "$excluded_service")")"
    if grep -Fq "\"$translation_network\"" <<<"$excluded_networks"; then
      die "$excluded_service must not join linguaspindle-private"
    fi
  done
else
  if grep -Fq "\"$translation_network\"" <<<"$server_networks"; then
    die "disabled Server unexpectedly remains attached to linguaspindle-private"
  fi
  stale_relay_containers="$(staging_provider_relay_container_ids)" \
    || die "could not inspect disabled Provider Relay containers"
  [[ -z "$stale_relay_containers" ]] \
    || die "disabled translation retains a Provider Relay container"
fi

revision="$(database_revision)"
[[ -n "$revision" ]] || die "Alembic revision is unavailable"

printf 'staging healthcheck PASS\n'
printf 'environment=staging\n'
printf 'base_url=%s\n' "$PUBLIC_BASE_URL"
printf 'server_probe_url=%s\n' "$healthcheck_base_url"
printf 'alembic_revision=%s\n' "$revision"
printf 'public_services=web\n'
if [[ "$LINGUASPINDLE_ENABLED" == "true" ]]; then
  printf 'private_services=server,postgres,provider-relay\n'
else
  printf 'private_services=server,postgres\n'
fi
printf 'translation_enabled=%s\n' "$LINGUASPINDLE_ENABLED"
