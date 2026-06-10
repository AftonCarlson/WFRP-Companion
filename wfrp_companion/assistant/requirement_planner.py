from __future__ import annotations

import re
from dataclasses import replace

from wfrp_companion.assistant import agent_planning
from wfrp_companion.assistant import chat_store
from wfrp_companion.assistant import context_resolution
from wfrp_companion.assistant import evidence_policy
from wfrp_companion.assistant import requirement_contract
from wfrp_companion.assistant import turn_contract
from wfrp_companion.assistant.query_planner import meaningful_tokens


RULES_OBJECT_TYPES = ("rule_section", "table")
STATLINE_OBJECT_TYPES = ("stat_block", "monster_profile", "npc_profile")
STATLINE_REQUEST_FILLER = {
    "both",
    "compare",
    "give",
    "me",
    "show",
}
FOLLOWUP_CONTEXT_MARKER = "Recent chat terms for reference resolution:"


def plan_requirements(
    content: str,
    *,
    decision: turn_contract.TurnDecision,
    resolved: context_resolution.ResolvedResearchRequest,
) -> tuple[requirement_contract.RequirementSpec, ...]:
    if decision.turn_kind == "statline_lookup" or resolved.intent == "statline_lookup":
        subject_source = resolved.subject or decision.subject or researchable_subject_text(content)
        if has_statline_comparison_signal(content):
            subject_source = content
        subject_groups = statline_subject_groups(subject_source)
        return tuple(
            requirement_contract.RequirementSpec(
                id=requirement_id("statline", subject_terms),
                kind="statline",
                query=query_from_terms((*subject_terms, "statline")),
                subject_terms=subject_terms,
                optional_terms=("profile", "statline"),
                object_type_hints=STATLINE_OBJECT_TYPES,
            )
            for subject_terms in subject_groups
        )
    if decision.turn_kind == "source_navigation" or resolved.page_reference is not None:
        page_hint = (
            resolved.page_reference.printed_page_label
            if resolved.page_reference is not None
            else None
        )
        subject_terms = subject_terms_from_text(resolved.subject)
        return (
            requirement_contract.RequirementSpec(
                id="page_reference",
                kind="page_reference",
                query=content.strip(),
                subject_terms=subject_terms,
                optional_terms=(),
                object_type_hints=("page_fallback",),
                page_hints=tuple(hint for hint in (page_hint,) if hint),
            ),
        )
    if is_hit_location_and_armor_query(content):
        return (
            requirement_contract.RequirementSpec(
                id="hit_location_rule",
                kind="rules_topic",
                query="hit location combat table body location",
                subject_terms=("hit", "location"),
                optional_terms=("combat", "attack", "table", "body"),
                object_type_hints=RULES_OBJECT_TYPES,
                book_hints=("core rules",),
            ),
            requirement_contract.RequirementSpec(
                id="armor_location_rule",
                kind="rules_topic",
                query="armor armour points location body location combat",
                subject_terms=("armor", "location"),
                optional_terms=("armour", "points", "body", "combat"),
                object_type_hints=RULES_OBJECT_TYPES,
                book_hints=("core rules",),
            ),
        )
    subject_source = resolved.subject or decision.subject or researchable_subject_text(content)
    subject_terms = (
        ()
        if decision.turn_kind == "scene_prep"
        else subject_terms_from_text(subject_source)
    )
    if not subject_terms:
        subject_terms = tuple(meaningful_tokens(content)[:4])
    if decision.turn_kind == "scene_prep":
        subject_terms = ()
    kind: requirement_contract.RequirementKind = (
        "supporting_context"
        if decision.turn_kind in {"lore_lookup", "scene_prep"}
        else "rules_topic"
    )
    return (
        requirement_contract.RequirementSpec(
            id=requirement_id(kind, subject_terms),
            kind=kind,
            query=content.strip(),
            subject_terms=subject_terms,
            optional_terms=optional_terms_from_content(content, subject_terms),
            object_type_hints=(),
        ),
    )


def build_research_plan(
    *,
    research_run_id: str,
    content: str,
    decision: turn_contract.TurnDecision,
    resolved: context_resolution.ResolvedResearchRequest,
) -> agent_planning.ResearchPlan:
    specs = plan_requirements(content, decision=decision, resolved=resolved)
    requirements = tuple(
        requirement_contract.to_evidence_requirement(spec) for spec in specs
    )
    subject_terms = requirements[0].subject.include_terms if requirements else ()
    subject_text = " ".join(subject_terms) or resolved.subject
    planned_actions = tuple(planned_action_for_spec(spec, resolved=resolved) for spec in specs[:1])
    return agent_planning.ResearchPlan(
        id=chat_store.new_id("plan"),
        research_run_id=research_run_id,
        revision=1,
        intent=resolved.intent,  # type: ignore[arg-type]
        plan_summary=f"Find accepted local evidence for {content.strip()}.",
        subject=agent_planning.SubjectConstraint(
            canonical=subject_text,
            surface=subject_text,
            include_terms=subject_terms,
            exclude_terms=(),
            book_title_hints=(),
            page_hints=(),
            notes="app-owned deterministic plan",
        ),
        requirements=requirements,
        planned_actions=planned_actions,
        provider_call_id=None,
        status="accepted",
    )


def normalize_provider_plan(
    plan: agent_planning.ResearchPlan,
) -> agent_planning.ResearchPlan:
    requirements = tuple(normalize_requirement(requirement) for requirement in plan.requirements)
    return replace(
        plan,
        subject=normalize_subject_constraint(plan.subject),
        requirements=requirements,
        planned_actions=tuple(
            normalize_planned_action(action, requirements=requirements)
            for action in plan.planned_actions
        ),
    )


def normalize_requirement(
    requirement: agent_planning.EvidenceRequirement,
) -> agent_planning.EvidenceRequirement:
    subject = normalize_subject_constraint(requirement.subject)
    subject_terms = tuple(term.casefold() for term in subject.include_terms)
    required_terms = tuple(
        term
        for term in requirement.required_terms
        if required_term_survives_normalization(term, subject_terms)
    )
    return replace(
        requirement,
        subject=subject,
        required_terms=required_terms,
        object_type_hints=normalize_object_type_hints(requirement.object_type_hints),
    )


def normalize_subject_constraint(
    subject: agent_planning.SubjectConstraint,
) -> agent_planning.SubjectConstraint:
    source = subject.canonical or subject.surface or " ".join(subject.include_terms)
    essential_terms = evidence_policy.essential_subject_terms(source)
    if not essential_terms:
        return subject
    essential_text = " ".join(essential_terms)
    return agent_planning.SubjectConstraint(
        canonical=essential_text,
        surface=subject.surface or essential_text,
        include_terms=essential_terms,
        exclude_terms=subject.exclude_terms,
        book_title_hints=subject.book_title_hints,
        page_hints=subject.page_hints,
        notes=subject.notes,
    )


def normalize_planned_action(
    action: agent_planning.PlannedAction,
    *,
    requirements: tuple[agent_planning.EvidenceRequirement, ...],
) -> agent_planning.PlannedAction:
    if action.requirement_id is None:
        return action
    requirement = next(
        (
            candidate
            for candidate in requirements
            if candidate.id == action.requirement_id
        ),
        None,
    )
    if requirement is None:
        return action
    arguments = dict(action.arguments)
    if requirement.subject.canonical:
        arguments["subject"] = requirement.subject.canonical
        arguments["include_terms"] = list(requirement.subject.include_terms)
    arguments["object_type_hints"] = list(requirement.object_type_hints)
    return replace(action, arguments=arguments)


def planned_action_for_spec(
    spec: requirement_contract.RequirementSpec,
    *,
    resolved: context_resolution.ResolvedResearchRequest | None = None,
) -> agent_planning.PlannedAction:
    if spec.kind == "page_reference":
        return agent_planning.PlannedAction(
            tool_name="open_page",
            requirement_id=spec.id,
            purpose=f"Open checked source page for {spec.id}.",
            arguments={
                "requirement_id": spec.id,
                "book_id": resolved.active_book_id if resolved is not None else None,
                "book_title_hint": spec.book_hints[0] if spec.book_hints else None,
                "printed_page_label": spec.page_hints[0] if spec.page_hints else None,
                "pdf_page_number": None,
                "subject_hint": " ".join(spec.subject_terms) or None,
                "intent": "source_navigation",
            },
        )
    return agent_planning.PlannedAction(
        tool_name="search_library",
        requirement_id=spec.id,
        purpose=f"Search checked books for {spec.id}.",
        arguments={
            "requirement_id": spec.id,
            "query": spec.query,
            "intent": "statline_lookup" if spec.kind == "statline" else "rules_lookup",
            "subject": " ".join(spec.subject_terms) or None,
            "limit": 8,
            "include_terms": list(spec.subject_terms),
            "exclude_terms": [],
            "object_type_hints": list(spec.object_type_hints),
            "book_title_hints": list(spec.book_hints),
            "page_hints": list(spec.page_hints),
        },
    )


def subject_terms_from_text(text: str | None) -> tuple[str, ...]:
    return evidence_policy.essential_subject_terms(text)


def statline_subject_groups(text: str | None) -> tuple[tuple[str, ...], ...]:
    if text is None:
        return ((),)
    cleaned = re.sub(
        r"\b(stats?|statlines?|profiles?)\b",
        " ",
        text.casefold(),
    )
    groups: list[tuple[str, ...]] = []
    for part in re.split(r"\b(?:and|with|versus|vs)\b|[,;/]", cleaned):
        terms = tuple(
            term
            for term in subject_terms_from_text(part)
            if term not in STATLINE_REQUEST_FILLER
        )
        if terms:
            groups.append(terms)
    if groups:
        return tuple(groups)
    return (subject_terms_from_text(text),)


def has_statline_comparison_signal(content: str) -> bool:
    normalized = content.casefold()
    return bool(re.search(r"\b(?:and|with|versus|vs)\b|[,;/]", normalized))


def researchable_subject_text(content: str) -> str:
    if FOLLOWUP_CONTEXT_MARKER not in content:
        return content
    return content.split(FOLLOWUP_CONTEXT_MARKER, 1)[1]


def optional_terms_from_content(
    content: str,
    subject_terms: tuple[str, ...],
) -> tuple[str, ...]:
    subject_set = set(subject_terms)
    return tuple(
        token
        for token in meaningful_tokens(content)
        if token not in subject_set
        and token not in evidence_policy.PROVIDER_STRUCTURAL_FILLER_TERMS
    )[:8]


def required_term_survives_normalization(
    term: str,
    subject_terms: tuple[str, ...],
) -> bool:
    essential = evidence_policy.essential_subject_terms(term)
    if not essential:
        return False
    return not all(token in subject_terms for token in essential)


def normalize_object_type_hints(values: tuple[str, ...]) -> tuple[str, ...]:
    allowed = {
        "glossary_entry",
        "index_entry",
        "monster_profile",
        "npc_profile",
        "page_fallback",
        "rule_section",
        "source_object",
        "stat_block",
        "table",
        "table_row",
    }
    normalized: list[str] = []
    for value in values:
        key = "_".join(re.findall(r"[a-z0-9]+", value.casefold()))
        if key in allowed and key not in normalized:
            normalized.append(key)
    return tuple(normalized)


def is_hit_location_and_armor_query(content: str) -> bool:
    tokens = set(meaningful_tokens(content))
    has_hit_location = "hit" in tokens and "location" in tokens
    has_armor_location = bool(tokens.intersection({"armor", "armour"})) and (
        "location" in tokens
    )
    return has_hit_location and has_armor_location


def requirement_id(prefix: str, subject_terms: tuple[str, ...]) -> str:
    raw = "_".join((prefix, *subject_terms)) if subject_terms else prefix
    slug = re.sub(r"[^a-z0-9_]+", "_", raw.casefold()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    if not slug or not slug[0].isalpha():
        slug = f"req_{slug}" if slug else "requirement"
    if len(slug) < 2:
        slug = f"{slug}_requirement"
    return slug[:64]


def query_from_terms(terms: tuple[str, ...]) -> str:
    return " ".join(term for term in terms if term).strip()
