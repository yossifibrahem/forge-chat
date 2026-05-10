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
# collect_all_extra_volumes
# ---------------------------------------------------------------------------

class TestCollectAllExtraVolumes:
    """
    collect_all_extra_volumes gathers host-mount volume specs for every enabled
    MCP server upfront, so the container can be created with all required paths
    before the turn begins — preventing mid-turn recreation when the model
    switches between servers.
    """

    def test_returns_empty_for_no_server_names(self, isolated_mcp_config):
        isolated_mcp_config.write_text('{"mcpServers": {}}')
        assert mcp_service.collect_all_extra_volumes([]) == []

    def test_returns_empty_for_packaged_server(self, isolated_mcp_config):
        config = {"mcpServers": {
            "exa": {"command": "npx", "args": ["-y", "mcp-remote", "https://mcp.exa.ai/mcp"]}
        }}
        isolated_mcp_config.write_text(__import__("json").dumps(config))
        assert mcp_service.collect_all_extra_volumes(["exa"]) == []

    def test_returns_empty_for_unknown_server_name(self, isolated_mcp_config):
        isolated_mcp_config.write_text('{"mcpServers": {}}')
        assert mcp_service.collect_all_extra_volumes(["nonexistent"]) == []

    def test_collects_volume_for_local_node_server(self, isolated_mcp_config, tmp_path):
        project = tmp_path / "bash-mcp-server"
        (project / "dist").mkdir(parents=True)
        (project / "dist" / "index.js").touch()
        (project / "package.json").touch()

        config = {"mcpServers": {
            "bash": {"command": "node", "args": [str(project / "dist" / "index.js")]}
        }}
        isolated_mcp_config.write_text(__import__("json").dumps(config))

        volumes = mcp_service.collect_all_extra_volumes(["bash"])
        assert len(volumes) == 1
        assert str(project) in volumes[0]

    def test_combines_volumes_for_two_local_servers(self, isolated_mcp_config, tmp_path):
        for name in ("bash-mcp-server", "filesystem-mcp-server"):
            p = tmp_path / name / "dist"
            p.mkdir(parents=True)
            (p / "index.js").touch()
            (tmp_path / name / "package.json").touch()

        config = {"mcpServers": {
            "bash":       {"command": "node", "args": [str(tmp_path / "bash-mcp-server/dist/index.js")]},
            "filesystem": {"command": "node", "args": [str(tmp_path / "filesystem-mcp-server/dist/index.js")]},
        }}
        isolated_mcp_config.write_text(__import__("json").dumps(config))

        volumes = mcp_service.collect_all_extra_volumes(["bash", "filesystem"])
        assert len(volumes) == 2
        assert any("bash-mcp-server" in v for v in volumes)
        assert any("filesystem-mcp-server" in v for v in volumes)

    def test_deduplicates_same_source_across_servers(self, isolated_mcp_config, tmp_path):
        project = tmp_path / "shared-server"
        (project / "dist").mkdir(parents=True)
        script = project / "dist" / "index.js"
        script.touch()
        (project / "package.json").touch()

        config = {"mcpServers": {
            "a": {"command": "node", "args": [str(script)]},
            "b": {"command": "node", "args": [str(script)]},
        }}
        isolated_mcp_config.write_text(__import__("json").dumps(config))

        volumes = mcp_service.collect_all_extra_volumes(["a", "b"])
        sources = [v.split(":", 1)[0] for v in volumes]
        assert len(sources) == len(set(sources))  # no duplicates
