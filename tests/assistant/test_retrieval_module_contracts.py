from __future__ import annotations

from wfrp_companion.assistant import candidates
from wfrp_companion.assistant import evidence
from wfrp_companion.assistant import query_planner
from wfrp_companion.assistant import reranking
from wfrp_companion.assistant import retrieval
from wfrp_companion.assistant import source_map


def test_retrieval_facade_reexports_focused_module_contracts() -> None:
    assert retrieval.SourceMapEntry is source_map.SourceMapEntry
    assert retrieval.SourceScope is source_map.SourceScope
    assert retrieval.QueryPlan is query_planner.QueryPlan
    assert retrieval.QueryExpansion is query_planner.QueryExpansion
    assert retrieval.RetrievedHit is evidence.RetrievedHit
    assert retrieval.RetrievalContext is evidence.RetrievalContext
    assert retrieval.EvidenceCandidate is evidence.EvidenceCandidate


def test_retrieval_facade_reexports_phase_one_helpers() -> None:
    assert retrieval.current_thread_source_scope is source_map.current_thread_source_scope
    assert retrieval.build_enabled_source_map is source_map.build_enabled_source_map
    assert retrieval.plan_query is query_planner.plan_query
    assert retrieval.collect_evidence_candidates is candidates.collect_evidence_candidates
    assert retrieval.rerank_candidates is reranking.rerank_candidates
