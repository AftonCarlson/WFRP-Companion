from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from wfrp_companion.assistant import chat_service
from wfrp_companion.assistant import provider
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database, open_connection
from wfrp_companion.library import source_sets
from wfrp_companion.search.fts import rebuild_global_fts


class FakeProvider:
    def stream_response(
        self,
        *,
        messages: Sequence[provider.ProviderMessage],
        request_id: str,
        **_kwargs,
    ):
        assert request_id.startswith("run-")
        assert messages[-1].role == "user"
        yield provider.ProviderStreamEvent(type="delta", text_delta="Critical ")
        yield provider.ProviderStreamEvent(type="delta", text_delta="hits.")
        yield provider.ProviderStreamEvent(
            type="completed",
            provider_response_id="resp-1",
            input_tokens=10,
            output_tokens=2,
        )


class CapturingProvider:
    def __init__(self, answer: str = "Follow-up answer.") -> None:
        self.answer = answer
        self.messages: tuple[provider.ProviderMessage, ...] = ()

    def stream_response(
        self,
        *,
        messages: Sequence[provider.ProviderMessage],
        request_id: str,
        **_kwargs,
    ):
        self.messages = tuple(messages)
        yield provider.ProviderStreamEvent(type="delta", text_delta=self.answer)
        yield provider.ProviderStreamEvent(type="completed")


class EmptyDeltaProvider:
    def stream_response(self, *, messages, request_id, **_kwargs):
        yield provider.ProviderStreamEvent(type="delta", text_delta="")
        yield provider.ProviderStreamEvent(type="delta", text_delta="Answer")
        yield provider.ProviderStreamEvent(type="completed")


class ProviderUnavailableDuringStream:
    def stream_response(self, *, messages, request_id, **_kwargs):
        raise provider.ProviderUnavailableError("provider dropped")
        yield provider.ProviderStreamEvent(type="completed")


class BrokenProvider:
    def stream_response(self, *, messages, request_id, **_kwargs):
        raise RuntimeError("provider exploded")
        yield provider.ProviderStreamEvent(type="completed")


def make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        pdf_root=tmp_path / "pdf-root",
        data_dir=data_dir,
        db_path=data_dir / "wfrp_companion.sqlite",
        asset_dir=data_dir / "library" / "assets",
        openai_api_key="test-key",
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
            page_number=134,
            text=(
                "Critical hit rules explain what happens after a critical hit. "
                "Use the critical hit table and apply the listed result."
            ),
        )
    source_sets.ensure_builtin_source_sets(config)
    rebuild_global_fts(config)


def test_stream_chat_message_persists_completed_run_and_streams_deltas(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_searchable_books(config)
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="What happens after a critical hit?",
            idempotency_key="send-1",
            provider_factory=lambda _: FakeProvider(),
        )
    )

    assert [event.type for event in events] == [
        "accepted",
        "research_started",
        "tool_call",
        "retrieval",
        "tool_result",
        "evidence_validation",
        "delta",
        "delta",
        "completed",
    ]
    assert [event.text_delta for event in events if event.type == "delta"] == [
        "Critical ",
        "hits.",
    ]
    assert events[-1].assistant_message is not None
    assert events[-1].assistant_message.content == "Critical hits."
    assert events[-1].model_run.status == "completed"
    assert events[-1].model_run.provider_response_id == "resp-1"
    assert events[-1].citations[0].title == "Core Rules"
    assert events[-1].citations[0].page_number == 134

    with open_connection(config.db_path) as connection:
        model_run = connection.execute("select * from model_runs").fetchone()
        assistant_message_count = connection.execute(
            "select count(*) from chat_messages where role = 'assistant'"
        ).fetchone()[0]
        retrieval_hit_count = connection.execute(
            "select count(*) from retrieval_hits"
        ).fetchone()[0]

    assert model_run["status"] == "completed"
    assert model_run["assistant_message_id"] is not None
    assert model_run["retrieval_run_id"] is not None
    assert model_run["provider_response_id"] == "resp-1"
    assert model_run["input_tokens"] == 10
    assert model_run["output_tokens"] == 2
    assert assistant_message_count == 1
    assert retrieval_hit_count == 2

    duplicate_events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="Different text should not duplicate.",
            idempotency_key="send-1",
            provider_factory=lambda _: FakeProvider(),
        )
    )

    assert [event.type for event in duplicate_events] == ["accepted", "completed"]
    assert duplicate_events[-1].assistant_message is not None
    assert duplicate_events[-1].assistant_message.content == "Critical hits."


def test_stream_chat_message_sends_recent_completed_turns_to_provider(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_searchable_books(config)
    thread = chat_service.chat_store.create_thread(config)
    first_provider = CapturingProvider(answer="Captain Alder wears mail.")

    first_events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="Tell me about Captain Alder.",
            idempotency_key="send-1",
            provider_factory=lambda _: first_provider,
        )
    )
    assert first_events[-1].assistant_message is not None
    with open_connection(config.db_path) as connection:
        connection.execute(
            "update chat_messages set created_at = ? where id in (?, ?)",
            (
                "2026-06-06T00:00:01Z",
                first_events[-1].user_message.id,
                first_events[-1].assistant_message.id,
            ),
        )
        connection.execute(
            """
            update model_runs
            set created_at = ?, updated_at = ?, completed_at = ?
            where id = ?
            """,
            (
                "2026-06-06T00:00:01Z",
                "2026-06-06T00:00:01Z",
                "2026-06-06T00:00:01Z",
                first_events[-1].model_run.id,
            ),
        )
    followup_provider = CapturingProvider()

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="What about his armor?",
            idempotency_key="send-2",
            provider_factory=lambda _: followup_provider,
        )
    )

    assert events[-1].assistant_message is not None
    assert [message.role for message in followup_provider.messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert followup_provider.messages[1].content == "Tell me about Captain Alder."
    assert followup_provider.messages[2].content == "Captain Alder wears mail."
    assert followup_provider.messages[-1].content.startswith(
        "Question:\nWhat about his armor?"
    )


def test_stream_chat_message_uses_history_aware_query_for_followup_retrieval(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_searchable_books(config)
    thread = chat_service.chat_store.create_thread(config)
    first_provider = CapturingProvider(
        answer="Critical hit rules use the critical hit table."
    )

    first_events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="Tell me about critical hits.",
            idempotency_key="send-1",
            provider_factory=lambda _: first_provider,
        )
    )
    assert first_events[-1].assistant_message is not None
    with open_connection(config.db_path) as connection:
        connection.execute(
            "update chat_messages set created_at = ? where id in (?, ?)",
            (
                "2026-06-06T00:00:01Z",
                first_events[-1].user_message.id,
                first_events[-1].assistant_message.id,
            ),
        )
        connection.execute(
            """
            update model_runs
            set created_at = ?, updated_at = ?, completed_at = ?
            where id = ?
            """,
            (
                "2026-06-06T00:00:01Z",
                "2026-06-06T00:00:01Z",
                "2026-06-06T00:00:01Z",
                first_events[-1].model_run.id,
            ),
        )

    second_events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="What about it?",
            idempotency_key="send-2",
            provider_factory=lambda _: CapturingProvider(),
        )
    )

    retrieval_events = [event for event in second_events if event.type == "retrieval"]
    assert retrieval_events
    assert retrieval_events[0].citations[0].title == "Core Rules"
    with open_connection(config.db_path) as connection:
        rows = connection.execute(
            """
            select query, metadata_json
            from retrieval_runs
            where message_id = ?
            """,
            (second_events[-1].user_message.id,),
        ).fetchall()
    row = next(
        row
        for row in rows
        if json.loads(row["metadata_json"]).get("tool_name") == "search_library"
    )
    metadata = json.loads(row["metadata_json"])
    assert row["query"] != "What about it?"
    assert "critical hits" in row["query"].lower()
    assert metadata["retrieval_query"] == row["query"]
    assert metadata["history_strategy"] == "followup_contextualized"
    assert metadata["history_turn_count"] == 1
    assert metadata["history_message_ids"] == [
        first_events[-1].user_message.id,
        first_events[-1].assistant_message.id,
    ]


def test_stream_close_after_retrieval_marks_active_run_failed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = make_config(tmp_path)
    seed_searchable_books(config)
    thread = chat_service.chat_store.create_thread(config)

    def fake_retrieve_context(
        config: AppConfig,
        thread_id: str,
        query: str,
        *,
        hit_limit: int,
        total_char_limit: int,
        window_chars: int,
    ) -> chat_service.retrieval.RetrievalContext:
        return chat_service.retrieval.RetrievalContext(
            query=query,
            candidates=(),
            hits=(),
            source_set_id="rules-core",
            source_book_ids=("core-rules",),
            source_map=(),
        )

    monkeypatch.setattr(
        chat_service.retrieval,
        "retrieve_context",
        fake_retrieve_context,
    )
    events = chat_service.stream_chat_message(
        config,
        thread_id=thread.id,
        content="What about it?",
        idempotency_key="send-interrupted",
        provider_factory=lambda _: CapturingProvider(),
    )

    accepted_event = next(events)
    research_event = next(events)
    tool_event = next(events)
    retrieval_event = next(events)
    events.close()

    assert accepted_event.type == "accepted"
    assert research_event.type == "research_started"
    assert tool_event.type == "tool_call"
    assert retrieval_event.type == "retrieval"
    with open_connection(config.db_path) as connection:
        row = connection.execute(
            "select status, error_code from model_runs where id = ?",
            (retrieval_event.model_run.id,),
        ).fetchone()

    assert dict(row) == {
        "status": "failed",
        "error_code": "stream_interrupted",
    }


def test_stream_chat_message_fails_without_openai_key(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    config = AppConfig(
        pdf_root=config.pdf_root,
        data_dir=config.data_dir,
        db_path=config.db_path,
        asset_dir=config.asset_dir,
        openai_api_key=None,
    )
    seed_searchable_books(config)
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="What happens after a critical hit?",
            idempotency_key="send-1",
        )
    )

    assert [event.type for event in events] == ["accepted", "failed"]
    assert events[-1].model_run.status == "failed"
    assert events[-1].model_run.error_code == "provider_unavailable"
    assert "OPENAI_API_KEY" in (events[-1].error_message or "")

    duplicate_events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="Different text should not duplicate.",
            idempotency_key="send-1",
            provider_factory=lambda _: FakeProvider(),
        )
    )

    assert [event.type for event in duplicate_events] == ["accepted", "failed"]
    assert duplicate_events[-1].error_message is not None


def test_stream_chat_message_ignores_empty_deltas(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_searchable_books(config)
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="critical hit",
            idempotency_key="send-empty-delta",
            provider_factory=lambda _: EmptyDeltaProvider(),
        )
    )

    assert [event.type for event in events] == [
        "accepted",
        "research_started",
        "tool_call",
        "retrieval",
        "tool_result",
        "evidence_validation",
        "delta",
        "completed",
    ]
    assert events[-1].assistant_message is not None
    assert events[-1].assistant_message.content == "Answer"


def test_stream_chat_message_marks_provider_unavailable_during_stream(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_searchable_books(config)
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="critical hit",
            idempotency_key="send-provider-drop",
            provider_factory=lambda _: ProviderUnavailableDuringStream(),
        )
    )

    assert events[0].type == "accepted"
    assert "retrieval" in [event.type for event in events]
    assert events[-1].type == "failed"
    assert events[-1].model_run.status == "failed"
    assert events[-1].model_run.error_code == "provider_unavailable"
    assert events[-1].error_message == "provider dropped"


def test_stream_chat_message_marks_generic_provider_failure(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_searchable_books(config)
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="critical hit",
            idempotency_key="send-provider-error",
            provider_factory=lambda _: BrokenProvider(),
        )
    )

    assert events[0].type == "accepted"
    assert "retrieval" in [event.type for event in events]
    assert events[-1].type == "failed"
    assert events[-1].model_run.status == "failed"
    assert events[-1].model_run.error_code == "provider_error"
    assert events[-1].error_message == "provider exploded"


def test_stream_chat_message_leaves_existing_inflight_run_alone(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_searchable_books(config)
    thread = chat_service.chat_store.create_thread(config)
    result = chat_service.chat_store.create_queued_turn(
        config,
        thread.id,
        content="critical hit",
        idempotency_key="send-inflight",
        provider="openai",
        model="gpt-5.4-mini",
    )
    chat_service.chat_store.transition_model_run(
        config,
        result.model_run.id,
        from_statuses=("queued",),
        to_status="retrieving",
    )

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="Different text should not duplicate.",
            idempotency_key="send-inflight",
            provider_factory=lambda _: FakeProvider(),
        )
    )

    assert [event.type for event in events] == ["accepted"]
    assert events[0].model_run.status == "retrieving"
