from __future__ import annotations

import struct
import sys
import types
from dataclasses import replace
from pathlib import Path

import pytest

from tests.db.test_migrations import create_legacy_phase6_database
from tests.source_objects.test_store import (
    count_rows,
    fetch_one,
    insert_indexed_book,
    make_config,
)
from wfrp_companion.config import AppConfig
from wfrp_companion.assistant import retrieval
from wfrp_companion.db.connection import open_connection
from wfrp_companion.db.migrations import apply_migration
from wfrp_companion.source_objects import embedding_providers as provider_module
from wfrp_companion.source_objects.embedding_providers import (
    EmbeddingDimensionError,
    EmbeddingProviderDependencyError,
    EmbeddingProviderRuntimeError,
    LocalHashEmbeddingProvider,
    UnsupportedEmbeddingProviderError,
    resolve_embedding_provider,
)
from wfrp_companion.source_objects.embeddings import (
    cosine_similarity,
    embedding_source_snapshot_sha256,
    local_hash_embeddings_enabled,
    recover_stale_embedding_jobs,
    rebuild_book_embeddings,
    rebuild_embeddings,
    source_object_embeddings_current,
    source_object_embeddings_job_id,
    source_object_embedding_book_ids,
    text_embedding_vector,
    vector_blob,
    vector_from_blob,
)
from wfrp_companion.source_objects.extractor import extract_source_object_library


def local_embedding_config(tmp_path: Path):
    return replace(
        make_config(tmp_path),
        embedding_provider="local-hash",
        embedding_model="local-hash-test",
        embedding_dimensions=16,
    )


def test_resolve_embedding_provider_disabled_local_and_unsupported(
    tmp_path: Path,
) -> None:
    disabled = make_config(tmp_path)
    assert resolve_embedding_provider(disabled) is None
    assert not local_hash_embeddings_enabled(disabled)

    config = local_embedding_config(tmp_path)
    assert local_hash_embeddings_enabled(config)
    provider = resolve_embedding_provider(config)

    assert isinstance(provider, LocalHashEmbeddingProvider)
    assert provider.provider_name == "local-hash"
    assert provider.model_name == "local-hash-test"
    assert provider.dimensions == 16
    assert provider.embed_documents(("critical hit", "wyrdstone")) == (
        text_embedding_vector("critical hit", dimensions=16),
        text_embedding_vector("wyrdstone", dimensions=16),
    )
    assert provider.embed_query("critical hit") == text_embedding_vector(
        "critical hit",
        dimensions=16,
    )

    with pytest.raises(UnsupportedEmbeddingProviderError, match="custom"):
        resolve_embedding_provider(replace(config, embedding_provider="custom"))


def test_sentence_transformers_provider_uses_lazy_cached_model_and_encode_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    init_calls: list[tuple[str, dict[str, object]]] = []
    encode_calls: list[tuple[object, dict[str, object]]] = []

    class FakeSentenceTransformer:
        def __init__(self, model_name_or_path: str, **kwargs: object) -> None:
            init_calls.append((model_name_or_path, kwargs))

        def encode(self, sentences: object, **kwargs: object) -> object:
            encode_calls.append((sentences, kwargs))
            if isinstance(sentences, str):
                return [0.0, 1.0, 0.0]
            return [[1.0, 0.0, 0.0] for _ in sentences]

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    config = replace(
        local_embedding_config(tmp_path),
        embedding_provider="sentence-transformers",
        embedding_model="fake/bge-cache",
        embedding_dimensions=3,
        embedding_batch_size=2,
        embedding_device="mps",
        embedding_query_prompt_name="query",
        embedding_local_files_only=True,
    )

    provider_one = resolve_embedding_provider(config)
    provider_two = resolve_embedding_provider(config)

    assert init_calls == []
    assert provider_one is not None
    assert provider_two is not None
    assert provider_one.embed_documents(("alpha", "beta")) == (
        (1.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
    )
    assert provider_two.embed_query("question") == (0.0, 1.0, 0.0)
    assert init_calls == [
        (
            "fake/bge-cache",
            {"device": "mps", "local_files_only": True},
        )
    ]
    assert encode_calls == [
        (
            ("alpha", "beta"),
            {"batch_size": 2, "normalize_embeddings": True},
        ),
        (
            "question",
            {
                "batch_size": 1,
                "normalize_embeddings": True,
                "prompt_name": "query",
            },
        ),
    ]


def test_sentence_transformers_provider_reports_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_import(module_name: str) -> object:
        if module_name == "sentence_transformers":
            raise ModuleNotFoundError("No module named 'sentence_transformers'")
        raise AssertionError(module_name)

    monkeypatch.setattr(provider_module.importlib, "import_module", fail_import)
    config = replace(
        local_embedding_config(tmp_path),
        embedding_provider="sentence-transformers",
        embedding_model="fake/missing-dependency",
        embedding_dimensions=3,
    )
    provider = resolve_embedding_provider(config)

    assert provider is not None
    with pytest.raises(EmbeddingProviderDependencyError, match="sentence-transformers"):
        provider.embed_query("critical hit")


def test_sentence_transformers_provider_reports_model_load_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeSentenceTransformer:
        def __init__(self, model_name_or_path: str, **kwargs: object) -> None:
            raise OSError("cache miss")

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    config = replace(
        local_embedding_config(tmp_path),
        embedding_provider="sentence-transformers",
        embedding_model="fake/cache-miss",
        embedding_dimensions=3,
    )
    provider = resolve_embedding_provider(config)

    assert provider is not None
    with pytest.raises(EmbeddingProviderRuntimeError, match="Unable to load"):
        provider.embed_query("critical hit")


def test_sentence_transformers_provider_reports_encode_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeSentenceTransformer:
        def __init__(self, model_name_or_path: str, **kwargs: object) -> None:
            pass

        def encode(self, sentences: object, **kwargs: object) -> object:
            raise RuntimeError("encode failed")

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    config = replace(
        local_embedding_config(tmp_path),
        embedding_provider="sentence-transformers",
        embedding_model="fake/encode-failure",
        embedding_dimensions=3,
    )
    provider = resolve_embedding_provider(config)

    assert provider is not None
    with pytest.raises(EmbeddingProviderRuntimeError, match="Unable to encode"):
        provider.embed_documents(("critical hit",))
    with pytest.raises(EmbeddingProviderRuntimeError, match="Unable to encode query"):
        provider.embed_query("critical hit")


def test_sentence_transformers_provider_validates_vector_dimensions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeSentenceTransformer:
        def __init__(self, model_name_or_path: str, **kwargs: object) -> None:
            pass

        def encode(self, sentences: object, **kwargs: object) -> object:
            if isinstance(sentences, str):
                return [1.0, 0.0]
            return [[1.0, 0.0] for _ in sentences]

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    config = replace(
        local_embedding_config(tmp_path),
        embedding_provider="sentence-transformers",
        embedding_model="fake/dimension-mismatch",
        embedding_dimensions=3,
    )
    provider = resolve_embedding_provider(config)

    assert provider is not None
    with pytest.raises(EmbeddingDimensionError, match="expected 3 dimensions"):
        provider.embed_documents(("critical hit",))


def test_sentence_transformers_provider_handles_empty_and_array_like_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeArray:
        def __init__(self, value: object) -> None:
            self.value = value

        def tolist(self) -> object:
            return self.value

    class FakeSentenceTransformer:
        def __init__(self, model_name_or_path: str, **kwargs: object) -> None:
            pass

        def encode(self, sentences: object, **kwargs: object) -> object:
            if isinstance(sentences, str):
                return FakeArray([0.0, 1.0, 0.0])
            return FakeArray([[1.0, 0.0, 0.0] for _ in sentences])

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    config = replace(
        local_embedding_config(tmp_path),
        embedding_provider="sentence-transformers",
        embedding_model="fake/array-like",
        embedding_dimensions=3,
    )
    provider = resolve_embedding_provider(config)

    assert provider is not None
    assert provider.embed_documents(()) == ()
    assert provider.embed_documents(("critical hit",)) == ((1.0, 0.0, 0.0),)
    assert provider.embed_query("critical hit") == (0.0, 1.0, 0.0)


def test_rebuild_embeddings_is_disabled_by_default(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)

    summary = rebuild_embeddings(config)

    assert summary.discovered == 1
    assert summary.indexed == 0
    assert summary.skipped_disabled == 1
    assert summary.embeddings_written == 0
    assert count_rows(config, "source_object_embeddings") == 0
    status = fetch_one(config, "select vector_status from book_retrieval_status")
    assert status["vector_status"] == "disabled"


def test_rebuild_embeddings_initializes_missing_database(tmp_path: Path) -> None:
    config = local_embedding_config(tmp_path)

    summary = rebuild_embeddings(config)

    assert summary.discovered == 0
    assert config.db_path.exists()


def test_rebuild_embeddings_indexes_current_source_objects_and_skips_current(
    tmp_path: Path,
) -> None:
    config = local_embedding_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        snapshot = embedding_source_snapshot_sha256(connection, "rules")

    summary = rebuild_embeddings(config)

    assert summary.discovered == 1
    assert summary.indexed == 1
    assert summary.skipped_current == 0
    assert summary.embeddings_written == 2
    assert count_rows(config, "source_object_embeddings") == 2
    status = fetch_one(config, "select * from book_retrieval_status")
    job = fetch_one(config, "select * from ingest_jobs where job_type = 'rebuild_embeddings'")
    row = fetch_one(config, "select * from source_object_embeddings order by id limit 1")
    assert status["vector_status"] == "indexed"
    assert status["vector_snapshot_sha256"] == snapshot
    assert status["embedding_provider"] == "local-hash"
    assert status["embedding_model"] == "local-hash-test"
    assert status["embedding_dimensions"] == 16
    assert job["status"] == "succeeded"
    assert job["idempotency_key"] == source_object_embeddings_job_id(
        "rules",
        "local-hash",
        "local-hash-test",
        16,
        snapshot,
    )
    assert row["embedding_provider"] == "local-hash"
    assert len(row["vector_blob"]) == 16 * struct.calcsize("<f")
    with open_connection(config.db_path) as connection:
        assert source_object_embeddings_current(connection, "rules", config=config)

    second = rebuild_embeddings(config)

    assert second.indexed == 0
    assert second.skipped_current == 1


def test_rebuild_embeddings_invalidates_when_source_object_text_changes(
    tmp_path: Path,
) -> None:
    config = local_embedding_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    assert rebuild_embeddings(config).indexed == 1
    before = fetch_one(config, "select vector_snapshot_sha256 from book_retrieval_status")[
        "vector_snapshot_sha256"
    ]
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update source_objects
            set search_text = search_text || ' wyrdstone',
                text_snapshot_sha256 = 'changed-snapshot'
            where book_id = 'rules'
              and page_start = 1
            """
        )
        assert not source_object_embeddings_current(connection, "rules", config=config)

    summary = rebuild_embeddings(config)

    after = fetch_one(config, "select vector_snapshot_sha256 from book_retrieval_status")[
        "vector_snapshot_sha256"
    ]
    assert summary.indexed == 1
    assert before != after


def test_source_object_embeddings_current_rejects_malformed_vector_blob(
    tmp_path: Path,
) -> None:
    config = local_embedding_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    assert rebuild_embeddings(config).indexed == 1

    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update source_object_embeddings
            set vector_blob = ?
            where rowid = (
              select rowid
              from source_object_embeddings
              order by rowid
              limit 1
            )
            """,
            (vector_blob((1.0,)),),
        )

        assert not source_object_embeddings_current(connection, "rules", config=config)


def test_vector_candidates_are_filtered_to_checked_books(tmp_path: Path) -> None:
    config = local_embedding_config(tmp_path)
    insert_indexed_book(config, book_id="rules")
    insert_indexed_book(config, book_id="lore")
    extract_source_object_library(config)
    assert rebuild_embeddings(config).indexed == 2

    with open_connection(config.db_path) as connection:
        candidates = retrieval.search_vector_candidates(
            connection,
            "critical hits",
            book_ids=("lore",),
            limit=5,
            config=config,
        )

    assert candidates
    assert {candidate.channel for candidate in candidates} == {"vector"}
    assert {candidate.book_id for candidate in candidates} == {"lore"}
    with open_connection(config.db_path) as connection:
        assert retrieval.search_vector_candidates(
            connection,
            "!!!",
            book_ids=("lore",),
            limit=5,
            config=config,
        ) == ()


def test_vector_candidates_do_not_trust_embedding_book_id_for_scope(
    tmp_path: Path,
) -> None:
    config = local_embedding_config(tmp_path)
    insert_indexed_book(config, book_id="rules")
    insert_indexed_book(config, book_id="lore")
    extract_source_object_library(config)
    assert rebuild_embeddings(config).indexed == 2

    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update source_object_embeddings
            set book_id = 'lore'
            where source_object_id in (
              select id
              from source_objects
              where book_id = 'rules'
              limit 1
            )
            """
        )
        candidates = retrieval.search_vector_candidates(
            connection,
            "critical hits",
            book_ids=("lore",),
            limit=10,
            config=config,
        )

    assert "rules" not in {candidate.book_id for candidate in candidates}


def test_vector_candidates_require_current_embedding_snapshot(tmp_path: Path) -> None:
    config = local_embedding_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    assert rebuild_embeddings(config).indexed == 1

    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update source_objects
            set search_text = search_text || ' stale-but-same-text-snapshot'
            where book_id = 'rules'
              and page_start = 1
            """
        )
        assert not source_object_embeddings_current(connection, "rules", config=config)
        assert retrieval.search_vector_candidates(
            connection,
            "critical hits",
            book_ids=("rules",),
            limit=10,
            config=config,
        ) == ()


def test_vector_candidates_filter_embedding_provider(tmp_path: Path) -> None:
    config = local_embedding_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    assert rebuild_embeddings(config).indexed == 1

    with open_connection(config.db_path) as connection:
        row = connection.execute(
            """
            select
              source_object_id,
              book_id,
              text_snapshot_sha256,
              vector_blob
            from source_object_embeddings
            order by id
            limit 1
            """
        ).fetchone()
        connection.execute(
            """
            insert into source_object_embeddings (
              id,
              source_object_id,
              book_id,
              embedding_provider,
              embedding_model,
              embedding_dimensions,
              text_snapshot_sha256,
              vector_blob,
              created_at,
              updated_at
            )
            values (
              'embedding:other-provider-current',
              ?,
              ?,
              'other-provider',
              ?,
              ?,
              ?,
              ?,
              '2026-06-08T00:00:00Z',
              '2026-06-08T00:00:00Z'
            )
            """,
            (
                row["source_object_id"],
                row["book_id"],
                config.embedding_model,
                config.embedding_dimensions,
                row["text_snapshot_sha256"],
                row["vector_blob"],
            ),
        )
        candidates = retrieval.search_vector_candidates(
            connection,
            "critical hits",
            book_ids=("rules",),
            limit=10,
            config=config,
        )

    candidate_ids = [candidate.source_object_id for candidate in candidates]
    assert row["source_object_id"] in candidate_ids
    assert candidate_ids.count(row["source_object_id"]) == 1


def test_rebuild_embeddings_applies_pending_vector_migration_for_existing_db(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy-0002.sqlite"
    create_legacy_phase6_database(db_path)
    with open_connection(db_path) as connection:
        apply_migration(connection, "0001_phase_7_source_objects")
        apply_migration(connection, "0002_source_map_retrieval")
        connection.execute(
            """
            insert into source_objects (
              id,
              book_id,
              page_id,
              object_type,
              heading_path_json,
              page_start,
              page_end,
              text,
              search_text,
              confidence,
              extraction_method,
              text_snapshot_sha256,
              created_at,
              updated_at
            )
            values (
              'core-rules:critical',
              'core-rules',
              'core-rules:1',
              'rule_section',
              '[]',
              1,
              1,
              'Critical hits',
              'Critical hits',
              0.91,
              'test',
              'snapshot-1',
              '2026-06-05T00:00:00Z',
              '2026-06-05T00:00:00Z'
            )
            """
        )

    config = AppConfig(
        pdf_root=tmp_path / "pdfs",
        data_dir=tmp_path,
        db_path=db_path,
        asset_dir=tmp_path / "assets",
        embedding_provider="local-hash",
        embedding_model="local-hash-test",
        embedding_dimensions=16,
    )

    summary = rebuild_embeddings(config)

    assert summary.indexed == 1
    with open_connection(db_path) as connection:
        assert (
            connection.execute(
                "select id from schema_migrations where id = '0003_vector_retrieval'"
            ).fetchone()
            is not None
        )
        assert (
            connection.execute(
                """
                select status
                from ingest_jobs
                where job_type = 'rebuild_embeddings'
                """
            ).fetchone()["status"]
            == "succeeded"
        )


def test_vector_channel_does_not_bury_exact_object_hits() -> None:
    exact = retrieval.EvidenceCandidate(
        book_id="rules",
        title="Rules Primer",
        category="Core",
        page_id="rules:1",
        page_number=1,
        pdf_page_number=1,
        page_label=None,
        page_start=1,
        page_end=1,
        page_range_label=None,
        snippet="critical hit",
        base_score=-0.1,
        context_text="critical hit result table",
        channel="source_object_fts",
        source_object_id="rules:critical",
        object_type="rule_section",
        object_title="Critical Hits",
        confidence=0.9,
    )
    vector = retrieval.EvidenceCandidate(
        book_id="rules",
        title="Rules Primer",
        category="Core",
        page_id="rules:2",
        page_number=2,
        pdf_page_number=2,
        page_label=None,
        page_start=2,
        page_end=2,
        page_range_label=None,
        snippet="critical hit",
        base_score=-0.99,
        context_text="critical hit aside",
        channel="vector",
        source_object_id="rules:aside",
        object_type="page_chunk",
        object_title="Aside",
        confidence=0.4,
    )
    query_plan = retrieval.plan_query("critical hit", ())

    fused = retrieval.reciprocal_rank_fuse((vector, exact))
    ranked = retrieval.rerank_candidates(fused, query_plan)

    assert ranked[0][0].source_object_id == "rules:critical"


def test_embedding_vector_blob_round_trips_and_normalizes() -> None:
    vector = text_embedding_vector("critical critical hit", dimensions=8)
    decoded = vector_from_blob(vector_blob(vector))

    assert len(decoded) == 8
    assert decoded == vector
    assert abs(sum(value * value for value in decoded) - 1.0) < 0.000001


def test_embedding_book_filters_and_disabled_current_edges(tmp_path: Path) -> None:
    config = local_embedding_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        assert source_object_embedding_book_ids(connection, book_ids=()) == ()
        assert source_object_embedding_book_ids(
            connection,
            book_ids=("rules",),
        ) == ("rules",)
        assert not source_object_embeddings_current(
            connection,
            "rules",
            config=replace(config, embedding_provider="disabled"),
        )
        assert not source_object_embeddings_current(
            connection,
            "rules",
            config=replace(config, embedding_provider="custom"),
        )
        assert not source_object_embeddings_current(connection, "missing", config=config)
        assert not source_object_embeddings_current(connection, "rules", config=config)


def test_embedding_currentness_handles_none_provider_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = local_embedding_config(tmp_path)
    insert_indexed_book(config)
    monkeypatch.setattr(
        "wfrp_companion.source_objects.embeddings.resolve_embedding_provider",
        lambda config: None,
    )

    with open_connection(config.db_path) as connection:
        assert not source_object_embeddings_current(connection, "rules", config=config)


def test_rebuild_embeddings_reports_unsupported_provider_and_claim_conflict(
    tmp_path: Path,
) -> None:
    config = replace(local_embedding_config(tmp_path), embedding_provider="custom")
    insert_indexed_book(config)
    extract_source_object_library(config)

    unsupported = rebuild_embeddings(config)

    assert unsupported.failed == 1
    assert "Unsupported embedding provider" in unsupported.failures[0].reason
    assert fetch_one(config, "select vector_status from book_retrieval_status")[
        "vector_status"
    ] == "failed"

    local_config = replace(config, embedding_provider="local-hash")
    with open_connection(local_config.db_path) as connection:
        snapshot = embedding_source_snapshot_sha256(connection, "rules")
        job_id = source_object_embeddings_job_id(
            "rules",
            local_config.embedding_provider,
            local_config.embedding_model,
            local_config.embedding_dimensions,
            snapshot,
        )
        connection.execute(
            """
            insert into ingest_jobs (
              id,
              job_type,
              target_id,
              status,
              idempotency_key,
              attempts,
              created_at,
              updated_at
            )
            values (?, 'rebuild_embeddings', 'rules', 'running', ?, 1,
                    '2999-01-01T00:00:00Z', '2999-01-01T00:00:00Z')
            """,
            (job_id, job_id),
        )

    conflict = rebuild_embeddings(local_config)

    assert conflict.failed == 1
    assert "already running" in conflict.failures[0].reason


def test_embedding_currentness_detects_status_and_projection_mismatches(
    tmp_path: Path,
) -> None:
    config = local_embedding_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    assert rebuild_embeddings(config).indexed == 1

    with open_connection(config.db_path) as connection:
        source_object = connection.execute(
            """
            select id
            from source_objects
            where book_id = 'rules'
            order by id
            limit 1
            """
        ).fetchone()
        connection.execute(
            """
            insert into source_object_embeddings (
              id,
              source_object_id,
              book_id,
              embedding_provider,
              embedding_model,
              embedding_dimensions,
              text_snapshot_sha256,
              vector_blob,
              created_at,
              updated_at
            )
            values (
              'embedding:other-provider-stale',
              ?,
              'rules',
              'other-provider',
              ?,
              ?,
              'stale-snapshot',
              ?,
              '2026-06-08T00:00:00Z',
              '2026-06-08T00:00:00Z'
            )
            """,
            (
                source_object["id"],
                config.embedding_model,
                config.embedding_dimensions,
                vector_blob((0.0,) * config.embedding_dimensions),
            ),
        )
        assert source_object_embeddings_current(connection, "rules", config=config)
        connection.execute(
            """
            update book_retrieval_status
            set embedding_model = 'other-model'
            where book_id = 'rules'
            """
        )
        assert not source_object_embeddings_current(connection, "rules", config=config)
        connection.execute(
            """
            update book_retrieval_status
            set embedding_model = ?,
                embedding_dimensions = 99
            where book_id = 'rules'
            """,
            (config.embedding_model,),
        )
        assert not source_object_embeddings_current(connection, "rules", config=config)
        connection.execute(
            """
            update book_retrieval_status
            set embedding_dimensions = ?,
                vector_status = 'indexed',
                embedding_provider = 'other-provider'
            where book_id = 'rules'
            """,
            (config.embedding_dimensions,),
        )
        assert not source_object_embeddings_current(connection, "rules", config=config)
        connection.execute(
            """
            update book_retrieval_status
            set embedding_provider = ?
            where book_id = 'rules'
            """,
            (config.embedding_provider,),
        )
        connection.execute("delete from source_object_embeddings where rowid = 1")
        assert not source_object_embeddings_current(connection, "rules", config=config)

    assert rebuild_embeddings(config, force=True).indexed == 1
    with open_connection(config.db_path) as connection:
        connection.execute("delete from source_objects where book_id = 'rules'")
        empty_snapshot = embedding_source_snapshot_sha256(connection, "rules")
        connection.execute(
            """
            update book_retrieval_status
            set vector_status = 'indexed',
                vector_snapshot_sha256 = ?
            where book_id = 'rules'
            """,
            (empty_snapshot,),
        )
        assert not source_object_embeddings_current(connection, "rules", config=config)


def test_rebuild_book_embeddings_computes_vectors_outside_write_transaction(
    tmp_path: Path,
) -> None:
    config = local_embedding_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)

    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            insert into book_retrieval_status (book_id, updated_at)
            values ('rules', '2026-06-08T00:00:00Z')
            on conflict(book_id) do nothing
            """
        )
        observed_transactions: list[bool] = []

        class InspectingProvider:
            provider_name = "local-hash"
            model_name = "local-hash-test"
            dimensions = 16

            def embed_documents(self, texts):  # noqa: ANN001
                observed_transactions.append(connection.in_transaction)
                return tuple(
                    text_embedding_vector(text, dimensions=self.dimensions)
                    for text in texts
                )

            def embed_query(self, text: str) -> tuple[float, ...]:
                return text_embedding_vector(text, dimensions=self.dimensions)

        written = rebuild_book_embeddings(
            connection,
            book_id="rules",
            config=config,
            provider=InspectingProvider(),
            now="2026-06-08T00:00:00Z",
        )

    assert written == 2
    assert observed_transactions == [False]


def test_rebuild_book_embeddings_marks_job_failed_when_provider_raises(
    tmp_path: Path,
) -> None:
    config = local_embedding_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)

    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            insert into book_retrieval_status (book_id, updated_at)
            values ('rules', '2026-06-08T00:00:00Z')
            on conflict(book_id) do nothing
            """
        )

        class FailingProvider:
            provider_name = "local-hash"
            model_name = "local-hash-test"
            dimensions = 16

            def embed_documents(self, texts):  # noqa: ANN001
                raise RuntimeError("model load failed")

            def embed_query(self, text: str) -> tuple[float, ...]:
                return text_embedding_vector(text, dimensions=self.dimensions)

        with pytest.raises(RuntimeError, match="model load failed"):
            rebuild_book_embeddings(
                connection,
                book_id="rules",
                config=config,
                provider=FailingProvider(),
                now="2026-06-08T00:00:00Z",
            )

        status = connection.execute(
            """
            select vector_status, last_error
            from book_retrieval_status
            where book_id = 'rules'
            """
        ).fetchone()
        job = connection.execute(
            """
            select status, last_error, completed_at
            from ingest_jobs
            where job_type = 'rebuild_embeddings'
            order by updated_at desc, id desc
            limit 1
            """
        ).fetchone()

    assert status["vector_status"] == "failed"
    assert "RuntimeError: model load failed" in status["last_error"]
    assert job["status"] == "failed"
    assert "RuntimeError: model load failed" in job["last_error"]
    assert job["completed_at"] is not None


def test_rebuild_book_embeddings_preserves_rows_when_source_snapshot_drifts(
    tmp_path: Path,
) -> None:
    config = local_embedding_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    assert rebuild_embeddings(config).indexed == 1
    with open_connection(config.db_path) as setup_connection:
        before_rows = tuple(
            (row["id"], row["updated_at"])
            for row in setup_connection.execute(
                """
                select id, updated_at
                from source_object_embeddings
                order by id
                """
            ).fetchall()
        )

    with open_connection(config.db_path) as connection:

        class DriftingProvider:
            provider_name = "local-hash"
            model_name = "local-hash-test"
            dimensions = 16

            def embed_documents(self, texts):  # noqa: ANN001
                vectors = tuple(
                    text_embedding_vector(text, dimensions=self.dimensions)
                    for text in texts
                )
                connection.execute(
                    """
                    update source_objects
                    set search_text = search_text || ' changed',
                        text_snapshot_sha256 = 'changed-during-embedding'
                    where book_id = 'rules'
                      and page_start = 1
                    """
                )
                return vectors

            def embed_query(self, text: str) -> tuple[float, ...]:
                return text_embedding_vector(text, dimensions=self.dimensions)

        written = rebuild_book_embeddings(
            connection,
            book_id="rules",
            config=config,
            provider=DriftingProvider(),
            now="2026-06-08T00:00:00Z",
        )
        after_rows = tuple(
            (row["id"], row["updated_at"])
            for row in connection.execute(
                """
                select id, updated_at
                from source_object_embeddings
                order by id
                """
            ).fetchall()
        )
        status = connection.execute(
            """
            select vector_status, last_error
            from book_retrieval_status
            where book_id = 'rules'
            """
        ).fetchone()
        job = connection.execute(
            """
            select status, last_error
            from ingest_jobs
            where job_type = 'rebuild_embeddings'
              and status = 'failed'
            order by updated_at desc, id desc
            limit 1
            """
        ).fetchone()

    assert written == 0
    assert after_rows == before_rows
    assert status["vector_status"] == "needs_refresh"
    assert "changed during embedding rebuild" in status["last_error"]
    assert job["status"] == "failed"
    assert "changed during embedding rebuild" in job["last_error"]


def test_rebuild_embeddings_reports_snapshot_drift_without_marking_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = local_embedding_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)

    def drift_rebuild(*args, **kwargs):  # noqa: ANN002, ANN003
        return 0

    monkeypatch.setattr(
        "wfrp_companion.source_objects.embeddings.rebuild_book_embeddings",
        drift_rebuild,
    )

    summary = rebuild_embeddings(config, force=True)

    assert summary.indexed == 0
    assert summary.failed == 1
    assert summary.failures[0].reason == "Source objects changed during embedding rebuild."


def test_rebuild_book_embeddings_rejects_status_changed_before_commit(
    tmp_path: Path,
) -> None:
    config = local_embedding_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)

    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            insert into book_retrieval_status (book_id, updated_at)
            values ('rules', '2026-06-08T00:00:00Z')
            on conflict(book_id) do nothing
            """
        )

        class StatusChangingProvider:
            provider_name = "local-hash"
            model_name = "local-hash-test"
            dimensions = 16

            def embed_documents(self, texts):  # noqa: ANN001
                vectors = tuple(
                    text_embedding_vector(text, dimensions=self.dimensions)
                    for text in texts
                )
                connection.execute(
                    """
                    update book_retrieval_status
                    set vector_status = 'needs_refresh'
                    where book_id = 'rules'
                    """
                )
                return vectors

            def embed_query(self, text: str) -> tuple[float, ...]:
                return text_embedding_vector(text, dimensions=self.dimensions)

        with pytest.raises(RuntimeError, match="status changed"):
            rebuild_book_embeddings(
                connection,
                book_id="rules",
                config=config,
                provider=StatusChangingProvider(),
                now="2026-06-08T00:00:00Z",
            )


def test_stale_embedding_job_recovery_marks_status_for_retry(tmp_path: Path) -> None:
    config = local_embedding_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            insert into book_retrieval_status (
              book_id,
              vector_status,
              updated_at
            )
            values ('rules', 'indexing', '2026-06-05T00:00:00Z')
            on conflict(book_id) do update set
              vector_status = excluded.vector_status,
              updated_at = excluded.updated_at
            """
        )
        connection.execute(
            """
            insert into ingest_jobs (
              id,
              job_type,
              target_id,
              status,
              idempotency_key,
              attempts,
              created_at,
              updated_at
            )
            values ('stale-embedding', 'rebuild_embeddings', 'rules',
                    'running', 'stale-embedding', 1,
                    '2026-06-05T00:00:00Z', '2026-06-05T00:00:00Z')
            """
        )
        connection.execute(
            """
            insert into ingest_jobs (
              id,
              job_type,
              target_id,
              status,
              idempotency_key,
              attempts,
              created_at,
              updated_at
            )
            values ('stale-embedding-null', 'rebuild_embeddings', null,
                    'running', 'stale-embedding-null', 1,
                    '2026-06-05T00:00:00Z', '2026-06-05T00:00:00Z')
            """
        )

        assert recover_stale_embedding_jobs(
            connection,
            retry_running=True,
            stale_running_minutes=30,
        ) == 2
        assert recover_stale_embedding_jobs(
            connection,
            retry_running=False,
            stale_running_minutes=30,
        ) == 0

    status = fetch_one(config, "select vector_status, last_error from book_retrieval_status")
    assert status["vector_status"] == "needs_refresh"
    assert "Recovered stale" in status["last_error"]


def test_vector_candidate_edges_and_collect_path(tmp_path: Path) -> None:
    config = local_embedding_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    assert rebuild_embeddings(config).indexed == 1
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update source_object_embeddings
            set vector_blob = ?
            where rowid = 1
            """,
            (vector_blob((0.0,) * config.embedding_dimensions),),
        )
        zero_or_positive = retrieval.search_vector_candidates(
            connection,
            "critical hits",
            book_ids=("rules",),
            limit=5,
            config=config,
        )
        assert all(
            any("vector_similarity" in reason for reason in candidate.rank_reasons)
            for candidate in zero_or_positive
        )
        assert retrieval.search_vector_candidates(
            connection,
            "critical hits",
            book_ids=(),
            limit=5,
            config=config,
        ) == ()
        assert retrieval.search_vector_candidates(
            connection,
            "critical hits",
            book_ids=("rules",),
            limit=5,
            config=replace(config, embedding_provider="disabled"),
        ) == ()

    collected = retrieval.collect_evidence_candidates(
        config,
        source_book_ids=("rules",),
        query_plan=retrieval.plan_query("critical hits", ()),
        per_candidate_limit=5,
    )
    assert any(
        any(
            reason.startswith("fusion_channel:vector@")
            for reason in candidate.rank_reasons
        )
        for candidate in collected
    )


def test_vector_helper_edge_cases() -> None:
    assert text_embedding_vector("", dimensions=4) == (0.0, 0.0, 0.0, 0.0)
    assert vector_from_blob(b"") == ()
    assert cosine_similarity((0.0, 0.0), (1.0, 0.0)) == 0.0
    with pytest.raises(ValueError, match="dimensions"):
        text_embedding_vector("critical", dimensions=0)
    with pytest.raises(ValueError, match="divisible"):
        vector_from_blob(b"x")
    with pytest.raises(ValueError, match="matching dimensions"):
        cosine_similarity((1.0,), (1.0, 0.0))
