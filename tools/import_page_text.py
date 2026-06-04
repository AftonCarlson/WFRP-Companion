from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # pragma: no cover

from wfrp_companion.config import AppConfig, load_config
from wfrp_companion.library.page_text_importer import (
    PageTextImportSummary,
    import_page_text_library,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import private page-level text JSON into SQLite."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        help="Directory containing <book_id>.json page text files. Defaults to <data-dir>/page_text.",
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
        "--force",
        action="store_true",
        help="Replace existing imported page text for matching books.",
    )
    parser.add_argument(
        "--retry-running",
        action="store_true",
        help="Recover all running page-text import jobs before import.",
    )
    parser.add_argument(
        "--stale-running-minutes",
        type=int,
        default=30,
        help="Recover running page-text jobs older than this many minutes. Default: 30.",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> AppConfig:
    config = load_config()
    data_dir = args.data_dir or config.data_dir
    db_path = args.db_path or (
        data_dir / "wfrp_companion.sqlite" if args.data_dir else config.db_path
    )
    return AppConfig(
        pdf_root=config.pdf_root,
        data_dir=data_dir,
        db_path=db_path,
        asset_dir=config.asset_dir,
    )


def input_dir_from_args(config: AppConfig, args: argparse.Namespace) -> Path:
    return args.input_dir or config.data_dir / "page_text"


def print_summary(
    config: AppConfig,
    input_dir: Path,
    summary: PageTextImportSummary,
) -> None:
    print("WFRP page text import")
    print(f"Input dir: {input_dir}")
    print(f"DB path: {config.db_path}")
    print(f"JSON files discovered: {summary.discovered}")
    print(f"Imported: {summary.imported}")
    print(f"Skipped current: {summary.skipped_current}")
    print(f"Stale recovered: {summary.stale_recovered}")
    print(f"Pages imported: {summary.pages_imported}")
    print(f"Failed: {summary.failed}")
    if summary.failures:
        print("Failures:")
        for failure in summary.failures:
            book_id = failure.book_id or "unknown"
            print(f"- {failure.relative_path} [{book_id}]: {failure.reason}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = config_from_args(args)
    input_dir = input_dir_from_args(config, args)

    if not input_dir.exists() or not input_dir.is_dir():
        print(
            f"Input dir does not exist or is not a directory: {input_dir}",
            file=sys.stderr,
        )
        return 1

    summary = import_page_text_library(
        config,
        input_dir=input_dir,
        force=args.force,
        retry_running=args.retry_running,
        stale_running_minutes=args.stale_running_minutes,
    )
    print_summary(config, input_dir, summary)
    return 1 if summary.failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
