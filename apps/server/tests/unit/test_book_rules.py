import pytest

from novel_platform.domain.books.models import normalise_book_title
from novel_platform.domain.errors import DomainRuleViolation


def test_book_title_is_trimmed() -> None:
    assert normalise_book_title("  A novel  ") == "A novel"


def test_book_title_cannot_be_blank() -> None:
    with pytest.raises(DomainRuleViolation) as error:
        normalise_book_title("  ")
    assert error.value.code == "invalid_book_title"
