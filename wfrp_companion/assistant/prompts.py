from __future__ import annotations

import re
from dataclasses import dataclass
from collections.abc import Sequence

from wfrp_companion.assistant.retrieval import RetrievedHit


SYSTEM_INSTRUCTIONS = """You are Familiar, a private local WFRP 2e Game Master aid.
Answer from retrieved context when possible. Cite book and page for factual rules
claims. If the retrieved context is insufficient, say that clearly. Distinguish
rules text from GM interpretation. Do not dump long copyrighted passages."""


@dataclass(frozen=True)
class PromptMessage:
    role: str
    content: str


def build_prompt_messages(
    *,
    question: str,
    hits: Sequence[RetrievedHit],
    recent_messages: Sequence[PromptMessage],
    context_char_limit: int = 9000,
) -> tuple[PromptMessage, ...]:
    context = build_context_block(hits, context_char_limit=context_char_limit)
    user_content = f"""Question:
{question}

Retrieved context:
{context if context else 'No retrieved context was found.'}

Answer with concise table guidance and citations."""
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
        block = f"[{hit.rank}] {hit.title} p. {hit.page_number}\n{clean_context}"
        blocks.append(block)
        remaining -= len(clean_context)
    return "\n\n".join(blocks)


def scrub_private_paths(text: str) -> str:
    scrubbed = re.sub(r"/Users/[^\s]+", "[local path removed]", text)
    scrubbed = re.sub(r"[\w.-]+\.pdf", "[pdf filename removed]", scrubbed)
    return scrubbed
