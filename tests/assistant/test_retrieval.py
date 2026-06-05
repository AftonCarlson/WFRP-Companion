from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from wfrp_companion.assistant import chat_store
from wfrp_companion.assistant import retrieval
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
        values (?, 'core', ?, ?, ?, ?, ?, ?, ?, 1, 'copied', 'imported',
                'not_indexed', 'not_scanned', '2026-06-04T00:00:00Z',
                '2026-06-04T00:00:00Z')
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
          extraction_method,
          embedded_text_chars,
          text_chars,
          word_count,
          image_count,
          ocr_attempted,
          has_text
        )
        values (?, ?, ?, 'ocr', 0, ?, ?, 0, 1, 1)
        """,
        (page_id, book_id, page_number, len(text), len(text.split())),
    )
    connection.execute(
        """
        insert into page_text (page_id, text, text_sha256, generated_at)
        values (?, ?, ?, '2026-06-04T00:00:00Z')
        """,
        (page_id, text, f"sha-{page_id}"),
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


def test_retrieval_uses_thread_source_snapshot_not_live_source_set(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_searchable_books(config)
    original_thread = chat_store.create_thread(config)
    source_sets.set_book_enabled(config, "rules-core", "core-rules", False)
    source_sets.set_book_enabled(config, "rules-core", "barony", True)
    new_thread = chat_store.create_thread(config)

    original_context = retrieval.retrieve_context(
        config,
        original_thread.id,
        "What happens when a character takes a critical hit?",
        hit_limit=4,
        total_char_limit=500,
        window_chars=120,
    )
    new_context = retrieval.retrieve_context(
        config,
        new_thread.id,
        "Where is the black knight?",
        hit_limit=4,
        total_char_limit=500,
        window_chars=120,
    )

    assert [hit.book_id for hit in original_context.hits] == ["core-rules"]
    assert [hit.book_id for hit in new_context.hits] == ["barony"]
    assert "critical hit" in original_context.hits[0].context_text.lower()
    assert "black knight" in new_context.hits[0].context_text.lower()
    assert "/managed/" not in original_context.hits[0].context_text


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
    )

    with open_connection(config.db_path) as connection:
        run = connection.execute(
            "select query from retrieval_runs where id = ?",
            (retrieval_run_id,),
        ).fetchone()
        hits = connection.execute(
            """
            select retrieval_hits.page_id, retrieval_hits.rank, retrieval_hits.snippet
            from retrieval_hits
            where retrieval_run_id = ?
            """,
            (retrieval_run_id,),
        ).fetchall()

    assert run["query"] == "critical hit"
    assert [(hit["page_id"], hit["rank"]) for hit in hits] == [("core-rules:1", 1)]
    assert "Critical" in hits[0]["snippet"]


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

    monkeypatch.setattr(retrieval, "search_exact", lambda *args, **kwargs: (FakeHit(),))

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
