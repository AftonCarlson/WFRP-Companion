from __future__ import annotations

import sqlite3
from pathlib import Path

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database, open_connection
from wfrp_companion.search import fts


def make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        pdf_root=tmp_path / "pdf-root",
        data_dir=data_dir,
        db_path=data_dir / "wfrp_companion.sqlite",
        asset_dir=data_dir / "library" / "assets",
    )


def insert_book(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    title: str,
    text_status: str = "imported",
    search_status: str = "not_indexed",
    copy_status: str = "copied",
) -> None:
    connection.execute(
        """
        insert into library_folders (id, parent_id, name, relative_path, sort_order)
        values ('core', null, 'Core', 'Core', 0)
        on conflict(id) do nothing
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
        values (?, 'core', ?, 'Core', ?, ?, ?, ?, ?, 2, ?, ?, ?, 'not_scanned',
                '2026-06-04T00:00:00Z', '2026-06-04T00:00:00Z')
        """,
        (
            book_id,
            title,
            f"Core/{title}.pdf",
            f"/source/{title}.pdf",
            f"/managed/{title}.pdf",
            f"sha-{book_id}",
            f"sha-{book_id}" if copy_status == "copied" else None,
            copy_status,
            text_status,
            search_status,
        ),
    )


def insert_page_text(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    page_number: int,
    text: str,
) -> None:
    page_id = f"{book_id}:{page_number}"
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
        values (?, ?, ?, 'ocr', 0, ?, ?, 1, 1, 1)
        """,
        (page_id, book_id, page_number, len(text), len(text.split())),
    )
    connection.execute(
        """
        insert into page_text (page_id, text, text_sha256, generated_at)
        values (?, ?, lower(hex(randomblob(32))), '2026-06-04T00:00:00Z')
        """,
        (page_id, text),
    )


def setup_imported_book(config: AppConfig) -> None:
    with initialize_database(config.db_path) as connection:
        insert_book(connection, book_id="core-rules", title="Core Rules")
        insert_page_text(
            connection,
            book_id="core-rules",
            page_number=1,
            text="Critical hit rules",
        )
        insert_page_text(
            connection,
            book_id="core-rules",
            page_number=2,
            text="Bögenhafen trouble",
        )


def fetch_one(config: AppConfig, query: str) -> sqlite3.Row:
    with open_connection(config.db_path) as connection:
        row = connection.execute(query).fetchone()
    assert row is not None
    return row


def count_rows(config: AppConfig, table: str) -> int:
    with open_connection(config.db_path) as connection:
        return connection.execute(f"select count(*) from {table}").fetchone()[0]


def test_rebuild_global_fts_indexes_only_copied_imported_books(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    setup_imported_book(config)
    with open_connection(config.db_path) as connection:
        insert_book(
            connection,
            book_id="unimported-book",
            title="Unimported Book",
            text_status="not_imported",
        )
        connection.commit()

    summary = fts.rebuild_global_fts(config)

    book = fetch_one(config, "select * from books where id = 'core-rules'")
    other = fetch_one(config, "select * from books where id = 'unimported-book'")
    readiness = fetch_one(
        config,
        "select search_ready from book_readiness where book_id = 'core-rules'",
    )
    assert summary.books_indexed == 1
    assert summary.pages_indexed == 2
    assert summary.failed == 0
    assert count_rows(config, "page_search") == 2
    assert book["search_status"] == "indexed"
    assert other["search_status"] == "not_indexed"
    assert readiness["search_ready"] == 1


def test_text_snapshot_sha_is_deterministic_and_changes_with_text_hash(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    setup_imported_book(config)

    with open_connection(config.db_path) as connection:
        first = fts.text_snapshot_sha256(connection)
        second = fts.text_snapshot_sha256(connection)
        connection.execute(
            """
            update page_text
            set text_sha256 = 'changed'
            where page_id = 'core-rules:1'
            """
        )
        changed = fts.text_snapshot_sha256(connection)

    assert first == second
    assert changed != first


def test_rebuild_populates_external_content_fts(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    setup_imported_book(config)

    fts.rebuild_global_fts(config)

    with open_connection(config.db_path) as connection:
        row = connection.execute(
            """
            select page_search.page_id
            from page_search_fts
            join page_search on page_search.rowid = page_search_fts.rowid
            where page_search_fts match '"critical"'
            """
        ).fetchone()
    assert row["page_id"] == "core-rules:1"


def test_rebuild_rerun_is_idempotent_for_same_snapshot(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    setup_imported_book(config)

    first = fts.rebuild_global_fts(config)
    second = fts.rebuild_global_fts(config)

    job = fetch_one(config, "select * from ingest_jobs")
    assert first.books_indexed == 1
    assert second.skipped_current == 1
    assert count_rows(config, "ingest_jobs") == 1
    assert job["attempts"] == 1


def test_rebuild_does_not_skip_when_projection_has_stale_rows(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    setup_imported_book(config)
    fts.rebuild_global_fts(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update books
            set text_status = 'not_imported'
            where id = 'core-rules'
            """
        )
        empty_snapshot = fts.text_snapshot_sha256(connection)
        job_id = fts.rebuild_job_id(empty_snapshot)
        connection.execute(
            """
            insert into ingest_jobs (
              id, job_type, target_id, status, idempotency_key, attempts,
              created_at, updated_at, completed_at
            )
            values (?, 'rebuild_fts', 'global', 'succeeded', ?, 1,
                    '2026-06-04T00:00:00Z', '2026-06-04T00:00:00Z',
                    '2026-06-04T00:00:00Z')
            """,
            (job_id, job_id),
        )
        connection.commit()

    summary = fts.rebuild_global_fts(config)

    book = fetch_one(config, "select search_status from books where id = 'core-rules'")
    assert summary.skipped_current == 0
    assert summary.pages_indexed == 0
    assert count_rows(config, "page_search") == 0
    assert book["search_status"] == "not_indexed"


def test_rebuild_does_not_skip_when_imported_book_is_not_indexed(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    setup_imported_book(config)
    with open_connection(config.db_path) as connection:
        snapshot_sha = fts.text_snapshot_sha256(connection)
        job_id = fts.rebuild_job_id(snapshot_sha)
        connection.execute(
            """
            insert into ingest_jobs (
              id, job_type, target_id, status, idempotency_key, attempts,
              created_at, updated_at, completed_at
            )
            values (?, 'rebuild_fts', 'global', 'succeeded', ?, 1,
                    '2026-06-04T00:00:00Z', '2026-06-04T00:00:00Z',
                    '2026-06-04T00:00:00Z')
            """,
            (job_id, job_id),
        )
        connection.commit()

    summary = fts.rebuild_global_fts(config)

    assert summary.skipped_current == 0
    assert summary.books_indexed == 1


def test_rebuild_does_not_skip_when_projection_row_count_drifts(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    setup_imported_book(config)
    fts.rebuild_global_fts(config)
    with open_connection(config.db_path) as connection:
        connection.execute("delete from page_search where page_id = 'core-rules:2'")
        connection.commit()

    summary = fts.rebuild_global_fts(config)

    assert summary.skipped_current == 0
    assert summary.pages_indexed == 2
    assert count_rows(config, "page_search") == 2


def test_rebuild_does_not_skip_when_integrity_check_fails_once(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    setup_imported_book(config)
    fts.rebuild_global_fts(config)
    original_integrity_check = fts.run_fts_integrity_check
    calls = 0

    def flaky_integrity_check(connection: sqlite3.Connection) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise sqlite3.DatabaseError("temporary drift")
        original_integrity_check(connection)

    monkeypatch.setattr(fts, "run_fts_integrity_check", flaky_integrity_check)

    summary = fts.rebuild_global_fts(config)

    assert summary.skipped_current == 0
    assert summary.books_indexed == 1
    assert calls == 2


def test_force_rebuild_replaces_existing_projection(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    setup_imported_book(config)
    fts.rebuild_global_fts(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            "delete from page_text where page_id = 'core-rules:2'"
        )
        connection.commit()

    summary = fts.rebuild_global_fts(config, force=True)

    assert summary.books_indexed == 1
    assert summary.pages_indexed == 1
    assert count_rows(config, "page_search") == 1


def test_rebuild_failure_marks_job_and_imported_books_failed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    setup_imported_book(config)

    def fail_integrity_check(connection: sqlite3.Connection) -> None:
        raise RuntimeError("integrity broke")

    monkeypatch.setattr(fts, "run_fts_integrity_check", fail_integrity_check)

    summary = fts.rebuild_global_fts(config)

    book = fetch_one(config, "select search_status from books where id = 'core-rules'")
    job = fetch_one(config, "select * from ingest_jobs")
    assert summary.failed == 1
    assert summary.failure_reason == "RuntimeError: integrity broke"
    assert book["search_status"] == "failed"
    assert job["status"] == "failed"
    assert "integrity broke" in job["last_error"]


def test_rebuild_failure_on_fts_row_count_drift(monkeypatch, tmp_path: Path) -> None:
    config = make_config(tmp_path)
    setup_imported_book(config)
    monkeypatch.setattr(fts, "fts_row_count", lambda _connection: -1)

    summary = fts.rebuild_global_fts(config)

    book = fetch_one(config, "select search_status from books where id = 'core-rules'")
    assert summary.failed == 1
    assert "page_search and page_search_fts row counts drifted" in (
        summary.failure_reason or ""
    )
    assert book["search_status"] == "failed"


def test_rebuild_recovers_stale_running_job(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    setup_imported_book(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update books
            set search_status = 'indexing'
            where id = 'core-rules'
            """
        )
        connection.execute(
            """
            insert into ingest_jobs (
              id, job_type, target_id, status, idempotency_key, attempts,
              created_at, updated_at
            )
            values (
              'rebuild_fts:global:old', 'rebuild_fts', 'global', 'running',
              'rebuild_fts:global:old', 1,
              '2026-06-04T00:00:00Z', '2026-06-04T00:00:00Z'
            )
            """
        )
        connection.commit()

    summary = fts.rebuild_global_fts(config, stale_running_minutes=0)

    book = fetch_one(config, "select search_status from books where id = 'core-rules'")
    assert summary.stale_recovered == 1
    assert summary.books_indexed == 1
    assert book["search_status"] == "indexed"


def test_rebuild_retry_running_recovers_fresh_running_job(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    setup_imported_book(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update books
            set search_status = 'indexing'
            where id = 'core-rules'
            """
        )
        connection.execute(
            """
            insert into ingest_jobs (
              id, job_type, target_id, status, idempotency_key, attempts,
              created_at, updated_at
            )
            values (
              'rebuild_fts:global:fresh', 'rebuild_fts', 'global', 'running',
              'rebuild_fts:global:fresh', 1,
              '2099-01-01T00:00:00Z', '2099-01-01T00:00:00Z'
            )
            """
        )
        connection.commit()

    summary = fts.rebuild_global_fts(config, retry_running=True)

    assert summary.stale_recovered == 1
    assert summary.books_indexed == 1


def test_rebuild_does_not_steal_same_key_fresh_running_job(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    setup_imported_book(config)
    with open_connection(config.db_path) as connection:
        snapshot_sha = fts.text_snapshot_sha256(connection)
        job_id = fts.rebuild_job_id(snapshot_sha)
        connection.execute(
            """
            insert into ingest_jobs (
              id, job_type, target_id, status, idempotency_key, attempts,
              created_at, updated_at
            )
            values (?, 'rebuild_fts', 'global', 'running', ?, 1,
                    '2099-01-01T00:00:00Z', '2099-01-01T00:00:00Z')
            """,
            (job_id, job_id),
        )
        connection.commit()

    summary = fts.rebuild_global_fts(config)

    job = fetch_one(config, "select * from ingest_jobs where job_type = 'rebuild_fts'")
    assert summary.books_indexed == 0
    assert summary.failed == 0
    assert job["status"] == "running"
    assert job["attempts"] == 1
    assert count_rows(config, "page_search") == 0


def test_build_fts_query_tokenizes_terms_and_unicode() -> None:
    assert fts.build_fts_query("critical hit") == '"critical" AND "hit"'
    assert fts.build_fts_query("Ulric's Fury!") == '"Ulric" AND "s" AND "Fury"'
    assert fts.build_fts_query("Bögenhafen") == '"Bögenhafen"'


def test_build_fts_query_returns_none_without_tokens() -> None:
    assert fts.build_fts_query("!? ") is None


def test_search_exact_returns_structured_hits(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    setup_imported_book(config)
    fts.rebuild_global_fts(config)

    hits = fts.search_exact(config, "critical hit")

    assert len(hits) == 1
    assert hits[0].rank == 1
    assert hits[0].book_id == "core-rules"
    assert hits[0].title == "Core Rules"
    assert hits[0].category == "Core"
    assert hits[0].page_id == "core-rules:1"
    assert hits[0].page_number == 1
    assert "[Critical]" in hits[0].snippet
    assert isinstance(hits[0].score, float)


def test_search_exact_none_book_ids_searches_whole_index(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    setup_imported_book(config)
    fts.rebuild_global_fts(config)

    hits = fts.search_exact(config, "Bögenhafen", book_ids=None)

    assert len(hits) == 1
    assert hits[0].page_id == "core-rules:2"


def test_search_exact_empty_book_ids_returns_no_hits(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    setup_imported_book(config)
    fts.rebuild_global_fts(config)

    assert fts.search_exact(config, "critical", book_ids=()) == ()


def test_search_exact_requires_indexed_book_state(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    setup_imported_book(config)
    fts.rebuild_global_fts(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update books
            set search_status = 'not_indexed'
            where id = 'core-rules'
            """
        )
        connection.commit()

    assert fts.search_exact(config, "critical") == ()


def test_search_exact_filters_non_empty_book_ids(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    setup_imported_book(config)
    fts.rebuild_global_fts(config)

    included = fts.search_exact(config, "critical", book_ids=("core-rules",))
    excluded = fts.search_exact(config, "critical", book_ids=("other-book",))

    assert len(included) == 1
    assert excluded == ()


def test_search_exact_clamps_limit_to_100(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_book(connection, book_id="core-rules", title="Core Rules")
        for page_number in range(1, 121):
            insert_page_text(
                connection,
                book_id="core-rules",
                page_number=page_number,
                text=f"critical match {page_number}",
            )

    fts.rebuild_global_fts(config)

    hits = fts.search_exact(config, "critical", limit=500)

    assert len(hits) == 100


def test_search_exact_returns_no_hits_for_empty_query(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    setup_imported_book(config)
    fts.rebuild_global_fts(config)

    assert fts.search_exact(config, "!?") == ()
