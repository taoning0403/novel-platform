def deletable_expired_keys(
    expired_keys: set[str],
    remaining_references: set[str],
) -> set[str]:
    """Return expired temporary objects that no import record still references."""

    return expired_keys - remaining_references
