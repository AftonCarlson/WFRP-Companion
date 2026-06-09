from __future__ import annotations

from fastapi import FastAPI

from wfrp_companion.config import AppConfig, load_config
from wfrp_companion.library import source_sets

from .routes import chat, health, library, search, source_sets as source_set_routes


def create_app(config: AppConfig | None = None) -> FastAPI:
    app_config = load_config() if config is None else config
    source_sets.ensure_builtin_source_sets(app_config)

    app = FastAPI(title="WFRP Companion API")
    app.state.config = app_config
    app.include_router(health.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(library.router, prefix="/api")
    app.include_router(source_set_routes.router, prefix="/api")
    app.include_router(search.router, prefix="/api")
    return app
