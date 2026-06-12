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


def validate_rules_entry_payload(
    payload: Mapping[str, Any],
) -> ContractValidationResult:
    data = cloned_payload(payload)
    issues = []
    if data.get("schema_version") != 2:
        issues.append(issue("invalid_schema_version", "schema_version must be 2"))
    if data.get("object_shape") != "rules_entry":
        issues.append(issue("invalid_object_shape", "expected rules_entry"))
    required_identity_name(data, issues)
    require_source(data, issues)
    entry = required_mapping(data, "entry", issues)
    has_body = (
        has_text(entry.get("description"))
        or has_nonempty_list(entry.get("body_sections"))
        or has_nonempty_list(entry.get("child_table_refs"))
    )
    if not has_body:
        issues.append(issue("rules_entry_missing_body", "rules entry body is required"))
    return result(data, issues)
