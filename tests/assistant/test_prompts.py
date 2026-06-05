from __future__ import annotations

from wfrp_companion.assistant import prompts
from wfrp_companion.assistant.retrieval import RetrievedHit


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
    assert "Core Rules p. 1" in user_text
    assert "Critical hit rules explain" in user_text


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
    assert len(combined) < 700


def test_build_context_block_stops_at_context_limit_and_skips_empty_hits() -> None:
    block = prompts.build_context_block(
        (
            RetrievedHit(
                book_id="empty",
                title="Empty",
                category="Core",
                page_id="empty:1",
                page_number=1,
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
