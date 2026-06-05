from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from wfrp_companion.source_objects.models import SourceObject


@dataclass(frozen=True)
class EligibleBook:
    book_id: str
    title: str
    managed_pdf_path: str
    page_count: int


@dataclass(frozen=True)
class SourcePage:
    page_id: str
    book_id: str
    page_number: int
    extraction_method: str
    ocr_attempted: bool
    text_sha256: str
    text: str


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def extraction_job_id(book_id: str, text_snapshot_sha256: str) -> str:
    return f"extract_source_objects:{book_id}:{text_snapshot_sha256}"


def eligible_books(
    connection: sqlite3.Connection,
    *,
    book_ids: tuple[str, ...] | None = None,
) -> tuple[EligibleBook, ...]:
    sql = """
        select id, title, managed_pdf_path, page_count
        from books
        where copy_status = 'copied'
          and text_status = 'imported'
          and search_status = 'indexed'
    """
    parameters: list[object] = []
    if book_ids is not None:
        if not book_ids:
            return ()
        placeholders = ",".join("?" for _ in book_ids)
        sql += f" and id in ({placeholders})"
        parameters.extend(book_ids)
    sql += " order by id"
    rows = connection.execute(sql, parameters).fetchall()
    return tuple(
        EligibleBook(
            book_id=row["id"],
            title=row["title"],
            managed_pdf_path=row["managed_pdf_path"],
            page_count=row["page_count"],
        )
        for row in rows
    )


def book_text_snapshot_sha256(connection: sqlite3.Connection, book_id: str) -> str:
    digest = hashlib.sha256()
    rows = connection.execute(
        """
        select pages.id as page_id, page_text.text_sha256
        from pages
        join page_text on page_text.page_id = pages.id
        where pages.book_id = ?
        order by pages.page_number, pages.id
        """,
        (book_id,),
    ).fetchall()
    for row in rows:
        digest.update(row["page_id"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(row["text_sha256"].encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def load_book_pages(
    connection: sqlite3.Connection,
    book_id: str,
) -> tuple[SourcePage, ...]:
    rows = connection.execute(
        """
        select
          pages.id as page_id,
          pages.book_id,
          pages.page_number,
          pages.extraction_method,
          pages.ocr_attempted,
          page_text.text_sha256,
          page_text.text
        from pages
        join page_text on page_text.page_id = pages.id
        where pages.book_id = ?
        order by pages.page_number, pages.id
        """,
        (book_id,),
    ).fetchall()
    return tuple(
        SourcePage(
            page_id=row["page_id"],
            book_id=row["book_id"],
            page_number=row["page_number"],
            extraction_method=row["extraction_method"],
            ocr_attempted=bool(row["ocr_attempted"]),
            text_sha256=row["text_sha256"],
            text=row["text"],
        )
        for row in rows
    )


def ensure_book_object_status(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    now: str,
) -> None:
    connection.execute(
        """
        insert into book_object_status (book_id, status, updated_at)
        values (?, 'not_started', ?)
        on conflict(book_id) do nothing
        """,
        (book_id, now),
    )


def object_status_current(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    text_snapshot_sha256: str,
) -> bool:
    row = connection.execute(
        """
        select status, object_count
        from book_object_status
        where book_id = ?
          and text_snapshot_sha256 = ?
          and status in ('extracted', 'indexed')
        """,
        (book_id, text_snapshot_sha256),
    ).fetchone()
    if row is None:
        return False
    object_count = connection.execute(
        """
        select count(*)
        from source_objects
        where book_id = ?
          and text_snapshot_sha256 = ?
        """,
        (book_id, text_snapshot_sha256),
    ).fetchone()[0]
    return object_count == row["object_count"]


def recover_stale_running_jobs(
    connection: sqlite3.Connection,
    *,
    retry_running: bool,
    stale_running_minutes: int,
) -> int:
    now = utc_timestamp()
    stale_before = (
        datetime.now(timezone.utc).replace(microsecond=0)
        - timedelta(minutes=stale_running_minutes)
    ).isoformat().replace("+00:00", "Z")
    if retry_running:
        rows = connection.execute(
            """
            select id, target_id
            from ingest_jobs
            where job_type = 'extract_source_objects'
              and status = 'running'
            """
        ).fetchall()
    else:
        rows = connection.execute(
            """
            select id, target_id
            from ingest_jobs
            where job_type = 'extract_source_objects'
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
                    last_error = 'Recovered stale running source-object extraction job.',
                    updated_at = ?
                where id = ?
                """,
                (now, row["id"]),
            )
            if row["target_id"]:
                connection.execute(
                    """
                    update book_object_status
                    set status = 'failed',
                        last_error = 'Recovered stale running source-object extraction job.',
                        updated_at = ?
                    where book_id = ?
                      and status = 'extracting'
                    """,
                    (now, row["target_id"]),
                )
    return len(rows)


def claim_extraction_job(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    text_snapshot_sha256: str,
    force: bool,
    now: str,
) -> bool:
    ensure_book_object_status(connection, book_id=book_id, now=now)
    status = connection.execute(
        "select status from book_object_status where book_id = ?",
        (book_id,),
    ).fetchone()
    if status is not None and status["status"] == "extracting":
        return False

    job_id = extraction_job_id(book_id, text_snapshot_sha256)
    with connection:
        status_cursor = connection.execute(
            """
            update book_object_status
            set status = 'extracting',
                text_snapshot_sha256 = ?,
                last_error = null,
                updated_at = ?
            where book_id = ?
              and (
                ? = 1
                or status in ('not_started', 'failed', 'extracted', 'indexed')
              )
            """,
            (text_snapshot_sha256, now, book_id, int(force)),
        )
        if status_cursor.rowcount != 1:
            return False
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
            values (?, 'extract_source_objects', ?, 'running', ?, 1, null, ?, ?, null)
            on conflict(idempotency_key) do update set
              status = 'running',
              attempts = ingest_jobs.attempts + 1,
              last_error = null,
              updated_at = excluded.updated_at,
              completed_at = null
            where ingest_jobs.status in ('queued', 'failed', 'succeeded')
            """,
            (job_id, book_id, job_id, now, now),
        )
        if cursor.rowcount != 1:
            connection.execute(
                """
                update book_object_status
                set status = 'failed',
                    last_error = 'Could not claim source-object extraction job.',
                    updated_at = ?
                where book_id = ?
                  and status = 'extracting'
                """,
                (now, book_id),
            )
            return False
    return True


def replace_book_source_objects(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    text_snapshot_sha256: str,
    source_objects: tuple[SourceObject, ...],
    job_id: str,
    now: str,
) -> None:
    with connection:
        connection.execute("delete from source_object_search where book_id = ?", (book_id,))
        connection.execute("delete from source_objects where book_id = ?", (book_id,))
        for source_object in source_objects:
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
                  char_start,
                  char_end,
                  bbox_json,
                  text,
                  search_text,
                  metadata_json,
                  confidence,
                  extraction_method,
                  text_snapshot_sha256,
                  created_at,
                  updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_object.id,
                    source_object.book_id,
                    source_object.page_id,
                    source_object.object_type,
                    source_object.parent_object_id,
                    source_object.title,
                    json.dumps(list(source_object.heading_path)),
                    source_object.page_start,
                    source_object.page_end,
                    source_object.char_start,
                    source_object.char_end,
                    source_object.bbox_json,
                    source_object.text,
                    source_object.search_text,
                    source_object.metadata_json,
                    source_object.confidence,
                    source_object.extraction_method,
                    source_object.text_snapshot_sha256,
                    now,
                    now,
                ),
            )
        connection.execute(
            """
            update book_object_status
            set status = 'extracted',
                object_count = ?,
                table_count = 0,
                stat_block_count = 0,
                location_count = 0,
                text_snapshot_sha256 = ?,
                last_error = null,
                updated_at = ?
            where book_id = ?
            """,
            (len(source_objects), text_snapshot_sha256, now, book_id),
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


def mark_extraction_failed(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    job_id: str,
    error: str,
    now: str,
) -> None:
    with connection:
        connection.execute(
            """
            update book_object_status
            set status = 'failed',
                last_error = ?,
                updated_at = ?
            where book_id = ?
            """,
            (error, now, book_id),
        )
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
