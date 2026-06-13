from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class StructuredObjectShape(StrEnum):
    STRUCTURED_TABLE = "structured_table"
    PROFILE_BUNDLE = "profile_bundle"
    PROFILE_CARD = "profile_card"
    CAREER_ENTRY = "career_entry"
    RULES_ENTRY = "rules_entry"


class StructuredVisualRegionKind(StrEnum):
    TABLE = "table"
    PROFILE_CARD = "profile_card"
    CAREER_ENTRY = "career_entry"
    RULES_ENTRY = "rules_entry"
    HEADING = "heading"
    TEXT_BLOCK = "text_block"
    STAT_GRID = "stat_grid"
    UNKNOWN = "unknown"


class StructuredEnvelopeKind(StrEnum):
    PROFILE_CARD = "profile_card"
    CAREER_ENTRY = "career_entry"
    RULES_ENTRY = "rules_entry"
    STRUCTURED_TABLE = "structured_table"


class StructuredEnvelopeScopeKind(StrEnum):
    BOOK = "book"
    CHAPTER = "chapter"
    SECTION = "section"
    PAGE = "page"
    PARENT_OBJECT = "parent_object"
    LOCATION = "location"


class StructuredEnvelopeStatus(StrEnum):
    CANDIDATE = "candidate"
    NEEDS_REVIEW = "needs_review"
    VALIDATED = "validated"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    BLOCKED = "blocked"


class StructuredReviewActionKind(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    CORRECT_FIELDS = "correct_fields"
    RECLASSIFY = "reclassify"
    MERGE = "merge"
    SPLIT = "split"
    SET_PARENT = "set_parent"
    CLEAR_PARENT = "clear_parent"
    MARK_SUSPICIOUS = "mark_suspicious"
    RERUN_READER = "rerun_reader"


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
        "blocked",
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


def deterministic_visual_region_id(region: StructuredVisualRegion) -> str:
    digest = _short_hash(
        "|".join(
            (
                region.book_id,
                region.source_snapshot_sha256,
                region.provider_name,
                region.provider_version,
                str(region.pdf_page_start),
                str(region.pdf_page_end),
                str(region.region_kind),
                _stable_json(region.bbox_json),
                hashlib.sha256(region.raw_text.encode("utf-8")).hexdigest(),
            )
        )
    )
    return (
        f"structured-region:{region.book_id}:"
        f"p{region.pdf_page_start}-p{region.pdf_page_end}:{digest}"
    )


@dataclass(frozen=True)
class StructuredVisualRegion:
    id: str
    book_id: str
    source_snapshot_sha256: str
    ingest_job_id: str | None
    provider_name: str
    provider_version: str
    pdf_page_start: int
    pdf_page_end: int
    printed_page_start: str | None
    printed_page_end: str | None
    region_kind: StructuredVisualRegionKind | str
    bbox_json: dict[str, Any]
    crop_asset_path: str | None
    raw_text: str
    confidence: float
    issues: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _validate_page_range(self.pdf_page_start, self.pdf_page_end)
        _validate_confidence(self.confidence)
        _validate_required_text("book_id", self.book_id)
        _validate_required_text("source_snapshot_sha256", self.source_snapshot_sha256)
        _validate_required_text("provider_name", self.provider_name)


@dataclass(frozen=True)
class StructuredEnvelope:
    id: str
    book_id: str
    source_snapshot_sha256: str
    envelope_kind: StructuredEnvelopeKind | str
    scope_kind: StructuredEnvelopeScopeKind | str
    scope_value: str
    identity_raw: str
    identity_normalized: str
    parent_envelope_id: str | None
    pdf_page_start: int
    pdf_page_end: int
    printed_page_start: str | None
    printed_page_end: str | None
    confidence: float
    status: StructuredEnvelopeStatus | str
    issues: tuple[str, ...] = field(default_factory=tuple)
    region_links: tuple[tuple[str, str, int], ...] = field(default_factory=tuple)
    source_object_links: tuple[tuple[str, str, int], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _validate_page_range(self.pdf_page_start, self.pdf_page_end)
        _validate_confidence(self.confidence)
        _validate_required_text("id", self.id)
        _validate_required_text("book_id", self.book_id)
        _validate_required_text("source_snapshot_sha256", self.source_snapshot_sha256)


@dataclass(frozen=True)
class StructuredReviewAction:
    id: str
    candidate_id: str | None
    envelope_id: str | None
    validated_object_id: str | None
    action_kind: StructuredReviewActionKind | str
    action_payload_json: dict[str, Any]
    reviewer: str = "local_user"

    def __post_init__(self) -> None:
        _validate_required_text("id", self.id)
        _validate_required_text("reviewer", self.reviewer)


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


def _stable_json(value: Any) -> str:
    import json

    return json.dumps(value, sort_keys=True, separators=(",", ":"))


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
