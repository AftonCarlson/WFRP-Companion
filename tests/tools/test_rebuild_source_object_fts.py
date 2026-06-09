from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from tests.source_objects.test_store import insert_indexed_book, make_config
from tools.rebuild_source_object_fts import main
from tools.rebuild_source_object_fts import safe_failure_reason
from wfrp_companion.db.connection import open_connection
from wfrp_companion.source_objects.extractor import extract_source_object_library


def test_rebuild_source_object_fts_cli_repairs_missing_projection(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute("delete from source_object_search where book_id = 'rules'")

    exit_code = main(["--db-path", str(config.db_path)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "WFRP source object FTS rebuild" in output
    assert "Books indexed: 1" in output
    assert "Objects written: 2" in output
    assert "Critical Hits" not in output


def test_rebuild_source_object_fts_cli_returns_failure_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    make_config(tmp_path)

    def fail_rebuild(config, **kwargs):  # noqa: ANN001
        from wfrp_companion.source_objects.store import (
            ObjectSearchRebuildFailure,
            ObjectSearchRebuildSummary,
        )

        return ObjectSearchRebuildSummary(
            discovered=1,
            indexed=0,
            skipped_current=0,
            stale_recovered=0,
            failed=1,
            objects_written=0,
            failures=(
                ObjectSearchRebuildFailure(
                    "rules",
                    "synthetic failure " + ("x" * 240),
                ),
            ),
        )

    monkeypatch.setattr(
        "tools.rebuild_source_object_fts.rebuild_source_object_search",
        fail_rebuild,
    )

    exit_code = main(["--db-path", str(tmp_path / "missing.sqlite")])

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "synthetic failure" in output
    assert "x" * 200 not in output


def test_safe_failure_reason_keeps_short_messages() -> None:
    assert safe_failure_reason("  short\nmessage\t ") == "short message"


def test_rebuild_source_object_fts_script_path_entrypoint(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute("delete from source_object_search where book_id = 'rules'")

    completed = subprocess.run(
        [
            sys.executable,
            "tools/rebuild_source_object_fts.py",
            "--db-path",
            str(config.db_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Books indexed: 1" in completed.stdout


def test_rebuild_source_object_fts_script_main_path_is_covered_in_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute("delete from source_object_search where book_id = 'rules'")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tools/rebuild_source_object_fts.py",
            "--db-path",
            str(config.db_path),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path("tools/rebuild_source_object_fts.py", run_name="__main__")

    assert exit_info.value.code == 0
    assert "Books indexed: 1" in capsys.readouterr().out
