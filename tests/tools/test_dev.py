from __future__ import annotations

from pathlib import Path
from typing import Sequence
import subprocess
import urllib.error

import pytest

from tools import dev


class FakeProcess:
    def __init__(self, name: str, returncode: int | None = None) -> None:
        self.name = name
        self.returncode = returncode
        self.terminated = False
        self.killed = False
        self.wait_calls: list[float | None] = []

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        if self.returncode is None:
            raise TimeoutError
        return self.returncode


class StubbornProcess(FakeProcess):
    def terminate(self) -> None:
        self.terminated = True


def make_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    frontend = repo_root / "frontend"
    frontend.mkdir(parents=True)
    (frontend / "package.json").write_text("{}", encoding="utf-8")
    (repo_root / "tools").mkdir()
    (repo_root / "tools" / "serve_api.py").write_text("", encoding="utf-8")
    return repo_root


def test_main_starts_backend_and_frontend_with_local_defaults(tmp_path: Path) -> None:
    repo_root = make_repo(tmp_path)
    launched: list[tuple[Sequence[str], Path]] = []
    probes: list[str] = []
    processes = [FakeProcess("backend"), FakeProcess("frontend")]

    def process_factory(command: Sequence[str], cwd: Path) -> FakeProcess:
        launched.append((tuple(command), cwd))
        return processes[len(launched) - 1]

    def probe(url: str, *, timeout_seconds: float) -> None:
        probes.append(url)

    exit_code = dev.main(
        ["--repo-root", str(repo_root)],
        process_factory=process_factory,
        probe_url=probe,
        wait_for_interrupt=lambda running: 0,
    )

    assert exit_code == 0
    assert launched == [
        (
            (
                "python",
                "tools/serve_api.py",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ),
            repo_root,
        ),
        (
            (
                "npm",
                "run",
                "dev",
                "--",
                "--host",
                "127.0.0.1",
                "--port",
                "5173",
            ),
            repo_root / "frontend",
        ),
    ]
    assert probes == ["http://127.0.0.1:8000/api/health", "http://127.0.0.1:5173/"]


def test_main_cleans_up_both_processes_when_readiness_probe_fails(
    tmp_path: Path,
) -> None:
    repo_root = make_repo(tmp_path)
    processes = [FakeProcess("backend"), FakeProcess("frontend")]

    def process_factory(command: Sequence[str], cwd: Path) -> FakeProcess:
        return processes.pop(0)

    started = list(processes)

    def probe(url: str, *, timeout_seconds: float) -> None:
        raise dev.DevServerError("not ready")

    with pytest.raises(dev.DevServerError, match="not ready"):
        dev.main(
            ["--repo-root", str(repo_root)],
            process_factory=process_factory,
            probe_url=probe,
            wait_for_interrupt=lambda running: 0,
        )

    assert [process.terminated for process in started] == [True, True]


def test_main_reports_missing_frontend_package_before_spawning(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    spawned = False

    def process_factory(command: Sequence[str], cwd: Path) -> FakeProcess:
        nonlocal spawned
        spawned = True
        return FakeProcess("unexpected")

    with pytest.raises(dev.DevServerError, match="frontend/package.json"):
        dev.main(
            ["--repo-root", str(repo_root)],
            process_factory=process_factory,
            probe_url=lambda url, *, timeout_seconds: None,
            wait_for_interrupt=lambda running: 0,
        )

    assert spawned is False


def test_validate_repo_reports_missing_api_tool(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "frontend").mkdir(parents=True)
    (repo_root / "frontend" / "package.json").write_text("{}", encoding="utf-8")

    with pytest.raises(dev.DevServerError, match="tools/serve_api.py"):
        dev.validate_repo(repo_root)


def test_default_process_factory_delegates_to_subprocess_popen(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: dict[str, object] = {}

    def fake_popen(command: Sequence[str], cwd: Path) -> FakeProcess:
        calls["command"] = tuple(command)
        calls["cwd"] = cwd
        return FakeProcess("spawned")

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    process = dev.default_process_factory(("python", "--version"), tmp_path)

    assert isinstance(process, FakeProcess)
    assert calls == {"command": ("python", "--version"), "cwd": tmp_path}


def test_probe_url_returns_for_http_response_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status = 204

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

    monkeypatch.setattr(dev.urllib.request, "urlopen", lambda url, timeout: FakeResponse())

    dev.probe_url("http://127.0.0.1:5173", timeout_seconds=0.1)


def test_probe_url_reports_last_error_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    times = iter([0.0, 0.1, 2.0])

    monkeypatch.setattr(dev.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(dev.time, "sleep", lambda seconds: None)

    def raise_url_error(url: str, timeout: float) -> None:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(dev.urllib.request, "urlopen", raise_url_error)

    with pytest.raises(dev.DevServerError, match="offline"):
        dev.probe_url("http://127.0.0.1:5173", timeout_seconds=1.0)


def test_wait_for_interrupt_returns_process_exit_code() -> None:
    assert dev.wait_for_interrupt([FakeProcess("frontend", returncode=17)]) == 17


def test_wait_for_interrupt_handles_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dev.time, "sleep", lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt))

    assert dev.wait_for_interrupt([FakeProcess("frontend")]) == 0


def test_shutdown_kills_process_that_ignores_terminate() -> None:
    stubborn = StubbornProcess("stubborn")

    dev.shutdown_processes([stubborn], terminate_timeout_seconds=0.1)

    assert stubborn.terminated is True
    assert stubborn.killed is True
