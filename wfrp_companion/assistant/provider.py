from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ProviderToolDefinition:
    name: str
    description: str
    parameters: dict[str, object]
    strict: bool = True


@dataclass(frozen=True)
class ProviderToolResult:
    tool_call_id: str
    output_json: str


@dataclass(frozen=True)
class ProviderStreamEvent:
    type: str
    text_delta: str | None = None
    provider_response_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_arguments_json: str | None = None


class ProviderError(Exception):
    pass


class ProviderUnavailableError(ProviderError):
    pass


class ProviderClient(Protocol):
    responses: Any


ClientFactory = Callable[..., ProviderClient]


class OpenAIProvider:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        client_factory: ClientFactory | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not api_key:
            raise ProviderUnavailableError("OPENAI_API_KEY is not configured")
        self.model = model
        self.client = (client_factory or default_openai_client)(
            api_key=api_key,
            max_retries=0,
            timeout=timeout_seconds,
        )

    def stream_response(
        self,
        *,
        messages: Sequence[ProviderMessage],
        request_id: str,
        tools: Sequence[ProviderToolDefinition] = (),
        tool_results: Sequence[ProviderToolResult] = (),
        previous_response_id: str | None = None,
        tool_choice: object | None = None,
    ) -> Iterable[ProviderStreamEvent]:
        create_kwargs: dict[str, object] = {
            "model": self.model,
            "input": response_input(messages, tool_results),
            "stream": True,
            "store": False,
            "extra_headers": {"X-Client-Request-Id": request_id},
        }
        if tools:
            create_kwargs["tools"] = [tool_definition_payload(tool) for tool in tools]
        if previous_response_id is not None:
            create_kwargs["previous_response_id"] = previous_response_id
        if tool_choice is not None:
            create_kwargs["tool_choice"] = tool_choice

        stream = self.client.responses.create(
            **create_kwargs,
        )
        seen_tool_call_ids: set[str] = set()
        for event in stream:
            event_type = getattr(event, "type", "")
            if event_type == "response.output_text.delta":
                yield ProviderStreamEvent(type="delta", text_delta=getattr(event, "delta", ""))
            elif event_type == "response.function_call_arguments.done":
                tool_call_id = getattr(event, "call_id", None)
                if isinstance(tool_call_id, str) and tool_call_id not in seen_tool_call_ids:
                    seen_tool_call_ids.add(tool_call_id)
                    yield ProviderStreamEvent(
                        type="tool_call",
                        tool_name=getattr(event, "name", None),
                        tool_call_id=tool_call_id,
                        tool_arguments_json=getattr(event, "arguments", None),
                    )
            elif event_type == "response.output_item.done":
                item = getattr(event, "item", None)
                if getattr(item, "type", None) == "function_call":
                    tool_call_id = getattr(item, "call_id", None)
                    if (
                        isinstance(tool_call_id, str)
                        and tool_call_id not in seen_tool_call_ids
                    ):
                        seen_tool_call_ids.add(tool_call_id)
                        yield ProviderStreamEvent(
                            type="tool_call",
                            tool_name=getattr(item, "name", None),
                            tool_call_id=tool_call_id,
                            tool_arguments_json=getattr(item, "arguments", None),
                        )
            elif event_type == "response.completed":
                response = getattr(event, "response", None)
                usage = getattr(response, "usage", None)
                yield ProviderStreamEvent(
                    type="completed",
                    provider_response_id=getattr(response, "id", None),
                    input_tokens=usage_value(usage, "input_tokens"),
                    output_tokens=usage_value(usage, "output_tokens"),
                )


def default_openai_client(**kwargs: object) -> ProviderClient:
    from openai import OpenAI

    return OpenAI(**kwargs)


def response_input(
    messages: Sequence[ProviderMessage],
    tool_results: Sequence[ProviderToolResult],
) -> list[dict[str, object]]:
    if tool_results:
        return [
            {
                "type": "function_call_output",
                "call_id": result.tool_call_id,
                "output": result.output_json,
            }
            for result in tool_results
        ]
    return [
        {"role": message.role, "content": message.content}
        for message in messages
    ]


def tool_definition_payload(tool: ProviderToolDefinition) -> dict[str, object]:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters,
        "strict": tool.strict,
    }


def usage_value(usage: object, key: str) -> int | None:
    if usage is None:
        return None
    if isinstance(usage, dict):
        value = usage.get(key)
    else:
        value = getattr(usage, key, None)
    return value if isinstance(value, int) else None
