from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # pragma: no cover

from wfrp_companion.config import AppConfig, load_config
from wfrp_companion.library import source_sets
from wfrp_companion.search.fts import SearchHit, search_exact


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search imported WFRP page text with SQLite FTS."
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
        help="Restrict search to a book id. Can be passed more than once.",
    )
    parser.add_argument(
        "--source-set",
        default=None,
        help="Restrict search to enabled, search-ready books in a source set.",
    )
    parser.add_argument(
        "--all-books",
        action="store_true",
        help="Search every indexed book instead of the active source set.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum hits to print. Clamped to 100. Default: 20.",
    )
    parser.add_argument("query", nargs="+", help="Search query.")
    return parser


def validate_search_scope(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> None:
    if args.all_books and args.source_set is not None:
        parser.error("--all-books cannot be combined with --source-set")
    if args.all_books and args.book_id is not None:
        parser.error("--all-books cannot be combined with --book-id")
    if args.source_set is not None and args.book_id is not None:
        parser.error("--source-set cannot be combined with --book-id")


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


def resolve_book_ids(
    config: AppConfig,
    args: argparse.Namespace,
) -> tuple[str, ...] | None:
    if args.all_books:
        return None
    if args.book_id is not None:
        return tuple(args.book_id)
    if args.source_set is not None:
        return source_sets.enabled_book_ids(config, args.source_set)
    return source_sets.enabled_book_ids(config)


def print_hits(config: AppConfig, query: str, hits: tuple[SearchHit, ...]) -> None:
    print("WFRP exact text search")
    print(f"DB path: {config.db_path}")
    print(f"Query: {query}")
    print(f"Hits: {len(hits)}")
    for hit in hits:
        snippet = " ".join(hit.snippet.split())
        print(
            f"{hit.rank}. {hit.title} p. {hit.page_number} "
            f"[{hit.page_id}] {snippet}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_search_scope(parser, args)
    config = config_from_args(args)
    query = " ".join(args.query)
    try:
        book_ids = resolve_book_ids(config, args)
    except source_sets.SourceSetError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    hits = search_exact(config, query, book_ids=book_ids, limit=args.limit)
    print_hits(config, query, hits)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
