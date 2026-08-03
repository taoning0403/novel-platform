"""Fail closed before running PostgreSQL-backed verification."""

from __future__ import annotations

import os
import string
from collections.abc import Mapping
from urllib.parse import parse_qsl, unquote, urlsplit

LOCAL_DATABASE_HOSTS = {"", "localhost", "127.0.0.1", "::1"}
TARGET_QUERY_KEYS = {
    "database",
    "dbname",
    "host",
    "hostaddr",
    "port",
    "service",
    "servicefile",
}


def database_prerequisite(
    environment: Mapping[str, str] | None = None,
) -> str | None:
    env = os.environ if environment is None else environment
    raw_url = env.get("TEST_DATABASE_URL", "").strip()
    if not raw_url:
        return "TEST_DATABASE_URL is required for an isolated test database"
    parsed = parse_database_url(raw_url)
    if parsed is None:
        return "TEST_DATABASE_URL is not a valid PostgreSQL URL"
    host, database_name, query_keys = parsed
    if TARGET_QUERY_KEYS.intersection(query_keys):
        return "TEST_DATABASE_URL query cannot override the connection target"
    if "test" not in database_segments(database_name):
        return "TEST_DATABASE_URL database name must contain a standalone test segment"
    if host not in LOCAL_DATABASE_HOSTS and env.get("ALLOW_REMOTE_TEST_DATABASE") != "1":
        return "remote TEST_DATABASE_URL requires ALLOW_REMOTE_TEST_DATABASE=1"
    return None


def parse_database_url(raw_url: str) -> tuple[str, str, set[str]] | None:
    try:
        parsed = urlsplit(raw_url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    scheme = parsed.scheme.casefold()
    if scheme not in {"postgres", "postgresql"} and not scheme.startswith("postgresql+"):
        return None
    if not valid_percent_encoding(parsed.path):
        return None
    database_name = unquote(parsed.path.lstrip("/"))
    if not database_name:
        return None
    query_keys = parsed_query_keys(parsed.query)
    if query_keys is None:
        return None
    return host, database_name, query_keys


def parsed_query_keys(query: str) -> set[str] | None:
    if not valid_percent_encoding(query):
        return None
    try:
        pairs = parse_qsl(
            query,
            keep_blank_values=True,
            strict_parsing=True,
            separator="&",
        )
    except ValueError:
        return None
    return {key.casefold() for key, _value in pairs}


def valid_percent_encoding(value: str) -> bool:
    index = 0
    while index < len(value):
        if value[index] != "%":
            index += 1
            continue
        escape = value[index + 1 : index + 3]
        if len(escape) != 2 or any(character not in string.hexdigits for character in escape):
            return False
        index += 3
    return True


def database_segments(database_name: str) -> list[str]:
    normalized = database_name.lower().replace("-", "_")
    return [segment for segment in normalized.split("_") if segment]
