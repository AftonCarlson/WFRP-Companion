from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import fitz

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database


BOOK_REQUIRED_FIELDS = (
    "book_id",
    "source_sha256",
    "page_count",
    "generated_at",
    "pages",
)
PAGE_REQUIRED_FIELDS = (
    "page_number",
    "text",
    "extraction_method",
    "embedded_text_chars",
    "text_chars",
    "word_count",
    "image_count",
    "ocr_attempted",
    "ocr_error",
)


@dataclass(frozen=True)
class PageTextImportFailure:
    relative_path: str
    book_id: str | None
    reason: str


@dataclass(frozen=True)
class PageTextImportSummary:
    discovered: int
    imported: int
    skipped_current: int
    stale_recovered: int
    failed: int
    pages_imported: int
    failures: tuple[PageTextImportFailure, ...]


@dataclass(frozen=True)
class PageTextRecord:
    page_number: int
    page_label: str | None
    text: str
    extraction_method: str
    embedded_text_chars: int
    text_chars: int
    word_count: int
    image_count: int
    ocr_attempted: bool
    ocr_error: str | None


@dataclass(frozen=True)
class BookTextRecord:
    book_id: str
    source_sha256: str
    page_count: int
    generated_at: str
    ocr_language: str | None
    ocr_dpi: int | None
    low_text_chars_threshold: int | None
    pages: tuple[PageTextRecord, ...]


class FileLevelImportError(Exception):
    def __init__(
        self,
        *,
        relative_path: str,
        json_sha256: str,
        reason: str,
        book_id: str | None = None,
    ) -> None:
        super().__init__(reason)
        self.relative_path = relative_path
        self.json_sha256 = json_sha256
        self.reason = reason
        self.book_id = book_id


class BookImportError(Exception):
    def __init__(self, *, relative_path: str, book_id: str, reason: str) -> None:
        super().__init__(reason)
        self.relative_path = relative_path
        self.book_id = book_id
        self.reason = reason


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def import_job_id(book_id: str, json_sha256: str) -> str:
    return f"import_page_text:{book_id}:{json_sha256}"


def file_import_job_id(relative_path: str, json_sha256: str) -> str:
    return f"import_page_text_file:{relative_path}:{json_sha256}"


def import_page_text_library(
    config: AppConfig,
    *,
    input_dir: Path | None = None,
    force: bool = False,
    retry_running: bool = False,
    stale_running_minutes: int = 30,
) -> PageTextImportSummary:
    source_dir = input_dir or config.data_dir / "page_text"
    with initialize_database(config.db_path) as connection:
        stale_recovered = recover_stale_running_jobs(
            connection,
            retry_running=retry_running,
            stale_running_minutes=stale_running_minutes,
        )
        files = sorted(source_dir.glob("*.json")) if source_dir.exists() else []
        imported = 0
        skipped_current = 0
        failed = 0
        pages_imported = 0
        failures: list[PageTextImportFailure] = []

        for path in files:
            relative_path = path.relative_to(source_dir).as_posix()
            content = path.read_bytes()
            json_sha = sha256_bytes(content)
            try:
                document = parse_book_text(
                    content,
                    relative_path=relative_path,
                    json_sha256=json_sha,
                )
                validate_filename_matches_book(relative_path, document.book_id, json_sha)
                validate_book_against_database(connection, document, relative_path)
            except FileLevelImportError as exc:
                record_file_failure(connection, exc=exc, now=utc_timestamp())
                failures.append(
                    PageTextImportFailure(exc.relative_path, exc.book_id, exc.reason)
                )
                failed += 1
                continue
            except BookImportError as exc:
                record_book_failure(connection, exc=exc, json_sha256=json_sha)
                failures.append(
                    PageTextImportFailure(exc.relative_path, exc.book_id, exc.reason)
                )
                failed += 1
                continue

            job_id = import_job_id(document.book_id, json_sha)
            if (
                import_job_succeeded(connection, job_id)
                and not force
                and imported_text_current(connection, document, json_sha)
            ):
                skipped_current += 1
                continue

            if not claim_import_job(
                connection,
                job_id=job_id,
                book_id=document.book_id,
                now=utc_timestamp(),
            ):
                continue
            try:
                imported_pages = write_book_text(
                    connection,
                    document=document,
                    job_id=job_id,
                    json_sha256=json_sha,
                    force=force,
                    now=utc_timestamp(),
                )
            except Exception as exc:  # noqa: BLE001
                mark_claimed_job_failed(
                    connection,
                    job_id=job_id,
                    book_id=document.book_id,
                    error=f"{type(exc).__name__}: {exc}",
                    now=utc_timestamp(),
                )
                failures.append(
                    PageTextImportFailure(
                        relative_path,
                        document.book_id,
                        f"{type(exc).__name__}: {exc}",
                    )
                )
                failed += 1
                continue

            imported += 1
            pages_imported += imported_pages

        return PageTextImportSummary(
            discovered=len(files),
            imported=imported,
            skipped_current=skipped_current,
            stale_recovered=stale_recovered,
            failed=failed,
            pages_imported=pages_imported,
            failures=tuple(failures),
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
            select id, target_id
            from ingest_jobs
            where job_type = 'import_page_text'
              and status = 'running'
            """
        ).fetchall()
    else:
        rows = connection.execute(
            """
            select id, target_id
            from ingest_jobs
            where job_type = 'import_page_text'
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
                    last_error = 'Recovered stale running page text import job.',
                    updated_at = ?
                where id = ?
                """,
                (now, row["id"]),
            )
            if row["target_id"]:
                connection.execute(
                    """
                    update books
                    set text_status = 'failed',
                        updated_at = ?
                    where id = ?
                      and text_status = 'importing'
                    """,
                    (now, row["target_id"]),
                )
    return len(rows)


def parse_book_text(
    content: bytes,
    *,
    relative_path: str,
    json_sha256: str,
) -> BookTextRecord:
    try:
        raw = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FileLevelImportError(
            relative_path=relative_path,
            json_sha256=json_sha256,
            reason=f"Invalid JSON: {exc}",
        ) from exc

    if not isinstance(raw, dict):
        raise FileLevelImportError(
            relative_path=relative_path,
            json_sha256=json_sha256,
            reason="Invalid JSON: root value must be an object",
        )

    if "book_id" not in raw:
        raise FileLevelImportError(
            relative_path=relative_path,
            json_sha256=json_sha256,
            reason="Missing required book field: book_id",
        )

    book_id = required_str(
        raw,
        "book_id",
        relative_path=relative_path,
        json_sha256=json_sha256,
    )
    for field in BOOK_REQUIRED_FIELDS:
        if field not in raw:
            raise BookImportError(
                relative_path=relative_path,
                book_id=book_id,
                reason=f"Missing required book field: {field}",
            )

    pages_raw = raw["pages"]
    if not isinstance(pages_raw, list):
        raise BookImportError(
            relative_path=relative_path,
            book_id=book_id,
            reason="Book field must be a list: pages",
        )

    pages = tuple(
        parse_page_text(page, relative_path=relative_path, book_id=book_id)
        for page in pages_raw
    )
    page_count = required_int(raw, "page_count", relative_path, book_id)
    expected_pages = list(range(1, page_count + 1))
    actual_pages = sorted(page.page_number for page in pages)
    if actual_pages != expected_pages:
        raise BookImportError(
            relative_path=relative_path,
            book_id=book_id,
            reason=f"Page numbers must be exactly 1..{page_count} for {book_id}",
        )

    return BookTextRecord(
        book_id=book_id,
        source_sha256=required_str(
            raw,
            "source_sha256",
            relative_path=relative_path,
            book_id=book_id,
        ),
        page_count=page_count,
        generated_at=required_str(
            raw,
            "generated_at",
            relative_path=relative_path,
            book_id=book_id,
        ),
        ocr_language=optional_str(raw.get("ocr_language")),
        ocr_dpi=optional_int(raw.get("ocr_dpi")),
        low_text_chars_threshold=optional_int(raw.get("low_text_chars_threshold")),
        pages=pages,
    )


def parse_page_text(
    raw: Any,
    *,
    relative_path: str,
    book_id: str,
) -> PageTextRecord:
    if not isinstance(raw, dict):
        raise BookImportError(
            relative_path=relative_path,
            book_id=book_id,
            reason=f"Page record must be an object for {book_id}",
        )

    page_number = raw.get("page_number")
    page_label = page_number if isinstance(page_number, int) else "unknown"
    for field in PAGE_REQUIRED_FIELDS:
        if field not in raw:
            raise BookImportError(
                relative_path=relative_path,
                book_id=book_id,
                reason=f"Missing required page field on page {page_label}: {field}",
            )

    return PageTextRecord(
        page_number=required_int(raw, "page_number", relative_path, book_id),
        page_label=normalize_page_label(raw.get("page_label")),
        text=required_str(
            raw,
            "text",
            relative_path=relative_path,
            allow_empty=True,
            book_id=book_id,
        ),
        extraction_method=required_str(
            raw,
            "extraction_method",
            relative_path=relative_path,
            book_id=book_id,
        ),
        embedded_text_chars=required_int(
            raw,
            "embedded_text_chars",
            relative_path,
            book_id,
        ),
        text_chars=required_int(raw, "text_chars", relative_path, book_id),
        word_count=required_int(raw, "word_count", relative_path, book_id),
        image_count=required_int(raw, "image_count", relative_path, book_id),
        ocr_attempted=required_bool(raw, "ocr_attempted", relative_path, book_id),
        ocr_error=optional_str(raw["ocr_error"]),
    )


def required_str(
    raw: dict[str, Any],
    field: str,
    *,
    relative_path: str,
    allow_empty: bool = False,
    book_id: str | None = None,
    json_sha256: str | None = None,
) -> str:
    value = raw[field]
    if not isinstance(value, str) or (not allow_empty and not value):
        if book_id is None:
            raise FileLevelImportError(
                relative_path=relative_path,
                json_sha256=json_sha256
                or sha256_bytes(json.dumps(raw, sort_keys=True).encode("utf-8")),
                reason=f"Book field must be a non-empty string: {field}",
            )
        raise BookImportError(
            relative_path=relative_path,
            book_id=book_id,
            reason=f"Field must be a non-empty string: {field}",
        )
    return value


def required_int(
    raw: dict[str, Any],
    field: str,
    relative_path: str,
    book_id: str,
) -> int:
    value = raw[field]
    if not isinstance(value, int):
        raise BookImportError(
            relative_path=relative_path,
            book_id=book_id,
            reason=f"Field must be an integer: {field}",
        )
    return value


def required_bool(
    raw: dict[str, Any],
    field: str,
    relative_path: str,
    book_id: str,
) -> bool:
    value = raw[field]
    if not isinstance(value, bool):
        raise BookImportError(
            relative_path=relative_path,
            book_id=book_id,
            reason=f"Field must be a boolean: {field}",
        )
    return value


def optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def normalize_page_label(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def pdf_page_labels_for_book(
    connection: sqlite3.Connection,
    book_id: str,
    page_count: int,
) -> dict[int, str]:
    row = connection.execute(
        "select managed_pdf_path from books where id = ?",
        (book_id,),
    ).fetchone()
    if row is None or row["managed_pdf_path"] is None:  # pragma: no cover
        return {}  # pragma: no cover

    path = Path(row["managed_pdf_path"])
    if not path.exists():
        return {}

    try:
        with fitz.open(path) as document:
            labels: dict[int, str] = {}
            for index in range(min(page_count, document.page_count)):
                label = normalize_page_label(document[index].get_label())
                if label is not None:
                    labels[index + 1] = label
            return labels
    except Exception:  # pragma: no cover
        return {}  # pragma: no cover


def page_label_for_import(
    page: PageTextRecord,
    *,
    pdf_page_labels: dict[int, str],
) -> str | None:
    return page.page_label or pdf_page_labels.get(page.page_number)


def validate_filename_matches_book(
    relative_path: str,
    book_id: str,
    json_sha256: str,
) -> None:
    stem = Path(relative_path).stem
    if stem != book_id:
        raise FileLevelImportError(
            relative_path=relative_path,
            json_sha256=json_sha256,
            reason=f"JSON filename {stem} does not match book_id {book_id}",
            book_id=book_id,
        )


def validate_book_against_database(
    connection: sqlite3.Connection,
    document: BookTextRecord,
    relative_path: str,
) -> None:
    book = connection.execute(
        "select * from books where id = ?",
        (document.book_id,),
    ).fetchone()
    if book is None:
        raise BookImportError(
            relative_path=relative_path,
            book_id=document.book_id,
            reason=f"Book is not registered: {document.book_id}",
        )
    if book["copy_status"] != "copied":
        raise BookImportError(
            relative_path=relative_path,
            book_id=document.book_id,
            reason=f"Book is not copied: {document.book_id}",
        )
    if book["original_sha256"] != document.source_sha256:
        raise BookImportError(
            relative_path=relative_path,
            book_id=document.book_id,
            reason=f"Source SHA mismatch for {document.book_id}",
        )
    if book["page_count"] != document.page_count:
        raise BookImportError(
            relative_path=relative_path,
            book_id=document.book_id,
            reason=f"Page count mismatch for {document.book_id}",
        )


def import_job_succeeded(connection: sqlite3.Connection, job_id: str) -> bool:
    row = connection.execute(
        """
        select status
        from ingest_jobs
        where idempotency_key = ?
        """,
        (job_id,),
    ).fetchone()
    return row is not None and row["status"] == "succeeded"


def imported_text_current(
    connection: sqlite3.Connection,
    document: BookTextRecord,
    json_sha256: str,
) -> bool:
    book = connection.execute(
        "select text_status from books where id = ?",
        (document.book_id,),
    ).fetchone()
    if book is None or book["text_status"] != "imported":
        return False

    rows = connection.execute(
        """
        select
          pages.page_number,
          pages.page_label,
          pages.metadata_json,
          page_text.text_sha256,
          page_text.generated_at
        from pages
        left join page_text on page_text.page_id = pages.id
        where pages.book_id = ?
        order by pages.page_number
        """,
        (document.book_id,),
    ).fetchall()
    if len(rows) != len(document.pages):
        return False

    expected = {page.page_number: page for page in document.pages}
    pdf_page_labels = pdf_page_labels_for_book(
        connection,
        document.book_id,
        document.page_count,
    )
    for row in rows:
        page = expected.get(row["page_number"])
        if page is None or row["text_sha256"] is None:
            return False
        try:
            metadata = json.loads(row["metadata_json"])
        except json.JSONDecodeError:
            return False
        if metadata.get("json_sha256") != json_sha256:
            return False
        expected_hash = hashlib.sha256(page.text.encode("utf-8")).hexdigest()
        if row["text_sha256"] != expected_hash:
            return False
        if row["generated_at"] != document.generated_at:
            return False
        expected_label = page_label_for_import(
            page,
            pdf_page_labels=pdf_page_labels,
        )
        if row["page_label"] != expected_label:
            return False
    return True


def claim_import_job(
    connection: sqlite3.Connection,
    *,
    job_id: str,
    book_id: str,
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
            values (?, 'import_page_text', ?, 'running', ?, 1, null, ?, ?, null)
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
    return cursor.rowcount == 1


def write_book_text(
    connection: sqlite3.Connection,
    *,
    document: BookTextRecord,
    job_id: str,
    json_sha256: str,
    force: bool,
    now: str,
) -> int:
    pdf_page_labels = pdf_page_labels_for_book(
        connection,
        document.book_id,
        document.page_count,
    )
    metadata_json = json.dumps(
        {
            "source": "data/page_text",
            "json_sha256": json_sha256,
            "ocr_language": document.ocr_language,
            "ocr_dpi": document.ocr_dpi,
            "low_text_chars_threshold": document.low_text_chars_threshold,
        },
        sort_keys=True,
    )

    with connection:
        updated = connection.execute(
            """
            update books
            set text_status = 'importing',
                updated_at = ?
            where id = ?
              and copy_status = 'copied'
              and (
                text_status in ('not_imported', 'failed', 'needs_refresh', 'imported')
                or (? = 1 and text_status = 'imported')
              )
            """,
            (now, document.book_id, 1 if force else 0),
        )
        if updated.rowcount != 1:
            raise RuntimeError(f"Book text import is not claimable: {document.book_id}")

        connection.execute("delete from pages where book_id = ?", (document.book_id,))
        for page in document.pages:
            page_id = f"{document.book_id}:{page.page_number}"
            connection.execute(
                """
                insert into pages (
                  id,
                  book_id,
                  page_number,
                  page_label,
                  extraction_method,
                  embedded_text_chars,
                  text_chars,
                  word_count,
                  image_count,
                  ocr_attempted,
                  ocr_error,
                  has_text,
                  metadata_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    page_id,
                    document.book_id,
                    page.page_number,
                    page_label_for_import(page, pdf_page_labels=pdf_page_labels),
                    page.extraction_method,
                    page.embedded_text_chars,
                    page.text_chars,
                    page.word_count,
                    page.image_count,
                    1 if page.ocr_attempted else 0,
                    page.ocr_error,
                    1 if page.text.strip() else 0,
                    metadata_json,
                ),
            )
            connection.execute(
                """
                insert into page_text (page_id, text, text_sha256, generated_at)
                values (?, ?, ?, ?)
                """,
                (
                    page_id,
                    page.text,
                    hashlib.sha256(page.text.encode("utf-8")).hexdigest(),
                    document.generated_at,
                ),
            )

        connection.execute(
            """
            update books
            set text_status = 'imported',
                search_status = case
                  when search_status = 'not_indexed' then 'not_indexed'
                  else 'needs_refresh'
                end,
                updated_at = ?
            where id = ?
            """,
            (now, document.book_id),
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
    return len(document.pages)


def record_file_failure(
    connection: sqlite3.Connection,
    *,
    exc: FileLevelImportError,
    now: str,
) -> None:
    job_id = file_import_job_id(exc.relative_path, exc.json_sha256)
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
            values (?, 'import_page_text', null, 'failed', ?, 1, ?, ?, ?)
            on conflict(idempotency_key) do update set
              status = 'failed',
              attempts = ingest_jobs.attempts + 1,
              last_error = excluded.last_error,
              updated_at = excluded.updated_at
            """,
            (job_id, job_id, exc.reason, now, now),
        )


def record_book_failure(
    connection: sqlite3.Connection,
    *,
    exc: BookImportError,
    json_sha256: str,
) -> None:
    now = utc_timestamp()
    job_id = import_job_id(exc.book_id, json_sha256)
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
            values (?, 'import_page_text', ?, 'failed', ?, 1, ?, ?, ?)
            on conflict(idempotency_key) do update set
              status = 'failed',
              attempts = ingest_jobs.attempts + 1,
              last_error = excluded.last_error,
              updated_at = excluded.updated_at
            """,
            (job_id, exc.book_id, job_id, exc.reason, now, now),
        )
        connection.execute(
            """
            update books
            set text_status = 'failed',
                updated_at = ?
            where id = ?
            """,
            (now, exc.book_id),
        )


def mark_claimed_job_failed(
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
            set text_status = 'failed',
                updated_at = ?
            where id = ?
            """,
            (now, book_id),
        )
