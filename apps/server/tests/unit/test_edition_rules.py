from uuid import uuid4

import pytest

from novel_platform.domain.editions.models import (
    ContentRole,
    TranslationOrigin,
    validate_edition,
)
from novel_platform.domain.errors import DomainRuleViolation


def test_source_edition_is_valid_without_translation_fields() -> None:
    title, language = validate_edition(
        edition_id=uuid4(),
        title="  Japanese source  ",
        language=" ja ",
        content_role=ContentRole.SOURCE,
        translation_origin=None,
        source_edition_id=None,
        supersedes_edition_id=None,
        revision=1,
    )
    assert (title, language) == ("Japanese source", "ja")


@pytest.mark.parametrize("origin", [TranslationOrigin.AI, TranslationOrigin.HUMAN])
def test_translation_is_valid_without_a_source(origin: TranslationOrigin) -> None:
    validate_edition(
        edition_id=uuid4(),
        title="Independent translation",
        language="zh-CN",
        content_role=ContentRole.TRANSLATION,
        translation_origin=origin,
        source_edition_id=None,
        supersedes_edition_id=None,
        revision=1,
    )


@pytest.mark.parametrize(
    ("role", "origin", "expected_code"),
    [
        (ContentRole.SOURCE, TranslationOrigin.AI, "invalid_translation_origin"),
        (ContentRole.TRANSLATION, None, "invalid_translation_origin"),
    ],
)
def test_role_and_origin_must_be_consistent(
    role: ContentRole,
    origin: TranslationOrigin | None,
    expected_code: str,
) -> None:
    with pytest.raises(DomainRuleViolation) as error:
        validate_edition(
            edition_id=uuid4(),
            title="Edition",
            language="en",
            content_role=role,
            translation_origin=origin,
            source_edition_id=None,
            supersedes_edition_id=None,
            revision=1,
        )
    assert error.value.code == expected_code


def test_edition_cannot_reference_itself() -> None:
    edition_id = uuid4()
    with pytest.raises(DomainRuleViolation) as error:
        validate_edition(
            edition_id=edition_id,
            title="Edition",
            language="en",
            content_role=ContentRole.TRANSLATION,
            translation_origin=TranslationOrigin.AI,
            source_edition_id=edition_id,
            supersedes_edition_id=None,
            revision=1,
        )
    assert error.value.code == "edition_cannot_reference_itself"


def test_revision_must_be_positive() -> None:
    with pytest.raises(DomainRuleViolation) as error:
        validate_edition(
            edition_id=uuid4(),
            title="Edition",
            language="en",
            content_role=ContentRole.SOURCE,
            translation_origin=None,
            source_edition_id=None,
            supersedes_edition_id=None,
            revision=0,
        )
    assert error.value.code == "invalid_revision"
