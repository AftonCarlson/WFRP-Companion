from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from tests.source_objects.test_store import insert_indexed_book, make_config
from tools.rebuild_source_maps import main
from tools.rebuild_source_maps import safe_failure_reason
from wfrp_companion.db.connection import open_connection
from wfrp_companion.source_objects.extractor import extract_source_object_library
from wfrp_companion.source_objects.source_map_builder import (
    source_map_job_id,
    source_object_snapshot_sha256,
)


def test_rebuild_source_maps_cli_persists_profiles(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)

    exit_code = main(["--db-path", str(config.db_path)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "WFRP source map rebuild" in output
    assert "Books indexed: 1" in output
    assert "Critical Hits" not in output


def test_rebuild_source_maps_cli_returns_failure_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = make_config(tmp_path)

    def fail_rebuild(config, **kwargs):  # noqa: ANN001
        from wfrp_companion.source_objects.source_map_builder import (
            SourceMapFailure,
            SourceMapRebuildSummary,
        )

        return SourceMapRebuildSummary(
            discovered=1,
            indexed=0,
            skipped_current=0,
            stale_recovered=0,
            failed=1,
            failures=(SourceMapFailure("rules", "synthetic failure " + ("x" * 240)),),
            book_summaries=(),
        )

    monkeypatch.setattr("tools.rebuild_source_maps.rebuild_source_maps", fail_rebuild)

    exit_code = main(["--db-path", str(config.db_path)])

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "synthetic failure" in output
    assert "x" * 200 not in output


def test_rebuild_source_maps_cli_returns_failure_for_job_claim_conflict(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        snapshot = source_object_snapshot_sha256(connection, "rules")
        job_id = source_map_job_id("rules", snapshot)
        connection.execute(
            """
            update book_retrieval_status
            set source_map_status = 'needs_refresh',
                updated_at = '2999-01-01T00:00:00Z'
            where book_id = 'rules'
            """
        )
        connection.execute(
            """
            insert into ingest_jobs (
              id,
              job_type,
              target_id,
              status,
              idempotency_key,
              attempts,
              created_at,
              updated_at
            )
            values (?, 'rebuild_source_maps', 'rules', 'running', ?, 1,
                    '2999-01-01T00:00:00Z', '2999-01-01T00:00:00Z')
            """,
            (job_id, job_id),
        )

    exit_code = main(["--db-path", str(config.db_path)])

    assert exit_code == 1
    assert "Could not claim source-map rebuild job." in capsys.readouterr().out


def test_safe_failure_reason_keeps_short_messages() -> None:
    assert safe_failure_reason("  short\nmessage\t ") == "short message"


def test_rebuild_source_maps_script_path_entrypoint(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)

    completed = subprocess.run(
        [
            sys.executable,
            "tools/rebuild_source_maps.py",
            "--db-path",
            str(config.db_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Books indexed: 1" in completed.stdout


def test_rebuild_source_maps_script_main_path_is_covered_in_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tools/rebuild_source_maps.py",
            "--db-path",
            str(config.db_path),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path("tools/rebuild_source_maps.py", run_name="__main__")

    assert exit_info.value.code == 0
    assert "Books indexed: 1" in capsys.readouterr().out
