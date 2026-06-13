from __future__ import annotations

from pathlib import Path

import pytest

from tools import rebuild_retrieval_assets
from wfrp_companion.library.page_labels import PageLabelBackfillSummary
from wfrp_companion.library.retrieval_status import RetrievalStatus
from wfrp_companion.search.fts import FtsRebuildSummary
from wfrp_companion.source_objects.embeddings import EmbeddingRebuildSummary
from wfrp_companion.source_objects.extractor import ExtractionSummary
from wfrp_companion.source_objects.source_map_builder import SourceMapRebuildSummary
from wfrp_companion.source_objects.store import ObjectSearchRebuildSummary
from wfrp_companion.structured_evidence.store import (
    StructuredEvidenceExtractionSummary,
)


def successful_summaries() -> dict[str, object]:
    return {
        "fts": FtsRebuildSummary(
            books_indexed=1,
            pages_indexed=2,
            skipped_current=0,
            stale_recovered=0,
            failed=0,
            failure_reason=None,
        ),
        "extraction": ExtractionSummary(
            discovered=1,
            extracted=1,
            skipped_current=0,
            stale_recovered=0,
            failed=0,
            objects_written=3,
            failures=(),
            book_summaries=(),
        ),
        "object_search": ObjectSearchRebuildSummary(
            discovered=1,
            indexed=1,
            skipped_current=0,
            stale_recovered=0,
            failed=0,
            objects_written=3,
            failures=(),
        ),
        "structured": StructuredEvidenceExtractionSummary(
            discovered=1,
            extracted=1,
            skipped_current=0,
            stale_recovered=0,
            failed=0,
            observations_written=3,
            candidates_written=2,
            needs_review=1,
            failures=(),
        ),
        "source_maps": SourceMapRebuildSummary(
            discovered=1,
            indexed=1,
            skipped_current=0,
            stale_recovered=0,
            failed=0,
            failures=(),
            book_summaries=(),
        ),
        "page_labels": PageLabelBackfillSummary(
            discovered=1,
            calibrated=1,
            needs_review=0,
            skipped_current=0,
            stale_recovered=0,
            failed=0,
            pages_calibrated=2,
            manual_review_pages=0,
            failures=(),
        ),
        "embeddings": EmbeddingRebuildSummary(
            discovered=1,
            indexed=1,
            skipped_current=0,
            skipped_disabled=0,
            stale_recovered=0,
            failed=0,
            embeddings_written=3,
            failures=(),
        ),
        "status": RetrievalStatus(
            books_total=1,
            books_enabled=1,
            page_text_indexed=1,
            source_objects_indexed=1,
            table_or_stat_indexed=1,
            structured_candidates=2,
            structured_needs_review=1,
            validated_structured_active=1,
            vectorized_current=1,
            vectorized_enabled=1,
            embedding_provider="local-hash",
            embedding_dimensions=16,
            vector_status="ready",
        ),
    }


def patch_steps(
    monkeypatch: pytest.MonkeyPatch,
    summaries: dict[str, object],
    calls: list[str],
) -> None:
    monkeypatch.setattr(
        rebuild_retrieval_assets,
        "rebuild_global_fts",
        lambda config, **kwargs: calls.append("fts") or summaries["fts"],
    )
    monkeypatch.setattr(
        rebuild_retrieval_assets,
        "extract_source_object_library",
        lambda config, **kwargs: calls.append("extract") or summaries["extraction"],
    )
    monkeypatch.setattr(
        rebuild_retrieval_assets,
        "rebuild_source_object_search",
        lambda config, **kwargs: calls.append("object_fts")
        or summaries["object_search"],
    )
    monkeypatch.setattr(
        rebuild_retrieval_assets,
        "extract_structured_evidence_library",
        lambda config, **kwargs: calls.append("structured")
        or summaries["structured"],
    )
    monkeypatch.setattr(
        rebuild_retrieval_assets,
        "rebuild_source_maps",
        lambda config, **kwargs: calls.append("source_maps")
        or summaries["source_maps"],
    )
    monkeypatch.setattr(
        rebuild_retrieval_assets,
        "backfill_page_labels",
        lambda config, **kwargs: calls.append("page_labels")
        or summaries["page_labels"],
    )
    monkeypatch.setattr(
        rebuild_retrieval_assets,
        "rebuild_embeddings",
        lambda config, **kwargs: calls.append("embeddings")
        or summaries["embeddings"],
    )
    monkeypatch.setattr(
        rebuild_retrieval_assets,
        "get_retrieval_status",
        lambda config: calls.append("status") or summaries["status"],
    )


def test_rebuild_retrieval_assets_cli_runs_steps_and_prints_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    patch_steps(monkeypatch, successful_summaries(), calls)

    exit_code = rebuild_retrieval_assets.main(
        [
            "--db-path",
            str(tmp_path / "wfrp.sqlite"),
            "--book-id",
            "bestiary",
            "--embedding-provider",
            "local-hash",
            "--embedding-model",
            "local-hash-test",
            "--embedding-dimensions",
            "16",
        ]
    )

    assert exit_code == 0
    assert calls == [
        "fts",
        "extract",
        "object_fts",
        "structured",
        "source_maps",
        "page_labels",
        "embeddings",
        "status",
    ]
    output = capsys.readouterr().out
    assert "WFRP retrieval asset rebuild" in output
    assert "FTS pages indexed: 2" in output
    assert "Source objects written: 3" in output
    assert "Structured candidates written: 2" in output
    assert "Structured needs review: 1" in output
    assert "Structured candidates total: 2" in output
    assert "Structured candidates needing review: 1" in output
    assert "Validated structured active: 1" in output
    assert "Embeddings written: 3" in output
    assert "Vector status: ready" in output
    assert "Vectorized enabled books: 1" in output


def test_rebuild_retrieval_assets_cli_returns_failure_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    summaries = successful_summaries()
    summaries["fts"] = FtsRebuildSummary(
        books_indexed=0,
        pages_indexed=0,
        skipped_current=0,
        stale_recovered=0,
        failed=1,
        failure_reason="synthetic failure",
    )
    patch_steps(monkeypatch, summaries, calls)

    exit_code = rebuild_retrieval_assets.main(
        ["--db-path", str(tmp_path / "wfrp.sqlite")]
    )

    assert exit_code == 1
    assert "Failed steps: 1" in capsys.readouterr().out


def test_config_from_args_preserves_embedding_options(tmp_path: Path) -> None:
    config = rebuild_retrieval_assets.config_from_args(
        rebuild_retrieval_assets.build_parser().parse_args(
            [
                "--data-dir",
                str(tmp_path / "data"),
                "--embedding-provider",
                "local-hash",
                "--embedding-model",
                "local-hash-test",
                "--embedding-dimensions",
                "16",
                "--embedding-batch-size",
                "4",
                "--embedding-device",
                "mps",
                "--embedding-query-prompt-name",
                "query",
                "--embedding-local-files-only",
            ]
        )
    )

    assert config.data_dir == tmp_path / "data"
    assert config.embedding_provider == "local-hash"
    assert config.embedding_model == "local-hash-test"
    assert config.embedding_dimensions == 16
    assert config.embedding_batch_size == 4
    assert config.embedding_device == "mps"
    assert config.embedding_query_prompt_name == "query"
    assert config.embedding_local_files_only is True


def test_stale_running_minutes_requires_positive_integer() -> None:
    parser = rebuild_retrieval_assets.build_parser()

    parsed = parser.parse_args(["--stale-running-minutes", "5"])

    assert parsed.stale_running_minutes == 5
    with pytest.raises(SystemExit):
        parser.parse_args(["--stale-running-minutes", "0"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--stale-running-minutes", "not-an-int"])
