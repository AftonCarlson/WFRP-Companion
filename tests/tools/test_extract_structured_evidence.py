from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from tests.source_objects.test_store import insert_indexed_book, make_config
from tools.extract_structured_evidence import main, safe_failure_reason
from wfrp_companion.db.connection import initialize_database, open_connection


def insert_table_source_objects(config) -> None:  # noqa: ANN001
    with initialize_database(config.db_path) as connection:
        connection.execute(
            """
            insert into book_object_status (
              book_id,
              status,
              object_count,
              table_count,
              stat_block_count,
              location_count,
              text_snapshot_sha256,
              extractor_version,
              updated_at
            )
            values (
              'rules',
              'indexed',
              2,
              1,
              0,
              0,
              'snapshot',
              'test',
              '2026-06-10T00:00:00Z'
            )
            """
        )
        for object_id, object_type, title, text, parent in (
            (
                "table",
                "table",
                "Table 5-6: Advanced Armour",
                "Table 5-6: Advanced Armour\n| Location | AP |",
                None,
            ),
            ("row", "table_row", "Advanced Armour row 1", "| Head | 1 |", "table"),
        ):
            connection.execute(
                """
                insert into source_objects (
                  id,
                  book_id,
                  page_id,
                  object_type,
                  parent_object_id,
                  title,
                  heading_path_json,
                  page_start,
                  page_end,
                  text,
                  search_text,
                  confidence,
                  extraction_method,
                  text_snapshot_sha256,
                  created_at,
                  updated_at
                )
                values (
                  ?,
                  'rules',
                  'rules:1',
                  ?,
                  ?,
                  ?,
                  '["Chapter V", "Armour"]',
                  1,
                  1,
                  ?,
                  ?,
                  0.8,
                  'test',
                  'snapshot',
                  '2026-06-10T00:00:00Z',
                  '2026-06-10T00:00:00Z'
                )
                """,
                (object_id, object_type, parent, title, text, text),
            )
        connection.execute(
            """
            insert into source_object_links (
              id,
              from_object_id,
              to_object_id,
              link_type,
              label,
              confidence,
              created_at
            )
            values (
              'row-to-table',
              'row',
              'table',
              'table_row',
              'Advanced Armour row',
              0.9,
              '2026-06-10T00:00:00Z'
            )
            """
        )


def count_rows(config, table: str) -> int:  # noqa: ANN001
    allowed_tables = {
        "structured_reader_observations",
        "structured_evidence_candidates",
    }
    if table not in allowed_tables:
        raise ValueError(f"Unexpected test table: {table}")
    with open_connection(config.db_path) as connection:
        return connection.execute(f"select count(*) from {table}").fetchone()[0]


def test_extract_structured_evidence_cli_writes_candidates_count_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    insert_table_source_objects(config)

    exit_code = main(["--db-path", str(config.db_path)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "WFRP structured evidence extraction" in output
    assert "Books extracted: 1" in output
    assert "Candidates written: 1" in output
    assert "Advanced Armour" not in output
    assert count_rows(config, "structured_reader_observations") == 2
    assert count_rows(config, "structured_evidence_candidates") == 1
    with open_connection(config.db_path) as connection:
        status = connection.execute(
            """
            select structured_evidence_status
            from book_retrieval_status
            where book_id = 'rules'
            """
        ).fetchone()
    assert status["structured_evidence_status"] == "indexed"


def test_extract_structured_evidence_cli_returns_failure_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = make_config(tmp_path)

    def fail_extraction(config, **kwargs):  # noqa: ANN001
        from wfrp_companion.structured_evidence.store import (
            StructuredEvidenceExtractionFailure,
            StructuredEvidenceExtractionSummary,
        )

        return StructuredEvidenceExtractionSummary(
            discovered=1,
            extracted=0,
            skipped_current=0,
            stale_recovered=0,
            failed=1,
            observations_written=0,
            candidates_written=0,
            needs_review=0,
            failures=(
                StructuredEvidenceExtractionFailure(
                    "rules",
                    "synthetic failure " + ("x" * 240),
                ),
            ),
        )

    monkeypatch.setattr(
        "tools.extract_structured_evidence.extract_structured_evidence_library",
        fail_extraction,
    )

    exit_code = main(["--db-path", str(config.db_path)])

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "synthetic failure" in output
    assert "x" * 200 not in output


def test_safe_failure_reason_keeps_short_messages() -> None:
    assert safe_failure_reason("  short\nmessage\t ") == "short message"


def test_extract_structured_evidence_script_path_entrypoint(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    insert_table_source_objects(config)

    completed = subprocess.run(
        [
            sys.executable,
            "tools/extract_structured_evidence.py",
            "--db-path",
            str(config.db_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Books extracted: 1" in completed.stdout


def test_extract_structured_evidence_script_main_path_is_covered_in_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    insert_table_source_objects(config)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tools/extract_structured_evidence.py",
            "--db-path",
            str(config.db_path),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path("tools/extract_structured_evidence.py", run_name="__main__")

    assert exit_info.value.code == 0
    assert "Books extracted: 1" in capsys.readouterr().out
