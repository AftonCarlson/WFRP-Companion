from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # pragma: no cover

from wfrp_companion.config import AppConfig, load_config
from wfrp_companion.library.importer import ImportSummary, import_pdf_library


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import owned WFRP PDFs into managed local app storage."
    )
    parser.add_argument(
        "--pdf-root",
        type=Path,
        default=None,
        help="Root folder containing PDFs. Defaults to WFRP_PDF_ROOT.",
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
        "--retry-running",
        action="store_true",
        help="Recover all running copy jobs before import.",
    )
    parser.add_argument(
        "--stale-running-minutes",
        type=int,
        default=30,
        help="Recover running copy jobs older than this many minutes. Default: 30.",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> AppConfig:
    config = load_config()
    pdf_root = args.pdf_root or config.pdf_root
    data_dir = args.data_dir or config.data_dir
    db_path = args.db_path or (
        data_dir / "wfrp_companion.sqlite" if args.data_dir else config.db_path
    )
    return AppConfig(
        pdf_root=pdf_root,
        data_dir=data_dir,
        db_path=db_path,
        asset_dir=config.asset_dir,
    )


def print_summary(config: AppConfig, summary: ImportSummary) -> None:
    print("WFRP PDF library import")
    print(f"PDF root: {config.pdf_root}")
    print(f"DB path: {config.db_path}")
    print(f"Managed PDF root: {config.data_dir / 'library' / 'pdfs'}")
    print(f"Candidates discovered: {summary.discovered}")
    print(f"Copied: {summary.copied}")
    print(f"Skipped current: {summary.skipped_current}")
    print(f"Repaired: {summary.repaired}")
    print(f"Stale recovered: {summary.stale_recovered}")
    print(f"Failed: {summary.failed}")
    if summary.failures:
        print("Failures:")
        for failure in summary.failures:
            print(
                f"- {failure.relative_path} [{failure.book_id}]: {failure.reason}"
            )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = config_from_args(args)

    if not config.pdf_root.exists() or not config.pdf_root.is_dir():
        print(
            f"PDF root does not exist or is not a directory: {config.pdf_root}",
            file=sys.stderr,
        )
        return 1

    summary = import_pdf_library(
        config,
        retry_running=args.retry_running,
        stale_running_minutes=args.stale_running_minutes,
    )
    print_summary(config, summary)
    return 1 if summary.failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
