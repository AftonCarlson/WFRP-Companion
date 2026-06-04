from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database


@dataclass(frozen=True)
class FtsRebuildSummary:
    books_indexed: int
    pages_indexed: int
    skipped_current: int
    stale_recovered: int
    failed: int
    failure_reason: str | None


@dataclass(frozen=True)
class SearchHit:
    book_id: str
    title: str
    category: str
    page_id: str
    page_number: int
    snippet: str
    rank: int
    score: float


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def rebuild_job_id(snapshot_sha256: str) -> str:
    return f"rebuild_fts:global:{snapshot_sha256}"


def rebuild_global_fts(
    config: AppConfig,
    *,
    force: bool = False,
    retry_running: bool = False,
    stale_running_minutes: int = 30,
) -> FtsRebuildSummary:
    with initialize_database(config.db_path) as connection:
        stale_recovered = recover_stale_running_jobs(
            connection,
            retry_running=retry_running,
            stale_running_minutes=stale_running_minutes,
        )
        book_ids = imported_book_ids(connection)
        snapshot_sha = text_snapshot_sha256(connection)
        job_id = rebuild_job_id(snapshot_sha)

        if (
            rebuild_job_succeeded(connection, job_id)
            and not force
            and fts_projection_current(connection, book_ids)
        ):
            return FtsRebuildSummary(
                books_indexed=0,
                pages_indexed=0,
                skipped_current=1,
                stale_recovered=stale_recovered,
                failed=0,
                failure_reason=None,
            )

        if not claim_rebuild_job(connection, job_id=job_id, now=utc_timestamp()):
            return FtsRebuildSummary(
                books_indexed=0,
                pages_indexed=0,
                skipped_current=0,
                stale_recovered=stale_recovered,
                failed=0,
                failure_reason=None,
            )
        try:
            pages_indexed = write_global_fts(
                connection,
                book_ids=book_ids,
                job_id=job_id,
                now=utc_timestamp(),
            )
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            mark_rebuild_failed(connection, job_id=job_id, error=error, now=utc_timestamp())
            return FtsRebuildSummary(
                books_indexed=0,
                pages_indexed=0,
                skipped_current=0,
                stale_recovered=stale_recovered,
                failed=1,
                failure_reason=error,
            )

        return FtsRebuildSummary(
            books_indexed=len(book_ids),
            pages_indexed=pages_indexed,
            skipped_current=0,
            stale_recovered=stale_recovered,
            failed=0,
            failure_reason=None,
        )


def recover_stale_running_jobs(
    connection: sqlite3.Connection,
    *,
    retry_running: bool,
    stale_running_minutes: int,
) -> int:
    now = utc_timestamp()
    stale_before = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        - timedelta(minutes=stale_running_minutes)
    ).isoformat().replace("+00:00", "Z")

    if retry_running:
        rows = connection.execute(
            """
            select id
            from ingest_jobs
            where job_type = 'rebuild_fts'
              and status = 'running'
            """
        ).fetchall()
    else:
        rows = connection.execute(
            """
            select id
            from ingest_jobs
            where job_type = 'rebuild_fts'
              and status = 'running'
              and updated_at < ?
            """,
            (stale_before,),
        ).fetchall()

    if not rows:
        return 0

    with connection:
        for row in rows:
            connection.execute(
                """
                update ingest_jobs
                set status = 'failed',
                    last_error = 'Recovered stale running FTS rebuild job.',
                    updated_at = ?
                where id = ?
                """,
                (now, row["id"]),
            )
        connection.execute(
            """
            update books
            set search_status = 'failed',
                updated_at = ?
            where search_status = 'indexing'
            """,
            (now,),
        )
    return len(rows)


def imported_book_ids(connection: sqlite3.Connection) -> tuple[str, ...]:
    rows = connection.execute(
        """
        select id
        from books
        where copy_status = 'copied'
          and text_status = 'imported'
        order by id
        """
    ).fetchall()
    return tuple(row["id"] for row in rows)


def text_snapshot_sha256(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    rows = connection.execute(
        """
        select page_text.page_id, page_text.text_sha256
        from page_text
        join pages on pages.id = page_text.page_id
        join books on books.id = pages.book_id
        where books.copy_status = 'copied'
          and books.text_status = 'imported'
        order by page_text.page_id
        """
    ).fetchall()
    for row in rows:
        digest.update(row["page_id"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(row["text_sha256"].encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def rebuild_job_succeeded(connection: sqlite3.Connection, job_id: str) -> bool:
    row = connection.execute(
        """
        select status
        from ingest_jobs
        where idempotency_key = ?
        """,
        (job_id,),
    ).fetchone()
    return row is not None and row["status"] == "succeeded"


def fts_projection_current(
    connection: sqlite3.Connection,
    book_ids: tuple[str, ...],
) -> bool:
    stale_rows = connection.execute(
        """
        select count(*)
        from page_search
        left join books on books.id = page_search.book_id
        where books.id is null
          or books.copy_status != 'copied'
          or books.text_status != 'imported'
          or books.search_status != 'indexed'
        """
    ).fetchone()[0]
    if stale_rows:
        return False

    not_indexed = connection.execute(
        """
        select count(*)
        from books
        where copy_status = 'copied'
          and text_status = 'imported'
          and search_status != 'indexed'
        """
    ).fetchone()[0]
    if not_indexed:
        return False

    if page_search_row_count(connection) != imported_page_text_count(connection):
        return False

    try:
        run_fts_integrity_check(connection)
    except sqlite3.DatabaseError:
        return False
    return fts_row_count(connection) == page_search_row_count(connection)


def imported_page_text_count(connection: sqlite3.Connection) -> int:
    return connection.execute(
        """
        select count(*)
        from page_text
        join pages on pages.id = page_text.page_id
        join books on books.id = pages.book_id
        where books.copy_status = 'copied'
          and books.text_status = 'imported'
        """
    ).fetchone()[0]


def claim_rebuild_job(
    connection: sqlite3.Connection,
    *,
    job_id: str,
    now: str,
) -> bool:
    with connection:
        cursor = connection.execute(
            """
            insert into ingest_jobs (
              id,
              job_type,
              target_id,
              status,
              idempotency_key,
              attempts,
              last_error,
              created_at,
              updated_at,
              completed_at
            )
            values (?, 'rebuild_fts', 'global', 'running', ?, 1, null, ?, ?, null)
            on conflict(idempotency_key) do update set
              status = 'running',
              attempts = ingest_jobs.attempts + 1,
              last_error = null,
              updated_at = excluded.updated_at,
              completed_at = null
            where ingest_jobs.status in ('queued', 'failed', 'succeeded')
            """,
            (job_id, job_id, now, now),
        )
    return cursor.rowcount == 1


def write_global_fts(
    connection: sqlite3.Connection,
    *,
    book_ids: tuple[str, ...],
    job_id: str,
    now: str,
) -> int:
    with connection:
        if book_ids:
            placeholders = ",".join("?" for _ in book_ids)
            connection.execute(
                f"""
                update books
                set search_status = 'indexing',
                    updated_at = ?
                where id in ({placeholders})
                """,
                (now, *book_ids),
            )

        connection.execute("delete from page_search")
        connection.execute(
            """
            insert into page_search (
              page_id,
              book_id,
              folder_id,
              category,
              title,
              page_number,
              text
            )
            select
              pages.id,
              books.id,
              books.folder_id,
              books.category,
              books.title,
              pages.page_number,
              page_text.text
            from pages
            join page_text on page_text.page_id = pages.id
            join books on books.id = pages.book_id
            where books.copy_status = 'copied'
              and books.text_status = 'imported'
            order by books.id, pages.page_number
            """
        )
        rebuild_fts_table(connection)
        run_fts_integrity_check(connection)
        pages_indexed = page_search_row_count(connection)
        if pages_indexed != fts_row_count(connection):
            raise RuntimeError("page_search and page_search_fts row counts drifted")

        if book_ids:
            placeholders = ",".join("?" for _ in book_ids)
            connection.execute(
                f"""
                update books
                set search_status = 'indexed',
                    updated_at = ?
                where id in ({placeholders})
                """,
                (now, *book_ids),
            )
        connection.execute(
            """
            update books
            set search_status = 'not_indexed',
                updated_at = ?
            where text_status != 'imported'
              and search_status in ('indexing', 'needs_refresh', 'indexed')
            """,
            (now,),
        )
        connection.execute(
            """
            update ingest_jobs
            set status = 'succeeded',
                last_error = null,
                updated_at = ?,
                completed_at = ?
            where idempotency_key = ?
            """,
            (now, now, job_id),
        )
    return pages_indexed


def rebuild_fts_table(connection: sqlite3.Connection) -> None:
    connection.execute("insert into page_search_fts(page_search_fts) values('rebuild')")


def run_fts_integrity_check(connection: sqlite3.Connection) -> None:
    connection.execute(
        "insert into page_search_fts(page_search_fts, rank) values('integrity-check', 1)"
    )


def page_search_row_count(connection: sqlite3.Connection) -> int:
    return connection.execute("select count(*) from page_search").fetchone()[0]


def fts_row_count(connection: sqlite3.Connection) -> int:
    return connection.execute("select count(*) from page_search_fts").fetchone()[0]


def mark_rebuild_failed(
    connection: sqlite3.Connection,
    *,
    job_id: str,
    error: str,
    now: str,
) -> None:
    with connection:
        connection.execute(
            """
            update ingest_jobs
            set status = 'failed',
                last_error = ?,
                updated_at = ?
            where idempotency_key = ?
            """,
            (error, now, job_id),
        )
        connection.execute(
            """
            update books
            set search_status = 'failed',
                updated_at = ?
            where copy_status = 'copied'
              and text_status = 'imported'
            """,
            (now,),
        )


def build_fts_query(query: str) -> str | None:
    tokens = re.findall(r"(?u)\w+", query)
    if not tokens:
        return None
    return " AND ".join(f'"{token}"' for token in tokens)


def search_exact(
    config: AppConfig,
    query: str,
    *,
    book_ids: Collection[str] | None = None,
    limit: int = 20,
) -> tuple[SearchHit, ...]:
    selected_book_ids = None if book_ids is None else tuple(book_ids)
    if selected_book_ids == ():
        return ()

    fts_query = build_fts_query(query)
    if fts_query is None:
        return ()

    bounded_limit = max(1, min(limit, 100))
    sql = """
        select
          page_search.book_id,
          page_search.title,
          page_search.category,
          page_search.page_id,
          page_search.page_number,
          snippet(page_search_fts, 1, '[', ']', '...', 12) as snippet,
          bm25(page_search_fts) as score
        from page_search_fts
        join page_search on page_search.rowid = page_search_fts.rowid
        join books on books.id = page_search.book_id
        where page_search_fts match ?
          and books.copy_status = 'copied'
          and books.text_status = 'imported'
          and books.search_status = 'indexed'
    """
    parameters: list[object] = [fts_query]
    if selected_book_ids is not None:
        placeholders = ",".join("?" for _ in selected_book_ids)
        sql += f" and page_search.book_id in ({placeholders})"
        parameters.extend(selected_book_ids)
    sql += """
        order by score asc, page_search.title asc, page_search.page_number asc
        limit ?
    """
    parameters.append(bounded_limit)

    with initialize_database(config.db_path) as connection:
        rows = connection.execute(sql, parameters).fetchall()

    return tuple(
        SearchHit(
            book_id=row["book_id"],
            title=row["title"],
            category=row["category"],
            page_id=row["page_id"],
            page_number=row["page_number"],
            snippet=row["snippet"],
            rank=rank,
            score=float(row["score"]),
        )
        for rank, row in enumerate(rows, start=1)
    )
