from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tools.import_page_text import main
from wfrp_companion.db.connection import initialize_database


def insert_copied_book(db_path: Path) -> None:
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
              'copied', 'not_imported', 'not_indexed', 'not_scanned',
              '2026-06-04T00:00:00Z', '2026-06-04T00:00:00Z'
            )
            """
        )


def write_page_text(input_dir: Path) -> None:
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "core-rules.json").write_text(
        json.dumps(
            {
                "book_id": "core-rules",
                "title": "Core Rules",
                "category": "Core",
                "source_path": "/source/Core Rules.pdf",
                "source_sha256": "source-sha",
                "page_count": 1,
                "generated_at": "2026-06-04T00:00:00Z",
                "ocr_language": "eng",
                "ocr_dpi": 200,
                "low_text_chars_threshold": 100,
                "pages": [
                    {
                        "page_number": 1,
                        "text": "Critical hit rules",
                        "extraction_method": "ocr",
                        "embedded_text_chars": 0,
                        "text_chars": 18,
                        "word_count": 3,
                        "image_count": 1,
                        "ocr_attempted": True,
                        "ocr_error": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def page_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as connection:
        return connection.execute("select count(*) from pages").fetchone()[0]


def test_main_imports_page_text_from_data_dir_default(capsys, tmp_path: Path) -> None:
    data_dir = tmp_path / "private-data"
    db_path = data_dir / "wfrp_companion.sqlite"
    insert_copied_book(db_path)
    write_page_text(data_dir / "page_text")

    exit_code = main(["--data-dir", str(data_dir)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert page_count(db_path) == 1
    assert "WFRP page text import" in output
    assert f"Input dir: {data_dir / 'page_text'}" in output
    assert f"DB path: {db_path}" in output
    assert "Imported: 1" in output
    assert "Pages imported: 1" in output
    assert "Failed: 0" in output


def test_main_honors_explicit_db_and_input_paths(tmp_path: Path) -> None:
    data_dir = tmp_path / "private-data"
    db_path = tmp_path / "custom" / "library.sqlite"
    input_dir = tmp_path / "page-text-json"
    insert_copied_book(db_path)
    write_page_text(input_dir)

    exit_code = main(
        [
            "--data-dir",
            str(data_dir),
            "--db-path",
            str(db_path),
            "--input-dir",
            str(input_dir),
        ]
    )

    assert exit_code == 0
    assert page_count(db_path) == 1
    assert not (data_dir / "wfrp_companion.sqlite").exists()


def test_main_missing_input_dir_exits_before_initializing_db(
    capsys,
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "missing"
    db_path = tmp_path / "db" / "wfrp.sqlite"

    exit_code = main(["--input-dir", str(input_dir), "--db-path", str(db_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert not db_path.exists()
    assert f"Input dir does not exist or is not a directory: {input_dir}" in (
        captured.err
    )


def test_main_returns_nonzero_and_prints_failure_details(
    capsys,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "private-data"
    input_dir = data_dir / "page_text"
    input_dir.mkdir(parents=True)
    (input_dir / "broken.json").write_text("{not json", encoding="utf-8")

    exit_code = main(["--data-dir", str(data_dir)])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Failed: 1" in output
    assert "Failures:" in output
    assert "- broken.json [unknown]: Invalid JSON" in output


def test_import_page_text_script_runs_from_file_path(tmp_path: Path) -> None:
    data_dir = tmp_path / "private-data"
    db_path = data_dir / "wfrp_companion.sqlite"
    insert_copied_book(db_path)
    write_page_text(data_dir / "page_text")
    script_path = Path(__file__).resolve().parents[2] / "tools" / "import_page_text.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--data-dir",
            str(data_dir),
            "--retry-running",
            "--stale-running-minutes",
            "0",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "Imported: 1" in completed.stdout
