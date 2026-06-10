from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.db.migrations import apply_pending_migrations
from wfrp_companion.source_objects.layout import LayoutPage
from wfrp_companion.source_objects.layout import load_pdf_layout_pages
from wfrp_companion.source_objects.store import source_object_search_snapshot_sha256
from wfrp_companion.structured_evidence.candidates import (
    build_candidates_from_observations,
)
from wfrp_companion.structured_evidence.models import (
    StructuredEvidenceCandidate,
    deterministic_candidate_id,
    normalize_structured_alias,
    normalize_table_number,
)
from wfrp_companion.structured_evidence.readers import (
    ReaderObservation,
    known_table_numbers_from_observations,
    load_page_text_snapshots,
    load_source_object_link_snapshots,
    load_source_object_snapshots,
    layout_observations_from_pages,
    page_reference_observations_from_pages,
    reader_observations_from_source_objects,
)
from wfrp_companion.structured_evidence.payloads import (
    payload_hash,
    table_payload_search_text,
    validate_profile_bundle_payload,
    validate_structured_table_payload,
)


STRUCTURED_EXTRACTOR_VERSION = "structured-evidence-validation-v1"


@dataclass(frozen=True)
class EligibleStructuredBook:
    book_id: str


@dataclass(frozen=True)
class StructuredEvidenceExtractionFailure:
    book_id: str
    reason: str


@dataclass(frozen=True)
class StructuredEvidenceWriteResult:
    candidates_inserted: int
    needs_review_inserted: bool


@dataclass(frozen=True)
class StructuredEvidenceExtractionSummary:
    discovered: int
    extracted: int
    skipped_current: int
    stale_recovered: int
    failed: int
    observations_written: int
    candidates_written: int
    needs_review: int
    failures: tuple[StructuredEvidenceExtractionFailure, ...]


@dataclass(frozen=True)
class StructuredReviewSummary:
    candidates_total: int
    candidates_needs_review: int
    validated_active: int
    validated_stale: int
    validated_retired: int


@dataclass(frozen=True)
class StructuredCandidateListItem:
    id: str
    book_id: str
    book_title: str
    object_shape: str
    content_kind: str
    entity_kind: str
    canonical_name: str | None
    title: str | None
    table_number: str | None
    table_number_normalized: str | None
    page_start: int
    page_end: int
    printed_page_start: str | None
    printed_page_end: str | None
    confidence: float
    suspicious_flags: tuple[str, ...]
    status: str
    updated_at: str
    payload_json: None = None


@dataclass(frozen=True)
class StructuredObservationDetail:
    id: str
    reader_name: str
    reader_version: str
    observation_type: str
    object_shape: str | None
    content_kind: str | None
    entity_kind: str | None
    title: str | None
    table_number: str | None
    canonical_name: str | None
    page_number: int
    confidence: float
    text_hash: str | None


@dataclass(frozen=True)
class StructuredCandidateDetail:
    id: str
    book_id: str
    book_title: str
    primary_page_id: str
    primary_source_object_id: str | None
    object_shape: str
    content_kind: str
    entity_kind: str
    canonical_name: str | None
    title: str | None
    table_number: str | None
    table_number_normalized: str | None
    page_start: int
    page_end: int
    printed_page_start: str | None
    printed_page_end: str | None
    heading_path: tuple[str, ...]
    payload_json: dict[str, Any]
    confidence: float
    suspicious_flags: tuple[str, ...]
    status: str
    text_snapshot_sha256: str
    structured_extractor_version: str
    updated_at: str
    observations: tuple[StructuredObservationDetail, ...]


@dataclass(frozen=True)
class StructuredReviewResult:
    action: str
    candidate_id: str
    validated_object_id: str | None
    review_id: str
    source_snapshot_sha256: str | None


class StructuredEvidenceError(RuntimeError):
    """Base error for structured-evidence review operations."""


class StructuredEvidenceNotFoundError(StructuredEvidenceError):
    """Raised when a requested structured candidate does not exist."""


class StructuredEvidenceConflictError(StructuredEvidenceError):
    """Raised when candidate state does not allow the requested action."""


class StructuredEvidenceInvalidPayloadError(StructuredEvidenceError):
    """Raised when corrected structured payload JSON is invalid."""


class StructuredEvidenceStaleError(StructuredEvidenceError):
    """Raised when source snapshots changed after candidate extraction."""


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def structured_evidence_job_id(book_id: str, snapshot_sha256: str) -> str:
    return (
        f"extract_structured_evidence:{book_id}:"
        f"{snapshot_sha256}:{STRUCTURED_EXTRACTOR_VERSION}"
    )


def eligible_structured_books(
    connection: sqlite3.Connection,
    *,
    book_ids: tuple[str, ...] | None = None,
) -> tuple[EligibleStructuredBook, ...]:
    sql = """
        select books.id
        from books
        where books.copy_status = 'copied'
          and books.text_status = 'imported'
          and books.search_status = 'indexed'
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
        sql += f" and books.id in ({placeholders})"
        parameters.extend(book_ids)
    sql += " order by books.id"
    rows = connection.execute(sql, parameters).fetchall()
    return tuple(EligibleStructuredBook(book_id=row["id"]) for row in rows)


def structured_evidence_snapshot_sha256(
    connection: sqlite3.Connection,
    book_id: str,
) -> str:
    digest = hashlib.sha256()
    digest.update(STRUCTURED_EXTRACTOR_VERSION.encode("utf-8"))
    digest.update(b"\0")
    digest.update(source_object_search_snapshot_sha256(connection, book_id).encode("utf-8"))
    digest.update(b"\0")
    page_rows = connection.execute(
        """
        select pages.id, page_text.text_sha256
        from pages
        join page_text on page_text.page_id = pages.id
        where pages.book_id = ?
        order by pages.page_number, pages.id
        """,
        (book_id,),
    ).fetchall()
    for row in page_rows:
        digest.update(row["id"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(row["text_sha256"].encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def structured_evidence_current(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    snapshot_sha256: str,
) -> bool:
    row = connection.execute(
        """
        select structured_evidence_status, structured_evidence_snapshot_sha256
        from book_retrieval_status
        where book_id = ?
        """,
        (book_id,),
    ).fetchone()
    if row is None:
        return False
    if row["structured_evidence_snapshot_sha256"] != snapshot_sha256:
        return False
    return row["structured_evidence_status"] in {"indexed", "needs_review"}


def recover_stale_structured_evidence_jobs(
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
            where job_type = 'extract_structured_evidence'
              and status = 'running'
            """
        ).fetchall()
    else:
        rows = connection.execute(
            """
            select id, target_id
            from ingest_jobs
            where job_type = 'extract_structured_evidence'
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
                    last_error = 'Recovered stale structured-evidence extraction job.',
                    updated_at = ?
                where id = ?
                """,
                (now, row["id"]),
            )
            if row["target_id"]:
                connection.execute(
                    """
                    insert into book_retrieval_status (
                      book_id,
                      structured_evidence_status,
                      last_error,
                      updated_at
                    )
                    values (?, 'failed', ?, ?)
                    on conflict(book_id) do update set
                      structured_evidence_status = 'failed',
                      last_error = excluded.last_error,
                      updated_at = excluded.updated_at
                    """,
                    (
                        row["target_id"],
                        "Recovered stale structured-evidence extraction job.",
                        now,
                    ),
                )
    return len(rows)


def claim_structured_evidence_job(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    snapshot_sha256: str,
    force: bool,
    now: str,
) -> bool:
    ensure_book_retrieval_status(connection, book_id=book_id, now=now)
    row = connection.execute(
        """
        select structured_evidence_status
        from book_retrieval_status
        where book_id = ?
        """,
        (book_id,),
    ).fetchone()
    if row is not None and row["structured_evidence_status"] == "extracting":
        return False

    job_id = structured_evidence_job_id(book_id, snapshot_sha256)
    with connection:
        status_cursor = connection.execute(
            """
            update book_retrieval_status
            set structured_evidence_status = 'extracting',
                structured_evidence_snapshot_sha256 = ?,
                last_error = null,
                updated_at = ?
            where book_id = ?
              and (
                ? = 1
                or structured_evidence_status in (
                  'not_started',
                  'stale',
                  'failed',
                  'indexed',
                  'needs_review'
                )
              )
            """,
            (snapshot_sha256, now, book_id, int(force)),
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
            values (
              ?,
              'extract_structured_evidence',
              ?,
              'running',
              ?,
              1,
              null,
              ?,
              ?,
              null
            )
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
                set structured_evidence_status = 'failed',
                    last_error = 'Could not claim structured-evidence extraction job.',
                    updated_at = ?
                where book_id = ?
                  and structured_evidence_status = 'extracting'
                """,
                (now, book_id),
            )
            return False
    return True


def extract_structured_evidence_library(
    config: AppConfig,
    *,
    book_ids: tuple[str, ...] | None = None,
    force: bool = False,
    retry_running: bool = False,
    stale_running_minutes: int = 30,
) -> StructuredEvidenceExtractionSummary:
    if not config.db_path.exists():
        initialize_database(config.db_path).close()
    apply_pending_migrations(config.db_path)
    with initialize_database(config.db_path) as connection:
        stale_recovered = recover_stale_structured_evidence_jobs(
            connection,
            retry_running=retry_running,
            stale_running_minutes=stale_running_minutes,
        )
        books = eligible_structured_books(connection, book_ids=book_ids)
        extracted = 0
        skipped_current = 0
        observations_written = 0
        candidates_written = 0
        needs_review = 0
        failures: list[StructuredEvidenceExtractionFailure] = []

        for book in books:
            snapshot = structured_evidence_snapshot_sha256(connection, book.book_id)
            if (
                not force
                and structured_evidence_current(
                    connection,
                    book_id=book.book_id,
                    snapshot_sha256=snapshot,
                )
            ):
                skipped_current += 1
                continue

            now = utc_timestamp()
            if not claim_structured_evidence_job(
                connection,
                book_id=book.book_id,
                snapshot_sha256=snapshot,
                force=force,
                now=now,
            ):
                continue

            job_id = structured_evidence_job_id(book.book_id, snapshot)
            try:
                observations = build_reader_observations(connection, book.book_id)
                candidates = build_candidates_from_observations(observations)
                write_result = write_structured_evidence(
                    connection,
                    book_id=book.book_id,
                    snapshot_sha256=snapshot,
                    observations=observations,
                    candidates=candidates,
                    job_id=job_id,
                    now=utc_timestamp(),
                )
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
                mark_structured_evidence_failed(
                    connection,
                    book_id=book.book_id,
                    job_id=job_id,
                    error=error,
                    now=utc_timestamp(),
                )
                failures.append(
                    StructuredEvidenceExtractionFailure(book.book_id, error)
                )
                continue

            extracted += 1
            observations_written += len(observations)
            candidates_written += write_result.candidates_inserted
            if write_result.needs_review_inserted:
                needs_review += 1

    return StructuredEvidenceExtractionSummary(
        discovered=len(books),
        extracted=extracted,
        skipped_current=skipped_current,
        stale_recovered=stale_recovered,
        failed=len(failures),
        observations_written=observations_written,
        candidates_written=candidates_written,
        needs_review=needs_review,
        failures=tuple(failures),
    )


def build_reader_observations(
    connection: sqlite3.Connection,
    book_id: str,
) -> tuple[ReaderObservation, ...]:
    page_snapshots = load_page_text_snapshots(connection, book_id)
    source_observations = reader_observations_from_source_objects(
        load_source_object_snapshots(connection, book_id),
        links=load_source_object_link_snapshots(connection, book_id),
    )
    page_reference_observations = page_reference_observations_from_pages(
        page_snapshots,
        known_table_numbers=known_table_numbers_from_observations(source_observations),
    )
    layout_observations = layout_observations_from_pages(
        book_id=book_id,
        pages=page_snapshots,
        layout_pages=load_managed_pdf_layout_pages(connection, book_id),
    )
    return (*source_observations, *page_reference_observations, *layout_observations)


def load_managed_pdf_layout_pages(
    connection: sqlite3.Connection,
    book_id: str,
) -> tuple[LayoutPage, ...]:
    row = connection.execute(
        """
        select managed_pdf_path, page_count
        from books
        where id = ?
        """,
        (book_id,),
    ).fetchone()
    if row is None or not row["managed_pdf_path"]:
        return ()
    return load_pdf_layout_pages(
        Path(row["managed_pdf_path"]),
        page_count=int(row["page_count"] or 0),
    )


def write_structured_evidence(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    snapshot_sha256: str,
    observations: tuple[ReaderObservation, ...],
    candidates: tuple[StructuredEvidenceCandidate, ...],
    job_id: str,
    now: str,
) -> StructuredEvidenceWriteResult:
    with connection:
        stale_active_validated_objects(
            connection,
            book_id=book_id,
            current_snapshot_sha256=snapshot_sha256,
            now=now,
        )
        insertable_candidates = candidates_not_already_reviewed(
            connection,
            book_id=book_id,
            candidates=candidates_for_snapshot(candidates, snapshot_sha256),
        )
        preserved_observation_ids = reviewed_candidate_observation_ids(
            connection,
            book_id=book_id,
        )
        status = "needs_review" if any(
            candidate.status == "needs_review" for candidate in insertable_candidates
        ) else "indexed"
        connection.execute(
            """
            update structured_evidence_candidates
            set status = 'superseded',
                updated_at = ?
            where book_id = ?
              and status in ('candidate', 'needs_review', 'auto_rejected')
            """,
            (now, book_id),
        )
        delete_replaceable_reader_observations(
            connection,
            book_id=book_id,
            preserved_observation_ids=preserved_observation_ids,
        )
        for observation in observations:
            insert_reader_observation(connection, observation, now=now)
        for candidate in insertable_candidates:
            insert_structured_candidate(connection, candidate, now=now)
        connection.execute(
            """
            update book_retrieval_status
            set structured_evidence_status = ?,
                structured_evidence_snapshot_sha256 = ?,
                structured_evidence_started_at = coalesce(
                  structured_evidence_started_at,
                  ?
                ),
                last_error = null,
                updated_at = ?
            where book_id = ?
            """,
            (status, snapshot_sha256, now, now, book_id),
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
    return StructuredEvidenceWriteResult(
        candidates_inserted=len(insertable_candidates),
        needs_review_inserted=any(
            candidate.status == "needs_review" for candidate in insertable_candidates
        ),
    )


def candidates_not_already_reviewed(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    candidates: tuple[StructuredEvidenceCandidate, ...],
) -> tuple[StructuredEvidenceCandidate, ...]:
    reviewed_keys = reviewed_candidate_identity_keys(connection, book_id=book_id)
    return tuple(
        candidate
        for candidate in candidates
        if candidate_active_identity_key(candidate) not in reviewed_keys
    )


def reviewed_candidate_identity_keys(
    connection: sqlite3.Connection,
    *,
    book_id: str,
) -> frozenset[tuple[str, str, str, str, int, str, str]]:
    rows = connection.execute(
        """
        select
          book_id,
          object_shape,
          coalesce(table_number_normalized, '') as table_number_normalized,
          coalesce(canonical_name, '') as canonical_name,
          page_start,
          text_snapshot_sha256,
          structured_extractor_version
        from structured_evidence_candidates
        where book_id = ?
          and status in ('approved', 'corrected', 'rejected')
        """,
        (book_id,),
    ).fetchall()
    return frozenset(
        (
            row["book_id"],
            row["object_shape"],
            row["table_number_normalized"],
            row["canonical_name"],
            int(row["page_start"]),
            row["text_snapshot_sha256"],
            row["structured_extractor_version"],
        )
        for row in rows
    )


def reviewed_candidate_observation_ids(
    connection: sqlite3.Connection,
    *,
    book_id: str,
) -> tuple[str, ...]:
    rows = connection.execute(
        """
        select observation_ids_json
        from structured_evidence_candidates
        where book_id = ?
          and status in ('approved', 'corrected', 'rejected')
        """,
        (book_id,),
    ).fetchall()
    observation_ids: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for observation_id in _json_list(row["observation_ids_json"]):
            if not isinstance(observation_id, str) or not observation_id:
                continue
            if observation_id in seen:
                continue
            seen.add(observation_id)
            observation_ids.append(observation_id)
    return tuple(observation_ids)


def delete_replaceable_reader_observations(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    preserved_observation_ids: tuple[str, ...],
) -> None:
    if not preserved_observation_ids:
        connection.execute(
            "delete from structured_reader_observations where book_id = ?",
            (book_id,),
        )
        return
    placeholders = ",".join("?" for _ in preserved_observation_ids)
    connection.execute(
        f"""
        delete from structured_reader_observations
        where book_id = ?
          and id not in ({placeholders})
        """,
        (book_id, *preserved_observation_ids),
    )


def candidate_active_identity_key(
    candidate: StructuredEvidenceCandidate,
) -> tuple[str, str, str, str, int, str, str]:
    return (
        candidate.book_id,
        str(candidate.object_shape),
        candidate.table_number_normalized or "",
        candidate.canonical_name or "",
        candidate.page_start,
        candidate.text_snapshot_sha256,
        candidate.structured_extractor_version,
    )


def candidates_for_snapshot(
    candidates: tuple[StructuredEvidenceCandidate, ...],
    snapshot_sha256: str,
) -> tuple[StructuredEvidenceCandidate, ...]:
    return tuple(
        candidate_for_snapshot(candidate, snapshot_sha256)
        for candidate in candidates
    )


def candidate_for_snapshot(
    candidate: StructuredEvidenceCandidate,
    snapshot_sha256: str,
) -> StructuredEvidenceCandidate:
    payload = json.loads(stable_json(candidate.payload_json))
    source = payload.get("source")
    if isinstance(source, dict):
        source["text_snapshot_sha256"] = snapshot_sha256
    identity = (
        candidate.table_number_normalized
        or candidate.table_number
        or candidate.canonical_name
        or candidate.title
        or candidate.id
    )
    return replace(
        candidate,
        id=deterministic_candidate_id(
            book_id=candidate.book_id,
            object_shape=str(candidate.object_shape),
            identity=identity,
            page_start=candidate.page_start,
            page_end=candidate.page_end,
            snapshot_sha256=snapshot_sha256,
            extractor_version=candidate.structured_extractor_version,
        ),
        payload_json=payload,
        text_snapshot_sha256=snapshot_sha256,
    )


def stale_active_validated_objects(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    current_snapshot_sha256: str,
    now: str,
) -> None:
    connection.execute(
        """
        update validated_structured_objects
        set validation_status = 'stale',
            updated_at = ?
        where book_id = ?
          and validation_status = 'active'
          and source_snapshot_sha256 != ?
        """,
        (now, book_id, current_snapshot_sha256),
    )


def ensure_book_retrieval_status(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    now: str,
) -> None:
    connection.execute(
        """
        insert into book_retrieval_status (
          book_id,
          structured_evidence_status,
          updated_at
        )
        values (?, 'not_started', ?)
        on conflict(book_id) do nothing
        """,
        (book_id, now),
    )


def insert_reader_observation(
    connection: sqlite3.Connection,
    observation: ReaderObservation,
    *,
    now: str,
) -> None:
    connection.execute(
        """
        insert or ignore into structured_reader_observations (
          id,
          book_id,
          page_id,
          source_object_id,
          reader_name,
          reader_version,
          observation_type,
          object_shape,
          content_kind,
          entity_kind,
          title,
          table_number,
          canonical_name,
          page_number,
          char_start,
          char_end,
          bbox_json,
          payload_json,
          text_hash,
          text_snapshot_sha256,
          confidence,
          created_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            observation.id,
            observation.book_id,
            observation.page_id,
            observation.source_object_id,
            observation.reader_name,
            observation.reader_version,
            observation.observation_type,
            observation.object_shape,
            observation.content_kind,
            observation.entity_kind,
            observation.title,
            observation.table_number,
            observation.canonical_name,
            observation.page_number,
            observation.char_start,
            observation.char_end,
            observation.bbox_json,
            stable_json(observation.payload_json),
            observation.text_hash,
            observation.text_snapshot_sha256,
            observation.confidence,
            now,
        ),
    )


def insert_structured_candidate(
    connection: sqlite3.Connection,
    candidate: StructuredEvidenceCandidate,
    *,
    now: str,
) -> None:
    connection.execute(
        """
        insert into structured_evidence_candidates (
          id,
          book_id,
          primary_page_id,
          primary_source_object_id,
          object_shape,
          content_kind,
          entity_kind,
          canonical_name,
          title,
          table_number,
          table_number_normalized,
          page_start,
          page_end,
          printed_page_start,
          printed_page_end,
          heading_path_json,
          observation_ids_json,
          source_object_ids_json,
          payload_json,
          search_text,
          confidence,
          suspicious_flags_json,
          status,
          text_snapshot_sha256,
          structured_extractor_version,
          created_at,
          updated_at
        )
        values (
          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
          ?, ?
        )
        on conflict(id) do update set
          primary_page_id = excluded.primary_page_id,
          primary_source_object_id = excluded.primary_source_object_id,
          object_shape = excluded.object_shape,
          content_kind = excluded.content_kind,
          entity_kind = excluded.entity_kind,
          canonical_name = excluded.canonical_name,
          title = excluded.title,
          table_number = excluded.table_number,
          table_number_normalized = excluded.table_number_normalized,
          page_start = excluded.page_start,
          page_end = excluded.page_end,
          printed_page_start = excluded.printed_page_start,
          printed_page_end = excluded.printed_page_end,
          heading_path_json = excluded.heading_path_json,
          observation_ids_json = excluded.observation_ids_json,
          source_object_ids_json = excluded.source_object_ids_json,
          payload_json = excluded.payload_json,
          search_text = excluded.search_text,
          confidence = excluded.confidence,
          suspicious_flags_json = excluded.suspicious_flags_json,
          status = excluded.status,
          text_snapshot_sha256 = excluded.text_snapshot_sha256,
          structured_extractor_version = excluded.structured_extractor_version,
          updated_at = excluded.updated_at
        where structured_evidence_candidates.status in (
          'candidate',
          'needs_review',
          'auto_rejected',
          'superseded'
        )
        """,
        (
            candidate.id,
            candidate.book_id,
            candidate.primary_page_id,
            candidate.primary_source_object_id,
            candidate.object_shape,
            candidate.content_kind,
            candidate.entity_kind,
            candidate.canonical_name,
            candidate.title,
            candidate.table_number,
            candidate.table_number_normalized,
            candidate.page_start,
            candidate.page_end,
            candidate.printed_page_start,
            candidate.printed_page_end,
            stable_json(list(candidate.heading_path)),
            stable_json(list(candidate.observation_ids)),
            stable_json(list(candidate.source_object_ids)),
            stable_json(candidate.payload_json),
            candidate.search_text,
            candidate.confidence,
            stable_json(list(candidate.suspicious_flags)),
            candidate.status,
            candidate.text_snapshot_sha256,
            candidate.structured_extractor_version,
            now,
            now,
        ),
    )


def mark_structured_evidence_failed(
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
            set structured_evidence_status = 'failed',
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


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def structured_review_summary(config: AppConfig) -> StructuredReviewSummary:
    apply_pending_migrations(config.db_path)
    with initialize_database(config.db_path) as connection:
        candidate_counts = {
            row["status"]: row["count"]
            for row in connection.execute(
                """
                select status, count(*) as count
                from structured_evidence_candidates
                group by status
                """
            ).fetchall()
        }
        validated_counts = {
            row["validation_status"]: row["count"]
            for row in connection.execute(
                """
                select validation_status, count(*) as count
                from validated_structured_objects
                group by validation_status
                """
            ).fetchall()
        }
    return StructuredReviewSummary(
        candidates_total=sum(candidate_counts.values()),
        candidates_needs_review=candidate_counts.get("needs_review", 0),
        validated_active=validated_counts.get("active", 0),
        validated_stale=validated_counts.get("stale", 0),
        validated_retired=validated_counts.get("retired", 0),
    )


def list_structured_candidates(
    config: AppConfig,
    *,
    status: str | None = None,
    limit: int = 50,
) -> tuple[StructuredCandidateListItem, ...]:
    apply_pending_migrations(config.db_path)
    sql = """
        select
          structured_evidence_candidates.*,
          books.title as book_title
        from structured_evidence_candidates
        join books on books.id = structured_evidence_candidates.book_id
    """
    parameters: list[object] = []
    if status is not None:
        sql += " where structured_evidence_candidates.status = ?"
        parameters.append(status)
    sql += " order by structured_evidence_candidates.updated_at desc"
    sql += " limit ?"
    parameters.append(limit)
    with initialize_database(config.db_path) as connection:
        rows = connection.execute(sql, parameters).fetchall()
    return tuple(_candidate_list_item_from_row(row) for row in rows)


def get_structured_candidate_detail(
    config: AppConfig,
    candidate_id: str,
) -> StructuredCandidateDetail:
    apply_pending_migrations(config.db_path)
    with initialize_database(config.db_path) as connection:
        row = load_candidate_row(connection, candidate_id)
        if row is None:
            raise StructuredEvidenceNotFoundError(
                f"Structured evidence candidate not found: {candidate_id}"
            )
        observations = load_candidate_observation_details(connection, row)
    return _candidate_detail_from_row(row, observations)


def approve_structured_candidate(
    config: AppConfig,
    candidate_id: str,
    *,
    reviewer: str | None = None,
    notes: str | None = None,
) -> StructuredReviewResult:
    apply_pending_migrations(config.db_path)
    with initialize_database(config.db_path) as connection:
        row = require_reviewable_candidate(connection, candidate_id)
        source_snapshot = require_current_structured_snapshot(connection, row)
        payload = _payload_from_row(row)
        return promote_candidate(
            connection,
            row=row,
            payload=payload,
            action="approve",
            review_state="human_approved",
            reviewer=reviewer,
            notes=notes,
            patch={},
            source_snapshot=source_snapshot,
        )


def correct_structured_candidate(
    config: AppConfig,
    candidate_id: str,
    payload: Mapping[str, Any],
    *,
    reviewer: str | None = None,
    notes: str | None = None,
) -> StructuredReviewResult:
    apply_pending_migrations(config.db_path)
    with initialize_database(config.db_path) as connection:
        row = require_reviewable_candidate(connection, candidate_id)
        source_snapshot = require_current_structured_snapshot(connection, row)
        corrected_payload = validate_payload_for_shape(
            row["object_shape"],
            payload,
        )
        return promote_candidate(
            connection,
            row=row,
            payload=corrected_payload,
            action="correct",
            review_state="human_corrected",
            reviewer=reviewer,
            notes=notes,
            patch={"payload_json": corrected_payload},
            source_snapshot=source_snapshot,
        )


def reject_structured_candidate(
    config: AppConfig,
    candidate_id: str,
    *,
    reviewer: str | None = None,
    notes: str | None = None,
) -> StructuredReviewResult:
    apply_pending_migrations(config.db_path)
    with initialize_database(config.db_path) as connection:
        row = load_candidate_row(connection, candidate_id)
        if row is None:
            raise StructuredEvidenceNotFoundError(
                f"Structured evidence candidate not found: {candidate_id}"
            )
        if row["status"] not in {"candidate", "needs_review"}:
            raise StructuredEvidenceConflictError(
                f"Candidate {candidate_id} cannot be rejected from {row['status']}"
            )
        now = utc_timestamp()
        review_id = new_review_id(candidate_id, "reject")
        before_hash = payload_hash(_payload_from_row(row))
        with connection:
            connection.execute(
                """
                update structured_evidence_candidates
                set status = 'rejected',
                    updated_at = ?
                where id = ?
                """,
                (now, candidate_id),
            )
            insert_review_event(
                connection,
                review_id=review_id,
                candidate_id=candidate_id,
                validated_object_id=None,
                action="reject",
                reviewer=reviewer,
                notes=notes,
                patch={},
                prior_payload_hash=before_hash,
                after_payload_hash=before_hash,
                now=now,
            )
            update_last_review_timestamp(connection, row["book_id"], now)
    return StructuredReviewResult(
        action="reject",
        candidate_id=candidate_id,
        validated_object_id=None,
        review_id=review_id,
        source_snapshot_sha256=None,
    )


def promote_candidate(
    connection: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    payload: Mapping[str, Any],
    action: str,
    review_state: str,
    reviewer: str | None,
    notes: str | None,
    patch: Mapping[str, Any],
    source_snapshot: str,
) -> StructuredReviewResult:
    now = utc_timestamp()
    candidate_id = row["id"]
    review_id = new_review_id(candidate_id, action)
    validated_object_id = new_validated_object_id(row, review_id)
    previous_payload = _payload_from_row(row)
    prior_hash = payload_hash(previous_payload)
    after_hash = payload_hash(payload)
    identity = structured_payload_identity(row, payload)
    search_text = structured_payload_search_text(row["object_shape"], payload)

    with connection:
        retire_conflicting_active_objects(
            connection,
            row=row,
            identity=identity,
            now=now,
        )
        connection.execute(
            """
            update structured_evidence_candidates
            set status = ?,
                payload_json = ?,
                search_text = ?,
                updated_at = ?
            where id = ?
            """,
            (
                "approved" if action == "approve" else "corrected",
                stable_json(payload),
                search_text,
                now,
                candidate_id,
            ),
        )
        insert_validated_object(
            connection,
            row=row,
            payload=payload,
            identity=identity,
            validated_object_id=validated_object_id,
            review_state=review_state,
            source_snapshot=source_snapshot,
            now=now,
        )
        insert_validated_sources(
            connection,
            row=row,
            validated_object_id=validated_object_id,
            source_snapshot=source_snapshot,
            now=now,
        )
        insert_validated_aliases(
            connection,
            row=row,
            payload=payload,
            validated_object_id=validated_object_id,
            identity=identity,
            now=now,
        )
        insert_review_event(
            connection,
            review_id=review_id,
            candidate_id=candidate_id,
            validated_object_id=validated_object_id,
            action=action,
            reviewer=reviewer,
            notes=notes,
            patch=patch,
            prior_payload_hash=prior_hash,
            after_payload_hash=after_hash,
            now=now,
        )
        update_last_review_timestamp(connection, row["book_id"], now)

    return StructuredReviewResult(
        action=action,
        candidate_id=candidate_id,
        validated_object_id=validated_object_id,
        review_id=review_id,
        source_snapshot_sha256=source_snapshot,
    )


def load_candidate_row(
    connection: sqlite3.Connection,
    candidate_id: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        select
          structured_evidence_candidates.*,
          books.title as book_title
        from structured_evidence_candidates
        join books on books.id = structured_evidence_candidates.book_id
        where structured_evidence_candidates.id = ?
        """,
        (candidate_id,),
    ).fetchone()


def require_reviewable_candidate(
    connection: sqlite3.Connection,
    candidate_id: str,
) -> sqlite3.Row:
    row = load_candidate_row(connection, candidate_id)
    if row is None:
        raise StructuredEvidenceNotFoundError(
            f"Structured evidence candidate not found: {candidate_id}"
        )
    if row["status"] not in {"candidate", "needs_review"}:
        raise StructuredEvidenceConflictError(
            f"Candidate {candidate_id} cannot be reviewed from {row['status']}"
        )
    return row


def require_current_structured_snapshot(
    connection: sqlite3.Connection,
    candidate: sqlite3.Row,
) -> str:
    current_snapshot = structured_evidence_snapshot_sha256(
        connection,
        candidate["book_id"],
    )
    status = connection.execute(
        """
        select structured_evidence_snapshot_sha256
        from book_retrieval_status
        where book_id = ?
        """,
        (candidate["book_id"],),
    ).fetchone()
    recorded_snapshot = None if status is None else status[
        "structured_evidence_snapshot_sha256"
    ]
    if recorded_snapshot != current_snapshot:
        raise StructuredEvidenceStaleError(
            f"Structured evidence candidate is stale for book {candidate['book_id']}"
        )
    return current_snapshot


def load_candidate_observation_details(
    connection: sqlite3.Connection,
    candidate: sqlite3.Row,
) -> tuple[StructuredObservationDetail, ...]:
    observation_ids = tuple(_json_list(candidate["observation_ids_json"]))
    if not observation_ids:
        return ()
    placeholders = ",".join("?" for _ in observation_ids)
    rows = connection.execute(
        f"""
        select
          id,
          reader_name,
          reader_version,
          observation_type,
          object_shape,
          content_kind,
          entity_kind,
          title,
          table_number,
          canonical_name,
          page_number,
          confidence,
          text_hash
        from structured_reader_observations
        where id in ({placeholders})
        order by page_number, id
        """,
        observation_ids,
    ).fetchall()
    return tuple(
        StructuredObservationDetail(
            id=row["id"],
            reader_name=row["reader_name"],
            reader_version=row["reader_version"],
            observation_type=row["observation_type"],
            object_shape=row["object_shape"],
            content_kind=row["content_kind"],
            entity_kind=row["entity_kind"],
            title=row["title"],
            table_number=row["table_number"],
            canonical_name=row["canonical_name"],
            page_number=row["page_number"],
            confidence=row["confidence"],
            text_hash=row["text_hash"],
        )
        for row in rows
    )


def validate_payload_for_shape(
    object_shape: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        if object_shape == "structured_table":
            return validate_structured_table_payload(payload)
        if object_shape == "profile_bundle":
            return validate_profile_bundle_payload(payload)
    except ValueError as error:
        raise StructuredEvidenceInvalidPayloadError(str(error)) from error
    raise StructuredEvidenceInvalidPayloadError(
        f"Unsupported structured object shape: {object_shape}"
    )


def structured_payload_identity(
    row: sqlite3.Row,
    payload: Mapping[str, Any],
) -> dict[str, str | None]:
    if row["object_shape"] == "structured_table":
        identity = _mapping(payload.get("identity"))
        table_number = _optional_text(identity.get("table_number_raw")) or row[
            "table_number"
        ]
        table_number_normalized = (
            _optional_text(identity.get("table_number_normalized"))
            or normalize_table_number(table_number or "")
            or row["table_number_normalized"]
        )
        title = _optional_text(identity.get("title_raw")) or row["title"]
        canonical_name = None
    else:
        identity = _mapping(payload.get("identity"))
        title = _optional_text(identity.get("name_raw")) or row["title"]
        canonical_name = (
            _optional_text(identity.get("name_normalized"))
            or normalize_structured_alias(title or "")
            or row["canonical_name"]
        )
        table_number = None
        table_number_normalized = None
    return {
        "title": title,
        "canonical_name": canonical_name,
        "table_number": table_number,
        "table_number_normalized": table_number_normalized,
    }


def structured_payload_search_text(
    object_shape: str,
    payload: Mapping[str, Any],
) -> str:
    if object_shape == "structured_table":
        return table_payload_search_text(payload)
    identity = _mapping(payload.get("identity"))
    profile = _mapping(payload.get("profile"))
    parts: list[str] = []
    for key in ("name_raw", "name_normalized"):
        value = identity.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    aliases = identity.get("aliases")
    if isinstance(aliases, list):
        parts.extend(alias for alias in aliases if isinstance(alias, str))
    for key in (
        "description",
        "skills",
        "talents",
        "traits",
        "special_rules",
        "weapons",
        "armour",
        "trappings",
        "notes",
    ):
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(item for item in value if isinstance(item, str))
    return " ".join(parts)


def retire_conflicting_active_objects(
    connection: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    identity: Mapping[str, str | None],
    now: str,
) -> None:
    if row["object_shape"] == "structured_table":
        connection.execute(
            """
            update validated_structured_objects
            set validation_status = 'retired',
                updated_at = ?
            where book_id = ?
              and object_shape = 'structured_table'
              and table_number_normalized = ?
              and validation_status = 'active'
            """,
            (now, row["book_id"], identity["table_number_normalized"]),
        )
        return
    connection.execute(
        """
        update validated_structured_objects
        set validation_status = 'retired',
            updated_at = ?
        where book_id = ?
          and object_shape = 'profile_bundle'
          and canonical_name = ?
          and entity_kind = ?
          and validation_status = 'active'
        """,
        (now, row["book_id"], identity["canonical_name"], row["entity_kind"]),
    )


def insert_validated_object(
    connection: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    payload: Mapping[str, Any],
    identity: Mapping[str, str | None],
    validated_object_id: str,
    review_state: str,
    source_snapshot: str,
    now: str,
) -> None:
    connection.execute(
        """
        insert into validated_structured_objects (
          id,
          candidate_id,
          book_id,
          primary_page_id,
          primary_source_object_id,
          object_shape,
          content_kind,
          entity_kind,
          canonical_name,
          title,
          table_number,
          table_number_normalized,
          page_start,
          page_end,
          printed_page_start,
          printed_page_end,
          heading_path_json,
          payload_schema_version,
          payload_json,
          field_confidence_json,
          source_snapshot_sha256,
          validation_status,
          review_state,
          created_at,
          updated_at,
          reviewed_at
        )
        values (
          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active',
          ?, ?, ?, ?
        )
        """,
        (
            validated_object_id,
            row["id"],
            row["book_id"],
            row["primary_page_id"],
            row["primary_source_object_id"],
            row["object_shape"],
            row["content_kind"],
            row["entity_kind"],
            identity["canonical_name"],
            identity["title"],
            identity["table_number"],
            identity["table_number_normalized"],
            row["page_start"],
            row["page_end"],
            row["printed_page_start"],
            row["printed_page_end"],
            row["heading_path_json"],
            int(payload.get("schema_version", 1)),
            stable_json(payload),
            stable_json(field_confidence_from_payload(row["object_shape"], payload)),
            source_snapshot,
            review_state,
            now,
            now,
            now,
        ),
    )


def insert_validated_sources(
    connection: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    validated_object_id: str,
    source_snapshot: str,
    now: str,
) -> None:
    source_ids = tuple(_json_list(row["source_object_ids_json"]))
    if not source_ids:
        insert_validated_source(
            connection,
            validated_object_id=validated_object_id,
            anchor_kind="page",
            source_object_id=None,
            page_id=row["primary_page_id"],
            source_role="fallback_page",
            source_snapshot=source_snapshot,
            confidence=row["confidence"],
            now=now,
        )
        return
    source_types = load_source_object_types(connection, source_ids)
    for index, source_object_id in enumerate(source_ids):
        source_role = source_role_for(
            row["object_shape"],
            source_types.get(source_object_id),
            is_primary=source_object_id == row["primary_source_object_id"]
            or index == 0,
        )
        insert_validated_source(
            connection,
            validated_object_id=validated_object_id,
            anchor_kind="source_object",
            source_object_id=source_object_id,
            page_id=None,
            source_role=source_role,
            source_snapshot=source_snapshot,
            confidence=row["confidence"],
            now=now,
        )


def insert_validated_source(
    connection: sqlite3.Connection,
    *,
    validated_object_id: str,
    anchor_kind: str,
    source_object_id: str | None,
    page_id: str | None,
    source_role: str,
    source_snapshot: str,
    confidence: float,
    now: str,
) -> None:
    source_identity = source_object_id or page_id or "manual"
    source_id = short_hash(
        "|".join((validated_object_id, anchor_kind, source_role, source_identity))
    )
    connection.execute(
        """
        insert into validated_structured_object_sources (
          id,
          validated_object_id,
          anchor_kind,
          source_object_id,
          page_id,
          source_role,
          source_snapshot_sha256,
          confidence,
          created_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"validated-source:{source_id}",
            validated_object_id,
            anchor_kind,
            source_object_id,
            page_id,
            source_role,
            source_snapshot,
            confidence,
            now,
        ),
    )


def insert_validated_aliases(
    connection: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    payload: Mapping[str, Any],
    validated_object_id: str,
    identity: Mapping[str, str | None],
    now: str,
) -> None:
    aliases = aliases_for_payload(row, payload, identity)
    for alias, alias_source, confidence in aliases:
        alias_normalized = normalize_structured_alias(alias)
        if not alias_normalized:
            continue
        connection.execute(
            """
            insert into validated_structured_object_aliases (
              validated_object_id,
              book_id,
              alias,
              alias_normalized,
              alias_source,
              confidence,
              created_at
            )
            values (?, ?, ?, ?, ?, ?, ?)
            on conflict(validated_object_id, alias_normalized) do nothing
            """,
            (
                validated_object_id,
                row["book_id"],
                alias,
                alias_normalized,
                alias_source,
                confidence,
                now,
            ),
        )


def aliases_for_payload(
    row: sqlite3.Row,
    payload: Mapping[str, Any],
    identity: Mapping[str, str | None],
) -> tuple[tuple[str, str, float], ...]:
    aliases: list[tuple[str, str, float]] = []
    payload_identity = _mapping(payload.get("identity"))
    if row["object_shape"] == "structured_table":
        table_number = identity["table_number_normalized"]
        if table_number:
            aliases.append((f"table {table_number}", "table_number", 1.0))
        title = identity["title"]
        if title:
            aliases.append((title, "title", 0.95))
            aliases.append((f"{title} table", "generated_word_order", 0.85))
    else:
        canonical_name = identity["canonical_name"]
        if canonical_name:
            aliases.append((canonical_name, "canonical", 1.0))
        title = identity["title"]
        if title:
            aliases.append((title, "title", 0.95))
    raw_aliases = payload_identity.get("aliases")
    if isinstance(raw_aliases, Sequence) and not isinstance(raw_aliases, str):
        aliases.extend(
            (alias, "manual", 0.9)
            for alias in raw_aliases
            if isinstance(alias, str) and alias.strip()
        )
    return tuple(aliases)


def insert_review_event(
    connection: sqlite3.Connection,
    *,
    review_id: str,
    candidate_id: str | None,
    validated_object_id: str | None,
    action: str,
    reviewer: str | None,
    notes: str | None,
    patch: Mapping[str, Any],
    prior_payload_hash: str | None,
    after_payload_hash: str | None,
    now: str,
) -> None:
    connection.execute(
        """
        insert into structured_evidence_reviews (
          id,
          candidate_id,
          validated_object_id,
          action,
          reviewer,
          notes,
          patch_json,
          prior_payload_hash,
          after_payload_hash,
          created_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            review_id,
            candidate_id,
            validated_object_id,
            action,
            reviewer,
            notes,
            stable_json(patch),
            prior_payload_hash,
            after_payload_hash,
            now,
        ),
    )


def update_last_review_timestamp(
    connection: sqlite3.Connection,
    book_id: str,
    now: str,
) -> None:
    connection.execute(
        """
        update book_retrieval_status
        set structured_evidence_last_review_at = ?,
            updated_at = ?
        where book_id = ?
        """,
        (now, now, book_id),
    )


def load_source_object_types(
    connection: sqlite3.Connection,
    source_object_ids: tuple[str, ...],
) -> dict[str, str]:
    if not source_object_ids:
        return {}
    placeholders = ",".join("?" for _ in source_object_ids)
    return {
        row["id"]: row["object_type"]
        for row in connection.execute(
            f"""
            select id, object_type
            from source_objects
            where id in ({placeholders})
            """,
            source_object_ids,
        ).fetchall()
    }


def source_role_for(
    object_shape: str,
    source_object_type: str | None,
    *,
    is_primary: bool,
) -> str:
    if is_primary:
        return "primary"
    if object_shape == "structured_table" and source_object_type == "table_row":
        return "table_row"
    if object_shape == "profile_bundle" and source_object_type == "stat_block":
        return "stat_block"
    if object_shape == "profile_bundle":
        return "profile_text"
    return "supporting_section"


def field_confidence_from_payload(
    object_shape: str,
    payload: Mapping[str, Any],
) -> dict[str, float]:
    if object_shape == "profile_bundle":
        provenance = _mapping(payload.get("provenance"))
        field_confidence = provenance.get("field_confidence")
        if isinstance(field_confidence, Mapping):
            return {
                str(key): float(value)
                for key, value in field_confidence.items()
                if isinstance(value, int | float)
            }
    return {}


def _candidate_list_item_from_row(row: sqlite3.Row) -> StructuredCandidateListItem:
    return StructuredCandidateListItem(
        id=row["id"],
        book_id=row["book_id"],
        book_title=row["book_title"],
        object_shape=row["object_shape"],
        content_kind=row["content_kind"],
        entity_kind=row["entity_kind"],
        canonical_name=row["canonical_name"],
        title=row["title"],
        table_number=row["table_number"],
        table_number_normalized=row["table_number_normalized"],
        page_start=row["page_start"],
        page_end=row["page_end"],
        printed_page_start=row["printed_page_start"],
        printed_page_end=row["printed_page_end"],
        confidence=row["confidence"],
        suspicious_flags=tuple(_json_list(row["suspicious_flags_json"])),
        status=row["status"],
        updated_at=row["updated_at"],
    )


def _candidate_detail_from_row(
    row: sqlite3.Row,
    observations: tuple[StructuredObservationDetail, ...],
) -> StructuredCandidateDetail:
    return StructuredCandidateDetail(
        id=row["id"],
        book_id=row["book_id"],
        book_title=row["book_title"],
        primary_page_id=row["primary_page_id"],
        primary_source_object_id=row["primary_source_object_id"],
        object_shape=row["object_shape"],
        content_kind=row["content_kind"],
        entity_kind=row["entity_kind"],
        canonical_name=row["canonical_name"],
        title=row["title"],
        table_number=row["table_number"],
        table_number_normalized=row["table_number_normalized"],
        page_start=row["page_start"],
        page_end=row["page_end"],
        printed_page_start=row["printed_page_start"],
        printed_page_end=row["printed_page_end"],
        heading_path=tuple(_json_list(row["heading_path_json"])),
        payload_json=_payload_from_row(row),
        confidence=row["confidence"],
        suspicious_flags=tuple(_json_list(row["suspicious_flags_json"])),
        status=row["status"],
        text_snapshot_sha256=row["text_snapshot_sha256"],
        structured_extractor_version=row["structured_extractor_version"],
        updated_at=row["updated_at"],
        observations=observations,
    )


def _payload_from_row(row: sqlite3.Row) -> dict[str, Any]:
    value = json.loads(row["payload_json"])
    if not isinstance(value, dict):
        raise StructuredEvidenceInvalidPayloadError("payload_json must be an object")
    return value


def _json_list(value: str) -> list[Any]:
    parsed = json.loads(value or "[]")
    return parsed if isinstance(parsed, list) else []


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _optional_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def new_review_id(candidate_id: str, action: str) -> str:
    return f"structured-review:{short_hash(f'{candidate_id}:{action}:{uuid.uuid4()}')}"


def new_validated_object_id(row: sqlite3.Row, review_id: str) -> str:
    return f"validated-structured:{row['book_id']}:{short_hash(review_id)}"


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
