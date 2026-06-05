from __future__ import annotations

from collections.abc import Sequence

from wfrp_companion.assistant.evidence import EvidenceCandidate
from wfrp_companion.assistant.query_planner import QueryPlan
from wfrp_companion.assistant.query_planner import meaningful_tokens
from wfrp_companion.assistant.query_planner import term_variants
from wfrp_companion.assistant.query_planner import terms_are_close


PREFERRED_OBJECT_BOOSTS = {
    "rule_section": 7.0,
    "table": 7.0,
    "stat_block": 7.0,
    "npc_profile": 7.0,
    "monster_profile": 7.0,
    "location_description": 6.0,
    "encounter": 5.0,
    "index_entry": 4.0,
    "cross_reference": 2.0,
    "page_chunk": 1.0,
}


def rerank_candidates(
    candidates: Sequence[EvidenceCandidate],
    query_plan: QueryPlan,
) -> tuple[tuple[EvidenceCandidate, float, tuple[str, ...]], ...]:
    ranked: list[tuple[EvidenceCandidate, float, tuple[str, ...]]] = []
    all_terms = query_plan.terms + query_plan.expanded_terms
    for candidate in candidates:
        matched_terms = semantic_overlaps(all_terms, candidate_relevance_text(candidate))
        if not matched_terms:
            continue
        reasons = list(candidate.rank_reasons)
        reasons.append(f"semantic_overlap:{','.join(matched_terms)}")
        for expansion in query_plan.expansions:
            if expansion.expanded in matched_terms:
                reasons.append(f"expanded:{expansion.original}->{expansion.expanded}")

        score = float(len(matched_terms) * 10)
        if phrase_matches(query_plan.terms, candidate.context_text):
            score += 6.0
            reasons.append("phrase_match:query_terms")
        if candidate.source_object_id is not None:
            score += PREFERRED_OBJECT_BOOSTS.get(candidate.object_type, 2.0)
        if candidate.confidence is not None:
            score += candidate.confidence * 2
        if candidate.base_score < 0:
            score += min(4.0, abs(candidate.base_score))

        ranked.append((candidate, score, tuple(dict.fromkeys(reasons))))
    ranked.sort(
        key=lambda item: (
            -item[1],
            item[0].page_start,
            item[0].title.casefold(),
            item[0].dedupe_key,
        )
    )
    return tuple(ranked)

def candidate_relevance_text(candidate: EvidenceCandidate) -> str:
    return " ".join(
        value
        for value in (
            candidate.title,
            candidate.object_title or "",
            " ".join(candidate.heading_path),
            candidate.snippet,
            candidate.context_text,
        )
        if value
    )

def phrase_matches(terms: Sequence[str], text: str) -> bool:
    if len(terms) < 2:
        return False
    normalized_text = " ".join(meaningful_tokens(text))
    return " ".join(terms) in normalized_text

def semantic_overlap_count(terms: Sequence[str], text: str) -> int:
    return len(semantic_overlaps(terms, text))

def semantic_overlaps(terms: Sequence[str], text: str) -> tuple[str, ...]:
    source_tokens = set(meaningful_tokens(text))
    matched: list[str] = []
    for term in terms:
        if term in matched:
            continue
        if token_matches_source(term, source_tokens):
            matched.append(term)
    return tuple(matched)

def token_matches_source(term: str, source_tokens: set[str]) -> bool:
    variants = term_variants(term)
    if variants.intersection(source_tokens):
        return True
    if len(term) < 5:
        return False
    return any(terms_are_close(term, source_token) for source_token in source_tokens)
