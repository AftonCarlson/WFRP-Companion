from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.db.migrations import apply_pending_migrations


CALIBRATION_SCHEMA_VERSION = 1
PAGE_LABEL_BUILDER_VERSION = "page-label-calibration-v1"


@dataclass(frozen=True)
class PageLabelAnchor:
    pdf_page_number: int
    printed_label: str


@dataclass(frozen=True)
class PageLabelBackfillFailure:
    book_id: str
    reason: str


@dataclass(frozen=True)
class PageLabelBackfillSummary:
    discovered: int
    calibrated: int
    needs_review: int
    skipped_current: int
    stale_recovered: int
    failed: int
    pages_calibrated: int
    manual_review_pages: int
    failures: tuple[PageLabelBackfillFailure, ...]


@dataclass(frozen=True)
class PageLabelCalibration:
    book_id: str
    status: str
    method: str
    calibration_json: str
    page_text_snapshot_sha256: str
    pages_calibrated: int
    manual_review_pages: int
    last_error: str | None


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def normalize_page_label(value: object) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    return normalized or None


def page_label_backfill_job_id(book_id: str, page_text_snapshot: str) -> str:
    return f"backfill_page_labels:{book_id}:{page_text_snapshot}:{PAGE_LABEL_BUILDER_VERSION}"


def page_label_snapshot_sha256(connection: sqlite3.Connection, book_id: str) -> str:
    digest = hashlib.sha256()
    book = connection.execute(
        """
        select id, title, page_count
        from books
        where id = ?
        """,
        (book_id,),
    ).fetchone()
    if book is not None:
        for value in ("book", book["id"], book["title"], str(book["page_count"])):
            digest.update(str(value).encode("utf-8"))
            digest.update(b"\0")
        digest.update(b"\n")
    rows = connection.execute(
        """
        select pages.page_number,
               pages.page_label,
               coalesce(page_text.text_sha256, '') as text_sha256
        from pages
        left join page_text on page_text.page_id = pages.id
        where pages.book_id = ?
        order by pages.page_number
        """,
        (book_id,),
    ).fetchall()
    for row in rows:
        for value in (
            str(row["page_number"]),
            normalize_page_label(row["page_label"]) or "",
            row["text_sha256"],
        ):
            digest.update(str(value).encode("utf-8"))
            digest.update(b"\0")
        digest.update(b"\n")
    return digest.hexdigest()


def backfill_page_labels(
    config: AppConfig,
    *,
    book_ids: tuple[str, ...] | None = None,
    anchors: Mapping[str, PageLabelAnchor] | None = None,
    force: bool = False,
    retry_running: bool = False,
    stale_running_minutes: int = 30,
) -> PageLabelBackfillSummary:
    if not config.db_path.exists():
        initialize_database(config.db_path).close()
    apply_pending_migrations(config.db_path)
    selected_anchors = dict(anchors or {})
    calibrated = 0
    needs_review = 0
    skipped_current = 0
    pages_calibrated = 0
    manual_review_pages = 0
    failures: list[PageLabelBackfillFailure] = []
    with initialize_database(config.db_path) as connection:
        stale_recovered = recover_stale_page_label_jobs(
            connection,
            retry_running=retry_running,
            stale_running_minutes=stale_running_minutes,
        )
        discovered_book_ids = eligible_books(connection, book_ids=book_ids)
        ensure_book_retrieval_status_rows(
            connection,
            discovered_book_ids,
            now=utc_timestamp(),
        )
        for book_id in discovered_book_ids:
            snapshot = page_label_snapshot_sha256(connection, book_id)
            explicit_anchor = selected_anchors.get(book_id)
            if not force and page_label_calibration_current(
                connection,
                book_id=book_id,
                page_text_snapshot=snapshot,
                anchor=explicit_anchor,
            ):
                skipped_current += 1
                continue
            anchor = explicit_anchor
            if anchor is None and not force:
                anchor = load_existing_page_label_anchor(connection, book_id)
            job_id = page_label_backfill_job_id(book_id, snapshot)
            now = utc_timestamp()
            if not claim_page_label_job(
                connection,
                book_id=book_id,
                page_text_snapshot=snapshot,
                job_id=job_id,
                force=force,
                now=now,
            ):
                reason = page_label_claim_failure(connection, book_id)
                if reason:
                    failures.append(PageLabelBackfillFailure(book_id, reason))
                else:
                    skipped_current += 1
                continue
            try:
                calibration = build_page_label_calibration(
                    connection,
                    book_id=book_id,
                    anchor=anchor,
                )
                persist_page_label_calibration(
                    connection,
                    calibration=calibration,
                    job_id=job_id,
                    now=utc_timestamp(),
                )
            except Exception as exc:  # noqa: BLE001
                reason = f"{type(exc).__name__}: {exc}"
                mark_page_label_failed(
                    connection,
                    book_id=book_id,
                    job_id=job_id,
                    error=reason,
                    now=utc_timestamp(),
                )
                failures.append(PageLabelBackfillFailure(book_id, reason))
                continue
            if calibration.status == "calibrated":
                calibrated += 1
            else:
                needs_review += 1
            pages_calibrated += calibration.pages_calibrated
            manual_review_pages += calibration.manual_review_pages
    return PageLabelBackfillSummary(
        discovered=len(discovered_book_ids),
        calibrated=calibrated,
        needs_review=needs_review,
        skipped_current=skipped_current,
        stale_recovered=stale_recovered,
        failed=len(failures),
        pages_calibrated=pages_calibrated,
        manual_review_pages=manual_review_pages,
        failures=tuple(failures),
    )


def eligible_books(
    connection: sqlite3.Connection,
    *,
    book_ids: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    sql = """
        select books.id
        from books
        where books.copy_status = 'copied'
          and books.text_status = 'imported'
          and exists (
            select 1 from pages where pages.book_id = books.id
          )
    """
    parameters: list[object] = []
    if book_ids is not None:
        if not book_ids:
            return ()
        placeholders = ",".join("?" for _ in book_ids)
        sql += f" and books.id in ({placeholders})"
        parameters.extend(book_ids)
    sql += " order by books.id"
    rows = connection.execute(sql, parameters).fetchall()
    return tuple(row["id"] for row in rows)


def ensure_book_retrieval_status_rows(
    connection: sqlite3.Connection,
    book_ids: tuple[str, ...],
    *,
    now: str,
) -> None:
    for book_id in book_ids:
        connection.execute(
            """
            insert into book_retrieval_status (book_id, updated_at)
            values (?, ?)
            on conflict(book_id) do nothing
            """,
            (book_id, now),
        )


def page_label_calibration_current(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    page_text_snapshot: str,
    anchor: PageLabelAnchor | None = None,
) -> bool:
    row = connection.execute(
        """
        select status, calibration_json, page_text_snapshot_sha256
        from book_page_label_calibrations
        where book_id = ?
        """,
        (book_id,),
    ).fetchone()
    if row is None:
        return False
    if row["status"] not in {"calibrated", "needs_review"}:
        return False
    if anchor is not None and row["status"] == "needs_review":
        return False
    if row["page_text_snapshot_sha256"] != page_text_snapshot:
        return False
    metadata = decode_calibration_json(row["calibration_json"])
    if metadata is None:
        return False
    if not calibration_anchor_matches(metadata, anchor):
        return False
    return (
        metadata.get("schema_version") == CALIBRATION_SCHEMA_VERSION
        and metadata.get("builder_version") == PAGE_LABEL_BUILDER_VERSION
        and metadata.get("page_count") == page_count(connection, book_id)
    )


def calibration_anchor_matches(
    metadata: dict[str, object],
    anchor: PageLabelAnchor | None,
) -> bool:
    metadata_anchor = metadata.get("anchor")
    if anchor is None:
        return True
    if not isinstance(metadata_anchor, dict):
        return False
    return (
        metadata_anchor.get("pdf_page_number") == anchor.pdf_page_number
        and metadata_anchor.get("printed_label") == anchor.printed_label
    )


def load_existing_page_label_anchor(
    connection: sqlite3.Connection,
    book_id: str,
) -> PageLabelAnchor | None:
    row = connection.execute(
        """
        select status, calibration_json
        from book_page_label_calibrations
        where book_id = ?
        """,
        (book_id,),
    ).fetchone()
    if row is None or row["status"] not in {"calibrated", "needs_review", "failed"}:
        return None
    metadata = decode_calibration_json(row["calibration_json"])
    if metadata is None:
        return None
    anchor = metadata.get("anchor")
    if not isinstance(anchor, dict):
        return None
    printed_label = normalize_page_label(anchor.get("printed_label"))
    if printed_label is None:
        return None
    try:
        pdf_page_number = int(anchor.get("pdf_page_number"))
    except (TypeError, ValueError):
        return None
    if pdf_page_number < 1:
        return None
    return PageLabelAnchor(
        pdf_page_number=pdf_page_number,
        printed_label=printed_label,
    )


def build_page_label_calibration(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    anchor: PageLabelAnchor | None,
) -> PageLabelCalibration:
    rows = connection.execute(
        """
        select page_number, page_label
        from pages
        where book_id = ?
        order by page_number
        """,
        (book_id,),
    ).fetchall()
    if not rows:
        raise ValueError(f"No imported pages found for {book_id}.")

    labels_by_page: dict[str, str] = {}
    missing_label_pages: list[int] = []
    conflicting_label_pages: list[dict[str, object]] = []
    generated_label_count = 0
    imported_label_count = 0
    anchor_start: int | None = None
    page_numbers = {int(row["page_number"]) for row in rows}
    if anchor is not None:
        if anchor.pdf_page_number not in page_numbers:
            raise ValueError(
                f"Anchor page {anchor.pdf_page_number} is not present for {book_id}."
            )
        try:
            anchor_start = int(anchor.printed_label)
        except ValueError as exc:
            raise ValueError("Offset anchor printed label must be an integer.") from exc

    for row in rows:
        page_number = int(row["page_number"])
        imported_label = normalize_page_label(row["page_label"])
        if anchor is not None and anchor_start is not None and page_number >= anchor.pdf_page_number:
            calibrated_label = str(anchor_start + page_number - anchor.pdf_page_number)
            labels_by_page[str(page_number)] = calibrated_label
            generated_label_count += 1
            if imported_label is not None and imported_label != calibrated_label:
                conflicting_label_pages.append(
                    {
                        "page_number": page_number,
                        "imported_label": imported_label,
                        "calibrated_label": calibrated_label,
                    }
                )
            continue
        if imported_label is not None:
            labels_by_page[str(page_number)] = imported_label
            imported_label_count += 1
        else:
            missing_label_pages.append(page_number)

    manual_review_numbers = {
        *missing_label_pages,
        *(int(item["page_number"]) for item in conflicting_label_pages),
    }
    needs_review = bool(manual_review_numbers)
    method = calibration_method(anchor=anchor, needs_review=needs_review)
    metadata = {
        "schema_version": CALIBRATION_SCHEMA_VERSION,
        "builder_version": PAGE_LABEL_BUILDER_VERSION,
        "method": method,
        "page_count": len(rows),
        "labels_by_page": labels_by_page,
        "missing_label_pages": missing_label_pages,
        "conflicting_label_pages": conflicting_label_pages,
        "imported_label_count": imported_label_count,
        "generated_label_count": generated_label_count,
        "anchor": None
        if anchor is None
        else {
            "pdf_page_number": anchor.pdf_page_number,
            "printed_label": anchor.printed_label,
        },
    }
    status = "needs_review" if needs_review else "calibrated"
    return PageLabelCalibration(
        book_id=book_id,
        status=status,
        method=method,
        calibration_json=json.dumps(metadata, sort_keys=True),
        page_text_snapshot_sha256=page_label_snapshot_sha256(connection, book_id),
        pages_calibrated=len(labels_by_page),
        manual_review_pages=len(manual_review_numbers),
        last_error=manual_review_error(len(manual_review_numbers))
        if needs_review
        else None,
    )


def calibration_method(*, anchor: PageLabelAnchor | None, needs_review: bool) -> str:
    if anchor is not None:
        return "offset_anchor_needs_review" if needs_review else "offset_anchor"
    return "imported_labels_partial" if needs_review else "imported_labels"


def manual_review_error(page_count_value: int) -> str:
    noun = "page label" if page_count_value == 1 else "page labels"
    verb = "needs" if page_count_value == 1 else "need"
    return f"{page_count_value} {noun} {verb} manual review."


def persist_page_label_calibration(
    connection: sqlite3.Connection,
    *,
    calibration: PageLabelCalibration,
    job_id: str,
    now: str,
) -> None:
    with connection:
        connection.execute(
            """
            insert into book_page_label_calibrations (
              book_id,
              status,
              method,
              calibration_json,
              page_text_snapshot_sha256,
              last_error,
              updated_at
            )
            values (?, ?, ?, ?, ?, ?, ?)
            on conflict(book_id) do update set
              status = excluded.status,
              method = excluded.method,
              calibration_json = excluded.calibration_json,
              page_text_snapshot_sha256 = excluded.page_text_snapshot_sha256,
              last_error = excluded.last_error,
              updated_at = excluded.updated_at
            """,
            (
                calibration.book_id,
                calibration.status,
                calibration.method,
                calibration.calibration_json,
                calibration.page_text_snapshot_sha256,
                calibration.last_error,
                now,
            ),
        )
        connection.execute(
            """
            update book_retrieval_status
            set page_label_status = ?,
                page_text_snapshot_sha256 = ?,
                last_error = ?,
                updated_at = ?
            where book_id = ?
            """,
            (
                calibration.status,
                calibration.page_text_snapshot_sha256,
                calibration.last_error,
                now,
                calibration.book_id,
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


def claim_page_label_job(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    page_text_snapshot: str,
    job_id: str,
    force: bool,
    now: str,
) -> bool:
    status = connection.execute(
        """
        select page_label_status
        from book_retrieval_status
        where book_id = ?
        """,
        (book_id,),
    ).fetchone()
    if status is not None and status["page_label_status"] == "calibrating":
        return False

    with connection:
        status_cursor = connection.execute(
            """
            update book_retrieval_status
            set page_label_status = 'calibrating',
                page_label_started_at = ?,
                page_text_snapshot_sha256 = ?,
                last_error = null,
                updated_at = ?
            where book_id = ?
              and (
                ? = 1
                or page_label_status in (
                  'not_started',
                  'calibrated',
                  'needs_review',
                  'failed'
                )
              )
            """,
            (now, page_text_snapshot, now, book_id, int(force)),
        )
        if status_cursor.rowcount != 1:
            return False
        connection.execute(
            """
            insert into book_page_label_calibrations (
              book_id,
              status,
              method,
              calibration_json,
              page_text_snapshot_sha256,
              last_error,
              updated_at
            )
            values (?, 'calibrating', 'pending', '{}', ?, null, ?)
            on conflict(book_id) do update set
              status = 'calibrating',
              method = 'pending',
              page_text_snapshot_sha256 = excluded.page_text_snapshot_sha256,
              last_error = null,
              updated_at = excluded.updated_at
            """,
            (book_id, page_text_snapshot, now),
        )
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
            values (?, 'backfill_page_labels', ?, 'running', ?, 1, null, ?, ?, null)
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
        if cursor.rowcount == 1:
            return True
        connection.execute(
            """
            update book_retrieval_status
            set page_label_status = 'failed',
                last_error = 'Could not claim page-label backfill job.',
                updated_at = ?
            where book_id = ?
            """,
            (now, book_id),
        )
        connection.execute(
            """
            update book_page_label_calibrations
            set status = 'failed',
                last_error = 'Could not claim page-label backfill job.',
                updated_at = ?
            where book_id = ?
            """,
            (now, book_id),
        )
    return False


def page_label_claim_failure(connection: sqlite3.Connection, book_id: str) -> str | None:
    row = connection.execute(
        """
        select page_label_status, last_error
        from book_retrieval_status
        where book_id = ?
        """,
        (book_id,),
    ).fetchone()
    if row is None:
        return None
    if row["page_label_status"] == "failed" and row["last_error"]:
        return str(row["last_error"])
    return None


def recover_stale_page_label_jobs(
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
            where job_type = 'backfill_page_labels'
              and status = 'running'
            """
        ).fetchall()
    else:
        rows = connection.execute(
            """
            select id, target_id
            from ingest_jobs
            where job_type = 'backfill_page_labels'
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
                    last_error = 'Recovered stale page-label backfill job.',
                    updated_at = ?
                where id = ?
                """,
                (now, row["id"]),
            )
            if row["target_id"] is None:
                continue
            connection.execute(
                """
                update book_retrieval_status
                set page_label_status = 'needs_review',
                    last_error = 'Recovered stale page-label backfill job.',
                    updated_at = ?
                where book_id = ?
                  and page_label_status = 'calibrating'
                """,
                (now, row["target_id"]),
            )
            connection.execute(
                """
                update book_page_label_calibrations
                set status = 'failed',
                    last_error = 'Recovered stale page-label backfill job.',
                    updated_at = ?
                where book_id = ?
                  and status = 'calibrating'
                """,
                (now, row["target_id"]),
            )
    return len(rows)


def mark_page_label_failed(
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
            set page_label_status = 'failed',
                last_error = ?,
                updated_at = ?
            where book_id = ?
            """,
            (error, now, book_id),
        )
        connection.execute(
            """
            update book_page_label_calibrations
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


def load_calibrated_page_label(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    page_number: int,
    fallback_label: str | None,
) -> str:
    labels = load_calibrated_page_labels(
        connection,
        book_id=book_id,
        page_numbers=(page_number,),
    )
    if labels.get(page_number):
        return labels[page_number]
    if fallback_label:
        return fallback_label
    row = connection.execute(
        """
        select page_label
        from pages
        where book_id = ?
          and page_number = ?
        """,
        (book_id, page_number),
    ).fetchone()
    if row is not None and normalize_page_label(row["page_label"]):
        return normalize_page_label(row["page_label"]) or str(page_number)
    return str(page_number)


def load_calibrated_printed_page_label(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    page_number: int,
    fallback_label: str | None,
) -> str | None:
    if page_label_needs_manual_review(
        connection,
        book_id=book_id,
        page_number=page_number,
    ):
        return None
    labels = load_calibrated_page_labels(
        connection,
        book_id=book_id,
        page_numbers=(page_number,),
    )
    if labels.get(page_number):
        return labels[page_number]
    if normalize_page_label(fallback_label):
        return normalize_page_label(fallback_label)
    row = connection.execute(
        """
        select page_label
        from pages
        where book_id = ?
          and page_number = ?
        """,
        (book_id, page_number),
    ).fetchone()
    if row is None:
        return None
    return normalize_page_label(row["page_label"])


def load_calibrated_printed_page_range_label(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    page_start: int,
    page_end: int,
) -> str | None:
    page_numbers = tuple(range(page_start, page_end + 1))
    if any(
        page_label_needs_manual_review(
            connection,
            book_id=book_id,
            page_number=page_number,
        )
        for page_number in page_numbers
    ):
        return None
    labels = load_calibrated_page_labels(
        connection,
        book_id=book_id,
        page_numbers=(page_start, page_end),
    )
    raw_labels = load_raw_page_labels(
        connection,
        book_id=book_id,
        page_numbers=(page_start, page_end),
    )
    start_label = labels.get(page_start) or raw_labels.get(page_start)
    end_label = labels.get(page_end) or raw_labels.get(page_end)
    if start_label is None or end_label is None:
        return None
    if page_start == page_end or start_label == end_label:
        return start_label
    return f"{start_label}-{end_label}"


def load_calibrated_page_range_label(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    page_start: int,
    page_end: int,
) -> str:
    rows = connection.execute(
        """
        select page_number, page_label
        from pages
        where book_id = ?
          and page_number in (?, ?)
        order by page_number
        """,
        (book_id, page_start, page_end),
    ).fetchall()
    fallback_labels = {
        int(row["page_number"]): normalize_page_label(row["page_label"])
        or str(row["page_number"])
        for row in rows
    }
    calibrated_labels = load_calibrated_page_labels(
        connection,
        book_id=book_id,
        page_numbers=(page_start, page_end),
    )
    start_label = (
        calibrated_labels.get(page_start)
        or fallback_labels.get(page_start)
        or str(page_start)
    )
    end_label = (
        calibrated_labels.get(page_end)
        or fallback_labels.get(page_end)
        or str(page_end)
    )
    if page_start == page_end or start_label == end_label:
        return start_label
    return f"{start_label}-{end_label}"


def load_calibrated_page_labels(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    page_numbers: tuple[int, ...],
) -> dict[int, str]:
    if not page_numbers:
        return {}
    metadata = load_current_page_label_calibration_metadata(connection, book_id)
    if metadata is None:
        return {}
    labels_by_page = metadata.get("labels_by_page")
    if not isinstance(labels_by_page, dict):
        return {}
    manual_review_pages = calibration_manual_review_page_numbers(metadata)
    labels: dict[int, str] = {}
    for page_number in page_numbers:
        if page_number in manual_review_pages:
            continue
        label = labels_by_page.get(str(page_number))
        normalized = normalize_page_label(label)
        if normalized is not None:
            labels[page_number] = normalized
    return labels


def load_current_page_label_calibration_metadata(
    connection: sqlite3.Connection,
    book_id: str,
) -> dict[str, object] | None:
    row = connection.execute(
        """
        select status, calibration_json, page_text_snapshot_sha256
        from book_page_label_calibrations
        where book_id = ?
        """,
        (book_id,),
    ).fetchone()
    if row is None:
        return None
    if row["status"] not in {"calibrated", "needs_review"}:
        return None
    if row["page_text_snapshot_sha256"] != page_label_snapshot_sha256(
        connection,
        book_id,
    ):
        return None
    return decode_calibration_json(row["calibration_json"])


def page_label_needs_manual_review(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    page_number: int,
) -> bool:
    row = connection.execute(
        """
        select status, calibration_json
        from book_page_label_calibrations
        where book_id = ?
        """,
        (book_id,),
    ).fetchone()
    if row is None or row["status"] != "needs_review":
        return False
    metadata = decode_calibration_json(row["calibration_json"])
    if metadata is None:
        return False
    return page_number in calibration_manual_review_page_numbers(metadata)


def calibration_manual_review_page_numbers(
    metadata: dict[str, object],
) -> set[int]:
    page_numbers: set[int] = set()
    missing_label_pages = metadata.get("missing_label_pages")
    if isinstance(missing_label_pages, list):
        for page_number in missing_label_pages:
            parsed_page_number = parse_positive_int(page_number)
            if parsed_page_number is not None:
                page_numbers.add(parsed_page_number)
    conflicting_label_pages = metadata.get("conflicting_label_pages")
    if isinstance(conflicting_label_pages, list):
        for item in conflicting_label_pages:
            if not isinstance(item, dict):
                continue
            parsed_page_number = parse_positive_int(item.get("page_number"))
            if parsed_page_number is not None:
                page_numbers.add(parsed_page_number)
    return page_numbers


def parse_positive_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def load_raw_page_labels(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    page_numbers: tuple[int, ...],
) -> dict[int, str]:
    if not page_numbers:
        return {}
    placeholders = ",".join("?" for _ in page_numbers)
    rows = connection.execute(
        f"""
        select page_number, page_label
        from pages
        where book_id = ?
          and page_number in ({placeholders})
        """,
        (book_id, *page_numbers),
    ).fetchall()
    labels: dict[int, str] = {}
    for row in rows:
        normalized = normalize_page_label(row["page_label"])
        if normalized is not None:
            labels[int(row["page_number"])] = normalized
    return labels


def decode_calibration_json(value: str | None) -> dict[str, object] | None:
    if not value:
        return None
    try:
        metadata = json.loads(value)
    except json.JSONDecodeError:
        return None
    return metadata if isinstance(metadata, dict) else None


def page_count(connection: sqlite3.Connection, book_id: str) -> int:
    return int(
        connection.execute(
            "select count(*) from pages where book_id = ?",
            (book_id,),
        ).fetchone()[0]
    )
