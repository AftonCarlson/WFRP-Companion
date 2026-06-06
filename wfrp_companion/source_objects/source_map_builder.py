from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from wfrp_companion.assistant.evidence import parse_heading_path
from wfrp_companion.assistant.query_planner import add_candidate, meaningful_tokens
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.db.migrations import apply_pending_migrations


BUILDER_VERSION = "source-map-builder-v1"
SCHEMA_VERSION = 1
SOURCE_MAP_ALIAS_LIMIT = 24
SOURCE_MAP_CHAPTER_LIMIT = 20


@dataclass(frozen=True)
class SourceMapBookSummary:
    book_id: str
    snapshot: str


@dataclass(frozen=True)
class SourceMapFailure:
    book_id: str
    reason: str


@dataclass(frozen=True)
class SourceMapRebuildSummary:
    discovered: int
    indexed: int
    skipped_current: int
    stale_recovered: int
    failed: int
    failures: tuple[SourceMapFailure, ...]
    book_summaries: tuple[SourceMapBookSummary, ...]


@dataclass(frozen=True)
class BookSourceMap:
    book_id: str
    summary: str
    aliases: tuple[str, ...]
    chapters: tuple[str, ...]
    best_source_for: tuple[str, ...]
    index_terms: tuple[str, ...]
    glossary_terms: tuple[str, ...]
    source_object_snapshot_sha256: str


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def source_map_job_id(book_id: str, source_object_snapshot: str) -> str:
    return f"rebuild_source_maps:{book_id}:{source_object_snapshot}:{BUILDER_VERSION}"


def source_object_snapshot_sha256(connection: sqlite3.Connection, book_id: str) -> str:
    digest = hashlib.sha256()
    book = connection.execute(
        """
        select id, title, category
        from books
        where id = ?
        """,
        (book_id,),
    ).fetchone()
    if book is not None:
        for value in ("book", book["id"], book["title"], book["category"]):
            digest.update(str(value).encode("utf-8"))
            digest.update(b"\0")
        digest.update(b"\n")
    rows = connection.execute(
        """
        select
          id,
          object_type,
          title,
          heading_path_json,
          page_start,
          page_end,
          text_snapshot_sha256
        from source_objects
        where book_id = ?
        order by page_start, page_end, id
        """,
        (book_id,),
    ).fetchall()
    for row in rows:
        for value in (
            row["id"],
            row["object_type"],
            row["title"] or "",
            row["heading_path_json"],
            str(row["page_start"]),
            str(row["page_end"]),
            row["text_snapshot_sha256"],
        ):
            digest.update(str(value).encode("utf-8"))
            digest.update(b"\0")
        digest.update(b"\n")
    return digest.hexdigest()


def rebuild_source_maps(
    config: AppConfig,
    *,
    book_ids: tuple[str, ...] | None = None,
    force: bool = False,
    retry_running: bool = False,
    stale_running_minutes: int = 30,
) -> SourceMapRebuildSummary:
    if not config.db_path.exists():
        initialize_database(config.db_path).close()
    apply_pending_migrations(config.db_path)
    failures: list[SourceMapFailure] = []
    book_summaries: list[SourceMapBookSummary] = []
    indexed = 0
    skipped_current = 0
    with initialize_database(config.db_path) as connection:
        stale_recovered = recover_stale_running_jobs(
            connection,
            retry_running=retry_running,
            stale_running_minutes=stale_running_minutes,
        )
        books = eligible_books(connection, book_ids=book_ids)
        for book_id in books:
            snapshot = source_object_snapshot_sha256(connection, book_id)
            if not force and source_map_current(
                connection,
                book_id=book_id,
                source_object_snapshot=snapshot,
            ):
                skipped_current += 1
                book_summaries.append(SourceMapBookSummary(book_id, snapshot))
                continue

            now = utc_timestamp()
            job_id = source_map_job_id(book_id, snapshot)
            if not claim_source_map_job(
                connection,
                book_id=book_id,
                source_object_snapshot=snapshot,
                force=force,
                now=now,
            ):
                if failure_reason := source_map_claim_failure(connection, book_id):
                    failures.append(SourceMapFailure(book_id, failure_reason))
                else:
                    skipped_current += 1
                continue
            try:
                source_map = build_book_source_map(connection, book_id, snapshot)
                persist_book_source_map(
                    connection,
                    source_map=source_map,
                    job_id=job_id,
                    now=utc_timestamp(),
                )
            except Exception as error:  # pragma: no cover - exercised via tool monkeypatch
                mark_source_map_failed(
                    connection,
                    book_id=book_id,
                    job_id=job_id,
                    error=str(error),
                    now=utc_timestamp(),
                )
                failures.append(SourceMapFailure(book_id, str(error)))
                continue
            indexed += 1
            book_summaries.append(SourceMapBookSummary(book_id, snapshot))

    return SourceMapRebuildSummary(
        discovered=len(books),
        indexed=indexed,
        skipped_current=skipped_current,
        stale_recovered=stale_recovered,
        failed=len(failures),
        failures=tuple(failures),
        book_summaries=tuple(book_summaries),
    )


def eligible_books(
    connection: sqlite3.Connection,
    *,
    book_ids: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    sql = """
        select id
        from books
        where copy_status = 'copied'
          and text_status = 'imported'
          and search_status = 'indexed'
          and exists (
            select 1
            from source_objects
            where source_objects.book_id = books.id
          )
    """
    parameters: list[object] = []
    if book_ids is not None:
        if not book_ids:
            return ()
        placeholders = ",".join("?" for _ in book_ids)
        sql += f" and id in ({placeholders})"
        parameters.extend(book_ids)
    sql += " order by id"
    return tuple(row["id"] for row in connection.execute(sql, parameters).fetchall())


def source_map_current(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    source_object_snapshot: str,
) -> bool:
    row = connection.execute(
        """
        select source_map_status, source_map_snapshot_sha256
        from book_retrieval_status
        where book_id = ?
        """,
        (book_id,),
    ).fetchone()
    return (
        row is not None
        and row["source_map_status"] == "indexed"
        and row["source_map_snapshot_sha256"] == source_object_snapshot
    )


def source_map_claim_failure(connection: sqlite3.Connection, book_id: str) -> str | None:
    row = connection.execute(
        """
        select source_map_status, last_error
        from book_retrieval_status
        where book_id = ?
        """,
        (book_id,),
    ).fetchone()
    if row is None:
        return None
    if row["source_map_status"] == "failed" and row["last_error"]:
        return str(row["last_error"])
    return None


def ensure_book_retrieval_status(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    now: str,
) -> None:
    connection.execute(
        """
        insert into book_retrieval_status (book_id, updated_at)
        values (?, ?)
        on conflict(book_id) do nothing
        """,
        (book_id, now),
    )


def claim_source_map_job(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    source_object_snapshot: str,
    force: bool,
    now: str,
) -> bool:
    ensure_book_retrieval_status(connection, book_id=book_id, now=now)
    status = connection.execute(
        "select source_map_status from book_retrieval_status where book_id = ?",
        (book_id,),
    ).fetchone()
    if status is not None and status["source_map_status"] == "indexing":
        return False

    job_id = source_map_job_id(book_id, source_object_snapshot)
    with connection:
        status_cursor = connection.execute(
            """
            update book_retrieval_status
            set source_map_status = 'indexing',
                source_map_started_at = ?,
                source_object_snapshot_sha256 = ?,
                last_error = null,
                updated_at = ?
            where book_id = ?
              and (
                ? = 1
                or source_map_status in ('not_started', 'needs_refresh', 'failed', 'indexed')
              )
            """,
            (now, source_object_snapshot, now, book_id, int(force)),
        )
        if status_cursor.rowcount != 1:  # pragma: no cover - concurrent status guard
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
            values (?, 'rebuild_source_maps', ?, 'running', ?, 1, null, ?, ?, null)
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
                update book_retrieval_status
                set source_map_status = 'failed',
                    last_error = 'Could not claim source-map rebuild job.',
                    updated_at = ?
                where book_id = ?
                  and source_map_status = 'indexing'
                """,
                (now, book_id),
            )
            return False
    return True


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
            where job_type = 'rebuild_source_maps'
              and status = 'running'
            """
        ).fetchall()
    else:
        rows = connection.execute(
            """
            select id, target_id
            from ingest_jobs
            where job_type = 'rebuild_source_maps'
              and status = 'running'
              and updated_at < ?
            """,
            (stale_before,),
        ).fetchall()
    with connection:
        for row in rows:
            connection.execute(
                """
                update ingest_jobs
                set status = 'failed',
                    last_error = 'Recovered stale running source-map rebuild job.',
                    updated_at = ?
                where id = ?
                """,
                (now, row["id"]),
            )
            if row["target_id"]:
                connection.execute(
                    """
                    update book_retrieval_status
                    set source_map_status = 'needs_refresh',
                        last_error = 'Recovered stale running source-map rebuild job.',
                        updated_at = ?
                    where book_id = ?
                      and source_map_status = 'indexing'
                    """,
                    (now, row["target_id"]),
                )
    return len(rows)


def build_book_source_map(
    connection: sqlite3.Connection,
    book_id: str,
    source_object_snapshot: str,
) -> BookSourceMap:
    book = connection.execute(
        "select id, title, category from books where id = ?",
        (book_id,),
    ).fetchone()
    if book is None:
        raise ValueError(f"Book not found: {book_id}")
    chapters = source_map_chapters(connection, book_id)
    aliases = source_map_aliases(
        title=book["title"],
        category=book["category"],
        chapters=chapters,
    )
    best_source_for = infer_best_source_for(book["category"], aliases)
    return BookSourceMap(
        book_id=book_id,
        summary=f"{book['title']} is in {book['category']}.",
        aliases=aliases,
        chapters=chapters,
        best_source_for=best_source_for,
        index_terms=(),
        glossary_terms=(),
        source_object_snapshot_sha256=source_object_snapshot,
    )


def source_map_chapters(
    connection: sqlite3.Connection,
    book_id: str,
) -> tuple[str, ...]:
    rows = connection.execute(
        """
        select title, heading_path_json
        from source_objects
        where book_id = ?
          and title is not null
        order by page_start, id
        limit 120
        """,
        (book_id,),
    ).fetchall()
    chapters: list[str] = []
    for row in rows:
        for value in (*parse_heading_path(row["heading_path_json"]), row["title"]):
            if value and value not in chapters:
                chapters.append(value)
            if len(chapters) >= SOURCE_MAP_CHAPTER_LIMIT:
                return tuple(chapters)
    return tuple(chapters)


def source_map_aliases(
    *,
    title: str,
    category: str,
    chapters: tuple[str, ...],
) -> tuple[str, ...]:
    aliases: list[str] = []
    for value in (title, category, *chapters):
        for token in meaningful_tokens(value):
            add_candidate(aliases, token)
            if len(aliases) >= SOURCE_MAP_ALIAS_LIMIT:
                return tuple(aliases)
    return tuple(aliases)


def infer_best_source_for(
    category: str,
    aliases: tuple[str, ...],
) -> tuple[str, ...]:
    values: list[str] = []
    lowered_category = category.casefold()
    if "adventure" in lowered_category:
        values.append("adventure_scene_lookup")
    if "world" in lowered_category or "faction" in lowered_category:
        values.append("lore_lookup")
    if "rules" in lowered_category or "core" in lowered_category:
        values.append("rules_lookup")
    if aliases:
        values.append("source_navigation")
    return tuple(dict.fromkeys(values))


def persist_book_source_map(
    connection: sqlite3.Connection,
    *,
    source_map: BookSourceMap,
    job_id: str,
    now: str,
) -> None:
    with connection:
        connection.execute(
            """
            insert into book_source_maps (
              book_id,
              summary,
              aliases_json,
              chapters_json,
              best_source_for_json,
              index_terms_json,
              glossary_terms_json,
              source_object_snapshot_sha256,
              schema_version,
              builder_version,
              created_at,
              updated_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(book_id) do update set
              summary = excluded.summary,
              aliases_json = excluded.aliases_json,
              chapters_json = excluded.chapters_json,
              best_source_for_json = excluded.best_source_for_json,
              index_terms_json = excluded.index_terms_json,
              glossary_terms_json = excluded.glossary_terms_json,
              source_object_snapshot_sha256 = excluded.source_object_snapshot_sha256,
              schema_version = excluded.schema_version,
              builder_version = excluded.builder_version,
              updated_at = excluded.updated_at
            """,
            (
                source_map.book_id,
                source_map.summary,
                json.dumps(list(source_map.aliases)),
                json.dumps(list(source_map.chapters)),
                json.dumps(list(source_map.best_source_for)),
                json.dumps(list(source_map.index_terms)),
                json.dumps(list(source_map.glossary_terms)),
                source_map.source_object_snapshot_sha256,
                SCHEMA_VERSION,
                BUILDER_VERSION,
                now,
                now,
            ),
        )
        connection.execute(
            "delete from book_query_profiles where book_id = ?",
            (source_map.book_id,),
        )
        for query_type in source_map.best_source_for:
            connection.execute(
                """
                insert into book_query_profiles (
                  book_id,
                  query_type,
                  confidence,
                  evidence_json,
                  updated_at
                )
                values (?, ?, 0.75, ?, ?)
                """,
                (
                    source_map.book_id,
                    query_type,
                    json.dumps(
                        {
                            "source_map_snapshot": source_map.source_object_snapshot_sha256,
                            "builder_version": BUILDER_VERSION,
                        },
                        sort_keys=True,
                    ),
                    now,
                ),
            )
        connection.execute(
            """
            update book_retrieval_status
            set source_map_status = 'indexed',
                source_object_snapshot_sha256 = ?,
                source_map_snapshot_sha256 = ?,
                last_error = null,
                updated_at = ?
            where book_id = ?
            """,
            (
                source_map.source_object_snapshot_sha256,
                source_map.source_object_snapshot_sha256,
                now,
                source_map.book_id,
            ),
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


def mark_source_map_failed(
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
            update book_retrieval_status
            set source_map_status = 'failed',
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
