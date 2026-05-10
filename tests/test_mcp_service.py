"""
Tests for mcp_service.py — config persistence (load, save, find_server).

MCP_CONFIG_FILE is redirected to a temp file for every test via the
`isolated_mcp_config` fixture so no mcp.json in the project root is
ever touched.

async tool fetching and invocation (fetch_tools / invoke_tool) require a
running MCP stdio server and are out of scope here. They are covered by the
manual verification checklist in agent.md.
"""
from __future__ import annotations

import asyncio
import json
import pytest
from pathlib import Path

import mcp_service


# ---------------------------------------------------------------------------
# Fixture: isolate MCP_CONFIG_FILE
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_mcp_config(tmp_path, monkeypatch):
    """Point MCP_CONFIG_FILE at a writable temp path for every test."""
    config_path = tmp_path / "mcp.json"
    monkeypatch.setattr("mcp_service.MCP_CONFIG_FILE", config_path)
    monkeypatch.setattr("mcp_service._config_cache", None)
    monkeypatch.setattr("mcp_service._config_cache_at", 0.0)
    monkeypatch.setattr("mcp_service._config_cache_path", None)
    return config_path


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------

class TestLoadConfig:

    def test_returns_empty_servers_when_file_absent(self):
        result = mcp_service.load_config()
        assert result == {"mcpServers": {}}

    def test_returns_config_dict_when_file_exists(self, isolated_mcp_config):
        config = {"mcpServers": {"fs": {"command": "npx", "args": ["-y", "@fs"]}}}
        isolated_mcp_config.write_text(json.dumps(config))
        assert mcp_service.load_config() == config

    def test_returns_empty_on_corrupt_json(self, isolated_mcp_config):
        isolated_mcp_config.write_text("not valid json {{{")
        assert mcp_service.load_config() == {"mcpServers": {}}

    def test_returns_empty_when_file_is_a_list(self, isolated_mcp_config):
        isolated_mcp_config.write_text(json.dumps(["not", "a", "dict"]))
        assert mcp_service.load_config() == {"mcpServers": {}}

    def test_returns_empty_when_mcp_servers_is_list(self, isolated_mcp_config):
        isolated_mcp_config.write_text(json.dumps({"mcpServers": ["bad"]}))
        assert mcp_service.load_config() == {"mcpServers": {}}

    def test_returns_empty_when_file_is_empty(self, isolated_mcp_config):
        isolated_mcp_config.write_text("")
        assert mcp_service.load_config() == {"mcpServers": {}}

    def test_preserves_extra_top_level_keys(self, isolated_mcp_config):
        config = {"mcpServers": {}, "globalEnv": {"FOO": "bar"}}
        isolated_mcp_config.write_text(json.dumps(config))
        result = mcp_service.load_config()
        assert result.get("globalEnv") == {"FOO": "bar"}


# ---------------------------------------------------------------------------
# save_config
# ---------------------------------------------------------------------------

class TestSaveConfig:

    def test_saves_valid_config(self, isolated_mcp_config):
        config = {"mcpServers": {"srv": {"command": "node", "args": []}}}
        mcp_service.save_config(config)
        assert isolated_mcp_config.exists()
        assert json.loads(isolated_mcp_config.read_text()) == config

    def test_adds_default_mcp_servers_key_if_absent(self, isolated_mcp_config):
        mcp_service.save_config({})
        saved = json.loads(isolated_mcp_config.read_text())
        assert "mcpServers" in saved

    def test_raises_value_error_for_non_dict(self):
        with pytest.raises(ValueError, match="JSON object"):
            mcp_service.save_config(["not", "a", "dict"])

    def test_raises_value_error_when_mcp_servers_not_dict(self):
        with pytest.raises(ValueError, match="mcpServers"):
            mcp_service.save_config({"mcpServers": "wrong-type"})

    def test_raises_value_error_when_mcp_servers_is_list(self):
        with pytest.raises(ValueError, match="mcpServers"):
            mcp_service.save_config({"mcpServers": [1, 2, 3]})

    def test_write_is_atomic_no_tmp_files_left(self, isolated_mcp_config):
        mcp_service.save_config({"mcpServers": {}})
        residual = list(isolated_mcp_config.parent.glob("*.tmp-*"))
        assert residual == []

    def test_save_then_load_roundtrip(self, isolated_mcp_config):
        config = {"mcpServers": {"bash": {"command": "bash", "args": ["-c"]}}}
        mcp_service.save_config(config)
        assert mcp_service.load_config() == config

    def test_overwrites_existing_file(self, isolated_mcp_config):
        mcp_service.save_config({"mcpServers": {"old": {}}})
        mcp_service.save_config({"mcpServers": {"new": {}}})
        saved = json.loads(isolated_mcp_config.read_text())
        assert "new" in saved["mcpServers"]
        assert "old" not in saved["mcpServers"]


# ---------------------------------------------------------------------------
# find_server
# ---------------------------------------------------------------------------

class TestFindServer:

    def test_finds_existing_server(self, isolated_mcp_config):
        config = {"mcpServers": {
            "bash": {"command": "bash", "args": ["-c"]},
            "fs":   {"command": "npx",  "args": ["-y", "@fs"]},
        }}
        isolated_mcp_config.write_text(json.dumps(config))
        result = mcp_service.find_server("bash")
        assert result == {"command": "bash", "args": ["-c"]}

    def test_returns_none_for_missing_server(self, isolated_mcp_config):
        isolated_mcp_config.write_text(json.dumps({"mcpServers": {}}))
        assert mcp_service.find_server("nonexistent") is None

    def test_returns_none_when_config_file_absent(self):
        assert mcp_service.find_server("anything") is None

    def test_returns_full_server_config(self, isolated_mcp_config):
        server_cfg = {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"],
            "env": {"SOME_VAR": "some_val"},
        }
        isolated_mcp_config.write_text(json.dumps({"mcpServers": {"fs": server_cfg}}))
        result = mcp_service.find_server("fs")
        assert result == server_cfg


# ---------------------------------------------------------------------------
# run_async (sync bridge)
# ---------------------------------------------------------------------------

class TestRunAsync:

    def test_runs_simple_coroutine(self):
        import asyncio

        async def _coro():
            return 42

        assert mcp_service.run_async(_coro()) == 42

    def test_coroutine_exception_propagates(self):
        import asyncio

        async def _failing():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            mcp_service.run_async(_failing())


# ---------------------------------------------------------------------------
# config cache
# ---------------------------------------------------------------------------

class TestConfigCache:

    def test_load_config_uses_short_lived_cache(self, isolated_mcp_config, monkeypatch):
        first = {"mcpServers": {"one": {"command": "a"}}}
        second = {"mcpServers": {"two": {"command": "b"}}}
        isolated_mcp_config.write_text(json.dumps(first))
        monkeypatch.setattr("mcp_service._CONFIG_TTL_SECONDS", 60)

        assert mcp_service.load_config() == first
        isolated_mcp_config.write_text(json.dumps(second))
        assert mcp_service.load_config() == first
        assert mcp_service.load_config(refresh=True) == second


# ---------------------------------------------------------------------------
# McpSessionPool
# ---------------------------------------------------------------------------

class TestMcpSessionPool:

    def _install_fake_mcp(self, monkeypatch):
        import sys
        import types
        from types import SimpleNamespace

        created_stdio = []
        created_sessions = []

        class FakeStdioContext:
            def __init__(self, params):
                self.params = params
                self.entered = 0
                self.exited = 0
                created_stdio.append(self)

            async def __aenter__(self):
                self.entered += 1
                self.enter_task = asyncio.current_task()
                return "reader", "writer"

            async def __aexit__(self, exc_type, exc, tb):
                assert asyncio.current_task() is self.enter_task
                self.exited += 1

        class FakeClientSession:
            def __init__(self, reader, writer):
                self.reader = reader
                self.writer = writer
                self.entered = 0
                self.exited = 0
                self.initialized = 0
                self.calls = []
                created_sessions.append(self)

            async def __aenter__(self):
                self.entered += 1
                self.enter_task = asyncio.current_task()
                return self

            async def __aexit__(self, exc_type, exc, tb):
                assert asyncio.current_task() is self.enter_task
                self.exited += 1

            async def initialize(self):
                self.initialized += 1

            async def call_tool(self, tool_name, arguments):
                self.calls.append((tool_name, arguments))
                return SimpleNamespace(content=[SimpleNamespace(text=f"{tool_name}:{arguments.get('n')}")])

        def fake_stdio_client(params):
            return FakeStdioContext(params)

        mcp_module = types.ModuleType("mcp")
        mcp_module.ClientSession = FakeClientSession
        mcp_module.StdioServerParameters = lambda **kwargs: kwargs
        mcp_client_module = types.ModuleType("mcp.client")
        mcp_stdio_module = types.ModuleType("mcp.client.stdio")
        mcp_stdio_module.stdio_client = fake_stdio_client

        monkeypatch.setitem(sys.modules, "mcp", mcp_module)
        monkeypatch.setitem(sys.modules, "mcp.client", mcp_client_module)
        monkeypatch.setitem(sys.modules, "mcp.client.stdio", mcp_stdio_module)
        monkeypatch.setattr(mcp_service, "_build_server_params", lambda name, cfg, conv_id="": {"server": name, "conv_id": conv_id})
        return created_stdio, created_sessions

    def test_reuses_one_session_for_repeated_calls_to_same_server(self, monkeypatch):
        created_stdio, created_sessions = self._install_fake_mcp(monkeypatch)

        pool = mcp_service.McpSessionPool(conv_id="conv-1")
        try:
            assert pool.invoke_tool("srv", {}, "tool", {"n": 1}) == "tool:1"
            assert pool.invoke_tool("srv", {}, "tool", {"n": 2}) == "tool:2"
        finally:
            pool.close()

        assert len(created_stdio) == 1
        assert len(created_sessions) == 1
        assert created_sessions[0].initialized == 1
        assert created_sessions[0].calls == [("tool", {"n": 1}), ("tool", {"n": 2})]
        assert created_sessions[0].exited == 1
        assert created_stdio[0].exited == 1

    def test_uses_separate_sessions_for_different_servers(self, monkeypatch):
        created_stdio, created_sessions = self._install_fake_mcp(monkeypatch)

        with mcp_service.McpSessionPool(conv_id="conv-1") as pool:
            assert pool.invoke_tool("one", {}, "tool", {"n": 1}) == "tool:1"
            assert pool.invoke_tool("two", {}, "tool", {"n": 2}) == "tool:2"

        assert len(created_stdio) == 2
        assert len(created_sessions) == 2
        assert all(session.initialized == 1 for session in created_sessions)
        assert all(session.exited == 1 for session in created_sessions)
        assert all(stdio.exited == 1 for stdio in created_stdio)

    def test_closed_pool_rejects_new_invocations(self, monkeypatch):
        self._install_fake_mcp(monkeypatch)
        pool = mcp_service.McpSessionPool(conv_id="conv-1")
        pool.close()

        with pytest.raises(RuntimeError, match="closed"):
            pool.invoke_tool("srv", {}, "tool", {})

    def test_lock_not_held_while_waiting_for_result(self, monkeypatch):
        """
        Regression: invoke_tool() must release self._lock before blocking on
        future.result().  If the lock were held across the wait, any code that
        acquires self._lock while a call is in-flight (e.g. a concurrent
        close()) would deadlock.

        This test proves the lock is free during the wait by acquiring it from
        a second thread while the pool is processing a (slightly delayed) tool
        call.  Under the old code the second thread would hang forever; under
        the fix it succeeds immediately.
        """
        import threading

        created_stdio, created_sessions = self._install_fake_mcp(monkeypatch)

        # Patch _build_server_params to return something the fake accepts.
        delay_event = threading.Event()
        original_invoke = mcp_service.McpSessionPool._invoke

        async def slow_invoke(self_pool, server_name, server_config, tool_name, arguments):
            # Briefly yield so the main thread has time to try acquiring the lock.
            import asyncio
            await asyncio.sleep(0.05)
            return await original_invoke(self_pool, server_name, server_config, tool_name, arguments)

        monkeypatch.setattr(mcp_service.McpSessionPool, "_invoke", slow_invoke)

        pool = mcp_service.McpSessionPool(conv_id="conv-1")
        pool.start()

        lock_acquired_while_in_flight = threading.Event()
        lock_acquire_error = []

        def try_acquire_lock():
            # Give invoke_tool() a moment to have submitted the job and be
            # blocking on future.result().
            import time
            time.sleep(0.02)
            acquired = pool._lock.acquire(timeout=1.0)
            if acquired:
                pool._lock.release()
                lock_acquired_while_in_flight.set()
            else:
                lock_acquire_error.append("timed out acquiring lock — possible deadlock")

        probe = threading.Thread(target=try_acquire_lock, daemon=True)
        probe.start()

        result = pool.invoke_tool("srv", {}, "tool", {"n": 1})
        probe.join(timeout=2.0)
        pool.close()

        assert result == "tool:1"
        assert not lock_acquire_error, lock_acquire_error[0]
        assert lock_acquired_while_in_flight.is_set(), (
            "Probe thread could not acquire lock while invoke_tool() was in flight — "
            "lock was still held across future.result() (deadlock regression)"
        )
