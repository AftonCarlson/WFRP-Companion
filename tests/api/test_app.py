from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from wfrp_companion.api.dependencies import ConfigDependency
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database, open_connection
from wfrp_companion.library import source_sets


def make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        pdf_root=tmp_path / "pdf-root",
        data_dir=data_dir,
        db_path=data_dir / "wfrp_companion.sqlite",
        asset_dir=data_dir / "library" / "assets",
    )


def test_create_app_initializes_builtin_source_set_and_health(tmp_path: Path) -> None:
    from wfrp_companion.api.app import create_app

    config = make_config(tmp_path)
    app = create_app(config)
    response = TestClient(app).get("/api/health")

    with open_connection(config.db_path) as connection:
        source_set = connection.execute(
            "select id, name, is_builtin from source_sets where id = ?",
            (source_sets.RULES_CORE_SOURCE_SET_ID,),
        ).fetchone()
        active = connection.execute(
            "select value_json from app_settings where key = ?",
            (source_sets.ACTIVE_SOURCE_SET_SETTING_KEY,),
        ).fetchone()

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "configured"}
    assert source_set is not None
    assert source_set["name"] == source_sets.RULES_CORE_SOURCE_SET_NAME
    assert source_set["is_builtin"] == 1
    assert active is not None
    assert active["value_json"] == '"rules-core"'


def test_create_app_surfaces_builtin_source_set_conflicts(tmp_path: Path) -> None:
    from wfrp_companion.api.app import create_app

    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        connection.execute(
            """
            insert into source_sets (id, name, is_builtin, created_at, updated_at)
            values ('rules-core', 'Rules/Core', 0, '2026-06-04T00:00:00Z',
                    '2026-06-04T00:00:00Z')
            """
        )

    with pytest.raises(source_sets.SourceSetConflictError):
        create_app(config)


def test_config_dependency_requires_initialized_app_config() -> None:
    app = FastAPI()

    @app.get("/config")
    def read_config(config: ConfigDependency) -> dict[str, str]:
        return {"db_path": str(config.db_path)}

    with pytest.raises(RuntimeError, match="config is not initialized"):
        TestClient(app).get("/config")
