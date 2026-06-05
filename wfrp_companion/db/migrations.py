from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from wfrp_companion.db.connection import open_connection


MIGRATION_DIR = Path(__file__).with_name("migration_files")
PHASE_7_MIGRATION_ID = "0001_phase_7_source_objects"
MIGRATION_IDS: tuple[str, ...] = (PHASE_7_MIGRATION_ID,)


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
    if migration_id != PHASE_7_MIGRATION_ID:
        raise ValueError(f"Unknown migration: {migration_id}")

    preflight_phase_7_source_objects(connection)
    foreign_keys_enabled = connection.execute("pragma foreign_keys").fetchone()[0]
    try:
        connection.execute("pragma foreign_keys = off")
        connection.execute("begin")
        ensure_schema_migrations(connection)
        apply_phase_7_source_objects(connection)
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
        "retrieval_hits",
        "model_runs",
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


def rebuild_ingest_jobs_if_needed(connection: sqlite3.Connection) -> None:
    if "extract_source_objects" in table_sql(connection, "ingest_jobs"):
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


def create_phase_7_indexes(connection: sqlite3.Connection) -> None:
    for statement in INDEX_SQL:
        connection.execute(statement)


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
    'rebuild_source_object_fts'
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
