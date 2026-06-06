from __future__ import annotations

import hashlib
import math
import re
import sqlite3
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.db.migrations import apply_pending_migrations


LOCAL_HASH_PROVIDER = "local-hash"


@dataclass(frozen=True)
class EmbeddingRebuildFailure:
    book_id: str
    reason: str


@dataclass(frozen=True)
class EmbeddingRebuildSummary:
    discovered: int
    indexed: int
    skipped_current: int
    skipped_disabled: int
    stale_recovered: int
    failed: int
    embeddings_written: int
    failures: tuple[EmbeddingRebuildFailure, ...]


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def embeddings_enabled(config: AppConfig) -> bool:
    return config.embedding_provider != "disabled"


def local_hash_embeddings_enabled(config: AppConfig) -> bool:
    return config.embedding_provider == LOCAL_HASH_PROVIDER


def source_object_embeddings_job_id(
    book_id: str,
    embedding_model: str,
    embedding_dimensions: int,
    source_object_snapshot: str,
) -> str:
    return (
        "rebuild_embeddings:"
        f"{book_id}:{embedding_model}:{embedding_dimensions}:{source_object_snapshot}"
    )


def embedding_source_snapshot_sha256(
    connection: sqlite3.Connection,
    book_id: str,
) -> str:
    digest = hashlib.sha256()
    rows = connection.execute(
        """
        select id, book_id, search_text, text_snapshot_sha256
        from source_objects
        where book_id = ?
        order by page_start, page_end, id
        """,
        (book_id,),
    ).fetchall()
    for row in rows:
        for value in (
            row["id"],
            row["book_id"],
            row["search_text"],
            row["text_snapshot_sha256"],
        ):
            digest.update(str(value).encode("utf-8"))
            digest.update(b"\0")
        digest.update(b"\n")
    return digest.hexdigest()


def source_object_embedding_book_ids(
    connection: sqlite3.Connection,
    *,
    book_ids: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    sql = """
        select source_objects.book_id
        from source_objects
        join books on books.id = source_objects.book_id
        where books.copy_status = 'copied'
          and books.text_status = 'imported'
          and books.search_status = 'indexed'
    """
    parameters: list[object] = []
    if book_ids is not None:
        if not book_ids:
            return ()
        placeholders = ",".join("?" for _ in book_ids)
        sql += f" and source_objects.book_id in ({placeholders})"
        parameters.extend(book_ids)
    sql += " group by source_objects.book_id order by source_objects.book_id"
    rows = connection.execute(sql, parameters).fetchall()
    return tuple(row["book_id"] for row in rows)


def ensure_book_retrieval_status_rows(
    connection: sqlite3.Connection,
    book_ids: Sequence[str],
    *,
    now: str,
) -> None:
    for book_id in book_ids:
        connection.execute(
            """
            insert into book_retrieval_status (book_id, updated_at)
            values (?, ?)
            on conflict(book_id) do nothing
            """,
            (book_id, now),
        )


def rebuild_embeddings(
    config: AppConfig,
    *,
    book_ids: tuple[str, ...] | None = None,
    force: bool = False,
    retry_running: bool = False,
    stale_running_minutes: int = 30,
) -> EmbeddingRebuildSummary:
    if not config.db_path.exists():
        initialize_database(config.db_path).close()
    apply_pending_migrations(config.db_path)
    with initialize_database(config.db_path) as connection:
        stale_recovered = recover_stale_embedding_jobs(
            connection,
            retry_running=retry_running,
            stale_running_minutes=stale_running_minutes,
        )
        discovered_book_ids = source_object_embedding_book_ids(
            connection,
            book_ids=book_ids,
        )
        now = utc_timestamp()
        ensure_book_retrieval_status_rows(connection, discovered_book_ids, now=now)

        if not embeddings_enabled(config):
            mark_embeddings_disabled(connection, discovered_book_ids, now=now)
            return EmbeddingRebuildSummary(
                discovered=len(discovered_book_ids),
                indexed=0,
                skipped_current=0,
                skipped_disabled=len(discovered_book_ids),
                stale_recovered=stale_recovered,
                failed=0,
                embeddings_written=0,
                failures=(),
            )

        indexed = 0
        skipped_current = 0
        embeddings_written = 0
        failures: list[EmbeddingRebuildFailure] = []
        for book_id in discovered_book_ids:
            if not local_hash_embeddings_enabled(config):
                reason = f"Unsupported embedding provider: {config.embedding_provider}"
                mark_embedding_failed(connection, book_id=book_id, error=reason, now=now)
                failures.append(EmbeddingRebuildFailure(book_id, reason))
                continue
            if (
                not force
                and source_object_embeddings_current(connection, book_id, config=config)
            ):
                skipped_current += 1
                continue
            try:
                written = rebuild_book_embeddings(
                    connection,
                    book_id=book_id,
                    config=config,
                    now=utc_timestamp(),
                )
            except Exception as exc:  # noqa: BLE001
                reason = f"{type(exc).__name__}: {exc}"
                mark_embedding_failed(
                    connection,
                    book_id=book_id,
                    error=reason,
                    now=utc_timestamp(),
                )
                failures.append(EmbeddingRebuildFailure(book_id, reason))
                continue
            indexed += 1
            embeddings_written += written

    return EmbeddingRebuildSummary(
        discovered=len(discovered_book_ids),
        indexed=indexed,
        skipped_current=skipped_current,
        skipped_disabled=0,
        stale_recovered=stale_recovered,
        failed=len(failures),
        embeddings_written=embeddings_written,
        failures=tuple(failures),
    )


def source_object_embeddings_current(
    connection: sqlite3.Connection,
    book_id: str,
    *,
    config: AppConfig,
) -> bool:
    if not local_hash_embeddings_enabled(config):
        return False
    snapshot = embedding_source_snapshot_sha256(connection, book_id)
    status = connection.execute(
        """
        select vector_status,
               vector_snapshot_sha256,
               embedding_model,
               embedding_dimensions
        from book_retrieval_status
        where book_id = ?
        """,
        (book_id,),
    ).fetchone()
    if status is None:
        return False
    if status["vector_status"] != "indexed":
        return False
    if status["vector_snapshot_sha256"] != snapshot:
        return False
    if status["embedding_model"] != config.embedding_model:
        return False
    if int(status["embedding_dimensions"] or 0) != config.embedding_dimensions:
        return False

    source_count = source_object_count(connection, book_id)
    if source_count == 0:
        return False
    current_count = connection.execute(
        """
        select count(*)
        from source_object_embeddings
        join source_objects
          on source_objects.id = source_object_embeddings.source_object_id
         and source_objects.book_id = source_object_embeddings.book_id
         and source_objects.text_snapshot_sha256 =
             source_object_embeddings.text_snapshot_sha256
        where source_object_embeddings.book_id = ?
          and source_object_embeddings.embedding_model = ?
          and source_object_embeddings.embedding_dimensions = ?
        """,
        (book_id, config.embedding_model, config.embedding_dimensions),
    ).fetchone()[0]
    if current_count != source_count:
        return False
    stale_count = connection.execute(
        """
        select count(*)
        from source_object_embeddings
        left join source_objects
          on source_objects.id = source_object_embeddings.source_object_id
         and source_objects.book_id = source_object_embeddings.book_id
        where source_object_embeddings.book_id = ?
          and source_object_embeddings.embedding_model = ?
          and source_object_embeddings.embedding_dimensions = ?
          and (
            source_objects.id is null
            or source_objects.text_snapshot_sha256 !=
               source_object_embeddings.text_snapshot_sha256
          )
        """,
        (book_id, config.embedding_model, config.embedding_dimensions),
    ).fetchone()[0]
    return stale_count == 0


def source_object_count(connection: sqlite3.Connection, book_id: str) -> int:
    return int(
        connection.execute(
            "select count(*) from source_objects where book_id = ?",
            (book_id,),
        ).fetchone()[0]
    )


def rebuild_book_embeddings(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    config: AppConfig,
    now: str,
) -> int:
    snapshot = embedding_source_snapshot_sha256(connection, book_id)
    job_id = source_object_embeddings_job_id(
        book_id,
        config.embedding_model,
        config.embedding_dimensions,
        snapshot,
    )
    if not claim_embedding_job(connection, book_id=book_id, job_id=job_id, now=now):
        raise RuntimeError("Embedding rebuild job is already running")

    rows = connection.execute(
        """
        select id, book_id, search_text, text_snapshot_sha256
        from source_objects
        where book_id = ?
        order by page_start, page_end, id
        """,
        (book_id,),
    ).fetchall()
    with connection:
        connection.execute(
            """
            update book_retrieval_status
            set vector_status = 'indexing',
                vector_started_at = ?,
                vector_snapshot_sha256 = ?,
                embedding_model = ?,
                embedding_dimensions = ?,
                last_error = null,
                updated_at = ?
            where book_id = ?
            """,
            (
                now,
                snapshot,
                config.embedding_model,
                config.embedding_dimensions,
                now,
                book_id,
            ),
        )
        connection.execute(
            """
            delete from source_object_embeddings
            where book_id = ?
              and embedding_model = ?
              and embedding_dimensions = ?
            """,
            (book_id, config.embedding_model, config.embedding_dimensions),
        )
        for row in rows:
            embedding_id = source_object_embedding_id(
                row["id"],
                config.embedding_model,
                config.embedding_dimensions,
                row["text_snapshot_sha256"],
            )
            vector = text_embedding_vector(
                row["search_text"],
                dimensions=config.embedding_dimensions,
            )
            connection.execute(
                """
                insert into source_object_embeddings (
                  id,
                  source_object_id,
                  book_id,
                  embedding_model,
                  embedding_dimensions,
                  text_snapshot_sha256,
                  vector_blob,
                  created_at,
                  updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    embedding_id,
                    row["id"],
                    row["book_id"],
                    config.embedding_model,
                    config.embedding_dimensions,
                    row["text_snapshot_sha256"],
                    vector_blob(vector),
                    now,
                    now,
                ),
            )
        connection.execute(
            """
            update book_retrieval_status
            set vector_status = 'indexed',
                vector_snapshot_sha256 = ?,
                embedding_model = ?,
                embedding_dimensions = ?,
                last_error = null,
                updated_at = ?
            where book_id = ?
            """,
            (
                snapshot,
                config.embedding_model,
                config.embedding_dimensions,
                now,
                book_id,
            ),
        )
        connection.execute(
            """
            update ingest_jobs
            set status = 'succeeded',
                last_error = null,
                updated_at = ?,
                completed_at = ?
            where idempotency_key = ?
            """,
            (now, now, job_id),
        )
    return len(rows)


def source_object_embedding_id(
    source_object_id: str,
    embedding_model: str,
    embedding_dimensions: int,
    text_snapshot_sha256: str,
) -> str:
    digest = hashlib.sha256(
        f"{source_object_id}\0{embedding_model}\0{embedding_dimensions}\0"
        f"{text_snapshot_sha256}".encode("utf-8")
    ).hexdigest()[:16]
    return f"embedding:{source_object_id}:{digest}"


def claim_embedding_job(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    job_id: str,
    now: str,
) -> bool:
    with connection:
        cursor = connection.execute(
            """
            insert into ingest_jobs (
              id,
              job_type,
              target_id,
              status,
              idempotency_key,
              attempts,
              last_error,
              created_at,
              updated_at,
              completed_at
            )
            values (?, 'rebuild_embeddings', ?, 'running', ?, 1, null, ?, ?, null)
            on conflict(idempotency_key) do update set
              status = 'running',
              attempts = ingest_jobs.attempts + 1,
              last_error = null,
              updated_at = excluded.updated_at,
              completed_at = null
            where ingest_jobs.status in ('queued', 'failed', 'succeeded')
            """,
            (job_id, book_id, job_id, now, now),
        )
    return cursor.rowcount == 1


def recover_stale_embedding_jobs(
    connection: sqlite3.Connection,
    *,
    retry_running: bool,
    stale_running_minutes: int,
) -> int:
    now = utc_timestamp()
    stale_before = (
        datetime.now(timezone.utc).replace(microsecond=0)
        - timedelta(minutes=stale_running_minutes)
    ).isoformat().replace("+00:00", "Z")
    if retry_running:
        rows = connection.execute(
            """
            select target_id
            from ingest_jobs
            where job_type = 'rebuild_embeddings'
              and status = 'running'
            """
        ).fetchall()
    else:
        rows = connection.execute(
            """
            select target_id
            from ingest_jobs
            where job_type = 'rebuild_embeddings'
              and status = 'running'
              and updated_at < ?
            """,
            (stale_before,),
        ).fetchall()
    if not rows:
        return 0
    with connection:
        connection.execute(
            """
            update ingest_jobs
            set status = 'failed',
                last_error = 'Recovered stale embedding rebuild job.',
                updated_at = ?
            where job_type = 'rebuild_embeddings'
              and status = 'running'
              and (? = 1 or updated_at < ?)
            """,
            (now, int(retry_running), stale_before),
        )
        for row in rows:
            if row["target_id"] is None:
                continue
            connection.execute(
                """
                update book_retrieval_status
                set vector_status = 'needs_refresh',
                    last_error = 'Recovered stale embedding rebuild job.',
                    updated_at = ?
                where book_id = ?
                  and vector_status = 'indexing'
                """,
                (now, row["target_id"]),
            )
    return len(rows)


def mark_embeddings_disabled(
    connection: sqlite3.Connection,
    book_ids: Sequence[str],
    *,
    now: str,
) -> None:
    with connection:
        for book_id in book_ids:
            connection.execute(
                """
                update book_retrieval_status
                set vector_status = 'disabled',
                    last_error = null,
                    updated_at = ?
                where book_id = ?
                """,
                (now, book_id),
            )


def mark_embedding_failed(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    error: str,
    now: str,
) -> None:
    with connection:
        connection.execute(
            """
            update book_retrieval_status
            set vector_status = 'failed',
                last_error = ?,
                updated_at = ?
            where book_id = ?
            """,
            (error, now, book_id),
        )


def text_embedding_vector(text: str, *, dimensions: int) -> tuple[float, ...]:
    if dimensions <= 0:
        raise ValueError("dimensions must be positive")
    values = [0.0] * dimensions
    for token in embedding_tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "little") % dimensions
        sign = -1.0 if digest[4] % 2 else 1.0
        values[index] += sign
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        return tuple(values)
    normalized = tuple(value / norm for value in values)
    return vector_from_blob(vector_blob(normalized))


def embedding_tokens(text: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in re.findall(r"(?u)\b[\w'-]+\b", text))


def vector_blob(vector: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def vector_from_blob(blob: bytes) -> tuple[float, ...]:
    if len(blob) % struct.calcsize("<f") != 0:
        raise ValueError("vector blob length must be divisible by 4")
    if not blob:
        return ()
    return struct.unpack(f"<{len(blob) // struct.calcsize('<f')}f", blob)


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vectors must have matching dimensions")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    dot = sum(l_value * r_value for l_value, r_value in zip(left, right, strict=True))
    return dot / (left_norm * right_norm)
