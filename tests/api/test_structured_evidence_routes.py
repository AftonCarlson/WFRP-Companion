from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tests.source_objects.test_store import make_config
from tests.structured_evidence.test_structured_evidence_store import build_candidate
from wfrp_companion.api.app import create_app
from wfrp_companion.api import errors
from wfrp_companion.db.connection import open_connection
from wfrp_companion.structured_evidence import store


def test_structured_review_summary_and_queue_are_metadata_only(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    build_candidate(config)
    client = TestClient(create_app(config))

    summary = client.get("/api/structured-evidence/review/summary")
    queue = client.get("/api/structured-evidence/candidates", params={"status": "candidate"})

    assert summary.status_code == 200
    assert summary.json()["candidates_total"] == 1
    assert summary.json()["validated_active"] == 0
    assert queue.status_code == 200
    candidate = queue.json()["candidates"][0]
    assert candidate["book_title"] == "Rules Primer"
    assert candidate["table_number_normalized"] == "5-6"
    assert "payload_json" not in candidate
    assert "managed_pdf_path" not in str(candidate)


def test_structured_candidate_detail_stays_local_and_approves_candidate(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    candidate_id = build_candidate(config)
    client = TestClient(create_app(config))

    detail = client.get(f"/api/structured-evidence/candidates/{candidate_id}")
    approve = client.post(
        f"/api/structured-evidence/candidates/{candidate_id}/approve",
        json={"reviewer": "gm", "notes": "approved"},
    )

    assert detail.status_code == 200
    assert detail.json()["payload_json"]["identity"]["title_normalized"] == (
        "table 5 6 advanced armour"
    )
    assert detail.json()["observations"][0]["reader_name"] == "source_object_heuristic"
    assert "managed_pdf_path" not in detail.text
    assert approve.status_code == 200
    assert approve.json()["action"] == "approve"
    with open_connection(config.db_path) as connection:
        assert connection.execute(
            "select count(*) from validated_structured_objects"
        ).fetchone()[0] == 1


def test_structured_candidate_correct_and_reject_routes_map_errors(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    candidate_id = build_candidate(config)
    client = TestClient(create_app(config))
    detail = store.get_structured_candidate_detail(config, candidate_id)
    payload = detail.payload_json
    payload["identity"]["aliases"] = ["table 5-6", "armour points by location"]

    invalid = client.post(
        f"/api/structured-evidence/candidates/{candidate_id}/correct",
        json={"payload_json": {"schema_version": 1}},
    )
    corrected = client.post(
        f"/api/structured-evidence/candidates/{candidate_id}/correct",
        json={"payload_json": payload, "reviewer": "gm"},
    )
    conflict = client.post(
        f"/api/structured-evidence/candidates/{candidate_id}/reject",
        json={},
    )
    missing = client.get("/api/structured-evidence/candidates/missing")

    assert invalid.status_code == 422
    assert corrected.status_code == 200
    assert corrected.json()["action"] == "correct"
    assert conflict.status_code == 409
    assert missing.status_code == 404


def test_structured_candidate_reject_route_succeeds(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    candidate_id = build_candidate(config)
    client = TestClient(create_app(config))

    rejected = client.post(
        f"/api/structured-evidence/candidates/{candidate_id}/reject",
        json={"reviewer": "gm", "notes": "not a real table"},
    )

    assert rejected.status_code == 200
    assert rejected.json()["action"] == "reject"


def test_structured_candidate_stale_route_returns_conflict(tmp_path: Path) -> None:
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
    client = TestClient(create_app(config))

    response = client.post(
        f"/api/structured-evidence/candidates/{candidate_id}/approve",
        json={},
    )

    assert response.status_code == 409
    assert "stale" in response.json()["detail"].lower()


def test_generic_structured_error_maps_to_internal_server_error() -> None:
    response = errors.structured_evidence_error(
        store.StructuredEvidenceError("unexpected"),
    )

    assert response.status_code == 500
    assert response.detail == "Unexpected structured evidence error"
