import codecs
from pathlib import Path

import pytest

from novel_platform.application.errors import ApplicationError
from novel_platform.application.library.text import detect_text_encoding, normalize_text


@pytest.mark.parametrize(
    ("encoding", "payload"),
    [
        ("utf-8", codecs.BOM_UTF8 + "第一章\r\n内容".encode()),
        ("utf-16-le", codecs.BOM_UTF16_LE + "第一章\r\n内容".encode("utf-16-le")),
        ("utf-16-be", codecs.BOM_UTF16_BE + "第一章\r\n内容".encode("utf-16-be")),
    ],
)
def test_bom_encodings_are_detected_and_normalized(
    tmp_path: Path, encoding: str, payload: bytes
) -> None:
    source = tmp_path / "source.txt"
    normalized = tmp_path / "normalized.txt"
    source.write_bytes(payload)
    parsed = normalize_text(
        source,
        normalized,
        requested_encoding="auto",
        inferred_title="source",
    )
    assert parsed.encoding == encoding
    assert parsed.content_item_count == 1
    assert normalized.read_text(encoding="utf-8") == "第一章\n内容"


@pytest.mark.parametrize(
    ("encoding", "text"),
    [
        ("gb18030", "第一章\n中文内容"),
        ("cp932", "第一章\n日本語の本文"),
        ("euc-kr", "제1장\n한국어 본문"),
    ],
)
def test_explicit_legacy_encodings_decode_strictly(
    tmp_path: Path, encoding: str, text: str
) -> None:
    source = tmp_path / f"{encoding}.txt"
    normalized = tmp_path / f"{encoding}.utf8.txt"
    source.write_bytes(text.encode(encoding))
    parsed = normalize_text(
        source,
        normalized,
        requested_encoding=encoding,
        inferred_title="fixture",
    )
    assert parsed.encoding == encoding
    assert normalized.read_text(encoding="utf-8") == text


def test_invalid_explicit_decode_and_binary_nul_are_rejected(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.txt"
    invalid.write_bytes(b"\xff\xff\xff")
    with pytest.raises(ApplicationError) as decode_error:
        normalize_text(
            invalid,
            tmp_path / "invalid-normalized.txt",
            requested_encoding="utf-8",
            inferred_title="invalid",
        )
    assert decode_error.value.code == "text_decode_failed"

    with pytest.raises(ApplicationError) as binary_error:
        detect_text_encoding(b"plain\x00binary\x00payload", requested_encoding="auto")
    assert binary_error.value.code == "binary_file_not_allowed"


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("gb2312", "gb18030"),
        ("windows-31j", "cp932"),
        ("uhc", "cp949"),
    ],
)
def test_common_detector_aliases_use_supported_superset_codecs(
    alias: str,
    canonical: str,
) -> None:
    assert detect_text_encoding(b"plain ASCII", requested_encoding=alias) == (
        canonical,
        canonical,
    )


def test_auto_detection_returns_understandable_error_for_unsupported_guess() -> None:
    with pytest.raises(ApplicationError) as caught:
        detect_text_encoding(bytes(range(128, 256)), requested_encoding="auto")
    assert caught.value.code in {"text_encoding_undetermined", "binary_file_not_allowed"}
