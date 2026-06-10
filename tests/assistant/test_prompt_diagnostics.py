from __future__ import annotations

from wfrp_companion.assistant import prompt_diagnostics
from wfrp_companion.assistant import prompts


def test_prompt_surface_summary_hashes_without_exposing_full_content() -> None:
    messages = (
        prompts.PromptMessage(
            role="user",
            content="/Users/aftoncarlson/private/book.pdf\nHidden source text",
        ),
    )

    summary = prompt_diagnostics.prompt_surface_summary(messages)

    assert summary[0].role == "user"
    assert summary[0].char_count == len(messages[0].content)
    assert len(summary[0].sha256) == 64
    assert summary[0].first_line == "[local path removed]"
    assert "Hidden source text" not in summary[0].to_json().values()
