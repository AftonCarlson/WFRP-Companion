from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


MAIN_PROFILE_FIELDS = ("ws", "bs", "s", "t", "ag", "int", "wp", "fel")
SECONDARY_PROFILE_FIELDS = ("a", "w", "sb", "tb", "m", "mag", "ip", "fp")
FOLLOWUP_FIELDS = (
    "skills",
    "talents",
    "traits",
    "special_rules",
    "weapons",
    "armour",
    "trappings",
)
RANGE_RE = re.compile(r"(?P<start>\d{1,3}|0?0)\s*[-\u2010-\u2014]\s*(?P<end>\d{1,3}|0?0)")


def range_suspicious_flags(range_values: Sequence[str | None]) -> tuple[str, ...]:
    ranges = [_parse_range(value) for value in range_values if value]
    parsed = sorted(value for value in ranges if value is not None)
    if len(parsed) < 2:
        return ()
    has_gap = False
    has_overlap = False
    previous_end = parsed[0][1]
    for start, end in parsed[1:]:
        if start <= previous_end:
            has_overlap = True
        elif start > previous_end + 1:
            has_gap = True
        previous_end = max(previous_end, end)
    flags: list[str] = []
    if has_gap:
        flags.append("range_gap")
    if has_overlap:
        flags.append("range_overlap")
    return tuple(flags)


def profile_suspicious_flags(payload: Mapping[str, Any]) -> tuple[str, ...]:
    profile = payload.get("profile")
    if not isinstance(profile, Mapping):
        return ("profile_missing_main_fields", "profile_missing_secondary_fields")
    flags: list[str] = []
    main_profile = profile.get("main_profile")
    if not _has_all_fields(main_profile, MAIN_PROFILE_FIELDS):
        flags.append("profile_missing_main_fields")
    secondary_profile = profile.get("secondary_profile")
    if not _has_all_fields(secondary_profile, SECONDARY_PROFILE_FIELDS):
        flags.append("profile_missing_secondary_fields")
    if not all(_has_list_value(profile.get(field)) for field in FOLLOWUP_FIELDS):
        flags.append("profile_followup_uncertain")
    return tuple(flags)


def _parse_range(value: str) -> tuple[int, int] | None:
    match = RANGE_RE.search(value)
    if match is None:
        return None
    start = _parse_roll_value(match.group("start"))
    end = _parse_roll_value(match.group("end"))
    if start > end:
        return None
    return start, end


def _parse_roll_value(value: str) -> int:
    parsed = int(value)
    return 100 if parsed == 0 else parsed


def _has_all_fields(value: object, fields: tuple[str, ...]) -> bool:
    if not isinstance(value, Mapping):
        return False
    return all(value.get(field) is not None for field in fields)


def _has_list_value(value: object) -> bool:
    return isinstance(value, list) and bool(value)
