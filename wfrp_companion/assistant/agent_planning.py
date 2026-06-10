from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from wfrp_companion.assistant import provider


JsonObject = dict[str, object]
ResearchIntent = Literal[
    "rules_lookup",
    "statline_lookup",
    "source_navigation",
    "lore_lookup",
    "scene_prep",
]
RequirementType = Literal[
    "topical_evidence",
    "statline_evidence",
    "page_evidence",
    "source_object_evidence",
]
StructuredLookupPolicy = Literal[
    "required",
    "allowed",
    "supporting_only",
    "forbidden",
    "not_primary",
]
PlanStatus = Literal["proposed", "accepted", "rejected", "superseded"]
ToolName = Literal[
    "search_library",
    "open_page",
    "lookup_source_object",
    "finish_research",
]


RESEARCH_INTENTS = {
    "rules_lookup",
    "statline_lookup",
    "source_navigation",
    "lore_lookup",
    "scene_prep",
}
REQUIREMENT_TYPES = {
    "topical_evidence",
    "statline_evidence",
    "page_evidence",
    "source_object_evidence",
}
STRUCTURED_LOOKUP_POLICIES = {
    "required",
    "allowed",
    "supporting_only",
    "forbidden",
    "not_primary",
}
TOOL_NAMES = {
    "search_library",
    "open_page",
    "lookup_source_object",
    "finish_research",
}
REQUIREMENT_ID_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"
REQUIREMENT_ID_RE = re.compile(REQUIREMENT_ID_PATTERN)
MAX_TERMS = 12
MAX_TEXT_CHARS = 240
MAX_PLAN_SUMMARY_CHARS = 500


class PlanValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SubjectConstraint:
    canonical: str | None
    surface: str | None
    include_terms: tuple[str, ...] = ()
    exclude_terms: tuple[str, ...] = ()
    book_title_hints: tuple[str, ...] = ()
    page_hints: tuple[str, ...] = ()
    notes: str | None = None

    def to_json(self) -> JsonObject:
        return {
            "canonical": self.canonical,
            "surface": self.surface,
            "include_terms": list(self.include_terms),
            "exclude_terms": list(self.exclude_terms),
            "book_title_hints": list(self.book_title_hints),
            "page_hints": list(self.page_hints),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class EvidenceRequirement:
    id: str
    requirement_type: RequirementType
    subject: SubjectConstraint
    required_terms: tuple[str, ...] = ()
    excluded_terms: tuple[str, ...] = ()
    object_type_hints: tuple[str, ...] = ()
    structured_lookup_policy: StructuredLookupPolicy = "not_primary"
    structured_object_shape_hints: tuple[str, ...] = ()
    structured_content_kind_hints: tuple[str, ...] = ()
    structured_entity_kind_hints: tuple[str, ...] = ()
    table_number_hints: tuple[str, ...] = ()
    min_accepted_hits: int = 1
    required: bool = True

    def to_json(self) -> JsonObject:
        return {
            "id": self.id,
            "requirement_type": self.requirement_type,
            "subject": self.subject.to_json(),
            "required_terms": list(self.required_terms),
            "excluded_terms": list(self.excluded_terms),
            "object_type_hints": list(self.object_type_hints),
            "structured_lookup_policy": self.structured_lookup_policy,
            "structured_object_shape_hints": list(
                self.structured_object_shape_hints
            ),
            "structured_content_kind_hints": list(
                self.structured_content_kind_hints
            ),
            "structured_entity_kind_hints": list(self.structured_entity_kind_hints),
            "table_number_hints": list(self.table_number_hints),
            "min_accepted_hits": self.min_accepted_hits,
            "required": self.required,
        }


@dataclass(frozen=True)
class PlannedAction:
    tool_name: ToolName
    requirement_id: str | None
    purpose: str
    arguments: JsonObject

    def to_json(self) -> JsonObject:
        return {
            "tool_name": self.tool_name,
            "requirement_id": self.requirement_id,
            "purpose": self.purpose,
            "arguments": self.arguments,
        }


@dataclass(frozen=True)
class ResearchPlan:
    id: str
    research_run_id: str
    revision: int
    intent: ResearchIntent
    plan_summary: str
    subject: SubjectConstraint
    requirements: tuple[EvidenceRequirement, ...]
    planned_actions: tuple[PlannedAction, ...] = ()
    provider_call_id: str | None = None
    status: PlanStatus = "accepted"
    validation_errors: tuple[str, ...] = ()

    def to_json(self) -> JsonObject:
        return {
            "intent": self.intent,
            "plan_summary": self.plan_summary,
            "subject": self.subject.to_json(),
            "requirements": [requirement.to_json() for requirement in self.requirements],
            "planned_actions": [action.to_json() for action in self.planned_actions],
        }


def parse_research_plan(
    payload: Mapping[str, object],
    *,
    research_run_id: str,
    plan_id: str,
    revision: int,
    provider_call_id: str | None = None,
    status: PlanStatus = "accepted",
) -> ResearchPlan:
    if revision < 1:
        raise PlanValidationError("revision must be at least 1")
    intent = required_string(payload, "intent")
    if intent not in RESEARCH_INTENTS:
        raise PlanValidationError(f"unknown intent: {intent}")
    plan_summary = bounded_required_string(
        payload,
        "plan_summary",
        max_chars=MAX_PLAN_SUMMARY_CHARS,
    )
    subject = parse_subject_constraint(required_object(payload, "subject"))
    requirements_payload = required_list(payload, "requirements")
    if not requirements_payload:
        raise PlanValidationError("requirements must not be empty")
    if len(requirements_payload) > 6:
        raise PlanValidationError("requirements may include at most 6 items")
    requirements = tuple(
        parse_requirement(item)
        for item in objects_from_sequence(requirements_payload, "requirements")
    )
    requirement_ids: set[str] = set()
    for requirement in requirements:
        if requirement.id in requirement_ids:
            raise PlanValidationError(f"duplicate requirement id: {requirement.id}")
        requirement_ids.add(requirement.id)

    planned_actions_payload = required_list(payload, "planned_actions")
    if len(planned_actions_payload) > 4:
        raise PlanValidationError("planned_actions may include at most 4 items")
    planned_actions = tuple(
        parse_planned_action(item, requirement_ids=requirement_ids)
        for item in objects_from_sequence(planned_actions_payload, "planned_actions")
    )
    return ResearchPlan(
        id=plan_id,
        research_run_id=research_run_id,
        revision=revision,
        intent=intent,  # type: ignore[arg-type]
        plan_summary=plan_summary,
        subject=subject,
        requirements=requirements,
        planned_actions=planned_actions,
        provider_call_id=provider_call_id,
        status=status,
    )


def parse_subject_constraint(payload: Mapping[str, object]) -> SubjectConstraint:
    return SubjectConstraint(
        canonical=optional_bounded_string(payload, "canonical"),
        surface=optional_bounded_string(payload, "surface"),
        include_terms=terms_tuple(payload.get("include_terms"), "include_terms"),
        exclude_terms=terms_tuple(payload.get("exclude_terms"), "exclude_terms"),
        book_title_hints=terms_tuple(payload.get("book_title_hints"), "book_title_hints"),
        page_hints=terms_tuple(payload.get("page_hints"), "page_hints"),
        notes=optional_bounded_string(payload, "notes"),
    )


def parse_requirement(payload: Mapping[str, object]) -> EvidenceRequirement:
    requirement_id = required_string(payload, "id")
    if not REQUIREMENT_ID_RE.match(requirement_id):
        raise PlanValidationError(f"invalid requirement id: {requirement_id}")
    requirement_type = required_string(payload, "requirement_type")
    if requirement_type not in REQUIREMENT_TYPES:
        raise PlanValidationError(f"unknown requirement_type: {requirement_type}")
    structured_lookup_policy = str(
        payload.get("structured_lookup_policy", "not_primary")
    )
    if structured_lookup_policy not in STRUCTURED_LOOKUP_POLICIES:
        raise PlanValidationError(
            f"unknown structured_lookup_policy: {structured_lookup_policy}"
        )
    min_accepted_hits = required_int(payload, "min_accepted_hits")
    if min_accepted_hits < 1 or min_accepted_hits > 6:
        raise PlanValidationError("min_accepted_hits must be between 1 and 6")
    required_value = payload.get("required")
    if not isinstance(required_value, bool):
        raise PlanValidationError("required must be a boolean")
    return EvidenceRequirement(
        id=requirement_id,
        requirement_type=requirement_type,  # type: ignore[arg-type]
        subject=parse_subject_constraint(required_object(payload, "subject")),
        required_terms=terms_tuple(payload.get("required_terms"), "required_terms"),
        excluded_terms=terms_tuple(payload.get("excluded_terms"), "excluded_terms"),
        object_type_hints=terms_tuple(
            payload.get("object_type_hints"),
            "object_type_hints",
            max_items=8,
        ),
        structured_lookup_policy=structured_lookup_policy,  # type: ignore[arg-type]
        structured_object_shape_hints=terms_tuple(
            payload.get("structured_object_shape_hints"),
            "structured_object_shape_hints",
            max_items=4,
        ),
        structured_content_kind_hints=terms_tuple(
            payload.get("structured_content_kind_hints"),
            "structured_content_kind_hints",
            max_items=8,
        ),
        structured_entity_kind_hints=terms_tuple(
            payload.get("structured_entity_kind_hints"),
            "structured_entity_kind_hints",
            max_items=8,
        ),
        table_number_hints=terms_tuple(
            payload.get("table_number_hints"),
            "table_number_hints",
            max_items=8,
        ),
        min_accepted_hits=min_accepted_hits,
        required=required_value,
    )


def parse_planned_action(
    payload: Mapping[str, object],
    *,
    requirement_ids: set[str],
) -> PlannedAction:
    tool_name = required_string(payload, "tool_name")
    if tool_name not in TOOL_NAMES:
        raise PlanValidationError(f"unknown tool: {tool_name}")
    requirement_id = optional_bounded_string(payload, "requirement_id")
    if requirement_id is not None and requirement_id not in requirement_ids:
        raise PlanValidationError(f"unknown requirement: {requirement_id}")
    purpose = bounded_required_string(payload, "purpose", max_chars=MAX_TEXT_CHARS)
    arguments = required_object(payload, "arguments")
    reject_oversized_argument_text(arguments)
    return PlannedAction(
        tool_name=tool_name,  # type: ignore[arg-type]
        requirement_id=requirement_id,
        purpose=purpose,
        arguments=dict(arguments),
    )


def reject_oversized_argument_text(value: object) -> None:
    if isinstance(value, str):
        if len(value) > MAX_TEXT_CHARS:
            raise PlanValidationError("argument text is too long")
        return
    if isinstance(value, Mapping):
        for child in value.values():
            reject_oversized_argument_text(child)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for child in value:
            reject_oversized_argument_text(child)


def required_object(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise PlanValidationError(f"{key} must be an object")
    return value


def required_list(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise PlanValidationError(f"{key} must be a list")
    return value


def objects_from_sequence(
    values: Sequence[object],
    key: str,
) -> tuple[Mapping[str, object], ...]:
    objects: list[Mapping[str, object]] = []
    for value in values:
        if not isinstance(value, Mapping):
            raise PlanValidationError(f"{key} entries must be objects")
        objects.append(value)
    return tuple(objects)


def required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PlanValidationError(f"{key} must be a non-empty string")
    return value.strip()


def bounded_required_string(
    payload: Mapping[str, object],
    key: str,
    *,
    max_chars: int,
) -> str:
    value = required_string(payload, key)
    if len(value) > max_chars:
        raise PlanValidationError(f"{key} must be at most {max_chars} characters")
    return value


def optional_bounded_string(
    payload: Mapping[str, object],
    key: str,
    *,
    max_chars: int = MAX_TEXT_CHARS,
) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise PlanValidationError(f"{key} must be a string or null")
    stripped = value.strip()
    if not stripped:
        return None
    if len(stripped) > max_chars:
        raise PlanValidationError(f"{key} must be at most {max_chars} characters")
    return stripped


def required_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise PlanValidationError(f"{key} must be an integer")
    return value


def terms_tuple(
    value: object,
    key: str,
    *,
    max_items: int = MAX_TERMS,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise PlanValidationError(f"{key} must be a list")
    if len(value) > max_items:
        raise PlanValidationError(f"{key} may include at most {max_items} items")
    terms: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise PlanValidationError(f"{key} values must be strings")
        term = item.strip()
        if not term:
            continue
        if len(term) > MAX_TEXT_CHARS:
            raise PlanValidationError(f"{key} values must be bounded strings")
        folded = term.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        terms.append(term)
    return tuple(terms)


def planning_tool_definition() -> provider.ProviderToolDefinition:
    return provider.ProviderToolDefinition(
        name="set_research_plan",
        description="Create the bounded research plan before local retrieval tools run.",
        parameters=planning_tool_parameters(),
    )


def planning_tool_parameters() -> dict[str, object]:
    return strict_object(
        {
            "intent": {"type": "string", "enum": sorted(RESEARCH_INTENTS)},
            "plan_summary": bounded_string_schema(
                max_chars=MAX_PLAN_SUMMARY_CHARS,
            ),
            "subject": subject_schema(),
            "requirements": {
                "type": "array",
                "items": requirement_schema(),
                "maxItems": 6,
            },
            "planned_actions": {
                "type": "array",
                "items": planned_action_schema(),
                "maxItems": 4,
            },
        }
    )


def subject_schema() -> dict[str, object]:
    return strict_object(
        {
            "canonical": bounded_string_schema(nullable=True),
            "surface": bounded_string_schema(nullable=True),
            "include_terms": string_array_schema(),
            "exclude_terms": string_array_schema(),
            "book_title_hints": string_array_schema(),
            "page_hints": string_array_schema(),
            "notes": bounded_string_schema(nullable=True),
        }
    )


def requirement_schema() -> dict[str, object]:
    return strict_object(
        {
            "id": requirement_id_schema(),
            "requirement_type": {"type": "string", "enum": sorted(REQUIREMENT_TYPES)},
            "subject": subject_schema(),
            "required_terms": string_array_schema(),
            "excluded_terms": string_array_schema(),
            "object_type_hints": string_array_schema(max_items=8),
            "min_accepted_hits": {"type": "integer", "minimum": 1, "maximum": 6},
            "required": {"type": "boolean"},
        }
    )


def planned_action_schema() -> dict[str, object]:
    return strict_object(
        {
            "tool_name": {"type": "string", "enum": sorted(TOOL_NAMES)},
            "requirement_id": requirement_id_schema(nullable=True),
            "purpose": {"type": "string"},
            "arguments": action_arguments_schema(),
        }
    )


def action_arguments_schema() -> dict[str, object]:
    return strict_object(
        {
            "query": bounded_string_schema(nullable=True),
            "intent": bounded_string_schema(nullable=True),
            "subject": bounded_string_schema(nullable=True),
            "limit": {"type": ["integer", "null"]},
            "book_id": bounded_string_schema(nullable=True),
            "book_title_hint": bounded_string_schema(nullable=True),
            "printed_page_label": bounded_string_schema(nullable=True),
            "pdf_page_number": {"type": ["integer", "null"]},
            "subject_hint": bounded_string_schema(nullable=True),
            "source_object_id": bounded_string_schema(nullable=True),
            "include_terms": string_array_schema(),
            "exclude_terms": string_array_schema(),
            "object_type_hints": string_array_schema(),
            "book_title_hints": string_array_schema(),
            "page_hints": string_array_schema(),
            "status": bounded_string_schema(nullable=True),
            "reason": bounded_string_schema(nullable=True),
            "satisfied_requirement_ids": string_array_schema(max_items=6),
            "unmet_requirement_ids": string_array_schema(max_items=6),
        }
    )


def string_array_schema(*, max_items: int = MAX_TERMS) -> dict[str, object]:
    return {
        "type": "array",
        "items": bounded_string_schema(max_chars=MAX_TEXT_CHARS),
        "maxItems": max_items,
    }


def bounded_string_schema(
    *,
    max_chars: int = MAX_TEXT_CHARS,
    nullable: bool = False,
) -> dict[str, object]:
    return {
        "type": ["string", "null"] if nullable else "string",
        "maxLength": max_chars,
    }


def requirement_id_schema(*, nullable: bool = False) -> dict[str, object]:
    return {
        "type": ["string", "null"] if nullable else "string",
        "pattern": REQUIREMENT_ID_PATTERN,
    }


def strict_object(properties: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
