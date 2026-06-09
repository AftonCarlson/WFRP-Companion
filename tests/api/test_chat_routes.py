from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from pathlib import Path

import anyio
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from wfrp_companion.assistant import provider
from wfrp_companion.assistant import chat_store
from wfrp_companion.api.app import create_app
from wfrp_companion.api.routes import chat as chat_routes
from wfrp_companion.api.schemas import SendChatMessageRequest
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


def count_rows(config: AppConfig, table: str) -> int:
    with open_connection(config.db_path) as connection:
        return connection.execute(f"select count(*) from {table}").fetchone()[0]


def test_chat_thread_create_list_and_detail_routes(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    client = TestClient(create_app(config))

    created = client.post("/api/chat/threads", json={"title": "Rules Help"})
    listed = client.get("/api/chat/threads")
    detail = client.get(f"/api/chat/threads/{created.json()['id']}")

    assert created.status_code == 200
    assert created.json()["title"] == "Rules Help"
    assert created.json()["active_source_set_id"] == source_sets.RULES_CORE_SOURCE_SET_ID
    assert created.json()["source_book_count"] == 1
    assert listed.status_code == 200
    assert listed.json()["threads"][0]["id"] == created.json()["id"]
    assert detail.status_code == 200
    assert detail.json()["source_book_ids"] == ["core-rules"]
    assert detail.json()["turns"] == []


def test_create_thread_maps_unknown_source_set_to_not_found(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    client = TestClient(create_app(config))

    response = client.post(
        "/api/chat/threads",
        json={"title": "Bad scope", "source_set_id": "missing-source-set"},
    )

    assert response.status_code == 404


def test_send_message_returns_failed_provider_unavailable_run_and_is_idempotent(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    client = TestClient(create_app(config))
    thread_id = client.post("/api/chat/threads", json={}).json()["id"]

    first = client.post(
        f"/api/chat/threads/{thread_id}/messages",
        json={"content": "What is dodge?", "idempotency_key": "send-1"},
    )
    duplicate = client.post(
        f"/api/chat/threads/{thread_id}/messages",
        json={"content": "Do not duplicate this", "idempotency_key": "send-1"},
    )
    detail = client.get(f"/api/chat/threads/{thread_id}")

    assert first.status_code == 200
    assert first.json()["user_message"]["content"] == "What is dodge?"
    assert first.json()["assistant_message"] is None
    assert first.json()["model_run"]["status"] == "failed"
    assert first.json()["model_run"]["error_code"] == "provider_unavailable"
    assert first.json()["model_run"]["retryable"] is True
    assert duplicate.status_code == 200
    assert duplicate.json()["user_message"]["id"] == first.json()["user_message"]["id"]
    assert count_rows(config, "chat_messages") == 1
    assert count_rows(config, "model_runs") == 1
    assert detail.json()["turns"][0]["model_run"]["error_code"] == "provider_unavailable"


def test_stream_message_returns_accepted_and_failed_events(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    client = TestClient(create_app(config))
    thread_id = client.post("/api/chat/threads", json={}).json()["id"]

    response = client.post(
        f"/api/chat/threads/{thread_id}/messages/stream",
        json={"content": "What is dodge?", "idempotency_key": "send-stream-1"},
    )

    events = [line for line in response.text.splitlines() if line]
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert '"type":"accepted"' in events[0]
    assert '"user_message"' in events[0]
    assert '"type":"failed"' in events[-1]
    assert '"provider_unavailable"' in events[-1]
    assert count_rows(config, "chat_messages") == 1
    assert count_rows(config, "model_runs") == 1


def test_stream_message_can_emit_model_deltas_and_completed_event(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    app = create_app(config)
    client = TestClient(app)
    app.state.assistant_provider_factory = lambda _: FakeProvider()
    thread_id = client.post("/api/chat/threads", json={}).json()["id"]

    response = client.post(
        f"/api/chat/threads/{thread_id}/messages/stream",
        json={"content": "What is dodge?", "idempotency_key": "send-stream-2"},
    )

    events = [line for line in response.text.splitlines() if line]
    assert response.status_code == 200
    assert '"type":"accepted"' in events[0]
    assert '"type":"research_started"' in events[1]
    assert any('"type":"retrieval"' in event for event in events)
    delta_event = next(event for event in events if '"type":"delta"' in event)
    assert '"text_delta":"Rules answer."' in delta_event
    assert '"type":"completed"' in events[-1]
    assert '"assistant_message"' in events[-1]
    assert count_rows(config, "chat_messages") == 2
    assert count_rows(config, "model_runs") == 1


def test_retry_route_reuses_user_message_and_is_idempotent(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    client = TestClient(create_app(config))
    thread_id = client.post("/api/chat/threads", json={}).json()["id"]
    failed = client.post(
        f"/api/chat/threads/{thread_id}/messages",
        json={"content": "What is fear?", "idempotency_key": "send-1"},
    ).json()

    retry = client.post(
        f"/api/chat/model-runs/{failed['model_run']['id']}/retry",
        json={"idempotency_key": "retry-1"},
    )
    duplicate = client.post(
        f"/api/chat/model-runs/{failed['model_run']['id']}/retry",
        json={"idempotency_key": "retry-1"},
    )

    assert retry.status_code == 200
    assert retry.json()["user_message"]["id"] == failed["user_message"]["id"]
    assert retry.json()["model_run"]["retry_of_model_run_id"] == failed["model_run"]["id"]
    assert retry.json()["model_run"]["error_code"] == "provider_unavailable"
    assert duplicate.status_code == 200
    assert duplicate.json()["model_run"]["id"] == retry.json()["model_run"]["id"]
    assert count_rows(config, "chat_messages") == 1
    assert count_rows(config, "model_runs") == 2


def test_thread_detail_route_collapses_successful_retry(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    app = create_app(config)
    client = TestClient(app)
    thread_id = client.post("/api/chat/threads", json={}).json()["id"]
    failed = client.post(
        f"/api/chat/threads/{thread_id}/messages",
        json={"content": "What is fear?", "idempotency_key": "send-1"},
    ).json()
    app.state.assistant_provider_factory = lambda _: FakeProvider()

    retry = client.post(
        f"/api/chat/model-runs/{failed['model_run']['id']}/retry",
        json={"idempotency_key": "retry-1"},
    )
    detail = client.get(f"/api/chat/threads/{thread_id}")

    assert retry.status_code == 200
    assert retry.json()["assistant_message"]["content"] == "Rules answer."
    assert detail.status_code == 200
    assert len(detail.json()["turns"]) == 1
    turn = detail.json()["turns"][0]
    assert turn["user_message"]["id"] == failed["user_message"]["id"]
    assert turn["assistant_message"]["content"] == "Rules answer."
    assert turn["model_run"]["id"] == retry.json()["model_run"]["id"]
    assert turn["model_run"]["status"] == "completed"
    assert turn["model_run"]["retryable"] is False


def test_chat_routes_map_missing_resources_and_validation(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    client = TestClient(create_app(config))

    missing_thread = client.get("/api/chat/threads/missing-thread")
    send_missing = client.post(
        "/api/chat/threads/missing-thread/messages",
        json={"content": "Hello", "idempotency_key": "send-1"},
    )
    empty_content = client.post(
        "/api/chat/threads/missing-thread/messages",
        json={"content": "", "idempotency_key": "send-2"},
    )
    retry_missing = client.post(
        "/api/chat/model-runs/missing-run/retry",
        json={"idempotency_key": "retry-1"},
    )

    assert missing_thread.status_code == 404
    assert send_missing.status_code == 404
    assert empty_content.status_code == 422
    assert retry_missing.status_code == 404


def test_send_and_retry_routes_reject_empty_service_event_streams(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    client = TestClient(create_app(config))
    thread_id = client.post("/api/chat/threads", json={}).json()["id"]
    failed = client.post(
        f"/api/chat/threads/{thread_id}/messages",
        json={"content": "What is fear?", "idempotency_key": "send-1"},
    ).json()

    monkeypatch.setattr(
        chat_routes.chat_service,
        "stream_chat_message",
        lambda *args, **kwargs: iter(()),
    )
    monkeypatch.setattr(
        chat_routes.chat_service,
        "stream_retry_model_run",
        lambda *args, **kwargs: iter(()),
    )

    send_response = client.post(
        f"/api/chat/threads/{thread_id}/messages",
        json={"content": "Still here?", "idempotency_key": "send-empty"},
    )
    retry_response = client.post(
        f"/api/chat/model-runs/{failed['model_run']['id']}/retry",
        json={"idempotency_key": "retry-empty"},
    )

    assert send_response.status_code == 409
    assert retry_response.status_code == 409


def test_stream_route_maps_chat_store_error_from_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)

    def raise_store_error(*args, **kwargs):
        raise chat_store.ChatThreadNotFoundError("missing thread")

    monkeypatch.setattr(
        chat_routes.chat_service,
        "stream_chat_message",
        raise_store_error,
    )
    response = chat_routes.stream_message(
        "missing-thread",
        SendChatMessageRequest(content="Hello", idempotency_key="send-1"),
        config,
        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
    )

    async def consume_response() -> None:
        with pytest.raises(HTTPException) as error_info:
            async for _ in response.body_iterator:
                pass
        assert error_info.value.status_code == 404

    anyio.run(consume_response)


def test_response_helpers_include_citations(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    source_sets.ensure_builtin_source_sets(config)
    thread = chat_store.create_thread(config)
    turn = chat_store.create_provider_unavailable_turn(
        config,
        thread.id,
        content="What is fear?",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )
    citation = chat_store.ChatCitation(
        book_id="core-rules",
        title="Core Rules",
        category="Core Book & GM Essentials",
        page_id="core-rules:1",
        page_number=1,
        pdf_page_number=1,
        page_label="132",
        snippet="Fear rules",
        rank=1,
        score=0.5,
    )
    result = chat_store.SendChatResult(
        thread=turn.thread,
        user_message=turn.user_message,
        assistant_message=turn.assistant_message,
        model_run=turn.model_run,
        citations=(citation,),
    )

    response = chat_routes.send_response(result)
    citation_response = chat_routes.citation_response(citation)

    assert response.citations[0].book_id == "core-rules"
    assert citation_response.page_number == 1
    assert citation_response.pdf_page_number == 1
    assert citation_response.page_label == "132"


class FakeProvider:
    def stream_response(self, *, messages, request_id, **_kwargs):
        assert request_id.startswith("run-")
        assert messages[-1].role == "user"
        yield provider.ProviderStreamEvent(type="delta", text_delta="Rules answer.")
        yield provider.ProviderStreamEvent(
            type="completed",
            provider_response_id="resp-route-1",
            input_tokens=5,
            output_tokens=2,
        )
