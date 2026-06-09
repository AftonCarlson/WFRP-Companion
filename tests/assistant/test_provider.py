from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from wfrp_companion.assistant import provider


@dataclass
class FakeDeltaEvent:
    type: str
    delta: str


@dataclass
class FakeCompletedEvent:
    type: str
    response: object


class FakeResponse:
    id = "resp-1"
    usage = {"input_tokens": 3, "output_tokens": 4}


class ObjectUsage:
    input_tokens = 8
    output_tokens = 13
    cached_tokens = "not-an-int"


class FakeResponses:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] | None = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return [
            FakeDeltaEvent("response.output_text.delta", "Hello "),
            FakeDeltaEvent("response.output_text.delta", "world"),
            FakeCompletedEvent("response.completed", FakeResponse()),
        ]


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


def test_openai_provider_requires_api_key() -> None:
    with pytest.raises(provider.ProviderUnavailableError):
        provider.OpenAIProvider(api_key=None, model="gpt-5.4-mini")


def test_openai_provider_streams_text_deltas_and_metadata() -> None:
    fake_client = FakeOpenAIClient()
    openai_provider = provider.OpenAIProvider(
        api_key="test-key",
        model="gpt-5.4-mini",
        client_factory=lambda **kwargs: fake_client,
        timeout_seconds=12.5,
    )

    events = tuple(
        openai_provider.stream_response(
            messages=[provider.ProviderMessage(role="user", content="Hi")],
            request_id="run-1",
        )
    )

    assert [event.text_delta for event in events if event.type == "delta"] == [
        "Hello ",
        "world",
    ]
    assert events[-1].type == "completed"
    assert events[-1].provider_response_id == "resp-1"
    assert events[-1].input_tokens == 3
    assert events[-1].output_tokens == 4
    assert fake_client.responses.kwargs is not None
    assert fake_client.responses.kwargs["model"] == "gpt-5.4-mini"
    assert fake_client.responses.kwargs["stream"] is True
    assert fake_client.responses.kwargs["store"] is False
    assert "conversation" not in fake_client.responses.kwargs
    assert "previous_response_id" not in fake_client.responses.kwargs
    assert fake_client.responses.kwargs["extra_headers"] == {
        "X-Client-Request-Id": "run-1"
    }


def test_openai_provider_sends_tools_tool_results_and_previous_response_id() -> None:
    fake_client = FakeOpenAIClient()
    openai_provider = provider.OpenAIProvider(
        api_key="test-key",
        model="gpt-5.4-mini",
        client_factory=lambda **kwargs: fake_client,
    )

    events = tuple(
        openai_provider.stream_response(
            messages=(provider.ProviderMessage(role="user", content="Research"),),
            request_id="run-2",
            tools=(
                provider.ProviderToolDefinition(
                    name="search_library",
                    description="Search enabled source books.",
                    parameters={
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                ),
            ),
            tool_results=(
                provider.ProviderToolResult(
                    tool_call_id="call-1",
                    output_json='{"status":"ok"}',
                ),
            ),
            previous_response_id="resp-prev",
            tool_choice="none",
            parallel_tool_calls=False,
        )
    )

    assert events[-1].type == "completed"
    assert fake_client.responses.kwargs is not None
    assert fake_client.responses.kwargs["previous_response_id"] == "resp-prev"
    assert fake_client.responses.kwargs["tool_choice"] == "none"
    assert fake_client.responses.kwargs["parallel_tool_calls"] is False
    assert fake_client.responses.kwargs["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": '{"status":"ok"}',
        }
    ]
    assert fake_client.responses.kwargs["tools"] == [
        {
            "type": "function",
            "name": "search_library",
            "description": "Search enabled source books.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
            "strict": True,
        }
    ]


def test_openai_provider_streams_function_call_events() -> None:
    function_item = SimpleNamespace(
        type="function_call",
        name="open_page",
        call_id="call-open",
        arguments='{"printed_page_label":"99"}',
    )
    fake_client = FakeOpenAIClient()
    fake_client.responses.create = lambda **kwargs: [
        SimpleNamespace(type="response.output_item.done", item=function_item),
        FakeCompletedEvent("response.completed", FakeResponse()),
    ]
    openai_provider = provider.OpenAIProvider(
        api_key="test-key",
        model="gpt-5.4-mini",
        client_factory=lambda **kwargs: fake_client,
    )

    events = tuple(
        openai_provider.stream_response(
            messages=(provider.ProviderMessage(role="user", content="Research"),),
            request_id="run-3",
        )
    )

    assert events[0] == provider.ProviderStreamEvent(
        type="tool_call",
        tool_name="open_page",
        tool_call_id="call-open",
        tool_arguments_json='{"printed_page_label":"99"}',
    )
    assert events[-1].type == "completed"


def test_openai_provider_streams_function_argument_done_events_once() -> None:
    function_item = SimpleNamespace(
        type="function_call",
        name="open_page",
        call_id="call-open",
        arguments='{"printed_page_label":"99"}',
    )
    fake_client = FakeOpenAIClient()
    fake_client.responses.create = lambda **kwargs: [
        SimpleNamespace(
            type="response.function_call_arguments.done",
            name="open_page",
            call_id="call-open",
            arguments='{"printed_page_label":"99"}',
        ),
        SimpleNamespace(type="response.output_item.done", item=function_item),
        FakeCompletedEvent("response.completed", FakeResponse()),
    ]
    openai_provider = provider.OpenAIProvider(
        api_key="test-key",
        model="gpt-5.4-mini",
        client_factory=lambda **kwargs: fake_client,
    )

    events = tuple(
        openai_provider.stream_response(
            messages=(provider.ProviderMessage(role="user", content="Research"),),
            request_id="run-4",
        )
    )

    assert [event.type for event in events] == ["tool_call", "completed"]
    assert events[0].tool_name == "open_page"
    assert events[0].tool_call_id == "call-open"


def test_openai_provider_configures_client_retry_and_timeout() -> None:
    calls: list[dict[str, object]] = []

    def factory(**kwargs):
        calls.append(kwargs)
        return FakeOpenAIClient()

    provider.OpenAIProvider(
        api_key="test-key",
        model="gpt-5.4-mini",
        client_factory=factory,
        timeout_seconds=9.0,
    )

    assert calls == [{"api_key": "test-key", "max_retries": 0, "timeout": 9.0}]


def test_default_openai_client_constructs_sdk_client_without_network_call() -> None:
    client = provider.default_openai_client(api_key="test-key")

    assert hasattr(client, "responses")


def test_usage_value_supports_objects_none_and_non_integer_values() -> None:
    usage = ObjectUsage()

    assert provider.usage_value(usage, "input_tokens") == 8
    assert provider.usage_value(usage, "output_tokens") == 13
    assert provider.usage_value(usage, "cached_tokens") is None
    assert provider.usage_value(None, "input_tokens") is None
