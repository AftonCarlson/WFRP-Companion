from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from wfrp_companion.api.app import create_app
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database


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
    managed_path: Path | None = None,
    copy_status: str = "copied",
    text_status: str = "imported",
    search_status: str = "indexed",
) -> None:
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
            values (?, 'core', 'Core Rules', 'Core Book & GM Essentials',
                    'Core/Core Rules.pdf', ?, ?, ?, ?, 1, ?, ?, ?,
                    'not_scanned', '2026-06-04T00:00:00Z',
                    '2026-06-04T00:00:00Z')
            """,
            (
                book_id,
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
        connection.execute(
            """
            insert into page_text (page_id, text, text_sha256, generated_at)
            values (?, 'private page text must not be returned', 'text-sha',
                    '2026-06-04T00:00:00Z')
            """,
            (f"{book_id}:1",),
        )


def test_books_detail_and_page_routes_return_reader_metadata(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_book(config)
    client = TestClient(create_app(config))

    books_response = client.get("/api/books")
    detail_response = client.get("/api/books/core-rules")
    page_response = client.get("/api/books/core-rules/pages/1")

    assert books_response.status_code == 200
    assert books_response.json()["books"][0]["id"] == "core-rules"
    assert books_response.json()["books"][0]["reader_ready"] is True
    assert "managed_pdf_path" not in books_response.text
    assert detail_response.status_code == 200
    assert detail_response.json()["managed_pdf_available"] is True
    assert "managed_pdf_path" not in detail_response.text
    assert page_response.status_code == 200
    assert page_response.json() == {
        "page_id": "core-rules:1",
        "book_id": "core-rules",
        "page_number": 1,
        "page_label": "i",
        "has_text": True,
        "text_chars": 42,
        "image_count": 1,
    }
    assert "private page text" not in page_response.text


def test_page_text_route_returns_explicit_page_text(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_book(config)
    client = TestClient(create_app(config))

    response = client.get("/api/books/core-rules/pages/1/text")

    assert response.status_code == 200
    assert response.json() == {
        "page_id": "core-rules:1",
        "book_id": "core-rules",
        "page_number": 1,
        "page_label": "i",
        "text": "private page text must not be returned",
        "text_chars": 42,
    }
    assert "managed_pdf_path" not in response.text
    assert "original_source_path" not in response.text


def test_page_text_route_requires_search_ready_book(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_book(config, search_status="not_indexed")
    client = TestClient(create_app(config))

    response = client.get("/api/books/core-rules/pages/1/text")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Page text is unavailable for book: core-rules",
    }


def test_pdf_route_serves_inline_pdf_and_supports_ranges(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_book(config)
    client = TestClient(create_app(config))

    full_response = client.get("/api/books/core-rules/pdf")
    range_response = client.get(
        "/api/books/core-rules/pdf",
        headers={"Range": "bytes=0-3"},
    )
    invalid_range_response = client.get(
        "/api/books/core-rules/pdf",
        headers={"Range": "bytes=999-1000"},
    )

    assert full_response.status_code == 200
    assert full_response.headers["content-type"] == "application/pdf"
    assert full_response.headers["content-disposition"].startswith("inline")
    assert full_response.content.startswith(b"%PDF")
    assert range_response.status_code == 206
    assert range_response.content == b"%PDF"
    assert range_response.headers["content-range"].startswith("bytes 0-3/")
    assert invalid_range_response.status_code == 416


def test_library_routes_map_missing_rows_to_404(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_book(config)
    client = TestClient(create_app(config))

    missing_book = client.get("/api/books/missing-book")
    missing_page = client.get("/api/books/core-rules/pages/9")
    missing_book_text = client.get("/api/books/missing-book/pages/1/text")
    missing_page_text = client.get("/api/books/core-rules/pages/9/text")

    with initialize_database(config.db_path) as connection:
        connection.execute("delete from page_text where page_id = 'core-rules:1'")
    missing_text_row = client.get("/api/books/core-rules/pages/1/text")

    assert missing_book.status_code == 404
    assert missing_page.status_code == 404
    assert missing_book_text.status_code == 404
    assert missing_page_text.status_code == 404
    assert missing_text_row.status_code == 404


def test_pdf_route_maps_unavailable_or_unsafe_files_to_409(tmp_path: Path) -> None:
    not_ready = make_config(tmp_path / "not-ready")
    seed_book(not_ready, copy_status="discovered", text_status="not_imported")

    missing = make_config(tmp_path / "missing")
    missing_path = missing.data_dir / "library" / "pdfs" / "core-rules" / "missing.pdf"
    seed_book(missing, managed_path=missing_path)

    outside = make_config(tmp_path / "outside")
    outside_path = tmp_path / "outside.pdf"
    outside_path.write_bytes(b"%PDF-1.4\noutside\n%%EOF\n")
    seed_book(outside, managed_path=outside_path)

    wrong_suffix = make_config(tmp_path / "wrong-suffix")
    wrong_path = managed_pdf(wrong_suffix, "core-rules", "source-sha.txt")
    seed_book(wrong_suffix, managed_path=wrong_path)

    assert TestClient(create_app(not_ready)).get("/api/books/core-rules/pdf").status_code == 409
    assert TestClient(create_app(missing)).get("/api/books/core-rules/pdf").status_code == 409
    assert TestClient(create_app(outside)).get("/api/books/core-rules/pdf").status_code == 409
    assert (
        TestClient(create_app(wrong_suffix)).get("/api/books/core-rules/pdf").status_code
        == 409
    )
