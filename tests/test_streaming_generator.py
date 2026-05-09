"""Tests for stream_chat_completion's OpenAI stream adapter."""
from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import streaming


def _payload(raw: str) -> dict | str:
    data = raw.removeprefix("data: ").strip()
    return data if data == "[DONE]" else json.loads(data)


class FakeOpenAIStream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def __iter__(self):
        return iter(self.chunks)

    def close(self):
        self.closed = True


class FakeClient:
    def __init__(self, stream_or_exc):
        self.stream_or_exc = stream_or_exc
        self.kwargs = None
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.stream_or_exc, Exception):
            raise self.stream_or_exc
        return self.stream_or_exc


def _chunk(*, content=None, reasoning=None, tool_calls=None, finish_reason=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    if reasoning is not None:
        delta.reasoning_content = reasoning
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)]
    )


def _tool_delta(index, *, id="", name="", arguments=""):
    return SimpleNamespace(
        index=index,
        id=id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class TestStreamChatCompletion:
    def test_sends_request_with_model_messages_temperature_timeout_and_tools(self):
        stream = FakeOpenAIStream([_chunk(content="hi")])
        client = FakeClient(stream)

        events = list(streaming.stream_chat_completion(
            client,
            model="gpt-test",
            messages=[{"role": "user", "content": "hello"}],
            tools=[{"type": "function"}],
            cancel_event=threading.Event(),
            temperature=0.2,
            timeout=30,
        ))

        assert client.kwargs["model"] == "gpt-test"
        assert client.kwargs["messages"] == [{"role": "user", "content": "hello"}]
        assert client.kwargs["temperature"] == 0.2
        assert client.kwargs["timeout"] == 30
        assert client.kwargs["tools"] == [{"type": "function"}]
        assert client.kwargs["tool_choice"] == "auto"
        assert _payload(events[-1]) == "[DONE]"

    def test_streams_reasoning_and_text_events(self):
        stream = FakeOpenAIStream([
            _chunk(reasoning="thinking "),
            _chunk(content="hello"),
        ])
        client = FakeClient(stream)

        payloads = [_payload(e) for e in streaming.stream_chat_completion(
            client, "gpt", [], [], threading.Event()
        )]

        assert payloads[:2] == [
            {"type": "reasoning", "content": "thinking "},
            {"type": "text", "content": "hello"},
        ]
        assert payloads[-1] == "[DONE]"

    def test_streams_tool_start_once_and_final_tool_calls(self):
        stream = FakeOpenAIStream([
            _chunk(tool_calls=[_tool_delta(0, id="call_1", name="ba", arguments='{"cmd":')]),
            _chunk(tool_calls=[_tool_delta(0, name="sh", arguments='"ls"}')]),
            _chunk(finish_reason="tool_calls"),
        ])
        client = FakeClient(stream)

        payloads = [_payload(e) for e in streaming.stream_chat_completion(
            client, "gpt", [], [{"type": "function"}], threading.Event()
        )]

        assert payloads[0] == {"type": "tool_start", "name": "ba"}
        assert payloads[1] == {
            "type": "tool_calls",
            "calls": [{
                "id": "call_1",
                "function": {"name": "bash", "arguments": '{"cmd":"ls"}'},
            }],
        }

    def test_cancel_closes_openai_stream_and_still_finishes_sse(self):
        cancel = threading.Event()
        stream = FakeOpenAIStream([
            _chunk(content="first"),
            _chunk(content="second"),
        ])
        client = FakeClient(stream)

        gen = streaming.stream_chat_completion(client, "gpt", [], [], cancel)
        assert _payload(next(gen)) == {"type": "text", "content": "first"}
        cancel.set()
        remaining = list(gen)

        assert stream.closed is True
        assert [_payload(e) for e in remaining] == ["[DONE]"]

    def test_provider_exception_is_emitted_as_error_event(self):
        client = FakeClient(RuntimeError("provider exploded"))

        payloads = [_payload(e) for e in streaming.stream_chat_completion(
            client, "gpt", [], [], threading.Event()
        )]

        assert payloads[0] == {"type": "error", "message": "provider exploded"}
        assert payloads[1] == "[DONE]"
