from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from wfrp_companion.assistant import chat_store
from wfrp_companion.assistant import research
from wfrp_companion.assistant.evidence import RetrievedHit
from wfrp_companion.assistant.query_planner import meaningful_tokens
from wfrp_companion.config import AppConfig


STATLINE_INTENT = "statline_lookup"
STATLINE_OBJECT_TYPES = {
    "stat_block",
    "monster_profile",
    "npc_profile",
    "table",
    "table_row",
}
STATLINE_MARKER_RE = re.compile(
    r"\b(?:m|ws|bs|s|t|w|ag|int|wp|fel|a|fp|ip|sb|tb)\b\s*[:0-9]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EvidenceJudgmentDraft:
    hit: RetrievedHit
    requirement_type: str
    status: str
    reason_code: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceValidationResult:
    status: str
    judgments: tuple[EvidenceJudgmentDraft, ...]
    accepted_hits: tuple[RetrievedHit, ...]


def validate_hits(
    hits: Sequence[RetrievedHit],
    *,
    subject: str | None,
    intent: str,
    source_book_ids: Sequence[str],
) -> EvidenceValidationResult:
    scoped_book_ids = set(source_book_ids)
    judgments = tuple(
        validate_hit(
            hit,
            subject=subject,
            intent=intent,
            source_book_ids=scoped_book_ids,
        )
        for hit in hits
    )
    accepted_hits = tuple(
        judgment.hit for judgment in judgments if judgment.status == "accepted"
    )
    partial_hits = tuple(
        judgment.hit for judgment in judgments if judgment.status == "partial"
    )
    if accepted_hits:
        status = "sufficient"
    elif partial_hits:
        status = "partial"
    else:
        status = "insufficient"
    return EvidenceValidationResult(
        status=status,
        judgments=judgments,
        accepted_hits=accepted_hits,
    )


def validate_hit(
    hit: RetrievedHit,
    *,
    subject: str | None,
    intent: str,
    source_book_ids: set[str],
) -> EvidenceJudgmentDraft:
    requirement_type = intent
    if hit.book_id not in source_book_ids:
        return EvidenceJudgmentDraft(
            hit=hit,
            requirement_type=requirement_type,
            status="rejected",
            reason_code="unchecked_source",
            reasons=(f"{hit.book_id} is not in the enabled thread source scope.",),
        )
    if subject and not hit_mentions_subject(hit, subject):
        return EvidenceJudgmentDraft(
            hit=hit,
            requirement_type=requirement_type,
            status="rejected",
            reason_code="subject_mismatch",
            reasons=(f"Evidence does not mention requested subject {subject!r}.",),
        )
    if intent == STATLINE_INTENT and not hit_has_statline_evidence(hit):
        if hit.object_type == "page_fallback":
            return EvidenceJudgmentDraft(
                hit=hit,
                requirement_type=requirement_type,
                status="partial",
                reason_code="subject_only_page",
                reasons=("Page evidence mentions the subject but lacks statline markers.",),
            )
        return EvidenceJudgmentDraft(
            hit=hit,
            requirement_type=requirement_type,
            status="rejected",
            reason_code="missing_statline_markers",
            reasons=("Evidence does not contain a structured stat/profile marker.",),
        )
    return EvidenceJudgmentDraft(
        hit=hit,
        requirement_type=requirement_type,
        status="accepted",
        reason_code="statline_evidence" if intent == STATLINE_INTENT else "topical_evidence",
        reasons=("Evidence matches the requested source scope, subject, and intent.",),
    )


def record_evidence_judgments(
    config: AppConfig,
    *,
    research_run_id: str,
    retrieval_run_id: str | None,
    validation: EvidenceValidationResult,
) -> tuple[research.FamiliarEvidenceJudgment, ...]:
    return tuple(
        chat_store.record_familiar_evidence_judgment(
            config,
            research_run_id=research_run_id,
            retrieval_run_id=retrieval_run_id,
            source_object_id=judgment.hit.source_object_id,
            book_id=judgment.hit.book_id,
            printed_page_label=judgment.hit.page_range_label
            or judgment.hit.page_label,
            requirement_type=judgment.requirement_type,
            status=judgment.status,
            reason_code=judgment.reason_code,
            reasons=judgment.reasons,
        )
        for judgment in validation.judgments
    )


def update_thread_context_from_validation(
    config: AppConfig,
    *,
    thread_id: str,
    validation: EvidenceValidationResult,
    subject: str | None,
    intent: str,
    updated_from_message_id: str | None,
    updated_from_model_run_id: str | None,
) -> research.ChatThreadContext | None:
    current = chat_store.get_chat_thread_context(config, thread_id)
    if validation.status not in {"sufficient", "partial"} or not validation.accepted_hits:
        return current
    hit = validation.accepted_hits[0]
    return chat_store.upsert_chat_thread_context(
        config,
        thread_id,
        active_subject=subject,
        active_intent=intent,
        active_book_id=hit.book_id,
        active_printed_page_label=hit.page_range_label or hit.page_label,
        active_pdf_page_number=hit.pdf_page_number,
        active_source_object_id=hit.source_object_id,
        updated_from_message_id=updated_from_message_id,
        updated_from_model_run_id=updated_from_model_run_id,
        metadata={
            "evidence_status": validation.status,
            "accepted_hit_count": len(validation.accepted_hits),
        },
    )


def hit_mentions_subject(hit: RetrievedHit, subject: str) -> bool:
    subject_terms = meaningful_tokens(subject)
    if not subject_terms:
        return True
    evidence_text = " ".join(
        part
        for part in (
            hit.object_title,
            hit.title,
            hit.snippet,
            hit.context_text,
        )
        if part
    ).casefold()
    return all(term.casefold() in evidence_text for term in subject_terms)


def hit_has_statline_evidence(hit: RetrievedHit) -> bool:
    if hit.object_type in STATLINE_OBJECT_TYPES:
        return True
    if "stat_block" in hit.context_text.casefold():
        return True
    return bool(STATLINE_MARKER_RE.search(hit.context_text))
