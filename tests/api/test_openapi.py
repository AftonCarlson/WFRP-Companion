from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from wfrp_companion.api.app import create_app
from wfrp_companion.config import AppConfig


def make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        pdf_root=tmp_path / "pdf-root",
        data_dir=data_dir,
        db_path=data_dir / "wfrp_companion.sqlite",
        asset_dir=data_dir / "library" / "assets",
    )


def test_openapi_exposes_phase_4_api_paths(tmp_path: Path) -> None:
    client = TestClient(create_app(make_config(tmp_path)))

    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert {
        "/api/health",
        "/api/chat/threads",
        "/api/chat/threads/{thread_id}",
        "/api/chat/threads/{thread_id}/messages",
        "/api/chat/threads/{thread_id}/messages/stream",
        "/api/chat/model-runs/{model_run_id}/retry",
        "/api/books",
        "/api/books/{book_id}",
        "/api/books/{book_id}/pages/{page_number}",
        "/api/books/{book_id}/pages/{page_number}/text",
        "/api/books/{book_id}/pdf",
        "/api/source-sets",
        "/api/source-sets/active",
        "/api/source-sets/{source_set_id}/books",
        "/api/source-sets/{source_set_id}/books/{book_id}",
        "/api/search/exact",
    }.issubset(paths)
