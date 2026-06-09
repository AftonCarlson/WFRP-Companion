from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fitz

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.library import discovery, storage
from wfrp_companion.library.discovery import PdfCandidate
from wfrp_companion.library.identity import folder_id_for, path_to_posix


@dataclass(frozen=True)
class ImportFailure:
    relative_path: str
    book_id: str
    reason: str


@dataclass(frozen=True)
class ImportSummary:
    discovered: int
    copied: int
    skipped_current: int
    repaired: int
    stale_recovered: int
    failed: int
    failures: tuple[ImportFailure, ...]


@dataclass(frozen=True)
class BookPreparation:
    copy_needed: bool
    repaired: bool
    job_id: str
    managed_path: Path


class ImportCandidateError(Exception):
    pass


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def copy_job_id(book_id: str, source_sha256: str) -> str:
    return f"copy_pdf:{book_id}:{source_sha256}"


def import_pdf_library(
    config: AppConfig,
    *,
    retry_running: bool = False,
    stale_running_minutes: int = 30,
) -> ImportSummary:
    with initialize_database(config.db_path) as connection:
        stale_recovered = recover_stale_running_jobs(
            connection,
            retry_running=retry_running,
            stale_running_minutes=stale_running_minutes,
        )
        candidates = discovery.discover_pdfs(config.pdf_root)
        book_collisions = colliding_book_ids(candidates)
        folder_collisions = colliding_folder_ids(candidates)

        copied = 0
        skipped_current = 0
        repaired = 0
        failed = 0
        failures: list[ImportFailure] = []

        for candidate in candidates:
            collision_reason = collision_failure_reason(
                candidate,
                book_collisions,
                folder_collisions,
            )
            if collision_reason:
                failures.append(
                    record_candidate_failure(
                        connection,
                        candidate=candidate,
                        reason=collision_reason,
                        now=utc_timestamp(),
                    )
                )
                failed += 1
                continue

            now = utc_timestamp()
            source_sha = storage.sha256_file(candidate.source_path)
            job_id = copy_job_id(candidate.book_id, source_sha)
            try:
                page_count = pdf_page_count(candidate.source_path)
            except Exception as exc:  # noqa: BLE001
                record_failed_job(
                    connection,
                    job_id=job_id,
                    book_id=candidate.book_id,
                    error=f"Failed to open PDF: {type(exc).__name__}: {exc}",
                    now=now,
                )
                failures.append(
                    ImportFailure(
                        relative_path=candidate.relative_path_posix,
                        book_id=candidate.book_id,
                        reason=f"Failed to open PDF: {type(exc).__name__}: {exc}",
                    )
                )
                failed += 1
                continue

            try:
                preparation = prepare_book_for_copy(
                    connection,
                    candidate=candidate,
                    data_dir=config.data_dir,
                    source_sha=source_sha,
                    page_count=page_count,
                    now=now,
                )
            except ImportCandidateError as exc:
                failures.append(
                    record_candidate_failure(
                        connection,
                        candidate=candidate,
                        reason=str(exc),
                        now=utc_timestamp(),
                    )
                )
                failed += 1
                continue

            if not preparation.copy_needed:
                skipped_current += 1
                continue

            if preparation.repaired:
                repaired += 1

            if not claim_copy_job(
                connection,
                book_id=candidate.book_id,
                job_id=preparation.job_id,
                now=utc_timestamp(),
            ):
                continue

            try:
                managed_sha = storage.copy_pdf_atomic(
                    candidate.source_path,
                    preparation.managed_path,
                )
                if managed_sha != source_sha:
                    raise ImportCandidateError(
                        f"Managed SHA mismatch for {candidate.relative_path_posix}"
                    )
            except Exception as exc:  # noqa: BLE001
                mark_copy_failed(
                    connection,
                    book_id=candidate.book_id,
                    job_id=preparation.job_id,
                    error=f"{type(exc).__name__}: {exc}",
                    now=utc_timestamp(),
                )
                failures.append(
                    ImportFailure(
                        relative_path=candidate.relative_path_posix,
                        book_id=candidate.book_id,
                        reason=f"{type(exc).__name__}: {exc}",
                    )
                )
                failed += 1
                continue

            mark_copy_succeeded(
                connection,
                book_id=candidate.book_id,
                job_id=preparation.job_id,
                managed_path=preparation.managed_path,
                managed_sha=managed_sha,
                now=utc_timestamp(),
            )
            copied += 1

        return ImportSummary(
            discovered=len(candidates),
            copied=copied,
            skipped_current=skipped_current,
            repaired=repaired,
            stale_recovered=stale_recovered,
            failed=failed,
            failures=tuple(failures),
        )


def pdf_page_count(path: Path) -> int:
    with fitz.open(path) as document:
        return document.page_count


def colliding_book_ids(candidates: list[PdfCandidate]) -> set[str]:
    paths_by_id: dict[str, set[str]] = {}
    for candidate in candidates:
        paths_by_id.setdefault(candidate.book_id, set()).add(candidate.relative_path_posix)
    return {
        book_id
        for book_id, relative_paths in paths_by_id.items()
        if len(relative_paths) > 1
    }


def colliding_folder_ids(candidates: list[PdfCandidate]) -> set[str]:
    paths_by_id: dict[str, set[str]] = {}
    for candidate in candidates:
        if candidate.folder_id != "root":
            paths_by_id.setdefault(candidate.folder_id, set()).add(
                path_to_posix(candidate.folder_relative_path)
            )
    return {
        folder_id
        for folder_id, relative_paths in paths_by_id.items()
        if len(relative_paths) > 1
    }


def collision_failure_reason(
    candidate: PdfCandidate,
    book_collisions: set[str],
    folder_collisions: set[str],
) -> str | None:
    if candidate.book_id in book_collisions:
        return f"Book id collision for {candidate.book_id}"
    if candidate.folder_id in folder_collisions:
        return f"Folder id collision for {candidate.folder_id}"
    return None


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
            select id, target_id
            from ingest_jobs
            where job_type = 'copy_pdf'
              and status = 'running'
            """
        ).fetchall()
    else:
        rows = connection.execute(
            """
            select id, target_id
            from ingest_jobs
            where job_type = 'copy_pdf'
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
                    last_error = 'Recovered stale running copy job from interrupted import.',
                    updated_at = ?
                where id = ?
                """,
                (now, row["id"]),
            )
            if row["target_id"]:
                connection.execute(
                    """
                    update books
                    set copy_status = 'failed',
                        updated_at = ?
                    where id = ?
                      and copy_status = 'copying'
                    """,
                    (now, row["target_id"]),
        )
    return len(rows)


def record_candidate_failure(
    connection: sqlite3.Connection,
    *,
    candidate: PdfCandidate,
    reason: str,
    now: str,
) -> ImportFailure:
    try:
        source_sha = storage.sha256_file(candidate.source_path)
    except OSError as exc:
        return ImportFailure(
            relative_path=candidate.relative_path_posix,
            book_id=candidate.book_id,
            reason=f"{reason}; failed to hash source: {type(exc).__name__}: {exc}",
        )

    record_failed_job(
        connection,
        job_id=copy_job_id(candidate.book_id, source_sha),
        book_id=candidate.book_id,
        error=reason,
        now=now,
    )
    return ImportFailure(
        relative_path=candidate.relative_path_posix,
        book_id=candidate.book_id,
        reason=reason,
    )


def record_failed_job(
    connection: sqlite3.Connection,
    *,
    job_id: str,
    book_id: str,
    error: str,
    now: str,
) -> None:
    with connection:
        connection.execute(
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
              updated_at
            )
            values (?, 'copy_pdf', ?, 'failed', ?, 1, ?, ?, ?)
            on conflict(idempotency_key) do update set
              status = 'failed',
              attempts = ingest_jobs.attempts + 1,
              last_error = excluded.last_error,
              updated_at = excluded.updated_at
            """,
            (job_id, book_id, job_id, error, now, now),
        )


def prepare_book_for_copy(
    connection: sqlite3.Connection,
    *,
    candidate: PdfCandidate,
    data_dir: Path,
    source_sha: str,
    page_count: int,
    now: str,
) -> BookPreparation:
    managed_path = storage.managed_pdf_path(data_dir, candidate.book_id, source_sha)
    job_id = copy_job_id(candidate.book_id, source_sha)
    existing_copy_status = None
    existing_managed_sha = None
    existing_managed_path = None

    with connection:
        folder_id = ensure_folder_hierarchy(connection, candidate, now)
        existing = connection.execute(
            "select * from books where id = ?",
            (candidate.book_id,),
        ).fetchone()

        if existing is None:
            insert_book(
                connection,
                candidate=candidate,
                folder_id=folder_id,
                source_sha=source_sha,
                managed_path=managed_path,
                page_count=page_count,
                now=now,
            )
            ensure_copy_job(connection, job_id=job_id, book_id=candidate.book_id, now=now)
            return BookPreparation(True, False, job_id, managed_path)

        if existing["relative_path"] != candidate.relative_path_posix:
            raise ImportCandidateError(
                f"Book id collision for {candidate.book_id}: "
                f"{existing['relative_path']} != {candidate.relative_path_posix}"
            )

        if existing["original_sha256"] == source_sha:
            update_same_source_book(
                connection,
                candidate=candidate,
                folder_id=folder_id,
                page_count=page_count,
                now=now,
            )
            existing_copy_status = existing["copy_status"]
            existing_managed_sha = existing["managed_sha256"]
            existing_managed_path = existing["managed_pdf_path"]
        else:
            update_changed_source_book(
                connection,
                candidate=candidate,
                folder_id=folder_id,
                source_sha=source_sha,
                page_count=page_count,
                now=now,
            )
            ensure_copy_job(
                connection,
                job_id=job_id,
                book_id=candidate.book_id,
                now=now,
            )
            return BookPreparation(True, False, job_id, managed_path)

    if (
        existing_copy_status == "copied"
        and existing_managed_sha
        and existing_managed_path
        and storage.managed_file_matches(
            Path(existing_managed_path),
            existing_managed_sha,
        )
    ):
        return BookPreparation(False, False, job_id, managed_path)

    with connection:
        connection.execute(
            """
            update books
            set copy_status = 'managed_missing',
                managed_pdf_path = ?,
                updated_at = ?
            where id = ?
            """,
            (str(managed_path), now, candidate.book_id),
        )
        ensure_copy_job(
            connection,
            job_id=job_id,
            book_id=candidate.book_id,
            now=now,
            reset_succeeded=True,
        )
    return BookPreparation(True, True, job_id, managed_path)


def ensure_folder_hierarchy(
    connection: sqlite3.Connection,
    candidate: PdfCandidate,
    now: str,
) -> str:
    ensure_folder(
        connection,
        folder_id="root",
        parent_id=None,
        name="Library",
        relative_path="",
        sort_order=0,
    )

    parent_id = "root"
    current = Path("")
    parts = [] if path_to_posix(candidate.folder_relative_path) == "" else list(
        candidate.folder_relative_path.parts
    )
    for sort_order, part in enumerate(parts, start=1):
        current = current / part
        folder_id = folder_id_for(current)
        ensure_folder(
            connection,
            folder_id=folder_id,
            parent_id=parent_id,
            name=part,
            relative_path=path_to_posix(current),
            sort_order=sort_order,
        )
        parent_id = folder_id

    return parent_id


def ensure_folder(
    connection: sqlite3.Connection,
    *,
    folder_id: str,
    parent_id: str | None,
    name: str,
    relative_path: str,
    sort_order: int,
) -> None:
    existing_by_id = connection.execute(
        "select relative_path from library_folders where id = ?",
        (folder_id,),
    ).fetchone()
    if existing_by_id and existing_by_id["relative_path"] != relative_path:
        raise ImportCandidateError(
            f"Folder id collision for {folder_id}: "
            f"{existing_by_id['relative_path']} != {relative_path}"
        )

    connection.execute(
        """
        insert into library_folders (id, parent_id, name, relative_path, sort_order)
        values (?, ?, ?, ?, ?)
        on conflict(relative_path) do update set
          parent_id = excluded.parent_id,
          name = excluded.name,
          sort_order = excluded.sort_order
        """,
        (folder_id, parent_id, name, relative_path, sort_order),
    )


def insert_book(
    connection: sqlite3.Connection,
    *,
    candidate: PdfCandidate,
    folder_id: str,
    source_sha: str,
    managed_path: Path,
    page_count: int,
    now: str,
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
        values (?, ?, ?, ?, ?, ?, ?, ?, null, ?, 'discovered',
                'not_imported', 'not_indexed', 'not_scanned', ?, ?)
        """,
        (
            candidate.book_id,
            folder_id,
            candidate.title,
            candidate.category,
            candidate.relative_path_posix,
            str(candidate.source_path.resolve()),
            str(managed_path),
            source_sha,
            page_count,
            now,
            now,
        ),
    )


def update_same_source_book(
    connection: sqlite3.Connection,
    *,
    candidate: PdfCandidate,
    folder_id: str,
    page_count: int,
    now: str,
) -> None:
    connection.execute(
        """
        update books
        set folder_id = ?,
            title = ?,
            category = ?,
            original_source_path = ?,
            page_count = ?,
            updated_at = ?
        where id = ?
        """,
        (
            folder_id,
            candidate.title,
            candidate.category,
            str(candidate.source_path.resolve()),
            page_count,
            now,
            candidate.book_id,
        ),
    )


def update_changed_source_book(
    connection: sqlite3.Connection,
    *,
    candidate: PdfCandidate,
    folder_id: str,
    source_sha: str,
    page_count: int,
    now: str,
) -> None:
    connection.execute(
        """
        update books
        set folder_id = ?,
            title = ?,
            category = ?,
            original_source_path = ?,
            original_sha256 = ?,
            page_count = ?,
            copy_status = 'discovered',
            text_status = case when text_status = 'imported'
              then 'needs_refresh' else text_status end,
            search_status = case when search_status = 'indexed'
              then 'needs_refresh' else search_status end,
            visual_status = case when visual_status = 'scanned'
              then 'needs_refresh' else visual_status end,
            updated_at = ?
        where id = ?
        """,
        (
            folder_id,
            candidate.title,
            candidate.category,
            str(candidate.source_path.resolve()),
            source_sha,
            page_count,
            now,
            candidate.book_id,
        ),
    )


def ensure_copy_job(
    connection: sqlite3.Connection,
    *,
    job_id: str,
    book_id: str,
    now: str,
    reset_succeeded: bool = False,
) -> None:
    existing = connection.execute(
        "select status from ingest_jobs where idempotency_key = ?",
        (job_id,),
    ).fetchone()
    if existing is None:
        connection.execute(
            """
            insert into ingest_jobs (
              id,
              job_type,
              target_id,
              status,
              idempotency_key,
              created_at,
              updated_at
            )
            values (?, 'copy_pdf', ?, 'queued', ?, ?, ?)
            """,
            (job_id, book_id, job_id, now, now),
        )
        return

    if reset_succeeded and existing["status"] == "succeeded":
        connection.execute(
            """
            update ingest_jobs
            set target_id = ?,
                status = 'queued',
                last_error = null,
                updated_at = ?,
                completed_at = null
            where idempotency_key = ?
            """,
            (book_id, now, job_id),
        )


def claim_copy_job(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    job_id: str,
    now: str,
) -> bool:
    try:
        connection.execute("begin immediate")
        job_result = connection.execute(
            """
            update ingest_jobs
            set status = 'running',
                attempts = attempts + 1,
                last_error = null,
                updated_at = ?
            where id = ?
              and status in ('queued', 'failed')
            """,
            (now, job_id),
        )
        book_result = connection.execute(
            """
            update books
            set copy_status = 'copying',
                updated_at = ?
            where id = ?
              and copy_status in ('discovered', 'managed_missing', 'failed')
            """,
            (now, book_id),
        )
        if job_result.rowcount == 1 and book_result.rowcount == 1:
            connection.commit()
            return True
        connection.rollback()
        return False
    except Exception:
        connection.rollback()
        raise


def mark_copy_succeeded(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    job_id: str,
    managed_path: Path,
    managed_sha: str,
    now: str,
) -> None:
    with connection:
        connection.execute(
            """
            update books
            set copy_status = 'copied',
                managed_sha256 = ?,
                managed_pdf_path = ?,
                copied_at = ?,
                updated_at = ?
            where id = ?
              and copy_status = 'copying'
            """,
            (managed_sha, str(managed_path), now, now, book_id),
        )
        connection.execute(
            """
            update ingest_jobs
            set status = 'succeeded',
                last_error = null,
                updated_at = ?,
                completed_at = ?
            where id = ?
            """,
            (now, now, job_id),
        )


def mark_copy_failed(
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
            update books
            set copy_status = 'failed',
                updated_at = ?
            where id = ?
              and copy_status = 'copying'
            """,
            (now, book_id),
        )
        connection.execute(
            """
            update ingest_jobs
            set status = 'failed',
                last_error = ?,
                updated_at = ?
            where id = ?
            """,
            (error, now, job_id),
        )
