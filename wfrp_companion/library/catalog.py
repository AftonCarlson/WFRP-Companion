from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database


@dataclass(frozen=True)
class BookSummary:
    id: str
    title: str
    category: str
    relative_path: str
    page_count: int
    copy_status: str
    text_status: str
    search_status: str
    visual_status: str
    reader_ready: bool
    search_ready: bool
    fully_ready: bool
    needs_attention: bool
    vector_status: str
    embedding_provider: str | None
    embedding_model: str | None
    embedding_dimensions: int | None


@dataclass(frozen=True)
class BookDetail(BookSummary):
    managed_pdf_available: bool


@dataclass(frozen=True)
class PageReference:
    page_id: str
    book_id: str
    page_number: int
    page_label: str | None
    has_text: bool
    text_chars: int
    image_count: int


@dataclass(frozen=True)
class PageTextReference:
    page_id: str
    book_id: str
    page_number: int
    page_label: str | None
    text: str
    text_chars: int


class CatalogError(Exception):
    pass


class BookNotFoundError(CatalogError):
    pass


class PageNotFoundError(CatalogError):
    pass


class ReaderUnavailableError(CatalogError):
    pass


class PageTextUnavailableError(CatalogError):
    pass


class ManagedPdfMissingError(CatalogError):
    pass


class ManagedPdfPathRejectedError(CatalogError):
    pass


BOOK_COLUMNS = """
  books.id,
  books.title,
  books.category,
  books.relative_path,
  books.managed_pdf_path,
  books.page_count,
  books.copy_status,
  books.text_status,
  books.search_status,
  books.visual_status,
  book_readiness.reader_ready,
  book_readiness.search_ready,
  book_readiness.fully_ready,
  book_readiness.needs_attention,
  coalesce(book_retrieval_status.vector_status, 'disabled') as vector_status,
  book_retrieval_status.embedding_provider,
  book_retrieval_status.embedding_model,
  book_retrieval_status.embedding_dimensions
"""


def list_books(config: AppConfig) -> tuple[BookSummary, ...]:
    with initialize_database(config.db_path) as connection:
        rows = connection.execute(
            f"""
            select {BOOK_COLUMNS}
            from books
            left join book_readiness on book_readiness.book_id = books.id
            left join book_retrieval_status
              on book_retrieval_status.book_id = books.id
            order by books.category, books.title, books.id
            """
        ).fetchall()
    return tuple(book_summary_from_row(row) for row in rows)


def get_book(config: AppConfig, book_id: str) -> BookDetail:
    with initialize_database(config.db_path) as connection:
        row = book_row(connection, book_id)

    summary = book_summary_from_row(row)
    return BookDetail(
        **summary.__dict__,
        managed_pdf_available=managed_pdf_available(config, row),
    )


def get_page(config: AppConfig, book_id: str, page_number: int) -> PageReference:
    with initialize_database(config.db_path) as connection:
        if not book_exists(connection, book_id):
            raise BookNotFoundError(f"Book not found: {book_id}")
        row = connection.execute(
            """
            select
              pages.id,
              pages.book_id,
              pages.page_number,
              pages.page_label,
              pages.has_text,
              pages.text_chars,
              pages.image_count
            from pages
            where pages.book_id = ?
              and pages.page_number = ?
            """,
            (book_id, page_number),
        ).fetchone()

    if row is None:
        raise PageNotFoundError(f"Page not found: {book_id} p. {page_number}")

    return PageReference(
        page_id=row["id"],
        book_id=row["book_id"],
        page_number=row["page_number"],
        page_label=row["page_label"],
        has_text=bool(row["has_text"]),
        text_chars=row["text_chars"],
        image_count=row["image_count"],
    )


def get_page_text(
    config: AppConfig,
    book_id: str,
    page_number: int,
) -> PageTextReference:
    with initialize_database(config.db_path) as connection:
        book = book_row(connection, book_id)
        if not bool(book["search_ready"]):
            raise PageTextUnavailableError(
                f"Page text is unavailable for book: {book_id}"
            )
        row = connection.execute(
            """
            select
              pages.id,
              pages.book_id,
              pages.page_number,
              pages.page_label,
              pages.text_chars,
              page_text.text
            from pages
            join page_text on page_text.page_id = pages.id
            where pages.book_id = ?
              and pages.page_number = ?
            """,
            (book_id, page_number),
        ).fetchone()

    if row is None:
        raise PageNotFoundError(f"Page text not found: {book_id} p. {page_number}")

    return PageTextReference(
        page_id=row["id"],
        book_id=row["book_id"],
        page_number=row["page_number"],
        page_label=row["page_label"],
        text=row["text"],
        text_chars=row["text_chars"],
    )


def reader_pdf_path(config: AppConfig, book_id: str) -> Path:
    with initialize_database(config.db_path) as connection:
        row = book_row(connection, book_id)

    if not bool(row["reader_ready"]):
        raise ReaderUnavailableError(f"Reader is unavailable for book: {book_id}")
    path = validate_managed_pdf_path(config, book_id, row["managed_pdf_path"])
    if not path.is_file():
        raise ManagedPdfMissingError(f"Managed PDF is missing for book: {book_id}")
    return path


def book_row(connection: sqlite3.Connection, book_id: str) -> sqlite3.Row:
    row = connection.execute(
        f"""
        select {BOOK_COLUMNS}
        from books
        left join book_readiness on book_readiness.book_id = books.id
        left join book_retrieval_status
          on book_retrieval_status.book_id = books.id
        where books.id = ?
        """,
        (book_id,),
    ).fetchone()
    if row is None:
        raise BookNotFoundError(f"Book not found: {book_id}")
    return row


def book_exists(connection: sqlite3.Connection, book_id: str) -> bool:
    return (
        connection.execute(
            """
            select 1
            from books
            where id = ?
            """,
            (book_id,),
        ).fetchone()
        is not None
    )


def book_summary_from_row(row: sqlite3.Row) -> BookSummary:
    return BookSummary(
        id=row["id"],
        title=row["title"],
        category=row["category"],
        relative_path=row["relative_path"],
        page_count=row["page_count"],
        copy_status=row["copy_status"],
        text_status=row["text_status"],
        search_status=row["search_status"],
        visual_status=row["visual_status"],
        reader_ready=bool(row["reader_ready"]),
        search_ready=bool(row["search_ready"]),
        fully_ready=bool(row["fully_ready"]),
        needs_attention=bool(row["needs_attention"]),
        vector_status=row["vector_status"],
        embedding_provider=row["embedding_provider"],
        embedding_model=row["embedding_model"],
        embedding_dimensions=row["embedding_dimensions"],
    )


def managed_pdf_available(config: AppConfig, row: sqlite3.Row) -> bool:
    if not bool(row["reader_ready"]):
        return False
    try:
        return validate_managed_pdf_path(
            config,
            row["id"],
            row["managed_pdf_path"],
        ).is_file()
    except ManagedPdfPathRejectedError:
        return False


def validate_managed_pdf_path(config: AppConfig, book_id: str, raw_path: str) -> Path:
    managed_root = (config.data_dir / "library" / "pdfs").expanduser().resolve()
    book_root = (managed_root / book_id).resolve()
    path = Path(raw_path).expanduser().resolve()

    if (
        not book_root.is_relative_to(managed_root)
        or not path.is_relative_to(managed_root)
        or not path.is_relative_to(book_root)
    ):
        raise ManagedPdfPathRejectedError(
            f"Managed PDF path is outside the book storage root: {book_id}"
        )
    if path.suffix.lower() != ".pdf":
        raise ManagedPdfPathRejectedError(
            f"Managed PDF path does not reference a PDF: {book_id}"
        )
    return path
