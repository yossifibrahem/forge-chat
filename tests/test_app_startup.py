"""Startup behavior tests for app.py."""
from __future__ import annotations

import subprocess

import pytest

import app as app_module


def completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=["docker"], returncode=returncode, stdout=stdout, stderr=stderr)


class TestDockerStartupChecks:
    def test_require_docker_exits_when_docker_info_fails(self, monkeypatch):
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            return completed(returncode=1, stderr="daemon unavailable")

        monkeypatch.setattr(app_module.subprocess, "run", fake_run)

        with pytest.raises(SystemExit) as exc:
            app_module._require_docker()

        assert exc.value.code == 1
        assert calls == [["docker", "info"]]

    def test_require_docker_passes_when_docker_info_succeeds(self, monkeypatch):
        monkeypatch.setattr(app_module.subprocess, "run", lambda args, **kwargs: completed())

        app_module._require_docker()

    def test_require_sandbox_image_exits_when_image_missing(self, monkeypatch):
        calls = []
        monkeypatch.setattr(app_module.container_service, "SANDBOX_IMAGE", "custom-sandbox")

        def fake_run(args, **kwargs):
            calls.append(args)
            return completed(returncode=1, stderr="no such image")

        monkeypatch.setattr(app_module.subprocess, "run", fake_run)

        with pytest.raises(SystemExit) as exc:
            app_module._require_sandbox_image()

        assert exc.value.code == 1
        assert calls == [["docker", "image", "inspect", "custom-sandbox"]]

    def test_require_sandbox_image_passes_when_image_exists(self, monkeypatch):
        monkeypatch.setattr(app_module.subprocess, "run", lambda args, **kwargs: completed())

        app_module._require_sandbox_image()


class TestCreateApp:
    def test_create_app_runs_checks_registers_routes_and_cleans_stale(self, monkeypatch):
        calls = []
        monkeypatch.setattr(app_module, "_require_docker", lambda: calls.append("docker"))
        monkeypatch.setattr(app_module, "_require_sandbox_image", lambda: calls.append("image"))
        monkeypatch.setattr(app_module, "_cleanup_stale_containers", lambda: calls.append("cleanup"))

        flask_app = app_module.create_app()

        assert calls == ["docker", "image", "cleanup"]
        assert flask_app.test_client().get("/api/conversations").status_code == 200

    def test_cleanup_stale_containers_removes_unknown_containers(self, monkeypatch):
        calls = []
        import store

        monkeypatch.setattr(store, "list_all", lambda: [{"id": "known-1"}, {"id": "known-2"}])
        monkeypatch.setattr(app_module.container_service, "cleanup_stale", lambda ids: calls.append(ids) or ["old"])

        app_module._cleanup_stale_containers()

        assert calls == [["known-1", "known-2"]]

    def test_cleanup_stale_containers_is_non_fatal(self, monkeypatch):
        import store

        monkeypatch.setattr(store, "list_all", lambda: (_ for _ in ()).throw(RuntimeError("store down")))

        app_module._cleanup_stale_containers()
