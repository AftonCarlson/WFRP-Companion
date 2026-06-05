from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field

from wfrp_companion.assistant import chat_store
from wfrp_companion.assistant.evidence import parse_heading_path
from wfrp_companion.assistant.query_planner import add_candidate
from wfrp_companion.assistant.query_planner import meaningful_tokens
from wfrp_companion.assistant.query_planner import terms_are_close
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.library import source_sets


SOURCE_MAP_PAGE_CHAR_LIMIT = 180_000
SOURCE_MAP_ALIAS_LIMIT = 12
SOURCE_MAP_CHAPTER_LIMIT = 10


@dataclass(frozen=True)
class SourceMapEntry:
    book_id: str
    title: str
    category: str
    summary: str
    aliases: tuple[str, ...] = field(default_factory=tuple)
    best_source_for: tuple[str, ...] = field(default_factory=tuple)
    chapters: tuple[str, ...] = field(default_factory=tuple)

@dataclass(frozen=True)
class SourceScope:
    source_set_id: str | None
    book_ids: tuple[str, ...]

def current_thread_source_scope(config: AppConfig, thread_id: str) -> SourceScope:
    with initialize_database(config.db_path) as connection:
        thread = connection.execute(
            "select active_source_set_id from chat_threads where id = ?",
            (thread_id,),
        ).fetchone()
        if thread is None:
            raise chat_store.ChatThreadNotFoundError(f"Chat thread not found: {thread_id}")
        source_set_id = thread["active_source_set_id"]
        if source_set_id is None:
            source_set_id = source_sets.get_active_source_set_id_from_connection(
                connection
            )
        if source_set_id is None:
            return SourceScope(source_set_id=None, book_ids=())
        source_sets.require_source_set(connection, source_set_id)
        return SourceScope(
            source_set_id=source_set_id,
            book_ids=chat_store.enabled_book_ids_from_connection(
                connection,
                source_set_id,
            ),
        )

def build_enabled_source_map(
    config: AppConfig,
    source_book_ids: Sequence[str],
    *,
    query_terms: tuple[str, ...],
) -> tuple[SourceMapEntry, ...]:
    if not source_book_ids:
        return ()
    with initialize_database(config.db_path) as connection:
        return build_enabled_source_map_from_connection(
            connection,
            source_book_ids=tuple(source_book_ids),
            query_terms=query_terms,
        )

def build_enabled_source_map_from_connection(
    connection: sqlite3.Connection,
    *,
    source_book_ids: tuple[str, ...],
    query_terms: tuple[str, ...],
) -> tuple[SourceMapEntry, ...]:
    placeholders = ",".join("?" for _ in source_book_ids)
    book_rows = connection.execute(
        f"""
        select id, title, category, metadata_json
        from books
        where id in ({placeholders})
        order by id
        """,
        source_book_ids,
    ).fetchall()
    return tuple(
        source_map_entry_from_book_row(
            connection,
            row,
            query_terms=query_terms,
        )
        for row in book_rows
    )

def source_map_entry_from_book_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    query_terms: tuple[str, ...],
) -> SourceMapEntry:
    chapters = source_map_chapters(connection, row["id"])
    aliases = source_map_aliases(
        connection,
        row["id"],
        title=row["title"],
        category=row["category"],
        chapters=chapters,
        query_terms=query_terms,
    )
    matched = tuple(alias for alias in aliases if alias not in meaningful_tokens(row["title"]))
    summary_parts = [f"{row['title']} is in {row['category']}."]
    if matched:
        summary_parts.append(f"Matched routing terms: {', '.join(matched[:6])}.")
    if chapters:
        summary_parts.append(f"Indexed sections include {', '.join(chapters[:3])}.")
    return SourceMapEntry(
        book_id=row["id"],
        title=row["title"],
        category=row["category"],
        summary=" ".join(summary_parts),
        aliases=aliases,
        best_source_for=infer_best_source_for(row["category"], aliases, query_terms),
        chapters=chapters,
    )

def source_map_chapters(
    connection: sqlite3.Connection,
    book_id: str,
) -> tuple[str, ...]:
    rows = connection.execute(
        """
        select title, heading_path_json
        from source_objects
        where book_id = ?
          and title is not null
        order by page_start, id
        limit 80
        """,
        (book_id,),
    ).fetchall()
    chapters: list[str] = []
    for row in rows:
        heading_path = parse_heading_path(row["heading_path_json"])
        for value in (*heading_path, row["title"]):
            if value and value not in chapters:
                chapters.append(value)
            if len(chapters) >= SOURCE_MAP_CHAPTER_LIMIT:
                return tuple(chapters)
    return tuple(chapters)

def source_map_aliases(
    connection: sqlite3.Connection,
    book_id: str,
    *,
    title: str,
    category: str,
    chapters: tuple[str, ...],
    query_terms: tuple[str, ...],
) -> tuple[str, ...]:
    aliases: list[str] = []
    for value in (title, category, *chapters):
        for token in meaningful_tokens(value):
            add_candidate(aliases, token)

    vocabulary = source_vocabulary(connection, book_id)
    for query_term in query_terms:
        if len(query_term) < 5:
            continue
        for source_term in vocabulary:
            if source_term == query_term:
                add_candidate(aliases, source_term)
            elif terms_are_close(query_term, source_term):
                add_candidate(aliases, source_term)
            if len(aliases) >= SOURCE_MAP_ALIAS_LIMIT:
                return tuple(aliases)
    return tuple(aliases[:SOURCE_MAP_ALIAS_LIMIT])

def source_vocabulary(connection: sqlite3.Connection, book_id: str) -> tuple[str, ...]:
    text_parts: list[str] = []
    total_chars = 0
    for table_name, column_name in (
        ("source_objects", "search_text"),
        ("page_search", "text"),
    ):
        rows = connection.execute(
            f"""
            select {column_name} as text
            from {table_name}
            where book_id = ?
            order by rowid
            """,
            (book_id,),
        ).fetchall()
        for row in rows:
            if total_chars >= SOURCE_MAP_PAGE_CHAR_LIMIT:
                break
            text = row["text"] or ""
            text_parts.append(text[: SOURCE_MAP_PAGE_CHAR_LIMIT - total_chars])
            total_chars += len(text_parts[-1])
        if total_chars >= SOURCE_MAP_PAGE_CHAR_LIMIT:
            break
    vocabulary: list[str] = []
    for token in meaningful_tokens(" ".join(text_parts)):
        if len(token) >= 3 and token not in vocabulary:
            vocabulary.append(token)
    return tuple(vocabulary)

def infer_best_source_for(
    category: str,
    aliases: tuple[str, ...],
    query_terms: tuple[str, ...],
) -> tuple[str, ...]:
    values: list[str] = []
    lowered_category = category.casefold()
    if "adventure" in lowered_category:
        values.append("adventure_scene_lookup")
    if "world" in lowered_category or "faction" in lowered_category:
        values.append("lore_lookup")
    if "rules" in lowered_category or "core" in lowered_category:
        values.append("rules_lookup")
    if set(aliases).intersection(query_terms):
        values.append("source_navigation")
    return tuple(dict.fromkeys(values))
