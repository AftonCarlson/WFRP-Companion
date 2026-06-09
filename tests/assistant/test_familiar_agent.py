from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path

import pytest

from wfrp_companion.assistant import chat_service
from wfrp_companion.assistant import chat_store
from wfrp_companion.assistant import context_resolution
from wfrp_companion.assistant import conversation_context
from wfrp_companion.assistant import familiar_agent
from wfrp_companion.assistant import provider
from wfrp_companion.assistant import research
from wfrp_companion.assistant import research_tools
from wfrp_companion.assistant.evidence import RetrievedHit
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database, open_connection
from wfrp_companion.library import source_sets


class FinalAnswerProvider:
    def __init__(self, answer: str = "Harpy statline answer.") -> None:
        self.answer = answer
        self.messages: tuple[provider.ProviderMessage, ...] = ()

    def stream_response(
        self,
        *,
        messages: Sequence[provider.ProviderMessage],
        request_id: str,
        tools: Sequence[provider.ProviderToolDefinition] = (),
        tool_results: Sequence[provider.ProviderToolResult] = (),
        previous_response_id: str | None = None,
        tool_choice: object | None = None,
    ):
        self.messages = tuple(messages)
        assert tools == ()
        assert tool_results == ()
        assert previous_response_id is None
        assert tool_choice in (None, "none")
        yield provider.ProviderStreamEvent(type="delta", text_delta=self.answer)
        yield provider.ProviderStreamEvent(
            type="completed",
            provider_response_id="resp-final",
            input_tokens=11,
            output_tokens=3,
        )


class ToolThenFinalProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def stream_response(
        self,
        *,
        messages: Sequence[provider.ProviderMessage],
        request_id: str,
        tools: Sequence[provider.ProviderToolDefinition] = (),
        tool_results: Sequence[provider.ProviderToolResult] = (),
        previous_response_id: str | None = None,
        tool_choice: object | None = None,
    ):
        self.calls.append(
            {
                "messages": tuple(messages),
                "tools": tuple(tools),
                "tool_results": tuple(tool_results),
                "previous_response_id": previous_response_id,
                "tool_choice": tool_choice,
            }
        )
        if len(self.calls) == 1:
            assert tools
            yield provider.ProviderStreamEvent(
                type="tool_call",
                tool_name="open_page",
                tool_call_id="call-open-page",
                tool_arguments_json=json.dumps(
                    {
                        "book_title_hint": "Old World Bestiary",
                        "printed_page_label": "99",
                        "subject_hint": "harpy",
                        "intent": "statline_lookup",
                    }
                ),
            )
            yield provider.ProviderStreamEvent(
                type="completed",
                provider_response_id="resp-plan",
                input_tokens=7,
                output_tokens=1,
            )
            return
        yield provider.ProviderStreamEvent(type="delta", text_delta="Recovered harpy stats.")
        yield provider.ProviderStreamEvent(
            type="completed",
            provider_response_id="resp-final",
            input_tokens=13,
            output_tokens=4,
        )


class NoToolThenFinalProvider:
    def __init__(self) -> None:
        self.messages_by_call: list[tuple[provider.ProviderMessage, ...]] = []

    def stream_response(
        self,
        *,
        messages: Sequence[provider.ProviderMessage],
        request_id: str,
        tools: Sequence[provider.ProviderToolDefinition] = (),
        tool_results: Sequence[provider.ProviderToolResult] = (),
        previous_response_id: str | None = None,
        tool_choice: object | None = None,
    ):
        self.messages_by_call.append(tuple(messages))
        if len(self.messages_by_call) == 1:
            yield provider.ProviderStreamEvent(
                type="completed",
                provider_response_id="resp-no-tool",
                input_tokens=5,
                output_tokens=0,
            )
            return
        yield provider.ProviderStreamEvent(type="delta", text_delta="No citable evidence.")
        yield provider.ProviderStreamEvent(
            type="completed",
            provider_response_id="resp-insufficient",
            input_tokens=9,
            output_tokens=3,
        )


class PartialOpenPageThenFinalProvider:
    def __init__(self) -> None:
        self.planning_calls = 0

    def stream_response(
        self,
        *,
        messages: Sequence[provider.ProviderMessage],
        request_id: str,
        tools: Sequence[provider.ProviderToolDefinition] = (),
        tool_results: Sequence[provider.ProviderToolResult] = (),
        previous_response_id: str | None = None,
        tool_choice: object | None = None,
    ):
        if tools:
            self.planning_calls += 1
            if self.planning_calls == 1:
                yield provider.ProviderStreamEvent(
                    type="tool_call",
                    tool_name="open_page",
                    tool_call_id="call-partial-open-page",
                    tool_arguments_json=json.dumps(
                        {
                            "book_title_hint": "Old World Bestiary",
                            "printed_page_label": "99",
                            "subject_hint": "harpy",
                            "intent": "statline_lookup",
                        }
                    ),
                )
            yield provider.ProviderStreamEvent(
                type="completed",
                provider_response_id=f"resp-planning-{self.planning_calls}",
            )
            return
        yield provider.ProviderStreamEvent(type="delta", text_delta="Still insufficient.")
        yield provider.ProviderStreamEvent(
            type="completed",
            provider_response_id="resp-partial-final",
        )


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


def seed_bestiary(config: AppConfig) -> None:
    with initialize_database(config.db_path) as connection:
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
            values ('bestiary', 'core', 'Old World Bestiary',
                    'Rules and Mechanics Toolkits', 'bestiary.pdf',
                    '/source/bestiary.pdf', '/managed/bestiary.pdf',
                    'source-sha', 'managed-sha', 150, 'copied', 'imported',
                    'indexed', 'not_scanned', '2026-06-09T00:00:00Z',
                    '2026-06-09T00:00:00Z')
            """
        )
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
            values ('bestiary:101', 'bestiary', 101, '99', 'ocr',
                    0, 70, 12, 0, 1, 1)
            """
        )
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
            values ('bestiary:102', 'bestiary', 102, '100', 'ocr',
                    0, 60, 10, 0, 1, 1)
            """
        )
        connection.execute(
            """
            insert into page_text (page_id, text, text_sha256, generated_at)
            values ('bestiary:101',
                    'Synthetic Harpy stat_block: M 4 WS 31 BS 0 S 31 T 30 W 10.',
                    'sha-bestiary-101', '2026-06-09T00:00:00Z')
            """
        )
        connection.execute(
            """
            insert into page_text (page_id, text, text_sha256, generated_at)
            values ('bestiary:102',
                    'Synthetic Gor stat_block: M 4 WS 31 BS 0 S 31 T 30 W 10.',
                    'sha-bestiary-102', '2026-06-09T00:00:00Z')
            """
        )
    source_sets.ensure_builtin_source_sets(config)


def hit(
    *,
    rank: int,
    subject: str,
    object_type: str = "stat_block",
    source_object_id: str | None = None,
) -> RetrievedHit:
    text = f"Synthetic {subject.title()} stat_block: M 4 WS 31 BS 0 S 31 T 30 W 10."
    page_number = 102 if subject == "gor" else 101
    page_label = "100" if subject == "gor" else "99"
    return RetrievedHit(
        book_id="bestiary",
        title="Old World Bestiary",
        category="Rules and Mechanics Toolkits",
        page_id=f"bestiary:{page_number}",
        page_number=page_number,
        pdf_page_number=page_number,
        page_label=page_label,
        snippet=text,
        score=1.0 / rank,
        rank=rank,
        context_text=text,
        source_object_id=source_object_id,
        object_type=object_type,
        object_title=subject.title(),
        page_start=page_number,
        page_end=page_number,
        page_range_label=page_label,
        rank_reasons=("test",),
        text_snapshot_sha256=f"sha-{subject}",
    )


def diagnostics(status: str = "not_evaluated") -> research.RetrievalDiagnostics:
    return research.RetrievalDiagnostics(
        channel_counts={
            "page_fts": 1,
            "source_object_fts": 1,
            "source_object_scan": 1,
            "vector": 0,
            "page_lookup": 0,
            "table_stat_lookup": 1,
        },
        channel_skip_reasons={"vector": "disabled"},
        vector_status="disabled",
        candidate_count_before_fusion=2,
        candidate_count_after_fusion=2,
        reranked_count=2,
        selected_count=2,
        page_lookup_attempted=False,
        validation_status=status,
    )


def empty_tool_result(config: AppConfig, *, thread_id: str, message_id: str) -> str:
    return chat_store.record_retrieval_run(
        config,
        thread_id=thread_id,
        message_id=message_id,
        source_set_id="rules-core",
        query="empty",
        hits=(),
        source_book_ids=("bestiary",),
        diagnostics=diagnostics(),
    )


def test_familiar_runs_hybrid_search_and_filters_final_citations(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    provider_instance = FinalAnswerProvider()

    def fake_search_library(**kwargs):
        retrieval_run_id = chat_store.record_retrieval_run(
            config,
            thread_id=kwargs["thread_id"],
            message_id=kwargs["message_id"],
            source_set_id="rules-core",
            query=kwargs["query"],
            hits=(hit(rank=1, subject="harpy"), hit(rank=2, subject="gor")),
            source_book_ids=("bestiary",),
            diagnostics=diagnostics(),
            tool_call_id=kwargs["tool_call_id"],
            attempt_number=kwargs["attempt_number"],
            intent=kwargs["intent"],
            resolved_query=kwargs["query"],
            tool_name="search_library",
        )
        return research_tools.SearchLibraryResult(
            retrieval_run_id=retrieval_run_id,
            query=kwargs["query"],
            source_set_id="rules-core",
            source_book_ids=("bestiary",),
            hits=(hit(rank=1, subject="harpy"), hit(rank=2, subject="gor")),
            diagnostics=diagnostics(),
        )

    monkeypatch.setattr(research_tools, "search_library", fake_search_library)
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="harpy statline",
            idempotency_key="send-agent-1",
            provider_factory=lambda _: provider_instance,
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
    assert events[-1].assistant_message.content == "Harpy statline answer."
    assert [citation.snippet for citation in events[-1].citations] == [
        "Synthetic Harpy stat_block: M 4 WS 31 BS 0 S 31 T 30 W 10."
    ]
    assert "Synthetic Harpy stat_block" in provider_instance.messages[-1].content
    assert "Synthetic Gor stat_block" not in provider_instance.messages[-1].content
    with open_connection(config.db_path) as connection:
        research_run = connection.execute(
            "select status, evidence_status from familiar_research_runs"
        ).fetchone()
        judgments = connection.execute(
            """
            select status, reason_code
            from familiar_evidence_judgments
            order by created_at, id
            """
        ).fetchall()
        retrieval_metadata = json.loads(
            connection.execute(
                "select metadata_json from retrieval_runs order by created_at desc limit 1"
            ).fetchone()["metadata_json"]
        )

    assert dict(research_run) == {"status": "completed", "evidence_status": "sufficient"}
    assert sorted(tuple(row) for row in judgments) == [
        ("accepted", "statline_evidence"),
        ("rejected", "subject_mismatch"),
    ]
    assert retrieval_metadata["validation_status"] == "sufficient"


def test_familiar_uses_provider_requested_page_lookup_after_weak_search(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    provider_instance = ToolThenFinalProvider()

    def fake_empty_search_library(**kwargs):
        retrieval_run_id = empty_tool_result(
            config,
            thread_id=kwargs["thread_id"],
            message_id=kwargs["message_id"],
        )
        return research_tools.SearchLibraryResult(
            retrieval_run_id=retrieval_run_id,
            query=kwargs["query"],
            source_set_id="rules-core",
            source_book_ids=("bestiary",),
            hits=(),
            diagnostics=diagnostics(),
        )

    monkeypatch.setattr(research_tools, "search_library", fake_empty_search_library)
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="harpy statline",
            idempotency_key="send-agent-2",
            provider_factory=lambda _: provider_instance,
        )
    )

    event_types = [event.type for event in events]
    assert event_types.count("tool_call") == 2
    assert event_types.count("tool_result") == 2
    assert "evidence_validation" in event_types
    assert events[-1].assistant_message is not None
    assert events[-1].assistant_message.content == "Recovered harpy stats."
    assert events[-1].citations[0].title == "Old World Bestiary"
    assert events[-1].citations[0].page_label == "99"
    assert provider_instance.calls[0]["tools"]
    assert provider_instance.calls[0]["tool_results"] == ()
    assert '"hit_count": 0' in provider_instance.calls[0]["messages"][-1].content
    assert "Prior local tool results:" in provider_instance.calls[0]["messages"][-1].content
    assert provider_instance.calls[-1]["tool_choice"] in (None, "none")
    with open_connection(config.db_path) as connection:
        tool_rows = connection.execute(
            "select tool_name, status from familiar_tool_calls order by step_number"
        ).fetchall()
    assert [tuple(row) for row in tool_rows] == [
        ("search_library", "succeeded"),
        ("open_page", "succeeded"),
    ]


def test_familiar_finalizes_insufficient_after_empty_research(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    provider_instance = NoToolThenFinalProvider()

    def fake_empty_search_library(**kwargs):
        retrieval_run_id = empty_tool_result(
            config,
            thread_id=kwargs["thread_id"],
            message_id=kwargs["message_id"],
        )
        return research_tools.SearchLibraryResult(
            retrieval_run_id=retrieval_run_id,
            query=kwargs["query"],
            source_set_id="rules-core",
            source_book_ids=("bestiary",),
            hits=(),
            diagnostics=diagnostics(),
        )

    monkeypatch.setattr(research_tools, "search_library", fake_empty_search_library)
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="harpy statline",
            idempotency_key="send-agent-3",
            provider_factory=lambda _: provider_instance,
        )
    )

    assert events[-1].assistant_message is not None
    assert events[-1].assistant_message.content == "No citable evidence."
    assert events[-1].citations == ()
    assert "No accepted evidence was found" in provider_instance.messages_by_call[-1][-1].content
    with open_connection(config.db_path) as connection:
        research_run = connection.execute(
            "select status, evidence_status from familiar_research_runs"
        ).fetchone()
    assert dict(research_run) == {
        "status": "insufficient",
        "evidence_status": "insufficient",
    }


def test_familiar_tracks_partial_page_evidence_from_initial_search(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    provider_instance = NoToolThenFinalProvider()

    def fake_partial_search_library(**kwargs):
        partial_hit = hit(rank=1, subject="harpy", object_type="page_fallback")
        partial_hit = RetrievedHit(
            **{
                **partial_hit.__dict__,
                "context_text": "Harpy creature entry mentions wings and claws.",
                "snippet": "Harpy creature entry mentions wings and claws.",
            }
        )
        retrieval_run_id = chat_store.record_retrieval_run(
            config,
            thread_id=kwargs["thread_id"],
            message_id=kwargs["message_id"],
            source_set_id="rules-core",
            query=kwargs["query"],
            hits=(partial_hit,),
            source_book_ids=("bestiary",),
            diagnostics=diagnostics(),
        )
        return research_tools.SearchLibraryResult(
            retrieval_run_id=retrieval_run_id,
            query=kwargs["query"],
            source_set_id="rules-core",
            source_book_ids=("bestiary",),
            hits=(partial_hit,),
            diagnostics=diagnostics(),
        )

    monkeypatch.setattr(research_tools, "search_library", fake_partial_search_library)
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="harpy statline",
            idempotency_key="send-agent-partial-initial",
            provider_factory=lambda _: provider_instance,
        )
    )

    assert events[-1].assistant_message is not None
    assert events[-1].citations == ()
    with open_connection(config.db_path) as connection:
        row = connection.execute(
            "select status, evidence_status from familiar_research_runs"
        ).fetchone()
    assert dict(row) == {"status": "insufficient", "evidence_status": "partial"}


def test_familiar_tracks_partial_page_evidence_from_provider_tool(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update page_text
            set text = 'Harpy creature entry mentions wings and claws.'
            where page_id = 'bestiary:101'
            """
        )
    provider_instance = PartialOpenPageThenFinalProvider()

    def fake_empty_search_library(**kwargs):
        retrieval_run_id = empty_tool_result(
            config,
            thread_id=kwargs["thread_id"],
            message_id=kwargs["message_id"],
        )
        return research_tools.SearchLibraryResult(
            retrieval_run_id=retrieval_run_id,
            query=kwargs["query"],
            source_set_id="rules-core",
            source_book_ids=("bestiary",),
            hits=(),
            diagnostics=diagnostics(),
        )

    monkeypatch.setattr(research_tools, "search_library", fake_empty_search_library)
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="harpy statline",
            idempotency_key="send-agent-partial-provider",
            provider_factory=lambda _: provider_instance,
        )
    )

    assert provider_instance.planning_calls == 2
    assert events[-1].assistant_message is not None
    with open_connection(config.db_path) as connection:
        row = connection.execute(
            "select status, evidence_status from familiar_research_runs"
        ).fetchone()
    assert dict(row) == {"status": "insufficient", "evidence_status": "partial"}


def test_familiar_marks_tool_and_research_failed_when_tool_execution_raises(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)

    def fake_search_library(**kwargs):
        raise RuntimeError("synthetic tool failure")

    monkeypatch.setattr(research_tools, "search_library", fake_search_library)
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="harpy statline",
            idempotency_key="send-agent-tool-failure",
            provider_factory=lambda _: FinalAnswerProvider(),
        )
    )

    assert [event.type for event in events] == ["accepted", "failed"]
    with open_connection(config.db_path) as connection:
        research_row = connection.execute(
            """
            select status, evidence_status, tool_rounds_used, completed_at
            from familiar_research_runs
            """
        ).fetchone()
        tool_row = connection.execute(
            """
            select status, error_code, error_message, completed_at
            from familiar_tool_calls
            """
        ).fetchone()

    assert dict(research_row) | {"completed_at": bool(research_row["completed_at"])} == {
        "status": "failed",
        "evidence_status": "insufficient",
        "tool_rounds_used": 1,
        "completed_at": True,
    }
    assert dict(tool_row) | {"completed_at": bool(tool_row["completed_at"])} == {
        "status": "failed",
        "error_code": "tool_execution_failed",
        "error_message": "synthetic tool failure",
        "completed_at": True,
    }


def test_initial_tool_helpers_use_page_reference_context() -> None:
    active = research.ChatThreadContext(
        thread_id="thread-1",
        active_subject="harpy",
        active_intent="statline_lookup",
        active_book_id="bestiary",
        active_printed_page_label="99",
        active_pdf_page_number=101,
        active_source_object_id=None,
        updated_from_message_id=None,
        updated_from_model_run_id=None,
        metadata={},
        updated_at="2026-06-09T00:00:00Z",
    )
    resolved = context_resolution.resolve_research_request(
        "it's on pg 99",
        active_context=active,
    )

    assert familiar_agent.initial_tool_name(resolved) == "open_page"
    assert familiar_agent.initial_tool_arguments(
        resolved,
        query=resolved.resolved_query,
    ) == {
        "book_id": "bestiary",
        "book_title_hint": None,
        "printed_page_label": "99",
        "pdf_page_number": None,
        "subject_hint": "harpy",
        "intent": "statline_lookup",
    }


def test_tool_argument_parsing_and_status_helpers_handle_edges() -> None:
    assert familiar_agent.parse_tool_arguments(None) == {}
    assert familiar_agent.parse_tool_arguments("{bad json") == {}
    assert familiar_agent.parse_tool_arguments("[]") == {}
    assert familiar_agent.aggregate_evidence_status(
        accepted_hits=(),
        partial_hits=(),
        fallback_status="not_evaluated",
    ) == "not_evaluated"
    assert familiar_agent.bounded_error_message(Exception()) == "Exception"
    assert "/Users/" not in familiar_agent.bounded_error_message(
        RuntimeError("/Users/aftoncarlson/private.pdf failed"),
    )
    assert "private.pdf" not in familiar_agent.bounded_error_message(
        RuntimeError("/Users/aftoncarlson/private.pdf failed"),
    )
    assert len(
        familiar_agent.bounded_error_message(RuntimeError("x" * 500), max_chars=24)
    ) == 24


def test_execute_tool_dispatches_lookup_source_object_and_rejects_unknown_tool(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    thread = chat_service.chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="harpy statline",
        idempotency_key="send-agent-dispatch",
        provider="openai",
        model="gpt-5.4-mini",
    )
    resolved = context_resolution.resolve_research_request(
        "harpy statline",
        active_context=None,
    )
    conversation = conversation_context.ConversationContext(
        prompt_messages=(),
        retrieval_query="harpy statline",
        history_message_ids=(),
        history_turn_count=0,
        history_strategy="none",
    )
    tool_call = research.FamiliarToolCall(
        id="tool-call-dispatch",
        research_run_id="research-dispatch",
        step_number=1,
        call_index=0,
        provider_call_id=None,
        tool_name="lookup_source_object",
        arguments={"source_object_id": "harpy-stat", "intent": "statline_lookup"},
        argument_hash="hash",
        status="running",
        retrieval_run_id=None,
        output_summary={},
        error_code=None,
        error_message=None,
        created_at="2026-06-09T00:00:00Z",
        updated_at="2026-06-09T00:00:00Z",
        completed_at=None,
    )
    expected = research_tools.SearchLibraryResult(
        retrieval_run_id="retrieval-dispatch",
        query="source_object:harpy-stat",
        source_set_id="rules-core",
        source_book_ids=("bestiary",),
        hits=(),
        diagnostics=diagnostics(),
    )

    def fake_lookup_source_object(**kwargs):
        assert kwargs["source_object_id"] == "harpy-stat"
        assert kwargs["intent"] == "statline_lookup"
        return expected

    monkeypatch.setattr(
        research_tools,
        "lookup_source_object",
        fake_lookup_source_object,
    )
    result = chat_store.SendChatResult(
        thread=thread,
        user_message=queued.user_message,
        assistant_message=None,
        model_run=queued.model_run,
        citations=(),
    )

    dispatched = familiar_agent.execute_tool(
        config,
        result=result,
        resolved=resolved,
        tool_call=tool_call,
        step_number=1,
        tool_name="lookup_source_object",
        arguments={"source_object_id": "harpy-stat", "intent": "statline_lookup"},
        conversation=conversation,
    )

    assert dispatched == expected
    with pytest.raises(ValueError, match="Unknown Familiar tool"):
        familiar_agent.execute_tool(
            config,
            result=result,
            resolved=resolved,
            tool_call=tool_call,
            step_number=1,
            tool_name="missing_tool",
            arguments={},
            conversation=conversation,
        )
