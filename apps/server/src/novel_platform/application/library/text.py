import os
import re
from dataclasses import dataclass
from pathlib import Path

from charset_normalizer import from_bytes

from novel_platform.application.errors import ApplicationError

_SAMPLE_BYTES = 1024 * 1024
_CHUNK_CHARACTERS = 64 * 1024
_CHAPTER_PATTERN = re.compile(
    r"^\s*(?:第[0-9\uff10-\uff19一二三四五六七八九十百千万零\u3007两]+[章节回卷]|chapter\s+\d+)\b",
    re.IGNORECASE,
)
_ENCODING_ALIASES = {
    "utf8": "utf-8",
    "utf_8": "utf-8",
    "utf-8-sig": "utf-8",
    "utf16le": "utf-16-le",
    "utf_16_le": "utf-16-le",
    "utf16be": "utf-16-be",
    "utf_16_be": "utf-16-be",
    "gbk": "gb18030",
    "cp936": "gb18030",
    "gb2312": "gb18030",
    "gb_2312": "gb18030",
    "gb_18030": "gb18030",
    "shift_jis": "cp932",
    "shift-jis": "cp932",
    "sjis": "cp932",
    "ms932": "cp932",
    "ms_kanji": "cp932",
    "windows_31j": "cp932",
    "windows-31j": "cp932",
    "euc_kr": "euc-kr",
    "euckr": "euc-kr",
    "ks_c_5601-1987": "euc-kr",
    "cp949": "cp949",
    "uhc": "cp949",
    "windows_949": "cp949",
    "windows-949": "cp949",
}
_SUPPORTED_ENCODINGS = {"utf-8", "utf-16-le", "utf-16-be", "gb18030", "cp932", "euc-kr", "cp949"}


@dataclass(frozen=True, slots=True)
class ParsedText:
    encoding: str
    content_item_count: int | None
    metadata: dict[str, object]


def normalize_text(
    source_path: Path,
    destination_path: Path,
    *,
    requested_encoding: str,
    inferred_title: str,
) -> ParsedText:
    with source_path.open("rb") as source:
        sample = source.read(_SAMPLE_BYTES)
    encoding, decoder = detect_text_encoding(sample, requested_encoding=requested_encoding)
    chapter_count = 0
    decoded_characters = 0
    suspicious_controls = 0
    carry = ""
    first_chunk = True
    try:
        with (
            source_path.open("r", encoding=decoder, errors="strict", newline=None) as source,
            destination_path.open("w", encoding="utf-8", errors="strict", newline="\n") as output,
        ):
            while text := source.read(_CHUNK_CHARACTERS):
                if first_chunk:
                    text = text.removeprefix("\ufeff")
                    first_chunk = False
                decoded_characters += len(text)
                suspicious_controls += sum(
                    1 for character in text if ord(character) < 32 and character not in "\n\t\f"
                )
                if "\x00" in text:
                    raise _error("binary_file_not_allowed", "TXT 中包含 NUL，疑似二进制文件。")
                output.write(text)
                lines = f"{carry}{text}".split("\n")
                carry = lines.pop()[-512:]
                chapter_count += sum(1 for line in lines if _CHAPTER_PATTERN.match(line))
            output.flush()
            os.fsync(output.fileno())
        if carry and _CHAPTER_PATTERN.match(carry):
            chapter_count += 1
    except UnicodeDecodeError as exc:
        destination_path.unlink(missing_ok=True)
        raise _error("text_decode_failed", "TXT 无法使用所选编码完整解码。") from exc
    except Exception:
        destination_path.unlink(missing_ok=True)
        raise

    if decoded_characters and suspicious_controls / decoded_characters > 0.01:
        destination_path.unlink(missing_ok=True)
        raise _error("binary_file_not_allowed", "TXT 包含过多控制字符，疑似二进制文件。")

    return ParsedText(
        encoding=encoding,
        content_item_count=chapter_count or None,
        metadata={"title": inferred_title, "encoding": encoding},
    )


def detect_text_encoding(sample: bytes, *, requested_encoding: str = "auto") -> tuple[str, str]:
    requested = requested_encoding.strip().lower()
    if requested != "auto":
        encoding = _normalise_encoding_name(requested)
        if encoding not in _SUPPORTED_ENCODINGS:
            raise _error("text_encoding_undetermined", "所选 TXT 编码不受支持。")
        return encoding, encoding

    if sample.startswith(b"\xef\xbb\xbf"):
        return "utf-8", "utf-8-sig"
    if sample.startswith(b"\xff\xfe"):
        return "utf-16-le", "utf-16"
    if sample.startswith(b"\xfe\xff"):
        return "utf-16-be", "utf-16"
    if not sample:
        return "utf-8", "utf-8"
    if sample.count(b"\x00") / len(sample) > 0.01:
        raise _error("binary_file_not_allowed", "TXT 中包含大量 NUL，疑似二进制文件。")
    try:
        sample.decode("utf-8", errors="strict")
        return "utf-8", "utf-8"
    except UnicodeDecodeError:
        pass

    match = from_bytes(sample).best()
    if match is None or not match.encoding:
        raise _error("text_encoding_undetermined", "无法可靠判断 TXT 编码，请手动选择。")
    encoding = _normalise_encoding_name(match.encoding)
    if encoding not in _SUPPORTED_ENCODINGS or match.percent_chaos > 20:
        raise _error("text_encoding_undetermined", "无法可靠判断 TXT 编码，请手动选择。")
    return encoding, encoding


def _normalise_encoding_name(value: str) -> str:
    lowered = value.lower().replace(" ", "_")
    return _ENCODING_ALIASES.get(lowered, lowered.replace("_", "-"))


def _error(code: str, message: str) -> ApplicationError:
    return ApplicationError(code, message, status_code=422)
