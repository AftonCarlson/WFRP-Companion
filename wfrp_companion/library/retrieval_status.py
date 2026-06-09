from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.library import source_sets
from wfrp_companion.source_objects.embeddings import (
    embeddings_enabled,
    source_object_embeddings_current,
)


STRUCTURED_EVIDENCE_TYPES = {
    "stat_block",
    "monster_profile",
    "npc_profile",
    "table",
    "table_row",
}


@dataclass(frozen=True)
class RetrievalStatus:
    books_total: int
    books_enabled: int
    page_text_indexed: int
    source_objects_indexed: int
    table_or_stat_indexed: int
    vectorized_current: int
    vectorized_enabled: int
    embedding_provider: str
    embedding_dimensions: int | None
    vector_status: str


def get_retrieval_status(config: AppConfig) -> RetrievalStatus:
    with initialize_database(config.db_path) as connection:
        book_ids = copied_book_ids(connection)
        enabled_book_ids = active_enabled_book_ids(connection)
        source_object_book_ids = indexed_source_object_book_ids(connection)
        structured_book_ids = structured_evidence_book_ids(connection)
        vectorized_book_ids = current_vectorized_book_ids(
            connection,
            config=config,
            book_ids=source_object_book_ids,
        )
        vector_state = aggregate_vector_status(
            connection,
            config=config,
            source_object_book_ids=source_object_book_ids,
            vectorized_book_ids=vectorized_book_ids,
        )
        return RetrievalStatus(
            books_total=len(book_ids),
            books_enabled=len(enabled_book_ids),
            page_text_indexed=page_text_indexed_count(connection),
            source_objects_indexed=len(source_object_book_ids),
            table_or_stat_indexed=len(structured_book_ids),
            vectorized_current=len(vectorized_book_ids),
            vectorized_enabled=len(vectorized_book_ids.intersection(enabled_book_ids)),
            embedding_provider=config.embedding_provider,
            embedding_dimensions=(
                config.embedding_dimensions if embeddings_enabled(config) else None
            ),
            vector_status=vector_state,
        )


def copied_book_ids(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        """
        select id
        from books
        where copy_status = 'copied'
        order by id
        """
    ).fetchall()
    return {row["id"] for row in rows}


def active_enabled_book_ids(connection: sqlite3.Connection) -> set[str]:
    source_set_id = source_sets.get_active_source_set_id_from_connection(connection)
    if source_set_id is None:
        return set()
    rows = connection.execute(
        """
        select book_id
        from source_set_books
        where source_set_id = ?
          and enabled = 1
        order by book_id
        """,
        (source_set_id,),
    ).fetchall()
    return {row["book_id"] for row in rows}


def page_text_indexed_count(connection: sqlite3.Connection) -> int:
    return int(
        connection.execute(
            """
            select count(*)
            from books
            where copy_status = 'copied'
              and text_status = 'imported'
              and search_status = 'indexed'
            """
        ).fetchone()[0]
    )


def indexed_source_object_book_ids(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        """
        select book_id
        from book_object_status
        where status = 'indexed'
          and object_count > 0
        order by book_id
        """
    ).fetchall()
    return {row["book_id"] for row in rows}


def structured_evidence_book_ids(connection: sqlite3.Connection) -> set[str]:
    placeholders = ",".join("?" for _ in STRUCTURED_EVIDENCE_TYPES)
    rows = connection.execute(
        f"""
        select distinct book_id
        from source_objects
        where object_type in ({placeholders})
        order by book_id
        """,
        tuple(sorted(STRUCTURED_EVIDENCE_TYPES)),
    ).fetchall()
    return {row["book_id"] for row in rows}


def current_vectorized_book_ids(
    connection: sqlite3.Connection,
    *,
    config: AppConfig,
    book_ids: set[str],
) -> set[str]:
    if not embeddings_enabled(config):
        return set()
    return {
        book_id
        for book_id in book_ids
        if source_object_embeddings_current(connection, book_id, config=config)
    }


def aggregate_vector_status(
    connection: sqlite3.Connection,
    *,
    config: AppConfig,
    source_object_book_ids: set[str],
    vectorized_book_ids: set[str],
) -> str:
    if not embeddings_enabled(config):
        return "disabled"
    if not source_object_book_ids:
        return "missing"
    rows = connection.execute(
        """
        select vector_status
        from book_retrieval_status
        where book_id in ({})
        """.format(",".join("?" for _ in source_object_book_ids)),
        tuple(sorted(source_object_book_ids)),
    ).fetchall()
    statuses = {row["vector_status"] for row in rows}
    if "failed" in statuses:
        return "error"
    if "needs_refresh" in statuses:
        return "stale"
    if vectorized_book_ids == source_object_book_ids:
        return "ready"
    return "missing"
