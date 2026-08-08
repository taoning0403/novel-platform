from typing import Annotated

from fastapi import Depends

from novel_platform.config import Settings, get_settings
from novel_platform.infrastructure.integrations.linguaspindle import (
    LinguaSpindleClient,
    LinguaSpindleGateway,
)


def get_linguaspindle_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> LinguaSpindleGateway:
    return LinguaSpindleClient(settings)


TranslationSettings = Annotated[Settings, Depends(get_settings)]
LinguaSpindleDependency = Annotated[LinguaSpindleGateway, Depends(get_linguaspindle_client)]
