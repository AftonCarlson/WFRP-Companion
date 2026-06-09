from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from wfrp_companion.assistant import chat_store
from wfrp_companion.assistant import candidates as retrieval_candidates
from wfrp_companion.assistant import retrieval
from wfrp_companion.assistant import source_map as retrieval_source_map
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database, open_connection
from wfrp_companion.library import page_labels
from wfrp_companion.library import source_sets
from wfrp_companion.search.fts import rebuild_global_fts
from wfrp_companion.source_objects.source_map_builder import (
    BUILDER_VERSION,
    SCHEMA_VERSION,
    source_object_snapshot_sha256,
)
from wfrp_companion.source_objects.embeddings import (
    embedding_source_snapshot_sha256,
    vector_blob,
)
from wfrp_companion.source_objects import embeddings as embedding_module
from wfrp_companion.source_objects.embedding_providers import (
    EmbeddingProviderDependencyError,
)
from wfrp_companion.source_objects.store import rebuild_source_object_search


def make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        pdf_root=tmp_path / "pdf-root",
        data_dir=data_dir,
        db_path=data_dir / "wfrp_companion.sqlite",
        asset_dir=data_dir / "library" / "assets",
    )


def insert_folder(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        insert into library_folders (id, parent_id, name, relative_path, sort_order)
        values ('core', null, 'Core', 'Core', 0)
        on conflict(id) do nothing
        """
    )


def insert_searchable_page(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    title: str,
    category: str,
    page_number: int,
    text: str,
    page_label: str | None = None,
    page_count: int = 1,
) -> None:
    insert_folder(connection)
    connection.execute(
        """
        insert into books (
          id,
          folder_id,
          title,
          category,
          relative_path,
          original_source_path,
          managed_pdf_path,
          original_sha256,
          managed_sha256,
          page_count,
          copy_status,
          text_status,
          search_status,
          visual_status,
          discovered_at,
          updated_at
        )
        values (?, 'core', ?, ?, ?, ?, ?, ?, ?, ?, 'copied', 'imported',
                'not_indexed', 'not_scanned', '2026-06-04T00:00:00Z',
                '2026-06-04T00:00:00Z')
        on conflict(id) do nothing
        """,
        (
            book_id,
            title,
            category,
            f"{category}/{title}.pdf",
            f"/source/{book_id}.pdf",
            f"/managed/{book_id}.pdf",
            f"sha-{book_id}",
            f"sha-{book_id}",
            page_count,
        ),
    )
    page_id = f"{book_id}:{page_number}"
    connection.execute(
        """
        insert into pages (
          id,
          book_id,
          page_number,
          page_label,
          extraction_method,
          embedded_text_chars,
          text_chars,
          word_count,
          image_count,
          ocr_attempted,
          has_text
        )
        values (?, ?, ?, ?, 'ocr', 0, ?, ?, 0, 1, 1)
        """,
        (page_id, book_id, page_number, page_label, len(text), len(text.split())),
    )
    connection.execute(
        """
        insert into page_text (page_id, text, text_sha256, generated_at)
        values (?, ?, ?, '2026-06-04T00:00:00Z')
        """,
        (page_id, text, f"sha-{page_id}"),
    )


def insert_source_object(
    connection: sqlite3.Connection,
    *,
    object_id: str,
    book_id: str,
    page_id: str,
    object_type: str,
    title: str,
    heading_path: tuple[str, ...],
    page_start: int,
    page_end: int,
    text: str,
    parent_object_id: str | None = None,
    metadata_json: str = "{}",
    char_start: int | None = None,
    char_end: int | None = None,
) -> None:
    connection.execute(
        """
        insert into source_objects (
          id,
          book_id,
          page_id,
          object_type,
          parent_object_id,
          title,
          heading_path_json,
          page_start,
          page_end,
          char_start,
          char_end,
          text,
          search_text,
          confidence,
          extraction_method,
          text_snapshot_sha256,
          metadata_json,
          created_at,
          updated_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.91, 'test', ?, ?, ?, ?)
        """,
        (
            object_id,
            book_id,
            page_id,
            object_type,
            parent_object_id,
            title,
            json.dumps(list(heading_path)),
            page_start,
            page_end,
            char_start,
            char_end,
            text,
            " ".join((*heading_path, text)),
            f"sha-{object_id}",
            metadata_json,
            "2026-06-05T00:00:00Z",
            "2026-06-05T00:00:00Z",
        ),
    )


def insert_source_object_link(
    connection: sqlite3.Connection,
    *,
    link_id: str,
    from_object_id: str,
    link_type: str,
    to_object_id: str | None = None,
    to_book_id: str | None = None,
    to_page_id: str | None = None,
    label: str | None = None,
    confidence: float = 0.91,
) -> None:
    connection.execute(
        """
        insert into source_object_links (
          id,
          from_object_id,
          to_object_id,
          to_book_id,
          to_page_id,
          link_type,
          label,
          confidence,
          created_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, '2026-06-05T00:00:00Z')
        """,
        (
            link_id,
            from_object_id,
            to_object_id,
            to_book_id,
            to_page_id,
            link_type,
            label,
            confidence,
        ),
    )


def seed_searchable_books(config: AppConfig) -> None:
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=1,
            text=(
                "Critical hit rules explain what happens after a critical hit. "
                "Use the critical hit table and apply the listed result."
            ),
        )
        insert_searchable_page(
            connection,
            book_id="barony",
            title="Barony of the Damned",
            category="Adventure Modules and Campaigns",
            page_number=41,
            text=(
                "The Black Knight rides under dark banners. "
                "The black knight encounter is part of the adventure."
            ),
        )
    source_sets.ensure_builtin_source_sets(config)
    rebuild_global_fts(config)


def test_query_candidates_drop_filler_words_and_keep_useful_phrases() -> None:
    candidates = retrieval.query_candidates(
        "What happens when a character takes a critical hit?"
    )

    assert candidates[0] == "character takes critical hit"
    assert "critical hit" in candidates
    assert "what happens when" not in candidates


def test_retrieve_context_includes_hybrid_channel_diagnostics(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_searchable_books(config)
    thread = chat_store.create_thread(config)

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "critical hit",
        hit_limit=4,
        total_char_limit=500,
        window_chars=120,
    )

    assert context.hits
    assert context.diagnostics is not None
    assert context.diagnostics.channel_counts["page_fts"] > 0
    assert context.diagnostics.channel_counts["source_object_fts"] == 0
    assert context.diagnostics.channel_counts["source_object_scan"] == 0
    assert context.diagnostics.channel_counts["vector"] == 0
    assert context.diagnostics.vector_status == "disabled"
    assert context.diagnostics.candidate_count_before_fusion >= 1
    assert context.diagnostics.candidate_count_after_fusion >= 1
    assert context.diagnostics.reranked_count >= len(context.hits)
    assert context.diagnostics.selected_count == len(context.hits)


def test_retrieval_keeps_thread_snapshot_for_history_but_uses_live_scope(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_searchable_books(config)
    original_thread = chat_store.create_thread(config)
    source_sets.set_book_enabled(config, "rules-core", "core-rules", False)
    source_sets.set_book_enabled(config, "rules-core", "barony", True)
    original_detail = chat_store.get_thread_detail(config, original_thread.id)

    context = retrieval.retrieve_context(
        config,
        original_thread.id,
        "Where is the black knight?",
        hit_limit=4,
        total_char_limit=500,
        window_chars=120,
    )

    assert original_detail.source_book_ids == ("core-rules",)
    assert context.source_book_ids == ("barony",)
    assert [hit.book_id for hit in context.hits] == ["barony"]
    assert "black knight" in context.hits[0].context_text.lower()
    assert "/managed/" not in context.hits[0].context_text


def test_retrieval_uses_current_enabled_books_not_stale_thread_snapshot(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_searchable_books(config)
    thread = chat_store.create_thread(config)
    source_sets.set_book_enabled(config, "rules-core", "core-rules", False)
    source_sets.set_book_enabled(config, "rules-core", "barony", True)

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "Where is the black knight?",
        hit_limit=4,
        total_char_limit=500,
        window_chars=120,
    )

    assert context.source_set_id == "rules-core"
    assert context.source_book_ids == ("barony",)
    assert [hit.book_id for hit in context.hits] == ["barony"]
    assert all(entry.book_id == "barony" for entry in context.source_map)


def test_vector_candidates_query_with_resolved_provider_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = replace(
        make_config(tmp_path),
        embedding_provider="local-hash-alias",
        embedding_model="config-model-alias",
        embedding_dimensions=8,
    )
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=1,
            text="Critical hit rules are here.",
        )
        connection.execute(
            "update books set search_status = 'indexed' where id = 'core-rules'"
        )
        insert_source_object(
            connection,
            object_id="core-rules:critical-hits",
            book_id="core-rules",
            page_id="core-rules:1",
            object_type="rule_section",
            title="Critical Hits",
            heading_path=("Chapter I: Combat",),
            page_start=1,
            page_end=1,
            text="Critical hit rules are here.",
        )
        source_object = connection.execute(
            """
            select id, text_snapshot_sha256
            from source_objects
            where id = 'core-rules:critical-hits'
            """
        ).fetchone()
        snapshot = embedding_source_snapshot_sha256(connection, "core-rules")
        connection.execute(
            """
            insert into book_retrieval_status (
              book_id,
              vector_status,
              vector_snapshot_sha256,
              embedding_provider,
              embedding_model,
              embedding_dimensions,
              updated_at
            )
            values (
              'core-rules',
              'indexed',
              ?,
              'local-hash',
              'local-hash-test',
              4,
              '2026-06-08T00:00:00Z'
            )
            """,
            (snapshot,),
        )
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
              'embedding:critical-hits',
              ?,
              'core-rules',
              'local-hash',
              'local-hash-test',
              4,
              ?,
              ?,
              '2026-06-08T00:00:00Z',
              '2026-06-08T00:00:00Z'
            )
            """,
            (
                source_object["id"],
                source_object["text_snapshot_sha256"],
                vector_blob((1.0, 0.0, 0.0, 0.0)),
            ),
        )

        calls: list[str] = []

        class FakeProvider:
            provider_name = "local-hash"
            model_name = "local-hash-test"
            dimensions = 4

            def embed_documents(self, texts):  # noqa: ANN001
                raise AssertionError("query search must not embed documents")

            def embed_query(self, text: str) -> tuple[float, ...]:
                calls.append(text)
                return (1.0, 0.0, 0.0, 0.0)

        monkeypatch.setattr(
            retrieval_candidates,
            "resolve_embedding_provider",
            lambda config: FakeProvider(),
            raising=False,
        )
        monkeypatch.setattr(
            embedding_module,
            "resolve_embedding_provider",
            lambda config: FakeProvider(),
            raising=False,
        )

        candidates = retrieval_candidates.search_vector_candidates(
            connection,
            "critical hits",
            book_ids=("core-rules",),
            limit=5,
            config=config,
        )

        assert candidates
        assert candidates[0].source_object_id == "core-rules:critical-hits"
        assert "vector_provider:local-hash" in candidates[0].rank_reasons
        assert "vector_model:local-hash-test" in candidates[0].rank_reasons

        def fail_vector_from_blob(_blob: bytes) -> tuple[float, ...]:
            raise ValueError("bad vector blob")

        monkeypatch.setattr(
            retrieval_candidates,
            "vector_from_blob",
            fail_vector_from_blob,
        )

        assert (
            retrieval_candidates.search_vector_candidates(
                connection,
                "critical hits",
                book_ids=("core-rules",),
                limit=5,
                config=config,
            )
            == ()
        )

    assert calls == ["critical hits", "critical hits"]


def test_vector_candidates_ignore_unsupported_embedding_provider(
    tmp_path: Path,
) -> None:
    config = replace(
        make_config(tmp_path),
        embedding_provider="custom",
        embedding_model="custom-model",
        embedding_dimensions=4,
    )
    with initialize_database(config.db_path) as connection:
        assert (
            retrieval_candidates.search_vector_candidates(
                connection,
                "critical hits",
                book_ids=("core-rules",),
                limit=5,
                config=config,
            )
            == ()
        )


def test_vector_candidates_ignore_embedding_provider_runtime_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = replace(
        make_config(tmp_path),
        embedding_provider="sentence-transformers",
        embedding_model="BAAI/bge-m3",
        embedding_dimensions=4,
    )
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=1,
            text="Critical hit rules are here.",
        )
        connection.execute(
            "update books set search_status = 'indexed' where id = 'core-rules'"
        )
        insert_source_object(
            connection,
            object_id="core-rules:critical-hits",
            book_id="core-rules",
            page_id="core-rules:1",
            object_type="rule_section",
            title="Critical Hits",
            heading_path=("Chapter I: Combat",),
            page_start=1,
            page_end=1,
            text="Critical hit rules are here.",
        )
        source_object = connection.execute(
            """
            select id, text_snapshot_sha256
            from source_objects
            where id = 'core-rules:critical-hits'
            """
        ).fetchone()
        snapshot = embedding_source_snapshot_sha256(connection, "core-rules")
        connection.execute(
            """
            insert into book_retrieval_status (
              book_id,
              vector_status,
              vector_snapshot_sha256,
              embedding_provider,
              embedding_model,
              embedding_dimensions,
              updated_at
            )
            values (
              'core-rules',
              'indexed',
              ?,
              'sentence-transformers',
              'BAAI/bge-m3',
              4,
              '2026-06-08T00:00:00Z'
            )
            """,
            (snapshot,),
        )
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
              'embedding:critical-hits',
              ?,
              'core-rules',
              'sentence-transformers',
              'BAAI/bge-m3',
              4,
              ?,
              ?,
              '2026-06-08T00:00:00Z',
              '2026-06-08T00:00:00Z'
            )
            """,
            (
                source_object["id"],
                source_object["text_snapshot_sha256"],
                vector_blob((1.0, 0.0, 0.0, 0.0)),
            ),
        )

        class FailingProvider:
            provider_name = "sentence-transformers"
            model_name = "BAAI/bge-m3"
            dimensions = 4

            def embed_documents(self, texts):  # noqa: ANN001
                raise AssertionError("query search must not embed documents")

            def embed_query(self, text: str) -> tuple[float, ...]:
                raise EmbeddingProviderDependencyError("missing dependency")

        monkeypatch.setattr(
            retrieval_candidates,
            "resolve_embedding_provider",
            lambda config: FailingProvider(),
            raising=False,
        )

        assert (
            retrieval_candidates.search_vector_candidates(
                connection,
                "critical hits",
                book_ids=("core-rules",),
                limit=5,
                config=config,
            )
            == ()
        )
        assert (
            retrieval_candidates.search_vector_candidates_with_status(
                connection,
                "critical hits",
                book_ids=("core-rules",),
                limit=5,
                config=config,
            ).status
            == "provider_error"
        )


def test_vector_channel_reports_ran_no_candidates_when_current_vectors_match_nothing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = replace(
        make_config(tmp_path),
        embedding_provider="fake-semantic-empty",
        embedding_model="fake-semantic-empty-model",
        embedding_dimensions=3,
    )

    class FakeSemanticProvider:
        provider_name = "fake-semantic-empty"
        model_name = "fake-semantic-empty-model"
        dimensions = 3

        def embed_documents(self, texts):  # noqa: ANN001
            raise AssertionError("test inserts synthetic vectors directly")

        def embed_query(self, text: str) -> tuple[float, ...]:
            return (1.0, 0.0, 0.0)

    provider = FakeSemanticProvider()
    monkeypatch.setattr(
        embedding_module,
        "resolve_embedding_provider",
        lambda config: provider,
    )
    monkeypatch.setattr(
        retrieval_candidates,
        "resolve_embedding_provider",
        lambda config: provider,
    )
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=1,
            text="Critical Hits determine injury results.",
        )
        connection.execute(
            "update books set search_status = 'indexed' where id = 'core-rules'"
        )
        insert_source_object(
            connection,
            object_id="core-rules:critical-hits",
            book_id="core-rules",
            page_id="core-rules:1",
            object_type="rule_section",
            title="Critical Hits",
            heading_path=("Combat",),
            page_start=1,
            page_end=1,
            text="Critical Hits determine injury results.",
        )
        source_object = connection.execute(
            """
            select id, text_snapshot_sha256
            from source_objects
            where id = 'core-rules:critical-hits'
            """
        ).fetchone()
        snapshot = embedding_source_snapshot_sha256(connection, "core-rules")
        connection.execute(
            """
            insert into book_retrieval_status (
              book_id,
              vector_status,
              vector_snapshot_sha256,
              embedding_provider,
              embedding_model,
              embedding_dimensions,
              updated_at
            )
            values ('core-rules', 'indexed', ?, 'fake-semantic-empty',
                    'fake-semantic-empty-model', 3, '2026-06-08T00:00:00Z')
            """,
            (snapshot,),
        )
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
            values ('embedding:semantic-empty', ?, 'core-rules',
                    'fake-semantic-empty', 'fake-semantic-empty-model', 3, ?, ?,
                    '2026-06-08T00:00:00Z', '2026-06-08T00:00:00Z')
            """,
            (
                source_object["id"],
                source_object["text_snapshot_sha256"],
                vector_blob((-1.0, 0.0, 0.0)),
            ),
        )

    result = retrieval_candidates.collect_evidence_candidates_with_diagnostics(
        config,
        source_book_ids=("core-rules",),
        query_plan=retrieval.plan_query("wounds", ()),
        per_candidate_limit=5,
    )

    assert result.diagnostics.vector_status == "ran_no_candidates"
    assert result.diagnostics.channel_counts["vector"] == 0
    assert result.diagnostics.channel_skip_reasons["vector"] == "ran_no_candidates"


@pytest.mark.parametrize(
    ("vector_status", "stored_provider"),
    (
        ("needs_refresh", "fake-semantic-stale"),
        ("indexed", "old-provider"),
    ),
)
def test_vector_status_reports_stale_embeddings_when_index_is_not_current(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    vector_status: str,
    stored_provider: str,
) -> None:
    config = replace(
        make_config(tmp_path),
        embedding_provider="fake-semantic-stale",
        embedding_model="fake-semantic-stale-model",
        embedding_dimensions=3,
    )

    class FakeSemanticProvider:
        provider_name = "fake-semantic-stale"
        model_name = "fake-semantic-stale-model"
        dimensions = 3

        def embed_documents(self, texts):  # noqa: ANN001
            raise AssertionError("test does not rebuild embeddings")

        def embed_query(self, text: str) -> tuple[float, ...]:
            return (1.0, 0.0, 0.0)

    provider = FakeSemanticProvider()
    monkeypatch.setattr(
        embedding_module,
        "resolve_embedding_provider",
        lambda config: provider,
    )
    monkeypatch.setattr(
        retrieval_candidates,
        "resolve_embedding_provider",
        lambda config: provider,
    )
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=1,
            text="Critical Hits determine injury results.",
        )
        connection.execute(
            "update books set search_status = 'indexed' where id = 'core-rules'"
        )
        insert_source_object(
            connection,
            object_id="core-rules:critical-hits",
            book_id="core-rules",
            page_id="core-rules:1",
            object_type="rule_section",
            title="Critical Hits",
            heading_path=("Combat",),
            page_start=1,
            page_end=1,
            text="Critical Hits determine injury results.",
        )
        snapshot = embedding_source_snapshot_sha256(connection, "core-rules")
        connection.execute(
            """
            insert into book_retrieval_status (
              book_id,
              vector_status,
              vector_snapshot_sha256,
              embedding_provider,
              embedding_model,
              embedding_dimensions,
              updated_at
            )
            values ('core-rules', ?, ?, ?, 'fake-semantic-stale-model', 3,
                    '2026-06-08T00:00:00Z')
            """,
            (vector_status, snapshot, stored_provider),
        )

    result = retrieval_candidates.collect_evidence_candidates_with_diagnostics(
        config,
        source_book_ids=("core-rules",),
        query_plan=retrieval.plan_query("wounds", ()),
        per_candidate_limit=5,
    )

    assert result.diagnostics.vector_status == "stale_embeddings"
    assert result.diagnostics.channel_skip_reasons["vector"] == "stale_embeddings"


@pytest.mark.parametrize(
    ("status_row", "expected_status"),
    (
        (None, "missing_embeddings"),
        (("failed", "fake-semantic", "fake-semantic-model", 3), "provider_error"),
        (("indexed", "fake-semantic", "old-model", 3), "stale_embeddings"),
        (("indexed", "fake-semantic", "fake-semantic-model", 4), "stale_embeddings"),
    ),
)
def test_vector_unavailable_status_reports_precise_noncurrent_reasons(
    tmp_path: Path,
    status_row: tuple[str, str, str, int] | None,
    expected_status: str,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=1,
            text="Critical Hits determine injury results.",
        )
        insert_source_object(
            connection,
            object_id="core-rules:critical-hits",
            book_id="core-rules",
            page_id="core-rules:1",
            object_type="rule_section",
            title="Critical Hits",
            heading_path=("Combat",),
            page_start=1,
            page_end=1,
            text="Critical Hits determine injury results.",
        )
        if status_row is not None:
            vector_status, stored_provider, stored_model, stored_dimensions = status_row
            connection.execute(
                """
                insert into book_retrieval_status (
                  book_id,
                  vector_status,
                  vector_snapshot_sha256,
                  embedding_provider,
                  embedding_model,
                  embedding_dimensions,
                  updated_at
                )
                values ('core-rules', ?, ?, ?, ?, ?, '2026-06-08T00:00:00Z')
                """,
                (
                    vector_status,
                    embedding_source_snapshot_sha256(connection, "core-rules"),
                    stored_provider,
                    stored_model,
                    stored_dimensions,
                ),
            )

        assert (
            retrieval_candidates.vector_unavailable_status(
                connection,
                ("core-rules",),
                provider_name="fake-semantic",
                model_name="fake-semantic-model",
                dimensions=3,
            )
            == expected_status
        )


def test_fake_semantic_provider_recalls_related_source_object_without_exact_terms(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = replace(
        make_config(tmp_path),
        embedding_provider="fake-semantic",
        embedding_model="fake-semantic-model",
        embedding_dimensions=3,
    )

    class FakeSemanticProvider:
        provider_name = "fake-semantic"
        model_name = "fake-semantic-model"
        dimensions = 3

        def embed_documents(self, texts):  # noqa: ANN001
            raise AssertionError("test inserts synthetic vectors directly")

        def embed_query(self, text: str) -> tuple[float, ...]:
            assert text == "after devastating blow battle"
            return (1.0, 0.0, 0.0)

    provider = FakeSemanticProvider()
    monkeypatch.setattr(
        embedding_module,
        "resolve_embedding_provider",
        lambda config: provider,
    )
    monkeypatch.setattr(
        retrieval_candidates,
        "resolve_embedding_provider",
        lambda config: provider,
    )
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=1,
            text="Critical Hits determine injury results.",
        )
        connection.execute(
            "update books set search_status = 'indexed' where id = 'core-rules'"
        )
        insert_source_object(
            connection,
            object_id="core-rules:critical-hits",
            book_id="core-rules",
            page_id="core-rules:1",
            object_type="rule_section",
            title="Critical Hits",
            heading_path=("Combat",),
            page_start=1,
            page_end=1,
            text="Critical Hits determine injury results.",
        )
        source_object = connection.execute(
            """
            select id, text_snapshot_sha256
            from source_objects
            where id = 'core-rules:critical-hits'
            """
        ).fetchone()
        snapshot = embedding_source_snapshot_sha256(connection, "core-rules")
        connection.execute(
            """
            insert into book_retrieval_status (
              book_id,
              vector_status,
              vector_snapshot_sha256,
              embedding_provider,
              embedding_model,
              embedding_dimensions,
              updated_at
            )
            values ('core-rules', 'indexed', ?, 'fake-semantic',
                    'fake-semantic-model', 3, '2026-06-08T00:00:00Z')
            """,
            (snapshot,),
        )
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
            values ('embedding:semantic-critical', ?, 'core-rules',
                    'fake-semantic', 'fake-semantic-model', 3, ?, ?,
                    '2026-06-08T00:00:00Z', '2026-06-08T00:00:00Z')
            """,
            (
                source_object["id"],
                source_object["text_snapshot_sha256"],
                vector_blob((1.0, 0.0, 0.0)),
            ),
        )

    candidates = retrieval.collect_evidence_candidates(
        config,
        source_book_ids=("core-rules",),
        query_plan=retrieval.plan_query(
            "What happens after a devastating blow in battle?",
            (),
        ),
        per_candidate_limit=5,
    )

    assert any(
        candidate.channel == "vector"
        and candidate.source_object_id == "core-rules:critical-hits"
        for candidate in candidates
    )


def test_exact_source_object_still_outranks_related_vector_only_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = replace(
        make_config(tmp_path),
        embedding_provider="fake-semantic-rank",
        embedding_model="fake-semantic-rank-model",
        embedding_dimensions=3,
    )

    class FakeSemanticProvider:
        provider_name = "fake-semantic-rank"
        model_name = "fake-semantic-rank-model"
        dimensions = 3

        def embed_documents(self, texts):  # noqa: ANN001
            raise AssertionError("test inserts synthetic vectors directly")

        def embed_query(self, text: str) -> tuple[float, ...]:
            assert text == "critical hits"
            return (1.0, 0.0, 0.0)

    provider = FakeSemanticProvider()
    monkeypatch.setattr(
        embedding_module,
        "resolve_embedding_provider",
        lambda config: provider,
    )
    monkeypatch.setattr(
        retrieval_candidates,
        "resolve_embedding_provider",
        lambda config: provider,
    )
    with initialize_database(config.db_path) as connection:
        for page_number, object_id, title, text, vector in (
            (
                1,
                "core-rules:critical-hits",
                "Critical Hits",
                "Critical Hits table entries.",
                (0.0, 1.0, 0.0),
            ),
            (
                2,
                "core-rules:related-wounds",
                "Battle Wounds",
                "A related injury section after a mighty strike.",
                (1.0, 0.0, 0.0),
            ),
        ):
            insert_searchable_page(
                connection,
                book_id="core-rules",
                title="Core Rules",
                category="Core Book & GM Essentials",
                page_number=page_number,
                text=text,
                page_count=2,
            )
            insert_source_object(
                connection,
                object_id=object_id,
                book_id="core-rules",
                page_id=f"core-rules:{page_number}",
                object_type="table" if page_number == 1 else "rule_section",
                title=title,
                heading_path=("Combat",),
                page_start=page_number,
                page_end=page_number,
                text=text,
            )
            source_object = connection.execute(
                """
                select id, text_snapshot_sha256
                from source_objects
                where id = ?
                """,
                (object_id,),
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
                values (?, ?, 'core-rules', 'fake-semantic-rank',
                        'fake-semantic-rank-model', 3, ?, ?,
                        '2026-06-08T00:00:00Z', '2026-06-08T00:00:00Z')
                """,
                (
                    f"embedding:{object_id}",
                    source_object["id"],
                    source_object["text_snapshot_sha256"],
                    vector_blob(vector),
                ),
            )
        connection.execute(
            "update books set search_status = 'indexed' where id = 'core-rules'"
        )
        snapshot = embedding_source_snapshot_sha256(connection, "core-rules")
        connection.execute(
            """
            insert into book_retrieval_status (
              book_id,
              vector_status,
              vector_snapshot_sha256,
              embedding_provider,
              embedding_model,
              embedding_dimensions,
              updated_at
            )
            values ('core-rules', 'indexed', ?, 'fake-semantic-rank',
                    'fake-semantic-rank-model', 3, '2026-06-08T00:00:00Z')
            """,
            (snapshot,),
        )

    query_plan = retrieval.plan_query("critical hits", ())
    candidates = retrieval.collect_evidence_candidates(
        config,
        source_book_ids=("core-rules",),
        query_plan=query_plan,
        per_candidate_limit=5,
    )
    assert any(
        candidate.channel == "vector"
        and candidate.source_object_id == "core-rules:related-wounds"
        for candidate in candidates
    )
    ranked = retrieval.rerank_candidates(candidates, query_plan)

    assert ranked[0][0].source_object_id == "core-rules:critical-hits"
    assert ranked[0][0].channel != "vector"


def test_source_map_reads_current_durable_maps_for_checked_books(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=1,
            text="Critical hit rules are here.",
        )
        insert_source_object(
            connection,
            object_id="core-rules:critical-hits",
            book_id="core-rules",
            page_id="core-rules:1",
            object_type="rule_section",
            title="Critical Hits",
            heading_path=("Chapter I: Combat", "Critical Hits"),
            page_start=1,
            page_end=1,
            text="Critical hit rules are here.",
        )
        insert_searchable_page(
            connection,
            book_id="barony",
            title="Barony of the Damned",
            category="Adventure Modules and Campaigns",
            page_number=1,
            text="The black knight waits here.",
        )
        insert_source_object(
            connection,
            object_id="barony:black-knight",
            book_id="barony",
            page_id="barony:1",
            object_type="encounter",
            title="Black Knight",
            heading_path=("Chapter II", "Black Knight"),
            page_start=1,
            page_end=1,
            text="The black knight waits here.",
        )
        core_snapshot = source_object_snapshot_sha256(connection, "core-rules")
        barony_snapshot = source_object_snapshot_sha256(connection, "barony")
        for book_id, snapshot, summary, aliases, chapters, best_source_for in (
            (
                "core-rules",
                core_snapshot,
                "Durable Core summary.",
                ("durable-critical", "durable-rules"),
                ("Durable Combat",),
                ("rules_lookup",),
            ),
            (
                "barony",
                barony_snapshot,
                "Unchecked durable adventure summary.",
                ("unchecked-leak",),
                ("Unchecked Chapter",),
                ("adventure_scene_lookup",),
            ),
        ):
            connection.execute(
                """
                insert into book_retrieval_status (book_id, updated_at)
                values (?, '2026-06-05T00:00:00Z')
                """,
                (book_id,),
            )
            connection.execute(
                """
                update book_retrieval_status
                set source_map_status = 'indexed',
                    source_object_snapshot_sha256 = ?,
                    source_map_snapshot_sha256 = ?,
                    updated_at = '2026-06-05T00:00:00Z'
                where book_id = ?
                """,
                (snapshot, snapshot, book_id),
            )
            connection.execute(
                """
                insert into book_source_maps (
                  book_id,
                  summary,
                  aliases_json,
                  chapters_json,
                  best_source_for_json,
                  source_object_snapshot_sha256,
                  schema_version,
                  builder_version,
                  created_at,
                  updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, '2026-06-05T00:00:00Z',
                        '2026-06-05T00:00:00Z')
                """,
                (
                    book_id,
                    summary,
                    json.dumps(list(aliases)),
                    json.dumps(list(chapters)),
                    json.dumps(list(best_source_for)),
                    snapshot,
                    SCHEMA_VERSION,
                    BUILDER_VERSION,
                ),
            )

    source_map = retrieval.build_enabled_source_map(
        config,
        ("core-rules",),
        query_terms=("critical",),
    )

    assert len(source_map) == 1
    assert source_map[0].book_id == "core-rules"
    assert source_map[0].summary == "Durable Core summary."
    assert source_map[0].aliases == ("durable-critical", "durable-rules")
    assert source_map[0].chapters == ("Durable Combat",)
    assert source_map[0].best_source_for == ("rules_lookup",)
    assert all(entry.book_id != "barony" for entry in source_map)
    assert "unchecked-leak" not in source_map[0].aliases


def test_source_map_falls_back_when_durable_map_is_stale_or_malformed(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=1,
            text="Critical hit rules are here.",
        )
        insert_source_object(
            connection,
            object_id="core-rules:critical-hits",
            book_id="core-rules",
            page_id="core-rules:1",
            object_type="rule_section",
            title="Critical Hits",
            heading_path=("Chapter I: Combat", "Critical Hits"),
            page_start=1,
            page_end=1,
            text="Critical hit rules are here.",
        )
        snapshot = source_object_snapshot_sha256(connection, "core-rules")
        connection.execute(
            """
            insert into book_retrieval_status (book_id, updated_at)
            values ('core-rules', '2026-06-05T00:00:00Z')
            """
        )
        connection.execute(
            """
            update book_retrieval_status
            set source_map_status = 'indexed',
                source_object_snapshot_sha256 = ?,
                source_map_snapshot_sha256 = 'stale-snapshot',
                updated_at = '2026-06-05T00:00:00Z'
            where book_id = 'core-rules'
            """,
            (snapshot,),
        )
        connection.execute(
            """
            insert into book_source_maps (
              book_id,
              summary,
              aliases_json,
              chapters_json,
              best_source_for_json,
              source_object_snapshot_sha256,
              schema_version,
              builder_version,
              created_at,
              updated_at
            )
            values ('core-rules', 'Stale durable summary.', '{bad json',
                    '["Stale Chapter"]', '["rules_lookup"]', ?, ?, ?,
                    '2026-06-05T00:00:00Z', '2026-06-05T00:00:00Z')
            """,
            (snapshot, SCHEMA_VERSION, BUILDER_VERSION),
        )

    source_map = retrieval.build_enabled_source_map(
        config,
        ("core-rules",),
        query_terms=("critical",),
    )

    assert len(source_map) == 1
    assert source_map[0].summary != "Stale durable summary."
    assert "Critical Hits" in source_map[0].chapters


def test_source_map_falls_back_when_current_durable_map_is_malformed(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=1,
            text="Critical hit rules are here.",
        )
        insert_source_object(
            connection,
            object_id="core-rules:critical-hits",
            book_id="core-rules",
            page_id="core-rules:1",
            object_type="rule_section",
            title="Critical Hits",
            heading_path=("Chapter I: Combat", "Critical Hits"),
            page_start=1,
            page_end=1,
            text="Critical hit rules are here.",
        )
        snapshot = source_object_snapshot_sha256(connection, "core-rules")
        connection.execute(
            """
            insert into book_retrieval_status (
              book_id,
              source_map_status,
              source_object_snapshot_sha256,
              source_map_snapshot_sha256,
              updated_at
            )
            values ('core-rules', 'indexed', ?, ?,
                    '2026-06-05T00:00:00Z')
            """,
            (snapshot, snapshot),
        )
        connection.execute(
            """
            insert into book_source_maps (
              book_id,
              summary,
              aliases_json,
              chapters_json,
              best_source_for_json,
              source_object_snapshot_sha256,
              schema_version,
              builder_version,
              created_at,
              updated_at
            )
            values ('core-rules', 'Malformed durable summary.', '{bad json',
                    '["Current Chapter"]', '["rules_lookup"]', ?, ?, ?,
                    '2026-06-05T00:00:00Z', '2026-06-05T00:00:00Z')
            """,
            (snapshot, SCHEMA_VERSION, BUILDER_VERSION),
        )

    source_map = retrieval.build_enabled_source_map(
        config,
        ("core-rules",),
        query_terms=("critical",),
    )

    assert len(source_map) == 1
    assert source_map[0].summary != "Malformed durable summary."
    assert "Critical Hits" in source_map[0].chapters


def test_retrieval_broad_pool_reranks_relevant_hit_over_filler(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="filler",
            title="Conversational Primer",
            category="Core Book & GM Essentials",
            page_number=1,
            text=(
                "You tell me which powerful king you have in mind. "
                "This page is conversational filler and has no regional lore."
            ),
        )
        insert_searchable_page(
            connection,
            book_id="grail",
            title="Knights of the Grail",
            category="World Guides and Faction Sourcebooks",
            page_number=12,
            text=(
                "Bretonnia is divided into duchies ruled by dukes. "
                "The king stands above the dukes as the most powerful noble."
            ),
        )
    source_sets.ensure_builtin_source_sets(config)
    source_sets.set_book_enabled(config, "rules-core", "grail", True)
    rebuild_global_fts(config)
    thread = chat_store.create_thread(config)

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "Can you tell me which Bretonia duchy has a powerful king?",
        hit_limit=1,
        total_char_limit=500,
        window_chars=180,
    )

    assert context.source_book_ids == ("filler", "grail")
    assert [hit.book_id for hit in context.hits] == ["grail"]
    assert "bretonnia" in context.hits[0].context_text.lower()
    assert any(
        "expanded:bretonia->bretonnia" in reason
        for reason in context.hits[0].rank_reasons
    )
    assert any(
        "semantic_overlap" in reason for reason in context.hits[0].rank_reasons
    )
    assert any(reason.startswith("fusion:rrf=") for reason in context.hits[0].rank_reasons)
    assert any(
        reason.startswith("reranker:deterministic:accepted")
        for reason in context.hits[0].rank_reasons
    )


def test_retrieval_rejects_weak_lexical_candidate_after_fusion(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="filler",
            title="Coin Tossing Etiquette",
            category="Core Book & GM Essentials",
            page_number=1,
            text=(
                "The word critical appears in a joke about counting coins. "
                "Nothing here explains bookkeeping or ledgers."
            ),
        )
    source_sets.ensure_builtin_source_sets(config)
    rebuild_global_fts(config)
    thread = chat_store.create_thread(config)

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "critical hit injury result",
        hit_limit=1,
        total_char_limit=500,
        window_chars=180,
    )

    assert context.hits == ()


def test_reciprocal_rank_fusion_prefers_candidate_seen_by_multiple_channels() -> None:
    page_only = retrieval.EvidenceCandidate(
        book_id="core-rules",
        title="Core Rules",
        category="Core",
        page_id="core-rules:1",
        page_number=1,
        pdf_page_number=1,
        page_label=None,
        page_start=1,
        page_end=1,
        page_range_label=None,
        snippet="critical hit",
        base_score=-0.8,
        context_text="critical hit",
        channel="page_fts",
        rank_reasons=("candidate:page_fts",),
    )
    multi_page = retrieval.EvidenceCandidate(
        book_id="core-rules",
        title="Core Rules",
        category="Core",
        page_id="core-rules:2",
        page_number=2,
        pdf_page_number=2,
        page_label=None,
        page_start=2,
        page_end=2,
        page_range_label=None,
        snippet="critical hit table",
        base_score=-0.4,
        context_text="critical hit table",
        channel="page_fts",
        source_object_id="critical-table",
        object_type="table",
        object_title="Critical Hits",
        rank_reasons=("candidate:page_fts",),
    )
    multi_object = retrieval.EvidenceCandidate(
        book_id="core-rules",
        title="Core Rules",
        category="Core",
        page_id="core-rules:2",
        page_number=2,
        pdf_page_number=2,
        page_label=None,
        page_start=2,
        page_end=2,
        page_range_label=None,
        snippet="critical hit table",
        base_score=-0.2,
        context_text="critical hit table",
        channel="source_object_fts",
        source_object_id="critical-table",
        object_type="table",
        object_title="Critical Hits",
        rank_reasons=("candidate:source_object_fts",),
    )

    fused = retrieval.reciprocal_rank_fuse((page_only, multi_page, multi_object))

    assert [candidate.dedupe_key for candidate in fused] == [
        "source-object:critical-table",
        "page:core-rules:1",
    ]
    assert any(
        "fusion_channel:page_fts@2" in reason for reason in fused[0].rank_reasons
    )
    assert any(
        "fusion_channel:source_object_fts@1" in reason
        for reason in fused[0].rank_reasons
    )
    assert retrieval.ReciprocalRankFusion(rank_constant=60).fuse((page_only,))[
        0
    ].dedupe_key == "page:core-rules:1"
    with pytest.raises(ValueError, match="rank_constant"):
        retrieval.reciprocal_rank_fuse((page_only,), rank_constant=0)


def test_reciprocal_rank_fusion_deduplicates_channel_before_ranking() -> None:
    duplicate_best = retrieval.EvidenceCandidate(
        book_id="core-rules",
        title="Core Rules",
        category="Core",
        page_id="core-rules:1",
        page_number=1,
        pdf_page_number=1,
        page_label=None,
        page_start=1,
        page_end=1,
        page_range_label=None,
        snippet="critical hit",
        base_score=-0.9,
        context_text="critical hit",
        channel="page_fts",
    )
    duplicate_worse = retrieval.EvidenceCandidate(
        book_id="core-rules",
        title="Core Rules",
        category="Core",
        page_id="core-rules:1",
        page_number=1,
        pdf_page_number=1,
        page_label=None,
        page_start=1,
        page_end=1,
        page_range_label=None,
        snippet="critical hit",
        base_score=-0.8,
        context_text="critical hit",
        channel="page_fts",
    )
    next_unique = retrieval.EvidenceCandidate(
        book_id="core-rules",
        title="Core Rules",
        category="Core",
        page_id="core-rules:2",
        page_number=2,
        pdf_page_number=2,
        page_label=None,
        page_start=2,
        page_end=2,
        page_range_label=None,
        snippet="critical hit table",
        base_score=-0.7,
        context_text="critical hit table",
        channel="page_fts",
    )

    fused = retrieval.reciprocal_rank_fuse(
        (duplicate_best, duplicate_worse, next_unique)
    )

    assert [candidate.dedupe_key for candidate in fused] == [
        "page:core-rules:1",
        "page:core-rules:2",
    ]
    assert any(
        reason.startswith("fusion_channel:page_fts@2:")
        for reason in fused[1].rank_reasons
    )


def test_retrieval_preserves_exact_table_name_candidate(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    table_text = (
        "Critical Hit Effects\n"
        "This table lists critical hit effects and the injury result to apply."
    )
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=17,
            text=table_text,
        )
        insert_source_object(
            connection,
            object_id="core-rules:critical-hit-effects",
            book_id="core-rules",
            page_id="core-rules:17",
            object_type="table",
            title="Critical Hit Effects",
            heading_path=("Combat", "Critical Hit Effects"),
            page_start=17,
            page_end=17,
            text=table_text,
        )
    source_sets.ensure_builtin_source_sets(config)
    rebuild_global_fts(config)
    thread = chat_store.create_thread(config)

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "Critical Hit Effects table",
        hit_limit=1,
        total_char_limit=500,
        window_chars=180,
    )

    assert len(context.hits) == 1
    assert context.hits[0].source_object_id == "core-rules:critical-hit-effects"
    assert context.hits[0].object_type == "table"
    assert any("phrase_match:query_terms" in reason for reason in context.hits[0].rank_reasons)


def test_retrieval_preserves_object_type_table_candidate(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    table_text = (
        "Wyrdstone\n"
        "Roll once for the strange mineral result and apply the listed entry."
    )
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=18,
            text=table_text,
        )
        insert_source_object(
            connection,
            object_id="core-rules:wyrdstone",
            book_id="core-rules",
            page_id="core-rules:18",
            object_type="table",
            title="Wyrdstone",
            heading_path=("Appendix", "Wyrdstone"),
            page_start=18,
            page_end=18,
            text=table_text,
        )
        connection.execute(
            """
            insert into source_object_search (
              source_object_id,
              book_id,
              page_id,
              object_type,
              title,
              heading_path,
              page_start,
              page_end,
              confidence,
              search_text
            )
            values (
              'core-rules:wyrdstone',
              'core-rules',
              'core-rules:18',
              'table',
              'Wyrdstone',
              'Appendix > Wyrdstone',
              18,
              18,
              0.91,
              ?
            )
            """,
            (table_text,),
        )
        connection.execute(
            "insert into source_object_search_fts(source_object_search_fts) values('rebuild')"
        )
    source_sets.ensure_builtin_source_sets(config)
    rebuild_global_fts(config)
    thread = chat_store.create_thread(config)

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "Wyrdstone table",
        hit_limit=1,
        total_char_limit=500,
        window_chars=180,
    )

    assert len(context.hits) == 1
    assert context.hits[0].source_object_id == "core-rules:wyrdstone"
    assert context.hits[0].object_type == "table"


def test_retrieval_resolves_hits_to_complete_source_object_spans(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    section_text = (
        "Critical Hits\n"
        "A critical hit begins with a table result on the first page.\n"
        "The second page explains how the result continues and is applied."
    )
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=1,
            page_label="10",
            page_count=2,
            text="Critical Hits\nA critical hit begins with a table result on the first page.",
        )
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=2,
            page_label="11",
            page_count=2,
            text="The second page explains how the result continues and is applied.",
        )
        insert_source_object(
            connection,
            object_id="core-rules:critical-hits",
            book_id="core-rules",
            page_id="core-rules:1",
            object_type="rule_section",
            title="Critical Hits",
            heading_path=("Chapter I: Combat", "Critical Hits"),
            page_start=1,
            page_end=2,
            text=section_text,
        )
    source_sets.ensure_builtin_source_sets(config)
    rebuild_global_fts(config)
    thread = chat_store.create_thread(config)

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "How do critical hits continue?",
        hit_limit=1,
        total_char_limit=600,
        window_chars=120,
    )

    assert len(context.hits) == 1
    hit = context.hits[0]
    assert hit.source_object_id == "core-rules:critical-hits"
    assert hit.object_type == "rule_section"
    assert hit.heading_path == ("Chapter I: Combat", "Critical Hits")
    assert hit.page_start == 1
    assert hit.page_end == 2
    assert hit.page_label == "10"
    assert hit.page_range_label == "10-11"
    assert "first page" in hit.context_text
    assert "second page" in hit.context_text
    assert "source_object:rule_section" in hit.rank_reasons


def test_table_row_retrieval_resolves_to_complete_parent_table(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    table_text = (
        "Weather Results\n"
        "| Roll | Result |\n"
        "| 1 | Clear skies |\n"
        "| 2 | Storms force a travel test |\n"
    )
    row_text = "| 2 | Storms force a travel test |"
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=10,
            page_label="100",
            page_count=11,
            text="Weather Results table row two has storms that force a travel test.",
        )
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=11,
            page_label="101",
            page_count=11,
            text="The weather table continues with journey guidance.",
        )
        insert_source_object(
            connection,
            object_id="core-rules:weather-table",
            book_id="core-rules",
            page_id="core-rules:10",
            object_type="table",
            title="Weather Results",
            heading_path=("Travel", "Weather Results"),
            page_start=10,
            page_end=11,
            text=table_text + "Use the result for the next journey.",
        )
        insert_source_object(
            connection,
            object_id="core-rules:weather-row-2",
            book_id="core-rules",
            page_id="core-rules:10",
            object_type="table_row",
            title="Weather Results row 2",
            heading_path=("Travel", "Weather Results"),
            page_start=10,
            page_end=10,
            text=row_text,
            parent_object_id="core-rules:weather-table",
        )
        insert_source_object_link(
            connection,
            link_id="weather-row-2-parent",
            from_object_id="core-rules:weather-row-2",
            to_object_id="core-rules:weather-table",
            to_book_id="core-rules",
            to_page_id="core-rules:10",
            link_type="table_row",
            label="Weather Results",
        )
    source_sets.ensure_builtin_source_sets(config)
    rebuild_global_fts(config)
    thread = chat_store.create_thread(config)

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "storm table row weather",
        hit_limit=1,
        total_char_limit=700,
        window_chars=120,
    )

    assert len(context.hits) == 1
    hit = context.hits[0]
    assert hit.source_object_id == "core-rules:weather-table"
    assert hit.object_type == "table"
    assert hit.object_title == "Weather Results"
    assert hit.page_start == 10
    assert hit.page_end == 11
    assert hit.page_range_label == "100-101"
    assert "Clear skies" in hit.context_text
    assert "Storms force a travel test" in hit.context_text
    assert any("linked_evidence:table_row" in reason for reason in hit.rank_reasons)


def test_stat_block_retrieval_resolves_to_complete_profile(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    profile_text = (
        "Captain Mira\n"
        "M WS BS S T W I A Dex Int WP Fel\n"
        "4 41 32 3 3 12 38 1 34 35 36 37\n"
        "Skills: Command, Perception\n"
        "Talents: Coolheaded\n"
    )
    stat_text = (
        "M WS BS S T W I A Dex Int WP Fel\n"
        "4 41 32 3 3 12 38 1 34 35 36 37"
    )
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=12,
            text="Captain Mira has WS 41 and the Command skill.",
        )
        insert_source_object(
            connection,
            object_id="core-rules:captain-mira",
            book_id="core-rules",
            page_id="core-rules:12",
            object_type="npc_profile",
            title="Captain Mira",
            heading_path=("People", "Captain Mira"),
            page_start=12,
            page_end=12,
            text=profile_text,
        )
        insert_source_object(
            connection,
            object_id="core-rules:captain-mira-stats",
            book_id="core-rules",
            page_id="core-rules:12",
            object_type="stat_block",
            title="Captain Mira Statistics",
            heading_path=("People", "Captain Mira"),
            page_start=12,
            page_end=12,
            text=stat_text,
            parent_object_id="core-rules:captain-mira",
        )
        insert_source_object_link(
            connection,
            link_id="captain-mira-stat-profile",
            from_object_id="core-rules:captain-mira-stats",
            to_object_id="core-rules:captain-mira",
            to_book_id="core-rules",
            to_page_id="core-rules:12",
            link_type="stat_profile",
            label="Captain Mira",
        )
    source_sets.ensure_builtin_source_sets(config)
    rebuild_global_fts(config)
    thread = chat_store.create_thread(config)

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "Captain Mira WS Command",
        hit_limit=1,
        total_char_limit=700,
        window_chars=120,
    )

    assert len(context.hits) == 1
    hit = context.hits[0]
    assert hit.source_object_id == "core-rules:captain-mira"
    assert hit.object_type == "npc_profile"
    assert "WS BS" in hit.context_text
    assert "Skills: Command" in hit.context_text
    assert any("linked_evidence:stat_profile" in reason for reason in hit.rank_reasons)


def test_index_entry_retrieval_routes_to_deterministic_target_section(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=2,
            text="Falling rules explain how sudden drops are resolved.",
        )
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=20,
            text="Index\nFalling ..... 2",
            page_count=20,
        )
        insert_source_object(
            connection,
            object_id="core-rules:falling",
            book_id="core-rules",
            page_id="core-rules:2",
            object_type="rule_section",
            title="Falling",
            heading_path=("Hazards", "Falling"),
            page_start=2,
            page_end=2,
            text="Falling rules explain how sudden drops are resolved.",
        )
        insert_source_object(
            connection,
            object_id="core-rules:index-falling",
            book_id="core-rules",
            page_id="core-rules:20",
            object_type="index_entry",
            title="Falling",
            heading_path=("Index",),
            page_start=20,
            page_end=20,
            text="Falling ..... 2",
        )
        insert_source_object_link(
            connection,
            link_id="index-falling-target",
            from_object_id="core-rules:index-falling",
            to_object_id="core-rules:falling",
            to_book_id="core-rules",
            to_page_id="core-rules:2",
            link_type="index_entry",
            label="Falling",
        )
    source_sets.ensure_builtin_source_sets(config)
    rebuild_global_fts(config)
    thread = chat_store.create_thread(config)

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "Falling index",
        hit_limit=1,
        total_char_limit=500,
        window_chars=120,
    )

    assert len(context.hits) == 1
    hit = context.hits[0]
    assert hit.source_object_id == "core-rules:falling"
    assert hit.object_type == "rule_section"
    assert hit.page_start == 2
    assert "sudden drops" in hit.context_text
    assert any("linked_evidence:index_entry" in reason for reason in hit.rank_reasons)


def test_index_entry_page_only_link_routes_to_target_page_object(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=2,
            text="Falling rules explain how sudden drops are resolved.",
        )
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=20,
            text="Index\nFalling ..... 2",
            page_count=20,
        )
        insert_source_object(
            connection,
            object_id="core-rules:falling",
            book_id="core-rules",
            page_id="core-rules:2",
            object_type="rule_section",
            title="Falling",
            heading_path=("Hazards", "Falling"),
            page_start=2,
            page_end=2,
            text="Falling rules explain how sudden drops are resolved.",
        )
        insert_source_object(
            connection,
            object_id="core-rules:index-falling",
            book_id="core-rules",
            page_id="core-rules:20",
            object_type="index_entry",
            title="Falling",
            heading_path=("Index",),
            page_start=20,
            page_end=20,
            text="Falling ..... 2",
        )
        insert_source_object_link(
            connection,
            link_id="index-falling-page-target",
            from_object_id="core-rules:index-falling",
            to_object_id=None,
            to_book_id="core-rules",
            to_page_id="core-rules:2",
            link_type="index_entry",
            label="Falling",
        )
    source_sets.ensure_builtin_source_sets(config)
    rebuild_global_fts(config)
    thread = chat_store.create_thread(config)

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "Falling index",
        hit_limit=1,
        total_char_limit=500,
        window_chars=120,
    )

    assert len(context.hits) == 1
    hit = context.hits[0]
    assert hit.source_object_id == "core-rules:falling"
    assert hit.object_type == "rule_section"
    assert hit.page_start == 2
    assert "sudden drops" in hit.context_text
    assert any("linked_evidence:index_entry" in reason for reason in hit.rank_reasons)


def test_page_only_link_prefers_target_title_on_crowded_page(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=2,
            text=(
                "Armour rules discuss protection. "
                "Falling rules explain how sudden drops are resolved."
            ),
        )
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=20,
            text="Index\nFalling ..... 2",
            page_count=20,
        )
        insert_source_object(
            connection,
            object_id="core-rules:aaa-armour",
            book_id="core-rules",
            page_id="core-rules:2",
            object_type="rule_section",
            title="Armour",
            heading_path=("Equipment", "Armour"),
            page_start=2,
            page_end=2,
            text="Armour rules discuss protection.",
        )
        insert_source_object(
            connection,
            object_id="core-rules:falling",
            book_id="core-rules",
            page_id="core-rules:2",
            object_type="rule_section",
            title="Falling",
            heading_path=("Hazards", "Falling"),
            page_start=2,
            page_end=2,
            text="Falling rules explain how sudden drops are resolved.",
        )
        insert_source_object(
            connection,
            object_id="core-rules:index-falling",
            book_id="core-rules",
            page_id="core-rules:20",
            object_type="index_entry",
            title="Falling",
            heading_path=("Index",),
            page_start=20,
            page_end=20,
            text="Falling ..... 2",
        )
        insert_source_object_link(
            connection,
            link_id="index-falling-page-target",
            from_object_id="core-rules:index-falling",
            to_object_id=None,
            to_book_id="core-rules",
            to_page_id="core-rules:2",
            link_type="index_entry",
            label="Falling",
        )
    source_sets.ensure_builtin_source_sets(config)
    rebuild_global_fts(config)
    thread = chat_store.create_thread(config)

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "Falling index",
        hit_limit=1,
        total_char_limit=500,
        window_chars=120,
    )

    assert len(context.hits) == 1
    assert context.hits[0].source_object_id == "core-rules:falling"
    assert "sudden drops" in context.hits[0].context_text
    assert "Armour rules" not in context.hits[0].context_text


def test_index_entry_page_only_link_falls_back_to_target_page_text(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=2,
            text="Falling rules explain how sudden drops are resolved.",
        )
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=20,
            text="Index\nFalling ..... 2",
            page_count=20,
        )
        insert_source_object(
            connection,
            object_id="core-rules:index-falling",
            book_id="core-rules",
            page_id="core-rules:20",
            object_type="index_entry",
            title="Falling",
            heading_path=("Index",),
            page_start=20,
            page_end=20,
            text="Falling ..... 2",
        )
        insert_source_object_link(
            connection,
            link_id="index-falling-page-fallback",
            from_object_id="core-rules:index-falling",
            to_object_id=None,
            to_book_id="core-rules",
            to_page_id="core-rules:2",
            link_type="index_entry",
            label="Falling",
        )
    source_sets.ensure_builtin_source_sets(config)
    rebuild_global_fts(config)
    thread = chat_store.create_thread(config)

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "Falling index",
        hit_limit=1,
        total_char_limit=500,
        window_chars=120,
    )

    assert len(context.hits) == 1
    hit = context.hits[0]
    assert hit.source_object_id is None
    assert hit.object_type == "page_fallback"
    assert hit.page_start == 2
    assert "sudden drops" in hit.context_text
    assert any("linked_evidence:index_entry" in reason for reason in hit.rank_reasons)


def test_glossary_entry_evidence_keeps_definition_and_linked_target_context(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=2,
            text="Falling rules explain how sudden drops are resolved.",
        )
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=30,
            text="Glossary\nDooming: a ceremonial prophecy. See Falling.",
            page_count=30,
        )
        insert_source_object(
            connection,
            object_id="core-rules:falling",
            book_id="core-rules",
            page_id="core-rules:2",
            object_type="rule_section",
            title="Falling",
            heading_path=("Hazards", "Falling"),
            page_start=2,
            page_end=2,
            text="Falling rules explain how sudden drops are resolved.",
        )
        insert_source_object(
            connection,
            object_id="core-rules:glossary-dooming",
            book_id="core-rules",
            page_id="core-rules:30",
            object_type="glossary_entry",
            title="Dooming",
            heading_path=("Glossary",),
            page_start=30,
            page_end=30,
            text="Dooming: a ceremonial prophecy. See Falling.",
        )
        insert_source_object_link(
            connection,
            link_id="glossary-dooming-target",
            from_object_id="core-rules:glossary-dooming",
            to_object_id="core-rules:falling",
            to_book_id="core-rules",
            to_page_id="core-rules:2",
            link_type="glossary_definition",
            label="Falling",
        )
    source_sets.ensure_builtin_source_sets(config)
    rebuild_global_fts(config)
    thread = chat_store.create_thread(config)

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "Dooming glossary Falling",
        hit_limit=1,
        total_char_limit=700,
        window_chars=120,
    )

    assert len(context.hits) == 1
    hit = context.hits[0]
    assert hit.source_object_id == "core-rules:glossary-dooming"
    assert hit.object_type == "glossary_entry"
    assert hit.page_start == 30
    assert hit.page_end == 30
    assert hit.page_range_label is None
    assert "ceremonial prophecy" in hit.context_text
    assert "sudden drops" in hit.context_text
    assert any(
        "linked_evidence:glossary_definition" in reason
        for reason in hit.rank_reasons
    )


def test_link_traversal_does_not_cross_unchecked_book_scope(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="checked-book",
            title="Checked Book",
            category="Core Book & GM Essentials",
            page_number=1,
            text="Index\nForbidden Topic ..... 7",
        )
        insert_searchable_page(
            connection,
            book_id="unchecked-book",
            title="Unchecked Book",
            category="Adventure Modules and Campaigns",
            page_number=7,
            text="Forbidden Topic text from an unchecked book.",
        )
        insert_source_object(
            connection,
            object_id="checked-book:index-forbidden",
            book_id="checked-book",
            page_id="checked-book:1",
            object_type="index_entry",
            title="Forbidden Topic",
            heading_path=("Index",),
            page_start=1,
            page_end=1,
            text="Forbidden Topic ..... 7",
        )
        insert_source_object(
            connection,
            object_id="unchecked-book:forbidden",
            book_id="unchecked-book",
            page_id="unchecked-book:7",
            object_type="rule_section",
            title="Forbidden Topic",
            heading_path=("Secrets", "Forbidden Topic"),
            page_start=7,
            page_end=7,
            text="Forbidden Topic text from an unchecked book.",
        )
        insert_source_object_link(
            connection,
            link_id="cross-book-forbidden-link",
            from_object_id="checked-book:index-forbidden",
            to_object_id="unchecked-book:forbidden",
            to_book_id="unchecked-book",
            to_page_id="unchecked-book:7",
            link_type="index_entry",
            label="Forbidden Topic",
        )
    source_sets.ensure_builtin_source_sets(config)
    source_sets.set_book_enabled(config, "rules-core", "checked-book", True)
    source_sets.set_book_enabled(config, "rules-core", "unchecked-book", False)
    rebuild_global_fts(config)
    thread = chat_store.create_thread(config)

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "Forbidden Topic index",
        hit_limit=2,
        total_char_limit=700,
        window_chars=120,
    )

    assert context.source_book_ids == ("checked-book",)
    assert context.hits
    assert all(hit.book_id == "checked-book" for hit in context.hits)
    assert all(hit.source_object_id != "unchecked-book:forbidden" for hit in context.hits)
    assert "unchecked book" not in " ".join(hit.context_text for hit in context.hits)


def test_source_object_parent_fallback_resolves_without_link_row(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=4,
            text="Weather table row two has storms.",
        )
        insert_source_object(
            connection,
            object_id="core-rules:weather-table",
            book_id="core-rules",
            page_id="core-rules:4",
            object_type="table",
            title="Weather Results",
            heading_path=("Travel", "Weather Results"),
            page_start=4,
            page_end=4,
            text="Weather Results\n| Roll | Result |\n| 2 | Storms |",
        )
        insert_source_object(
            connection,
            object_id="core-rules:weather-row-2",
            book_id="core-rules",
            page_id="core-rules:4",
            object_type="table_row",
            title="Weather Results row 2",
            heading_path=("Travel", "Weather Results"),
            page_start=4,
            page_end=4,
            text="| 2 | Storms |",
            parent_object_id="core-rules:weather-table",
        )
        connection.execute(
            "update books set search_status = 'indexed' where id = 'core-rules'"
        )
        row = connection.execute(
            """
            select
              source_objects.*,
              books.title as book_title,
              books.category,
              pages.page_number as pdf_page_number,
              pages.page_label
            from source_objects
            join books on books.id = source_objects.book_id
            join pages on pages.id = source_objects.page_id
            where source_objects.id = 'core-rules:weather-row-2'
            """
        ).fetchone()
        assert row is not None

        candidate = retrieval_candidates.evidence_candidate_from_source_object_row(
            connection,
            row,
            base_score=0.0,
            snippet="Weather Results row 2",
            channel="source_object_scan",
            source_book_ids=("core-rules",),
        )

    assert retrieval_candidates.preferred_link_types("cross_reference") == (
        "cross_reference",
    )
    assert retrieval_candidates.preferred_link_types("rule_section") == ()
    assert candidate.source_object_id == "core-rules:weather-table"
    assert candidate.object_type == "table"
    assert any("linked_evidence:table_row" in reason for reason in candidate.rank_reasons)


def test_source_object_parent_fallback_ignores_unsupported_or_missing_parents(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=4,
            text="Weather reference and row text.",
        )
        insert_searchable_page(
            connection,
            book_id="unchecked-book",
            title="Unchecked Book",
            category="Adventure Modules and Campaigns",
            page_number=4,
            text="Unchecked parent table.",
        )
        insert_source_object(
            connection,
            object_id="core-rules:weather-table",
            book_id="core-rules",
            page_id="core-rules:4",
            object_type="table",
            title="Weather Results",
            heading_path=("Travel", "Weather Results"),
            page_start=4,
            page_end=4,
            text="Weather Results table.",
        )
        insert_source_object(
            connection,
            object_id="core-rules:unsupported-cross-reference",
            book_id="core-rules",
            page_id="core-rules:4",
            object_type="cross_reference",
            title="Weather Results",
            heading_path=("Travel",),
            page_start=4,
            page_end=4,
            text="See also Weather Results.",
            parent_object_id="core-rules:weather-table",
        )
        insert_source_object(
            connection,
            object_id="unchecked-book:weather-table",
            book_id="unchecked-book",
            page_id="unchecked-book:4",
            object_type="table",
            title="Weather Results",
            heading_path=("Travel", "Weather Results"),
            page_start=4,
            page_end=4,
            text="Unchecked Weather Results table.",
        )
        insert_source_object(
            connection,
            object_id="core-rules:missing-parent-row",
            book_id="core-rules",
            page_id="core-rules:4",
            object_type="table_row",
            title="Weather Results row 3",
            heading_path=("Travel", "Weather Results"),
            page_start=4,
            page_end=4,
            text="| 3 | Missing parent |",
            parent_object_id="unchecked-book:weather-table",
        )
        connection.execute(
            "update books set search_status = 'indexed' where id = 'core-rules'"
        )
        rows = {
            row["id"]: row
            for row in connection.execute(
                """
                select
                  source_objects.*,
                  books.title as book_title,
                  books.category,
                  pages.page_number as pdf_page_number,
                  pages.page_label
                from source_objects
                join books on books.id = source_objects.book_id
                join pages on pages.id = source_objects.page_id
                where source_objects.id in (
                  'core-rules:unsupported-cross-reference',
                  'core-rules:missing-parent-row'
                )
                """
            ).fetchall()
        }

        unsupported = retrieval_candidates.evidence_candidate_from_source_object_row(
            connection,
            rows["core-rules:unsupported-cross-reference"],
            base_score=0.0,
            snippet="Weather Results",
            channel="source_object_scan",
            source_book_ids=("core-rules",),
        )
        missing_parent = retrieval_candidates.evidence_candidate_from_source_object_row(
            connection,
            rows["core-rules:missing-parent-row"],
            base_score=0.0,
            snippet="Weather Results row 3",
            channel="source_object_scan",
            source_book_ids=("core-rules",),
        )

    assert unsupported.source_object_id == "core-rules:unsupported-cross-reference"
    assert missing_parent.source_object_id == "core-rules:missing-parent-row"


def test_retrieval_falls_back_to_active_source_set_for_legacy_threads(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_searchable_books(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            insert into chat_threads (id, title, active_source_set_id, created_at, updated_at)
            values ('legacy-thread', null, null, '2026-06-05T00:00:00Z',
                    '2026-06-05T00:00:00Z')
            """
        )
        connection.commit()

    context = retrieval.retrieve_context(
        config,
        "legacy-thread",
        "critical hit",
        hit_limit=1,
        total_char_limit=200,
        window_chars=120,
    )

    assert context.source_set_id == "rules-core"
    assert context.source_book_ids == ("core-rules",)
    assert context.hits[0].book_id == "core-rules"


def test_retrieval_returns_empty_scope_when_no_active_source_set(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        connection.execute(
            """
            insert into chat_threads (id, title, active_source_set_id, created_at, updated_at)
            values ('unscoped-thread', null, null, '2026-06-05T00:00:00Z',
                    '2026-06-05T00:00:00Z')
            """
        )

    context = retrieval.retrieve_context(
        config,
        "unscoped-thread",
        "critical hit",
        hit_limit=1,
        total_char_limit=200,
        window_chars=120,
    )

    assert context.source_set_id is None
    assert context.source_book_ids == ()
    assert context.source_map == ()
    assert context.hits == ()


def test_retrieval_skips_selected_hit_when_truncation_removes_context(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=1,
            text="critical",
        )
        insert_source_object(
            connection,
            object_id="core-rules:blank-critical",
            book_id="core-rules",
            page_id="core-rules:1",
            object_type="rule_section",
            title="Critical",
            heading_path=("Critical",),
            page_start=1,
            page_end=1,
            text=" critical body",
        )
    source_sets.ensure_builtin_source_sets(config)
    rebuild_global_fts(config)
    thread = chat_store.create_thread(config)

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "critical",
        hit_limit=1,
        total_char_limit=1,
        window_chars=120,
    )

    assert context.hits == ()


def test_page_hit_falls_back_when_source_object_has_no_semantic_overlap(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=1,
            text="Critical hit rules are here.",
        )
        insert_source_object(
            connection,
            object_id="core-rules:lantern",
            book_id="core-rules",
            page_id="core-rules:1",
            object_type="rule_section",
            title="Lanterns",
            heading_path=("Equipment", "Lanterns"),
            page_start=1,
            page_end=1,
            text="Lantern oil and tunnel light.",
        )
    source_sets.ensure_builtin_source_sets(config)
    rebuild_global_fts(config)
    thread = chat_store.create_thread(config)

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "critical hit",
        hit_limit=1,
        total_char_limit=200,
        window_chars=120,
    )

    assert context.hits[0].source_object_id is None
    assert context.hits[0].object_type == "page_fallback"


def test_source_map_and_candidate_helper_edges(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=1,
            text="Bretonnia critical lantern",
            page_label="i",
        )
        for index in range(12):
            insert_source_object(
                connection,
                object_id=f"core-rules:section-{index}",
                book_id="core-rules",
                page_id="core-rules:1",
                object_type="rule_section",
                title=f"Section {index}",
                heading_path=(f"Chapter {index}", f"Section {index}"),
                page_start=1,
                page_end=1,
                text=f"Section {index} Bretonnia critical lantern",
            )
        connection.execute(
            """
            insert into source_object_search (
              source_object_id,
              book_id,
              page_id,
              object_type,
              title,
              heading_path,
              page_start,
              page_end,
              confidence,
              search_text
            )
            values (
              'core-rules:section-0',
              'core-rules',
              'core-rules:1',
              'rule_section',
              'Section 0',
              'Chapter 0 > Section 0',
              1,
              1,
              0.91,
              'Section 0 Bretonnia critical lantern'
            )
            """
        )
        connection.execute(
            "insert into source_object_search_fts(source_object_search_fts) values('rebuild')"
        )
    source_sets.ensure_builtin_source_sets(config)
    rebuild_global_fts(config)

    with open_connection(config.db_path) as connection:
        assert len(retrieval.source_map_chapters(connection, "core-rules")) == 10
        assert retrieval_source_map.string_tuple_from_json("{bad json") is None
        assert retrieval_source_map.string_tuple_from_json('{"not": "a list"}') is None
        assert retrieval_source_map.string_tuple_from_json('[3, "ok"]') == ("ok",)
        aliases = retrieval.source_map_aliases(
            connection,
            "core-rules",
            title="One Two Three",
            category="Four Five Six",
            chapters=("Seven Eight Nine Ten Eleven",),
            query_terms=("bretonia",),
        )
        assert "bretonnia" in aliases

        monkeypatch.setattr(retrieval_source_map, "SOURCE_MAP_PAGE_CHAR_LIMIT", 10)
        vocabulary = retrieval.source_vocabulary(connection, "core-rules")
        assert vocabulary

        fts_candidates = retrieval.search_source_object_candidates(
            connection,
            "critical",
            book_ids=("core-rules",),
            limit=5,
        )
        assert fts_candidates[0].channel == "source_object_fts"
        assert retrieval.collect_evidence_candidates(
            config,
            source_book_ids=(),
            query_plan=retrieval.plan_query("critical", ()),
            per_candidate_limit=5,
        ) == ()
        assert retrieval.search_source_object_candidates(
            connection,
            "critical",
            book_ids=(),
            limit=5,
        ) == ()
        assert retrieval.search_source_object_fts_candidates(
            connection,
            "!!!",
            book_ids=("core-rules",),
            limit=5,
        ) == ()
        assert retrieval.search_source_object_like_candidates(
            connection,
            "!!!",
            book_ids=("core-rules",),
            limit=5,
        ) == ()
        assert retrieval.load_page_range_label(
            connection,
            book_id="core-rules",
            page_start=1,
            page_end=1,
        ) == "i"


def test_source_object_candidate_prefers_calibrated_page_labels(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=9,
            text="Critical hit rules start here.",
            page_label="9",
            page_count=10,
        )
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=10,
            text="Critical hit rules continue here.",
            page_label="10",
            page_count=10,
        )
        insert_source_object(
            connection,
            object_id="core-rules:critical-hits",
            book_id="core-rules",
            page_id="core-rules:9",
            object_type="rule_section",
            title="Critical Hits",
            heading_path=("Combat", "Critical Hits"),
            page_start=9,
            page_end=10,
            text="Critical hit rules start here.\nCritical hit rules continue here.",
        )
        connection.execute(
            """
            insert into book_page_label_calibrations (
              book_id,
              status,
              method,
              calibration_json,
              page_text_snapshot_sha256,
              updated_at
            )
            values (
              'core-rules',
              'calibrated',
              'offset_anchor',
              '{"labels_by_page":{"9":"1","10":"2"}}',
              ?,
              '2026-06-05T00:00:00Z'
            )
            """,
            (page_labels.page_label_snapshot_sha256(connection, "core-rules"),),
        )
        row = connection.execute(
            """
            select
              source_objects.*,
              books.title as book_title,
              books.category,
              pages.page_number as pdf_page_number,
              pages.page_label
            from source_objects
            join books on books.id = source_objects.book_id
            join pages on pages.id = source_objects.page_id
            where source_objects.id = 'core-rules:critical-hits'
            """
        ).fetchone()
        candidate = retrieval_candidates.source_object_row_to_candidate(
            connection,
            row,
            base_score=0.1,
            snippet="Critical Hits",
            channel="source_object_fts",
        )

    assert candidate.pdf_page_number == 9
    assert candidate.page_label == "1"
    assert candidate.page_range_label == "1-2"


def test_source_object_candidate_omits_untrusted_printed_page_range(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=9,
            text="Critical hit rules start here.",
            page_label=None,
            page_count=10,
        )
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=10,
            text="Critical hit rules continue here.",
            page_label=None,
            page_count=10,
        )
        insert_source_object(
            connection,
            object_id="core-rules:critical-hits",
            book_id="core-rules",
            page_id="core-rules:9",
            object_type="rule_section",
            title="Critical Hits",
            heading_path=("Combat", "Critical Hits"),
            page_start=9,
            page_end=10,
            text="Critical hit rules start here.\nCritical hit rules continue here.",
        )
        row = connection.execute(
            """
            select
              source_objects.*,
              books.title as book_title,
              books.category,
              pages.page_number as pdf_page_number,
              pages.page_label
            from source_objects
            join books on books.id = source_objects.book_id
            join pages on pages.id = source_objects.page_id
            where source_objects.id = 'core-rules:critical-hits'
            """
        ).fetchone()
        candidate = retrieval_candidates.source_object_row_to_candidate(
            connection,
            row,
            base_score=0.1,
            snippet="Critical Hits",
            channel="source_object_fts",
        )

    assert candidate.pdf_page_number == 9
    assert candidate.page_label is None
    assert candidate.page_range_label is None


def test_page_fallback_candidate_omits_uncalibrated_missing_printed_label(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=9,
            text="Critical hit rules start here.",
            page_label=None,
        )
        connection.execute(
            """
            update books
            set search_status = 'indexed'
            where id = 'core-rules'
            """
        )
        connection.execute(
            """
            insert into book_page_label_calibrations (
              book_id,
              status,
              method,
              calibration_json,
              page_text_snapshot_sha256,
              last_error,
              updated_at
            )
            values (
              'core-rules',
              'needs_review',
              'imported_labels_partial',
              '{"labels_by_page":{},"missing_label_pages":[9]}',
              ?,
              '1 page label needs manual review.',
              '2026-06-05T00:00:00Z'
            )
            """,
            (page_labels.page_label_snapshot_sha256(connection, "core-rules"),),
        )
        class PageHit:
            book_id = "core-rules"
            title = "Core Rules"
            category = "Core Book & GM Essentials"
            page_id = "core-rules:9"
            page_number = 9
            pdf_page_number = 9
            page_label = None
            snippet = "Critical hit"
            score = 0.1

        candidate = retrieval_candidates.evidence_candidate_from_page_hit(
            connection,
            PageHit(),
            query_terms=("missing",),
        )

    assert candidate is not None
    assert candidate.page_label is None
    assert candidate.page_range_label is None


def test_linked_page_candidate_omits_untrusted_printed_page_label(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=9,
            text="Critical hit rules start here.",
            page_label=None,
        )
        insert_source_object(
            connection,
            object_id="core-rules:index-critical",
            book_id="core-rules",
            page_id="core-rules:9",
            object_type="index_entry",
            title="Critical Hits",
            heading_path=("Index",),
            page_start=9,
            page_end=9,
            text="Critical Hits 9",
        )
        source_row = connection.execute(
            """
            select *
            from source_objects
            where id = 'core-rules:index-critical'
            """
        ).fetchone()
        page_row = connection.execute(
            """
            select
              pages.id as page_id,
              pages.book_id,
              books.title as book_title,
              books.category,
              pages.page_number,
              pages.page_label,
              page_text.text
            from pages
            join books on books.id = pages.book_id
            join page_text on page_text.page_id = pages.id
            where pages.id = 'core-rules:9'
            """
        ).fetchone()
        candidate = retrieval_candidates.linked_page_row_to_candidate(
            connection,
            page_row,
            source_row=source_row,
            base_score=0.1,
            snippet="Critical Hits",
            channel="source_object_fts",
            link_type="index_entry",
        )

    assert candidate.page_label is None
    assert candidate.page_range_label is None


def test_semantic_helper_edges(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_searchable_books(config)

    assert retrieval.build_enabled_source_map(config, (), query_terms=("critical",)) == ()
    assert retrieval.load_page_text(config, "core-rules:1").startswith("Critical")
    assert retrieval.parse_heading_path(None) == ()
    assert retrieval.parse_heading_path("{bad json") == ()
    assert retrieval.parse_heading_path('{"not": "a list"}') == ()
    assert retrieval.phrase_matches(("critical",), "critical hit") is False
    assert retrieval.semantic_overlaps(("critical", "critical"), "critical hit") == (
        "critical",
    )
    assert retrieval.token_matches_source("it", {"lantern"}) is False
    assert retrieval.terms_are_close("same", "same") is True
    assert retrieval.edit_distance_at_most_one("same", "same") is True

    candidate = retrieval.EvidenceCandidate(
        book_id="core-rules",
        title="Core Rules",
        category="Core",
        page_id="core-rules:1",
        page_number=1,
        pdf_page_number=1,
        page_label=None,
        page_start=1,
        page_end=1,
        page_range_label=None,
        snippet="lantern",
        base_score=0,
        context_text="lantern oil",
        channel="page_fts",
    )
    assert retrieval.rerank_candidates(
        (candidate,),
        retrieval.plan_query("critical hit", ()),
    ) == ()


def test_structural_query_terms_do_not_fuzzy_match_source_map_aliases() -> None:
    source_map = (
        retrieval.SourceMapEntry(
            book_id="barony",
            title="Barony",
            category="Adventures",
            summary="",
            aliases=("black",),
            best_source_for=(),
            chapters=(),
        ),
    )

    plan = retrieval.plan_query("give me the stat block for gors", source_map)

    assert ("block", "black") not in {
        (expansion.original, expansion.expanded) for expansion in plan.expansions
    }
    assert "black" not in plan.expanded_terms
    assert retrieval.token_matches_source("block", {"black"}) is False


def test_query_planner_generates_compound_and_plural_search_alternatives() -> None:
    plan = retrieval.plan_query("give me the statblocks for harpies", ())

    assert "stat block harpy" in plan.candidates
    assert "stat block" in plan.candidates
    assert "harpy" in plan.candidates


def test_query_planner_treats_stat_line_as_structural_statistics_intent() -> None:
    plan = retrieval.plan_query("harpies stat line", ())

    assert "harpy statistics" in plan.candidates
    assert "harpy stat block" in plan.candidates
    assert "harpy profile" in plan.candidates
    assert "statistics" in plan.match_terms
    assert "block" in plan.match_terms
    assert "profile" not in plan.match_terms
    assert "line" not in plan.match_terms


def test_compound_plural_structural_query_retrieves_singular_stat_evidence(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="bestiary",
            title="Bestiary",
            category="Rules",
            page_number=12,
            text="Harpy Statistics Main Profile WS BS S T Ag Int WP Fel.",
        )
        connection.execute("update books set search_status = 'indexed'")
        insert_source_object(
            connection,
            object_id="bestiary:harpy-statistics",
            book_id="bestiary",
            page_id="bestiary:12",
            object_type="stat_block",
            title="Harpy Statistics",
            heading_path=("Creatures",),
            page_start=12,
            page_end=12,
            text="Harpy Statistics stat block Main Profile WS BS S T Ag Int WP Fel.",
        )
    rebuild_source_object_search(config, force=True)

    evidence_pool = retrieval.collect_evidence_candidates(
        config,
        source_book_ids=("bestiary",),
        query_plan=retrieval.plan_query("give me the statblocks for harpies", ()),
        per_candidate_limit=5,
    )
    ranked = retrieval.rerank_candidates(
        evidence_pool,
        retrieval.plan_query("give me the statblocks for harpies", ()),
    )

    assert [candidate.source_object_id for candidate, _score, _reasons in ranked] == [
        "bestiary:harpy-statistics"
    ]


def test_stat_line_query_prefers_named_statistics_chunk_over_movement_line_noise(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Rules",
            page_number=1,
            text=(
                "Harpies follow the flying movement line when retreating. "
                "See the Harpy profile for movement details."
            ),
        )
        insert_searchable_page(
            connection,
            book_id="bestiary",
            title="Bestiary",
            category="Rules",
            page_number=12,
            text=(
                "Harpies are winged predators. Harpy Statistics Main Profile. "
                "Hippogriff Statistics Main Profile."
            ),
        )
        connection.execute("update books set search_status = 'indexed'")
        insert_source_object(
            connection,
            object_id="core-rules:harpy-movement",
            book_id="core-rules",
            page_id="core-rules:1",
            object_type="rule_section",
            title="Flying Movement",
            heading_path=("Movement",),
            page_start=1,
            page_end=1,
            text=(
                "Harpies follow the flying movement line when retreating. "
                "See the Harpy profile for movement details."
            ),
        )
        insert_source_object(
            connection,
            object_id="bestiary:harpy-statistics-heading",
            book_id="bestiary",
            page_id="bestiary:12",
            object_type="page_chunk",
            title="Page 12",
            heading_path=("Page 12",),
            page_start=12,
            page_end=12,
            text="Harpy Statistics",
        )
        insert_source_object(
            connection,
            object_id="bestiary:hippogriff-statistics",
            book_id="bestiary",
            page_id="bestiary:12",
            object_type="npc_profile",
            title="Hippogriff Statistics",
            heading_path=("Creatures",),
            page_start=12,
            page_end=12,
            text="Hippogriff Statistics Main Profile stat block.",
        )
    rebuild_source_object_search(config, force=True)

    evidence_pool = retrieval.collect_evidence_candidates(
        config,
        source_book_ids=("core-rules", "bestiary"),
        query_plan=retrieval.plan_query("harpies stat line", ()),
        per_candidate_limit=10,
    )
    ranked = retrieval.rerank_candidates(
        evidence_pool,
        retrieval.plan_query("harpies stat line", ()),
    )

    assert ranked
    assert ranked[0][0].source_object_id == "bestiary:harpy-statistics-heading"
    assert "core-rules:harpy-movement" not in [
        candidate.source_object_id for candidate, _score, _reasons in ranked
    ]
    assert "bestiary:hippogriff-statistics" not in [
        candidate.source_object_id for candidate, _score, _reasons in ranked
    ]


def test_short_page_chunk_candidate_uses_bounded_surrounding_page_context(
    tmp_path: Path,
) -> None:
    page_text = (
        "Harpies are winged predators. "
        "Harpy Statistics Main Profile WS BS S T Ag Int WP Fel. "
        "Secondary Profile A W SB TB M Mag IP FP. "
        "Skills: Dodge Blow."
    )
    heading_start = page_text.index("Harpy Statistics")
    heading_end = heading_start + len("Harpy Statistics")
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="bestiary",
            title="Bestiary",
            category="Rules",
            page_number=12,
            text=page_text,
        )
        connection.execute("update books set search_status = 'indexed'")
        insert_source_object(
            connection,
            object_id="bestiary:harpy-statistics-heading",
            book_id="bestiary",
            page_id="bestiary:12",
            object_type="page_chunk",
            title="Page 12",
            heading_path=("Page 12",),
            page_start=12,
            page_end=12,
            text="Harpy Statistics",
            char_start=heading_start,
            char_end=heading_end,
        )
    rebuild_source_object_search(config, force=True)

    with initialize_database(config.db_path) as connection:
        candidates = retrieval.search_source_object_candidates(
            connection,
            "harpy statistics",
            book_ids=("bestiary",),
            limit=5,
        )

    assert candidates[0].source_object_id == "bestiary:harpy-statistics-heading"
    assert candidates[0].context_text != "Harpy Statistics"
    assert "Main Profile WS BS" in candidates[0].context_text
    assert "Secondary Profile" in candidates[0].context_text


def test_short_page_chunk_context_falls_back_when_page_text_missing(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="bestiary",
            title="Bestiary",
            category="Rules",
            page_number=12,
            text="Harpy Statistics Main Profile.",
        )
        connection.execute("update books set search_status = 'indexed'")
        insert_source_object(
            connection,
            object_id="bestiary:harpy-statistics-heading",
            book_id="bestiary",
            page_id="bestiary:12",
            object_type="page_chunk",
            title="Page 12",
            heading_path=("Page 12",),
            page_start=12,
            page_end=12,
            text="Harpy Statistics",
            char_start=0,
            char_end=16,
        )
        connection.execute("delete from page_text where page_id = 'bestiary:12'")
        row = connection.execute(
            "select * from source_objects where id = 'bestiary:harpy-statistics-heading'"
        ).fetchone()

        assert retrieval_candidates.source_object_context_text(connection, row) == (
            "Harpy Statistics"
        )


def test_context_around_span_handles_empty_and_end_biased_windows() -> None:
    assert (
        retrieval_candidates.context_around_span(
            "0123456789",
            start=1,
            end=10,
            max_chars=5,
        )
        == "56789"
    )
    assert (
        retrieval_candidates.context_around_span(
            "0123456789",
            start=4,
            end=5,
            max_chars=0,
        )
        == ""
    )


def test_structural_entity_match_ignores_page_snippet_from_neighbor_object() -> None:
    candidate = retrieval.EvidenceCandidate(
        book_id="bestiary",
        title="Bestiary",
        category="Rules",
        page_id="bestiary:12",
        page_number=12,
        pdf_page_number=12,
        page_label=None,
        page_start=12,
        page_end=12,
        page_range_label=None,
        snippet="Harpy Statistics",
        base_score=-10,
        context_text="Hippogriff Statistics Main Profile stat block.",
        channel="page_fts_resolved",
        source_object_id="bestiary:hippogriff-statistics",
        object_type="npc_profile",
        object_title="Hippogriff Statistics",
        heading_path=("Creatures",),
        confidence=0.9,
        rank_reasons=("candidate:page_fts_resolved",),
    )

    assert retrieval.rerank_candidates(
        (candidate,),
        retrieval.plan_query("harpies stat line", ()),
    ) == ()


def test_structural_entity_match_rejects_wrong_titled_rule_section_body_overlap() -> None:
    candidate = retrieval.EvidenceCandidate(
        book_id="companion",
        title="Companion",
        category="Rules",
        page_id="companion:12",
        page_number=12,
        pdf_page_number=12,
        page_label=None,
        page_start=12,
        page_end=12,
        page_range_label=None,
        snippet="Harpies Statistics",
        base_score=-10,
        context_text="This mermaid discussion compares Harpies Statistics.",
        channel="source_object_fts",
        source_object_id="companion:mermaids",
        object_type="rule_section",
        object_title="MERMAIDS",
        heading_path=("Creatures", "MERMAIDS"),
        confidence=0.9,
        rank_reasons=("candidate:source_object_fts",),
    )

    assert retrieval.rerank_candidates(
        (candidate,),
        retrieval.plan_query("harpies stat line", ()),
    ) == ()


def test_keep_best_candidate_replaces_weaker_page_candidate() -> None:
    weaker_candidate = retrieval.EvidenceCandidate(
        book_id="core-rules",
        title="Core Rules",
        category="Core",
        page_id="core-rules:1",
        page_number=1,
        pdf_page_number=1,
        page_label=None,
        page_start=1,
        page_end=1,
        page_range_label=None,
        snippet="critical hit",
        base_score=4,
        context_text="critical hit",
        channel="page_fts",
    )
    stronger_candidate = retrieval.EvidenceCandidate(
        book_id="core-rules",
        title="Core Rules",
        category="Core",
        page_id="core-rules:1",
        page_number=1,
        pdf_page_number=1,
        page_label=None,
        page_start=1,
        page_end=1,
        page_range_label=None,
        snippet="critical hit",
        base_score=-2,
        context_text="critical hit",
        channel="page_fts",
    )
    candidates: dict[str, retrieval.EvidenceCandidate] = {}

    retrieval.keep_best_candidate(candidates, weaker_candidate)
    retrieval.keep_best_candidate(candidates, stronger_candidate)

    assert candidates[weaker_candidate.dedupe_key] == stronger_candidate


def test_chart_queries_prefer_typed_tables_over_rule_mentions() -> None:
    table_candidate = retrieval.EvidenceCandidate(
        book_id="core-rules",
        title="Core Rules",
        category="Core",
        page_id="core-rules:130",
        page_number=130,
        pdf_page_number=130,
        page_label=None,
        page_start=130,
        page_end=130,
        page_range_label=None,
        snippet="table chart Hit Location",
        base_score=-8,
        context_text="% roll Location\n01-15 Head\n16-35 Right Arm",
        channel="source_object_fts",
        source_object_id="hit-location-table",
        object_type="table",
        object_title="Hit Location",
        confidence=0.82,
        rank_reasons=("fusion:rrf=0.012",),
    )
    rule_candidate = retrieval.EvidenceCandidate(
        book_id="core-rules",
        title="Core Rules",
        category="Core",
        page_id="core-rules:161",
        page_number=161,
        pdf_page_number=161,
        page_label=None,
        page_start=161,
        page_end=161,
        page_range_label=None,
        snippet="hit location chart",
        base_score=-12,
        context_text="The hit location chart is mentioned while explaining another rule.",
        channel="source_object_fts",
        source_object_id="hit-location-mention",
        object_type="rule_section",
        object_title="Another Rule",
        confidence=0.68,
        rank_reasons=("fusion:rrf=0.03",),
    )

    ranked = retrieval.rerank_candidates(
        (rule_candidate, table_candidate),
        retrieval.plan_query("hit location chart", ()),
    )

    assert ranked[0][0].object_type == "table"
    assert ranked[0][0].object_title == "Hit Location"
    plural_ranked = retrieval.rerank_candidates(
        (rule_candidate, table_candidate),
        retrieval.plan_query("hit location charts", ()),
    )

    assert plural_ranked[0][0].object_type == "table"


def test_stat_queries_boost_typed_stat_blocks() -> None:
    stat_candidate = retrieval.EvidenceCandidate(
        book_id="core-rules",
        title="Core Rules",
        category="Core",
        page_id="core-rules:12",
        page_number=12,
        pdf_page_number=12,
        page_label=None,
        page_start=12,
        page_end=12,
        page_range_label=None,
        snippet="Captain Mira stat block",
        base_score=-4,
        context_text="Captain Mira stat block WS BS S T",
        channel="source_object_fts",
        source_object_id="captain-mira-stats",
        object_type="stat_block",
        object_title="Captain Mira Statistics",
        confidence=0.82,
        rank_reasons=("fusion:rrf=not-a-number",),
    )
    profile_candidate = retrieval.EvidenceCandidate(
        book_id="core-rules",
        title="Core Rules",
        category="Core",
        page_id="core-rules:13",
        page_number=13,
        pdf_page_number=13,
        page_label=None,
        page_start=13,
        page_end=13,
        page_range_label=None,
        snippet="Captain Mira stat block",
        base_score=-5,
        context_text="Captain Mira stat block Skills: Command",
        channel="source_object_fts",
        source_object_id="captain-mira-profile",
        object_type="npc_profile",
        object_title="Captain Mira",
        confidence=0.78,
        rank_reasons=(
            "linked_source_object:stat_block",
            "fusion:rrf=0.01",
        ),
    )

    ranked = retrieval.rerank_candidates(
        (profile_candidate, stat_candidate),
        retrieval.plan_query("Captain Mira stat block", ()),
    )

    assert any("structural_intent_boost:14.0" in reason for reason in ranked[0][2])
    assert any("structural_intent_boost:12.0" in reason for reason in ranked[1][2])
    no_fusion_candidate = retrieval.EvidenceCandidate(
        book_id="core-rules",
        title="Core Rules",
        category="Core",
        page_id="core-rules:14",
        page_number=14,
        pdf_page_number=14,
        page_label=None,
        page_start=14,
        page_end=14,
        page_range_label=None,
        snippet="Captain Mira stat block",
        base_score=-6,
        context_text="Captain Mira stat block",
        channel="source_object_fts",
        source_object_id="captain-mira-no-fusion",
        object_type="stat_block",
        object_title="Captain Mira Statistics",
        confidence=0.82,
    )

    assert retrieval.rerank_candidates(
        (no_fusion_candidate,),
        retrieval.plan_query("Captain Mira stat block", ()),
    )


def test_structural_stat_queries_require_named_entity_match() -> None:
    black_orc_candidate = retrieval.EvidenceCandidate(
        book_id="bestiary",
        title="Old World Bestiary",
        category="Rules",
        page_id="bestiary:104",
        page_number=104,
        pdf_page_number=104,
        page_label=None,
        page_start=104,
        page_end=104,
        page_range_label=None,
        snippet="Black Orc stat block",
        base_score=-14,
        context_text="Black Orc stat block WS BS S T Ag Int WP Fel.",
        channel="source_object_fts",
        source_object_id="black-orc-stat-block",
        object_type="monster_profile",
        object_title="Black Orc Statistics",
        confidence=0.82,
        rank_reasons=("linked_source_object:stat_block", "fusion:rrf=0.04"),
    )
    black_knight_candidate = retrieval.EvidenceCandidate(
        book_id="barony",
        title="Barony of the Damned",
        category="Adventures",
        page_id="barony:38",
        page_number=38,
        pdf_page_number=38,
        page_label=None,
        page_start=38,
        page_end=38,
        page_range_label=None,
        snippet="Black Knight Main Profile",
        base_score=-10,
        context_text="The Black Knight Main Profile WS BS S T Ag Int WP Fel.",
        channel="source_object_fts",
        source_object_id="black-knight-stat-block",
        object_type="npc_profile",
        object_title="Race: Human",
        heading_path=("Chapter Three: Rise of the Black Knight",),
        confidence=0.78,
        rank_reasons=("linked_source_object:stat_block", "fusion:rrf=0.02"),
    )

    ranked = retrieval.rerank_candidates(
        (black_orc_candidate, black_knight_candidate),
        retrieval.plan_query("give me the stat block for the black knight", ()),
    )

    assert [candidate.source_object_id for candidate, _score, _reasons in ranked] == [
        "black-knight-stat-block"
    ]


def test_stat_queries_prefer_named_profile_over_phrase_only_section() -> None:
    phrase_section = retrieval.EvidenceCandidate(
        book_id="barony",
        title="Barony of the Damned",
        category="Adventures",
        page_id="barony:3",
        page_number=3,
        pdf_page_number=3,
        page_label=None,
        page_start=3,
        page_end=3,
        page_range_label=None,
        snippet="Rise of the Black Knight",
        base_score=-15,
        context_text="Rise of the Black Knight chapter listing.",
        channel="source_object_fts",
        source_object_id="black-knight-toc",
        object_type="rule_section",
        object_title="Rise of the Black Knight",
        confidence=0.68,
        rank_reasons=("fusion:rrf=0.05",),
    )
    stat_profile = retrieval.EvidenceCandidate(
        book_id="barony",
        title="Barony of the Damned",
        category="Adventures",
        page_id="barony:38",
        page_number=38,
        pdf_page_number=38,
        page_label=None,
        page_start=38,
        page_end=38,
        page_range_label=None,
        snippet="Black Knight Main Profile",
        base_score=-7,
        context_text="The Black Knight Main Profile WS BS S T Ag Int WP Fel.",
        channel="source_object_fts",
        source_object_id="black-knight-profile",
        object_type="npc_profile",
        object_title="Race: Human",
        heading_path=("Chapter Three: Rise of the Black Knight",),
        confidence=0.78,
        rank_reasons=("fusion:rrf=0.01",),
    )

    ranked = retrieval.rerank_candidates(
        (phrase_section, stat_profile),
        retrieval.plan_query("give me the stat block for the black knight", ()),
    )

    assert [candidate.source_object_id for candidate, _score, _reasons in ranked] == [
        "black-knight-profile",
        "black-knight-toc",
    ]


def test_structural_only_stat_query_accepts_typed_stat_evidence() -> None:
    stat_candidate = retrieval.EvidenceCandidate(
        book_id="core-rules",
        title="Core Rules",
        category="Core",
        page_id="core-rules:12",
        page_number=12,
        pdf_page_number=12,
        page_label=None,
        page_start=12,
        page_end=12,
        page_range_label=None,
        snippet="stat block",
        base_score=-4,
        context_text="stat block WS BS S T Ag Int WP Fel",
        channel="source_object_fts",
        source_object_id="anonymous-stat-block",
        object_type="stat_block",
        object_title="Statistics",
        confidence=0.82,
        rank_reasons=("fusion:rrf=0.01",),
    )

    ranked = retrieval.rerank_candidates(
        (stat_candidate,),
        retrieval.plan_query("stat block", ()),
    )

    assert ranked[0][0].source_object_id == "anonymous-stat-block"


def test_entity_queries_reject_heading_path_only_matches() -> None:
    heading_only_candidate = retrieval.EvidenceCandidate(
        book_id="barony",
        title="Barony of the Damned",
        category="Adventures",
        page_id="barony:45",
        page_number=45,
        pdf_page_number=45,
        page_label=None,
        page_start=45,
        page_end=45,
        page_range_label=None,
        snippet="",
        base_score=-10,
        context_text=(
            "Chapter Three: Rise of the Black Knight\n\n"
            "A plague surgeon observes the city."
        ),
        channel="source_object_fts",
        source_object_id="barony:unrelated",
        object_type="rule_section",
        object_title="The Thirteenth Claw",
        heading_path=("Chapter Three: Rise of the Black Knight", "The Thirteenth Claw"),
        confidence=0.68,
        rank_reasons=("fusion:rrf=0.03",),
    )
    direct_candidate = retrieval.EvidenceCandidate(
        book_id="barony",
        title="Barony of the Damned",
        category="Adventures",
        page_id="barony:31",
        page_number=31,
        pdf_page_number=31,
        page_label=None,
        page_start=31,
        page_end=31,
        page_range_label=None,
        snippet="",
        base_score=-9,
        context_text="The Black Knight threatens the duchy.",
        channel="source_object_fts",
        source_object_id="barony:black-knight",
        object_type="rule_section",
        object_title="The Black Knight",
        heading_path=("Chapter Three: Rise of the Black Knight",),
        confidence=0.68,
        rank_reasons=("fusion:rrf=0.02",),
    )

    ranked = retrieval.rerank_candidates(
        (heading_only_candidate, direct_candidate),
        retrieval.plan_query("tell me about the black knight", ()),
    )

    assert [candidate.object_title for candidate, _score, _reasons in ranked] == [
        "The Black Knight"
    ]


def test_retrieval_records_ranked_hits(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_searchable_books(config)
    thread = chat_store.create_thread(config)
    turn = chat_store.create_provider_unavailable_turn(
        config,
        thread.id,
        content="critical hit",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )
    context = retrieval.retrieve_context(
        config,
        thread.id,
        "critical hit",
        hit_limit=4,
        total_char_limit=500,
        window_chars=120,
    )

    retrieval_run_id = chat_store.record_retrieval_run(
        config,
        thread_id=thread.id,
        message_id=turn.user_message.id,
        source_set_id=thread.active_source_set_id,
        query="critical hit",
        hits=context.hits,
        source_book_ids=context.source_book_ids,
        source_map=context.source_map,
        candidates=context.candidates,
    )

    with open_connection(config.db_path) as connection:
        run = connection.execute(
            "select query, metadata_json from retrieval_runs where id = ?",
            (retrieval_run_id,),
        ).fetchone()
        hits = connection.execute(
            """
            select
              retrieval_hits.page_id,
              retrieval_hits.rank,
              retrieval_hits.snippet,
              retrieval_hits.object_type_snapshot,
              retrieval_hits.rank_reasons_json
            from retrieval_hits
            where retrieval_run_id = ?
            """,
            (retrieval_run_id,),
        ).fetchall()

    assert run["query"] == "critical hit"
    metadata = json.loads(run["metadata_json"])
    assert metadata["source_book_ids"] == ["core-rules"]
    assert metadata["source_map"][0]["book_id"] == "core-rules"
    assert "critical hit" in metadata["candidates"]
    assert [(hit["page_id"], hit["rank"]) for hit in hits] == [("core-rules:1", 1)]
    assert "Critical" in hits[0]["snippet"]
    assert hits[0]["object_type_snapshot"] == "page_fallback"
    rank_reasons = json.loads(hits[0]["rank_reasons_json"])
    assert any(reason.startswith("fusion_channel:page_fts@") for reason in rank_reasons)
    assert any(reason.startswith("fusion:rrf=") for reason in rank_reasons)
    assert any(
        reason.startswith("reranker:deterministic:accepted")
        for reason in rank_reasons
    )


def test_retrieval_returns_no_hits_for_zero_limit(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_searchable_books(config)
    thread = chat_store.create_thread(config)

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "critical hit",
        hit_limit=0,
        total_char_limit=500,
        window_chars=120,
    )

    assert context.hits == ()


def test_retrieval_truncates_context_to_remaining_total_limit(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_searchable_books(config)
    thread = chat_store.create_thread(config)

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "critical hit",
        hit_limit=1,
        total_char_limit=24,
        window_chars=120,
    )

    assert len(context.hits) == 1
    assert len(context.hits[0].context_text) <= 24


def test_retrieval_skips_hits_with_no_page_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_searchable_books(config)
    thread = chat_store.create_thread(config)

    class FakeHit:
        book_id = "core-rules"
        title = "Core Rules"
        category = "Core Book & GM Essentials"
        page_id = "missing-page"
        page_number = 99
        snippet = "missing"
        rank = 1
        score = 0.5

    monkeypatch.setattr(
        retrieval_candidates,
        "search_exact",
        lambda *args, **kwargs: (FakeHit(),),
    )

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "critical hit",
        hit_limit=1,
        total_char_limit=200,
        window_chars=120,
    )

    assert context.hits == ()


def test_retrieval_requires_existing_thread(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_searchable_books(config)

    with pytest.raises(chat_store.ChatThreadNotFoundError):
        retrieval.retrieve_context(
            config,
            "missing-thread",
            "critical hit",
            hit_limit=1,
            total_char_limit=200,
            window_chars=120,
        )


def test_context_window_centers_first_matching_term_and_falls_back_to_start() -> None:
    text = "prefix " * 40 + "critical hit rule appears here " + "suffix " * 40

    centered = retrieval.context_window(text, terms=["critical"], max_chars=80)
    fallback = retrieval.context_window(text, terms=["absent"], max_chars=40)

    assert "critical hit rule" in centered
    assert fallback == text[:40].strip()
