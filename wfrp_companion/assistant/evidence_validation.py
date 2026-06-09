from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from wfrp_companion.assistant import agent_planning
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
QUESTION_FILLER_TERMS = {
    "about",
    "after",
    "happen",
    "happens",
    "what",
}


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
    requirement_type = (
        "statline_evidence" if intent == STATLINE_INTENT else "topical_evidence"
    )
    include_terms = tuple(meaningful_tokens(subject or ""))
    requirement = agent_planning.EvidenceRequirement(
        id="compatibility_requirement",
        requirement_type=requirement_type,
        subject=agent_planning.SubjectConstraint(
            canonical=subject,
            surface=subject,
            include_terms=include_terms,
            exclude_terms=(),
        ),
        required_terms=include_terms,
        excluded_terms=(),
        object_type_hints=(),
        min_accepted_hits=1,
        required=True,
    )
    return validate_hits_for_requirement(
        hits,
        requirement=requirement,
        source_book_ids=source_book_ids,
    )


def validate_hits_for_requirement(
    hits: Sequence[RetrievedHit],
    *,
    requirement: agent_planning.EvidenceRequirement,
    source_book_ids: Sequence[str],
) -> EvidenceValidationResult:
    scoped_book_ids = set(source_book_ids)
    judgments = tuple(
        validate_hit_for_requirement(
            hit,
            requirement=requirement,
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
    requirement_type = (
        "statline_evidence" if intent == STATLINE_INTENT else "topical_evidence"
    )
    requirement = agent_planning.EvidenceRequirement(
        id="compatibility_requirement",
        requirement_type=requirement_type,
        subject=agent_planning.SubjectConstraint(
            canonical=subject,
            surface=subject,
            include_terms=tuple(meaningful_tokens(subject or "")),
            exclude_terms=(),
        ),
        required_terms=tuple(meaningful_tokens(subject or "")),
        excluded_terms=(),
        object_type_hints=(),
        min_accepted_hits=1,
        required=True,
    )
    return validate_hit_for_requirement(
        hit,
        requirement=requirement,
        source_book_ids=source_book_ids,
    )


def validate_hit_for_requirement(
    hit: RetrievedHit,
    *,
    requirement: agent_planning.EvidenceRequirement,
    source_book_ids: set[str],
) -> EvidenceJudgmentDraft:
    requirement_type = requirement.requirement_type
    if hit.book_id not in source_book_ids:
        return EvidenceJudgmentDraft(
            hit=hit,
            requirement_type=requirement_type,
            status="rejected",
            reason_code="unchecked_source",
            reasons=(f"{hit.book_id} is not in the enabled thread source scope.",),
        )
    excluded_term = first_matching_excluded_term(hit, requirement)
    if excluded_term is not None:
        return EvidenceJudgmentDraft(
            hit=hit,
            requirement_type=requirement_type,
            status="rejected",
            reason_code="excluded_subject",
            reasons=(f"Evidence matches excluded term {excluded_term!r}.",),
        )
    if not hit_matches_requirement_subject(hit, requirement):
        return EvidenceJudgmentDraft(
            hit=hit,
            requirement_type=requirement_type,
            status="rejected",
            reason_code="subject_mismatch",
            reasons=("Evidence does not match the requested subject constraint.",),
        )
    if requirement_type == "statline_evidence" and not hit_has_statline_evidence(hit):
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
    if not hit_matches_required_terms(hit, requirement):
        return EvidenceJudgmentDraft(
            hit=hit,
            requirement_type=requirement_type,
            status="rejected",
            reason_code="missing_required_terms",
            reasons=("Evidence does not contain required supporting terms.",),
        )
    return EvidenceJudgmentDraft(
        hit=hit,
        requirement_type=requirement_type,
        status="accepted",
        reason_code="statline_evidence"
        if requirement_type == "statline_evidence"
        else "topical_evidence",
        reasons=("Evidence matches the requested source scope, subject, and intent.",),
    )


def record_evidence_judgments(
    config: AppConfig,
    *,
    research_run_id: str,
    research_plan_id: str | None = None,
    requirement_id: str | None = None,
    retrieval_run_id: str | None,
    validation: EvidenceValidationResult,
) -> tuple[research.FamiliarEvidenceJudgment, ...]:
    return tuple(
        chat_store.record_familiar_evidence_judgment(
            config,
            research_run_id=research_run_id,
            research_plan_id=research_plan_id,
            requirement_id=requirement_id,
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
    evidence_text = evidence_text_for_hit(hit)
    return all(term.casefold() in evidence_text for term in subject_terms)


def hit_matches_requirement_subject(
    hit: RetrievedHit,
    requirement: agent_planning.EvidenceRequirement,
) -> bool:
    include_terms = tuple(
        term
        for term in (
            *requirement.subject.include_terms,
            *(meaningful_tokens(requirement.subject.canonical or "")),
        )
        if term
    )
    if not include_terms:
        return True
    evidence_text = evidence_text_for_hit(hit)
    return any(text_matches_term_or_tokens(evidence_text, term) for term in include_terms)


def hit_matches_required_terms(
    hit: RetrievedHit,
    requirement: agent_planning.EvidenceRequirement,
) -> bool:
    if not requirement.required_terms:
        return True
    evidence_text = evidence_text_for_hit(hit)
    return all(
        text_matches_required_term(evidence_text, term)
        for term in requirement.required_terms
    )


def first_matching_excluded_term(
    hit: RetrievedHit,
    requirement: agent_planning.EvidenceRequirement,
) -> str | None:
    excluded_terms = (
        *requirement.subject.exclude_terms,
        *requirement.excluded_terms,
    )
    evidence_text = evidence_text_for_hit(hit)
    for term in excluded_terms:
        if term and text_contains_term(evidence_text, term):
            return term
    return None


def evidence_text_for_hit(hit: RetrievedHit) -> str:
    return " ".join(
        part
        for part in (
            hit.object_title,
            hit.title,
            hit.snippet,
            hit.context_text,
        )
        if part
    ).casefold()


def text_contains_term(text: str, term: str) -> bool:
    normalized = term.casefold().strip()
    if not normalized:
        return False
    return normalized in text


def text_matches_term_or_tokens(text: str, term: str) -> bool:
    if text_contains_term(text, term):
        return True
    tokens = meaningful_tokens(term)
    return bool(tokens) and all(token.casefold() in text for token in tokens)


def text_matches_required_term(text: str, term: str) -> bool:
    if text_contains_term(text, term):
        return True
    tokens = tuple(
        token
        for token in meaningful_tokens(term)
        if token.casefold() not in QUESTION_FILLER_TERMS
    )
    return bool(tokens) and all(token.casefold() in text for token in tokens)


def hit_has_statline_evidence(hit: RetrievedHit) -> bool:
    if hit.object_type in STATLINE_OBJECT_TYPES:
        return True
    if "stat_block" in hit.context_text.casefold():
        return True
    return bool(STATLINE_MARKER_RE.search(hit.context_text))
