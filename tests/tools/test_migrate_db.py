from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from tests.db.test_migrations import create_legacy_phase6_database
from tools.migrate_db import main
from wfrp_companion.db.connection import open_connection


def test_migrate_db_cli_applies_pending_migrations(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "legacy.sqlite"
    create_legacy_phase6_database(db_path)

    exit_code = main(["--db-path", str(db_path)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Applied migrations: 0001_phase_7_source_objects" in output
    assert "Row counts:" in output
    assert "books=1" in output
    assert "retrieval_hits=1" in output
    assert "critical hits" not in output
    with open_connection(db_path) as connection:
        assert (
            connection.execute(
                "select id from schema_migrations where id = ?",
                ("0001_phase_7_source_objects",),
            ).fetchone()
            is not None
        )


def test_migrate_db_cli_reports_no_pending_migrations(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "legacy.sqlite"
    create_legacy_phase6_database(db_path)
    assert main(["--db-path", str(db_path)]) == 0

    exit_code = main(["--db-path", str(db_path)])

    assert exit_code == 0
    assert "No pending migrations." in capsys.readouterr().out


def test_migrate_db_script_path_entrypoint_applies_migrations(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy.sqlite"
    create_legacy_phase6_database(db_path)

    completed = subprocess.run(
        [
            sys.executable,
            "tools/migrate_db.py",
            "--db-path",
            str(db_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Applied migrations: 0001_phase_7_source_objects" in completed.stdout


def test_migrate_db_script_main_path_is_covered_in_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "legacy.sqlite"
    create_legacy_phase6_database(db_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tools/migrate_db.py",
            "--db-path",
            str(db_path),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path("tools/migrate_db.py", run_name="__main__")

    assert exit_info.value.code == 0
    assert "Applied migrations: 0001_phase_7_source_objects" in capsys.readouterr().out
