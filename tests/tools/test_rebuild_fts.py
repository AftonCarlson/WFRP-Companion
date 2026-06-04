from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

from tools.rebuild_fts import main
from wfrp_companion.db.connection import initialize_database


def insert_imported_book(db_path: Path) -> None:
    with initialize_database(db_path) as connection:
        connection.execute(
            """
            insert into library_folders (id, parent_id, name, relative_path, sort_order)
            values ('core', null, 'Core', 'Core', 0)
            """
        )
        connection.execute(
            """
            insert into books (
              id,
              folder_id,
              title,
              category,
              relative_path,
              original_source_path,
              managed_pdf_path,
              original_sha256,
              managed_sha256,
              page_count,
              copy_status,
              text_status,
              search_status,
              visual_status,
              discovered_at,
              updated_at
            )
            values (
              'core-rules', 'core', 'Core Rules', 'Core',
              'Core/Core Rules.pdf', '/source/Core Rules.pdf',
              '/managed/Core Rules.pdf', 'source-sha', 'source-sha', 1,
              'copied', 'imported', 'not_indexed', 'not_scanned',
              '2026-06-04T00:00:00Z', '2026-06-04T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            insert into pages (
              id,
              book_id,
              page_number,
              extraction_method,
              embedded_text_chars,
              text_chars,
              word_count,
              image_count,
              ocr_attempted,
              has_text
            )
            values ('core-rules:1', 'core-rules', 1, 'ocr', 0, 18, 3, 1, 1, 1)
            """
        )
        connection.execute(
            """
            insert into page_text (page_id, text, text_sha256, generated_at)
            values (
              'core-rules:1',
              'Critical hit rules',
              'text-sha',
              '2026-06-04T00:00:00Z'
            )
            """
        )


def search_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as connection:
        return connection.execute("select count(*) from page_search").fetchone()[0]


def test_main_rebuilds_fts_from_data_dir_default(capsys, tmp_path: Path) -> None:
    data_dir = tmp_path / "private-data"
    db_path = data_dir / "wfrp_companion.sqlite"
    insert_imported_book(db_path)

    exit_code = main(["--data-dir", str(data_dir)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert search_count(db_path) == 1
    assert "WFRP global FTS rebuild" in output
    assert f"DB path: {db_path}" in output
    assert "Books indexed: 1" in output
    assert "Pages indexed: 1" in output
    assert "Failed: 0" in output


def test_main_honors_explicit_db_path(tmp_path: Path) -> None:
    data_dir = tmp_path / "private-data"
    db_path = tmp_path / "custom" / "library.sqlite"
    insert_imported_book(db_path)

    exit_code = main(
        [
            "--data-dir",
            str(data_dir),
            "--db-path",
            str(db_path),
            "--force",
            "--retry-running",
            "--stale-running-minutes",
            "0",
        ]
    )

    assert exit_code == 0
    assert search_count(db_path) == 1
    assert not (data_dir / "wfrp_companion.sqlite").exists()


def test_main_returns_nonzero_when_rebuild_fails(monkeypatch, capsys) -> None:
    from tools import rebuild_fts

    def fail_rebuild(*_args, **_kwargs):
        return rebuild_fts.FtsRebuildSummary(
            books_indexed=0,
            pages_indexed=0,
            skipped_current=0,
            stale_recovered=0,
            failed=1,
            failure_reason="boom",
        )

    monkeypatch.setattr(rebuild_fts, "rebuild_global_fts", fail_rebuild)

    exit_code = main([])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Failed: 1" in output
    assert "Failure: boom" in output


def test_rebuild_fts_script_runs_from_file_path(tmp_path: Path) -> None:
    data_dir = tmp_path / "private-data"
    db_path = data_dir / "wfrp_companion.sqlite"
    insert_imported_book(db_path)
    script_path = Path(__file__).resolve().parents[2] / "tools" / "rebuild_fts.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--data-dir",
            str(data_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "Books indexed: 1" in completed.stdout
