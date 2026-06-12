from __future__ import annotations

import pytest

from wfrp_companion.structured_evidence.contracts.base import (
    normalize_identity,
    reject_label_identity,
)
from wfrp_companion.structured_evidence.contracts.profile_card import (
    validate_profile_card_payload,
)


MAIN_PROFILE = {
    "ws": 41,
    "bs": 32,
    "s": 35,
    "t": 36,
    "ag": 29,
    "int": 28,
    "wp": 31,
    "fel": 30,
}
SECONDARY_PROFILE = {
    "a": 1,
    "w": 12,
    "sb": 3,
    "tb": 3,
    "m": 4,
    "mag": 0,
    "ip": 0,
    "fp": 0,
}


def profile_card_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 2,
        "object_shape": "profile_card",
        "identity": {
            "name_raw": "Synthetic Road Wardens",
            "aliases": ["synthetic road wardens"],
        },
        "profile_kind": "enemy_group",
        "source": {
            "book_id": "synthetic-book",
            "text_snapshot_sha256": "snapshot",
        },
        "profile": {
            "race": "Human",
            "career": "Roadwarden",
            "description": "Synthetic descriptive fixture text.",
            "main_profile": dict(MAIN_PROFILE),
            "secondary_profile": dict(SECONDARY_PROFILE),
            "skills": ["Synthetic Skill"],
            "talents": ["Synthetic Talent"],
            "traits": [],
            "special_rules": [],
            "weapons": ["Synthetic Weapon"],
            "armour": ["Synthetic Armour"],
            "armour_points": {
                "head": 0,
                "arms": 1,
                "body": 2,
                "legs": 0,
            },
            "trappings": ["Synthetic Trapping"],
            "notes": [],
        },
        "provenance": {"field_confidence": {}},
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    "label_identity",
    (
        "Race: Human",
        "Race",
        "Race:",
        "Career: Bodyguard",
        "Career",
        "Career:",
        "Main Profile",
        "Secondary Profile",
        "Skills",
        "Talents",
        "Armour",
        "Armour Points",
        "Weapons",
        "Trappings",
        "WS BS S T Ag Int WP Fel",
        "A W SB TB M Mag IP FP",
        "Ay Int Fel",
    ),
)
def test_profile_card_rejects_label_identities(label_identity: str) -> None:
    payload = profile_card_payload(identity={"name_raw": label_identity})

    result = validate_profile_card_payload(payload)

    assert not result.ok
    assert "identity_is_label" in result.issue_codes
    assert reject_label_identity(label_identity)


def test_profile_card_accepts_group_identity_with_race_and_career_fields() -> None:
    payload = profile_card_payload(
        identity={
            "name_raw": "Ruggbroder's Bodyguards",
            "aliases": ["ruggbroders bodyguards"],
        },
        profile_kind="enemy_group",
    )

    result = validate_profile_card_payload(payload)

    assert result.ok
    assert result.payload["identity"]["name_normalized"] == "ruggbroders bodyguards"
    assert result.payload["profile"]["race"] == "Human"
    assert result.payload["profile"]["career"] == "Roadwarden"
    assert normalize_identity("Ruggbroder's Bodyguards") == "ruggbroders bodyguards"


def test_profile_card_accepts_followup_lists_without_race_or_career_text() -> None:
    payload = profile_card_payload()
    profile = dict(payload["profile"])  # type: ignore[arg-type]
    profile.update({"race": "", "career": "", "description": ""})
    payload["profile"] = profile

    result = validate_profile_card_payload(payload)

    assert result.ok


def test_profile_card_accepts_complete_stat_grid_without_optional_followups() -> None:
    payload = profile_card_payload()
    profile = dict(payload["profile"])  # type: ignore[arg-type]
    profile.update(
        {
            "race": "",
            "career": "",
            "description": "",
            "skills": [],
            "talents": [],
            "traits": [],
            "special_rules": [],
            "weapons": [],
            "armour": [],
            "armour_points": {},
            "trappings": [],
            "notes": [],
        }
    )
    payload["profile"] = profile

    result = validate_profile_card_payload(payload)

    assert result.ok


def test_profile_card_rejects_missing_stat_grid_and_followup_fields() -> None:
    payload = profile_card_payload(
        profile={
            "main_profile": {key: None for key in MAIN_PROFILE},
            "secondary_profile": {key: None for key in SECONDARY_PROFILE},
            "skills": [],
            "talents": [],
            "traits": [],
            "special_rules": [],
            "weapons": [],
            "armour": [],
            "armour_points": {},
            "trappings": [],
            "notes": [],
            "description": "",
            "race": "",
            "career": "",
        }
    )

    result = validate_profile_card_payload(payload)

    assert not result.ok
    assert "profile_missing_stat_grid" in result.issue_codes
    assert "profile_missing_followup_fields" in result.issue_codes


def test_profile_card_requires_field_provenance() -> None:
    payload = profile_card_payload(provenance={})

    result = validate_profile_card_payload(payload)

    assert not result.ok
    assert "field_provenance_missing" in result.issue_codes


def test_profile_card_rejects_missing_identity_source_and_profile_contract() -> None:
    payload = profile_card_payload(
        schema_version=1,
        identity={},
        profile_kind="unsupported",
        source={},
        profile={},
    )

    result = validate_profile_card_payload(payload)

    assert not result.ok
    assert "invalid_schema_version" in result.issue_codes
    assert "identity_missing" in result.issue_codes
    assert "invalid_profile_kind" in result.issue_codes
    assert "source_book_id_missing" in result.issue_codes
    assert "source_text_snapshot_sha256_missing" in result.issue_codes
    assert "profile_missing_stat_grid" in result.issue_codes


def test_profile_card_rejects_career_entry_payload_shape() -> None:
    payload = {
        "schema_version": 2,
        "object_shape": "career_entry",
        "identity": {"name_raw": "Synthetic Lamplighter"},
        "source": {
            "book_id": "synthetic-book",
            "text_snapshot_sha256": "snapshot",
        },
        "career": {
            "advance_scheme": {"main_profile": {}, "secondary_profile": {}},
            "skills": ["Synthetic Skill"],
            "talents": [],
            "trappings": [],
            "career_entries": [],
            "career_exits": [],
        },
        "provenance": {"field_confidence": {}},
    }

    result = validate_profile_card_payload(payload)

    assert not result.ok
    assert "invalid_object_shape" in result.issue_codes
