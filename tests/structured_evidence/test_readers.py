from __future__ import annotations

from wfrp_companion.structured_evidence import readers
from wfrp_companion.structured_evidence.readers import (
    PageTextSnapshot,
    SourceObjectLinkSnapshot,
    SourceObjectSnapshot,
    layout_observations_from_pages,
    page_reference_observations_from_pages,
    reader_observations_from_source_objects,
)
from wfrp_companion.source_objects.layout import LayoutPage


def test_source_object_reader_observes_tables_rows_profiles_and_stats() -> None:
    objects = (
        SourceObjectSnapshot(
            id="table",
            book_id="core-rules",
            page_id="core-rules:112",
            page_number=112,
            object_type="table",
            title="Table 5-6: Advanced Armour",
            text="Table 5-6: Advanced Armour\n| Location | AP |",
            heading_path=("Chapter V", "Armour"),
            page_start=112,
            page_end=112,
            text_snapshot_sha256="snapshot",
            confidence=0.82,
        ),
        SourceObjectSnapshot(
            id="row",
            book_id="core-rules",
            page_id="core-rules:112",
            page_number=112,
            object_type="table_row",
            title="Advanced Armour row 1",
            text="| Head | 1 |",
            heading_path=("Chapter V", "Armour"),
            page_start=112,
            page_end=112,
            text_snapshot_sha256="snapshot",
            confidence=0.76,
            parent_object_id="table",
        ),
        SourceObjectSnapshot(
            id="profile",
            book_id="bestiary",
            page_id="bestiary:104",
            page_number=104,
            object_type="monster_profile",
            title="Common Orc",
            text="Common Orc\nSkills: Intimidate\nTalents: Menacing",
            heading_path=("Greenskins",),
            page_start=104,
            page_end=104,
            text_snapshot_sha256="snapshot",
            confidence=0.78,
        ),
        SourceObjectSnapshot(
            id="stat",
            book_id="bestiary",
            page_id="bestiary:104",
            page_number=104,
            object_type="stat_block",
            title="Common Orc Statistics",
            text="WS BS S T Ag Int WP Fel\n35 35 35 45 25 25 30 20",
            heading_path=("Greenskins",),
            page_start=104,
            page_end=104,
            text_snapshot_sha256="snapshot",
            confidence=0.82,
            parent_object_id="profile",
        ),
    )

    observations = reader_observations_from_source_objects(objects)

    by_object = {observation.source_object_id: observation for observation in observations}
    assert by_object["table"].observation_type == "table_region"
    assert by_object["table"].object_shape == "structured_table"
    assert by_object["table"].table_number == "5-6"
    assert by_object["row"].observation_type == "table_row"
    assert by_object["row"].payload_json["parent_source_object_id"] == "table"
    assert by_object["profile"].object_shape == "profile_bundle"
    assert by_object["profile"].entity_kind == "monster"
    assert by_object["stat"].observation_type == "profile_stat_block"


def test_page_text_reader_observes_table_references_without_source_objects() -> None:
    pages = (
        PageTextSnapshot(
            page_id="core-rules:112",
            book_id="core-rules",
            page_number=112,
            text="The advanced armour options are listed in Table 5-6.",
            text_snapshot_sha256="page-snapshot",
        ),
    )

    observations = page_reference_observations_from_pages(
        pages,
        known_table_numbers=frozenset(),
    )

    assert len(observations) == 1
    assert observations[0].observation_type == "page_reference"
    assert observations[0].table_number == "5-6"
    assert observations[0].payload_json["reference_text"] == "Table 5-6"


def test_page_text_reader_deduplicates_repeated_table_references() -> None:
    pages = (
        PageTextSnapshot(
            page_id="core-rules:112",
            book_id="core-rules",
            page_number=112,
            text="Table 5-6 appears here. Table 5-6 is repeated later.",
            text_snapshot_sha256="page-snapshot",
        ),
    )

    observations = page_reference_observations_from_pages(
        pages,
        known_table_numbers=frozenset(),
    )

    assert len(observations) == 1
    assert observations[0].table_number == "5-6"


def test_page_text_reader_skips_references_already_backed_by_tables() -> None:
    pages = (
        PageTextSnapshot(
            page_id="core-rules:130",
            book_id="core-rules",
            page_number=130,
            text="Roll on Table 6-1.",
            text_snapshot_sha256="page-snapshot",
        ),
    )

    observations = page_reference_observations_from_pages(
        pages,
        known_table_numbers=frozenset({"6-1"}),
    )

    assert observations == ()


def test_layout_reader_records_pymupdf_word_geometry_observations() -> None:
    pages = (
        PageTextSnapshot(
            page_id="core-rules:112",
            book_id="core-rules",
            page_number=112,
            text="Advanced armour table text.",
            text_snapshot_sha256="page-snapshot",
        ),
    )
    layout_pages = (
        LayoutPage(
            page_number=112,
            has_word_geometry=True,
            word_count=42,
            block_count=6,
        ),
        LayoutPage(
            page_number=113,
            has_word_geometry=True,
            word_count=7,
            block_count=1,
        ),
    )

    observations = layout_observations_from_pages(
        book_id="core-rules",
        pages=pages,
        layout_pages=layout_pages,
    )

    assert len(observations) == 1
    assert observations[0].reader_name == "pymupdf_words"
    assert observations[0].observation_type == "layout_metadata"
    assert observations[0].object_shape is None
    assert observations[0].payload_json == {
        "has_word_geometry": True,
        "word_count": 42,
        "block_count": 6,
    }
    assert observations[0].text_snapshot_sha256 == "page-snapshot"


def test_link_snapshots_are_hashable_for_reader_grouping() -> None:
    link = SourceObjectLinkSnapshot(
        id="link",
        from_object_id="row",
        to_object_id="table",
        link_type="table_row",
    )

    assert {link} == {link}


def test_reader_skips_unsupported_source_object_types() -> None:
    observations = reader_observations_from_source_objects(
        (
            SourceObjectSnapshot(
                id="rule",
                book_id="core-rules",
                page_id="core-rules:130",
                page_number=130,
                object_type="rule_section",
                title="Hit Locations",
                text="Rules text.",
                heading_path=("Combat",),
                page_start=130,
                page_end=130,
                text_snapshot_sha256="snapshot",
                confidence=0.9,
            ),
        )
    )

    assert observations == ()


def test_reader_finds_table_number_from_text_and_classifies_table_kinds() -> None:
    observations = reader_observations_from_source_objects(
        (
            SourceObjectSnapshot(
                id="table-from-text",
                book_id="core-rules",
                page_id="core-rules:130",
                page_number=130,
                object_type="table",
                title="Results",
                text="Table 6-1: Hit Location\n| Roll | Location |",
                heading_path=("Combat",),
                page_start=130,
                page_end=130,
                text_snapshot_sha256="snapshot",
                confidence=0.86,
            ),
            SourceObjectSnapshot(
                id="combat-table",
                book_id="core-rules",
                page_id="core-rules:131",
                page_number=131,
                object_type="table",
                title="Hit Location Results",
                text="| Roll | Location |",
                heading_path=("Combat",),
                page_start=131,
                page_end=131,
                text_snapshot_sha256="snapshot",
                confidence=0.8,
            ),
            SourceObjectSnapshot(
                id="rules-table",
                book_id="core-rules",
                page_id="core-rules:132",
                page_number=132,
                object_type="table",
                title="Magic Results",
                text="| Roll | Result |",
                heading_path=("Magic",),
                page_start=132,
                page_end=132,
                text_snapshot_sha256="snapshot",
                confidence=0.8,
            ),
        )
    )

    by_id = {observation.source_object_id: observation for observation in observations}
    assert by_id["table-from-text"].table_number == "6-1"
    assert by_id["combat-table"].content_kind == "combat_table"
    assert by_id["rules-table"].content_kind == "rules_table"


def test_reader_json_parsers_fail_closed() -> None:
    assert readers._parse_heading_path("{") == ()
    assert readers._parse_heading_path("{}") == ()
    assert readers._parse_metadata("{") == {}
    assert readers._parse_metadata("[]") == {}
