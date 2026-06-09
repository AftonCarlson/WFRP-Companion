from __future__ import annotations

from dataclasses import replace

from wfrp_companion.assistant.candidates import collect_evidence_candidates as collect_evidence_candidates
from wfrp_companion.assistant.candidates import collect_evidence_candidates_with_diagnostics as collect_evidence_candidates_with_diagnostics
from wfrp_companion.assistant.candidates import evidence_candidate_from_page_hit as evidence_candidate_from_page_hit
from wfrp_companion.assistant.candidates import evidence_candidate_from_source_object_row as evidence_candidate_from_source_object_row
from wfrp_companion.assistant.candidates import keep_best_candidate as keep_best_candidate
from wfrp_companion.assistant.candidates import resolve_page_hit_to_source_object as resolve_page_hit_to_source_object
from wfrp_companion.assistant.candidates import search_source_object_candidates as search_source_object_candidates
from wfrp_companion.assistant.candidates import search_source_object_fts_candidates as search_source_object_fts_candidates
from wfrp_companion.assistant.candidates import search_source_object_like_candidates as search_source_object_like_candidates
from wfrp_companion.assistant.candidates import search_vector_candidates as search_vector_candidates
from wfrp_companion.assistant.evidence import EvidenceCandidate as EvidenceCandidate
from wfrp_companion.assistant.evidence import RetrievalContext as RetrievalContext
from wfrp_companion.assistant.evidence import RetrievedHit as RetrievedHit
from wfrp_companion.assistant.evidence import context_window as context_window
from wfrp_companion.assistant.evidence import load_page_range_label as load_page_range_label
from wfrp_companion.assistant.evidence import load_page_text as load_page_text
from wfrp_companion.assistant.evidence import load_page_text_from_connection as load_page_text_from_connection
from wfrp_companion.assistant.evidence import parse_heading_path as parse_heading_path
from wfrp_companion.assistant.query_planner import QueryExpansion as QueryExpansion
from wfrp_companion.assistant.query_planner import QueryPlan as QueryPlan
from wfrp_companion.assistant.query_planner import add_candidate as add_candidate
from wfrp_companion.assistant.query_planner import append_candidate_tuple as append_candidate_tuple
from wfrp_companion.assistant.query_planner import edit_distance_at_most_one as edit_distance_at_most_one
from wfrp_companion.assistant.query_planner import expand_terms_from_source_map as expand_terms_from_source_map
from wfrp_companion.assistant.query_planner import meaningful_tokens as meaningful_tokens
from wfrp_companion.assistant.query_planner import plan_query as plan_query
from wfrp_companion.assistant.query_planner import query_candidates as query_candidates
from wfrp_companion.assistant.query_planner import query_candidates_from_terms as query_candidates_from_terms
from wfrp_companion.assistant.query_planner import query_match_terms as query_match_terms
from wfrp_companion.assistant.query_planner import term_variants as term_variants
from wfrp_companion.assistant.query_planner import terms_are_close as terms_are_close
from wfrp_companion.assistant.reranking import candidate_relevance_text as candidate_relevance_text
from wfrp_companion.assistant.reranking import DeterministicReranker as DeterministicReranker
from wfrp_companion.assistant.reranking import phrase_matches as phrase_matches
from wfrp_companion.assistant.reranking import reciprocal_rank_fuse as reciprocal_rank_fuse
from wfrp_companion.assistant.reranking import ReciprocalRankFusion as ReciprocalRankFusion
from wfrp_companion.assistant.reranking import rerank_candidates as rerank_candidates
from wfrp_companion.assistant.reranking import Reranker as Reranker
from wfrp_companion.assistant.reranking import semantic_overlap_count as semantic_overlap_count
from wfrp_companion.assistant.reranking import semantic_overlaps as semantic_overlaps
from wfrp_companion.assistant.reranking import token_matches_source as token_matches_source
from wfrp_companion.assistant.source_map import SourceMapEntry as SourceMapEntry
from wfrp_companion.assistant.source_map import SourceScope as SourceScope
from wfrp_companion.assistant.source_map import build_enabled_source_map as build_enabled_source_map
from wfrp_companion.assistant.source_map import build_enabled_source_map_from_connection as build_enabled_source_map_from_connection
from wfrp_companion.assistant.source_map import current_thread_source_scope as current_thread_source_scope
from wfrp_companion.assistant.source_map import infer_best_source_for as infer_best_source_for
from wfrp_companion.assistant.source_map import source_map_aliases as source_map_aliases
from wfrp_companion.assistant.source_map import source_map_chapters as source_map_chapters
from wfrp_companion.assistant.source_map import source_map_entry_from_book_row as source_map_entry_from_book_row
from wfrp_companion.assistant.source_map import source_vocabulary as source_vocabulary
from wfrp_companion.config import AppConfig
from wfrp_companion.assistant.research import RetrievalDiagnostics


def retrieve_context(
    config: AppConfig,
    thread_id: str,
    query: str,
    *,
    hit_limit: int,
    total_char_limit: int,
    window_chars: int,
) -> RetrievalContext:
    source_scope = current_thread_source_scope(config, thread_id)
    return retrieve_context_for_source_scope(
        config,
        source_scope,
        query,
        hit_limit=hit_limit,
        total_char_limit=total_char_limit,
        window_chars=window_chars,
    )


def retrieve_context_for_source_scope(
    config: AppConfig,
    source_scope: SourceScope,
    query: str,
    *,
    hit_limit: int,
    total_char_limit: int,
    window_chars: int,
) -> RetrievalContext:
    source_map = build_enabled_source_map(
        config,
        source_scope.book_ids,
        query_terms=tuple(meaningful_tokens(query)),
    )
    query_plan = plan_query(query, source_map)
    if hit_limit <= 0 or total_char_limit <= 0:
        return RetrievalContext(
            query=query,
            candidates=query_plan.candidates,
            hits=(),
            source_set_id=source_scope.source_set_id,
            source_book_ids=source_scope.book_ids,
            source_map=source_map,
            diagnostics=empty_diagnostics(config),
        )

    candidate_result = collect_evidence_candidates_with_diagnostics(
        config,
        source_book_ids=source_scope.book_ids,
        query_plan=query_plan,
        per_candidate_limit=max(8, hit_limit * 4),
    )
    evidence_pool = candidate_result.candidates
    ranked_candidates = rerank_candidates(evidence_pool, query_plan)
    selected_hits: list[RetrievedHit] = []
    remaining_chars = total_char_limit

    for candidate, score, rank_reasons in ranked_candidates:
        if len(selected_hits) >= hit_limit or remaining_chars <= 0:
            break
        context_text = candidate.context_text
        if candidate.source_object_id is None:
            context_text = context_window(
                context_text,
                terms=list(query_plan.match_terms),
                max_chars=window_chars,
            )
        if len(context_text) > remaining_chars:
            context_text = context_text[:remaining_chars].rstrip()
        if not context_text:
            continue
        selected_hits.append(
            RetrievedHit(
                book_id=candidate.book_id,
                title=candidate.title,
                category=candidate.category,
                page_id=candidate.page_id,
                page_number=candidate.page_number,
                pdf_page_number=candidate.pdf_page_number,
                page_label=candidate.page_label,
                snippet=candidate.snippet,
                score=score,
                rank=len(selected_hits) + 1,
                context_text=context_text,
                source_object_id=candidate.source_object_id,
                object_type=candidate.object_type,
                object_title=candidate.object_title,
                heading_path=candidate.heading_path,
                page_start=candidate.page_start,
                page_end=candidate.page_end,
                page_range_label=candidate.page_range_label,
                confidence=candidate.confidence,
                rank_reasons=rank_reasons,
                text_snapshot_sha256=candidate.text_snapshot_sha256,
            )
        )
        remaining_chars -= len(context_text)

    return RetrievalContext(
        query=query,
        candidates=query_plan.candidates,
        hits=tuple(selected_hits),
        source_set_id=source_scope.source_set_id,
        source_book_ids=source_scope.book_ids,
        source_map=source_map,
        diagnostics=replace(
            candidate_result.diagnostics,
            reranked_count=len(ranked_candidates),
            selected_count=len(selected_hits),
        ),
    )


def empty_diagnostics(config: AppConfig) -> RetrievalDiagnostics:
    vector_status = "disabled" if config.embedding_provider == "disabled" else "missing_embeddings"
    return RetrievalDiagnostics(
        channel_counts={
            "page_fts": 0,
            "source_object_fts": 0,
            "source_object_scan": 0,
            "vector": 0,
            "page_lookup": 0,
            "table_stat_lookup": 0,
        },
        channel_skip_reasons={"retrieval": "disabled_by_limits"},
        vector_status=vector_status,
        candidate_count_before_fusion=0,
        candidate_count_after_fusion=0,
        reranked_count=0,
        selected_count=0,
        page_lookup_attempted=False,
        validation_status="not_evaluated",
    )
