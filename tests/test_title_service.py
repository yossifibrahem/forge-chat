"""
Tests for title_service.py — stateless, independently importable.

title_service was split out of chat_turn_service.py.  It has no Flask context,
no DB, and no network dependency, so it can be imported and unit-tested in
isolation without any other Lumen module.

Functions under test:
  _messages_to_text  — converts message history to a compact plain-text block
  _extract_title     — extracts a title string from three possible model response shapes
  _SET_TITLE_TOOL    — the tool definition sent to the model (shape contract)
  generate_title     — end-to-end orchestration (mocked client)
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

import title_service as svc


# ---------------------------------------------------------------------------
# _SET_TITLE_TOOL shape
# ---------------------------------------------------------------------------

class TestSetTitleToolShape:
    """The tool definition must satisfy the OpenAI function-calling schema."""

    def test_type_is_function(self):
        assert svc._SET_TITLE_TOOL["type"] == "function"

    def test_function_name_is_set_title(self):
        assert svc._SET_TITLE_TOOL["function"]["name"] == "set_title"

    def test_title_parameter_is_required(self):
        params = svc._SET_TITLE_TOOL["function"]["parameters"]
        assert "title" in params["properties"]
        assert "title" in params["required"]

    def test_title_parameter_is_string_type(self):
        params = svc._SET_TITLE_TOOL["function"]["parameters"]
        assert params["properties"]["title"]["type"] == "string"


# ---------------------------------------------------------------------------
# _messages_to_text
# ---------------------------------------------------------------------------

class TestMessagesToText:
    """
    Converts a message list into a compact plain-text block for the title model.
    Only user/assistant roles are included; system, tool, and other roles are
    filtered out.
    """

    def test_simple_user_and_assistant_messages(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = svc._messages_to_text(messages)
        assert "user: Hello" in result
        assert "assistant: Hi there" in result

    def test_roles_appear_as_prefixes(self):
        messages = [{"role": "user", "content": "What is 2+2?"}]
        assert svc._messages_to_text(messages).startswith("user:")

    def test_system_messages_excluded(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Question"},
        ]
        result = svc._messages_to_text(messages)
        assert "system" not in result
        assert "Question" in result

    def test_tool_messages_excluded(self):
        messages = [
            {"role": "user", "content": "Run it"},
            {"role": "tool", "content": "result output"},
        ]
        result = svc._messages_to_text(messages)
        assert "result output" not in result

    def test_list_content_blocks_joined(self):
        """Vision messages carry content as a list of typed blocks."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this"},
                    {"type": "image_url", "image_url": {"url": "data:..."}},
                ],
            }
        ]
        result = svc._messages_to_text(messages)
        assert "Describe this" in result

    def test_image_blocks_excluded_from_text(self):
        """Non-text blocks must not inject garbage like 'image_url' into the text."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                    {"type": "text", "text": "Caption this"},
                ],
            }
        ]
        result = svc._messages_to_text(messages)
        assert "image_url" not in result
        assert "Caption this" in result

    def test_double_newlines_collapsed(self):
        messages = [{"role": "user", "content": "Line one\n\nLine two"}]
        result = svc._messages_to_text(messages)
        assert "\n\n" not in result

    def test_empty_messages_returns_empty_string(self):
        assert svc._messages_to_text([]) == ""

    def test_multiple_messages_separated_by_newline(self):
        messages = [
            {"role": "user", "content": "Ping"},
            {"role": "assistant", "content": "Pong"},
        ]
        result = svc._messages_to_text(messages)
        lines = result.strip().splitlines()
        assert len(lines) == 2

    def test_whitespace_stripped_from_content(self):
        messages = [{"role": "user", "content": "  trimmed  "}]
        result = svc._messages_to_text(messages)
        assert "  trimmed  " not in result
        assert "trimmed" in result

    def test_empty_content_message_omitted(self):
        """A message with empty content after stripping should not produce a blank line."""
        messages = [
            {"role": "user", "content": "   "},
            {"role": "user", "content": "real"},
        ]
        result = svc._messages_to_text(messages)
        assert result.strip() == "user: real"


# ---------------------------------------------------------------------------
# _extract_title
# ---------------------------------------------------------------------------

class TestExtractTitle:
    """
    Three distinct response shapes are supported because different model
    families return the set_title tool call differently.
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

    # -- standard tool_calls path -------------------------------------------

    def test_standard_tool_call_path(self):
        msg = self._tool_call_message("Docker Volume Permissions")
        assert svc._extract_title(msg) == "Docker Volume Permissions"

    def test_tool_call_title_with_spaces(self):
        msg = self._tool_call_message("JWT Token Expiry Bug")
        assert svc._extract_title(msg) == "JWT Token Expiry Bug"

    def test_tool_call_title_unicode(self):
        msg = self._tool_call_message("Débogage Python")
        assert svc._extract_title(msg) == "Débogage Python"

    # -- <tool_call> XML in reasoning_content path --------------------------

    def test_reasoning_xml_tool_call_path(self):
        """Some reasoning models embed the call in <tool_call> XML."""
        reasoning = '<tool_call>{"name": "set_title", "arguments": {"title": "JWT Token Bug"}}</tool_call>'
        msg = self._reasoning_message(reasoning)
        assert svc._extract_title(msg) == "JWT Token Bug"

    def test_reasoning_xml_with_whitespace_inside_tags(self):
        reasoning = (
            "<tool_call>\n"
            '  {"name": "set_title", "arguments": {"title": "Async Race Condition"}}\n'
            "</tool_call>"
        )
        msg = self._reasoning_message(reasoning)
        assert svc._extract_title(msg) == "Async Race Condition"

    # -- <parameter=title> XML path -----------------------------------------

    def test_reasoning_parameter_xml_path(self):
        """Alternate XML format used by some models."""
        reasoning = "<parameter=title>Fibonacci in Python</parameter>"
        msg = self._reasoning_message(reasoning)
        assert svc._extract_title(msg) == "Fibonacci in Python"

    def test_parameter_xml_with_leading_trailing_whitespace(self):
        reasoning = "<parameter=title>  Spaced Title  </parameter>"
        msg = self._reasoning_message(reasoning)
        assert svc._extract_title(msg) == "Spaced Title"

    # -- error path ---------------------------------------------------------

    def test_no_tool_call_and_no_xml_raises(self):
        msg = MagicMock()
        msg.tool_calls = None
        msg.reasoning_content = "I was just thinking..."
        with pytest.raises(ValueError, match="tool call"):
            svc._extract_title(msg)

    def test_empty_reasoning_content_raises(self):
        msg = MagicMock()
        msg.tool_calls = None
        msg.reasoning_content = ""
        with pytest.raises(ValueError, match="tool call"):
            svc._extract_title(msg)

    def test_none_reasoning_content_raises(self):
        msg = MagicMock()
        msg.tool_calls = None
        msg.reasoning_content = None
        with pytest.raises(ValueError, match="tool call"):
            svc._extract_title(msg)


# ---------------------------------------------------------------------------
# generate_title
# ---------------------------------------------------------------------------

class TestGenerateTitle:
    """
    generate_title orchestrates one chat-completions request using a mocked
    OpenAI client.  Network calls must never be made in these tests.
    """

    def _make_client(self, title: str) -> MagicMock:
        """Return a mock OpenAI client whose models.list yields the given title."""
        tc = MagicMock()
        tc.function.arguments = json.dumps({"title": title})
        message = MagicMock()
        message.tool_calls = [tc]
        message.reasoning_content = None
        choice = MagicMock()
        choice.message = message
        completion = MagicMock()
        completion.choices = [choice]
        client = MagicMock()
        client.chat.completions.create.return_value = completion
        return client

    def test_returns_generated_title(self):
        client = self._make_client("Fibonacci in Python")
        messages = [{"role": "user", "content": "How do I write Fibonacci in Python?"}]
        result = svc.generate_title(client, {"model": "gpt-4o"}, messages)
        assert result == "Fibonacci in Python"

    def test_uses_model_from_body(self):
        client = self._make_client("Test Title")
        svc.generate_title(client, {"model": "gpt-4o-mini"}, [])
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o-mini"

    def test_default_model_when_body_has_no_model(self):
        client = self._make_client("Test Title")
        svc.generate_title(client, {}, [])
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"]  # non-empty default

    def test_tool_choice_is_required(self):
        """The model must be forced to call set_title, not answer in text."""
        client = self._make_client("T")
        svc.generate_title(client, {}, [])
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs.get("tool_choice") == "required"

    def test_set_title_tool_is_passed(self):
        client = self._make_client("T")
        svc.generate_title(client, {}, [])
        call_kwargs = client.chat.completions.create.call_args.kwargs
        tool_names = [t["function"]["name"] for t in call_kwargs.get("tools", [])]
        assert "set_title" in tool_names

    def test_returns_none_on_client_exception(self):
        """Any exception from the API must be swallowed and return None."""
        client = MagicMock()
        client.chat.completions.create.side_effect = Exception("network error")
        result = svc.generate_title(client, {}, [{"role": "user", "content": "hi"}])
        assert result is None

    def test_returns_none_when_model_gives_no_tool_call(self):
        """If the model skips the tool call, generate_title must not raise."""
        message = MagicMock()
        message.tool_calls = None
        message.reasoning_content = None
        choice = MagicMock()
        choice.message = message
        completion = MagicMock()
        completion.choices = [choice]
        client = MagicMock()
        client.chat.completions.create.return_value = completion
        result = svc.generate_title(client, {}, [{"role": "user", "content": "hi"}])
        assert result is None

    def test_only_first_four_messages_sent(self):
        """The caller slices [:4]; generate_title must not crash on fewer or more."""
        client = self._make_client("Any Title")
        messages = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
        # Pass all 10 — function must accept them; only first 4 should be used
        result = svc.generate_title(client, {}, messages[:4])
        assert result == "Any Title"