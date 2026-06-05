from __future__ import annotations

import re
from dataclasses import dataclass

from wfrp_companion.assistant import chat_store
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.search.fts import search_exact


STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "can",
    "do",
    "does",
    "for",
    "happen",
    "happens",
    "how",
    "i",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "when",
    "where",
    "with",
}


@dataclass(frozen=True)
class RetrievedHit:
    book_id: str
    title: str
    category: str
    page_id: str
    page_number: int
    snippet: str
    score: float
    rank: int
    context_text: str


@dataclass(frozen=True)
class RetrievalContext:
    query: str
    candidates: tuple[str, ...]
    hits: tuple[RetrievedHit, ...]


def query_candidates(query: str) -> tuple[str, ...]:
    tokens = meaningful_tokens(query)
    candidates: list[str] = []
    add_candidate(candidates, " ".join(tokens))
    for size in (3, 2):
        for index in range(0, max(0, len(tokens) - size + 1)):
            add_candidate(candidates, " ".join(tokens[index : index + size]))
    for token in tokens:
        add_candidate(candidates, token)
    return tuple(candidates)


def meaningful_tokens(query: str) -> list[str]:
    tokens = [token.lower() for token in re.findall(r"(?u)\b[\w'-]+\b", query)]
    return [token for token in tokens if token and token not in STOP_WORDS]


def add_candidate(candidates: list[str], candidate: str) -> None:
    cleaned = " ".join(candidate.split())
    if cleaned and cleaned not in candidates:
        candidates.append(cleaned)


def retrieve_context(
    config: AppConfig,
    thread_id: str,
    query: str,
    *,
    hit_limit: int,
    total_char_limit: int,
    window_chars: int,
) -> RetrievalContext:
    source_book_ids = thread_source_book_ids(config, thread_id)
    candidates = query_candidates(query)
    hits: list[RetrievedHit] = []
    seen_page_ids: set[str] = set()
    remaining_chars = total_char_limit
    terms = meaningful_tokens(query)

    for candidate in candidates:
        if len(hits) >= hit_limit or remaining_chars <= 0:
            break
        for hit in search_exact(
            config,
            candidate,
            book_ids=source_book_ids,
            limit=hit_limit,
        ):
            if hit.page_id in seen_page_ids:
                continue
            page_text = load_page_text(config, hit.page_id)
            context_text = context_window(page_text, terms=terms, max_chars=window_chars)
            if len(context_text) > remaining_chars:
                context_text = context_text[:remaining_chars].rstrip()
            if not context_text:
                continue
            seen_page_ids.add(hit.page_id)
            hits.append(
                RetrievedHit(
                    book_id=hit.book_id,
                    title=hit.title,
                    category=hit.category,
                    page_id=hit.page_id,
                    page_number=hit.page_number,
                    snippet=hit.snippet,
                    score=hit.score,
                    rank=len(hits) + 1,
                    context_text=context_text,
                )
            )
            remaining_chars -= len(context_text)
            if len(hits) >= hit_limit or remaining_chars <= 0:
                break

    return RetrievalContext(query=query, candidates=candidates, hits=tuple(hits))


def thread_source_book_ids(config: AppConfig, thread_id: str) -> tuple[str, ...]:
    with initialize_database(config.db_path) as connection:
        row = connection.execute(
            "select 1 from chat_threads where id = ?",
            (thread_id,),
        ).fetchone()
        if row is None:
            raise chat_store.ChatThreadNotFoundError(f"Chat thread not found: {thread_id}")
        rows = connection.execute(
            """
            select book_id
            from chat_thread_source_books
            where thread_id = ?
            order by book_id
            """,
            (thread_id,),
        ).fetchall()
    return tuple(row["book_id"] for row in rows)


def load_page_text(config: AppConfig, page_id: str) -> str:
    with initialize_database(config.db_path) as connection:
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
