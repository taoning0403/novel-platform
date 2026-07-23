from enum import StrEnum


class TranslationRunStatus(StrEnum):
    PREPARING = "preparing"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    FAILED = "failed"
    INGESTING = "ingesting"
    SUCCEEDED = "succeeded"
    ATTENTION_REQUIRED = "attention_required"


ACTIVE_TRANSLATION_RUN_STATUSES = frozenset(
    {
        TranslationRunStatus.PREPARING,
        TranslationRunStatus.QUEUED,
        TranslationRunStatus.RUNNING,
        TranslationRunStatus.PAUSED,
        TranslationRunStatus.CANCELLING,
        TranslationRunStatus.INGESTING,
        TranslationRunStatus.ATTENTION_REQUIRED,
    }
)

TERMINAL_TRANSLATION_RUN_STATUSES = frozenset(
    {
        TranslationRunStatus.CANCELLED,
        TranslationRunStatus.PARTIALLY_SUCCEEDED,
        TranslationRunStatus.FAILED,
        TranslationRunStatus.SUCCEEDED,
    }
)

REMOTE_STATUS_MAP = {
    "queued": TranslationRunStatus.QUEUED,
    "running": TranslationRunStatus.RUNNING,
    "paused": TranslationRunStatus.PAUSED,
    "cancelling": TranslationRunStatus.CANCELLING,
    "cancelled": TranslationRunStatus.CANCELLED,
    "partially_succeeded": TranslationRunStatus.PARTIALLY_SUCCEEDED,
    "failed": TranslationRunStatus.FAILED,
}


def local_status_for_remote(remote_status: str) -> TranslationRunStatus:
    if remote_status == "succeeded":
        return TranslationRunStatus.INGESTING
    try:
        return REMOTE_STATUS_MAP[remote_status]
    except KeyError as exc:
        raise ValueError("unknown remote translation status") from exc


class TranslationCleanupStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
