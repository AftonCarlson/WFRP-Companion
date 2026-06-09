from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from tests.source_objects.test_store import insert_indexed_book, make_config
from tools.extract_source_objects import main
from tools.extract_source_objects import safe_failure_reason


def test_extract_source_objects_cli_extracts_books(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)

    exit_code = main(["--db-path", str(config.db_path)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "WFRP source object extraction" in output
    assert "Books extracted: 1" in output
    assert "Objects written: 2" in output
    assert "Critical Hits" not in output


def test_extract_source_objects_cli_returns_failure_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)

    def fail_extraction(config, **kwargs):  # noqa: ANN001
        from wfrp_companion.source_objects.extractor import (
            ExtractionFailure,
            ExtractionSummary,
        )

        return ExtractionSummary(
            discovered=1,
            extracted=0,
            skipped_current=0,
            stale_recovered=0,
            failed=1,
            objects_written=0,
            failures=(ExtractionFailure("rules", "synthetic failure " + ("x" * 240)),),
            book_summaries=(),
        )

    monkeypatch.setattr(
        "tools.extract_source_objects.extract_source_object_library",
        fail_extraction,
    )

    exit_code = main(["--db-path", str(config.db_path)])

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "synthetic failure" in output
    assert "x" * 200 not in output


def test_safe_failure_reason_keeps_short_messages() -> None:
    assert safe_failure_reason("  short\nmessage\t ") == "short message"


def test_extract_source_objects_script_path_entrypoint(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)

    completed = subprocess.run(
        [
            sys.executable,
            "tools/extract_source_objects.py",
            "--db-path",
            str(config.db_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Books extracted: 1" in completed.stdout


def test_extract_source_objects_script_main_path_is_covered_in_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tools/extract_source_objects.py",
            "--db-path",
            str(config.db_path),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path("tools/extract_source_objects.py", run_name="__main__")

    assert exit_info.value.code == 0
    assert "Books extracted: 1" in capsys.readouterr().out
