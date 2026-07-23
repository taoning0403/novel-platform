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


class TranslationCleanupStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
