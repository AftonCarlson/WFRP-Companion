from __future__ import annotations

import re
from dataclasses import dataclass

from wfrp_companion.assistant import research
from wfrp_companion.assistant.query_planner import meaningful_tokens


STATLINE_INTENT = "statline_lookup"
RULES_INTENT = "rules_lookup"
STATLINE_TERMS = {
    "profile",
    "profiles",
    "stat",
    "stats",
    "statblock",
    "statblocks",
    "statline",
    "statlines",
}
ACTIVE_SUBJECT_STAT_FOLLOWUP_TERMS = {
    "are",
    "can",
    "could",
    "get",
    "give",
    "have",
    "i",
    "it",
    "its",
    "line",
    "me",
    "need",
    "please",
    "show",
    "that",
    "the",
    "their",
    "them",
    "there",
    "these",
    "they",
    "this",
    "those",
    "want",
    "what",
    "would",
    "you",
}
SHORT_STAT_FOLLOWUPS = {
    "i want the stats",
    "i want stats",
    "the stats",
    "stats",
    "the statline",
    "statline",
    "stat line",
    "the stat block",
    "stat block",
    "profile",
}
PAGE_REFERENCE_RE = re.compile(
    r"\b(?:p|pg|page)\.?\s*(?P<label>[0-9]+[A-Za-z]?)\b",
    re.IGNORECASE,
)
SAME_FOR_RE = re.compile(r"\bsame\s+for\s+(?P<subject>[\w' -]+)$", re.IGNORECASE)
RECOMMENDATION_TERMS = {
    "best",
    "better",
    "good",
    "great",
    "ideal",
    "recommend",
    "recommendation",
    "suggest",
    "suggestion",
}
SETTING_RECOMMENDATION_TERMS = {
    "adventure",
    "module",
    "place",
    "run",
    "setting",
    "settings",
    "site",
}
DUNGEON_CRAWL_RETRIEVAL_QUERY = (
    "dungeon crawl adventure setting underground ruins sewer mine"
)


@dataclass(frozen=True)
class PageReference:
    printed_page_label: str | None
    pdf_page_number: int | None
    same_page: bool = False


@dataclass(frozen=True)
class ResolvedResearchRequest:
    raw_query: str
    resolved_query: str
    intent: str
    subject: str | None
    page_reference: PageReference | None
    active_book_id: str | None
    used_active_subject: bool


def resolve_research_request(
    raw_query: str,
    *,
    active_context: research.ChatThreadContext | None,
) -> ResolvedResearchRequest:
    normalized = normalize_text(raw_query)
    active_subject = active_context.active_subject if active_context is not None else None
    active_intent = active_context.active_intent if active_context is not None else None
    page_reference = resolve_page_reference(
        raw_query,
        active_context=active_context,
    )
    recommendation_query = recommendation_retrieval_query(normalized)

    same_for_subject = same_for_subject_from_query(normalized)
    if recommendation_query is not None:
        subject = None
        intent = RULES_INTENT
        used_active_subject = False
    elif same_for_subject is not None:
        subject = same_for_subject
        intent = active_intent or RULES_INTENT
        used_active_subject = False
    else:
        intent = classify_intent(normalized, active_intent=active_intent)
        used_active_subject = False
        if should_use_active_subject(
            normalized,
            page_reference,
            intent=intent,
        ):
            subject = active_subject
            used_active_subject = subject is not None
        else:
            subject = subject_from_query(normalized, intent=intent)

    return ResolvedResearchRequest(
        raw_query=raw_query,
        resolved_query=build_resolved_query(
            subject=subject,
            intent=intent,
            page_reference=page_reference,
            fallback=recommendation_query or normalized,
        ),
        intent=intent,
        subject=subject,
        page_reference=page_reference,
        active_book_id=active_context.active_book_id if active_context is not None else None,
        used_active_subject=used_active_subject,
    )


def resolve_page_reference(
    raw_query: str,
    *,
    active_context: research.ChatThreadContext | None,
) -> PageReference | None:
    parsed = parse_page_reference(raw_query)
    if parsed is None:
        return None
    if parsed.same_page and active_context is not None:
        return PageReference(
            printed_page_label=active_context.active_printed_page_label,
            pdf_page_number=active_context.active_pdf_page_number,
            same_page=True,
        )
    return parsed


def parse_page_reference(raw_query: str) -> PageReference | None:
    normalized = normalize_text(raw_query)
    if normalized == "same page":
        return PageReference(
            printed_page_label=None,
            pdf_page_number=None,
            same_page=True,
        )
    match = PAGE_REFERENCE_RE.search(raw_query)
    if match is None:
        return None
    return PageReference(
        printed_page_label=match.group("label"),
        pdf_page_number=None,
        same_page=False,
    )


def classify_intent(normalized_query: str, *, active_intent: str | None) -> str:
    if is_statline_query(normalized_query):
        return STATLINE_INTENT
    return active_intent or RULES_INTENT


def is_statline_query(normalized_query: str) -> bool:
    if normalized_query in SHORT_STAT_FOLLOWUPS:
        return True
    compact = normalized_query.replace(" ", "")
    if "statline" in compact or "statblock" in compact:
        return True
    return bool({"stats", "profile"}.intersection(meaningful_tokens(normalized_query)))


def same_for_subject_from_query(normalized_query: str) -> str | None:
    match = SAME_FOR_RE.search(normalized_query)
    if match is None:
        return None
    return normalize_subject(match.group("subject"))


def recommendation_retrieval_query(normalized_query: str) -> str | None:
    tokens = set(meaningful_tokens(normalized_query))
    if (
        tokens.intersection(RECOMMENDATION_TERMS)
        and tokens.intersection(SETTING_RECOMMENDATION_TERMS)
        and has_dungeon_crawl_terms(tokens)
    ):
        return DUNGEON_CRAWL_RETRIEVAL_QUERY
    return None


def has_dungeon_crawl_terms(tokens: set[str]) -> bool:
    has_dungeon = bool(tokens.intersection({"dungeon", "dungeons"}))
    has_crawl = bool(tokens.intersection({"crawl", "crawls"}))
    has_compound = bool(tokens.intersection({"dungeon-crawl", "dungeon-crawls"}))
    return has_compound or (has_dungeon and has_crawl)


def subject_from_query(normalized_query: str, *, intent: str) -> str | None:
    if intent == STATLINE_INTENT:
        before_intent = re.match(
            r"(?P<subject>.+?)\s+(?:stat\s*line|statline|stat\s*block|statblock|stats?|profile)s?$",
            normalized_query,
        )
        if before_intent is not None:
            return normalize_subject(before_intent.group("subject"))
        after_intent = re.match(
            r"(?:stat\s*line|statline|stat\s*block|statblock|stats?|profile)s?\s+for\s+(?P<subject>.+)$",
            normalized_query,
        )
        if after_intent is not None:
            return normalize_subject(after_intent.group("subject"))
    tokens = [
        token
        for token in meaningful_tokens(normalized_query)
        if token not in STATLINE_TERMS and token != "page"
    ]
    return " ".join(tokens) if tokens else None


def should_use_active_subject(
    normalized_query: str,
    page_reference: PageReference | None,
    *,
    intent: str,
) -> bool:
    if page_reference is not None or normalized_query in SHORT_STAT_FOLLOWUPS:
        return True
    if intent != STATLINE_INTENT or not is_statline_query(normalized_query):
        return False
    tokens = re.findall(r"(?u)\b[\w'-]+\b", normalized_query)
    non_reference_tokens = [
        token
        for token in tokens
        if token not in STATLINE_TERMS
        and token not in ACTIVE_SUBJECT_STAT_FOLLOWUP_TERMS
    ]
    return not non_reference_tokens


def build_resolved_query(
    *,
    subject: str | None,
    intent: str,
    page_reference: PageReference | None,
    fallback: str,
) -> str:
    if subject is not None and intent == STATLINE_INTENT:
        base = f"{subject} statline"
    elif subject is not None:
        base = subject
    elif intent == STATLINE_INTENT:
        base = "statline"
    else:
        base = fallback
    if page_reference is None:
        return base
    label = page_reference.printed_page_label
    if label:
        return f"{base} page {label}"
    return base


def normalize_subject(value: str) -> str | None:
    cleaned = normalize_text(value)
    cleaned = re.sub(r"^(?:the|a|an)\s+", "", cleaned)
    tokens = [
        token
        for token in meaningful_tokens(cleaned)
        if token not in STATLINE_TERMS and token != "for"
    ]
    return " ".join(tokens) if tokens else None


def normalize_text(value: str) -> str:
    return " ".join(value.casefold().strip().split())
