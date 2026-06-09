from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from wfrp_companion.assistant import chat_store
from wfrp_companion.assistant import evidence_constraints
from wfrp_companion.assistant import retrieval
from wfrp_companion.assistant.evidence import context_window
from wfrp_companion.assistant.evidence import parse_heading_path
from wfrp_companion.assistant.evidence import RetrievedHit
from wfrp_companion.assistant.research import RetrievalDiagnostics
from wfrp_companion.assistant.source_map import SourceScope
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.library.page_labels import load_calibrated_page_labels
from wfrp_companion.library.page_labels import load_calibrated_printed_page_label
from wfrp_companion.library.page_labels import load_calibrated_printed_page_range_label
from wfrp_companion.library.page_labels import normalize_page_label


@dataclass(frozen=True)
class SearchLibraryResult:
    retrieval_run_id: str
    query: str
    source_set_id: str | None
    source_book_ids: tuple[str, ...]
    hits: tuple[RetrievedHit, ...]
    diagnostics: RetrievalDiagnostics


def search_library(
    config: AppConfig,
    *,
    thread_id: str,
    message_id: str,
    tool_call_id: str,
    attempt_number: int,
    query: str,
    intent: str,
    hit_limit: int,
    total_char_limit: int,
    window_chars: int,
    history_message_ids: Sequence[str] = (),
    history_turn_count: int = 0,
    history_strategy: str = "none",
    requirement_constraint: evidence_constraints.EvidenceConstraint | None = None,
) -> SearchLibraryResult:
    source_scope = thread_source_scope(config, thread_id)
    retrieve_kwargs: dict[str, object] = {}
    if requirement_constraint is not None:
        retrieve_kwargs["requirement_constraint"] = requirement_constraint
    context = retrieval.retrieve_context_for_source_scope(
        config,
        source_scope,
        query,
        hit_limit=hit_limit,
        total_char_limit=total_char_limit,
        window_chars=window_chars,
        **retrieve_kwargs,
    )
    diagnostics = context.diagnostics
    if diagnostics is None:
        diagnostics = retrieval.empty_diagnostics(config)

    retrieval_run_id = chat_store.record_retrieval_run(
        config,
        thread_id=thread_id,
        message_id=message_id,
        source_set_id=context.source_set_id,
        query=query,
        hits=context.hits,
        source_book_ids=context.source_book_ids,
        source_map=context.source_map,
        candidates=context.candidates,
        retrieval_query=query,
        diagnostics=diagnostics,
        tool_call_id=tool_call_id,
        attempt_number=attempt_number,
        intent=intent,
        resolved_query=query,
        tool_name="search_library",
        history_message_ids=history_message_ids,
        history_turn_count=history_turn_count,
        history_strategy=history_strategy,
    )
    return SearchLibraryResult(
        retrieval_run_id=retrieval_run_id,
        query=query,
        source_set_id=context.source_set_id,
        source_book_ids=context.source_book_ids,
        hits=context.hits,
        diagnostics=diagnostics,
    )


def open_page(
    config: AppConfig,
    *,
    thread_id: str,
    message_id: str,
    tool_call_id: str,
    attempt_number: int,
    book_id: str | None,
    book_title_hint: str | None,
    printed_page_label: str | None,
    pdf_page_number: int | None,
    subject_hint: str | None,
    intent: str,
    hit_limit: int,
    total_char_limit: int,
    window_chars: int,
) -> SearchLibraryResult:
    source_scope = thread_source_scope(config, thread_id)
    with initialize_database(config.db_path) as connection:
        resolved_book_id = resolve_book_id(
            connection,
            source_scope=source_scope,
            book_id=book_id,
            book_title_hint=book_title_hint,
        )
        page_row = None
        if resolved_book_id is not None:
            page_row = resolve_page_row(
                connection,
                book_id=resolved_book_id,
                printed_page_label=printed_page_label,
                pdf_page_number=pdf_page_number,
            )
        hits = (
            ()
            if page_row is None or hit_limit <= 0 or total_char_limit <= 0
            else (
                page_row_to_hit(
                    connection,
                    page_row,
                    rank=1,
                    terms=tool_terms(subject_hint, intent),
                    max_chars=min(total_char_limit, window_chars),
                ),
            )
        )

    diagnostics = tool_diagnostics(
        config,
        page_lookup_attempted=True,
        page_lookup_count=1 if hits else 0,
        table_stat_lookup_count=0,
        selected_count=len(hits),
        skip_reasons={} if hits else {"page_lookup": "not_found"},
    )
    query = page_lookup_query(
        book_id=resolved_book_id or book_id,
        printed_page_label=printed_page_label,
        pdf_page_number=pdf_page_number,
        subject_hint=subject_hint,
        intent=intent,
    )
    retrieval_run_id = chat_store.record_retrieval_run(
        config,
        thread_id=thread_id,
        message_id=message_id,
        source_set_id=source_scope.source_set_id,
        query=query,
        hits=hits,
        source_book_ids=source_scope.book_ids,
        source_map=(),
        candidates=(),
        retrieval_query=query,
        diagnostics=diagnostics,
        tool_call_id=tool_call_id,
        attempt_number=attempt_number,
        intent=intent,
        resolved_query=query,
        tool_name="open_page",
    )
    return SearchLibraryResult(
        retrieval_run_id=retrieval_run_id,
        query=query,
        source_set_id=source_scope.source_set_id,
        source_book_ids=source_scope.book_ids,
        hits=hits,
        diagnostics=diagnostics,
    )


def lookup_source_object(
    config: AppConfig,
    *,
    thread_id: str,
    message_id: str,
    tool_call_id: str,
    attempt_number: int,
    source_object_id: str,
    intent: str,
    total_char_limit: int,
    window_chars: int,
) -> SearchLibraryResult:
    source_scope = thread_source_scope(config, thread_id)
    with initialize_database(config.db_path) as connection:
        row = source_object_row(connection, source_object_id)
        if row is not None and row["book_id"] not in source_scope.book_ids:
            row = None
        hits = (
            ()
            if row is None or total_char_limit <= 0
            else (
                source_object_row_to_hit(
                    connection,
                    row,
                    rank=1,
                    terms=tool_terms(row["title"], intent),
                    max_chars=min(total_char_limit, window_chars),
                ),
            )
        )

    diagnostics = tool_diagnostics(
        config,
        page_lookup_attempted=False,
        page_lookup_count=0,
        table_stat_lookup_count=1 if hits else 0,
        selected_count=len(hits),
        skip_reasons={} if hits else {"table_stat_lookup": "not_found"},
    )
    query = f"source_object:{source_object_id}"
    retrieval_run_id = chat_store.record_retrieval_run(
        config,
        thread_id=thread_id,
        message_id=message_id,
        source_set_id=source_scope.source_set_id,
        query=query,
        hits=hits,
        source_book_ids=source_scope.book_ids,
        source_map=(),
        candidates=(),
        retrieval_query=query,
        diagnostics=diagnostics,
        tool_call_id=tool_call_id,
        attempt_number=attempt_number,
        intent=intent,
        resolved_query=query,
        tool_name="lookup_source_object",
    )
    return SearchLibraryResult(
        retrieval_run_id=retrieval_run_id,
        query=query,
        source_set_id=source_scope.source_set_id,
        source_book_ids=source_scope.book_ids,
        hits=hits,
        diagnostics=diagnostics,
    )


def thread_source_scope(config: AppConfig, thread_id: str) -> SourceScope:
    with initialize_database(config.db_path) as connection:
        thread = connection.execute(
            """
            select active_source_set_id
            from chat_threads
            where id = ?
            """,
            (thread_id,),
        ).fetchone()
        if thread is None:
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
    return SourceScope(
        source_set_id=thread["active_source_set_id"],
        book_ids=tuple(row["book_id"] for row in rows),
    )


def resolve_book_id(
    connection: sqlite3.Connection,
    *,
    source_scope: SourceScope,
    book_id: str | None,
    book_title_hint: str | None,
) -> str | None:
    if book_id is not None:
        return book_id if book_id in source_scope.book_ids else None
    if book_title_hint is None:
        return None
    normalized_hint = normalize_for_match(book_title_hint)
    if not normalized_hint:
        return None
    placeholders = ",".join("?" for _ in source_scope.book_ids)
    if not placeholders:
        return None
    rows = connection.execute(
        f"""
        select id, title
        from books
        where id in ({placeholders})
        order by id
        """,
        source_scope.book_ids,
    ).fetchall()
    matches = [
        row["id"]
        for row in rows
        if normalized_hint in normalize_for_match(row["title"])
        or normalize_for_match(row["title"]) in normalized_hint
    ]
    return matches[0] if len(matches) == 1 else None


def resolve_page_row(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    printed_page_label: str | None,
    pdf_page_number: int | None,
) -> sqlite3.Row | None:
    if pdf_page_number is not None:
        return page_row_by_page_number(connection, book_id=book_id, page_number=pdf_page_number)
    normalized_label = normalize_page_label(printed_page_label)
    if normalized_label is None:
        return None
    rows = page_rows_for_book(connection, book_id)
    if not rows:
        return None
    page_numbers = tuple(int(row["page_number"]) for row in rows)
    calibrated = load_calibrated_page_labels(
        connection,
        book_id=book_id,
        page_numbers=page_numbers,
    )
    for row in rows:
        page_number = int(row["page_number"])
        candidate_label = calibrated.get(page_number) or normalize_page_label(
            row["page_label"]
        )
        if candidate_label == normalized_label:
            return row
    return None


def page_rows_for_book(
    connection: sqlite3.Connection,
    book_id: str,
) -> tuple[sqlite3.Row, ...]:
    rows = connection.execute(
        """
        select
          books.id as book_id,
          books.title,
          books.category,
          pages.id as page_id,
          pages.page_number,
          pages.page_label,
          page_text.text,
          page_text.text_sha256
        from pages
        join books on books.id = pages.book_id
        left join page_text on page_text.page_id = pages.id
        where books.id = ?
          and books.copy_status = 'copied'
          and books.text_status = 'imported'
        order by pages.page_number
        """,
        (book_id,),
    ).fetchall()
    return tuple(rows)


def page_row_by_page_number(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    page_number: int,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        select
          books.id as book_id,
          books.title,
          books.category,
          pages.id as page_id,
          pages.page_number,
          pages.page_label,
          page_text.text,
          page_text.text_sha256
        from pages
        join books on books.id = pages.book_id
        left join page_text on page_text.page_id = pages.id
        where books.id = ?
          and books.copy_status = 'copied'
          and books.text_status = 'imported'
          and pages.page_number = ?
        """,
        (book_id, page_number),
    ).fetchone()


def source_object_row(
    connection: sqlite3.Connection,
    source_object_id: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        select
          source_objects.*,
          books.title as book_title,
          books.category,
          pages.page_number as pdf_page_number,
          pages.page_label
        from source_objects
        join books on books.id = source_objects.book_id
        join pages on pages.id = source_objects.page_id
        where source_objects.id = ?
          and books.copy_status = 'copied'
          and books.text_status = 'imported'
        """,
        (source_object_id,),
    ).fetchone()


def page_row_to_hit(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    rank: int,
    terms: Sequence[str],
    max_chars: int,
) -> RetrievedHit:
    page_number = int(row["page_number"])
    page_label = load_calibrated_printed_page_label(
        connection,
        book_id=row["book_id"],
        page_number=page_number,
        fallback_label=row["page_label"],
    )
    context_text = bounded_context(row["text"] or "", terms=terms, max_chars=max_chars)
    return RetrievedHit(
        book_id=row["book_id"],
        title=row["title"],
        category=row["category"],
        page_id=row["page_id"],
        page_number=page_number,
        pdf_page_number=page_number,
        page_label=page_label,
        snippet=context_text,
        score=1.0,
        rank=rank,
        context_text=context_text,
        page_start=page_number,
        page_end=page_number,
        page_range_label=page_label,
        rank_reasons=("tool:open_page", "channel:page_lookup"),
        text_snapshot_sha256=row["text_sha256"],
    )


def source_object_row_to_hit(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    rank: int,
    terms: Sequence[str],
    max_chars: int,
) -> RetrievedHit:
    page_start = int(row["page_start"])
    page_end = int(row["page_end"])
    page_label = load_calibrated_printed_page_label(
        connection,
        book_id=row["book_id"],
        page_number=page_start,
        fallback_label=row["page_label"],
    )
    page_range_label = load_calibrated_printed_page_range_label(
        connection,
        book_id=row["book_id"],
        page_start=page_start,
        page_end=page_end,
    )
    context_text = bounded_context(row["text"] or "", terms=terms, max_chars=max_chars)
    return RetrievedHit(
        book_id=row["book_id"],
        title=row["book_title"],
        category=row["category"],
        page_id=row["page_id"],
        page_number=page_start,
        pdf_page_number=int(row["pdf_page_number"]),
        page_label=page_label,
        snippet=context_text,
        score=1.0,
        rank=rank,
        context_text=context_text,
        source_object_id=row["id"],
        object_type=row["object_type"],
        object_title=row["title"],
        heading_path=parse_heading_path(row["heading_path_json"]),
        page_start=page_start,
        page_end=page_end,
        page_range_label=page_range_label,
        confidence=float(row["confidence"]),
        rank_reasons=("tool:lookup_source_object", "channel:table_stat_lookup"),
        text_snapshot_sha256=row["text_snapshot_sha256"],
    )


def tool_diagnostics(
    config: AppConfig,
    *,
    page_lookup_attempted: bool,
    page_lookup_count: int,
    table_stat_lookup_count: int,
    selected_count: int,
    skip_reasons: dict[str, str],
) -> RetrievalDiagnostics:
    channel_counts = {
        "page_fts": 0,
        "source_object_fts": 0,
        "source_object_scan": 0,
        "vector": 0,
        "page_lookup": page_lookup_count,
        "table_stat_lookup": table_stat_lookup_count,
    }
    vector_status = (
        "disabled" if config.embedding_provider == "disabled" else "missing_embeddings"
    )
    return RetrievalDiagnostics(
        channel_counts=channel_counts,
        channel_skip_reasons=skip_reasons,
        vector_status=vector_status,
        candidate_count_before_fusion=selected_count,
        candidate_count_after_fusion=selected_count,
        reranked_count=selected_count,
        selected_count=selected_count,
        page_lookup_attempted=page_lookup_attempted,
        validation_status="not_evaluated",
    )


def bounded_context(text: str, *, terms: Sequence[str], max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    return context_window(text, terms=list(terms), max_chars=max_chars)


def tool_terms(*values: str | None) -> tuple[str, ...]:
    terms: list[str] = []
    for value in values:
        if not value:
            continue
        terms.extend(part.lower() for part in value.split() if part.strip())
    return tuple(terms)


def page_lookup_query(
    *,
    book_id: str | None,
    printed_page_label: str | None,
    pdf_page_number: int | None,
    subject_hint: str | None,
    intent: str,
) -> str:
    parts = ["open_page"]
    if book_id:
        parts.append(f"book={book_id}")
    if printed_page_label:
        parts.append(f"printed_page={printed_page_label}")
    if pdf_page_number is not None:
        parts.append(f"pdf_page={pdf_page_number}")
    if subject_hint:
        parts.append(f"subject={subject_hint}")
    parts.append(f"intent={intent}")
    return " ".join(parts)


def normalize_for_match(value: str) -> str:
    return " ".join(value.casefold().split())
