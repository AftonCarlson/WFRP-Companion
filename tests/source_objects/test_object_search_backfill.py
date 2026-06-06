from __future__ import annotations

from pathlib import Path

import pytest

from tests.source_objects.test_store import (
    count_rows,
    fetch_one,
    insert_indexed_book,
    make_config,
)
from wfrp_companion.db.connection import open_connection
from wfrp_companion.source_objects import store
from wfrp_companion.source_objects.extractor import extract_source_object_library
from wfrp_companion.source_objects.store import (
    common_text_snapshot,
    heading_path_text,
    rebuild_source_object_search,
    source_object_search_book_ids,
    source_object_search_claim_failure,
    source_object_search_current,
    source_object_search_job_id,
    source_object_search_snapshot_sha256,
)


def test_rebuild_source_object_search_repairs_missing_projection_and_job(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        snapshot = source_object_search_snapshot_sha256(connection, "rules")
        connection.execute("delete from source_object_search where book_id = 'rules'")
        connection.execute(
            "insert into source_object_search_fts(source_object_search_fts) values('rebuild')"
        )

    summary = rebuild_source_object_search(config)

    assert summary.discovered == 1
    assert summary.indexed == 1
    assert summary.objects_written == 2
    assert summary.skipped_current == 0
    assert summary.failed == 0
    assert count_rows(config, "source_object_search") == 2
    assert count_rows(config, "source_object_search_fts") == 2
    status = fetch_one(config, "select * from book_object_status")
    job = fetch_one(
        config,
        "select * from ingest_jobs where job_type = 'rebuild_source_object_fts'",
    )
    assert status["status"] == "indexed"
    assert status["object_count"] == 2
    assert status["last_error"] is None
    assert job["status"] == "succeeded"
    assert job["idempotency_key"] == source_object_search_job_id("rules", snapshot)
    with open_connection(config.db_path) as connection:
        assert source_object_search_current(connection, "rules") is True
        row = connection.execute(
            """
            select source_object_search.source_object_id
            from source_object_search_fts
            join source_object_search
              on source_object_search.rowid = source_object_search_fts.rowid
            where source_object_search_fts match '"critical"'
            """
        ).fetchone()
    assert row["source_object_id"].startswith("rules:")

    second = rebuild_source_object_search(config)

    assert second.indexed == 0
    assert second.skipped_current == 1


def test_rebuild_source_object_search_supports_filters_and_stale_projection(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config, book_id="rules")
    insert_indexed_book(config, book_id="lore")
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update source_object_search
            set title = 'Stale Projection',
                search_text = 'stale projection'
            where book_id = 'rules'
            """
        )
        connection.execute("delete from source_object_search where book_id = 'lore'")
        connection.execute(
            "insert into source_object_search_fts(source_object_search_fts) values('rebuild')"
        )

    summary = rebuild_source_object_search(config, book_ids=("lore",))

    assert summary.discovered == 1
    assert summary.indexed == 1
    with open_connection(config.db_path) as connection:
        assert source_object_search_current(connection, "lore") is True
        assert source_object_search_current(connection, "rules") is False
        stale_title = connection.execute(
            """
            select title
            from source_object_search
            where book_id = 'rules'
            order by rowid
            limit 1
            """
        ).fetchone()["title"]
    assert stale_title == "Stale Projection"


def test_rebuild_source_object_search_repairs_stale_fts_same_row_count(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update source_object_search
            set search_text = 'stale only'
            where book_id = 'rules'
            """
        )
        connection.execute(
            "insert into source_object_search_fts(source_object_search_fts) values('rebuild')"
        )
        connection.execute(
            """
            update source_object_search
            set search_text = (
                select search_text
                from source_objects
                where source_objects.id = source_object_search.source_object_id
            )
            where book_id = 'rules'
            """
        )
        assert source_object_search_current(connection, "rules") is False

    summary = rebuild_source_object_search(config)

    assert summary.indexed == 1
    with open_connection(config.db_path) as connection:
        fresh_match = connection.execute(
            """
            select source_object_search.source_object_id
            from source_object_search_fts
            join source_object_search
              on source_object_search.rowid = source_object_search_fts.rowid
            where source_object_search_fts match '"critical"'
            """
        ).fetchone()
        stale_match = connection.execute(
            """
            select source_object_search.source_object_id
            from source_object_search_fts
            join source_object_search
              on source_object_search.rowid = source_object_search_fts.rowid
            where source_object_search_fts match '"stale"'
            """
        ).fetchone()
    assert fresh_match is not None
    assert stale_match is None


def test_rebuild_source_object_search_repairs_fts_with_extra_stale_terms(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update source_object_search
            set search_text = search_text || ' extrastaleterm'
            where book_id = 'rules'
            """
        )
        connection.execute(
            "insert into source_object_search_fts(source_object_search_fts) values('rebuild')"
        )
        connection.execute(
            """
            update source_object_search
            set search_text = (
                select search_text
                from source_objects
                where source_objects.id = source_object_search.source_object_id
            )
            where book_id = 'rules'
            """
        )
        assert source_object_search_current(connection, "rules") is False

    summary = rebuild_source_object_search(config)

    assert summary.indexed == 1
    with open_connection(config.db_path) as connection:
        stale_match = connection.execute(
            """
            select source_object_search.source_object_id
            from source_object_search_fts
            join source_object_search
              on source_object_search.rowid = source_object_search_fts.rowid
            where source_object_search_fts match '"extrastaleterm"'
            """
        ).fetchone()
    assert stale_match is None


def test_rebuild_source_object_search_repairs_fts_with_wrong_rowids(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        rows = connection.execute(
            """
            select source_object_id, search_text
            from source_object_search
            where book_id = 'rules'
            order by rowid
            """
        ).fetchall()
        assert len(rows) == 2
        connection.execute(
            """
            update source_object_search
            set search_text = ?
            where source_object_id = ?
            """,
            (rows[1]["search_text"], rows[0]["source_object_id"]),
        )
        connection.execute(
            """
            update source_object_search
            set search_text = ?
            where source_object_id = ?
            """,
            (rows[0]["search_text"], rows[1]["source_object_id"]),
        )
        connection.execute(
            "insert into source_object_search_fts(source_object_search_fts) values('rebuild')"
        )
        for row in rows:
            connection.execute(
                """
                update source_object_search
                set search_text = ?
                where source_object_id = ?
                """,
                (row["search_text"], row["source_object_id"]),
            )
        assert source_object_search_current(connection, "rules") is False

    summary = rebuild_source_object_search(config)

    assert summary.indexed == 1
    with open_connection(config.db_path) as connection:
        assert source_object_search_current(connection, "rules") is True


def test_rebuild_source_object_search_repairs_fts_with_wrong_object_type_rowids(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        rows = connection.execute(
            """
            select source_object_id, object_type
            from source_object_search
            where book_id = 'rules'
            order by rowid
            """
        ).fetchall()
        assert len(rows) == 2
        connection.execute(
            """
            update source_object_search
            set object_type = ?
            where source_object_id = ?
            """,
            (rows[1]["object_type"], rows[0]["source_object_id"]),
        )
        connection.execute(
            """
            update source_object_search
            set object_type = ?
            where source_object_id = ?
            """,
            (rows[0]["object_type"], rows[1]["source_object_id"]),
        )
        connection.execute(
            "insert into source_object_search_fts(source_object_search_fts) values('rebuild')"
        )
        for row in rows:
            connection.execute(
                """
                update source_object_search
                set object_type = ?
                where source_object_id = ?
                """,
                (row["object_type"], row["source_object_id"]),
            )
        assert source_object_search_current(connection, "rules") is False

    summary = rebuild_source_object_search(config)

    assert summary.indexed == 1
    with open_connection(config.db_path) as connection:
        assert source_object_search_current(connection, "rules") is True


def test_rebuild_source_object_search_repairs_status_when_projection_current(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update book_object_status
            set status = 'failed',
                last_error = 'stale status'
            where book_id = 'rules'
            """
        )

    summary = rebuild_source_object_search(config)

    assert summary.discovered == 1
    assert summary.indexed == 1
    assert summary.skipped_current == 0
    status = fetch_one(config, "select * from book_object_status")
    assert status["status"] == "indexed"
    assert status["last_error"] is None


def test_rebuild_source_object_search_can_force_current_projection(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)

    summary = rebuild_source_object_search(config, force=True)

    assert summary.indexed == 1
    assert summary.skipped_current == 0


def test_rebuild_source_object_search_initializes_missing_database(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)

    summary = rebuild_source_object_search(config)

    assert config.db_path.exists()
    assert summary.discovered == 0
    assert summary.indexed == 0


def test_rebuild_source_object_search_skips_active_indexing_status(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute("delete from source_object_search where book_id = 'rules'")
        connection.execute(
            """
            update book_object_status
            set status = 'indexing',
                updated_at = '2999-01-01T00:00:00Z'
            where book_id = 'rules'
            """
        )

    summary = rebuild_source_object_search(config)

    assert summary.discovered == 1
    assert summary.indexed == 0
    assert summary.skipped_current == 1
    assert summary.failed == 0


def test_rebuild_source_object_search_recovers_running_jobs(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update book_object_status
            set status = 'indexing',
                updated_at = '2026-06-05T00:00:00Z'
            where book_id = 'rules'
            """
        )
        connection.execute(
            """
            insert into ingest_jobs (
              id,
              job_type,
              target_id,
              status,
              idempotency_key,
              attempts,
              created_at,
              updated_at
            )
            values ('stale-object-search', 'rebuild_source_object_fts', 'rules',
                    'running', 'rebuild_source_object_fts:rules:stale', 1,
                    '2026-06-05T00:00:00Z', '2026-06-05T00:00:00Z')
            """
        )
        connection.execute("delete from source_object_search where book_id = 'rules'")

    summary = rebuild_source_object_search(config, retry_running=True)

    assert summary.stale_recovered == 1
    assert summary.indexed == 1
    with open_connection(config.db_path) as connection:
        stale_job = connection.execute(
            """
            select status, last_error
            from ingest_jobs
            where id = 'stale-object-search'
            """
        ).fetchone()
    assert stale_job["status"] == "failed"
    assert stale_job["last_error"] == "Recovered stale source-object FTS rebuild job."


def test_rebuild_source_object_search_reports_claim_conflict_as_failure(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        snapshot = source_object_search_snapshot_sha256(connection, "rules")
        job_id = source_object_search_job_id("rules", snapshot)
        connection.execute(
            """
            update book_object_status
            set status = 'indexed',
                updated_at = '2999-01-01T00:00:00Z'
            where book_id = 'rules'
            """
        )
        connection.execute(
            """
            insert into ingest_jobs (
              id,
              job_type,
              target_id,
              status,
              idempotency_key,
              attempts,
              created_at,
              updated_at
            )
            values (?, 'rebuild_source_object_fts', 'rules', 'running', ?, 1,
                    '2999-01-01T00:00:00Z', '2999-01-01T00:00:00Z')
            """,
            (job_id, job_id),
        )
        connection.execute("delete from source_object_search where book_id = 'rules'")

    summary = rebuild_source_object_search(config)

    assert summary.failed == 1
    assert summary.failures[0].reason == "Could not claim source-object FTS rebuild job."
    status = fetch_one(config, "select * from book_object_status")
    assert status["status"] == "failed"
    assert status["last_error"] == "Could not claim source-object FTS rebuild job."


def test_rebuild_source_object_search_records_projection_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute("delete from source_object_search where book_id = 'rules'")

    def fail_projection(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("synthetic projection failure")

    monkeypatch.setattr(store, "write_source_object_search_projection", fail_projection)

    summary = rebuild_source_object_search(config)

    assert summary.failed == 1
    assert summary.failures[0].book_id == "rules"
    status = fetch_one(config, "select * from book_object_status")
    job = fetch_one(
        config,
        "select * from ingest_jobs where job_type = 'rebuild_source_object_fts'",
    )
    assert status["status"] == "failed"
    assert status["last_error"] == "synthetic projection failure"
    assert job["status"] == "failed"
    assert job["last_error"] == "synthetic projection failure"


def test_source_object_search_snapshot_changes_with_projection_inputs(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)

    with open_connection(config.db_path) as connection:
        before = source_object_search_snapshot_sha256(connection, "rules")
        connection.execute(
            """
            update source_objects
            set search_text = 'changed search text'
            where id = (
                select id
                from source_objects
                where book_id = 'rules'
                order by id
                limit 1
            )
            """
        )
        after = source_object_search_snapshot_sha256(connection, "rules")

    assert before != after


def test_source_object_search_helper_edges(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)

    assert heading_path_text("{bad json") == ""
    assert heading_path_text('{"not": "a list"}') == ""
    with open_connection(config.db_path) as connection:
        assert source_object_search_current(connection, "missing-book") is False
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
              'empty-book',
              'core',
              'Empty Book',
              'Core',
              'Core/Empty Book.pdf',
              '/source/empty.pdf',
              '/managed/empty.pdf',
              'empty-source-sha',
              'empty-managed-sha',
              1,
              'copied',
              'imported',
              'indexed',
              'not_scanned',
              '2026-06-05T00:00:00Z',
              '2026-06-05T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            insert into book_object_status (book_id, status, updated_at)
            values ('empty-book', 'indexed', '2026-06-05T00:00:00Z')
            """
        )
        assert source_object_search_current(connection, "empty-book") is False
        assert source_object_search_book_ids(connection, book_ids=()) == ()
        assert source_object_search_claim_failure(connection, "missing-book") is None
        assert source_object_search_claim_failure(connection, "rules") is None
        connection.execute(
            """
            update source_objects
            set text_snapshot_sha256 = 'changed'
            where id = (
                select id
                from source_objects
                where book_id = 'rules'
                order by id
                limit 1
            )
            """
        )
        rows = connection.execute(
            """
            select text_snapshot_sha256
            from source_objects
            where book_id = 'rules'
            """
        ).fetchall()
        assert common_text_snapshot(rows) is None
