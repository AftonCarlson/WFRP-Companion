from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from wfrp_companion.assistant import agent_planning
from wfrp_companion.assistant.evidence import RetrievedHit


AnswerOutcomeKind = Literal[
    "direct_response",
    "full_answer",
    "partial_answer",
    "clarifying_question",
    "insufficient_evidence",
    "provider_error",
]
RequirementOutcomeStatus = Literal["satisfied", "partial", "unsatisfied"]


@dataclass(frozen=True)
class RequirementOutcome:
    requirement_id: str
    status: RequirementOutcomeStatus
    required: bool
    accepted_hit_count: int
    partial_hit_count: int
    missing_summary: str | None

    def to_json(self) -> dict[str, object]:
        return {
            "requirement_id": self.requirement_id,
            "status": self.status,
            "required": self.required,
            "accepted_hit_count": self.accepted_hit_count,
            "partial_hit_count": self.partial_hit_count,
            "missing_summary": self.missing_summary,
        }


@dataclass(frozen=True)
class AnswerOutcome:
    kind: AnswerOutcomeKind
    evidence_status: str
    requirement_outcomes: tuple[RequirementOutcome, ...]
    user_message: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "evidence_status": self.evidence_status,
            "requirement_outcomes": [
                outcome.to_json() for outcome in self.requirement_outcomes
            ],
            "user_message": self.user_message,
        }

    @property
    def missing_summaries(self) -> tuple[str, ...]:
        return tuple(
            outcome.missing_summary
            for outcome in self.requirement_outcomes
            if outcome.missing_summary
        )


def build_answer_outcome(
    plan: agent_planning.ResearchPlan,
    *,
    accepted_hits_by_requirement: dict[str, list[RetrievedHit]],
    partial_hits_by_requirement: dict[str, list[RetrievedHit]],
) -> AnswerOutcome:
    requirement_outcomes = tuple(
        build_requirement_outcome(
            requirement,
            accepted_hits=accepted_hits_by_requirement.get(requirement.id, []),
            partial_hits=partial_hits_by_requirement.get(requirement.id, []),
        )
        for requirement in plan.requirements
    )
    required = tuple(outcome for outcome in requirement_outcomes if outcome.required)
    if required and all(outcome.status == "satisfied" for outcome in required):
        return AnswerOutcome(
            kind="full_answer",
            evidence_status="sufficient",
            requirement_outcomes=requirement_outcomes,
        )
    if any(outcome.status == "satisfied" for outcome in required):
        return AnswerOutcome(
            kind="partial_answer",
            evidence_status="partial",
            requirement_outcomes=requirement_outcomes,
            user_message="Some required evidence is still missing.",
        )
    return AnswerOutcome(
        kind="insufficient_evidence",
        evidence_status="insufficient",
        requirement_outcomes=requirement_outcomes,
        user_message="No required evidence has been accepted yet.",
    )


def build_requirement_outcome(
    requirement: agent_planning.EvidenceRequirement,
    *,
    accepted_hits: list[RetrievedHit],
    partial_hits: list[RetrievedHit],
) -> RequirementOutcome:
    accepted_count = len(accepted_hits)
    partial_count = len(partial_hits)
    if accepted_count >= requirement.min_accepted_hits:
        status: RequirementOutcomeStatus = "satisfied"
        missing_summary = None
    elif accepted_count or partial_count:
        status = "partial"
        missing_summary = missing_summary_for_requirement(requirement)
    else:
        status = "unsatisfied"
        missing_summary = missing_summary_for_requirement(requirement)
    return RequirementOutcome(
        requirement_id=requirement.id,
        status=status,
        required=requirement.required,
        accepted_hit_count=accepted_count,
        partial_hit_count=partial_count,
        missing_summary=missing_summary,
    )


def missing_summary_for_requirement(
    requirement: agent_planning.EvidenceRequirement,
) -> str:
    subject = (
        requirement.subject.canonical
        or requirement.subject.surface
        or " ".join(requirement.subject.include_terms)
        or requirement.id.replace("_", " ")
    )
    if requirement.requirement_type == "statline_evidence":
        return f"Need accepted stat/profile fields for {subject}."
    if requirement.requirement_type == "page_evidence":
        return f"Need accepted evidence for page reference {subject}."
    return f"Need accepted evidence for {subject}."
