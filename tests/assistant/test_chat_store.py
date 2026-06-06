from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from wfrp_companion.assistant import chat_store
from wfrp_companion.assistant.evidence import RetrievedHit
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database, open_connection
from wfrp_companion.library import page_labels
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


def test_record_retrieval_run_snapshots_source_books_in_relationship_table(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="What sources are checked?",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )

    retrieval_run_id = chat_store.record_retrieval_run(
        config,
        thread_id=thread.id,
        message_id=queued.user_message.id,
        source_set_id=thread.active_source_set_id,
        query="What sources are checked?",
        hits=(),
        source_book_ids=("barony", "missing-book", "core-rules"),
        source_map=(),
        candidates=("checked sources",),
        retrieval_query="What sources are checked?\nchecked source context",
        history_message_ids=("message-history-user", "message-history-assistant"),
        history_turn_count=1,
        history_strategy="followup_contextualized",
    )

    with open_connection(config.db_path) as connection:
        metadata = connection.execute(
            "select metadata_json from retrieval_runs where id = ?",
            (retrieval_run_id,),
        ).fetchone()["metadata_json"]
        rows = connection.execute(
            """
            select source_set_id, book_id, book_title_snapshot
            from retrieval_run_source_books
            where retrieval_run_id = ?
            order by book_id
            """,
            (retrieval_run_id,),
        ).fetchall()

    assert '"source_book_ids": ["barony", "missing-book", "core-rules"]' in metadata
    metadata_dict = json.loads(metadata)
    assert metadata_dict["retrieval_query"] == (
        "What sources are checked?\nchecked source context"
    )
    assert metadata_dict["history_message_ids"] == [
        "message-history-user",
        "message-history-assistant",
    ]
    assert metadata_dict["history_turn_count"] == 1
    assert metadata_dict["history_strategy"] == "followup_contextualized"
    assert [tuple(row) for row in rows] == [
        ("rules-core", "barony", "Barony of the Damned"),
        ("rules-core", "core-rules", "Core Rules"),
    ]


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


def test_thread_detail_collapses_failed_run_after_active_retry(tmp_path: Path) -> None:
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
    active_retry = chat_store.create_queued_retry(
        config,
        failed.model_run.id,
        idempotency_key="retry-1",
        provider="openai",
        model="gpt-5.4-mini",
    )

    detail = chat_store.get_thread_detail(config, thread.id)

    assert len(detail.turns) == 1
    assert detail.turns[0].user_message.id == failed.user_message.id
    assert detail.turns[0].model_run.id == active_retry.model_run.id
    assert detail.turns[0].model_run.status == "queued"
    assert detail.turns[0].model_run.retryable is False


def test_thread_detail_collapses_successful_retry_to_completed_turn(
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
    retry = chat_store.create_queued_retry(
        config,
        failed.model_run.id,
        idempotency_key="retry-1",
        provider="openai",
        model="gpt-5.4-mini",
    )
    chat_store.transition_model_run(
        config,
        retry.model_run.id,
        from_statuses=("queued",),
        to_status="calling_model",
    )
    completed_retry = chat_store.complete_model_run(
        config,
        retry.model_run.id,
        content="Fear answer.",
        provider_response_id="resp-1",
        input_tokens=1,
        output_tokens=2,
    )

    detail = chat_store.get_thread_detail(config, thread.id)

    assert len(detail.turns) == 1
    assert detail.turns[0].user_message.id == failed.user_message.id
    assert detail.turns[0].assistant_message is not None
    assert detail.turns[0].assistant_message.content == "Fear answer."
    assert detail.turns[0].model_run.id == completed_retry.model_run.id
    assert detail.turns[0].model_run.status == "completed"
    assert detail.turns[0].model_run.retryable is False


def test_completed_retry_makes_original_failed_run_non_retryable(
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
    retry = chat_store.create_queued_retry(
        config,
        failed.model_run.id,
        idempotency_key="retry-1",
        provider="openai",
        model="gpt-5.4-mini",
    )
    chat_store.transition_model_run(
        config,
        retry.model_run.id,
        from_statuses=("queued",),
        to_status="calling_model",
    )
    chat_store.complete_model_run(
        config,
        retry.model_run.id,
        content="Fear answer.",
        provider_response_id="resp-1",
        input_tokens=1,
        output_tokens=2,
    )

    with open_connection(config.db_path) as connection:
        reloaded_failed = chat_store.result_for_model_run(
            connection,
            failed.model_run.id,
        )

    assert reloaded_failed.model_run.retryable is False
    with pytest.raises(chat_store.ModelRunNotRetryableError):
        chat_store.create_provider_unavailable_retry(
            config,
            failed.model_run.id,
            idempotency_key="retry-provider-stale",
            provider="openai",
            model="gpt-5.4-mini",
        )
    with pytest.raises(chat_store.ModelRunNotRetryableError):
        chat_store.create_queued_retry(
            config,
            failed.model_run.id,
            idempotency_key="retry-queued-stale",
            provider="openai",
            model="gpt-5.4-mini",
        )


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


def test_retrieval_hit_page_range_label_handles_missing_or_malformed_metadata() -> None:
    assert chat_store.retrieval_hit_page_range_label(None) is None
    assert chat_store.retrieval_hit_page_range_label("{bad json") is None
    assert chat_store.retrieval_hit_page_range_label("[]") is None
    assert (
        chat_store.retrieval_hit_page_range_label('{"page_range_label":"10-11"}')
        == "10-11"
    )


def test_retrieval_hit_page_span_handles_missing_or_malformed_metadata() -> None:
    assert chat_store.retrieval_hit_page_span(None) is None
    assert chat_store.retrieval_hit_page_span("{bad json") is None
    assert chat_store.retrieval_hit_page_span("[]") is None
    assert chat_store.retrieval_hit_page_span('{"page_start":"1","page_end":2}') is None
    assert chat_store.retrieval_hit_page_span('{"page_start":2,"page_end":1}') is None
    assert chat_store.retrieval_hit_page_span('{"page_start":1,"page_end":2}') == (
        1,
        2,
    )


def test_citation_page_range_label_falls_back_to_legacy_metadata() -> None:
    with sqlite3.connect(":memory:") as connection:
        assert (
            chat_store.citation_page_range_label(
                connection,
                {"metadata_json": '{"page_range_label":"10-11"}'},
            )
            == "10-11"
        )


def test_citation_page_range_label_does_not_invent_missing_printed_label(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        connection.execute(
            """
            insert into library_folders (id, parent_id, name, relative_path, sort_order)
            values ('core', null, 'Core', 'Core', 0)
            """
        )
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
            values ('core-rules', 'core', 'Core Rules', 'Core', 'core.pdf',
                    '/source/core.pdf', '/managed/core.pdf', 'source-sha',
                    'managed-sha', 9, 'copied', 'imported', 'indexed',
                    'not_scanned', '2026-06-05T00:00:00Z',
                    '2026-06-05T00:00:00Z')
            """
        )
        connection.execute(
            """
            insert into pages (
              id,
              book_id,
              page_number,
              page_label,
              extraction_method,
              embedded_text_chars,
              text_chars,
              word_count,
              image_count,
              ocr_attempted,
              has_text
            )
            values ('core-rules:9', 'core-rules', 9, null, 'ocr', 0, 12, 2, 0, 1, 1)
            """
        )
        connection.execute(
            """
            insert into book_page_label_calibrations (
              book_id,
              status,
              method,
              calibration_json,
              page_text_snapshot_sha256,
              last_error,
              updated_at
            )
            values (
              'core-rules',
              'needs_review',
              'imported_labels_partial',
              '{"labels_by_page":{},"missing_label_pages":[9]}',
              ?,
              '1 page label needs manual review.',
              '2026-06-05T00:00:00Z'
            )
            """,
            (page_labels.page_label_snapshot_sha256(connection, "core-rules"),),
        )
        row = {
            "book_id": "core-rules",
            "metadata_json": '{"page_start":9,"page_end":9}',
        }
        assert chat_store.citation_page_range_label(connection, row) is None


def test_result_citations_omit_manual_review_printed_page_label(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    calibration_json = (
        '{"labels_by_page":{"1":"1"},'
        '"conflicting_label_pages":[{'
        '"page_number":1,'
        '"imported_label":"9",'
        '"calibrated_label":"1"'
        "}]} "
    ).strip()
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            insert into pages (
              id,
              book_id,
              page_number,
              page_label,
              extraction_method,
              embedded_text_chars,
              text_chars,
              word_count,
              image_count,
              ocr_attempted,
              has_text
            )
            values ('core-rules:1', 'core-rules', 1, '9', 'ocr', 0, 12, 2, 0, 1, 1)
            """
        )
        connection.execute(
            """
            insert into book_page_label_calibrations (
              book_id,
              status,
              method,
              calibration_json,
              page_text_snapshot_sha256,
              last_error,
              updated_at
            )
            values (
              'core-rules',
              'needs_review',
              'offset_anchor_needs_review',
              ?,
              ?,
              '1 page label needs manual review.',
              '2026-06-05T00:00:00Z'
            )
            """,
            (
                calibration_json,
                page_labels.page_label_snapshot_sha256(connection, "core-rules"),
            ),
        )
    thread = chat_store.create_thread(config)
    turn = chat_store.create_provider_unavailable_turn(
        config,
        thread.id,
        content="critical hit",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )
    retrieval_run_id = chat_store.record_retrieval_run(
        config,
        thread_id=thread.id,
        message_id=turn.user_message.id,
        source_set_id=thread.active_source_set_id,
        query="critical hit",
        hits=(
            RetrievedHit(
                book_id="core-rules",
                title="Core Rules",
                category="Core Book & GM Essentials",
                page_id="core-rules:1",
                page_number=1,
                pdf_page_number=1,
                page_label=None,
                snippet="critical hit",
                score=0.1,
                rank=1,
                context_text="critical hit",
                page_start=1,
                page_end=1,
            ),
        ),
        source_book_ids=("core-rules",),
    )

    result = chat_store.attach_retrieval_run(
        config,
        turn.model_run.id,
        retrieval_run_id=retrieval_run_id,
    )

    assert result.citations[0].page_label is None
    assert result.citations[0].page_range_label is None


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
            values ('null-user-run', ?, null, 'fake', 'fake-model',
                    'queued', 'null-user-run', '2026-06-04T00:00:00Z',
                    '2026-06-04T00:00:00Z')
            """,
            (thread.id,),
        )
        null_user_run = chat_store.model_run_row(connection, "null-user-run")

        assert (
            chat_store.has_active_or_completed_logical_successor(
                connection,
                null_user_run,
            )
            is False
        )
        assert chat_store.is_model_run_retryable(connection, null_user_run) is False

        with pytest.raises(chat_store.ModelRunNotRetryableError):
            chat_store.result_for_model_run(connection, "orphan-run")

        assert chat_store.load_turns_from_connection(connection, thread.id) == ()
