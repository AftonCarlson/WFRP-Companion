from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import replace
from typing import Protocol

from wfrp_companion.assistant.evidence import EvidenceCandidate
from wfrp_companion.assistant.query_planner import QueryPlan
from wfrp_companion.assistant.query_planner import STAT_LINE_FILLER_TERMS
from wfrp_companion.assistant.query_planner import STRUCTURAL_QUERY_TERMS
from wfrp_companion.assistant.query_planner import has_stat_line_intent
from wfrp_companion.assistant.query_planner import meaningful_tokens
from wfrp_companion.assistant.query_planner import split_query_sequence
from wfrp_companion.assistant.query_planner import term_variants
from wfrp_companion.assistant.query_planner import terms_are_close


PREFERRED_OBJECT_BOOSTS = {
    "rule_section": 7.0,
    "table": 7.0,
    "table_row": 5.0,
    "stat_block": 7.0,
    "npc_profile": 7.0,
    "monster_profile": 7.0,
    "location_description": 6.0,
    "encounter": 5.0,
    "index_entry": 4.0,
    "glossary_entry": 5.0,
    "cross_reference": 2.0,
    "page_chunk": 1.0,
}

RankedCandidate = tuple[EvidenceCandidate, float, tuple[str, ...]]


class Reranker(Protocol):
    def rerank(
        self,
        candidates: Sequence[EvidenceCandidate],
        query_plan: QueryPlan,
    ) -> tuple[RankedCandidate, ...]:
        """Return semantically accepted candidates in final rank order."""


@dataclass(frozen=True)
class ReciprocalRankFusion:
    rank_constant: int = 60

    def fuse(
        self,
        candidates: Sequence[EvidenceCandidate],
    ) -> tuple[EvidenceCandidate, ...]:
        return reciprocal_rank_fuse(candidates, rank_constant=self.rank_constant)


@dataclass(frozen=True)
class _FusionBucket:
    candidate: EvidenceCandidate
    score: float
    reasons: tuple[str, ...]


class DeterministicReranker:
    def rerank(
        self,
        candidates: Sequence[EvidenceCandidate],
        query_plan: QueryPlan,
    ) -> tuple[RankedCandidate, ...]:
        ranked: list[RankedCandidate] = []
        all_terms = query_plan.match_terms
        required_overlap = required_semantic_overlap(query_plan)
        for candidate in candidates:
            matched_terms = semantic_overlaps(
                all_terms,
                candidate_relevance_text(candidate),
            )
            has_phrase_match = phrase_matches(
                query_plan.terms,
                candidate_phrase_relevance_text(candidate),
            )
            if len(matched_terms) < required_overlap and not has_phrase_match:
                continue
            if is_heading_path_only_match(candidate, query_plan, required_overlap):
                continue
            if not structural_query_matches_named_entity(
                candidate,
                query_plan,
                matched_terms,
            ):
                continue
            reasons = list(candidate.rank_reasons)
            reasons.append(f"semantic_overlap:{','.join(matched_terms)}")
            reasons.append(
                "reranker:deterministic:accepted:"
                f"overlap={len(matched_terms)}:required={required_overlap}"
            )
            for expansion in query_plan.expansions:
                if expansion.expanded in matched_terms:
                    reasons.append(f"expanded:{expansion.original}->{expansion.expanded}")

            score = float(len(matched_terms) * 10)
            if has_phrase_match:
                score += 6.0
                reasons.append("phrase_match:query_terms")
            if candidate.source_object_id is not None:
                score += PREFERRED_OBJECT_BOOSTS.get(candidate.object_type, 2.0)
            structural_boost = structural_intent_boost(candidate, query_plan)
            if structural_boost:
                score += structural_boost
                reasons.append(f"structural_intent_boost:{structural_boost:.1f}")
            if candidate.confidence is not None:
                score += candidate.confidence * 2
            if candidate.base_score < 0:
                score += min(4.0, abs(candidate.base_score))
            score += candidate_fusion_score(candidate) * 25
            reasons.append(f"reranker_score:deterministic={score:.3f}")

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


def reciprocal_rank_fuse(
    candidates: Sequence[EvidenceCandidate],
    *,
    rank_constant: int = 60,
) -> tuple[EvidenceCandidate, ...]:
    if not candidates:
        return ()
    if rank_constant < 1:
        raise ValueError("rank_constant must be positive")

    channels = tuple(dict.fromkeys(candidate.channel for candidate in candidates))
    buckets: dict[str, _FusionBucket] = {}
    for channel in channels:
        ranked_channel = unique_ranked_channel_candidates(
            (candidate for candidate in candidates if candidate.channel == channel),
        )
        for rank, candidate in enumerate(ranked_channel, start=1):
            contribution = 1 / (rank_constant + rank)
            reason = (
                f"fusion_channel:{channel}@{rank}:"
                f"score={candidate.base_score:.6g}:rrf={contribution:.6f}"
            )
            bucket = buckets.get(candidate.dedupe_key)
            if bucket is None:
                buckets[candidate.dedupe_key] = _FusionBucket(
                    candidate=candidate,
                    score=contribution,
                    reasons=(reason,),
                )
                continue
            preferred = preferred_candidate(bucket.candidate, candidate)
            buckets[candidate.dedupe_key] = _FusionBucket(
                candidate=replace(
                    preferred,
                    rank_reasons=tuple(
                        dict.fromkeys(
                            (
                                *preferred.rank_reasons,
                                *bucket.candidate.rank_reasons,
                                *candidate.rank_reasons,
                            )
                        )
                    ),
                ),
                score=bucket.score + contribution,
                reasons=(*bucket.reasons, reason),
            )

    fused_candidates = tuple(
        replace(
            bucket.candidate,
            rank_reasons=tuple(
                dict.fromkeys(
                    (
                        *bucket.candidate.rank_reasons,
                        *bucket.reasons,
                        f"fusion:rrf={bucket.score:.6f}",
                    )
                )
            ),
        )
        for bucket in sorted(
            buckets.values(),
            key=lambda item: (
                -item.score,
                item.candidate.page_start,
                item.candidate.title.casefold(),
                item.candidate.dedupe_key,
            ),
        )
    )
    return fused_candidates


def rerank_candidates(
    candidates: Sequence[EvidenceCandidate],
    query_plan: QueryPlan,
    *,
    reranker: Reranker | None = None,
) -> tuple[tuple[EvidenceCandidate, float, tuple[str, ...]], ...]:
    selected_reranker = reranker or DeterministicReranker()
    return selected_reranker.rerank(candidates, query_plan)


def candidate_channel_sort_key(candidate: EvidenceCandidate) -> tuple[float, int, str, str]:
    return (
        candidate.base_score,
        candidate.page_start,
        candidate.title.casefold(),
        candidate.dedupe_key,
    )


def unique_ranked_channel_candidates(
    candidates: Sequence[EvidenceCandidate],
) -> tuple[EvidenceCandidate, ...]:
    unique_candidates: dict[str, EvidenceCandidate] = {}
    for candidate in sorted(candidates, key=candidate_channel_sort_key):
        current = unique_candidates.get(candidate.dedupe_key)
        if current is None:
            unique_candidates[candidate.dedupe_key] = candidate
            continue
        preferred = preferred_candidate(current, candidate)
        unique_candidates[candidate.dedupe_key] = replace(
            preferred,
            rank_reasons=tuple(
                dict.fromkeys(
                    (
                        *preferred.rank_reasons,
                        *current.rank_reasons,
                        *candidate.rank_reasons,
                    )
                )
            ),
        )
    return tuple(
        sorted(
            unique_candidates.values(),
            key=candidate_channel_sort_key,
        )
    )


def preferred_candidate(
    current: EvidenceCandidate,
    candidate: EvidenceCandidate,
) -> EvidenceCandidate:
    if candidate_preference_key(candidate) < candidate_preference_key(current):
        return candidate
    return current


def candidate_preference_key(candidate: EvidenceCandidate) -> tuple[int, float, int, str]:
    return (
        0 if candidate.source_object_id is not None else 1,
        candidate.base_score,
        candidate.page_start,
        candidate.dedupe_key,
    )


def candidate_fusion_score(candidate: EvidenceCandidate) -> float:
    for reason in candidate.rank_reasons:
        if not reason.startswith("fusion:rrf="):
            continue
        try:
            return float(reason.removeprefix("fusion:rrf="))
        except ValueError:
            return 0.0
    return 0.0


def structural_intent_boost(candidate: EvidenceCandidate, query_plan: QueryPlan) -> float:
    terms = set(query_plan.match_terms)
    if {"table", "tables", "chart", "charts"}.intersection(terms) and candidate.object_type == "table":
        return 14.0
    if {
        "block",
        "blocks",
        "profile",
        "profiles",
        "stat",
        "stats",
        "statistics",
    }.intersection(terms):
        if candidate.object_type == "stat_block":
            return 14.0
        if candidate.object_type in {"npc_profile", "monster_profile"}:
            if any(
                reason.startswith("linked_source_object:stat_block")
                for reason in candidate.rank_reasons
            ):
                return 12.0
            return 10.0
    return 0.0


def structural_query_matches_named_entity(
    candidate: EvidenceCandidate,
    query_plan: QueryPlan,
    matched_terms: Sequence[str],
) -> bool:
    original_terms = tuple(dict.fromkeys(query_plan.terms))
    all_terms = tuple(dict.fromkeys(query_plan.match_terms))
    if not STRUCTURAL_QUERY_TERMS.intersection(all_terms):
        return True
    entity_terms = structural_query_entity_terms(query_plan)
    if not entity_terms:
        return True
    entity_matches = semantic_overlaps(
        entity_terms,
        candidate_entity_relevance_text(candidate),
    )
    if len(entity_terms) == 1:
        return entity_terms[0] in entity_matches
    phrase_pairs = adjacent_entity_phrase_pairs(original_terms)
    if phrase_pairs:
        phrase_text = candidate_phrase_relevance_text(candidate)
        return any(phrase_matches(pair, phrase_text) for pair in phrase_pairs)
    required_entities = min(2, len(entity_terms))
    return len(entity_matches) >= required_entities


def structural_query_entity_terms(query_plan: QueryPlan) -> tuple[str, ...]:
    original_terms = tuple(dict.fromkeys(query_plan.terms))
    stat_line_intent = has_stat_line_intent(split_query_sequence(original_terms))
    return tuple(
        term
        for term in original_terms
        if term not in STRUCTURAL_QUERY_TERMS
        and not (stat_line_intent and term in STAT_LINE_FILLER_TERMS)
    )


def adjacent_entity_phrase_pairs(terms: Sequence[str]) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    for left, right in zip(terms, terms[1:], strict=False):
        if left in STRUCTURAL_QUERY_TERMS or right in STRUCTURAL_QUERY_TERMS:
            continue
        pair = (left, right)
        if pair not in pairs:
            pairs.append(pair)
    return tuple(pairs)


def required_semantic_overlap(query_plan: QueryPlan) -> int:
    unique_terms = tuple(dict.fromkeys((*query_plan.terms, *query_plan.expanded_terms)))
    if len(unique_terms) <= 1:
        return 1
    return 2

def candidate_relevance_text(candidate: EvidenceCandidate) -> str:
    return " ".join(
        value
        for value in (
            candidate.title,
            candidate_object_type_text(candidate),
            candidate.object_title or "",
            " ".join(candidate.heading_path),
            candidate.snippet,
            candidate.context_text,
        )
        if value
    )


def candidate_direct_relevance_text(candidate: EvidenceCandidate) -> str:
    return " ".join(
        value
        for value in (
            candidate.title,
            candidate_object_type_text(candidate),
            candidate.object_title or "",
            context_without_heading_lines(candidate),
        )
        if value
    )


def candidate_entity_relevance_text(candidate: EvidenceCandidate) -> str:
    if candidate.source_object_id is None or candidate.object_type in {
        "page_chunk",
        "table",
        "table_row",
    }:
        return candidate_direct_relevance_text(candidate)
    return " ".join(
        value
        for value in (
            candidate.object_title or "",
            candidate_object_type_text(candidate),
            " ".join(candidate.heading_path),
        )
        if value
    )


def candidate_phrase_relevance_text(candidate: EvidenceCandidate) -> str:
    return " ".join(
        value
        for value in (
            candidate.object_title or "",
            candidate_object_type_text(candidate),
            context_without_heading_lines(candidate),
        )
        if value
    )


def is_heading_path_only_match(
    candidate: EvidenceCandidate,
    query_plan: QueryPlan,
    required_overlap: int,
) -> bool:
    if candidate.source_object_id is None or len(query_plan.terms) < 2:
        return False
    heading_matches = semantic_overlaps(query_plan.match_terms, " ".join(candidate.heading_path))
    if len(heading_matches) < required_overlap:
        return False
    direct_matches = semantic_overlaps(
        query_plan.match_terms,
        candidate_direct_relevance_text(candidate),
    )
    return len(direct_matches) < required_overlap


def candidate_object_type_text(candidate: EvidenceCandidate) -> str:
    if candidate.source_object_id is None:
        return ""
    return candidate.object_type.replace("_", " ")


def context_without_heading_lines(candidate: EvidenceCandidate) -> str:
    if not candidate.heading_path:
        return candidate.context_text
    normalized_headings = {
        " ".join(meaningful_tokens(heading)) for heading in candidate.heading_path
    }
    lines = [
        line
        for line in candidate.context_text.splitlines()
        if " ".join(meaningful_tokens(line)) not in normalized_headings
    ]
    return "\n".join(lines)

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
