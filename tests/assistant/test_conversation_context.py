from __future__ import annotations

import sqlite3
from pathlib import Path

from wfrp_companion.assistant import chat_store, conversation_context
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database, open_connection
from wfrp_companion.library import source_sets


def make_config(
    tmp_path: Path,
    *,
    prompt_turn_limit: int = 6,
    prompt_char_limit: int = 2500,
    retrieval_turn_limit: int = 3,
    retrieval_query_char_limit: int = 900,
) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        pdf_root=tmp_path / "pdf-root",
        data_dir=data_dir,
        db_path=data_dir / "wfrp_companion.sqlite",
        asset_dir=data_dir / "library" / "assets",
        chat_prompt_history_turn_limit=prompt_turn_limit,
        chat_prompt_history_char_limit=prompt_char_limit,
        chat_retrieval_history_turn_limit=retrieval_turn_limit,
        chat_retrieval_query_char_limit=retrieval_query_char_limit,
    )


def insert_folder(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        insert into library_folders (id, parent_id, name, relative_path, sort_order)
        values ('core', null, 'Core', 'Core', 0)
        on conflict(id) do nothing
        """
    )


def seed_books(config: AppConfig) -> None:
    with initialize_database(config.db_path) as connection:
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
            values ('core-rules', 'core', 'Core Rules',
                    'Core Book & GM Essentials', 'core.pdf', '/source/core.pdf',
                    '/managed/core.pdf', 'source-sha', 'managed-sha', 1,
                    'copied', 'imported', 'indexed', 'not_scanned',
                    '2026-06-04T00:00:00Z', '2026-06-04T00:00:00Z')
            """
        )
    source_sets.ensure_builtin_source_sets(config)


def complete_turn(
    config: AppConfig,
    thread_id: str,
    *,
    content: str,
    answer: str,
    idempotency_key: str,
) -> chat_store.SendChatResult:
    queued = chat_store.create_queued_turn(
        config,
        thread_id,
        content=content,
        idempotency_key=idempotency_key,
        provider="openai",
        model="gpt-5.4-mini",
    )
    chat_store.transition_model_run(
        config,
        queued.model_run.id,
        from_statuses=("queued",),
        to_status="calling_model",
    )
    return chat_store.complete_model_run(
        config,
        queued.model_run.id,
        content=answer,
        provider_response_id=None,
        input_tokens=None,
        output_tokens=None,
    )


def set_turn_times(
    config: AppConfig,
    result: chat_store.SendChatResult,
    *,
    user_time: str,
    assistant_time: str | None = None,
    run_time: str | None = None,
) -> None:
    with open_connection(config.db_path) as connection:
        connection.execute(
            "update chat_messages set created_at = ? where id = ?",
            (user_time, result.user_message.id),
        )
        if result.assistant_message is not None and assistant_time is not None:
            connection.execute(
                "update chat_messages set created_at = ? where id = ?",
                (assistant_time, result.assistant_message.id),
            )
        if run_time is not None:
            connection.execute(
                """
                update model_runs
                set created_at = ?, updated_at = ?, completed_at = ?
                where id = ?
                """,
                (run_time, run_time, assistant_time or run_time, result.model_run.id),
            )


def test_conversation_context_selects_completed_history_and_excludes_failed_or_active(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    completed = complete_turn(
        config,
        thread.id,
        content="Tell me about Captain Alder.",
        answer="Captain Alder wears a bright mail coat.",
        idempotency_key="send-1",
    )
    failed = chat_store.create_provider_unavailable_turn(
        config,
        thread.id,
        content="This failed turn should stay out.",
        idempotency_key="failed-1",
        provider="openai",
        model="gpt-5.4-mini",
    )
    active = chat_store.create_queued_turn(
        config,
        thread.id,
        content="This active turn should stay out.",
        idempotency_key="active-1",
        provider="openai",
        model="gpt-5.4-mini",
    )
    current = chat_store.create_queued_turn(
        config,
        thread.id,
        content="What about his armor?",
        idempotency_key="current-1",
        provider="openai",
        model="gpt-5.4-mini",
    )
    set_turn_times(
        config,
        completed,
        user_time="2026-06-06T00:00:01Z",
        assistant_time="2026-06-06T00:00:02Z",
        run_time="2026-06-06T00:00:02Z",
    )
    set_turn_times(config, failed, user_time="2026-06-06T00:00:03Z")
    set_turn_times(config, active, user_time="2026-06-06T00:00:04Z")
    set_turn_times(config, current, user_time="2026-06-06T00:00:05Z")

    context = conversation_context.build_conversation_context(
        config,
        thread_id=thread.id,
        current_user_message_id=current.user_message.id,
        current_user_content=current.user_message.content,
    )

    assert [(message.role, message.content) for message in context.prompt_messages] == [
        ("user", "Tell me about Captain Alder."),
        ("assistant", "Captain Alder wears a bright mail coat."),
    ]
    assert context.history_message_ids == (
        completed.user_message.id,
        completed.assistant_message.id,
    )
    assert context.history_turn_count == 1
    assert context.retrieval_query.startswith("What about his armor?")
    assert context.history_strategy in {"self_contained", "followup_contextualized"}


def test_conversation_context_for_retry_anchors_before_original_user_message(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    first = complete_turn(
        config,
        thread.id,
        content="Tell me about Captain Alder.",
        answer="Captain Alder wears mail.",
        idempotency_key="send-1",
    )
    failed = chat_store.create_provider_unavailable_turn(
        config,
        thread.id,
        content="What about his armor?",
        idempotency_key="failed-1",
        provider="openai",
        model="gpt-5.4-mini",
    )
    later = complete_turn(
        config,
        thread.id,
        content="Tell me about Lantern Ford.",
        answer="Lantern Ford is unrelated to Captain Alder.",
        idempotency_key="send-later",
    )
    retry = chat_store.create_queued_retry(
        config,
        failed.model_run.id,
        idempotency_key="retry-1",
        provider="openai",
        model="gpt-5.4-mini",
    )
    set_turn_times(
        config,
        first,
        user_time="2026-06-06T00:00:01Z",
        assistant_time="2026-06-06T00:00:02Z",
        run_time="2026-06-06T00:00:02Z",
    )
    set_turn_times(config, failed, user_time="2026-06-06T00:00:03Z")
    set_turn_times(
        config,
        later,
        user_time="2026-06-06T00:00:04Z",
        assistant_time="2026-06-06T00:00:05Z",
        run_time="2026-06-06T00:00:05Z",
    )

    context = conversation_context.build_conversation_context(
        config,
        thread_id=thread.id,
        current_user_message_id=retry.user_message.id,
        current_user_content=retry.user_message.content,
    )

    assert [message.content for message in context.prompt_messages] == [
        "Tell me about Captain Alder.",
        "Captain Alder wears mail.",
    ]
    assert "Lantern Ford" not in "\n".join(
        message.content for message in context.prompt_messages
    )


def test_conversation_context_prompt_budget_prefers_recent_complete_turns(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, prompt_turn_limit=6, prompt_char_limit=80)
    seed_books(config)
    thread = chat_store.create_thread(config)
    older = complete_turn(
        config,
        thread.id,
        content="Older question about Amber Bridge.",
        answer="Older answer should be trimmed away.",
        idempotency_key="send-older",
    )
    newer = complete_turn(
        config,
        thread.id,
        content="Newer question about Captain Alder.",
        answer="Newer answer mentions mail.",
        idempotency_key="send-newer",
    )
    current = chat_store.create_queued_turn(
        config,
        thread.id,
        content="What about his armor?",
        idempotency_key="current",
        provider="openai",
        model="gpt-5.4-mini",
    )
    set_turn_times(
        config,
        older,
        user_time="2026-06-06T00:00:01Z",
        assistant_time="2026-06-06T00:00:02Z",
        run_time="2026-06-06T00:00:02Z",
    )
    set_turn_times(
        config,
        newer,
        user_time="2026-06-06T00:00:03Z",
        assistant_time="2026-06-06T00:00:04Z",
        run_time="2026-06-06T00:00:04Z",
    )
    set_turn_times(config, current, user_time="2026-06-06T00:00:05Z")

    context = conversation_context.build_conversation_context(
        config,
        thread_id=thread.id,
        current_user_message_id=current.user_message.id,
        current_user_content=current.user_message.content,
    )

    contents = [message.content for message in context.prompt_messages]
    assert contents == [
        "Newer question about Captain Alder.",
        "Newer answer mentions mail.",
    ]
    assert all("Amber Bridge" not in content for content in contents)


def test_conversation_context_prompt_turn_limit_is_separate_from_retrieval_history(
    tmp_path: Path,
) -> None:
    config = make_config(
        tmp_path,
        prompt_turn_limit=0,
        prompt_char_limit=500,
        retrieval_turn_limit=1,
        retrieval_query_char_limit=500,
    )
    seed_books(config)
    thread = chat_store.create_thread(config)
    completed = complete_turn(
        config,
        thread.id,
        content="Tell me about Captain Alder.",
        answer="Captain Alder wears mail.",
        idempotency_key="send-1",
    )
    current = chat_store.create_queued_turn(
        config,
        thread.id,
        content="What about it?",
        idempotency_key="current",
        provider="openai",
        model="gpt-5.4-mini",
    )
    set_turn_times(
        config,
        completed,
        user_time="2026-06-06T00:00:01Z",
        assistant_time="2026-06-06T00:00:02Z",
        run_time="2026-06-06T00:00:02Z",
    )
    set_turn_times(config, current, user_time="2026-06-06T00:00:03Z")

    context = conversation_context.build_conversation_context(
        config,
        thread_id=thread.id,
        current_user_message_id=current.user_message.id,
        current_user_content=current.user_message.content,
    )

    assert context.prompt_messages == ()
    assert context.history_strategy == "followup_contextualized"
    assert "Captain Alder" in context.retrieval_query
    assert context.history_message_ids == (
        completed.user_message.id,
        completed.assistant_message.id,
    )
    assert context.history_turn_count == 1


def test_history_aware_retrieval_query_leaves_self_contained_query_unchanged(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    completed = complete_turn(
        config,
        thread.id,
        content="Tell me about Captain Alder.",
        answer="Captain Alder wears mail.",
        idempotency_key="send-1",
    )
    current = chat_store.create_queued_turn(
        config,
        thread.id,
        content="How does Captain Alder use armor in combat?",
        idempotency_key="current",
        provider="openai",
        model="gpt-5.4-mini",
    )
    set_turn_times(
        config,
        completed,
        user_time="2026-06-06T00:00:01Z",
        assistant_time="2026-06-06T00:00:02Z",
        run_time="2026-06-06T00:00:02Z",
    )
    set_turn_times(config, current, user_time="2026-06-06T00:00:03Z")

    context = conversation_context.build_conversation_context(
        config,
        thread_id=thread.id,
        current_user_message_id=current.user_message.id,
        current_user_content=current.user_message.content,
    )

    assert context.retrieval_query == "How does Captain Alder use armor in combat?"
    assert context.history_strategy == "self_contained"


def test_history_aware_retrieval_query_does_not_contextualize_standalone_phrase(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)
    completed = complete_turn(
        config,
        thread.id,
        content="Tell me about Captain Alder.",
        answer="Captain Alder wears mail.",
        idempotency_key="send-1",
    )
    current = chat_store.create_queued_turn(
        config,
        thread.id,
        content="What about Bretonnian knightly careers?",
        idempotency_key="current",
        provider="openai",
        model="gpt-5.4-mini",
    )
    set_turn_times(
        config,
        completed,
        user_time="2026-06-06T00:00:01Z",
        assistant_time="2026-06-06T00:00:02Z",
        run_time="2026-06-06T00:00:02Z",
    )
    set_turn_times(config, current, user_time="2026-06-06T00:00:03Z")

    context = conversation_context.build_conversation_context(
        config,
        thread_id=thread.id,
        current_user_message_id=current.user_message.id,
        current_user_content=current.user_message.content,
    )

    assert context.retrieval_query == "What about Bretonnian knightly careers?"
    assert context.history_message_ids == ()
    assert context.history_turn_count == 0
    assert context.history_strategy == "self_contained"


def test_history_aware_retrieval_query_contextualizes_followups_and_caps_length(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, retrieval_query_char_limit=150)
    seed_books(config)
    thread = chat_store.create_thread(config)
    completed = complete_turn(
        config,
        thread.id,
        content="Tell me about Captain Alder.",
        answer="Captain Alder wears mail and carries a lantern shield.",
        idempotency_key="send-1",
    )
    current = chat_store.create_queued_turn(
        config,
        thread.id,
        content="What about it?",
        idempotency_key="current",
        provider="openai",
        model="gpt-5.4-mini",
    )
    set_turn_times(
        config,
        completed,
        user_time="2026-06-06T00:00:01Z",
        assistant_time="2026-06-06T00:00:02Z",
        run_time="2026-06-06T00:00:02Z",
    )
    set_turn_times(config, current, user_time="2026-06-06T00:00:03Z")

    context = conversation_context.build_conversation_context(
        config,
        thread_id=thread.id,
        current_user_message_id=current.user_message.id,
        current_user_content=current.user_message.content,
    )

    assert context.history_strategy == "followup_contextualized"
    assert context.retrieval_query.startswith("What about it?")
    assert "Recent chat terms for reference resolution" in context.retrieval_query
    assert "Captain Alder" in context.retrieval_query
    assert "mail" in context.retrieval_query
    assert len(context.retrieval_query) <= 150


def test_conversation_context_zero_limits_disable_prompt_and_retrieval_history(
    tmp_path: Path,
) -> None:
    config = make_config(
        tmp_path,
        prompt_turn_limit=0,
        prompt_char_limit=0,
        retrieval_turn_limit=0,
        retrieval_query_char_limit=0,
    )
    seed_books(config)
    thread = chat_store.create_thread(config)
    completed = complete_turn(
        config,
        thread.id,
        content="Tell me about Captain Alder.",
        answer="Captain Alder wears mail.",
        idempotency_key="send-1",
    )
    current = chat_store.create_queued_turn(
        config,
        thread.id,
        content="What about it?",
        idempotency_key="current",
        provider="openai",
        model="gpt-5.4-mini",
    )
    set_turn_times(
        config,
        completed,
        user_time="2026-06-06T00:00:01Z",
        assistant_time="2026-06-06T00:00:02Z",
        run_time="2026-06-06T00:00:02Z",
    )
    set_turn_times(config, current, user_time="2026-06-06T00:00:03Z")

    context = conversation_context.build_conversation_context(
        config,
        thread_id=thread.id,
        current_user_message_id=current.user_message.id,
        current_user_content=current.user_message.content,
    )

    assert context.prompt_messages == ()
    assert context.history_message_ids == ()
    assert context.history_turn_count == 0
    assert context.retrieval_query == ""
    assert context.history_strategy == "none"


def test_conversation_context_rejects_missing_current_user_message(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    thread = chat_store.create_thread(config)

    try:
        conversation_context.build_conversation_context(
            config,
            thread_id=thread.id,
            current_user_message_id="missing-message",
            current_user_content="What about it?",
        )
    except chat_store.ModelRunNotRetryableError as error:
        assert "missing-message" in str(error)
    else:  # pragma: no cover - assertion path
        raise AssertionError("missing current user message was accepted")
