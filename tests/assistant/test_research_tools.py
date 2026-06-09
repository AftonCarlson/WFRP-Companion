from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from wfrp_companion.assistant import chat_store
from wfrp_companion.assistant import evidence_constraints
from wfrp_companion.assistant import candidates as candidate_module
from wfrp_companion.assistant.evidence import RetrievalContext
from wfrp_companion.assistant import research_tools
from wfrp_companion.assistant.source_map import SourceScope
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database, open_connection
from wfrp_companion.library import source_sets
from wfrp_companion.search.fts import rebuild_global_fts


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
        values (?, 'core', ?, ?, ?, ?, ?, ?, ?, 150, 'copied', 'imported',
                'not_indexed', 'not_scanned', '2026-06-09T00:00:00Z',
                '2026-06-09T00:00:00Z')
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
        values (?, ?, ?, '2026-06-09T00:00:00Z')
        """,
        (page_id, text, f"sha-{page_id}"),
    )


def seed_books(config: AppConfig) -> None:
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=12,
            text="Critical hit rules explain how critical hits work.",
        )
        insert_searchable_page(
            connection,
            book_id="barony",
            title="Barony of the Damned",
            category="Adventure Modules and Campaigns",
            page_number=41,
            text="The Black Knight rides through the adventure.",
        )
    source_sets.ensure_builtin_source_sets(config)
    rebuild_global_fts(config)


def insert_source_object(
    connection: sqlite3.Connection,
    *,
    source_object_id: str,
    book_id: str,
    page_number: int,
    object_type: str,
    title: str,
    text: str,
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
          bbox_json,
          text,
          search_text,
          metadata_json,
          confidence,
          extraction_method,
          text_snapshot_sha256,
          created_at,
          updated_at
        )
        values (?, ?, ?, ?, null, ?, ?, ?, ?, null, null, null, ?, ?, '{}',
                0.95, 'synthetic', ?, '2026-06-09T00:00:00Z',
                '2026-06-09T00:00:00Z')
        """,
        (
            source_object_id,
            book_id,
            f"{book_id}:{page_number}",
            object_type,
            title,
            json.dumps(["Creatures", title]),
            page_number,
            page_number,
            text,
            f"{title}\n{text}",
            f"sha-{source_object_id}",
        ),
    )


def seed_bestiary(config: AppConfig) -> None:
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="bestiary",
            title="Old World Bestiary",
            category="Rules and Mechanics Toolkits",
            page_number=101,
            page_label="99",
            text=(
                "Harpy creature entry. The synthetic profile describes wings, "
                "claws, and a compact statline marker for test use."
            ),
        )
        insert_source_object(
            connection,
            source_object_id="harpy-stat",
            book_id="bestiary",
            page_number=101,
            object_type="stat_block",
            title="Harpy",
            text="Synthetic Harpy stat_block: M 4 WS 31 BS 0 S 31 T 30 W 10.",
        )
    source_sets.ensure_builtin_source_sets(config)
    rebuild_global_fts(config)


def test_search_library_tool_uses_thread_snapshot_and_persists_diagnostics(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    source_sets.set_book_enabled(config, "rules-core", "core-rules", False)
    source_sets.set_book_enabled(config, "rules-core", "barony", True)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="critical hit",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )

    result = research_tools.search_library(
        config,
        thread_id=thread.id,
        message_id=queued.user_message.id,
        tool_call_id="tool-call-1",
        attempt_number=1,
        query="critical hit",
        intent="rules_lookup",
        hit_limit=4,
        total_char_limit=500,
        window_chars=120,
    )

    assert result.retrieval_run_id.startswith("retrieval-")
    assert [hit.book_id for hit in result.hits] == ["core-rules"]
    assert result.diagnostics.channel_counts["page_fts"] > 0
    assert result.diagnostics.vector_status == "disabled"
    with open_connection(config.db_path) as connection:
        metadata = json.loads(
            connection.execute(
                "select metadata_json from retrieval_runs where id = ?",
                (result.retrieval_run_id,),
            ).fetchone()["metadata_json"]
        )
        scoped_books = connection.execute(
            """
            select book_id
            from retrieval_run_source_books
            where retrieval_run_id = ?
            order by book_id
            """,
            (result.retrieval_run_id,),
        ).fetchall()

    assert metadata["diagnostics_schema_version"] == 1
    assert metadata["tool_call_id"] == "tool-call-1"
    assert metadata["attempt_number"] == 1
    assert metadata["intent"] == "rules_lookup"
    assert metadata["channel_counts"]["page_fts"] > 0
    assert [row["book_id"] for row in scoped_books] == ["core-rules"]


def test_open_page_tool_resolves_printed_page_and_records_page_lookup(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    thread = chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="it's on pg 99",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )

    result = research_tools.open_page(
        config,
        thread_id=thread.id,
        message_id=queued.user_message.id,
        tool_call_id="tool-call-page",
        attempt_number=2,
        book_id="bestiary",
        book_title_hint=None,
        printed_page_label="99",
        pdf_page_number=None,
        subject_hint="harpy",
        intent="statline_lookup",
        hit_limit=4,
        total_char_limit=500,
        window_chars=160,
    )

    assert result.retrieval_run_id.startswith("retrieval-")
    assert [hit.page_id for hit in result.hits] == ["bestiary:101"]
    assert result.hits[0].page_label == "99"
    assert "Harpy" in result.hits[0].context_text
    assert result.diagnostics.page_lookup_attempted is True
    assert result.diagnostics.channel_counts["page_lookup"] == 1
    with open_connection(config.db_path) as connection:
        metadata = json.loads(
            connection.execute(
                "select metadata_json from retrieval_runs where id = ?",
                (result.retrieval_run_id,),
            ).fetchone()["metadata_json"]
        )
    assert metadata["tool_call_id"] == "tool-call-page"
    assert metadata["intent"] == "statline_lookup"
    assert metadata["channel_counts"]["page_lookup"] == 1
    assert metadata["page_lookup_attempted"] is True


def test_lookup_source_object_tool_records_structured_stat_lookup(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    thread = chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="harpy statline",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )

    result = research_tools.lookup_source_object(
        config,
        thread_id=thread.id,
        message_id=queued.user_message.id,
        tool_call_id="tool-call-object",
        attempt_number=3,
        source_object_id="harpy-stat",
        intent="statline_lookup",
        total_char_limit=500,
        window_chars=160,
    )

    assert [hit.source_object_id for hit in result.hits] == ["harpy-stat"]
    assert result.hits[0].object_type == "stat_block"
    assert result.hits[0].page_label == "99"
    assert "Synthetic Harpy stat_block" in result.hits[0].context_text
    assert result.diagnostics.channel_counts["table_stat_lookup"] == 1
    with open_connection(config.db_path) as connection:
        metadata = json.loads(
            connection.execute(
                "select metadata_json from retrieval_runs where id = ?",
                (result.retrieval_run_id,),
            ).fetchone()["metadata_json"]
        )
    assert metadata["tool_call_id"] == "tool-call-object"
    assert metadata["channel_counts"]["table_stat_lookup"] == 1


def test_search_library_falls_back_to_empty_diagnostics_when_context_has_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="critical hit",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )

    def fake_retrieve_context_for_source_scope(
        config: AppConfig,
        source_scope: SourceScope,
        query: str,
        *,
        hit_limit: int,
        total_char_limit: int,
        window_chars: int,
    ) -> RetrievalContext:
        return RetrievalContext(
            query=query,
            candidates=("critical hit",),
            hits=(),
            source_set_id=source_scope.source_set_id,
            source_book_ids=source_scope.book_ids,
            source_map=(),
            diagnostics=None,
        )

    monkeypatch.setattr(
        research_tools.retrieval,
        "retrieve_context_for_source_scope",
        fake_retrieve_context_for_source_scope,
    )

    result = research_tools.search_library(
        config,
        thread_id=thread.id,
        message_id=queued.user_message.id,
        tool_call_id="tool-call-empty-diagnostics",
        attempt_number=1,
        query="critical hit",
        intent="rules_lookup",
        hit_limit=4,
        total_char_limit=500,
        window_chars=120,
    )

    assert result.hits == ()
    assert result.diagnostics.channel_skip_reasons == {
        "retrieval": "disabled_by_limits"
    }


def test_search_library_passes_requirement_constraint_to_retrieval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="orc stats",
        idempotency_key="send-constraint",
        provider="openai",
        model="gpt-5.4-mini",
    )
    constraint = evidence_constraints.EvidenceConstraint(
        requirement_id="orc_stats",
        requirement_type="statline_evidence",
        canonical_subject="Orc",
        subject_terms=("orc",),
        subject_aliases=(),
        excluded_terms=(),
        required_terms=(),
        structural_terms=("statline",),
        object_type_hints=("stat_block",),
        book_title_hints=("Old World Bestiary",),
        page_hints=("104",),
        min_accepted_hits=1,
    )
    captured: dict[str, object] = {}

    def fake_retrieve_context_for_source_scope(
        config: AppConfig,
        source_scope: SourceScope,
        query: str,
        *,
        hit_limit: int,
        total_char_limit: int,
        window_chars: int,
        requirement_constraint: evidence_constraints.EvidenceConstraint | None = None,
    ) -> RetrievalContext:
        captured["constraint"] = requirement_constraint
        return RetrievalContext(
            query=query,
            candidates=("orc stats",),
            hits=(),
            source_set_id=source_scope.source_set_id,
            source_book_ids=source_scope.book_ids,
            source_map=(),
            diagnostics=research_tools.retrieval.empty_diagnostics(config),
        )

    monkeypatch.setattr(
        research_tools.retrieval,
        "retrieve_context_for_source_scope",
        fake_retrieve_context_for_source_scope,
    )

    result = research_tools.search_library(
        config,
        thread_id=thread.id,
        message_id=queued.user_message.id,
        tool_call_id="tool-call-constraint",
        attempt_number=1,
        query="orc stats",
        intent="statline_lookup",
        hit_limit=4,
        total_char_limit=500,
        window_chars=120,
        requirement_constraint=constraint,
    )

    assert captured["constraint"] is constraint
    assert result.query == "orc stats"


def test_page_tool_supports_title_hint_pdf_page_and_helper_miss_paths(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    thread = chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="open the page",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )

    result = research_tools.open_page(
        config,
        thread_id=thread.id,
        message_id=queued.user_message.id,
        tool_call_id="tool-call-pdf-page",
        attempt_number=1,
        book_id=None,
        book_title_hint="Old World Bestiary",
        printed_page_label=None,
        pdf_page_number=101,
        subject_hint=None,
        intent="source_navigation",
        hit_limit=1,
        total_char_limit=250,
        window_chars=120,
    )

    assert [hit.page_id for hit in result.hits] == ["bestiary:101"]
    assert "pdf_page=101" in result.query
    with initialize_database(config.db_path) as connection:
        source_scope = research_tools.thread_source_scope(config, thread.id)
        assert research_tools.resolve_book_id(
            connection,
            source_scope=source_scope,
            book_id=None,
            book_title_hint=None,
        ) is None
        assert research_tools.resolve_book_id(
            connection,
            source_scope=source_scope,
            book_id=None,
            book_title_hint="   ",
        ) is None
        assert research_tools.resolve_book_id(
            connection,
            source_scope=SourceScope(source_set_id="rules-core", book_ids=()),
            book_id=None,
            book_title_hint="Old World Bestiary",
        ) is None
        assert research_tools.resolve_page_row(
            connection,
            book_id="bestiary",
            printed_page_label=None,
            pdf_page_number=None,
        ) is None
        assert research_tools.resolve_page_row(
            connection,
            book_id="missing",
            printed_page_label="99",
            pdf_page_number=None,
        ) is None
        assert research_tools.resolve_page_row(
            connection,
            book_id="bestiary",
            printed_page_label="100",
            pdf_page_number=None,
        ) is None

    assert research_tools.bounded_context("abc", terms=(), max_chars=0) == ""
    assert research_tools.page_lookup_query(
        book_id=None,
        printed_page_label=None,
        pdf_page_number=101,
        subject_hint=None,
        intent="source_navigation",
    ) == "open_page pdf_page=101 intent=source_navigation"


def test_lookup_source_object_rejects_objects_outside_thread_scope(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    with initialize_database(config.db_path) as connection:
        insert_source_object(
            connection,
            source_object_id="barony-stat",
            book_id="barony",
            page_number=41,
            object_type="stat_block",
            title="Black Knight",
            text="Synthetic Black Knight stat_block.",
        )
    thread = chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="black knight statline",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )

    result = research_tools.lookup_source_object(
        config,
        thread_id=thread.id,
        message_id=queued.user_message.id,
        tool_call_id="tool-call-out-of-scope",
        attempt_number=1,
        source_object_id="barony-stat",
        intent="statline_lookup",
        total_char_limit=500,
        window_chars=160,
    )

    assert result.hits == ()
    assert result.diagnostics.channel_skip_reasons == {
        "table_stat_lookup": "not_found"
    }


def test_thread_source_scope_requires_existing_thread(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    with pytest.raises(chat_store.ChatThreadNotFoundError):
        research_tools.thread_source_scope(config, "missing-thread")


def test_candidate_helpers_report_missing_vectors_and_scan_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = replace(make_config(tmp_path), embedding_provider="local-hash")
    assert (
        candidate_module.vector_channel_status(config, candidate_count=0)
        == "missing_embeddings"
    )
    assert (
        candidate_module.vector_channel_status(
            replace(config, embedding_provider="disabled"),
            candidate_count=0,
        )
        == "disabled"
    )
    assert candidate_module.vector_channel_status(config, candidate_count=2) == "ran"

    def no_fts_candidates(
        connection: sqlite3.Connection,
        candidate_query: str,
        *,
        book_ids: tuple[str, ...],
        limit: int,
    ) -> tuple[object, ...]:
        return ()

    def scan_candidates(
        connection: sqlite3.Connection,
        candidate_query: str,
        *,
        book_ids: tuple[str, ...],
        limit: int,
    ) -> tuple[object, ...]:
        return ("scan-hit",)

    monkeypatch.setattr(
        candidate_module,
        "search_source_object_fts_candidates",
        no_fts_candidates,
    )
    monkeypatch.setattr(
        candidate_module,
        "search_source_object_like_candidates",
        scan_candidates,
    )

    assert candidate_module.search_source_object_candidates(
        object(),
        "harpy",
        book_ids=("bestiary",),
        limit=4,
    ) == ("scan-hit",)
