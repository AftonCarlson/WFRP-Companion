from __future__ import annotations

import pytest

from wfrp_companion.structured_evidence.contracts import (
    validate_contract_payload,
    validator_for_shape,
)
from wfrp_companion.structured_evidence.contracts.profile_card import (
    validate_profile_card_payload,
)


def test_contract_registry_returns_validator_for_shape() -> None:
    assert validator_for_shape("profile_card") is validate_profile_card_payload


def test_contract_registry_validates_payload_by_object_shape() -> None:
    payload = {
        "schema_version": 2,
        "object_shape": "profile_card",
        "identity": {"name_raw": "Synthetic Profile"},
        "profile_kind": "generic_npc",
        "source": {
            "book_id": "synthetic-book",
            "text_snapshot_sha256": "snapshot",
        },
        "profile": {
            "main_profile": {
                "ws": 30,
                "bs": 30,
                "s": 30,
                "t": 30,
                "ag": 30,
                "int": 30,
                "wp": 30,
                "fel": 30,
            },
            "secondary_profile": {
                "a": 1,
                "w": 10,
                "sb": 3,
                "tb": 3,
                "m": 4,
                "mag": 0,
                "ip": 0,
                "fp": 0,
            },
            "skills": [],
            "talents": [],
            "traits": [],
            "special_rules": [],
            "weapons": [],
            "armour": [],
            "armour_points": {},
            "trappings": [],
            "notes": [],
        },
        "provenance": {"field_confidence": {}},
    }

    result = validate_contract_payload(payload)

    assert result.ok


def test_contract_registry_rejects_unknown_shape() -> None:
    with pytest.raises(ValueError, match="Unsupported structured evidence shape"):
        validator_for_shape("unknown_shape")
