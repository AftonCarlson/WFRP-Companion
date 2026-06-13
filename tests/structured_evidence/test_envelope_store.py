from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests.source_objects.test_store import insert_indexed_book, make_config
from tests.tools.test_extract_structured_evidence import insert_table_source_objects
from wfrp_companion.db.connection import open_connection
from wfrp_companion.db.migrations import apply_pending_migrations
from wfrp_companion.structured_evidence import store
from wfrp_companion.structured_evidence.models import (
    StructuredEnvelope,
    StructuredReviewAction,
    StructuredVisualRegion,
)


def prepare_envelope_store(tmp_path: Path):
    config = make_config(tmp_path)
    insert_indexed_book(config)
    insert_table_source_objects(config)
    apply_pending_migrations(config.db_path)
    return config


def make_region(config) -> StructuredVisualRegion:  # noqa: ANN001
    return StructuredVisualRegion(
        id="region:test",
        book_id="rules",
        source_snapshot_sha256="snapshot",
        ingest_job_id=None,
        provider_name="page_image_detector",
        provider_version="test",
        pdf_page_start=1,
        pdf_page_end=1,
        printed_page_start=None,
        printed_page_end=None,
        region_kind="table",
        bbox_json={"x0": 1, "y0": 2, "x1": 101, "y1": 202},
        crop_asset_path=str(config.data_dir / "crops" / "region.png"),
        raw_text="Synthetic table",
        confidence=0.9,
        issues=(),
    )


def make_envelope(region_id: str) -> StructuredEnvelope:
    return StructuredEnvelope(
        id="envelope:test",
        book_id="rules",
        source_snapshot_sha256="snapshot",
        envelope_kind="structured_table",
        scope_kind="section",
        scope_value="Synthetic Section",
        identity_raw="Synthetic Table",
        identity_normalized="synthetic table",
        parent_envelope_id=None,
        pdf_page_start=1,
        pdf_page_end=1,
        printed_page_start=None,
        printed_page_end=None,
        confidence=0.88,
        status="candidate",
        issues=(),
        region_links=((region_id, "primary", 0),),
        source_object_links=(("table", "primary", 0), ("row", "table_row", 1)),
    )


def test_create_envelope_links_regions_and_source_objects(tmp_path: Path) -> None:
    config = prepare_envelope_store(tmp_path)
    region = make_region(config)

    with open_connection(config.db_path) as connection:
        region_id = store.upsert_structured_visual_region(
            connection,
            region,
            now="2026-06-12T00:00:00Z",
        )
        envelope_id = store.upsert_structured_envelope(
            connection,
            make_envelope(region_id),
            now="2026-06-12T00:00:00Z",
        )
        envelope = connection.execute(
            "select * from structured_envelopes where id = ?",
            (envelope_id,),
        ).fetchone()
        region_links = connection.execute(
            """
            select visual_region_id, role, ordinal
            from structured_envelope_regions
            order by ordinal
            """
        ).fetchall()
        source_links = connection.execute(
            """
            select source_object_id, role, ordinal
            from structured_envelope_source_objects
            order by ordinal
            """
        ).fetchall()

    assert envelope is not None
    assert envelope["envelope_kind"] == "structured_table"
    assert envelope["scope_kind"] == "section"
    assert envelope["scope_value"] == "Synthetic Section"
    assert envelope["status"] == "candidate"
    assert [(row["visual_region_id"], row["role"], row["ordinal"]) for row in region_links] == [
        (region_id, "primary", 0)
    ]
    assert [(row["source_object_id"], row["role"], row["ordinal"]) for row in source_links] == [
        ("table", "primary", 0),
        ("row", "table_row", 1),
    ]


def test_candidate_status_guard_allows_blocked_and_rejects_reviewed_states(
    tmp_path: Path,
) -> None:
    config = prepare_envelope_store(tmp_path)

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
            values (
              'candidate:blocked',
              'rules',
              'rules:1',
              'profile_card',
              'npc_profile',
              'npc',
              1,
              1,
              '{}',
              'Synthetic profile',
              0.7,
              'blocked',
              'snapshot',
              'test',
              '2026-06-12T00:00:00Z',
              '2026-06-12T00:00:00Z'
            )
            """
        )
        assert store.transition_candidate_review_status(
            connection,
            candidate_id="candidate:blocked",
            new_status="needs_review",
            now="2026-06-12T00:01:00Z",
        )
        connection.execute(
            """
            update structured_evidence_candidates
            set status = 'approved'
            where id = 'candidate:blocked'
            """
        )
        assert not store.transition_candidate_review_status(
            connection,
            candidate_id="candidate:blocked",
            new_status="needs_review",
            now="2026-06-12T00:02:00Z",
        )
        with pytest.raises(ValueError, match="Unsupported candidate status"):
            store.transition_candidate_review_status(
                connection,
                candidate_id="candidate:blocked",
                new_status="not_a_status",
                now="2026-06-12T00:03:00Z",
            )


def test_candidate_transition_helper_rejects_promotional_statuses(
    tmp_path: Path,
) -> None:
    config = prepare_envelope_store(tmp_path)

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
            values (
              'candidate:transition',
              'rules',
              'rules:1',
              'profile_card',
              'npc_profile',
              'npc',
              1,
              1,
              '{}',
              'Synthetic profile',
              0.7,
              'candidate',
              'snapshot',
              'test',
              '2026-06-12T00:00:00Z',
              '2026-06-12T00:00:00Z'
            )
            """
        )
        for status in ("approved", "corrected"):
            with pytest.raises(ValueError, match="Promotional candidate status"):
                store.transition_candidate_review_status(
                    connection,
                    candidate_id="candidate:transition",
                    new_status=status,
                    now="2026-06-12T00:01:00Z",
                )
        candidate = connection.execute(
            """
            select status
            from structured_evidence_candidates
            where id = 'candidate:transition'
            """
        ).fetchone()

    assert candidate["status"] == "candidate"


@pytest.mark.parametrize(
    ("field_name", "field_value", "message"),
    (
        ("envelope_kind", "not_an_envelope", "Unsupported envelope kind"),
        ("scope_kind", "not_a_scope", "Unsupported envelope scope kind"),
        ("status", "not_a_status", "Unsupported envelope status"),
    ),
)
def test_envelope_store_rejects_unknown_enums(
    tmp_path: Path,
    field_name: str,
    field_value: str,
    message: str,
) -> None:
    config = prepare_envelope_store(tmp_path)
    region = make_region(config)

    with open_connection(config.db_path) as connection:
        region_id = store.upsert_structured_visual_region(
            connection,
            region,
            now="2026-06-12T00:00:00Z",
        )
        envelope = make_envelope(region_id)
        invalid_envelope = StructuredEnvelope(
            **{
                **envelope.__dict__,
                field_name: field_value,
            }
        )
        with pytest.raises(ValueError, match=message):
            store.upsert_structured_envelope(
                connection,
                invalid_envelope,
                now="2026-06-12T00:01:00Z",
            )


def test_envelope_store_rejects_unknown_link_roles(tmp_path: Path) -> None:
    config = prepare_envelope_store(tmp_path)
    region = make_region(config)

    with open_connection(config.db_path) as connection:
        region_id = store.upsert_structured_visual_region(
            connection,
            region,
            now="2026-06-12T00:00:00Z",
        )
        connection.commit()
        with pytest.raises(ValueError, match="Unsupported envelope region role"):
            store.upsert_structured_envelope(
                connection,
                StructuredEnvelope(
                    **{
                        **make_envelope(region_id).__dict__,
                        "id": "envelope:bad-region-role",
                        "region_links": ((region_id, "not_a_role", 0),),
                    }
                ),
                now="2026-06-12T00:01:00Z",
            )
        with pytest.raises(ValueError, match="Unsupported envelope source-object role"):
            store.upsert_structured_envelope(
                connection,
                StructuredEnvelope(
                    **{
                        **make_envelope(region_id).__dict__,
                        "id": "envelope:bad-source-role",
                        "source_object_links": (("table", "not_a_role", 0),),
                    }
                ),
                now="2026-06-12T00:02:00Z",
            )


def test_review_actions_are_append_only(tmp_path: Path) -> None:
    config = prepare_envelope_store(tmp_path)
    action = StructuredReviewAction(
        id="review-action:test",
        candidate_id=None,
        envelope_id="envelope:test",
        validated_object_id=None,
        action_kind="mark_suspicious",
        action_payload_json={"issues": ["synthetic_issue"]},
        reviewer="local_user",
    )

    with open_connection(config.db_path) as connection:
        region_id = store.upsert_structured_visual_region(
            connection,
            make_region(config),
            now="2026-06-12T00:00:00Z",
        )
        envelope_id = store.upsert_structured_envelope(
            connection,
            make_envelope(region_id),
            now="2026-06-12T00:00:00Z",
        )
        assert envelope_id == "envelope:test"
        action_id = store.insert_structured_review_action(
            connection,
            action,
            now="2026-06-12T00:01:00Z",
        )
        row = connection.execute(
            "select * from structured_review_actions where id = ?",
            (action_id,),
        ).fetchone()
        assert row is not None
        assert json.loads(row["action_payload_json"]) == {
            "issues": ["synthetic_issue"]
        }
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                update structured_review_actions
                set reviewer = 'someone_else'
                where id = ?
                """,
                (action_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "delete from structured_review_actions where id = ?",
                (action_id,),
            )


def test_review_action_store_rejects_unknown_action_kind(tmp_path: Path) -> None:
    config = prepare_envelope_store(tmp_path)

    with open_connection(config.db_path) as connection:
        with pytest.raises(ValueError, match="Unsupported review action kind"):
            store.insert_structured_review_action(
                connection,
                StructuredReviewAction(
                    id="review-action:bad",
                    candidate_id=None,
                    envelope_id=None,
                    validated_object_id=None,
                    action_kind="not_an_action",
                    action_payload_json={},
                    reviewer="local_user",
                ),
                now="2026-06-12T00:00:00Z",
            )
