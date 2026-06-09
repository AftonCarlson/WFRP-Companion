from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path

import pytest

from wfrp_companion.assistant import chat_service
from wfrp_companion.assistant import agent_planning
from wfrp_companion.assistant import chat_store
from wfrp_companion.assistant import context_resolution
from wfrp_companion.assistant import conversation_context
from wfrp_companion.assistant import evidence_validation
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
        parallel_tool_calls: bool | None = None,
    ):
        assert previous_response_id is None
        if tools:
            assert [tool.name for tool in tools] == ["set_research_plan"]
            assert tool_choice == {"type": "function", "name": "set_research_plan"}
            assert parallel_tool_calls is False
            yield provider.ProviderStreamEvent(
                type="tool_call",
                tool_name="set_research_plan",
                tool_call_id="call-plan",
                tool_arguments_json=json.dumps(plan_payload_from_messages(messages)),
            )
            yield provider.ProviderStreamEvent(type="completed")
            return
        self.messages = tuple(messages)
        assert tool_results == ()
        assert tool_choice in (None, "none")
        yield provider.ProviderStreamEvent(type="delta", text_delta=self.answer)
        yield provider.ProviderStreamEvent(
            type="completed",
            provider_response_id="resp-final",
            input_tokens=11,
            output_tokens=3,
        )


class PlanThenFinalProvider:
    def __init__(
        self,
        *,
        plan_payload: dict[str, object] | None = None,
        answer: str = "Harpy statline answer.",
    ) -> None:
        self.plan_payload = plan_payload
        self.answer = answer
        self.calls: list[dict[str, object]] = []
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
        parallel_tool_calls: bool | None = None,
    ):
        self.calls.append(
            {
                "messages": tuple(messages),
                "tools": tuple(tools),
                "tool_results": tuple(tool_results),
                "previous_response_id": previous_response_id,
                "tool_choice": tool_choice,
                "parallel_tool_calls": parallel_tool_calls,
            }
        )
        self.messages = tuple(messages)
        if tools and [tool.name for tool in tools] == ["set_research_plan"]:
            yield provider.ProviderStreamEvent(
                type="tool_call",
                tool_name="set_research_plan",
                tool_call_id="call-plan",
                tool_arguments_json=json.dumps(
                    self.plan_payload or plan_payload(query="harpy statline")
                ),
            )
            yield provider.ProviderStreamEvent(
                type="completed",
                provider_response_id="resp-plan",
                input_tokens=7,
                output_tokens=2,
            )
            return
        if tools:
            yield provider.ProviderStreamEvent(type="completed")
            return
        assert tool_choice == "none"
        yield provider.ProviderStreamEvent(type="delta", text_delta=self.answer)
        yield provider.ProviderStreamEvent(
            type="completed",
            provider_response_id="resp-final",
            input_tokens=11,
            output_tokens=3,
        )


class PlanningUnavailableProvider:
    def stream_response(
        self,
        *,
        messages: Sequence[provider.ProviderMessage],
        request_id: str,
        tools: Sequence[provider.ProviderToolDefinition] = (),
        tool_results: Sequence[provider.ProviderToolResult] = (),
        previous_response_id: str | None = None,
        tool_choice: object | None = None,
        parallel_tool_calls: bool | None = None,
    ):
        raise provider.ProviderUnavailableError("planning unavailable")
        yield  # pragma: no cover - keeps this as a generator.


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
        parallel_tool_calls: bool | None = None,
    ):
        self.calls.append(
            {
                "messages": tuple(messages),
                "tools": tuple(tools),
                "tool_results": tuple(tool_results),
                "previous_response_id": previous_response_id,
                "tool_choice": tool_choice,
                "parallel_tool_calls": parallel_tool_calls,
            }
        )
        if len(self.calls) == 1:
            assert [tool.name for tool in tools] == ["set_research_plan"]
            assert tool_choice == {"type": "function", "name": "set_research_plan"}
            assert parallel_tool_calls is False
            yield provider.ProviderStreamEvent(
                type="tool_call",
                tool_name="set_research_plan",
                tool_call_id="call-plan",
                tool_arguments_json=json.dumps(plan_payload_from_messages(messages)),
            )
            yield provider.ProviderStreamEvent(
                type="completed",
                provider_response_id="resp-plan",
                input_tokens=7,
                output_tokens=1,
            )
            return
        if tools:
            yield provider.ProviderStreamEvent(
                type="tool_call",
                tool_name="open_page",
                tool_call_id="call-open-page",
                tool_arguments_json=json.dumps(
                    {
                        "requirement_id": "harpy_stats",
                        "book_id": None,
                        "book_title_hint": "Old World Bestiary",
                        "printed_page_label": "99",
                        "pdf_page_number": None,
                        "subject_hint": "harpy",
                        "intent": "statline_lookup",
                    }
                ),
            )
            yield provider.ProviderStreamEvent(type="completed")
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
        parallel_tool_calls: bool | None = None,
    ):
        self.messages_by_call.append(tuple(messages))
        if tools and [tool.name for tool in tools] == ["set_research_plan"]:
            yield provider.ProviderStreamEvent(
                type="tool_call",
                tool_name="set_research_plan",
                tool_call_id="call-plan",
                tool_arguments_json=json.dumps(plan_payload_from_messages(messages)),
            )
            yield provider.ProviderStreamEvent(type="completed")
            return
        if tools:
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
        parallel_tool_calls: bool | None = None,
    ):
        self.calls.append(
            {
                "messages": tuple(messages),
                "tools": tuple(tools),
                "tool_results": tuple(tool_results),
                "previous_response_id": previous_response_id,
                "tool_choice": tool_choice,
                "parallel_tool_calls": parallel_tool_calls,
            }
        )
        if tools and [tool.name for tool in tools] == ["set_research_plan"]:
            yield provider.ProviderStreamEvent(
                type="tool_call",
                tool_name="set_research_plan",
                tool_call_id="call-plan",
                tool_arguments_json=json.dumps(plan_payload_from_messages(messages)),
            )
            yield provider.ProviderStreamEvent(type="completed")
            return
        if tools:
            self.planning_calls += 1
            if self.planning_calls == 1:
                yield provider.ProviderStreamEvent(
                    type="tool_call",
                    tool_name="open_page",
                    tool_call_id="call-partial-open-page",
                    tool_arguments_json=json.dumps(
                        {
                            "requirement_id": "harpy_stats",
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


class UnknownRequirementActionProvider:
    def stream_response(
        self,
        *,
        messages: Sequence[provider.ProviderMessage],
        request_id: str,
        tools: Sequence[provider.ProviderToolDefinition] = (),
        tool_results: Sequence[provider.ProviderToolResult] = (),
        previous_response_id: str | None = None,
        tool_choice: object | None = None,
        parallel_tool_calls: bool | None = None,
    ):
        if tools and [tool.name for tool in tools] == ["set_research_plan"]:
            yield provider.ProviderStreamEvent(
                type="tool_call",
                tool_name="set_research_plan",
                tool_call_id="call-plan",
                tool_arguments_json=json.dumps(plan_payload(query="harpy statline")),
            )
            yield provider.ProviderStreamEvent(type="completed")
            return
        if tools:
            assert parallel_tool_calls is False
            yield provider.ProviderStreamEvent(
                type="tool_call",
                tool_name="open_page",
                tool_call_id="call-bad-requirement",
                tool_arguments_json=json.dumps(
                    {
                        "requirement_id": "missing_requirement",
                        "book_id": "bestiary",
                        "book_title_hint": None,
                        "printed_page_label": "99",
                        "pdf_page_number": None,
                        "subject_hint": "harpy",
                        "intent": "statline_lookup",
                    }
                ),
            )
            yield provider.ProviderStreamEvent(type="completed")
            return
        yield provider.ProviderStreamEvent(type="delta", text_delta="should not answer")
        yield provider.ProviderStreamEvent(type="completed")


class FinishAfterEmptySearchProvider:
    def __init__(self) -> None:
        self.action_calls = 0

    def stream_response(
        self,
        *,
        messages: Sequence[provider.ProviderMessage],
        request_id: str,
        tools: Sequence[provider.ProviderToolDefinition] = (),
        tool_results: Sequence[provider.ProviderToolResult] = (),
        previous_response_id: str | None = None,
        tool_choice: object | None = None,
        parallel_tool_calls: bool | None = None,
    ):
        if tools and [tool.name for tool in tools] == ["set_research_plan"]:
            yield provider.ProviderStreamEvent(
                type="tool_call",
                tool_name="set_research_plan",
                tool_call_id="call-plan",
                tool_arguments_json=json.dumps(plan_payload(query="harpy statline")),
            )
            yield provider.ProviderStreamEvent(type="completed")
            return
        if tools:
            self.action_calls += 1
            assert parallel_tool_calls is False
            yield provider.ProviderStreamEvent(
                type="tool_call",
                tool_name="finish_research",
                tool_call_id="call-finish",
                tool_arguments_json=json.dumps(
                    {
                        "reason": "no_useful_action",
                        "requirement_ids": ["harpy_stats"],
                        "evidence_status": "insufficient",
                        "decision_summary": "No useful remaining local tool.",
                    }
                ),
            )
            yield provider.ProviderStreamEvent(type="completed")
            return
        assert tool_choice == "none"
        yield provider.ProviderStreamEvent(type="delta", text_delta="No citable evidence.")
        yield provider.ProviderStreamEvent(type="completed")


class MultiRequirementProvider:
    def __init__(self) -> None:
        self.recovery_messages: tuple[provider.ProviderMessage, ...] = ()

    def stream_response(
        self,
        *,
        messages: Sequence[provider.ProviderMessage],
        request_id: str,
        tools: Sequence[provider.ProviderToolDefinition] = (),
        tool_results: Sequence[provider.ProviderToolResult] = (),
        previous_response_id: str | None = None,
        tool_choice: object | None = None,
        parallel_tool_calls: bool | None = None,
    ):
        if tools and [tool.name for tool in tools] == ["set_research_plan"]:
            yield provider.ProviderStreamEvent(
                type="tool_call",
                tool_name="set_research_plan",
                tool_call_id="call-plan",
                tool_arguments_json=json.dumps(multi_requirement_plan_payload()),
            )
            yield provider.ProviderStreamEvent(type="completed")
            return
        if tools:
            self.recovery_messages = tuple(messages)
            assert parallel_tool_calls is False
            yield provider.ProviderStreamEvent(
                type="tool_call",
                tool_name="search_library",
                tool_call_id="call-gor-search",
                tool_arguments_json=json.dumps(
                    {
                        "requirement_id": "gor_stats",
                        "query": "gor statline",
                        "intent": "statline_lookup",
                        "subject": "gor",
                        "decision_summary": "Search for the unsatisfied Gor requirement.",
                    }
                ),
            )
            yield provider.ProviderStreamEvent(type="completed")
            return
        assert tool_choice == "none"
        yield provider.ProviderStreamEvent(type="delta", text_delta="Both statlines cited.")
        yield provider.ProviderStreamEvent(type="completed")


class MultipleRecoveryCallsProvider:
    def stream_response(
        self,
        *,
        messages: Sequence[provider.ProviderMessage],
        request_id: str,
        tools: Sequence[provider.ProviderToolDefinition] = (),
        tool_results: Sequence[provider.ProviderToolResult] = (),
        previous_response_id: str | None = None,
        tool_choice: object | None = None,
        parallel_tool_calls: bool | None = None,
    ):
        if tools and [tool.name for tool in tools] == ["set_research_plan"]:
            yield provider.ProviderStreamEvent(
                type="tool_call",
                tool_name="set_research_plan",
                tool_call_id="call-plan",
                tool_arguments_json=json.dumps(plan_payload(query="harpy statline")),
            )
            yield provider.ProviderStreamEvent(type="completed")
            return
        if tools:
            assert parallel_tool_calls is False
            payload = json.dumps(
                {
                    "requirement_id": "harpy_stats",
                    "query": "harpy statline",
                    "intent": "statline_lookup",
                }
            )
            yield provider.ProviderStreamEvent(
                type="tool_call",
                tool_name="search_library",
                tool_call_id="call-search-1",
                tool_arguments_json=payload,
            )
            yield provider.ProviderStreamEvent(
                type="tool_call",
                tool_name="open_page",
                tool_call_id="call-open-2",
                tool_arguments_json=json.dumps(
                    {
                        "requirement_id": "harpy_stats",
                        "printed_page_label": "99",
                    }
                ),
            )
            yield provider.ProviderStreamEvent(type="completed")
            return
        yield provider.ProviderStreamEvent(type="delta", text_delta="should not answer")
        yield provider.ProviderStreamEvent(type="completed")


class MultiplePlanCallsProvider:
    def stream_response(
        self,
        *,
        messages: Sequence[provider.ProviderMessage],
        request_id: str,
        tools: Sequence[provider.ProviderToolDefinition] = (),
        tool_results: Sequence[provider.ProviderToolResult] = (),
        previous_response_id: str | None = None,
        tool_choice: object | None = None,
        parallel_tool_calls: bool | None = None,
    ):
        payload = json.dumps(plan_payload(query="harpy statline"))
        yield provider.ProviderStreamEvent(
            type="tool_call",
            tool_name="set_research_plan",
            tool_call_id="call-plan-1",
            tool_arguments_json=payload,
        )
        yield provider.ProviderStreamEvent(
            type="tool_call",
            tool_name="set_research_plan",
            tool_call_id="call-plan-2",
            tool_arguments_json=payload,
        )
        yield provider.ProviderStreamEvent(type="completed")


class NoPlanCallProvider:
    def stream_response(
        self,
        *,
        messages: Sequence[provider.ProviderMessage],
        request_id: str,
        tools: Sequence[provider.ProviderToolDefinition] = (),
        tool_results: Sequence[provider.ProviderToolResult] = (),
        previous_response_id: str | None = None,
        tool_choice: object | None = None,
        parallel_tool_calls: bool | None = None,
    ):
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


def plan_payload(
    *,
    query: str,
    subject: str | None = "harpy",
    intent: str = "statline_lookup",
    requirement_id: str = "harpy_stats",
) -> dict[str, object]:
    include_terms = [] if subject is None else [subject]
    return {
        "intent": intent,
        "plan_summary": f"Find accepted evidence for {query}.",
        "subject": {
            "canonical": subject,
            "surface": subject,
            "include_terms": include_terms,
            "exclude_terms": [],
            "book_title_hints": [],
            "page_hints": [],
            "notes": None,
        },
        "requirements": [
            {
                "id": requirement_id,
                "requirement_type": "statline_evidence"
                if intent == "statline_lookup"
                else "topical_evidence",
                "subject": {
                    "canonical": subject,
                    "surface": subject,
                    "include_terms": include_terms,
                    "exclude_terms": [],
                    "book_title_hints": [],
                    "page_hints": [],
                    "notes": None,
                },
                "required_terms": include_terms,
                "excluded_terms": [],
                "object_type_hints": ["stat_block", "monster_profile"]
                if intent == "statline_lookup"
                else [],
                "min_accepted_hits": 1,
                "required": True,
            }
        ],
        "planned_actions": [
            {
                "tool_name": "search_library",
                "requirement_id": requirement_id,
                "purpose": f"Search checked books for {query}.",
                "arguments": {
                    "query": query,
                    "intent": intent,
                    "subject": subject,
                    "limit": 8,
                    "include_terms": include_terms,
                    "exclude_terms": [],
                    "object_type_hints": ["stat_block", "monster_profile"]
                    if intent == "statline_lookup"
                    else [],
                    "book_title_hints": [],
                    "page_hints": [],
                },
            }
        ],
    }


def multi_requirement_plan_payload() -> dict[str, object]:
    harpy_plan = plan_payload(query="harpy statline")
    gor_requirement = {
        "id": "gor_stats",
        "requirement_type": "statline_evidence",
        "subject": {
            "canonical": "gor",
            "surface": "gor",
            "include_terms": ["gor"],
            "exclude_terms": [],
            "book_title_hints": [],
            "page_hints": [],
            "notes": None,
        },
        "required_terms": ["gor"],
        "excluded_terms": [],
        "object_type_hints": ["stat_block", "monster_profile"],
        "min_accepted_hits": 1,
        "required": True,
    }
    return {
        **harpy_plan,
        "plan_summary": "Find accepted statline evidence for Harpy and Gor.",
        "requirements": [*harpy_plan["requirements"], gor_requirement],
    }


def plan_payload_from_messages(
    messages: Sequence[provider.ProviderMessage],
) -> dict[str, object]:
    content = messages[-1].content
    query = planning_line(content, "Resolved query hint") or "harpy statline"
    intent = planning_line(content, "Intent hint") or "statline_lookup"
    subject = planning_line(content, "Subject hint")
    active_book = planning_line(content, "Active book hint")
    active_page = planning_line(content, "Active printed page hint")
    subject = None if subject in (None, "none") else subject
    if "page 99" in query or active_page not in (None, "none"):
        return page_plan_payload(
            query=query,
            intent=intent,
            subject=subject,
            active_book=None if active_book in (None, "none") else active_book,
            printed_page="99" if active_page in (None, "none") else active_page,
        )
    return plan_payload(
        query=query,
        subject=subject,
        intent=intent,
        requirement_id="research_evidence" if subject is None else f"{subject}_stats",
    )


def planning_line(content: str, label: str) -> str | None:
    prefix = f"{label}: "
    for line in content.splitlines():
        if line.startswith(prefix):
            value = line.removeprefix(prefix).strip()
            return value if value else None
    return None


def page_plan_payload(
    *,
    query: str,
    intent: str,
    subject: str | None,
    active_book: str | None,
    printed_page: str | None,
) -> dict[str, object]:
    payload = plan_payload(
        query=query,
        subject=subject,
        intent=intent,
        requirement_id="page_evidence",
    )
    payload["planned_actions"] = [
        {
            "tool_name": "open_page",
            "requirement_id": "page_evidence",
            "purpose": "Open the user-indicated source page.",
            "arguments": {
                "book_id": active_book,
                "book_title_hint": None,
                "printed_page_label": printed_page,
                "pdf_page_number": None,
                "subject_hint": subject,
                "intent": intent,
                "include_terms": [] if subject is None else [subject],
                "exclude_terms": [],
            },
        }
    ]
    return payload


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
        "research_plan",
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
            select status, reason_code, research_plan_id, requirement_id
            from familiar_evidence_judgments
            order by created_at, id
            """
        ).fetchall()
        plan_id = connection.execute(
            "select id from familiar_research_plans"
        ).fetchone()["id"]
        retrieval_metadata = json.loads(
            connection.execute(
                "select metadata_json from retrieval_runs order by created_at desc limit 1"
            ).fetchone()["metadata_json"]
        )

    assert dict(research_run) == {"status": "completed", "evidence_status": "sufficient"}
    assert sorted(tuple(row) for row in judgments) == [
        ("accepted", "statline_evidence", plan_id, "harpy_stats"),
        ("rejected", "subject_mismatch", plan_id, "harpy_stats"),
    ]
    assert retrieval_metadata["validation_status"] == "sufficient"


def test_familiar_accepts_provider_short_requirement_ids(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    provider_instance = PlanThenFinalProvider(
        plan_payload=plan_payload(query="orc stats", subject="orc", requirement_id="r1")
    )
    observed_tool_call_ids: list[str] = []

    def fake_search_library(**kwargs):
        observed_tool_call_ids.append(kwargs["tool_call_id"])
        retrieved_hit = hit(rank=1, subject="orc")
        retrieval_run_id = chat_store.record_retrieval_run(
            config,
            thread_id=kwargs["thread_id"],
            message_id=kwargs["message_id"],
            source_set_id="rules-core",
            query=kwargs["query"],
            hits=(retrieved_hit,),
            source_book_ids=("bestiary",),
            diagnostics=diagnostics("accepted"),
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
            hits=(retrieved_hit,),
            diagnostics=diagnostics("accepted"),
        )

    monkeypatch.setattr(research_tools, "search_library", fake_search_library)
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="orc stats",
            idempotency_key="send-agent-short-requirement-id",
            provider_factory=lambda _: provider_instance,
        )
    )

    assert len(observed_tool_call_ids) == 1
    assert [event.type for event in events] == [
        "accepted",
        "research_started",
        "research_plan",
        "tool_call",
        "retrieval",
        "tool_result",
        "evidence_validation",
        "delta",
        "completed",
    ]
    with open_connection(config.db_path) as connection:
        plan_requirement = json.loads(
            connection.execute(
                "select requirements_json from familiar_research_plans"
            ).fetchone()["requirements_json"]
        )[0]
        tool_row = connection.execute(
            "select requirement_id from familiar_tool_calls"
        ).fetchone()
        judgment_row = connection.execute(
            "select requirement_id from familiar_evidence_judgments"
        ).fetchone()

    assert plan_requirement["id"] == "r1"
    assert tool_row["requirement_id"] == "r1"
    assert judgment_row["requirement_id"] == "r1"


def test_familiar_tool_call_trace_uses_public_scrubbed_arguments(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    payload = plan_payload(
        query="/Users/aftoncarlson/private/bestiary.pdf harpy statline"
    )
    payload["planned_actions"][0]["arguments"]["copied_source_text"] = (
        "Synthetic Harpy stat_block copied from a local PDF."
    )
    provider_instance = PlanThenFinalProvider(plan_payload=payload)

    def fake_search_library(**kwargs):
        retrieved_hit = hit(rank=1, subject="harpy")
        retrieval_run_id = chat_store.record_retrieval_run(
            config,
            thread_id=kwargs["thread_id"],
            message_id=kwargs["message_id"],
            source_set_id="rules-core",
            query=kwargs["query"],
            hits=(retrieved_hit,),
            source_book_ids=("bestiary",),
            diagnostics=diagnostics("accepted"),
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
            hits=(retrieved_hit,),
            diagnostics=diagnostics("accepted"),
        )

    monkeypatch.setattr(research_tools, "search_library", fake_search_library)
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="harpy statline",
            idempotency_key="send-agent-public-trace-arguments",
            provider_factory=lambda _: provider_instance,
        )
    )

    tool_event = next(event for event in events if event.type == "tool_call")
    public_arguments = tool_event.metadata["arguments"]
    serialized_arguments = json.dumps(public_arguments)
    assert "copied_source_text" not in public_arguments
    assert "query" not in public_arguments
    assert "/Users/" not in serialized_arguments
    assert ".pdf" not in serialized_arguments
    assert public_arguments == {
        "intent": "statline_lookup",
        "limit": 8,
    }


def test_familiar_persists_plan_before_executing_local_retrieval(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    provider_instance = PlanThenFinalProvider()
    observed: list[str] = []

    def fake_search_library(**kwargs):
        with open_connection(config.db_path) as connection:
            stored_plan = connection.execute(
                """
                select id, status, plan_summary
                from familiar_research_plans
                """
            ).fetchone()
        observed.append(f"search_after_plan:{stored_plan['status']}")
        retrieval_run_id = chat_store.record_retrieval_run(
            config,
            thread_id=kwargs["thread_id"],
            message_id=kwargs["message_id"],
            source_set_id="rules-core",
            query=kwargs["query"],
            hits=(hit(rank=1, subject="harpy"),),
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
            hits=(hit(rank=1, subject="harpy"),),
            diagnostics=diagnostics(),
        )

    monkeypatch.setattr(research_tools, "search_library", fake_search_library)
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="harpy statline",
            idempotency_key="send-agent-plan-first",
            provider_factory=lambda _: provider_instance,
        )
    )

    assert observed == ["search_after_plan:accepted"]
    assert [event.type for event in events][:4] == [
        "accepted",
        "research_started",
        "research_plan",
        "tool_call",
    ]
    plan_event = next(event for event in events if event.type == "research_plan")
    assert plan_event.metadata == {
        "research_run_id": plan_event.metadata["research_run_id"],
        "research_plan_id": plan_event.metadata["research_plan_id"],
        "intent": "statline_lookup",
        "requirement_count": 1,
        "requirements": [
            {
                "id": "harpy_stats",
                "requirement_type": "statline_evidence",
                "min_accepted_hits": 1,
                "required": True,
            }
        ],
    }
    planning_call = provider_instance.calls[0]
    assert [tool.name for tool in planning_call["tools"]] == ["set_research_plan"]
    assert planning_call["tool_choice"] == {
        "type": "function",
        "name": "set_research_plan",
    }
    assert planning_call["parallel_tool_calls"] is False
    with open_connection(config.db_path) as connection:
        plan_row = connection.execute(
            "select status, provider_call_id from familiar_research_plans"
        ).fetchone()
        tool_row = connection.execute(
            """
            select research_plan_id, requirement_id, purpose
            from familiar_tool_calls
            """
        ).fetchone()

    assert dict(plan_row) == {"status": "accepted", "provider_call_id": "call-plan"}
    assert tool_row["research_plan_id"] == plan_event.metadata["research_plan_id"]
    assert tool_row["requirement_id"] == "harpy_stats"
    assert tool_row["purpose"] == "Search checked books for harpy statline."


def test_planning_provider_unavailable_creates_no_tool_calls_and_fails_run(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="harpy statline",
            idempotency_key="send-agent-plan-unavailable",
            provider_factory=lambda _: PlanningUnavailableProvider(),
        )
    )

    assert [event.type for event in events] == ["accepted", "failed"]
    assert events[-1].model_run.status == "failed"
    assert events[-1].model_run.error_code == "provider_unavailable"
    with open_connection(config.db_path) as connection:
        research_row = connection.execute(
            "select status, evidence_status from familiar_research_runs"
        ).fetchone()
        tool_count = connection.execute(
            "select count(*) from familiar_tool_calls"
        ).fetchone()[0]
        retrieval_count = connection.execute(
            "select count(*) from retrieval_runs"
        ).fetchone()[0]

    assert dict(research_row) == {
        "status": "failed",
        "evidence_status": "insufficient",
    }
    assert tool_count == 0
    assert retrieval_count == 0


def test_planning_multiple_tool_calls_fails_before_retrieval(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="harpy statline",
            idempotency_key="send-agent-plan-multiple",
            provider_factory=lambda _: MultiplePlanCallsProvider(),
        )
    )

    assert events[-1].type == "failed"
    assert events[-1].error_message == "Planning returned multiple tool calls"
    with open_connection(config.db_path) as connection:
        assert connection.execute("select count(*) from retrieval_runs").fetchone()[0] == 0


def test_planning_without_tool_call_fails_before_retrieval(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="harpy statline",
            idempotency_key="send-agent-plan-missing",
            provider_factory=lambda _: NoPlanCallProvider(),
        )
    )

    assert events[-1].type == "failed"
    assert events[-1].error_message == "Planning did not return set_research_plan"


def test_familiar_handles_plan_with_no_initial_actions(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    payload = plan_payload(query="harpy statline")
    payload["planned_actions"] = []
    provider_instance = PlanThenFinalProvider(
        plan_payload=payload,
        answer="No action answer.",
    )
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="harpy statline",
            idempotency_key="send-agent-no-actions",
            provider_factory=lambda _: provider_instance,
        )
    )

    assert [event.type for event in events] == [
        "accepted",
        "research_started",
        "research_plan",
        "evidence_validation",
        "delta",
        "completed",
    ]
    assert events[-1].assistant_message is not None
    assert events[-1].assistant_message.content == "No action answer."


def test_familiar_handles_initial_finish_research_action(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    payload = plan_payload(query="harpy statline")
    payload["planned_actions"] = [
        {
            "tool_name": "finish_research",
            "requirement_id": "harpy_stats",
            "purpose": "Stop before retrieval.",
            "arguments": {
                "reason": "no_useful_action",
                "requirement_ids": ["harpy_stats"],
                "evidence_status": "insufficient",
                "decision_summary": "No local tool can improve this.",
            },
        }
    ]
    provider_instance = PlanThenFinalProvider(
        plan_payload=payload,
        answer="Initial finish answer.",
    )
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="harpy statline",
            idempotency_key="send-agent-initial-finish",
            provider_factory=lambda _: provider_instance,
        )
    )

    assert [event.type for event in events] == [
        "accepted",
        "research_started",
        "research_plan",
        "finalizing",
        "evidence_validation",
        "delta",
        "completed",
    ]
    assert events[-1].assistant_message is not None
    with open_connection(config.db_path) as connection:
        assert connection.execute("select count(*) from retrieval_runs").fetchone()[0] == 0


def test_familiar_accepts_topical_evidence_for_dungeon_crawl_recommendation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    provider_instance = FinalAnswerProvider(answer="Karak Azgal recommendation.")
    karak_hit = RetrievedHit(
        **{
            **hit(rank=1, subject="karak azgal", object_type="page_fallback").__dict__,
            "title": "Karak Azgal",
            "object_title": "Using Karak Azgal",
            "snippet": (
                "Karak Azgal is a ruined hold with mines, tombs, and adventure sites."
            ),
            "context_text": (
                "Karak Azgal is a ruined hold with mines, tombs, and adventure sites."
            ),
            "text_snapshot_sha256": "sha-karak-azgal",
        }
    )

    def fake_search_library(**kwargs):
        assert kwargs["query"] == (
            "dungeon crawl adventure setting underground ruins sewer mine"
        )
        retrieval_run_id = chat_store.record_retrieval_run(
            config,
            thread_id=kwargs["thread_id"],
            message_id=kwargs["message_id"],
            source_set_id="rules-core",
            query=kwargs["query"],
            hits=(karak_hit,),
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
            hits=(karak_hit,),
            diagnostics=diagnostics(),
        )

    monkeypatch.setattr(research_tools, "search_library", fake_search_library)
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="tell me what the best setting to run a dungeon crawl",
            idempotency_key="send-agent-dungeon-crawl-recommendation",
            provider_factory=lambda _: provider_instance,
        )
    )

    assert events[-1].assistant_message is not None
    assert events[-1].assistant_message.content == "Karak Azgal recommendation."
    assert events[-1].citations[0].snippet == (
        "Karak Azgal is a ruined hold with mines, tombs, and adventure sites."
    )
    assert "Karak Azgal is a ruined hold" in provider_instance.messages[-1].content
    with open_connection(config.db_path) as connection:
        research_row = connection.execute(
            """
            select resolved_query, evidence_status, metadata_json
            from familiar_research_runs
            """
        ).fetchone()
        tool_arguments = json.loads(
            connection.execute(
                "select arguments_json from familiar_tool_calls"
            ).fetchone()["arguments_json"]
        )
        judgments = connection.execute(
            """
            select status, reason_code
            from familiar_evidence_judgments
            """
        ).fetchall()

    assert research_row["resolved_query"] == (
        "dungeon crawl adventure setting underground ruins sewer mine"
    )
    assert research_row["evidence_status"] == "sufficient"
    assert json.loads(research_row["metadata_json"])["subject"] is None
    assert tool_arguments["subject"] is None
    assert [tuple(row) for row in judgments] == [("accepted", "topical_evidence")]


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
    assert "research_plan" in event_types
    assert event_types.count("tool_call") == 2
    assert event_types.count("tool_result") == 2
    assert "evidence_validation" in event_types
    assert events[-1].assistant_message is not None
    assert events[-1].assistant_message.content == "Recovered harpy stats."
    assert events[-1].citations[0].title == "Old World Bestiary"
    assert events[-1].citations[0].page_label == "99"
    assert provider_instance.calls[0]["tools"]
    assert provider_instance.calls[0]["tool_results"] == ()
    assert provider_instance.calls[1]["tools"]
    assert '"hit_count": 0' in provider_instance.calls[1]["messages"][-1].content
    assert "Prior local tool results:" in provider_instance.calls[1]["messages"][-1].content
    assert provider_instance.calls[-1]["tool_choice"] in (None, "none")
    with open_connection(config.db_path) as connection:
        tool_rows = connection.execute(
            "select tool_name, status from familiar_tool_calls order by step_number"
        ).fetchall()
    assert [tuple(row) for row in tool_rows] == [
        ("search_library", "succeeded"),
        ("open_page", "succeeded"),
    ]


def test_familiar_rejects_provider_action_with_unknown_requirement(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)

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
            idempotency_key="send-agent-bad-requirement",
            provider_factory=lambda _: UnknownRequirementActionProvider(),
        )
    )

    assert events[-1].type == "failed"
    assert "unknown requirement" in (events[-1].error_message or "")
    with open_connection(config.db_path) as connection:
        research_row = connection.execute(
            """
            select status, evidence_status, tool_rounds_used
            from familiar_research_runs
            """
        ).fetchone()
        retrieval_count = connection.execute(
            "select count(*) from retrieval_runs"
        ).fetchone()[0]
        tool_rows = connection.execute(
            "select tool_name, requirement_id from familiar_tool_calls order by step_number"
        ).fetchall()

    assert dict(research_row) == {
        "status": "failed",
        "evidence_status": "insufficient",
        "tool_rounds_used": 1,
    }
    assert retrieval_count == 1
    assert [tuple(row) for row in tool_rows] == [("search_library", "harpy_stats")]


def test_familiar_finish_research_action_runs_no_additional_retrieval(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    provider_instance = FinishAfterEmptySearchProvider()

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
            idempotency_key="send-agent-finish-research",
            provider_factory=lambda _: provider_instance,
        )
    )

    assert provider_instance.action_calls == 1
    assert [event.type for event in events] == [
        "accepted",
        "research_started",
        "research_plan",
        "tool_call",
        "retrieval",
        "tool_result",
        "finalizing",
        "evidence_validation",
        "delta",
        "completed",
    ]
    assert events[-1].assistant_message is not None
    assert events[-1].assistant_message.content == "No citable evidence."
    with open_connection(config.db_path) as connection:
        retrieval_count = connection.execute(
            "select count(*) from retrieval_runs"
        ).fetchone()[0]
        tool_rows = connection.execute(
            "select tool_name from familiar_tool_calls order by step_number"
        ).fetchall()

    assert retrieval_count == 1
    assert [row["tool_name"] for row in tool_rows] == ["search_library"]


def test_recovery_and_final_prompts_summarize_rejections_without_rejected_text(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    provider_instance = NoToolThenFinalProvider()

    def fake_wrong_search_library(**kwargs):
        rejected_hit = hit(rank=1, subject="gor")
        retrieval_run_id = chat_store.record_retrieval_run(
            config,
            thread_id=kwargs["thread_id"],
            message_id=kwargs["message_id"],
            source_set_id="rules-core",
            query=kwargs["query"],
            hits=(rejected_hit,),
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
            hits=(rejected_hit,),
            diagnostics=diagnostics(),
        )

    monkeypatch.setattr(research_tools, "search_library", fake_wrong_search_library)
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="harpy statline",
            idempotency_key="send-agent-rejected-ledger",
            provider_factory=lambda _: provider_instance,
        )
    )

    assert events[-1].assistant_message is not None
    assert events[-1].assistant_message.content == "No citable evidence."
    leaked_events = [
        event
        for event in events
        if event.type in {"retrieval", "tool_result", "failed", "completed"}
        and event.citations
    ]
    assert leaked_events == []
    recovery_prompt = provider_instance.messages_by_call[1][-1].content
    final_prompt = provider_instance.messages_by_call[2][-1].content
    assert "Synthetic Gor stat_block" not in recovery_prompt
    assert '"rejected_reason_counts": {"subject_mismatch": 1}' in recovery_prompt
    assert "Synthetic Gor stat_block" not in final_prompt
    assert "No accepted evidence was found." in final_prompt
    assert "- harpy_stats (statline_evidence): unsatisfied" in final_prompt


def test_familiar_continues_until_all_required_plan_requirements_are_satisfied(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    provider_instance = MultiRequirementProvider()
    queries: list[str] = []

    def fake_search_library(**kwargs):
        queries.append(kwargs["query"])
        subject = "gor" if "gor" in kwargs["query"] else "harpy"
        retrieved_hit = hit(rank=1, subject=subject)
        retrieval_run_id = chat_store.record_retrieval_run(
            config,
            thread_id=kwargs["thread_id"],
            message_id=kwargs["message_id"],
            source_set_id="rules-core",
            query=kwargs["query"],
            hits=(retrieved_hit,),
            source_book_ids=("bestiary",),
            diagnostics=diagnostics("accepted"),
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
            hits=(retrieved_hit,),
            diagnostics=diagnostics("accepted"),
        )

    monkeypatch.setattr(research_tools, "search_library", fake_search_library)
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="compare harpy and gor statlines",
            idempotency_key="send-agent-multi-requirement",
            provider_factory=lambda _: provider_instance,
        )
    )

    assert queries == ["harpy statline", "gor statline"]
    assert events[-1].assistant_message is not None
    assert events[-1].assistant_message.content == "Both statlines cited."
    recovery_prompt = provider_instance.recovery_messages[-1].content
    assert "Accepted research plan:" in recovery_prompt
    assert "harpy_stats (statline_evidence): satisfied" in recovery_prompt
    assert "include: harpy" in recovery_prompt
    assert "required_terms: harpy" in recovery_prompt
    assert "gor_stats (statline_evidence): unsatisfied" in recovery_prompt
    tool_event = next(event for event in events if event.type == "tool_call")
    assert "purpose" not in tool_event.metadata
    validation_event = next(
        event for event in events if event.type == "evidence_validation"
    )
    requirement_summary = validation_event.metadata["requirements"][0]
    assert set(requirement_summary) == {
        "id",
        "requirement_type",
        "status",
        "accepted_hit_count",
        "partial_hit_count",
        "min_accepted_hits",
        "required",
    }
    with open_connection(config.db_path) as connection:
        research_run = connection.execute(
            """
            select status, evidence_status, tool_rounds_used
            from familiar_research_runs
            """
        ).fetchone()
        tool_rows = connection.execute(
            """
            select tool_name, requirement_id
            from familiar_tool_calls
            order by step_number
            """
        ).fetchall()
    assert dict(research_run) == {
        "status": "completed",
        "evidence_status": "sufficient",
        "tool_rounds_used": 2,
    }
    assert [tuple(row) for row in tool_rows] == [
        ("search_library", "harpy_stats"),
        ("search_library", "gor_stats"),
    ]


def test_familiar_rejects_multiple_recovery_tool_calls(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)

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
            idempotency_key="send-agent-multiple-recovery-calls",
            provider_factory=lambda _: MultipleRecoveryCallsProvider(),
        )
    )
    assert events[-1].type == "failed"
    assert events[-1].error_message == "Research action returned multiple tool calls"
    with open_connection(config.db_path) as connection:
        tool_count = connection.execute(
            "select count(*) from familiar_tool_calls"
        ).fetchone()[0]
        research_run = connection.execute(
            "select status, evidence_status from familiar_research_runs"
        ).fetchone()
    assert tool_count == 1
    assert dict(research_run) == {
        "status": "failed",
        "evidence_status": "insufficient",
    }


def test_familiar_uses_reader_context_for_page_correction(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    provider_instance = FinalAnswerProvider(answer="Page-corrected answer.")
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="it's on pg 99",
            idempotency_key="send-reader-page",
            reader_context=research.ReaderContext(
                active_book_id="bestiary",
                active_pdf_page_number=101,
                open_book_ids=("bestiary",),
            ),
            provider_factory=lambda _: provider_instance,
        )
    )

    tool_event = next(event for event in events if event.type == "tool_call")
    assert tool_event.metadata is not None
    assert tool_event.metadata["tool_name"] == "open_page"
    assert tool_event.metadata["arguments"] == {
        "book_id": "bestiary",
        "printed_page_label": "99",
        "pdf_page_number": None,
        "intent": "rules_lookup",
    }
    assert events[-1].assistant_message is not None
    assert events[-1].assistant_message.content == "Page-corrected answer."
    assert events[-1].citations[0].book_id == "bestiary"
    assert events[-1].citations[0].page_label == "99"
    with open_connection(config.db_path) as connection:
        row = connection.execute(
            "select resolved_query, metadata_json from familiar_research_runs"
        ).fetchone()
    metadata = json.loads(row["metadata_json"])
    assert row["resolved_query"] == "it's on pg 99 page 99"
    assert metadata["reader_context"] == {
        "active_book_id": "bestiary",
        "active_pdf_page_number": 101,
        "open_book_ids": ["bestiary"],
    }


def test_reader_context_merge_preserves_subject_and_tracks_reader_hint() -> None:
    active_context = research.ChatThreadContext(
        thread_id="thread-1",
        active_subject="harpy",
        active_intent="statline_lookup",
        active_book_id="old-book",
        active_printed_page_label="44",
        active_pdf_page_number=46,
        active_source_object_id="old-object",
        updated_from_message_id="message-1",
        updated_from_model_run_id="run-1",
        metadata={"evidence_status": "sufficient"},
        updated_at="2026-06-09T00:00:00Z",
    )

    unchanged = familiar_agent.merge_reader_context(
        active_context,
        None,
        thread_id="thread-1",
    )
    empty = familiar_agent.merge_reader_context(
        active_context,
        research.ReaderContext(),
        thread_id="thread-1",
    )
    merged = familiar_agent.merge_reader_context(
        active_context,
        research.ReaderContext(
            active_book_id="bestiary",
            active_pdf_page_number=101,
            active_printed_page_label="99",
            open_book_ids=("bestiary", "bestiary", "core-rules"),
        ),
        thread_id="thread-1",
    )

    assert unchanged is active_context
    assert empty is active_context
    assert merged is not None
    assert merged.active_subject == "harpy"
    assert merged.active_intent == "statline_lookup"
    assert merged.active_book_id == "bestiary"
    assert merged.active_printed_page_label == "99"
    assert merged.active_pdf_page_number == 101
    assert merged.metadata == {
        "evidence_status": "sufficient",
        "reader_context": {
            "active_book_id": "bestiary",
            "active_pdf_page_number": 101,
            "active_printed_page_label": "99",
            "open_book_ids": ["bestiary", "core-rules"],
        },
    }


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
    assert all(call["previous_response_id"] is None for call in provider_instance.calls)
    assert all(call["tool_results"] == () for call in provider_instance.calls)
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
    search_resolved = context_resolution.resolve_research_request(
        "harpy statline",
        active_context=None,
    )
    assert familiar_agent.initial_tool_name(search_resolved) == "search_library"
    assert familiar_agent.initial_tool_arguments(
        search_resolved,
        query=search_resolved.resolved_query,
    ) == {
        "query": "harpy statline",
        "intent": "statline_lookup",
        "subject": "harpy",
        "limit": 8,
    }


def test_tool_argument_parsing_and_status_helpers_handle_edges() -> None:
    assert familiar_agent.parse_tool_arguments(None) == {}
    assert familiar_agent.parse_tool_arguments("{bad json") == {}
    assert familiar_agent.parse_tool_arguments("[]") == {}
    assert familiar_agent.string_list_argument({}, "requirement_ids") == ()
    assert familiar_agent.string_list_argument(
        {"requirement_ids": ["harpy_stats", "", 42]},
        "requirement_ids",
    ) == ("harpy_stats",)
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


def test_action_validation_helpers_reject_invalid_actions() -> None:
    plan = agent_planning.parse_research_plan(
        plan_payload(query="harpy statline"),
        research_run_id="research-1",
        plan_id="plan-1",
        revision=1,
    )
    planned_action = plan.planned_actions[0]

    with pytest.raises(provider.ProviderError, match="missing requirement_id"):
        familiar_agent.validate_planned_tool_action(
            plan,
            agent_planning.PlannedAction(
                tool_name="search_library",
                requirement_id=None,
                purpose="Missing requirement.",
                arguments={"query": "harpy"},
            ),
        )
    with pytest.raises(provider.ProviderError, match="mismatch"):
        familiar_agent.validate_planned_tool_action(
            plan,
            agent_planning.PlannedAction(
                tool_name="search_library",
                requirement_id=planned_action.requirement_id,
                purpose="Mismatched requirement.",
                arguments={"requirement_id": "other_requirement"},
            ),
        )
    with pytest.raises(provider.ProviderError, match="finish_research"):
        familiar_agent.validate_planned_tool_action(
            plan,
            agent_planning.PlannedAction(
                tool_name="finish_research",
                requirement_id=planned_action.requirement_id,
                purpose="Finish.",
                arguments={},
            ),
        )
    with pytest.raises(provider.ProviderError, match="Unknown Familiar tool"):
        familiar_agent.validate_planned_tool_action(
            plan,
            agent_planning.PlannedAction(
                tool_name="missing_tool",
                requirement_id=planned_action.requirement_id,
                purpose="Bad tool.",
                arguments={},
            ),
        )
    with pytest.raises(provider.ProviderError, match="tool name"):
        familiar_agent.validate_provider_tool_action(
            plan,
            familiar_agent.ProviderToolRequest(
                tool_name=None,
                tool_call_id="call-tool",
                arguments={},
            ),
        )
    with pytest.raises(provider.ProviderError, match="Unknown Familiar tool"):
        familiar_agent.validate_provider_tool_action(
            plan,
            familiar_agent.ProviderToolRequest(
                tool_name="missing_tool",
                tool_call_id="call-tool",
                arguments={"requirement_id": "harpy_stats"},
            ),
        )
    with pytest.raises(provider.ProviderError, match="missing requirement_id"):
        familiar_agent.validate_provider_tool_action(
            plan,
            familiar_agent.ProviderToolRequest(
                tool_name="search_library",
                tool_call_id="call-tool",
                arguments={},
            ),
        )
    with pytest.raises(provider.ProviderError, match="unknown requirement"):
        familiar_agent.requirement_by_id(plan, "missing_requirement")


@pytest.mark.parametrize(
    ("arguments", "accepted", "rounds", "message"),
    (
        (
            {
                "reason": "bad",
                "requirement_ids": ["harpy_stats"],
                "evidence_status": "insufficient",
                "decision_summary": "Stop.",
            },
            (),
            1,
            "reason",
        ),
        (
            {
                "reason": "no_useful_action",
                "requirement_ids": ["harpy_stats"],
                "evidence_status": "bad",
                "decision_summary": "Stop.",
            },
            (),
            1,
            "evidence_status",
        ),
        (
            {
                "reason": "no_useful_action",
                "requirement_ids": [],
                "evidence_status": "insufficient",
                "decision_summary": "Stop.",
            },
            (),
            1,
            "missing requirement_ids",
        ),
        (
            {
                "reason": "requirements_satisfied",
                "requirement_ids": ["harpy_stats"],
                "evidence_status": "sufficient",
                "decision_summary": "Stop.",
            },
            (),
            1,
            "cannot satisfy",
        ),
        (
            {
                "reason": "budget_exhausted",
                "requirement_ids": ["harpy_stats"],
                "evidence_status": "insufficient",
                "decision_summary": "Stop.",
            },
            (),
            1,
            "budget is not exhausted",
        ),
        (
            {
                "reason": "no_useful_action",
                "requirement_ids": ["harpy_stats"],
                "evidence_status": "insufficient",
            },
            (),
            1,
            "missing decision_summary",
        ),
        (
            {
                "reason": "requirements_satisfied",
                "requirement_ids": ["harpy_stats"],
                "evidence_status": "sufficient",
                "decision_summary": "Stop.",
            },
            (hit(rank=1, subject="harpy"),),
            1,
            "unsatisfied requirements",
        ),
    ),
)
def test_finish_research_validation_rejects_invalid_arguments(
    arguments: dict[str, object],
    accepted: tuple[RetrievedHit, ...],
    rounds: int,
    message: str,
) -> None:
    plan = agent_planning.parse_research_plan(
        plan_payload(query="harpy statline"),
        research_run_id="research-1",
        plan_id="plan-1",
        revision=1,
    )

    with pytest.raises(provider.ProviderError, match=message):
        familiar_agent.validate_finish_research_action(
            plan,
            arguments,
            accepted_hits=accepted,
            tool_rounds_used=rounds,
            plan_satisfied=False if message == "unsatisfied requirements" else True,
        )


def test_plan_requirement_helpers_cover_empty_and_partial_states() -> None:
    plan_payload_without_required = plan_payload(query="harpy statline")
    plan_payload_without_required["requirements"][0]["required"] = False
    plan = agent_planning.parse_research_plan(
        plan_payload_without_required,
        research_run_id="research-1",
        plan_id="plan-1",
        revision=1,
    )

    assert familiar_agent.plan_requirements_satisfied(plan, {}) is False
    assert (
        familiar_agent.aggregate_evidence_status(
            accepted_hits=(hit(rank=1, subject="harpy"),),
            partial_hits=(),
            fallback_status="not_evaluated",
        )
        == "sufficient"
    )
    assert (
        familiar_agent.aggregate_evidence_status(
            accepted_hits=(),
            partial_hits=(hit(rank=1, subject="harpy"),),
            fallback_status="not_evaluated",
        )
        == "partial"
    )


def test_public_trace_helpers_scrub_lists_truncate_and_fallback_types() -> None:
    assert familiar_agent.public_trace_text(None) == ""
    assert familiar_agent.public_argument_value(
        ["/Users/aftoncarlson/private.pdf", 3, False, None, {"hidden": "ignored"}]
    ) == ["[local path removed]", 3, False, None]
    assert familiar_agent.public_argument_value({"unexpected": "value"}) == (
        "{'unexpected': 'value'}"
    )
    assert familiar_agent.public_trace_text("x" * 300, max_chars=12) == "x" * 12


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
        research_plan_id=None,
        requirement_id=None,
        purpose=None,
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


def test_execute_tool_passes_requirement_constraint_to_search_library(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    thread = chat_service.chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="orc stats",
        idempotency_key="send-agent-constraint",
        provider="openai",
        model="gpt-5.4-mini",
    )
    resolved = context_resolution.resolve_research_request(
        "orc stats",
        active_context=None,
    )
    conversation = conversation_context.ConversationContext(
        prompt_messages=(),
        retrieval_query="orc stats",
        history_message_ids=(),
        history_turn_count=0,
        history_strategy="none",
    )
    tool_call = research.FamiliarToolCall(
        id="tool-call-constraint",
        research_run_id="research-constraint",
        research_plan_id=None,
        requirement_id="orc_stats",
        purpose=None,
        step_number=1,
        call_index=0,
        provider_call_id=None,
        tool_name="search_library",
        arguments={"query": "orc stats", "intent": "statline_lookup"},
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
    requirement = agent_planning.EvidenceRequirement(
        id="orc_stats",
        requirement_type="statline_evidence",
        subject=agent_planning.SubjectConstraint(
            canonical="Orc",
            surface="orc",
            book_title_hints=("Old World Bestiary",),
            page_hints=("104",),
        ),
        required_terms=("WS", "BS", "S", "T"),
        object_type_hints=("stat_block",),
        min_accepted_hits=1,
        required=True,
    )
    expected = research_tools.SearchLibraryResult(
        retrieval_run_id="retrieval-constraint",
        query="orc stats",
        source_set_id="rules-core",
        source_book_ids=("bestiary",),
        hits=(),
        diagnostics=diagnostics(),
    )

    def fake_search_library(**kwargs):
        constraint = kwargs["requirement_constraint"]
        assert constraint.requirement_id == "orc_stats"
        assert constraint.subject_terms == ("orc",)
        assert constraint.object_type_hints == ("stat_block",)
        assert constraint.book_title_hints == ("Old World Bestiary",)
        assert constraint.page_hints == ("104",)
        return expected

    monkeypatch.setattr(research_tools, "search_library", fake_search_library)
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
        tool_name="search_library",
        arguments={"query": "orc stats", "intent": "statline_lookup"},
        conversation=conversation,
        requirement=requirement,
    )

    assert dispatched == expected


def test_execute_tool_and_validate_uses_compatibility_validation(
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
        idempotency_key="send-agent-compat-validation",
        provider="openai",
        model="gpt-5.4-mini",
    )
    research_run = chat_store.create_familiar_research_run(
        config,
        model_run_id=queued.model_run.id,
        raw_query="harpy statline",
        resolved_query="harpy statline",
        intent="statline_lookup",
        max_tool_rounds=4,
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
    result = chat_store.SendChatResult(
        thread=thread,
        user_message=queued.user_message,
        assistant_message=None,
        model_run=queued.model_run,
        citations=(),
    )

    def fake_search_library(**kwargs):
        retrieval_run_id = chat_store.record_retrieval_run(
            config,
            thread_id=kwargs["thread_id"],
            message_id=kwargs["message_id"],
            source_set_id="rules-core",
            query=kwargs["query"],
            hits=(hit(rank=1, subject="harpy"),),
            source_book_ids=("bestiary",),
            diagnostics=diagnostics(),
        )
        return research_tools.SearchLibraryResult(
            retrieval_run_id=retrieval_run_id,
            query=kwargs["query"],
            source_set_id="rules-core",
            source_book_ids=("bestiary",),
            hits=(hit(rank=1, subject="harpy"),),
            diagnostics=diagnostics(),
        )

    monkeypatch.setattr(research_tools, "search_library", fake_search_library)

    outcome = familiar_agent.execute_tool_and_validate(
        config,
        research_run=research_run,
        result=result,
        resolved=resolved,
        step_number=1,
        call_index=0,
        provider_call_id="call-compat",
        tool_name="search_library",
        arguments={
            "query": "harpy statline",
            "intent": "statline_lookup",
            "subject": "harpy",
            "limit": 8,
        },
        conversation=conversation,
    )

    assert outcome.validation.status == "sufficient"


def test_requirement_validation_outcome_deduplicates_accepted_hits() -> None:
    accepted_hits_by_requirement: dict[str, list[RetrievedHit]] = {"r1": []}
    partial_hits_by_requirement: dict[str, list[RetrievedHit]] = {"r1": []}
    accepted_hit = hit(
        rank=1,
        subject="orc",
        source_object_id="bestiary:orc-statline",
    )
    validation = evidence_validation.EvidenceValidationResult(
        status="sufficient",
        judgments=(),
        accepted_hits=(accepted_hit, accepted_hit),
    )

    familiar_agent.record_requirement_validation_outcome(
        accepted_hits_by_requirement,
        partial_hits_by_requirement,
        "r1",
        validation,
    )
    familiar_agent.record_requirement_validation_outcome(
        accepted_hits_by_requirement,
        partial_hits_by_requirement,
        "r1",
        validation,
    )

    assert accepted_hits_by_requirement["r1"] == [accepted_hit]


def test_accepted_evidence_retrieval_run_deduplicates_hits_before_persisting(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_bestiary(config)
    thread = chat_service.chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="orc stats",
        idempotency_key="send-agent-accepted-evidence-dedupe",
        provider="openai",
        model="gpt-5.4-mini",
    )
    research_run = chat_store.create_familiar_research_run(
        config,
        model_run_id=queued.model_run.id,
        raw_query="orc stats",
        resolved_query="orc statline",
        intent="statline_lookup",
        max_tool_rounds=4,
    )
    result = chat_store.SendChatResult(
        thread=thread,
        user_message=queued.user_message,
        assistant_message=None,
        model_run=queued.model_run,
        citations=(),
    )

    retrieval_run_id = familiar_agent.record_accepted_evidence_retrieval_run(
        config,
        result=result,
        research_run=research_run,
        query="orc statline",
        accepted_hits=(hit(rank=1, subject="orc"), hit(rank=2, subject="orc")),
        diagnostics=diagnostics("sufficient"),
        evidence_status="sufficient",
    )

    with open_connection(config.db_path) as connection:
        persisted_hits = connection.execute(
            """
            select page_id, rank
            from retrieval_hits
            where retrieval_run_id = ?
            """,
            (retrieval_run_id,),
        ).fetchall()
        metadata = json.loads(
            connection.execute(
                "select metadata_json from retrieval_runs where id = ?",
                (retrieval_run_id,),
            ).fetchone()["metadata_json"]
        )

    assert [tuple(row) for row in persisted_hits] == [("bestiary:101", 1)]
    assert metadata["selected_count"] == 1
