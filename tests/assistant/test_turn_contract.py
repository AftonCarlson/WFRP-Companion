from __future__ import annotations

from wfrp_companion.assistant import turn_contract


def test_greeting_is_direct_conversation_with_ignored_reader_context() -> None:
    decision = turn_contract.classify_turn("hello")

    assert decision.turn_kind == "conversation"
    assert decision.answer_mode == "direct"
    assert decision.subject is None
    assert decision.confidence == "high"
    assert decision.reader_context_policy == "ignore"
    assert "greeting_or_social_text" in decision.reasons


def test_app_help_is_direct_without_research() -> None:
    decision = turn_contract.classify_turn("what can you do?")

    assert decision.turn_kind == "app_help"
    assert decision.answer_mode == "direct"
    assert decision.reader_context_policy == "ignore"


def test_rules_lookup_uses_research_mode() -> None:
    decision = turn_contract.classify_turn("what are the rules for hit location?")

    assert decision.turn_kind == "rules_lookup"
    assert decision.answer_mode == "research"
    assert decision.subject == "what are the rules for hit location?"
    assert decision.reader_context_policy == "routing_hint"


def test_ambiguous_frustration_clarifies_instead_of_researching() -> None:
    decision = turn_contract.classify_turn("why are you doing that")

    assert decision.turn_kind == "clarification_needed"
    assert decision.answer_mode == "clarify"
    assert decision.subject is None
    assert decision.reader_context_policy == "ignore"


def test_empty_and_unknown_turns_clarify_without_reader_context() -> None:
    empty = turn_contract.classify_turn("   ")
    unknown = turn_contract.classify_turn("about")

    assert empty.turn_kind == "clarification_needed"
    assert empty.confidence == "high"
    assert empty.reasons == ("empty_message",)
    assert unknown.turn_kind == "clarification_needed"
    assert unknown.confidence == "low"
    assert unknown.reasons == ("low_confidence_unknown_turn",)
    assert not turn_contract.has_lore_signal("about")


def test_normal_questions_containing_no_substring_still_research() -> None:
    armor = turn_contract.classify_turn("what do I need to know about armor?")
    mutations = turn_contract.classify_turn("what are known mutations?")
    no_armor = turn_contract.classify_turn("what happens if I have no armor?")

    assert armor.turn_kind == "rules_lookup"
    assert armor.answer_mode == "research"
    assert mutations.turn_kind == "rules_lookup"
    assert mutations.answer_mode == "research"
    assert no_armor.turn_kind == "rules_lookup"
    assert no_armor.answer_mode == "research"
    assert turn_contract.has_frustration_signal("stop")
    assert turn_contract.has_frustration_signal("no, that is wrong")
    assert not turn_contract.has_frustration_signal("no armor")
    assert not turn_contract.has_frustration_signal("known armor")


def test_acknowledgment_is_direct_thanks_turn() -> None:
    decision = turn_contract.classify_turn("thanks")

    assert decision.turn_kind == "conversation"
    assert decision.answer_mode == "direct"
    assert decision.subject == "thanks"
    assert decision.reasons == ("acknowledgment_text",)


def test_followup_contextualized_query_can_route_research() -> None:
    decision = turn_contract.classify_turn(
        "what about that",
        contextualized_query="orc statline",
        history_strategy="followup_contextualized",
    )

    assert decision.turn_kind == "statline_lookup"
    assert decision.answer_mode == "research"
