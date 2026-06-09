from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools.search_text import main
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database, open_connection
from wfrp_companion.library import source_sets
from wfrp_companion.search.fts import rebuild_global_fts


def insert_indexed_books(db_path: Path, data_dir: Path) -> None:
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
              'core-rules', 'core', 'Core Rules', 'Core Book & GM Essentials',
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
              'adventure-book', 'core', 'Adventure Book', 'Adventure Modules and Campaigns',
              'Adventure/Adventure Book.pdf', '/source/Adventure Book.pdf',
              '/managed/Adventure Book.pdf', 'adventure-source-sha', 'adventure-source-sha', 1,
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
            values ('adventure-book:1', 'adventure-book', 1, 'ocr', 0, 23, 4, 1, 1, 1)
            """
        )
        connection.execute(
            """
            insert into page_text (page_id, text, text_sha256, generated_at)
            values (
              'adventure-book:1',
              'Critical hit adventure',
              'adventure-text-sha',
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


def init_source_sets(db_path: Path, data_dir: Path) -> None:
    source_sets.ensure_builtin_source_sets(
        AppConfig(
            pdf_root=data_dir / "pdfs",
            data_dir=data_dir,
            db_path=db_path,
            asset_dir=data_dir / "library" / "assets",
        )
    )


def test_main_defaults_to_active_source_set(capsys, tmp_path: Path) -> None:
    data_dir = tmp_path / "private-data"
    db_path = data_dir / "wfrp_companion.sqlite"
    insert_indexed_books(db_path, data_dir)
    init_source_sets(db_path, data_dir)

    exit_code = main(["--data-dir", str(data_dir), "critical", "hit"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "WFRP exact text search" in output
    assert "Query: critical hit" in output
    assert "Hits: 1" in output
    assert "1. Core Rules p. 1 [core-rules:1]" in output
    assert "Adventure Book" not in output
    assert "[Critical]" in output


def test_main_active_source_set_still_uses_search_readiness_gate(
    capsys,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "private-data"
    db_path = data_dir / "wfrp_companion.sqlite"
    insert_indexed_books(db_path, data_dir)
    init_source_sets(db_path, data_dir)
    source_sets.set_book_enabled(
        AppConfig(
            pdf_root=data_dir / "pdfs",
            data_dir=data_dir,
            db_path=db_path,
            asset_dir=data_dir / "library" / "assets",
        ),
        source_sets.RULES_CORE_SOURCE_SET_ID,
        "adventure-book",
        True,
    )
    with open_connection(db_path) as connection:
        connection.execute(
            """
            update books
            set search_status = 'not_indexed'
            where id = 'adventure-book'
            """
        )
        connection.commit()

    exit_code = main(["--data-dir", str(data_dir), "critical"])

    output = capsys.readouterr().out
    assert source_sets.enabled_book_ids(
        AppConfig(
            pdf_root=data_dir / "pdfs",
            data_dir=data_dir,
            db_path=db_path,
            asset_dir=data_dir / "library" / "assets",
        )
    ) == ("adventure-book", "core-rules")
    assert exit_code == 0
    assert "Hits: 1" in output
    assert "Core Rules p. 1 [core-rules:1]" in output
    assert "Adventure Book" not in output


def test_main_honors_explicit_db_path(capsys, tmp_path: Path) -> None:
    data_dir = tmp_path / "private-data"
    db_path = tmp_path / "custom" / "library.sqlite"
    insert_indexed_books(db_path, data_dir)
    init_source_sets(db_path, data_dir)

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


def test_main_all_books_preserves_whole_library_search(capsys, tmp_path: Path) -> None:
    data_dir = tmp_path / "private-data"
    db_path = data_dir / "wfrp_companion.sqlite"
    insert_indexed_books(db_path, data_dir)
    init_source_sets(db_path, data_dir)

    exit_code = main(["--data-dir", str(data_dir), "--all-books", "critical"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Hits: 2" in output
    assert "Adventure Book p. 1 [adventure-book:1]" in output
    assert "Core Rules p. 1 [core-rules:1]" in output


def test_main_source_set_and_book_id_filters(capsys, tmp_path: Path) -> None:
    data_dir = tmp_path / "private-data"
    db_path = data_dir / "wfrp_companion.sqlite"
    insert_indexed_books(db_path, data_dir)
    init_source_sets(db_path, data_dir)

    source_set_exit = main(
        [
            "--data-dir",
            str(data_dir),
            "--source-set",
            "rules-core",
            "critical",
        ]
    )
    source_set_output = capsys.readouterr().out
    book_id_exit = main(
        [
            "--data-dir",
            str(data_dir),
            "--book-id",
            "adventure-book",
            "critical",
        ]
    )
    book_output = capsys.readouterr().out

    assert source_set_exit == 0
    assert "Hits: 1" in source_set_output
    assert "Core Rules p. 1 [core-rules:1]" in source_set_output
    assert "Adventure Book" not in source_set_output
    assert book_id_exit == 0
    assert "Hits: 1" in book_output
    assert "Adventure Book p. 1 [adventure-book:1]" in book_output
    assert "Core Rules" not in book_output


def test_main_prints_zero_hits(capsys, tmp_path: Path) -> None:
    data_dir = tmp_path / "private-data"
    db_path = data_dir / "wfrp_companion.sqlite"
    insert_indexed_books(db_path, data_dir)
    init_source_sets(db_path, data_dir)

    exit_code = main(["--data-dir", str(data_dir), "wyrdstone"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Hits: 0" in output


def test_main_missing_or_malformed_active_source_set_returns_nonzero(
    capsys,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "private-data"
    db_path = data_dir / "wfrp_companion.sqlite"
    insert_indexed_books(db_path, data_dir)
    missing_exit = main(["--data-dir", str(data_dir), "critical"])

    with open_connection(db_path) as connection:
        connection.execute(
            """
            insert into app_settings (key, value_json, updated_at)
            values (?, '{not-json', '2026-06-04T00:00:00Z')
            """,
            (source_sets.ACTIVE_SOURCE_SET_SETTING_KEY,),
        )
        connection.commit()
    malformed_exit = main(["--data-dir", str(data_dir), "critical"])

    captured = capsys.readouterr()
    assert missing_exit == 1
    assert malformed_exit == 1
    assert "Run tools/source_sets.py init or use --all-books" in captured.err


def test_main_empty_active_source_set_returns_zero_hits(capsys, tmp_path: Path) -> None:
    data_dir = tmp_path / "private-data"
    db_path = data_dir / "wfrp_companion.sqlite"
    insert_indexed_books(db_path, data_dir)
    init_source_sets(db_path, data_dir)
    with open_connection(db_path) as connection:
        connection.execute(
            """
            update source_set_books
            set enabled = 0
            where source_set_id = ?
            """,
            (source_sets.RULES_CORE_SOURCE_SET_ID,),
        )
        connection.commit()

    exit_code = main(["--data-dir", str(data_dir), "critical"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Hits: 0" in output


def test_main_rejects_conflicting_search_scope_flags(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as all_books_source_set:
        main(["--all-books", "--source-set", "rules-core", "critical"])

    with pytest.raises(SystemExit) as all_books_book_id:
        main(["--all-books", "--book-id", "core-rules", "critical"])

    with pytest.raises(SystemExit) as source_set_book_id:
        main(["--source-set", "rules-core", "--book-id", "core-rules", "critical"])

    assert all_books_source_set.value.code == 2
    assert all_books_book_id.value.code == 2
    assert source_set_book_id.value.code == 2


def test_search_text_script_runs_from_file_path(tmp_path: Path) -> None:
    data_dir = tmp_path / "private-data"
    db_path = data_dir / "wfrp_companion.sqlite"
    insert_indexed_books(db_path, data_dir)
    init_source_sets(db_path, data_dir)
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
