from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # pragma: no cover

from wfrp_companion.config import AppConfig, load_config
from wfrp_companion.library.page_labels import (
    PageLabelAnchor,
    PageLabelBackfillSummary,
    backfill_page_labels,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill calibrated printed page labels for imported books."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Private app data directory. Defaults to WFRP_DATA_DIR or data/.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="SQLite database path. Defaults to WFRP_DB_PATH or <data-dir>/wfrp_companion.sqlite.",
    )
    parser.add_argument(
        "--book-id",
        action="append",
        default=None,
        help="Backfill one book id. Repeat to backfill several specific books.",
    )
    parser.add_argument(
        "--anchor",
        action="append",
        default=None,
        help=(
            "Per-book page offset anchor in book_id:pdf_page_number:printed_label "
            "form. Repeat for multiple books."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even when page-label calibration is current.",
    )
    parser.add_argument(
        "--retry-running",
        action="store_true",
        help="Recover all running page-label backfill jobs before rebuilding.",
    )
    parser.add_argument(
        "--stale-running-minutes",
        type=int,
        default=30,
        help="Recover running page-label jobs older than this many minutes. Default: 30.",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> AppConfig:
    config = load_config()
    data_dir = args.data_dir or config.data_dir
    db_path = args.db_path or (
        data_dir / "wfrp_companion.sqlite" if args.data_dir else config.db_path
    )
    return replace(config, data_dir=data_dir, db_path=db_path)


def parse_anchor(value: str) -> tuple[str, PageLabelAnchor]:
    parts = value.split(":", 2)
    if len(parts) != 3 or not parts[0]:
        raise ValueError("Anchor must use book_id:pdf_page_number:printed_label.")
    try:
        pdf_page_number = int(parts[1])
    except ValueError as exc:
        raise ValueError("PDF page must be an integer.") from exc
    if pdf_page_number < 1:
        raise ValueError("PDF page must be 1 or greater.")
    printed_label = " ".join(parts[2].split())
    if not printed_label:
        raise ValueError("Printed label must not be blank.")
    return parts[0], PageLabelAnchor(
        pdf_page_number=pdf_page_number,
        printed_label=printed_label,
    )


def anchors_from_args(values: Sequence[str] | None) -> dict[str, PageLabelAnchor]:
    anchors: dict[str, PageLabelAnchor] = {}
    for value in values or ():
        book_id, anchor = parse_anchor(value)
        anchors[book_id] = anchor
    return anchors


def print_summary(config: AppConfig, summary: PageLabelBackfillSummary) -> None:
    print("WFRP page-label backfill")
    print(f"DB path: {config.db_path}")
    print(f"Books discovered: {summary.discovered}")
    print(f"Books calibrated: {summary.calibrated}")
    print(f"Books needing review: {summary.needs_review}")
    print(f"Skipped current: {summary.skipped_current}")
    print(f"Stale recovered: {summary.stale_recovered}")
    print(f"Failed: {summary.failed}")
    print(f"Pages calibrated: {summary.pages_calibrated}")
    print(f"Manual review pages: {summary.manual_review_pages}")
    for failure in summary.failures:
        print(f"Failure {failure.book_id}: {safe_failure_reason(failure.reason)}")


def safe_failure_reason(reason: str, *, max_chars: int = 120) -> str:
    normalized = " ".join(reason.split())
    if not normalized:
        return "failure"
    error_type, separator, _details = normalized.partition(":")
    if separator and error_type.replace("_", "").replace(".", "").isalnum():
        return error_type[:max_chars]
    if len(normalized) <= max_chars:
        return "failure"
    return "failure"


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        anchors = anchors_from_args(args.anchor)
    except ValueError as error:
        parser.error(str(error))
    config = config_from_args(args)
    summary = backfill_page_labels(
        config,
        book_ids=None if args.book_id is None else tuple(args.book_id),
        anchors=anchors,
        force=args.force,
        retry_running=args.retry_running,
        stale_running_minutes=args.stale_running_minutes,
    )
    print_summary(config, summary)
    return 1 if summary.failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
