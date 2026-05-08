"""
SSE streaming — event formatting and OpenAI stream consumption.

`stream_chat_completion` is a pure generator; it knows nothing about
Flask.  `make_streaming_response` wraps it into a Flask Response.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Generator

from flask import Response, stream_with_context
from openai import OpenAI


def sse_event(payload: dict) -> str:
    """Encode a dict as a Server-Sent Event data line."""
    return f"data: {json.dumps(payload)}\n\n"


def _merge_tool_call_chunk(store: dict[int, dict], chunk) -> None:
    """Accumulate a streaming tool-call delta into *store* (keyed by chunk index)."""
    idx = chunk.index
    if idx not in store:
        store[idx] = {"id": chunk.id or "", "function": {"name": "", "arguments": ""}}
    if chunk.id:
        store[idx]["id"] = chunk.id
    if chunk.function:
        store[idx]["function"]["name"]      += chunk.function.name      or ""
        store[idx]["function"]["arguments"] += chunk.function.arguments or ""


def stream_chat_completion(
    client: OpenAI,
    model: str,
    messages: list[dict],
    tools: list[dict],
    cancel_event: threading.Event,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    timeout: float | None = None,
) -> Generator[str, None, None]:
    """Yield SSE strings for a streaming OpenAI chat completion.

    The cancel_event is checked before every yielded chunk.  When the
    frontend calls POST /api/chat/cancel the event is set, the loop
    breaks, and the stream is closed before [DONE] is flushed.
    """
    openai_stream = None
    try:
        request_kwargs: dict[str, Any] = {
            "model": model, "messages": messages, "stream": True,
            "temperature": temperature,
        }
        if max_tokens:
            request_kwargs["max_tokens"] = max_tokens
        if timeout:
            request_kwargs["timeout"] = timeout
        if tools:
            request_kwargs["tools"] = tools
            request_kwargs["tool_choice"] = "auto"

        accumulated_tool_calls: dict[int, dict] = {}
        announced_tool_indices: set[int] = set()
        openai_stream = client.chat.completions.create(**request_kwargs)

        for chunk in openai_stream:
            if cancel_event.is_set():
                openai_stream.close()
                break

            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            reasoning = getattr(delta, 'reasoning_content', None)
            if reasoning:
                yield sse_event({"type": "reasoning", "content": reasoning})

            if delta.content:
                yield sse_event({"type": "text", "content": delta.content})

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    _merge_tool_call_chunk(accumulated_tool_calls, tc)
                    idx = tc.index
                    tool_name = accumulated_tool_calls[idx]["function"]["name"]
                    if idx not in announced_tool_indices and tool_name:
                        announced_tool_indices.add(idx)
                        yield sse_event({"type": "tool_start", "name": tool_name})

            if chunk.choices and chunk.choices[0].finish_reason == "tool_calls":
                yield sse_event({"type": "tool_calls", "calls": list(accumulated_tool_calls.values())})

        yield "data: [DONE]\n\n"

    except Exception as exc:
        yield sse_event({"type": "error", "message": str(exc)})
        yield "data: [DONE]\n\n"


def make_streaming_response(generator: Generator) -> Response:
    """Wrap a generator in a Server-Sent Events Flask Response."""
    return Response(
        stream_with_context(generator),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
