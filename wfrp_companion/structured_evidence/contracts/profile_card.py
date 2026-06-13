from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from wfrp_companion.structured_evidence.contracts.base import (
    ContractValidationResult,
    cloned_payload,
    has_nonempty_list,
    has_text,
    issue,
    required_identity_name,
    required_mapping,
    require_source,
    result,
)

MAIN_PROFILE_FIELDS = ("ws", "bs", "s", "t", "ag", "int", "wp", "fel")
SECONDARY_PROFILE_FIELDS = ("a", "w", "sb", "tb", "m", "mag", "ip", "fp")
PROFILE_KINDS = frozenset(
    {"npc", "monster", "enemy_group", "named_npc", "generic_npc", "unknown"}
)
FOLLOWUP_LIST_FIELDS = (
    "skills",
    "talents",
    "traits",
    "special_rules",
    "weapons",
    "armour",
    "trappings",
    "notes",
)


def validate_profile_card_payload(
    payload: Mapping[str, Any],
) -> ContractValidationResult:
    data = cloned_payload(payload)
    issues = []
    if data.get("schema_version") != 2:
        issues.append(issue("invalid_schema_version", "schema_version must be 2"))
    if data.get("object_shape") != "profile_card":
        issues.append(issue("invalid_object_shape", "expected profile_card"))
    required_identity_name(data, issues)
    profile_kind = data.get("profile_kind")
    if profile_kind not in PROFILE_KINDS:
        issues.append(issue("invalid_profile_kind", "profile_kind is not supported"))
    require_source(data, issues)
    provenance = required_mapping(data, "provenance", issues)
    if not isinstance(provenance.get("field_confidence"), Mapping):
        issues.append(
            issue("field_provenance_missing", "profile field provenance is required")
        )
    profile = required_mapping(data, "profile", issues)
    has_stat_grid = _has_complete_stat_grid(profile)
    has_followups = _has_followup_fields(profile)
    if not has_stat_grid:
        issues.append(issue("profile_missing_stat_grid", "profile stat grid is incomplete"))
    if not has_stat_grid and not has_followups:
        issues.append(
            issue("profile_missing_followup_fields", "profile follow-up fields are missing")
        )
    return result(data, issues)


def _has_complete_stat_grid(profile: Mapping[str, Any]) -> bool:
    main_profile = profile.get("main_profile")
    secondary_profile = profile.get("secondary_profile")
    return _has_int_fields(main_profile, MAIN_PROFILE_FIELDS) and _has_int_fields(
        secondary_profile,
        SECONDARY_PROFILE_FIELDS,
    )


def _has_int_fields(value: object, field_names: tuple[str, ...]) -> bool:
    if not isinstance(value, Mapping):
        return False
    return all(isinstance(value.get(field_name), int) for field_name in field_names)


def _has_followup_fields(profile: Mapping[str, Any]) -> bool:
    if any(has_text(profile.get(field_name)) for field_name in ("race", "career", "description")):
        return True
    if any(has_nonempty_list(profile.get(field_name)) for field_name in FOLLOWUP_LIST_FIELDS):
        return True
    armour_points = profile.get("armour_points")
    return isinstance(armour_points, Mapping) and bool(armour_points)
