"""
Tests for container_service.py — pure/non-Docker functions only.

Docker subprocess calls are never made here. The functions under test are:
  _safe_id              — sanitises conv_id for use in container names (security)
  container_name        — full container name construction
  wrap_command_for_exec — builds the docker-exec argv (env injection, ordering)
  _is_name_conflict     — race-condition guard for concurrent container creation
  _volume_args          — volume flag construction
"""
from __future__ import annotations

import pytest

import container_service


# ---------------------------------------------------------------------------
# _safe_id
# ---------------------------------------------------------------------------

class TestSafeId:
    """
    _safe_id() feeds directly into container names passed to `docker run`.
    Any character that Docker or the shell might misinterpret must be
    replaced with an underscore.
    """

    def test_uuid_with_hyphens_unchanged(self):
        uid = "550e8400-e29b-41d4-a716-446655440000"
        assert container_service._safe_id(uid) == uid

    def test_alphanumeric_unchanged(self):
        assert container_service._safe_id("abc123") == "abc123"

    def test_spaces_replaced_with_underscore(self):
        assert "_" in container_service._safe_id("my conv id")
        assert " " not in container_service._safe_id("my conv id")

    def test_special_chars_replaced(self):
        result = container_service._safe_id("conv/with;bad&chars")
        assert "/" not in result
        assert ";" not in result
        assert "&" not in result

    def test_empty_string_returns_default(self):
        assert container_service._safe_id("") == "default"

    def test_none_like_falsy_returns_default(self):
        # None would cause AttributeError upstream; only empty string tested here
        assert container_service._safe_id("") == "default"

    def test_underscores_and_hyphens_kept(self):
        assert container_service._safe_id("my_conv-1") == "my_conv-1"

    def test_output_safe_for_docker_name(self):
        """Result must contain only characters Docker accepts in container names."""
        import re
        result = container_service._safe_id("weird: chars! here@")
        assert re.match(r"^[a-zA-Z0-9_-]+$", result), f"Unsafe name: {result!r}"


# ---------------------------------------------------------------------------
# container_name
# ---------------------------------------------------------------------------

class TestContainerName:

    def test_includes_prefix(self):
        name = container_service.container_name("abc")
        assert name.startswith(container_service.CONTAINER_PREFIX)

    def test_includes_sanitised_id(self):
        name = container_service.container_name("my conv")
        assert "my_conv" in name or "my conv" not in name  # space removed

    def test_special_chars_in_id_sanitised(self):
        name = container_service.container_name("conv/slash")
        assert "/" not in name


# ---------------------------------------------------------------------------
# wrap_command_for_exec
# ---------------------------------------------------------------------------

class TestWrapCommandForExec:
    """
    wrap_command_for_exec builds the argv for `docker exec`. The exact shape
    of this list is what MCP servers receive — getting it wrong means broken
    tool calls.
    """

    def test_returns_docker_as_command(self):
        cmd, _ = container_service.wrap_command_for_exec("c1", "npx", ["-y", "@fs"])
        assert cmd == "docker"

    def test_first_arg_is_exec(self):
        _, args = container_service.wrap_command_for_exec("c1", "npx", [])
        assert args[0] == "exec"

    def test_interactive_flag_present(self):
        _, args = container_service.wrap_command_for_exec("c1", "npx", [])
        assert "-i" in args

    def test_workdir_set_to_workspace(self):
        _, args = container_service.wrap_command_for_exec("c1", "npx", [])
        assert "--workdir" in args
        idx = args.index("--workdir")
        assert args[idx + 1] == "/workspace"

    def test_container_name_in_args(self):
        _, args = container_service.wrap_command_for_exec("c1", "npx", ["-y"])
        expected_name = container_service.container_name("c1")
        assert expected_name in args

    def test_original_command_follows_container_name(self):
        _, args = container_service.wrap_command_for_exec("c1", "node", ["server.js"])
        name = container_service.container_name("c1")
        idx = args.index(name)
        assert args[idx + 1] == "node"

    def test_original_args_appended_after_command(self):
        _, args = container_service.wrap_command_for_exec("c1", "node", ["server.js", "--port", "3000"])
        assert args[-3:] == ["server.js", "--port", "3000"]

    def test_env_vars_injected_as_env_flags(self):
        _, args = container_service.wrap_command_for_exec(
            "c1", "npx", [], env={"MY_VAR": "hello", "PORT": "8080"}
        )
        # Each env entry must appear as --env KEY=VALUE
        assert "--env" in args
        env_pairs = [args[i + 1] for i, a in enumerate(args) if a == "--env"]
        assert any(p.startswith("MY_VAR=") for p in env_pairs)
        assert any(p.startswith("PORT=") for p in env_pairs)

    def test_env_vars_appear_before_container_name(self):
        """--env flags must come before the container name, not after."""
        _, args = container_service.wrap_command_for_exec(
            "c1", "npx", [], env={"K": "V"}
        )
        name = container_service.container_name("c1")
        env_idx = next(i for i, a in enumerate(args) if a == "--env")
        name_idx = args.index(name)
        assert env_idx < name_idx

    def test_no_env_produces_no_env_flags(self):
        _, args = container_service.wrap_command_for_exec("c1", "npx", [], env=None)
        assert "--env" not in args

    def test_empty_env_dict_produces_no_env_flags(self):
        _, args = container_service.wrap_command_for_exec("c1", "npx", [], env={})
        assert "--env" not in args


# ---------------------------------------------------------------------------
# _is_name_conflict
# ---------------------------------------------------------------------------

class TestIsNameConflict:
    """
    Guards against the race where two Flask workers try to create the same
    container simultaneously. Must parse Docker's error messages reliably.
    """

    def test_already_in_use_detected(self):
        assert container_service._is_name_conflict(
            'Error response from daemon: Conflict. The container name "/lumen-chat-abc" is already in use'
        )

    def test_conflict_keyword_detected(self):
        assert container_service._is_name_conflict("conflict with existing container")

    def test_case_insensitive(self):
        assert container_service._is_name_conflict("CONFLICT: name already in use")
        assert container_service._is_name_conflict("Already In Use by container xyz")

    def test_unrelated_error_not_detected(self):
        assert not container_service._is_name_conflict("OCI runtime error: exec failed")
        assert not container_service._is_name_conflict("")
        assert not container_service._is_name_conflict("No such image: lumen-sandbox")


# ---------------------------------------------------------------------------
# _volume_args
# ---------------------------------------------------------------------------

class TestVolumeArgs:
    """
    Verifies the --volume flag list passed to `docker run`.
    """
    from pathlib import Path

    def test_workspace_volume_always_first(self, tmp_path):
        result = container_service._volume_args(tmp_path, [])
        assert result[0] == "--volume"
        assert result[1].startswith(str(tmp_path))
        assert ":/workspace" in result[1]

    def test_extra_volumes_appended(self, tmp_path):
        extra = ["/host/path:/host/path:ro"]
        result = container_service._volume_args(tmp_path, extra)
        assert "/host/path:/host/path:ro" in result

    def test_no_extra_volumes_only_workspace(self, tmp_path):
        result = container_service._volume_args(tmp_path, [])
        # Should be exactly ["--volume", "<workspace>:/workspace"]
        assert len(result) == 2


# ---------------------------------------------------------------------------
# discovery container cleanup protection
# ---------------------------------------------------------------------------

class TestCleanupStaleDiscoveryContainer:
    """
    The settings/tools discovery container is reusable and intentionally kept
    stopped between discovery runs, so stale cleanup must never delete it.
    """

    def test_cleanup_stale_keeps_discovery_container(self, monkeypatch):
        import subprocess

        discovery_name = container_service.container_name(
            container_service.DISCOVERY_CONTAINER_ID
        )
        active_name = container_service.container_name("active-chat")
        stale_name = container_service.container_name("old-chat")
        calls: list[list[str]] = []

        def fake_run(args):
            calls.append(args)
            if args[:3] == ["docker", "ps", "-a"]:
                return subprocess.CompletedProcess(
                    args,
                    0,
                    stdout=f"{discovery_name}\n{active_name}\n{stale_name}\n",
                    stderr="",
                )
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        monkeypatch.setattr(container_service, "_run", fake_run)

        removed = container_service.cleanup_stale(["active-chat"])

        assert removed == ["old-chat"]
        rm_calls = [args for args in calls if args[:3] == ["docker", "rm", "-f"]]
        assert rm_calls == [["docker", "rm", "-f", stale_name]]
