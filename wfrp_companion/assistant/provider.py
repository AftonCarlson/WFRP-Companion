from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ProviderStreamEvent:
    type: str
    text_delta: str | None = None
    provider_response_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


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
    ) -> Iterable[ProviderStreamEvent]:
        stream = self.client.responses.create(
            model=self.model,
            input=[
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            stream=True,
            store=False,
            extra_headers={"X-Client-Request-Id": request_id},
        )
        for event in stream:
            event_type = getattr(event, "type", "")
            if event_type == "response.output_text.delta":
                yield ProviderStreamEvent(type="delta", text_delta=getattr(event, "delta", ""))
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


def usage_value(usage: object, key: str) -> int | None:
    if usage is None:
        return None
    if isinstance(usage, dict):
        value = usage.get(key)
    else:
        value = getattr(usage, key, None)
    return value if isinstance(value, int) else None
