"""Unit tests for Docker container lifecycle helpers."""
from __future__ import annotations

import subprocess

import pytest

import container_service


def _cp(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class TestContainerNaming:
    def test_container_name_sanitises_conversation_id(self):
        assert container_service.container_name("chat/../../bad id") == "lumen-chat-chat_______bad_id"

    def test_workspace_uses_sanitised_id(self):
        path = container_service.conversation_workspace("a/b")
        assert path.name == "a_b"
        assert path.exists()


class TestDockerCommand:
    def test_docker_run_command_contains_sandbox_defaults_and_workspace_mount(self, tmp_path):
        cmd = container_service._docker_run_command(
            "lumen-chat-1",
            tmp_path,
            ["/host/tool:/host/tool:ro"],
        )

        assert cmd[:3] == ["docker", "run", "--detach"]
        assert "--name" in cmd and "lumen-chat-1" in cmd
        assert "--workdir" in cmd and "/workspace" in cmd
        assert "--cap-drop" in cmd and "ALL" in cmd
        assert f"{tmp_path}:/workspace" in cmd
        assert "/host/tool:/host/tool:ro" in cmd
        assert cmd[-1] == container_service.SANDBOX_IMAGE

    def test_wrap_command_for_exec_includes_env_and_workspace(self):
        command, args = container_service.wrap_command_for_exec(
            "conv1",
            "node",
            ["server.js"],
            env={"WORKING_DIR": "/workspace"},
        )

        assert command == "docker"
        assert args[:3] == ["exec", "-i", "--workdir"]
        assert "/workspace" in args
        assert "--env" in args
        assert "WORKING_DIR=/workspace" in args
        assert args[-3:] == ["lumen-chat-conv1", "node", "server.js"]


class TestEnsureContainer:
    def test_missing_container_is_created(self, monkeypatch):
        monkeypatch.setattr(container_service, "get_status", lambda conv_id: "missing")
        calls = []
        monkeypatch.setattr(container_service, "_run", lambda args: calls.append(args) or _cp(stdout="abc123"))

        info = container_service.ensure_container("conv-create")

        assert info.status == "running"
        assert info.name == "lumen-chat-conv-create"
        assert calls[0][:3] == ["docker", "run", "--detach"]

    def test_stopped_container_is_started_without_recreate(self, monkeypatch):
        monkeypatch.setattr(container_service, "get_status", lambda conv_id: "stopped")
        monkeypatch.setattr(container_service, "_get_mounted_sources", lambda name: set())
        started = []
        monkeypatch.setattr(container_service, "_start_existing", lambda name: started.append(name))

        info = container_service.ensure_container("conv-stopped")

        assert info.status == "running"
        assert started == ["lumen-chat-conv-stopped"]

    def test_running_container_with_required_mount_is_reused(self, monkeypatch):
        monkeypatch.setattr(container_service, "get_status", lambda conv_id: "running")
        monkeypatch.setattr(container_service, "_get_mounted_sources", lambda name: {"/tool"})

        info = container_service.ensure_container("conv-running", extra_volumes=["/tool:/tool:ro"])

        assert info.status == "running"
        assert info.name == "lumen-chat-conv-running"

    def test_existing_container_missing_extra_mount_is_recreated(self, monkeypatch):
        statuses = iter(["running", "missing"])
        monkeypatch.setattr(container_service, "get_status", lambda conv_id: next(statuses))
        monkeypatch.setattr(container_service, "_get_mounted_sources", lambda name: set())
        removed = []
        monkeypatch.setattr(container_service, "stop_container", lambda conv_id: removed.append(conv_id))
        monkeypatch.setattr(container_service, "_run", lambda args: _cp(stdout="newid"))

        info = container_service.ensure_container("conv-remount", extra_volumes=["/tool:/tool:ro"])

        assert removed == ["conv-remount"]
        assert info.status == "running"

    def test_name_conflict_reuses_concurrently_created_container(self, monkeypatch):
        monkeypatch.setattr(container_service, "get_status", lambda conv_id: "missing")
        monkeypatch.setattr(container_service, "_run", lambda args: _cp(1, stderr="Conflict. name already in use"))
        monkeypatch.setattr(container_service, "_reuse_conflicting_container", lambda conv_id, sources: container_service.ContainerInfo(conv_id, "reused", container_service.conversation_workspace(conv_id), "running"))

        info = container_service.ensure_container("conv-race")

        assert info.name == "reused"

    def test_create_failure_raises_runtime_error(self, monkeypatch):
        monkeypatch.setattr(container_service, "get_status", lambda conv_id: "missing")
        monkeypatch.setattr(container_service, "_run", lambda args: _cp(1, stderr="boom"))

        with pytest.raises(RuntimeError, match="Failed to create container"):
            container_service.ensure_container("conv-fail")


class TestCleanupAndDelete:
    def test_cleanup_stale_removes_only_unknown_prefixed_containers(self, monkeypatch):
        calls = []
        def fake_run(args):
            calls.append(args)
            if args[:3] == ["docker", "ps", "-a"]:
                return _cp(stdout="lumen-chat-known\nlumen-chat-old\nother\n")
            return _cp()
        monkeypatch.setattr(container_service, "_run", fake_run)

        removed = container_service.cleanup_stale(["known"])

        assert removed == ["old"]
        assert ["docker", "rm", "-f", "lumen-chat-old"] in calls
        assert ["docker", "rm", "-f", "other"] not in calls

    def test_delete_workspace_refuses_non_directory(self):
        path = container_service.CONTAINERS_ROOT / "file-id"
        path.write_text("not a dir")

        with pytest.raises(RuntimeError, match="non-directory"):
            container_service.delete_workspace("file-id")

    def test_cleanup_stale_returns_empty_when_docker_ps_fails(self, monkeypatch):
        monkeypatch.setattr(container_service, "_run", lambda args: _cp(1, stderr="docker down"))

        assert container_service.cleanup_stale(["known"]) == []

    def test_stop_container_noops_when_missing(self, monkeypatch):
        calls = []
        monkeypatch.setattr(container_service, "get_status", lambda conv_id: "missing")
        monkeypatch.setattr(container_service, "_run", lambda args: calls.append(args) or _cp())

        container_service.stop_container("gone")

        assert calls == []

    def test_stop_container_removes_existing_container(self, monkeypatch):
        calls = []
        monkeypatch.setattr(container_service, "get_status", lambda conv_id: "running")
        monkeypatch.setattr(container_service, "_run", lambda args: calls.append(args) or _cp())

        container_service.stop_container("conv-stop")

        assert calls == [["docker", "rm", "-f", "lumen-chat-conv-stop"]]

    def test_delete_workspace_removes_existing_directory(self):
        path = container_service.conversation_workspace("delete-me")
        (path / "file.txt").write_text("bye")

        container_service.delete_workspace("delete-me")

        assert not path.exists()

    def test_delete_workspace_ignores_missing_directory(self):
        path = container_service.CONTAINERS_ROOT / "already-gone"
        assert not path.exists()

        container_service.delete_workspace("already-gone")

        assert not path.exists()


class TestStatusAndVolumeHelpers:
    def test_get_status_maps_docker_states(self, monkeypatch):
        monkeypatch.setattr(container_service, "_run", lambda args: _cp(stdout="running\n"))
        assert container_service.get_status("conv") == "running"

        monkeypatch.setattr(container_service, "_run", lambda args: _cp(stdout="exited\n"))
        assert container_service.get_status("conv") == "stopped"

        monkeypatch.setattr(container_service, "_run", lambda args: _cp(1, stderr="not found"))
        assert container_service.get_status("conv") == "missing"

    def test_volume_source_uses_host_side_before_first_colon(self):
        assert container_service._volume_source("/host/path:/workspace/path:ro") == "/host/path"

    def test_volume_args_flattens_workspace_and_extra_volumes(self, tmp_path):
        assert container_service._volume_args(tmp_path, ["/a:/a:ro", "/b:/b"]) == [
            "--volume", f"{tmp_path}:/workspace",
            "--volume", "/a:/a:ro",
            "--volume", "/b:/b",
        ]
