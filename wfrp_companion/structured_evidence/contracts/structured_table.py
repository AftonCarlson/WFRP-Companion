from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from wfrp_companion.structured_evidence.contracts.base import (
    ContractValidationResult,
    cloned_payload,
    has_text,
    issue,
    normalize_identity,
    required_mapping,
    require_source,
    result,
)

TABLE_KINDS = frozenset(
    {
        "lookup",
        "roll_table",
        "modifier_matrix",
        "grouped_matrix",
        "profile_stat_grid",
        "embedded_child",
        "context_random",
        "unknown",
    }
)


def validate_structured_table_payload(
    payload: Mapping[str, Any],
) -> ContractValidationResult:
    data = cloned_payload(payload)
    issues = []
    if data.get("schema_version") != 2:
        issues.append(issue("invalid_schema_version", "schema_version must be 2"))
    if data.get("object_shape") != "structured_table":
        issues.append(issue("invalid_object_shape", "expected structured_table"))
    table_kind = data.get("table_kind")
    if table_kind not in TABLE_KINDS:
        issues.append(issue("invalid_table_kind", "table_kind is not supported"))
    _normalize_title(data, issues)
    require_source(data, issues)
    scope = required_mapping(data, "scope", issues)
    if not has_text(scope.get("scope_kind")) or not has_text(scope.get("scope_value")):
        issues.append(issue("scope_required", "table scope is required"))
    structure = required_mapping(data, "structure", issues)
    if not _has_real_cells(structure):
        issues.append(issue("missing_required_cells", "table rows must include real cells"))
    if table_kind == "embedded_child" and not isinstance(data.get("parent_ref"), Mapping):
        issues.append(
            issue("embedded_table_missing_parent", "embedded child tables require parent_ref")
        )
    return result(data, issues)


def _normalize_title(data: dict[str, Any], issues: list[Any]) -> None:
    identity = required_mapping(data, "identity", issues)
    title_raw = identity.get("title_raw")
    if not isinstance(title_raw, str) or not title_raw.strip():
        issues.append(issue("identity_missing", "table title is required"))
    else:
        identity["title_normalized"] = normalize_identity(title_raw)
    data["identity"] = identity


def _has_real_cells(structure: Mapping[str, Any]) -> bool:
    rows = structure.get("rows")
    if not isinstance(rows, list):
        return False
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        cells = row.get("cells")
        if isinstance(cells, Mapping) and any(has_text(value) for value in cells.values()):
            return True
    return False
