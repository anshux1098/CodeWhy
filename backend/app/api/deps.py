from __future__ import annotations

from typing import Optional

from fastapi import Depends

from app.config import Settings, settings
from app.services.data_source import DataSource, get_data_source

_DATA_SOURCE: Optional[DataSource] = None


def get_settings() -> Settings:
    return settings


def reset_data_source_cache() -> None:
    """Forget the cached data source.

    The cache exists so one process builds one store instead of per request. A
    test that builds a second application must not be handed the first one's
    source, so it clears this in between.
    """
    global _DATA_SOURCE
    _DATA_SOURCE = None


def get_source(config: Settings = Depends(get_settings)) -> DataSource:
    global _DATA_SOURCE
    if _DATA_SOURCE is None:
        _DATA_SOURCE = get_data_source(config)
    return _DATA_SOURCE
