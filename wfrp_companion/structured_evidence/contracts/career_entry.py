from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from wfrp_companion.structured_evidence.contracts.base import (
    ContractValidationResult,
    cloned_payload,
    issue,
    required_identity_name,
    required_mapping,
    require_source,
    result,
)


def validate_career_entry_payload(
    payload: Mapping[str, Any],
) -> ContractValidationResult:
    data = cloned_payload(payload)
    issues = []
    if data.get("schema_version") != 2:
        issues.append(issue("invalid_schema_version", "schema_version must be 2"))
    if data.get("object_shape") != "career_entry":
        issues.append(issue("invalid_object_shape", "expected career_entry"))
    required_identity_name(data, issues)
    require_source(data, issues)
    career = required_mapping(data, "career", issues)
    advance_scheme = career.get("advance_scheme")
    if not isinstance(advance_scheme, Mapping):
        issues.append(
            issue("career_missing_advance_scheme", "career advance scheme is required")
        )
    return result(data, issues)
