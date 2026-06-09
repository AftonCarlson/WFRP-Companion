from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

from wfrp_companion.assistant.retrieval import RetrievedHit, SourceMapEntry


SYSTEM_INSTRUCTIONS = """You are Familiar, a private local WFRP 2e Game Master aid and bounded tool-calling research agent.
Use only enabled books and accepted retrieved evidence supplied by the local app.
Unchecked books are out of scope even if you know about them. Hybrid retrieval is backend policy: exact/full-text, source-object, vector, page, table, and stat lookup are local tools owned by the app. Do not answer factual WFRP claims from memory.
Cite book and page using printed page labels for factual rules or setting claims. If the accepted evidence is insufficient, say that clearly. Distinguish rules text from GM interpretation. Use chat history only to understand conversational references and user intent. Do not treat chat history as retrieved rules or setting evidence. Do not treat reader context as retrieved rules or setting evidence.
Follow the tool/evidence contract: request local tools when evidence is weak, rely on backend validation, answer only from accepted retrieved evidence, and preserve private/copyright boundaries. Do not dump long copyrighted passages."""


@dataclass(frozen=True)
class PromptMessage:
    role: str
    content: str


def build_prompt_messages(
    *,
    question: str,
    hits: Sequence[RetrievedHit],
    source_map: Sequence[SourceMapEntry] = (),
    recent_messages: Sequence[PromptMessage],
    context_char_limit: int = 9000,
) -> tuple[PromptMessage, ...]:
    context = build_context_block(hits, context_char_limit=context_char_limit)
    source_map_block = build_source_map_block(source_map)
    user_content = f"""Question:
{question}

Enabled source map:
{source_map_block if source_map_block else 'No enabled searchable books were found.'}

Retrieved context:
{context if context else 'No retrieved context was found.'}

Answer concisely with citations to the retrieved evidence."""
    return (
        PromptMessage(role="system", content=SYSTEM_INSTRUCTIONS),
        *recent_messages,
        PromptMessage(role="user", content=user_content),
    )


def build_research_prompt_messages(
    *,
    raw_query: str,
    resolved_query: str,
    intent: str,
    subject: str | None,
    active_book_id: str | None,
    active_printed_page_label: str | None,
    recent_messages: Sequence[PromptMessage],
    prior_tool_outputs: Sequence[dict[str, object]] = (),
) -> tuple[PromptMessage, ...]:
    subject_line = subject if subject else "none"
    book_line = active_book_id if active_book_id else "none"
    page_line = active_printed_page_label if active_printed_page_label else "none"
    prior_tool_block = build_prior_tool_outputs_block(prior_tool_outputs)
    user_content = f"""Research request:
Raw query: {raw_query}
Resolved query: {resolved_query}
Intent: {intent}
Subject: {subject_line}
Active book: {book_line}
Active printed page: {page_line}

Prior local tool results:
{prior_tool_block if prior_tool_block else 'No prior local tool results.'}

Available local tools:
- search_library: run backend-owned hybrid retrieval over enabled books.
- open_page: open a resolved enabled book page by printed label or PDF page.
- lookup_source_object: inspect a retrieved structured source object by id.

If evidence is weak, empty, mismatched, or the user gives a page correction, request the most useful tool. Do not answer factual WFRP claims in this research step."""
    return (
        PromptMessage(role="system", content=SYSTEM_INSTRUCTIONS),
        *recent_messages,
        PromptMessage(role="user", content=user_content),
    )


def build_prior_tool_outputs_block(
    prior_tool_outputs: Sequence[dict[str, object]],
    *,
    max_chars: int = 4000,
) -> str:
    remaining = max_chars
    blocks: list[str] = []
    for index, output in enumerate(prior_tool_outputs, start=1):
        if remaining <= 0:
            break
        serialized = scrub_private_paths(json.dumps(output, sort_keys=True))
        if len(serialized) > remaining:
            serialized = serialized[:remaining].rstrip()
        if not serialized:
            continue
        blocks.append(f"[{index}] {serialized}")
        remaining -= len(serialized)
    return "\n".join(blocks)


def build_final_answer_prompt_messages(
    *,
    question: str,
    accepted_hits: Sequence[RetrievedHit],
    evidence_status: str,
    recent_messages: Sequence[PromptMessage],
    context_char_limit: int = 9000,
) -> tuple[PromptMessage, ...]:
    evidence_block = build_context_block(
        accepted_hits,
        context_char_limit=context_char_limit,
    )
    if evidence_block:
        evidence_section = f"Accepted evidence:\n{evidence_block}"
        instruction = "Answer only from accepted evidence and cite book/page."
    else:
        evidence_section = "No accepted evidence was found."
        instruction = (
            "Explain the insufficiency clearly; do not reconstruct the WFRP facts "
            "from memory."
        )
    user_content = f"""Question:
{question}

Evidence status: {evidence_status}

{evidence_section}

{instruction}"""
    return (
        PromptMessage(role="system", content=SYSTEM_INSTRUCTIONS),
        *recent_messages,
        PromptMessage(role="user", content=user_content),
    )


def build_context_block(
    hits: Sequence[RetrievedHit],
    *,
    context_char_limit: int,
) -> str:
    remaining = context_char_limit
    blocks: list[str] = []
    for hit in hits:
        if remaining <= 0:
            break
        clean_context = scrub_private_paths(hit.context_text)
        if len(clean_context) > remaining:
            clean_context = clean_context[:remaining].rstrip()
        if not clean_context:
            continue
        block = f"[{hit.rank}] {source_label(hit)}{page_label_separator(hit)}{page_label(hit)}\n{clean_context}"
        blocks.append(block)
        remaining -= len(clean_context)
    return "\n\n".join(blocks)


def build_source_map_block(source_map: Sequence[SourceMapEntry]) -> str:
    blocks: list[str] = []
    for entry in source_map:
        details = [f"- {entry.title} - {entry.summary}"]
        if entry.best_source_for:
            details.append(f"  Best for: {', '.join(entry.best_source_for[:5])}")
        if entry.aliases:
            details.append(f"  Routing terms: {', '.join(entry.aliases[:8])}")
        if entry.chapters:
            details.append(f"  Sections: {', '.join(entry.chapters[:6])}")
        blocks.append("\n".join(details))
    return "\n".join(blocks)


def source_label(hit: RetrievedHit) -> str:
    if hit.object_title and hit.object_title != hit.title:
        return f"{hit.title}, {hit.object_title}"
    return hit.title


def page_label_separator(hit: RetrievedHit) -> str:
    return " " if page_label(hit).startswith("p.") else ", "


def page_label(hit: RetrievedHit) -> str:
    if hit.page_range_label:
        if hit.page_start is not None and hit.page_end is not None and hit.page_start != hit.page_end:
            return f"printed pages {hit.page_range_label}"
        return f"printed page {hit.page_range_label}"
    if hit.page_label and hit.page_label != str(hit.pdf_page_number):
        return f"printed page {hit.page_label}"
    return f"p. {hit.page_number}"


def scrub_private_paths(text: str) -> str:
    scrubbed = re.sub(r"/Users/[^\s]+", "[local path removed]", text)
    scrubbed = re.sub(r"[\w.-]+\.pdf", "[pdf filename removed]", scrubbed)
    return scrubbed
