from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # pragma: no cover

from wfrp_companion.config import AppConfig
from wfrp_companion.config import load_config
from wfrp_companion.library.page_labels import PageLabelBackfillSummary
from wfrp_companion.library.page_labels import backfill_page_labels
from wfrp_companion.library.retrieval_status import RetrievalStatus
from wfrp_companion.library.retrieval_status import get_retrieval_status
from wfrp_companion.search.fts import FtsRebuildSummary
from wfrp_companion.search.fts import rebuild_global_fts
from wfrp_companion.source_objects.embeddings import EmbeddingRebuildSummary
from wfrp_companion.source_objects.embeddings import rebuild_embeddings
from wfrp_companion.source_objects.extractor import ExtractionSummary
from wfrp_companion.source_objects.extractor import extract_source_object_library
from wfrp_companion.source_objects.source_map_builder import SourceMapRebuildSummary
from wfrp_companion.source_objects.source_map_builder import rebuild_source_maps
from wfrp_companion.source_objects.store import ObjectSearchRebuildSummary
from wfrp_companion.source_objects.store import rebuild_source_object_search
from wfrp_companion.structured_evidence.store import (
    StructuredEvidenceExtractionSummary,
)
from wfrp_companion.structured_evidence.store import (
    extract_structured_evidence_library,
)


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


@dataclass(frozen=True)
class RetrievalAssetRebuildSummary:
    fts: FtsRebuildSummary
    extraction: ExtractionSummary
    object_search: ObjectSearchRebuildSummary
    structured: StructuredEvidenceExtractionSummary
    source_maps: SourceMapRebuildSummary
    page_labels: PageLabelBackfillSummary
    embeddings: EmbeddingRebuildSummary
    status: RetrievalStatus

    @property
    def failed_steps(self) -> int:
        return sum(
            1
            for failed in (
                self.fts.failed,
                self.extraction.failed,
                self.object_search.failed,
                self.structured.failed,
                self.source_maps.failed,
                self.page_labels.failed,
                self.embeddings.failed,
            )
            if failed
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rebuild all local retrieval assets for Familiar."
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
        help="Limit source-object, map, label, and embedding rebuilds to one book id. Repeat for several books.",
    )
    parser.add_argument(
        "--embedding-provider",
        default=None,
        help="Embedding provider. Use local-hash for deterministic local embeddings.",
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
        "--embedding-batch-size",
        type=int,
        default=None,
        help="Embedding document batch size for local model inference.",
    )
    parser.add_argument(
        "--embedding-device",
        default=None,
        help="Optional local embedding device, such as cpu, cuda, or mps.",
    )
    parser.add_argument(
        "--embedding-query-prompt-name",
        default=None,
        help="Optional query prompt name for instruction-aware embedding models.",
    )
    parser.add_argument(
        "--embedding-local-files-only",
        action="store_true",
        default=None,
        help="Load local embedding model files only; do not download from the hub.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild every supported retrieval asset even if current.",
    )
    parser.add_argument(
        "--retry-running",
        action="store_true",
        help="Recover running retrieval rebuild jobs before rebuilding.",
    )
    parser.add_argument(
        "--stale-running-minutes",
        type=positive_int,
        default=30,
        help="Recover running jobs older than this many minutes. Default: 30.",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> AppConfig:
    config = load_config()
    data_dir = args.data_dir or config.data_dir
    db_path = args.db_path or (
        data_dir / "wfrp_companion.sqlite" if args.data_dir else config.db_path
    )
    return replace(
        config,
        data_dir=data_dir,
        db_path=db_path,
        embedding_provider=args.embedding_provider or config.embedding_provider,
        embedding_model=args.embedding_model or config.embedding_model,
        embedding_dimensions=(
            args.embedding_dimensions
            if args.embedding_dimensions is not None
            else config.embedding_dimensions
        ),
        embedding_batch_size=(
            args.embedding_batch_size
            if args.embedding_batch_size is not None
            else config.embedding_batch_size
        ),
        embedding_device=(
            args.embedding_device
            if args.embedding_device is not None
            else config.embedding_device
        ),
        embedding_query_prompt_name=(
            args.embedding_query_prompt_name
            if args.embedding_query_prompt_name is not None
            else config.embedding_query_prompt_name
        ),
        embedding_local_files_only=(
            args.embedding_local_files_only
            if args.embedding_local_files_only is not None
            else config.embedding_local_files_only
        ),
    )


def rebuild_retrieval_assets(
    config: AppConfig,
    *,
    book_ids: tuple[str, ...] | None,
    force: bool,
    retry_running: bool,
    stale_running_minutes: int,
) -> RetrievalAssetRebuildSummary:
    fts = rebuild_global_fts(
        config,
        force=force,
        retry_running=retry_running,
        stale_running_minutes=stale_running_minutes,
    )
    extraction = extract_source_object_library(
        config,
        book_ids=book_ids,
        force=force,
        retry_running=retry_running,
        stale_running_minutes=stale_running_minutes,
    )
    object_search = rebuild_source_object_search(
        config,
        book_ids=book_ids,
        force=force,
        retry_running=retry_running,
        stale_running_minutes=stale_running_minutes,
    )
    structured = extract_structured_evidence_library(
        config,
        book_ids=book_ids,
        force=force,
        retry_running=retry_running,
        stale_running_minutes=stale_running_minutes,
    )
    source_maps = rebuild_source_maps(
        config,
        book_ids=book_ids,
        force=force,
        retry_running=retry_running,
        stale_running_minutes=stale_running_minutes,
    )
    page_labels = backfill_page_labels(
        config,
        book_ids=book_ids,
        force=force,
        retry_running=retry_running,
        stale_running_minutes=stale_running_minutes,
    )
    embeddings = rebuild_embeddings(
        config,
        book_ids=book_ids,
        force=force,
        retry_running=retry_running,
        stale_running_minutes=stale_running_minutes,
    )
    status = get_retrieval_status(config)
    return RetrievalAssetRebuildSummary(
        fts=fts,
        extraction=extraction,
        object_search=object_search,
        structured=structured,
        source_maps=source_maps,
        page_labels=page_labels,
        embeddings=embeddings,
        status=status,
    )


def print_summary(config: AppConfig, summary: RetrievalAssetRebuildSummary) -> None:
    status = summary.status
    print("WFRP retrieval asset rebuild")
    print(f"DB path: {config.db_path}")
    print(f"FTS books indexed: {summary.fts.books_indexed}")
    print(f"FTS pages indexed: {summary.fts.pages_indexed}")
    print(f"Source object books extracted: {summary.extraction.extracted}")
    print(f"Source objects written: {summary.extraction.objects_written}")
    print(f"Source object FTS books indexed: {summary.object_search.indexed}")
    print(f"Structured candidates written: {summary.structured.candidates_written}")
    print(f"Structured needs review: {summary.structured.needs_review}")
    print(f"Source maps indexed: {summary.source_maps.indexed}")
    print(f"Page-label books calibrated: {summary.page_labels.calibrated}")
    print(f"Embeddings indexed: {summary.embeddings.indexed}")
    print(f"Embeddings written: {summary.embeddings.embeddings_written}")
    print(f"Books total: {status.books_total}")
    print(f"Books enabled: {status.books_enabled}")
    print(f"Page text indexed: {status.page_text_indexed}")
    print(f"Source-object books indexed: {status.source_objects_indexed}")
    print(f"Table/stat books indexed: {status.table_or_stat_indexed}")
    print(f"Structured candidates total: {status.structured_candidates}")
    print(f"Structured candidates needing review: {status.structured_needs_review}")
    print(f"Validated structured active: {status.validated_structured_active}")
    print(f"Vectorized current books: {status.vectorized_current}")
    print(f"Vectorized enabled books: {status.vectorized_enabled}")
    print(f"Embedding provider: {status.embedding_provider}")
    print(f"Embedding dimensions: {status.embedding_dimensions or 'none'}")
    print(f"Vector status: {status.vector_status}")
    print(f"Failed steps: {summary.failed_steps}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = config_from_args(args)
    summary = rebuild_retrieval_assets(
        config,
        book_ids=None if args.book_id is None else tuple(args.book_id),
        force=args.force,
        retry_running=args.retry_running,
        stale_running_minutes=args.stale_running_minutes,
    )
    print_summary(config, summary)
    return 1 if summary.failed_steps else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
