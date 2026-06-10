from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class StructuredObjectShape(StrEnum):
    STRUCTURED_TABLE = "structured_table"
    PROFILE_BUNDLE = "profile_bundle"


class StructuredLookupPolicy(StrEnum):
    REQUIRED = "required"
    ALLOWED = "allowed"
    SUPPORTING_ONLY = "supporting_only"
    FORBIDDEN = "forbidden"
    NOT_PRIMARY = "not_primary"


CANDIDATE_STATUSES = frozenset(
    {
        "candidate",
        "needs_review",
        "auto_rejected",
        "approved",
        "corrected",
        "rejected",
        "superseded",
    }
)
VALIDATION_STATUSES = frozenset({"active", "stale", "retired"})
REVIEW_STATES = frozenset({"auto_approved", "human_approved", "human_corrected"})


def normalize_structured_alias(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def normalize_table_number(value: str) -> str:
    cleaned = value.lower()
    cleaned = cleaned.replace("\u2010", "-")
    cleaned = cleaned.replace("\u2011", "-")
    cleaned = cleaned.replace("\u2012", "-")
    cleaned = cleaned.replace("\u2013", "-")
    cleaned = cleaned.replace("\u2014", "-")
    cleaned = re.sub(r"\btable\b", "", cleaned)
    match = re.search(r"\d+\s*-\s*\d+", cleaned)
    if match:
        return re.sub(r"\s+", "", match.group(0))
    return normalize_structured_alias(cleaned)


def deterministic_candidate_id(
    *,
    book_id: str,
    object_shape: str,
    identity: str,
    page_start: int,
    page_end: int,
    snapshot_sha256: str,
    extractor_version: str,
) -> str:
    _validate_page_range(page_start, page_end)
    digest = _short_hash(
        "|".join(
            (
                book_id,
                object_shape,
                normalize_structured_alias(identity),
                str(page_start),
                str(page_end),
                snapshot_sha256,
                extractor_version,
            )
        )
    )
    return f"structured-candidate:{book_id}:p{page_start}-p{page_end}:{digest}"


def deterministic_validated_object_id(
    *,
    book_id: str,
    object_shape: str,
    identity: str,
) -> str:
    digest = _short_hash(
        "|".join((book_id, object_shape, normalize_structured_alias(identity)))
    )
    return f"validated-structured:{book_id}:{object_shape}:{digest}"


@dataclass(frozen=True)
class StructuredEvidenceCandidate:
    id: str
    book_id: str
    primary_page_id: str
    object_shape: StructuredObjectShape | str
    content_kind: str
    entity_kind: str
    page_start: int
    page_end: int
    payload_json: dict[str, Any]
    search_text: str
    confidence: float
    status: str
    text_snapshot_sha256: str
    structured_extractor_version: str
    primary_source_object_id: str | None = None
    canonical_name: str | None = None
    title: str | None = None
    table_number: str | None = None
    table_number_normalized: str | None = None
    printed_page_start: str | None = None
    printed_page_end: str | None = None
    heading_path: tuple[str, ...] = field(default_factory=tuple)
    observation_ids: tuple[str, ...] = field(default_factory=tuple)
    source_object_ids: tuple[str, ...] = field(default_factory=tuple)
    suspicious_flags: tuple[str, ...] = field(default_factory=tuple)
    status_reason: str | None = None

    def __post_init__(self) -> None:
        shape = StructuredObjectShape(self.object_shape)
        object.__setattr__(self, "object_shape", shape)
        if self.status not in CANDIDATE_STATUSES:
            raise ValueError(f"Unsupported candidate status: {self.status}")
        _validate_page_range(self.page_start, self.page_end)
        _validate_confidence(self.confidence)
        _validate_required_text("id", self.id)
        _validate_required_text("book_id", self.book_id)
        _validate_required_text("primary_page_id", self.primary_page_id)
        _validate_required_text("content_kind", self.content_kind)
        _validate_required_text("entity_kind", self.entity_kind)
        _validate_required_text("search_text", self.search_text)
        _validate_required_text("text_snapshot_sha256", self.text_snapshot_sha256)
        _validate_required_text(
            "structured_extractor_version",
            self.structured_extractor_version,
        )


@dataclass(frozen=True)
class ValidatedStructuredObject:
    id: str
    book_id: str
    primary_page_id: str
    object_shape: StructuredObjectShape | str
    content_kind: str
    entity_kind: str
    page_start: int
    page_end: int
    payload_schema_version: int
    payload_json: dict[str, Any]
    source_snapshot_sha256: str
    validation_status: str
    review_state: str
    candidate_id: str | None = None
    primary_source_object_id: str | None = None
    canonical_name: str | None = None
    title: str | None = None
    table_number: str | None = None
    table_number_normalized: str | None = None
    printed_page_start: str | None = None
    printed_page_end: str | None = None
    heading_path: tuple[str, ...] = field(default_factory=tuple)
    field_confidence: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        shape = StructuredObjectShape(self.object_shape)
        object.__setattr__(self, "object_shape", shape)
        if self.validation_status not in VALIDATION_STATUSES:
            raise ValueError(
                f"Unsupported validation_status: {self.validation_status}"
            )
        if self.review_state not in REVIEW_STATES:
            raise ValueError(f"Unsupported review_state: {self.review_state}")
        if self.payload_schema_version < 1:
            raise ValueError("payload_schema_version must be at least 1")
        _validate_page_range(self.page_start, self.page_end)
        _validate_required_text("id", self.id)
        _validate_required_text("book_id", self.book_id)
        _validate_required_text("primary_page_id", self.primary_page_id)
        _validate_required_text("content_kind", self.content_kind)
        _validate_required_text("entity_kind", self.entity_kind)
        _validate_required_text("source_snapshot_sha256", self.source_snapshot_sha256)


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _validate_confidence(value: float) -> None:
    if value < 0 or value > 1:
        raise ValueError("confidence must be between 0 and 1")


def _validate_page_range(page_start: int, page_end: int) -> None:
    if page_start < 1:
        raise ValueError("page_start must be at least 1")
    if page_end < page_start:
        raise ValueError("page_end must be greater than or equal to page_start")


def _validate_required_text(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} must not be empty")
