from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # pragma: no cover

from wfrp_companion.config import AppConfig, load_config
from wfrp_companion.source_objects.source_map_builder import (
    SourceMapRebuildSummary,
    rebuild_source_maps,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rebuild compact source maps for imported WFRP books."
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
        help="Rebuild one book id. Repeat to rebuild several specific books.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even when the current source-object snapshot is already indexed.",
    )
    parser.add_argument(
        "--retry-running",
        action="store_true",
        help="Recover all running source-map rebuild jobs before rebuilding.",
    )
    parser.add_argument(
        "--stale-running-minutes",
        type=int,
        default=30,
        help="Recover running source-map jobs older than this many minutes. Default: 30.",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> AppConfig:
    config = load_config()
    data_dir = args.data_dir or config.data_dir
    db_path = args.db_path or (
        data_dir / "wfrp_companion.sqlite" if args.data_dir else config.db_path
    )
    return replace(config, data_dir=data_dir, db_path=db_path)


def print_summary(config: AppConfig, summary: SourceMapRebuildSummary) -> None:
    print("WFRP source map rebuild")
    print(f"DB path: {config.db_path}")
    print(f"Books discovered: {summary.discovered}")
    print(f"Books indexed: {summary.indexed}")
    print(f"Skipped current: {summary.skipped_current}")
    print(f"Stale recovered: {summary.stale_recovered}")
    print(f"Failed: {summary.failed}")
    for failure in summary.failures:
        print(f"Failure {failure.book_id}: {safe_failure_reason(failure.reason)}")


def safe_failure_reason(reason: str, *, max_chars: int = 120) -> str:
    normalized = " ".join(reason.split())
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[: max_chars - 3]}..."


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = config_from_args(args)
    summary = rebuild_source_maps(
        config,
        book_ids=None if args.book_id is None else tuple(args.book_id),
        force=args.force,
        retry_running=args.retry_running,
        stale_running_minutes=args.stale_running_minutes,
    )
    print_summary(config, summary)
    return 1 if summary.failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
