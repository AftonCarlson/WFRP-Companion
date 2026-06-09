from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.library.page_labels import load_calibrated_printed_page_label
from wfrp_companion.library.page_labels import load_calibrated_printed_page_range_label
from wfrp_companion.library import source_sets
from wfrp_companion.assistant import agent_planning
from wfrp_companion.assistant import research


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
        if has_active_or_completed_logical_successor(connection, failed_run):
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
        if has_active_or_completed_logical_successor(connection, failed_run):
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
    retrieval_query: str | None = None,
    history_message_ids: Sequence[str] = (),
    history_turn_count: int = 0,
    history_strategy: str = "none",
    diagnostics: research.RetrievalDiagnostics | None = None,
    tool_call_id: str | None = None,
    attempt_number: int | None = None,
    intent: str | None = None,
    resolved_query: str | None = None,
    tool_name: str | None = None,
) -> str:
    retrieval_run_id = new_id("retrieval")
    now = utc_timestamp()
    metadata = retrieval_run_metadata(
        source_book_ids=source_book_ids,
        source_map=source_map,
        candidates=candidates,
        retrieval_query=retrieval_query,
        history_message_ids=history_message_ids,
        history_turn_count=history_turn_count,
        history_strategy=history_strategy,
        diagnostics=diagnostics,
        tool_call_id=tool_call_id,
        attempt_number=attempt_number,
        intent=intent,
        resolved_query=resolved_query,
        tool_name=tool_name,
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
            record_retrieval_run_source_books(
                connection,
                retrieval_run_id=retrieval_run_id,
                source_set_id=source_set_id,
                source_book_ids=source_book_ids,
                captured_at=now,
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


def update_retrieval_run_validation_status(
    config: AppConfig,
    retrieval_run_id: str,
    *,
    validation_status: str,
    validation_summary: dict[str, object],
) -> bool:
    with initialize_database(config.db_path) as connection:
        row = connection.execute(
            """
            select metadata_json
            from retrieval_runs
            where id = ?
            """,
            (retrieval_run_id,),
        ).fetchone()
        if row is None:
            return False
        metadata = research.object_from_json(row["metadata_json"])
        metadata["validation_status"] = validation_status
        metadata["validation_summary"] = validation_summary
        with connection:
            connection.execute(
                """
                update retrieval_runs
                set metadata_json = ?
                where id = ?
                """,
                (json.dumps(metadata, sort_keys=True), retrieval_run_id),
            )
    return True


def record_retrieval_run_source_books(
    connection: sqlite3.Connection,
    *,
    retrieval_run_id: str,
    source_set_id: str | None,
    source_book_ids: Sequence[str],
    captured_at: str,
) -> None:
    for book_id in source_book_ids:
        book = connection.execute(
            "select title from books where id = ?",
            (book_id,),
        ).fetchone()
        if book is None:
            continue
        connection.execute(
            """
            insert into retrieval_run_source_books (
              retrieval_run_id,
              source_set_id,
              book_id,
              book_title_snapshot,
              captured_at
            )
            values (?, ?, ?, ?, ?)
            """,
            (
                retrieval_run_id,
                source_set_id,
                book_id,
                book["title"],
                captured_at,
            ),
        )


def create_familiar_research_run(
    config: AppConfig,
    *,
    model_run_id: str,
    raw_query: str,
    resolved_query: str,
    intent: str,
    max_tool_rounds: int,
    metadata: dict[str, object] | None = None,
) -> research.FamiliarResearchRun:
    now = utc_timestamp()
    with initialize_database(config.db_path) as connection:
        existing = familiar_research_run_by_model_run_id(connection, model_run_id)
        if existing is not None:
            return familiar_research_run_from_row(existing)
        run = model_run_row(connection, model_run_id)
        if run["user_message_id"] is None:
            raise ModelRunNotRetryableError(
                f"Model run has no user message: {model_run_id}"
            )
        thread = thread_row(connection, run["thread_id"])
        research_run_id = new_id("research")
        with connection:
            connection.execute(
                """
                insert or ignore into familiar_research_runs (
                  id,
                  model_run_id,
                  thread_id,
                  user_message_id,
                  source_set_id,
                  raw_query,
                  resolved_query,
                  intent,
                  status,
                  max_tool_rounds,
                  evidence_status,
                  metadata_json,
                  created_at,
                  updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, 'planning', ?, 'not_evaluated',
                        ?, ?, ?)
                """,
                (
                    research_run_id,
                    model_run_id,
                    run["thread_id"],
                    run["user_message_id"],
                    thread["active_source_set_id"],
                    raw_query,
                    resolved_query,
                    intent,
                    max_tool_rounds,
                    research.normalized_json(metadata or {}),
                    now,
                    now,
                ),
            )
        row = familiar_research_run_by_model_run_id(connection, model_run_id)
        if row is None:  # pragma: no cover - defensive after insert-or-ignore.
            raise ModelRunNotFoundError(
                f"Familiar research run not found for model run: {model_run_id}"
            )
        return familiar_research_run_from_row(row)


def transition_familiar_research_run(
    config: AppConfig,
    research_run_id: str,
    *,
    from_statuses: Sequence[str],
    to_status: str,
    evidence_status: str | None = None,
    tool_rounds_used: int | None = None,
    final_retrieval_run_id: str | None = None,
) -> research.FamiliarResearchRun:
    if not from_statuses:
        raise ValueError("from_statuses must not be empty")
    placeholders = ",".join("?" for _ in from_statuses)
    now = utc_timestamp()
    completed_at = now if to_status in {"completed", "insufficient", "failed"} else None
    assignments = ["status = ?", "updated_at = ?"]
    values: list[object] = [to_status, now]
    if evidence_status is not None:
        assignments.append("evidence_status = ?")
        values.append(evidence_status)
    if tool_rounds_used is not None:
        assignments.append("tool_rounds_used = ?")
        values.append(tool_rounds_used)
    if final_retrieval_run_id is not None:
        assignments.append("final_retrieval_run_id = ?")
        values.append(final_retrieval_run_id)
    if completed_at is not None:
        assignments.append("completed_at = ?")
        values.append(completed_at)
    with initialize_database(config.db_path) as connection:
        with connection:
            connection.execute(
                f"""
                update familiar_research_runs
                set {", ".join(assignments)}
                where id = ?
                  and status in ({placeholders})
                """,
                (*values, research_run_id, *from_statuses),
            )
        return familiar_research_run_from_row(
            familiar_research_run_row(connection, research_run_id)
        )


def record_familiar_research_plan(
    config: AppConfig,
    plan: agent_planning.ResearchPlan,
) -> agent_planning.ResearchPlan:
    now = utc_timestamp()
    with initialize_database(config.db_path) as connection:
        existing = familiar_research_plan_row_or_none(connection, plan.id)
        if existing is not None:
            return familiar_research_plan_from_row(existing)
        with connection:
            connection.execute(
                """
                insert into familiar_research_plans (
                  id,
                  research_run_id,
                  revision,
                  status,
                  intent,
                  plan_summary,
                  subject_json,
                  requirements_json,
                  planned_actions_json,
                  provider_call_id,
                  validation_errors_json,
                  created_at,
                  updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.id,
                    plan.research_run_id,
                    plan.revision,
                    plan.status,
                    plan.intent,
                    plan.plan_summary,
                    research.normalized_json(plan.subject.to_json()),
                    research.normalized_json(
                        [requirement.to_json() for requirement in plan.requirements]
                    ),
                    research.normalized_json(
                        [action.to_json() for action in plan.planned_actions]
                    ),
                    plan.provider_call_id,
                    research.normalized_json(list(plan.validation_errors)),
                    now,
                    now,
                ),
            )
        return familiar_research_plan_from_row(
            familiar_research_plan_row(connection, plan.id)
        )


def get_familiar_research_plan(
    config: AppConfig,
    plan_id: str,
) -> agent_planning.ResearchPlan:
    with initialize_database(config.db_path) as connection:
        return familiar_research_plan_from_row(
            familiar_research_plan_row(connection, plan_id)
        )


def record_familiar_tool_call(
    config: AppConfig,
    research_run_id: str,
    *,
    research_plan_id: str | None = None,
    requirement_id: str | None = None,
    purpose: str | None = None,
    step_number: int,
    call_index: int = 0,
    provider_call_id: str | None,
    tool_name: str,
    arguments: dict[str, object],
) -> research.FamiliarToolCall:
    now = utc_timestamp()
    argument_hash = research.normalized_json_hash(arguments)
    with initialize_database(config.db_path) as connection:
        if provider_call_id is not None:
            existing = familiar_tool_call_by_provider_call_id(
                connection,
                research_run_id=research_run_id,
                provider_call_id=provider_call_id,
            )
            if existing is not None:
                return familiar_tool_call_from_row(existing)
        tool_call_id = new_id("tool-call")
        with connection:
            connection.execute(
                """
                insert into familiar_tool_calls (
                  id,
                  research_run_id,
                  research_plan_id,
                  requirement_id,
                  purpose,
                  step_number,
                  call_index,
                  provider_call_id,
                  tool_name,
                  arguments_json,
                  argument_hash,
                  status,
                  created_at,
                  updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'requested', ?, ?)
                """,
                (
                    tool_call_id,
                    research_run_id,
                    research_plan_id,
                    requirement_id,
                    purpose,
                    step_number,
                    call_index,
                    provider_call_id,
                    tool_name,
                    research.normalized_json(arguments),
                    argument_hash,
                    now,
                    now,
                ),
            )
        return familiar_tool_call_from_row(
            familiar_tool_call_row(connection, tool_call_id)
        )


def transition_familiar_tool_call(
    config: AppConfig,
    tool_call_id: str,
    *,
    from_statuses: Sequence[str],
    to_status: str,
    retrieval_run_id: str | None = None,
    output_summary: dict[str, object] | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> research.FamiliarToolCall:
    if not from_statuses:
        raise ValueError("from_statuses must not be empty")
    placeholders = ",".join("?" for _ in from_statuses)
    now = utc_timestamp()
    completed_at = now if to_status in {"succeeded", "failed", "rejected"} else None
    assignments = ["status = ?", "updated_at = ?"]
    values: list[object] = [to_status, now]
    if retrieval_run_id is not None:
        assignments.append("retrieval_run_id = ?")
        values.append(retrieval_run_id)
    if output_summary is not None:
        assignments.append("output_summary_json = ?")
        values.append(research.normalized_json(output_summary))
    if error_code is not None:
        assignments.append("error_code = ?")
        values.append(error_code)
    if error_message is not None:
        assignments.append("error_message = ?")
        values.append(error_message)
    if completed_at is not None:
        assignments.append("completed_at = ?")
        values.append(completed_at)
    with initialize_database(config.db_path) as connection:
        with connection:
            connection.execute(
                f"""
                update familiar_tool_calls
                set {", ".join(assignments)}
                where id = ?
                  and status in ({placeholders})
                """,
                (*values, tool_call_id, *from_statuses),
            )
        return familiar_tool_call_from_row(familiar_tool_call_row(connection, tool_call_id))


def record_familiar_evidence_judgment(
    config: AppConfig,
    *,
    research_run_id: str,
    research_plan_id: str | None = None,
    requirement_id: str | None = None,
    requirement_type: str,
    status: str,
    reason_code: str,
    reasons: Sequence[str] = (),
    retrieval_run_id: str | None = None,
    retrieval_hit_id: str | None = None,
    source_object_id: str | None = None,
    book_id: str | None = None,
    printed_page_label: str | None = None,
    subject_constraint: dict[str, object] | None = None,
    constraint_status: str | None = None,
) -> research.FamiliarEvidenceJudgment:
    judgment_id = new_id("evidence-judgment")
    now = utc_timestamp()
    with initialize_database(config.db_path) as connection:
        with connection:
            connection.execute(
                """
                insert into familiar_evidence_judgments (
                  id,
                  research_run_id,
                  research_plan_id,
                  requirement_id,
                  retrieval_run_id,
                  retrieval_hit_id,
                  source_object_id,
                  book_id,
                  printed_page_label,
                  requirement_type,
                  status,
                  reason_code,
                  reasons_json,
                  subject_constraint_json,
                  constraint_status,
                  created_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    judgment_id,
                    research_run_id,
                    research_plan_id,
                    requirement_id,
                    retrieval_run_id,
                    retrieval_hit_id,
                    source_object_id,
                    book_id,
                    printed_page_label,
                    requirement_type,
                    status,
                    reason_code,
                    research.normalized_json(list(reasons)),
                    research.normalized_json(subject_constraint or {}),
                    constraint_status,
                    now,
                ),
            )
        return familiar_evidence_judgment_from_row(
            familiar_evidence_judgment_row(connection, judgment_id)
        )


def list_familiar_evidence_judgments(
    config: AppConfig,
    research_run_id: str,
) -> tuple[research.FamiliarEvidenceJudgment, ...]:
    with initialize_database(config.db_path) as connection:
        rows = connection.execute(
            """
            select *
            from familiar_evidence_judgments
            where research_run_id = ?
            order by created_at, id
            """,
            (research_run_id,),
        ).fetchall()
    return tuple(familiar_evidence_judgment_from_row(row) for row in rows)


def list_public_research_events(
    config: AppConfig,
    model_run_id: str,
) -> tuple[dict[str, object], ...]:
    with initialize_database(config.db_path) as connection:
        research_run = familiar_research_run_by_model_run_id(
            connection,
            model_run_id,
        )
        if research_run is None:
            return ()
        plan = connection.execute(
            """
            select *
            from familiar_research_plans
            where research_run_id = ?
              and status = 'accepted'
            order by revision desc
            limit 1
            """,
            (research_run["id"],),
        ).fetchone()
        tool_rows = connection.execute(
            """
            select tool_name, requirement_id, purpose, status, step_number
            from familiar_tool_calls
            where research_run_id = ?
            order by step_number, call_index, created_at, id
            """,
            (research_run["id"],),
        ).fetchall()
        judgment_rows = connection.execute(
            """
            select status, reason_code
            from familiar_evidence_judgments
            where research_run_id = ?
            """,
            (research_run["id"],),
        ).fetchall()

    events: list[dict[str, object]] = [
        {
            "type": "research_started",
            "label": "Research started",
            "metadata": {
                "research_run_id": research_run["id"],
                "intent": research_run["intent"],
            },
        }
    ]
    if plan is not None:
        events.append(
            {
                "type": "research_plan",
                "label": "Research plan accepted",
                "metadata": {
                    "research_run_id": research_run["id"],
                    "research_plan_id": plan["id"],
                    "intent": plan["intent"],
                },
            }
        )
    for row in tool_rows:
        events.append(
            {
                "type": "tool_call",
                "label": tool_trace_label(row),
                "metadata": {
                    "tool_name": row["tool_name"],
                    "requirement_id": row["requirement_id"],
                    "status": row["status"],
                    "step_number": row["step_number"],
                },
            }
        )
    if judgment_rows:
        accepted = sum(1 for row in judgment_rows if row["status"] == "accepted")
        partial = sum(1 for row in judgment_rows if row["status"] == "partial")
        rejected = sum(1 for row in judgment_rows if row["status"] == "rejected")
        reason_counts: dict[str, int] = {}
        for row in judgment_rows:
            reason_code = row["reason_code"]
            if reason_code:
                reason_counts[reason_code] = reason_counts.get(reason_code, 0) + 1
        events.append(
            {
                "type": "evidence_validation",
                "label": (
                    f"Evidence {research_run['evidence_status']}; "
                    f"{accepted} accepted, {partial} partial, {rejected} rejected"
                ),
                "metadata": {
                    "evidence_status": research_run["evidence_status"],
                    "accepted_hit_count": accepted,
                    "partial_hit_count": partial,
                    "rejected_hit_count": rejected,
                    "reason_counts": dict(sorted(reason_counts.items())),
                },
            }
        )
    elif research_run["status"] == "failed":
        events.append(
            {
                "type": "failed",
                "label": "Research failed before evidence was accepted",
                "metadata": {"evidence_status": research_run["evidence_status"]},
            }
        )
    return tuple(events)


def tool_trace_label(row: sqlite3.Row) -> str:
    tool_name = row["tool_name"]
    if tool_name == "search_library":
        return "Searched enabled books"
    if tool_name == "open_page":
        return "Opened source page"
    if tool_name == "lookup_source_object":
        return "Inspected source object"
    return f"Ran {tool_name}"


def upsert_chat_thread_context(
    config: AppConfig,
    thread_id: str,
    *,
    active_subject: str | None = None,
    active_intent: str | None = None,
    active_book_id: str | None = None,
    active_printed_page_label: str | None = None,
    active_pdf_page_number: int | None = None,
    active_source_object_id: str | None = None,
    updated_from_message_id: str | None = None,
    updated_from_model_run_id: str | None = None,
    metadata: dict[str, object] | None = None,
) -> research.ChatThreadContext:
    now = utc_timestamp()
    with initialize_database(config.db_path) as connection:
        thread_row(connection, thread_id)
        with connection:
            connection.execute(
                """
                insert into chat_thread_context (
                  thread_id,
                  active_subject,
                  active_intent,
                  active_book_id,
                  active_printed_page_label,
                  active_pdf_page_number,
                  active_source_object_id,
                  updated_from_message_id,
                  updated_from_model_run_id,
                  metadata_json,
                  updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(thread_id) do update set
                  active_subject = excluded.active_subject,
                  active_intent = excluded.active_intent,
                  active_book_id = excluded.active_book_id,
                  active_printed_page_label = excluded.active_printed_page_label,
                  active_pdf_page_number = excluded.active_pdf_page_number,
                  active_source_object_id = excluded.active_source_object_id,
                  updated_from_message_id = excluded.updated_from_message_id,
                  updated_from_model_run_id = excluded.updated_from_model_run_id,
                  metadata_json = excluded.metadata_json,
                  updated_at = excluded.updated_at
                """,
                (
                    thread_id,
                    active_subject,
                    active_intent,
                    active_book_id,
                    active_printed_page_label,
                    active_pdf_page_number,
                    active_source_object_id,
                    updated_from_message_id,
                    updated_from_model_run_id,
                    research.normalized_json(metadata or {}),
                    now,
                ),
            )
        context = chat_thread_context_row(connection, thread_id)
    if context is None:
        raise ChatThreadNotFoundError(f"Chat thread context not found: {thread_id}")
    return chat_thread_context_from_row(context)


def get_chat_thread_context(
    config: AppConfig,
    thread_id: str,
) -> research.ChatThreadContext | None:
    with initialize_database(config.db_path) as connection:
        row = chat_thread_context_row(connection, thread_id)
    return None if row is None else chat_thread_context_from_row(row)


def retrieval_run_metadata(
    *,
    source_book_ids: Sequence[str],
    source_map: Sequence[object],
    candidates: Sequence[str],
    retrieval_query: str | None = None,
    history_message_ids: Sequence[str] = (),
    history_turn_count: int = 0,
    history_strategy: str = "none",
    diagnostics: research.RetrievalDiagnostics | None = None,
    tool_call_id: str | None = None,
    attempt_number: int | None = None,
    intent: str | None = None,
    resolved_query: str | None = None,
    tool_name: str | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "source_book_ids": list(source_book_ids),
        "source_map": [source_map_entry_to_metadata(entry) for entry in source_map],
        "candidates": list(candidates),
    }
    if retrieval_query is not None:
        metadata["retrieval_query"] = retrieval_query
    if history_message_ids:
        metadata["history_message_ids"] = list(history_message_ids)
    if history_turn_count:
        metadata["history_turn_count"] = history_turn_count
    if history_strategy != "none":
        metadata["history_strategy"] = history_strategy
    if diagnostics is not None:
        metadata.update(retrieval_diagnostics_to_metadata(diagnostics))
    if tool_call_id is not None:
        metadata["tool_call_id"] = tool_call_id
    if attempt_number is not None:
        metadata["attempt_number"] = attempt_number
    if intent is not None:
        metadata["intent"] = intent
    if resolved_query is not None:
        metadata["resolved_query"] = resolved_query
    if tool_name is not None:
        metadata["tool_name"] = tool_name
    return metadata


def retrieval_diagnostics_to_metadata(
    diagnostics: research.RetrievalDiagnostics,
) -> dict[str, object]:
    return {
        "diagnostics_schema_version": 1,
        "channel_counts": dict(diagnostics.channel_counts),
        "channel_skip_reasons": dict(diagnostics.channel_skip_reasons),
        "vector_status": diagnostics.vector_status,
        "candidate_count_before_fusion": diagnostics.candidate_count_before_fusion,
        "candidate_count_after_fusion": diagnostics.candidate_count_after_fusion,
        "reranked_count": diagnostics.reranked_count,
        "selected_count": diagnostics.selected_count,
        "page_lookup_attempted": diagnostics.page_lookup_attempted,
        "validation_status": diagnostics.validation_status,
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


def familiar_research_run_row(
    connection: sqlite3.Connection,
    research_run_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        """
        select *
        from familiar_research_runs
        where id = ?
        """,
        (research_run_id,),
    ).fetchone()
    if row is None:
        raise ModelRunNotFoundError(f"Familiar research run not found: {research_run_id}")
    return row


def familiar_research_run_by_model_run_id(
    connection: sqlite3.Connection,
    model_run_id: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        select *
        from familiar_research_runs
        where model_run_id = ?
        """,
        (model_run_id,),
    ).fetchone()


def familiar_tool_call_row(
    connection: sqlite3.Connection,
    tool_call_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        """
        select *
        from familiar_tool_calls
        where id = ?
        """,
        (tool_call_id,),
    ).fetchone()
    if row is None:
        raise ModelRunNotFoundError(f"Familiar tool call not found: {tool_call_id}")
    return row


def familiar_research_plan_row(
    connection: sqlite3.Connection,
    plan_id: str,
) -> sqlite3.Row:
    row = familiar_research_plan_row_or_none(connection, plan_id)
    if row is None:
        raise ModelRunNotFoundError(f"Familiar research plan not found: {plan_id}")
    return row


def familiar_research_plan_row_or_none(
    connection: sqlite3.Connection,
    plan_id: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        select *
        from familiar_research_plans
        where id = ?
        """,
        (plan_id,),
    ).fetchone()


def familiar_tool_call_by_provider_call_id(
    connection: sqlite3.Connection,
    *,
    research_run_id: str,
    provider_call_id: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        select *
        from familiar_tool_calls
        where research_run_id = ?
          and provider_call_id = ?
        """,
        (research_run_id, provider_call_id),
    ).fetchone()


def familiar_evidence_judgment_row(
    connection: sqlite3.Connection,
    judgment_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        """
        select *
        from familiar_evidence_judgments
        where id = ?
        """,
        (judgment_id,),
    ).fetchone()
    if row is None:
        raise ModelRunNotFoundError(
            f"Familiar evidence judgment not found: {judgment_id}"
        )
    return row


def chat_thread_context_row(
    connection: sqlite3.Connection,
    thread_id: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        select *
        from chat_thread_context
        where thread_id = ?
        """,
        (thread_id,),
    ).fetchone()


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
        model_run=model_run_from_row(
            row,
            retryable=is_model_run_retryable(connection, row),
        ),
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
    selected_rows: dict[str, sqlite3.Row] = {}
    selected_user_rows: dict[str, sqlite3.Row] = {}
    user_order: list[str] = []
    for row in rows:
        user_row = message_row(connection, row["user_message_id"])
        if user_row is None:
            continue
        user_message_id = row["user_message_id"]
        if user_message_id not in selected_rows:
            selected_rows[user_message_id] = row
            selected_user_rows[user_message_id] = user_row
            user_order.append(user_message_id)
            continue
        if logical_turn_key(row) >= logical_turn_key(selected_rows[user_message_id]):
            selected_rows[user_message_id] = row
            selected_user_rows[user_message_id] = user_row
    turns: list[ChatTurn] = []
    for user_message_id in user_order:
        row = selected_rows[user_message_id]
        user_row = selected_user_rows[user_message_id]
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
                model_run=model_run_from_row(
                    row,
                    retryable=is_model_run_retryable(connection, row),
                ),
                citations=citations_for_model_run(connection, row),
            )
        )
    return tuple(turns)


def logical_turn_key(row: sqlite3.Row) -> tuple[int, str, str]:
    status = row["status"]
    if status == "completed":
        return (3, row["completed_at"] or row["updated_at"], row["id"])
    if status in {"queued", "retrieving", "calling_model"}:
        return (2, row["created_at"], row["id"])
    return (1, row["created_at"], row["id"])


def load_completed_turn_messages_before_user_message(
    connection: sqlite3.Connection,
    *,
    thread_id: str,
    before_user_message_id: str,
    max_turns: int,
) -> tuple[ChatMessage, ...]:
    if max_turns <= 0:
        return ()
    current_user = message_row(connection, before_user_message_id)
    if current_user is None:
        raise ModelRunNotRetryableError(
            f"Chat message not found: {before_user_message_id}"
        )
    rows = connection.execute(
        """
        select
          user_msg.id as user_message_id,
          user_msg.thread_id as user_thread_id,
          user_msg.content as user_content,
          user_msg.created_at as user_created_at,
          assistant_msg.id as assistant_message_id,
          assistant_msg.thread_id as assistant_thread_id,
          assistant_msg.content as assistant_content,
          assistant_msg.created_at as assistant_created_at
        from model_runs
        join chat_messages as user_msg
          on user_msg.id = model_runs.user_message_id
        join chat_messages as assistant_msg
          on assistant_msg.id = model_runs.assistant_message_id
        where model_runs.thread_id = ?
          and model_runs.status = 'completed'
          and model_runs.user_message_id is not null
          and model_runs.assistant_message_id is not null
          and model_runs.completed_at is not null
          and (
            user_msg.created_at < ?
            or (
              user_msg.created_at = ?
              and user_msg.id < ?
            )
          )
          and (
            assistant_msg.created_at < ?
            or (
              assistant_msg.created_at = ?
              and assistant_msg.id < ?
            )
          )
          and not exists (
            select 1
            from model_runs as newer_completed
            join chat_messages as newer_assistant_msg
              on newer_assistant_msg.id = newer_completed.assistant_message_id
            where newer_completed.thread_id = model_runs.thread_id
              and newer_completed.user_message_id = model_runs.user_message_id
              and newer_completed.status = 'completed'
              and newer_completed.completed_at is not null
              and (
                newer_assistant_msg.created_at < ?
                or (
                  newer_assistant_msg.created_at = ?
                  and newer_assistant_msg.id < ?
                )
              )
              and (
                newer_completed.completed_at > model_runs.completed_at
                or (
                  newer_completed.completed_at = model_runs.completed_at
                  and newer_completed.id > model_runs.id
                )
              )
          )
        order by user_msg.created_at desc, user_msg.id desc
        limit ?
        """,
        (
            thread_id,
            current_user["created_at"],
            current_user["created_at"],
            before_user_message_id,
            current_user["created_at"],
            current_user["created_at"],
            before_user_message_id,
            current_user["created_at"],
            current_user["created_at"],
            before_user_message_id,
            max_turns,
        ),
    ).fetchall()
    messages: list[ChatMessage] = []
    for row in reversed(rows):
        messages.append(
            ChatMessage(
                id=row["user_message_id"],
                thread_id=row["user_thread_id"],
                role="user",
                content=row["user_content"],
                created_at=row["user_created_at"],
            )
        )
        messages.append(
            ChatMessage(
                id=row["assistant_message_id"],
                thread_id=row["assistant_thread_id"],
                role="assistant",
                content=row["assistant_content"],
                created_at=row["assistant_created_at"],
            )
        )
    return tuple(messages)


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
            page_label=load_calibrated_printed_page_label(
                connection,
                book_id=row["book_id"],
                page_number=int(row["page_number"]),
                fallback_label=row["page_label"],
            ),
            snippet=row["snippet"] or "",
            rank=row["rank"],
            score=row["score"],
            page_range_label=citation_page_range_label(connection, row),
        )
        for row in rows
    )


def citation_page_range_label(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> str | None:
    page_span = retrieval_hit_page_span(row["metadata_json"])
    if page_span is not None:
        return load_calibrated_printed_page_range_label(
            connection,
            book_id=row["book_id"],
            page_start=page_span[0],
            page_end=page_span[1],
        )
    return retrieval_hit_page_range_label(row["metadata_json"])


def retrieval_hit_page_span(metadata_json: str | None) -> tuple[int, int] | None:
    if not metadata_json:
        return None
    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(metadata, dict):
        return None
    page_start = metadata.get("page_start")
    page_end = metadata.get("page_end")
    if not isinstance(page_start, int) or not isinstance(page_end, int):
        return None
    if page_start < 1 or page_end < page_start:
        return None
    return (page_start, page_end)


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


def familiar_research_run_from_row(row: sqlite3.Row) -> research.FamiliarResearchRun:
    return research.FamiliarResearchRun(
        id=row["id"],
        model_run_id=row["model_run_id"],
        thread_id=row["thread_id"],
        user_message_id=row["user_message_id"],
        source_set_id=row["source_set_id"],
        raw_query=row["raw_query"],
        resolved_query=row["resolved_query"],
        intent=row["intent"],
        status=row["status"],
        max_tool_rounds=int(row["max_tool_rounds"]),
        tool_rounds_used=int(row["tool_rounds_used"]),
        evidence_status=row["evidence_status"],
        final_retrieval_run_id=row["final_retrieval_run_id"],
        metadata=research.object_from_json(row["metadata_json"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )


def familiar_tool_call_from_row(row: sqlite3.Row) -> research.FamiliarToolCall:
    return research.FamiliarToolCall(
        id=row["id"],
        research_run_id=row["research_run_id"],
        research_plan_id=row["research_plan_id"],
        requirement_id=row["requirement_id"],
        purpose=row["purpose"],
        step_number=int(row["step_number"]),
        call_index=int(row["call_index"]),
        provider_call_id=row["provider_call_id"],
        tool_name=row["tool_name"],
        arguments=research.object_from_json(row["arguments_json"]),
        argument_hash=row["argument_hash"],
        status=row["status"],
        retrieval_run_id=row["retrieval_run_id"],
        output_summary=research.object_from_json(row["output_summary_json"]),
        error_code=row["error_code"],
        error_message=row["error_message"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )


def familiar_research_plan_from_row(row: sqlite3.Row) -> agent_planning.ResearchPlan:
    subject = research.object_from_json(row["subject_json"])
    requirements = json_list_from_string(row["requirements_json"])
    planned_actions = json_list_from_string(row["planned_actions_json"])
    plan = agent_planning.parse_research_plan(
        {
            "intent": row["intent"],
            "plan_summary": row["plan_summary"],
            "subject": subject,
            "requirements": requirements,
            "planned_actions": planned_actions,
        },
        research_run_id=row["research_run_id"],
        plan_id=row["id"],
        revision=int(row["revision"]),
        provider_call_id=row["provider_call_id"],
        status=row["status"],
    )
    return replace(
        plan,
        validation_errors=research.string_tuple_from_json(
            row["validation_errors_json"]
        ),
    )


def familiar_evidence_judgment_from_row(
    row: sqlite3.Row,
) -> research.FamiliarEvidenceJudgment:
    return research.FamiliarEvidenceJudgment(
        id=row["id"],
        research_run_id=row["research_run_id"],
        research_plan_id=row["research_plan_id"],
        requirement_id=row["requirement_id"],
        retrieval_run_id=row["retrieval_run_id"],
        retrieval_hit_id=row["retrieval_hit_id"],
        source_object_id=row["source_object_id"],
        book_id=row["book_id"],
        printed_page_label=row["printed_page_label"],
        requirement_type=row["requirement_type"],
        status=row["status"],
        reason_code=row["reason_code"],
        reasons=research.string_tuple_from_json(row["reasons_json"]),
        subject_constraint=research.object_from_json(row["subject_constraint_json"]),
        constraint_status=row["constraint_status"],
        created_at=row["created_at"],
    )


def chat_thread_context_from_row(row: sqlite3.Row) -> research.ChatThreadContext:
    return research.ChatThreadContext(
        thread_id=row["thread_id"],
        active_subject=row["active_subject"],
        active_intent=row["active_intent"],
        active_book_id=row["active_book_id"],
        active_printed_page_label=row["active_printed_page_label"],
        active_pdf_page_number=row["active_pdf_page_number"],
        active_source_object_id=row["active_source_object_id"],
        updated_from_message_id=row["updated_from_message_id"],
        updated_from_model_run_id=row["updated_from_model_run_id"],
        metadata=research.object_from_json(row["metadata_json"]),
        updated_at=row["updated_at"],
    )


def json_list_from_string(value: str | None) -> list[object]:
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    return decoded if isinstance(decoded, list) else []


def is_model_run_retryable(connection: sqlite3.Connection, row: sqlite3.Row) -> bool:
    if row["status"] != "failed" or row["user_message_id"] is None:
        return False
    return not has_active_or_completed_logical_successor(connection, row)


def has_active_or_completed_logical_successor(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> bool:
    if row["user_message_id"] is None:
        return False
    successor = connection.execute(
        """
        select 1
        from model_runs
        where user_message_id = ?
          and id <> ?
          and status in ('queued', 'retrieving', 'calling_model', 'completed')
        limit 1
        """,
        (row["user_message_id"], row["id"]),
    ).fetchone()
    return successor is not None


def model_run_from_row(row: sqlite3.Row, *, retryable: bool | None = None) -> ModelRun:
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
        retryable=row["status"] == "failed" if retryable is None else retryable,
    )
