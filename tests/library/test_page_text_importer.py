from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import fitz

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database, open_connection
from wfrp_companion.library import page_text_importer
from wfrp_companion.library.page_text_importer import import_page_text_library


def make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        pdf_root=tmp_path / "pdf-root",
        data_dir=data_dir,
        db_path=data_dir / "wfrp_companion.sqlite",
        asset_dir=data_dir / "library" / "assets",
    )


def insert_copied_book(
    config: AppConfig,
    *,
    book_id: str = "core-rules",
    source_sha: str = "source-sha",
    page_count: int = 2,
    copy_status: str = "copied",
    text_status: str = "not_imported",
    search_status: str = "not_indexed",
    managed_pdf_path: str = "/managed/Core Rules.pdf",
) -> None:
    with initialize_database(config.db_path) as connection:
        connection.execute(
            """
            insert into library_folders (
              id, parent_id, name, relative_path, sort_order
            )
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
            values (?, 'core', 'Core Rules', 'Core', 'Core/Core Rules.pdf',
                    '/source/Core Rules.pdf', ?,
                    ?, ?, ?, ?, ?, ?, 'not_scanned',
                    '2026-06-04T00:00:00Z', '2026-06-04T00:00:00Z')
            """,
            (
                book_id,
                managed_pdf_path,
                source_sha,
                source_sha if copy_status == "copied" else None,
                page_count,
                copy_status,
                text_status,
                search_status,
            ),
        )


def page_text_document(
    *,
    book_id: str = "core-rules",
    source_sha: str = "source-sha",
    page_count: int = 2,
) -> dict[str, object]:
    return {
        "book_id": book_id,
        "title": "Core Rules",
        "category": "Core",
        "source_path": "/source/Core Rules.pdf",
        "source_sha256": source_sha,
        "page_count": page_count,
        "generated_at": "2026-06-04T00:00:00Z",
        "ocr_language": "eng",
        "ocr_dpi": 200,
        "low_text_chars_threshold": 100,
        "pages": [
            {
                "page_number": 1,
                "text": "Critical hit rules",
                "extraction_method": "ocr",
                "embedded_text_chars": 0,
                "text_chars": 18,
                "word_count": 3,
                "image_count": 1,
                "ocr_attempted": True,
                "ocr_error": None,
            },
            {
                "page_number": 2,
                "text": "",
                "extraction_method": "ocr-empty",
                "embedded_text_chars": 0,
                "text_chars": 0,
                "word_count": 0,
                "image_count": 2,
                "ocr_attempted": True,
                "ocr_error": None,
            },
        ],
    }


def write_page_text(
    input_dir: Path,
    document: dict[str, object],
    *,
    filename: str | None = None,
) -> Path:
    input_dir.mkdir(parents=True, exist_ok=True)
    path = input_dir / (filename or f"{document['book_id']}.json")
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def parsed_document_and_sha(
    input_dir: Path,
) -> tuple[page_text_importer.BookTextRecord, str]:
    path = write_page_text(input_dir, page_text_document())
    content = path.read_bytes()
    json_sha = hashlib.sha256(content).hexdigest()
    return (
        page_text_importer.parse_book_text(
            content,
            relative_path=path.name,
            json_sha256=json_sha,
        ),
        json_sha,
    )


def fetch_one(config: AppConfig, query: str) -> sqlite3.Row:
    with open_connection(config.db_path) as connection:
        row = connection.execute(query).fetchone()
    assert row is not None
    return row


def count_rows(config: AppConfig, table: str) -> int:
    with open_connection(config.db_path) as connection:
        return connection.execute(f"select count(*) from {table}").fetchone()[0]


def test_import_page_text_creates_pages_text_and_import_job(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    write_page_text(config.data_dir / "page_text", page_text_document())

    summary = import_page_text_library(config)

    page = fetch_one(config, "select * from pages where page_number = 1")
    empty_page = fetch_one(config, "select * from pages where page_number = 2")
    text = fetch_one(config, "select * from page_text where page_id = 'core-rules:1'")
    book = fetch_one(config, "select * from books where id = 'core-rules'")
    job = fetch_one(config, "select * from ingest_jobs")
    assert summary.discovered == 1
    assert summary.imported == 1
    assert summary.pages_imported == 2
    assert summary.failed == 0
    assert page["id"] == "core-rules:1"
    assert page["extraction_method"] == "ocr"
    assert page["ocr_attempted"] == 1
    assert page["has_text"] == 1
    assert empty_page["has_text"] == 0
    assert text["text"] == "Critical hit rules"
    assert text["text_sha256"] == hashlib.sha256(b"Critical hit rules").hexdigest()
    assert book["text_status"] == "imported"
    assert book["search_status"] == "not_indexed"
    assert job["job_type"] == "import_page_text"
    assert job["target_id"] == "core-rules"
    assert job["status"] == "succeeded"
    assert job["attempts"] == 1


def test_import_page_text_preserves_json_page_labels(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    document = page_text_document()
    pages = document["pages"]
    assert isinstance(pages, list)
    pages[0]["page_label"] = " 132 "
    pages[1]["page_label"] = " "
    write_page_text(config.data_dir / "page_text", document)

    summary = import_page_text_library(config)

    page = fetch_one(config, "select page_label from pages where page_number = 1")
    empty_label_page = fetch_one(
        config,
        "select page_label from pages where page_number = 2",
    )
    assert summary.imported == 1
    assert page["page_label"] == "132"
    assert empty_label_page["page_label"] is None


def test_import_page_text_reads_pdf_page_labels_when_json_has_none(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    pdf_path = tmp_path / "managed.pdf"
    document = fitz.open()
    document.new_page()
    document.new_page()
    document.set_page_labels(
        [{"startpage": 0, "style": "D", "firstpagenum": 132}]
    )
    document.save(pdf_path)
    document.close()
    insert_copied_book(config, managed_pdf_path=str(pdf_path))
    write_page_text(config.data_dir / "page_text", page_text_document())

    first = import_page_text_library(config)
    second = import_page_text_library(config)

    page = fetch_one(config, "select page_label from pages where page_number = 1")
    next_page = fetch_one(config, "select page_label from pages where page_number = 2")
    assert first.imported == 1
    assert second.skipped_current == 1
    assert page["page_label"] == "132"
    assert next_page["page_label"] == "133"


def test_import_page_text_rerun_is_idempotent(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    write_page_text(config.data_dir / "page_text", page_text_document())

    first = import_page_text_library(config)
    second = import_page_text_library(config)

    assert first.imported == 1
    assert second.imported == 0
    assert second.skipped_current == 1
    assert count_rows(config, "pages") == 2
    assert count_rows(config, "page_text") == 2
    assert count_rows(config, "ingest_jobs") == 1


def test_import_rerun_repairs_failed_status_after_prior_success(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    write_page_text(config.data_dir / "page_text", page_text_document())
    import_page_text_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update books
            set text_status = 'failed'
            where id = 'core-rules'
            """
        )
        connection.commit()

    summary = import_page_text_library(config)

    book = fetch_one(config, "select text_status from books where id = 'core-rules'")
    assert summary.imported == 1
    assert summary.skipped_current == 0
    assert book["text_status"] == "imported"


def test_import_rerun_repairs_missing_page_rows_after_prior_success(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    write_page_text(config.data_dir / "page_text", page_text_document())
    import_page_text_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute("delete from pages where book_id = 'core-rules'")
        connection.commit()

    summary = import_page_text_library(config)

    assert summary.imported == 1
    assert count_rows(config, "pages") == 2
    assert count_rows(config, "page_text") == 2


def test_import_current_detects_unexpected_page_number(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    document, json_sha = parsed_document_and_sha(config.data_dir / "page_text")
    import_page_text_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update pages
            set page_number = 99
            where id = 'core-rules:1'
            """
        )
        connection.commit()
        assert not page_text_importer.imported_text_current(
            connection,
            document,
            json_sha,
        )


def test_import_current_detects_unexpected_page_label(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    document, json_sha = parsed_document_and_sha(config.data_dir / "page_text")
    import_page_text_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update pages
            set page_label = 'wrong'
            where id = 'core-rules:1'
            """
        )
        connection.commit()
        assert not page_text_importer.imported_text_current(
            connection,
            document,
            json_sha,
        )


def test_import_current_detects_invalid_metadata_json(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    document, json_sha = parsed_document_and_sha(config.data_dir / "page_text")
    import_page_text_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update pages
            set metadata_json = '{not json'
            where id = 'core-rules:1'
            """
        )
        connection.commit()
        assert not page_text_importer.imported_text_current(
            connection,
            document,
            json_sha,
        )


def test_import_current_detects_json_sha_drift(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    document, json_sha = parsed_document_and_sha(config.data_dir / "page_text")
    import_page_text_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update pages
            set metadata_json = '{"json_sha256": "different"}'
            where id = 'core-rules:1'
            """
        )
        connection.commit()
        assert not page_text_importer.imported_text_current(
            connection,
            document,
            json_sha,
        )


def test_import_current_detects_text_hash_drift(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    document, json_sha = parsed_document_and_sha(config.data_dir / "page_text")
    import_page_text_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update page_text
            set text_sha256 = 'different'
            where page_id = 'core-rules:1'
            """
        )
        connection.commit()
        assert not page_text_importer.imported_text_current(
            connection,
            document,
            json_sha,
        )


def test_import_current_detects_generated_at_drift(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    document, json_sha = parsed_document_and_sha(config.data_dir / "page_text")
    import_page_text_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update page_text
            set generated_at = '2026-06-04T01:00:00Z'
            where page_id = 'core-rules:1'
            """
        )
        connection.commit()
        assert not page_text_importer.imported_text_current(
            connection,
            document,
            json_sha,
        )


def test_force_import_replaces_existing_page_text(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    input_dir = config.data_dir / "page_text"
    document = page_text_document()
    write_page_text(input_dir, document)
    import_page_text_library(config)
    document["pages"][0]["text"] = "Updated critical hit rules"  # type: ignore[index]
    document["pages"][0]["text_chars"] = 26  # type: ignore[index]
    write_page_text(input_dir, document)

    summary = import_page_text_library(config, force=True)

    text = fetch_one(config, "select text from page_text where page_id = 'core-rules:1'")
    assert summary.imported == 1
    assert text["text"] == "Updated critical hit rules"


def test_import_rejects_missing_required_book_field(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    document = page_text_document()
    del document["source_sha256"]
    write_page_text(config.data_dir / "page_text", document)

    summary = import_page_text_library(config)

    book = fetch_one(config, "select text_status from books where id = 'core-rules'")
    job = fetch_one(config, "select * from ingest_jobs")
    assert summary.failed == 1
    assert summary.failures[0].book_id == "core-rules"
    assert "Missing required book field: source_sha256" in summary.failures[0].reason
    assert book["text_status"] == "failed"
    assert job["status"] == "failed"
    assert count_rows(config, "pages") == 0


def test_import_rejects_missing_required_page_field(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    document = page_text_document()
    del document["pages"][0]["text"]  # type: ignore[index]
    write_page_text(config.data_dir / "page_text", document)

    summary = import_page_text_library(config)

    assert summary.failed == 1
    assert "Missing required page field on page 1: text" in (
        summary.failures[0].reason
    )
    assert count_rows(config, "pages") == 0


def test_import_rejects_filename_book_id_mismatch_with_file_job(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    path = write_page_text(
        config.data_dir / "page_text",
        page_text_document(),
        filename="wrong-name.json",
    )
    json_sha = hashlib.sha256(path.read_bytes()).hexdigest()

    summary = import_page_text_library(config)

    job = fetch_one(config, "select * from ingest_jobs")
    assert summary.failed == 1
    assert summary.failures[0].book_id == "core-rules"
    assert "does not match book_id" in summary.failures[0].reason
    assert job["target_id"] is None
    assert job["idempotency_key"] == f"import_page_text_file:wrong-name.json:{json_sha}"


def test_import_records_file_level_failure_for_corrupt_json(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    input_dir = config.data_dir / "page_text"
    input_dir.mkdir(parents=True)
    path = input_dir / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    json_sha = hashlib.sha256(path.read_bytes()).hexdigest()

    summary = import_page_text_library(config)

    job = fetch_one(config, "select * from ingest_jobs")
    assert summary.failed == 1
    assert summary.failures[0].book_id is None
    assert "Invalid JSON" in summary.failures[0].reason
    assert job["target_id"] is None
    assert job["idempotency_key"] == f"import_page_text_file:broken.json:{json_sha}"


def test_repeated_file_level_failure_updates_existing_job(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    input_dir = config.data_dir / "page_text"
    input_dir.mkdir(parents=True)
    (input_dir / "broken.json").write_text("{not json", encoding="utf-8")

    first = import_page_text_library(config)
    second = import_page_text_library(config)

    job = fetch_one(config, "select * from ingest_jobs")
    assert first.failed == 1
    assert second.failed == 1
    assert job["attempts"] == 2


def test_import_records_file_level_failure_for_non_object_json(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    input_dir = config.data_dir / "page_text"
    input_dir.mkdir(parents=True)
    (input_dir / "list.json").write_text("[]", encoding="utf-8")

    summary = import_page_text_library(config)

    assert summary.failed == 1
    assert "root value must be an object" in summary.failures[0].reason


def test_import_records_file_level_failure_for_missing_book_id(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    document = page_text_document()
    del document["book_id"]
    path = write_page_text(
        config.data_dir / "page_text",
        document,
        filename="missing-book-id.json",
    )
    json_sha = hashlib.sha256(path.read_bytes()).hexdigest()

    summary = import_page_text_library(config)

    job = fetch_one(config, "select * from ingest_jobs")
    assert summary.failed == 1
    assert summary.failures[0].book_id is None
    assert "Missing required book field: book_id" in summary.failures[0].reason
    assert job["target_id"] is None
    assert job["idempotency_key"] == (
        f"import_page_text_file:missing-book-id.json:{json_sha}"
    )


def test_import_rejects_empty_book_id_as_file_level_failure(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    document = page_text_document(book_id="")
    write_page_text(config.data_dir / "page_text", document, filename="empty.json")

    summary = import_page_text_library(config)

    job = fetch_one(config, "select * from ingest_jobs")
    assert summary.failed == 1
    assert "Book field must be a non-empty string: book_id" in (
        summary.failures[0].reason
    )
    assert job["target_id"] is None


def test_import_rejects_missing_book_row(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    write_page_text(config.data_dir / "page_text", page_text_document())

    summary = import_page_text_library(config)

    job = fetch_one(config, "select * from ingest_jobs")
    assert summary.failed == 1
    assert "Book is not registered: core-rules" in summary.failures[0].reason
    assert job["target_id"] == "core-rules"
    assert job["status"] == "failed"


def test_import_rejects_book_that_is_not_copied(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config, copy_status="failed")
    write_page_text(config.data_dir / "page_text", page_text_document())

    summary = import_page_text_library(config)

    book = fetch_one(config, "select text_status from books where id = 'core-rules'")
    assert summary.failed == 1
    assert "Book is not copied: core-rules" in summary.failures[0].reason
    assert book["text_status"] == "failed"


def test_import_rejects_source_sha_mismatch(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config, source_sha="expected-sha")
    write_page_text(
        config.data_dir / "page_text",
        page_text_document(source_sha="actual-sha"),
    )

    summary = import_page_text_library(config)

    assert summary.failed == 1
    assert "Source SHA mismatch for core-rules" in summary.failures[0].reason
    assert count_rows(config, "pages") == 0


def test_import_rejects_invalid_source_sha_as_book_failure(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    document = page_text_document()
    document["source_sha256"] = None
    path = write_page_text(config.data_dir / "page_text", document)
    json_sha = hashlib.sha256(path.read_bytes()).hexdigest()

    summary = import_page_text_library(config)

    book = fetch_one(config, "select text_status from books where id = 'core-rules'")
    job = fetch_one(config, "select * from ingest_jobs")
    assert summary.failed == 1
    assert summary.failures[0].book_id == "core-rules"
    assert "Field must be a non-empty string: source_sha256" in (
        summary.failures[0].reason
    )
    assert book["text_status"] == "failed"
    assert job["target_id"] == "core-rules"
    assert job["idempotency_key"] == f"import_page_text:core-rules:{json_sha}"


def test_import_rejects_invalid_page_text_as_book_failure(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    document = page_text_document()
    document["pages"][0]["text"] = None  # type: ignore[index]
    write_page_text(config.data_dir / "page_text", document)

    summary = import_page_text_library(config)

    book = fetch_one(config, "select text_status from books where id = 'core-rules'")
    assert summary.failed == 1
    assert summary.failures[0].book_id == "core-rules"
    assert "Field must be a non-empty string: text" in summary.failures[0].reason
    assert book["text_status"] == "failed"


def test_import_rejects_page_count_mismatch(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config, page_count=3)
    write_page_text(config.data_dir / "page_text", page_text_document(page_count=2))

    summary = import_page_text_library(config)

    assert summary.failed == 1
    assert "Page count mismatch for core-rules" in summary.failures[0].reason


def test_import_rejects_duplicate_or_missing_page_numbers(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    document = page_text_document()
    document["pages"][1]["page_number"] = 1  # type: ignore[index]
    write_page_text(config.data_dir / "page_text", document)

    summary = import_page_text_library(config)

    assert summary.failed == 1
    assert "Page numbers must be exactly 1..2 for core-rules" in (
        summary.failures[0].reason
    )


def test_import_rejects_pages_that_are_not_a_list(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    document = page_text_document()
    document["pages"] = {}
    write_page_text(config.data_dir / "page_text", document)

    summary = import_page_text_library(config)

    assert summary.failed == 1
    assert "Book field must be a list: pages" in summary.failures[0].reason


def test_import_rejects_page_record_that_is_not_an_object(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    document = page_text_document()
    document["pages"][0] = "not-a-page"  # type: ignore[index]
    write_page_text(config.data_dir / "page_text", document)

    summary = import_page_text_library(config)

    assert summary.failed == 1
    assert "Page record must be an object for core-rules" in (
        summary.failures[0].reason
    )


def test_import_rejects_non_integer_page_field(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    document = page_text_document()
    document["pages"][0]["page_number"] = "one"  # type: ignore[index]
    write_page_text(config.data_dir / "page_text", document)

    summary = import_page_text_library(config)

    assert summary.failed == 1
    assert "Field must be an integer: page_number" in summary.failures[0].reason


def test_import_rejects_non_boolean_ocr_attempted(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    document = page_text_document()
    document["pages"][0]["ocr_attempted"] = "yes"  # type: ignore[index]
    write_page_text(config.data_dir / "page_text", document)

    summary = import_page_text_library(config)

    assert summary.failed == 1
    assert "Field must be a boolean: ocr_attempted" in summary.failures[0].reason


def test_import_marks_claimed_job_failed_when_write_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config)
    write_page_text(config.data_dir / "page_text", page_text_document())

    def fail_write(*_args, **_kwargs) -> int:
        raise RuntimeError("write failed")

    monkeypatch.setattr(page_text_importer, "write_book_text", fail_write)

    summary = import_page_text_library(config)

    job = fetch_one(config, "select * from ingest_jobs")
    book = fetch_one(config, "select text_status from books where id = 'core-rules'")
    assert summary.failed == 1
    assert summary.failures[0].reason == "RuntimeError: write failed"
    assert job["status"] == "failed"
    assert book["text_status"] == "failed"


def test_import_marks_claimed_job_failed_when_book_update_is_not_claimable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config, copy_status="failed")
    write_page_text(config.data_dir / "page_text", page_text_document())
    monkeypatch.setattr(
        page_text_importer,
        "validate_book_against_database",
        lambda *_args, **_kwargs: None,
    )

    summary = import_page_text_library(config)

    job = fetch_one(config, "select * from ingest_jobs")
    assert summary.failed == 1
    assert "Book text import is not claimable: core-rules" in (
        summary.failures[0].reason
    )
    assert job["status"] == "failed"


def test_import_recovers_stale_running_job(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config, text_status="importing")
    write_page_text(config.data_dir / "page_text", page_text_document())
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            insert into ingest_jobs (
              id, job_type, target_id, status, idempotency_key, attempts,
              created_at, updated_at
            )
            values (
              'import_page_text:core-rules:old', 'import_page_text',
              'core-rules', 'running', 'import_page_text:core-rules:old',
              1, '2026-06-04T00:00:00Z', '2026-06-04T00:00:00Z'
            )
            """
        )
        connection.commit()

    summary = import_page_text_library(config, stale_running_minutes=0)

    book = fetch_one(config, "select text_status from books where id = 'core-rules'")
    assert summary.stale_recovered == 1
    assert summary.imported == 1
    assert book["text_status"] == "imported"


def test_import_retry_running_recovers_fresh_running_job(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config, text_status="importing")
    write_page_text(config.data_dir / "page_text", page_text_document())
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            insert into ingest_jobs (
              id, job_type, target_id, status, idempotency_key, attempts,
              created_at, updated_at
            )
            values (
              'import_page_text:core-rules:fresh', 'import_page_text',
              'core-rules', 'running', 'import_page_text:core-rules:fresh',
              1, '2099-01-01T00:00:00Z', '2099-01-01T00:00:00Z'
            )
            """
        )
        connection.commit()

    summary = import_page_text_library(config, retry_running=True)

    assert summary.stale_recovered == 1
    assert summary.imported == 1


def test_import_does_not_steal_same_key_fresh_running_job(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_copied_book(config, text_status="importing")
    path = write_page_text(config.data_dir / "page_text", page_text_document())
    json_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    job_id = f"import_page_text:core-rules:{json_sha}"
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            insert into ingest_jobs (
              id, job_type, target_id, status, idempotency_key, attempts,
              created_at, updated_at
            )
            values (?, 'import_page_text', 'core-rules', 'running', ?, 1,
                    '2099-01-01T00:00:00Z', '2099-01-01T00:00:00Z')
            """,
            (job_id, job_id),
        )
        connection.commit()

    summary = import_page_text_library(config)

    job = fetch_one(config, "select * from ingest_jobs where id = '%s'" % job_id)
    book = fetch_one(config, "select text_status from books where id = 'core-rules'")
    assert summary.imported == 0
    assert summary.failed == 0
    assert job["status"] == "running"
    assert job["attempts"] == 1
    assert book["text_status"] == "importing"
