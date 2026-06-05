from __future__ import annotations

import json

from wfrp_companion.source_objects.extractor import (
    SourcePage,
    build_page_chunks,
    extract_objects_from_pages,
    heading_lines,
    uncovered_spans,
)
from wfrp_companion.source_objects.layout import LayoutPage


def test_extract_objects_from_pages_creates_rule_sections_and_page_chunks() -> None:
    pages = (
        SourcePage(
            page_id="rules:1",
            book_id="rules",
            page_number=1,
            extraction_method="embedded",
            ocr_attempted=False,
            text_sha256="sha-1",
            text=(
                "Chapter I: Combat\n"
                "Critical Hits\n"
                "When damage exceeds wounds, roll on the critical table.\n"
            ),
        ),
        SourcePage(
            page_id="rules:2",
            book_id="rules",
            page_number=2,
            extraction_method="ocr",
            ocr_attempted=True,
            text_sha256="sha-2",
            text="A fallback paragraph with no heading but useful rules text.",
        ),
    )
    objects = extract_objects_from_pages(
        book_id="rules",
        text_snapshot_sha256="snapshot",
        pages=pages,
        layout_pages=(
            LayoutPage(
                page_number=1,
                has_word_geometry=True,
                word_count=12,
                block_count=2,
            ),
        ),
    )

    assert [source_object.object_type for source_object in objects] == [
        "rule_section",
        "page_chunk",
    ]
    rule_section = objects[0]
    page_chunk = objects[1]
    assert rule_section.title == "Critical Hits"
    assert rule_section.heading_path == ("Chapter I: Combat", "Critical Hits")
    assert rule_section.page_start == 1
    assert rule_section.text_snapshot_sha256 == "snapshot"
    assert json.loads(rule_section.metadata_json) == {
        "layout_available": True,
        "ocr_derived": False,
        "ocr_layout_available": True,
        "word_geometry_available": True,
    }
    assert page_chunk.object_type == "page_chunk"
    assert page_chunk.page_start == 2
    assert page_chunk.confidence == 0.45
    assert json.loads(page_chunk.metadata_json) == {
        "layout_available": False,
        "ocr_derived": True,
        "ocr_layout_available": False,
        "word_geometry_available": False,
    }


def test_extract_objects_from_pages_keeps_uncovered_text_as_page_chunks() -> None:
    pages = (
        SourcePage(
            page_id="rules:1",
            book_id="rules",
            page_number=1,
            extraction_method="embedded",
            ocr_attempted=False,
            text_sha256="sha-1",
            text=(
                "Opening note before the heading.\n"
                "Chapter I: Combat\n"
                "Critical Hits\n"
                "Roll on the result table.\n"
                "Closing note after the section."
            ),
        ),
    )

    objects = extract_objects_from_pages(
        book_id="rules",
        text_snapshot_sha256="snapshot",
        pages=pages,
        layout_pages=(),
    )

    assert [source_object.object_type for source_object in objects] == [
        "rule_section",
        "page_chunk",
    ]
    assert objects[1].text == "Opening note before the heading."
    assert objects[1].char_start == 0


def test_build_page_chunks_skips_whitespace_only_uncovered_spans() -> None:
    page = SourcePage(
        page_id="rules:1",
        book_id="rules",
        page_number=1,
        extraction_method="embedded",
        ocr_attempted=False,
        text_sha256="sha-1",
        text="   covered",
    )

    chunks = build_page_chunks(
        page=page,
        book_id="rules",
        text_snapshot_sha256="snapshot",
        metadata={},
        covered_spans=((3, len(page.text)),),
    )

    assert chunks == ()


def test_uncovered_spans_includes_trailing_uncovered_text() -> None:
    assert uncovered_spans(12, ((2, 5),)) == ((0, 2), (5, 12))


def test_extract_objects_from_pages_uses_page_local_ordinals_for_stable_ids() -> None:
    baseline_pages = (
        SourcePage(
            page_id="rules:1",
            book_id="rules",
            page_number=1,
            extraction_method="embedded",
            ocr_attempted=False,
            text_sha256="sha-1",
            text="Chapter I: Combat\nCritical Hits\nRoll on the result table.",
        ),
        SourcePage(
            page_id="rules:2",
            book_id="rules",
            page_number=2,
            extraction_method="embedded",
            ocr_attempted=False,
            text_sha256="sha-2",
            text="Chapter II: Travel\nRoad Hazards\nTest when roads flood.",
        ),
    )
    inserted_pages = (
        SourcePage(
            page_id="rules:1",
            book_id="rules",
            page_number=1,
            extraction_method="embedded",
            ocr_attempted=False,
            text_sha256="sha-1",
            text=(
                "Chapter I: Combat\n"
                "New Earlier Rule\n"
                "This inserted rule should not churn later pages.\n"
                "Critical Hits\n"
                "Roll on the result table."
            ),
        ),
        baseline_pages[1],
    )

    baseline = extract_objects_from_pages(
        book_id="rules",
        text_snapshot_sha256="snapshot",
        pages=baseline_pages,
        layout_pages=(),
    )
    inserted = extract_objects_from_pages(
        book_id="rules",
        text_snapshot_sha256="snapshot",
        pages=inserted_pages,
        layout_pages=(),
    )

    baseline_page_2_id = next(
        source_object.id
        for source_object in baseline
        if source_object.title == "Road Hazards"
    )
    inserted_page_2_id = next(
        source_object.id
        for source_object in inserted
        if source_object.title == "Road Hazards"
    )
    assert inserted_page_2_id == baseline_page_2_id


def test_extract_objects_from_pages_keeps_same_page_section_ids_stable() -> None:
    baseline_pages = (
        SourcePage(
            page_id="rules:1",
            book_id="rules",
            page_number=1,
            extraction_method="embedded",
            ocr_attempted=False,
            text_sha256="sha-1",
            text=(
                "Critical Hits\n"
                "Roll on the result table.\n"
                "Armour\n"
                "Armour reduces incoming damage."
            ),
        ),
    )
    inserted_pages = (
        SourcePage(
            page_id="rules:1",
            book_id="rules",
            page_number=1,
            extraction_method="embedded",
            ocr_attempted=False,
            text_sha256="sha-1",
            text=(
                "New Earlier Rule\n"
                "This inserted rule should not churn unrelated sections.\n"
                "Critical Hits\n"
                "Roll on the result table.\n"
                "Armour\n"
                "Armour reduces incoming damage."
            ),
        ),
    )

    baseline = extract_objects_from_pages(
        book_id="rules",
        text_snapshot_sha256="snapshot",
        pages=baseline_pages,
        layout_pages=(),
    )
    inserted = extract_objects_from_pages(
        book_id="rules",
        text_snapshot_sha256="snapshot",
        pages=inserted_pages,
        layout_pages=(),
    )

    baseline_critical_id = next(
        source_object.id
        for source_object in baseline
        if source_object.title == "Critical Hits"
    )
    inserted_critical_id = next(
        source_object.id
        for source_object in inserted
        if source_object.title == "Critical Hits"
    )
    assert inserted_critical_id == baseline_critical_id


def test_page_metadata_treats_embedded_text_as_not_ocr_derived() -> None:
    objects = extract_objects_from_pages(
        book_id="rules",
        text_snapshot_sha256="snapshot",
        pages=(
            SourcePage(
                page_id="rules:1",
                book_id="rules",
                page_number=1,
                extraction_method="embedded",
                ocr_attempted=True,
                text_sha256="sha-1",
                text="Plain page text without headings.",
            ),
        ),
        layout_pages=(),
    )

    metadata = json.loads(objects[0].metadata_json)
    assert metadata["ocr_derived"] is False
    assert objects[0].confidence == 0.55


def test_extract_objects_from_pages_skips_empty_pages() -> None:
    objects = extract_objects_from_pages(
        book_id="rules",
        text_snapshot_sha256="snapshot",
        pages=(
            SourcePage(
                page_id="rules:1",
                book_id="rules",
                page_number=1,
                extraction_method="ocr-empty",
                ocr_attempted=True,
                text_sha256="empty",
                text="   \n  ",
            ),
        ),
        layout_pages=(),
    )

    assert objects == ()


def test_heading_lines_rejects_sentence_noise_and_accepts_uppercase() -> None:
    headings = heading_lines(
        "Hi\n"
        "An ordinary sentence.\n"
        "This Heading Has Too Many Words For The Small Detector\n"
        "12345\n"
        "LOUD TITLE\n"
    )

    assert headings == ((86, 96, "LOUD TITLE"),)
