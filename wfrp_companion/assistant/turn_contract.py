from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


TurnKind = Literal[
    "conversation",
    "app_help",
    "rules_lookup",
    "statline_lookup",
    "source_navigation",
    "lore_lookup",
    "scene_prep",
    "clarification_needed",
]
AnswerMode = Literal["direct", "research", "clarify"]
Confidence = Literal["high", "medium", "low"]
ReaderContextPolicy = Literal["ignore", "routing_hint", "page_navigation_hint"]


@dataclass(frozen=True)
class TurnDecision:
    turn_kind: TurnKind
    answer_mode: AnswerMode
    subject: str | None
    confidence: Confidence
    reasons: tuple[str, ...]
    reader_context_policy: ReaderContextPolicy


GREETING_TEXTS = {
    "hello",
    "hi",
    "hey",
    "good morning",
    "good afternoon",
    "good evening",
}
ACKNOWLEDGMENT_TEXTS = {
    "thanks",
    "thank you",
    "thx",
    "ok",
    "okay",
}
APP_HELP_PHRASES = (
    "what can you do",
    "how do i use",
    "help",
)
FRUSTRATION_PHRASES = (
    "why are you doing that",
    "this is broken",
    "that is wrong",
    "no",
    "stop",
)
STATLINE_TERMS = (
    "stat",
    "stats",
    "statline",
    "statlines",
    "profile",
    "ws",
    "bs",
)
RULES_TERMS = (
    "rule",
    "rules",
    "critical",
    "hit",
    "hits",
    "combat",
    "damage",
    "armor",
    "armour",
    "talent",
    "spell",
    "career",
    "skill",
    "test",
    "mutation",
    "mutations",
)
LORE_PHRASES = (
    "lore",
    "background",
    "about",
    "who is",
    "what is",
)
SCENE_PREP_TERMS = (
    "adventure",
    "crawl",
    "dungeon",
    "setting",
    "scenario",
    "prep",
    "ruins",
    "sewer",
    "mine",
)


def classify_turn(
    content: str,
    *,
    contextualized_query: str | None = None,
    history_strategy: str = "none",
) -> TurnDecision:
    normalized = normalize_text(content)
    lookup_text = (
        normalize_text(contextualized_query or content)
        if history_strategy == "followup_contextualized"
        else normalized
    )
    if not normalized:
        return TurnDecision(
            turn_kind="clarification_needed",
            answer_mode="clarify",
            subject=None,
            confidence="high",
            reasons=("empty_message",),
            reader_context_policy="ignore",
        )
    if normalized in GREETING_TEXTS:
        return TurnDecision(
            turn_kind="conversation",
            answer_mode="direct",
            subject=None,
            confidence="high",
            reasons=("greeting_or_social_text",),
            reader_context_policy="ignore",
        )
    if normalized in ACKNOWLEDGMENT_TEXTS:
        return TurnDecision(
            turn_kind="conversation",
            answer_mode="direct",
            subject=normalized,
            confidence="high",
            reasons=("acknowledgment_text",),
            reader_context_policy="ignore",
        )
    if has_frustration_signal(normalized):
        return TurnDecision(
            turn_kind="clarification_needed",
            answer_mode="clarify",
            subject=None,
            confidence="medium",
            reasons=("ambiguous_meta_or_frustration",),
            reader_context_policy="ignore",
        )
    if any(phrase in normalized for phrase in APP_HELP_PHRASES):
        return TurnDecision(
            turn_kind="app_help",
            answer_mode="direct",
            subject=None,
            confidence="high",
            reasons=("app_help_request",),
            reader_context_policy="ignore",
        )
    if re.fullmatch(r"(same page|page \d+|p\.? \d+)", normalized) or re.search(
        r"\b(p|pg|page)\.?\s*\d+\b",
        normalized,
    ):
        return TurnDecision(
            turn_kind="source_navigation",
            answer_mode="research",
            subject=content.strip(),
            confidence="medium",
            reasons=("page_reference",),
            reader_context_policy="page_navigation_hint",
        )
    if has_any_token(lookup_text, STATLINE_TERMS):
        return TurnDecision(
            turn_kind="statline_lookup",
            answer_mode="research",
            subject=content.strip(),
            confidence="medium",
            reasons=("statline_terms",),
            reader_context_policy="routing_hint",
        )
    if has_any_token(lookup_text, RULES_TERMS):
        return TurnDecision(
            turn_kind="rules_lookup",
            answer_mode="research",
            subject=content.strip(),
            confidence="medium",
            reasons=("rules_terms",),
            reader_context_policy="routing_hint",
        )
    if has_any_token(lookup_text, SCENE_PREP_TERMS):
        return TurnDecision(
            turn_kind="scene_prep",
            answer_mode="research",
            subject=content.strip(),
            confidence="medium",
            reasons=("scene_prep_terms",),
            reader_context_policy="routing_hint",
        )
    if has_lore_signal(normalized):
        return TurnDecision(
            turn_kind="lore_lookup",
            answer_mode="research",
            subject=content.strip(),
            confidence="low",
            reasons=("explicit_lore_signal",),
            reader_context_policy="routing_hint",
        )
    return TurnDecision(
        turn_kind="clarification_needed",
        answer_mode="clarify",
        subject=None,
        confidence="low",
        reasons=("low_confidence_unknown_turn",),
        reader_context_policy="ignore",
    )


def normalize_text(content: str) -> str:
    return " ".join(content.casefold().strip().split())


def has_any_token(normalized: str, terms: tuple[str, ...]) -> bool:
    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    return any(term in tokens for term in terms)


def has_lore_signal(normalized: str) -> bool:
    tokens = re.findall(r"[a-z0-9]+", normalized)
    if len(tokens) <= 1:
        return False
    return any(phrase in normalized for phrase in LORE_PHRASES)


def has_frustration_signal(normalized: str) -> bool:
    tokens = re.findall(r"[a-z0-9]+", normalized)
    for phrase in FRUSTRATION_PHRASES:
        phrase_tokens = re.findall(r"[a-z0-9]+", phrase)
        if len(phrase_tokens) == 1:
            if tokens == [phrase_tokens[0]]:
                return True
            continue
        if re.search(rf"\b{re.escape(phrase)}\b", normalized):
            return True
    return False
