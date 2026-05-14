"""
Shared pytest fixtures for Lumen AI Chat tests.

Key responsibilities:
  - Redirect all filesystem paths (conversations, images, containers) to tmp_path
    so tests never touch ~/.lumen.
  - Create a Flask test app with Docker startup checks completely bypassed.
  - Expose a `client` fixture for HTTP integration tests.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def _clear_persistent_pools(monkeypatch):
    """Reset the persistent MCP session pool registry before every test.

    The registry is module-level state in mcp_service.  Without this fixture,
    a pool created by one test could leak into the next test, causing
    unexpected reuse or interference.

    Pools must be closed before the registry is replaced, not just discarded.
    Discarding a live pool without closing it leaks its worker thread.
    """
    import mcp_service
    # Close any pools left over from a previous test before wiping the registry.
    mcp_service.close_all_persistent_pools()
    monkeypatch.setattr("mcp_service._persistent_pools", {})


# ---------------------------------------------------------------------------
# Filesystem isolation
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_lumen(tmp_path, monkeypatch):
    """
    Redirect every Lumen storage path to an isolated temp directory.

    Patches module-level constants in `store` and `container_service` so that
    all fixture-scoped tests read and write to `tmp_path` only.

    Returns a dict with the three directory Paths for use in individual tests.
    """
    conv_dir = tmp_path / "conversations"
    images_dir = tmp_path / "images"
    containers_dir = tmp_path / "containers"
    conv_dir.mkdir()
    images_dir.mkdir()
    containers_dir.mkdir()

    monkeypatch.setattr("store.CONVERSATIONS_DIR", conv_dir)
    monkeypatch.setattr("store.IMAGES_DIR", images_dir)
    monkeypatch.setattr("container_service.CONTAINERS_ROOT", containers_dir)

    import store
    store.invalidate_index()

    return {
        "conv_dir": conv_dir,
        "images_dir": images_dir,
        "containers_dir": containers_dir,
        "root": tmp_path,
    }


# ---------------------------------------------------------------------------
# Flask app / test client
# ---------------------------------------------------------------------------

@pytest.fixture
def app(tmp_lumen):
    """
    Create a Flask test application with all Docker calls mocked out.

    `create_app()` in app.py calls:
      1. _require_docker()       — subprocess call to `docker info`
      2. _require_sandbox_image() — subprocess call to `docker image inspect`
      3. _cleanup_stale_containers() — calls container_service.cleanup_stale

    We patch (1) and (2) at the module level inside app.py (where create_app
    resolves them via the module's global dict) and stub out (3) entirely.
    """
    import app as app_module

    with (
        patch("app._require_docker"),
        patch("app._require_sandbox_image"),
        patch("container_service.cleanup_stale", return_value=[]),
    ):
        flask_app = app_module.create_app()

    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    """Flask test client wired to the isolated test app."""
    return app.test_client()


# ---------------------------------------------------------------------------
# Helpers shared across test modules
# ---------------------------------------------------------------------------

def make_png_bytes() -> bytes:
    """Return a valid 1×1 red PNG as raw bytes."""
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def make_png_b64() -> str:
    """Return a valid 1×1 PNG as a base64 string (no line breaks)."""
    import base64
    return base64.b64encode(make_png_bytes()).decode()