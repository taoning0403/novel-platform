from novel_platform.domain.errors import DomainRuleViolation


def normalise_book_title(title: str) -> str:
    normalised = title.strip()
    if not normalised:
        raise DomainRuleViolation("invalid_book_title", "Book title cannot be empty.")
    return normalised
