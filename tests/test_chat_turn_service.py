"""
Tests for the pure helper functions in chat_turn_service.py.

run_persistent_chat_turn() requires a live OpenAI stream and is covered
by the streaming integration tests. Everything tested here is a pure function
or a thin stateful helper that does not touch the network.

Functions under test (chat_turn_service):
  _parse_stream_payload   — typed dict event passthrough
  _safe_tool_args         — silent JSON parser for tool arguments
  _tool_call_message      — OpenAI tool-call message constructor
  TurnRecorder            — throttled persistence helper
  _bare_tool_name         — server-namespace stripper

Functions under test (title_service — stateless, independently importable):
  _messages_to_text       — title-generation input formatter
  _extract_title          — 3-path title extractor (tool_calls / XML)

Note: title_service functions have their own dedicated test module
(test_title_service.py).  The tests here exercise them via the title_service
module directly, matching their new home after the split.
"""
from __future__ import annotations

import json
import threading
import time
from unittest.mock import MagicMock, patch, call

import pytest

import chat_turn_service as svc
import title_service


# ---------------------------------------------------------------------------
# _parse_stream_payload
# ---------------------------------------------------------------------------

class TestParseStreamPayload:
    """Streaming internals are dict-based; SSE encoding happens only in routes.py."""

    def test_dict_event_is_returned(self):
        payload = {"type": "text", "content": "hi"}
        assert svc._parse_stream_payload(payload) is payload

    def test_done_dict_is_returned(self):
        payload = {"type": "done"}
        assert svc._parse_stream_payload(payload) is payload

    def test_sse_string_is_ignored(self):
        assert svc._parse_stream_payload('data: {"type": "text", "content": "hi"}') is None

    def test_non_dict_is_ignored(self):
        assert svc._parse_stream_payload(None) is None
        assert svc._parse_stream_payload(123) is None


# ---------------------------------------------------------------------------
# _messages_to_text
# ---------------------------------------------------------------------------

class TestMessagesToText:
    """
    Input to the title-generation model. Must include only user/assistant turns,
    handle list-format content (vision messages), and strip formatting noise.

    _messages_to_text now lives in title_service; tests use that module directly.
    """

    def test_simple_user_and_assistant_messages(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = title_service._messages_to_text(messages)
        assert "user: Hello" in result
        assert "assistant: Hi there" in result

    def test_system_messages_excluded(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Question"},
        ]
        result = title_service._messages_to_text(messages)
        assert "system" not in result
        assert "Question" in result

    def test_tool_messages_excluded(self):
        messages = [
            {"role": "user", "content": "Run it"},
            {"role": "tool", "content": "result output"},
        ]
        result = title_service._messages_to_text(messages)
        assert "result output" not in result

    def test_list_content_blocks_joined(self):
        """Vision messages have content as a list of typed blocks."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this"},
                    {"type": "image_url", "image_url": {"url": "data:..."}},
                ],
            }
        ]
        result = title_service._messages_to_text(messages)
        assert "Describe this" in result

    def test_double_newlines_collapsed(self):
        messages = [{"role": "user", "content": "Line one\n\nLine two"}]
        result = title_service._messages_to_text(messages)
        assert "\n\n" not in result

    def test_empty_messages_returns_empty_string(self):
        assert title_service._messages_to_text([]) == ""

    def test_only_four_messages_consumed(self):
        """Only the first 4 messages are passed by the caller — function must not crash on fewer."""
        messages = [{"role": "user", "content": f"msg{i}"} for i in range(2)]
        result = title_service._messages_to_text(messages)
        assert "msg0" in result


# ---------------------------------------------------------------------------
# _extract_title
# ---------------------------------------------------------------------------

class TestExtractTitle:
    """
    Three distinct code paths exist because different model families return
    the set_title tool call in different formats.

    _extract_title now lives in title_service; tests use that module directly.
    """

    def _tool_call_message(self, title: str) -> MagicMock:
        tc = MagicMock()
        tc.function.arguments = json.dumps({"title": title})
        msg = MagicMock()
        msg.tool_calls = [tc]
        msg.reasoning_content = None
        return msg

    def _reasoning_message(self, reasoning: str) -> MagicMock:
        msg = MagicMock()
        msg.tool_calls = None
        msg.reasoning_content = reasoning
        return msg

    def test_standard_tool_call_path(self):
        msg = self._tool_call_message("Docker Volume Permissions")
        assert title_service._extract_title(msg) == "Docker Volume Permissions"

    def test_reasoning_xml_tool_call_path(self):
        """Some reasoning models embed the call in <tool_call> XML in reasoning_content."""
        reasoning = '<tool_call>{"name": "set_title", "arguments": {"title": "JWT Token Bug"}}</tool_call>'
        msg = self._reasoning_message(reasoning)
        assert title_service._extract_title(msg) == "JWT Token Bug"

    def test_reasoning_parameter_xml_path(self):
        """Alternate XML format used by some models."""
        reasoning = "<parameter=title>Fibonacci in Python</parameter>"
        msg = self._reasoning_message(reasoning)
        assert title_service._extract_title(msg) == "Fibonacci in Python"

    def test_no_tool_call_and_no_xml_raises(self):
        msg = MagicMock()
        msg.tool_calls = None
        msg.reasoning_content = "I was just thinking..."
        with pytest.raises(ValueError, match="tool call"):
            title_service._extract_title(msg)


# ---------------------------------------------------------------------------
# _safe_tool_args
# ---------------------------------------------------------------------------

class TestSafeToolArgs:
    """
    Tool argument JSON comes from the model and can be malformed. Errors must
    be swallowed and return an empty dict so the tool-call loop doesn't crash.
    """

    def test_valid_json_returns_dict(self):
        assert svc._safe_tool_args('{"cmd": "ls", "path": "/"}') == {"cmd": "ls", "path": "/"}

    def test_empty_string_returns_empty_dict(self):
        assert svc._safe_tool_args("") == {}

    def test_invalid_json_returns_empty_dict(self):
        assert svc._safe_tool_args("{bad json") == {}

    def test_none_like_empty_returns_empty_dict(self):
        assert svc._safe_tool_args("{}") == {}

    def test_nested_object_preserved(self):
        args = '{"options": {"flag": true, "count": 3}}'
        assert svc._safe_tool_args(args) == {"options": {"flag": True, "count": 3}}


# ---------------------------------------------------------------------------
# _tool_call_message
# ---------------------------------------------------------------------------

class TestToolCallMessage:
    """
    Constructs the assistant message that gets appended to api_messages for
    the next model turn. The OpenAI API is strict about this format.
    """

    def _make_call(self, call_id: str, name: str, args: str = "{}") -> dict:
        return {"id": call_id, "function": {"name": name, "arguments": args}}

    def test_role_is_assistant(self):
        msg = svc._tool_call_message([self._make_call("c1", "bash")], None)
        assert msg["role"] == "assistant"

    def test_tool_calls_list_present(self):
        msg = svc._tool_call_message([self._make_call("c1", "bash")], None)
        assert len(msg["tool_calls"]) == 1

    def test_each_call_has_openai_shape(self):
        msg = svc._tool_call_message([self._make_call("c1", "read_file", '{"path":"/f"}')], None)
        tc = msg["tool_calls"][0]
        assert tc["id"] == "c1"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "read_file"
        assert tc["function"]["arguments"] == '{"path":"/f"}'

    def test_multiple_calls_all_included(self):
        calls = [self._make_call("c1", "bash"), self._make_call("c2", "write_file")]
        msg = svc._tool_call_message(calls, None)
        assert len(msg["tool_calls"]) == 2
        names = {tc["function"]["name"] for tc in msg["tool_calls"]}
        assert names == {"bash", "write_file"}

    def test_content_set_when_provided(self):
        msg = svc._tool_call_message([self._make_call("c1", "bash")], "partial text")
        assert msg["content"] == "partial text"

    def test_content_none_when_not_provided(self):
        msg = svc._tool_call_message([self._make_call("c1", "bash")], None)
        assert msg["content"] is None


# ---------------------------------------------------------------------------
# TurnRecorder
# ---------------------------------------------------------------------------

class TestTurnRecorder:
    """
    TurnRecorder throttles disk writes during streaming to avoid hammering the
    filesystem on every token. The key contracts are:
      - force=True always writes regardless of throttle window
      - Within the throttle window and below the size delta, writes are skipped
      - finalize() always writes with no active stream_id
    """

    @pytest.fixture(autouse=True)
    def _isolate_store(self, tmp_lumen):
        pass

    def _make_recorder(self, conv_id: str) -> svc.TurnRecorder:
        import store
        store.create("stub")  # ensure conv exists on disk
        return svc.TurnRecorder(conv_id="stub", title="T", messages=[], stream_id="s1")

    def test_force_true_always_saves(self, tmp_lumen):
        recorder = self._make_recorder("stub")
        with patch("chat_turn_service._save_turn") as mock_save:
            recorder.save([], force=True)
            recorder.save([], force=True)
        assert mock_save.call_count == 2

    def test_rapid_small_saves_throttled(self, tmp_lumen):
        """Calls within the 0.75s window with no size growth must be skipped."""
        recorder = self._make_recorder("stub")
        with patch("chat_turn_service._save_turn") as mock_save:
            recorder.save([], force=True)  # first call seeds the timer
            recorder.save([], reasoning="a", text="b")  # within window, small delta
            recorder.save([], reasoning="a", text="b")  # still within window
        # Only the forced first call should have persisted
        assert mock_save.call_count == 1

    def test_large_size_delta_bypasses_throttle(self, tmp_lumen):
        """A text burst > 512 chars must not be dropped even within the window."""
        recorder = self._make_recorder("stub")
        big_text = "x" * 600
        with patch("chat_turn_service._save_turn") as mock_save:
            recorder.save([], force=True)
            recorder.save([], text=big_text)
        assert mock_save.call_count == 2

    def test_finalize_calls_save_turn_without_stream_id(self, tmp_lumen):
        recorder = self._make_recorder("stub")
        with patch("chat_turn_service._save_turn") as mock_save:
            recorder.finalize([])
        args, kwargs = mock_save.call_args
        # _save_turn(conv_id, title, messages, display_log) — no stream_id kwarg
        assert "stream_id" not in kwargs or kwargs.get("stream_id") == ""

    def test_update_title_changes_saved_title(self, tmp_lumen):
        recorder = self._make_recorder("stub")
        recorder.update_title("New Title")
        with patch("chat_turn_service._save_turn") as mock_save:
            recorder.save([], force=True)
        _, title_arg, *_ = mock_save.call_args.args
        assert title_arg == "New Title"


# ---------------------------------------------------------------------------
# _bare_tool_name
# ---------------------------------------------------------------------------

class TestBareToolName:
    """
    Tool names are namespaced on the frontend as ``{server}_{tool}`` before
    being sent to the model.  _bare_tool_name must reverse that namespace so
    the backend can dispatch to the real tool name on the MCP server.

    The tricky case is a server whose own name contains underscores (e.g.
    ``my_search``): the namespaced form ``my_search_web_search`` must yield
    ``web_search``, not ``search_web_search`` (the old split-on-first-underscore
    bug).
    """

    def test_original_name_in_meta_takes_priority(self):
        """originalName is the canonical path — always wins over any heuristic."""
        meta = {"originalName": "web_search", "server": "search"}
        assert svc._bare_tool_name("search_web_search", meta) == "web_search"

    def test_server_with_underscores_stripped_exactly(self):
        """
        Regression: server name ``my_search`` must strip exactly 10 chars
        (``my_search_``) so ``my_search_web_search`` → ``web_search``, not
        ``search_web_search`` as the old split("_", 1) heuristic produced.
        """
        meta = {"server": "my_search"}
        assert svc._bare_tool_name("my_search_web_search", meta) == "web_search"

    def test_plain_server_name_no_underscores(self):
        """Standard single-word server name still works via the server-prefix path."""
        meta = {"server": "filesystem"}
        assert svc._bare_tool_name("filesystem_read_file", meta) == "read_file"

    def test_no_meta_falls_back_to_split_heuristic(self):
        """When there is no meta at all the old heuristic is still the fallback."""
        assert svc._bare_tool_name("server_tool") == "tool"

    def test_no_meta_no_underscore_returns_name_unchanged(self):
        assert svc._bare_tool_name("tool") == "tool"

    def test_empty_meta_falls_back_to_split_heuristic(self):
        assert svc._bare_tool_name("server_tool", {}) == "tool"

    def test_original_name_preferred_over_server_key(self):
        """Even when both originalName and server are present, originalName wins."""
        meta = {"originalName": "correct_name", "server": "my_server"}
        assert svc._bare_tool_name("my_server_correct_name", meta) == "correct_name"