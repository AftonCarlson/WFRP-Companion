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


def test_config_from_args_preserves_openai_runtime_settings(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("WFRP_OPENAI_MODEL", "test-model")
    monkeypatch.setenv("WFRP_OPENAI_TIMEOUT_SECONDS", "7.5")
    monkeypatch.setenv("WFRP_CHAT_CONTEXT_HIT_LIMIT", "2")
    monkeypatch.setenv("WFRP_CHAT_CONTEXT_CHAR_LIMIT", "300")
    monkeypatch.setenv("WFRP_CHAT_CONTEXT_WINDOW_CHARS", "100")
    monkeypatch.setenv("WFRP_CHAT_PROMPT_HISTORY_TURN_LIMIT", "5")
    monkeypatch.setenv("WFRP_CHAT_PROMPT_HISTORY_CHAR_LIMIT", "700")
    monkeypatch.setenv("WFRP_CHAT_RETRIEVAL_HISTORY_TURN_LIMIT", "3")
    monkeypatch.setenv("WFRP_CHAT_RETRIEVAL_QUERY_CHAR_LIMIT", "450")
    monkeypatch.setenv("WFRP_EMBEDDING_PROVIDER", "local-hash")
    monkeypatch.setenv("WFRP_EMBEDDING_MODEL", "local-hash-test")
    monkeypatch.setenv("WFRP_EMBEDDING_DIMENSIONS", "16")
    monkeypatch.setenv("WFRP_EMBEDDING_BATCH_SIZE", "8")
    monkeypatch.setenv("WFRP_EMBEDDING_DEVICE", "mps")
    monkeypatch.setenv("WFRP_EMBEDDING_QUERY_PROMPT_NAME", "query")
    monkeypatch.setenv("WFRP_EMBEDDING_LOCAL_FILES_ONLY", "true")

    config = serve_api.config_from_args(
        serve_api.build_parser().parse_args(["--data-dir", str(tmp_path / "data")])
    )

    assert config.openai_api_key == "test-key"
    assert config.openai_model == "test-model"
    assert config.openai_timeout_seconds == 7.5
    assert config.chat_context_hit_limit == 2
    assert config.chat_context_char_limit == 300
    assert config.chat_context_window_chars == 100
    assert config.chat_prompt_history_turn_limit == 5
    assert config.chat_prompt_history_char_limit == 700
    assert config.chat_retrieval_history_turn_limit == 3
    assert config.chat_retrieval_query_char_limit == 450
    assert config.embedding_provider == "local-hash"
    assert config.embedding_model == "local-hash-test"
    assert config.embedding_dimensions == 16
    assert config.embedding_batch_size == 8
    assert config.embedding_device == "mps"
    assert config.embedding_query_prompt_name == "query"
    assert config.embedding_local_files_only is True


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
