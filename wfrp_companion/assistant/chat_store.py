from __future__ import annotations

import sqlite3
import uuid
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.library import source_sets


PROVIDER_UNAVAILABLE_MESSAGE = (
    "Familiar cannot reach OpenAI because OPENAI_API_KEY is not configured."
)


@dataclass(frozen=True)
class ChatThread:
    id: str
    title: str | None
    active_source_set_id: str | None
    source_book_count: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ChatMessage:
    id: str
    thread_id: str
    role: str
    content: str
    created_at: str


@dataclass(frozen=True)
class ModelRun:
    id: str
    thread_id: str
    user_message_id: str | None
    assistant_message_id: str | None
    retrieval_run_id: str | None
    retry_of_model_run_id: str | None
    status: str
    provider: str
    model: str
    provider_response_id: str | None
    error_code: str | None
    error_message: str | None
    input_tokens: int | None
    output_tokens: int | None
    retryable: bool


@dataclass(frozen=True)
class ChatCitation:
    book_id: str
    title: str
    category: str
    page_id: str
    page_number: int
    pdf_page_number: int
    page_label: str | None
    snippet: str
    rank: int
    score: float
    page_range_label: str | None = None


@dataclass(frozen=True)
class ChatTurn:
    user_message: ChatMessage
    assistant_message: ChatMessage | None
    model_run: ModelRun
    citations: tuple[ChatCitation, ...]


@dataclass(frozen=True)
class ChatThreadDetail:
    thread: ChatThread
    source_book_ids: tuple[str, ...]
    turns: tuple[ChatTurn, ...]


@dataclass(frozen=True)
class SendChatResult:
    thread: ChatThread
    user_message: ChatMessage
    assistant_message: ChatMessage | None
    model_run: ModelRun
    citations: tuple[ChatCitation, ...]


class ChatStoreError(Exception):
    pass


class ChatThreadNotFoundError(ChatStoreError):
    pass


class ModelRunNotFoundError(ChatStoreError):
    pass


class ModelRunNotRetryableError(ChatStoreError):
    pass


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def create_thread(
    config: AppConfig,
    *,
    title: str | None = None,
    source_set_id: str | None = None,
) -> ChatThread:
    with initialize_database(config.db_path) as connection:
        selected_source_set_id = source_set_id
        if selected_source_set_id is None:
            selected_source_set_id = source_sets.get_active_source_set_id_from_connection(
                connection
            )
            if selected_source_set_id is None:
                raise source_sets.ActiveSourceSetMissingError(
                    "No active source set. Run tools/source_sets.py init."
                )
        else:
            source_sets.require_source_set(connection, selected_source_set_id)

        book_ids = enabled_book_ids_from_connection(connection, selected_source_set_id)
        now = utc_timestamp()
        thread_id = new_id("thread")
        with connection:
            connection.execute(
                """
                insert into chat_threads (
                  id,
                  title,
                  active_source_set_id,
                  created_at,
                  updated_at
                )
                values (?, ?, ?, ?, ?)
                """,
                (thread_id, title, selected_source_set_id, now, now),
            )
            for book_id in book_ids:
                connection.execute(
                    """
                    insert into chat_thread_source_books (
                      thread_id,
                      book_id,
                      source_set_id,
                      captured_at
                    )
                    values (?, ?, ?, ?)
                    """,
                    (thread_id, book_id, selected_source_set_id, now),
                )
    return get_thread(config, thread_id)


def list_threads(config: AppConfig) -> tuple[ChatThread, ...]:
    with initialize_database(config.db_path) as connection:
        rows = connection.execute(
            """
            select
              chat_threads.id,
              chat_threads.title,
              chat_threads.active_source_set_id,
              chat_threads.created_at,
              chat_threads.updated_at,
              count(chat_thread_source_books.book_id) as source_book_count
            from chat_threads
            left join chat_thread_source_books
              on chat_thread_source_books.thread_id = chat_threads.id
            group by chat_threads.id
            order by chat_threads.updated_at desc, chat_threads.id
            """
        ).fetchall()
    return tuple(thread_from_row(row) for row in rows)


def get_thread(config: AppConfig, thread_id: str) -> ChatThread:
    with initialize_database(config.db_path) as connection:
        row = thread_row(connection, thread_id)
    return thread_from_row(row)


def get_thread_detail(config: AppConfig, thread_id: str) -> ChatThreadDetail:
    with initialize_database(config.db_path) as connection:
        thread = thread_from_row(thread_row(connection, thread_id))
        source_book_ids = tuple(
            row["book_id"]
            for row in connection.execute(
                """
                select book_id
                from chat_thread_source_books
                where thread_id = ?
                order by book_id
                """,
                (thread_id,),
            ).fetchall()
        )
        turns = load_turns_from_connection(connection, thread_id)
    return ChatThreadDetail(
        thread=thread,
        source_book_ids=source_book_ids,
        turns=turns,
    )


def create_provider_unavailable_turn(
    config: AppConfig,
    thread_id: str,
    *,
    content: str,
    idempotency_key: str,
    provider: str,
    model: str,
) -> SendChatResult:
    with initialize_database(config.db_path) as connection:
        existing = model_run_by_idempotency_key(connection, idempotency_key)
        if existing is not None:
            return result_for_model_run(connection, existing["id"])

        thread_row(connection, thread_id)
        now = utc_timestamp()
        user_message_id = new_id("message")
        model_run_id = new_id("run")
        with connection:
            connection.execute(
                """
                insert into chat_messages (
                  id,
                  thread_id,
                  role,
                  content,
                  created_at
                )
                values (?, ?, 'user', ?, ?)
                """,
                (user_message_id, thread_id, content, now),
            )
            connection.execute(
                """
                insert into model_runs (
                  id,
                  thread_id,
                  user_message_id,
                  provider,
                  model,
                  status,
                  idempotency_key,
                  error_code,
                  error_message,
                  created_at,
                  updated_at
                )
                values (?, ?, ?, ?, ?, 'failed', ?, 'provider_unavailable', ?, ?, ?)
                """,
                (
                    model_run_id,
                    thread_id,
                    user_message_id,
                    provider,
                    model,
                    idempotency_key,
                    PROVIDER_UNAVAILABLE_MESSAGE,
                    now,
                    now,
                ),
            )
            touch_thread(connection, thread_id, now=now)
        return result_for_model_run(connection, model_run_id)


def create_queued_turn(
    config: AppConfig,
    thread_id: str,
    *,
    content: str,
    idempotency_key: str,
    provider: str,
    model: str,
) -> SendChatResult:
    with initialize_database(config.db_path) as connection:
        existing = model_run_by_idempotency_key(connection, idempotency_key)
        if existing is not None:
            return result_for_model_run(connection, existing["id"])

        thread_row(connection, thread_id)
        now = utc_timestamp()
        user_message_id = new_id("message")
        model_run_id = new_id("run")
        with connection:
            connection.execute(
                """
                insert into chat_messages (
                  id,
                  thread_id,
                  role,
                  content,
                  created_at
                )
                values (?, ?, 'user', ?, ?)
                """,
                (user_message_id, thread_id, content, now),
            )
            connection.execute(
                """
                insert into model_runs (
                  id,
                  thread_id,
                  user_message_id,
                  provider,
                  model,
                  status,
                  idempotency_key,
                  created_at,
                  updated_at
                )
                values (?, ?, ?, ?, ?, 'queued', ?, ?, ?)
                """,
                (
                    model_run_id,
                    thread_id,
                    user_message_id,
                    provider,
                    model,
                    idempotency_key,
                    now,
                    now,
                ),
            )
            touch_thread(connection, thread_id, now=now)
        return result_for_model_run(connection, model_run_id)


def create_provider_unavailable_retry(
    config: AppConfig,
    model_run_id: str,
    *,
    idempotency_key: str,
    provider: str,
    model: str,
) -> SendChatResult:
    with initialize_database(config.db_path) as connection:
        existing = model_run_by_idempotency_key(connection, idempotency_key)
        if existing is not None:
            return result_for_model_run(connection, existing["id"])

        failed_run = model_run_row(connection, model_run_id)
        if failed_run["status"] != "failed" or failed_run["user_message_id"] is None:
            raise ModelRunNotRetryableError(f"Model run is not retryable: {model_run_id}")

        now = utc_timestamp()
        retry_id = new_id("run")
        with connection:
            connection.execute(
                """
                insert into model_runs (
                  id,
                  thread_id,
                  user_message_id,
                  retry_of_model_run_id,
                  provider,
                  model,
                  status,
                  idempotency_key,
                  error_code,
                  error_message,
                  created_at,
                  updated_at
                )
                values (?, ?, ?, ?, ?, ?, 'failed', ?, 'provider_unavailable', ?, ?, ?)
                """,
                (
                    retry_id,
                    failed_run["thread_id"],
                    failed_run["user_message_id"],
                    model_run_id,
                    provider,
                    model,
                    idempotency_key,
                    PROVIDER_UNAVAILABLE_MESSAGE,
                    now,
                    now,
                ),
            )
            touch_thread(connection, failed_run["thread_id"], now=now)
        return result_for_model_run(connection, retry_id)


def create_queued_retry(
    config: AppConfig,
    model_run_id: str,
    *,
    idempotency_key: str,
    provider: str,
    model: str,
) -> SendChatResult:
    with initialize_database(config.db_path) as connection:
        existing = model_run_by_idempotency_key(connection, idempotency_key)
        if existing is not None:
            return result_for_model_run(connection, existing["id"])

        failed_run = model_run_row(connection, model_run_id)
        if failed_run["status"] != "failed" or failed_run["user_message_id"] is None:
            raise ModelRunNotRetryableError(f"Model run is not retryable: {model_run_id}")

        active_retry = connection.execute(
            """
            select id
            from model_runs
            where retry_of_model_run_id = ?
              and status in ('queued', 'retrieving', 'calling_model')
            order by created_at, id
            limit 1
            """,
            (model_run_id,),
        ).fetchone()
        if active_retry is not None:
            return result_for_model_run(connection, active_retry["id"])

        now = utc_timestamp()
        retry_id = new_id("run")
        with connection:
            connection.execute(
                """
                insert into model_runs (
                  id,
                  thread_id,
                  user_message_id,
                  retry_of_model_run_id,
                  provider,
                  model,
                  status,
                  idempotency_key,
                  created_at,
                  updated_at
                )
                values (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)
                """,
                (
                    retry_id,
                    failed_run["thread_id"],
                    failed_run["user_message_id"],
                    model_run_id,
                    provider,
                    model,
                    idempotency_key,
                    now,
                    now,
                ),
            )
            touch_thread(connection, failed_run["thread_id"], now=now)
        return result_for_model_run(connection, retry_id)


def transition_model_run(
    config: AppConfig,
    model_run_id: str,
    *,
    from_statuses: Sequence[str],
    to_status: str,
) -> SendChatResult:
    if not from_statuses:
        raise ValueError("from_statuses must not be empty")
    placeholders = ",".join("?" for _ in from_statuses)
    now = utc_timestamp()
    with initialize_database(config.db_path) as connection:
        with connection:
            cursor = connection.execute(
                f"""
                update model_runs
                set status = ?,
                    updated_at = ?
                where id = ?
                  and status in ({placeholders})
                """,
                (to_status, now, model_run_id, *from_statuses),
            )
            if cursor.rowcount != 1:
                model_run_row(connection, model_run_id)
        return result_for_model_run(connection, model_run_id)


def attach_retrieval_run(
    config: AppConfig,
    model_run_id: str,
    *,
    retrieval_run_id: str,
) -> SendChatResult:
    now = utc_timestamp()
    with initialize_database(config.db_path) as connection:
        with connection:
            connection.execute(
                """
                update model_runs
                set retrieval_run_id = ?,
                    updated_at = ?
                where id = ?
                """,
                (retrieval_run_id, now, model_run_id),
            )
        return result_for_model_run(connection, model_run_id)


def complete_model_run(
    config: AppConfig,
    model_run_id: str,
    *,
    content: str,
    provider_response_id: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
) -> SendChatResult:
    now = utc_timestamp()
    with initialize_database(config.db_path) as connection:
        run = model_run_row(connection, model_run_id)
        if run["status"] == "completed":
            return result_for_model_run(connection, model_run_id)
        assistant_message_id = new_id("message")
        with connection:
            connection.execute(
                """
                insert into chat_messages (
                  id,
                  thread_id,
                  role,
                  content,
                  created_at
                )
                values (?, ?, 'assistant', ?, ?)
                """,
                (assistant_message_id, run["thread_id"], content, now),
            )
            cursor = connection.execute(
                """
                update model_runs
                set assistant_message_id = ?,
                    status = 'completed',
                    provider_response_id = ?,
                    input_tokens = ?,
                    output_tokens = ?,
                    updated_at = ?,
                    completed_at = ?
                where id = ?
                  and status = 'calling_model'
                """,
                (
                    assistant_message_id,
                    provider_response_id,
                    input_tokens,
                    output_tokens,
                    now,
                    now,
                    model_run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ModelRunNotRetryableError(
                    f"Model run cannot be completed from status: {run['status']}"
                )
            touch_thread(connection, run["thread_id"], now=now)
        return result_for_model_run(connection, model_run_id)


def fail_model_run(
    config: AppConfig,
    model_run_id: str,
    *,
    error_code: str,
    error_message: str,
) -> SendChatResult:
    now = utc_timestamp()
    with initialize_database(config.db_path) as connection:
        run = model_run_row(connection, model_run_id)
        with connection:
            connection.execute(
                """
                update model_runs
                set status = 'failed',
                    error_code = ?,
                    error_message = ?,
                    updated_at = ?,
                    completed_at = ?
                where id = ?
                  and status in ('queued', 'retrieving', 'calling_model')
                """,
                (error_code, error_message, now, now, model_run_id),
            )
            touch_thread(connection, run["thread_id"], now=now)
        return result_for_model_run(connection, model_run_id)


def record_retrieval_run(
    config: AppConfig,
    *,
    thread_id: str,
    message_id: str,
    source_set_id: str | None,
    query: str,
    hits: Sequence[object],
    source_book_ids: Sequence[str] = (),
    source_map: Sequence[object] = (),
    candidates: Sequence[str] = (),
) -> str:
    retrieval_run_id = new_id("retrieval")
    now = utc_timestamp()
    metadata = retrieval_run_metadata(
        source_book_ids=source_book_ids,
        source_map=source_map,
        candidates=candidates,
    )
    with initialize_database(config.db_path) as connection:
        thread_row(connection, thread_id)
        with connection:
            connection.execute(
                """
                insert into retrieval_runs (
                  id,
                  thread_id,
                  message_id,
                  source_set_id,
                  query,
                  metadata_json,
                  created_at
                )
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    retrieval_run_id,
                    thread_id,
                    message_id,
                    source_set_id,
                    query,
                    json.dumps(metadata, sort_keys=True),
                    now,
                ),
            )
            for hit in hits:
                source_object_id = getattr(hit, "source_object_id", None)
                object_type = getattr(hit, "object_type", None)
                heading_path = tuple(getattr(hit, "heading_path", ()) or ())
                rank_reasons = tuple(getattr(hit, "rank_reasons", ()) or ())
                hit_metadata = {
                    "page_start": getattr(hit, "page_start", None),
                    "page_end": getattr(hit, "page_end", None),
                    "page_range_label": getattr(hit, "page_range_label", None),
                }
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
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("retrieval-hit"),
                        retrieval_run_id,
                        getattr(hit, "page_id"),
                        source_object_id,
                        float(getattr(hit, "score")),
                        int(getattr(hit, "rank")),
                        getattr(hit, "snippet"),
                        object_type or "page_fallback",
                        getattr(hit, "object_title", None) or getattr(hit, "title", None),
                        json.dumps(list(heading_path)),
                        getattr(hit, "confidence", None),
                        json.dumps(list(rank_reasons)),
                        getattr(hit, "text_snapshot_sha256", None),
                        json.dumps(hit_metadata, sort_keys=True),
                    ),
                )
    return retrieval_run_id


def retrieval_run_metadata(
    *,
    source_book_ids: Sequence[str],
    source_map: Sequence[object],
    candidates: Sequence[str],
) -> dict[str, object]:
    return {
        "source_book_ids": list(source_book_ids),
        "source_map": [source_map_entry_to_metadata(entry) for entry in source_map],
        "candidates": list(candidates),
    }


def source_map_entry_to_metadata(entry: object) -> dict[str, object]:
    return {
        "book_id": getattr(entry, "book_id", None),
        "title": getattr(entry, "title", None),
        "category": getattr(entry, "category", None),
        "summary": getattr(entry, "summary", None),
        "aliases": list(getattr(entry, "aliases", ()) or ()),
        "best_source_for": list(getattr(entry, "best_source_for", ()) or ()),
        "chapters": list(getattr(entry, "chapters", ()) or ()),
    }


def enabled_book_ids_from_connection(
    connection: sqlite3.Connection,
    source_set_id: str,
) -> tuple[str, ...]:
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
    return tuple(row["book_id"] for row in rows)


def thread_row(connection: sqlite3.Connection, thread_id: str) -> sqlite3.Row:
    row = connection.execute(
        """
        select
          chat_threads.id,
          chat_threads.title,
          chat_threads.active_source_set_id,
          chat_threads.created_at,
          chat_threads.updated_at,
          count(chat_thread_source_books.book_id) as source_book_count
        from chat_threads
        left join chat_thread_source_books
          on chat_thread_source_books.thread_id = chat_threads.id
        where chat_threads.id = ?
        group by chat_threads.id
        """,
        (thread_id,),
    ).fetchone()
    if row is None:
        raise ChatThreadNotFoundError(f"Chat thread not found: {thread_id}")
    return row


def model_run_row(connection: sqlite3.Connection, model_run_id: str) -> sqlite3.Row:
    row = connection.execute(
        """
        select *
        from model_runs
        where id = ?
        """,
        (model_run_id,),
    ).fetchone()
    if row is None:
        raise ModelRunNotFoundError(f"Model run not found: {model_run_id}")
    return row


def model_run_by_idempotency_key(
    connection: sqlite3.Connection,
    idempotency_key: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        select *
        from model_runs
        where idempotency_key = ?
        """,
        (idempotency_key,),
    ).fetchone()


def message_row(connection: sqlite3.Connection, message_id: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        select id, thread_id, role, content, created_at
        from chat_messages
        where id = ?
        """,
        (message_id,),
    ).fetchone()


def result_for_model_run(
    connection: sqlite3.Connection,
    model_run_id: str,
) -> SendChatResult:
    row = model_run_row(connection, model_run_id)
    user_row = message_row(connection, row["user_message_id"])
    if user_row is None:
        raise ModelRunNotRetryableError(f"Model run has no user message: {model_run_id}")
    assistant_row = (
        None
        if row["assistant_message_id"] is None
        else message_row(connection, row["assistant_message_id"])
    )
    return SendChatResult(
        thread=thread_from_row(thread_row(connection, row["thread_id"])),
        user_message=message_from_row(user_row),
        assistant_message=None if assistant_row is None else message_from_row(assistant_row),
        model_run=model_run_from_row(row),
        citations=citations_for_model_run(connection, row),
    )


def load_turns_from_connection(
    connection: sqlite3.Connection,
    thread_id: str,
) -> tuple[ChatTurn, ...]:
    rows = connection.execute(
        """
        select *
        from model_runs
        where thread_id = ?
          and user_message_id is not null
        order by created_at, id
        """,
        (thread_id,),
    ).fetchall()
    turns: list[ChatTurn] = []
    for row in rows:
        user_row = message_row(connection, row["user_message_id"])
        if user_row is None:
            continue
        assistant_row = (
            None
            if row["assistant_message_id"] is None
            else message_row(connection, row["assistant_message_id"])
        )
        turns.append(
            ChatTurn(
                user_message=message_from_row(user_row),
                assistant_message=None
                if assistant_row is None
                else message_from_row(assistant_row),
                model_run=model_run_from_row(row),
                citations=citations_for_model_run(connection, row),
            )
        )
    return tuple(turns)


def citations_for_model_run(
    connection: sqlite3.Connection,
    model_run: sqlite3.Row,
) -> tuple[ChatCitation, ...]:
    retrieval_run_id = model_run["retrieval_run_id"]
    if retrieval_run_id is None:
        return ()
    rows = connection.execute(
        """
        select
          books.id as book_id,
          books.title,
          books.category,
          pages.id as page_id,
          pages.page_number,
          pages.page_label,
          retrieval_hits.snippet,
          retrieval_hits.rank,
          retrieval_hits.score,
          retrieval_hits.metadata_json
        from retrieval_hits
        join pages on pages.id = retrieval_hits.page_id
        join books on books.id = pages.book_id
        where retrieval_hits.retrieval_run_id = ?
        order by retrieval_hits.rank, retrieval_hits.page_id
        """,
        (retrieval_run_id,),
    ).fetchall()
    return tuple(
        ChatCitation(
            book_id=row["book_id"],
            title=row["title"],
            category=row["category"],
            page_id=row["page_id"],
            page_number=row["page_number"],
            pdf_page_number=row["page_number"],
            page_label=row["page_label"],
            snippet=row["snippet"] or "",
            rank=row["rank"],
            score=row["score"],
            page_range_label=retrieval_hit_page_range_label(row["metadata_json"]),
        )
        for row in rows
    )


def retrieval_hit_page_range_label(metadata_json: str | None) -> str | None:
    if not metadata_json:
        return None
    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(metadata, dict):
        return None
    page_range_label = metadata.get("page_range_label")
    return page_range_label if isinstance(page_range_label, str) else None


def touch_thread(
    connection: sqlite3.Connection,
    thread_id: str,
    *,
    now: str,
) -> None:
    connection.execute(
        """
        update chat_threads
        set updated_at = ?
        where id = ?
        """,
        (now, thread_id),
    )


def thread_from_row(row: sqlite3.Row) -> ChatThread:
    return ChatThread(
        id=row["id"],
        title=row["title"],
        active_source_set_id=row["active_source_set_id"],
        source_book_count=int(row["source_book_count"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def message_from_row(row: sqlite3.Row) -> ChatMessage:
    return ChatMessage(
        id=row["id"],
        thread_id=row["thread_id"],
        role=row["role"],
        content=row["content"],
        created_at=row["created_at"],
    )


def model_run_from_row(row: sqlite3.Row) -> ModelRun:
    return ModelRun(
        id=row["id"],
        thread_id=row["thread_id"],
        user_message_id=row["user_message_id"],
        assistant_message_id=row["assistant_message_id"],
        retrieval_run_id=row["retrieval_run_id"],
        retry_of_model_run_id=row["retry_of_model_run_id"],
        status=row["status"],
        provider=row["provider"],
        model=row["model"],
        provider_response_id=row["provider_response_id"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        retryable=row["status"] == "failed",
    )
