from __future__ import annotations

from pathlib import Path

from wfrp_companion.assistant import chat_store
from wfrp_companion.assistant import evidence_validation
from wfrp_companion.assistant.evidence import RetrievedHit
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.library import source_sets


def make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        pdf_root=tmp_path / "pdf-root",
        data_dir=data_dir,
        db_path=data_dir / "wfrp_companion.sqlite",
        asset_dir=data_dir / "library" / "assets",
    )


def seed_book(config: AppConfig) -> None:
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
            values ('bestiary', 'core', 'Old World Bestiary',
                    'Rules and Mechanics Toolkits', 'bestiary.pdf',
                    '/source/bestiary.pdf', '/managed/bestiary.pdf',
                    'source-sha', 'managed-sha', 150, 'copied', 'imported',
                    'indexed', 'not_scanned', '2026-06-09T00:00:00Z',
                    '2026-06-09T00:00:00Z')
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
            values ('bestiary:101', 'bestiary', 101, '99', 'ocr',
                    0, 20, 4, 0, 1, 1)
            """
        )
        connection.execute(
            """
            insert into source_objects (
              id,
              book_id,
              page_id,
              object_type,
              parent_object_id,
              title,
              heading_path_json,
              page_start,
              page_end,
              char_start,
              char_end,
              bbox_json,
              text,
              search_text,
              metadata_json,
              confidence,
              extraction_method,
              text_snapshot_sha256,
              created_at,
              updated_at
            )
            values ('harpy-stat', 'bestiary', 'bestiary:101', 'stat_block',
                    null, 'Harpy', '["Creatures", "Harpy"]', 101, 101,
                    null, null, null, 'Harpy stat_block: M 4 WS 31.',
                    'Harpy stat_block: M 4 WS 31.', '{}', 0.95,
                    'synthetic', 'sha-harpy-stat', '2026-06-09T00:00:00Z',
                    '2026-06-09T00:00:00Z')
            """
        )
    source_sets.ensure_builtin_source_sets(config)


def hit(
    *,
    book_id: str = "bestiary",
    title: str = "Old World Bestiary",
    context_text: str,
    object_type: str = "stat_block",
    object_title: str | None = "Harpy",
    source_object_id: str | None = "harpy-stat",
) -> RetrievedHit:
    return RetrievedHit(
        book_id=book_id,
        title=title,
        category="Rules and Mechanics Toolkits",
        page_id=f"{book_id}:101",
        page_number=101,
        pdf_page_number=101,
        page_label="99",
        snippet=context_text,
        score=1.0,
        rank=1,
        context_text=context_text,
        source_object_id=source_object_id,
        object_type=object_type,
        object_title=object_title,
        page_start=101,
        page_end=101,
        page_range_label="99",
    )


def create_research_run(config: AppConfig) -> tuple[str, str, str, str, str]:
    seed_book(config)
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
    retrieval_run_id = chat_store.record_retrieval_run(
        config,
        thread_id=thread.id,
        message_id=queued.user_message.id,
        source_set_id=thread.active_source_set_id,
        query="harpy statline",
        hits=(),
        source_book_ids=("bestiary",),
    )
    return (
        thread.id,
        queued.user_message.id,
        queued.model_run.id,
        research_run.id,
        retrieval_run_id,
    )


def test_validate_statline_requires_subject_source_and_stat_evidence() -> None:
    accepted = hit(context_text="Harpy stat_block: M 4 WS 31 BS 0 S 31.")
    wrong_subject = hit(context_text="Gor stat_block: M 4 WS 33.", object_title="Gor")
    non_stat = hit(
        context_text="Harpy flying movement rules discuss altitude.",
        object_type="rule_section",
        object_title="Harpy",
        source_object_id="harpy-flight",
    )
    unchecked = hit(
        book_id="unchecked",
        title="Unchecked Book",
        context_text="Harpy stat_block: M 4 WS 31.",
    )

    result = evidence_validation.validate_hits(
        (accepted, wrong_subject, non_stat, unchecked),
        subject="harpy",
        intent="statline_lookup",
        source_book_ids=("bestiary",),
    )

    assert result.status == "sufficient"
    assert [judgment.status for judgment in result.judgments] == [
        "accepted",
        "rejected",
        "rejected",
        "rejected",
    ]
    assert [judgment.reason_code for judgment in result.judgments] == [
        "statline_evidence",
        "subject_mismatch",
        "missing_statline_markers",
        "unchecked_source",
    ]
    assert result.accepted_hits == (accepted,)


def test_validate_partial_page_and_topical_evidence_paths() -> None:
    partial_page = hit(
        context_text="Harpy creature entry mentions wings and claws.",
        object_type="page_fallback",
        object_title=None,
        source_object_id=None,
    )
    stat_text_page = hit(
        context_text="Harpy stat_block: M 4 WS 31 BS 0 S 31.",
        object_type="page_fallback",
        object_title=None,
        source_object_id=None,
    )
    topical = hit(
        context_text="Harpy creature entry mentions wings and claws.",
        object_type="rule_section",
        object_title="Harpy",
        source_object_id="harpy-lore",
    )

    partial_result = evidence_validation.validate_hits(
        (partial_page,),
        subject="harpy",
        intent="statline_lookup",
        source_book_ids=("bestiary",),
    )
    stat_text_result = evidence_validation.validate_hits(
        (stat_text_page,),
        subject="harpy",
        intent="statline_lookup",
        source_book_ids=("bestiary",),
    )
    topical_result = evidence_validation.validate_hits(
        (topical,),
        subject="",
        intent="rules_lookup",
        source_book_ids=("bestiary",),
    )

    assert partial_result.status == "partial"
    assert partial_result.judgments[0].reason_code == "subject_only_page"
    assert stat_text_result.status == "sufficient"
    assert stat_text_result.judgments[0].reason_code == "statline_evidence"
    assert topical_result.status == "sufficient"
    assert topical_result.judgments[0].reason_code == "topical_evidence"
    assert evidence_validation.hit_mentions_subject(topical, "the") is True


def test_record_validation_persists_judgments_and_updates_thread_context(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    (
        thread_id,
        user_message_id,
        model_run_id,
        research_run_id,
        retrieval_run_id,
    ) = create_research_run(config)
    accepted = hit(context_text="Harpy stat_block: M 4 WS 31 BS 0 S 31.")
    result = evidence_validation.validate_hits(
        (accepted,),
        subject="harpy",
        intent="statline_lookup",
        source_book_ids=("bestiary",),
    )

    judgments = evidence_validation.record_evidence_judgments(
        config,
        research_run_id=research_run_id,
        retrieval_run_id=retrieval_run_id,
        validation=result,
    )
    context = evidence_validation.update_thread_context_from_validation(
        config,
        thread_id=thread_id,
        validation=result,
        subject="harpy",
        intent="statline_lookup",
        updated_from_message_id=user_message_id,
        updated_from_model_run_id=model_run_id,
    )

    assert len(judgments) == 1
    assert judgments[0].status == "accepted"
    assert context is not None
    assert context.active_subject == "harpy"
    assert context.active_intent == "statline_lookup"
    assert context.active_book_id == "bestiary"
    assert context.active_printed_page_label == "99"
    assert context.active_pdf_page_number == 101
    assert context.active_source_object_id == "harpy-stat"


def test_insufficient_validation_does_not_update_thread_context(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    (
        thread_id,
        user_message_id,
        model_run_id,
        _research_run_id,
        _retrieval_run_id,
    ) = create_research_run(config)
    existing = chat_store.upsert_chat_thread_context(
        config,
        thread_id,
        active_subject="harpy",
        active_intent="statline_lookup",
        active_book_id="bestiary",
        active_printed_page_label="99",
        active_pdf_page_number=101,
        updated_from_message_id=user_message_id,
        updated_from_model_run_id=model_run_id,
    )
    result = evidence_validation.validate_hits(
        (hit(context_text="Flying movement rules.", object_type="rule_section"),),
        subject="harpy",
        intent="statline_lookup",
        source_book_ids=("bestiary",),
    )

    context = evidence_validation.update_thread_context_from_validation(
        config,
        thread_id=thread_id,
        validation=result,
        subject="gor",
        intent="statline_lookup",
        updated_from_message_id="message-2",
        updated_from_model_run_id=model_run_id,
    )

    assert result.status == "insufficient"
    assert context == existing
