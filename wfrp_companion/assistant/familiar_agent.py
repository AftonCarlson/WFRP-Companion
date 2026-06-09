from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from wfrp_companion.assistant import chat_store
from wfrp_companion.assistant import context_resolution
from wfrp_companion.assistant import evidence_validation
from wfrp_companion.assistant import prompts
from wfrp_companion.assistant import provider
from wfrp_companion.assistant import research
from wfrp_companion.assistant import research_tools
from wfrp_companion.assistant.conversation_context import ConversationContext
from wfrp_companion.assistant.evidence import RetrievedHit
from wfrp_companion.config import AppConfig


MAX_TOOL_ROUNDS = 4
DEFAULT_HIT_LIMIT = 8


@dataclass(frozen=True)
class FamiliarProgressEvent:
    type: str
    hits: tuple[RetrievedHit, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class FamiliarResearchResult:
    research_run: research.FamiliarResearchRun
    accepted_hits: tuple[RetrievedHit, ...]
    evidence_status: str
    final_retrieval_run_id: str | None
    final_prompt_messages: tuple[prompts.PromptMessage, ...]
    progress_events: tuple[FamiliarProgressEvent, ...]


def run_research(
    config: AppConfig,
    *,
    result: chat_store.SendChatResult,
    content: str,
    conversation: ConversationContext,
    response_provider: object,
    reader_context: research.ReaderContext | None = None,
) -> FamiliarResearchResult:
    active_context = merge_reader_context(
        chat_store.get_chat_thread_context(config, result.thread.id),
        reader_context,
        thread_id=result.thread.id,
    )
    resolved = context_resolution.resolve_research_request(
        content,
        active_context=active_context,
    )
    initial_query = initial_retrieval_query(
        resolved,
        conversation=conversation,
    )
    metadata: dict[str, object] = {
        "subject": resolved.subject,
        "used_active_subject": resolved.used_active_subject,
    }
    reader_metadata = reader_context_metadata(reader_context)
    if reader_metadata:
        metadata["reader_context"] = reader_metadata
    research_run = chat_store.create_familiar_research_run(
        config,
        model_run_id=result.model_run.id,
        raw_query=content,
        resolved_query=initial_query,
        intent=resolved.intent,
        max_tool_rounds=MAX_TOOL_ROUNDS,
        metadata=metadata,
    )
    progress: list[FamiliarProgressEvent] = [
        FamiliarProgressEvent(
            type="research_started",
            metadata={
                "research_run_id": research_run.id,
                "resolved_query": initial_query,
                "intent": resolved.intent,
                "subject": resolved.subject,
                "reader_context": reader_metadata,
            },
        )
    ]

    tool_rounds_used = 0
    accepted_hits: list[RetrievedHit] = []
    partial_hits: list[RetrievedHit] = []
    final_retrieval_run_id: str | None = None
    final_diagnostics: research.RetrievalDiagnostics | None = None
    last_validation_status = "not_evaluated"

    first_tool = initial_tool_name(resolved)
    first_arguments = initial_tool_arguments(
        resolved,
        query=initial_query,
    )
    outcome = execute_tool_and_validate(
        config,
        research_run=research_run,
        result=result,
        resolved=resolved,
        step_number=1,
        call_index=0,
        provider_call_id=None,
        tool_name=first_tool,
        arguments=first_arguments,
        conversation=conversation,
    )
    tool_rounds_used += 1
    progress.extend(outcome.progress_events)
    accepted_hits.extend(outcome.validation.accepted_hits)
    if outcome.validation.status == "partial":
        partial_hits.extend(partial_hits_from_judgments(outcome.validation))
    final_retrieval_run_id = outcome.tool_result.retrieval_run_id
    final_diagnostics = outcome.tool_result.diagnostics
    last_validation_status = outcome.validation.status

    prior_tool_outputs: list[dict[str, object]] = [outcome.tool_output]
    while not accepted_hits and tool_rounds_used < MAX_TOOL_ROUNDS:
        planning = request_recovery_tool(
            response_provider,
            request_id=result.model_run.id,
            resolved=resolved,
            conversation=conversation,
            prior_tool_outputs=tuple(prior_tool_outputs),
        )
        if planning.tool_call is None:
            break
        tool_call = planning.tool_call
        outcome = execute_tool_and_validate(
            config,
            research_run=research_run,
            result=result,
            resolved=resolved,
            step_number=tool_rounds_used + 1,
            call_index=0,
            provider_call_id=tool_call.tool_call_id,
            tool_name=tool_call.tool_name or "",
            arguments=tool_call.arguments,
            conversation=conversation,
        )
        tool_rounds_used += 1
        progress.extend(outcome.progress_events)
        accepted_hits.extend(outcome.validation.accepted_hits)
        if outcome.validation.status == "partial":
            partial_hits.extend(partial_hits_from_judgments(outcome.validation))
        final_retrieval_run_id = outcome.tool_result.retrieval_run_id
        final_diagnostics = outcome.tool_result.diagnostics
        last_validation_status = outcome.validation.status
        prior_tool_outputs.append(outcome.tool_output)

    evidence_status = aggregate_evidence_status(
        accepted_hits=accepted_hits,
        partial_hits=partial_hits,
        fallback_status=last_validation_status,
    )
    if accepted_hits:
        final_retrieval_run_id = record_accepted_evidence_retrieval_run(
            config,
            result=result,
            research_run=research_run,
            query=initial_query,
            accepted_hits=tuple(accepted_hits),
            diagnostics=final_diagnostics,
            evidence_status=evidence_status,
        )
    else:
        final_retrieval_run_id = None
    terminal_status = "completed" if accepted_hits else "insufficient"
    research_run = chat_store.transition_familiar_research_run(
        config,
        research_run.id,
        from_statuses=("planning", "tool_calling", "validating", "finalizing"),
        to_status=terminal_status,
        evidence_status=evidence_status,
        tool_rounds_used=tool_rounds_used,
        final_retrieval_run_id=final_retrieval_run_id,
    )
    progress.append(
        FamiliarProgressEvent(
            type="evidence_validation",
            hits=tuple(accepted_hits),
            metadata={
                "research_run_id": research_run.id,
                "evidence_status": evidence_status,
                "accepted_hit_count": len(accepted_hits),
                "partial_hit_count": len(partial_hits),
                "tool_rounds_used": tool_rounds_used,
            },
        )
    )
    final_prompt_messages = prompts.build_final_answer_prompt_messages(
        question=content,
        accepted_hits=tuple(accepted_hits),
        evidence_status=evidence_status,
        recent_messages=conversation.prompt_messages,
        context_char_limit=config.chat_context_char_limit,
    )
    return FamiliarResearchResult(
        research_run=research_run,
        accepted_hits=tuple(accepted_hits),
        evidence_status=evidence_status,
        final_retrieval_run_id=final_retrieval_run_id,
        final_prompt_messages=final_prompt_messages,
        progress_events=tuple(progress),
    )


def merge_reader_context(
    active_context: research.ChatThreadContext | None,
    reader_context: research.ReaderContext | None,
    *,
    thread_id: str,
) -> research.ChatThreadContext | None:
    if reader_context is None:
        return active_context
    reader_metadata = reader_context_metadata(reader_context)
    if not reader_metadata:
        return active_context
    if active_context is None:
        return research.ChatThreadContext(
            thread_id=thread_id,
            active_subject=None,
            active_intent=None,
            active_book_id=reader_context.active_book_id,
            active_printed_page_label=reader_context.active_printed_page_label,
            active_pdf_page_number=reader_context.active_pdf_page_number,
            active_source_object_id=None,
            updated_from_message_id=None,
            updated_from_model_run_id=None,
            metadata={"reader_context": reader_metadata},
            updated_at="",
        )
    return replace(
        active_context,
        active_book_id=reader_context.active_book_id or active_context.active_book_id,
        active_printed_page_label=reader_context.active_printed_page_label
        or active_context.active_printed_page_label,
        active_pdf_page_number=reader_context.active_pdf_page_number
        or active_context.active_pdf_page_number,
        metadata={
            **active_context.metadata,
            "reader_context": reader_metadata,
        },
    )


def reader_context_metadata(
    reader_context: research.ReaderContext | None,
) -> dict[str, object]:
    if reader_context is None:
        return {}
    metadata: dict[str, object] = {}
    if reader_context.active_book_id:
        metadata["active_book_id"] = reader_context.active_book_id
    if reader_context.active_pdf_page_number is not None:
        metadata["active_pdf_page_number"] = reader_context.active_pdf_page_number
    if reader_context.active_printed_page_label:
        metadata["active_printed_page_label"] = reader_context.active_printed_page_label
    open_book_ids = tuple(dict.fromkeys(reader_context.open_book_ids))
    if open_book_ids:
        metadata["open_book_ids"] = list(open_book_ids[:12])
    return metadata


@dataclass(frozen=True)
class ToolExecutionOutcome:
    tool_call: research.FamiliarToolCall
    tool_result: research_tools.SearchLibraryResult
    validation: evidence_validation.EvidenceValidationResult
    tool_output: dict[str, object]
    progress_events: tuple[FamiliarProgressEvent, ...]


@dataclass(frozen=True)
class ProviderToolRequest:
    tool_name: str | None
    tool_call_id: str | None
    arguments: dict[str, object]


@dataclass(frozen=True)
class ProviderPlanningResult:
    tool_call: ProviderToolRequest | None
    provider_response_id: str | None


def execute_tool_and_validate(
    config: AppConfig,
    *,
    research_run: research.FamiliarResearchRun,
    result: chat_store.SendChatResult,
    resolved: context_resolution.ResolvedResearchRequest,
    step_number: int,
    call_index: int,
    provider_call_id: str | None,
    tool_name: str,
    arguments: dict[str, object],
    conversation: ConversationContext,
) -> ToolExecutionOutcome:
    research_run = chat_store.transition_familiar_research_run(
        config,
        research_run.id,
        from_statuses=("planning", "tool_calling", "validating"),
        to_status="tool_calling",
        tool_rounds_used=step_number,
    )
    tool_call = chat_store.record_familiar_tool_call(
        config,
        research_run.id,
        step_number=step_number,
        call_index=call_index,
        provider_call_id=provider_call_id,
        tool_name=tool_name,
        arguments=arguments,
    )
    progress: list[FamiliarProgressEvent] = [
        FamiliarProgressEvent(
            type="tool_call",
            metadata={
                "research_run_id": research_run.id,
                "tool_call_id": tool_call.id,
                "tool_name": tool_name,
                "arguments": arguments,
                "step_number": step_number,
            },
        )
    ]
    running_call = chat_store.transition_familiar_tool_call(
        config,
        tool_call.id,
        from_statuses=("requested",),
        to_status="running",
    )
    try:
        tool_result = execute_tool(
            config,
            result=result,
            resolved=resolved,
            tool_call=running_call,
            step_number=step_number,
            tool_name=tool_name,
            arguments=arguments,
            conversation=conversation,
        )
        validation = evidence_validation.validate_hits(
            tool_result.hits,
            subject=resolved.subject,
            intent=resolved.intent,
            source_book_ids=tool_result.source_book_ids,
        )
        evidence_validation.record_evidence_judgments(
            config,
            research_run_id=research_run.id,
            retrieval_run_id=tool_result.retrieval_run_id,
            validation=validation,
        )
        evidence_validation.update_thread_context_from_validation(
            config,
            thread_id=result.thread.id,
            validation=validation,
            subject=resolved.subject,
            intent=resolved.intent,
            updated_from_message_id=result.user_message.id,
            updated_from_model_run_id=result.model_run.id,
        )
        chat_store.update_retrieval_run_validation_status(
            config,
            tool_result.retrieval_run_id,
            validation_status=validation.status,
            validation_summary=validation_summary(validation),
        )
    except Exception as error:
        chat_store.transition_familiar_tool_call(
            config,
            running_call.id,
            from_statuses=("running",),
            to_status="failed",
            error_code="tool_execution_failed",
            error_message=bounded_error_message(error),
        )
        chat_store.transition_familiar_research_run(
            config,
            research_run.id,
            from_statuses=("tool_calling", "validating"),
            to_status="failed",
            evidence_status="insufficient",
            tool_rounds_used=step_number,
        )
        raise
    tool_output = tool_output_payload(
        tool_result,
        validation=validation,
    )
    succeeded = chat_store.transition_familiar_tool_call(
        config,
        running_call.id,
        from_statuses=("running",),
        to_status="succeeded",
        retrieval_run_id=tool_result.retrieval_run_id,
        output_summary=tool_output_summary(tool_result, validation=validation),
    )
    chat_store.transition_familiar_research_run(
        config,
        research_run.id,
        from_statuses=("tool_calling",),
        to_status="validating",
        evidence_status=validation.status,
    )
    progress.extend(
        (
            FamiliarProgressEvent(type="retrieval", hits=tool_result.hits),
            FamiliarProgressEvent(
                type="tool_result",
                hits=tool_result.hits,
                metadata={
                    "research_run_id": research_run.id,
                    "tool_call_id": succeeded.id,
                    "tool_name": succeeded.tool_name,
                    "retrieval_run_id": tool_result.retrieval_run_id,
                    "hit_count": len(tool_result.hits),
                    "diagnostics": retrieval_diagnostics_metadata(
                        tool_result.diagnostics
                    ),
                },
            ),
        )
    )
    return ToolExecutionOutcome(
        tool_call=succeeded,
        tool_result=tool_result,
        validation=validation,
        tool_output=tool_output,
        progress_events=tuple(progress),
    )


def execute_tool(
    config: AppConfig,
    *,
    result: chat_store.SendChatResult,
    resolved: context_resolution.ResolvedResearchRequest,
    tool_call: research.FamiliarToolCall,
    step_number: int,
    tool_name: str,
    arguments: dict[str, object],
    conversation: ConversationContext,
) -> research_tools.SearchLibraryResult:
    if tool_name == "search_library":
        query = string_argument(arguments, "query") or resolved.resolved_query
        return research_tools.search_library(
            config=config,
            thread_id=result.thread.id,
            message_id=result.user_message.id,
            tool_call_id=tool_call.id,
            attempt_number=step_number,
            query=query,
            intent=string_argument(arguments, "intent") or resolved.intent,
            hit_limit=integer_argument(arguments, "limit") or DEFAULT_HIT_LIMIT,
            total_char_limit=config.chat_context_char_limit,
            window_chars=config.chat_context_window_chars,
            history_message_ids=conversation.history_message_ids,
            history_turn_count=conversation.history_turn_count,
            history_strategy=conversation.history_strategy,
        )
    if tool_name == "open_page":
        return research_tools.open_page(
            config=config,
            thread_id=result.thread.id,
            message_id=result.user_message.id,
            tool_call_id=tool_call.id,
            attempt_number=step_number,
            book_id=string_argument(arguments, "book_id"),
            book_title_hint=string_argument(arguments, "book_title_hint"),
            printed_page_label=string_argument(arguments, "printed_page_label"),
            pdf_page_number=integer_argument(arguments, "pdf_page_number"),
            subject_hint=string_argument(arguments, "subject_hint") or resolved.subject,
            intent=string_argument(arguments, "intent") or resolved.intent,
            hit_limit=1,
            total_char_limit=config.chat_context_char_limit,
            window_chars=config.chat_context_window_chars,
        )
    if tool_name == "lookup_source_object":
        return research_tools.lookup_source_object(
            config=config,
            thread_id=result.thread.id,
            message_id=result.user_message.id,
            tool_call_id=tool_call.id,
            attempt_number=step_number,
            source_object_id=string_argument(arguments, "source_object_id") or "",
            intent=string_argument(arguments, "intent") or resolved.intent,
            total_char_limit=config.chat_context_char_limit,
            window_chars=config.chat_context_window_chars,
        )
    raise ValueError(f"Unknown Familiar tool: {tool_name}")


def request_recovery_tool(
    response_provider: object,
    *,
    request_id: str,
    resolved: context_resolution.ResolvedResearchRequest,
    conversation: ConversationContext,
    prior_tool_outputs: Sequence[dict[str, object]] = (),
) -> ProviderPlanningResult:
    messages = prompts.build_research_prompt_messages(
        raw_query=resolved.raw_query,
        resolved_query=resolved.resolved_query,
        intent=resolved.intent,
        subject=resolved.subject,
        active_book_id=resolved.active_book_id,
        active_printed_page_label=None
        if resolved.page_reference is None
        else resolved.page_reference.printed_page_label,
        recent_messages=conversation.prompt_messages,
        prior_tool_outputs=prior_tool_outputs,
    )
    provider_messages = tuple(
        provider.ProviderMessage(role=message.role, content=message.content)
        for message in messages
    )
    tool_call: ProviderToolRequest | None = None
    provider_response_id: str | None = None
    for event in response_provider.stream_response(
        messages=provider_messages,
        request_id=request_id,
        tools=tool_definitions(),
        tool_results=(),
        previous_response_id=None,
    ):
        if event.type == "tool_call":
            tool_call = ProviderToolRequest(
                tool_name=event.tool_name,
                tool_call_id=event.tool_call_id,
                arguments=parse_tool_arguments(event.tool_arguments_json),
            )
        elif event.type == "completed":
            provider_response_id = event.provider_response_id
    return ProviderPlanningResult(
        tool_call=tool_call,
        provider_response_id=provider_response_id,
    )


def bounded_error_message(error: Exception, *, max_chars: int = 240) -> str:
    message = " ".join(str(error).split())
    if not message:
        return error.__class__.__name__
    message = re.sub(r"/Users/[^\s]+", "[local path removed]", message)
    message = re.sub(r"[\w.-]+\.pdf", "[pdf filename removed]", message)
    if len(message) > max_chars:
        return message[:max_chars].rstrip()
    return message


def initial_retrieval_query(
    resolved: context_resolution.ResolvedResearchRequest,
    *,
    conversation: ConversationContext,
) -> str:
    if (
        conversation.history_strategy == "followup_contextualized"
        and not resolved.subject
    ):
        return conversation.retrieval_query
    return resolved.resolved_query


def initial_tool_name(
    resolved: context_resolution.ResolvedResearchRequest,
) -> str:
    if resolved.page_reference is not None and (
        resolved.active_book_id
        or resolved.page_reference.printed_page_label
        or resolved.page_reference.pdf_page_number
    ):
        return "open_page"
    return "search_library"


def initial_tool_arguments(
    resolved: context_resolution.ResolvedResearchRequest,
    *,
    query: str,
) -> dict[str, object]:
    if initial_tool_name(resolved) == "open_page":
        page_reference = resolved.page_reference
        return {
            "book_id": resolved.active_book_id,
            "book_title_hint": None,
            "printed_page_label": None
            if page_reference is None
            else page_reference.printed_page_label,
            "pdf_page_number": None if page_reference is None else page_reference.pdf_page_number,
            "subject_hint": resolved.subject,
            "intent": resolved.intent,
        }
    return {
        "query": query,
        "intent": resolved.intent,
        "subject": resolved.subject,
        "limit": DEFAULT_HIT_LIMIT,
    }


def tool_definitions() -> tuple[provider.ProviderToolDefinition, ...]:
    return (
        provider.ProviderToolDefinition(
            name="search_library",
            description=(
                "Run backend-owned hybrid retrieval over enabled local source books."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "intent": {"type": "string"},
                    "subject": {"type": ["string", "null"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 12},
                },
                "required": ["query", "intent", "subject", "limit"],
                "additionalProperties": False,
            },
        ),
        provider.ProviderToolDefinition(
            name="open_page",
            description="Open a printed or PDF page from an enabled local source book.",
            parameters={
                "type": "object",
                "properties": {
                    "book_id": {"type": ["string", "null"]},
                    "book_title_hint": {"type": ["string", "null"]},
                    "printed_page_label": {"type": ["string", "null"]},
                    "pdf_page_number": {"type": ["integer", "null"]},
                    "subject_hint": {"type": ["string", "null"]},
                    "intent": {"type": "string"},
                },
                "required": [
                    "book_id",
                    "book_title_hint",
                    "printed_page_label",
                    "pdf_page_number",
                    "subject_hint",
                    "intent",
                ],
                "additionalProperties": False,
            },
        ),
        provider.ProviderToolDefinition(
            name="lookup_source_object",
            description="Inspect a structured source object from enabled local books.",
            parameters={
                "type": "object",
                "properties": {
                    "source_object_id": {"type": "string"},
                    "intent": {"type": "string"},
                },
                "required": ["source_object_id", "intent"],
                "additionalProperties": False,
            },
        ),
    )


def parse_tool_arguments(arguments_json: str | None) -> dict[str, object]:
    if not arguments_json:
        return {}
    try:
        decoded = json.loads(arguments_json)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def string_argument(arguments: dict[str, object], key: str) -> str | None:
    value = arguments.get(key)
    return value if isinstance(value, str) and value else None


def integer_argument(arguments: dict[str, object], key: str) -> int | None:
    value = arguments.get(key)
    return value if isinstance(value, int) else None


def validation_summary(
    validation: evidence_validation.EvidenceValidationResult,
) -> dict[str, object]:
    return {
        "status": validation.status,
        "accepted": sum(1 for judgment in validation.judgments if judgment.status == "accepted"),
        "partial": sum(1 for judgment in validation.judgments if judgment.status == "partial"),
        "rejected": sum(1 for judgment in validation.judgments if judgment.status == "rejected"),
        "reason_codes": [judgment.reason_code for judgment in validation.judgments],
    }


def retrieval_diagnostics_metadata(
    diagnostics: research.RetrievalDiagnostics,
) -> dict[str, object]:
    return {
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


def tool_output_summary(
    tool_result: research_tools.SearchLibraryResult,
    *,
    validation: evidence_validation.EvidenceValidationResult,
) -> dict[str, object]:
    return {
        "retrieval_run_id": tool_result.retrieval_run_id,
        "query": tool_result.query,
        "hit_count": len(tool_result.hits),
        "validation": validation_summary(validation),
        "diagnostics": retrieval_diagnostics_metadata(tool_result.diagnostics),
    }


def tool_output_payload(
    tool_result: research_tools.SearchLibraryResult,
    *,
    validation: evidence_validation.EvidenceValidationResult,
) -> dict[str, object]:
    return {
        **tool_output_summary(tool_result, validation=validation),
        "hits": [hit_payload(hit) for hit in tool_result.hits],
    }


def hit_payload(hit: RetrievedHit) -> dict[str, object]:
    return {
        "book_id": hit.book_id,
        "title": hit.title,
        "page_label": hit.page_range_label or hit.page_label,
        "page_number": hit.page_number,
        "source_object_id": hit.source_object_id,
        "object_type": hit.object_type,
        "object_title": hit.object_title,
        "snippet": hit.snippet,
        "rank": hit.rank,
    }


def partial_hits_from_judgments(
    validation: evidence_validation.EvidenceValidationResult,
) -> tuple[RetrievedHit, ...]:
    return tuple(
        judgment.hit
        for judgment in validation.judgments
        if judgment.status == "partial"
    )


def aggregate_evidence_status(
    *,
    accepted_hits: Sequence[RetrievedHit],
    partial_hits: Sequence[RetrievedHit],
    fallback_status: str,
) -> str:
    if accepted_hits:
        return "sufficient"
    if partial_hits:
        return "partial"
    return "insufficient" if fallback_status != "not_evaluated" else fallback_status


def record_accepted_evidence_retrieval_run(
    config: AppConfig,
    *,
    result: chat_store.SendChatResult,
    research_run: research.FamiliarResearchRun,
    query: str,
    accepted_hits: Sequence[RetrievedHit],
    diagnostics: research.RetrievalDiagnostics | None,
    evidence_status: str,
) -> str:
    source_book_ids = tuple(sorted({hit.book_id for hit in accepted_hits}))
    accepted_diagnostics = (
        diagnostics
        if diagnostics is None
        else replace(
            diagnostics,
            selected_count=len(accepted_hits),
            validation_status=evidence_status,
        )
    )
    retrieval_run_id = chat_store.record_retrieval_run(
        config,
        thread_id=result.thread.id,
        message_id=result.user_message.id,
        source_set_id=research_run.source_set_id,
        query=f"accepted evidence for {query}",
        hits=accepted_hits,
        source_book_ids=source_book_ids,
        diagnostics=accepted_diagnostics,
        intent=research_run.intent,
        resolved_query=query,
        tool_name="accepted_evidence",
    )
    chat_store.update_retrieval_run_validation_status(
        config,
        retrieval_run_id,
        validation_status=evidence_status,
        validation_summary={
            "status": evidence_status,
            "accepted": len(accepted_hits),
            "partial": 0,
            "rejected": 0,
            "reason_codes": ["accepted_evidence"],
        },
    )
    return retrieval_run_id
