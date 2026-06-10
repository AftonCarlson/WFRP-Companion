from __future__ import annotations

from wfrp_companion.structured_evidence.candidates import (
    build_candidates_from_observations,
)
from wfrp_companion.structured_evidence.readers import (
    PageTextSnapshot,
    ReaderObservation,
    SourceObjectSnapshot,
    page_reference_observations_from_pages,
    reader_observations_from_source_objects,
)


def test_candidates_build_structured_table_from_table_and_rows() -> None:
    observations = reader_observations_from_source_objects(
        (
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
                id="row-head",
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
                id="row-body",
                book_id="core-rules",
                page_id="core-rules:112",
                page_number=112,
                object_type="table_row",
                title="Advanced Armour row 2",
                text="| Body | 3 |",
                heading_path=("Chapter V", "Armour"),
                page_start=112,
                page_end=112,
                text_snapshot_sha256="snapshot",
                confidence=0.76,
                parent_object_id="table",
            ),
        )
    )

    candidates = build_candidates_from_observations(observations)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.object_shape == "structured_table"
    assert candidate.table_number_normalized == "5-6"
    assert candidate.status == "candidate"
    assert candidate.source_object_ids == ("table", "row-head", "row-body")
    assert candidate.payload_json["structure"]["columns"][0]["key"] == "location"
    assert candidate.payload_json["structure"]["rows"][0]["cells"] == {
        "location": "Head",
        "ap": "1",
    }
    assert "advanced armour" in candidate.search_text


def test_candidates_build_profile_bundle_with_followup_fields() -> None:
    profile_text = """Common Orc
WS BS S T Ag Int WP Fel
35 35 35 45 25 25 30 20
A W SB TB M Mag IP FP
1 12 3 4 4 0 0 0
Skills: Intimidate
Talents: Menacing
Traits: Synthetic Trait
Special Rules: Synthetic Rule
Weapons: Choppa
Armour: Leather
Trappings: Teeth"""
    observations = reader_observations_from_source_objects(
        (
            SourceObjectSnapshot(
                id="profile",
                book_id="bestiary",
                page_id="bestiary:104",
                page_number=104,
                object_type="monster_profile",
                title="Common Orc",
                text=profile_text,
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
                text="\n".join(profile_text.splitlines()[1:5]),
                heading_path=("Greenskins",),
                page_start=104,
                page_end=104,
                text_snapshot_sha256="snapshot",
                confidence=0.82,
                parent_object_id="profile",
            ),
        )
    )

    candidates = build_candidates_from_observations(observations)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.object_shape == "profile_bundle"
    assert candidate.entity_kind == "monster"
    profile = candidate.payload_json["profile"]
    assert profile["main_profile"]["ws"] == 35
    assert profile["secondary_profile"]["w"] == 12
    assert profile["skills"] == ["Intimidate"]
    assert profile["talents"] == ["Menacing"]
    assert profile["traits"] == ["Synthetic Trait"]
    assert profile["special_rules"] == ["Synthetic Rule"]
    assert profile["weapons"] == ["Choppa"]
    assert profile["armour"] == ["Leather"]
    assert profile["trappings"] == ["Teeth"]


def test_candidates_mark_referenced_missing_table_as_needs_review() -> None:
    observations = page_reference_observations_from_pages(
        (
            PageTextSnapshot(
                page_id="core-rules:112",
                book_id="core-rules",
                page_number=112,
                text="The advanced armour options are listed in Table 5-6.",
                text_snapshot_sha256="page-snapshot",
            ),
        ),
        known_table_numbers=frozenset(),
    )

    candidates = build_candidates_from_observations(observations)

    assert len(candidates) == 1
    assert candidates[0].status == "needs_review"
    assert candidates[0].suspicious_flags == ("referenced_table_missing",)
    assert candidates[0].table_number_normalized == "5-6"


def test_candidates_skip_missing_reference_when_table_candidate_exists() -> None:
    observations = (
        ReaderObservation(
            id="table-observation",
            book_id="core-rules",
            page_id="core-rules:112",
            page_number=112,
            source_object_id="table",
            reader_name="source_object_heuristic",
            reader_version="test",
            observation_type="table_region",
            object_shape="structured_table",
            content_kind="equipment_table",
            entity_kind="rules",
            title="Table 5-6: Advanced Armour",
            table_number="5-6",
            payload_json={
                "text": "Table 5-6: Advanced Armour\n| Location | AP |",
                "heading_path": ["Armour"],
            },
            text_snapshot_sha256="snapshot",
            confidence=0.9,
        ),
        ReaderObservation(
            id="reference-observation",
            book_id="core-rules",
            page_id="core-rules:112",
            page_number=112,
            reader_name="page_text_reference",
            reader_version="test",
            observation_type="page_reference",
            object_shape="structured_table",
            content_kind="unknown",
            entity_kind="unknown",
            title="Referenced table 5-6",
            table_number="5-6",
            payload_json={"reference_text": "Table 5-6"},
            text_snapshot_sha256="snapshot",
            confidence=0.55,
        ),
    )

    candidates = build_candidates_from_observations(observations)

    assert len(candidates) == 1
    assert candidates[0].title == "Table 5-6: Advanced Armour"
    assert candidates[0].suspicious_flags == ()


def test_table_candidate_falls_back_when_no_pipe_cells_or_rows() -> None:
    observations = (
        ReaderObservation(
            id="table-observation",
            book_id="core-rules",
            page_id="core-rules:112",
            page_number=112,
            source_object_id="table",
            reader_name="source_object_heuristic",
            reader_version="test",
            observation_type="table_region",
            object_shape="structured_table",
            content_kind="rules_table",
            entity_kind="rules",
            title="Table 6-1",
            table_number="6-1",
            payload_json={"text": "No pipe cells here"},
            text_snapshot_sha256="snapshot",
            confidence=0.7,
        ),
    )

    candidates = build_candidates_from_observations(observations)

    assert len(candidates) == 1
    structure = candidates[0].payload_json["structure"]
    assert structure["columns"][0]["label_raw"] == "Value"
    assert structure["rows"][0]["raw_text"] == ""
    assert candidates[0].status == "candidate"


def test_profile_candidate_without_stat_block_keeps_description_and_unknown_labels() -> None:
    observations = (
        ReaderObservation(
            id="profile-observation",
            book_id="bestiary",
            page_id="bestiary:104",
            page_number=104,
            source_object_id="profile",
            reader_name="source_object_heuristic",
            reader_version="test",
            observation_type="profile_header",
            object_shape="profile_bundle",
            content_kind="creature_profile",
            entity_kind="monster",
            title="Common Orc",
            canonical_name="common orc",
            payload_json={
                "text": "Common Orc\nA brutal greenskin.\nUnknown: ignored\nSkills: Intimidate",
                "heading_path": "not a list",
            },
            text_snapshot_sha256="snapshot",
            confidence=0.64,
        ),
    )

    candidates = build_candidates_from_observations(observations)

    assert len(candidates) == 1
    profile = candidates[0].payload_json["profile"]
    assert profile["description"] == "A brutal greenskin."
    assert profile["skills"] == ["Intimidate"]
    assert candidates[0].heading_path == ()
    assert candidates[0].source_object_ids == ("profile",)
    assert candidates[0].suspicious_flags == (
        "profile_missing_main_fields",
        "profile_missing_secondary_fields",
        "profile_followup_uncertain",
    )
