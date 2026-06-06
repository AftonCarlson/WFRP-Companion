from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests.db.test_migrations import create_legacy_phase6_database
from tests.source_objects.test_store import fetch_one, insert_indexed_book, make_config
from wfrp_companion.db.connection import initialize_database, open_connection
from wfrp_companion.source_objects import source_map_builder
from wfrp_companion.source_objects.extractor import extract_source_object_library
from wfrp_companion.source_objects.source_map_builder import (
    build_book_source_map,
    eligible_books,
    infer_best_source_for,
    rebuild_source_maps,
    source_map_claim_failure,
    source_map_job_id,
    source_map_aliases,
    source_map_chapters,
    source_object_snapshot_sha256,
)


def test_rebuild_source_maps_persists_book_profile_status_and_job(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)

    summary = rebuild_source_maps(config)

    assert summary.discovered == 1
    assert summary.indexed == 1
    assert summary.skipped_current == 0
    assert summary.failed == 0
    assert summary.failures == ()
    status = fetch_one(config, "select * from book_retrieval_status")
    source_map = fetch_one(config, "select * from book_source_maps")
    job = fetch_one(config, "select * from ingest_jobs where job_type = 'rebuild_source_maps'")
    profile = fetch_one(config, "select * from book_query_profiles")
    aliases = json.loads(source_map["aliases_json"])
    chapters = json.loads(source_map["chapters_json"])

    assert status["source_map_status"] == "indexed"
    assert status["source_object_snapshot_sha256"] == summary.book_summaries[0].snapshot
    assert status["source_map_snapshot_sha256"] == summary.book_summaries[0].snapshot
    assert status["last_error"] is None
    assert source_map["book_id"] == "rules"
    assert source_map["summary"] == "Rules Primer is in Core."
    assert "rules" in aliases
    assert "Critical Hits" in chapters
    assert source_map["schema_version"] == 1
    assert source_map["builder_version"] == "source-map-builder-v1"
    assert job["status"] == "succeeded"
    assert job["idempotency_key"] == source_map_job_id(
        "rules",
        summary.book_summaries[0].snapshot,
    )
    assert profile["query_type"] == "rules_lookup"
    assert json.loads(profile["evidence_json"])["source_map_snapshot"] == summary.book_summaries[0].snapshot

    second = rebuild_source_maps(config)

    assert second.indexed == 0
    assert second.skipped_current == 1


def test_rebuild_source_maps_can_force_rebuild_current_profile(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    rebuild_source_maps(config)

    forced = rebuild_source_maps(config, force=True)

    assert forced.indexed == 1
    assert forced.skipped_current == 0


def test_rebuild_source_maps_supports_book_filters(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config, book_id="rules")
    insert_indexed_book(config, book_id="lore")
    extract_source_object_library(config)

    summary = rebuild_source_maps(config, book_ids=("lore",))

    assert summary.discovered == 1
    assert summary.indexed == 1
    with open_connection(config.db_path) as connection:
        assert eligible_books(connection, book_ids=()) == ()
        assert connection.execute(
            """
            select count(*)
            from book_source_maps
            where book_id = 'lore'
            """
        ).fetchone()[0] == 1
        assert connection.execute(
            """
            select count(*)
            from book_source_maps
            where book_id = 'rules'
            """
        ).fetchone()[0] == 0


def test_rebuild_source_maps_skips_running_book_without_claiming_job(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update book_retrieval_status
            set source_map_status = 'indexing',
                updated_at = '2999-01-01T00:00:00Z'
            where book_id = 'rules'
            """
        )

    summary = rebuild_source_maps(config)

    assert summary.discovered == 1
    assert summary.indexed == 0
    assert summary.skipped_current == 1
    with open_connection(config.db_path) as connection:
        job_count = connection.execute(
            """
            select count(*)
            from ingest_jobs
            where job_type = 'rebuild_source_maps'
            """
        ).fetchone()[0]
    assert job_count == 0


def test_source_map_claim_failure_returns_none_for_missing_status(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        assert source_map_claim_failure(connection, "missing-book") is None


def test_rebuild_source_maps_marks_failed_when_job_conflict_cannot_be_claimed(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        snapshot = source_object_snapshot_sha256(connection, "rules")
        job_id = source_map_job_id("rules", snapshot)
        connection.execute(
            """
            update book_retrieval_status
            set source_map_status = 'needs_refresh',
                updated_at = '2999-01-01T00:00:00Z'
            where book_id = 'rules'
            """
        )
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
            values (?, 'rebuild_source_maps', 'rules', 'running', ?, 1,
                    '2999-01-01T00:00:00Z', '2999-01-01T00:00:00Z')
            """,
            (job_id, job_id),
        )

    summary = rebuild_source_maps(config)

    assert summary.discovered == 1
    assert summary.indexed == 0
    assert summary.skipped_current == 0
    assert summary.failed == 1
    assert summary.failures[0].book_id == "rules"
    assert summary.failures[0].reason == "Could not claim source-map rebuild job."
    status = fetch_one(config, "select * from book_retrieval_status")
    assert status["source_map_status"] == "failed"
    assert status["last_error"] == "Could not claim source-map rebuild job."


def test_rebuild_source_maps_recovers_running_jobs_when_retry_requested(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update book_retrieval_status
            set source_map_status = 'indexing',
                updated_at = '2026-06-05T00:00:00Z'
            where book_id = 'rules'
            """
        )
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
            values ('stale-source-map', 'rebuild_source_maps', 'rules', 'running',
                    'rebuild_source_maps:rules:stale', 1,
                    '2026-06-05T00:00:00Z', '2026-06-05T00:00:00Z')
            """
        )

    summary = rebuild_source_maps(config, retry_running=True)

    assert summary.stale_recovered == 1
    assert summary.indexed == 1
    with open_connection(config.db_path) as connection:
        stale_job = connection.execute(
            """
            select status, last_error
            from ingest_jobs
            where id = 'stale-source-map'
            """
        ).fetchone()
    assert stale_job["status"] == "failed"
    assert stale_job["last_error"] == "Recovered stale running source-map rebuild job."


def test_rebuild_source_maps_records_failed_build(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)

    def fail_build(connection, book_id, source_object_snapshot):  # noqa: ANN001
        raise RuntimeError(f"failed source map for {book_id}")

    monkeypatch.setattr(source_map_builder, "build_book_source_map", fail_build)

    summary = rebuild_source_maps(config)

    assert summary.failed == 1
    assert summary.failures[0].book_id == "rules"
    status = fetch_one(config, "select * from book_retrieval_status")
    job = fetch_one(config, "select * from ingest_jobs where job_type = 'rebuild_source_maps'")
    assert status["source_map_status"] == "failed"
    assert status["last_error"] == "failed source map for rules"
    assert job["status"] == "failed"
    assert job["last_error"] == "failed source map for rules"


def test_rebuild_source_maps_initializes_and_migrates_database(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)

    summary = rebuild_source_maps(config)

    assert summary.discovered == 0
    assert config.db_path.exists()


def test_rebuild_source_maps_migrates_legacy_database(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    create_legacy_phase6_database(config.db_path)

    summary = rebuild_source_maps(config)

    assert summary.discovered == 0
    with sqlite3.connect(config.db_path) as connection:
        applied = connection.execute(
            """
            select id
            from schema_migrations
            where id = '0002_source_map_retrieval'
            """
        ).fetchone()
    assert applied is not None


def test_source_map_helpers_limit_terms_and_infer_query_types(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        for index in range(25):
            connection.execute(
                """
                insert into source_objects (
                  id,
                  book_id,
                  page_id,
                  object_type,
                  title,
                  heading_path_json,
                  page_start,
                  page_end,
                  text,
                  search_text,
                  confidence,
                  extraction_method,
                  text_snapshot_sha256,
                  created_at,
                  updated_at
                )
                values (?, 'rules', 'rules:1', 'rule_section', ?, '[]', 1, 1,
                        'Synthetic section', 'Synthetic section', 0.8, 'test',
                        ?, '2026-06-05T00:00:00Z', '2026-06-05T00:00:00Z')
                """,
                (
                    f"rules:synthetic:{index}",
                    f"Synthetic Chapter {index}",
                    f"synthetic-sha-{index}",
                ),
            )
        chapters = source_map_chapters(connection, "rules")

    aliases = source_map_aliases(
        title="Rules Primer",
        category="Core Rules",
        chapters=tuple(f"Unique Topic {index}" for index in range(40)),
    )
    best_sources = infer_best_source_for(
        "World Adventure Faction Core Rules",
        ("rules",),
    )

    assert len(chapters) == 20
    assert len(aliases) == 24
    assert best_sources == (
        "adventure_scene_lookup",
        "lore_lookup",
        "rules_lookup",
        "source_navigation",
    )


def test_build_book_source_map_rejects_missing_book(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)

    with open_connection(config.db_path) as connection:
        with pytest.raises(ValueError, match="Book not found: missing"):
            build_book_source_map(connection, "missing", "snapshot")


def test_source_object_snapshot_changes_with_source_object_content(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)

    with open_connection(config.db_path) as connection:
        before = source_object_snapshot_sha256(connection, "rules")
        connection.execute(
            """
            update source_objects
            set text_snapshot_sha256 = 'changed'
            where id = (
                select id
                from source_objects
                where book_id = 'rules'
                order by id
                limit 1
            )
            """
        )
        after = source_object_snapshot_sha256(connection, "rules")

    assert before != after


def test_source_object_snapshot_changes_with_source_map_metadata_inputs(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    extract_source_object_library(config)

    with open_connection(config.db_path) as connection:
        before = source_object_snapshot_sha256(connection, "rules")
        connection.execute(
            """
            update books
            set title = 'Updated Rules Primer'
            where id = 'rules'
            """
        )
        after_title = source_object_snapshot_sha256(connection, "rules")
        connection.execute(
            """
            update source_objects
            set title = 'Updated Critical Hits',
                heading_path_json = '["Updated Combat"]'
            where id = (
                select id
                from source_objects
                where book_id = 'rules'
                order by id
                limit 1
            )
            """
        )
        after_heading = source_object_snapshot_sha256(connection, "rules")

    assert before != after_title
    assert after_title != after_heading
