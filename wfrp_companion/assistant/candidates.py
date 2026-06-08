from __future__ import annotations

import sqlite3
from collections.abc import Collection
from dataclasses import dataclass
from dataclasses import replace

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
from wfrp_companion.library.page_labels import load_calibrated_printed_page_label
from wfrp_companion.library.page_labels import load_calibrated_printed_page_range_label
from wfrp_companion.search.fts import build_fts_query, search_exact
from wfrp_companion.source_objects.embeddings import cosine_similarity
from wfrp_companion.source_objects.embeddings import source_object_embeddings_current
from wfrp_companion.source_objects.embeddings import vector_from_blob
from wfrp_companion.source_objects.embedding_providers import (
    EmbeddingDimensionError,
    EmbeddingProviderError,
    UnsupportedEmbeddingProviderError,
    resolve_embedding_provider,
)


@dataclass(frozen=True)
class LinkedEvidenceTarget:
    link_type: str
    source_object_row: sqlite3.Row | None = None
    page_row: sqlite3.Row | None = None


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
        vector_query = " ".join((*query_plan.terms, *query_plan.expanded_terms))
        for candidate in search_vector_candidates(
            connection,
            vector_query,
            book_ids=source_book_ids,
            limit=per_candidate_limit,
            config=config,
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
    printed_page_label = load_calibrated_printed_page_label(
        connection,
        book_id=getattr(hit, "book_id"),
        page_number=page_number,
        fallback_label=page_label,
    )
    return EvidenceCandidate(
        book_id=getattr(hit, "book_id"),
        title=getattr(hit, "title"),
        category=getattr(hit, "category"),
        page_id=page_id,
        page_number=page_number,
        pdf_page_number=pdf_page_number,
        page_label=printed_page_label,
        page_start=page_number,
        page_end=page_number,
        page_range_label=printed_page_label,
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
        source_book_ids=(getattr(hit, "book_id"),),
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
            source_book_ids=book_ids,
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
            source_book_ids=book_ids,
        )
        for row in rows
    )


def search_vector_candidates(
    connection: sqlite3.Connection,
    query_text: str,
    *,
    book_ids: Collection[str],
    limit: int,
    config: AppConfig,
) -> tuple[EvidenceCandidate, ...]:
    selected_book_ids = tuple(book_ids)
    if not selected_book_ids:
        return ()
    try:
        provider = resolve_embedding_provider(config)
    except UnsupportedEmbeddingProviderError:
        return ()
    if provider is None:
        return ()
    current_book_ids = tuple(
        book_id
        for book_id in selected_book_ids
        if source_object_embeddings_current(connection, book_id, config=config)
    )
    if not current_book_ids:
        return ()
    try:
        query_vector = provider.embed_query(query_text)
    except (EmbeddingProviderError, EmbeddingDimensionError):
        return ()
    if not any(query_vector):
        return ()
    placeholders = ",".join("?" for _ in current_book_ids)
    rows = connection.execute(
        f"""
        select
          source_objects.*,
          books.title as book_title,
          books.category,
          pages.page_number as pdf_page_number,
          pages.page_label,
          source_object_embeddings.vector_blob
        from source_object_embeddings
        join source_objects
          on source_objects.id = source_object_embeddings.source_object_id
         and source_objects.book_id = source_object_embeddings.book_id
        join book_retrieval_status
          on book_retrieval_status.book_id = source_objects.book_id
        join books on books.id = source_objects.book_id
        join pages on pages.id = source_objects.page_id
        where source_objects.book_id in ({placeholders})
          and source_object_embeddings.embedding_provider = ?
          and source_object_embeddings.embedding_model = ?
          and source_object_embeddings.embedding_dimensions = ?
          and length(source_object_embeddings.vector_blob) = ?
          and source_object_embeddings.text_snapshot_sha256 =
              source_objects.text_snapshot_sha256
          and book_retrieval_status.vector_status = 'indexed'
          and book_retrieval_status.embedding_provider = ?
          and book_retrieval_status.embedding_model = ?
          and book_retrieval_status.embedding_dimensions = ?
          and books.copy_status = 'copied'
          and books.text_status = 'imported'
          and books.search_status = 'indexed'
        """,
        (
            *current_book_ids,
            provider.provider_name,
            provider.model_name,
            provider.dimensions,
            provider.dimensions * 4,
            provider.provider_name,
            provider.model_name,
            provider.dimensions,
        ),
    ).fetchall()
    scored_rows: list[tuple[float, sqlite3.Row]] = []
    for row in rows:
        try:
            similarity = cosine_similarity(
                query_vector,
                vector_from_blob(row["vector_blob"]),
            )
        except ValueError:
            continue
        scored_rows.append((similarity, row))
    scored_rows.sort(
        key=lambda item: (-item[0], item[1]["page_start"], item[1]["id"])
    )
    candidates: list[EvidenceCandidate] = []
    for similarity, row in scored_rows[: max(1, min(limit, 100))]:
        if similarity <= 0:
            continue
        candidate = evidence_candidate_from_source_object_row(
            connection,
            row,
            base_score=-similarity,
            snippet=row["title"] or "",
            channel="vector",
            source_book_ids=current_book_ids,
        )
        candidates.append(
            replace(
                candidate,
                rank_reasons=(
                    *candidate.rank_reasons,
                    f"vector_provider:{provider.provider_name}",
                    f"vector_model:{provider.model_name}",
                    f"vector_similarity:{similarity:.6f}",
                ),
            )
        )
    return tuple(candidates)


def evidence_candidate_from_source_object_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    base_score: float,
    snippet: str,
    channel: str,
    source_book_ids: Collection[str] | None = None,
) -> EvidenceCandidate:
    selected_book_ids = tuple(source_book_ids or (row["book_id"],))
    linked = linked_evidence_target(
        connection,
        row,
        source_book_ids=selected_book_ids,
    )
    if linked is not None and row["object_type"] != "glossary_entry":
        if linked.source_object_row is not None:
            candidate = source_object_row_to_candidate(
                connection,
                linked.source_object_row,
                base_score=base_score,
                snippet=linked_evidence_snippet(row, linked.link_type, snippet),
                channel=channel,
            )
        else:
            assert linked.page_row is not None
            candidate = linked_page_row_to_candidate(
                connection,
                linked.page_row,
                source_row=row,
                base_score=base_score,
                snippet=snippet,
                channel=channel,
                link_type=linked.link_type,
            )
        return replace(
            candidate,
            rank_reasons=(
                *candidate.rank_reasons,
                f"linked_evidence:{linked.link_type}:{row['id']}",
                f"linked_source_object:{row['object_type']}",
            ),
        )

    candidate = source_object_row_to_candidate(
        connection,
        row,
        base_score=base_score,
        snippet=snippet,
        channel=channel,
    )
    if linked is None or row["object_type"] != "glossary_entry":
        return candidate

    linked_context = (
        linked.source_object_row["text"]
        if linked.source_object_row is not None
        else linked.page_row["text"]
        if linked.page_row is not None
        else ""
    )
    linked_id = (
        linked.source_object_row["id"]
        if linked.source_object_row is not None
        else linked.page_row["page_id"]
        if linked.page_row is not None
        else "unknown"
    )
    return replace(
        candidate,
        context_text="\n\n".join(
            part for part in (candidate.context_text, linked_context) if part
        ),
        rank_reasons=(
            *candidate.rank_reasons,
            f"linked_evidence:{linked.link_type}:{linked_id}",
        ),
    )


def source_object_row_to_candidate(
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
    page_label = load_calibrated_printed_page_label(
        connection,
        book_id=row["book_id"],
        page_number=int(row["page_start"]),
        fallback_label=row["page_label"],
    )
    return EvidenceCandidate(
        book_id=row["book_id"],
        title=row["book_title"],
        category=row["category"],
        page_id=row["page_id"],
        page_number=int(row["page_start"]),
        pdf_page_number=int(row["page_start"]),
        page_label=page_label,
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


def linked_page_row_to_candidate(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    source_row: sqlite3.Row,
    base_score: float,
    snippet: str,
    channel: str,
    link_type: str,
) -> EvidenceCandidate:
    page_number = int(row["page_number"])
    page_label = load_calibrated_printed_page_label(
        connection,
        book_id=row["book_id"],
        page_number=page_number,
        fallback_label=row["page_label"],
    )
    return EvidenceCandidate(
        book_id=row["book_id"],
        title=row["book_title"],
        category=row["category"],
        page_id=row["page_id"],
        page_number=page_number,
        pdf_page_number=page_number,
        page_label=page_label,
        page_start=page_number,
        page_end=page_number,
        page_range_label=load_calibrated_printed_page_range_label(
            connection,
            book_id=row["book_id"],
            page_start=page_number,
            page_end=page_number,
        ),
        snippet=linked_evidence_snippet(source_row, link_type, snippet),
        base_score=base_score,
        context_text=row["text"],
        channel=channel,
        object_type="page_fallback",
        rank_reasons=(f"candidate:{channel}", "source_object:page_fallback"),
    )


def linked_evidence_target(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    source_book_ids: tuple[str, ...],
) -> LinkedEvidenceTarget | None:
    link_types = preferred_link_types(row["object_type"])
    if not link_types or not source_book_ids:
        return None
    placeholders = ",".join("?" for _ in source_book_ids)
    link_placeholders = ",".join("?" for _ in link_types)
    linked_row = connection.execute(
        f"""
        select
          target.*,
          books.title as book_title,
          books.category,
          pages.page_number as pdf_page_number,
          pages.page_label,
          source_object_links.link_type
        from source_object_links
        join source_objects target
          on target.id = source_object_links.to_object_id
        join books on books.id = target.book_id
        join pages on pages.id = target.page_id
        where source_object_links.from_object_id = ?
          and source_object_links.link_type in ({link_placeholders})
          and target.book_id in ({placeholders})
          and (
            source_object_links.to_book_id is null
            or source_object_links.to_book_id = target.book_id
          )
          and books.copy_status = 'copied'
          and books.text_status = 'imported'
          and books.search_status = 'indexed'
        order by source_object_links.confidence desc, target.page_start, target.id
        limit 1
        """,
        (row["id"], *link_types, *source_book_ids),
    ).fetchone()
    if linked_row is not None:
        return LinkedEvidenceTarget(
            link_type=str(linked_row["link_type"]),
            source_object_row=linked_row,
        )

    linked_page_object = connection.execute(
        f"""
        select
          target.*,
          books.title as book_title,
          books.category,
          pages.page_number as pdf_page_number,
          pages.page_label,
          source_object_links.link_type
        from source_object_links
        join source_objects target
          on target.page_id = source_object_links.to_page_id
         and (
            source_object_links.to_book_id is null
            or target.book_id = source_object_links.to_book_id
         )
        join books on books.id = target.book_id
        join pages on pages.id = target.page_id
        where source_object_links.from_object_id = ?
          and source_object_links.to_object_id is null
          and source_object_links.to_page_id is not null
          and source_object_links.link_type in ({link_placeholders})
          and target.book_id in ({placeholders})
          and books.copy_status = 'copied'
          and books.text_status = 'imported'
          and books.search_status = 'indexed'
        order by
          source_object_links.confidence desc,
          case
            when source_object_links.label is not null
             and target.title is not null
             and lower(target.title) = lower(source_object_links.label)
              then 0
            when source_object_links.label is not null
             and lower(target.heading_path_json) like
                 '%' || lower(source_object_links.label) || '%'
              then 1
            else 2
          end,
          case target.object_type
            when 'index_entry' then 2
            when 'glossary_entry' then 2
            when 'cross_reference' then 2
            when 'page_chunk' then 1
            else 0
          end,
          target.confidence desc,
          target.page_start,
          target.id
        limit 1
        """,
        (row["id"], *link_types, *source_book_ids),
    ).fetchone()
    if linked_page_object is not None:
        return LinkedEvidenceTarget(
            link_type=str(linked_page_object["link_type"]),
            source_object_row=linked_page_object,
        )

    linked_page = connection.execute(
        f"""
        select
          pages.id as page_id,
          pages.book_id,
          books.title as book_title,
          books.category,
          pages.page_number,
          pages.page_label,
          page_text.text,
          source_object_links.link_type
        from source_object_links
        join pages on pages.id = source_object_links.to_page_id
        join page_text on page_text.page_id = pages.id
        join books on books.id = pages.book_id
        where source_object_links.from_object_id = ?
          and source_object_links.to_object_id is null
          and source_object_links.to_page_id is not null
          and source_object_links.link_type in ({link_placeholders})
          and pages.book_id in ({placeholders})
          and (
            source_object_links.to_book_id is null
            or source_object_links.to_book_id = pages.book_id
          )
          and books.copy_status = 'copied'
          and books.text_status = 'imported'
          and books.search_status = 'indexed'
        order by source_object_links.confidence desc, pages.page_number, pages.id
        limit 1
        """,
        (row["id"], *link_types, *source_book_ids),
    ).fetchone()
    if linked_page is not None:
        return LinkedEvidenceTarget(
            link_type=str(linked_page["link_type"]),
            page_row=linked_page,
        )

    if row["parent_object_id"] is None:
        return None
    parent_link_types = tuple(
        link_type for link_type in link_types if link_type in {"table_row", "stat_profile"}
    )
    if not parent_link_types:
        return None
    linked_parent = connection.execute(
        f"""
        select
          parent.*,
          books.title as book_title,
          books.category,
          pages.page_number as pdf_page_number,
          pages.page_label
        from source_objects parent
        join books on books.id = parent.book_id
        join pages on pages.id = parent.page_id
        where parent.id = ?
          and parent.book_id in ({placeholders})
          and books.copy_status = 'copied'
          and books.text_status = 'imported'
          and books.search_status = 'indexed'
        limit 1
        """,
        (row["parent_object_id"], *source_book_ids),
    ).fetchone()
    if linked_parent is None:
        return None
    return LinkedEvidenceTarget(
        link_type=parent_link_types[0],
        source_object_row=linked_parent,
    )


def preferred_link_types(object_type: str) -> tuple[str, ...]:
    if object_type == "table_row":
        return ("table_row",)
    if object_type == "stat_block":
        return ("stat_profile",)
    if object_type == "index_entry":
        return ("index_entry",)
    if object_type == "cross_reference":
        return ("cross_reference",)
    if object_type == "glossary_entry":
        return ("glossary_definition",)
    return ()


def linked_evidence_snippet(
    row: sqlite3.Row,
    link_type: str,
    snippet: str,
) -> str:
    source_type = str(row["object_type"]).replace("_", " ")
    source_title = row["title"] or ""
    source_text = snippet or row["text"] or ""
    return f"{source_type} {link_type} {source_title} {source_text}".strip()
