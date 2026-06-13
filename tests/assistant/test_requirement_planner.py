from __future__ import annotations

from wfrp_companion.assistant import agent_planning
from wfrp_companion.assistant import context_resolution
from wfrp_companion.assistant import requirement_contract
from wfrp_companion.assistant import requirement_planner
from wfrp_companion.assistant import turn_contract


def decision(
    kind: turn_contract.TurnKind,
    *,
    subject: str | None,
) -> turn_contract.TurnDecision:
    return turn_contract.TurnDecision(
        turn_kind=kind,
        answer_mode="research",
        subject=subject,
        confidence="medium",
        reasons=(f"{kind}_test",),
        reader_context_policy="routing_hint",
    )


def resolved(
    *,
    raw_query: str,
    intent: str,
    subject: str | None,
    page_reference: context_resolution.PageReference | None = None,
) -> context_resolution.ResolvedResearchRequest:
    return context_resolution.ResolvedResearchRequest(
        raw_query=raw_query,
        resolved_query=raw_query,
        intent=intent,
        subject=subject,
        page_reference=page_reference,
        active_book_id=None,
        used_active_subject=False,
    )


def test_multi_part_rules_query_creates_hit_location_and_armor_requirements() -> None:
    specs = requirement_planner.plan_requirements(
        "what are the rules on hit location and armor per location in combat",
        decision=decision("rules_lookup", subject=None),
        resolved=resolved(
            raw_query="what are the rules on hit location and armor per location",
            intent="rules_lookup",
            subject=None,
        ),
    )

    assert [spec.id for spec in specs] == [
        "hit_location_rule",
        "armor_location_rule",
    ]
    assert specs[0].subject_terms == ("hit", "location")
    assert specs[1].subject_terms == ("armor", "location")
    assert all(spec.required for spec in specs)
    assert all(spec.structured_lookup_policy == "allowed" for spec in specs)
    assert all(
        spec.structured_object_shape_hints == ("structured_table",) for spec in specs
    )


def test_statline_requirement_uses_resolved_active_subject() -> None:
    specs = requirement_planner.plan_requirements(
        "give me stats",
        decision=decision("statline_lookup", subject="give me stats"),
        resolved=resolved(
            raw_query="give me stats",
            intent="statline_lookup",
            subject="orc",
        ),
    )

    assert specs == (
        requirement_contract.RequirementSpec(
            id="statline_orc",
            kind="statline",
            query="orc statline",
            subject_terms=("orc",),
            optional_terms=("profile", "statline"),
            object_type_hints=("stat_block", "monster_profile", "npc_profile"),
            structured_lookup_policy="required",
            structured_object_shape_hints=("profile_bundle",),
            structured_entity_kind_hints=("monster", "npc", "creature"),
        ),
    )


def test_source_navigation_requirement_preserves_page_hint() -> None:
    specs = requirement_planner.plan_requirements(
        "open page 104",
        decision=decision("source_navigation", subject="open page 104"),
        resolved=resolved(
            raw_query="open page 104",
            intent="source_navigation",
            subject=None,
            page_reference=context_resolution.PageReference(
                printed_page_label="104",
                pdf_page_number=None,
            ),
        ),
    )
    requirement = requirement_contract.to_evidence_requirement(specs[0])

    assert specs[0].kind == "page_reference"
    assert specs[0].page_hints == ("104",)
    assert requirement.requirement_type == "page_evidence"


def test_lore_lookup_uses_supporting_context_fallback_terms() -> None:
    specs = requirement_planner.plan_requirements(
        "lore and background",
        decision=decision("lore_lookup", subject=None),
        resolved=resolved(
            raw_query="lore and background",
            intent="rules_lookup",
            subject=None,
        ),
    )

    assert specs[0].kind == "supporting_context"
    assert specs[0].subject_terms == ("lore", "background")
    assert specs[0].optional_terms == ()


def test_scene_prep_with_only_stop_words_keeps_empty_fallback_subject() -> None:
    specs = requirement_planner.plan_requirements(
        "and the of",
        decision=decision("scene_prep", subject=None),
        resolved=resolved(
            raw_query="and the of",
            intent="rules_lookup",
            subject=None,
        ),
    )

    assert specs[0].kind == "supporting_context"
    assert specs[0].subject_terms == ()
    assert specs[0].id == "supporting_context"
    assert specs[0].structured_lookup_policy == "supporting_only"
    assert specs[0].structured_object_shape_hints == ("profile_bundle",)
    assert specs[0].structured_entity_kind_hints == ("monster", "npc", "creature")


def test_explicit_table_number_query_enables_structured_table_lookup() -> None:
    specs = requirement_planner.plan_requirements(
        "what is table 5-6 in the core rulebook",
        decision=decision("rules_lookup", subject=None),
        resolved=resolved(
            raw_query="what is table 5-6 in the core rulebook",
            intent="rules_lookup",
            subject=None,
        ),
    )

    assert specs[0].structured_lookup_policy == "allowed"
    assert specs[0].structured_object_shape_hints == ("structured_table",)
    assert specs[0].table_number_hints == ("5-6",)


def test_normalize_provider_plan_removes_filler_from_hard_subject_terms() -> None:
    plan = agent_planning.ResearchPlan(
        id="plan-1",
        research_run_id="research-1",
        revision=1,
        intent="rules_lookup",
        plan_summary="Find hit location.",
        subject=agent_planning.SubjectConstraint(
            canonical="hit location determination in combat",
            surface="hit location determination in combat",
            include_terms=("hit location determination in combat",),
        ),
        requirements=(
            agent_planning.EvidenceRequirement(
                id="hit_location_rule",
                requirement_type="topical_evidence",
                subject=agent_planning.SubjectConstraint(
                    canonical="hit location determination in combat",
                    surface="hit location determination in combat",
                    include_terms=("hit location determination in combat",),
                ),
                required_terms=("hit location determination in combat",),
                object_type_hints=("Table", "rule section"),
            ),
        ),
        planned_actions=(
            agent_planning.PlannedAction(
                tool_name="search_library",
                requirement_id="hit_location_rule",
                purpose="Search",
                arguments={
                    "query": "hit location determination in combat",
                    "subject": "hit location determination in combat",
                    "object_type_hints": ["Table"],
                },
            ),
        ),
    )

    normalized = requirement_planner.normalize_provider_plan(plan)

    assert normalized.requirements[0].subject.canonical == "hit location"
    assert normalized.requirements[0].subject.include_terms == ("hit", "location")
    assert normalized.requirements[0].required_terms == ()
    assert normalized.requirements[0].object_type_hints == ("table", "rule_section")
    assert normalized.planned_actions[0].arguments["subject"] == "hit location"


def test_planner_helper_edge_branches_are_stable() -> None:
    source_object = requirement_contract.to_evidence_requirement(
        requirement_contract.RequirementSpec(
            id="object",
            kind="source_object",
            query="object lookup",
            subject_terms=("harpy",),
            optional_terms=(),
            object_type_hints=("stat_block",),
        )
    )
    action_without_requirement = agent_planning.PlannedAction(
        tool_name="search_library",
        requirement_id=None,
        purpose="No requirement.",
        arguments={"query": "harpy"},
    )
    action_for_missing_requirement = agent_planning.PlannedAction(
        tool_name="search_library",
        requirement_id="missing",
        purpose="Missing requirement.",
        arguments={"query": "harpy"},
    )

    assert source_object.requirement_type == "source_object_evidence"
    assert (
        requirement_planner.normalize_planned_action(
            action_without_requirement,
            requirements=(source_object,),
        )
        == action_without_requirement
    )
    assert (
        requirement_planner.normalize_planned_action(
            action_for_missing_requirement,
            requirements=(source_object,),
        )
        == action_for_missing_requirement
    )
    assert requirement_planner.optional_terms_from_content(
        "rules for fear and corruption",
        ("fear",),
    ) == ("corruption",)
    assert not requirement_planner.required_term_survives_normalization(
        "profile",
        ("harpy",),
    )
    assert not requirement_planner.required_term_survives_normalization(
        "hit location",
        ("hit", "location"),
    )
    assert requirement_planner.requirement_id("1", ()) == "req_1"
    assert requirement_planner.requirement_id("a", ()) == "a_requirement"
    empty_subject = agent_planning.SubjectConstraint(
        canonical=None,
        surface=None,
        include_terms=(),
    )
    assert requirement_planner.normalize_subject_constraint(empty_subject) == empty_subject
    assert requirement_planner.statline_subject_groups(None) == ((),)
    assert requirement_planner.statline_subject_groups("stats") == ((),)
    assert requirement_planner.has_statline_comparison_signal("harpy and gor")
