from __future__ import annotations

import pytest

from wfrp_companion.source_objects.models import (
    SOURCE_OBJECT_TYPES,
    SourceObject,
    deterministic_source_object_id,
)


def test_source_object_validates_type_confidence_and_page_range() -> None:
    source_object = SourceObject(
        id="core-rules:p1-p1:rule_section:1:aaaaaaaaaaaa",
        book_id="core-rules",
        page_id="core-rules:1",
        object_type="rule_section",
        page_start=1,
        page_end=1,
        text="Critical hits are dangerous.",
        search_text="Critical hits dangerous combat",
        confidence=0.8,
        extraction_method="heading_heuristic",
        text_snapshot_sha256="text-snapshot",
    )

    assert source_object.object_type == "rule_section"
    assert "table" in SOURCE_OBJECT_TYPES
    assert "glossary_entry" in SOURCE_OBJECT_TYPES

    with pytest.raises(ValueError, match="Unsupported source object type"):
        SourceObject(
            id="bad-type",
            book_id="core-rules",
            page_id="core-rules:1",
            object_type="rumor",
            page_start=1,
            page_end=1,
            text="bad",
            search_text="bad",
            confidence=0.5,
            extraction_method="test",
            text_snapshot_sha256="text-snapshot",
        )

    with pytest.raises(ValueError, match="confidence"):
        SourceObject(
            id="bad-confidence",
            book_id="core-rules",
            page_id="core-rules:1",
            object_type="rule_section",
            page_start=1,
            page_end=1,
            text="bad",
            search_text="bad",
            confidence=1.1,
            extraction_method="test",
            text_snapshot_sha256="text-snapshot",
        )

    with pytest.raises(ValueError, match="page_end"):
        SourceObject(
            id="bad-page-range",
            book_id="core-rules",
            page_id="core-rules:2",
            object_type="rule_section",
            page_start=2,
            page_end=1,
            text="bad",
            search_text="bad",
            confidence=0.5,
            extraction_method="test",
            text_snapshot_sha256="text-snapshot",
        )

    with pytest.raises(ValueError, match="page_start"):
        SourceObject(
            id="bad-page-start",
            book_id="core-rules",
            page_id="core-rules:0",
            object_type="rule_section",
            page_start=0,
            page_end=1,
            text="bad",
            search_text="bad",
            confidence=0.5,
            extraction_method="test",
            text_snapshot_sha256="text-snapshot",
        )


def test_deterministic_source_object_id_is_stable_and_does_not_embed_text() -> None:
    first = deterministic_source_object_id(
        book_id="core-rules",
        page_start=12,
        page_end=13,
        object_type="table",
        ordinal=2,
        text="Critical hits table text that must not appear in the identifier.",
    )
    second = deterministic_source_object_id(
        book_id="core-rules",
        page_start=12,
        page_end=13,
        object_type="table",
        ordinal=2,
        text="Critical hits table text that must not appear in the identifier.",
    )
    different = deterministic_source_object_id(
        book_id="core-rules",
        page_start=12,
        page_end=13,
        object_type="table",
        ordinal=3,
        text="Critical hits table text that must not appear in the identifier.",
    )

    assert first == second
    assert first != different
    assert first.startswith("core-rules:p12-p13:table:2:")
    assert "Critical" not in first
    assert len(first.rsplit(":", maxsplit=1)[-1]) == 12


def test_deterministic_source_object_id_normalizes_text_before_hashing() -> None:
    compact = deterministic_source_object_id(
        book_id="core-rules",
        page_start=12,
        page_end=13,
        object_type="table",
        ordinal=2,
        text="Critical hits table text",
    )
    noisy_whitespace = deterministic_source_object_id(
        book_id="core-rules",
        page_start=12,
        page_end=13,
        object_type="table",
        ordinal=2,
        text="  Critical\t hits\n table   text  ",
    )

    assert compact == noisy_whitespace


def test_deterministic_source_object_id_validates_inputs() -> None:
    with pytest.raises(ValueError, match="Unsupported source object type"):
        deterministic_source_object_id(
            book_id="core-rules",
            page_start=1,
            page_end=1,
            object_type="rumor",
            ordinal=1,
            text="bad",
        )

    with pytest.raises(ValueError, match="page_start"):
        deterministic_source_object_id(
            book_id="core-rules",
            page_start=0,
            page_end=1,
            object_type="table",
            ordinal=1,
            text="bad",
        )

    with pytest.raises(ValueError, match="page_end"):
        deterministic_source_object_id(
            book_id="core-rules",
            page_start=2,
            page_end=1,
            object_type="table",
            ordinal=1,
            text="bad",
        )

    with pytest.raises(ValueError, match="ordinal"):
        deterministic_source_object_id(
            book_id="core-rules",
            page_start=1,
            page_end=1,
            object_type="table",
            ordinal=0,
            text="bad",
        )
