from __future__ import annotations

from wfrp_companion.structured_evidence.contracts.career_entry import (
    validate_career_entry_payload,
)


def career_entry_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 2,
        "object_shape": "career_entry",
        "identity": {"name_raw": "Synthetic Lamplighter"},
        "source": {
            "book_id": "synthetic-book",
            "text_snapshot_sha256": "snapshot",
        },
        "career": {
            "description": "Synthetic career description.",
            "advance_scheme": {
                "main_profile": {
                    "ws": "+5%",
                    "bs": "-",
                    "s": "+5%",
                    "t": "-",
                    "ag": "+10%",
                    "int": "+5%",
                    "wp": "+5%",
                    "fel": "+5%",
                },
                "secondary_profile": {
                    "a": "-",
                    "w": "+2",
                    "sb": "-",
                    "tb": "-",
                    "m": "-",
                    "mag": "-",
                    "ip": "-",
                    "fp": "-",
                },
            },
            "skills": ["Synthetic Skill"],
            "talents": ["Synthetic Talent"],
            "trappings": ["Synthetic Trapping"],
            "career_entries": ["Synthetic Entry"],
            "career_exits": ["Synthetic Exit"],
            "notes": [],
        },
        "provenance": {"field_confidence": {}},
    }
    payload.update(overrides)
    return payload


def test_career_entry_accepts_advance_scheme() -> None:
    result = validate_career_entry_payload(career_entry_payload())

    assert result.ok
    assert result.payload["identity"]["name_normalized"] == "synthetic lamplighter"
    assert result.payload["career"]["advance_scheme"]["main_profile"]["ag"] == "+10%"


def test_career_entry_rejects_missing_advance_scheme() -> None:
    payload = career_entry_payload(career={"skills": ["Synthetic Skill"]})

    result = validate_career_entry_payload(payload)

    assert not result.ok
    assert "career_missing_advance_scheme" in result.issue_codes


def test_career_entry_rejects_label_identity() -> None:
    payload = career_entry_payload(identity={"name_raw": "Career: Bodyguard"})

    result = validate_career_entry_payload(payload)

    assert not result.ok
    assert "identity_is_label" in result.issue_codes


def test_career_entry_rejects_invalid_schema_and_shape() -> None:
    payload = career_entry_payload(schema_version=1, object_shape="profile_card")

    result = validate_career_entry_payload(payload)

    assert not result.ok
    assert "invalid_schema_version" in result.issue_codes
    assert "invalid_object_shape" in result.issue_codes
