from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database


ACTIVE_SOURCE_SET_SETTING_KEY = "active_source_set_id"
RULES_CORE_SOURCE_SET_ID = "rules-core"
RULES_CORE_SOURCE_SET_NAME = "Rules/Core"
RULES_CORE_SOURCE_SET_DESCRIPTION = (
    "Core rules, GM essentials, and rules/mechanics toolkit books."
)
RULES_CORE_ENABLED_CATEGORIES = (
    "Core Book & GM Essentials",
    "Rules and Mechanics Toolkits",
)


@dataclass(frozen=True)
class SourceSet:
    id: str
    name: str
    description: str | None
    is_builtin: bool


@dataclass(frozen=True)
class SourceSetBook:
    source_set_id: str
    book_id: str
    title: str
    category: str
    enabled: bool
    search_ready: bool


@dataclass(frozen=True)
class SourceSetSyncSummary:
    source_sets_created: int
    book_rows_inserted: int
    active_source_set_id: str


class SourceSetError(Exception):
    pass


class SourceSetNotFoundError(SourceSetError):
    pass


class BookNotFoundError(SourceSetError):
    pass


class ActiveSourceSetMissingError(SourceSetError):
    pass


class SourceSetConflictError(SourceSetError):
    pass


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def ensure_builtin_source_sets(config: AppConfig) -> SourceSetSyncSummary:
    with initialize_database(config.db_path) as connection:
        now = utc_timestamp()
        with connection:
            ensure_no_rules_core_conflicts(connection)
            source_set_created = upsert_rules_core_source_set(connection, now=now)
            book_rows_inserted = insert_missing_source_set_books(
                connection,
                source_set_id=RULES_CORE_SOURCE_SET_ID,
                now=now,
            )
            active_source_set_id = get_active_source_set_id_from_connection(connection)
            if active_source_set_id is None:
                write_active_source_set_id(
                    connection,
                    source_set_id=RULES_CORE_SOURCE_SET_ID,
                    now=now,
                )
                active_source_set_id = RULES_CORE_SOURCE_SET_ID

    return SourceSetSyncSummary(
        source_sets_created=1 if source_set_created else 0,
        book_rows_inserted=book_rows_inserted,
        active_source_set_id=active_source_set_id,
    )


def ensure_no_rules_core_conflicts(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        select id, name, is_builtin
        from source_sets
        where id = ?
           or name = ?
        order by id
        """,
        (RULES_CORE_SOURCE_SET_ID, RULES_CORE_SOURCE_SET_NAME),
    ).fetchall()
    for row in rows:
        if row["id"] == RULES_CORE_SOURCE_SET_ID:
            if row["is_builtin"] != 1:
                raise SourceSetConflictError(
                    "rules-core already exists as user-owned source set"
                )
            if row["name"] != RULES_CORE_SOURCE_SET_NAME:
                raise SourceSetConflictError(
                    f"rules-core already exists with name {row['name']!r}"
                )
        elif row["name"] == RULES_CORE_SOURCE_SET_NAME:
            raise SourceSetConflictError(
                f"Rules/Core already exists as source set {row['id']}"
            )


def upsert_rules_core_source_set(connection: sqlite3.Connection, *, now: str) -> bool:
    existed = source_set_exists(connection, RULES_CORE_SOURCE_SET_ID)
    connection.execute(
        """
        insert into source_sets (
          id,
          name,
          description,
          is_builtin,
          created_at,
          updated_at
        )
        values (?, ?, ?, 1, ?, ?)
        on conflict(id) do update set
          name = excluded.name,
          description = excluded.description,
          is_builtin = 1,
          updated_at = excluded.updated_at
        """,
        (
            RULES_CORE_SOURCE_SET_ID,
            RULES_CORE_SOURCE_SET_NAME,
            RULES_CORE_SOURCE_SET_DESCRIPTION,
            now,
            now,
        ),
    )
    return not existed


def insert_missing_source_set_books(
    connection: sqlite3.Connection,
    *,
    source_set_id: str,
    now: str,
) -> int:
    rows = connection.execute(
        """
        select books.id, books.category
        from books
        where not exists (
          select 1
          from source_set_books
          where source_set_books.source_set_id = ?
            and source_set_books.book_id = books.id
        )
        order by books.id
        """,
        (source_set_id,),
    ).fetchall()
    for row in rows:
        connection.execute(
            """
            insert into source_set_books (
              source_set_id,
              book_id,
              enabled,
              updated_at
            )
            values (?, ?, ?, ?)
            """,
            (
                source_set_id,
                row["id"],
                1 if default_enabled_for_source_set(source_set_id, row["category"]) else 0,
                now,
            ),
        )
    return len(rows)


def default_enabled_for_source_set(source_set_id: str, category: str) -> bool:
    if source_set_id != RULES_CORE_SOURCE_SET_ID:
        return False
    return category in RULES_CORE_ENABLED_CATEGORIES


def list_source_sets(config: AppConfig) -> tuple[SourceSet, ...]:
    with initialize_database(config.db_path) as connection:
        rows = connection.execute(
            """
            select id, name, description, is_builtin
            from source_sets
            order by name, id
            """
        ).fetchall()
    return tuple(
        SourceSet(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            is_builtin=bool(row["is_builtin"]),
        )
        for row in rows
    )


def list_source_set_books(
    config: AppConfig,
    source_set_id: str,
) -> tuple[SourceSetBook, ...]:
    with initialize_database(config.db_path) as connection:
        require_source_set(connection, source_set_id)
        rows = connection.execute(
            """
            select
              source_set_books.source_set_id,
              books.id as book_id,
              books.title,
              books.category,
              source_set_books.enabled,
              book_readiness.search_ready
            from source_set_books
            join books on books.id = source_set_books.book_id
            left join book_readiness on book_readiness.book_id = books.id
            where source_set_books.source_set_id = ?
            order by books.category, books.title, books.id
            """,
            (source_set_id,),
        ).fetchall()
    return tuple(
        SourceSetBook(
            source_set_id=row["source_set_id"],
            book_id=row["book_id"],
            title=row["title"],
            category=row["category"],
            enabled=bool(row["enabled"]),
            search_ready=bool(row["search_ready"]),
        )
        for row in rows
    )


def get_active_source_set_id(config: AppConfig) -> str | None:
    with initialize_database(config.db_path) as connection:
        return get_active_source_set_id_from_connection(connection)


def get_active_source_set_id_from_connection(
    connection: sqlite3.Connection,
) -> str | None:
    row = connection.execute(
        """
        select value_json
        from app_settings
        where key = ?
        """,
        (ACTIVE_SOURCE_SET_SETTING_KEY,),
    ).fetchone()
    if row is None:
        return None
    try:
        value = json.loads(row["value_json"])
    except json.JSONDecodeError:
        return None
    if not isinstance(value, str):
        return None
    if not source_set_exists(connection, value):
        return None
    return value


def set_active_source_set(config: AppConfig, source_set_id: str) -> None:
    with initialize_database(config.db_path) as connection:
        require_source_set(connection, source_set_id)
        with connection:
            write_active_source_set_id(
                connection,
                source_set_id=source_set_id,
                now=utc_timestamp(),
            )


def write_active_source_set_id(
    connection: sqlite3.Connection,
    *,
    source_set_id: str,
    now: str,
) -> None:
    connection.execute(
        """
        insert into app_settings (key, value_json, updated_at)
        values (?, ?, ?)
        on conflict(key) do update set
          value_json = excluded.value_json,
          updated_at = excluded.updated_at
        """,
        (ACTIVE_SOURCE_SET_SETTING_KEY, json.dumps(source_set_id), now),
    )


def enabled_book_ids(
    config: AppConfig,
    source_set_id: str | None = None,
) -> tuple[str, ...]:
    with initialize_database(config.db_path) as connection:
        selected_source_set_id = source_set_id
        if selected_source_set_id is None:
            selected_source_set_id = get_active_source_set_id_from_connection(connection)
            if selected_source_set_id is None:
                raise ActiveSourceSetMissingError(
                    "No active source set. Run tools/source_sets.py init or use --all-books."
                )
        else:
            require_source_set(connection, selected_source_set_id)

        rows = connection.execute(
            """
            select source_set_books.book_id
            from source_set_books
            where source_set_books.source_set_id = ?
              and source_set_books.enabled = 1
            order by source_set_books.book_id
            """,
            (selected_source_set_id,),
        ).fetchall()
    return tuple(row["book_id"] for row in rows)


def set_book_enabled(
    config: AppConfig,
    source_set_id: str,
    book_id: str,
    enabled: bool,
) -> None:
    with initialize_database(config.db_path) as connection:
        require_source_set(connection, source_set_id)
        book = require_book(connection, book_id)
        now = utc_timestamp()
        with connection:
            ensure_source_set_book_row(
                connection,
                source_set_id=source_set_id,
                book_id=book_id,
                category=book["category"],
                now=now,
            )
            connection.execute(
                """
                update source_set_books
                set enabled = ?,
                    updated_at = ?
                where source_set_id = ?
                  and book_id = ?
                """,
                (1 if enabled else 0, now, source_set_id, book_id),
            )


def ensure_source_set_book_row(
    connection: sqlite3.Connection,
    *,
    source_set_id: str,
    book_id: str,
    category: str,
    now: str,
) -> None:
    connection.execute(
        """
        insert into source_set_books (
          source_set_id,
          book_id,
          enabled,
          updated_at
        )
        values (?, ?, ?, ?)
        on conflict(source_set_id, book_id) do nothing
        """,
        (
            source_set_id,
            book_id,
            1 if default_enabled_for_source_set(source_set_id, category) else 0,
            now,
        ),
    )


def source_set_exists(connection: sqlite3.Connection, source_set_id: str) -> bool:
    return (
        connection.execute(
            """
            select 1
            from source_sets
            where id = ?
            """,
            (source_set_id,),
        ).fetchone()
        is not None
    )


def require_source_set(
    connection: sqlite3.Connection,
    source_set_id: str,
) -> None:
    if not source_set_exists(connection, source_set_id):
        raise SourceSetNotFoundError(f"Source set not found: {source_set_id}")


def require_book(connection: sqlite3.Connection, book_id: str) -> sqlite3.Row:
    row = connection.execute(
        """
        select id, category
        from books
        where id = ?
        """,
        (book_id,),
    ).fetchone()
    if row is None:
        raise BookNotFoundError(f"Book not found: {book_id}")
    return row
