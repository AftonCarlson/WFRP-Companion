from __future__ import annotations

from wfrp_companion.structured_evidence.suspicion import (
    profile_suspicious_flags,
    range_suspicious_flags,
)


def test_range_suspicion_flags_gaps_and_overlaps() -> None:
    assert range_suspicious_flags(["01-10", "11-20"]) == ()
    assert range_suspicious_flags(["01-10", "12-20"]) == ("range_gap",)
    assert range_suspicious_flags(["01-15", "10-20"]) == ("range_overlap",)
    assert range_suspicious_flags(["not a range"]) == ()
    assert range_suspicious_flags(["20-10"]) == ()


def test_profile_suspicion_flags_missing_stat_and_followup_fields() -> None:
    payload = {
        "profile": {
            "main_profile": {"ws": 35, "bs": 35},
            "secondary_profile": {"a": 1},
            "skills": [],
            "talents": ["Synthetic Talent"],
            "traits": [],
            "special_rules": [],
            "weapons": [],
            "armour": [],
            "trappings": [],
            "notes": [],
        }
    }

    assert profile_suspicious_flags(payload) == (
        "profile_missing_main_fields",
        "profile_missing_secondary_fields",
        "profile_followup_uncertain",
    )


def test_profile_suspicion_flags_fail_closed_for_missing_profile_object() -> None:
    assert profile_suspicious_flags({}) == (
        "profile_missing_main_fields",
        "profile_missing_secondary_fields",
    )
    assert profile_suspicious_flags({"profile": {"main_profile": []}}) == (
        "profile_missing_main_fields",
        "profile_missing_secondary_fields",
        "profile_followup_uncertain",
    )


def test_profile_suspicion_flags_accept_complete_profile() -> None:
    payload = {
        "profile": {
            "main_profile": {
                "ws": 35,
                "bs": 35,
                "s": 35,
                "t": 45,
                "ag": 25,
                "int": 25,
                "wp": 30,
                "fel": 20,
            },
            "secondary_profile": {
                "a": 1,
                "w": 12,
                "sb": 3,
                "tb": 4,
                "m": 4,
                "mag": 0,
                "ip": 0,
                "fp": 0,
            },
            "skills": ["Intimidate"],
            "talents": ["Menacing"],
            "traits": ["Synthetic Trait"],
            "special_rules": ["Synthetic Rule"],
            "weapons": ["Choppa"],
            "armour": ["Leather"],
            "trappings": ["Teeth"],
        }
    }

    assert profile_suspicious_flags(payload) == ()
