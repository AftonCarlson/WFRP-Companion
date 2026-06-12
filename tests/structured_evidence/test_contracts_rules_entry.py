from __future__ import annotations

from wfrp_companion.structured_evidence.contracts.rules_entry import (
    validate_rules_entry_payload,
)


def rules_entry_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 2,
        "object_shape": "rules_entry",
        "entry_kind": "mutation",
        "identity": {"name_raw": "Synthetic Entry"},
        "source": {
            "book_id": "synthetic-book",
            "text_snapshot_sha256": "snapshot",
        },
        "entry": {
            "description": "Synthetic entry description.",
            "body_sections": ["Synthetic section."],
            "child_table_refs": [
                {"table_kind": "embedded_child", "identity": "synthetic child"}
            ],
            "page_refs": [],
            "notes": [],
        },
        "provenance": {"field_confidence": {}},
    }
    payload.update(overrides)
    return payload


def test_rules_entry_accepts_child_table_refs() -> None:
    result = validate_rules_entry_payload(rules_entry_payload())

    assert result.ok
    assert result.payload["identity"]["name_normalized"] == "synthetic entry"
    assert result.payload["entry"]["child_table_refs"][0]["identity"] == "synthetic child"


def test_rules_entry_rejects_empty_body_without_child_tables() -> None:
    payload = rules_entry_payload(
        entry={
            "description": "",
            "body_sections": [],
            "child_table_refs": [],
            "page_refs": [],
            "notes": [],
        }
    )

    result = validate_rules_entry_payload(payload)

    assert not result.ok
    assert "rules_entry_missing_body" in result.issue_codes


def test_rules_entry_rejects_invalid_schema_and_shape() -> None:
    payload = rules_entry_payload(schema_version=1, object_shape="profile_card")

    result = validate_rules_entry_payload(payload)

    assert not result.ok
    assert "invalid_schema_version" in result.issue_codes
    assert "invalid_object_shape" in result.issue_codes
