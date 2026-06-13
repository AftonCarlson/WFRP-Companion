from __future__ import annotations

import pytest

from wfrp_companion.structured_evidence.models import (
    StructuredEvidenceCandidate,
    StructuredLookupPolicy,
    StructuredObjectShape,
    ValidatedStructuredObject,
    deterministic_candidate_id,
    deterministic_validated_object_id,
    normalize_structured_alias,
    normalize_table_number,
)
from wfrp_companion.structured_evidence.payloads import (
    payload_hash,
    table_payload_search_text,
    validate_profile_bundle_payload,
    validate_structured_table_payload,
)


def table_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "object_shape": "structured_table",
        "content_kind": "equipment_table",
        "identity": {
            "table_number_raw": "Table 5-6",
            "table_number_normalized": "5-6",
            "title_raw": "Advanced Armour",
            "title_normalized": "advanced armour",
            "aliases": ["table 5-6", "armour points by location"],
        },
        "source": {
            "book_id": "core-rules",
            "chapter_path": ["Chapter V"],
            "printed_page_start": "112",
            "printed_page_end": "112",
            "pdf_page_start": 112,
            "pdf_page_end": 112,
            "source_object_ids": ["table-source"],
            "text_snapshot_sha256": "snapshot",
        },
        "structure": {
            "columns": [
                {"key": "location", "label_raw": "Location", "confidence": 0.9},
                {"key": "ap", "label_raw": "AP", "confidence": 0.9},
            ],
            "rows": [
                {
                    "ordinal": 1,
                    "range_raw": None,
                    "cells": {"location": "Head", "ap": "1"},
                    "raw_text": "Head 1",
                    "confidence": 0.9,
                    "suspicious_cells": [],
                }
            ],
        },
        "provenance": {
            "reader_names": ["page_text_import", "source_object_heuristic"],
            "confidence": 0.9,
            "issues": [],
        },
    }


def profile_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "object_shape": "profile_bundle",
        "content_kind": "creature_profile",
        "entity_kind": "monster",
        "identity": {
            "name_raw": "Common Orc",
            "name_normalized": "common orc",
            "aliases": ["orc", "common orc"],
        },
        "source": {
            "book_id": "bestiary",
            "chapter_path": ["Greenskins"],
            "printed_page_start": "104",
            "printed_page_end": "104",
            "pdf_page_start": 104,
            "pdf_page_end": 104,
            "source_object_ids": ["profile-source"],
            "text_snapshot_sha256": "snapshot",
        },
        "profile": {
            "description": "A short synthetic description.",
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
            "skills": ["synthetic skill"],
            "talents": ["synthetic talent"],
            "traits": ["synthetic trait"],
            "special_rules": ["synthetic rule"],
            "weapons": ["synthetic weapon"],
            "armour": ["synthetic armour"],
            "trappings": ["synthetic trapping"],
            "notes": [],
        },
        "provenance": {
            "reader_names": ["page_text_import", "source_object_heuristic"],
            "field_confidence": {"ws": 0.9},
            "suspicious_fields": [],
        },
    }


def test_normalizers_are_stable_without_embedding_private_text() -> None:
    assert normalize_table_number("Table 5-6") == "5-6"
    assert normalize_table_number("table 5-6") == "5-6"
    assert normalize_table_number("Advanced Armour") == "advanced armour"
    assert normalize_structured_alias("  Warriors of Chaos! ") == "warriors of chaos"

    first = deterministic_candidate_id(
        book_id="core-rules",
        object_shape="structured_table",
        identity="table 5-6 advanced armour",
        page_start=112,
        page_end=112,
        snapshot_sha256="snapshot",
        extractor_version="structured-test-v1",
    )
    second = deterministic_candidate_id(
        book_id="core-rules",
        object_shape="structured_table",
        identity="table 5-6 advanced armour",
        page_start=112,
        page_end=112,
        snapshot_sha256="snapshot",
        extractor_version="structured-test-v1",
    )
    assert first == second
    assert "advanced" not in first
    assert first.startswith("structured-candidate:core-rules:p112-p112:")


def test_candidate_and_validated_models_validate_lifecycle_fields() -> None:
    candidate = StructuredEvidenceCandidate(
        id="candidate",
        book_id="core-rules",
        primary_page_id="core-rules:112",
        object_shape=StructuredObjectShape.STRUCTURED_TABLE,
        content_kind="equipment_table",
        entity_kind="none",
        page_start=112,
        page_end=112,
        payload_json=table_payload(),
        search_text="advanced armour table 5-6",
        confidence=0.9,
        status="needs_review",
        text_snapshot_sha256="snapshot",
        structured_extractor_version="structured-test-v1",
    )
    assert candidate.object_shape is StructuredObjectShape.STRUCTURED_TABLE
    assert candidate.status == "needs_review"

    with pytest.raises(ValueError, match="confidence"):
        StructuredEvidenceCandidate(
            id="bad-confidence",
            book_id="core-rules",
            primary_page_id="core-rules:112",
            object_shape=StructuredObjectShape.STRUCTURED_TABLE,
            content_kind="equipment_table",
            entity_kind="none",
            page_start=112,
            page_end=112,
            payload_json=table_payload(),
            search_text="advanced armour table",
            confidence=1.5,
            status="candidate",
            text_snapshot_sha256="snapshot",
            structured_extractor_version="structured-test-v1",
        )
    with pytest.raises(ValueError, match="candidate status"):
        StructuredEvidenceCandidate(
            id="bad-status",
            book_id="core-rules",
            primary_page_id="core-rules:112",
            object_shape=StructuredObjectShape.STRUCTURED_TABLE,
            content_kind="equipment_table",
            entity_kind="none",
            page_start=112,
            page_end=112,
            payload_json=table_payload(),
            search_text="advanced armour table",
            confidence=0.9,
            status="trusted",
            text_snapshot_sha256="snapshot",
            structured_extractor_version="structured-test-v1",
        )
    with pytest.raises(ValueError, match="page_end"):
        StructuredEvidenceCandidate(
            id="bad-page-range",
            book_id="core-rules",
            primary_page_id="core-rules:112",
            object_shape=StructuredObjectShape.STRUCTURED_TABLE,
            content_kind="equipment_table",
            entity_kind="none",
            page_start=113,
            page_end=112,
            payload_json=table_payload(),
            search_text="advanced armour table",
            confidence=0.9,
            status="candidate",
            text_snapshot_sha256="snapshot",
            structured_extractor_version="structured-test-v1",
        )
    with pytest.raises(ValueError, match="id"):
        StructuredEvidenceCandidate(
            id=" ",
            book_id="core-rules",
            primary_page_id="core-rules:112",
            object_shape=StructuredObjectShape.STRUCTURED_TABLE,
            content_kind="equipment_table",
            entity_kind="none",
            page_start=112,
            page_end=112,
            payload_json=table_payload(),
            search_text="advanced armour table",
            confidence=0.9,
            status="candidate",
            text_snapshot_sha256="snapshot",
            structured_extractor_version="structured-test-v1",
        )

    validated = ValidatedStructuredObject(
        id=deterministic_validated_object_id(
            book_id="core-rules",
            object_shape="structured_table",
            identity="5-6",
        ),
        book_id="core-rules",
        primary_page_id="core-rules:112",
        object_shape=StructuredObjectShape.STRUCTURED_TABLE,
        content_kind="equipment_table",
        entity_kind="none",
        page_start=112,
        page_end=112,
        payload_schema_version=1,
        payload_json=table_payload(),
        source_snapshot_sha256="snapshot",
        validation_status="active",
        review_state="human_approved",
    )
    assert validated.validation_status == "active"

    with pytest.raises(ValueError, match="validation_status"):
        ValidatedStructuredObject(
            id="bad-status",
            book_id="core-rules",
            primary_page_id="core-rules:112",
            object_shape=StructuredObjectShape.STRUCTURED_TABLE,
            content_kind="equipment_table",
            entity_kind="none",
            page_start=112,
            page_end=112,
            payload_schema_version=1,
            payload_json=table_payload(),
            source_snapshot_sha256="snapshot",
            validation_status="trusted",
            review_state="human_approved",
        )
    with pytest.raises(ValueError, match="review_state"):
        ValidatedStructuredObject(
            id="bad-review-state",
            book_id="core-rules",
            primary_page_id="core-rules:112",
            object_shape=StructuredObjectShape.STRUCTURED_TABLE,
            content_kind="equipment_table",
            entity_kind="none",
            page_start=112,
            page_end=112,
            payload_schema_version=1,
            payload_json=table_payload(),
            source_snapshot_sha256="snapshot",
            validation_status="active",
            review_state="unreviewed",
        )
    with pytest.raises(ValueError, match="payload_schema_version"):
        ValidatedStructuredObject(
            id="bad-schema-version",
            book_id="core-rules",
            primary_page_id="core-rules:112",
            object_shape=StructuredObjectShape.STRUCTURED_TABLE,
            content_kind="equipment_table",
            entity_kind="none",
            page_start=112,
            page_end=112,
            payload_schema_version=0,
            payload_json=table_payload(),
            source_snapshot_sha256="snapshot",
            validation_status="active",
            review_state="human_approved",
        )
    with pytest.raises(ValueError, match="page_start"):
        ValidatedStructuredObject(
            id="bad-page-start",
            book_id="core-rules",
            primary_page_id="core-rules:112",
            object_shape=StructuredObjectShape.STRUCTURED_TABLE,
            content_kind="equipment_table",
            entity_kind="none",
            page_start=0,
            page_end=112,
            payload_schema_version=1,
            payload_json=table_payload(),
            source_snapshot_sha256="snapshot",
            validation_status="active",
            review_state="human_approved",
        )


def test_payload_validators_reject_malformed_structured_json() -> None:
    table = validate_structured_table_payload(table_payload())
    assert table["identity"]["table_number_normalized"] == "5-6"
    assert "advanced armour" in table_payload_search_text(table)
    assert len(payload_hash(table)) == 64

    malformed_table = table_payload()
    malformed_table["object_shape"] = "profile_bundle"
    with pytest.raises(ValueError, match="structured_table"):
        validate_structured_table_payload(malformed_table)

    profile = validate_profile_bundle_payload(profile_payload())
    assert profile["profile"]["main_profile"]["ws"] == 35

    malformed_profile = profile_payload()
    malformed_profile["profile"] = {}
    with pytest.raises(ValueError, match="main_profile"):
        validate_profile_bundle_payload(malformed_profile)


def test_structured_lookup_policy_values_are_explicit() -> None:
    assert StructuredLookupPolicy.REQUIRED.value == "required"
    assert StructuredLookupPolicy.ALLOWED.value == "allowed"
    assert StructuredLookupPolicy.SUPPORTING_ONLY.value == "supporting_only"
    assert StructuredLookupPolicy.FORBIDDEN.value == "forbidden"
    assert StructuredLookupPolicy.NOT_PRIMARY.value == "not_primary"
