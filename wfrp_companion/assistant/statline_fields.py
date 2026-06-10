from __future__ import annotations

import re


CORE_STAT_FIELDS = (
    "M",
    "WS",
    "BS",
    "S",
    "T",
    "Ag",
    "Int",
    "WP",
    "Fel",
    "A",
    "W",
    "SB",
    "TB",
    "Mag",
    "IP",
    "FP",
)
MINIMUM_STAT_FIELD_COUNT = 6

STAT_FIELD_RE = re.compile(
    r"(?<![\w'-])"
    r"(WS|BS|Ag|Int|WP|Fel|SB|TB|Mag|IP|FP|M|S|T|A|W)"
    r"(?![\w'-])"
    r"\s*(?:[:=|]|\s)\s*"
    r"(?:[+-]?\d+|[-—])",
    re.IGNORECASE,
)
FIELD_ORDER = {field.casefold(): index for index, field in enumerate(CORE_STAT_FIELDS)}
CANONICAL_FIELD = {field.casefold(): field for field in CORE_STAT_FIELDS}


def extract_stat_fields(text: str) -> tuple[str, ...]:
    fields: list[str] = []
    for match in STAT_FIELD_RE.finditer(text):
        field = CANONICAL_FIELD[match.group(1).casefold()]
        if field not in fields:
            fields.append(field)
    fields.sort(key=lambda field: FIELD_ORDER[field.casefold()])
    return tuple(fields)


def has_sufficient_statline_fields(text: str) -> bool:
    return len(extract_stat_fields(text)) >= MINIMUM_STAT_FIELD_COUNT
