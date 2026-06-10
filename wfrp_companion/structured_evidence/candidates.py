from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from wfrp_companion.structured_evidence.models import (
    StructuredEvidenceCandidate,
    deterministic_candidate_id,
    normalize_structured_alias,
    normalize_table_number,
)
from wfrp_companion.structured_evidence.payloads import (
    table_payload_search_text,
    validate_profile_bundle_payload,
    validate_structured_table_payload,
)
from wfrp_companion.structured_evidence.readers import ReaderObservation
from wfrp_companion.structured_evidence.suspicion import (
    profile_suspicious_flags,
    range_suspicious_flags,
)


MAIN_FIELDS = ("ws", "bs", "s", "t", "ag", "int", "wp", "fel")
SECONDARY_FIELDS = ("a", "w", "sb", "tb", "m", "mag", "ip", "fp")
FOLLOWUP_LABELS = {
    "skills": "skills",
    "talents": "talents",
    "traits": "traits",
    "special rules": "special_rules",
    "weapons": "weapons",
    "armour": "armour",
    "armor": "armour",
    "trappings": "trappings",
    "notes": "notes",
}


def build_candidates_from_observations(
    observations: tuple[ReaderObservation, ...],
) -> tuple[StructuredEvidenceCandidate, ...]:
    table_candidates = _table_candidates(observations)
    profile_candidates = _profile_candidates(observations)
    missing_reference_candidates = _missing_reference_candidates(
        observations,
        known_table_numbers=frozenset(
            candidate.table_number_normalized
            for candidate in table_candidates
            if candidate.table_number_normalized
        ),
    )
    return (*table_candidates, *profile_candidates, *missing_reference_candidates)


def _table_candidates(
    observations: tuple[ReaderObservation, ...],
) -> tuple[StructuredEvidenceCandidate, ...]:
    table_observations = [
        observation
        for observation in observations
        if observation.observation_type == "table_region"
    ]
    row_observations = [
        observation
        for observation in observations
        if observation.observation_type == "table_row"
    ]
    rows_by_parent: dict[str, list[ReaderObservation]] = {}
    for row in row_observations:
        parent_id = row.payload_json.get("parent_source_object_id")
        if isinstance(parent_id, str):
            rows_by_parent.setdefault(parent_id, []).append(row)

    candidates: list[StructuredEvidenceCandidate] = []
    for table in table_observations:
        table_source_id = table.source_object_id or table.id
        rows = rows_by_parent.get(table_source_id, [])
        payload = _table_payload(table, rows)
        validate_structured_table_payload(payload)
        range_flags = range_suspicious_flags(
            row.get("range_raw")
            for row in payload["structure"]["rows"]
            if isinstance(row, dict)
        )
        status = "needs_review" if range_flags else "candidate"
        source_object_ids = tuple(
            source_id
            for source_id in (
                table.source_object_id,
                *(row.source_object_id for row in rows),
            )
            if source_id is not None
        )
        candidates.append(
            StructuredEvidenceCandidate(
                id=deterministic_candidate_id(
                    book_id=table.book_id,
                    object_shape="structured_table",
                    identity=table.table_number or table.title or table.id,
                    page_start=table.page_number,
                    page_end=table.page_number,
                    snapshot_sha256=table.text_snapshot_sha256,
                    extractor_version=table.reader_version,
                ),
                book_id=table.book_id,
                primary_page_id=table.page_id,
                primary_source_object_id=table.source_object_id,
                object_shape="structured_table",
                content_kind=table.content_kind or "unknown",
                entity_kind="none",
                canonical_name=None,
                title=table.title,
                table_number=table.table_number,
                table_number_normalized=table.table_number,
                page_start=table.page_number,
                page_end=table.page_number,
                printed_page_start=None,
                printed_page_end=None,
                heading_path=tuple(_payload_heading_path(table)),
                observation_ids=tuple(
                    observation.id for observation in (table, *tuple(rows))
                ),
                source_object_ids=source_object_ids,
                payload_json=payload,
                search_text=table_payload_search_text(payload),
                confidence=min(
                    [table.confidence, *(row.confidence for row in rows)] or [0.0]
                ),
                suspicious_flags=range_flags,
                status=status,
                text_snapshot_sha256=table.text_snapshot_sha256,
                structured_extractor_version=table.reader_version,
            )
        )
    return tuple(candidates)


def _profile_candidates(
    observations: tuple[ReaderObservation, ...],
) -> tuple[StructuredEvidenceCandidate, ...]:
    profiles = [
        observation
        for observation in observations
        if observation.observation_type == "profile_header"
    ]
    stat_blocks = [
        observation
        for observation in observations
        if observation.observation_type == "profile_stat_block"
    ]
    stat_by_parent: dict[str, ReaderObservation] = {}
    for stat_block in stat_blocks:
        parent_id = stat_block.payload_json.get("parent_source_object_id")
        if isinstance(parent_id, str):
            stat_by_parent[parent_id] = stat_block

    candidates: list[StructuredEvidenceCandidate] = []
    for profile in profiles:
        profile_source_id = profile.source_object_id or profile.id
        stat_block = stat_by_parent.get(profile_source_id)
        payload = _profile_payload(profile, stat_block)
        validate_profile_bundle_payload(payload)
        flags = profile_suspicious_flags(payload)
        status = "needs_review" if flags else "candidate"
        source_object_ids = tuple(
            source_id
            for source_id in (
                profile.source_object_id,
                stat_block.source_object_id if stat_block else None,
            )
            if source_id is not None
        )
        candidates.append(
            StructuredEvidenceCandidate(
                id=deterministic_candidate_id(
                    book_id=profile.book_id,
                    object_shape="profile_bundle",
                    identity=profile.canonical_name or profile.title or profile.id,
                    page_start=profile.page_number,
                    page_end=profile.page_number,
                    snapshot_sha256=profile.text_snapshot_sha256,
                    extractor_version=profile.reader_version,
                ),
                book_id=profile.book_id,
                primary_page_id=profile.page_id,
                primary_source_object_id=profile.source_object_id,
                object_shape="profile_bundle",
                content_kind=profile.content_kind or "creature_profile",
                entity_kind=profile.entity_kind or "unknown",
                canonical_name=profile.canonical_name,
                title=profile.title,
                page_start=profile.page_number,
                page_end=profile.page_number,
                heading_path=tuple(_payload_heading_path(profile)),
                observation_ids=tuple(
                    observation.id
                    for observation in (profile, *(() if stat_block is None else (stat_block,)))
                ),
                source_object_ids=source_object_ids,
                payload_json=payload,
                search_text=_profile_search_text(payload),
                confidence=min(profile.confidence, stat_block.confidence)
                if stat_block
                else profile.confidence,
                suspicious_flags=flags,
                status=status,
                text_snapshot_sha256=profile.text_snapshot_sha256,
                structured_extractor_version=profile.reader_version,
            )
        )
    return tuple(candidates)


def _missing_reference_candidates(
    observations: tuple[ReaderObservation, ...],
    *,
    known_table_numbers: frozenset[str],
) -> tuple[StructuredEvidenceCandidate, ...]:
    candidates: list[StructuredEvidenceCandidate] = []
    for observation in observations:
        if observation.observation_type != "page_reference":
            continue
        if observation.table_number in known_table_numbers:
            continue
        table_number = observation.table_number or "unknown"
        payload = {
            "schema_version": 1,
            "object_shape": "structured_table",
            "content_kind": "unknown",
            "identity": {
                "table_number_raw": table_number,
                "table_number_normalized": table_number,
                "title_raw": observation.title or f"Referenced table {table_number}",
                "title_normalized": normalize_structured_alias(
                    observation.title or f"Referenced table {table_number}"
                ),
                "aliases": [f"table {table_number}"],
            },
            "source": {
                "book_id": observation.book_id,
                "chapter_path": [],
                "printed_page_start": None,
                "printed_page_end": None,
                "pdf_page_start": observation.page_number,
                "pdf_page_end": observation.page_number,
                "source_object_ids": [],
                "text_snapshot_sha256": observation.text_snapshot_sha256,
            },
            "structure": {
                "columns": [
                    {"key": "unknown", "label_raw": "Unknown", "confidence": 0.0}
                ],
                "rows": [
                    {
                        "ordinal": 1,
                        "range_raw": None,
                        "cells": {},
                        "raw_text": "",
                        "confidence": 0.0,
                        "suspicious_cells": [],
                    }
                ],
            },
            "provenance": {
                "reader_names": [observation.reader_name],
                "confidence": observation.confidence,
                "issues": ["referenced_table_missing"],
            },
        }
        validate_structured_table_payload(payload)
        candidates.append(
            StructuredEvidenceCandidate(
                id=deterministic_candidate_id(
                    book_id=observation.book_id,
                    object_shape="structured_table",
                    identity=f"missing-table:{table_number}:{observation.page_id}",
                    page_start=observation.page_number,
                    page_end=observation.page_number,
                    snapshot_sha256=observation.text_snapshot_sha256,
                    extractor_version=observation.reader_version,
                ),
                book_id=observation.book_id,
                primary_page_id=observation.page_id,
                object_shape="structured_table",
                content_kind="unknown",
                entity_kind="none",
                title=observation.title,
                table_number=table_number,
                table_number_normalized=table_number,
                page_start=observation.page_number,
                page_end=observation.page_number,
                observation_ids=(observation.id,),
                source_object_ids=(),
                payload_json=payload,
                search_text=table_payload_search_text(payload),
                confidence=observation.confidence,
                suspicious_flags=("referenced_table_missing",),
                status="needs_review",
                text_snapshot_sha256=observation.text_snapshot_sha256,
                structured_extractor_version=observation.reader_version,
            )
        )
    return tuple(candidates)


def _table_payload(
    table: ReaderObservation,
    rows: list[ReaderObservation],
) -> dict[str, Any]:
    header_cells = _first_pipe_cells(table.payload_json.get("text"))
    if not header_cells:
        header_cells = ["Value"]
    columns = [
        {
            "key": _column_key(cell, index),
            "label_raw": cell,
            "confidence": table.confidence,
        }
        for index, cell in enumerate(header_cells, start=1)
    ]
    payload_rows = []
    for index, row in enumerate(rows, start=1):
        cells = _pipe_cells(str(row.payload_json.get("text", "")))
        row_cells = {
            column["key"]: cells[cell_index]
            for cell_index, column in enumerate(columns)
            if cell_index < len(cells)
        }
        raw_text = str(row.payload_json.get("text", ""))
        payload_rows.append(
            {
                "ordinal": index,
                "range_raw": _range_text(raw_text),
                "cells": row_cells,
                "raw_text": raw_text,
                "confidence": row.confidence,
                "suspicious_cells": [],
            }
        )
    if not payload_rows:
        payload_rows.append(
            {
                "ordinal": 1,
                "range_raw": None,
                "cells": {},
                "raw_text": "",
                "confidence": 0.0,
                "suspicious_cells": [],
            }
        )
    return {
        "schema_version": 1,
        "object_shape": "structured_table",
        "content_kind": table.content_kind or "unknown",
        "identity": {
            "table_number_raw": table.table_number,
            "table_number_normalized": table.table_number,
            "title_raw": table.title,
            "title_normalized": normalize_structured_alias(table.title or ""),
            "aliases": _table_aliases(table),
        },
        "source": {
            "book_id": table.book_id,
            "chapter_path": _payload_heading_path(table),
            "printed_page_start": None,
            "printed_page_end": None,
            "pdf_page_start": table.page_number,
            "pdf_page_end": table.page_number,
            "source_object_ids": [
                source_id
                for source_id in (table.source_object_id, *(row.source_object_id for row in rows))
                if source_id is not None
            ],
            "text_snapshot_sha256": table.text_snapshot_sha256,
        },
        "structure": {"columns": columns, "rows": payload_rows},
        "provenance": {
            "reader_names": sorted({table.reader_name, *(row.reader_name for row in rows)}),
            "confidence": table.confidence,
            "issues": [],
        },
    }


def _profile_payload(
    profile: ReaderObservation,
    stat_block: ReaderObservation | None,
) -> dict[str, Any]:
    profile_text = str(profile.payload_json.get("text", ""))
    stat_text = str(stat_block.payload_json.get("text", "")) if stat_block else ""
    main_profile, secondary_profile = _parse_stat_profiles(stat_text or profile_text)
    followups = _parse_followups(profile_text)
    return {
        "schema_version": 1,
        "object_shape": "profile_bundle",
        "content_kind": profile.content_kind or "creature_profile",
        "entity_kind": profile.entity_kind or "unknown",
        "identity": {
            "name_raw": profile.title,
            "name_normalized": profile.canonical_name or normalize_structured_alias(profile.title or ""),
            "aliases": [alias for alias in {profile.title, profile.canonical_name} if alias],
        },
        "source": {
            "book_id": profile.book_id,
            "chapter_path": _payload_heading_path(profile),
            "printed_page_start": None,
            "printed_page_end": None,
            "pdf_page_start": profile.page_number,
            "pdf_page_end": profile.page_number,
            "source_object_ids": [
                source_id
                for source_id in (
                    profile.source_object_id,
                    stat_block.source_object_id if stat_block else None,
                )
                if source_id is not None
            ],
            "text_snapshot_sha256": profile.text_snapshot_sha256,
        },
        "profile": {
            "description": _description_text(profile_text, profile.title),
            "main_profile": main_profile,
            "secondary_profile": secondary_profile,
            **followups,
        },
        "provenance": {
            "reader_names": [profile.reader_name]
            + ([] if stat_block is None else [stat_block.reader_name]),
            "field_confidence": {
                field: stat_block.confidence if stat_block else profile.confidence
                for field, value in {**main_profile, **secondary_profile}.items()
                if value is not None
            },
            "suspicious_fields": [],
        },
    }


def _parse_stat_profiles(text: str) -> tuple[dict[str, int | None], dict[str, int | None]]:
    main_profile = {field: None for field in MAIN_FIELDS}
    secondary_profile = {field: None for field in SECONDARY_FIELDS}
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines[:-1]):
        header = _stat_header_tokens(line)
        if header == MAIN_FIELDS:
            main_profile.update(_values_for_fields(MAIN_FIELDS, lines[index + 1]))
        if header == SECONDARY_FIELDS:
            secondary_profile.update(_values_for_fields(SECONDARY_FIELDS, lines[index + 1]))
    return main_profile, secondary_profile


def _parse_followups(text: str) -> dict[str, list[str]]:
    followups = {value: [] for value in FOLLOWUP_LABELS.values()}
    for line in text.splitlines():
        if ":" not in line:
            continue
        label, value = line.split(":", maxsplit=1)
        key = FOLLOWUP_LABELS.get(normalize_structured_alias(label))
        if key is None:
            continue
        followups[key].extend(_split_list_values(value))
    return followups


def _profile_search_text(payload: dict[str, Any]) -> str:
    identity = payload["identity"]
    profile = payload["profile"]
    parts = [identity.get("name_raw") or "", identity.get("name_normalized") or ""]
    for field_name in FOLLOWUP_LABELS.values():
        parts.extend(profile.get(field_name, []))
    return " ".join(part for part in parts if part)


def _description_text(text: str, title: str | None) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped == title:
            continue
        if _stat_header_tokens(stripped) in {MAIN_FIELDS, SECONDARY_FIELDS}:
            break
        if ":" in stripped:
            break
        lines.append(stripped)
    return " ".join(lines)


def _payload_heading_path(observation: ReaderObservation) -> list[str]:
    heading_path = observation.payload_json.get("heading_path")
    if not isinstance(heading_path, list):
        return []
    return [value for value in heading_path if isinstance(value, str)]


def _table_aliases(table: ReaderObservation) -> list[str]:
    aliases = []
    if table.table_number:
        aliases.append(f"table {table.table_number}")
    if table.title:
        aliases.append(table.title)
        aliases.append(f"{table.title} table")
    return aliases


def _first_pipe_cells(text: object) -> list[str]:
    if not isinstance(text, str):
        return []
    for line in text.splitlines():
        cells = _pipe_cells(line)
        if cells:
            return cells
    return []


def _pipe_cells(text: str) -> list[str]:
    if "|" not in text:
        return []
    return [cell.strip() for cell in text.strip().strip("|").split("|")]


def _column_key(label: str, index: int) -> str:
    normalized = normalize_structured_alias(label).replace(" ", "_")
    return normalized or f"column_{index}"


def _range_text(text: str) -> str | None:
    match = re.search(r"\d{1,3}\s*[-\u2010-\u2014]\s*(?:\d{1,3}|0?0)", text)
    return None if match is None else normalize_table_number(match.group(0))


def _stat_header_tokens(line: str) -> tuple[str, ...]:
    tokens = normalize_structured_alias(line).split()
    return tuple("int" if token == "i" else token for token in tokens)


def _values_for_fields(fields: Iterable[str], line: str) -> dict[str, int | None]:
    values = re.findall(r"[-+]?\d+", line)
    parsed: dict[str, int | None] = {}
    for field, value in zip(fields, values, strict=False):
        parsed[field] = int(value)
    return parsed


def _split_list_values(value: str) -> list[str]:
    return [item.strip() for item in re.split(r",|;", value) if item.strip()]
