from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from wfrp_companion.assistant import agent_planning
from wfrp_companion.assistant import chat_store
from wfrp_companion.assistant import evidence_constraints
from wfrp_companion.assistant import research
from wfrp_companion.assistant import statline_fields
from wfrp_companion.assistant.evidence import RetrievedHit
from wfrp_companion.assistant.query_planner import meaningful_tokens
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database


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
    subject_constraint: dict[str, object]
    constraint_status: evidence_constraints.ConstraintStatus


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
    config: AppConfig | None = None,
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
        config=config,
    )


def validate_hits_for_requirement(
    hits: Sequence[RetrievedHit],
    *,
    requirement: agent_planning.EvidenceRequirement,
    source_book_ids: Sequence[str],
    config: AppConfig | None = None,
) -> EvidenceValidationResult:
    scoped_book_ids = set(source_book_ids)
    constraint = evidence_constraints.constraint_from_requirement(requirement)
    judgments = tuple(
        validate_hit_for_requirement(
            hit,
            requirement=requirement,
            constraint=constraint,
            source_book_ids=scoped_book_ids,
            config=config,
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
    config: AppConfig | None = None,
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
        config=config,
    )


def validate_hit_for_requirement(
    hit: RetrievedHit,
    *,
    requirement: agent_planning.EvidenceRequirement,
    constraint: evidence_constraints.EvidenceConstraint | None = None,
    source_book_ids: set[str],
    config: AppConfig | None = None,
) -> EvidenceJudgmentDraft:
    requirement_type = requirement.requirement_type
    evidence_constraint = constraint or evidence_constraints.constraint_from_requirement(
        requirement
    )
    constraint_json = evidence_constraint.to_json()
    zones = evidence_zones_for_hit(
        config,
        hit,
        source_book_ids=source_book_ids,
    )
    if hit.book_id not in source_book_ids:
        return EvidenceJudgmentDraft(
            hit=hit,
            requirement_type=requirement_type,
            status="rejected",
            reason_code="unchecked_source",
            reasons=(f"{hit.book_id} is not in the enabled thread source scope.",),
            subject_constraint=constraint_json,
            constraint_status="failed",
        )
    excluded_term = first_matching_excluded_term(hit, evidence_constraint, zones)
    if excluded_term is not None:
        return EvidenceJudgmentDraft(
            hit=hit,
            requirement_type=requirement_type,
            status="rejected",
            reason_code="excluded_subject",
            reasons=(f"Evidence matches excluded term {excluded_term!r}.",),
            subject_constraint=constraint_json,
            constraint_status="failed",
        )
    if evidence_constraint.has_generic_subject_only:
        return EvidenceJudgmentDraft(
            hit=hit,
            requirement_type=requirement_type,
            status="rejected",
            reason_code="generic_subject_only",
            reasons=("The requirement contains only generic structural subject terms.",),
            subject_constraint=constraint_json,
            constraint_status="failed",
        )
    if not hit_matches_requirement_subject(hit, evidence_constraint, zones):
        return EvidenceJudgmentDraft(
            hit=hit,
            requirement_type=requirement_type,
            status="rejected",
            reason_code="subject_mismatch",
            reasons=("Evidence does not match the requested subject constraint.",),
            subject_constraint=constraint_json,
            constraint_status="failed",
        )
    if not hit_matches_book_hints(evidence_constraint, zones):
        return EvidenceJudgmentDraft(
            hit=hit,
            requirement_type=requirement_type,
            status="rejected",
            reason_code="book_hint_mismatch",
            reasons=("Evidence does not match the requested book hint.",),
            subject_constraint=constraint_json,
            constraint_status="failed",
        )
    if not hit_matches_page_hints(evidence_constraint, zones):
        return EvidenceJudgmentDraft(
            hit=hit,
            requirement_type=requirement_type,
            status="rejected",
            reason_code="page_hint_mismatch",
            reasons=("Evidence does not match the requested page hint.",),
            subject_constraint=constraint_json,
            constraint_status="failed",
        )
    if not hit_matches_object_type_hints(hit, evidence_constraint):
        return EvidenceJudgmentDraft(
            hit=hit,
            requirement_type=requirement_type,
            status="rejected",
            reason_code="object_type_mismatch",
            reasons=("Evidence does not match the requested source object type.",),
            subject_constraint=constraint_json,
            constraint_status="failed",
        )
    if requirement_type == "statline_evidence" and not hit_has_statline_evidence(
        hit,
        zones,
    ):
        if hit.object_type == "page_fallback":
            return EvidenceJudgmentDraft(
                hit=hit,
                requirement_type=requirement_type,
                status="partial",
                reason_code="subject_only_page",
                reasons=("Page evidence mentions the subject but lacks statline markers.",),
                subject_constraint=constraint_json,
                constraint_status="partial",
            )
        return EvidenceJudgmentDraft(
            hit=hit,
            requirement_type=requirement_type,
            status="rejected",
            reason_code=statline_failure_reason_code(hit),
            reasons=("Evidence does not contain sufficient stat/profile fields.",),
            subject_constraint=constraint_json,
            constraint_status="failed",
        )
    if not hit_matches_required_terms(hit, evidence_constraint, zones):
        return EvidenceJudgmentDraft(
            hit=hit,
            requirement_type=requirement_type,
            status="rejected",
            reason_code="missing_required_terms",
            reasons=("Evidence does not contain required supporting terms.",),
            subject_constraint=constraint_json,
            constraint_status="failed",
        )
    return EvidenceJudgmentDraft(
        hit=hit,
        requirement_type=requirement_type,
        status="accepted",
        reason_code="statline_evidence"
        if requirement_type == "statline_evidence"
        else "topical_evidence",
        reasons=("Evidence matches the requested source scope, subject, and intent.",),
        subject_constraint=constraint_json,
        constraint_status="passed",
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
            subject_constraint=judgment.subject_constraint,
            constraint_status=judgment.constraint_status,
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
    requirement: agent_planning.EvidenceRequirement
    | evidence_constraints.EvidenceConstraint,
    zones: evidence_constraints.EvidenceZones | None = None,
) -> bool:
    constraint = (
        evidence_constraints.constraint_from_requirement(requirement)
        if isinstance(requirement, agent_planning.EvidenceRequirement)
        else requirement
    )
    if not constraint.subject_terms:
        return True
    if (
        len(constraint.subject_terms) > 1
        and constraint.requirement_type in evidence_constraints.STRUCTURAL_REQUIREMENT_TYPES
    ):
        phrase = " ".join(constraint.subject_terms)
        if (
            zones is not None
            and hit.object_type != "page_fallback"
        ):
            return evidence_constraints.text_matches_phrase(
                subject_identity_text(zones),
                phrase,
            )
        phrase_evidence_text = (
            subject_evidence_text(zones)
            if zones is not None
            else evidence_text_for_hit(hit)
        )
        return evidence_constraints.text_matches_phrase(
            phrase_evidence_text,
            phrase,
        )
    evidence_text = (
        subject_evidence_text(zones)
        if zones is not None
        else evidence_text_for_hit(hit)
    )
    return evidence_constraints.text_matches_all_terms(
        evidence_text,
        constraint.subject_terms,
    )


def hit_matches_required_terms(
    hit: RetrievedHit,
    requirement: agent_planning.EvidenceRequirement
    | evidence_constraints.EvidenceConstraint,
    zones: evidence_constraints.EvidenceZones | None = None,
) -> bool:
    constraint = (
        evidence_constraints.constraint_from_requirement(requirement)
        if isinstance(requirement, agent_planning.EvidenceRequirement)
        else requirement
    )
    if not constraint.required_terms:
        return True
    evidence_text = zones_text(zones) if zones is not None else evidence_text_for_hit(hit)
    return all(
        text_matches_required_term(evidence_text, term)
        for term in constraint.required_terms
    )


def hit_matches_book_hints(
    constraint: evidence_constraints.EvidenceConstraint,
    zones: evidence_constraints.EvidenceZones,
) -> bool:
    if not constraint.book_title_hints:
        return True
    return any(
        evidence_constraints.text_matches_hint(
            zones.page_scope_text,
            hint,
            ignored_terms=evidence_constraints.BOOK_HINT_STOP_TERMS,
        )
        for hint in constraint.book_title_hints
    )


def hit_matches_page_hints(
    constraint: evidence_constraints.EvidenceConstraint,
    zones: evidence_constraints.EvidenceZones,
) -> bool:
    if not constraint.page_hints:
        return True
    return any(
        evidence_constraints.text_matches_hint(
            zones.page_scope_text,
            hint,
            ignored_terms=evidence_constraints.PAGE_HINT_STOP_TERMS,
        )
        for hint in constraint.page_hints
    )


def hit_matches_object_type_hints(
    hit: RetrievedHit,
    constraint: evidence_constraints.EvidenceConstraint,
) -> bool:
    if not constraint.object_type_hints:
        return True
    if hit.object_type == "page_fallback":
        return True
    hint_keys = {
        key
        for key in (
            evidence_constraints.normalized_object_type_key(hint)
            for hint in constraint.object_type_hints
        )
        if key
    }
    if not hint_keys:
        return True
    if evidence_constraints.normalized_object_type_key(hit.object_type) in hint_keys:
        return True
    return any(
        normalized_linked_object_type_reason(reason) in hint_keys
        for reason in hit.rank_reasons
    )


def normalized_linked_object_type_reason(reason: str) -> str | None:
    for prefix in ("linked_source_object:", "linked_evidence:"):
        if reason.startswith(prefix):
            return evidence_constraints.normalized_object_type_key(
                reason.removeprefix(prefix)
            )
    return None


def first_matching_excluded_term(
    hit: RetrievedHit,
    requirement: agent_planning.EvidenceRequirement
    | evidence_constraints.EvidenceConstraint,
    zones: evidence_constraints.EvidenceZones | None = None,
) -> str | None:
    constraint = (
        evidence_constraints.constraint_from_requirement(requirement)
        if isinstance(requirement, agent_planning.EvidenceRequirement)
        else requirement
    )
    evidence_text = zones_text(zones) if zones is not None else evidence_text_for_hit(hit)
    for term in constraint.excluded_terms:
        if term and text_contains_term(evidence_text, term):
            return term
    return None


def evidence_zones_for_hit(
    config: AppConfig | None,
    hit: RetrievedHit,
    *,
    source_book_ids: set[str],
) -> evidence_constraints.EvidenceZones:
    if config is None or hit.source_object_id is None:
        return evidence_constraints.build_evidence_zones(
            None,
            hit,
            source_book_ids=source_book_ids,
        )
    with initialize_database(config.db_path) as connection:
        return evidence_constraints.build_evidence_zones(
            connection,
            hit,
            source_book_ids=source_book_ids,
        )


def zones_text(zones: evidence_constraints.EvidenceZones | None) -> str:
    if zones is None:
        return ""
    return " ".join(
        part
        for part in (
            zones.identity_text,
            zones.direct_body_text,
            zones.structural_text,
            zones.page_scope_text,
            zones.linked_identity_text,
            zones.linked_stat_text,
        )
        if part
    ).casefold()


def subject_evidence_text(zones: evidence_constraints.EvidenceZones | None) -> str:
    if zones is None:
        return ""
    return " ".join(
        part
        for part in (
            zones.identity_text,
            zones.direct_body_text,
            zones.linked_identity_text,
        )
        if part
    ).casefold()


def subject_identity_text(zones: evidence_constraints.EvidenceZones | None) -> str:
    if zones is None:
        return ""
    return " ".join(
        part
        for part in (
            zones.identity_text,
            zones.linked_identity_text,
        )
        if part
    ).casefold()


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
    return evidence_constraints.text_matches_phrase(text, term)


def text_matches_term_or_tokens(text: str, term: str) -> bool:
    if text_contains_term(text, term):
        return True
    tokens = meaningful_tokens(term)
    return bool(tokens) and all(text_contains_term(text, token) for token in tokens)


def text_matches_required_term(text: str, term: str) -> bool:
    if text_contains_term(text, term):
        return True
    tokens = tuple(
        token
        for token in meaningful_tokens(term)
        if token.casefold() not in QUESTION_FILLER_TERMS
    )
    return bool(tokens) and all(text_contains_term(text, token) for token in tokens)


def hit_has_statline_evidence(
    hit: RetrievedHit,
    zones: evidence_constraints.EvidenceZones | None = None,
) -> bool:
    evidence_text = zones_text(zones) if zones is not None else hit.context_text.casefold()
    if statline_fields.has_sufficient_statline_fields(evidence_text):
        return True
    return bool(STATLINE_MARKER_RE.search(evidence_text)) and len(
        statline_fields.extract_stat_fields(evidence_text)
    ) >= statline_fields.MINIMUM_STAT_FIELD_COUNT


def statline_failure_reason_code(hit: RetrievedHit) -> str:
    if hit.object_type in STATLINE_OBJECT_TYPES:
        return "missing_statline_fields"
    return "missing_statline_markers"
