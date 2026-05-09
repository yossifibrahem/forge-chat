"""Additional tests for applying container process options."""
from __future__ import annotations

import os

import mcp_adapters


class TestApplyWorkspaceProcessOptionsContainerPath:
    def test_rewrites_stdio_params_to_docker_exec_and_container_env(self, monkeypatch, tmp_path):
        project = tmp_path / "tool-project"
        project.mkdir()
        (project / "package.json").write_text("{}")
        script = project / "dist" / "server.js"
        script.parent.mkdir()
        script.write_text("")

        ensured = []
        monkeypatch.setattr(
            mcp_adapters.container_service,
            "ensure_container",
            lambda conv_id, extra_volumes=None: ensured.append((conv_id, extra_volumes)),
        )
        monkeypatch.setattr(
            mcp_adapters.container_service,
            "wrap_command_for_exec",
            lambda conv_id, command, args, env=None: (
                "docker",
                ["exec", "-i", f"name={conv_id}", command, *args, f"env={env['WORKING_DIR']}"],
            ),
        )

        params = {"command": "node", "args": [str(script)], "cwd": "/tmp/ignored"}
        env = {"OLD": "value"}

        mcp_adapters.apply_workspace_process_options(
            params,
            env,
            server_name="filesystem",
            server_config={"args": [str(script)], "env": {"CUSTOM": "~/demo"}},
            conv_id="chat-123",
        )

        assert ensured == [("chat-123", [f"{project}:{project}:ro"])]
        assert params["command"] == "docker"
        assert params["args"][:3] == ["exec", "-i", "name=chat-123"]
        assert "cwd" not in params
        assert env == os.environ
