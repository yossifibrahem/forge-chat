"""Unit tests for chat_turn_service.py turn orchestration."""
from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import chat_turn_service
import store
import streaming


def _payload(raw: str) -> dict:
    return json.loads(raw.removeprefix("data: ").strip())


class TestSmallHelpers:
    def test_parse_stream_payload_handles_json_done_and_invalid_events(self):
        assert chat_turn_service._parse_stream_payload(streaming.sse_event({"type": "text", "content": "x"})) == {
            "type": "text",
            "content": "x",
        }
        assert chat_turn_service._parse_stream_payload("data: [DONE]\n\n") == {"type": "done"}
        assert chat_turn_service._parse_stream_payload("event: nope") is None
        assert chat_turn_service._parse_stream_payload("data: not-json") is None

    def test_safe_tool_args_returns_empty_dict_for_invalid_json(self):
        assert chat_turn_service._safe_tool_args('{"x": 1}') == {"x": 1}
        assert chat_turn_service._safe_tool_args("not json") == {}

    def test_tool_call_message_keeps_model_facing_shape(self):
        message = chat_turn_service._tool_call_message([
            {"id": "call_1", "function": {"name": "bash", "arguments": '{"cmd":"ls"}'}}
        ], content="I'll run it")

        assert message == {
            "role": "assistant",
            "content": "I'll run it",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "bash", "arguments": '{"cmd":"ls"}'},
            }],
        }

    def test_messages_to_text_uses_user_and_assistant_text_only(self):
        text = chat_turn_service._messages_to_text([
            {"role": "system", "content": "hidden"},
            {"role": "user", "content": [{"type": "text", "text": "hello"}, {"type": "image_url", "image_url": {}}]},
            {"role": "assistant", "content": "hi\n\nthere"},
        ])

        assert text == "user: hello\nassistant: hi there"

    def test_extract_title_from_tool_call_reasoning_json_and_xml(self):
        tool_msg = SimpleNamespace(tool_calls=[SimpleNamespace(function=SimpleNamespace(arguments='{"title":"Docker Tests"}'))])
        assert chat_turn_service._extract_title(tool_msg) == "Docker Tests"

        reasoning_json = SimpleNamespace(
            tool_calls=[],
            reasoning_content='<tool_call>{"arguments":{"title":"MCP Routes"}}</tool_call>',
        )
        assert chat_turn_service._extract_title(reasoning_json) == "MCP Routes"

        reasoning_xml = SimpleNamespace(
            tool_calls=[],
            reasoning_content="<parameter=title>Streaming Fix</parameter>",
        )
        assert chat_turn_service._extract_title(reasoning_xml) == "Streaming Fix"


class TestToolApproval:
    def test_request_tool_approval_blocks_until_resolved_true(self):
        published = []
        cancel = threading.Event()
        result = {}

        thread = threading.Thread(
            target=lambda: result.setdefault("approved", chat_turn_service._request_tool_approval(
                "stream-approval", "call-1", "bash", {"cmd": "ls"}, published.append, cancel
            ))
        )
        thread.start()

        deadline = time.time() + 2
        while not published and time.time() < deadline:
            time.sleep(0.01)
        chat_turn_service.resolve_tool_approval("stream-approval", "call-1", True)
        thread.join(timeout=2)

        assert result["approved"] is True
        assert published == [{
            "type": "tool_approval_required",
            "call_id": "call-1",
            "name": "bash",
            "args": {"cmd": "ls"},
        }]

    def test_request_tool_approval_returns_false_when_cancelled(self):
        cancel = threading.Event()
        result = {}
        thread = threading.Thread(
            target=lambda: result.setdefault("approved", chat_turn_service._request_tool_approval(
                "stream-cancel", "call-2", "bash", {}, lambda payload: None, cancel
            ))
        )
        thread.start()
        cancel.set()
        thread.join(timeout=2)

        assert result["approved"] is False


class TestTurnRecorder:
    def test_save_writes_streaming_partial_and_finalize_clears_active_stream(self):
        conv = store.create("Recorder")
        messages = [{"role": "user", "content": "hello"}]
        recorder = chat_turn_service.TurnRecorder(conv["id"], "Recorder", messages, "stream-1")

        recorder.save([], reasoning="thinking", text="partial", force=True)
        saved = store.load(conv["id"])
        assert saved["streaming"] is True
        assert saved["active_stream_id"] == "stream-1"
        assert saved["displayLog"][-1] == {"type": "message", "role": "assistant", "content": "partial"}

        final_log = [{"type": "message", "role": "assistant", "content": "done"}]
        recorder.finalize(final_log)
        saved = store.load(conv["id"])
        assert saved["streaming"] is False
        assert "active_stream_id" not in saved
        assert saved["displayLog"] == final_log


class TestRunPersistentChatTurn:
    def test_text_only_turn_publishes_text_done_and_persists_messages(self, monkeypatch):
        conv = store.create("Chat")
        events = []
        monkeypatch.setattr(chat_turn_service, "openai_client", lambda body: object())
        monkeypatch.setattr(chat_turn_service.stream_module, "stream_chat_completion", lambda *a, **k: iter([
            streaming.sse_event({"type": "reasoning", "content": "think"}),
            streaming.sse_event({"type": "text", "content": "Hello"}),
            "data: [DONE]\n\n",
        ]))

        chat_turn_service.run_persistent_chat_turn({
            "conv_id": conv["id"],
            "title": "Chat",
            "conversation_messages": [{"role": "user", "content": "Hi"}],
            "display_log": [{"type": "message", "role": "user", "content": "Hi"}],
            "messages": [{"role": "user", "content": "Hi"}],
            "auto_generate_titles": False,
        }, threading.Event(), "stream-text", events.append)

        assert events == [
            {"type": "reasoning", "content": "think"},
            {"type": "text", "content": "Hello"},
            {
                "type": "assistant_done",
                "messages": [
                    {"role": "user", "content": "Hi"},
                    {"role": "assistant", "content": "Hello"},
                ],
                "displayLog": [
                    {"type": "message", "role": "user", "content": "Hi"},
                    {"type": "thinking", "content": "think"},
                    {"type": "message", "role": "assistant", "content": "Hello"},
                ],
            },
        ]
        saved = store.load(conv["id"])
        assert saved["messages"][-1] == {"role": "assistant", "content": "Hello"}
        assert saved["streaming"] is False

    def test_auto_approved_tool_call_runs_tool_then_continues_model_loop(self, monkeypatch):
        conv = store.create("Tool Chat")
        events = []
        streams = iter([
            [
                streaming.sse_event({"type": "tool_calls", "calls": [{
                    "id": "call_1",
                    "function": {"name": "bash", "arguments": '{"cmd":"pwd"}'},
                }]}),
                "data: [DONE]\n\n",
            ],
            [
                streaming.sse_event({"type": "text", "content": "Done"}),
                "data: [DONE]\n\n",
            ],
        ])
        monkeypatch.setattr(chat_turn_service, "openai_client", lambda body: object())
        monkeypatch.setattr(chat_turn_service.stream_module, "stream_chat_completion", lambda *a, **k: iter(next(streams)))
        monkeypatch.setattr(chat_turn_service.mcp_service, "find_server", lambda name: {"command": "node"})
        monkeypatch.setattr(chat_turn_service.mcp_service, "invoke_tool", lambda *a, **k: "TOOL RESULT")
        monkeypatch.setattr(chat_turn_service.mcp_service, "run_async", lambda value: value)

        chat_turn_service.run_persistent_chat_turn({
            "conv_id": conv["id"],
            "title": "Tool Chat",
            "conversation_messages": [{"role": "user", "content": "run pwd"}],
            "display_log": [],
            "messages": [{"role": "user", "content": "run pwd"}],
            "mcp_tool_meta": [{"name": "bash", "server": "shell", "autoApprove": True}],
            "tools": [{"type": "function"}],
            "auto_generate_titles": False,
        }, threading.Event(), "stream-tool", events.append)

        assert {"type": "tool_running", "name": "bash", "args": {"cmd": "pwd"}} in events
        assert {"type": "tool_result", "name": "bash", "args": {"cmd": "pwd"}, "result": "TOOL RESULT"} in events
        assert events[-1]["type"] == "assistant_done"
        saved = store.load(conv["id"])
        roles = [m["role"] for m in saved["messages"]]
        assert roles == ["user", "assistant", "tool", "assistant"]
        assert saved["messages"][-1]["content"] == "Done"

    def test_denied_tool_call_is_recorded_and_published(self, monkeypatch):
        conv = store.create("Denied")
        events = []
        monkeypatch.setattr(chat_turn_service, "openai_client", lambda body: object())
        streams = iter([
            [
                streaming.sse_event({"type": "tool_calls", "calls": [{
                    "id": "call_denied",
                    "function": {"name": "bash", "arguments": "{}"},
                }]}),
                "data: [DONE]\n\n",
            ],
            ["data: [DONE]\n\n"],
        ])
        monkeypatch.setattr(chat_turn_service.stream_module, "stream_chat_completion", lambda *a, **k: iter(next(streams)))
        monkeypatch.setattr(chat_turn_service, "_request_tool_approval", lambda *a, **k: False)

        chat_turn_service.run_persistent_chat_turn({
            "conv_id": conv["id"],
            "title": "Denied",
            "conversation_messages": [{"role": "user", "content": "run"}],
            "display_log": [],
            "messages": [{"role": "user", "content": "run"}],
            "mcp_tool_meta": [{"name": "bash", "server": "shell", "autoApprove": False}],
            "tools": [{"type": "function"}],
            "auto_generate_titles": False,
        }, threading.Event(), "stream-denied", events.append)

        assert {
            "type": "tool_result",
            "name": "bash",
            "args": {},
            "result": "Tool call denied by user.",
            "denied": True,
        } in events
        assert events[-1]["type"] == "assistant_done"
        saved = store.load(conv["id"])
        assert saved["messages"][-1] == {
            "role": "tool",
            "tool_call_id": "call_denied",
            "content": "Tool call denied by user.",
        }

    def test_cancelled_stream_preserves_partial_answer_without_assistant_done(self, monkeypatch):
        conv = store.create("Cancel")
        events = []
        cancel = threading.Event()

        def fake_stream(*args, **kwargs):
            yield streaming.sse_event({"type": "text", "content": "partial"})
            cancel.set()
            yield "data: [DONE]\n\n"

        monkeypatch.setattr(chat_turn_service, "openai_client", lambda body: object())
        monkeypatch.setattr(chat_turn_service.stream_module, "stream_chat_completion", fake_stream)

        chat_turn_service.run_persistent_chat_turn({
            "conv_id": conv["id"],
            "title": "Cancel",
            "conversation_messages": [{"role": "user", "content": "Hi"}],
            "display_log": [],
            "messages": [{"role": "user", "content": "Hi"}],
            "auto_generate_titles": False,
        }, cancel, "stream-cancel", events.append)

        assert events == [{"type": "text", "content": "partial"}]
        assert store.load(conv["id"])["messages"][-1] == {"role": "assistant", "content": "partial"}

    def test_first_user_message_generates_and_persists_title(self, monkeypatch):
        conv = store.create("Untitled")
        events = []
        monkeypatch.setattr(chat_turn_service, "openai_client", lambda body: object())
        monkeypatch.setattr(chat_turn_service.stream_module, "stream_chat_completion", lambda *a, **k: iter([
            streaming.sse_event({"type": "text", "content": "Sure, here is the answer."}),
            "data: [DONE]\n\n",
        ]))
        monkeypatch.setattr(chat_turn_service, "_generate_title", lambda body, messages: "Docker Startup Tests")

        chat_turn_service.run_persistent_chat_turn({
            "conv_id": conv["id"],
            "title": "Untitled",
            "conversation_messages": [{"role": "user", "content": "How do I test Docker startup?"}],
            "display_log": [],
            "messages": [{"role": "user", "content": "How do I test Docker startup?"}],
        }, threading.Event(), "stream-title", events.append)

        assert events[-1] == {"type": "title", "title": "Docker Startup Tests"}
        saved = store.load(conv["id"])
        assert saved["title"] == "Docker Startup Tests"
        assert saved["streaming"] is False

    def test_title_generation_is_skipped_when_disabled(self, monkeypatch):
        conv = store.create("Keep Title")
        events = []
        title_calls = []
        monkeypatch.setattr(chat_turn_service, "openai_client", lambda body: object())
        monkeypatch.setattr(chat_turn_service.stream_module, "stream_chat_completion", lambda *a, **k: iter([
            streaming.sse_event({"type": "text", "content": "Answer"}),
            "data: [DONE]\n\n",
        ]))
        monkeypatch.setattr(chat_turn_service, "_generate_title", lambda *a, **k: title_calls.append(True) or "Should Not Happen")

        chat_turn_service.run_persistent_chat_turn({
            "conv_id": conv["id"],
            "title": "Keep Title",
            "conversation_messages": [{"role": "user", "content": "Hi"}],
            "display_log": [],
            "messages": [{"role": "user", "content": "Hi"}],
            "auto_generate_titles": False,
        }, threading.Event(), "stream-no-title", events.append)

        assert title_calls == []
        assert not any(event.get("type") == "title" for event in events)
        assert store.load(conv["id"])["title"] == "Keep Title"

    def test_title_generation_is_skipped_after_first_user_message(self, monkeypatch):
        conv = store.create("Existing Topic")
        events = []
        title_calls = []
        monkeypatch.setattr(chat_turn_service, "openai_client", lambda body: object())
        monkeypatch.setattr(chat_turn_service.stream_module, "stream_chat_completion", lambda *a, **k: iter([
            streaming.sse_event({"type": "text", "content": "Follow-up answer"}),
            "data: [DONE]\n\n",
        ]))
        monkeypatch.setattr(chat_turn_service, "_generate_title", lambda *a, **k: title_calls.append(True) or "Should Not Happen")

        chat_turn_service.run_persistent_chat_turn({
            "conv_id": conv["id"],
            "title": "Existing Topic",
            "conversation_messages": [
                {"role": "user", "content": "First"},
                {"role": "assistant", "content": "First answer"},
                {"role": "user", "content": "Follow up"},
            ],
            "display_log": [],
            "messages": [{"role": "user", "content": "Follow up"}],
        }, threading.Event(), "stream-followup-title", events.append)

        assert title_calls == []
        assert not any(event.get("type") == "title" for event in events)
        assert store.load(conv["id"])["title"] == "Existing Topic"

    def test_title_generation_failure_does_not_break_completed_answer(self, monkeypatch):
        conv = store.create("Still Works")
        events = []
        monkeypatch.setattr(chat_turn_service, "openai_client", lambda body: object())
        monkeypatch.setattr(chat_turn_service.stream_module, "stream_chat_completion", lambda *a, **k: iter([
            streaming.sse_event({"type": "text", "content": "Completed"}),
            "data: [DONE]\n\n",
        ]))
        monkeypatch.setattr(chat_turn_service, "_generate_title", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("title API failed")))

        chat_turn_service.run_persistent_chat_turn({
            "conv_id": conv["id"],
            "title": "Still Works",
            "conversation_messages": [{"role": "user", "content": "Hi"}],
            "display_log": [],
            "messages": [{"role": "user", "content": "Hi"}],
        }, threading.Event(), "stream-title-fail", events.append)

        assert {"type": "assistant_done", "messages": [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Completed"},
        ], "displayLog": [{"type": "message", "role": "assistant", "content": "Completed"}]} in events
        assert events[-1] == {"type": "error", "message": "title API failed"}
        saved = store.load(conv["id"])
        assert saved["title"] == "Still Works"
        assert saved["messages"][-1] == {"role": "assistant", "content": "Completed"}
