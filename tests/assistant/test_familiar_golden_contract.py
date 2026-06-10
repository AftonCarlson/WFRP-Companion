from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from wfrp_companion.assistant import chat_service
from wfrp_companion.assistant import chat_store
from wfrp_companion.assistant import provider
from wfrp_companion.assistant import research
from wfrp_companion.assistant import research_tools
from wfrp_companion.assistant.evidence import RetrievedHit
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database, open_connection
from wfrp_companion.library import source_sets


class NoPlanThenFinalProvider:
    def __init__(self) -> None:
        self.final_messages: tuple[provider.ProviderMessage, ...] = ()

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
        if tools:
            yield provider.ProviderStreamEvent(type="completed")
            return
        self.final_messages = tuple(messages)
        yield provider.ProviderStreamEvent(type="delta", text_delta="Partial answer.")
        yield provider.ProviderStreamEvent(type="completed")


class NarrowPlanThenFinalProvider:
    def __init__(self) -> None:
        self.final_messages: tuple[provider.ProviderMessage, ...] = ()

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
        if tools:
            yield provider.ProviderStreamEvent(
                type="tool_call",
                tool_name="set_research_plan",
                tool_call_id="call-narrow-plan",
                tool_arguments_json=json.dumps(
                    {
                        "intent": "rules_lookup",
                        "plan_summary": "Find hit-location evidence only.",
                        "subject": {
                            "canonical": "hit location determination in combat",
                            "surface": "hit location determination in combat",
                            "include_terms": ["hit location determination in combat"],
                            "exclude_terms": [],
                            "book_title_hints": [],
                            "page_hints": [],
                            "notes": None,
                        },
                        "requirements": [
                            {
                                "id": "provider_hit_location_only",
                                "requirement_type": "topical_evidence",
                                "subject": {
                                    "canonical": "hit location determination in combat",
                                    "surface": "hit location determination in combat",
                                    "include_terms": [
                                        "hit location determination in combat"
                                    ],
                                    "exclude_terms": [],
                                    "book_title_hints": [],
                                    "page_hints": [],
                                    "notes": None,
                                },
                                "required_terms": [
                                    "hit location determination in combat"
                                ],
                                "excluded_terms": [],
                                "object_type_hints": ["table"],
                                "min_accepted_hits": 1,
                                "required": True,
                            }
                        ],
                        "planned_actions": [
                            {
                                "tool_name": "search_library",
                                "requirement_id": "provider_hit_location_only",
                                "purpose": "Search only for hit location.",
                                "arguments": {
                                    "requirement_id": "provider_hit_location_only",
                                    "query": "hit location determination in combat",
                                    "intent": "rules_lookup",
                                    "subject": "hit location determination in combat",
                                    "limit": 8,
                                },
                            }
                        ],
                    }
                ),
            )
            yield provider.ProviderStreamEvent(type="completed")
            return
        self.final_messages = tuple(messages)
        yield provider.ProviderStreamEvent(type="delta", text_delta="Partial answer.")
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


def seed_book(config: AppConfig) -> None:
    with initialize_database(config.db_path) as connection:
        connection.execute(
            """
            insert into library_folders (id, parent_id, name, relative_path, sort_order)
            values ('core', null, 'Core', 'Core', 0)
            """
        )
        connection.execute(
            """
            insert into books (
              id, folder_id, title, category, relative_path, original_source_path,
              managed_pdf_path, original_sha256, managed_sha256, page_count,
              copy_status, text_status, search_status, visual_status, discovered_at,
              updated_at
            )
            values ('core-rules', 'core', 'Core Rules', 'Core', 'core.pdf',
                    '/source/core.pdf', '/managed/core.pdf', 'source-sha',
                    'managed-sha', 260, 'copied', 'imported', 'indexed',
                    'not_scanned', '2026-06-09T00:00:00Z',
                    '2026-06-09T00:00:00Z')
            """
        )
        connection.execute(
            """
            insert into pages (
              id, book_id, page_number, page_label, extraction_method,
              embedded_text_chars, text_chars, word_count, image_count,
              ocr_attempted, has_text
            )
            values ('core-rules:130', 'core-rules', 130, '130', 'ocr',
                    0, 40, 6, 0, 1, 1)
            """
        )
    source_sets.ensure_builtin_source_sets(config)


def hit_location_hit() -> RetrievedHit:
    return RetrievedHit(
        book_id="core-rules",
        title="Core Rules",
        category="Core",
        page_id="core-rules:130",
        page_number=130,
        pdf_page_number=130,
        page_label="130",
        snippet="Hit Location",
        score=1.0,
        rank=1,
        context_text="Hit Location table.",
        source_object_id=None,
        object_type="table",
        object_title="Hit Location",
        page_start=130,
        page_end=130,
        page_range_label="130",
    )


def empty_result(
    config: AppConfig,
    *,
    thread_id: str,
    message_id: str,
    query: str,
    tool_call_id: str,
    attempt_number: int,
) -> research_tools.SearchLibraryResult:
    retrieval_run_id = chat_store.record_retrieval_run(
        config,
        thread_id=thread_id,
        message_id=message_id,
        source_set_id="rules-core",
        query=query,
        hits=(),
        source_book_ids=("core-rules",),
        diagnostics=diagnostics("insufficient"),
        tool_call_id=tool_call_id,
        attempt_number=attempt_number,
        intent="rules_lookup",
        resolved_query=query,
        tool_name="search_library",
    )
    return research_tools.SearchLibraryResult(
        retrieval_run_id=retrieval_run_id,
        query=query,
        source_set_id="rules-core",
        source_book_ids=("core-rules",),
        hits=(),
        diagnostics=diagnostics("insufficient"),
    )


def diagnostics(status: str) -> research.RetrievalDiagnostics:
    return research.RetrievalDiagnostics(
        channel_counts={
            "page_fts": 0,
            "source_object_fts": 1,
            "source_object_scan": 0,
            "vector": 0,
            "page_lookup": 0,
            "table_stat_lookup": 0,
        },
        channel_skip_reasons={"vector": "disabled"},
        vector_status="disabled",
        candidate_count_before_fusion=1,
        candidate_count_after_fusion=1,
        reranked_count=1,
        selected_count=1,
        page_lookup_attempted=False,
        validation_status=status,  # type: ignore[arg-type]
    )


def test_multi_part_rules_query_attempts_each_requirement_and_prompts_partial(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_book(config)
    provider_instance = NarrowPlanThenFinalProvider()
    queries: list[str] = []

    def fake_search_library(**kwargs):
        query = kwargs["query"]
        queries.append(query)
        if query.startswith("hit location"):
            accepted = hit_location_hit()
            retrieval_run_id = chat_store.record_retrieval_run(
                config,
                thread_id=kwargs["thread_id"],
                message_id=kwargs["message_id"],
                source_set_id="rules-core",
                query=query,
                hits=(accepted,),
                source_book_ids=("core-rules",),
                diagnostics=diagnostics("sufficient"),
                tool_call_id=kwargs["tool_call_id"],
                attempt_number=kwargs["attempt_number"],
                intent=kwargs["intent"],
                resolved_query=query,
                tool_name="search_library",
            )
            return research_tools.SearchLibraryResult(
                retrieval_run_id=retrieval_run_id,
                query=query,
                source_set_id="rules-core",
                source_book_ids=("core-rules",),
                hits=(accepted,),
                diagnostics=diagnostics("sufficient"),
            )
        return empty_result(
            config,
            thread_id=kwargs["thread_id"],
            message_id=kwargs["message_id"],
            query=query,
            tool_call_id=kwargs["tool_call_id"],
            attempt_number=kwargs["attempt_number"],
        )

    monkeypatch.setattr(research_tools, "search_library", fake_search_library)
    thread = chat_service.chat_store.create_thread(config)

    events = tuple(
        chat_service.stream_chat_message(
            config,
            thread_id=thread.id,
            content="what are the rules on hit location and armor per location in combat",
            idempotency_key="send-golden-contract",
            provider_factory=lambda _: provider_instance,
        )
    )

    assert queries == [
        "hit location combat table body location",
        "armor location armour points body combat",
    ]
    assert events[-1].assistant_message is not None
    assert events[-1].citations[0].title == "Core Rules"
    final_prompt = provider_instance.final_messages[-1].content
    assert "Answer outcome: partial_answer" in final_prompt
    assert "Need accepted evidence for armor location." in final_prompt
    with open_connection(config.db_path) as connection:
        row = connection.execute(
            """
            select answer_outcome, outcome_json
            from familiar_turn_decisions
            """
        ).fetchone()
        plan = connection.execute(
            """
            select requirements_json, provider_call_id
            from familiar_research_plans
            """
        ).fetchone()
    outcome = json.loads(row["outcome_json"])
    requirements = json.loads(plan["requirements_json"])
    assert row["answer_outcome"] == "partial_answer"
    assert outcome["kind"] == "partial_answer"
    assert [requirement["id"] for requirement in requirements] == [
        "hit_location_rule",
        "armor_location_rule",
    ]
    assert plan["provider_call_id"] == "call-narrow-plan"
