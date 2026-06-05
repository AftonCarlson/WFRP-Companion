from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from wfrp_companion.assistant import chat_store
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database, open_connection
from wfrp_companion.library import source_sets


def make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        pdf_root=tmp_path / "pdf-root",
        data_dir=data_dir,
        db_path=data_dir / "wfrp_companion.sqlite",
        asset_dir=data_dir / "library" / "assets",
    )


def insert_folder(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        insert into library_folders (id, parent_id, name, relative_path, sort_order)
        values ('core', null, 'Core', 'Core', 0)
        on conflict(id) do nothing
        """
    )


def insert_book(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    title: str,
    category: str,
) -> None:
    insert_folder(connection)
    connection.execute(
        """
        insert into books (
          id,
          folder_id,
          title,
          category,
          relative_path,
          original_source_path,
          managed_pdf_path,
          original_sha256,
          managed_sha256,
          page_count,
          copy_status,
          text_status,
          search_status,
          visual_status,
          discovered_at,
          updated_at
        )
        values (?, 'core', ?, ?, ?, ?, ?, ?, ?, 1, 'copied', 'imported',
                'indexed', 'not_scanned', '2026-06-04T00:00:00Z',
                '2026-06-04T00:00:00Z')
        """,
        (
            book_id,
            title,
            category,
            f"{category}/{title}.pdf",
            f"/source/{book_id}.pdf",
            f"/managed/{book_id}.pdf",
            f"sha-{book_id}",
            f"sha-{book_id}",
        ),
    )


def seed_books(config: AppConfig) -> None:
    with initialize_database(config.db_path) as connection:
        insert_book(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
        )
        insert_book(
            connection,
            book_id="barony",
            title="Barony of the Damned",
            category="Adventure Modules and Campaigns",
        )
    source_sets.ensure_builtin_source_sets(config)


def count_rows(config: AppConfig, table: str) -> int:
    with open_connection(config.db_path) as connection:
        return connection.execute(f"select count(*) from {table}").fetchone()[0]


def test_create_thread_snapshots_enabled_books(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_books(config)

    thread = chat_store.create_thread(config, title="Rules Help")
    source_sets.set_book_enabled(config, "rules-core", "core-rules", False)
    source_sets.set_book_enabled(config, "rules-core", "barony", True)
    existing_detail = chat_store.get_thread_detail(config, thread.id)
    new_thread = chat_store.create_thread(config, title="Adventure Help")
    new_detail = chat_store.get_thread_detail(config, new_thread.id)

    assert thread.title == "Rules Help"
    assert thread.active_source_set_id == "rules-core"
    assert thread.source_book_count == 1
    assert existing_detail.source_book_ids == ("core-rules",)
    assert new_detail.source_book_ids == ("barony",)


def test_create_thread_requires_active_or_existing_source_set(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_book(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
        )

    with pytest.raises(source_sets.ActiveSourceSetMissingError):
        chat_store.create_thread(config)

    source_sets.ensure_builtin_source_sets(config)
    with pytest.raises(source_sets.SourceSetNotFoundError):
        chat_store.create_thread(config, source_set_id="missing-source-set")


def test_provider_unavailable_send_is_idempotent_and_visible_in_detail(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)

    first = chat_store.create_provider_unavailable_turn(
        config,
        thread.id,
        content="What is dodge?",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )
    duplicate = chat_store.create_provider_unavailable_turn(
        config,
        thread.id,
        content="Different text should not create a duplicate",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )
    detail = chat_store.get_thread_detail(config, thread.id)

    assert first.user_message.content == "What is dodge?"
    assert first.assistant_message is None
    assert first.model_run.status == "failed"
    assert first.model_run.error_code == "provider_unavailable"
    assert first.model_run.retryable is True
    assert duplicate.user_message.id == first.user_message.id
    assert duplicate.model_run.id == first.model_run.id
    assert count_rows(config, "chat_messages") == 1
    assert count_rows(config, "model_runs") == 1
    assert len(detail.turns) == 1
    assert detail.turns[0].model_run.error_code == "provider_unavailable"


def test_provider_unavailable_retry_reuses_original_user_message(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    failed = chat_store.create_provider_unavailable_turn(
        config,
        thread.id,
        content="What is fear?",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )

    retry = chat_store.create_provider_unavailable_retry(
        config,
        failed.model_run.id,
        idempotency_key="retry-1",
        provider="openai",
        model="gpt-5.4-mini",
    )
    duplicate = chat_store.create_provider_unavailable_retry(
        config,
        failed.model_run.id,
        idempotency_key="retry-1",
        provider="openai",
        model="gpt-5.4-mini",
    )

    assert retry.user_message.id == failed.user_message.id
    assert retry.model_run.retry_of_model_run_id == failed.model_run.id
    assert retry.model_run.error_code == "provider_unavailable"
    assert duplicate.model_run.id == retry.model_run.id
    assert count_rows(config, "chat_messages") == 1
    assert count_rows(config, "model_runs") == 2


def test_retry_helpers_reject_non_failed_runs_and_reuse_active_retry(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="What is fear?",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )

    with pytest.raises(chat_store.ModelRunNotRetryableError):
        chat_store.create_provider_unavailable_retry(
            config,
            queued.model_run.id,
            idempotency_key="retry-provider",
            provider="openai",
            model="gpt-5.4-mini",
        )

    with pytest.raises(chat_store.ModelRunNotRetryableError):
        chat_store.create_queued_retry(
            config,
            queued.model_run.id,
            idempotency_key="retry-queued",
            provider="openai",
            model="gpt-5.4-mini",
        )

    failed = chat_store.fail_model_run(
        config,
        queued.model_run.id,
        error_code="provider_error",
        error_message="boom",
    )
    active_retry = chat_store.create_queued_retry(
        config,
        failed.model_run.id,
        idempotency_key="retry-1",
        provider="openai",
        model="gpt-5.4-mini",
    )
    duplicate_active = chat_store.create_queued_retry(
        config,
        failed.model_run.id,
        idempotency_key="retry-2",
        provider="openai",
        model="gpt-5.4-mini",
    )

    assert duplicate_active.model_run.id == active_retry.model_run.id


def test_model_run_transitions_validate_inputs_and_wrong_state_is_noop(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="What is fear?",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )

    with pytest.raises(ValueError, match="from_statuses"):
        chat_store.transition_model_run(
            config,
            queued.model_run.id,
            from_statuses=(),
            to_status="retrieving",
        )

    unchanged = chat_store.transition_model_run(
        config,
        queued.model_run.id,
        from_statuses=("retrieving",),
        to_status="calling_model",
    )

    assert unchanged.model_run.status == "queued"


def test_complete_model_run_is_idempotent_and_rejects_wrong_status(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="What is fear?",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )

    with pytest.raises(chat_store.ModelRunNotRetryableError):
        chat_store.complete_model_run(
            config,
            queued.model_run.id,
            content="too soon",
            provider_response_id=None,
            input_tokens=None,
            output_tokens=None,
        )

    calling = chat_store.transition_model_run(
        config,
        queued.model_run.id,
        from_statuses=("queued",),
        to_status="calling_model",
    )
    completed = chat_store.complete_model_run(
        config,
        calling.model_run.id,
        content="answer",
        provider_response_id="resp-1",
        input_tokens=1,
        output_tokens=2,
    )
    duplicate = chat_store.complete_model_run(
        config,
        calling.model_run.id,
        content="ignored",
        provider_response_id="resp-2",
        input_tokens=3,
        output_tokens=4,
    )

    assert completed.assistant_message is not None
    assert duplicate.assistant_message is not None
    assert duplicate.assistant_message.content == "answer"
    assert count_rows(config, "chat_messages") == 2


def test_result_loading_rejects_or_skips_orphaned_model_runs(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    with open_connection(config.db_path) as connection:
        connection.execute("pragma foreign_keys = off")
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
            values ('orphan-run', ?, 'missing-message', 'fake', 'fake-model',
                    'failed', 'orphan-run', '2026-06-04T00:00:00Z',
                    '2026-06-04T00:00:00Z')
            """,
            (thread.id,),
        )

        with pytest.raises(chat_store.ModelRunNotRetryableError):
            chat_store.result_for_model_run(connection, "orphan-run")

        assert chat_store.load_turns_from_connection(connection, thread.id) == ()
