from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol


class DevServerError(Exception):
    pass


class DevProcess(Protocol):
    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...


ProcessFactory = Callable[[Sequence[str], Path], DevProcess]
ProbeUrl = Callable[[str], None]
WaitForInterrupt = Callable[[Sequence[DevProcess]], int]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the local WFRP Companion API and browser GUI together."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root. Defaults to the current checkout.",
    )
    parser.add_argument("--backend-host", default="127.0.0.1")
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-host", default="127.0.0.1")
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument("--probe-timeout-seconds", type=float, default=20.0)
    return parser


def default_process_factory(command: Sequence[str], cwd: Path) -> DevProcess:
    return subprocess.Popen(command, cwd=cwd)  # noqa: S603


def backend_command(args: argparse.Namespace) -> tuple[str, ...]:
    return (
        "python",
        "tools/serve_api.py",
        "--host",
        args.backend_host,
        "--port",
        str(args.backend_port),
    )


def frontend_command(args: argparse.Namespace) -> tuple[str, ...]:
    return (
        "npm",
        "run",
        "dev",
        "--",
        "--host",
        args.frontend_host,
        "--port",
        str(args.frontend_port),
    )


def backend_url(args: argparse.Namespace) -> str:
    return f"http://{args.backend_host}:{args.backend_port}/api/health"


def frontend_url(args: argparse.Namespace) -> str:
    return f"http://{args.frontend_host}:{args.frontend_port}/"


def validate_repo(repo_root: Path) -> None:
    if not (repo_root / "frontend" / "package.json").exists():
        raise DevServerError(f"Missing frontend/package.json under {repo_root}")
    if not (repo_root / "tools" / "serve_api.py").exists():
        raise DevServerError(f"Missing tools/serve_api.py under {repo_root}")


def probe_url(url: str, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:  # noqa: S310
                if 200 <= response.status < 500:
                    return
        except (OSError, urllib.error.URLError) as error:
            last_error = error
        time.sleep(0.2)
    detail = f": {last_error}" if last_error else ""
    raise DevServerError(f"Timed out waiting for {url}{detail}")


def shutdown_processes(
    processes: Sequence[DevProcess],
    *,
    terminate_timeout_seconds: float = 5.0,
) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=terminate_timeout_seconds)
        except (TimeoutError, subprocess.TimeoutExpired):
            process.kill()
            process.wait(timeout=terminate_timeout_seconds)


def wait_for_interrupt(processes: Sequence[DevProcess]) -> int:
    try:
        while True:
            for process in processes:
                returncode = process.poll()
                if returncode is not None:
                    return returncode
            time.sleep(0.25)
    except KeyboardInterrupt:
        return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    process_factory: ProcessFactory = default_process_factory,
    probe_url: Callable[[str], None] | Callable[..., None] = probe_url,
    wait_for_interrupt: WaitForInterrupt = wait_for_interrupt,
) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    validate_repo(repo_root)

    processes: list[DevProcess] = []
    try:
        processes.append(process_factory(backend_command(args), repo_root))
        processes.append(process_factory(frontend_command(args), repo_root / "frontend"))
        probe_url(backend_url(args), timeout_seconds=args.probe_timeout_seconds)
        probe_url(frontend_url(args), timeout_seconds=args.probe_timeout_seconds)
        print(f"Backend:  {backend_url(args)}")
        print(f"Frontend: {frontend_url(args)}")
        return wait_for_interrupt(processes)
    except Exception:
        shutdown_processes(processes)
        raise
    finally:
        shutdown_processes(processes)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
