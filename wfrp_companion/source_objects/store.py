from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.db.migrations import apply_pending_migrations
from wfrp_companion.source_objects.models import SourceObject


SOURCE_OBJECT_EXTRACTOR_VERSION = "structured-evidence-v1"


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


@dataclass(frozen=True)
class ObjectSearchRebuildFailure:
    book_id: str
    reason: str


@dataclass(frozen=True)
class ObjectSearchRebuildSummary:
    discovered: int
    indexed: int
    skipped_current: int
    stale_recovered: int
    failed: int
    objects_written: int
    failures: tuple[ObjectSearchRebuildFailure, ...]


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def extraction_job_id(book_id: str, text_snapshot_sha256: str) -> str:
    return f"extract_source_objects:{book_id}:{text_snapshot_sha256}"


def source_object_search_job_id(book_id: str, source_object_snapshot: str) -> str:
    return f"rebuild_source_object_fts:{book_id}:{source_object_snapshot}"


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


def source_object_search_snapshot_sha256(
    connection: sqlite3.Connection,
    book_id: str,
) -> str:
    digest = hashlib.sha256()
    rows = connection.execute(
        """
        select
          id,
          book_id,
          page_id,
          object_type,
          title,
          heading_path_json,
          page_start,
          page_end,
          confidence,
          search_text,
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
            row["book_id"],
            row["page_id"],
            row["object_type"],
            row["title"] or "",
            heading_path_text(row["heading_path_json"]),
            str(row["page_start"]),
            str(row["page_end"]),
            f"{float(row['confidence']):.6f}",
            row["search_text"],
            row["text_snapshot_sha256"],
        ):
            digest.update(str(value).encode("utf-8"))
            digest.update(b"\0")
        digest.update(b"\n")
    return digest.hexdigest()


def source_object_search_projection_snapshot_sha256(
    connection: sqlite3.Connection,
    book_id: str,
) -> str:
    digest = hashlib.sha256()
    rows = connection.execute(
        """
        select
          source_object_search.source_object_id,
          source_object_search.book_id,
          source_object_search.page_id,
          source_object_search.object_type,
          source_object_search.title,
          source_object_search.heading_path,
          source_object_search.page_start,
          source_object_search.page_end,
          source_object_search.confidence,
          source_object_search.search_text,
          source_objects.text_snapshot_sha256
        from source_object_search
        join source_objects
          on source_objects.id = source_object_search.source_object_id
        where source_object_search.book_id = ?
        order by
          source_object_search.page_start,
          source_object_search.page_end,
          source_object_search.source_object_id
        """,
        (book_id,),
    ).fetchall()
    for row in rows:
        for value in (
            row["source_object_id"],
            row["book_id"],
            row["page_id"],
            row["object_type"],
            row["title"] or "",
            row["heading_path"],
            str(row["page_start"]),
            str(row["page_end"]),
            f"{float(row['confidence']):.6f}",
            row["search_text"],
            row["text_snapshot_sha256"],
        ):
            digest.update(str(value).encode("utf-8"))
            digest.update(b"\0")
        digest.update(b"\n")
    return digest.hexdigest()


def heading_path_text(heading_path_json: str) -> str:
    try:
        parsed = json.loads(heading_path_json or "[]")
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, list):
        return ""
    return " > ".join(value for value in parsed if isinstance(value, str))


def source_object_search_current(connection: sqlite3.Connection, book_id: str) -> bool:
    status = connection.execute(
        """
        select status
        from book_object_status
        where book_id = ?
        """,
        (book_id,),
    ).fetchone()
    if status is None or status["status"] != "indexed":
        return False
    source_count = connection.execute(
        "select count(*) from source_objects where book_id = ?",
        (book_id,),
    ).fetchone()[0]
    if source_count == 0:
        return False
    search_count = connection.execute(
        "select count(*) from source_object_search where book_id = ?",
        (book_id,),
    ).fetchone()[0]
    fts_count = connection.execute(
        """
        select count(*)
        from source_object_search_fts
        join source_object_search
          on source_object_search.rowid = source_object_search_fts.rowid
        where source_object_search.book_id = ?
        """,
        (book_id,),
    ).fetchone()[0]
    if source_count != search_count or search_count != fts_count:
        return False
    if source_object_search_snapshot_sha256(
        connection,
        book_id,
    ) != source_object_search_projection_snapshot_sha256(connection, book_id):
        return False
    return source_object_fts_matches_projection(connection, book_id)


def source_object_fts_matches_projection(
    connection: sqlite3.Connection,
    book_id: str,
) -> bool:
    rows = connection.execute(
        """
        select
          rowid,
          title,
          heading_path,
          object_type,
          search_text
        from source_object_search
        where book_id = ?
        order by rowid
        """,
        (book_id,),
    ).fetchall()
    connection.execute(
        """
        create virtual table if not exists temp.expected_source_object_search_fts
        using fts5(title, heading_path, object_type, search_text)
        """
    )
    connection.execute("delete from temp.expected_source_object_search_fts")
    for row in rows:
        connection.execute(
            """
            insert into temp.expected_source_object_search_fts (
              rowid,
              title,
              heading_path,
              object_type,
              search_text
            )
            values (?, ?, ?, ?, ?)
            """,
            (
                row["rowid"],
                row["title"] or "",
                row["heading_path"],
                row["object_type"],
                row["search_text"],
            ),
        )
    if not source_object_fts_vocabulary_matches_projection(connection, book_id):
        return False
    for token in source_object_fts_validation_terms(rows):
        query = f'"{token}"'
        actual = tuple(
            row["rowid"]
            for row in connection.execute(
                """
                select source_object_search.rowid
                from source_object_search_fts
                join source_object_search
                  on source_object_search.rowid = source_object_search_fts.rowid
                where source_object_search.book_id = ?
                  and source_object_search_fts match ?
                order by source_object_search.rowid
                """,
                (book_id, query),
            ).fetchall()
        )
        expected = tuple(
            row["rowid"]
            for row in connection.execute(
                """
                select rowid
                from temp.expected_source_object_search_fts
                where expected_source_object_search_fts match ?
                order by rowid
                """,
                (query,),
            ).fetchall()
        )
        if actual != expected:
            return False
    return True


def source_object_fts_vocabulary_matches_projection(
    connection: sqlite3.Connection,
    book_id: str,
) -> bool:
    connection.execute(
        """
        drop table if exists source_object_search_fts_vocab_check
        """
    )
    connection.execute(
        """
        create virtual table source_object_search_fts_vocab_check
        using fts5vocab(source_object_search_fts, 'instance')
        """
    )
    connection.execute(
        """
        create virtual table if not exists temp.expected_source_object_search_vocab
        using fts5vocab(expected_source_object_search_fts, 'instance')
        """
    )
    try:
        actual = tuple(
            row["term"]
            for row in connection.execute(
                """
                select distinct source_object_search_fts_vocab_check.term
                from source_object_search_fts_vocab_check
                join source_object_search
                  on source_object_search.rowid = source_object_search_fts_vocab_check.doc
                where source_object_search.book_id = ?
                order by source_object_search_fts_vocab_check.term
                """,
                (book_id,),
            ).fetchall()
        )
        expected = tuple(
            row["term"]
            for row in connection.execute(
                """
                select distinct term
                from temp.expected_source_object_search_vocab
                order by term
                """
            ).fetchall()
        )
        return actual == expected
    finally:
        connection.execute("drop table if exists source_object_search_fts_vocab_check")


def source_object_fts_validation_terms(rows: list[sqlite3.Row]) -> tuple[str, ...]:
    terms: list[str] = []
    for row in rows:
        for token in re.findall(
            r"(?u)\b\w+\b",
            " ".join(
                (
                    row["title"] or "",
                    row["heading_path"] or "",
                    row["object_type"] or "",
                    row["search_text"] or "",
                )
            ).casefold(),
        ):
            if len(token) >= 3 and token not in terms:
                terms.append(token)
    return tuple(terms)


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
        select status, object_count, extractor_version
        from book_object_status
        where book_id = ?
          and text_snapshot_sha256 = ?
          and status in ('extracted', 'indexed')
        """,
        (book_id, text_snapshot_sha256),
    ).fetchone()
    if row is None:
        return False
    if row["extractor_version"] != SOURCE_OBJECT_EXTRACTOR_VERSION:
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
        detach_retrieval_hits_for_source_object_replacement(
            connection,
            book_id=book_id,
        )
        connection.execute("delete from source_object_search where book_id = ?", (book_id,))
        connection.execute(
            """
            delete from source_object_links
            where from_object_id in (
              select id from source_objects where book_id = ?
            )
               or to_object_id in (
              select id from source_objects where book_id = ?
            )
            """,
            (book_id, book_id),
        )
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
                insert into source_object_search (
                  source_object_id,
                  book_id,
                  page_id,
                  object_type,
                  title,
                  heading_path,
                  page_start,
                  page_end,
                  confidence,
                  search_text
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_object.id,
                    source_object.book_id,
                    source_object.page_id,
                    source_object.object_type,
                    source_object.title,
                    " > ".join(source_object.heading_path),
                    source_object.page_start,
                    source_object.page_end,
                    source_object.confidence,
                    source_object.search_text,
                ),
            )
        write_derived_source_object_links(connection, source_objects, now=now)
        rebuild_source_object_fts_table(connection)
        connection.execute(
            """
            update book_object_status
            set status = 'indexed',
                object_count = ?,
                table_count = ?,
                stat_block_count = ?,
                location_count = ?,
                text_snapshot_sha256 = ?,
                extractor_version = ?,
                last_error = null,
                updated_at = ?
            where book_id = ?
            """,
            (
                len(source_objects),
                count_source_objects(source_objects, "table"),
                count_source_objects(source_objects, "stat_block"),
                count_source_objects(source_objects, "location_description"),
                text_snapshot_sha256,
                SOURCE_OBJECT_EXTRACTOR_VERSION,
                now,
                book_id,
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


def detach_retrieval_hits_for_source_object_replacement(
    connection: sqlite3.Connection,
    *,
    book_id: str,
) -> None:
    rows = connection.execute(
        """
        select
          retrieval_hits.id,
          retrieval_hits.retrieval_run_id,
          retrieval_hits.page_id,
          retrieval_hits.source_object_id,
          retrieval_hits.rank
        from retrieval_hits
        left join source_objects
          on source_objects.id = retrieval_hits.source_object_id
        where retrieval_hits.page_id in (
            select id from pages where book_id = ?
          )
          and (
            retrieval_hits.source_object_id is null
            or source_objects.book_id = ?
          )
        order by
          retrieval_hits.retrieval_run_id,
          retrieval_hits.page_id,
          case when retrieval_hits.source_object_id is null then 0 else 1 end,
          retrieval_hits.rank,
          retrieval_hits.id
        """,
        (book_id, book_id),
    ).fetchall()
    seen_fallback_keys: set[tuple[str, str]] = set()
    duplicate_hit_ids: list[str] = []
    for row in rows:
        key = (row["retrieval_run_id"], row["page_id"])
        if key in seen_fallback_keys:
            duplicate_hit_ids.append(row["id"])
            continue
        seen_fallback_keys.add(key)
    for hit_id in duplicate_hit_ids:
        connection.execute("delete from retrieval_hits where id = ?", (hit_id,))
    connection.execute(
        """
        update retrieval_hits
        set source_object_id = null
        where source_object_id in (
          select id from source_objects where book_id = ?
        )
        """,
        (book_id,),
    )


def write_derived_source_object_links(
    connection: sqlite3.Connection,
    source_objects: tuple[SourceObject, ...],
    *,
    now: str,
) -> None:
    objects_by_id = {source_object.id: source_object for source_object in source_objects}
    for source_object in source_objects:
        if source_object.parent_object_id is not None:
            parent = objects_by_id.get(source_object.parent_object_id)
            if parent is not None:
                parent_link_type = parent_link_type_for(source_object, parent)
                if parent_link_type is not None:
                    insert_source_object_link(
                        connection,
                        from_object_id=source_object.id,
                        to_object_id=parent.id,
                        to_book_id=parent.book_id,
                        to_page_id=parent.page_id,
                        link_type=parent_link_type,
                        label=parent.title,
                        confidence=min(source_object.confidence, parent.confidence),
                        evidence={
                            "derived_from": "parent_object_id",
                            "from_type": source_object.object_type,
                            "to_type": parent.object_type,
                        },
                        now=now,
                    )
            continue

        reference_link_type = reference_link_type_for(source_object.object_type)
        if reference_link_type is None:
            continue
        metadata = source_object_metadata(source_object)
        target_title = metadata.get("target_title")
        target_page = metadata.get("target_page")
        if not isinstance(target_title, str):
            continue
        target_page_number = target_page if isinstance(target_page, int) else None
        target = find_reference_target_object(
            source_objects,
            source_object=source_object,
            target_title=target_title,
            target_page=target_page_number,
        )
        target_page_id = (
            target.page_id
            if target is not None
            else target_page_id_for(
                connection,
                book_id=source_object.book_id,
                page_number=target_page_number,
            )
        )
        if target is None and target_page_id is None:
            continue
        insert_source_object_link(
            connection,
            from_object_id=source_object.id,
            to_object_id=target.id if target is not None else None,
            to_book_id=source_object.book_id,
            to_page_id=target_page_id,
            link_type=reference_link_type,
            label=target_title,
            confidence=source_object.confidence,
            evidence={
                "derived_from": "reference_metadata",
                "target_title": target_title,
                **(
                    {"target_page": target_page_number}
                    if target_page_number is not None
                    else {}
                ),
            },
            now=now,
        )


def parent_link_type_for(child: SourceObject, parent: SourceObject) -> str | None:
    if child.object_type == "table_row" and parent.object_type == "table":
        return "table_row"
    if child.object_type == "stat_block" and parent.object_type in {
        "npc_profile",
        "monster_profile",
    }:
        return "stat_profile"
    return "same_section"


def reference_link_type_for(object_type: str) -> str | None:
    if object_type == "index_entry":
        return "index_entry"
    if object_type == "glossary_entry":
        return "glossary_definition"
    if object_type == "cross_reference":
        return "cross_reference"
    return None


def source_object_metadata(source_object: SourceObject) -> dict[str, object]:
    try:
        parsed = json.loads(source_object.metadata_json or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def find_reference_target_object(
    source_objects: tuple[SourceObject, ...],
    *,
    source_object: SourceObject,
    target_title: str,
    target_page: int | None,
) -> SourceObject | None:
    normalized_title = " ".join(target_title.casefold().split())
    candidates = [
        candidate
        for candidate in source_objects
        if candidate.book_id == source_object.book_id
        and candidate.id != source_object.id
        and candidate.title is not None
        and " ".join(candidate.title.casefold().split()) == normalized_title
        and (
            target_page is None
            or candidate.page_start <= target_page <= candidate.page_end
        )
        and candidate.object_type
        not in {"index_entry", "glossary_entry", "cross_reference", "page_chunk"}
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda candidate: (
            candidate.page_start,
            -candidate.confidence,
            candidate.id,
        )
    )
    return candidates[0]


def target_page_id_for(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    page_number: int | None,
) -> str | None:
    if page_number is None:
        return None
    row = connection.execute(
        """
        select id
        from pages
        where book_id = ?
          and page_number = ?
        """,
        (book_id, page_number),
    ).fetchone()
    return None if row is None else str(row["id"])


def insert_source_object_link(
    connection: sqlite3.Connection,
    *,
    from_object_id: str,
    to_object_id: str | None,
    to_book_id: str | None,
    to_page_id: str | None,
    link_type: str,
    label: str | None,
    confidence: float,
    evidence: dict[str, object],
    now: str,
) -> None:
    connection.execute(
        """
        insert into source_object_links (
          id,
          from_object_id,
          to_object_id,
          to_book_id,
          to_page_id,
          link_type,
          label,
          confidence,
          evidence_json,
          created_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(id) do nothing
        """,
        (
            source_object_link_id(
                from_object_id=from_object_id,
                to_object_id=to_object_id,
                to_book_id=to_book_id,
                to_page_id=to_page_id,
                link_type=link_type,
            ),
            from_object_id,
            to_object_id,
            to_book_id,
            to_page_id,
            link_type,
            label,
            confidence,
            json.dumps(evidence, sort_keys=True),
            now,
        ),
    )


def source_object_link_id(
    *,
    from_object_id: str,
    to_object_id: str | None,
    to_book_id: str | None,
    to_page_id: str | None,
    link_type: str,
) -> str:
    digest = hashlib.sha256()
    for value in (from_object_id, to_object_id, to_book_id, to_page_id, link_type):
        digest.update((value or "").encode("utf-8"))
        digest.update(b"\0")
    return f"{from_object_id}:link:{link_type}:{digest.hexdigest()[:12]}"


def count_source_objects(
    source_objects: tuple[SourceObject, ...],
    object_type: str,
) -> int:
    return sum(1 for source_object in source_objects if source_object.object_type == object_type)


def rebuild_source_object_search(
    config: AppConfig,
    *,
    book_ids: tuple[str, ...] | None = None,
    force: bool = False,
    retry_running: bool = False,
    stale_running_minutes: int = 30,
) -> ObjectSearchRebuildSummary:
    if not config.db_path.exists():
        initialize_database(config.db_path).close()
    apply_pending_migrations(config.db_path)
    failures: list[ObjectSearchRebuildFailure] = []
    indexed = 0
    skipped_current = 0
    objects_written = 0
    with initialize_database(config.db_path) as connection:
        stale_recovered = recover_stale_source_object_search_jobs(
            connection,
            retry_running=retry_running,
            stale_running_minutes=stale_running_minutes,
        )
        books = source_object_search_book_ids(connection, book_ids=book_ids)
        for book_id in books:
            if not force and source_object_search_current(connection, book_id):
                skipped_current += 1
                continue

            snapshot = source_object_search_snapshot_sha256(connection, book_id)
            now = utc_timestamp()
            job_id = source_object_search_job_id(book_id, snapshot)
            if not claim_source_object_search_job(
                connection,
                book_id=book_id,
                source_object_snapshot=snapshot,
                force=force,
                now=now,
            ):
                if failure_reason := source_object_search_claim_failure(
                    connection,
                    book_id,
                ):
                    failures.append(ObjectSearchRebuildFailure(book_id, failure_reason))
                else:
                    skipped_current += 1
                continue
            try:
                written = write_source_object_search_projection(
                    connection,
                    book_id=book_id,
                    job_id=job_id,
                    now=utc_timestamp(),
                )
            except Exception as error:
                mark_source_object_search_failed(
                    connection,
                    book_id=book_id,
                    job_id=job_id,
                    error=str(error),
                    now=utc_timestamp(),
                )
                failures.append(ObjectSearchRebuildFailure(book_id, str(error)))
                continue
            indexed += 1
            objects_written += written

    return ObjectSearchRebuildSummary(
        discovered=len(books),
        indexed=indexed,
        skipped_current=skipped_current,
        stale_recovered=stale_recovered,
        failed=len(failures),
        objects_written=objects_written,
        failures=tuple(failures),
    )


def source_object_search_book_ids(
    connection: sqlite3.Connection,
    *,
    book_ids: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    sql = """
        select distinct source_objects.book_id
        from source_objects
        join books on books.id = source_objects.book_id
        where books.copy_status = 'copied'
          and books.text_status = 'imported'
          and books.search_status = 'indexed'
    """
    parameters: list[object] = []
    if book_ids is not None:
        if not book_ids:
            return ()
        placeholders = ",".join("?" for _ in book_ids)
        sql += f" and source_objects.book_id in ({placeholders})"
        parameters.extend(book_ids)
    sql += " order by source_objects.book_id"
    return tuple(row["book_id"] for row in connection.execute(sql, parameters).fetchall())


def recover_stale_source_object_search_jobs(
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
            where job_type = 'rebuild_source_object_fts'
              and status = 'running'
            """
        ).fetchall()
    else:
        rows = connection.execute(
            """
            select id, target_id
            from ingest_jobs
            where job_type = 'rebuild_source_object_fts'
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
                    last_error = 'Recovered stale source-object FTS rebuild job.',
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
                        last_error = 'Recovered stale source-object FTS rebuild job.',
                        updated_at = ?
                    where book_id = ?
                      and status = 'indexing'
                    """,
                    (now, row["target_id"]),
                )
    return len(rows)


def claim_source_object_search_job(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    source_object_snapshot: str,
    force: bool,
    now: str,
) -> bool:
    ensure_book_object_status(connection, book_id=book_id, now=now)
    status = connection.execute(
        "select status from book_object_status where book_id = ?",
        (book_id,),
    ).fetchone()
    if status is not None and status["status"] in {"extracting", "indexing"}:
        return False

    job_id = source_object_search_job_id(book_id, source_object_snapshot)
    with connection:
        status_cursor = connection.execute(
            """
            update book_object_status
            set status = 'indexing',
                last_error = null,
                updated_at = ?
            where book_id = ?
              and (
                ? = 1
                or status in ('not_started', 'failed', 'extracted', 'indexed')
              )
            """,
            (now, book_id, int(force)),
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
            values (?, 'rebuild_source_object_fts', ?, 'running', ?, 1, null, ?, ?, null)
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
                    last_error = 'Could not claim source-object FTS rebuild job.',
                    updated_at = ?
                where book_id = ?
                  and status = 'indexing'
                """,
                (now, book_id),
            )
            return False
    return True


def source_object_search_claim_failure(
    connection: sqlite3.Connection,
    book_id: str,
) -> str | None:
    row = connection.execute(
        """
        select status, last_error
        from book_object_status
        where book_id = ?
        """,
        (book_id,),
    ).fetchone()
    if row is None:
        return None
    if row["status"] == "failed" and row["last_error"]:
        return str(row["last_error"])
    return None


def write_source_object_search_projection(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    job_id: str,
    now: str,
) -> int:
    rows = connection.execute(
        """
        select
          id,
          book_id,
          page_id,
          object_type,
          title,
          heading_path_json,
          page_start,
          page_end,
          confidence,
          search_text,
          text_snapshot_sha256
        from source_objects
        where book_id = ?
        order by page_start, page_end, id
        """,
        (book_id,),
    ).fetchall()
    text_snapshot = common_text_snapshot(rows)
    with connection:
        connection.execute("delete from source_object_search where book_id = ?", (book_id,))
        for row in rows:
            connection.execute(
                """
                insert into source_object_search (
                  source_object_id,
                  book_id,
                  page_id,
                  object_type,
                  title,
                  heading_path,
                  page_start,
                  page_end,
                  confidence,
                  search_text
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["book_id"],
                    row["page_id"],
                    row["object_type"],
                    row["title"],
                    heading_path_text(row["heading_path_json"]),
                    row["page_start"],
                    row["page_end"],
                    row["confidence"],
                    row["search_text"],
                ),
            )
        rebuild_source_object_fts_table(connection)
        connection.execute(
            """
            update book_object_status
            set status = 'indexed',
                object_count = ?,
                table_count = ?,
                stat_block_count = ?,
                location_count = ?,
                text_snapshot_sha256 = ?,
                last_error = null,
                updated_at = ?
            where book_id = ?
            """,
            (
                len(rows),
                count_object_type(rows, "table"),
                count_object_type(rows, "stat_block"),
                count_object_type(rows, "location_description"),
                text_snapshot,
                now,
                book_id,
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
    return len(rows)


def common_text_snapshot(rows: tuple[sqlite3.Row, ...] | list[sqlite3.Row]) -> str | None:
    snapshots = {row["text_snapshot_sha256"] for row in rows}
    if len(snapshots) == 1:
        return str(next(iter(snapshots)))
    return None


def count_object_type(rows: tuple[sqlite3.Row, ...] | list[sqlite3.Row], object_type: str) -> int:
    return sum(1 for row in rows if row["object_type"] == object_type)


def mark_source_object_search_failed(
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


def rebuild_source_object_fts_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        "insert into source_object_search_fts(source_object_search_fts) values('rebuild')"
    )
