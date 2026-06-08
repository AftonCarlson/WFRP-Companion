from __future__ import annotations

from pathlib import Path

import pytest

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.library import catalog


def make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        pdf_root=tmp_path / "pdf-root",
        data_dir=data_dir,
        db_path=data_dir / "wfrp_companion.sqlite",
        asset_dir=data_dir / "library" / "assets",
    )


def managed_pdf(config: AppConfig, book_id: str, filename: str = "source-sha.pdf") -> Path:
    path = config.data_dir / "library" / "pdfs" / book_id / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\nbody\n%%EOF\n")
    return path


def seed_book(
    config: AppConfig,
    *,
    book_id: str = "core-rules",
    title: str = "Core Rules",
    category: str = "Core Book & GM Essentials",
    managed_path: Path | None = None,
    copy_status: str = "copied",
    text_status: str = "imported",
    search_status: str = "indexed",
) -> Path:
    path = managed_pdf(config, book_id) if managed_path is None else managed_path
    with initialize_database(config.db_path) as connection:
        connection.execute(
            """
            insert into library_folders (id, parent_id, name, relative_path, sort_order)
            values ('core', null, 'Core', 'Core', 0)
            on conflict(id) do nothing
            """
        )
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
            values (?, 'core', ?, ?, ?, ?, ?, ?, ?, 2, ?, ?, ?, 'not_scanned',
                    '2026-06-04T00:00:00Z', '2026-06-04T00:00:00Z')
            """,
            (
                book_id,
                title,
                category,
                f"{category}/{title}.pdf",
                f"/source/{book_id}.pdf",
                str(path),
                f"sha-{book_id}",
                f"sha-{book_id}" if copy_status == "copied" else None,
                copy_status,
                text_status,
                search_status,
            ),
        )
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
              has_text
            )
            values (?, ?, 1, 'i', 'ocr', 0, 42, 7, 1, 1, 1)
            """,
            (f"{book_id}:1", book_id),
        )
    return path


def test_list_books_and_get_book_expose_readiness_without_paths(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_book(config)

    books = catalog.list_books(config)
    detail = catalog.get_book(config, "core-rules")

    assert books == (
        catalog.BookSummary(
            id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            relative_path="Core Book & GM Essentials/Core Rules.pdf",
            page_count=2,
            copy_status="copied",
            text_status="imported",
            search_status="indexed",
            visual_status="not_scanned",
            reader_ready=True,
            search_ready=True,
            fully_ready=False,
            needs_attention=False,
            vector_status="disabled",
            embedding_provider=None,
            embedding_model=None,
            embedding_dimensions=None,
        ),
    )
    assert detail.managed_pdf_available is True


def test_get_book_and_page_reject_missing_rows(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_book(config)

    with pytest.raises(catalog.BookNotFoundError, match="missing-book"):
        catalog.get_book(config, "missing-book")

    with pytest.raises(catalog.BookNotFoundError, match="missing-book"):
        catalog.get_page(config, "missing-book", 1)

    with pytest.raises(catalog.PageNotFoundError, match="core-rules p. 9"):
        catalog.get_page(config, "core-rules", 9)


def test_get_page_returns_page_reference_without_text(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_book(config)

    page = catalog.get_page(config, "core-rules", 1)

    assert page == catalog.PageReference(
        page_id="core-rules:1",
        book_id="core-rules",
        page_number=1,
        page_label="i",
        has_text=True,
        text_chars=42,
        image_count=1,
    )


def test_get_page_text_requires_search_ready_book(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_book(config, search_status="not_indexed")
    with initialize_database(config.db_path) as connection:
        connection.execute(
            """
            insert into page_text (page_id, text, text_sha256, generated_at)
            values ('core-rules:1', 'private text', 'text-sha',
                    '2026-06-04T00:00:00Z')
            """
        )

    with pytest.raises(catalog.PageTextUnavailableError, match="core-rules"):
        catalog.get_page_text(config, "core-rules", 1)


def test_reader_pdf_path_requires_ready_managed_pdf(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    pdf_path = seed_book(config)

    assert catalog.reader_pdf_path(config, "core-rules") == pdf_path.resolve()


def test_reader_pdf_path_rejects_unready_missing_and_unsafe_paths(
    tmp_path: Path,
) -> None:
    not_ready = make_config(tmp_path / "not-ready")
    seed_book(not_ready, copy_status="discovered", text_status="not_imported")

    missing = make_config(tmp_path / "missing")
    missing_path = missing.data_dir / "library" / "pdfs" / "core-rules" / "missing.pdf"
    seed_book(missing, managed_path=missing_path)

    outside = make_config(tmp_path / "outside")
    outside_path = tmp_path / "outside.pdf"
    outside_path.write_bytes(b"%PDF-1.4\noutside\n%%EOF\n")
    seed_book(outside, managed_path=outside_path)

    path_like_book = make_config(tmp_path / "path-like-book")
    path_like_path = path_like_book.data_dir / "library" / "outside.pdf"
    path_like_path.parent.mkdir(parents=True, exist_ok=True)
    path_like_path.write_bytes(b"%PDF-1.4\noutside\n%%EOF\n")
    seed_book(path_like_book, book_id="..", managed_path=path_like_path)

    wrong_suffix = make_config(tmp_path / "wrong-suffix")
    wrong_path = managed_pdf(wrong_suffix, "core-rules", "source-sha.txt")
    seed_book(wrong_suffix, managed_path=wrong_path)

    with pytest.raises(catalog.ReaderUnavailableError):
        catalog.reader_pdf_path(not_ready, "core-rules")

    with pytest.raises(catalog.ManagedPdfMissingError):
        catalog.reader_pdf_path(missing, "core-rules")

    with pytest.raises(catalog.ManagedPdfPathRejectedError):
        catalog.reader_pdf_path(outside, "core-rules")

    with pytest.raises(catalog.ManagedPdfPathRejectedError):
        catalog.reader_pdf_path(path_like_book, "..")

    with pytest.raises(catalog.ManagedPdfPathRejectedError):
        catalog.reader_pdf_path(wrong_suffix, "core-rules")
