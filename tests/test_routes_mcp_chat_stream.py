"""Route tests for MCP endpoints and chat stream replay/start behavior."""
from __future__ import annotations

import json

import pytest

from mcp_adapters import ContainerConversationRequired


def _json(resp) -> dict | list:
    return json.loads(resp.data)


class ImmediateThread:
    """Thread test double that runs target synchronously when start() is called."""

    def __init__(self, target, args=(), daemon=None, **kwargs):
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self):
        self.target(*self.args)


class TestMcpToolsRoute:
    def test_lists_tools_from_all_configured_servers(self, client, monkeypatch):
        import routes

        monkeypatch.setattr(routes.mcp_service, "load_config", lambda: {
            "mcpServers": {
                "bash": {"command": "node"},
                "fs": {"command": "node"},
            }
        })
        monkeypatch.setattr(routes.mcp_service, "run_async", lambda value: value)
        monkeypatch.setattr(routes.mcp_service, "fetch_tools", lambda name, cfg, conv_id="": [
            {"name": f"{name}_tool", "server": name, "conv_id": conv_id}
        ])

        resp = client.get("/api/mcp/tools?conv_id=conv-1")

        assert resp.status_code == 200
        assert _json(resp) == [
            {"name": "bash_tool", "server": "bash", "conv_id": "conv-1"},
            {"name": "fs_tool", "server": "fs", "conv_id": "conv-1"},
        ]

    def test_returns_skipped_servers_when_conversation_is_required(self, client, monkeypatch):
        import routes

        monkeypatch.setattr(routes.mcp_service, "load_config", lambda: {
            "mcpServers": {
                "bash": {"command": "node"},
                "exa": {"command": "npx"},
            }
        })

        def fake_fetch(name, cfg, conv_id=""):
            if name == "bash":
                raise ContainerConversationRequired("MCP server 'bash' requires a conversation to be open.")
            return [{"name": "search", "server": name}]

        monkeypatch.setattr(routes.mcp_service, "run_async", lambda value: value)
        monkeypatch.setattr(routes.mcp_service, "fetch_tools", fake_fetch)

        resp = client.get("/api/mcp/tools")

        assert resp.status_code == 200
        assert _json(resp) == {
            "tools": [{"name": "search", "server": "exa"}],
            "skipped": [{
                "server": "bash",
                "reason": "MCP server 'bash' requires a conversation to be open.",
            }],
        }


class TestMcpCallRoute:
    def test_calls_tool_and_returns_result(self, client, monkeypatch):
        import routes

        calls = []
        monkeypatch.setattr(routes.mcp_service, "find_server", lambda name: {"command": "node"})
        monkeypatch.setattr(routes.mcp_service, "invoke_tool", lambda *args, **kwargs: calls.append((args, kwargs)) or "ok")
        monkeypatch.setattr(routes.mcp_service, "run_async", lambda value: value)

        resp = client.post("/api/mcp/call", json={
            "server": "bash",
            "tool": "run_command",
            "arguments": {"cmd": "pwd"},
            "conv_id": "conv-1",
        })

        assert resp.status_code == 200
        assert _json(resp) == {"result": "ok"}
        assert calls == [(('bash', {"command": "node"}, "run_command", {"cmd": "pwd"}), {"conv_id": "conv-1"})]

    def test_unknown_server_returns_404(self, client, monkeypatch):
        import routes

        monkeypatch.setattr(routes.mcp_service, "find_server", lambda name: None)

        resp = client.post("/api/mcp/call", json={"server": "missing"})

        assert resp.status_code == 404
        assert _json(resp) == {"error": "MCP server 'missing' not found"}

    def test_container_conversation_required_returns_400(self, client, monkeypatch):
        import routes

        monkeypatch.setattr(routes.mcp_service, "find_server", lambda name: {"command": "node"})
        monkeypatch.setattr(routes.mcp_service, "invoke_tool", lambda *a, **k: (_ for _ in ()).throw(
            ContainerConversationRequired("conversation required")
        ))

        resp = client.post("/api/mcp/call", json={"server": "bash", "tool": "run"})

        assert resp.status_code == 400
        assert _json(resp) == {"error": "conversation required"}


class TestChatStreamRoute:
    @pytest.fixture(autouse=True)
    def clear_route_stream_state(self):
        import routes
        routes._active_streams.clear()
        routes._cancel_events.clear()
        yield
        routes._active_streams.clear()
        routes._cancel_events.clear()

    def _sse_payloads(self, resp):
        raw = resp.get_data(as_text=True)
        payloads = []
        for block in raw.strip().split("\n\n"):
            data = block.removeprefix("data: ").strip()
            payloads.append(data if data == "[DONE]" else json.loads(data))
        return payloads

    def test_attach_to_missing_stream_returns_404(self, client):
        resp = client.post("/api/chat/stream", json={"stream_id": "missing", "attach": True})

        assert resp.status_code == 404
        assert _json(resp) == {"error": "Stream not found"}

    def test_starts_chat_turn_and_streams_published_events(self, client, monkeypatch):
        import routes

        def fake_turn(body, cancel_event, stream_id, publish):
            publish({"type": "text", "content": f"hello:{body['conv_id']}:{stream_id}"})
            publish({"type": "assistant_done", "messages": [], "displayLog": []})

        monkeypatch.setattr(routes.threading, "Thread", ImmediateThread)
        monkeypatch.setattr(routes.chat_turn_service, "run_persistent_chat_turn", fake_turn)

        resp = client.post("/api/chat/stream", json={"conv_id": "conv-1", "stream_id": "stream-1"})

        assert resp.status_code == 200
        assert self._sse_payloads(resp) == [
            {"type": "text", "content": "hello:conv-1:stream-1"},
            {"type": "assistant_done", "messages": [], "displayLog": []},
            "[DONE]",
        ]
        assert "stream-1" not in routes._active_streams
        assert "stream-1" not in routes._cancel_events

    def test_attach_replays_existing_active_stream_without_starting_new_thread(self, client):
        import routes

        state = routes._stream_state("stream-replay", "conv-1")
        routes._publish_stream_event(state, {"type": "text", "content": "cached"})
        routes._finish_stream_state(state)

        # Put the finished state back to simulate a stream object that still exists
        # long enough for an attach request to replay it.
        routes._active_streams["stream-replay"] = state

        resp = client.post("/api/chat/stream", json={"stream_id": "stream-replay", "attach": True})

        assert resp.status_code == 200
        assert self._sse_payloads(resp) == [
            {"type": "text", "content": "cached"},
            "[DONE]",
        ]

    def test_second_post_with_same_stream_id_does_not_start_another_thread(self, client, monkeypatch):
        import routes

        started = []

        class FailingThread:
            def __init__(self, *args, **kwargs):
                started.append((args, kwargs))

            def start(self):
                raise AssertionError("a started stream should not be started again")

        state = routes._stream_state("stream-existing", "conv-1")
        state["started"] = True
        routes._publish_stream_event(state, {"type": "text", "content": "already running"})
        state["done"] = True
        monkeypatch.setattr(routes.threading, "Thread", FailingThread)

        resp = client.post("/api/chat/stream", json={"conv_id": "conv-1", "stream_id": "stream-existing"})

        assert resp.status_code == 200
        assert self._sse_payloads(resp) == [
            {"type": "text", "content": "already running"},
            "[DONE]",
        ]
        assert started == []

    def test_cancel_active_stream_sets_cancel_event(self, client):
        import routes

        routes._cancel_events["stream-cancel"] = routes.threading.Event()

        resp = client.post("/api/chat/cancel", json={"stream_id": "stream-cancel"})

        assert resp.status_code == 200
        assert _json(resp) == {"ok": True}
        assert routes._cancel_events["stream-cancel"].is_set()

    def test_cancel_missing_stream_returns_404(self, client):
        resp = client.post("/api/chat/cancel", json={"stream_id": "missing"})

        assert resp.status_code == 404
        assert _json(resp) == {"ok": False, "reason": "stream not found"}

    def test_attach_replays_buffered_events_in_order(self, client):
        import routes

        state = routes._stream_state("stream-buffered", "conv-1")
        routes._publish_stream_event(state, {"type": "reasoning", "content": "a"})
        routes._publish_stream_event(state, {"type": "text", "content": "b"})
        routes._finish_stream_state(state)
        routes._active_streams["stream-buffered"] = state

        resp = client.post("/api/chat/stream", json={"stream_id": "stream-buffered", "attach": True})

        assert resp.status_code == 200
        assert self._sse_payloads(resp) == [
            {"type": "reasoning", "content": "a"},
            {"type": "text", "content": "b"},
            "[DONE]",
        ]
