from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from wfrp_companion.db.connection import open_connection


MIGRATION_DIR = Path(__file__).with_name("migration_files")
PHASE_7_MIGRATION_ID = "0001_phase_7_source_objects"
SOURCE_MAP_RETRIEVAL_MIGRATION_ID = "0002_source_map_retrieval"
VECTOR_RETRIEVAL_MIGRATION_ID = "0003_vector_retrieval"
STRUCTURED_EVIDENCE_MIGRATION_ID = "0004_structured_evidence"
PAGE_LABEL_CALIBRATION_MIGRATION_ID = "0005_page_label_calibration"
EMBEDDING_PROVIDER_IDENTITY_MIGRATION_ID = "0006_embedding_provider_identity"
FAMILIAR_AGENT_RESEARCH_MIGRATION_ID = "0007_familiar_agent_research"
FAMILIAR_RESEARCH_PLANS_MIGRATION_ID = "0008_familiar_research_plans"
MIGRATION_IDS: tuple[str, ...] = (
    PHASE_7_MIGRATION_ID,
    SOURCE_MAP_RETRIEVAL_MIGRATION_ID,
    VECTOR_RETRIEVAL_MIGRATION_ID,
    STRUCTURED_EVIDENCE_MIGRATION_ID,
    PAGE_LABEL_CALIBRATION_MIGRATION_ID,
    EMBEDDING_PROVIDER_IDENTITY_MIGRATION_ID,
    FAMILIAR_AGENT_RESEARCH_MIGRATION_ID,
    FAMILIAR_RESEARCH_PLANS_MIGRATION_ID,
)


@dataclass(frozen=True)
class MigrationSummary:
    applied: tuple[str, ...]
    skipped: tuple[str, ...]
    table_counts: tuple[tuple[str, int], ...] = ()


class MigrationError(RuntimeError):
    """Raised when a local database cannot be migrated safely."""


def apply_pending_migrations(db_path: Path) -> MigrationSummary:
    if not db_path.exists():
        raise MigrationError(f"Database does not exist: {db_path}")

    applied: list[str] = []
    skipped: list[str] = []

    with open_connection(db_path) as connection:
        connection.execute("pragma journal_mode = wal")
        validate_initialized_database(connection)
        for migration_id in MIGRATION_IDS:
            if migration_applied(connection, migration_id):
                skipped.append(migration_id)
                continue
            apply_migration(connection, migration_id)
            applied.append(migration_id)
        table_counts = collect_table_counts(connection)

    return MigrationSummary(
        applied=tuple(applied),
        skipped=tuple(skipped),
        table_counts=table_counts,
    )


def ensure_schema_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        create table if not exists schema_migrations (
          id text primary key,
          applied_at text not null
        )
        """
    )


def table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        """
        select 1
        from sqlite_master
        where type = 'table'
          and name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def validate_initialized_database(connection: sqlite3.Connection) -> None:
    required_tables = (
        "books",
        "pages",
        "ingest_jobs",
        "retrieval_runs",
        "retrieval_hits",
        "model_runs",
    )
    missing_tables = [
        table_name
        for table_name in required_tables
        if not table_exists(connection, table_name)
    ]
    if missing_tables:
        missing = ", ".join(missing_tables)
        raise MigrationError(
            f"Database is not an initialized WFRP Companion database; "
            f"missing required tables: {missing}"
        )


def migration_applied(connection: sqlite3.Connection, migration_id: str) -> bool:
    if not table_exists(connection, "schema_migrations"):
        return False
    row = connection.execute(
        "select 1 from schema_migrations where id = ?",
        (migration_id,),
    ).fetchone()
    return row is not None


def apply_migration(connection: sqlite3.Connection, migration_id: str) -> None:
    if migration_id == PHASE_7_MIGRATION_ID:
        migration_function = apply_phase_7_source_objects
        preflight_phase_7_source_objects(connection)
    elif migration_id == SOURCE_MAP_RETRIEVAL_MIGRATION_ID:
        migration_function = apply_source_map_retrieval
    elif migration_id == VECTOR_RETRIEVAL_MIGRATION_ID:
        migration_function = apply_vector_retrieval
    elif migration_id == STRUCTURED_EVIDENCE_MIGRATION_ID:
        migration_function = apply_structured_evidence
    elif migration_id == PAGE_LABEL_CALIBRATION_MIGRATION_ID:
        migration_function = apply_page_label_calibration
    elif migration_id == EMBEDDING_PROVIDER_IDENTITY_MIGRATION_ID:
        migration_function = apply_embedding_provider_identity
    elif migration_id == FAMILIAR_AGENT_RESEARCH_MIGRATION_ID:
        migration_function = apply_familiar_agent_research
    elif migration_id == FAMILIAR_RESEARCH_PLANS_MIGRATION_ID:
        migration_function = apply_familiar_research_plans
    else:
        raise ValueError(f"Unknown migration: {migration_id}")

    foreign_keys_enabled = connection.execute("pragma foreign_keys").fetchone()[0]
    try:
        connection.execute("pragma foreign_keys = off")
        connection.execute("begin")
        ensure_schema_migrations(connection)
        migration_function(connection)
        connection.execute(
            """
            insert into schema_migrations (id, applied_at)
            values (?, ?)
            """,
            (migration_id, utc_timestamp()),
        )
        connection.commit()
    except sqlite3.DatabaseError as error:
        connection.rollback()
        raise MigrationError(f"Migration {migration_id} failed: {error}") from error
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute(f"pragma foreign_keys = {int(foreign_keys_enabled)}")


def apply_phase_7_source_objects(connection: sqlite3.Connection) -> None:
    execute_sql_script(
        connection,
        (MIGRATION_DIR / f"{PHASE_7_MIGRATION_ID}.sql").read_text(encoding="utf-8"),
    )
    rebuild_ingest_jobs_if_needed(connection)
    rebuild_model_runs_if_needed(connection)
    rebuild_retrieval_hits_if_needed(connection)
    create_phase_7_indexes(connection)


def apply_source_map_retrieval(connection: sqlite3.Connection) -> None:
    execute_sql_script(
        connection,
        (
            MIGRATION_DIR / f"{SOURCE_MAP_RETRIEVAL_MIGRATION_ID}.sql"
        ).read_text(encoding="utf-8"),
    )
    rebuild_ingest_jobs_if_needed(
        connection,
        required_job_type="rebuild_source_maps",
    )
    backfill_book_retrieval_status(connection)
    backfill_retrieval_run_source_books(connection)


def apply_vector_retrieval(connection: sqlite3.Connection) -> None:
    execute_sql_script(
        connection,
        (
            MIGRATION_DIR / f"{VECTOR_RETRIEVAL_MIGRATION_ID}.sql"
        ).read_text(encoding="utf-8"),
    )
    rebuild_ingest_jobs_if_needed(
        connection,
        required_job_type="rebuild_embeddings",
    )


def apply_structured_evidence(connection: sqlite3.Connection) -> None:
    execute_sql_script(
        connection,
        (
            MIGRATION_DIR / f"{STRUCTURED_EVIDENCE_MIGRATION_ID}.sql"
        ).read_text(encoding="utf-8"),
    )
    rebuild_structured_evidence_tables_if_needed(connection)
    add_extractor_version_column_if_needed(connection)
    mark_existing_extractions_stale_for_structured_evidence(connection)


def apply_page_label_calibration(connection: sqlite3.Connection) -> None:
    execute_sql_script(
        connection,
        (
            MIGRATION_DIR / f"{PAGE_LABEL_CALIBRATION_MIGRATION_ID}.sql"
        ).read_text(encoding="utf-8"),
    )
    rebuild_ingest_jobs_if_needed(
        connection,
        required_job_type="backfill_page_labels",
    )
    backfill_book_retrieval_status(connection)


def apply_embedding_provider_identity(connection: sqlite3.Connection) -> None:
    if "embedding_provider" not in column_names(connection, "book_retrieval_status"):
        connection.execute(
            "alter table book_retrieval_status add column embedding_provider text"
        )
    if "embedding_provider" not in column_names(connection, "source_object_embeddings"):
        connection.execute(
            """
            alter table source_object_embeddings
            add column embedding_provider text not null default 'local-hash'
            """
        )
    connection.execute(
        """
        update book_retrieval_status
        set embedding_provider = 'local-hash'
        where embedding_provider is null
          and vector_status = 'indexed'
          and embedding_model is not null
          and embedding_dimensions is not null
        """
    )
    execute_sql_script(
        connection,
        (
            MIGRATION_DIR / f"{EMBEDDING_PROVIDER_IDENTITY_MIGRATION_ID}.sql"
        ).read_text(encoding="utf-8"),
    )


def apply_familiar_agent_research(connection: sqlite3.Connection) -> None:
    execute_sql_script(
        connection,
        (
            MIGRATION_DIR / f"{FAMILIAR_AGENT_RESEARCH_MIGRATION_ID}.sql"
        ).read_text(encoding="utf-8"),
    )


def apply_familiar_research_plans(connection: sqlite3.Connection) -> None:
    execute_sql_script(
        connection,
        (
            MIGRATION_DIR / f"{FAMILIAR_RESEARCH_PLANS_MIGRATION_ID}.sql"
        ).read_text(encoding="utf-8"),
    )
    rebuild_familiar_research_runs_if_needed(connection)
    rebuild_familiar_tool_calls_if_needed(connection)
    rebuild_familiar_evidence_judgments_if_needed(connection)
    create_familiar_research_plan_indexes(connection)


def execute_sql_script(connection: sqlite3.Connection, sql: str) -> None:
    for statement in sql.split(";"):
        statement = statement.strip()
        if statement:
            connection.execute(statement)


def preflight_phase_7_source_objects(connection: sqlite3.Connection) -> None:
    if "id" in column_names(connection, "retrieval_hits"):
        return

    duplicate = connection.execute(
        """
        select retrieval_run_id, rank, count(*) as duplicate_count
        from retrieval_hits
        group by retrieval_run_id, rank
        having count(*) > 1
        limit 1
        """
    ).fetchone()
    if duplicate is not None:
        raise MigrationError(
            "Cannot migrate duplicate legacy retrieval hit ranks: "
            f"retrieval_run_id={duplicate['retrieval_run_id']}, "
            f"rank={duplicate['rank']}, "
            f"count={duplicate['duplicate_count']}"
        )


def collect_table_counts(connection: sqlite3.Connection) -> tuple[tuple[str, int], ...]:
    table_names = (
        "books",
        "pages",
        "source_objects",
        "source_object_links",
        "book_object_status",
        "source_object_search",
        "source_object_embeddings",
        "book_retrieval_status",
        "book_page_label_calibrations",
        "book_source_maps",
        "retrieval_run_source_books",
        "retrieval_hits",
        "model_runs",
        "chat_thread_context",
        "familiar_research_runs",
        "familiar_research_plans",
        "familiar_tool_calls",
        "familiar_evidence_judgments",
        "ingest_jobs",
    )
    return tuple(
        (table_name, table_count(connection, table_name))
        for table_name in table_names
        if table_exists(connection, table_name)
    )


def table_count(connection: sqlite3.Connection, table_name: str) -> int:
    row = connection.execute(f"select count(*) from {table_name}").fetchone()
    return int(row[0])


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def table_sql(connection: sqlite3.Connection, table_name: str) -> str:
    row = connection.execute(
        """
        select sql
        from sqlite_master
        where type = 'table'
          and name = ?
        """,
        (table_name,),
    ).fetchone()
    return "" if row is None else row["sql"] or ""


def column_names(connection: sqlite3.Connection, table_name: str) -> tuple[str, ...]:
    rows = connection.execute(f"pragma table_info({table_name})").fetchall()
    return tuple(row["name"] for row in rows)


def rebuild_ingest_jobs_if_needed(
    connection: sqlite3.Connection,
    *,
    required_job_type: str = "extract_source_objects",
) -> None:
    if required_job_type in table_sql(connection, "ingest_jobs"):
        return

    connection.execute("drop index if exists ix_ingest_jobs_status")
    connection.execute("alter table ingest_jobs rename to ingest_jobs_phase6")
    connection.execute(INGEST_JOBS_TABLE_SQL)
    connection.execute(
        """
        insert into ingest_jobs (
          id,
          job_type,
          target_id,
          status,
          idempotency_key,
          attempts,
          last_error,
          created_at,
          updated_at,
          completed_at
        )
        select
          id,
          job_type,
          target_id,
          status,
          idempotency_key,
          attempts,
          last_error,
          created_at,
          updated_at,
          completed_at
        from ingest_jobs_phase6
        """
    )
    connection.execute("drop table ingest_jobs_phase6")


def backfill_book_retrieval_status(connection: sqlite3.Connection) -> None:
    now = utc_timestamp()
    connection.execute(
        """
        insert into book_retrieval_status (book_id, updated_at)
        select books.id, ?
        from books
        where not exists (
          select 1
          from book_retrieval_status
          where book_retrieval_status.book_id = books.id
        )
        """,
        (now,),
    )


def backfill_retrieval_run_source_books(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        select id, source_set_id, created_at, metadata_json
        from retrieval_runs
        order by created_at, id
        """
    ).fetchall()
    for row in rows:
        source_book_ids = metadata_source_book_ids(row["metadata_json"])
        for book_id in source_book_ids:
            book = connection.execute(
                "select title from books where id = ?",
                (book_id,),
            ).fetchone()
            if book is None:
                continue
            connection.execute(
                """
                insert into retrieval_run_source_books (
                  retrieval_run_id,
                  source_set_id,
                  book_id,
                  book_title_snapshot,
                  captured_at
                )
                values (?, ?, ?, ?, ?)
                on conflict(retrieval_run_id, book_id) do nothing
                """,
                (
                    row["id"],
                    row["source_set_id"],
                    book_id,
                    book["title"],
                    row["created_at"],
                ),
            )


def metadata_source_book_ids(metadata_json: str) -> tuple[str, ...]:
    try:
        metadata = json.loads(metadata_json or "{}")
    except json.JSONDecodeError:
        return ()
    source_book_ids = metadata.get("source_book_ids")
    if not isinstance(source_book_ids, list):
        return ()
    return tuple(book_id for book_id in source_book_ids if isinstance(book_id, str))


def rebuild_model_runs_if_needed(connection: sqlite3.Connection) -> None:
    if "'local'" in table_sql(connection, "model_runs"):
        return

    connection.execute("drop index if exists ix_model_runs_thread_status")
    connection.execute("drop index if exists ix_model_runs_user_message")
    connection.execute("drop index if exists ix_model_runs_retry_of")
    connection.execute("drop index if exists ux_model_runs_one_active_retry")
    connection.execute("alter table model_runs rename to model_runs_phase6")
    connection.execute(MODEL_RUNS_TABLE_SQL)
    connection.execute(
        """
        insert into model_runs (
          id,
          thread_id,
          user_message_id,
          assistant_message_id,
          retrieval_run_id,
          retry_of_model_run_id,
          provider,
          model,
          status,
          idempotency_key,
          provider_response_id,
          error_code,
          error_message,
          input_tokens,
          output_tokens,
          created_at,
          updated_at,
          completed_at,
          metadata_json
        )
        select
          id,
          thread_id,
          user_message_id,
          assistant_message_id,
          retrieval_run_id,
          retry_of_model_run_id,
          provider,
          model,
          status,
          idempotency_key,
          provider_response_id,
          error_code,
          error_message,
          input_tokens,
          output_tokens,
          created_at,
          updated_at,
          completed_at,
          metadata_json
        from model_runs_phase6
        """
    )
    connection.execute("drop table model_runs_phase6")


def rebuild_retrieval_hits_if_needed(connection: sqlite3.Connection) -> None:
    if "id" in column_names(connection, "retrieval_hits"):
        return

    connection.execute("drop index if exists ix_retrieval_hits_run_rank")
    connection.execute("alter table retrieval_hits rename to retrieval_hits_phase6")
    connection.execute(RETRIEVAL_HITS_TABLE_SQL)
    connection.execute(
        """
        insert into retrieval_hits (
          id,
          retrieval_run_id,
          page_id,
          source_object_id,
          score,
          rank,
          snippet,
          object_type_snapshot,
          title_snapshot,
          heading_path_snapshot_json,
          confidence_snapshot,
          rank_reasons_json,
          text_snapshot_sha256,
          metadata_json
        )
        select
          'legacy:' || retrieval_run_id || ':' || page_id,
          retrieval_run_id,
          page_id,
          null,
          score,
          rank,
          snippet,
          'page_fallback',
          null,
          '[]',
          null,
          '[]',
          null,
          '{}'
        from retrieval_hits_phase6
        """
    )
    connection.execute("drop table retrieval_hits_phase6")


def rebuild_familiar_research_runs_if_needed(connection: sqlite3.Connection) -> None:
    if "deciding" in table_sql(connection, "familiar_research_runs"):
        return

    drop_familiar_research_indexes(connection)
    connection.execute(
        "alter table familiar_research_runs rename to familiar_research_runs_before_0008"
    )
    connection.execute(FAMILIAR_RESEARCH_RUNS_TABLE_SQL)
    connection.execute(
        """
        insert into familiar_research_runs (
          id,
          model_run_id,
          thread_id,
          user_message_id,
          source_set_id,
          raw_query,
          resolved_query,
          intent,
          status,
          max_tool_rounds,
          tool_rounds_used,
          evidence_status,
          final_retrieval_run_id,
          metadata_json,
          created_at,
          updated_at,
          completed_at
        )
        select
          id,
          model_run_id,
          thread_id,
          user_message_id,
          source_set_id,
          raw_query,
          resolved_query,
          intent,
          status,
          max_tool_rounds,
          tool_rounds_used,
          evidence_status,
          final_retrieval_run_id,
          metadata_json,
          created_at,
          updated_at,
          completed_at
        from familiar_research_runs_before_0008
        """
    )
    connection.execute("drop table familiar_research_runs_before_0008")


def rebuild_familiar_tool_calls_if_needed(connection: sqlite3.Connection) -> None:
    if "research_plan_id" in column_names(connection, "familiar_tool_calls"):
        return

    drop_familiar_research_indexes(connection)
    connection.execute(
        "alter table familiar_tool_calls rename to familiar_tool_calls_before_0008"
    )
    connection.execute(FAMILIAR_TOOL_CALLS_TABLE_SQL)
    connection.execute(
        """
        insert into familiar_tool_calls (
          id,
          research_run_id,
          step_number,
          call_index,
          provider_call_id,
          tool_name,
          arguments_json,
          argument_hash,
          status,
          retrieval_run_id,
          output_summary_json,
          error_code,
          error_message,
          created_at,
          updated_at,
          completed_at
        )
        select
          id,
          research_run_id,
          step_number,
          call_index,
          provider_call_id,
          tool_name,
          arguments_json,
          argument_hash,
          status,
          retrieval_run_id,
          output_summary_json,
          error_code,
          error_message,
          created_at,
          updated_at,
          completed_at
        from familiar_tool_calls_before_0008
        """
    )
    connection.execute("drop table familiar_tool_calls_before_0008")


def rebuild_familiar_evidence_judgments_if_needed(
    connection: sqlite3.Connection,
) -> None:
    if "research_plan_id" in column_names(connection, "familiar_evidence_judgments"):
        return

    drop_familiar_research_indexes(connection)
    connection.execute(
        """
        alter table familiar_evidence_judgments
        rename to familiar_evidence_judgments_before_0008
        """
    )
    connection.execute(FAMILIAR_EVIDENCE_JUDGMENTS_TABLE_SQL)
    connection.execute(
        """
        insert into familiar_evidence_judgments (
          id,
          research_run_id,
          retrieval_run_id,
          retrieval_hit_id,
          source_object_id,
          book_id,
          printed_page_label,
          requirement_type,
          status,
          reason_code,
          reasons_json,
          created_at
        )
        select
          id,
          research_run_id,
          retrieval_run_id,
          retrieval_hit_id,
          source_object_id,
          book_id,
          printed_page_label,
          requirement_type,
          status,
          reason_code,
          reasons_json,
          created_at
        from familiar_evidence_judgments_before_0008
        """
    )
    connection.execute("drop table familiar_evidence_judgments_before_0008")


def drop_familiar_research_indexes(connection: sqlite3.Connection) -> None:
    for index_name in (
        "ix_familiar_research_runs_model_run",
        "ix_familiar_research_runs_thread",
        "ux_familiar_research_plans_run_revision",
        "ux_familiar_research_plans_accepted_run",
        "ix_familiar_research_plans_run_status",
        "ix_familiar_tool_calls_run",
        "ux_familiar_tool_calls_step_call",
        "ux_familiar_tool_calls_provider_call",
        "ix_familiar_tool_calls_retrieval",
        "ix_familiar_tool_calls_plan_requirement",
        "ix_familiar_evidence_judgments_run",
        "ix_familiar_evidence_judgments_hit",
        "ix_familiar_evidence_judgments_requirement",
    ):
        connection.execute(f"drop index if exists {index_name}")


def create_familiar_research_plan_indexes(connection: sqlite3.Connection) -> None:
    for statement in FAMILIAR_RESEARCH_INDEX_SQL:
        connection.execute(statement)


def create_phase_7_indexes(connection: sqlite3.Connection) -> None:
    for statement in INDEX_SQL:
        connection.execute(statement)


def rebuild_structured_evidence_tables_if_needed(
    connection: sqlite3.Connection,
) -> None:
    if (
        "glossary_entry" in table_sql(connection, "source_objects")
        and "glossary_definition" in table_sql(connection, "source_object_links")
    ):
        return

    legacy_alter_table = connection.execute("pragma legacy_alter_table").fetchone()[0]
    connection.execute("pragma legacy_alter_table = on")
    try:
        drop_structured_evidence_indexes(connection)
        connection.execute(
            "alter table source_object_links rename to source_object_links_before_0004"
        )
        connection.execute("alter table source_objects rename to source_objects_before_0004")
        connection.execute(SOURCE_OBJECTS_TABLE_SQL)
        connection.execute(
            """
            insert into source_objects (
              id,
              book_id,
              page_id,
              object_type,
              parent_object_id,
              title,
              heading_path_json,
              page_start,
              page_end,
              char_start,
              char_end,
              bbox_json,
              text,
              search_text,
              metadata_json,
              confidence,
              extraction_method,
              text_snapshot_sha256,
              created_at,
              updated_at
            )
            select
              id,
              book_id,
              page_id,
              object_type,
              parent_object_id,
              title,
              heading_path_json,
              page_start,
              page_end,
              char_start,
              char_end,
              bbox_json,
              text,
              search_text,
              metadata_json,
              confidence,
              extraction_method,
              text_snapshot_sha256,
              created_at,
              updated_at
            from source_objects_before_0004
            """
        )
        connection.execute(SOURCE_OBJECT_LINKS_TABLE_SQL)
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
              evidence_json,
              created_at
            )
            select
              id,
              from_object_id,
              to_object_id,
              to_book_id,
              to_page_id,
              link_type,
              label,
              confidence,
              evidence_json,
              created_at
            from source_object_links_before_0004
            """
        )
        connection.execute("drop table source_object_links_before_0004")
        connection.execute("drop table source_objects_before_0004")
        create_structured_evidence_indexes(connection)
    finally:
        connection.execute(f"pragma legacy_alter_table = {int(legacy_alter_table)}")


def drop_structured_evidence_indexes(connection: sqlite3.Connection) -> None:
    for index_name in (
        "ix_source_objects_book_type",
        "ix_source_objects_page",
        "ix_source_objects_parent",
        "ix_source_object_links_from",
        "ix_source_object_links_to_object",
    ):
        connection.execute(f"drop index if exists {index_name}")


def create_structured_evidence_indexes(connection: sqlite3.Connection) -> None:
    for statement in STRUCTURED_EVIDENCE_INDEX_SQL:
        connection.execute(statement)


def add_extractor_version_column_if_needed(connection: sqlite3.Connection) -> None:
    if "extractor_version" in column_names(connection, "book_object_status"):
        return
    connection.execute("alter table book_object_status add column extractor_version text")


def mark_existing_extractions_stale_for_structured_evidence(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        update book_object_status
        set status = 'not_started',
            object_count = 0,
            table_count = 0,
            stat_block_count = 0,
            location_count = 0,
            text_snapshot_sha256 = null,
            extractor_version = null,
            last_error = null,
            updated_at = ?
        where status in ('extracted', 'indexed')
          and coalesce(extractor_version, '') != 'structured-evidence-v1'
        """,
        (utc_timestamp(),),
    )


SOURCE_OBJECTS_TABLE_SQL = """
create table source_objects (
  id text primary key,
  book_id text not null references books(id) on delete cascade,
  page_id text not null references pages(id) on delete cascade,
  object_type text not null,
  parent_object_id text references source_objects(id) on delete cascade,
  title text,
  heading_path_json text not null default '[]',
  page_start integer not null,
  page_end integer not null,
  char_start integer,
  char_end integer,
  bbox_json text,
  text text not null,
  search_text text not null,
  metadata_json text not null default '{}',
  confidence real not null default 0,
  extraction_method text not null,
  text_snapshot_sha256 text not null,
  created_at text not null,
  updated_at text not null,
  foreign key (page_id, book_id, page_start)
    references pages(id, book_id, page_number) on delete cascade,
  check(object_type in (
    'rule_section',
    'table',
    'table_row',
    'stat_block',
    'npc_profile',
    'monster_profile',
    'location_description',
    'encounter',
    'boxed_text',
    'map_reference',
    'image_reference',
    'index_entry',
    'glossary_entry',
    'cross_reference',
    'page_chunk'
  )),
  check(confidence >= 0 and confidence <= 1),
  check(page_start >= 1),
  check(page_end >= page_start)
)
"""


SOURCE_OBJECT_LINKS_TABLE_SQL = """
create table source_object_links (
  id text primary key,
  from_object_id text not null references source_objects(id) on delete cascade,
  to_object_id text references source_objects(id) on delete cascade,
  to_book_id text references books(id) on delete set null,
  to_page_id text references pages(id) on delete set null,
  link_type text not null,
  label text,
  confidence real not null default 0,
  evidence_json text not null default '{}',
  created_at text not null,
  check(link_type in (
    'index_entry',
    'cross_reference',
    'same_section',
    'table_row',
    'stat_profile',
    'glossary_definition',
    'map_reference',
    'image_reference',
    'entity_mention'
  )),
  check(confidence >= 0 and confidence <= 1)
)
"""


STRUCTURED_EVIDENCE_INDEX_SQL: tuple[str, ...] = (
    """
    create index if not exists ix_source_objects_book_type
    on source_objects(book_id, object_type)
    """,
    """
    create index if not exists ix_source_objects_page
    on source_objects(page_id)
    """,
    """
    create index if not exists ix_source_objects_parent
    on source_objects(parent_object_id)
    """,
    """
    create index if not exists ix_source_object_links_from
    on source_object_links(from_object_id)
    """,
    """
    create index if not exists ix_source_object_links_to_object
    on source_object_links(to_object_id)
    """,
)


INGEST_JOBS_TABLE_SQL = """
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
  check(job_type in (
    'copy_pdf',
    'import_page_text',
    'rebuild_fts',
    'scan_visual_assets',
    'render_page',
    'extract_source_objects',
    'rebuild_source_object_fts',
    'rebuild_source_maps',
    'rebuild_embeddings',
    'backfill_page_labels'
  )),
  check(status in ('queued', 'running', 'succeeded', 'failed'))
)
"""


MODEL_RUNS_TABLE_SQL = """
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
  check(provider in ('openai', 'fake', 'local')),
  check(status in ('queued', 'retrieving', 'calling_model', 'completed', 'failed')),
  check(status = 'queued' or user_message_id is not null)
)
"""


RETRIEVAL_HITS_TABLE_SQL = """
create table retrieval_hits (
  id text primary key,
  retrieval_run_id text not null references retrieval_runs(id) on delete cascade,
  page_id text not null references pages(id),
  source_object_id text references source_objects(id) on delete set null,
  score real not null,
  rank integer not null,
  snippet text,
  object_type_snapshot text,
  title_snapshot text,
  heading_path_snapshot_json text not null default '[]',
  confidence_snapshot real,
  rank_reasons_json text not null default '[]',
  text_snapshot_sha256 text,
  metadata_json text not null default '{}',
  check(confidence_snapshot is null or (confidence_snapshot >= 0 and confidence_snapshot <= 1))
)
"""


FAMILIAR_RESEARCH_RUNS_TABLE_SQL = """
create table familiar_research_runs (
  id text primary key,
  model_run_id text not null unique references model_runs(id) on delete cascade,
  thread_id text not null references chat_threads(id) on delete cascade,
  user_message_id text not null references chat_messages(id) on delete cascade,
  source_set_id text references source_sets(id) on delete set null,
  raw_query text not null,
  resolved_query text not null,
  intent text not null,
  status text not null,
  max_tool_rounds integer not null,
  tool_rounds_used integer not null default 0,
  evidence_status text not null,
  final_retrieval_run_id text references retrieval_runs(id) on delete set null,
  metadata_json text not null default '{}',
  created_at text not null,
  updated_at text not null,
  completed_at text,
  check(status in (
    'planning',
    'tool_calling',
    'validating',
    'deciding',
    'finalizing',
    'completed',
    'insufficient',
    'failed'
  )),
  check(evidence_status in (
    'not_evaluated',
    'sufficient',
    'partial',
    'insufficient'
  )),
  check(max_tool_rounds > 0),
  check(tool_rounds_used >= 0),
  check(tool_rounds_used <= max_tool_rounds)
)
"""


FAMILIAR_TOOL_CALLS_TABLE_SQL = """
create table familiar_tool_calls (
  id text primary key,
  research_run_id text not null references familiar_research_runs(id) on delete cascade,
  research_plan_id text references familiar_research_plans(id) on delete set null,
  requirement_id text,
  purpose text,
  step_number integer not null,
  call_index integer not null default 0,
  provider_call_id text,
  tool_name text not null,
  arguments_json text not null,
  argument_hash text not null,
  status text not null,
  retrieval_run_id text references retrieval_runs(id) on delete set null,
  output_summary_json text not null default '{}',
  error_code text,
  error_message text,
  created_at text not null,
  updated_at text not null,
  completed_at text,
  check(status in ('requested', 'running', 'succeeded', 'failed', 'rejected')),
  check(step_number >= 1),
  check(call_index >= 0),
  check(length(tool_name) > 0),
  check(length(argument_hash) > 0)
)
"""


FAMILIAR_EVIDENCE_JUDGMENTS_TABLE_SQL = """
create table familiar_evidence_judgments (
  id text primary key,
  research_run_id text not null references familiar_research_runs(id) on delete cascade,
  research_plan_id text references familiar_research_plans(id) on delete set null,
  requirement_id text,
  retrieval_run_id text references retrieval_runs(id) on delete set null,
  retrieval_hit_id text references retrieval_hits(id) on delete set null,
  source_object_id text references source_objects(id) on delete set null,
  book_id text references books(id) on delete set null,
  printed_page_label text,
  requirement_type text not null,
  status text not null,
  reason_code text not null,
  reasons_json text not null default '[]',
  subject_constraint_json text not null default '{}',
  constraint_status text,
  created_at text not null,
  check(status in ('accepted', 'rejected', 'partial')),
  check(length(requirement_type) > 0),
  check(length(reason_code) > 0)
)
"""


INDEX_SQL: tuple[str, ...] = (
    """
    create index if not exists ix_ingest_jobs_status
    on ingest_jobs(status, job_type)
    """,
    """
    create index if not exists ix_model_runs_thread_status
    on model_runs(thread_id, status, updated_at)
    """,
    """
    create index if not exists ix_model_runs_user_message
    on model_runs(user_message_id)
    """,
    """
    create index if not exists ix_model_runs_retry_of
    on model_runs(retry_of_model_run_id)
    """,
    """
    create unique index if not exists ux_model_runs_one_active_retry
    on model_runs(retry_of_model_run_id)
    where retry_of_model_run_id is not null
      and status in ('queued', 'retrieving', 'calling_model')
    """,
    """
    create unique index if not exists ux_retrieval_hits_run_source_object
    on retrieval_hits(retrieval_run_id, source_object_id)
    where source_object_id is not null
    """,
    """
    create unique index if not exists ux_retrieval_hits_run_page_fallback
    on retrieval_hits(retrieval_run_id, page_id)
    where source_object_id is null
    """,
    """
    create unique index if not exists ux_retrieval_hits_run_rank
    on retrieval_hits(retrieval_run_id, rank)
    """,
)


FAMILIAR_RESEARCH_INDEX_SQL: tuple[str, ...] = (
    """
    create index if not exists ix_familiar_research_runs_model_run
    on familiar_research_runs(model_run_id)
    """,
    """
    create index if not exists ix_familiar_research_runs_thread
    on familiar_research_runs(thread_id, created_at)
    """,
    """
    create unique index if not exists ux_familiar_research_plans_run_revision
    on familiar_research_plans(research_run_id, revision)
    """,
    """
    create unique index if not exists ux_familiar_research_plans_accepted_run
    on familiar_research_plans(research_run_id)
    where status = 'accepted'
    """,
    """
    create index if not exists ix_familiar_research_plans_run_status
    on familiar_research_plans(research_run_id, status)
    """,
    """
    create index if not exists ix_familiar_tool_calls_run
    on familiar_tool_calls(research_run_id, step_number)
    """,
    """
    create unique index if not exists ux_familiar_tool_calls_step_call
    on familiar_tool_calls(research_run_id, step_number, call_index)
    """,
    """
    create unique index if not exists ux_familiar_tool_calls_provider_call
    on familiar_tool_calls(research_run_id, provider_call_id)
    where provider_call_id is not null
    """,
    """
    create index if not exists ix_familiar_tool_calls_retrieval
    on familiar_tool_calls(retrieval_run_id)
    """,
    """
    create index if not exists ix_familiar_tool_calls_plan_requirement
    on familiar_tool_calls(research_plan_id, requirement_id, step_number)
    """,
    """
    create index if not exists ix_familiar_evidence_judgments_run
    on familiar_evidence_judgments(research_run_id, status)
    """,
    """
    create index if not exists ix_familiar_evidence_judgments_hit
    on familiar_evidence_judgments(retrieval_hit_id)
    """,
    """
    create index if not exists ix_familiar_evidence_judgments_requirement
    on familiar_evidence_judgments(research_plan_id, requirement_id, status)
    """,
)
