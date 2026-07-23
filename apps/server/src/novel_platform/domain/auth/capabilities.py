from collections.abc import Iterable
from enum import StrEnum


class CredentialCapability(StrEnum):
    LIBRARY_READ = "library.read"
    LIBRARY_UPLOAD = "library.upload"
    TRANSLATION_USE = "translation.use"


MANDATORY_READER_CAPABILITIES = frozenset({CredentialCapability.LIBRARY_READ})
ADMIN_CAPABILITIES = frozenset(CredentialCapability)


def validate_credential_capabilities(
    values: Iterable[CredentialCapability | str],
) -> frozenset[CredentialCapability]:
    parsed = tuple(CredentialCapability(value) for value in values)
    capabilities = frozenset(parsed)
    if len(parsed) != len(capabilities):
        raise ValueError("credential capabilities must not contain duplicates")
    if not MANDATORY_READER_CAPABILITIES <= capabilities:
        raise ValueError("library.read is required")
    return capabilities


def sorted_capabilities(
    capabilities: Iterable[CredentialCapability],
) -> list[CredentialCapability]:
    return sorted(set(capabilities), key=lambda item: item.value)
