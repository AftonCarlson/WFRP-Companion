from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from wfrp_companion.assistant import agent_planning


RequirementKind = Literal[
    "rules_topic",
    "statline",
    "page_reference",
    "source_object",
    "supporting_context",
]


@dataclass(frozen=True)
class RequirementSpec:
    id: str
    kind: RequirementKind
    query: str
    subject_terms: tuple[str, ...]
    optional_terms: tuple[str, ...]
    object_type_hints: tuple[str, ...]
    book_hints: tuple[str, ...] = ()
    page_hints: tuple[str, ...] = ()
    structured_lookup_policy: agent_planning.StructuredLookupPolicy = "not_primary"
    structured_object_shape_hints: tuple[str, ...] = ()
    structured_content_kind_hints: tuple[str, ...] = ()
    structured_entity_kind_hints: tuple[str, ...] = ()
    table_number_hints: tuple[str, ...] = ()
    required: bool = True
    min_accepted_hits: int = 1


def to_evidence_requirement(spec: RequirementSpec) -> agent_planning.EvidenceRequirement:
    subject_text = " ".join(spec.subject_terms) or None
    return agent_planning.EvidenceRequirement(
        id=spec.id,
        requirement_type=requirement_type_for_kind(spec.kind),
        subject=agent_planning.SubjectConstraint(
            canonical=subject_text,
            surface=subject_text,
            include_terms=tuple(dict.fromkeys((*spec.subject_terms, *spec.optional_terms))),
            exclude_terms=(),
            book_title_hints=spec.book_hints,
            page_hints=spec.page_hints,
            notes=None,
        ),
        required_terms=(),
        excluded_terms=(),
        object_type_hints=spec.object_type_hints,
        structured_lookup_policy=spec.structured_lookup_policy,
        structured_object_shape_hints=spec.structured_object_shape_hints,
        structured_content_kind_hints=spec.structured_content_kind_hints,
        structured_entity_kind_hints=spec.structured_entity_kind_hints,
        table_number_hints=spec.table_number_hints,
        min_accepted_hits=spec.min_accepted_hits,
        required=spec.required,
    )


def requirement_type_for_kind(
    kind: RequirementKind,
) -> agent_planning.RequirementType:
    if kind == "statline":
        return "statline_evidence"
    if kind == "page_reference":
        return "page_evidence"
    if kind == "source_object":
        return "source_object_evidence"
    return "topical_evidence"
