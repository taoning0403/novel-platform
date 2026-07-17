import unicodedata

from novel_platform.domain.errors import DomainRuleViolation


def normalize_username(value: str) -> tuple[str, str]:
    username = unicodedata.normalize("NFKC", value).strip()
    if not 3 <= len(username) <= 64:
        raise DomainRuleViolation("invalid_username", "用户名长度必须为 3 到 64 个字符。")
    if not all(character.isalnum() or character in {"_", "-"} for character in username):
        raise DomainRuleViolation(
            "invalid_username",
            "用户名只能包含字母、数字、下划线或短横线。",
        )
    return username, username.casefold()


def normalize_display_name(value: str) -> str:
    display_name = unicodedata.normalize("NFKC", value).strip()
    if not 1 <= len(display_name) <= 100:
        raise DomainRuleViolation("invalid_display_name", "显示名称长度必须为 1 到 100 个字符。")
    return display_name
