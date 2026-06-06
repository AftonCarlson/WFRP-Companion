from __future__ import annotations

import json

from wfrp_companion.source_objects import extractor
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


def test_extract_objects_from_pages_emits_tables_rows_and_parent_links() -> None:
    page_text = (
        "Chapter I: Weather\n"
        "Weather Results\n"
        "| Roll | Result |\n"
        "| 1 | Clear skies |\n"
        "| 2 | Storms force a travel test |\n"
        "Use the result for the next journey.\n"
    )
    pages = (
        SourcePage(
            page_id="rules:4",
            book_id="rules",
            page_number=4,
            extraction_method="embedded",
            ocr_attempted=False,
            text_sha256="sha-4",
            text=page_text,
        ),
    )

    objects = extract_objects_from_pages(
        book_id="rules",
        text_snapshot_sha256="snapshot",
        pages=pages,
        layout_pages=(),
    )

    table = next(source_object for source_object in objects if source_object.object_type == "table")
    table_rows = tuple(
        source_object
        for source_object in objects
        if source_object.object_type == "table_row"
    )

    assert table.title == "Weather Results"
    assert table.page_start == 4
    assert table.page_end == 4
    assert "Storms force a travel test" in table.text
    assert [row.parent_object_id for row in table_rows] == [table.id, table.id]
    assert [row.title for row in table_rows] == [
        "Weather Results row 1",
        "Weather Results row 2",
    ]
    assert all("table row" in row.search_text for row in table_rows)


def test_same_page_tables_with_identical_rows_get_unique_row_ids() -> None:
    page_text = (
        "Morning Results\n"
        "| Roll | Result |\n"
        "| 1 | Shared outcome |\n"
        "Evening Results\n"
        "| Roll | Result |\n"
        "| 1 | Shared outcome |\n"
    )

    objects = extract_objects_from_pages(
        book_id="rules",
        text_snapshot_sha256="snapshot",
        pages=(
            SourcePage(
                page_id="rules:6",
                book_id="rules",
                page_number=6,
                extraction_method="embedded",
                ocr_attempted=False,
                text_sha256="sha-6",
                text=page_text,
            ),
        ),
        layout_pages=(),
    )

    row_ids = [
        source_object.id
        for source_object in objects
        if source_object.object_type == "table_row"
    ]
    assert len(row_ids) == 2
    assert len(set(row_ids)) == 2


def test_extract_objects_from_pages_emits_stat_profiles_and_stat_blocks() -> None:
    page_text = (
        "Chapter II: People\n"
        "Captain Mira\n"
        "M WS BS S T W I A Dex Int WP Fel\n"
        "4 41 32 3 3 12 38 1 34 35 36 37\n"
        "Skills: Command, Perception\n"
        "Talents: Coolheaded\n"
    )
    pages = (
        SourcePage(
            page_id="rules:5",
            book_id="rules",
            page_number=5,
            extraction_method="embedded",
            ocr_attempted=False,
            text_sha256="sha-5",
            text=page_text,
        ),
    )

    objects = extract_objects_from_pages(
        book_id="rules",
        text_snapshot_sha256="snapshot",
        pages=pages,
        layout_pages=(),
    )

    profile = next(
        source_object for source_object in objects if source_object.object_type == "npc_profile"
    )
    stat_block = next(
        source_object for source_object in objects if source_object.object_type == "stat_block"
    )

    assert profile.title == "Captain Mira"
    assert stat_block.title == "Captain Mira Statistics"
    assert stat_block.parent_object_id == profile.id
    assert "WS BS" in stat_block.text
    assert "Skills: Command" in profile.text
    assert "stat block" in stat_block.search_text


def test_extract_objects_from_pages_emits_index_glossary_and_cross_references() -> None:
    pages = (
        SourcePage(
            page_id="rules:8",
            book_id="rules",
            page_number=8,
            extraction_method="embedded",
            ocr_attempted=False,
            text_sha256="sha-8",
            text=(
                "Index\n"
                "Falling ..... 12\n"
                "Glossary\n"
                "Dooming: a ceremonial prophecy. See Falling.\n"
                "See also Weather Results on page 4.\n"
            ),
        ),
    )

    objects = extract_objects_from_pages(
        book_id="rules",
        text_snapshot_sha256="snapshot",
        pages=pages,
        layout_pages=(),
    )

    index_entry = next(
        source_object for source_object in objects if source_object.object_type == "index_entry"
    )
    glossary_entry = next(
        source_object for source_object in objects if source_object.object_type == "glossary_entry"
    )
    cross_reference = next(
        source_object for source_object in objects if source_object.object_type == "cross_reference"
    )

    assert index_entry.title == "Falling"
    assert json.loads(index_entry.metadata_json)["target_page"] == 12
    assert glossary_entry.title == "Dooming"
    assert json.loads(glossary_entry.metadata_json)["target_title"] == "Falling"
    assert cross_reference.title == "Weather Results"
    assert json.loads(cross_reference.metadata_json)["target_page"] == 4


def test_structured_extractor_edges_avoid_false_positive_objects() -> None:
    objects = extract_objects_from_pages(
        book_id="rules",
        text_snapshot_sha256="snapshot",
        pages=(
            SourcePage(
                page_id="rules:9",
                book_id="rules",
                page_number=9,
                extraction_method="embedded",
                ocr_attempted=False,
                text_sha256="sha-9",
                text=(
                    "| Roll | Result |\n"
                    "| --- | --- |\n"
                    "M WS BS S T W I A Dex Int WP Fel\n"
                    "4 41 32 3 3 12 38 1 34 35 36 37\n"
                    "Index\n"
                    "\n"
                    "Falling ..... 12\n"
                ),
            ),
        ),
        layout_pages=(),
    )

    assert "table" not in {source_object.object_type for source_object in objects}
    assert "stat_block" not in {source_object.object_type for source_object in objects}
    assert any(source_object.object_type == "index_entry" for source_object in objects)


def test_structured_extractor_helper_edges() -> None:
    lines = extractor.page_line_spans("| A | B |\nM WS BS S T W I A\n\n")
    plain_lines = extractor.page_line_spans("plain lowercase\n")

    assert extractor.preceding_content_line(lines, len(lines)) is None
    assert extractor.structured_heading_path(plain_lines, 0, fallback="Table 1") == (
        "Table 1",
    )
    assert extractor.is_stat_value_line("1 2 3") is False
    assert extractor.classify_profile_type("Ancient Creature") == "monster_profile"
    assert extractor.parse_cross_reference("No reference here.") is None


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


def test_overlapping_equivalent_rule_sections_get_unique_ids() -> None:
    objects = extract_objects_from_pages(
        book_id="rules",
        text_snapshot_sha256="snapshot",
        pages=(
            SourcePage(
                page_id="rules:7",
                book_id="rules",
                page_number=7,
                extraction_method="embedded",
                ocr_attempted=False,
                text_sha256="sha-7",
                text=(
                    "Chapter I: A Brief History of the\n"
                    "Cults of the Empire\n"
                    "Chapter I:\n"
                    "A Brief History of the Cults\n"
                    "of the Empire\n"
                ),
            ),
        ),
        layout_pages=(),
    )

    rule_sections = [
        source_object for source_object in objects if source_object.object_type == "rule_section"
    ]
    rule_ids = [source_object.id for source_object in rule_sections]
    assert len(rule_sections) == 2
    assert len(set(rule_ids)) == len(rule_ids)


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
