from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # pragma: no cover

from wfrp_companion.config import AppConfig, load_config
from wfrp_companion.library import source_sets


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage WFRP source sets.")
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

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="Create or sync built-in source sets.")
    subparsers.add_parser("list", help="List source sets.")

    books = subparsers.add_parser("books", help="List books in a source set.")
    books.add_argument("--source-set", required=True, help="Source set id.")

    activate = subparsers.add_parser("activate", help="Set the active source set.")
    activate.add_argument("source_set_id", help="Source set id.")

    enable = subparsers.add_parser("enable", help="Enable a book in a source set.")
    enable.add_argument("source_set_id", help="Source set id.")
    enable.add_argument("book_id", help="Book id.")

    disable = subparsers.add_parser("disable", help="Disable a book in a source set.")
    disable.add_argument("source_set_id", help="Source set id.")
    disable.add_argument("book_id", help="Book id.")
    return parser


def config_from_args(args: argparse.Namespace) -> AppConfig:
    config = load_config()
    data_dir = args.data_dir or config.data_dir
    db_path = args.db_path or (
        data_dir / "wfrp_companion.sqlite" if args.data_dir else config.db_path
    )
    return replace(config, data_dir=data_dir, db_path=db_path)


def print_init_summary(
    config: AppConfig,
    summary: source_sets.SourceSetSyncSummary,
) -> None:
    print("WFRP source sets")
    print(f"DB path: {config.db_path}")
    print(f"Created source sets: {summary.source_sets_created}")
    print(f"Inserted book rows: {summary.book_rows_inserted}")
    print(f"Active source set: {summary.active_source_set_id}")


def print_source_sets(rows: tuple[source_sets.SourceSet, ...]) -> None:
    for row in rows:
        print(f"{row.id} | {row.name} | builtin={1 if row.is_builtin else 0}")


def print_source_set_books(rows: tuple[source_sets.SourceSetBook, ...]) -> None:
    for row in rows:
        print(
            f"enabled={1 if row.enabled else 0} | "
            f"search_ready={1 if row.search_ready else 0} | "
            f"{row.book_id} | {row.title} | {row.category}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = config_from_args(args)

    try:
        if args.command == "init":
            print_init_summary(config, source_sets.ensure_builtin_source_sets(config))
        elif args.command == "list":
            print_source_sets(source_sets.list_source_sets(config))
        elif args.command == "books":
            print_source_set_books(
                source_sets.list_source_set_books(config, args.source_set)
            )
        elif args.command == "activate":
            source_sets.set_active_source_set(config, args.source_set_id)
            print(f"Active source set: {args.source_set_id}")
        elif args.command == "enable":
            source_sets.set_book_enabled(
                config,
                args.source_set_id,
                args.book_id,
                True,
            )
            print(f"Enabled book: {args.book_id} in {args.source_set_id}")
        elif args.command == "disable":
            source_sets.set_book_enabled(
                config,
                args.source_set_id,
                args.book_id,
                False,
            )
            print(f"Disabled book: {args.book_id} in {args.source_set_id}")
    except source_sets.SourceSetError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
