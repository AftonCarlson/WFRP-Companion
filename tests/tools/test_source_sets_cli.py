from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

from tools.source_sets import main
from wfrp_companion.db.connection import initialize_database, open_connection
from wfrp_companion.library import source_sets


def insert_folder(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        insert into library_folders (id, parent_id, name, relative_path, sort_order)
        values ('core', null, 'Core', 'Core', 0)
        on conflict(id) do nothing
        """
    )


def insert_book(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    title: str,
    category: str,
    search_status: str = "indexed",
) -> None:
    insert_folder(connection)
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
        values (?, 'core', ?, ?, ?, ?, ?, ?, ?, 1, 'copied', 'imported', ?,
                'not_scanned', '2026-06-04T00:00:00Z', '2026-06-04T00:00:00Z')
        """,
        (
            book_id,
            title,
            category,
            f"{category}/{title}.pdf",
            f"/source/{book_id}.pdf",
            f"/managed/{book_id}.pdf",
            f"sha-{book_id}",
            f"sha-{book_id}",
            search_status,
        ),
    )


def seed_books(db_path: Path) -> None:
    with initialize_database(db_path) as connection:
        insert_book(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
        )
        insert_book(
            connection,
            book_id="thousand-thrones",
            title="The Thousand Thrones",
            category="Adventure Modules and Campaigns",
            search_status="not_indexed",
        )


def enabled_value(db_path: Path, book_id: str) -> int:
    with open_connection(db_path) as connection:
        return connection.execute(
            """
            select enabled
            from source_set_books
            where source_set_id = ? and book_id = ?
            """,
            (source_sets.RULES_CORE_SOURCE_SET_ID, book_id),
        ).fetchone()[0]


def test_init_prints_summary_and_honors_data_dir_default_db(
    capsys,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "private-data"
    db_path = data_dir / "wfrp_companion.sqlite"
    seed_books(db_path)

    exit_code = main(["--data-dir", str(data_dir), "init"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "WFRP source sets" in output
    assert f"DB path: {db_path}" in output
    assert "Created source sets: 1" in output
    assert "Inserted book rows: 2" in output
    assert "Active source set: rules-core" in output


def test_list_and_books_print_source_set_rows(capsys, tmp_path: Path) -> None:
    db_path = tmp_path / "custom" / "wfrp.sqlite"
    seed_books(db_path)
    main(["--db-path", str(db_path), "init"])

    list_exit = main(["--db-path", str(db_path), "list"])
    books_exit = main(["--db-path", str(db_path), "books", "--source-set", "rules-core"])

    output = capsys.readouterr().out
    assert list_exit == 0
    assert books_exit == 0
    assert "rules-core | Rules/Core | builtin=1" in output
    assert (
        "enabled=1 | search_ready=1 | core-rules | Core Rules | "
        "Core Book & GM Essentials"
    ) in output
    assert (
        "enabled=0 | search_ready=0 | thousand-thrones | The Thousand Thrones | "
        "Adventure Modules and Campaigns"
    ) in output


def test_activate_enable_and_disable_print_confirmations(
    capsys,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "wfrp.sqlite"
    seed_books(db_path)
    main(["--db-path", str(db_path), "init"])

    activate_exit = main(["--db-path", str(db_path), "activate", "rules-core"])
    disable_exit = main(["--db-path", str(db_path), "disable", "rules-core", "core-rules"])
    enable_exit = main(["--db-path", str(db_path), "enable", "rules-core", "core-rules"])

    output = capsys.readouterr().out
    assert activate_exit == 0
    assert disable_exit == 0
    assert enable_exit == 0
    assert "Active source set: rules-core" in output
    assert "Disabled book: core-rules in rules-core" in output
    assert "Enabled book: core-rules in rules-core" in output
    assert enabled_value(db_path, "core-rules") == 1


def test_missing_source_set_and_book_errors_go_to_stderr(
    capsys,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "wfrp.sqlite"
    seed_books(db_path)
    main(["--db-path", str(db_path), "init"])

    missing_set_exit = main(["--db-path", str(db_path), "books", "--source-set", "bad"])
    missing_book_exit = main(
        ["--db-path", str(db_path), "enable", "rules-core", "missing-book"]
    )

    captured = capsys.readouterr()
    assert missing_set_exit == 1
    assert missing_book_exit == 1
    assert "Source set not found: bad" in captured.err
    assert "Book not found: missing-book" in captured.err


def test_source_set_conflict_errors_go_to_stderr(capsys, tmp_path: Path) -> None:
    db_path = tmp_path / "wfrp.sqlite"
    with initialize_database(db_path) as connection:
        connection.execute(
            """
            insert into source_sets (id, name, is_builtin, created_at, updated_at)
            values ('rules-core', 'Rules/Core', 0, '2026-06-04T00:00:00Z',
                    '2026-06-04T00:00:00Z')
            """
        )

    exit_code = main(["--db-path", str(db_path), "init"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "rules-core already exists as user-owned source set" in captured.err


def test_source_sets_script_runs_from_file_path(tmp_path: Path) -> None:
    data_dir = tmp_path / "private-data"
    db_path = data_dir / "wfrp_companion.sqlite"
    seed_books(db_path)
    script_path = Path(__file__).resolve().parents[2] / "tools" / "source_sets.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--data-dir",
            str(data_dir),
            "init",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "Active source set: rules-core" in completed.stdout
