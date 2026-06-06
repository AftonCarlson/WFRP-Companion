from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from wfrp_companion.assistant.retrieval import RetrievedHit, SourceMapEntry


SYSTEM_INSTRUCTIONS = """You are Familiar, a private local WFRP 2e Game Master aid.
Use only the enabled books and retrieved evidence supplied in this request.
Unchecked books are out of scope even if you know about them. Cite book and page
using printed page labels for factual rules or setting claims. If the retrieved
context is insufficient, say that clearly. Distinguish rules text from GM
interpretation. Do not dump long copyrighted passages."""


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
