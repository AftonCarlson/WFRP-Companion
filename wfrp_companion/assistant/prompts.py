from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from wfrp_companion.assistant.retrieval import RetrievedHit, SourceMapEntry


SYSTEM_INSTRUCTIONS = """You are Familiar, a private local WFRP 2e Game Master aid and bounded research agent.
You operate over the user's enabled local books. The local app owns source scope, tools, retrieval, vector currentness, evidence validation, citations, and storage.
Use the public research plan and accepted retrieved evidence supplied by the app. Do not answer factual WFRP claims from memory. This includes rules, setting, statline, NPC, location, or source claims.
Unchecked books, chat history, and reader context are not evidence. Use chat history only to understand conversational references and user intent. Do not treat chat history as retrieved rules or setting evidence. Reader context can guide tool use but cannot satisfy a citation requirement.
For factual WFRP claims, Cite book and page using accepted evidence. If accepted evidence is insufficient, say exactly what is missing. For general GM advice that does not claim WFRP source facts, label it as general advice.
Keep copyrighted content brief: summarize, cite, and avoid long reproduced passages. Do not dump long copyrighted passages. Do not reveal hidden reasoning; public plan and evidence status summaries are allowed."""


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
    plan_summary: str | None = None,
    requirement_summaries: Sequence[Mapping[str, object]] = (),
) -> tuple[PromptMessage, ...]:
    subject_line = subject if subject else "none"
    book_line = active_book_id if active_book_id else "none"
    page_line = active_printed_page_label if active_printed_page_label else "none"
    prior_tool_block = build_prior_tool_outputs_block(prior_tool_outputs)
    plan_block = build_research_plan_status_block(
        plan_summary=plan_summary,
        requirement_summaries=requirement_summaries,
    )
    user_content = f"""Research request:
Raw query: {raw_query}
Resolved query: {resolved_query}
Intent: {intent}
Subject: {subject_line}
Active book: {book_line}
Active printed page: {page_line}

Prior local tool results:
{prior_tool_block if prior_tool_block else 'No prior local tool results.'}

Accepted research plan:
{plan_block}

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


def build_research_plan_status_block(
    *,
    plan_summary: str | None,
    requirement_summaries: Sequence[Mapping[str, object]],
) -> str:
    lines = [f"Plan summary: {single_line_hint(plan_summary or 'none')}"]
    if not requirement_summaries:
        lines.append("Requirements: none recorded")
        return "\n".join(lines)
    lines.append("Requirements:")
    for summary in requirement_summaries:
        requirement_id = single_line_hint(str(summary.get("id") or "unknown"))
        requirement_type = single_line_hint(
            str(summary.get("requirement_type") or "unknown")
        )
        status = single_line_hint(str(summary.get("status") or "unknown"))
        accepted_count = summary.get("accepted_hit_count", 0)
        partial_count = summary.get("partial_hit_count", 0)
        minimum = summary.get("min_accepted_hits", 1)
        required = "required" if summary.get("required", True) else "optional"
        subject = mapping_value(summary.get("subject"))
        lines.append(
            "- "
            f"{requirement_id} ({requirement_type}): {status}; "
            f"accepted {accepted_count}/{minimum}; partial {partial_count}; "
            f"{required}"
        )
        lines.extend(
            (
                f"  subject: {safe_summary_value(subject.get('canonical') or subject.get('surface') or 'none')}",
                f"  include: {safe_summary_list(subject.get('include_terms'))}",
                f"  exclude: {safe_summary_list(subject.get('exclude_terms'))}",
                f"  required_terms: {safe_summary_list(summary.get('required_terms'))}",
                f"  excluded_terms: {safe_summary_list(summary.get('excluded_terms'))}",
                f"  object_types: {safe_summary_list(summary.get('object_type_hints'))}",
                f"  book_hints: {safe_summary_list(subject.get('book_title_hints'))}",
                f"  page_hints: {safe_summary_list(subject.get('page_hints'))}",
            )
        )
    return scrub_private_paths("\n".join(lines))


def mapping_value(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def safe_summary_list(value: object, *, max_items: int = 6) -> str:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return "none"
    items = [
        safe_summary_value(item)
        for item in value[:max_items]
        if isinstance(item, str | int)
    ]
    return ", ".join(items) if items else "none"


def safe_summary_value(value: object, *, max_chars: int = 80) -> str:
    text = single_line_hint(str(value))
    text = scrub_private_paths(text)
    if len(text) > max_chars:
        return text[:max_chars].rstrip()
    return text


def build_research_planning_prompt_messages(
    *,
    raw_query: str,
    resolved_query: str,
    intent: str,
    subject: str | None,
    active_book_id: str | None,
    active_printed_page_label: str | None,
    recent_messages: Sequence[PromptMessage],
) -> tuple[PromptMessage, ...]:
    subject_line = subject if subject else "none"
    book_line = active_book_id if active_book_id else "none"
    page_line = active_printed_page_label if active_printed_page_label else "none"
    resolved_query_line = single_line_hint(resolved_query)
    user_content = f"""Create a JSON research plan for the local app to validate.

Research request:
Raw query: {raw_query}
Resolved query hint: {resolved_query_line}
Intent hint: {intent}
Subject hint: {subject_line}
Active book hint: {book_line}
Active printed page hint: {page_line}

The plan must use explicit evidence requirements. It may include planned actions
for search_library, open_page, lookup_source_object, or finish_research. Do not
include private book text, filesystem paths, or hidden reasoning."""
    return (
        PromptMessage(role="system", content=SYSTEM_INSTRUCTIONS),
        *recent_messages,
        PromptMessage(role="user", content=user_content),
    )


def single_line_hint(value: str) -> str:
    return " ".join(value.split())


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
    plan_summary: str | None = None,
    requirement_summaries: Sequence[Mapping[str, object]] = (),
    answer_policy: str = "cite_required",
    answer_outcome: str | None = None,
    missing_summaries: Sequence[str] = (),
    context_char_limit: int = 9000,
) -> tuple[PromptMessage, ...]:
    evidence_block = build_context_block(
        accepted_hits,
        context_char_limit=context_char_limit,
    )
    if evidence_block:
        evidence_section = f"Accepted evidence:\n{evidence_block}"
        instruction = final_answer_instruction(answer_outcome)
    else:
        evidence_section = "No accepted evidence was found."
        instruction = (
            "Explain the insufficiency clearly; do not reconstruct the WFRP facts "
            "from memory."
        )
    plan_block = build_final_plan_block(
        plan_summary=plan_summary,
        requirement_summaries=requirement_summaries,
        answer_policy=answer_policy,
        answer_outcome=answer_outcome,
        missing_summaries=missing_summaries,
    )
    user_content = f"""Question:
{question}

Evidence status: {evidence_status}

{plan_block}

{evidence_section}

{instruction}"""
    return (
        PromptMessage(role="system", content=SYSTEM_INSTRUCTIONS),
        *recent_messages,
        PromptMessage(role="user", content=user_content),
    )


def build_final_plan_block(
    *,
    plan_summary: str | None,
    requirement_summaries: Sequence[Mapping[str, object]],
    answer_policy: str,
    answer_outcome: str | None = None,
    missing_summaries: Sequence[str] = (),
) -> str:
    lines = [
        f"Answer policy: {answer_policy}",
        f"Answer outcome: {answer_outcome or 'not_recorded'}",
        f"Public plan: {plan_summary or 'No public plan summary was recorded.'}",
    ]
    if requirement_summaries:
        lines.append("Requirement status:")
        for summary in requirement_summaries:
            requirement_id = str(summary.get("id") or "unknown")
            requirement_type = str(summary.get("requirement_type") or "unknown")
            status = str(summary.get("status") or "unknown")
            lines.append(f"- {requirement_id} ({requirement_type}): {status}")
    else:
        lines.append("Requirement status: none recorded")
    if missing_summaries:
        lines.append("Missing requirements:")
        lines.extend(f"- {safe_summary_value(summary)}" for summary in missing_summaries)
    return "\n".join(lines)


def final_answer_instruction(answer_outcome: str | None) -> str:
    if answer_outcome == "partial_answer":
        return (
            "Answer the satisfied requirements from accepted evidence. Do not answer "
            "unsatisfied requirements. Briefly name missing requirements without "
            "blaming the user."
        )
    return "Answer only from accepted evidence and cite book/page."


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
    scrubbed = re.sub(
        r"(?i)/Users/[^\n\r,;]*?\.pdf\b",
        "[local path removed]",
        text,
    )
    scrubbed = re.sub(r"/Users/[^\n\r,;]+", "[local path removed]", scrubbed)
    scrubbed = re.sub(
        r"(?i)(^|[\s,;])[^/\\\n\r,;]{1,120}\.pdf\b",
        r"\1[pdf filename removed]",
        scrubbed,
    )
    return scrubbed
