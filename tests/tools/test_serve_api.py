from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tools import serve_api


def test_main_builds_app_and_invokes_runner_with_local_defaults(tmp_path: Path) -> None:
    data_dir = tmp_path / "private-data"
    calls: dict[str, object] = {}

    def fake_runner(app: object, host: str, port: int) -> None:
        calls["app"] = app
        calls["host"] = host
        calls["port"] = port

    exit_code = serve_api.main(
        ["--data-dir", str(data_dir), "--host", "127.0.0.2", "--port", "8123"],
        run_server=fake_runner,
    )

    assert exit_code == 0
    assert calls["host"] == "127.0.0.2"
    assert calls["port"] == 8123
    assert TestClient(calls["app"]).get("/api/health").json() == {
        "status": "ok",
        "database": "configured",
    }
    assert (data_dir / "wfrp_companion.sqlite").exists()


def test_main_honors_explicit_db_path(tmp_path: Path) -> None:
    data_dir = tmp_path / "private-data"
    db_path = tmp_path / "custom" / "api.sqlite"
    calls: dict[str, object] = {}

    def fake_runner(app: object, host: str, port: int) -> None:
        calls["app"] = app
        calls["host"] = host
        calls["port"] = port

    exit_code = serve_api.main(
        [
            "--data-dir",
            str(data_dir),
            "--db-path",
            str(db_path),
        ],
        run_server=fake_runner,
    )

    assert exit_code == 0
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8000
    assert db_path.exists()
    assert not (data_dir / "wfrp_companion.sqlite").exists()


def test_run_uvicorn_delegates_to_uvicorn_run(monkeypatch) -> None:
    calls: dict[str, object] = {}
    app = FastAPI()

    def fake_run(app_arg: object, *, host: str, port: int) -> None:
        calls["app"] = app_arg
        calls["host"] = host
        calls["port"] = port

    monkeypatch.setattr(serve_api.uvicorn, "run", fake_run)

    serve_api.run_uvicorn(app, "127.0.0.9", 9999)

    assert calls == {"app": app, "host": "127.0.0.9", "port": 9999}
