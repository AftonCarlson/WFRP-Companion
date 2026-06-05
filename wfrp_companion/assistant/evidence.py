from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database

if TYPE_CHECKING:
    from wfrp_companion.assistant.source_map import SourceMapEntry


@dataclass(frozen=True)
class RetrievedHit:
    book_id: str
    title: str
    category: str
    page_id: str
    page_number: int
    pdf_page_number: int
    page_label: str | None
    snippet: str
    score: float
    rank: int
    context_text: str
    source_object_id: str | None = None
    object_type: str = "page_fallback"
    object_title: str | None = None
    heading_path: tuple[str, ...] = field(default_factory=tuple)
    page_start: int | None = None
    page_end: int | None = None
    page_range_label: str | None = None
    confidence: float | None = None
    rank_reasons: tuple[str, ...] = field(default_factory=tuple)
    text_snapshot_sha256: str | None = None

@dataclass(frozen=True)
class RetrievalContext:
    query: str
    candidates: tuple[str, ...]
    hits: tuple[RetrievedHit, ...]
    source_set_id: str | None = None
    source_book_ids: tuple[str, ...] = field(default_factory=tuple)
    source_map: tuple[SourceMapEntry, ...] = field(default_factory=tuple)

@dataclass(frozen=True)
class EvidenceCandidate:
    book_id: str
    title: str
    category: str
    page_id: str
    page_number: int
    pdf_page_number: int
    page_label: str | None
    page_start: int
    page_end: int
    page_range_label: str | None
    snippet: str
    base_score: float
    context_text: str
    channel: str
    source_object_id: str | None = None
    object_type: str = "page_fallback"
    object_title: str | None = None
    heading_path: tuple[str, ...] = field(default_factory=tuple)
    confidence: float | None = None
    rank_reasons: tuple[str, ...] = field(default_factory=tuple)
    text_snapshot_sha256: str | None = None

    @property
    def dedupe_key(self) -> str:
        if self.source_object_id is not None:
            return f"source-object:{self.source_object_id}"
        return f"page:{self.page_id}"

def load_page_text(config: AppConfig, page_id: str) -> str:
    with initialize_database(config.db_path) as connection:
        return load_page_text_from_connection(connection, page_id)

def load_page_text_from_connection(
    connection: sqlite3.Connection,
    page_id: str,
) -> str:
    row = connection.execute(
        """
        select page_text.text
        from page_text
        join pages on pages.id = page_text.page_id
        join books on books.id = pages.book_id
        where page_text.page_id = ?
          and books.copy_status = 'copied'
          and books.text_status = 'imported'
          and books.search_status = 'indexed'
        """,
        (page_id,),
    ).fetchone()
    return "" if row is None else row["text"]

def context_window(text: str, *, terms: list[str], max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    lower_text = text.lower()
    match_positions = [
        lower_text.find(term.lower()) for term in terms if lower_text.find(term.lower()) >= 0
    ]
    center = min(match_positions) if match_positions else 0
    start = max(0, center - max_chars // 3)
    end = min(len(text), start + max_chars)
    return text[start:end].strip()

def load_page_range_label(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    page_start: int,
    page_end: int,
) -> str:
    rows = connection.execute(
        """
        select page_number, page_label
        from pages
        where book_id = ?
          and page_number in (?, ?)
        order by page_number
        """,
        (book_id, page_start, page_end),
    ).fetchall()
    labels_by_number = {
        int(row["page_number"]): row["page_label"] or str(row["page_number"])
        for row in rows
    }
    start_label = labels_by_number.get(page_start, str(page_start))
    end_label = labels_by_number.get(page_end, str(page_end))
    if page_start == page_end or start_label == end_label:
        return start_label
    return f"{start_label}-{end_label}"

def parse_heading_path(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return ()
    if not isinstance(decoded, list):
        return ()
    return tuple(item for item in decoded if isinstance(item, str) and item)
