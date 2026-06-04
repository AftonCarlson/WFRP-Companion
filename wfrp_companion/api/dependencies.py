from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from wfrp_companion.config import AppConfig


def get_config(request: Request) -> AppConfig:
    config = getattr(request.app.state, "config", None)
    if not isinstance(config, AppConfig):
        raise RuntimeError("WFRP Companion API config is not initialized")
    return config


ConfigDependency = Annotated[AppConfig, Depends(get_config)]
