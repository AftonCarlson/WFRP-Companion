from __future__ import annotations

from wfrp_companion.assistant import research


def test_research_json_helpers_are_deterministic_and_safe() -> None:
    assert research.normalized_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'
    assert research.normalized_json_hash({"a": 1}) == research.normalized_json_hash(
        {"a": 1}
    )
    assert research.object_from_json(None) == {}
    assert research.object_from_json("") == {}
    assert research.object_from_json("{bad json") == {}
    assert research.object_from_json("[]") == {}
    assert research.object_from_json('{"ok": true}') == {"ok": True}
    assert research.string_tuple_from_json(None) == ()
    assert research.string_tuple_from_json("") == ()
    assert research.string_tuple_from_json("{bad json") == ()
    assert research.string_tuple_from_json("{}") == ()
    assert research.string_tuple_from_json('["a", 1, "b"]') == ("a", "b")


def test_research_contracts_hold_agent_context_and_diagnostics() -> None:
    reader_context = research.ReaderContext(
        active_book_id="core-rules",
        active_pdf_page_number=101,
        active_printed_page_label="99",
        open_book_ids=("core-rules", "bestiary"),
    )
    diagnostics = research.RetrievalDiagnostics(
        channel_counts={"page_fts": 2, "vector": 1},
        channel_skip_reasons={},
        vector_status="ran",
        candidate_count_before_fusion=3,
        candidate_count_after_fusion=2,
        reranked_count=2,
        selected_count=1,
        page_lookup_attempted=True,
        validation_status="sufficient",
    )

    assert reader_context.open_book_ids == ("core-rules", "bestiary")
    assert diagnostics.channel_counts["vector"] == 1
    assert diagnostics.page_lookup_attempted is True
