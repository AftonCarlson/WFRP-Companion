from __future__ import annotations

import sqlite3
from pathlib import Path

import fitz
import pytest

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database, open_connection
from wfrp_companion.library import discovery, importer
from wfrp_companion.library.identity import book_id_for, folder_id_for
from wfrp_companion.library.importer import import_pdf_library
from wfrp_companion.library.storage import sha256_file


def make_config(tmp_path: Path, *, root: Path | None = None) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        pdf_root=root or tmp_path / "pdf-root",
        data_dir=data_dir,
        db_path=data_dir / "wfrp_companion.sqlite",
        asset_dir=data_dir / "library" / "assets",
    )


def create_pdf(path: Path, *, pages: int = 1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    document = fitz.open()
    try:
        for _ in range(pages):
            document.new_page()
        document.save(path)
    finally:
        document.close()
    return path


def fetch_one(config: AppConfig, query: str) -> sqlite3.Row:
    with open_connection(config.db_path) as connection:
        row = connection.execute(query).fetchone()
    assert row is not None
    return row


def count_rows(config: AppConfig, table: str) -> int:
    with open_connection(config.db_path) as connection:
        return connection.execute(f"select count(*) from {table}").fetchone()[0]


def test_import_pdf_library_creates_folder_book_job_and_managed_copy(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    pdf_path = create_pdf(
        config.pdf_root
        / "Adventure Modules and Campaigns"
        / "Paths of the Damned"
        / "Ashes of Middenheim.pdf",
        pages=2,
    )

    summary = import_pdf_library(config)

    book_id = book_id_for(config.pdf_root, pdf_path)
    source_sha = sha256_file(pdf_path)
    book = fetch_one(config, "select * from books")
    job = fetch_one(config, "select * from ingest_jobs")

    assert summary.discovered == 1
    assert summary.copied == 1
    assert summary.failed == 0
    assert count_rows(config, "library_folders") == 3
    assert fetch_one(config, "select * from library_folders where id = 'root'")[
        "relative_path"
    ] == ""
    assert fetch_one(
        config,
        "select * from library_folders where relative_path = "
        "'Adventure Modules and Campaigns/Paths of the Damned'",
    )["parent_id"] == folder_id_for(Path("Adventure Modules and Campaigns"))
    assert book["id"] == book_id
    assert book["folder_id"] == folder_id_for(
        Path("Adventure Modules and Campaigns") / "Paths of the Damned"
    )
    assert book["relative_path"] == (
        "Adventure Modules and Campaigns/Paths of the Damned/Ashes of Middenheim.pdf"
    )
    assert book["original_source_path"] == str(pdf_path.resolve())
    assert Path(book["managed_pdf_path"]).is_absolute()
    assert Path(book["managed_pdf_path"]).exists()
    assert book["original_sha256"] == source_sha
    assert book["managed_sha256"] == source_sha
    assert book["page_count"] == 2
    assert book["copy_status"] == "copied"
    assert book["text_status"] == "not_imported"
    assert book["search_status"] == "not_indexed"
    assert book["visual_status"] == "not_scanned"
    assert job["job_type"] == "copy_pdf"
    assert job["target_id"] == book_id
    assert job["status"] == "succeeded"
    assert job["idempotency_key"] == f"copy_pdf:{book_id}:{source_sha}"
    assert job["attempts"] == 1


def test_import_pdf_library_rerun_is_idempotent(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    create_pdf(config.pdf_root / "Core" / "Core Rulebook.pdf")

    first = import_pdf_library(config)
    second = import_pdf_library(config)

    assert first.copied == 1
    assert second.copied == 0
    assert second.skipped_current == 1
    assert count_rows(config, "books") == 1
    assert count_rows(config, "ingest_jobs") == 1


def test_prepare_book_hashes_managed_file_outside_transaction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    pdf_path = create_pdf(config.pdf_root / "Core" / "Core Rulebook.pdf")
    import_pdf_library(config)
    candidate = discovery.discover_pdfs(config.pdf_root)[0]
    source_sha = sha256_file(pdf_path)

    with open_connection(config.db_path) as connection:

        def assert_no_write_transaction(path: Path, expected_sha256: str) -> bool:
            assert connection.in_transaction is False
            assert path.exists()
            assert expected_sha256 == source_sha
            return True

        monkeypatch.setattr(
            importer.storage,
            "managed_file_matches",
            assert_no_write_transaction,
        )

        preparation = importer.prepare_book_for_copy(
            connection,
            candidate=candidate,
            data_dir=config.data_dir,
            source_sha=source_sha,
            page_count=1,
            now="2026-06-03T00:00:00Z",
        )

    assert preparation.copy_needed is False


def test_import_pdf_library_repairs_missing_managed_file(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    create_pdf(config.pdf_root / "Core" / "Core Rulebook.pdf")
    import_pdf_library(config)
    managed_path = Path(fetch_one(config, "select managed_pdf_path from books")[0])
    managed_path.unlink()

    summary = import_pdf_library(config)

    book = fetch_one(config, "select * from books")
    job = fetch_one(config, "select * from ingest_jobs")
    assert summary.repaired == 1
    assert summary.copied == 1
    assert Path(book["managed_pdf_path"]).exists()
    assert book["copy_status"] == "copied"
    assert job["status"] == "succeeded"
    assert job["attempts"] == 2


def test_source_change_moves_to_new_versioned_managed_file(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    pdf_path = create_pdf(config.pdf_root / "Core" / "Core Rulebook.pdf", pages=1)
    import_pdf_library(config)
    old_book = fetch_one(config, "select * from books")
    old_path = Path(old_book["managed_pdf_path"])

    create_pdf(pdf_path, pages=2)
    summary = import_pdf_library(config)

    new_book = fetch_one(config, "select * from books")
    new_path = Path(new_book["managed_pdf_path"])
    assert summary.copied == 1
    assert new_book["page_count"] == 2
    assert new_book["original_sha256"] != old_book["original_sha256"]
    assert new_path != old_path
    assert old_path.exists()
    assert new_path.exists()
    assert new_path.name == f"source-{new_book['original_sha256']}.pdf"


def test_source_change_keeps_old_managed_path_when_new_copy_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    pdf_path = create_pdf(config.pdf_root / "Core" / "Core Rulebook.pdf", pages=1)
    import_pdf_library(config)
    old_book = fetch_one(config, "select * from books")

    create_pdf(pdf_path, pages=2)

    def fail_copy(source_path: Path, target_path: Path) -> str:
        raise OSError(f"copy failed for {source_path} -> {target_path}")

    monkeypatch.setattr(importer.storage, "copy_pdf_atomic", fail_copy)

    summary = import_pdf_library(config)

    failed_book = fetch_one(config, "select * from books")
    assert summary.failed == 1
    assert failed_book["page_count"] == 2
    assert failed_book["original_sha256"] != old_book["original_sha256"]
    assert failed_book["managed_pdf_path"] == old_book["managed_pdf_path"]
    assert failed_book["managed_sha256"] == old_book["managed_sha256"]
    assert failed_book["copy_status"] == "failed"


def test_copy_hash_mismatch_marks_book_and_job_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    create_pdf(config.pdf_root / "Core" / "Core Rulebook.pdf")

    def wrong_hash_copy(source_path: Path, target_path: Path) -> str:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(source_path.read_bytes())
        return "0" * 64

    monkeypatch.setattr(importer.storage, "copy_pdf_atomic", wrong_hash_copy)

    summary = import_pdf_library(config)

    book = fetch_one(config, "select * from books")
    job = fetch_one(config, "select * from ingest_jobs")
    assert summary.failed == 1
    assert book["copy_status"] == "failed"
    assert job["status"] == "failed"
    assert "Managed SHA mismatch" in job["last_error"]


def test_import_skips_copy_when_job_claim_is_not_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    create_pdf(config.pdf_root / "Core" / "Core Rulebook.pdf")

    monkeypatch.setattr(importer, "claim_copy_job", lambda *_args, **_kwargs: False)

    summary = import_pdf_library(config)

    book = fetch_one(config, "select * from books")
    job = fetch_one(config, "select * from ingest_jobs")
    assert summary.copied == 0
    assert summary.failed == 0
    assert book["copy_status"] == "discovered"
    assert job["status"] == "queued"


def test_corrupt_pdf_records_failed_job_without_book_row(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    corrupt = config.pdf_root / "Core" / "Broken.pdf"
    corrupt.parent.mkdir(parents=True, exist_ok=True)
    corrupt.write_bytes(b"not a pdf")

    summary = import_pdf_library(config)

    job = fetch_one(config, "select * from ingest_jobs")
    assert summary.discovered == 1
    assert summary.failed == 1
    assert len(summary.failures) == 1
    assert summary.failures[0].relative_path == "Core/Broken.pdf"
    assert summary.failures[0].book_id == book_id_for(config.pdf_root, corrupt)
    assert "Failed to open PDF" in summary.failures[0].reason
    assert count_rows(config, "books") == 0
    assert job["status"] == "failed"
    assert job["target_id"] == book_id_for(config.pdf_root, corrupt)
    assert "Failed to open PDF" in job["last_error"]


def test_book_id_collision_fails_without_overwriting_state(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    create_pdf(config.pdf_root / "A+B.pdf")
    create_pdf(config.pdf_root / "A B.pdf")

    summary = import_pdf_library(config)

    assert summary.discovered == 2
    assert summary.failed == 2
    assert len(summary.failures) == 2
    assert {failure.relative_path for failure in summary.failures} == {
        "A+B.pdf",
        "A B.pdf",
    }
    assert all("Book id collision" in failure.reason for failure in summary.failures)
    assert count_rows(config, "books") == 0
    assert count_rows(config, "ingest_jobs") == 2


def test_existing_book_id_collision_fails_during_prepare(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    pdf_path = create_pdf(config.pdf_root / "A+B.pdf")
    source_sha = sha256_file(pdf_path)
    existing_book_id = book_id_for(config.pdf_root, pdf_path)
    with initialize_database(config.db_path) as connection:
        connection.execute(
            """
            insert into library_folders (id, parent_id, name, relative_path)
            values ('root', null, 'Library', '')
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
              page_count,
              copy_status,
              text_status,
              search_status,
              visual_status,
              discovered_at,
              updated_at
            )
            values (?, 'root', 'Other', '', 'Other.pdf', ?, ?, ?, 1,
                    'discovered', 'not_imported', 'not_indexed', 'not_scanned',
                    '2026-06-03T00:00:00Z', '2026-06-03T00:00:00Z')
            """,
            (
                existing_book_id,
                str(pdf_path.resolve()),
                str(config.data_dir / "library" / "pdfs" / "old.pdf"),
                source_sha,
            ),
        )
        connection.commit()

    summary = import_pdf_library(config)

    assert summary.failed == 1
    assert len(summary.failures) == 1
    assert summary.failures[0].relative_path == "A+B.pdf"
    assert "Book id collision" in summary.failures[0].reason
    assert count_rows(config, "books") == 1
    assert fetch_one(config, "select relative_path from books")["relative_path"] == (
        "Other.pdf"
    )


def test_folder_id_collision_fails_without_overwriting_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    create_pdf(config.pdf_root / "A+B" / "One.pdf")
    create_pdf(config.pdf_root / "A B" / "Two.pdf")

    def colliding_folder_id(relative_folder: Path) -> str:
        return "root" if relative_folder in {Path("."), Path("")} else "same-folder"

    monkeypatch.setattr(discovery, "folder_id_for", colliding_folder_id)

    summary = import_pdf_library(config)

    assert summary.discovered == 2
    assert summary.failed == 2
    assert len(summary.failures) == 2
    assert all("Folder id collision" in failure.reason for failure in summary.failures)
    assert count_rows(config, "books") == 0
    assert count_rows(config, "ingest_jobs") == 2


def test_existing_folder_id_collision_fails_during_prepare(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    create_pdf(config.pdf_root / "Core" / "Core Rulebook.pdf")
    core_folder_id = folder_id_for(Path("Core"))
    with initialize_database(config.db_path) as connection:
        connection.execute(
            """
            insert into library_folders (id, parent_id, name, relative_path)
            values (?, null, 'Different', 'Different')
            """,
            (core_folder_id,),
        )
        connection.commit()

    summary = import_pdf_library(config)

    assert summary.failed == 1
    assert len(summary.failures) == 1
    assert "Folder id collision" in summary.failures[0].reason
    assert count_rows(config, "books") == 0


def test_record_candidate_failure_handles_source_hash_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    pdf_path = create_pdf(config.pdf_root / "Core" / "Core Rulebook.pdf")
    candidate = discovery.discover_pdfs(config.pdf_root)[0]

    def fail_hash(path: Path) -> str:
        raise OSError(f"cannot hash {path}")

    monkeypatch.setattr(importer.storage, "sha256_file", fail_hash)

    with initialize_database(config.db_path) as connection:
        failure = importer.record_candidate_failure(
            connection,
            candidate=candidate,
            reason="Book id collision for core-core-rulebook",
            now="2026-06-03T00:00:00Z",
        )

    assert failure.relative_path == "Core/Core Rulebook.pdf"
    assert failure.book_id == book_id_for(config.pdf_root, pdf_path)
    assert "failed to hash source: OSError" in failure.reason
    assert count_rows(config, "ingest_jobs") == 0


def test_stale_running_job_is_recovered_and_copied(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    pdf_path = create_pdf(config.pdf_root / "Core" / "Core Rulebook.pdf")
    import_pdf_library(config)
    book_id = book_id_for(config.pdf_root, pdf_path)
    source_sha = sha256_file(pdf_path)
    managed_path = fetch_one(config, "select managed_pdf_path from books")[0]

    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update books
            set copy_status = 'copying'
            where id = ?
            """,
            (book_id,),
        )
        connection.execute(
            """
            update ingest_jobs
            set status = 'running', updated_at = '2020-01-01T00:00:00Z'
            where idempotency_key = ?
            """,
            (f"copy_pdf:{book_id}:{source_sha}",),
        )
        connection.commit()

    summary = import_pdf_library(config, stale_running_minutes=1)

    book = fetch_one(config, "select * from books")
    job = fetch_one(config, "select * from ingest_jobs")
    assert summary.stale_recovered == 1
    assert summary.repaired == 1
    assert summary.copied == 1
    assert book["copy_status"] == "copied"
    assert Path(book["managed_pdf_path"]) == Path(managed_path)
    assert job["status"] == "succeeded"
    assert job["attempts"] == 2


def test_retry_running_recovers_current_running_job(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    pdf_path = create_pdf(config.pdf_root / "Core" / "Core Rulebook.pdf")
    import_pdf_library(config)
    book_id = book_id_for(config.pdf_root, pdf_path)
    source_sha = sha256_file(pdf_path)
    with open_connection(config.db_path) as connection:
        connection.execute("update books set copy_status = 'copying' where id = ?", (book_id,))
        connection.execute(
            """
            update ingest_jobs
            set status = 'running', updated_at = '2999-01-01T00:00:00Z'
            where idempotency_key = ?
            """,
            (f"copy_pdf:{book_id}:{source_sha}",),
        )
        connection.commit()

    summary = import_pdf_library(config, retry_running=True)

    assert summary.stale_recovered == 1
    assert summary.copied == 1
    assert fetch_one(config, "select status from ingest_jobs")["status"] == "succeeded"


def test_claim_copy_job_returns_false_when_rows_are_not_claimable(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        assert (
            importer.claim_copy_job(
                connection,
                book_id="missing",
                job_id="missing",
                now="2026-06-03T00:00:00Z",
            )
            is False
        )


def test_claim_copy_job_rolls_back_and_reraises_on_execute_error() -> None:
    class BrokenConnection:
        rolled_back = False

        def execute(self, _query: str, _params: object = ()) -> object:
            raise RuntimeError("database is busy")

        def rollback(self) -> None:
            self.rolled_back = True

    connection = BrokenConnection()

    with pytest.raises(RuntimeError, match="database is busy"):
        importer.claim_copy_job(
            connection,  # type: ignore[arg-type]
            book_id="core-rules",
            job_id="job",
            now="2026-06-03T00:00:00Z",
        )

    assert connection.rolled_back is True


def test_import_pdf_library_handles_empty_source_root(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    config.pdf_root.mkdir(parents=True)

    summary = import_pdf_library(config)

    assert summary.discovered == 0
    assert summary.copied == 0
    assert summary.failed == 0
    assert count_rows(config, "books") == 0
