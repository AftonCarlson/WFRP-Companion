from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse

from wfrp_companion.api import errors
from wfrp_companion.api.dependencies import ConfigDependency
from wfrp_companion.api.schemas import (
    ChatCitationResponse,
    ChatMessageResponse,
    ChatResearchEventResponse,
    ChatThreadDetailResponse,
    ChatThreadResponse,
    ChatThreadsResponse,
    ChatTurnResponse,
    CreateChatThreadRequest,
    ModelRunResponse,
    RetryModelRunRequest,
    SendChatMessageRequest,
    SendChatMessageResponse,
)
from wfrp_companion.assistant import chat_service, chat_store, research
from wfrp_companion.library import source_sets


router = APIRouter(tags=["chat"])


@router.post("/chat/threads", response_model=ChatThreadResponse)
def create_thread(
    request: CreateChatThreadRequest,
    config: ConfigDependency,
) -> ChatThreadResponse:
    try:
        thread = chat_store.create_thread(
            config,
            title=request.title,
            source_set_id=request.source_set_id,
        )
    except source_sets.SourceSetError as error:
        raise errors.source_set_error(error) from error
    return thread_response(thread)


@router.get("/chat/threads", response_model=ChatThreadsResponse)
def list_threads(config: ConfigDependency) -> ChatThreadsResponse:
    return ChatThreadsResponse(
        threads=[thread_response(thread) for thread in chat_store.list_threads(config)]
    )


@router.get("/chat/threads/{thread_id}", response_model=ChatThreadDetailResponse)
def get_thread_detail(
    thread_id: str,
    config: ConfigDependency,
) -> ChatThreadDetailResponse:
    try:
        detail = chat_store.get_thread_detail(config, thread_id)
    except chat_store.ChatStoreError as error:
        raise errors.chat_store_error(error) from error
    return ChatThreadDetailResponse(
        thread=thread_response(detail.thread),
        source_book_ids=list(detail.source_book_ids),
        turns=[turn_response(config, turn) for turn in detail.turns],
    )


@router.post(
    "/chat/threads/{thread_id}/messages",
    response_model=SendChatMessageResponse,
)
def send_message(
    thread_id: str,
    request: SendChatMessageRequest,
    config: ConfigDependency,
    app_request: Request,
) -> SendChatMessageResponse:
    try:
        events = tuple(
            chat_service.stream_chat_message(
                config,
                thread_id=thread_id,
                content=request.content,
                idempotency_key=request.idempotency_key or chat_store.new_id("send"),
                reader_context=reader_context_from_request(request),
                provider_factory=getattr(
                    app_request.app.state,
                    "assistant_provider_factory",
                    None,
                ),
            )
        )
        if not events:
            raise chat_store.ModelRunNotRetryableError("Chat message did not produce a run")
    except chat_store.ChatStoreError as error:
        raise errors.chat_store_error(error) from error
    return send_response_from_event(events[-1])


@router.post("/chat/threads/{thread_id}/messages/stream")
def stream_message(
    thread_id: str,
    request: SendChatMessageRequest,
    config: ConfigDependency,
    app_request: Request,
) -> StreamingResponse:
    def event_stream() -> Iterator[str]:
        try:
            events = chat_service.stream_chat_message(
                config,
                thread_id=thread_id,
                content=request.content,
                idempotency_key=request.idempotency_key or chat_store.new_id("send"),
                reader_context=reader_context_from_request(request),
                provider_factory=getattr(
                    app_request.app.state,
                    "assistant_provider_factory",
                    None,
                ),
            )
        except chat_store.ChatStoreError as error:
            raise errors.chat_store_error(error) from error

        for event in events:
            yield json.dumps(
                stream_event_response(event),
                separators=(",", ":"),
            ) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.post(
    "/chat/model-runs/{model_run_id}/retry",
    response_model=SendChatMessageResponse,
)
def retry_model_run(
    model_run_id: str,
    request: RetryModelRunRequest,
    config: ConfigDependency,
    app_request: Request,
) -> SendChatMessageResponse:
    try:
        events = tuple(
            chat_service.stream_retry_model_run(
                config,
                model_run_id=model_run_id,
                idempotency_key=request.idempotency_key or chat_store.new_id("retry"),
                provider_factory=getattr(
                    app_request.app.state,
                    "assistant_provider_factory",
                    None,
                ),
            )
        )
        if not events:
            raise chat_store.ModelRunNotRetryableError("Retry did not produce a run")
    except chat_store.ChatStoreError as error:
        raise errors.chat_store_error(error) from error
    return send_response_from_event(events[-1])


def thread_response(thread: chat_store.ChatThread) -> ChatThreadResponse:
    return ChatThreadResponse(**thread.__dict__)


def message_response(message: chat_store.ChatMessage) -> ChatMessageResponse:
    return ChatMessageResponse(**message.__dict__)


def model_run_response(model_run: chat_store.ModelRun) -> ModelRunResponse:
    return ModelRunResponse(**model_run.__dict__)


def turn_response(config, turn: chat_store.ChatTurn) -> ChatTurnResponse:
    return ChatTurnResponse(
        user_message=message_response(turn.user_message),
        assistant_message=None
        if turn.assistant_message is None
        else message_response(turn.assistant_message),
        model_run=model_run_response(turn.model_run),
        citations=[citation_response(citation) for citation in turn.citations],
        research_events=[
            ChatResearchEventResponse(**event)
            for event in chat_store.list_public_research_events(
                config,
                turn.model_run.id,
            )
        ],
    )


def send_response(result: chat_store.SendChatResult) -> SendChatMessageResponse:
    return SendChatMessageResponse(
        thread=thread_response(result.thread),
        user_message=message_response(result.user_message),
        assistant_message=None
        if result.assistant_message is None
        else message_response(result.assistant_message),
        model_run=model_run_response(result.model_run),
        citations=[citation_response(citation) for citation in result.citations],
    )


def send_response_from_event(
    event: chat_service.ChatStreamEvent,
) -> SendChatMessageResponse:
    return SendChatMessageResponse(
        thread=thread_response(event.thread),
        user_message=message_response(event.user_message),
        assistant_message=None
        if event.assistant_message is None
        else message_response(event.assistant_message),
        model_run=model_run_response(event.model_run),
        citations=[citation_response(citation) for citation in event.citations],
    )


def stream_event_response(event: chat_service.ChatStreamEvent) -> dict[str, object]:
    return {
        "type": event.type,
        "thread": thread_response(event.thread).model_dump(),
        "user_message": message_response(event.user_message).model_dump(),
        "assistant_message": None
        if event.assistant_message is None
        else message_response(event.assistant_message).model_dump(),
        "model_run": model_run_response(event.model_run).model_dump(),
        "citations": [
            citation_response(citation).model_dump() for citation in event.citations
        ],
        "text_delta": event.text_delta,
        "error_message": event.error_message,
        "metadata": event.metadata,
    }


def reader_context_from_request(
    request: SendChatMessageRequest,
) -> research.ReaderContext | None:
    if request.reader_context is None:
        return None
    return research.ReaderContext(
        active_book_id=request.reader_context.active_book_id,
        active_pdf_page_number=request.reader_context.active_pdf_page_number,
        active_printed_page_label=request.reader_context.active_printed_page_label,
        open_book_ids=tuple(request.reader_context.open_book_ids),
    )


def citation_response(citation: chat_store.ChatCitation) -> ChatCitationResponse:
    return ChatCitationResponse(**citation.__dict__)
