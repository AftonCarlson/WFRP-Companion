from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal


JsonObject = dict[str, object]


@dataclass(frozen=True)
class ReaderContext:
    active_book_id: str | None = None
    active_pdf_page_number: int | None = None
    active_printed_page_label: str | None = None
    open_book_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RetrievalDiagnostics:
    channel_counts: dict[str, int]
    channel_skip_reasons: dict[str, str]
    vector_status: Literal[
        "ran",
        "ran_no_candidates",
        "disabled",
        "missing_embeddings",
        "stale_embeddings",
        "provider_error",
    ]
    candidate_count_before_fusion: int
    candidate_count_after_fusion: int
    reranked_count: int
    selected_count: int
    page_lookup_attempted: bool
    validation_status: Literal[
        "not_evaluated",
        "sufficient",
        "partial",
        "insufficient",
    ]


@dataclass(frozen=True)
class FamiliarResearchRun:
    id: str
    model_run_id: str
    thread_id: str
    user_message_id: str
    source_set_id: str | None
    raw_query: str
    resolved_query: str
    intent: str
    status: str
    max_tool_rounds: int
    tool_rounds_used: int
    evidence_status: str
    final_retrieval_run_id: str | None
    metadata: JsonObject
    created_at: str
    updated_at: str
    completed_at: str | None


@dataclass(frozen=True)
class FamiliarToolCall:
    id: str
    research_run_id: str
    research_plan_id: str | None
    requirement_id: str | None
    purpose: str | None
    step_number: int
    call_index: int
    provider_call_id: str | None
    tool_name: str
    arguments: JsonObject
    argument_hash: str
    status: str
    retrieval_run_id: str | None
    output_summary: JsonObject
    error_code: str | None
    error_message: str | None
    created_at: str
    updated_at: str
    completed_at: str | None


@dataclass(frozen=True)
class FamiliarEvidenceJudgment:
    id: str
    research_run_id: str
    research_plan_id: str | None
    requirement_id: str | None
    retrieval_run_id: str | None
    retrieval_hit_id: str | None
    source_object_id: str | None
    book_id: str | None
    printed_page_label: str | None
    requirement_type: str
    status: str
    reason_code: str
    reasons: tuple[str, ...]
    subject_constraint: JsonObject
    constraint_status: str | None
    created_at: str


@dataclass(frozen=True)
class ChatThreadContext:
    thread_id: str
    active_subject: str | None
    active_intent: str | None
    active_book_id: str | None
    active_printed_page_label: str | None
    active_pdf_page_number: int | None
    active_source_object_id: str | None
    updated_from_message_id: str | None
    updated_from_model_run_id: str | None
    metadata: JsonObject
    updated_at: str


def normalized_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def normalized_json_hash(value: object) -> str:
    return hashlib.sha256(normalized_json(value).encode("utf-8")).hexdigest()


def object_from_json(value: str | None) -> JsonObject:
    if not value:
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def string_tuple_from_json(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return ()
    if not isinstance(decoded, list):
        return ()
    return tuple(item for item in decoded if isinstance(item, str))
