from enum import StrEnum


class FileFormat(StrEnum):
    EPUB = "epub"
    TXT = "txt"
    JPEG = "jpeg"
    PNG = "png"
    WEBP = "webp"
    GIF = "gif"


class StoredFilePurpose(StrEnum):
    EDITION_SOURCE = "edition_source"
    NORMALIZED_TEXT = "normalized_text"
    BOOK_COVER = "book_cover"
    COVER_THUMBNAIL = "cover_thumbnail"


class ImportOperation(StrEnum):
    CREATE_BOOK = "create_book"
    ADD_EDITION = "add_edition"
    REPLACE_EDITION_FILE = "replace_edition_file"


class ImportStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
