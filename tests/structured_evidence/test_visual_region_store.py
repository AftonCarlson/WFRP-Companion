from __future__ import annotations

import json
from pathlib import Path

from tests.source_objects.test_store import insert_indexed_book, make_config
from wfrp_companion.db.connection import open_connection
from wfrp_companion.db.migrations import apply_pending_migrations
from wfrp_companion.structured_evidence import store
from wfrp_companion.structured_evidence.models import StructuredVisualRegion


def prepare_region_store(tmp_path: Path):
    config = make_config(tmp_path)
    insert_indexed_book(config)
    apply_pending_migrations(config.db_path)
    return config


def synthetic_region(config) -> StructuredVisualRegion:  # noqa: ANN001
    return StructuredVisualRegion(
        id="",
        book_id="rules",
        source_snapshot_sha256="snapshot",
        ingest_job_id=None,
        provider_name="pymupdf_words",
        provider_version="test",
        pdf_page_start=1,
        pdf_page_end=1,
        printed_page_start="12",
        printed_page_end="12",
        region_kind="table",
        bbox_json={"x0": 10, "y0": 20, "x1": 110, "y1": 220},
        crop_asset_path=str(
            config.data_dir
            / "structured_evidence"
            / "crops"
            / "rules"
            / "synthetic.png"
        ),
        raw_text="Synthetic table header\nSynthetic row",
        confidence=0.82,
        issues=("synthetic_issue",),
    )


def test_insert_visual_region_is_idempotent_and_stores_provider_metadata(
    tmp_path: Path,
) -> None:
    config = prepare_region_store(tmp_path)
    region = synthetic_region(config)

    with open_connection(config.db_path) as connection:
        first_id = store.upsert_structured_visual_region(
            connection,
            region,
            now="2026-06-12T00:00:00Z",
        )
        second_id = store.upsert_structured_visual_region(
            connection,
            region,
            now="2026-06-12T00:01:00Z",
        )
        rows = connection.execute("select * from structured_visual_regions").fetchall()

    assert first_id == second_id
    assert len(rows) == 1
    assert rows[0]["id"] == first_id
    assert rows[0]["provider_name"] == "pymupdf_words"
    assert rows[0]["provider_version"] == "test"
    assert rows[0]["region_kind"] == "table"
    assert json.loads(rows[0]["bbox_json"]) == {
        "x0": 10,
        "y0": 20,
        "x1": 110,
        "y1": 220,
    }
    assert json.loads(rows[0]["issues_json"]) == ["synthetic_issue"]
    assert rows[0]["crop_asset_path"].endswith("synthetic.png")
    assert rows[0]["created_at"] == "2026-06-12T00:00:00Z"


def test_visual_region_constraints_reject_unknown_kind(tmp_path: Path) -> None:
    config = prepare_region_store(tmp_path)
    region = synthetic_region(config)
    invalid = StructuredVisualRegion(
        **{
            **region.__dict__,
            "region_kind": "not_a_region",
        }
    )

    with open_connection(config.db_path) as connection:
        try:
            store.upsert_structured_visual_region(
                connection,
                invalid,
                now="2026-06-12T00:00:00Z",
            )
        except ValueError as exc:
            assert "Unsupported visual region kind" in str(exc)
        else:  # pragma: no cover - this is here to make the assertion explicit.
            raise AssertionError("unknown visual region kind was accepted")
