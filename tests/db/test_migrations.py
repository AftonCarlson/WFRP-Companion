from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from wfrp_companion.db.connection import initialize_database
from wfrp_companion.db.connection import open_connection
from wfrp_companion.db import migrations
from wfrp_companion.db.migrations import MigrationError, apply_migration, apply_pending_migrations


def create_legacy_phase6_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            pragma foreign_keys = on;

            create table library_folders (
              id text primary key,
              parent_id text references library_folders(id),
              name text not null,
              relative_path text not null unique,
              sort_order integer not null default 0
            );

            create table books (
              id text primary key,
              folder_id text not null references library_folders(id),
              title text not null,
              category text not null,
              relative_path text not null unique,
              original_source_path text not null,
              managed_pdf_path text not null,
              original_sha256 text not null,
              managed_sha256 text,
              page_count integer not null,
              copy_status text not null,
              text_status text not null,
              search_status text not null,
              visual_status text not null,
              enabled_default integer not null default 0,
              metadata_json text not null default '{}',
              discovered_at text not null,
              copied_at text,
              updated_at text not null,
              check(copy_status in ('discovered', 'copying', 'copied', 'managed_missing', 'failed')),
              check(copy_status != 'copied' or managed_sha256 is not null),
              check(text_status in ('not_imported', 'importing', 'imported', 'needs_refresh', 'failed')),
              check(search_status in ('not_indexed', 'indexing', 'indexed', 'needs_refresh', 'failed')),
              check(visual_status in ('not_scanned', 'scanning', 'scanned', 'needs_refresh', 'failed')),
              check(enabled_default in (0, 1))
            );

            create table pages (
              id text primary key,
              book_id text not null references books(id) on delete cascade,
              page_number integer not null,
              page_label text,
              extraction_method text not null,
              embedded_text_chars integer not null,
              text_chars integer not null,
              word_count integer not null,
              image_count integer not null,
              ocr_attempted integer not null,
              ocr_error text,
              has_text integer not null,
              metadata_json text not null default '{}',
              unique(book_id, page_number),
              unique(id, book_id, page_number)
            );

            create table source_sets (
              id text primary key,
              name text not null unique,
              description text,
              is_builtin integer not null default 0,
              created_at text not null,
              updated_at text not null,
              check(is_builtin in (0, 1))
            );

            create table ingest_jobs (
              id text primary key,
              job_type text not null,
              target_id text,
              status text not null,
              idempotency_key text not null unique,
              attempts integer not null default 0,
              last_error text,
              created_at text not null,
              updated_at text not null,
              completed_at text,
              check(job_type in ('copy_pdf', 'import_page_text', 'rebuild_fts', 'scan_visual_assets', 'render_page')),
              check(status in ('queued', 'running', 'succeeded', 'failed'))
            );

            create table chat_threads (
              id text primary key,
              title text,
              active_source_set_id text references source_sets(id),
              created_at text not null,
              updated_at text not null
            );

            create table chat_messages (
              id text primary key,
              thread_id text not null references chat_threads(id) on delete cascade,
              role text not null,
              content text not null,
              created_at text not null,
              metadata_json text not null default '{}',
              check(role in ('user', 'assistant', 'system', 'tool'))
            );

            create table retrieval_runs (
              id text primary key,
              thread_id text references chat_threads(id),
              message_id text references chat_messages(id),
              source_set_id text references source_sets(id),
              query text not null,
              created_at text not null,
              metadata_json text not null default '{}'
            );

            create table retrieval_hits (
              retrieval_run_id text not null references retrieval_runs(id) on delete cascade,
              page_id text not null references pages(id),
              score real not null,
              rank integer not null,
              snippet text,
              primary key(retrieval_run_id, page_id)
            );

            create table model_runs (
              id text primary key,
              thread_id text not null references chat_threads(id) on delete cascade,
              user_message_id text references chat_messages(id) on delete set null,
              assistant_message_id text references chat_messages(id) on delete set null,
              retrieval_run_id text references retrieval_runs(id) on delete set null,
              retry_of_model_run_id text references model_runs(id) on delete set null,
              provider text not null,
              model text not null,
              status text not null,
              idempotency_key text not null unique,
              provider_response_id text,
              error_code text,
              error_message text,
              input_tokens integer,
              output_tokens integer,
              created_at text not null,
              updated_at text not null,
              completed_at text,
              metadata_json text not null default '{}',
              check(provider in ('openai', 'fake')),
              check(status in ('queued', 'retrieving', 'calling_model', 'completed', 'failed')),
              check(status = 'queued' or user_message_id is not null)
            );

            insert into library_folders (id, name, relative_path)
            values ('core', 'Core', 'Core');

            insert into books (
              id,
              folder_id,
              title,
              category,
              relative_path,
              original_source_path,
              managed_pdf_path,
              original_sha256,
              managed_sha256,
              page_count,
              copy_status,
              text_status,
              search_status,
              visual_status,
              discovered_at,
              updated_at
            )
            values (
              'core-rules',
              'core',
              'Core Rules',
              'Core',
              'core.pdf',
              '/source/core.pdf',
              '/managed/core.pdf',
              'source-sha',
              'managed-sha',
              1,
              'copied',
              'imported',
              'indexed',
              'not_scanned',
              '2026-06-03T00:00:00Z',
              '2026-06-03T00:00:00Z'
            );

            insert into pages (
              id,
              book_id,
              page_number,
              extraction_method,
              embedded_text_chars,
              text_chars,
              word_count,
              image_count,
              ocr_attempted,
              has_text
            )
            values ('core-rules:1', 'core-rules', 1, 'ocr', 0, 42, 7, 1, 1, 1);

            insert into source_sets (id, name, is_builtin, created_at, updated_at)
            values ('rules-core', 'Rules/Core', 1, '2026-06-03T00:00:00Z',
                    '2026-06-03T00:00:00Z');

            insert into chat_threads (
              id,
              title,
              active_source_set_id,
              created_at,
              updated_at
            )
            values ('thread-1', 'Rules', 'rules-core', '2026-06-03T00:00:00Z',
                    '2026-06-03T00:00:00Z');

            insert into chat_messages (id, thread_id, role, content, created_at)
            values ('message-1', 'thread-1', 'user', 'critical hits?',
                    '2026-06-03T00:00:00Z');

            insert into retrieval_runs (
              id,
              thread_id,
              message_id,
              source_set_id,
              query,
              created_at,
              metadata_json
            )
            values ('retrieval-1', 'thread-1', 'message-1', 'rules-core',
                    'critical hits', '2026-06-03T00:00:00Z',
                    '{"source_book_ids": ["core-rules", "missing-book"]}');

            insert into retrieval_hits (retrieval_run_id, page_id, score, rank, snippet)
            values ('retrieval-1', 'core-rules:1', 0.5, 1, 'critical hits');

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
            values ('rebuild-1', 'rebuild_fts', 'global', 'succeeded',
                    'rebuild_fts:global:sha', 1, '2026-06-03T00:00:00Z',
                    '2026-06-03T00:00:00Z');

            insert into model_runs (
              id,
              thread_id,
              user_message_id,
              retrieval_run_id,
              provider,
              model,
              status,
              idempotency_key,
              created_at,
              updated_at
            )
            values ('model-1', 'thread-1', 'message-1', 'retrieval-1', 'fake',
                    'fake-model', 'completed', 'model-1',
                    '2026-06-03T00:00:00Z', '2026-06-03T00:00:00Z');
            """
        )


def test_apply_pending_migrations_preserves_legacy_chat_and_retrieval_rows(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy.sqlite"
    create_legacy_phase6_database(db_path)

    summary = apply_pending_migrations(db_path)

    assert summary.applied == (
        "0001_phase_7_source_objects",
        "0002_source_map_retrieval",
        "0003_vector_retrieval",
        "0004_structured_evidence",
        "0005_page_label_calibration",
    )
    assert summary.skipped == ()
    with open_connection(db_path) as connection:
        assert connection.execute("select count(*) from chat_messages").fetchone()[0] == 1
        legacy_hit = connection.execute(
            """
            select
              id,
              retrieval_run_id,
              page_id,
              source_object_id,
              object_type_snapshot,
              heading_path_snapshot_json,
              rank_reasons_json,
              metadata_json
            from retrieval_hits
            where retrieval_run_id = 'retrieval-1'
            """
        ).fetchone()
        assert legacy_hit["id"] == "legacy:retrieval-1:core-rules:1"
        assert legacy_hit["page_id"] == "core-rules:1"
        assert legacy_hit["source_object_id"] is None
        assert legacy_hit["object_type_snapshot"] == "page_fallback"
        assert legacy_hit["heading_path_snapshot_json"] == "[]"
        assert legacy_hit["rank_reasons_json"] == "[]"
        assert legacy_hit["metadata_json"] == "{}"
        assert (
            connection.execute(
                "select id from schema_migrations where id = ?",
                ("0001_phase_7_source_objects",),
            ).fetchone()
            is not None
        )
        assert (
            connection.execute(
                "select id from schema_migrations where id = ?",
                ("0002_source_map_retrieval",),
            ).fetchone()
            is not None
        )
        assert (
            connection.execute(
                "select id from schema_migrations where id = ?",
                ("0003_vector_retrieval",),
            ).fetchone()
            is not None
        )
        assert (
            connection.execute(
                "select id from schema_migrations where id = ?",
                ("0004_structured_evidence",),
            ).fetchone()
            is not None
        )
        assert (
            connection.execute(
                "select id from schema_migrations where id = ?",
                ("0005_page_label_calibration",),
            ).fetchone()
            is not None
        )
        assert migrations.table_exists(connection, "book_page_label_calibrations")
        assert migrations.table_exists(connection, "source_object_embeddings")
        assert (
            connection.execute(
                "select count(*) from book_retrieval_status"
            ).fetchone()[0]
            == 1
        )
        run_source = connection.execute(
            """
            select retrieval_run_id, source_set_id, book_id, book_title_snapshot
            from retrieval_run_source_books
            where retrieval_run_id = 'retrieval-1'
            """
        ).fetchone()
        assert (
            connection.execute(
                """
                select count(*)
                from retrieval_run_source_books
                where retrieval_run_id = 'retrieval-1'
                """
            ).fetchone()[0]
            == 1
        )
        assert run_source["source_set_id"] == "rules-core"
        assert run_source["book_id"] == "core-rules"
        assert run_source["book_title_snapshot"] == "Core Rules"


def test_metadata_source_book_ids_ignores_invalid_metadata() -> None:
    assert migrations.metadata_source_book_ids("{") == ()
    assert migrations.metadata_source_book_ids('{"source_book_ids": "core-rules"}') == ()
    assert migrations.metadata_source_book_ids(
        '{"source_book_ids": ["core-rules", 3, null]}'
    ) == ("core-rules",)


def test_phase7_migration_allows_new_job_types_local_provider_and_object_hits(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy.sqlite"
    create_legacy_phase6_database(db_path)
    apply_pending_migrations(db_path)

    with open_connection(db_path) as connection:
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
            values ('extract-1', 'extract_source_objects', 'core-rules',
                    'running', 'extract_source_objects:core-rules:sha', 1,
                    '2026-06-03T00:00:00Z', '2026-06-03T00:00:00Z')
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
            values ('embeddings-1', 'rebuild_embeddings', 'core-rules',
                    'running', 'rebuild_embeddings:core-rules:sha', 1,
                    '2026-06-03T00:00:00Z', '2026-06-03T00:00:00Z')
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
            values ('source-map-1', 'rebuild_source_maps', 'core-rules',
                    'running', 'rebuild_source_maps:core-rules:sha:v1', 1,
                    '2026-06-03T00:00:00Z', '2026-06-03T00:00:00Z')
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
            values ('page-labels-1', 'backfill_page_labels', 'core-rules',
                    'running',
                    'backfill_page_labels:core-rules:snapshot:page-label-calibration-v1',
                    1, '2026-06-03T00:00:00Z', '2026-06-03T00:00:00Z')
            """
        )
        connection.execute(
            """
            insert into book_page_label_calibrations (
              book_id,
              status,
              method,
              calibration_json,
              page_text_snapshot_sha256,
              updated_at
            )
            values (
              'core-rules',
              'calibrated',
              'imported_labels',
              '{"labels_by_page":{"1":"i"}}',
              'snapshot',
              '2026-06-03T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            insert into model_runs (
              id,
              thread_id,
              user_message_id,
              provider,
              model,
              status,
              idempotency_key,
              created_at,
              updated_at
            )
            values ('local-1', 'thread-1', 'message-1', 'local',
                    'retrieval-confidence-gate', 'completed', 'local-1',
                    '2026-06-03T00:00:00Z', '2026-06-03T00:00:00Z')
            """
        )
        connection.execute(
            """
            insert into source_objects (
              id,
              book_id,
              page_id,
              object_type,
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
            values (
              'core-rules:p1-p1:rule_section:1:aaaaaaaaaaaa',
              'core-rules',
              'core-rules:1',
              'rule_section',
              '[]',
              1,
              1,
              'Critical hits',
              'Critical hits',
              0.8,
              'test',
              'text-snapshot',
              '2026-06-03T00:00:00Z',
              '2026-06-03T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            insert into source_objects (
              id,
              book_id,
              page_id,
              object_type,
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
            values (
              'core-rules:p1-p1:table:2:bbbbbbbbbbbb',
              'core-rules',
              'core-rules:1',
              'table',
              '[]',
              1,
              1,
              'Critical table',
              'Critical table',
              0.8,
              'test',
              'text-snapshot',
              '2026-06-03T00:00:00Z',
              '2026-06-03T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            insert into retrieval_hits (
              id,
              retrieval_run_id,
              page_id,
              source_object_id,
              score,
              rank,
              object_type_snapshot
            )
            values (
              'object-hit-1',
              'retrieval-1',
              'core-rules:1',
              'core-rules:p1-p1:rule_section:1:aaaaaaaaaaaa',
              0.1,
              2,
              'rule_section'
            )
            """
        )
        connection.execute(
            """
            insert into retrieval_hits (
              id,
              retrieval_run_id,
              page_id,
              source_object_id,
              score,
              rank,
              object_type_snapshot
            )
            values (
              'object-hit-2',
              'retrieval-1',
              'core-rules:1',
              'core-rules:p1-p1:table:2:bbbbbbbbbbbb',
              0.2,
              3,
              'table'
            )
            """
        )

        object_hit_count = connection.execute(
            """
            select count(*)
            from retrieval_hits
            where source_object_id is not null
            """
        ).fetchone()[0]
        assert object_hit_count == 2

        connection.execute(
            """
            insert into source_objects (
              id,
              book_id,
              page_id,
              object_type,
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
            values (
              'core-rules:p1-p1:glossary_entry:3:cccccccccccc',
              'core-rules',
              'core-rules:1',
              'glossary_entry',
              '[]',
              1,
              1,
              'Falling: see Falling.',
              'Falling: see Falling.',
              0.8,
              'test',
              'text-snapshot',
              '2026-06-03T00:00:00Z',
              '2026-06-03T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            insert into source_object_links (
              id,
              from_object_id,
              to_object_id,
              to_book_id,
              to_page_id,
              link_type,
              label,
              confidence,
              created_at
            )
            values (
              'glossary-definition-link',
              'core-rules:p1-p1:glossary_entry:3:cccccccccccc',
              'core-rules:p1-p1:rule_section:1:aaaaaaaaaaaa',
              'core-rules',
              'core-rules:1',
              'glossary_definition',
              'Falling',
              0.8,
              '2026-06-03T00:00:00Z'
            )
            """
        )

        glossary_link = connection.execute(
            """
            select link_type
            from source_object_links
            where id = 'glossary-definition-link'
            """
        ).fetchone()
        assert glossary_link["link_type"] == "glossary_definition"


def test_apply_pending_migrations_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite"
    create_legacy_phase6_database(db_path)
    first = apply_pending_migrations(db_path)
    second = apply_pending_migrations(db_path)

    assert first.applied == (
        "0001_phase_7_source_objects",
        "0002_source_map_retrieval",
        "0003_vector_retrieval",
        "0004_structured_evidence",
        "0005_page_label_calibration",
    )
    assert second.applied == ()
    assert second.skipped == (
        "0001_phase_7_source_objects",
        "0002_source_map_retrieval",
        "0003_vector_retrieval",
        "0004_structured_evidence",
        "0005_page_label_calibration",
    )


def test_apply_pending_migrations_records_fresh_schema_without_rebuilds(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "fresh.sqlite"
    initialize_database(db_path)

    summary = apply_pending_migrations(db_path)

    assert summary.applied == (
        "0001_phase_7_source_objects",
        "0002_source_map_retrieval",
        "0003_vector_retrieval",
        "0004_structured_evidence",
        "0005_page_label_calibration",
    )
    with open_connection(db_path) as connection:
        assert (
            connection.execute(
                "select id from schema_migrations where id = ?",
                ("0001_phase_7_source_objects",),
            ).fetchone()
            is not None
        )
        assert (
            connection.execute(
                "select id from schema_migrations where id = ?",
                ("0002_source_map_retrieval",),
            ).fetchone()
            is not None
        )
        assert (
            connection.execute(
                "select id from schema_migrations where id = ?",
                ("0003_vector_retrieval",),
            ).fetchone()
            is not None
        )
        assert (
            connection.execute(
                "select id from schema_migrations where id = ?",
                ("0004_structured_evidence",),
            ).fetchone()
            is not None
        )
        assert (
            connection.execute(
                "select id from schema_migrations where id = ?",
                ("0005_page_label_calibration",),
            ).fetchone()
            is not None
        )


def test_structured_evidence_migration_marks_old_extractions_stale(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "fresh.sqlite"
    initialize_database(db_path)
    with open_connection(db_path) as connection:
        connection.execute(
            """
            insert into library_folders (id, name, relative_path)
            values ('core', 'Core', 'Core')
            """
        )
        connection.execute(
            """
            insert into books (
              id,
              folder_id,
              title,
              category,
              relative_path,
              original_source_path,
              managed_pdf_path,
              original_sha256,
              managed_sha256,
              page_count,
              copy_status,
              text_status,
              search_status,
              visual_status,
              discovered_at,
              updated_at
            )
            values (
              'core-rules',
              'core',
              'Core Rules',
              'Core',
              'core.pdf',
              '/source/core.pdf',
              '/managed/core.pdf',
              'source-sha',
              'managed-sha',
              1,
              'copied',
              'imported',
              'indexed',
              'not_scanned',
              '2026-06-05T00:00:00Z',
              '2026-06-05T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            insert into book_object_status (
              book_id,
              status,
              object_count,
              table_count,
              stat_block_count,
              text_snapshot_sha256,
              updated_at
            )
            values (
              'core-rules',
              'indexed',
              3,
              1,
              1,
              'old-snapshot',
              '2026-06-05T00:00:00Z'
            )
            """
        )

    apply_pending_migrations(db_path)

    with open_connection(db_path) as connection:
        status = connection.execute(
            """
            select
              status,
              object_count,
              table_count,
              stat_block_count,
              text_snapshot_sha256,
              extractor_version
            from book_object_status
            where book_id = 'core-rules'
            """
        ).fetchone()

    assert status["status"] == "not_started"
    assert status["object_count"] == 0
    assert status["table_count"] == 0
    assert status["stat_block_count"] == 0
    assert status["text_snapshot_sha256"] is None
    assert status["extractor_version"] is None


def test_apply_pending_migrations_refuses_missing_database(tmp_path: Path) -> None:
    db_path = tmp_path / "typo.sqlite"

    with pytest.raises(MigrationError, match="does not exist"):
        apply_pending_migrations(db_path)

    assert not db_path.exists()


def test_apply_pending_migrations_refuses_uninitialized_database(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.sqlite"
    sqlite3.connect(db_path).close()

    with pytest.raises(MigrationError, match="not an initialized WFRP Companion database"):
        apply_pending_migrations(db_path)

    with sqlite3.connect(db_path) as connection:
        tables = connection.execute(
            """
            select name
            from sqlite_master
            where type = 'table'
            """
        ).fetchall()
    assert tables == []


def test_phase7_migration_rolls_back_duplicate_legacy_ranks(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy.sqlite"
    create_legacy_phase6_database(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            insert into pages (
              id,
              book_id,
              page_number,
              extraction_method,
              embedded_text_chars,
              text_chars,
              word_count,
              image_count,
              ocr_attempted,
              has_text
            )
            values ('core-rules:2', 'core-rules', 2, 'ocr', 0, 42, 7, 1, 1, 1)
            """
        )
        connection.execute(
            """
            insert into retrieval_hits (retrieval_run_id, page_id, score, rank, snippet)
            values ('retrieval-1', 'core-rules:2', 0.4, 1, 'duplicate rank')
            """
        )

    with pytest.raises(MigrationError, match="duplicate legacy retrieval hit ranks"):
        apply_pending_migrations(db_path)

    with sqlite3.connect(db_path) as connection:
        columns = [
            row[1]
            for row in connection.execute("pragma table_info(retrieval_hits)").fetchall()
        ]
        assert columns == ["retrieval_run_id", "page_id", "score", "rank", "snippet"]
        assert (
            connection.execute(
                """
                select count(*)
                from sqlite_master
                where type = 'table'
                  and name = 'schema_migrations'
                """
            ).fetchone()[0]
            == 0
        )


def test_phase7_migration_rolls_back_database_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "fresh.sqlite"

    def fail_after_ddl(connection: sqlite3.Connection) -> None:
        connection.execute("create table transient_migration_table (id text primary key)")
        raise sqlite3.OperationalError("forced sqlite failure")

    monkeypatch.setattr(migrations, "apply_phase_7_source_objects", fail_after_ddl)
    with initialize_database(db_path) as connection:
        with pytest.raises(MigrationError, match="forced sqlite failure"):
            apply_migration(connection, "0001_phase_7_source_objects")
        assert not migrations.table_exists(connection, "transient_migration_table")


def test_phase7_migration_rolls_back_unexpected_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "fresh.sqlite"

    def fail_unexpectedly(connection: sqlite3.Connection) -> None:
        connection.execute("create table unexpected_migration_table (id text primary key)")
        raise RuntimeError("forced unexpected failure")

    monkeypatch.setattr(migrations, "apply_phase_7_source_objects", fail_unexpectedly)
    with initialize_database(db_path) as connection:
        with pytest.raises(RuntimeError, match="forced unexpected failure"):
            apply_migration(connection, "0001_phase_7_source_objects")
        assert not migrations.table_exists(connection, "unexpected_migration_table")


def test_apply_migration_rejects_unknown_migration_id(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.sqlite"
    with initialize_database(db_path) as connection:
        with pytest.raises(ValueError, match="Unknown migration"):
            apply_migration(connection, "9999_unknown")
