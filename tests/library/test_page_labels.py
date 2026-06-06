from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database, open_connection
from wfrp_companion.library import page_labels
from wfrp_companion.library.page_labels import PageLabelAnchor


def make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        pdf_root=tmp_path / "pdf-root",
        data_dir=data_dir,
        db_path=data_dir / "wfrp_companion.sqlite",
        asset_dir=data_dir / "library" / "assets",
    )


def insert_imported_book(
    connection: sqlite3.Connection,
    *,
    book_id: str = "core-rules",
    page_count: int = 4,
) -> None:
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
        values (?, 'core', 'Core Rules', 'Core', 'core.pdf', '/source/core.pdf',
                '/managed/core.pdf', 'source-sha', 'managed-sha', ?,
                'copied', 'imported', 'indexed', 'not_scanned',
                '2026-06-05T00:00:00Z', '2026-06-05T00:00:00Z')
        """
        ,
        (book_id, page_count),
    )


def insert_page(
    connection: sqlite3.Connection,
    *,
    book_id: str = "core-rules",
    page_number: int,
    text: str,
    page_label: str | None,
) -> None:
    page_id = f"{book_id}:{page_number}"
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
        values (?, ?, ?, ?, 'ocr', 0, ?, ?, 0, 1, 1)
        """,
        (page_id, book_id, page_number, page_label, len(text), len(text.split())),
    )
    connection.execute(
        """
        insert into page_text (page_id, text, text_sha256, generated_at)
        values (?, ?, ?, '2026-06-05T00:00:00Z')
        """,
        (page_id, text, f"sha-{page_id}"),
    )


def seed_pages(config: AppConfig, labels: tuple[str | None, ...]) -> None:
    with initialize_database(config.db_path) as connection:
        insert_imported_book(connection, page_count=len(labels))
        for index, label in enumerate(labels, start=1):
            insert_page(
                connection,
                page_number=index,
                page_label=label,
                text=f"Public synthetic page {index} label {label or 'missing'}",
            )


def calibration_json(config: AppConfig, book_id: str = "core-rules") -> dict[str, object]:
    with open_connection(config.db_path) as connection:
        row = connection.execute(
            """
            select calibration_json
            from book_page_label_calibrations
            where book_id = ?
            """,
            (book_id,),
        ).fetchone()
    assert row is not None
    decoded = json.loads(row["calibration_json"])
    assert isinstance(decoded, dict)
    return decoded


def test_backfill_calibrates_offset_and_preserves_roman_front_matter(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_pages(config, ("i", "ii", None, None))

    summary = page_labels.backfill_page_labels(
        config,
        anchors={"core-rules": PageLabelAnchor(pdf_page_number=3, printed_label="1")},
    )

    metadata = calibration_json(config)
    assert summary.discovered == 1
    assert summary.calibrated == 1
    assert summary.needs_review == 0
    assert summary.skipped_current == 0
    assert summary.failed == 0
    assert summary.pages_calibrated == 4
    assert summary.manual_review_pages == 0
    assert metadata["labels_by_page"] == {"1": "i", "2": "ii", "3": "1", "4": "2"}
    assert metadata["anchor"] == {"pdf_page_number": 3, "printed_label": "1"}

    with open_connection(config.db_path) as connection:
        status = connection.execute(
            """
            select page_label_status, page_text_snapshot_sha256, last_error
            from book_retrieval_status
            where book_id = 'core-rules'
            """
        ).fetchone()
        calibration = connection.execute(
            """
            select status, method, page_text_snapshot_sha256
            from book_page_label_calibrations
            where book_id = 'core-rules'
            """
        ).fetchone()
        job = connection.execute(
            """
            select job_type, status, attempts, idempotency_key
            from ingest_jobs
            where job_type = 'backfill_page_labels'
            """
        ).fetchone()
        assert page_labels.load_calibrated_page_label(
            connection,
            book_id="core-rules",
            page_number=3,
            fallback_label=None,
        ) == "1"
        assert page_labels.load_calibrated_page_range_label(
            connection,
            book_id="core-rules",
            page_start=2,
            page_end=4,
        ) == "ii-2"
        assert page_labels.load_calibrated_printed_page_range_label(
            connection,
            book_id="core-rules",
            page_start=3,
            page_end=3,
        ) == "1"
        assert page_labels.load_calibrated_printed_page_range_label(
            connection,
            book_id="core-rules",
            page_start=3,
            page_end=4,
        ) == "1-2"

    assert status["page_label_status"] == "calibrated"
    assert status["page_text_snapshot_sha256"] == calibration["page_text_snapshot_sha256"]
    assert status["last_error"] is None
    assert calibration["status"] == "calibrated"
    assert calibration["method"] == "offset_anchor"
    assert job["job_type"] == "backfill_page_labels"
    assert job["status"] == "succeeded"
    assert job["attempts"] == 1
    assert job["idempotency_key"].startswith("backfill_page_labels:core-rules:")

    rerun = page_labels.backfill_page_labels(
        config,
        anchors={"core-rules": PageLabelAnchor(pdf_page_number=3, printed_label="1")},
    )

    assert rerun.skipped_current == 1
    assert rerun.calibrated == 0


def test_backfill_marks_missing_unanchored_labels_needs_review(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_pages(config, (None, "10"))

    summary = page_labels.backfill_page_labels(config)

    metadata = calibration_json(config)
    assert summary.discovered == 1
    assert summary.calibrated == 0
    assert summary.needs_review == 1
    assert summary.pages_calibrated == 1
    assert summary.manual_review_pages == 1
    assert metadata["labels_by_page"] == {"2": "10"}
    assert metadata["missing_label_pages"] == [1]

    with open_connection(config.db_path) as connection:
        status = connection.execute(
            """
            select page_label_status, last_error
            from book_retrieval_status
            where book_id = 'core-rules'
            """
        ).fetchone()
        calibration = connection.execute(
            """
            select status, method
            from book_page_label_calibrations
            where book_id = 'core-rules'
            """
        ).fetchone()
        assert page_labels.load_calibrated_page_label(
            connection,
            book_id="core-rules",
            page_number=1,
            fallback_label=None,
        ) == "1"
        assert page_labels.load_calibrated_page_label(
            connection,
            book_id="core-rules",
            page_number=2,
            fallback_label=None,
        ) == "10"
        assert (
            page_labels.load_calibrated_printed_page_label(
                connection,
                book_id="core-rules",
                page_number=1,
                fallback_label=None,
            )
            is None
        )
        assert page_labels.load_calibrated_printed_page_label(
            connection,
            book_id="core-rules",
            page_number=2,
            fallback_label=None,
        ) == "10"

    assert status["page_label_status"] == "needs_review"
    assert status["last_error"] == "1 page label needs manual review."
    assert calibration["status"] == "needs_review"
    assert calibration["method"] == "imported_labels_partial"


def test_anchor_backfill_rebuilds_prior_needs_review_without_force(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_pages(config, (None, None))
    initial = page_labels.backfill_page_labels(config)

    anchored = page_labels.backfill_page_labels(
        config,
        anchors={"core-rules": PageLabelAnchor(pdf_page_number=1, printed_label="1")},
    )

    metadata = calibration_json(config)
    assert initial.needs_review == 1
    assert anchored.calibrated == 1
    assert anchored.skipped_current == 0
    assert metadata["labels_by_page"] == {"1": "1", "2": "2"}
    assert metadata["anchor"] == {"pdf_page_number": 1, "printed_label": "1"}


def test_plain_backfill_preserves_current_anchor_calibration(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_pages(config, (None, None))
    page_labels.backfill_page_labels(
        config,
        anchors={"core-rules": PageLabelAnchor(pdf_page_number=1, printed_label="20")},
    )

    plain = page_labels.backfill_page_labels(config)

    metadata = calibration_json(config)
    assert plain.skipped_current == 1
    assert plain.needs_review == 0
    assert metadata["labels_by_page"] == {"1": "20", "2": "21"}
    assert metadata["anchor"] == {"pdf_page_number": 1, "printed_label": "20"}


def test_plain_backfill_reuses_stored_anchor_after_snapshot_drift(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_pages(config, (None, None))
    page_labels.backfill_page_labels(
        config,
        anchors={"core-rules": PageLabelAnchor(pdf_page_number=1, printed_label="20")},
    )

    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update page_text
            set text_sha256 = 'sha-after-ocr-refresh'
            where page_id = 'core-rules:1'
            """
        )
        refreshed_snapshot = page_labels.page_label_snapshot_sha256(
            connection,
            "core-rules",
        )

    plain = page_labels.backfill_page_labels(config)

    metadata = calibration_json(config)
    assert plain.calibrated == 1
    assert plain.skipped_current == 0
    assert metadata["labels_by_page"] == {"1": "20", "2": "21"}
    assert metadata["anchor"] == {"pdf_page_number": 1, "printed_label": "20"}
    with open_connection(config.db_path) as connection:
        row = connection.execute(
            """
            select page_text_snapshot_sha256
            from book_page_label_calibrations
            where book_id = 'core-rules'
            """
        ).fetchone()
    assert row["page_text_snapshot_sha256"] == refreshed_snapshot


def test_plain_backfill_keeps_stored_anchor_after_failed_drift_rerun(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_pages(config, (None, None))
    page_labels.backfill_page_labels(
        config,
        anchors={"core-rules": PageLabelAnchor(pdf_page_number=1, printed_label="20")},
    )
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update page_text
            set text_sha256 = 'sha-after-ocr-refresh'
            where page_id = 'core-rules:1'
            """
        )

    original_builder = page_labels.build_page_label_calibration
    failures_remaining = 1

    def fail_once(*args, **kwargs):
        nonlocal failures_remaining
        if failures_remaining:
            failures_remaining -= 1
            raise RuntimeError("transient calibration failure")
        return original_builder(*args, **kwargs)

    monkeypatch.setattr(page_labels, "build_page_label_calibration", fail_once)

    failed = page_labels.backfill_page_labels(config)
    recovered = page_labels.backfill_page_labels(config)

    metadata = calibration_json(config)
    assert failed.failed == 1
    assert recovered.calibrated == 1
    assert metadata["labels_by_page"] == {"1": "20", "2": "21"}
    assert metadata["anchor"] == {"pdf_page_number": 1, "printed_label": "20"}


def test_force_rebuild_updates_current_anchor_calibration(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_pages(config, ("i", "ii", None, None))
    page_labels.backfill_page_labels(
        config,
        anchors={"core-rules": PageLabelAnchor(pdf_page_number=3, printed_label="1")},
    )

    summary = page_labels.backfill_page_labels(
        config,
        anchors={"core-rules": PageLabelAnchor(pdf_page_number=3, printed_label="20")},
        force=True,
    )

    metadata = calibration_json(config)
    assert summary.calibrated == 1
    assert summary.skipped_current == 0
    assert metadata["labels_by_page"] == {"1": "i", "2": "ii", "3": "20", "4": "21"}
    with open_connection(config.db_path) as connection:
        job = connection.execute(
            """
            select attempts
            from ingest_jobs
            where job_type = 'backfill_page_labels'
            """
        ).fetchone()
    assert job["attempts"] == 2


def test_backfill_records_count_only_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_pages(config, ("1",))

    def fail_calibration(*args, **kwargs):
        raise RuntimeError("forced calibration failure")

    monkeypatch.setattr(page_labels, "build_page_label_calibration", fail_calibration)

    summary = page_labels.backfill_page_labels(config)

    assert summary.failed == 1
    assert summary.failures[0].book_id == "core-rules"
    assert summary.failures[0].reason == "RuntimeError: forced calibration failure"
    with open_connection(config.db_path) as connection:
        status = connection.execute(
            """
            select page_label_status, last_error
            from book_retrieval_status
            where book_id = 'core-rules'
            """
        ).fetchone()
        job = connection.execute(
            """
            select status, last_error
            from ingest_jobs
            where job_type = 'backfill_page_labels'
            """
        ).fetchone()

    assert status["page_label_status"] == "failed"
    assert status["last_error"] == "RuntimeError: forced calibration failure"
    assert job["status"] == "failed"
    assert job["last_error"] == "RuntimeError: forced calibration failure"


def test_retry_running_recovers_stale_page_label_jobs(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_pages(config, ("1",))
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            insert into book_retrieval_status (
              book_id,
              page_label_status,
              updated_at
            )
            values ('core-rules', 'calibrating', '2026-06-05T00:00:00Z')
            on conflict(book_id) do update set
              page_label_status = excluded.page_label_status,
              updated_at = excluded.updated_at
            """
        )
        connection.execute(
            """
            insert into ingest_jobs (
              id,
              job_type,
              target_id,
              status,
              idempotency_key,
              attempts,
              created_at,
              updated_at
            )
            values (
              'backfill_page_labels:core-rules:old:page-label-calibration-v1',
              'backfill_page_labels',
              'core-rules',
              'running',
              'backfill_page_labels:core-rules:old:page-label-calibration-v1',
              1,
              '2026-06-05T00:00:00Z',
              '2026-06-05T00:00:00Z'
            )
            """
        )

    summary = page_labels.backfill_page_labels(config, retry_running=True)

    assert summary.stale_recovered == 1
    assert summary.calibrated == 1
    with open_connection(config.db_path) as connection:
        recovered = connection.execute(
            """
            select status, last_error
            from ingest_jobs
            where id = 'backfill_page_labels:core-rules:old:page-label-calibration-v1'
            """
        ).fetchone()
    assert recovered["status"] == "failed"
    assert recovered["last_error"] == "Recovered stale page-label backfill job."


def test_calibrated_label_helpers_fallback_for_missing_or_malformed_state(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_pages(config, ("9",))
    with open_connection(config.db_path) as connection:
        assert page_labels.load_calibrated_page_label(
            connection,
            book_id="core-rules",
            page_number=1,
            fallback_label="9",
        ) == "9"
        assert page_labels.load_calibrated_printed_page_label(
            connection,
            book_id="core-rules",
            page_number=1,
            fallback_label=" 9 ",
        ) == "9"
        assert page_labels.load_raw_page_labels(
            connection,
            book_id="core-rules",
            page_numbers=(1,),
        ) == {1: "9"}
        assert (
            page_labels.load_calibrated_printed_page_range_label(
                connection,
                book_id="core-rules",
                page_start=1,
                page_end=99,
            )
            is None
        )
        assert page_labels.load_calibrated_page_range_label(
            connection,
            book_id="core-rules",
            page_start=1,
            page_end=1,
        ) == "9"
        connection.execute(
            """
            insert into book_page_label_calibrations (
              book_id,
              status,
              method,
              calibration_json,
              page_text_snapshot_sha256,
              updated_at
            )
            values (
              'core-rules',
              'calibrated',
              'imported_labels',
              '{bad json',
              ?,
              '2026-06-05T00:00:00Z'
            )
            """,
            (page_labels.page_label_snapshot_sha256(connection, "core-rules"),),
        )
        assert page_labels.load_calibrated_page_label(
            connection,
            book_id="core-rules",
            page_number=1,
            fallback_label=None,
        ) == "9"
        assert page_labels.load_calibrated_printed_page_label(
            connection,
            book_id="core-rules",
            page_number=1,
            fallback_label=None,
        ) == "9"


def test_backfill_initializes_missing_database_and_handles_empty_selection(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)

    missing_db = page_labels.backfill_page_labels(config)
    empty_selection = page_labels.backfill_page_labels(config, book_ids=())

    assert missing_db.discovered == 0
    assert empty_selection.discovered == 0
    assert config.db_path.exists()


def test_eligible_books_honors_explicit_book_ids(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_pages(config, ("1",))

    with open_connection(config.db_path) as connection:
        assert page_labels.eligible_books(
            connection,
            book_ids=("core-rules", "missing-book"),
        ) == ("core-rules",)


def test_backfill_skips_running_book_without_retry(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_pages(config, ("1",))
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            insert into book_retrieval_status (
              book_id,
              page_label_status,
              updated_at
            )
            values ('core-rules', 'calibrating', '2026-06-05T00:00:00Z')
            on conflict(book_id) do update set
              page_label_status = excluded.page_label_status,
              updated_at = excluded.updated_at
            """
        )

    summary = page_labels.backfill_page_labels(config)

    assert summary.skipped_current == 1
    assert summary.failed == 0


def test_backfill_reports_claim_failure_for_current_running_job(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_pages(config, ("1",))
    with open_connection(config.db_path) as connection:
        snapshot = page_labels.page_label_snapshot_sha256(connection, "core-rules")
        job_id = page_labels.page_label_backfill_job_id("core-rules", snapshot)
        now = page_labels.utc_timestamp()
        connection.execute(
            """
            insert into book_retrieval_status (book_id, updated_at)
            values ('core-rules', ?)
            on conflict(book_id) do nothing
            """,
            (now,),
        )
        connection.execute(
            """
            insert into ingest_jobs (
              id,
              job_type,
              target_id,
              status,
              idempotency_key,
              attempts,
              created_at,
              updated_at
            )
            values (
              ?,
              'backfill_page_labels',
              'core-rules',
              'running',
              ?,
              1,
              ?,
              ?
            )
            """,
            (job_id, job_id, now, now),
        )

    summary = page_labels.backfill_page_labels(config)

    assert summary.failed == 1
    assert summary.failures[0].reason == "Could not claim page-label backfill job."
    with open_connection(config.db_path) as connection:
        calibration = connection.execute(
            """
            select status, last_error
            from book_page_label_calibrations
            where book_id = 'core-rules'
            """
        ).fetchone()
    assert calibration["status"] == "failed"
    assert calibration["last_error"] == "Could not claim page-label backfill job."


def test_page_label_currentness_rejects_stale_and_malformed_rows(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_pages(config, ("1",))
    with open_connection(config.db_path) as connection:
        snapshot = page_labels.page_label_snapshot_sha256(connection, "core-rules")
        connection.execute(
            """
            insert into book_page_label_calibrations (
              book_id,
              status,
              method,
              calibration_json,
              page_text_snapshot_sha256,
              updated_at
            )
            values (
              'core-rules',
              'calibrating',
              'pending',
              '{}',
              ?,
              '2026-06-05T00:00:00Z'
            )
            """,
            (snapshot,),
        )
        assert not page_labels.page_label_calibration_current(
            connection,
            book_id="core-rules",
            page_text_snapshot=snapshot,
        )
        connection.execute(
            """
            update book_page_label_calibrations
            set status = 'calibrated',
                page_text_snapshot_sha256 = 'old'
            where book_id = 'core-rules'
            """
        )
        assert not page_labels.page_label_calibration_current(
            connection,
            book_id="core-rules",
            page_text_snapshot=snapshot,
        )
        connection.execute(
            """
            update book_page_label_calibrations
            set page_text_snapshot_sha256 = ?,
                calibration_json = '{bad json'
            where book_id = 'core-rules'
            """,
            (snapshot,),
        )
        assert not page_labels.page_label_calibration_current(
            connection,
            book_id="core-rules",
            page_text_snapshot=snapshot,
        )
        connection.execute(
            """
            update book_page_label_calibrations
            set calibration_json = '{"schema_version":1,"builder_version":"page-label-calibration-v1","page_count":1,"anchor":{"not":"valid"}}',
                page_text_snapshot_sha256 = ?
            where book_id = 'core-rules'
            """,
            (snapshot,),
        )
        assert not page_labels.page_label_calibration_current(
            connection,
            book_id="core-rules",
            page_text_snapshot=snapshot,
            anchor=PageLabelAnchor(pdf_page_number=1, printed_label="1"),
        )


def test_calibration_anchor_matching_edges() -> None:
    assert page_labels.calibration_anchor_matches({"anchor": None}, None)
    assert page_labels.calibration_anchor_matches({"anchor": {"bad": "shape"}}, None)
    assert not page_labels.calibration_anchor_matches(
        {"anchor": None},
        PageLabelAnchor(pdf_page_number=1, printed_label="1"),
    )


def test_build_calibration_surfaces_anchor_errors_and_conflicts(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_imported_book(connection, page_count=0)
        no_pages_error = None
        try:
            page_labels.build_page_label_calibration(
                connection,
                book_id="core-rules",
                anchor=None,
            )
        except ValueError as error:
            no_pages_error = str(error)
    assert no_pages_error == "No imported pages found for core-rules."

    config = make_config(tmp_path / "anchored")
    seed_pages(config, ("9", "10"))
    with open_connection(config.db_path) as connection:
        missing_anchor_error = None
        try:
            page_labels.build_page_label_calibration(
                connection,
                book_id="core-rules",
                anchor=PageLabelAnchor(pdf_page_number=3, printed_label="1"),
            )
        except ValueError as error:
            missing_anchor_error = str(error)
        non_integer_error = None
        try:
            page_labels.build_page_label_calibration(
                connection,
                book_id="core-rules",
                anchor=PageLabelAnchor(pdf_page_number=1, printed_label="i"),
            )
        except ValueError as error:
            non_integer_error = str(error)
        calibration = page_labels.build_page_label_calibration(
            connection,
            book_id="core-rules",
            anchor=PageLabelAnchor(pdf_page_number=1, printed_label="1"),
        )

    metadata = json.loads(calibration.calibration_json)
    assert missing_anchor_error == "Anchor page 3 is not present for core-rules."
    assert non_integer_error == "Offset anchor printed label must be an integer."
    assert calibration.status == "needs_review"
    assert calibration.method == "offset_anchor_needs_review"
    assert metadata["conflicting_label_pages"] == [
        {"page_number": 1, "imported_label": "9", "calibrated_label": "1"},
        {"page_number": 2, "imported_label": "10", "calibrated_label": "2"},
    ]


def test_manual_review_conflicts_do_not_return_confident_printed_labels(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_pages(config, ("9", "10"))

    summary = page_labels.backfill_page_labels(
        config,
        anchors={"core-rules": PageLabelAnchor(pdf_page_number=1, printed_label="1")},
    )

    assert summary.needs_review == 1
    with open_connection(config.db_path) as connection:
        assert page_labels.load_calibrated_page_labels(
            connection,
            book_id="core-rules",
            page_numbers=(1, 2),
        ) == {}
        assert (
            page_labels.load_calibrated_printed_page_label(
                connection,
                book_id="core-rules",
                page_number=1,
                fallback_label="9",
            )
            is None
        )
        assert (
            page_labels.load_calibrated_printed_page_range_label(
                connection,
                book_id="core-rules",
                page_start=1,
                page_end=2,
            )
            is None
        )
        assert page_labels.page_label_needs_manual_review(
            connection,
            book_id="core-rules",
            page_number=2,
        )


def test_manual_review_page_number_parser_ignores_invalid_entries() -> None:
    metadata = {
        "missing_label_pages": ["1", 0, "bad"],
        "conflicting_label_pages": [
            {"page_number": "2"},
            {"page_number": -1},
            {"not_page_number": 3},
            "bad shape",
        ],
    }

    assert page_labels.calibration_manual_review_page_numbers(metadata) == {1, 2}


def test_claim_and_recovery_edge_helpers(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_pages(config, ("1",))
    with open_connection(config.db_path) as connection:
        assert not page_labels.claim_page_label_job(
            connection,
            book_id="core-rules",
            page_text_snapshot="snapshot",
            job_id="job",
            force=False,
            now="2026-06-05T00:00:00Z",
        )
        assert page_labels.page_label_claim_failure(connection, "missing-book") is None
        connection.execute(
            """
            insert into ingest_jobs (
              id,
              job_type,
              target_id,
              status,
              idempotency_key,
              attempts,
              created_at,
              updated_at
            )
            values (
              'backfill_page_labels:orphan',
              'backfill_page_labels',
              null,
              'running',
              'backfill_page_labels:orphan',
              1,
              '2026-06-05T00:00:00Z',
              '2026-06-05T00:00:00Z'
            )
            """
        )
        recovered = page_labels.recover_stale_page_label_jobs(
            connection,
            retry_running=True,
            stale_running_minutes=30,
        )

    assert recovered == 1


def test_label_helper_edge_cases(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_pages(config, ("1",))
    with open_connection(config.db_path) as connection:
        assert page_labels.load_raw_page_labels(
            connection,
            book_id="core-rules",
            page_numbers=(),
        ) == {}
        assert page_labels.load_calibrated_page_labels(
            connection,
            book_id="core-rules",
            page_numbers=(),
        ) == {}
        snapshot = page_labels.page_label_snapshot_sha256(connection, "core-rules")
        connection.execute(
            """
            insert into book_page_label_calibrations (
              book_id,
              status,
              method,
              calibration_json,
              page_text_snapshot_sha256,
              updated_at
            )
            values (
              'core-rules',
              'calibrating',
              'pending',
              '{}',
              ?,
              '2026-06-05T00:00:00Z'
            )
            """,
            (snapshot,),
        )
        assert page_labels.load_calibrated_page_labels(
            connection,
            book_id="core-rules",
            page_numbers=(1,),
        ) == {}
        connection.execute(
            """
            update book_page_label_calibrations
            set status = 'calibrated',
                page_text_snapshot_sha256 = 'old'
            where book_id = 'core-rules'
            """
        )
        assert page_labels.load_calibrated_page_labels(
            connection,
            book_id="core-rules",
            page_numbers=(1,),
        ) == {}
        connection.execute(
            """
            update book_page_label_calibrations
            set page_text_snapshot_sha256 = ?,
                calibration_json = '{"labels_by_page":[]}'
            where book_id = 'core-rules'
            """,
            (snapshot,),
        )
        assert page_labels.load_calibrated_page_labels(
            connection,
            book_id="core-rules",
            page_numbers=(1,),
        ) == {}
        assert (
            page_labels.load_calibrated_printed_page_label(
                connection,
                book_id="core-rules",
                page_number=99,
                fallback_label=None,
            )
            is None
        )

    assert page_labels.decode_calibration_json(None) is None


def test_existing_anchor_loader_rejects_malformed_rows(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_pages(config, ("1",))
    with open_connection(config.db_path) as connection:
        snapshot = page_labels.page_label_snapshot_sha256(connection, "core-rules")
        assert page_labels.load_existing_page_label_anchor(connection, "core-rules") is None
        connection.execute(
            """
            insert into book_page_label_calibrations (
              book_id,
              status,
              method,
              calibration_json,
              page_text_snapshot_sha256,
              updated_at
            )
            values (
              'core-rules',
              'failed',
              'imported_labels',
              '{}',
              ?,
              '2026-06-05T00:00:00Z'
            )
            """,
            (snapshot,),
        )
        assert page_labels.load_existing_page_label_anchor(connection, "core-rules") is None
        connection.execute(
            """
            update book_page_label_calibrations
            set status = 'needs_review',
                calibration_json = '{bad json'
            where book_id = 'core-rules'
            """
        )
        assert page_labels.load_existing_page_label_anchor(connection, "core-rules") is None
        assert not page_labels.page_label_needs_manual_review(
            connection,
            book_id="core-rules",
            page_number=1,
        )
        invalid_metadata = (
            '{"anchor":[]}',
            '{"anchor":{"pdf_page_number":1}}',
            '{"anchor":{"pdf_page_number":"bad","printed_label":"1"}}',
            '{"anchor":{"pdf_page_number":0,"printed_label":"1"}}',
        )
        for metadata in invalid_metadata:
            connection.execute(
                """
                update book_page_label_calibrations
                set calibration_json = ?
                where book_id = 'core-rules'
                """,
                (metadata,),
            )
            assert page_labels.load_existing_page_label_anchor(connection, "core-rules") is None

        connection.execute(
            """
            update book_page_label_calibrations
            set calibration_json =
                '{"anchor":{"pdf_page_number":1,"printed_label":" 10 "}}'
            where book_id = 'core-rules'
            """
        )

        assert page_labels.load_existing_page_label_anchor(
            connection,
            "core-rules",
        ) == PageLabelAnchor(pdf_page_number=1, printed_label="10")
