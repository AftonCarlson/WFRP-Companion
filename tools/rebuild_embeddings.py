from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # pragma: no cover

from wfrp_companion.config import AppConfig, load_config
from wfrp_companion.source_objects.embeddings import (
    EmbeddingRebuildSummary,
    rebuild_embeddings,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rebuild local source-object embeddings."
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
        "--embedding-provider",
        default=None,
        help="Embedding provider. Use local-hash to enable the local MVP.",
    )
    parser.add_argument(
        "--embedding-model",
        default=None,
        help="Embedding model name recorded in SQLite.",
    )
    parser.add_argument(
        "--embedding-dimensions",
        type=int,
        default=None,
        help="Embedding vector dimensions.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even when the embedding projection is current.",
    )
    parser.add_argument(
        "--retry-running",
        action="store_true",
        help="Recover all running embedding rebuild jobs before rebuilding.",
    )
    parser.add_argument(
        "--stale-running-minutes",
        type=int,
        default=30,
        help="Recover running embedding jobs older than this many minutes. Default: 30.",
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
        openai_api_key=config.openai_api_key,
        openai_model=config.openai_model,
        openai_timeout_seconds=config.openai_timeout_seconds,
        chat_context_hit_limit=config.chat_context_hit_limit,
        chat_context_char_limit=config.chat_context_char_limit,
        chat_context_window_chars=config.chat_context_window_chars,
        embedding_provider=args.embedding_provider or config.embedding_provider,
        embedding_model=args.embedding_model or config.embedding_model,
        embedding_dimensions=(
            args.embedding_dimensions
            if args.embedding_dimensions is not None
            else config.embedding_dimensions
        ),
    )


def print_summary(config: AppConfig, summary: EmbeddingRebuildSummary) -> None:
    print("WFRP embedding rebuild")
    print(f"DB path: {config.db_path}")
    print(f"Embedding provider: {config.embedding_provider}")
    print(f"Embedding model: {config.embedding_model}")
    print(f"Embedding dimensions: {config.embedding_dimensions}")
    print(f"Books discovered: {summary.discovered}")
    print(f"Books indexed: {summary.indexed}")
    print(f"Skipped current: {summary.skipped_current}")
    print(f"Skipped disabled: {summary.skipped_disabled}")
    print(f"Stale recovered: {summary.stale_recovered}")
    print(f"Failed: {summary.failed}")
    print(f"Embeddings written: {summary.embeddings_written}")
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
    summary = rebuild_embeddings(
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
