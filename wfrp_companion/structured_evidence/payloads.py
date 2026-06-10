from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def validate_structured_table_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    _expect(data.get("schema_version") == 1, "schema_version must be 1")
    _expect(data.get("object_shape") == "structured_table", "expected structured_table")
    identity = _required_mapping(data, "identity")
    source = _required_mapping(data, "source")
    structure = _required_mapping(data, "structure")
    provenance = _required_mapping(data, "provenance")
    _required_text(identity, "title_normalized")
    _required_text(source, "book_id")
    _required_text(source, "text_snapshot_sha256")
    columns = _required_list(structure, "columns")
    rows = _required_list(structure, "rows")
    _expect(bool(columns), "columns must not be empty")
    _expect(bool(rows), "rows must not be empty")
    _required_list(provenance, "reader_names")
    return data


def validate_profile_bundle_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    _expect(data.get("schema_version") == 1, "schema_version must be 1")
    _expect(data.get("object_shape") == "profile_bundle", "expected profile_bundle")
    identity = _required_mapping(data, "identity")
    source = _required_mapping(data, "source")
    profile = _required_mapping(data, "profile")
    provenance = _required_mapping(data, "provenance")
    _required_text(identity, "name_normalized")
    _required_text(source, "book_id")
    _required_text(source, "text_snapshot_sha256")
    _required_mapping(profile, "main_profile")
    _required_mapping(profile, "secondary_profile")
    for field_name in (
        "skills",
        "talents",
        "traits",
        "special_rules",
        "weapons",
        "armour",
        "trappings",
        "notes",
    ):
        _required_list(profile, field_name)
    _required_mapping(provenance, "field_confidence")
    return data


def payload_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def table_payload_search_text(payload: Mapping[str, Any]) -> str:
    identity = _required_mapping(payload, "identity")
    structure = _required_mapping(payload, "structure")
    parts: list[str] = []
    for key in ("table_number_raw", "title_raw", "title_normalized"):
        value = identity.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    aliases = identity.get("aliases")
    if isinstance(aliases, list):
        parts.extend(alias for alias in aliases if isinstance(alias, str))
    for row in structure.get("rows", []):
        if isinstance(row, Mapping):
            raw_text = row.get("raw_text")
            if isinstance(raw_text, str) and raw_text.strip():
                parts.append(raw_text)
    return " ".join(parts)


def _required_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    _expect(isinstance(value, Mapping), f"{key} must be an object")
    return value


def _required_list(payload: Mapping[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    _expect(isinstance(value, list), f"{key} must be a list")
    return value


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    _expect(isinstance(value, str) and bool(value.strip()), f"{key} is required")
    return value


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)
