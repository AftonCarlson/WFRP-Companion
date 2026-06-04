from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tools.search_text import main
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.search.fts import rebuild_global_fts


def insert_indexed_book(db_path: Path, data_dir: Path) -> None:
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
    rebuild_global_fts(
        AppConfig(
            pdf_root=data_dir / "pdfs",
            data_dir=data_dir,
            db_path=db_path,
            asset_dir=data_dir / "library" / "assets",
        )
    )


def test_main_prints_search_hits(capsys, tmp_path: Path) -> None:
    data_dir = tmp_path / "private-data"
    db_path = data_dir / "wfrp_companion.sqlite"
    insert_indexed_book(db_path, data_dir)

    exit_code = main(["--data-dir", str(data_dir), "critical", "hit"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "WFRP exact text search" in output
    assert "Query: critical hit" in output
    assert "Hits: 1" in output
    assert "1. Core Rules p. 1 [core-rules:1]" in output
    assert "[Critical]" in output


def test_main_honors_explicit_db_path(capsys, tmp_path: Path) -> None:
    data_dir = tmp_path / "private-data"
    db_path = tmp_path / "custom" / "library.sqlite"
    insert_indexed_book(db_path, data_dir)

    exit_code = main(
        [
            "--data-dir",
            str(data_dir),
            "--db-path",
            str(db_path),
            "--book-id",
            "core-rules",
            "--limit",
            "5",
            "critical",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Hits: 1" in output
    assert not (data_dir / "wfrp_companion.sqlite").exists()


def test_main_prints_zero_hits(capsys, tmp_path: Path) -> None:
    data_dir = tmp_path / "private-data"
    db_path = data_dir / "wfrp_companion.sqlite"
    insert_indexed_book(db_path, data_dir)

    exit_code = main(["--data-dir", str(data_dir), "wyrdstone"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Hits: 0" in output


def test_search_text_script_runs_from_file_path(tmp_path: Path) -> None:
    data_dir = tmp_path / "private-data"
    db_path = data_dir / "wfrp_companion.sqlite"
    insert_indexed_book(db_path, data_dir)
    script_path = Path(__file__).resolve().parents[2] / "tools" / "search_text.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--data-dir",
            str(data_dir),
            "critical",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "Hits: 1" in completed.stdout
