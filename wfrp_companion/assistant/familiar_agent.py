from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

from wfrp_companion.assistant import agent_planning
from wfrp_companion.assistant import answer_contract
from wfrp_companion.assistant import chat_store
from wfrp_companion.assistant import context_resolution
from wfrp_companion.assistant import evidence_constraints
from wfrp_companion.assistant import evidence_validation
from wfrp_companion.assistant import prompts
from wfrp_companion.assistant import provider
from wfrp_companion.assistant import requirement_planner
from wfrp_companion.assistant import research
from wfrp_companion.assistant import research_tools
from wfrp_companion.assistant import turn_contract
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
    answer_outcome: answer_contract.AnswerOutcome
    final_retrieval_run_id: str | None
    final_prompt_messages: tuple[prompts.PromptMessage, ...]
    progress_events: tuple[FamiliarProgressEvent, ...]


def run_research(
    config: AppConfig,
    *,
    result: chat_store.SendChatResult,
    content: str,
    conversation: ConversationContext,
    turn_decision: turn_contract.TurnDecision,
    response_provider_factory: Callable[[AppConfig], object],
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
                "intent": resolved.intent,
                "has_reader_context": bool(reader_metadata),
            },
        )
    ]

    tool_rounds_used = 0
    accepted_hits: list[RetrievedHit] = []
    partial_hits: list[RetrievedHit] = []
    final_retrieval_run_id: str | None = None
    final_diagnostics: research.RetrievalDiagnostics | None = None
    last_validation_status = "not_evaluated"

    advisory_provider_call_id: str | None = None
    try:
        response_provider = response_provider_factory(config)
        plan_result = request_research_plan(
            response_provider,
            request_id=result.model_run.id,
            research_run_id=research_run.id,
            resolved=resolved,
            initial_query=initial_query,
            conversation=conversation,
        )
        advisory_provider_call_id = plan_result.plan.provider_call_id
    except (agent_planning.PlanValidationError, provider.ProviderError):
        advisory_provider_call_id = None
    planning_content = (
        initial_query
        if conversation.history_strategy == "followup_contextualized"
        or (resolved.subject is None and initial_query != content.strip().casefold())
        else content
    )
    planning_decision = (
        replace(turn_decision, subject=None)
        if conversation.history_strategy == "followup_contextualized"
        else turn_decision
    )
    app_plan = requirement_planner.build_research_plan(
        research_run_id=research_run.id,
        content=planning_content,
        decision=planning_decision,
        resolved=resolved,
    )
    if advisory_provider_call_id is not None:
        app_plan = replace(app_plan, provider_call_id=advisory_provider_call_id)
    research_plan = chat_store.record_familiar_research_plan(config, app_plan)
    progress.append(
        FamiliarProgressEvent(
            type="research_plan",
            metadata=research_plan_event_metadata(research_plan),
        )
    )
    accepted_hits_by_requirement: dict[str, list[RetrievedHit]] = {
        requirement.id: [] for requirement in research_plan.requirements
    }
    partial_hits_by_requirement: dict[str, list[RetrievedHit]] = {
        requirement.id: [] for requirement in research_plan.requirements
    }
    attempted_action_signatures: set[tuple[str, str, str]] = set()
    first_action = research_plan.planned_actions[0]
    validated_first_action = validate_planned_tool_action(
        research_plan,
        first_action,
    )
    outcome = execute_tool_and_validate(
        config,
        research_run=research_run,
        result=result,
        resolved=resolved,
        research_plan_id=research_plan.id,
        requirement_id=validated_first_action.requirement_id,
        requirement=requirement_by_id(
            research_plan,
            validated_first_action.requirement_id,
        ),
        purpose=validated_first_action.purpose,
        step_number=1,
        call_index=0,
        provider_call_id=None,
        tool_name=validated_first_action.tool_name,
        arguments=validated_first_action.arguments,
        conversation=conversation,
    )
    attempted_action_signatures.add(action_signature(validated_first_action))
    tool_rounds_used += 1
    progress.extend(outcome.progress_events)
    extend_unique_hits(accepted_hits, outcome.validation.accepted_hits)
    record_requirement_validation_outcome(
        accepted_hits_by_requirement,
        partial_hits_by_requirement,
        validated_first_action.requirement_id,
        outcome.validation,
    )
    if outcome.validation.status == "partial":
        extend_unique_hits(partial_hits, partial_hits_from_judgments(outcome.validation))
    final_retrieval_run_id = outcome.tool_result.retrieval_run_id
    final_diagnostics = outcome.tool_result.diagnostics
    last_validation_status = outcome.validation.status
    prior_tool_outputs: list[dict[str, object]] = [outcome.tool_output]
    while (
        not plan_requirements_satisfied(research_plan, accepted_hits_by_requirement)
        and tool_rounds_used < MAX_TOOL_ROUNDS
    ):
        validated_action = next_backend_scheduled_action(
            research_plan,
            accepted_hits_by_requirement=accepted_hits_by_requirement,
            partial_hits_by_requirement=partial_hits_by_requirement,
            attempted_action_signatures=attempted_action_signatures,
        )
        if validated_action is None:
            break
        attempted_action_signatures.add(action_signature(validated_action))
        outcome = execute_tool_and_validate(
            config,
            research_run=research_run,
            result=result,
            resolved=resolved,
            research_plan_id=research_plan.id,
            requirement_id=validated_action.requirement_id,
            requirement=requirement_by_id(
                research_plan,
                validated_action.requirement_id,
            ),
            purpose=validated_action.purpose,
            step_number=tool_rounds_used + 1,
            call_index=0,
            provider_call_id=validated_action.provider_call_id,
            tool_name=validated_action.tool_name,
            arguments=validated_action.arguments,
            conversation=conversation,
        )
        tool_rounds_used += 1
        progress.extend(outcome.progress_events)
        extend_unique_hits(accepted_hits, outcome.validation.accepted_hits)
        record_requirement_validation_outcome(
            accepted_hits_by_requirement,
            partial_hits_by_requirement,
            validated_action.requirement_id,
            outcome.validation,
        )
        if outcome.validation.status == "partial":
            extend_unique_hits(partial_hits, partial_hits_from_judgments(outcome.validation))
        final_retrieval_run_id = outcome.tool_result.retrieval_run_id
        final_diagnostics = outcome.tool_result.diagnostics
        last_validation_status = outcome.validation.status
        prior_tool_outputs.append(outcome.tool_output)

    evidence_status = plan_evidence_status(
        research_plan,
        accepted_hits_by_requirement=accepted_hits_by_requirement,
        partial_hits_by_requirement=partial_hits_by_requirement,
        fallback_status=last_validation_status,
    )
    answer_outcome = answer_contract.build_answer_outcome(
        research_plan,
        accepted_hits_by_requirement=accepted_hits_by_requirement,
        partial_hits_by_requirement=partial_hits_by_requirement,
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
    terminal_status = "completed" if evidence_status == "sufficient" else "insufficient"
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
                "requirements": public_requirement_status_summaries(
                    research_plan,
                    accepted_hits_by_requirement=accepted_hits_by_requirement,
                    partial_hits_by_requirement=partial_hits_by_requirement,
                ),
                "tool_rounds_used": tool_rounds_used,
                "answer_outcome": answer_outcome.kind,
                "missing_summaries": list(answer_outcome.missing_summaries),
            },
        )
    )
    final_prompt_messages = prompts.build_final_answer_prompt_messages(
        question=content,
        accepted_hits=tuple(accepted_hits),
        evidence_status=evidence_status,
        plan_summary=research_plan.plan_summary,
        requirement_summaries=requirement_status_summaries(
            research_plan,
            accepted_hits_by_requirement=accepted_hits_by_requirement,
            partial_hits_by_requirement=partial_hits_by_requirement,
        ),
        answer_policy="cite_required",
        answer_outcome=answer_outcome.kind,
        missing_summaries=answer_outcome.missing_summaries,
        recent_messages=conversation.prompt_messages,
        context_char_limit=config.chat_context_char_limit,
    )
    return FamiliarResearchResult(
        research_run=research_run,
        accepted_hits=tuple(accepted_hits),
        evidence_status=evidence_status,
        answer_outcome=answer_outcome,
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
class ResearchPlanResult:
    plan: agent_planning.ResearchPlan
    provider_response_id: str | None


@dataclass(frozen=True)
class ValidatedToolAction:
    tool_name: str
    requirement_id: str
    purpose: str | None
    arguments: dict[str, object]
    provider_call_id: str | None


def execute_tool_and_validate(
    config: AppConfig,
    *,
    research_run: research.FamiliarResearchRun,
    result: chat_store.SendChatResult,
    resolved: context_resolution.ResolvedResearchRequest,
    research_plan_id: str | None = None,
    requirement_id: str | None = None,
    requirement: agent_planning.EvidenceRequirement | None = None,
    purpose: str | None = None,
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
        research_plan_id=research_plan_id,
        requirement_id=requirement_id,
        purpose=purpose,
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
                "arguments": public_tool_arguments(tool_name, arguments),
                "requirement_id": requirement_id,
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
            requirement=requirement,
        )
        if requirement is None:
            validation = evidence_validation.validate_hits(
                tool_result.hits,
                subject=resolved.subject,
                intent=resolved.intent,
                source_book_ids=tool_result.source_book_ids,
                config=config,
            )
        else:
            validation = evidence_validation.validate_hits_for_requirement(
                tool_result.hits,
                requirement=requirement,
                source_book_ids=tool_result.source_book_ids,
                config=config,
            )
        evidence_validation.record_evidence_judgments(
            config,
            research_run_id=research_run.id,
            research_plan_id=research_plan_id,
            requirement_id=requirement_id,
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
            FamiliarProgressEvent(
                type="retrieval",
                hits=validation.accepted_hits,
                metadata={
                    "retrieval_run_id": tool_result.retrieval_run_id,
                    "candidate_hit_count": len(tool_result.hits),
                    "accepted_hit_count": len(validation.accepted_hits),
                },
            ),
            FamiliarProgressEvent(
                type="tool_result",
                hits=validation.accepted_hits,
                metadata={
                    "research_run_id": research_run.id,
                    "tool_call_id": succeeded.id,
                    "tool_name": succeeded.tool_name,
                    "retrieval_run_id": tool_result.retrieval_run_id,
                    "hit_count": len(tool_result.hits),
                    "accepted_hit_count": len(validation.accepted_hits),
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
    requirement: agent_planning.EvidenceRequirement | None = None,
) -> research_tools.SearchLibraryResult:
    if tool_name == "search_library":
        query = string_argument(arguments, "query") or resolved.resolved_query
        requirement_constraint = (
            evidence_constraints.constraint_from_requirement(requirement)
            if requirement is not None
            else None
        )
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
            requirement_constraint=requirement_constraint,
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


def request_research_plan(
    response_provider: object,
    *,
    request_id: str,
    research_run_id: str,
    resolved: context_resolution.ResolvedResearchRequest,
    initial_query: str,
    conversation: ConversationContext,
) -> ResearchPlanResult:
    messages = prompts.build_research_planning_prompt_messages(
        raw_query=resolved.raw_query,
        resolved_query=initial_query,
        intent=resolved.intent,
        subject=resolved.subject,
        active_book_id=resolved.active_book_id,
        active_printed_page_label=None
        if resolved.page_reference is None
        else resolved.page_reference.printed_page_label,
        recent_messages=conversation.prompt_messages,
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
        tools=(agent_planning.planning_tool_definition(),),
        tool_results=(),
        previous_response_id=None,
        tool_choice={"type": "function", "name": "set_research_plan"},
        parallel_tool_calls=False,
    ):
        if event.type == "tool_call":
            if tool_call is not None:
                raise provider.ProviderError("Planning returned multiple tool calls")
            tool_call = ProviderToolRequest(
                tool_name=event.tool_name,
                tool_call_id=event.tool_call_id,
                arguments=parse_tool_arguments(event.tool_arguments_json),
            )
        elif event.type == "completed":
            provider_response_id = event.provider_response_id
    if tool_call is None or tool_call.tool_name != "set_research_plan":
        raise provider.ProviderError("Planning did not return set_research_plan")
    plan = agent_planning.parse_research_plan(
        tool_call.arguments,
        research_run_id=research_run_id,
        plan_id=chat_store.new_id("plan"),
        revision=1,
        provider_call_id=tool_call.tool_call_id,
    )
    return ResearchPlanResult(
        plan=plan,
        provider_response_id=provider_response_id,
    )


def validate_planned_tool_action(
    plan: agent_planning.ResearchPlan,
    action: agent_planning.PlannedAction,
) -> ValidatedToolAction:
    if action.tool_name == "finish_research":
        raise provider.ProviderError("finish_research is not a local retrieval tool")
    requirement_id = action.requirement_id
    if requirement_id is None:
        raise provider.ProviderError("tool action missing requirement_id")
    validate_requirement_id(plan, requirement_id)
    argument_requirement_id = string_argument(action.arguments, "requirement_id")
    if argument_requirement_id is not None and argument_requirement_id != requirement_id:
        raise provider.ProviderError("tool action requirement_id mismatch")
    if action.tool_name not in local_tool_names():
        raise provider.ProviderError(f"Unknown Familiar tool: {action.tool_name}")
    return ValidatedToolAction(
        tool_name=action.tool_name,
        requirement_id=requirement_id,
        purpose=action.purpose,
        arguments=dict(action.arguments),
        provider_call_id=None,
    )


def validate_provider_tool_action(
    plan: agent_planning.ResearchPlan,
    tool_call: ProviderToolRequest,
) -> ValidatedToolAction:
    tool_name = tool_call.tool_name
    if tool_name is None:
        raise provider.ProviderError("provider action did not include a tool name")
    if tool_name not in local_tool_names():
        raise provider.ProviderError(f"Unknown Familiar tool: {tool_name}")
    requirement_id = string_argument(tool_call.arguments, "requirement_id")
    if requirement_id is None:
        raise provider.ProviderError("tool action missing requirement_id")
    validate_requirement_id(plan, requirement_id)
    return ValidatedToolAction(
        tool_name=tool_name,
        requirement_id=requirement_id,
        purpose=string_argument(tool_call.arguments, "decision_summary"),
        arguments=tool_call.arguments,
        provider_call_id=tool_call.tool_call_id,
    )


def validate_finish_research_action(
    plan: agent_planning.ResearchPlan,
    arguments: dict[str, object],
    *,
    accepted_hits: Sequence[RetrievedHit],
    tool_rounds_used: int,
    plan_satisfied: bool = True,
) -> None:
    reason = string_argument(arguments, "reason")
    if reason not in {"requirements_satisfied", "budget_exhausted", "no_useful_action"}:
        raise provider.ProviderError("finish_research reason is invalid")
    evidence_status = string_argument(arguments, "evidence_status")
    if evidence_status not in {"sufficient", "partial", "insufficient"}:
        raise provider.ProviderError("finish_research evidence_status is invalid")
    requirement_ids = string_list_argument(arguments, "requirement_ids")
    if not requirement_ids:
        raise provider.ProviderError("finish_research missing requirement_ids")
    for requirement_id in requirement_ids:
        validate_requirement_id(plan, requirement_id)
    if reason == "requirements_satisfied" and not accepted_hits:
        raise provider.ProviderError("finish_research cannot satisfy without evidence")
    if reason == "requirements_satisfied" and not plan_satisfied:
        raise provider.ProviderError("finish_research cannot satisfy unsatisfied requirements")
    if reason == "budget_exhausted" and tool_rounds_used < MAX_TOOL_ROUNDS:
        raise provider.ProviderError("finish_research budget is not exhausted")
    decision_summary = string_argument(arguments, "decision_summary")
    if decision_summary is None:
        raise provider.ProviderError("finish_research missing decision_summary")


def validate_requirement_id(
    plan: agent_planning.ResearchPlan,
    requirement_id: str,
) -> None:
    known_requirement_ids = {requirement.id for requirement in plan.requirements}
    if requirement_id not in known_requirement_ids:
        raise provider.ProviderError(f"unknown requirement: {requirement_id}")


def requirement_by_id(
    plan: agent_planning.ResearchPlan,
    requirement_id: str,
) -> agent_planning.EvidenceRequirement:
    for requirement in plan.requirements:
        if requirement.id == requirement_id:
            return requirement
    raise provider.ProviderError(f"unknown requirement: {requirement_id}")


def local_tool_names() -> set[str]:
    return {"search_library", "open_page", "lookup_source_object"}


def research_plan_event_metadata(
    plan: agent_planning.ResearchPlan,
) -> dict[str, object]:
    return {
        "research_run_id": plan.research_run_id,
        "research_plan_id": plan.id,
        "intent": plan.intent,
        "requirement_count": len(plan.requirements),
        "requirements": [
            {
                "id": requirement.id,
                "requirement_type": requirement.requirement_type,
                "min_accepted_hits": requirement.min_accepted_hits,
                "required": requirement.required,
            }
            for requirement in plan.requirements
        ],
    }


def requirement_status_summaries(
    plan: agent_planning.ResearchPlan,
    *,
    accepted_hits_by_requirement: dict[str, list[RetrievedHit]],
    partial_hits_by_requirement: dict[str, list[RetrievedHit]],
) -> tuple[dict[str, object], ...]:
    summaries: list[dict[str, object]] = []
    for requirement in plan.requirements:
        accepted_count = len(accepted_hits_by_requirement.get(requirement.id, []))
        partial_count = len(partial_hits_by_requirement.get(requirement.id, []))
        if accepted_count >= requirement.min_accepted_hits:
            status = "satisfied"
        elif accepted_count or partial_count:
            status = "partial"
        else:
            status = "unsatisfied"
        summaries.append(
            {
                "id": requirement.id,
                "requirement_type": requirement.requirement_type,
                "status": status,
                "accepted_hit_count": accepted_count,
                "partial_hit_count": partial_count,
                "min_accepted_hits": requirement.min_accepted_hits,
                "required": requirement.required,
                "subject": {
                    "canonical": requirement.subject.canonical,
                    "surface": requirement.subject.surface,
                    "include_terms": list(requirement.subject.include_terms),
                    "exclude_terms": list(requirement.subject.exclude_terms),
                    "book_title_hints": list(requirement.subject.book_title_hints),
                    "page_hints": list(requirement.subject.page_hints),
                },
                "required_terms": list(requirement.required_terms),
                "excluded_terms": list(requirement.excluded_terms),
                "object_type_hints": list(requirement.object_type_hints),
            }
        )
    return tuple(summaries)


def next_backend_scheduled_action(
    plan: agent_planning.ResearchPlan,
    *,
    accepted_hits_by_requirement: dict[str, list[RetrievedHit]],
    partial_hits_by_requirement: dict[str, list[RetrievedHit]],
    attempted_action_signatures: set[tuple[str, str, str]],
) -> ValidatedToolAction | None:
    del partial_hits_by_requirement
    attempted_requirement_ids = {
        requirement_id
        for requirement_id, _tool_name, _target in attempted_action_signatures
    }
    unsatisfied = tuple(
        requirement
        for requirement in plan.requirements
        if requirement.required
        and len(accepted_hits_by_requirement.get(requirement.id, ()))
        < requirement.min_accepted_hits
    )
    for require_fresh_requirement in (True, False):
        for requirement in unsatisfied:
            if require_fresh_requirement and requirement.id in attempted_requirement_ids:
                continue
            action = scheduled_search_action(plan, requirement)
            if action_signature(action) in attempted_action_signatures:
                continue
            return action
    return None


def scheduled_search_action(
    plan: agent_planning.ResearchPlan,
    requirement: agent_planning.EvidenceRequirement,
) -> ValidatedToolAction:
    subject = (
        requirement.subject.canonical
        or requirement.subject.surface
        or " ".join(requirement.subject.include_terms)
        or plan.subject.canonical
        or plan.subject.surface
    )
    query = requirement_query(requirement, subject=subject)
    arguments: dict[str, object] = {
        "requirement_id": requirement.id,
        "query": query,
        "intent": plan.intent,
        "subject": subject,
        "limit": DEFAULT_HIT_LIMIT,
        "include_terms": list(requirement.subject.include_terms),
        "exclude_terms": list(
            (*requirement.subject.exclude_terms, *requirement.excluded_terms)
        ),
        "object_type_hints": list(requirement.object_type_hints),
        "book_title_hints": list(requirement.subject.book_title_hints),
        "page_hints": list(requirement.subject.page_hints),
    }
    return ValidatedToolAction(
        tool_name="search_library",
        requirement_id=requirement.id,
        purpose=f"Search checked books for unsatisfied requirement {requirement.id}.",
        arguments=arguments,
        provider_call_id=None,
    )


def requirement_query(
    requirement: agent_planning.EvidenceRequirement,
    *,
    subject: str | None,
) -> str:
    parts: list[str] = []
    if subject:
        parts.append(subject)
    subject_tokens = set(subject.casefold().split()) if subject else set()
    if requirement.requirement_type == "topical_evidence":
        parts.extend(
            term
            for term in requirement.subject.include_terms
            if term.casefold() not in subject_tokens
        )
    parts.extend(requirement.required_terms)
    if requirement.requirement_type == "statline_evidence":
        parts.append("statline")
    elif requirement.requirement_type == "page_evidence":
        parts.extend(requirement.subject.page_hints)
    elif requirement.requirement_type == "source_object_evidence":
        parts.extend(requirement.object_type_hints)
    unique_parts: list[str] = []
    seen: set[str] = set()
    for part in parts:
        normalized = " ".join(part.casefold().split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_parts.append(part)
    query = " ".join(unique_parts).strip()
    return query or requirement.id.replace("_", " ")


def action_signature(action: ValidatedToolAction) -> tuple[str, str, str]:
    query = string_argument(action.arguments, "query") or ""
    source_object_id = string_argument(action.arguments, "source_object_id") or ""
    page = (
        string_argument(action.arguments, "printed_page_label")
        or str(integer_argument(action.arguments, "pdf_page_number") or "")
    )
    target = query or source_object_id or page
    return (action.requirement_id, action.tool_name, target.casefold())


def public_requirement_status_summaries(
    plan: agent_planning.ResearchPlan,
    *,
    accepted_hits_by_requirement: dict[str, list[RetrievedHit]],
    partial_hits_by_requirement: dict[str, list[RetrievedHit]],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "id": summary["id"],
            "requirement_type": summary["requirement_type"],
            "status": summary["status"],
            "accepted_hit_count": summary["accepted_hit_count"],
            "partial_hit_count": summary["partial_hit_count"],
            "min_accepted_hits": summary["min_accepted_hits"],
            "required": summary["required"],
        }
        for summary in requirement_status_summaries(
            plan,
            accepted_hits_by_requirement=accepted_hits_by_requirement,
            partial_hits_by_requirement=partial_hits_by_requirement,
        )
    )


def plan_requirements_satisfied(
    plan: agent_planning.ResearchPlan,
    accepted_hits_by_requirement: dict[str, list[RetrievedHit]],
) -> bool:
    required_requirements = tuple(
        requirement for requirement in plan.requirements if requirement.required
    )
    if not required_requirements:
        return False
    return all(
        len(accepted_hits_by_requirement.get(requirement.id, ()))
        >= requirement.min_accepted_hits
        for requirement in required_requirements
    )


def plan_evidence_status(
    plan: agent_planning.ResearchPlan,
    *,
    accepted_hits_by_requirement: dict[str, list[RetrievedHit]],
    partial_hits_by_requirement: dict[str, list[RetrievedHit]],
    fallback_status: str,
) -> str:
    if plan_requirements_satisfied(plan, accepted_hits_by_requirement):
        return "sufficient"
    if any(accepted_hits_by_requirement.values()) or any(
        partial_hits_by_requirement.values()
    ):
        return "partial"
    return "insufficient" if fallback_status != "not_evaluated" else fallback_status


def record_requirement_validation_outcome(
    accepted_hits_by_requirement: dict[str, list[RetrievedHit]],
    partial_hits_by_requirement: dict[str, list[RetrievedHit]],
    requirement_id: str,
    validation: evidence_validation.EvidenceValidationResult,
) -> None:
    extend_unique_hits(
        accepted_hits_by_requirement.setdefault(requirement_id, []),
        validation.accepted_hits,
    )
    extend_unique_hits(
        partial_hits_by_requirement.setdefault(requirement_id, []),
        partial_hits_from_judgments(validation),
    )


def extend_unique_hits(
    target: list[RetrievedHit],
    hits: Sequence[RetrievedHit],
) -> None:
    seen = {evidence_key(hit) for hit in target}
    for hit in hits:
        key = evidence_key(hit)
        if key in seen:
            continue
        seen.add(key)
        target.append(hit)


def unique_hits(hits: Sequence[RetrievedHit]) -> tuple[RetrievedHit, ...]:
    unique: list[RetrievedHit] = []
    extend_unique_hits(unique, hits)
    return tuple(unique)


def evidence_key(hit: RetrievedHit) -> tuple[str, str]:
    if hit.source_object_id is not None:
        return ("source_object", hit.source_object_id)
    return ("page", hit.page_id)


def public_tool_arguments(
    tool_name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    allowed_keys_by_tool = {
        "search_library": ("intent", "limit", "requirement_id"),
        "open_page": (
            "book_id",
            "printed_page_label",
            "pdf_page_number",
            "intent",
            "requirement_id",
        ),
        "lookup_source_object": ("source_object_id", "intent", "requirement_id"),
    }
    allowed_keys = allowed_keys_by_tool.get(tool_name, ())
    public_arguments: dict[str, object] = {}
    for key in allowed_keys:
        if key not in arguments:
            continue
        public_arguments[key] = public_argument_value(arguments[key])
    return public_arguments


def public_argument_value(value: object) -> object:
    if isinstance(value, str):
        return public_trace_text(value, max_chars=160)
    if isinstance(value, int) or value is None:
        return value
    if isinstance(value, list):
        return [
            public_trace_text(item, max_chars=80) if isinstance(item, str) else item
            for item in value[:8]
            if isinstance(item, (str, int, bool)) or item is None
        ]
    return str(value)[:80]


def public_trace_text(value: str | None, *, max_chars: int = 240) -> str:
    if value is None:
        return ""
    text = prompts.scrub_private_paths(" ".join(value.split()))
    if len(text) > max_chars:
        return text[:max_chars].rstrip()
    return text


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


def string_list_argument(arguments: dict[str, object], key: str) -> tuple[str, ...]:
    value = arguments.get(key)
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


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
    accepted_hit_payloads = [hit_payload(hit) for hit in validation.accepted_hits]
    return {
        **tool_output_summary(tool_result, validation=validation),
        "hits": accepted_hit_payloads,
        "accepted_hits": accepted_hit_payloads,
        "partial_reason_counts": judgment_reason_counts(validation, status="partial"),
        "rejected_reason_counts": judgment_reason_counts(validation, status="rejected"),
    }


def judgment_reason_counts(
    validation: evidence_validation.EvidenceValidationResult,
    *,
    status: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for judgment in validation.judgments:
        if judgment.status != status:
            continue
        counts[judgment.reason_code] = counts.get(judgment.reason_code, 0) + 1
    return counts


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
    unique_accepted_hits = unique_hits(accepted_hits)
    source_book_ids = tuple(sorted({hit.book_id for hit in unique_accepted_hits}))
    accepted_diagnostics = (
        diagnostics
        if diagnostics is None
        else replace(
            diagnostics,
            selected_count=len(unique_accepted_hits),
            validation_status=evidence_status,
        )
    )
    retrieval_run_id = chat_store.record_retrieval_run(
        config,
        thread_id=result.thread.id,
        message_id=result.user_message.id,
        source_set_id=research_run.source_set_id,
        query=f"accepted evidence for {query}",
        hits=renumber_hits(unique_accepted_hits),
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
            "accepted": len(unique_accepted_hits),
            "partial": 0,
            "rejected": 0,
            "reason_codes": ["accepted_evidence"],
        },
    )
    return retrieval_run_id


def renumber_hits(hits: Sequence[RetrievedHit]) -> tuple[RetrievedHit, ...]:
    return tuple(replace(hit, rank=index) for index, hit in enumerate(hits, start=1))
