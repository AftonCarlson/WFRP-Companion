from __future__ import annotations

from wfrp_companion.assistant import context_resolution
from wfrp_companion.assistant import research


def active_context() -> research.ChatThreadContext:
    return research.ChatThreadContext(
        thread_id="thread-1",
        active_subject="harpy",
        active_intent="statline_lookup",
        active_book_id="bestiary",
        active_printed_page_label="99",
        active_pdf_page_number=101,
        active_source_object_id="harpy-stat",
        updated_from_message_id="message-1",
        updated_from_model_run_id="run-1",
        metadata={},
        updated_at="2026-06-09T00:00:00Z",
    )


def test_resolve_short_stat_followup_uses_active_subject() -> None:
    for query in (
        "I want the stats",
        "give me the stats",
        "give me their stats",
        "give me there stats",
        "their stats",
        "there stats",
    ):
        resolved = context_resolution.resolve_research_request(
            query,
            active_context=active_context(),
        )

        assert resolved.subject == "harpy"
        assert resolved.intent == "statline_lookup"
        assert resolved.resolved_query == "harpy statline"
        assert resolved.used_active_subject is True
        assert resolved.page_reference is None


def test_resolve_same_for_replaces_subject_and_preserves_intent() -> None:
    resolved = context_resolution.resolve_research_request(
        "same for gors",
        active_context=active_context(),
    )

    assert resolved.subject == "gors"
    assert resolved.intent == "statline_lookup"
    assert resolved.resolved_query == "gors statline"
    assert resolved.used_active_subject is False


def test_resolve_page_reference_preserves_subject_book_and_intent() -> None:
    resolved = context_resolution.resolve_research_request(
        "it's on pg 99",
        active_context=active_context(),
    )

    assert resolved.subject == "harpy"
    assert resolved.intent == "statline_lookup"
    assert resolved.active_book_id == "bestiary"
    assert resolved.page_reference is not None
    assert resolved.page_reference.printed_page_label == "99"
    assert resolved.page_reference.same_page is False
    assert resolved.resolved_query == "harpy statline page 99"


def test_resolve_same_page_uses_active_page_context() -> None:
    resolved = context_resolution.resolve_research_request(
        "same page",
        active_context=active_context(),
    )

    assert resolved.page_reference is not None
    assert resolved.page_reference.same_page is True
    assert resolved.page_reference.printed_page_label == "99"
    assert resolved.page_reference.pdf_page_number == 101


def test_resolve_self_contained_statline_query() -> None:
    resolved = context_resolution.resolve_research_request(
        "harpy stat line",
        active_context=None,
    )

    assert resolved.subject == "harpy"
    assert resolved.intent == "statline_lookup"
    assert resolved.resolved_query == "harpy statline"


def test_resolve_statline_for_subject_and_generic_queries() -> None:
    statline_for = context_resolution.resolve_research_request(
        "statline for the gors",
        active_context=None,
    )
    topical = context_resolution.resolve_research_request(
        "where is Castle Wittgenstein",
        active_context=None,
    )
    statline_only = context_resolution.resolve_research_request(
        "statline",
        active_context=None,
    )
    fallback = context_resolution.resolve_research_request(
        "what is it",
        active_context=None,
    )

    assert statline_for.subject == "gors"
    assert statline_for.resolved_query == "gors statline"
    assert topical.intent == "rules_lookup"
    assert topical.resolved_query == "castle wittgenstein"
    assert statline_only.subject is None
    assert statline_only.resolved_query == "statline"
    assert fallback.subject is None
    assert fallback.resolved_query == "what is it"


def test_resolve_dungeon_crawl_recommendation_as_broad_research_query() -> None:
    queries = (
        "tell me what the best setting to run a dungeon crawl",
        "recommend a good dungeon-crawl adventure site",
    )
    for query in queries:
        resolved = context_resolution.resolve_research_request(
            query,
            active_context=None,
        )

        assert resolved.intent == "rules_lookup"
        assert resolved.subject is None
        assert (
            resolved.resolved_query
            == "dungeon crawl adventure setting underground ruins sewer mine"
        )


def test_same_page_without_active_context_keeps_query_without_page_label() -> None:
    resolved = context_resolution.resolve_research_request(
        "same page",
        active_context=None,
    )

    assert resolved.page_reference is not None
    assert resolved.page_reference.same_page is True
    assert resolved.page_reference.printed_page_label is None
    assert resolved.resolved_query == "same page"


def test_page_reference_parser_handles_common_spellings() -> None:
    assert context_resolution.parse_page_reference("p. 12").printed_page_label == "12"
    assert context_resolution.parse_page_reference("pg 99").printed_page_label == "99"
    assert context_resolution.parse_page_reference("page 100").printed_page_label == "100"
    assert context_resolution.parse_page_reference("no page here") is None
