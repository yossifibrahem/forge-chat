"""
Flask route integration tests for Lumen AI Chat.

Uses the `client` fixture (Flask test client against an isolated test app).
Docker and OpenAI calls are mocked throughout.

Coverage:
  - GET/POST/PUT/DELETE /api/conversations
  - GET /api/conversations/<id>/workspace and /container
  - GET/POST /api/mcp/config
  - POST/GET /api/images
  - GET /api/conversations/<id>/files (list + content + download)
  - POST /api/chat/stream (attach, cancel, approve)
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import store
from tests.conftest import make_png_b64


# ===========================================================================
# Conversation CRUD
# ===========================================================================

class TestListConversations:

    def test_empty_list(self, client, tmp_lumen):
        resp = client.get("/api/conversations")
        assert resp.status_code == 200
        assert resp.json == []

    def test_includes_created_conversation(self, client, tmp_lumen):
        store.create("Alpha")
        resp = client.get("/api/conversations")
        assert any(c["title"] == "Alpha" for c in resp.json)


class TestCreateConversation:

    def test_returns_201_with_id(self, client, tmp_lumen):
        resp = client.post("/api/conversations",
                           json={"title": "Named"},
                           content_type="application/json")
        assert resp.status_code == 201
        assert "id" in resp.json
        assert resp.json["title"] == "Named"

    def test_default_title_when_missing(self, client, tmp_lumen):
        resp = client.post("/api/conversations",
                           json={},
                           content_type="application/json")
        assert resp.status_code == 201
        assert resp.json.get("title")  # non-empty


class TestGetConversation:

    def test_returns_200_for_existing(self, client, tmp_lumen):
        conv = store.create("get-me")
        resp = client.get(f"/api/conversations/{conv['id']}")
        assert resp.status_code == 200
        assert resp.json["title"] == "get-me"

    def test_returns_404_for_missing(self, client, tmp_lumen):
        resp = client.get("/api/conversations/does-not-exist")
        assert resp.status_code == 404

    def test_response_includes_working_directory(self, client, tmp_lumen):
        conv = store.create("wd-check")
        resp = client.get(f"/api/conversations/{conv['id']}")
        assert "working_directory" in resp.json


class TestUpdateConversation:

    def test_updates_title(self, client, tmp_lumen):
        conv = store.create("old")
        resp = client.put(f"/api/conversations/{conv['id']}",
                          json={"title": "new"},
                          content_type="application/json")
        assert resp.status_code == 200
        assert resp.json["title"] == "new"
        assert resp.json["id"] == conv["id"]  # id must be preserved


class TestDeleteConversation:

    def test_returns_ok_true(self, client, tmp_lumen):
        conv = store.create("delete-me")
        with patch("container_service.stop_container"), \
             patch("container_service.delete_workspace"):
            resp = client.delete(f"/api/conversations/{conv['id']}")
        assert resp.status_code == 200
        assert resp.json["ok"] is True

    def test_conversation_gone_after_delete(self, client, tmp_lumen):
        conv = store.create("gone")
        with patch("container_service.stop_container"), \
             patch("container_service.delete_workspace"):
            client.delete(f"/api/conversations/{conv['id']}")
        assert store.load(conv["id"]) is None

    def test_returns_404_for_nonexistent(self, client, tmp_lumen):
        with patch("container_service.stop_container"), \
             patch("container_service.delete_workspace"):
            resp = client.delete("/api/conversations/ghost-99")
        assert resp.status_code == 404


class TestConversationMetaRoutes:

    def test_workspace_returns_absolute_path(self, client, tmp_lumen):
        conv = store.create("ws")
        resp = client.get(f"/api/conversations/{conv['id']}/workspace")
        assert resp.status_code == 200
        wd = resp.json.get("working_directory", "")
        assert wd.startswith("/")  # must be an absolute host path

    def test_container_status_for_known_conv(self, client, tmp_lumen):
        conv = store.create("container")
        with patch("container_service.get_status", return_value="missing"):
            resp = client.get(f"/api/conversations/{conv['id']}/container")
        assert resp.status_code == 200
        assert resp.json["status"] == "missing"
        assert resp.json["conv_id"] == conv["id"]


# ===========================================================================
# MCP config
# ===========================================================================

class TestMcpConfigRoutes:

    @pytest.fixture(autouse=True)
    def _isolate_mcp_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr("mcp_service.MCP_CONFIG_FILE", tmp_path / "mcp.json")

    def test_get_returns_empty_when_no_file(self, client, tmp_lumen):
        resp = client.get("/api/mcp/config")
        assert resp.status_code == 200
        assert resp.json == {"mcpServers": {}}

    def test_post_saves_config(self, client, tmp_lumen):
        config = {"mcpServers": {"fs": {"command": "npx", "args": []}}}
        resp = client.post("/api/mcp/config",
                           json=config,
                           content_type="application/json")
        assert resp.status_code == 200
        assert resp.json["ok"] is True

    def test_post_then_get_roundtrip(self, client, tmp_lumen):
        config = {"mcpServers": {"bash": {"command": "bash", "args": []}}}
        client.post("/api/mcp/config", json=config, content_type="application/json")
        resp = client.get("/api/mcp/config")
        assert resp.json == config

    def test_post_invalid_config_returns_400(self, client, tmp_lumen):
        resp = client.post("/api/mcp/config",
                           json={"mcpServers": "not-an-object"},
                           content_type="application/json")
        assert resp.status_code == 400
        assert "error" in resp.json


# ===========================================================================
# Image upload and serving
# ===========================================================================

class TestImageRoutes:

    def test_upload_valid_png_returns_ref_and_url(self, client, tmp_lumen):
        resp = client.post("/api/images",
                           json={"data": make_png_b64(), "media_type": "image/png"},
                           content_type="application/json")
        assert resp.status_code == 200
        assert "ref" in resp.json
        assert resp.json["url"].startswith("/api/images/")

    def test_upload_invalid_base64_returns_400(self, client, tmp_lumen):
        resp = client.post("/api/images",
                           json={"data": "not-base64!!!", "media_type": "image/png"},
                           content_type="application/json")
        assert resp.status_code == 400
        assert "error" in resp.json

    def test_upload_unsupported_media_type_returns_400(self, client, tmp_lumen):
        resp = client.post("/api/images",
                           json={"data": make_png_b64(), "media_type": "image/bmp"},
                           content_type="application/json")
        assert resp.status_code == 400

    def test_serve_uploaded_image_200(self, client, tmp_lumen):
        upload = client.post("/api/images",
                             json={"data": make_png_b64(), "media_type": "image/png"},
                             content_type="application/json")
        name = upload.json["ref"]
        resp = client.get(f"/api/images/{name}")
        assert resp.status_code == 200
        assert resp.content_type.startswith("image/")

    def test_serve_nonexistent_image_returns_404(self, client, tmp_lumen):
        resp = client.get("/api/images/" + "a" * 64 + ".png")
        assert resp.status_code == 404

    def test_serve_unsafe_image_name_returns_404(self, client, tmp_lumen):
        resp = client.get("/api/images/../../etc/passwd")
        # Flask will 404 or redirect — either way, not 200
        assert resp.status_code in (400, 404)

    def test_same_content_deduplicated(self, client, tmp_lumen):
        b64 = make_png_b64()
        r1 = client.post("/api/images", json={"data": b64, "media_type": "image/png"},
                         content_type="application/json")
        r2 = client.post("/api/images", json={"data": b64, "media_type": "image/png"},
                         content_type="application/json")
        assert r1.json["ref"] == r2.json["ref"]


# ===========================================================================
# Workspace file routes
# ===========================================================================

class TestWorkspaceFileRoutes:

    def _make_workspace(self, tmp_lumen) -> tuple[str, Path]:
        conv = store.create("file-test")
        conv_id = conv["id"]
        root = tmp_lumen["containers_dir"] / conv_id
        root.mkdir(parents=True, exist_ok=True)
        return conv_id, root

    def test_list_unknown_conv_returns_error(self, client, tmp_lumen):
        resp = client.get("/api/conversations/ghost/files")
        # Service returns ({"error": ...}, 404) which route passes through
        assert resp.status_code in (404, 500)

    def test_list_files_returns_200_with_entries(self, client, tmp_lumen):
        conv_id, root = self._make_workspace(tmp_lumen)
        (root / "readme.md").write_text("# hi")
        with patch("workspace_service.workspace_root", return_value=root):
            resp = client.get(f"/api/conversations/{conv_id}/files")
        assert resp.status_code == 200
        assert "entries" in resp.json

    def test_file_content_returns_text(self, client, tmp_lumen):
        conv_id, root = self._make_workspace(tmp_lumen)
        (root / "script.py").write_text("x = 42")
        with patch("workspace_service.workspace_root", return_value=root):
            resp = client.get(
                f"/api/conversations/{conv_id}/files/content",
                query_string={"path": "/workspace/script.py"},
            )
        assert resp.status_code == 200
        assert resp.json["content"] == "x = 42"

    def test_file_download_returns_attachment(self, client, tmp_lumen):
        conv_id, root = self._make_workspace(tmp_lumen)
        (root / "data.txt").write_text("download me")
        with patch("workspace_service.workspace_root", return_value=root):
            resp = client.get(
                f"/api/conversations/{conv_id}/files/download",
                query_string={"path": "/workspace/data.txt"},
            )
        assert resp.status_code == 200
        assert b"download me" in resp.data

    def test_download_nonexistent_file_returns_404(self, client, tmp_lumen):
        conv_id, root = self._make_workspace(tmp_lumen)
        with patch("workspace_service.workspace_root", return_value=root):
            resp = client.get(
                f"/api/conversations/{conv_id}/files/download",
                query_string={"path": "/workspace/ghost.txt"},
            )
        assert resp.status_code == 404

    def test_list_with_traversal_path_returns_400(self, client, tmp_lumen):
        conv_id, root = self._make_workspace(tmp_lumen)
        with patch("workspace_service.workspace_root", return_value=root):
            resp = client.get(
                f"/api/conversations/{conv_id}/files",
                query_string={"path": "../escape"},
            )
        assert resp.status_code == 400


# ===========================================================================
# Chat stream routes (minimal — no real OpenAI call)
# ===========================================================================

class TestChatStreamRoutes:

    def test_cancel_unknown_stream_returns_404(self, client, tmp_lumen):
        resp = client.post("/api/chat/cancel",
                           json={"stream_id": "ghost-stream"},
                           content_type="application/json")
        assert resp.status_code == 404
        assert resp.json["ok"] is False

    def test_attach_to_nonexistent_stream_returns_404(self, client, tmp_lumen):
        resp = client.post("/api/chat/stream",
                           json={"stream_id": "ghost-stream", "attach": True},
                           content_type="application/json")
        assert resp.status_code == 404

    def test_approve_returns_ok_regardless_of_stream_existence(self, client, tmp_lumen):
        # resolve_tool_approval is a no-op for unknown streams; route still returns 200
        resp = client.post("/api/chat/approve",
                           json={"stream_id": "ghost", "call_id": "c1", "approved": True},
                           content_type="application/json")
        assert resp.status_code == 200
        assert resp.json["ok"] is True


# ===========================================================================
# Models route
# ===========================================================================

class TestModelsRoute:

    def test_returns_model_list(self, client, tmp_lumen):
        mock_model = MagicMock()
        mock_model.id = "gpt-4o"
        mock_client = MagicMock()
        mock_client.models.list.return_value = [mock_model]

        with patch("chat_turn_service.openai_client", return_value=mock_client):
            resp = client.post("/api/models",
                               json={"api_key": "sk-test"},
                               content_type="application/json")
        assert resp.status_code == 200
        assert "models" in resp.json
        assert "gpt-4o" in resp.json["models"]

    def test_bad_api_key_returns_400(self, client, tmp_lumen):
        mock_client = MagicMock()
        mock_client.models.list.side_effect = Exception("invalid api key")

        with patch("chat_turn_service.openai_client", return_value=mock_client):
            resp = client.post("/api/models",
                               json={"api_key": "bad"},
                               content_type="application/json")
        assert resp.status_code == 400
        assert "error" in resp.json


# ===========================================================================
# Index route
# ===========================================================================

class TestIndexRoute:

    def test_renders_app_shell(self, client, tmp_lumen):
        resp = client.get("/")
        assert resp.status_code == 200
        # Must contain the top-level script tag that bootstraps the app
        assert b"app.js" in resp.data


# ===========================================================================
# MCP tools discovery
# ===========================================================================

class TestMcpToolsDiscoveryRoutes:

    def test_no_conversation_uses_reusable_discovery_container(self, client, tmp_lumen):
        config = {"mcpServers": {"fs": {"command": "npx", "args": []}}}

        def fake_fetch(server_name, server_config, *, conv_id=""):
            return {"server_name": server_name, "conv_id": conv_id}

        def fake_run_async(payload):
            return [{
                "server": payload["server_name"],
                "name": "list_files",
                "description": "List files",
                "inputSchema": {},
            }]

        with (
            patch("mcp_service.load_config", return_value=config),
            patch("mcp_adapters.extract_host_mounts", return_value=[]),
            patch("container_service.ensure_container") as ensure_container,
            patch("container_service.stop_container_process") as stop_container_process,
            patch("mcp_service.fetch_tools", new=MagicMock(side_effect=fake_fetch)) as fetch_tools,
            patch("mcp_service.run_async", side_effect=fake_run_async),
        ):
            resp = client.get("/api/mcp/tools")

        assert resp.status_code == 200
        assert resp.json == [{
            "server": "fs",
            "name": "list_files",
            "description": "List files",
            "inputSchema": {},
        }]
        ensure_container.assert_called_once_with(
            "__mcp_discovery__",
            extra_volumes=[],
        )
        fetch_tools.assert_called_once_with(
            "fs",
            config["mcpServers"]["fs"],
            conv_id="__mcp_discovery__",
        )
        stop_container_process.assert_called_once_with("__mcp_discovery__")

    def test_no_conversation_mounts_deduplicated_discovery_volumes(self, client, tmp_lumen):
        config = {
            "mcpServers": {
                "a": {"command": "node", "args": ["/srv/a/server.js"]},
                "b": {"command": "node", "args": ["/srv/b/server.js"]},
            }
        }

        def fake_extract(cfg):
            if cfg is config["mcpServers"]["a"]:
                return [
                    "/host/shared:/host/shared:ro",
                    "/host/unique:/host/unique:ro",
                ]
            return ["/host/shared:/host/shared:ro"]

        with (
            patch("mcp_service.load_config", return_value=config),
            patch("mcp_adapters.extract_host_mounts", side_effect=fake_extract),
            patch("container_service.ensure_container") as ensure_container,
            patch("container_service.stop_container_process"),
            patch("mcp_service.fetch_tools", new=MagicMock(return_value=object())),
            patch("mcp_service.run_async", return_value=[]),
        ):
            resp = client.get("/api/mcp/tools")

        assert resp.status_code == 200
        ensure_container.assert_called_once_with(
            "__mcp_discovery__",
            extra_volumes=[
                "/host/shared:/host/shared:ro",
                "/host/unique:/host/unique:ro",
            ],
        )

    def test_existing_conversation_keeps_real_conversation_id(self, client, tmp_lumen):
        config = {"mcpServers": {"bash": {"command": "bash", "args": []}}}

        def fake_fetch(server_name, server_config, *, conv_id=""):
            return {"server_name": server_name, "conv_id": conv_id}

        def fake_run_async(payload):
            return [{
                "server": payload["server_name"],
                "name": "run",
                "description": "",
                "inputSchema": {},
            }]

        with (
            patch("mcp_service.load_config", return_value=config),
            patch("container_service.ensure_container") as ensure_container,
            patch("container_service.stop_container_process") as stop_container_process,
            patch("mcp_service.fetch_tools", new=MagicMock(side_effect=fake_fetch)) as fetch_tools,
            patch("mcp_service.run_async", side_effect=fake_run_async),
        ):
            resp = client.get("/api/mcp/tools", query_string={"conv_id": "chat-123"})

        assert resp.status_code == 200
        ensure_container.assert_not_called()
        stop_container_process.assert_not_called()
        fetch_tools.assert_called_once_with(
            "bash",
            config["mcpServers"]["bash"],
            conv_id="chat-123",
        )

    def test_skipped_server_reason_is_preserved(self, client, tmp_lumen):
        from mcp_adapters import ContainerConversationRequired

        config = {"mcpServers": {"remote": {"command": "npx", "args": []}}}

        with (
            patch("mcp_service.load_config", return_value=config),
            patch("mcp_adapters.extract_host_mounts", return_value=[]),
            patch("container_service.ensure_container"),
            patch("container_service.stop_container_process") as stop_container_process,
            patch("mcp_service.fetch_tools", new=MagicMock(return_value=object())),
            patch(
                "mcp_service.run_async",
                side_effect=ContainerConversationRequired("needs a conversation"),
            ),
        ):
            resp = client.get("/api/mcp/tools")

        assert resp.status_code == 200
        assert resp.json == {
            "tools": [],
            "skipped": [{"server": "remote", "reason": "needs a conversation"}],
        }
        stop_container_process.assert_called_once_with("__mcp_discovery__")
