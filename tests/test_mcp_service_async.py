"""Async-path tests for mcp_service.py."""
from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace

import mcp_service


class FakeStdioContext:
    def __init__(self, params, *, fail_enter: bool = False):
        self.params = params
        self.fail_enter = fail_enter

    async def __aenter__(self):
        if self.fail_enter:
            raise RuntimeError("stdio failed")
        return "reader", "writer"

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeClientSession:
    listed_tools = []
    call_result = None
    initialized = 0
    called_with = None
    fail_initialize = False

    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def initialize(self):
        FakeClientSession.initialized += 1
        if FakeClientSession.fail_initialize:
            raise RuntimeError("init failed")

    async def list_tools(self):
        return SimpleNamespace(tools=FakeClientSession.listed_tools)

    async def call_tool(self, tool_name, arguments):
        FakeClientSession.called_with = (tool_name, arguments)
        return FakeClientSession.call_result


def install_fake_mcp(monkeypatch, *, fail_stdio: bool = False):
    """Install tiny fake mcp modules so tests do not need a real MCP server."""
    FakeClientSession.listed_tools = []
    FakeClientSession.call_result = SimpleNamespace(content=[])
    FakeClientSession.initialized = 0
    FakeClientSession.called_with = None
    FakeClientSession.fail_initialize = False

    mcp_mod = types.ModuleType("mcp")

    class FakeStdioServerParameters:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            for key, value in kwargs.items():
                setattr(self, key, value)

    mcp_mod.StdioServerParameters = FakeStdioServerParameters
    mcp_mod.ClientSession = FakeClientSession

    client_mod = types.ModuleType("mcp.client")
    stdio_mod = types.ModuleType("mcp.client.stdio")

    def stdio_client(params):
        return FakeStdioContext(params, fail_enter=fail_stdio)

    stdio_mod.stdio_client = stdio_client

    monkeypatch.setitem(sys.modules, "mcp", mcp_mod)
    monkeypatch.setitem(sys.modules, "mcp.client", client_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", stdio_mod)
    return FakeStdioServerParameters


class TestBuildServerParams:
    def test_builds_stdio_params_and_applies_workspace_options(self, monkeypatch):
        ParamClass = install_fake_mcp(monkeypatch)
        calls = []

        def fake_apply(params, env, *, server_name, server_config, conv_id):
            calls.append((params.copy(), env.copy(), server_name, server_config, conv_id))
            params["command"] = "docker"
            params["args"] = ["exec", "container", *params["args"]]
            env["INJECTED"] = "yes"
            params["env"] = env

        monkeypatch.setenv("HOST_VALUE", "host")
        monkeypatch.setattr(mcp_service, "apply_workspace_process_options", fake_apply)

        result = mcp_service._build_server_params(
            "bash",
            {"command": "node", "args": ["server.js"], "env": {"SERVER_VALUE": "srv"}},
            conv_id="conv-1",
        )

        assert isinstance(result, ParamClass)
        assert result.command == "docker"
        assert result.args == ["exec", "container", "server.js"]
        assert result.env["HOST_VALUE"] == "host"
        assert result.env["SERVER_VALUE"] == "srv"
        assert result.env["INJECTED"] == "yes"
        assert calls[0][2:] == ("bash", {"command": "node", "args": ["server.js"], "env": {"SERVER_VALUE": "srv"}}, "conv-1")


class TestFetchTools:
    def test_fetch_tools_returns_openai_style_tool_metadata(self, monkeypatch):
        install_fake_mcp(monkeypatch)
        monkeypatch.setattr(mcp_service, "apply_workspace_process_options", lambda *a, **k: None)
        FakeClientSession.listed_tools = [
            SimpleNamespace(name="run", description="Run a command", inputSchema={"type": "object"}),
            SimpleNamespace(name="empty_desc", description=None, inputSchema={"type": "object", "properties": {}}),
        ]

        tools = asyncio.run(mcp_service.fetch_tools(
            "bash",
            {"command": "node", "args": ["server.js"]},
            conv_id="conv-1",
        ))

        assert tools == [
            {
                "server": "bash",
                "name": "run",
                "description": "Run a command",
                "inputSchema": {"type": "object"},
            },
            {
                "server": "bash",
                "name": "empty_desc",
                "description": "",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]
        assert FakeClientSession.initialized == 1

    def test_fetch_tools_returns_empty_list_on_mcp_failure(self, monkeypatch):
        install_fake_mcp(monkeypatch, fail_stdio=True)
        monkeypatch.setattr(mcp_service, "apply_workspace_process_options", lambda *a, **k: None)

        tools = asyncio.run(mcp_service.fetch_tools("bad", {"command": "node"}, conv_id="conv-1"))

        assert tools == []


class TestInvokeTool:
    def test_invoke_tool_returns_joined_text_content(self, monkeypatch):
        install_fake_mcp(monkeypatch)
        monkeypatch.setattr(mcp_service, "apply_workspace_process_options", lambda *a, **k: None)
        FakeClientSession.call_result = SimpleNamespace(content=[
            SimpleNamespace(text="first"),
            {"kind": "non_text"},
            SimpleNamespace(text="third"),
        ])

        result = asyncio.run(mcp_service.invoke_tool(
            "fs",
            {"command": "node", "args": ["server.js"]},
            "read_file",
            {"path": "/workspace/a.txt"},
            conv_id="conv-1",
        ))

        assert result == "first\n{'kind': 'non_text'}\nthird"
        assert FakeClientSession.called_with == ("read_file", {"path": "/workspace/a.txt"})

    def test_invoke_tool_returns_error_string_on_failure(self, monkeypatch):
        install_fake_mcp(monkeypatch)
        monkeypatch.setattr(mcp_service, "apply_workspace_process_options", lambda *a, **k: None)
        FakeClientSession.fail_initialize = True

        result = asyncio.run(mcp_service.invoke_tool(
            "fs",
            {"command": "node"},
            "read_file",
            {},
            conv_id="conv-1",
        ))

        assert result == "Error calling tool 'read_file': init failed"


class TestRunAsync:
    def test_run_async_uses_asyncio_run_when_no_loop_is_running(self):
        async def work():
            return "ok"

        assert mcp_service.run_async(work()) == "ok"

    def test_run_async_works_from_inside_existing_event_loop(self):
        async def outer():
            async def work():
                return "thread-ok"

            return mcp_service.run_async(work())

        assert asyncio.run(outer()) == "thread-ok"
