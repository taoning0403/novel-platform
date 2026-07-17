from novel_platform.application.library.cleanup import deletable_expired_keys


def test_expired_temporary_keys_still_referenced_by_another_import_are_preserved() -> None:
    assert deletable_expired_keys(
        {"expired-only", "shared"},
        {"shared", "current-only"},
    ) == {"expired-only"}
