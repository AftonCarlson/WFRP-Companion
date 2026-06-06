from __future__ import annotations

import runpy
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from tools.init_db import main as init_db_main
from wfrp_companion.config import DEFAULT_PDF_ROOT, load_config
from wfrp_companion.db.connection import initialize_database, open_connection


REQUIRED_TABLES = {
    "app_settings",
    "library_folders",
    "books",
    "pages",
    "page_text",
    "page_search",
    "page_search_fts",
    "source_sets",
    "source_set_books",
    "page_assets",
    "asset_labels",
    "ingest_jobs",
    "schema_migrations",
    "source_objects",
    "source_object_links",
    "book_object_status",
    "book_retrieval_status",
    "book_source_maps",
    "book_query_profiles",
    "source_object_search",
    "source_object_search_fts",
    "source_object_embeddings",
    "chat_threads",
    "chat_thread_source_books",
    "chat_messages",
    "retrieval_runs",
    "retrieval_run_source_books",
    "retrieval_hits",
    "model_runs",
}


def table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "select name from sqlite_master where type in ('table', 'view')"
    ).fetchall()
    return {row["name"] for row in rows}


def insert_folder(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        insert into library_folders (id, parent_id, name, relative_path, sort_order)
        values ('core', null, 'Core Book & GM Essentials', 'Core Book & GM Essentials', 0)
        """
    )


def insert_book(
    connection: sqlite3.Connection,
    *,
    book_id: str = "core-rules",
    copy_status: str = "copied",
    managed_sha256: str | None = "managed-sha",
) -> None:
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
        values (?, 'core', 'Core Rules', 'Core Book & GM Essentials', ?, ?, ?, ?, ?, 1, ?, 'not_imported', 'not_indexed', 'not_scanned', '2026-06-03T00:00:00Z', '2026-06-03T00:00:00Z')
        """,
        (
            book_id,
            f"Core Book & GM Essentials/{book_id}.pdf",
            f"/source/{book_id}.pdf",
            f"data/library/pdfs/{book_id}/source.pdf",
            f"original-{book_id}",
            managed_sha256,
            copy_status,
        ),
    )


def insert_page(connection: sqlite3.Connection) -> None:
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
        values ('core-rules:1', 'core-rules', 1, 'ocr-empty', 0, 0, 0, 1, 1, 0)
        """
    )


def insert_asset(
    connection: sqlite3.Connection,
    *,
    asset_id: str = "core-rules:1:visual_candidate:phash:abc",
    book_id: str = "core-rules",
    page_number: int = 1,
) -> None:
    connection.execute(
        """
        insert into page_assets (
          id,
          page_id,
          book_id,
          page_number,
          kind,
          perceptual_hash,
          confidence,
          review_status
        )
        values (?, 'core-rules:1', ?, ?, 'visual_candidate', 'abc', 0.8, 'auto_labeled')
        """,
        (asset_id, book_id, page_number),
    )


def test_load_config_uses_local_defaults(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"

    config = load_config(environ={}, repo_root=repo_root)

    assert config.pdf_root == DEFAULT_PDF_ROOT
    assert config.data_dir == repo_root / "data"
    assert config.db_path == repo_root / "data" / "wfrp_companion.sqlite"
    assert config.asset_dir == repo_root / "data" / "library" / "assets"
    assert config.openai_api_key is None
    assert config.openai_model == "gpt-5.4-mini"
    assert config.openai_timeout_seconds == 60
    assert config.chat_context_hit_limit == 6
    assert config.embedding_provider == "disabled"
    assert config.embedding_model == "local-hash-v1"
    assert config.embedding_dimensions == 64


def test_load_config_honors_environment_overrides(tmp_path: Path) -> None:
    config = load_config(
        environ={
            "WFRP_PDF_ROOT": str(tmp_path / "pdfs"),
            "WFRP_DATA_DIR": str(tmp_path / "private-data"),
            "WFRP_DB_PATH": str(tmp_path / "db" / "custom.sqlite"),
            "WFRP_ASSET_DIR": str(tmp_path / "assets"),
            "OPENAI_API_KEY": "test-key",
            "WFRP_OPENAI_MODEL": "gpt-test",
            "WFRP_OPENAI_TIMEOUT_SECONDS": "12.5",
            "WFRP_CHAT_CONTEXT_HIT_LIMIT": "3",
            "WFRP_CHAT_CONTEXT_CHAR_LIMIT": "1200",
            "WFRP_CHAT_CONTEXT_WINDOW_CHARS": "400",
            "WFRP_EMBEDDING_PROVIDER": "local-hash",
            "WFRP_EMBEDDING_MODEL": "local-hash-test",
            "WFRP_EMBEDDING_DIMENSIONS": "16",
        },
        repo_root=tmp_path / "repo",
    )

    assert config.pdf_root == tmp_path / "pdfs"
    assert config.data_dir == tmp_path / "private-data"
    assert config.db_path == tmp_path / "db" / "custom.sqlite"
    assert config.asset_dir == tmp_path / "assets"
    assert config.openai_api_key == "test-key"
    assert config.openai_model == "gpt-test"
    assert config.openai_timeout_seconds == 12.5
    assert config.chat_context_hit_limit == 3
    assert config.chat_context_char_limit == 1200
    assert config.chat_context_window_chars == 400
    assert config.embedding_provider == "local-hash"
    assert config.embedding_model == "local-hash-test"
    assert config.embedding_dimensions == 16


def test_initialize_database_creates_required_schema_and_wal(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "nested" / "wfrp.sqlite"

    initialize_database(db_path)

    assert db_path.exists()
    with open_connection(db_path) as connection:
        assert REQUIRED_TABLES <= table_names(connection)
        assert connection.execute("pragma foreign_keys").fetchone()[0] == 1
        assert connection.execute("pragma journal_mode").fetchone()[0] == "wal"


def test_initialize_database_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "wfrp.sqlite"

    initialize_database(db_path)
    initialize_database(db_path)

    with open_connection(db_path) as connection:
        assert "books" in table_names(connection)


def test_book_status_constraints_protect_lifecycle_state(tmp_path: Path) -> None:
    with initialize_database(tmp_path / "wfrp.sqlite") as connection:
        insert_folder(connection)
        insert_book(
            connection,
            book_id="discovered-book",
            copy_status="discovered",
            managed_sha256=None,
        )

        with pytest.raises(sqlite3.IntegrityError):
            insert_book(
                connection,
                book_id="bad-status",
                copy_status="banana",
                managed_sha256=None,
            )

        with pytest.raises(sqlite3.IntegrityError):
            insert_book(
                connection,
                book_id="copied-without-sha",
                copy_status="copied",
                managed_sha256=None,
            )


def test_asset_constraints_prevent_duplicate_candidates_and_current_labels(
    tmp_path: Path,
) -> None:
    with initialize_database(tmp_path / "wfrp.sqlite") as connection:
        insert_folder(connection)
        insert_book(connection)
        insert_page(connection)
        insert_asset(connection)

        with pytest.raises(sqlite3.IntegrityError):
            insert_asset(
                connection,
                asset_id="duplicate-id-is-not-the-point",
            )

        connection.execute(
            """
            insert into asset_labels (
              id,
              asset_id,
              label,
              source,
              confidence,
              is_current,
              created_at
            )
            values ('label-1', 'core-rules:1:visual_candidate:phash:abc', 'map_candidate', 'heuristic', 0.8, 1, '2026-06-03T00:00:00Z')
            """
        )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                insert into asset_labels (
                  id,
                  asset_id,
                  label,
                  source,
                  confidence,
                  is_current,
                  created_at
                )
                values ('label-2', 'core-rules:1:visual_candidate:phash:abc', 'unknown', 'heuristic', 0.2, 1, '2026-06-03T00:00:00Z')
                """
            )


def test_boolean_constraints_reject_ambiguous_state_values(tmp_path: Path) -> None:
    with initialize_database(tmp_path / "wfrp.sqlite") as connection:
        insert_folder(connection)

        with pytest.raises(sqlite3.IntegrityError):
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
                  enabled_default,
                  discovered_at,
                  updated_at
                )
                values ('bad-bool-book', 'core', 'Bad Bool', 'Core Book & GM Essentials', 'bad.pdf', '/source/bad.pdf', 'data/library/pdfs/bad/source.pdf', 'source-sha', 'managed-sha', 1, 'copied', 'not_imported', 'not_indexed', 'not_scanned', 2, '2026-06-03T00:00:00Z', '2026-06-03T00:00:00Z')
                """
            )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                insert into source_sets (id, name, is_builtin, created_at, updated_at)
                values ('bad-source-set', 'Bad Source Set', 2, '2026-06-03T00:00:00Z', '2026-06-03T00:00:00Z')
                """
            )

        insert_book(connection)
        connection.execute(
            """
            insert into source_sets (id, name, is_builtin, created_at, updated_at)
            values ('rules-core', 'Rules/Core', 1, '2026-06-03T00:00:00Z', '2026-06-03T00:00:00Z')
            """
        )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                insert into source_set_books (source_set_id, book_id, enabled, updated_at)
                values ('rules-core', 'core-rules', 2, '2026-06-03T00:00:00Z')
                """
            )

        insert_page(connection)
        insert_asset(connection)

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                insert into asset_labels (
                  id,
                  asset_id,
                  label,
                  source,
                  confidence,
                  is_current,
                  created_at
                )
                values ('bad-current-label', 'core-rules:1:visual_candidate:phash:abc', 'map_candidate', 'heuristic', 0.8, 2, '2026-06-03T00:00:00Z')
                """
            )


def test_chat_model_run_constraints_and_retry_guard(tmp_path: Path) -> None:
    with initialize_database(tmp_path / "wfrp.sqlite") as connection:
        insert_folder(connection)
        insert_book(connection)
        connection.execute(
            """
            insert into source_sets (id, name, is_builtin, created_at, updated_at)
            values ('rules-core', 'Rules/Core', 1, '2026-06-03T00:00:00Z',
                    '2026-06-03T00:00:00Z')
            """
        )
        connection.execute(
            """
            insert into chat_threads (
              id,
              title,
              active_source_set_id,
              created_at,
              updated_at
            )
            values ('thread-1', 'Rules Help', 'rules-core',
                    '2026-06-03T00:00:00Z', '2026-06-03T00:00:00Z')
            """
        )
        connection.execute(
            """
            insert into chat_thread_source_books (
              thread_id,
              book_id,
              source_set_id,
              captured_at
            )
            values ('thread-1', 'core-rules', 'rules-core',
                    '2026-06-03T00:00:00Z')
            """
        )
        connection.execute(
            """
            insert into chat_messages (
              id,
              thread_id,
              role,
              content,
              created_at
            )
            values ('message-1', 'thread-1', 'user', 'Help',
                    '2026-06-03T00:00:00Z')
            """
        )
        connection.execute(
            """
            insert into model_runs (
              id,
              thread_id,
              user_message_id,
              provider,
              model,
              status,
              idempotency_key,
              created_at,
              updated_at
            )
            values ('run-1', 'thread-1', 'message-1', 'fake', 'fake-model',
                    'failed', 'send-1', '2026-06-03T00:00:00Z',
                    '2026-06-03T00:00:00Z')
            """
        )
        connection.execute(
            """
            insert into model_runs (
              id,
              thread_id,
              retry_of_model_run_id,
              provider,
              model,
              status,
              idempotency_key,
              created_at,
              updated_at
            )
            values ('retry-1', 'thread-1', 'run-1', 'fake', 'fake-model',
                    'queued', 'retry-1', '2026-06-03T00:00:00Z',
                    '2026-06-03T00:00:00Z')
            """
        )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                insert into model_runs (
                  id,
                  thread_id,
                  provider,
                  model,
                  status,
                  idempotency_key,
                  created_at,
                  updated_at
                )
                values ('bad-provider', 'thread-1', 'banana', 'fake-model',
                        'queued', 'bad-provider', '2026-06-03T00:00:00Z',
                        '2026-06-03T00:00:00Z')
                """
            )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                insert into model_runs (
                  id,
                  thread_id,
                  provider,
                  model,
                  status,
                  idempotency_key,
                  created_at,
                  updated_at
                )
                values ('bad-status', 'thread-1', 'fake', 'fake-model',
                        'thinking', 'bad-status', '2026-06-03T00:00:00Z',
                        '2026-06-03T00:00:00Z')
                """
            )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                insert into model_runs (
                  id,
                  thread_id,
                  user_message_id,
                  retry_of_model_run_id,
                  provider,
                  model,
                  status,
                  idempotency_key,
                  created_at,
                  updated_at
                )
                values ('retry-2', 'thread-1', 'message-1', 'run-1', 'fake',
                        'fake-model', 'retrieving', 'retry-2',
                        '2026-06-03T00:00:00Z', '2026-06-03T00:00:00Z')
                """
            )

        connection.execute(
            """
            insert into model_runs (
              id,
              thread_id,
              user_message_id,
              retry_of_model_run_id,
              provider,
              model,
              status,
              idempotency_key,
              created_at,
              updated_at
            )
            values ('retry-3', 'thread-1', 'message-1', 'run-1', 'fake',
                    'fake-model', 'completed', 'retry-3', '2026-06-03T00:00:00Z',
                    '2026-06-03T00:00:00Z')
            """
        )

        connection.execute(
            """
            insert into model_runs (
              id,
              thread_id,
              user_message_id,
              provider,
              model,
              status,
              idempotency_key,
              created_at,
              updated_at
            )
            values ('local-gate', 'thread-1', 'message-1', 'local',
                    'retrieval-confidence-gate', 'completed', 'local-gate',
                    '2026-06-03T00:00:00Z', '2026-06-03T00:00:00Z')
            """
        )


def test_source_object_schema_constraints_and_retrieval_hit_snapshots(
    tmp_path: Path,
) -> None:
    with initialize_database(tmp_path / "wfrp.sqlite") as connection:
        insert_folder(connection)
        insert_book(connection)
        insert_page(connection)
        connection.execute(
            """
            insert into source_objects (
              id,
              book_id,
              page_id,
              object_type,
              title,
              heading_path_json,
              page_start,
              page_end,
              char_start,
              char_end,
              text,
              search_text,
              confidence,
              extraction_method,
              text_snapshot_sha256,
              created_at,
              updated_at
            )
            values (
              'core-rules:p1-p1:rule_section:1:aaaaaaaaaaaa',
              'core-rules',
              'core-rules:1',
              'rule_section',
              'Critical Hits',
              '["Combat"]',
              1,
              1,
              10,
              80,
              'Critical hits are dangerous.',
              'Critical Hits Combat',
              0.91,
              'heading_heuristic',
              'text-snapshot',
              '2026-06-03T00:00:00Z',
              '2026-06-03T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            insert into source_objects (
              id,
              book_id,
              page_id,
              object_type,
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
              'core-rules:p1-p1:table:2:bbbbbbbbbbbb',
              'core-rules',
              'core-rules:1',
              'table',
              'Critical Hit Table',
              '["Combat"]',
              1,
              1,
              'Roll Result',
              'Critical Hit Table Roll Result',
              0.82,
              'pymupdf_table',
              'text-snapshot',
              '2026-06-03T00:00:00Z',
              '2026-06-03T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            insert into retrieval_runs (id, query, created_at)
            values ('retrieval-1', 'critical hit rules', '2026-06-03T00:00:00Z')
            """
        )
        connection.execute(
            """
            insert into retrieval_hits (
              id,
              retrieval_run_id,
              page_id,
              source_object_id,
              score,
              rank,
              snippet,
              object_type_snapshot,
              title_snapshot,
              heading_path_snapshot_json,
              confidence_snapshot,
              rank_reasons_json,
              text_snapshot_sha256
            )
            values (
              'hit-1',
              'retrieval-1',
              'core-rules:1',
              'core-rules:p1-p1:rule_section:1:aaaaaaaaaaaa',
              0.1,
              1,
              'Critical hits',
              'rule_section',
              'Critical Hits',
              '["Combat"]',
              0.91,
              '["object_type_match"]',
              'text-snapshot'
            )
            """
        )
        connection.execute(
            """
            insert into retrieval_hits (
              id,
              retrieval_run_id,
              page_id,
              source_object_id,
              score,
              rank,
              snippet,
              object_type_snapshot,
              title_snapshot,
              heading_path_snapshot_json,
              confidence_snapshot,
              rank_reasons_json,
              text_snapshot_sha256
            )
            values (
              'hit-2',
              'retrieval-1',
              'core-rules:1',
              'core-rules:p1-p1:table:2:bbbbbbbbbbbb',
              0.2,
              2,
              'Critical Hit Table',
              'table',
              'Critical Hit Table',
              '["Combat"]',
              0.82,
              '["table_lookup"]',
              'text-snapshot'
            )
            """
        )
        connection.execute(
            """
            insert into retrieval_hits (
              id,
              retrieval_run_id,
              page_id,
              score,
              rank,
              snippet,
              object_type_snapshot
            )
            values (
              'fallback-hit',
              'retrieval-1',
              'core-rules:1',
              0.5,
              3,
              'page fallback',
              'page_fallback'
            )
            """
        )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                insert into source_objects (
                  id,
                  book_id,
                  page_id,
                  object_type,
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
                  'bad-type',
                  'core-rules',
                  'core-rules:1',
                  'rumor',
                  '[]',
                  1,
                  1,
                  'bad',
                  'bad',
                  0.5,
                  'test',
                  'text-snapshot',
                  '2026-06-03T00:00:00Z',
                  '2026-06-03T00:00:00Z'
                )
                """
            )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                insert into retrieval_hits (
                  id,
                  retrieval_run_id,
                  page_id,
                  score,
                  rank,
                  object_type_snapshot
                )
                values ('duplicate-rank', 'retrieval-1', 'core-rules:1', 0.6, 3,
                        'page_fallback')
                """
            )


def test_page_assets_must_match_referenced_page_identity(tmp_path: Path) -> None:
    with initialize_database(tmp_path / "wfrp.sqlite") as connection:
        insert_folder(connection)
        insert_book(connection)
        insert_page(connection)

        with pytest.raises(sqlite3.IntegrityError):
            insert_asset(
                connection,
                asset_id="wrong-book",
                book_id="different-book",
            )

        with pytest.raises(sqlite3.IntegrityError):
            insert_asset(
                connection,
                asset_id="wrong-page",
                page_number=2,
            )


def test_init_db_cli_creates_requested_database(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "cli.sqlite"

    exit_code = init_db_main(["--db-path", str(db_path)])

    assert exit_code == 0
    assert db_path.exists()
    assert str(db_path) in capsys.readouterr().out


def test_init_db_script_path_entrypoint_creates_requested_database(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "script.sqlite"
    completed = subprocess.run(
        [
            sys.executable,
            "tools/init_db.py",
            "--db-path",
            str(db_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert db_path.exists()
    assert str(db_path) in completed.stdout


def test_init_db_script_main_path_is_covered_in_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "runpy.sqlite"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tools/init_db.py",
            "--db-path",
            str(db_path),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path("tools/init_db.py", run_name="__main__")

    assert exit_info.value.code == 0
    assert db_path.exists()
    assert str(db_path) in capsys.readouterr().out
