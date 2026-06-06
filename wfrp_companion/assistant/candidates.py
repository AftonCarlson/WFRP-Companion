from __future__ import annotations

import sqlite3
from collections.abc import Collection

from wfrp_companion.assistant.evidence import EvidenceCandidate
from wfrp_companion.assistant.evidence import load_page_range_label
from wfrp_companion.assistant.evidence import load_page_text_from_connection
from wfrp_companion.assistant.evidence import parse_heading_path
from wfrp_companion.assistant.query_planner import QueryPlan
from wfrp_companion.assistant.query_planner import meaningful_tokens
from wfrp_companion.assistant.reranking import reciprocal_rank_fuse
from wfrp_companion.assistant.reranking import semantic_overlap_count
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.search.fts import build_fts_query, search_exact


def collect_evidence_candidates(
    config: AppConfig,
    *,
    source_book_ids: tuple[str, ...],
    query_plan: QueryPlan,
    per_candidate_limit: int,
) -> tuple[EvidenceCandidate, ...]:
    if not source_book_ids:
        return ()
    candidates: list[EvidenceCandidate] = []
    with initialize_database(config.db_path) as connection:
        for candidate_query in query_plan.candidates:
            for hit in search_exact(
                config,
                candidate_query,
                book_ids=source_book_ids,
                limit=per_candidate_limit,
            ):
                candidate = evidence_candidate_from_page_hit(
                    connection,
                    hit,
                    query_terms=query_plan.terms + query_plan.expanded_terms,
                )
                if candidate is not None:
                    candidates.append(candidate)
            for candidate in search_source_object_candidates(
                connection,
                candidate_query,
                book_ids=source_book_ids,
                limit=per_candidate_limit,
            ):
                candidates.append(candidate)
    return reciprocal_rank_fuse(candidates)

def keep_best_candidate(
    candidates: dict[str, EvidenceCandidate],
    candidate: EvidenceCandidate,
) -> None:
    current = candidates.get(candidate.dedupe_key)
    if current is None or candidate.base_score < current.base_score:
        candidates[candidate.dedupe_key] = candidate

def evidence_candidate_from_page_hit(
    connection: sqlite3.Connection,
    hit: object,
    *,
    query_terms: tuple[str, ...],
) -> EvidenceCandidate | None:
    page_id = getattr(hit, "page_id")
    page_number = int(getattr(hit, "page_number"))
    pdf_page_number = int(getattr(hit, "pdf_page_number", page_number))
    page_label = getattr(hit, "page_label", None)
    source_object = resolve_page_hit_to_source_object(
        connection,
        hit,
        query_terms=query_terms,
    )
    if source_object is not None:
        return source_object

    page_text = load_page_text_from_connection(connection, page_id)
    if not page_text:
        return None
    return EvidenceCandidate(
        book_id=getattr(hit, "book_id"),
        title=getattr(hit, "title"),
        category=getattr(hit, "category"),
        page_id=page_id,
        page_number=page_number,
        pdf_page_number=pdf_page_number,
        page_label=page_label,
        page_start=page_number,
        page_end=page_number,
        page_range_label=page_label,
        snippet=getattr(hit, "snippet", "") or "",
        base_score=float(getattr(hit, "score")),
        context_text=page_text,
        channel="page_fts",
        rank_reasons=("candidate:page_fts",),
    )

def resolve_page_hit_to_source_object(
    connection: sqlite3.Connection,
    hit: object,
    *,
    query_terms: tuple[str, ...],
) -> EvidenceCandidate | None:
    page_number = int(getattr(hit, "page_number"))
    rows = connection.execute(
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
        where source_objects.book_id = ?
          and source_objects.page_start <= ?
          and source_objects.page_end >= ?
        order by
          case source_objects.object_type
            when 'page_chunk' then 1
            else 0
          end,
          source_objects.confidence desc,
          source_objects.page_start,
          source_objects.id
        limit 12
        """,
        (getattr(hit, "book_id"), page_number, page_number),
    ).fetchall()
    best: tuple[int, sqlite3.Row] | None = None
    for row in rows:
        overlap = semantic_overlap_count(
            query_terms,
            row["search_text"] or row["text"] or "",
        )
        if overlap == 0:
            continue
        if best is None or overlap > best[0]:
            best = (overlap, row)
    if best is None:
        return None
    return evidence_candidate_from_source_object_row(
        connection,
        best[1],
        base_score=float(getattr(hit, "score")),
        snippet=getattr(hit, "snippet", "") or "",
        channel="page_fts_resolved",
    )

def search_source_object_candidates(
    connection: sqlite3.Connection,
    candidate_query: str,
    *,
    book_ids: Collection[str],
    limit: int,
) -> tuple[EvidenceCandidate, ...]:
    selected_book_ids = tuple(book_ids)
    if not selected_book_ids:
        return ()

    fts_candidates = search_source_object_fts_candidates(
        connection,
        candidate_query,
        book_ids=selected_book_ids,
        limit=limit,
    )
    if fts_candidates:
        return fts_candidates
    return search_source_object_like_candidates(
        connection,
        candidate_query,
        book_ids=selected_book_ids,
        limit=limit,
    )

def search_source_object_fts_candidates(
    connection: sqlite3.Connection,
    candidate_query: str,
    *,
    book_ids: tuple[str, ...],
    limit: int,
) -> tuple[EvidenceCandidate, ...]:
    fts_query = build_fts_query(candidate_query)
    if fts_query is None:
        return ()
    placeholders = ",".join("?" for _ in book_ids)
    rows = connection.execute(
        f"""
        select
          source_objects.*,
          books.title as book_title,
          books.category,
          pages.page_number as pdf_page_number,
          pages.page_label,
          snippet(source_object_search_fts, 3, '[', ']', '...', 12) as snippet,
          bm25(source_object_search_fts) as score
        from source_object_search_fts
        join source_object_search
          on source_object_search.rowid = source_object_search_fts.rowid
        join source_objects
          on source_objects.id = source_object_search.source_object_id
        join books on books.id = source_objects.book_id
        join pages on pages.id = source_objects.page_id
        where source_object_search_fts match ?
          and source_objects.book_id in ({placeholders})
          and books.copy_status = 'copied'
          and books.text_status = 'imported'
          and books.search_status = 'indexed'
        order by score asc, source_objects.page_start, source_objects.id
        limit ?
        """,
        (fts_query, *book_ids, max(1, min(limit, 100))),
    ).fetchall()
    return tuple(
        evidence_candidate_from_source_object_row(
            connection,
            row,
            base_score=float(row["score"]),
            snippet=row["snippet"] or "",
            channel="source_object_fts",
        )
        for row in rows
    )

def search_source_object_like_candidates(
    connection: sqlite3.Connection,
    candidate_query: str,
    *,
    book_ids: tuple[str, ...],
    limit: int,
) -> tuple[EvidenceCandidate, ...]:
    terms = meaningful_tokens(candidate_query)
    if not terms:
        return ()
    placeholders = ",".join("?" for _ in book_ids)
    term_filters = " and ".join("lower(source_objects.search_text) like ?" for _ in terms)
    rows = connection.execute(
        f"""
        select
          source_objects.*,
          books.title as book_title,
          books.category,
          pages.page_number as pdf_page_number,
          pages.page_label,
          0.0 as score
        from source_objects
        join books on books.id = source_objects.book_id
        join pages on pages.id = source_objects.page_id
        where source_objects.book_id in ({placeholders})
          and books.copy_status = 'copied'
          and books.text_status = 'imported'
          and books.search_status = 'indexed'
          and {term_filters}
        order by source_objects.confidence desc, source_objects.page_start, source_objects.id
        limit ?
        """,
        (*book_ids, *(f"%{term}%" for term in terms), max(1, min(limit, 100))),
    ).fetchall()
    return tuple(
        evidence_candidate_from_source_object_row(
            connection,
            row,
            base_score=float(row["score"]),
            snippet=row["title"] or "",
            channel="source_object_scan",
        )
        for row in rows
    )

def evidence_candidate_from_source_object_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    base_score: float,
    snippet: str,
    channel: str,
) -> EvidenceCandidate:
    page_range_label = load_page_range_label(
        connection,
        book_id=row["book_id"],
        page_start=int(row["page_start"]),
        page_end=int(row["page_end"]),
    )
    return EvidenceCandidate(
        book_id=row["book_id"],
        title=row["book_title"],
        category=row["category"],
        page_id=row["page_id"],
        page_number=int(row["page_start"]),
        pdf_page_number=int(row["page_start"]),
        page_label=row["page_label"],
        page_start=int(row["page_start"]),
        page_end=int(row["page_end"]),
        page_range_label=page_range_label,
        snippet=snippet or row["title"] or "",
        base_score=base_score,
        context_text=row["text"],
        channel=channel,
        source_object_id=row["id"],
        object_type=row["object_type"],
        object_title=row["title"],
        heading_path=parse_heading_path(row["heading_path_json"]),
        confidence=float(row["confidence"]),
        rank_reasons=(f"candidate:{channel}", f"source_object:{row['object_type']}"),
        text_snapshot_sha256=row["text_snapshot_sha256"],
    )
