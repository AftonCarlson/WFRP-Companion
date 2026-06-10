from __future__ import annotations

from collections.abc import Iterable

from wfrp_companion.assistant import evidence_constraints
from wfrp_companion.assistant.query_planner import meaningful_tokens


PROVIDER_STRUCTURAL_FILLER_TERMS = frozenset(
    {
        "book",
        "chart",
        "charts",
        "combat",
        "determination",
        "chat",
        "mechanic",
        "mechanics",
        "page",
        "per",
        "profile",
        "profiles",
        "recent",
        "reference",
        "resolution",
        "rule",
        "rules",
        "section",
        "source",
        "stat",
        "statline",
        "statlines",
        "table",
        "tables",
        "terms",
    }
)
CANONICAL_SUBJECT_TERMS = {
    "hits": "hit",
}

SPELLING_ALIASES: dict[str, tuple[str, ...]] = {
    "armor": ("armour",),
    "armour": ("armor",),
}


def essential_subject_terms(text: str | None) -> tuple[str, ...]:
    if text is None:
        return ()
    terms: list[str] = []
    for token in meaningful_tokens(text):
        normalized = CANONICAL_SUBJECT_TERMS.get(token.casefold(), token.casefold())
        if normalized in PROVIDER_STRUCTURAL_FILLER_TERMS:
            continue
        if normalized in evidence_constraints.STRUCTURAL_CONSTRAINT_TERMS:
            continue
        if normalized in evidence_constraints.STAT_FIELD_TERMS:
            continue
        if normalized in terms:
            continue
        terms.append(normalized)
    return tuple(terms)


def identity_satisfies_essential_terms(
    identity_text: str,
    essential_terms: tuple[str, ...],
) -> bool:
    identity_tokens = expanded_token_set(
        evidence_constraints.normalized_tokens(identity_text)
    )
    return bool(essential_terms) and all(
        term in identity_tokens for term in expanded_terms(essential_terms)
    )


def expanded_token_set(tokens: Iterable[str]) -> set[str]:
    expanded: set[str] = set()
    for token in tokens:
        expanded.add(token)
        expanded.update(SPELLING_ALIASES.get(token, ()))
    return expanded


def expanded_terms(terms: Iterable[str]) -> tuple[str, ...]:
    expanded: list[str] = []
    for term in terms:
        normalized = term.casefold()
        if normalized not in expanded:
            expanded.append(normalized)
    return tuple(expanded)
