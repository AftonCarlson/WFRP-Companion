from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal


SourceObjectType = Literal[
    "rule_section",
    "table",
    "table_row",
    "stat_block",
    "npc_profile",
    "monster_profile",
    "location_description",
    "encounter",
    "boxed_text",
    "map_reference",
    "image_reference",
    "index_entry",
    "cross_reference",
    "page_chunk",
]

SOURCE_OBJECT_TYPES: tuple[str, ...] = (
    "rule_section",
    "table",
    "table_row",
    "stat_block",
    "npc_profile",
    "monster_profile",
    "location_description",
    "encounter",
    "boxed_text",
    "map_reference",
    "image_reference",
    "index_entry",
    "cross_reference",
    "page_chunk",
)


@dataclass(frozen=True)
class SourceObject:
    id: str
    book_id: str
    page_id: str
    object_type: str
    page_start: int
    page_end: int
    text: str
    search_text: str
    confidence: float
    extraction_method: str
    text_snapshot_sha256: str
    parent_object_id: str | None = None
    title: str | None = None
    heading_path: tuple[str, ...] = field(default_factory=tuple)
    char_start: int | None = None
    char_end: int | None = None
    bbox_json: str | None = None
    metadata_json: str = "{}"

    def __post_init__(self) -> None:
        if self.object_type not in SOURCE_OBJECT_TYPES:
            raise ValueError(f"Unsupported source object type: {self.object_type}")
        if not 0 <= self.confidence <= 1:
            raise ValueError("Source object confidence must be between 0 and 1")
        if self.page_start < 1:
            raise ValueError("page_start must be greater than or equal to 1")
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")


def deterministic_source_object_id(
    *,
    book_id: str,
    page_start: int,
    page_end: int,
    object_type: str,
    ordinal: int,
    text: str,
) -> str:
    if object_type not in SOURCE_OBJECT_TYPES:
        raise ValueError(f"Unsupported source object type: {object_type}")
    if page_start < 1:
        raise ValueError("page_start must be greater than or equal to 1")
    if page_end < page_start:
        raise ValueError("page_end must be greater than or equal to page_start")
    if ordinal < 1:
        raise ValueError("ordinal must be greater than or equal to 1")

    normalized_text = " ".join(text.split())
    digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:12]
    return f"{book_id}:p{page_start}-p{page_end}:{object_type}:{ordinal}:{digest}"
