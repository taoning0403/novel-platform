from enum import StrEnum


class ReadingStatus(StrEnum):
    NOT_STARTED = "not_started"
    READING = "reading"
    FINISHED = "finished"


class ReaderTheme(StrEnum):
    LIGHT = "light"
    DARK = "dark"
    SEPIA = "sepia"


class ReaderFontFamily(StrEnum):
    SERIF = "serif"
    SANS = "sans"
    SYSTEM = "system"
