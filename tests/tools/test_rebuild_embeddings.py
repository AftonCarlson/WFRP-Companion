from __future__ import annotations

import runpy
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from tests.source_objects.test_store import insert_indexed_book, make_config
from tools.rebuild_embeddings import main
from tools.rebuild_embeddings import safe_failure_reason
from wfrp_companion.source_objects.extractor import extract_source_object_library


def test_rebuild_embeddings_cli_indexes_when_local_provider_enabled(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = replace(
        make_config(tmp_path),
        embedding_provider="local-hash",
        embedding_model="local-hash-test",
        embedding_dimensions=16,
    )
    insert_indexed_book(config)
    extract_source_object_library(config)

    exit_code = main(
        [
            "--db-path",
            str(config.db_path),
            "--embedding-provider",
            "local-hash",
            "--embedding-model",
            "local-hash-test",
            "--embedding-dimensions",
            "16",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "WFRP embedding rebuild" in output
    assert "Books indexed: 1" in output
    assert "Embeddings written: 2" in output
    assert "Critical Hits" not in output


def test_rebuild_embeddings_cli_reports_disabled_provider(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)

    exit_code = main(["--db-path", str(config.db_path)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Skipped disabled: 1" in output
    assert "Embeddings written: 0" in output


def test_rebuild_embeddings_cli_returns_failure_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    make_config(tmp_path)

    def fail_rebuild(config, **kwargs):  # noqa: ANN001
        from wfrp_companion.source_objects.embeddings import (
            EmbeddingRebuildFailure,
            EmbeddingRebuildSummary,
        )

        return EmbeddingRebuildSummary(
            discovered=1,
            indexed=0,
            skipped_current=0,
            skipped_disabled=0,
            stale_recovered=0,
            failed=1,
            embeddings_written=0,
            failures=(
                EmbeddingRebuildFailure(
                    "rules",
                    "synthetic failure " + ("x" * 240),
                ),
            ),
        )

    monkeypatch.setattr("tools.rebuild_embeddings.rebuild_embeddings", fail_rebuild)

    exit_code = main(["--db-path", str(tmp_path / "missing.sqlite")])

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "synthetic failure" in output
    assert "x" * 200 not in output


def test_safe_failure_reason_keeps_short_messages() -> None:
    assert safe_failure_reason("  short\nmessage\t ") == "short message"


def test_rebuild_embeddings_script_path_entrypoint(tmp_path: Path) -> None:
    config = replace(
        make_config(tmp_path),
        embedding_provider="local-hash",
        embedding_model="local-hash-test",
        embedding_dimensions=16,
    )
    insert_indexed_book(config)
    extract_source_object_library(config)

    completed = subprocess.run(
        [
            sys.executable,
            "tools/rebuild_embeddings.py",
            "--db-path",
            str(config.db_path),
            "--embedding-provider",
            "local-hash",
            "--embedding-model",
            "local-hash-test",
            "--embedding-dimensions",
            "16",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Books indexed: 1" in completed.stdout


def test_rebuild_embeddings_script_main_path_is_covered_in_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = replace(
        make_config(tmp_path),
        embedding_provider="local-hash",
        embedding_model="local-hash-test",
        embedding_dimensions=16,
    )
    insert_indexed_book(config)
    extract_source_object_library(config)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tools/rebuild_embeddings.py",
            "--db-path",
            str(config.db_path),
            "--embedding-provider",
            "local-hash",
            "--embedding-model",
            "local-hash-test",
            "--embedding-dimensions",
            "16",
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path("tools/rebuild_embeddings.py", run_name="__main__")

    assert exit_info.value.code == 0
    assert "Books indexed: 1" in capsys.readouterr().out
