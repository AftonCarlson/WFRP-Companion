from __future__ import annotations

from wfrp_companion.structured_evidence.contracts.structured_table import (
    validate_structured_table_payload,
)


def structured_table_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 2,
        "object_shape": "structured_table",
        "table_kind": "context_random",
        "identity": {
            "title_raw": "Synthetic Random Smells",
            "table_number_raw": None,
        },
        "scope": {
            "scope_kind": "location",
            "scope_value": "Synthetic City",
        },
        "source": {
            "book_id": "synthetic-book",
            "text_snapshot_sha256": "snapshot",
        },
        "structure": {
            "columns": [
                {"key": "roll", "label_raw": "Roll"},
                {"key": "result", "label_raw": "Result"},
            ],
            "rows": [
                {
                    "ordinal": 1,
                    "cells": {"roll": "1", "result": "Synthetic Result"},
                    "raw_text": "1 Synthetic Result",
                }
            ],
            "row_groups": [],
            "footnotes": [],
        },
        "provenance": {"reader_names": ["synthetic_reader"]},
    }
    payload.update(overrides)
    return payload


def test_structured_table_rejects_rows_without_real_cells() -> None:
    payload = structured_table_payload(
        structure={
            "columns": [{"key": "unknown", "label_raw": "Unknown"}],
            "rows": [{"ordinal": 1, "cells": {}, "raw_text": ""}],
            "row_groups": [],
            "footnotes": [],
        }
    )

    result = validate_structured_table_payload(payload)

    assert not result.ok
    assert "missing_required_cells" in result.issue_codes


def test_structured_table_rejects_invalid_contract_fields() -> None:
    payload = structured_table_payload(
        schema_version=1,
        object_shape="profile_card",
        table_kind="unsupported",
        identity={"title_raw": ""},
        scope={},
    )

    result = validate_structured_table_payload(payload)

    assert not result.ok
    assert "invalid_schema_version" in result.issue_codes
    assert "invalid_object_shape" in result.issue_codes
    assert "invalid_table_kind" in result.issue_codes
    assert "identity_missing" in result.issue_codes
    assert "scope_required" in result.issue_codes


def test_structured_table_allows_unnumbered_context_scoped_table() -> None:
    result = validate_structured_table_payload(structured_table_payload())

    assert result.ok
    assert result.payload["identity"]["title_normalized"] == "synthetic random smells"
    assert result.payload["scope"]["scope_kind"] == "location"
    assert result.payload["scope"]["scope_value"] == "Synthetic City"


def test_structured_table_requires_parent_for_embedded_child_table() -> None:
    payload = structured_table_payload(table_kind="embedded_child", parent_ref=None)

    result = validate_structured_table_payload(payload)

    assert not result.ok
    assert "embedded_table_missing_parent" in result.issue_codes


def test_structured_table_allows_embedded_child_table_with_parent() -> None:
    payload = structured_table_payload(
        table_kind="embedded_child",
        parent_ref={"object_shape": "rules_entry", "identity": "synthetic entry"},
        scope={"scope_kind": "parent_object", "scope_value": "synthetic entry"},
    )

    result = validate_structured_table_payload(payload)

    assert result.ok
    assert result.payload["parent_ref"]["identity"] == "synthetic entry"


def test_structured_table_rejects_rows_that_are_not_a_list() -> None:
    payload = structured_table_payload(
        structure={
            "columns": [{"key": "roll", "label_raw": "Roll"}],
            "rows": "not rows",
            "row_groups": [],
            "footnotes": [],
        }
    )

    result = validate_structured_table_payload(payload)

    assert not result.ok
    assert "missing_required_cells" in result.issue_codes


def test_structured_table_skips_malformed_rows_before_real_cells() -> None:
    payload = structured_table_payload(
        structure={
            "columns": [{"key": "roll", "label_raw": "Roll"}],
            "rows": ["bad row", {"ordinal": 2, "cells": {"roll": "2"}}],
            "row_groups": [],
            "footnotes": [],
        }
    )

    result = validate_structured_table_payload(payload)

    assert result.ok
