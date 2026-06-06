from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from wfrp_companion.assistant import chat_store, prompts
from wfrp_companion.assistant.query_planner import meaningful_tokens
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database


FOLLOW_UP_TOKENS = {
    "it",
    "its",
    "they",
    "them",
    "he",
    "him",
    "his",
    "she",
    "her",
    "hers",
    "that",
    "those",
    "there",
    "same",
    "above",
}
FOLLOW_UP_PHRASES = (
    "what about",
    "how about",
    "what else",
    "and ",
    "also",
    "compare",
)


@dataclass(frozen=True)
class ConversationHistoryMessage:
    id: str
    role: str
    content: str
    created_at: str


@dataclass(frozen=True)
class ConversationContext:
    prompt_messages: tuple[prompts.PromptMessage, ...]
    retrieval_query: str
    history_message_ids: tuple[str, ...]
    history_turn_count: int
    history_strategy: str


def build_conversation_context(
    config: AppConfig,
    *,
    thread_id: str,
    current_user_message_id: str,
    current_user_content: str,
) -> ConversationContext:
    with initialize_database(config.db_path) as connection:
        history_messages = tuple(
            ConversationHistoryMessage(
                id=message.id,
                role=message.role,
                content=message.content,
                created_at=message.created_at,
            )
            for message in chat_store.load_completed_turn_messages_before_user_message(
                connection,
                thread_id=thread_id,
                before_user_message_id=current_user_message_id,
                max_turns=max(
                    config.chat_prompt_history_turn_limit,
                    config.chat_retrieval_history_turn_limit,
                ),
            )
        )
    prompt_history = bounded_prompt_history(
        limit_history_turns(
            history_messages,
            turn_limit=config.chat_prompt_history_turn_limit,
        ),
        char_limit=config.chat_prompt_history_char_limit,
    )
    retrieval_history = limit_history_turns(
        history_messages,
        turn_limit=config.chat_retrieval_history_turn_limit,
    )
    retrieval_query, history_strategy = build_history_aware_retrieval_query(
        current_user_content=current_user_content,
        history_messages=retrieval_history,
        char_limit=config.chat_retrieval_query_char_limit,
    )
    retrieval_metadata_history = (
        retrieval_history if history_strategy == "followup_contextualized" else ()
    )
    return ConversationContext(
        prompt_messages=tuple(
            prompts.PromptMessage(
                role=message.role,
                content=prompts.scrub_private_paths(message.content),
            )
            for message in prompt_history
        ),
        retrieval_query=retrieval_query,
        history_message_ids=tuple(message.id for message in retrieval_metadata_history),
        history_turn_count=len(retrieval_metadata_history) // 2,
        history_strategy=history_strategy,
    )


def bounded_prompt_history(
    messages: Sequence[ConversationHistoryMessage],
    *,
    char_limit: int,
) -> tuple[ConversationHistoryMessage, ...]:
    if char_limit <= 0:
        return ()
    turns = tuple(zip(messages[0::2], messages[1::2], strict=False))
    selected_turns: list[tuple[ConversationHistoryMessage, ConversationHistoryMessage]] = []
    remaining = char_limit
    for user_message, assistant_message in reversed(turns):
        turn_length = len(user_message.content) + len(assistant_message.content)
        if turn_length > remaining:
            continue
        selected_turns.append((user_message, assistant_message))
        remaining -= turn_length
    selected_messages: list[ConversationHistoryMessage] = []
    for user_message, assistant_message in reversed(selected_turns):
        selected_messages.extend((user_message, assistant_message))
    return tuple(selected_messages)


def limit_history_turns(
    messages: Sequence[ConversationHistoryMessage],
    *,
    turn_limit: int,
) -> tuple[ConversationHistoryMessage, ...]:
    if turn_limit <= 0:
        return ()
    return tuple(messages[-turn_limit * 2 :])


def build_history_aware_retrieval_query(
    *,
    current_user_content: str,
    history_messages: Sequence[ConversationHistoryMessage],
    char_limit: int,
) -> tuple[str, str]:
    if not history_messages:
        return (limit_text(current_user_content, char_limit), "none")
    if not is_followup_query(current_user_content):
        return (limit_text(current_user_content, char_limit), "self_contained")
    parts = [
        current_user_content.strip(),
        "",
        "Recent chat terms for reference resolution:",
    ]
    for message in history_messages:
        label = "User" if message.role == "user" else "Familiar"
        parts.append(f"{label}: {prompts.scrub_private_paths(message.content)}")
    return (limit_text("\n".join(parts), char_limit), "followup_contextualized")


def is_followup_query(query: str) -> bool:
    normalized = " ".join(query.casefold().split())
    raw_tokens = re.findall(r"(?u)\b[\w'-]+\b", normalized)
    tokens = meaningful_tokens(query)
    if not tokens:
        return True
    has_followup_reference = bool(FOLLOW_UP_TOKENS.intersection(raw_tokens))
    if has_followup_reference and len(tokens) <= 4:
        return True
    starts_with_followup_phrase = any(
        normalized.startswith(phrase) for phrase in FOLLOW_UP_PHRASES
    )
    return starts_with_followup_phrase and len(tokens) <= 1


def limit_text(text: str, char_limit: int) -> str:
    if char_limit <= 0:
        return ""
    if len(text) <= char_limit:
        return text
    return text[:char_limit].rstrip()
