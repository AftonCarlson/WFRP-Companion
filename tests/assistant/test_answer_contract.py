from __future__ import annotations

from wfrp_companion.assistant import agent_planning
from wfrp_companion.assistant import answer_contract
from wfrp_companion.assistant.evidence import RetrievedHit


def requirement(
    requirement_id: str,
    subject: str,
    *,
    requirement_type: agent_planning.RequirementType = "topical_evidence",
) -> agent_planning.EvidenceRequirement:
    return agent_planning.EvidenceRequirement(
        id=requirement_id,
        requirement_type=requirement_type,
        subject=agent_planning.SubjectConstraint(
            canonical=subject,
            surface=subject,
            include_terms=tuple(subject.split()),
        ),
        min_accepted_hits=1,
        required=True,
    )


def plan(
    requirements: tuple[agent_planning.EvidenceRequirement, ...],
) -> agent_planning.ResearchPlan:
    return agent_planning.ResearchPlan(
        id="plan-1",
        research_run_id="research-1",
        revision=1,
        intent="rules_lookup",
        plan_summary="Find rules.",
        subject=agent_planning.SubjectConstraint(canonical=None, surface=None),
        requirements=requirements,
    )


def hit(subject: str) -> RetrievedHit:
    return RetrievedHit(
        book_id="core",
        title="Core Rules",
        category="Core",
        page_id="core:1",
        page_number=1,
        pdf_page_number=1,
        page_label="1",
        snippet=subject,
        score=1.0,
        rank=1,
        context_text=subject,
    )


def test_answer_outcome_full_when_all_required_requirements_satisfied() -> None:
    research_plan = plan((requirement("hit_location", "hit location"),))

    outcome = answer_contract.build_answer_outcome(
        research_plan,
        accepted_hits_by_requirement={"hit_location": [hit("hit location")]},
        partial_hits_by_requirement={},
    )

    assert outcome.kind == "full_answer"
    assert outcome.evidence_status == "sufficient"
    assert outcome.missing_summaries == ()


def test_answer_outcome_partial_names_unsatisfied_requirement() -> None:
    research_plan = plan(
        (
            requirement("hit_location", "hit location"),
            requirement("armor_location", "armor location"),
        )
    )

    outcome = answer_contract.build_answer_outcome(
        research_plan,
        accepted_hits_by_requirement={"hit_location": [hit("hit location")]},
        partial_hits_by_requirement={},
    )

    assert outcome.kind == "partial_answer"
    assert outcome.evidence_status == "partial"
    assert outcome.missing_summaries == (
        "Need accepted evidence for armor location.",
    )


def test_answer_outcome_insufficient_names_statline_missing_fields() -> None:
    research_plan = plan(
        (requirement("orc_stats", "orc", requirement_type="statline_evidence"),)
    )

    outcome = answer_contract.build_answer_outcome(
        research_plan,
        accepted_hits_by_requirement={},
        partial_hits_by_requirement={},
    )

    assert outcome.kind == "insufficient_evidence"
    assert outcome.missing_summaries == ("Need accepted stat/profile fields for orc.",)


def test_page_requirement_missing_summary_names_page_reference() -> None:
    evidence_requirement = requirement(
        "page_reference",
        "printed page 99",
        requirement_type="page_evidence",
    )

    assert answer_contract.missing_summary_for_requirement(evidence_requirement) == (
        "Need accepted evidence for page reference printed page 99."
    )
