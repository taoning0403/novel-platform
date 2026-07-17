from novel_platform.application.library.filenames import content_disposition, sanitize_filename


def test_sanitize_filename_removes_paths_controls_and_preserves_unicode() -> None:
    assert sanitize_filename("../目录/小说\n.txt") == "小说_.txt"
    assert sanitize_filename("..\\秘密\\book.epub") == "book.epub"
    assert sanitize_filename("\x00\n") == "upload"
    assert "../" not in sanitize_filename("../book.txt")


def test_content_disposition_has_ascii_fallback_and_rfc5987_name() -> None:
    value = content_disposition("小说 日本語 한국어.txt")
    assert 'filename="' in value
    assert "filename*=UTF-8''" in value
    assert "%E5%B0%8F%E8%AF%B4" in value
    assert "\n" not in value
