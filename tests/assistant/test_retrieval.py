from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from wfrp_companion.assistant import chat_store
from wfrp_companion.assistant import candidates as retrieval_candidates
from wfrp_companion.assistant import retrieval
from wfrp_companion.assistant import source_map as retrieval_source_map
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database, open_connection
from wfrp_companion.library import source_sets
from wfrp_companion.search.fts import rebuild_global_fts
from wfrp_companion.source_objects.source_map_builder import (
    BUILDER_VERSION,
    SCHEMA_VERSION,
    source_object_snapshot_sha256,
)


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
) -> None:
    connection.execute(
        """
        insert into source_objects (
          id,
          book_id,
          page_id,
          object_type,
          title,
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
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.91, 'test', ?, ?, ?)
        """,
        (
            object_id,
            book_id,
            page_id,
            object_type,
            title,
            json.dumps(list(heading_path)),
            page_start,
            page_end,
            text,
            " ".join((*heading_path, text)),
            f"sha-{object_id}",
            "2026-06-05T00:00:00Z",
            "2026-06-05T00:00:00Z",
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
    accepted_candidate = retrieval.EvidenceCandidate(
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
        base_score=0,
        context_text="critical hit",
        channel="page_fts",
        rank_reasons=("fusion:rrf=not-a-number",),
    )
    assert retrieval.rerank_candidates(
        (accepted_candidate,),
        retrieval.plan_query("critical hit", ()),
    )
    candidates: dict[str, retrieval.EvidenceCandidate] = {}
    retrieval.keep_best_candidate(candidates, accepted_candidate)
    retrieval.keep_best_candidate(candidates, candidate)
    assert candidates[accepted_candidate.dedupe_key] == accepted_candidate
    better_candidate = retrieval.EvidenceCandidate(
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
        base_score=-1,
        context_text="critical hit",
        channel="page_fts",
    )
    retrieval.keep_best_candidate(candidates, better_candidate)
    assert candidates[accepted_candidate.dedupe_key] == better_candidate
    assert retrieval.rerank_candidates(
        (better_candidate,),
        retrieval.plan_query("critical hit", ()),
    )


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
