from typing import Literal

from novel_platform.domain.translations.models import TranslationRunStatus

type TranslationControlAction = Literal["pause", "resume", "cancel", "retry"]


def control_actions_for_status(
    status: TranslationRunStatus,
) -> tuple[TranslationControlAction, ...]:
    if status in {TranslationRunStatus.QUEUED, TranslationRunStatus.RUNNING}:
        return ("pause", "cancel")
    if status is TranslationRunStatus.PAUSED:
        return ("resume", "cancel")
    if status in {
        TranslationRunStatus.PREPARING,
        TranslationRunStatus.CANCELLING,
        TranslationRunStatus.ATTENTION_REQUIRED,
    }:
        return ("cancel",)
    if status in {
        TranslationRunStatus.FAILED,
        TranslationRunStatus.PARTIALLY_SUCCEEDED,
    }:
        return ("retry",)
    return ()
