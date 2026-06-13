from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests.source_objects.test_store import insert_indexed_book, make_config
from tests.tools.test_extract_structured_evidence import insert_table_source_objects
from wfrp_companion.db.connection import open_connection
from wfrp_companion.structured_evidence import candidates as candidate_builder
from wfrp_companion.structured_evidence import store
from wfrp_companion.structured_evidence.payloads import payload_hash
from wfrp_companion.structured_evidence.readers import ReaderObservation
from wfrp_companion.source_objects.layout import LayoutPage
from wfrp_companion.structured_evidence.store import (
    StructuredEvidenceConflictError,
    StructuredEvidenceInvalidPayloadError,
    StructuredEvidenceNotFoundError,
    StructuredEvidenceStaleError,
)


def build_candidate(config) -> str:  # noqa: ANN001
    insert_indexed_book(config)
    insert_table_source_objects(config)
    summary = store.extract_structured_evidence_library(config)
    assert summary.extracted == 1
    with open_connection(config.db_path) as connection:
        row = connection.execute(
            "select id from structured_evidence_candidates"
        ).fetchone()
    assert row is not None
    return row["id"]


def fetch_one(config, sql: str, parameters: tuple[object, ...] = ()):  # noqa: ANN001
    with open_connection(config.db_path) as connection:
        row = connection.execute(sql, parameters).fetchone()
    assert row is not None
    return row


def valid_profile_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "object_shape": "profile_bundle",
        "content_kind": "creature_profile",
        "entity_kind": "monster",
        "identity": {
            "name_raw": "Common Orc",
            "name_normalized": "common orc",
            "aliases": ["Orc", "Common Orc"],
        },
        "source": {
            "book_id": "rules",
            "chapter_path": ["Bestiary"],
            "printed_page_start": None,
            "printed_page_end": None,
            "pdf_page_start": 1,
            "pdf_page_end": 1,
            "source_object_ids": [],
            "text_snapshot_sha256": "snapshot",
        },
        "profile": {
            "description": "A brutal greenskin.",
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
            "skills": ["Intimidate"],
            "talents": ["Menacing"],
            "traits": ["Animosity"],
            "special_rules": ["Synthetic Rule"],
            "weapons": ["Choppa"],
            "armour": ["Leather"],
            "trappings": ["Teeth"],
            "notes": ["Cave-dweller"],
        },
        "provenance": {
            "reader_names": ["test"],
            "field_confidence": {"ws": 0.9, "ignored": "high"},
            "suspicious_fields": [],
        },
    }


def valid_career_entry_payload() -> dict[str, object]:
    return {
        "schema_version": 2,
        "object_shape": "career_entry",
        "identity": {"name_raw": "Synthetic Career"},
        "source": {
            "book_id": "rules",
            "text_snapshot_sha256": "snapshot",
        },
        "career": {
            "description": "Synthetic career description.",
            "advance_scheme": {
                "main_profile": {"ws": "+5%"},
                "secondary_profile": {"w": "+2"},
            },
            "skills": ["Synthetic Skill"],
            "talents": [],
            "trappings": [],
            "career_entries": [],
            "career_exits": [],
            "notes": [],
        },
        "provenance": {"field_confidence": {}},
    }


def valid_v2_table_payload() -> dict[str, object]:
    return {
        "schema_version": 2,
        "object_shape": "structured_table",
        "table_kind": "lookup",
        "identity": {"title_raw": "Synthetic Table"},
        "source": {
            "book_id": "rules",
            "text_snapshot_sha256": "snapshot",
        },
        "scope": {"scope_kind": "section", "scope_value": "Synthetic"},
        "structure": {
            "columns": [{"key": "result", "label_raw": "Result"}],
            "rows": [
                {
                    "ordinal": 1,
                    "cells": {"result": "Synthetic result"},
                }
            ],
        },
    }


def insert_review_candidate(
    config,  # noqa: ANN001
    *,
    candidate_id: str,
    object_shape: str,
    status: str,
    payload: dict[str, object],
) -> None:
    insert_indexed_book(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            insert into structured_evidence_candidates (
              id,
              book_id,
              primary_page_id,
              object_shape,
              content_kind,
              entity_kind,
              canonical_name,
              title,
              page_start,
              page_end,
              payload_json,
              search_text,
              confidence,
              status,
              text_snapshot_sha256,
              structured_extractor_version,
              created_at,
              updated_at
            )
            values (?, 'rules', 'rules:1', ?, 'career_table', 'career',
                    'synthetic career', 'Synthetic Career', 1, 1, ?,
                    'Synthetic Career', 0.8, ?, 'snapshot', 'test',
                    '2026-06-12T00:00:00Z', '2026-06-12T00:00:00Z')
            """,
            (
                candidate_id,
                object_shape,
                json.dumps(payload),
                status,
            ),
        )
        connection.execute(
            """
            insert into book_retrieval_status (
              book_id,
              structured_evidence_status,
              structured_evidence_snapshot_sha256,
              updated_at
            )
            values ('rules', 'needs_review', ?, '2026-06-12T00:00:00Z')
            on conflict(book_id) do update set
              structured_evidence_status = excluded.structured_evidence_status,
              structured_evidence_snapshot_sha256 =
                excluded.structured_evidence_snapshot_sha256,
              updated_at = excluded.updated_at
            """,
            (store.structured_evidence_snapshot_sha256(connection, "rules"),),
        )


def test_review_queue_lists_metadata_without_private_payload(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    build_candidate(config)

    summary = store.structured_review_summary(config)
    candidates = store.list_structured_candidates(config, status="candidate")

    assert summary.candidates_total == 1
    assert summary.validated_active == 0
    assert len(candidates) == 1
    assert candidates[0].book_title == "Rules Primer"
    assert candidates[0].table_number_normalized == "5-6"
    assert candidates[0].payload_json is None
    assert candidates[0].suspicious_flags == ()


def test_review_summary_counts_blocked_candidates_separately(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    build_candidate(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update structured_evidence_candidates
            set status = 'blocked',
                status_reason = 'missing_visual_region'
            """
        )

    summary = store.structured_review_summary(config)

    assert summary.candidates_total == 1
    assert summary.candidates_needs_review == 0
    assert summary.candidates_blocked == 1


def test_candidate_detail_exposes_local_review_data_without_paths(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    candidate_id = build_candidate(config)

    detail = store.get_structured_candidate_detail(config, candidate_id)

    assert detail.id == candidate_id
    assert detail.book_title == "Rules Primer"
    assert detail.payload_json["identity"]["title_normalized"] == (
        "table 5 6 advanced armour"
    )
    assert detail.observations[0].reader_name == "source_object_heuristic"
    serialized = json.dumps(detail.__dict__, default=str)
    assert "managed_pdf_path" not in serialized
    assert "/managed/" not in serialized
    assert "export" not in serialized
    assert "telemetry" not in serialized


def test_structured_extraction_persists_pymupdf_layout_observations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    insert_table_source_objects(config)

    monkeypatch.setattr(
        store,
        "load_pdf_layout_pages",
        lambda *_args, **_kwargs: (
            LayoutPage(
                page_number=1,
                has_word_geometry=True,
                word_count=12,
                block_count=3,
            ),
        ),
    )

    summary = store.extract_structured_evidence_library(config)

    assert summary.extracted == 1
    with open_connection(config.db_path) as connection:
        layout_observation = connection.execute(
            """
            select reader_name, observation_type, payload_json
            from structured_reader_observations
            where reader_name = 'pymupdf_words'
            """
        ).fetchone()
    assert layout_observation is not None
    assert layout_observation["observation_type"] == "layout_metadata"
    assert json.loads(layout_observation["payload_json"]) == {
        "block_count": 3,
        "has_word_geometry": True,
        "word_count": 12,
    }
    with open_connection(config.db_path) as connection:
        assert store.load_managed_pdf_layout_pages(connection, "missing") == ()


def test_approve_candidate_writes_validated_object_sources_aliases_and_review(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    candidate_id = build_candidate(config)

    result = store.approve_structured_candidate(
        config,
        candidate_id,
        reviewer="gm",
        notes="looks correct",
    )

    assert result.candidate_id == candidate_id
    assert result.action == "approve"
    with open_connection(config.db_path) as connection:
        candidate = connection.execute(
            "select status from structured_evidence_candidates where id = ?",
            (candidate_id,),
        ).fetchone()
        validated = connection.execute(
            "select * from validated_structured_objects"
        ).fetchone()
        sources = connection.execute(
            "select source_role, source_object_id from validated_structured_object_sources"
        ).fetchall()
        aliases = connection.execute(
            "select alias_normalized from validated_structured_object_aliases"
        ).fetchall()
        review = connection.execute("select * from structured_evidence_reviews").fetchone()
        status = connection.execute(
            """
            select structured_evidence_last_review_at
            from book_retrieval_status
            where book_id = 'rules'
            """
        ).fetchone()

    assert candidate["status"] == "approved"
    assert validated["validation_status"] == "active"
    assert validated["review_state"] == "human_approved"
    assert validated["source_snapshot_sha256"] == result.source_snapshot_sha256
    assert [(row["source_role"], row["source_object_id"]) for row in sources] == [
        ("primary", "table"),
        ("table_row", "row"),
    ]
    assert "table 5 6" in {row["alias_normalized"] for row in aliases}
    assert "table 5 6 advanced armour" in {
        row["alias_normalized"] for row in aliases
    }
    assert review["action"] == "approve"
    assert review["prior_payload_hash"] == review["after_payload_hash"]
    assert status["structured_evidence_last_review_at"] is not None


def test_correct_candidate_validates_payload_and_records_hashes(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    candidate_id = build_candidate(config)
    detail = store.get_structured_candidate_detail(config, candidate_id)
    corrected_payload = dict(detail.payload_json)
    corrected_payload["identity"] = {
        **corrected_payload["identity"],
        "aliases": ["table 5-6", "armour points by location"],
    }

    with pytest.raises(StructuredEvidenceInvalidPayloadError):
        store.correct_structured_candidate(config, candidate_id, {"schema_version": 1})

    result = store.correct_structured_candidate(
        config,
        candidate_id,
        corrected_payload,
        reviewer="gm",
        notes="added alias",
    )

    with open_connection(config.db_path) as connection:
        review = connection.execute("select * from structured_evidence_reviews").fetchone()
        alias = connection.execute(
            """
            select 1
            from validated_structured_object_aliases
            where alias_normalized = 'armour points by location'
            """
        ).fetchone()
        candidate = connection.execute(
            "select status, payload_json from structured_evidence_candidates"
        ).fetchone()

    assert result.action == "correct"
    assert review["prior_payload_hash"] == payload_hash(detail.payload_json)
    assert review["after_payload_hash"] == payload_hash(corrected_payload)
    assert alias is not None
    assert candidate["status"] == "corrected"
    assert json.loads(candidate["payload_json"])["identity"]["aliases"] == [
        "table 5-6",
        "armour points by location",
    ]


def test_blocked_candidate_can_be_rejected_but_not_promoted(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_review_candidate(
        config,
        candidate_id="candidate:blocked",
        object_shape="career_entry",
        status="blocked",
        payload=valid_career_entry_payload(),
    )

    with pytest.raises(StructuredEvidenceConflictError):
        store.approve_structured_candidate(config, "candidate:blocked")
    with pytest.raises(StructuredEvidenceConflictError):
        store.correct_structured_candidate(
            config,
            "candidate:blocked",
            valid_career_entry_payload(),
        )

    result = store.reject_structured_candidate(config, "candidate:blocked")

    assert result.action == "reject"


def test_v2_candidate_payloads_are_contract_validated_before_promotion(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    valid_payload = valid_career_entry_payload()
    insert_review_candidate(
        config,
        candidate_id="candidate:career",
        object_shape="career_entry",
        status="candidate",
        payload=valid_payload,
    )

    approved = store.approve_structured_candidate(config, "candidate:career")

    assert approved.action == "approve"
    with open_connection(config.db_path) as connection:
        validated = connection.execute(
            """
            select object_shape, canonical_name
            from validated_structured_objects
            where id = ?
            """,
            (approved.validated_object_id,),
        ).fetchone()
    assert validated["object_shape"] == "career_entry"
    assert validated["canonical_name"] == "synthetic career"


def test_v2_approval_retires_conflicting_active_validated_identity(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_review_candidate(
        config,
        candidate_id="candidate:career-conflict",
        object_shape="career_entry",
        status="candidate",
        payload=valid_career_entry_payload(),
    )
    first = store.approve_structured_candidate(
        config,
        "candidate:career-conflict",
    )
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update structured_evidence_candidates
            set status = 'candidate'
            where id = 'candidate:career-conflict'
            """
        )

    second = store.approve_structured_candidate(
        config,
        "candidate:career-conflict",
        reviewer="gm",
    )

    with open_connection(config.db_path) as connection:
        first_row = connection.execute(
            """
            select validation_status
            from validated_structured_objects
            where id = ?
            """,
            (first.validated_object_id,),
        ).fetchone()
        second_row = connection.execute(
            """
            select validation_status
            from validated_structured_objects
            where id = ?
            """,
            (second.validated_object_id,),
        ).fetchone()
        active_count = connection.execute(
            """
            select count(*)
            from validated_structured_objects
            where object_shape = 'career_entry'
              and canonical_name = 'synthetic career'
              and validation_status = 'active'
            """
        ).fetchone()[0]

    assert first.validated_object_id != second.validated_object_id
    assert first_row["validation_status"] == "retired"
    assert second_row["validation_status"] == "active"
    assert active_count == 1


def test_invalid_v2_payload_fails_contract_validation_before_promotion(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    invalid_payload = {
        **valid_career_entry_payload(),
        "career": {"description": "No scheme."},
    }
    insert_review_candidate(
        config,
        candidate_id="candidate:invalid-career",
        object_shape="career_entry",
        status="candidate",
        payload=invalid_payload,
    )

    with pytest.raises(
        StructuredEvidenceInvalidPayloadError,
        match="career_missing_advance_scheme",
    ):
        store.approve_structured_candidate(config, "candidate:invalid-career")


def test_promotable_and_reviewable_helpers_reject_invalid_states(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_review_candidate(
        config,
        candidate_id="candidate:approved",
        object_shape="career_entry",
        status="approved",
        payload=valid_career_entry_payload(),
    )

    with open_connection(config.db_path) as connection:
        with pytest.raises(StructuredEvidenceNotFoundError):
            store.require_promotable_candidate(connection, "missing")
        with pytest.raises(StructuredEvidenceConflictError):
            store.require_reviewable_candidate(connection, "candidate:approved")

        connection.execute(
            """
            update structured_evidence_candidates
            set status = 'blocked'
            where id = 'candidate:approved'
            """
        )
        assert (
            store.require_reviewable_candidate(connection, "candidate:approved")["id"]
            == "candidate:approved"
        )


def test_valid_v2_structured_table_payload_uses_contract_registry(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_review_candidate(
        config,
        candidate_id="candidate:v2-table",
        object_shape="structured_table",
        status="candidate",
        payload=valid_v2_table_payload(),
    )

    result = store.approve_structured_candidate(config, "candidate:v2-table")

    assert result.action == "approve"


def test_invalid_v2_structured_table_payload_fails_contract_validation(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_review_candidate(
        config,
        candidate_id="candidate:invalid-table",
        object_shape="structured_table",
        status="candidate",
        payload={
            "schema_version": 2,
            "object_shape": "structured_table",
            "table_kind": "lookup",
            "identity": {"title_raw": "Synthetic Table"},
            "source": {
                "book_id": "rules",
                "text_snapshot_sha256": "snapshot",
            },
            "scope": {"scope_kind": "section", "scope_value": "Synthetic"},
            "structure": {"columns": [], "rows": [{"cells": {}}]},
        },
    )

    with pytest.raises(
        StructuredEvidenceInvalidPayloadError,
        match="missing_required_cells",
    ):
        store.approve_structured_candidate(config, "candidate:invalid-table")


def test_reject_candidate_marks_review_without_validating_object(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    candidate_id = build_candidate(config)

    result = store.reject_structured_candidate(
        config,
        candidate_id,
        reviewer="gm",
        notes="duplicate",
    )

    assert result.action == "reject"
    with open_connection(config.db_path) as connection:
        candidate = connection.execute(
            "select status from structured_evidence_candidates where id = ?",
            (candidate_id,),
        ).fetchone()
        validated_count = connection.execute(
            "select count(*) from validated_structured_objects"
        ).fetchone()[0]
        review = connection.execute("select action from structured_evidence_reviews").fetchone()
    assert candidate["status"] == "rejected"
    assert validated_count == 0
    assert review["action"] == "reject"


def test_approval_retires_conflicting_active_validated_identity(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    candidate_id = build_candidate(config)
    first = store.approve_structured_candidate(config, candidate_id)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update structured_evidence_candidates
            set status = 'candidate'
            where id = ?
            """,
            (candidate_id,),
        )
    second = store.approve_structured_candidate(config, candidate_id, reviewer="gm")

    with open_connection(config.db_path) as connection:
        first_row = connection.execute(
            """
            select validation_status
            from validated_structured_objects
            where id = ?
            """
            ,
            (first.validated_object_id,),
        ).fetchone()
        second_row = connection.execute(
            """
            select validation_status
            from validated_structured_objects
            where id = ?
            """,
            (second.validated_object_id,),
        ).fetchone()

    assert first.validated_object_id != second.validated_object_id
    assert first_row["validation_status"] == "retired"
    assert second_row["validation_status"] == "active"


def test_stale_snapshot_blocks_approval_until_rebuild(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    candidate_id = build_candidate(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update source_objects
            set search_text = 'changed table text'
            where id = 'table'
            """
        )

    with pytest.raises(StructuredEvidenceStaleError):
        store.approve_structured_candidate(config, candidate_id)


def test_rebuild_marks_active_validated_objects_stale_on_source_snapshot_drift(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    candidate_id = build_candidate(config)
    approved = store.approve_structured_candidate(config, candidate_id)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update source_objects
            set search_text = 'changed table text'
            where id = 'table'
            """
        )

    summary = store.extract_structured_evidence_library(config, force=True)

    assert summary.extracted == 1
    with open_connection(config.db_path) as connection:
        validated = connection.execute(
            """
            select validation_status
            from validated_structured_objects
            where id = ?
            """,
            (approved.validated_object_id,),
        ).fetchone()
    assert validated["validation_status"] == "stale"


def test_rebuild_preserves_reviewed_candidate_observation_snapshot(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    candidate_id = build_candidate(config)
    before_review = store.get_structured_candidate_detail(config, candidate_id)
    reviewed_observation_hashes = {
        observation.id: observation.text_hash
        for observation in before_review.observations
    }
    store.approve_structured_candidate(config, candidate_id)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update source_objects
            set text = 'Changed table text after review.',
                search_text = 'Changed table text after review.',
                text_snapshot_sha256 = 'changed-source-object-snapshot'
            where id = 'table'
            """
        )
        connection.execute(
            """
            update page_text
            set text_sha256 = 'changed-page-text-snapshot'
            where page_id = 'rules:1'
            """
        )

    summary = store.extract_structured_evidence_library(config, force=True)
    after_rebuild = store.get_structured_candidate_detail(config, candidate_id)

    assert summary.extracted == 1
    assert summary.failed == 0
    assert after_rebuild.status == "approved"
    assert {
        observation.id: observation.text_hash
        for observation in after_rebuild.observations
    } == reviewed_observation_hashes


def test_reviewed_candidate_observation_ids_filter_duplicates_and_invalid_values(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    candidate_id = build_candidate(config)
    store.approve_structured_candidate(config, candidate_id)

    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update structured_evidence_candidates
            set observation_ids_json = ?
            where id = ?
            """,
            (json.dumps(["observation-a", "", "observation-a", 42]), candidate_id),
        )
        observation_ids = store.reviewed_candidate_observation_ids(
            connection,
            book_id="rules",
        )

    assert observation_ids == ("observation-a",)


def test_force_rebuild_after_approval_preserves_validated_object_without_collision(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    candidate_id = build_candidate(config)
    approved = store.approve_structured_candidate(config, candidate_id)

    summary = store.extract_structured_evidence_library(config, force=True)

    assert summary.extracted == 1
    assert summary.failed == 0
    with open_connection(config.db_path) as connection:
        validated = connection.execute(
            """
            select validation_status
            from validated_structured_objects
            where id = ?
            """,
            (approved.validated_object_id,),
        ).fetchone()
        candidate_counts = {
            row["status"]: row["count"]
            for row in connection.execute(
                """
                select status, count(*) as count
                from structured_evidence_candidates
                group by status
                """
            ).fetchall()
        }
        review_count = connection.execute(
            "select count(*) from structured_evidence_reviews"
        ).fetchone()[0]

    assert validated["validation_status"] == "active"
    assert candidate_counts == {"approved": 1}
    assert review_count == 1


def test_force_rebuild_replaces_unreviewed_candidate_without_primary_key_collision(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    candidate_id = build_candidate(config)

    summary = store.extract_structured_evidence_library(config, force=True)

    assert summary.extracted == 1
    assert summary.failed == 0
    with open_connection(config.db_path) as connection:
        rows = connection.execute(
            """
            select id, status
            from structured_evidence_candidates
            """
        ).fetchall()

    assert [(row["id"], row["status"]) for row in rows] == [
        (candidate_id, "candidate")
    ]


def test_force_rebuild_after_correction_preserves_validated_object_without_collision(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    candidate_id = build_candidate(config)
    detail = store.get_structured_candidate_detail(config, candidate_id)
    corrected_payload = dict(detail.payload_json)
    corrected_payload["identity"] = {
        **corrected_payload["identity"],
        "aliases": ["table 5-6", "armour points by location"],
    }
    corrected = store.correct_structured_candidate(config, candidate_id, corrected_payload)

    summary = store.extract_structured_evidence_library(config, force=True)

    assert summary.extracted == 1
    assert summary.failed == 0
    with open_connection(config.db_path) as connection:
        validated = connection.execute(
            """
            select validation_status
            from validated_structured_objects
            where id = ?
            """,
            (corrected.validated_object_id,),
        ).fetchone()
        candidate_counts = {
            row["status"]: row["count"]
            for row in connection.execute(
                """
                select status, count(*) as count
                from structured_evidence_candidates
                group by status
                """
            ).fetchall()
        }

    assert validated["validation_status"] == "active"
    assert candidate_counts == {"corrected": 1}


def test_force_rebuild_after_rejection_preserves_review_without_collision(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    candidate_id = build_candidate(config)
    store.reject_structured_candidate(config, candidate_id)

    summary = store.extract_structured_evidence_library(config, force=True)

    assert summary.extracted == 1
    assert summary.failed == 0
    with open_connection(config.db_path) as connection:
        candidate_counts = {
            row["status"]: row["count"]
            for row in connection.execute(
                """
                select status, count(*) as count
                from structured_evidence_candidates
                group by status
                """
            ).fetchall()
        }
        validated_count = connection.execute(
            "select count(*) from validated_structured_objects"
        ).fetchone()[0]
        review_count = connection.execute(
            "select count(*) from structured_evidence_reviews"
        ).fetchone()[0]

    assert candidate_counts == {"rejected": 1}
    assert validated_count == 0
    assert review_count == 1


def test_review_store_raises_not_found_and_conflict(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    candidate_id = build_candidate(config)

    with pytest.raises(StructuredEvidenceNotFoundError):
        store.get_structured_candidate_detail(config, "missing")
    with pytest.raises(StructuredEvidenceNotFoundError):
        store.reject_structured_candidate(config, "missing")
    store.reject_structured_candidate(config, candidate_id)
    with pytest.raises(StructuredEvidenceConflictError):
        store.approve_structured_candidate(config, candidate_id)
    with open_connection(config.db_path) as connection:
        with pytest.raises(StructuredEvidenceNotFoundError):
            store.require_reviewable_candidate(connection, "missing")
        review_id = connection.execute(
            "select id from structured_evidence_reviews"
        ).fetchone()["id"]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                update structured_evidence_reviews
                set notes = 'changed'
                where id = ?
                """
                ,
                (review_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "delete from structured_evidence_reviews where id = ?",
                (review_id,),
            )


def test_structured_extraction_job_claim_and_recovery_edges(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    insert_table_source_objects(config)

    with open_connection(config.db_path) as connection:
        assert store.eligible_structured_books(connection, book_ids=()) == ()
        assert [
            book.book_id
            for book in store.eligible_structured_books(
                connection,
                book_ids=("rules",),
            )
        ] == ["rules"]
        snapshot = store.structured_evidence_snapshot_sha256(connection, "rules")
        assert not store.structured_evidence_current(
            connection,
            book_id="rules",
            snapshot_sha256="wrong-snapshot",
        )
        assert store.claim_structured_evidence_job(
            connection,
            book_id="rules",
            snapshot_sha256=snapshot,
            force=False,
            now="2026-06-10T00:00:00Z",
        )
        assert not store.claim_structured_evidence_job(
            connection,
            book_id="rules",
            snapshot_sha256=snapshot,
            force=False,
            now="2026-06-10T00:01:00Z",
        )
        connection.execute(
            """
            update book_retrieval_status
            set structured_evidence_status = 'disabled'
            where book_id = 'rules'
            """
        )
        assert not store.claim_structured_evidence_job(
            connection,
            book_id="rules",
            snapshot_sha256=snapshot,
            force=False,
            now="2026-06-10T00:02:00Z",
        )
        connection.execute(
            """
            update book_retrieval_status
            set structured_evidence_status = 'failed'
            where book_id = 'rules'
            """
        )
        assert not store.claim_structured_evidence_job(
            connection,
            book_id="rules",
            snapshot_sha256=snapshot,
            force=False,
            now="2026-06-10T00:03:00Z",
        )
        failed_status = connection.execute(
            """
            select structured_evidence_status, last_error
            from book_retrieval_status
            where book_id = 'rules'
            """
        ).fetchone()
        assert failed_status["structured_evidence_status"] == "failed"
        assert "Could not claim" in failed_status["last_error"]

        connection.execute(
            """
            insert into ingest_jobs (
              id,
              job_type,
              target_id,
              status,
              idempotency_key,
              attempts,
              created_at,
              updated_at
            )
            values (
              'stale-structured-job',
              'extract_structured_evidence',
              'rules',
              'running',
              'stale-key',
              1,
              '2026-06-10T00:00:00Z',
              '2026-06-10T00:00:00Z'
            )
            """
        )
        recovered = store.recover_stale_structured_evidence_jobs(
            connection,
            retry_running=True,
            stale_running_minutes=30,
        )
        recovered_status = connection.execute(
            """
            select status
            from ingest_jobs
            where id = 'stale-structured-job'
            """
        ).fetchone()

    assert recovered >= 1
    assert recovered_status["status"] == "failed"


def test_structured_extraction_summary_edges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty_config = make_config(tmp_path / "empty")
    assert store.extract_structured_evidence_library(empty_config).discovered == 0

    current_config = make_config(tmp_path / "current")
    candidate_id = build_candidate(current_config)
    current_summary = store.extract_structured_evidence_library(current_config)
    with open_connection(current_config.db_path) as connection:
        snapshot = store.structured_evidence_snapshot_sha256(connection, "rules")
        current = store.structured_evidence_current(
            connection,
            book_id="rules",
            snapshot_sha256=snapshot,
        )
    assert candidate_id
    assert current_summary.skipped_current == 1
    assert current

    needs_review_config = make_config(tmp_path / "needs-review")
    insert_indexed_book(needs_review_config)
    insert_table_source_objects(needs_review_config)

    def missing_reference_observations(
        connection: sqlite3.Connection,
        book_id: str,
    ) -> tuple[ReaderObservation, ...]:
        return (
            ReaderObservation(
                id="missing-reference",
                book_id=book_id,
                page_id=f"{book_id}:1",
                page_number=1,
                reader_name="page_text_import",
                reader_version="test",
                observation_type="page_reference",
                object_shape="structured_table",
                content_kind="unknown",
                entity_kind="unknown",
                title="Referenced table 9-9",
                table_number="9-9",
                payload_json={"reference_text": "Table 9-9"},
                text_snapshot_sha256="snapshot",
                confidence=0.55,
            ),
        )

    monkeypatch.setattr(
        store,
        "build_reader_observations",
        missing_reference_observations,
    )
    needs_review_summary = store.extract_structured_evidence_library(
        needs_review_config,
        force=True,
    )
    assert needs_review_summary.needs_review == 1

    skipped_config = make_config(tmp_path / "claim-false")
    insert_indexed_book(skipped_config)
    insert_table_source_objects(skipped_config)
    monkeypatch.setattr(
        store,
        "claim_structured_evidence_job",
        lambda *args, **kwargs: False,
    )
    skipped_summary = store.extract_structured_evidence_library(
        skipped_config,
        force=True,
    )
    assert skipped_summary.discovered == 1
    assert skipped_summary.extracted == 0
    assert skipped_summary.failed == 0

    failed_config = make_config(tmp_path / "failed")
    insert_indexed_book(failed_config)
    insert_table_source_objects(failed_config)

    def fail_reader_observations(
        connection: sqlite3.Connection,
        book_id: str,
    ) -> tuple[ReaderObservation, ...]:
        raise RuntimeError("synthetic extraction failure")

    monkeypatch.setattr(store, "build_reader_observations", fail_reader_observations)
    monkeypatch.undo()
    monkeypatch.setattr(store, "build_reader_observations", fail_reader_observations)
    failed_summary = store.extract_structured_evidence_library(failed_config, force=True)
    assert failed_summary.failed == 1
    assert "synthetic extraction failure" in failed_summary.failures[0].reason
    with open_connection(failed_config.db_path) as connection:
        status = connection.execute(
            """
            select structured_evidence_status, last_error
            from book_retrieval_status
            where book_id = 'rules'
            """
        ).fetchone()
        job = connection.execute(
            """
            select status, last_error
            from ingest_jobs
            where job_type = 'extract_structured_evidence'
            """
        ).fetchone()
    assert status["structured_evidence_status"] == "failed"
    assert "synthetic extraction failure" in status["last_error"]
    assert job["status"] == "failed"


def test_review_helpers_cover_profile_and_fallback_source_paths(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    candidate_id = build_candidate(config)
    approved = store.approve_structured_candidate(config, candidate_id)
    profile_payload = valid_profile_payload()
    profile_row = {
        "object_shape": "profile_bundle",
        "book_id": "rules",
        "entity_kind": "monster",
        "canonical_name": None,
        "title": None,
        "table_number": None,
        "table_number_normalized": None,
        "primary_page_id": "rules:1",
        "primary_source_object_id": None,
        "source_object_ids_json": "[]",
        "confidence": 0.5,
    }

    with open_connection(config.db_path) as connection:
        candidate_row = store.load_candidate_row(connection, candidate_id)
        assert candidate_row is not None
        connection.execute(
            """
            update structured_evidence_candidates
            set observation_ids_json = '[]'
            where id = ?
            """,
            (candidate_id,),
        )
        candidate_without_observations = store.load_candidate_row(connection, candidate_id)
        assert candidate_without_observations is not None
        assert (
            store.load_candidate_observation_details(
                connection,
                candidate_without_observations,
            )
            == ()
        )
        assert store.load_source_object_types(connection, ()) == {}
        assert store.validate_payload_for_shape(
            "profile_bundle",
            profile_payload,
        )["identity"]["name_normalized"] == "common orc"
        with pytest.raises(StructuredEvidenceInvalidPayloadError):
            store.validate_payload_for_shape("unknown_shape", {})
        profile_identity = store.structured_payload_identity(
            profile_row,  # type: ignore[arg-type]
            profile_payload,
        )
        assert profile_identity == {
            "title": "Common Orc",
            "canonical_name": "common orc",
            "table_number": None,
            "table_number_normalized": None,
        }
        profile_search_text = store.structured_payload_search_text(
            "profile_bundle",
            profile_payload,
        )
        assert "Common Orc" in profile_search_text
        assert "A brutal greenskin." in profile_search_text
        assert "Intimidate" in profile_search_text
        store.retire_conflicting_active_objects(
            connection,
            row=profile_row,  # type: ignore[arg-type]
            identity=profile_identity,
            now="2026-06-10T00:00:00Z",
        )
        store.insert_validated_sources(
            connection,
            row=profile_row,  # type: ignore[arg-type]
            validated_object_id=approved.validated_object_id,
            source_snapshot="snapshot",
            now="2026-06-10T00:00:00Z",
        )
        blank_alias_payload = {
            **profile_payload,
            "identity": {
                "name_raw": "",
                "name_normalized": "",
                "aliases": ["!!!"],
            },
        }
        store.insert_validated_aliases(
            connection,
            row=profile_row,  # type: ignore[arg-type]
            payload=blank_alias_payload,
            validated_object_id=approved.validated_object_id,
            identity={
                "title": None,
                "canonical_name": None,
                "table_number": None,
                "table_number_normalized": None,
            },
            now="2026-06-10T00:00:00Z",
        )
        fallback_source = connection.execute(
            """
            select source_role
            from validated_structured_object_sources
            where source_role = 'fallback_page'
            """
        ).fetchone()

    assert fallback_source["source_role"] == "fallback_page"
    assert store.aliases_for_payload(
        profile_row,  # type: ignore[arg-type]
        profile_payload,
        profile_identity,
    )[:2] == (
        ("common orc", "canonical", 1.0),
        ("Common Orc", "title", 0.95),
    )
    assert store.source_role_for(
        "profile_bundle",
        "stat_block",
        is_primary=False,
    ) == "stat_block"
    assert store.source_role_for(
        "profile_bundle",
        "npc_profile",
        is_primary=False,
    ) == "profile_text"
    assert store.source_role_for(
        "structured_table",
        "rule_section",
        is_primary=False,
    ) == "supporting_section"
    assert store.field_confidence_from_payload(
        "profile_bundle",
        profile_payload,
    ) == {"ws": 0.9}
    assert store._optional_text("   ") is None
    with pytest.raises(StructuredEvidenceInvalidPayloadError):
        store._payload_from_row({"payload_json": "[]"})  # type: ignore[arg-type]


def test_candidate_private_helpers_handle_non_string_table_text() -> None:
    assert candidate_builder._first_pipe_cells(None) == []
