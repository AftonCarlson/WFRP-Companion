from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from tests.db.test_migrations import create_legacy_phase6_database
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database, open_connection
from wfrp_companion.source_objects import store
from wfrp_companion.source_objects import extractor
from wfrp_companion.source_objects.extractor import extract_source_object_library
from wfrp_companion.source_objects.models import SourceObject
from wfrp_companion.source_objects.store import (
    SOURCE_OBJECT_EXTRACTOR_VERSION,
    book_text_snapshot_sha256,
    claim_extraction_job,
    eligible_books,
    extraction_job_id,
)


def make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        pdf_root=tmp_path / "pdfs",
        data_dir=data_dir,
        db_path=data_dir / "wfrp_companion.sqlite",
        asset_dir=data_dir / "library" / "assets",
    )


def insert_indexed_book(config: AppConfig, *, book_id: str = "rules") -> None:
    relative_path = "Core/Rules Primer.pdf"
    original_source_path = "/source/Rules Primer.pdf"
    original_sha256 = "source-sha"
    managed_sha256 = "managed-sha"
    if book_id != "rules":
        relative_path = f"Core/{book_id}.pdf"
        original_source_path = f"/source/{book_id}.pdf"
        original_sha256 = f"source-sha-{book_id}"
        managed_sha256 = f"managed-sha-{book_id}"
    with initialize_database(config.db_path) as connection:
        connection.execute(
            """
            insert into library_folders (id, name, relative_path)
            values ('core', 'Core', 'Core')
            on conflict(id) do nothing
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
              ?,
              'core',
              'Rules Primer',
              'Core',
              ?,
              ?,
              '/managed/missing.pdf',
              ?,
              ?,
              2,
              'copied',
              'imported',
              'indexed',
              'not_scanned',
              '2026-06-05T00:00:00Z',
              '2026-06-05T00:00:00Z'
            )
            """,
            (
                book_id,
                relative_path,
                original_source_path,
                original_sha256,
                managed_sha256,
            ),
        )
        pages = (
            (
                f"{book_id}:1",
                1,
                "embedded",
                70,
                11,
                False,
                "Chapter I: Combat\nCritical Hits\nRoll on the result table.",
            ),
            (
                f"{book_id}:2",
                2,
                "ocr",
                53,
                9,
                True,
                "Fallback text about lanterns and tunnels.",
            ),
        )
        for page_id, page_number, method, text_chars, word_count, ocr, text in pages:
            text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
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
                values (?, ?, ?, ?, ?, ?, ?, 0, ?, 1)
                """,
                (
                    page_id,
                    book_id,
                    page_number,
                    method,
                    0 if ocr else text_chars,
                    text_chars,
                    word_count,
                    int(ocr),
                ),
            )
            connection.execute(
                """
                insert into page_text (page_id, text, text_sha256, generated_at)
                values (?, ?, ?, '2026-06-05T00:00:00Z')
                """,
                (page_id, text, text_sha),
            )


def count_rows(config: AppConfig, table: str) -> int:
    with open_connection(config.db_path) as connection:
        return connection.execute(f"select count(*) from {table}").fetchone()[0]


def fetch_one(config: AppConfig, sql: str) -> sqlite3.Row:
    with open_connection(config.db_path) as connection:
        row = connection.execute(sql).fetchone()
    assert row is not None
    return row


def make_source_object(
    *,
    object_id: str,
    object_type: str,
    title: str | None = None,
    page_number: int = 1,
    text: str = "Reference text.",
    metadata_json: str = "{}",
    parent_object_id: str | None = None,
) -> SourceObject:
    return SourceObject(
        id=object_id,
        book_id="rules",
        page_id=f"rules:{page_number}",
        object_type=object_type,
        parent_object_id=parent_object_id,
        title=title,
        heading_path=(title,) if title is not None else (),
        page_start=page_number,
        page_end=page_number,
        text=text,
        search_text=text,
        confidence=0.8,
        extraction_method="test",
        text_snapshot_sha256="snapshot",
        metadata_json=metadata_json,
    )


def test_book_text_snapshot_hashes_page_text_in_page_order(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)

    with open_connection(config.db_path) as connection:
        snapshot = book_text_snapshot_sha256(connection, "rules")

    digest = hashlib.sha256()
    for page_id in ("rules:1", "rules:2"):
        text_sha = fetch_one(
            config,
            f"select text_sha256 from page_text where page_id = '{page_id}'",
        )["text_sha256"]
        digest.update(page_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(text_sha.encode("utf-8"))
        digest.update(b"\n")
    assert snapshot == digest.hexdigest()


def test_eligible_books_supports_empty_and_specific_filters(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)

    with open_connection(config.db_path) as connection:
        assert eligible_books(connection, book_ids=()) == ()
        filtered = eligible_books(connection, book_ids=("rules",))

    assert len(filtered) == 1
    assert filtered[0].book_id == "rules"


def test_extract_source_object_library_persists_objects_status_and_job(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)

    summary = extract_source_object_library(config)

    assert summary.discovered == 1
    assert summary.extracted == 1
    assert summary.objects_written == 2
    assert summary.skipped_current == 0
    assert summary.failed == 0
    assert count_rows(config, "source_objects") == 2
    assert count_rows(config, "source_object_search") == 2
    assert count_rows(config, "source_object_search_fts") == 2
    status = fetch_one(config, "select * from book_object_status")
    job = fetch_one(config, "select * from ingest_jobs where job_type = 'extract_source_objects'")
    rule = fetch_one(
        config,
        "select * from source_objects where object_type = 'rule_section'",
    )
    assert status["status"] == "indexed"
    assert status["object_count"] == 2
    assert status["extractor_version"] == SOURCE_OBJECT_EXTRACTOR_VERSION
    assert status["text_snapshot_sha256"] == summary.book_summaries[0].text_snapshot_sha256
    assert job["status"] == "succeeded"
    assert job["idempotency_key"] == extraction_job_id(
        "rules",
        summary.book_summaries[0].text_snapshot_sha256,
    )
    assert rule["title"] == "Critical Hits"
    with open_connection(config.db_path) as connection:
        row = connection.execute(
            """
            select source_object_search.source_object_id
            from source_object_search_fts
            join source_object_search
              on source_object_search.rowid = source_object_search_fts.rowid
            where source_object_search_fts match '"critical"'
            """
        ).fetchone()
    assert row["source_object_id"] == rule["id"]


def test_extract_source_object_library_reruns_stale_extractor_version(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    first = extract_source_object_library(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update book_object_status
            set extractor_version = 'legacy-heading-v1'
            where book_id = 'rules'
            """
        )

    second = extract_source_object_library(config)

    assert first.extracted == 1
    assert second.extracted == 1
    assert second.skipped_current == 0
    status = fetch_one(config, "select * from book_object_status")
    assert status["extractor_version"] == SOURCE_OBJECT_EXTRACTOR_VERSION


def test_extract_source_object_library_persists_structured_links_and_counts(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    structured_text = (
        "Chapter I: Weather\n"
        "Weather Results\n"
        "| Roll | Result |\n"
        "| 1 | Clear skies |\n"
        "| 2 | Storms force a travel test |\n"
        "Captain Mira\n"
        "M WS BS S T W I A Dex Int WP Fel\n"
        "4 41 32 3 3 12 38 1 34 35 36 37\n"
        "Skills: Command, Perception\n"
    )
    text_sha = hashlib.sha256(structured_text.encode("utf-8")).hexdigest()
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update page_text
            set text = ?,
                text_sha256 = ?
            where page_id = 'rules:1'
            """,
            (structured_text, text_sha),
        )
        connection.execute(
            """
            update pages
            set text_chars = ?,
                word_count = ?
            where id = 'rules:1'
            """,
            (len(structured_text), len(structured_text.split())),
        )

    summary = extract_source_object_library(config, force=True)

    assert summary.extracted == 1
    status = fetch_one(config, "select * from book_object_status")
    assert status["table_count"] == 1
    assert status["stat_block_count"] == 1
    assert count_rows(config, "source_object_links") == 3
    with open_connection(config.db_path) as connection:
        links = {
            row["link_type"]
            for row in connection.execute(
                "select link_type from source_object_links order by link_type"
            ).fetchall()
        }
        table_row_targets = connection.execute(
            """
            select count(*)
            from source_object_links
            join source_objects child
              on child.id = source_object_links.from_object_id
            join source_objects parent
              on parent.id = source_object_links.to_object_id
            where source_object_links.link_type = 'table_row'
              and child.object_type = 'table_row'
              and parent.object_type = 'table'
            """
        ).fetchone()[0]

    assert links == {"stat_profile", "table_row"}
    assert table_row_targets == 2


def test_replace_book_source_objects_writes_page_only_reference_links(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    source_objects = (
        make_source_object(
            object_id="rules:page-only-cross-reference",
            object_type="cross_reference",
            title="Known Topic",
            metadata_json='{"target_title": "Known Topic", "target_page": 2}',
        ),
        make_source_object(
            object_id="rules:missing-cross-reference",
            object_type="cross_reference",
            title="Missing Topic",
            metadata_json='{"target_title": "Missing Topic", "target_page": 99}',
        ),
        make_source_object(
            object_id="rules:untitled-cross-reference",
            object_type="cross_reference",
            title="Untitled Topic",
            metadata_json='{"target_page": 2}',
        ),
    )

    with open_connection(config.db_path) as connection:
        store.replace_book_source_objects(
            connection,
            book_id="rules",
            text_snapshot_sha256="snapshot",
            source_objects=source_objects,
            job_id="extract_source_objects:rules:snapshot",
            now="2026-06-05T00:00:00Z",
        )
        links = connection.execute(
            """
            select from_object_id, to_object_id, to_page_id, link_type
            from source_object_links
            order by from_object_id
            """
        ).fetchall()
        assert store.target_page_id_for(
            connection,
            book_id="rules",
            page_number=None,
        ) is None

    assert len(links) == 1
    assert links[0]["from_object_id"] == "rules:page-only-cross-reference"
    assert links[0]["to_object_id"] is None
    assert links[0]["to_page_id"] == "rules:2"
    assert links[0]["link_type"] == "cross_reference"


def test_replace_book_source_objects_dedupes_historical_hit_fallbacks(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    old_objects = (
        make_source_object(
            object_id="rules:old-a",
            object_type="rule_section",
            title="Old A",
            text="Old A text.",
        ),
        make_source_object(
            object_id="rules:old-b",
            object_type="rule_section",
            title="Old B",
            text="Old B text.",
        ),
    )
    new_objects = (
        make_source_object(
            object_id="rules:new",
            object_type="rule_section",
            title="New",
            text="New text.",
        ),
    )

    with open_connection(config.db_path) as connection:
        store.replace_book_source_objects(
            connection,
            book_id="rules",
            text_snapshot_sha256="snapshot",
            source_objects=old_objects,
            job_id="extract_source_objects:rules:snapshot",
            now="2026-06-05T00:00:00Z",
        )
        connection.execute(
            """
            insert into retrieval_runs (id, query, created_at)
            values ('retrieval-old', 'old query', '2026-06-05T00:00:00Z')
            """
        )
        connection.executemany(
            """
            insert into retrieval_hits (
              id,
              retrieval_run_id,
              page_id,
              source_object_id,
              score,
              rank,
              snippet
            )
            values (?, 'retrieval-old', 'rules:1', ?, 1, ?, ?)
            """,
            (
                ("hit-old-a", "rules:old-a", 1, "Old A"),
                ("hit-old-b", "rules:old-b", 2, "Old B"),
            ),
        )

        store.replace_book_source_objects(
            connection,
            book_id="rules",
            text_snapshot_sha256="snapshot-2",
            source_objects=new_objects,
            job_id="extract_source_objects:rules:snapshot-2",
            now="2026-06-05T00:00:01Z",
        )

        hits = connection.execute(
            """
            select id, source_object_id
            from retrieval_hits
            where retrieval_run_id = 'retrieval-old'
              and page_id = 'rules:1'
            order by rank
            """
        ).fetchall()

    assert len(hits) == 1
    assert hits[0]["id"] == "hit-old-a"
    assert hits[0]["source_object_id"] is None


def test_source_object_link_helper_edges() -> None:
    child = make_source_object(
        object_id="rules:child",
        object_type="page_chunk",
        parent_object_id="rules:parent",
    )
    parent = make_source_object(
        object_id="rules:parent",
        object_type="rule_section",
        title="Parent",
    )
    malformed = make_source_object(
        object_id="rules:bad-metadata",
        object_type="cross_reference",
        metadata_json="{",
    )
    list_metadata = make_source_object(
        object_id="rules:list-metadata",
        object_type="cross_reference",
        metadata_json="[]",
    )
    earlier_target = make_source_object(
        object_id="rules:target-earlier",
        object_type="rule_section",
        title="Shared Topic",
        page_number=1,
    )
    later_target = make_source_object(
        object_id="rules:target-later",
        object_type="rule_section",
        title="Shared Topic",
        page_number=2,
    )
    reference = make_source_object(
        object_id="rules:reference",
        object_type="index_entry",
        title="Shared Topic",
        page_number=3,
    )

    assert store.parent_link_type_for(child, parent) == "same_section"
    assert store.reference_link_type_for("index_entry") == "index_entry"
    assert store.reference_link_type_for("glossary_entry") == "glossary_definition"
    assert store.reference_link_type_for("cross_reference") == "cross_reference"
    assert store.reference_link_type_for("rule_section") is None
    assert store.source_object_metadata(malformed) == {}
    assert store.source_object_metadata(list_metadata) == {}
    assert store.find_reference_target_object(
        (later_target, earlier_target, reference),
        source_object=reference,
        target_title="Shared Topic",
        target_page=None,
    ) == earlier_target
    assert (
        store.find_reference_target_object(
            (earlier_target,),
            source_object=reference,
            target_title="Other Topic",
            target_page=None,
        )
        is None
    )


def test_extract_source_object_library_initializes_missing_database(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)

    summary = extract_source_object_library(config)

    assert config.db_path.exists()
    assert summary.discovered == 0
    assert summary.extracted == 0


def test_extract_source_object_library_migrates_existing_phase6_db_before_schema_replay(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    create_legacy_phase6_database(config.db_path)
    with sqlite3.connect(config.db_path) as connection:
        text = "Chapter I: Combat\nCritical Hits\nRoll on the result table."
        connection.execute(
            """
            create table page_text (
              page_id text primary key references pages(id) on delete cascade,
              text text not null,
              text_sha256 text not null,
              generated_at text not null
            )
            """
        )
        connection.execute(
            """
            insert into page_text (page_id, text, text_sha256, generated_at)
            values ('core-rules:1', ?, ?, '2026-06-05T00:00:00Z')
            """,
            (text, hashlib.sha256(text.encode("utf-8")).hexdigest()),
        )

    summary = extract_source_object_library(config, book_ids=("core-rules",))

    assert summary.extracted == 1
    assert count_rows(config, "source_objects") == 1


def test_extract_source_object_library_skips_current_and_force_replaces(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    first = extract_source_object_library(config)

    second = extract_source_object_library(config)
    forced = extract_source_object_library(config, force=True)

    assert first.extracted == 1
    assert second.extracted == 0
    assert second.skipped_current == 1
    assert forced.extracted == 1
    assert count_rows(config, "source_objects") == 2


def test_extract_source_object_library_recovers_stale_running_jobs(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            insert into book_object_status (book_id, status, updated_at)
            values ('rules', 'extracting', '2026-06-04T00:00:00Z')
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
            values (
              'stale-job',
              'extract_source_objects',
              'rules',
              'running',
              'extract_source_objects:rules:stale',
              1,
              '2026-06-04T00:00:00Z',
              '2026-06-04T00:00:00Z'
            )
            """
        )
        connection.commit()

    summary = extract_source_object_library(config, stale_running_minutes=1)

    assert summary.stale_recovered == 1
    assert summary.extracted == 1
    assert count_rows(config, "source_objects") == 2


def test_extract_source_object_library_leaves_active_running_job_alone(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    with open_connection(config.db_path) as connection:
        snapshot = book_text_snapshot_sha256(connection, "rules")
        connection.execute(
            """
            insert into book_object_status (
              book_id,
              status,
              text_snapshot_sha256,
              updated_at
            )
            values ('rules', 'extracting', ?, '2999-01-01T00:00:00Z')
            """,
            (snapshot,),
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
            values (
              'active-job',
              'extract_source_objects',
              'rules',
              'running',
              ?,
              1,
              '2999-01-01T00:00:00Z',
              '2999-01-01T00:00:00Z'
            )
            """,
            (extraction_job_id("rules", snapshot),),
        )
        connection.commit()

    summary = extract_source_object_library(config, stale_running_minutes=1)

    assert summary.discovered == 1
    assert summary.extracted == 0
    assert summary.objects_written == 0
    assert count_rows(config, "source_objects") == 0


def test_extract_source_object_library_retry_running_recovers_fresh_jobs(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            insert into book_object_status (book_id, status, updated_at)
            values ('rules', 'extracting', '2999-01-01T00:00:00Z')
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
            values (
              'fresh-running-job',
              'extract_source_objects',
              'rules',
              'running',
              'extract_source_objects:rules:fresh',
              1,
              '2999-01-01T00:00:00Z',
              '2999-01-01T00:00:00Z'
            )
            """
        )
        connection.commit()

    summary = extract_source_object_library(config, retry_running=True)

    assert summary.stale_recovered == 1
    assert summary.extracted == 1


def test_claim_extraction_job_rejects_running_idempotency_key(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    with open_connection(config.db_path) as connection:
        snapshot = book_text_snapshot_sha256(connection, "rules")
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
              'running-job',
              'extract_source_objects',
              'rules',
              'running',
              ?,
              1,
              '2026-06-05T00:00:00Z',
              '2026-06-05T00:00:00Z'
            )
            """,
            (extraction_job_id("rules", snapshot),),
        )
        connection.commit()

        claimed = claim_extraction_job(
            connection,
            book_id="rules",
            text_snapshot_sha256=snapshot,
            force=False,
            now="2026-06-05T00:00:01Z",
        )

    assert claimed is False


def test_claim_extraction_job_rejects_indexing_status_without_running_job(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)
    with open_connection(config.db_path) as connection:
        snapshot = book_text_snapshot_sha256(connection, "rules")
        connection.execute(
            """
            insert into book_object_status (book_id, status, updated_at)
            values ('rules', 'indexing', '2026-06-05T00:00:00Z')
            """
        )
        connection.commit()

        claimed = claim_extraction_job(
            connection,
            book_id="rules",
            text_snapshot_sha256=snapshot,
            force=False,
            now="2026-06-05T00:00:01Z",
        )
        status = fetch_one(config, "select status from book_object_status")["status"]
        job_count = count_rows(config, "ingest_jobs")

    assert claimed is False
    assert status == "indexing"
    assert job_count == 0


def test_extract_source_object_library_records_failures(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_book(config)

    def fail_extraction(**kwargs):
        raise RuntimeError("synthetic extraction failure")

    monkeypatch.setattr(extractor, "extract_objects_from_pages", fail_extraction)
    summary = extract_source_object_library(config)

    assert summary.failed == 1
    assert summary.failures[0].book_id == "rules"
    assert "synthetic extraction failure" in summary.failures[0].reason
    status = fetch_one(config, "select * from book_object_status")
    job = fetch_one(config, "select * from ingest_jobs where job_type = 'extract_source_objects'")
    assert status["status"] == "failed"
    assert "synthetic extraction failure" in status["last_error"]
    assert job["status"] == "failed"
