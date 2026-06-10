from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from wfrp_companion.assistant import agent_planning, research, turn_contract
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


def test_update_retrieval_run_validation_status_updates_diagnostics_metadata(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="Validate this evidence.",
        idempotency_key="send-validation",
        provider="openai",
        model="gpt-5.4-mini",
    )
    diagnostics = chat_store.research.RetrievalDiagnostics(
        channel_counts={"page_fts": 1},
        channel_skip_reasons={},
        vector_status="disabled",
        candidate_count_before_fusion=1,
        candidate_count_after_fusion=1,
        reranked_count=1,
        selected_count=1,
        page_lookup_attempted=False,
        validation_status="not_evaluated",
    )
    retrieval_run_id = chat_store.record_retrieval_run(
        config,
        thread_id=thread.id,
        message_id=queued.user_message.id,
        source_set_id=thread.active_source_set_id,
        query="Validate this evidence.",
        hits=(),
        diagnostics=diagnostics,
    )

    updated = chat_store.update_retrieval_run_validation_status(
        config,
        retrieval_run_id,
        validation_status="sufficient",
        validation_summary={
            "accepted": 1,
            "rejected": 0,
            "reason_codes": ["statline_evidence"],
        },
    )

    with open_connection(config.db_path) as connection:
        metadata = json.loads(
            connection.execute(
                "select metadata_json from retrieval_runs where id = ?",
                (retrieval_run_id,),
            ).fetchone()["metadata_json"]
        )
    assert updated is True
    assert metadata["validation_status"] == "sufficient"
    assert metadata["validation_summary"] == {
        "accepted": 1,
        "rejected": 0,
        "reason_codes": ["statline_evidence"],
    }


def test_update_retrieval_run_validation_status_returns_false_for_missing_run(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)

    updated = chat_store.update_retrieval_run_validation_status(
        config,
        "missing-retrieval",
        validation_status="insufficient",
        validation_summary={},
    )

    assert updated is False


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


def test_thread_detail_replaces_older_failed_run_with_later_active_retry(
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
    active_retry = chat_store.create_queued_retry(
        config,
        failed.model_run.id,
        idempotency_key="retry-1",
        provider="openai",
        model="gpt-5.4-mini",
    )
    with open_connection(config.db_path) as connection:
        connection.execute(
            "update model_runs set created_at = ? where id = ?",
            ("2026-06-06T00:00:01Z", failed.model_run.id),
        )
        connection.execute(
            "update model_runs set created_at = ? where id = ?",
            ("2026-06-06T00:00:02Z", active_retry.model_run.id),
        )

    detail = chat_store.get_thread_detail(config, thread.id)

    assert len(detail.turns) == 1
    assert detail.turns[0].model_run.id == active_retry.model_run.id


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


def test_familiar_research_run_creation_is_idempotent_and_guarded(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="harpy statline",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )

    created = chat_store.create_familiar_research_run(
        config,
        model_run_id=queued.model_run.id,
        raw_query="harpy statline",
        resolved_query="harpy statline",
        intent="statline_lookup",
        max_tool_rounds=4,
        metadata={"reader_context": {"active_printed_page_label": "99"}},
    )
    duplicate = chat_store.create_familiar_research_run(
        config,
        model_run_id=queued.model_run.id,
        raw_query="ignored duplicate raw query",
        resolved_query="ignored duplicate resolved query",
        intent="ignored_intent",
        max_tool_rounds=2,
    )
    tool_calling = chat_store.transition_familiar_research_run(
        config,
        created.id,
        from_statuses=("planning",),
        to_status="tool_calling",
        tool_rounds_used=1,
    )
    retrieval_run_id = chat_store.record_retrieval_run(
        config,
        thread_id=thread.id,
        message_id=queued.user_message.id,
        source_set_id=thread.active_source_set_id,
        query="harpy statline",
        hits=(),
        source_book_ids=("core-rules",),
    )
    completed = chat_store.transition_familiar_research_run(
        config,
        created.id,
        from_statuses=("tool_calling",),
        to_status="completed",
        evidence_status="sufficient",
        final_retrieval_run_id=retrieval_run_id,
    )
    unchanged = chat_store.transition_familiar_research_run(
        config,
        created.id,
        from_statuses=("planning",),
        to_status="failed",
    )

    assert created.model_run_id == queued.model_run.id
    assert created.thread_id == thread.id
    assert created.user_message_id == queued.user_message.id
    assert created.source_set_id == thread.active_source_set_id
    assert created.status == "planning"
    assert created.evidence_status == "not_evaluated"
    assert created.metadata == {"reader_context": {"active_printed_page_label": "99"}}
    assert duplicate.id == created.id
    assert duplicate.raw_query == "harpy statline"
    assert tool_calling.status == "tool_calling"
    assert tool_calling.tool_rounds_used == 1
    assert completed.status == "completed"
    assert completed.evidence_status == "sufficient"
    assert completed.final_retrieval_run_id == retrieval_run_id
    assert unchanged.status == "completed"
    assert count_rows(config, "familiar_research_runs") == 1


def test_familiar_tool_call_records_arguments_and_guarded_transitions(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="harpy statline",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )
    research_run = chat_store.create_familiar_research_run(
        config,
        model_run_id=queued.model_run.id,
        raw_query="harpy statline",
        resolved_query="harpy statline",
        intent="statline_lookup",
        max_tool_rounds=4,
    )

    tool_call = chat_store.record_familiar_tool_call(
        config,
        research_run.id,
        step_number=1,
        call_index=0,
        provider_call_id="call-1",
        tool_name="search_library",
        arguments={"limit": 8, "query": "harpy statline"},
    )
    duplicate = chat_store.record_familiar_tool_call(
        config,
        research_run.id,
        step_number=99,
        call_index=99,
        provider_call_id="call-1",
        tool_name="search_library",
        arguments={"query": "ignored"},
    )
    running = chat_store.transition_familiar_tool_call(
        config,
        tool_call.id,
        from_statuses=("requested",),
        to_status="running",
    )
    retrieval_run_id = chat_store.record_retrieval_run(
        config,
        thread_id=thread.id,
        message_id=queued.user_message.id,
        source_set_id=thread.active_source_set_id,
        query="harpy statline",
        hits=(),
        source_book_ids=("core-rules",),
    )
    succeeded = chat_store.transition_familiar_tool_call(
        config,
        tool_call.id,
        from_statuses=("running",),
        to_status="succeeded",
        retrieval_run_id=retrieval_run_id,
        output_summary={"accepted_candidate_count": 1},
    )
    unchanged = chat_store.transition_familiar_tool_call(
        config,
        tool_call.id,
        from_statuses=("requested",),
        to_status="failed",
        error_code="too_late",
        error_message="terminal calls are not rewritten",
    )

    assert tool_call.arguments == {"limit": 8, "query": "harpy statline"}
    assert tool_call.argument_hash == research.normalized_json_hash(
        {"limit": 8, "query": "harpy statline"}
    )
    assert duplicate.id == tool_call.id
    assert running.status == "running"
    assert succeeded.status == "succeeded"
    assert succeeded.retrieval_run_id == retrieval_run_id
    assert succeeded.output_summary == {"accepted_candidate_count": 1}
    assert unchanged.status == "succeeded"
    assert unchanged.error_code is None
    assert count_rows(config, "familiar_tool_calls") == 1


def test_familiar_research_plan_and_requirement_linkage_round_trip(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="harpy statline",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )
    research_run = chat_store.create_familiar_research_run(
        config,
        model_run_id=queued.model_run.id,
        raw_query="harpy statline",
        resolved_query="harpy statline",
        intent="statline_lookup",
        max_tool_rounds=4,
    )
    plan = agent_planning.ResearchPlan(
        id="plan-1",
        research_run_id=research_run.id,
        revision=1,
        intent="statline_lookup",
        plan_summary="Find Harpy statline evidence.",
        subject=agent_planning.SubjectConstraint(
            canonical="harpy",
            surface="harpy",
            include_terms=("harpy",),
        ),
        requirements=(
            agent_planning.EvidenceRequirement(
                id="harpy_stats",
                requirement_type="statline_evidence",
                subject=agent_planning.SubjectConstraint(
                    canonical="harpy",
                    surface="harpy",
                    include_terms=("harpy",),
                ),
                object_type_hints=("stat_block", "monster_profile"),
            ),
        ),
        planned_actions=(
            agent_planning.PlannedAction(
                tool_name="search_library",
                requirement_id="harpy_stats",
                purpose="Find a Harpy stat block.",
                arguments={
                    "query": "harpy statline",
                    "intent": "statline_lookup",
                    "subject": "harpy",
                    "limit": 8,
                    "include_terms": ["harpy"],
                    "exclude_terms": [],
                    "object_type_hints": ["stat_block", "monster_profile"],
                    "book_title_hints": [],
                    "page_hints": [],
                },
            ),
        ),
        provider_call_id="call-plan",
    )

    stored = chat_store.record_familiar_research_plan(config, plan)
    duplicate = chat_store.record_familiar_research_plan(config, plan)
    tool_call = chat_store.record_familiar_tool_call(
        config,
        research_run.id,
        research_plan_id=stored.id,
        requirement_id="harpy_stats",
        purpose="Find a Harpy stat block.",
        step_number=1,
        provider_call_id="call-tool",
        tool_name="search_library",
        arguments={"query": "harpy statline"},
    )
    judgment = chat_store.record_familiar_evidence_judgment(
        config,
        research_run_id=research_run.id,
        research_plan_id=stored.id,
        requirement_id="harpy_stats",
        requirement_type="statline_evidence",
        status="rejected",
        reason_code="missing_statline_markers",
        reasons=("No statline markers.",),
        subject_constraint={
            "canonical": "harpy",
            "include_terms": ["harpy"],
            "exclude_terms": [],
        },
        constraint_status="failed",
    )
    chat_store.transition_familiar_research_run(
        config,
        research_run.id,
        from_statuses=("planning",),
        to_status="insufficient",
        evidence_status="partial",
    )
    reloaded = chat_store.get_familiar_research_plan(config, stored.id)
    public_events = chat_store.list_public_research_events(config, queued.model_run.id)

    assert stored == plan
    assert duplicate == plan
    assert reloaded == plan
    assert tool_call.research_plan_id == stored.id
    assert tool_call.requirement_id == "harpy_stats"
    assert tool_call.purpose == "Find a Harpy stat block."
    assert judgment.research_plan_id == stored.id
    assert judgment.requirement_id == "harpy_stats"
    assert judgment.subject_constraint == {
        "canonical": "harpy",
        "include_terms": ["harpy"],
        "exclude_terms": [],
    }
    assert judgment.constraint_status == "failed"
    assert public_events[-1]["label"] == (
        "Evidence partial; 0 accepted, 0 partial, 1 rejected"
    )
    assert public_events[-1]["metadata"] == {
        "evidence_status": "partial",
        "accepted_hit_count": 0,
        "partial_hit_count": 0,
        "rejected_hit_count": 1,
        "reason_counts": {"missing_statline_markers": 1},
    }
    assert count_rows(config, "familiar_research_plans") == 1


def test_familiar_turn_decision_round_trip_and_missing_edges(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="hello",
        idempotency_key="turn-decision",
        provider="openai",
        model="gpt-test",
    )
    decision = turn_contract.TurnDecision(
        turn_kind="conversation",
        answer_mode="direct",
        subject=None,
        confidence="high",
        reasons=("greeting_or_social_text",),
        reader_context_policy="ignore",
    )

    created = chat_store.record_familiar_turn_decision(
        config,
        model_run_id=queued.model_run.id,
        decision=decision,
    )
    duplicate = chat_store.record_familiar_turn_decision(
        config,
        model_run_id=queued.model_run.id,
        decision=decision,
    )
    updated = chat_store.update_familiar_turn_decision_outcome(
        config,
        model_run_id=queued.model_run.id,
        answer_outcome="direct_response",
        outcome={"local_response": True},
    )
    with open_connection(config.db_path) as connection:
        fetched = chat_store.familiar_turn_decision_row(connection, created.id)
        with pytest.raises(chat_store.ModelRunNotFoundError):
            chat_store.familiar_turn_decision_row(connection, "missing-decision")
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
            values ('turn-run-without-user', ?, null, 'fake', 'fake-model',
                    'queued', 'turn-run-without-user', '2026-06-09T00:00:00Z',
                    '2026-06-09T00:00:00Z')
            """,
            (thread.id,),
        )

    assert duplicate == created
    assert updated.answer_outcome == "direct_response"
    assert updated.outcome == {"local_response": True}
    assert fetched["id"] == created.id
    with pytest.raises(chat_store.ModelRunNotRetryableError, match="no user message"):
        chat_store.record_familiar_turn_decision(
            config,
            model_run_id="turn-run-without-user",
            decision=decision,
        )
    with pytest.raises(chat_store.ModelRunNotFoundError):
        chat_store.update_familiar_turn_decision_outcome(
            config,
            model_run_id="missing-model-run",
            answer_outcome="direct_response",
        )


def test_retry_turn_decision_copies_original_contract(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    original = chat_store.create_queued_turn(
        config,
        thread.id,
        content="what happens if I have no armor?",
        idempotency_key="send-original",
        provider="openai",
        model="gpt-test",
    )
    original_decision = chat_store.record_familiar_turn_decision(
        config,
        model_run_id=original.model_run.id,
        decision=turn_contract.TurnDecision(
            turn_kind="rules_lookup",
            answer_mode="research",
            subject="what happens if I have no armor?",
            confidence="medium",
            reasons=("rules_terms",),
            reader_context_policy="routing_hint",
        ),
    )
    chat_store.fail_model_run(
        config,
        original.model_run.id,
        error_code="provider_error",
        error_message="provider failed",
    )
    retry = chat_store.create_queued_retry(
        config,
        original.model_run.id,
        idempotency_key="retry-original",
        provider="openai",
        model="gpt-test",
    )

    retry_decision = chat_store.record_familiar_turn_decision(
        config,
        model_run_id=retry.model_run.id,
        decision=turn_contract.TurnDecision(
            turn_kind="conversation",
            answer_mode="direct",
            subject=None,
            confidence="high",
            reasons=("greeting_or_social_text",),
            reader_context_policy="ignore",
        ),
    )

    assert retry_decision.retry_of_decision_id == original_decision.id
    assert retry_decision.turn_kind == original_decision.turn_kind
    assert retry_decision.answer_mode == original_decision.answer_mode
    assert retry_decision.subject == original_decision.subject
    assert retry_decision.confidence == original_decision.confidence
    assert retry_decision.reasons == original_decision.reasons
    assert retry_decision.reader_context_policy == (
        original_decision.reader_context_policy
    )
    assert retry_decision.metadata == {
        "retry_of_model_run_id": original.model_run.id,
        "copied_from_retry_of_decision_id": original_decision.id,
    }


def test_public_research_events_cover_failed_and_tool_fallback_labels(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="harpy statline",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )
    research_run = chat_store.create_familiar_research_run(
        config,
        model_run_id=queued.model_run.id,
        raw_query="harpy statline",
        resolved_query="harpy statline",
        intent="statline_lookup",
        max_tool_rounds=4,
    )
    for index, tool_name in enumerate(
        ("search_library", "open_page", "lookup_source_object", "custom_tool"),
        start=1,
    ):
        chat_store.record_familiar_tool_call(
            config,
            research_run.id,
            step_number=index,
            provider_call_id=f"call-tool-{index}",
            tool_name=tool_name,
            arguments={"query": "harpy statline"},
        )
    chat_store.transition_familiar_research_run(
        config,
        research_run.id,
        from_statuses=("planning",),
        to_status="failed",
        evidence_status="insufficient",
    )

    events = chat_store.list_public_research_events(config, queued.model_run.id)

    assert [event["label"] for event in events] == [
        "Research started",
        "Searched enabled books",
        "Opened source page",
        "Inspected source object",
        "Ran custom_tool",
        "Research failed before evidence was accepted",
    ]
    assert "resolved_query" not in events[0]["metadata"]
    assert chat_store.list_public_research_events(config, "missing-run") == ()


def test_research_plan_row_and_json_list_edge_cases(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    with open_connection(config.db_path) as connection:
        with pytest.raises(chat_store.ModelRunNotFoundError):
            chat_store.familiar_research_plan_row(connection, "missing-plan")

    assert chat_store.json_list_from_string(None) == []
    assert chat_store.json_list_from_string("{bad json") == []
    assert chat_store.json_list_from_string("{}") == []
    assert chat_store.json_list_from_string("[1, 2]") == [1, 2]


def test_familiar_evidence_judgments_and_thread_context_round_trip(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="harpy statline",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )
    research_run = chat_store.create_familiar_research_run(
        config,
        model_run_id=queued.model_run.id,
        raw_query="harpy statline",
        resolved_query="harpy statline",
        intent="statline_lookup",
        max_tool_rounds=4,
    )

    judgment = chat_store.record_familiar_evidence_judgment(
        config,
        research_run_id=research_run.id,
        requirement_type="statline_markers_present",
        status="accepted",
        reason_code="structured_stat_block",
        reasons=("matched subject", "matched stat markers"),
        book_id="core-rules",
        printed_page_label="99",
    )
    chat_store.upsert_chat_thread_context(
        config,
        thread.id,
        active_subject="harpy",
        active_intent="statline_lookup",
        active_book_id="core-rules",
        active_printed_page_label="99",
        active_pdf_page_number=101,
        updated_from_message_id=queued.user_message.id,
        updated_from_model_run_id=queued.model_run.id,
        metadata={"source": "validated_evidence"},
    )
    reloaded_context = chat_store.get_chat_thread_context(config, thread.id)
    judgments = chat_store.list_familiar_evidence_judgments(
        config,
        research_run.id,
    )

    assert judgment.reasons == ("matched subject", "matched stat markers")
    assert judgments == (judgment,)
    assert reloaded_context == research.ChatThreadContext(
        thread_id=thread.id,
        active_subject="harpy",
        active_intent="statline_lookup",
        active_book_id="core-rules",
        active_printed_page_label="99",
        active_pdf_page_number=101,
        active_source_object_id=None,
        updated_from_message_id=queued.user_message.id,
        updated_from_model_run_id=queued.model_run.id,
        metadata={"source": "validated_evidence"},
        updated_at=reloaded_context.updated_at if reloaded_context else "",
    )


def test_familiar_research_store_rejects_invalid_lifecycle_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="harpy statline",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )
    research_run = chat_store.create_familiar_research_run(
        config,
        model_run_id=queued.model_run.id,
        raw_query="harpy statline",
        resolved_query="harpy statline",
        intent="statline_lookup",
        max_tool_rounds=4,
    )
    tool_call = chat_store.record_familiar_tool_call(
        config,
        research_run.id,
        step_number=1,
        provider_call_id=None,
        tool_name="search_library",
        arguments={},
    )

    with pytest.raises(ValueError, match="from_statuses"):
        chat_store.transition_familiar_research_run(
            config,
            research_run.id,
            from_statuses=(),
            to_status="tool_calling",
        )
    with pytest.raises(ValueError, match="from_statuses"):
        chat_store.transition_familiar_tool_call(
            config,
            tool_call.id,
            from_statuses=(),
            to_status="running",
        )
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
            values ('run-without-user', ?, null, 'fake', 'fake-model',
                    'queued', 'run-without-user', '2026-06-09T00:00:00Z',
                    '2026-06-09T00:00:00Z')
            """,
            (thread.id,),
        )
    with pytest.raises(chat_store.ModelRunNotRetryableError, match="no user message"):
        chat_store.create_familiar_research_run(
            config,
            model_run_id="run-without-user",
            raw_query="orphan",
            resolved_query="orphan",
            intent="unknown",
            max_tool_rounds=4,
        )
    with open_connection(config.db_path) as connection:
        with pytest.raises(chat_store.ModelRunNotFoundError, match="research run"):
            chat_store.familiar_research_run_row(connection, "missing-research")
        with pytest.raises(chat_store.ModelRunNotFoundError, match="tool call"):
            chat_store.familiar_tool_call_row(connection, "missing-tool")
        with pytest.raises(chat_store.ModelRunNotFoundError, match="evidence judgment"):
            chat_store.familiar_evidence_judgment_row(connection, "missing-judgment")

    monkeypatch.setattr(chat_store, "chat_thread_context_row", lambda *_: None)
    with pytest.raises(chat_store.ChatThreadNotFoundError, match="context not found"):
        chat_store.upsert_chat_thread_context(config, thread.id, active_subject="harpy")
