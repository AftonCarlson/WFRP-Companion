from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


STOP_WORDS = {
    "a",
    "about",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "can",
    "could",
    "do",
    "does",
    "give",
    "has",
    "have",
    "for",
    "from",
    "happen",
    "happens",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "of",
    "on",
    "or",
    "please",
    "should",
    "tell",
    "that",
    "these",
    "thing",
    "things",
    "this",
    "those",
    "the",
    "there",
    "to",
    "what",
    "when",
    "where",
    "which",
    "would",
    "with",
    "you",
}


class SourceMapEntryLike(Protocol):
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class QueryExpansion:
    original: str
    expanded: str

@dataclass(frozen=True)
class QueryPlan:
    terms: tuple[str, ...]
    expanded_terms: tuple[str, ...]
    expansions: tuple[QueryExpansion, ...]
    candidates: tuple[str, ...]

def query_candidates(query: str) -> tuple[str, ...]:
    tokens = meaningful_tokens(query)
    return query_candidates_from_terms(tokens)

def query_candidates_from_terms(tokens: Sequence[str]) -> tuple[str, ...]:
    candidates: list[str] = []
    add_candidate(candidates, " ".join(tokens))
    for size in (3, 2):
        for index in range(0, max(0, len(tokens) - size + 1)):
            add_candidate(candidates, " ".join(tokens[index : index + size]))
    for token in tokens:
        add_candidate(candidates, token)
    return tuple(candidates)

def meaningful_tokens(query: str) -> list[str]:
    tokens = [token.lower() for token in re.findall(r"(?u)\b[\w'-]+\b", query)]
    return [token for token in tokens if token and token not in STOP_WORDS]

def add_candidate(candidates: list[str], candidate: str) -> None:
    cleaned = " ".join(candidate.split())
    if cleaned and cleaned not in candidates:
        candidates.append(cleaned)

def plan_query(query: str, source_map: Sequence[SourceMapEntryLike]) -> QueryPlan:
    terms = tuple(meaningful_tokens(query))
    expansions = tuple(expand_terms_from_source_map(terms, source_map))
    expanded_terms = tuple(
        expansion.expanded
        for expansion in expansions
        if expansion.expanded not in terms
    )
    candidates = query_candidates_from_terms((*terms, *expanded_terms))
    for expansion in expansions:
        candidates = append_candidate_tuple(candidates, expansion.expanded)
    return QueryPlan(
        terms=terms,
        expanded_terms=expanded_terms,
        expansions=expansions,
        candidates=candidates,
    )

def append_candidate_tuple(candidates: tuple[str, ...], candidate: str) -> tuple[str, ...]:
    candidate_list = list(candidates)
    add_candidate(candidate_list, candidate)
    return tuple(candidate_list)

def expand_terms_from_source_map(
    terms: Sequence[str],
    source_map: Sequence[SourceMapEntryLike],
) -> tuple[QueryExpansion, ...]:
    expansions: list[QueryExpansion] = []
    aliases = tuple(
        alias.casefold()
        for entry in source_map
        for alias in entry.aliases
        if alias
    )
    for term in terms:
        for alias in aliases:
            if alias == term:
                continue
            if terms_are_close(term, alias):
                expansion = QueryExpansion(original=term, expanded=alias)
                if expansion not in expansions:
                    expansions.append(expansion)
    return tuple(expansions)

def term_variants(term: str) -> set[str]:
    variants = {term}
    if term.endswith("y") and len(term) > 3:
        variants.add(f"{term[:-1]}ies")
    if term.endswith("ies") and len(term) > 4:
        variants.add(f"{term[:-3]}y")
    if term.endswith("s") and len(term) > 3:
        variants.add(term[:-1])
    else:
        variants.add(f"{term}s")
    return variants

def terms_are_close(left: str, right: str) -> bool:
    if left == right:
        return True
    if term_variants(left).intersection(term_variants(right)):
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) < 5 or len(right) < 5:
        return False
    return edit_distance_at_most_one(left, right)

def edit_distance_at_most_one(left: str, right: str) -> bool:
    if left == right:
        return True
    if len(left) == len(right):
        differences = sum(1 for l_char, r_char in zip(left, right, strict=True) if l_char != r_char)
        return differences <= 1

    if len(left) > len(right):
        left, right = right, left
    left_index = 0
    right_index = 0
    skipped = False
    while left_index < len(left) and right_index < len(right):
        if left[left_index] == right[right_index]:
            left_index += 1
            right_index += 1
            continue
        if skipped:
            return False
        skipped = True
        right_index += 1
    return True
