from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import product
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
    "name",
    "names",
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

STRUCTURAL_QUERY_TERMS = {
    "block",
    "blocks",
    "chart",
    "charts",
    "hitlocation",
    "hitlocations",
    "profile",
    "profiles",
    "row",
    "rows",
    "stat",
    "statblock",
    "statblocks",
    "stats",
    "statistics",
    "table",
    "tables",
}

COMPOUND_QUERY_PHRASES = (
    ("hit", "location"),
    ("main", "profile"),
    ("secondary", "profile"),
    ("stat", "block"),
)
MAX_QUERY_TERM_SEQUENCES = 16


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
    match_terms: tuple[str, ...]
    expansions: tuple[QueryExpansion, ...]
    candidates: tuple[str, ...]

def query_candidates(query: str) -> tuple[str, ...]:
    tokens = meaningful_tokens(query)
    return query_candidates_from_terms(tokens)

def query_candidates_from_terms(tokens: Sequence[str]) -> tuple[str, ...]:
    candidates: list[str] = []
    term_sequences = query_term_sequences(tokens)
    for sequence in term_sequences:
        add_candidate(candidates, " ".join(sequence))
    for sequence in term_sequences:
        for size in (3, 2):
            for index in range(0, max(0, len(sequence) - size + 1)):
                add_candidate(candidates, " ".join(sequence[index : index + size]))
        for token in sequence:
            add_candidate(candidates, token)
    return tuple(candidates)

def meaningful_tokens(query: str) -> list[str]:
    tokens = [token.lower() for token in re.findall(r"(?u)\b[\w'-]+\b", query)]
    return [token for token in tokens if token and token not in STOP_WORDS]

def query_match_terms(tokens: Sequence[str]) -> tuple[str, ...]:
    terms: list[str] = []
    for token in tokens:
        if token not in terms:
            terms.append(token)
    for token in tokens:
        for part in split_compound_query_token(token):
            if part not in terms:
                terms.append(part)
    return tuple(terms)

def query_term_sequences(tokens: Sequence[str]) -> tuple[tuple[str, ...], ...]:
    original = tuple(tokens)
    sequences: list[tuple[str, ...]] = []
    add_term_sequence(sequences, original)
    split_sequence = tuple(
        part
        for token in original
        for part in split_compound_query_token(token)
    )
    add_term_sequence(sequences, split_sequence)
    variant_groups = tuple(search_term_variants(token) for token in split_sequence)
    for variant_sequence in product(*variant_groups):
        add_term_sequence(sequences, variant_sequence)
        if len(sequences) >= MAX_QUERY_TERM_SEQUENCES:
            break
    return tuple(sequences)

def split_compound_query_token(token: str) -> tuple[str, ...]:
    normalized = token.replace("-", "")
    for phrase in COMPOUND_QUERY_PHRASES:
        phrase_text = "".join(phrase)
        plural_phrase_text = "".join((*phrase[:-1], f"{phrase[-1]}s"))
        if normalized in {phrase_text, plural_phrase_text}:
            return phrase
    return (token,)

def search_term_variants(term: str) -> tuple[str, ...]:
    variants = [term]
    for variant in (singular_search_term(term), plural_search_term(term)):
        if variant is not None and variant not in variants:
            variants.append(variant)
    return tuple(variants)

def singular_search_term(term: str) -> str | None:
    if term.endswith("ies") and len(term) > 4:
        return f"{term[:-3]}y"
    if term.endswith(("ss", "us", "is", "os", "ous")):
        return None
    if term.endswith("s") and len(term) > 3:
        return term[:-1]
    return None

def plural_search_term(term: str) -> str | None:
    if term.endswith("s") or len(term) <= 2:
        return None
    if term.endswith("y") and len(term) > 3:
        return f"{term[:-1]}ies"
    return f"{term}s"

def add_term_sequence(
    sequences: list[tuple[str, ...]],
    sequence: Sequence[str],
) -> None:
    normalized = tuple(token for token in sequence if token)
    if normalized and normalized not in sequences:
        sequences.append(normalized)

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
    match_terms = query_match_terms((*terms, *expanded_terms))
    return QueryPlan(
        terms=terms,
        expanded_terms=expanded_terms,
        match_terms=match_terms,
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
    if left in STRUCTURAL_QUERY_TERMS or right in STRUCTURAL_QUERY_TERMS:
        return False
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
