from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from wfrp_companion.structured_evidence.models import (
    normalize_structured_alias,
    normalize_table_number,
)


READER_VERSION = "structured-reader-v1"
TABLE_REFERENCE_RE = re.compile(
    r"\bTable\s+(?P<number>\d+\s*[-\u2010-\u2014]\s*\d+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SourceObjectSnapshot:
    id: str
    book_id: str
    page_id: str
    page_number: int
    object_type: str
    title: str | None
    text: str
    heading_path: tuple[str, ...]
    page_start: int
    page_end: int
    text_snapshot_sha256: str
    confidence: float
    parent_object_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    bbox_json: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceObjectLinkSnapshot:
    id: str
    from_object_id: str
    to_object_id: str | None
    link_type: str


@dataclass(frozen=True)
class PageTextSnapshot:
    page_id: str
    book_id: str
    page_number: int
    text: str
    text_snapshot_sha256: str
    page_label: str | None = None


@dataclass(frozen=True)
class ReaderObservation:
    id: str
    book_id: str
    page_id: str
    page_number: int
    reader_name: str
    reader_version: str
    observation_type: str
    text_snapshot_sha256: str
    confidence: float
    source_object_id: str | None = None
    object_shape: str | None = None
    content_kind: str | None = None
    entity_kind: str | None = None
    title: str | None = None
    table_number: str | None = None
    canonical_name: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    bbox_json: str | None = None
    payload_json: dict[str, Any] = field(default_factory=dict)
    text_hash: str | None = None


def load_source_object_snapshots(
    connection: sqlite3.Connection,
    book_id: str,
) -> tuple[SourceObjectSnapshot, ...]:
    rows = connection.execute(
        """
        select
          source_objects.id,
          source_objects.book_id,
          source_objects.page_id,
          pages.page_number,
          source_objects.object_type,
          source_objects.parent_object_id,
          source_objects.title,
          source_objects.heading_path_json,
          source_objects.page_start,
          source_objects.page_end,
          source_objects.char_start,
          source_objects.char_end,
          source_objects.bbox_json,
          source_objects.text,
          source_objects.confidence,
          source_objects.text_snapshot_sha256,
          source_objects.metadata_json
        from source_objects
        join pages on pages.id = source_objects.page_id
        where source_objects.book_id = ?
          and source_objects.object_type in (
            'table',
            'table_row',
            'stat_block',
            'npc_profile',
            'monster_profile'
          )
        order by source_objects.page_start, source_objects.char_start, source_objects.id
        """,
        (book_id,),
    ).fetchall()
    return tuple(_source_object_snapshot_from_row(row) for row in rows)


def load_source_object_link_snapshots(
    connection: sqlite3.Connection,
    book_id: str,
) -> tuple[SourceObjectLinkSnapshot, ...]:
    rows = connection.execute(
        """
        select
          source_object_links.id,
          source_object_links.from_object_id,
          source_object_links.to_object_id,
          source_object_links.link_type
        from source_object_links
        join source_objects
          on source_objects.id = source_object_links.from_object_id
        where source_objects.book_id = ?
          and source_object_links.link_type in ('table_row', 'stat_profile')
        order by source_object_links.id
        """,
        (book_id,),
    ).fetchall()
    return tuple(
        SourceObjectLinkSnapshot(
            id=row["id"],
            from_object_id=row["from_object_id"],
            to_object_id=row["to_object_id"],
            link_type=row["link_type"],
        )
        for row in rows
    )


def load_page_text_snapshots(
    connection: sqlite3.Connection,
    book_id: str,
) -> tuple[PageTextSnapshot, ...]:
    rows = connection.execute(
        """
        select
          pages.id,
          pages.book_id,
          pages.page_number,
          pages.page_label,
          page_text.text,
          page_text.text_sha256
        from pages
        join page_text on page_text.page_id = pages.id
        where pages.book_id = ?
        order by pages.page_number, pages.id
        """,
        (book_id,),
    ).fetchall()
    return tuple(
        PageTextSnapshot(
            page_id=row["id"],
            book_id=row["book_id"],
            page_number=row["page_number"],
            page_label=row["page_label"],
            text=row["text"],
            text_snapshot_sha256=row["text_sha256"],
        )
        for row in rows
    )


def reader_observations_from_source_objects(
    source_objects: tuple[SourceObjectSnapshot, ...],
    links: tuple[SourceObjectLinkSnapshot, ...] = (),
) -> tuple[ReaderObservation, ...]:
    link_parent_by_child = {
        link.from_object_id: link.to_object_id
        for link in links
        if link.to_object_id is not None
        and link.link_type in {"table_row", "stat_profile"}
    }
    observations: list[ReaderObservation] = []
    for source_object in source_objects:
        observation = _observation_from_source_object(
            source_object,
            linked_parent_id=link_parent_by_child.get(source_object.id),
        )
        if observation is not None:
            observations.append(observation)
    return tuple(observations)


def page_reference_observations_from_pages(
    pages: tuple[PageTextSnapshot, ...],
    *,
    known_table_numbers: frozenset[str],
) -> tuple[ReaderObservation, ...]:
    observations: list[ReaderObservation] = []
    for page in pages:
        for match in TABLE_REFERENCE_RE.finditer(page.text):
            table_number = normalize_table_number(match.group("number"))
            if table_number in known_table_numbers:
                continue
            reference_text = match.group(0)
            observations.append(
                ReaderObservation(
                    id=_observation_id(
                        "page_text_import",
                        page.book_id,
                        page.page_id,
                        "page_reference",
                        table_number,
                    ),
                    book_id=page.book_id,
                    page_id=page.page_id,
                    page_number=page.page_number,
                    reader_name="page_text_import",
                    reader_version=READER_VERSION,
                    observation_type="page_reference",
                    object_shape="structured_table",
                    content_kind="unknown",
                    entity_kind="none",
                    table_number=table_number,
                    title=f"Referenced table {table_number}",
                    text_snapshot_sha256=page.text_snapshot_sha256,
                    confidence=0.45,
                    payload_json={
                        "reference_text": reference_text,
                        "page_label": page.page_label,
                    },
                    text_hash=_hash_text(reference_text),
                )
            )
    return tuple(observations)


def known_table_numbers_from_observations(
    observations: tuple[ReaderObservation, ...],
) -> frozenset[str]:
    return frozenset(
        observation.table_number
        for observation in observations
        if observation.observation_type == "table_region" and observation.table_number
    )


def _source_object_snapshot_from_row(row: sqlite3.Row) -> SourceObjectSnapshot:
    return SourceObjectSnapshot(
        id=row["id"],
        book_id=row["book_id"],
        page_id=row["page_id"],
        page_number=row["page_number"],
        object_type=row["object_type"],
        parent_object_id=row["parent_object_id"],
        title=row["title"],
        text=row["text"],
        heading_path=_parse_heading_path(row["heading_path_json"]),
        page_start=row["page_start"],
        page_end=row["page_end"],
        char_start=row["char_start"],
        char_end=row["char_end"],
        bbox_json=row["bbox_json"],
        text_snapshot_sha256=row["text_snapshot_sha256"],
        confidence=row["confidence"],
        metadata=_parse_metadata(row["metadata_json"]),
    )


def _observation_from_source_object(
    source_object: SourceObjectSnapshot,
    *,
    linked_parent_id: str | None,
) -> ReaderObservation | None:
    if source_object.object_type == "table":
        title = source_object.title or "Untitled table"
        table_number = _table_number_from_title_or_text(title, source_object.text)
        return _source_object_observation(
            source_object,
            observation_type="table_region",
            object_shape="structured_table",
            content_kind=_table_content_kind(title),
            entity_kind="none",
            title=title,
            table_number=table_number,
            canonical_name=normalize_structured_alias(title),
        )
    if source_object.object_type == "table_row":
        parent_id = source_object.parent_object_id or linked_parent_id
        return _source_object_observation(
            source_object,
            observation_type="table_row",
            object_shape="table_row",
            content_kind="unknown",
            entity_kind="none",
            title=source_object.title,
            payload_extra={"parent_source_object_id": parent_id},
        )
    if source_object.object_type in {"npc_profile", "monster_profile"}:
        title = source_object.title or "Untitled profile"
        entity_kind = "monster" if source_object.object_type == "monster_profile" else "npc"
        return _source_object_observation(
            source_object,
            observation_type="profile_header",
            object_shape="profile_bundle",
            content_kind=(
                "creature_profile" if entity_kind == "monster" else "npc_profile"
            ),
            entity_kind=entity_kind,
            title=title,
            canonical_name=normalize_structured_alias(title),
        )
    if source_object.object_type == "stat_block":
        parent_id = source_object.parent_object_id or linked_parent_id
        return _source_object_observation(
            source_object,
            observation_type="profile_stat_block",
            object_shape="profile_field_block",
            content_kind="generic_stat_block",
            entity_kind="unknown",
            title=source_object.title,
            payload_extra={"parent_source_object_id": parent_id},
        )
    return None


def _source_object_observation(
    source_object: SourceObjectSnapshot,
    *,
    observation_type: str,
    object_shape: str,
    content_kind: str,
    entity_kind: str,
    title: str | None,
    table_number: str | None = None,
    canonical_name: str | None = None,
    payload_extra: dict[str, Any] | None = None,
) -> ReaderObservation:
    payload = {
        "source_object_id": source_object.id,
        "parent_source_object_id": source_object.parent_object_id,
        "object_type": source_object.object_type,
        "text": source_object.text,
        "heading_path": list(source_object.heading_path),
        "page_start": source_object.page_start,
        "page_end": source_object.page_end,
        "metadata": source_object.metadata,
    }
    if payload_extra:
        payload.update(payload_extra)
    return ReaderObservation(
        id=_observation_id(
            "source_object_heuristic",
            source_object.book_id,
            source_object.page_id,
            observation_type,
            source_object.id,
        ),
        book_id=source_object.book_id,
        page_id=source_object.page_id,
        page_number=source_object.page_number,
        source_object_id=source_object.id,
        reader_name="source_object_heuristic",
        reader_version=READER_VERSION,
        observation_type=observation_type,
        object_shape=object_shape,
        content_kind=content_kind,
        entity_kind=entity_kind,
        title=title,
        table_number=table_number,
        canonical_name=canonical_name,
        char_start=source_object.char_start,
        char_end=source_object.char_end,
        bbox_json=source_object.bbox_json,
        payload_json=payload,
        text_hash=_hash_text(source_object.text),
        text_snapshot_sha256=source_object.text_snapshot_sha256,
        confidence=source_object.confidence,
    )


def _table_number_from_title_or_text(title: str, text: str) -> str | None:
    for value in (title, text):
        match = TABLE_REFERENCE_RE.search(value)
        if match:
            return normalize_table_number(match.group("number"))
    return None


def _table_content_kind(title: str) -> str:
    lowered = title.casefold()
    if "armour" in lowered or "armor" in lowered or "equipment" in lowered:
        return "equipment_table"
    if "combat" in lowered or "hit location" in lowered:
        return "combat_table"
    return "rules_table"


def _observation_id(
    reader_name: str,
    book_id: str,
    page_id: str,
    observation_type: str,
    identity: str,
) -> str:
    digest = hashlib.sha256(
        "|".join((reader_name, book_id, page_id, observation_type, identity)).encode(
            "utf-8"
        )
    ).hexdigest()[:16]
    return f"structured-observation:{book_id}:{digest}"


def _hash_text(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


def _parse_heading_path(value: str) -> tuple[str, ...]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(item for item in parsed if isinstance(item, str) and item)


def _parse_metadata(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed
