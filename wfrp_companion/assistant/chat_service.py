from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from wfrp_companion.assistant import (
    chat_store,
    conversation_context,
    familiar_agent,
    provider,
    research,
)
from wfrp_companion.assistant import retrieval
from wfrp_companion.config import AppConfig


DEFAULT_PROVIDER = "openai"


class ResponseProvider(Protocol):
    def stream_response(
        self,
        *,
        messages: Sequence[provider.ProviderMessage],
        request_id: str,
        tools: Sequence[provider.ProviderToolDefinition] = (),
        tool_results: Sequence[provider.ProviderToolResult] = (),
        previous_response_id: str | None = None,
        tool_choice: object | None = None,
    ) -> Iterable[provider.ProviderStreamEvent]:
        pass  # pragma: no cover - protocol declaration only


ProviderFactory = Callable[[AppConfig], ResponseProvider]


@dataclass(frozen=True)
class ChatStreamEvent:
    type: str
    thread: chat_store.ChatThread
    user_message: chat_store.ChatMessage
    assistant_message: chat_store.ChatMessage | None
    model_run: chat_store.ModelRun
    citations: tuple[chat_store.ChatCitation, ...]
    text_delta: str | None = None
    error_message: str | None = None
    metadata: dict[str, object] | None = None


def stream_chat_message(
    config: AppConfig,
    *,
    thread_id: str,
    content: str,
    idempotency_key: str,
    reader_context: research.ReaderContext | None = None,
    provider_factory: ProviderFactory | None = None,
) -> Iterable[ChatStreamEvent]:
    result = chat_store.create_queued_turn(
        config,
        thread_id,
        content=content,
        idempotency_key=idempotency_key,
        provider=DEFAULT_PROVIDER,
        model=config.openai_model,
    )
    yield from stream_queued_result(
        config,
        result=result,
        content=content,
        reader_context=reader_context,
        provider_factory=provider_factory,
    )


def stream_retry_model_run(
    config: AppConfig,
    *,
    model_run_id: str,
    idempotency_key: str,
    provider_factory: ProviderFactory | None = None,
) -> Iterable[ChatStreamEvent]:
    result = chat_store.create_queued_retry(
        config,
        model_run_id,
        idempotency_key=idempotency_key,
        provider=DEFAULT_PROVIDER,
        model=config.openai_model,
    )
    yield from stream_queued_result(
        config,
        result=result,
        content=result.user_message.content,
        provider_factory=provider_factory,
    )


def stream_queued_result(
    config: AppConfig,
    *,
    result: chat_store.SendChatResult,
    content: str,
    reader_context: research.ReaderContext | None = None,
    provider_factory: ProviderFactory | None = None,
) -> Iterable[ChatStreamEvent]:
    yield event_from_result("accepted", result)

    if result.model_run.status == "completed":
        yield event_from_result("completed", result)
        return
    if result.model_run.status == "failed":
        yield event_from_result(
            "failed",
            result,
            error_message=result.model_run.error_message,
        )
        return
    if result.model_run.status != "queued":
        return

    try:
        response_provider = (
            provider_factory(config)
            if provider_factory is not None
            else default_provider_factory(config)
        )
    except provider.ProviderUnavailableError as error:
        failed = chat_store.fail_model_run(
            config,
            result.model_run.id,
            error_code="provider_unavailable",
            error_message=str(error),
        )
        yield event_from_result("failed", failed, error_message=str(error))
        return

    try:
        chat_store.transition_model_run(
            config,
            result.model_run.id,
            from_statuses=("queued",),
            to_status="retrieving",
        )
        conversation = conversation_context.build_conversation_context(
            config,
            thread_id=result.thread.id,
            current_user_message_id=result.user_message.id,
            current_user_content=content,
        )
        research_result = familiar_agent.run_research(
            config,
            result=result,
            content=content,
            conversation=conversation,
            reader_context=reader_context,
            response_provider=response_provider,
        )
        retrieved = (
            chat_store.attach_retrieval_run(
                config,
                result.model_run.id,
                retrieval_run_id=research_result.final_retrieval_run_id,
            )
            if research_result.final_retrieval_run_id is not None
            else result
        )
        for progress_event in research_result.progress_events:
            yield event_from_result(
                progress_event.type,
                retrieved,
                citations=citations_from_hits(progress_event.hits),
                metadata=progress_event.metadata,
            )

        chat_store.transition_model_run(
            config,
            result.model_run.id,
            from_statuses=("retrieving",),
            to_status="calling_model",
        )
        provider_messages = tuple(
            provider.ProviderMessage(role=message.role, content=message.content)
            for message in research_result.final_prompt_messages
        )
        citations = citations_from_hits(research_result.accepted_hits)
        text_parts: list[str] = []
        provider_response_id: str | None = None
        input_tokens: int | None = None
        output_tokens: int | None = None

        for provider_event in response_provider.stream_response(
            messages=provider_messages,
            request_id=result.model_run.id,
            tool_choice="none",
        ):
            if provider_event.type == "delta":
                delta = provider_event.text_delta or ""
                if not delta:
                    continue
                text_parts.append(delta)
                yield event_from_result(
                    "delta",
                    retrieved,
                    citations=citations,
                    text_delta=delta,
                )
            elif provider_event.type == "completed":
                provider_response_id = provider_event.provider_response_id
                input_tokens = provider_event.input_tokens
                output_tokens = provider_event.output_tokens

        completed = chat_store.complete_model_run(
            config,
            result.model_run.id,
            content="".join(text_parts),
            provider_response_id=provider_response_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        yield event_from_result("completed", completed)
    except GeneratorExit:
        chat_store.fail_model_run(
            config,
            result.model_run.id,
            error_code="stream_interrupted",
            error_message="Chat stream ended before the model run completed.",
        )
        raise
    except provider.ProviderUnavailableError as error:
        failed = chat_store.fail_model_run(
            config,
            result.model_run.id,
            error_code="provider_unavailable",
            error_message=str(error),
        )
        yield event_from_result("failed", failed, error_message=str(error))
    except Exception as error:
        failed = chat_store.fail_model_run(
            config,
            result.model_run.id,
            error_code="provider_error",
            error_message=str(error),
        )
        yield event_from_result("failed", failed, error_message=str(error))


def default_provider_factory(config: AppConfig) -> ResponseProvider:
    return provider.OpenAIProvider(
        api_key=config.openai_api_key,
        model=config.openai_model,
        timeout_seconds=config.openai_timeout_seconds,
    )


def event_from_result(
    event_type: str,
    result: chat_store.SendChatResult,
    *,
    citations: tuple[chat_store.ChatCitation, ...] | None = None,
    text_delta: str | None = None,
    error_message: str | None = None,
    metadata: dict[str, object] | None = None,
) -> ChatStreamEvent:
    return ChatStreamEvent(
        type=event_type,
        thread=result.thread,
        user_message=result.user_message,
        assistant_message=result.assistant_message,
        model_run=result.model_run,
        citations=result.citations if citations is None else citations,
        text_delta=text_delta,
        error_message=error_message,
        metadata=metadata,
    )


def citations_from_hits(
    hits: Sequence[retrieval.RetrievedHit],
) -> tuple[chat_store.ChatCitation, ...]:
    return tuple(
        chat_store.ChatCitation(
            book_id=hit.book_id,
            title=hit.title,
            category=hit.category,
            page_id=hit.page_id,
            page_number=hit.page_number,
            pdf_page_number=hit.pdf_page_number,
            page_label=hit.page_label,
            snippet=hit.snippet,
            rank=hit.rank,
            score=hit.score,
            page_range_label=hit.page_range_label,
        )
        for hit in hits
    )
