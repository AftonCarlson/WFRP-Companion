from __future__ import annotations

import pytest

from wfrp_companion.assistant import prompts
from wfrp_companion.assistant.retrieval import RetrievedHit, SourceMapEntry


def test_build_prompt_requires_citations_and_insufficient_context_honesty() -> None:
    messages = prompts.build_prompt_messages(
        question="How do critical hits work?",
        hits=(
            RetrievedHit(
                book_id="core-rules",
                title="Core Rules",
                category="Core Book & GM Essentials",
                page_id="core-rules:1",
                page_number=1,
                pdf_page_number=1,
                page_label=None,
                snippet="[Critical] hit rules",
                score=-1.2,
                rank=1,
                context_text="Critical hit rules explain the table result.",
            ),
        ),
        recent_messages=(),
    )

    system_text = messages[0].content
    user_text = messages[-1].content

    assert "Cite book and page" in system_text
    assert "insufficient" in system_text.lower()
    assert "Use chat history only to understand conversational references" in system_text
    assert "Do not treat chat history as retrieved rules" in system_text
    assert "Core Rules p. 1" in user_text
    assert "Critical hit rules explain" in user_text


def test_system_prompt_describes_tool_calling_agent_contract() -> None:
    system_text = prompts.SYSTEM_INSTRUCTIONS

    assert "bounded research agent" in system_text
    assert "local app owns source scope" in system_text
    assert "accepted retrieved evidence" in system_text
    assert "Do not answer factual WFRP claims from memory" in system_text
    assert "Reader context can guide tool use" in system_text
    assert "Do not dump long copyrighted passages" in system_text


def test_build_research_prompt_names_tools_and_active_context() -> None:
    messages = prompts.build_research_prompt_messages(
        raw_query="I want the stats",
        resolved_query="harpy statline",
        intent="statline_lookup",
        subject="harpy",
        active_book_id="bestiary",
        active_printed_page_label="99",
        recent_messages=(),
    )

    assert messages[0].role == "system"
    assert messages[-1].role == "user"
    assert "search_library" in messages[-1].content
    assert "open_page" in messages[-1].content
    assert "lookup_source_object" in messages[-1].content
    assert "Active book: bestiary" in messages[-1].content
    assert "Active printed page: 99" in messages[-1].content
    assert "Accepted research plan:" in messages[-1].content
    assert "Requirements: none recorded" in messages[-1].content


def test_build_research_prompt_includes_requirement_status_ledger() -> None:
    messages = prompts.build_research_prompt_messages(
        raw_query="compare them",
        resolved_query="compare harpy and gor statlines",
        intent="statline_lookup",
        subject=None,
        active_book_id=None,
        active_printed_page_label=None,
        recent_messages=(),
        plan_summary="/Users/aftoncarlson/private/notes.pdf find both statlines",
        requirement_summaries=(
            {
                "id": "harpy_stats",
                "requirement_type": "statline_evidence",
                "status": "satisfied",
                "accepted_hit_count": 1,
                "partial_hit_count": 0,
                "min_accepted_hits": 1,
                "required": True,
                "subject": {
                    "canonical": "harpy",
                    "surface": "Harpy",
                    "include_terms": ["harpy"],
                    "exclude_terms": ["rat ogre"],
                    "book_title_hints": ["Old World Bestiary.pdf"],
                    "page_hints": ["99"],
                },
                "required_terms": ["harpy", "statistics"],
                "excluded_terms": ["rat ogre"],
                "object_type_hints": ["stat_block"],
            },
            {
                "id": "gor_stats",
                "requirement_type": "statline_evidence",
                "status": "unsatisfied",
                "accepted_hit_count": 0,
                "partial_hit_count": 0,
                "min_accepted_hits": 1,
                "required": True,
                "subject": {
                    "canonical": "gor",
                    "surface": "Gor",
                    "include_terms": ["gor"],
                    "exclude_terms": [],
                    "book_title_hints": [],
                    "page_hints": [],
                },
                "required_terms": ["gor", "statistics"],
                "excluded_terms": [],
                "object_type_hints": ["stat_block"],
            },
        ),
    )

    user_text = messages[-1].content

    assert "Plan summary: [local path removed] find both statlines" in user_text
    assert "harpy_stats (statline_evidence): satisfied; accepted 1/1" in user_text
    assert "subject: harpy" in user_text
    assert "include: harpy" in user_text
    assert "exclude: rat ogre" in user_text
    assert "required_terms: harpy, statistics" in user_text
    assert "object_types: stat_block" in user_text
    assert "book_hints: [pdf filename removed]" in user_text
    assert "gor_stats (statline_evidence): unsatisfied; accepted 0/1" in user_text
    assert "/Users/" not in user_text
    assert ".pdf" not in user_text


def test_research_plan_status_helpers_cover_non_sequence_and_truncation() -> None:
    assert prompts.safe_summary_list("harpy") == "none"
    assert prompts.safe_summary_list({"ignored": "mapping"}) == "none"
    assert prompts.safe_summary_value("x" * 120, max_chars=12) == "x" * 12


def test_build_research_planning_prompt_keeps_resolved_hint_on_one_line() -> None:
    messages = prompts.build_research_planning_prompt_messages(
        raw_query="What about it?",
        resolved_query=(
            "What about it?\n\n"
            "Recent chat terms for reference resolution: critical hits table"
        ),
        intent="rules_lookup",
        subject=None,
        active_book_id=None,
        active_printed_page_label=None,
        recent_messages=(),
    )

    user_text = messages[-1].content

    assert (
        "Resolved query hint: What about it? Recent chat terms for "
        "reference resolution: critical hits table"
    ) in user_text
    assert "\nRecent chat terms for reference resolution" not in user_text


def test_build_research_prompt_includes_scrubbed_prior_tool_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = prompts.build_research_prompt_messages(
        raw_query="I want the stats",
        resolved_query="harpy statline",
        intent="statline_lookup",
        subject="harpy",
        active_book_id="bestiary",
        active_printed_page_label="99",
        recent_messages=(),
        prior_tool_outputs=(
            {
                "query": "/Users/aftoncarlson/private.pdf",
                "hit_count": 0,
                "validation": {"status": "insufficient"},
            },
        ),
    )

    user_text = messages[-1].content

    assert "Prior local tool results:" in user_text
    assert '"hit_count": 0' in user_text
    assert "[local path removed]" in user_text
    assert "private.pdf" not in user_text
    assert prompts.build_prior_tool_outputs_block(
        ({"long": "x" * 30},),
        max_chars=12,
    ).startswith("[1] {")
    assert prompts.build_prior_tool_outputs_block(
        ({"ignored": "x"},),
        max_chars=0,
    ) == ""
    monkeypatch.setattr(prompts, "scrub_private_paths", lambda _text: "")
    assert prompts.build_prior_tool_outputs_block(({"blank": "after scrub"},)) == ""


def test_build_final_answer_prompt_uses_only_accepted_evidence() -> None:
    accepted = RetrievedHit(
        book_id="bestiary",
        title="Old World Bestiary",
        category="Rules and Mechanics Toolkits",
        page_id="bestiary:101",
        page_number=101,
        pdf_page_number=101,
        page_label="99",
        snippet="Harpy stat_block",
        score=1,
        rank=1,
        context_text="Synthetic Harpy stat_block: M 4 WS 31.",
        object_title="Harpy",
        object_type="stat_block",
        page_range_label="99",
    )

    messages = prompts.build_final_answer_prompt_messages(
        question="harpy statline",
        accepted_hits=(accepted,),
        evidence_status="sufficient",
        plan_summary="Find cited Harpy statline evidence.",
        requirement_summaries=(
            {
                "id": "harpy_stats",
                "requirement_type": "statline_evidence",
                "status": "satisfied",
            },
        ),
        answer_policy="cite_required",
        answer_outcome="full_answer",
        recent_messages=(),
    )

    user_text = messages[-1].content
    assert "Public plan: Find cited Harpy statline evidence." in user_text
    assert "Answer policy: cite_required" in user_text
    assert "Answer outcome: full_answer" in user_text
    assert "- harpy_stats (statline_evidence): satisfied" in user_text
    assert "Accepted evidence:" in user_text
    assert "Synthetic Harpy stat_block" in user_text
    assert "Answer only from accepted evidence" in user_text


def test_build_final_answer_prompt_for_insufficient_evidence() -> None:
    messages = prompts.build_final_answer_prompt_messages(
        question="harpy statline",
        accepted_hits=(),
        evidence_status="insufficient",
        recent_messages=(),
    )

    user_text = messages[-1].content
    assert "No accepted evidence was found" in user_text
    assert "do not reconstruct the WFRP facts from memory" in user_text


def test_build_final_answer_prompt_for_partial_answer_names_missing_parts() -> None:
    accepted = RetrievedHit(
        book_id="core-rules",
        title="Core Rules",
        category="Core Book & GM Essentials",
        page_id="core-rules:130",
        page_number=130,
        pdf_page_number=130,
        page_label="130",
        snippet="Hit Location",
        score=1,
        rank=1,
        context_text="Hit Location table.",
        object_title="Hit Location",
        object_type="table",
        page_range_label="130",
    )

    messages = prompts.build_final_answer_prompt_messages(
        question="hit location and armor per location",
        accepted_hits=(accepted,),
        evidence_status="partial",
        plan_summary="Find hit-location and armor-by-location evidence.",
        requirement_summaries=(
            {
                "id": "hit_location_rule",
                "requirement_type": "topical_evidence",
                "status": "satisfied",
            },
            {
                "id": "armor_location_rule",
                "requirement_type": "topical_evidence",
                "status": "unsatisfied",
            },
        ),
        answer_policy="cite_required",
        answer_outcome="partial_answer",
        missing_summaries=("Need accepted evidence for armor location.",),
        recent_messages=(),
    )

    user_text = messages[-1].content
    assert "Answer outcome: partial_answer" in user_text
    assert "Need accepted evidence for armor location." in user_text
    assert "Do not answer unsatisfied requirements" in user_text


def test_build_prompt_includes_recent_messages_before_current_user_prompt() -> None:
    recent_messages = (
        prompts.PromptMessage(role="user", content="Tell me about Captain Alder."),
        prompts.PromptMessage(role="assistant", content="Captain Alder wears mail."),
    )

    messages = prompts.build_prompt_messages(
        question="What about his armor?",
        hits=(),
        recent_messages=recent_messages,
    )

    assert [message.role for message in messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert messages[1:3] == recent_messages
    assert messages[-1].content.startswith("Question:\nWhat about his armor?")


def test_build_prompt_includes_enabled_source_map_and_section_ranges() -> None:
    messages = prompts.build_prompt_messages(
        question="How do critical hits continue?",
        hits=(
            RetrievedHit(
                book_id="core-rules",
                title="Core Rules",
                category="Core Book & GM Essentials",
                page_id="core-rules:1",
                page_number=1,
                pdf_page_number=1,
                page_label="10",
                snippet="Critical hits",
                score=4.2,
                rank=1,
                context_text="Critical hits continue onto the next page.",
                source_object_id="core-rules:critical-hits",
                object_type="rule_section",
                object_title="Critical Hits",
                heading_path=("Chapter I: Combat", "Critical Hits"),
                page_start=1,
                page_end=2,
                page_range_label="10-11",
                confidence=0.91,
                rank_reasons=("source_object:rule_section", "semantic_overlap:critical"),
                text_snapshot_sha256="sha-critical",
            ),
        ),
        source_map=(
            SourceMapEntry(
                book_id="core-rules",
                title="Core Rules",
                category="Core Book & GM Essentials",
                summary="Core WFRP rules and combat references.",
                aliases=("critical", "combat"),
                best_source_for=("rules_lookup",),
                chapters=("Chapter I: Combat",),
            ),
        ),
        recent_messages=(),
    )

    user_text = messages[-1].content

    assert "Enabled source map:" in user_text
    assert "Core Rules - Core WFRP rules and combat references." in user_text
    assert "[1] Core Rules, Critical Hits, printed pages 10-11" in user_text
    assert "PDF page" not in user_text


def test_build_prompt_does_not_include_local_paths_or_unbounded_context() -> None:
    messages = prompts.build_prompt_messages(
        question="What is here?",
        hits=(
            RetrievedHit(
                book_id="core-rules",
                title="Core Rules",
                category="Core Book & GM Essentials",
                page_id="core-rules:1",
                page_number=1,
                pdf_page_number=1,
                page_label=None,
                snippet="snippet",
                score=0,
                rank=1,
                context_text="/Users/aftoncarlson/secret.pdf " + ("x" * 300),
            ),
        ),
        recent_messages=(),
        context_char_limit=80,
    )

    combined = "\n".join(message.content for message in messages)

    assert "/Users/" not in combined
    assert "secret.pdf" not in combined
    assert "x" * 120 not in combined


def test_build_context_block_stops_at_context_limit_and_skips_empty_hits() -> None:
    block = prompts.build_context_block(
        (
            RetrievedHit(
                book_id="empty",
                title="Empty",
                category="Core",
                page_id="empty:1",
                page_number=1,
                pdf_page_number=1,
                page_label=None,
                snippet="",
                score=0,
                rank=1,
                context_text="",
            ),
            RetrievedHit(
                book_id="core-rules",
                title="Core Rules",
                category="Core Book & GM Essentials",
                page_id="core-rules:1",
                page_number=1,
                pdf_page_number=1,
                page_label=None,
                snippet="snippet",
                score=0,
                rank=2,
                context_text="Critical hit rules.",
            ),
            RetrievedHit(
                book_id="barony",
                title="Barony",
                category="Adventure",
                page_id="barony:1",
                page_number=1,
                pdf_page_number=1,
                page_label=None,
                snippet="snippet",
                score=0,
                rank=3,
                context_text="This should not fit.",
            ),
        ),
        context_char_limit=18,
    )

    assert "Empty p. 1" not in block
    assert "Core Rules p. 1" in block
    assert "Barony" not in block


def test_page_labels_use_single_range_or_distinct_printed_label() -> None:
    single_range = RetrievedHit(
        book_id="core-rules",
        title="Core Rules",
        category="Core",
        page_id="core-rules:10",
        page_number=10,
        pdf_page_number=10,
        page_label="9",
        snippet="snippet",
        score=1,
        rank=1,
        context_text="text",
        page_start=10,
        page_end=10,
        page_range_label="9",
    )
    distinct_label = RetrievedHit(
        book_id="core-rules",
        title="Core Rules",
        category="Core",
        page_id="core-rules:11",
        page_number=11,
        pdf_page_number=11,
        page_label="10",
        snippet="snippet",
        score=1,
        rank=2,
        context_text="text",
    )

    assert prompts.page_label(single_range) == "printed page 9"
    assert prompts.page_label(distinct_label) == "printed page 10"
