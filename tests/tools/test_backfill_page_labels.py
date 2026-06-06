from __future__ import annotations

import sqlite3
from pathlib import Path

from tools import backfill_page_labels
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.library.page_labels import PageLabelBackfillFailure


def make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        pdf_root=tmp_path / "pdf-root",
        data_dir=data_dir,
        db_path=data_dir / "wfrp_companion.sqlite",
        asset_dir=data_dir / "library" / "assets",
    )


def seed_imported_book(config: AppConfig) -> None:
    with initialize_database(config.db_path) as connection:
        connection.execute(
            """
            insert into library_folders (id, parent_id, name, relative_path, sort_order)
            values ('core', null, 'Core', 'Core', 0)
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
            values ('core-rules', 'core', 'Core Rules', 'Core', 'core.pdf',
                    '/source/core.pdf', '/managed/core.pdf', 'source-sha',
                    'managed-sha', 2, 'copied', 'imported', 'indexed',
                    'not_scanned', '2026-06-05T00:00:00Z',
                    '2026-06-05T00:00:00Z')
            """
        )
        for page_number, label in ((1, "i"), (2, None)):
            page_id = f"core-rules:{page_number}"
            text = f"Public synthetic page {page_number}"
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
                values (?, 'core-rules', ?, ?, 'ocr', 0, ?, ?, 0, 1, 1)
                """,
                (page_id, page_number, label, len(text), len(text.split())),
            )
            connection.execute(
                """
                insert into page_text (page_id, text, text_sha256, generated_at)
                values (?, ?, ?, '2026-06-05T00:00:00Z')
                """,
                (page_id, text, f"sha-{page_id}"),
            )


def test_backfill_page_labels_tool_prints_count_only_summary(
    capsys,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_imported_book(config)

    exit_code = backfill_page_labels.main(
        [
            "--db-path",
            str(config.db_path),
            "--anchor",
            "core-rules:2:1",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "WFRP page-label backfill" in output
    assert "Books discovered: 1" in output
    assert "Books calibrated: 1" in output
    assert "Pages calibrated: 2" in output
    assert "Public synthetic page" not in output


def test_backfill_page_labels_tool_reports_failures_without_private_text(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_imported_book(config)

    def fail_backfill(*args, **kwargs):
        return backfill_page_labels.PageLabelBackfillSummary(
            discovered=1,
            calibrated=0,
            needs_review=0,
            skipped_current=0,
            stale_recovered=0,
            failed=1,
            pages_calibrated=0,
            manual_review_pages=0,
            failures=(
                PageLabelBackfillFailure(
                    "core-rules",
                    "RuntimeError: private synthetic phrase that should be suppressed",
                ),
            ),
        )

    monkeypatch.setattr(backfill_page_labels, "backfill_page_labels", fail_backfill)

    exit_code = backfill_page_labels.main(["--db-path", str(config.db_path)])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Failed: 1" in output
    assert "Failure core-rules: RuntimeError" in output
    assert "private synthetic phrase" not in output


def test_parse_anchor_rejects_invalid_anchor() -> None:
    try:
        backfill_page_labels.parse_anchor("core-rules:zero:1")
    except ValueError as error:
        assert "PDF page must be an integer" in str(error)
    else:  # pragma: no cover
        raise AssertionError("parse_anchor should reject invalid page numbers")


def test_parse_anchor_rejects_missing_book_negative_page_and_blank_label() -> None:
    invalid_values = (
        (":1:1", "Anchor must use book_id"),
        ("core-rules:0:1", "PDF page must be 1 or greater"),
        ("core-rules:1:   ", "Printed label must not be blank"),
    )

    for value, expected in invalid_values:
        try:
            backfill_page_labels.parse_anchor(value)
        except ValueError as error:
            assert expected in str(error)
        else:  # pragma: no cover
            raise AssertionError(f"parse_anchor should reject {value}")


def test_main_reports_invalid_anchor_as_parser_error(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    try:
        backfill_page_labels.main(
            ["--db-path", str(config.db_path), "--anchor", "core-rules:0:1"]
        )
    except SystemExit as error:
        assert error.code == 2
    else:  # pragma: no cover
        raise AssertionError("main should reject invalid anchors")


def test_safe_failure_reason_keeps_error_class_only() -> None:
    reason = backfill_page_labels.safe_failure_reason(
        "  RuntimeError: one\n two   three  ",
        max_chars=12,
    )

    assert reason == "RuntimeError"


def test_safe_failure_reason_suppresses_untyped_details() -> None:
    reason = backfill_page_labels.safe_failure_reason("  one\n two   three  ", max_chars=12)

    assert reason == "failure"


def test_safe_failure_reason_suppresses_short_untyped_details() -> None:
    assert backfill_page_labels.safe_failure_reason("short") == "failure"


def test_safe_failure_reason_handles_blank_reason() -> None:
    assert backfill_page_labels.safe_failure_reason(" \n ") == "failure"


def test_seed_helper_commits_rows(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_imported_book(config)

    with sqlite3.connect(config.db_path) as connection:
        count = connection.execute("select count(*) from pages").fetchone()[0]

    assert count == 2
