"""HTTP routes for Lumen.

Routes stay thin: parse request data, call services, and return HTTP-friendly
responses. Long-running chat and workspace file logic live in dedicated modules.
"""
from __future__ import annotations

import threading
import uuid

from flask import Blueprint, jsonify, render_template, request, send_file

import app_config
import chat_turn_service
import container_service
import mcp_service
import mcp_adapters
from mcp_adapters import ContainerConversationRequired
import store
import streaming as stream_module
import workspace_service

blueprint = Blueprint("main", __name__)

# stream_id -> cancellation event for POST /api/chat/cancel
_cancel_events: dict[str, threading.Event] = {}

# stream_id -> replayable state for reconnect/reload while a backend turn is active
_active_streams: dict[str, dict] = {}


def _stream_state(stream_id: str, conv_id: str = "") -> dict:
    if state := _active_streams.get(stream_id):
        return state
    state = {
        "stream_id": stream_id,
        "conv_id": conv_id,
        "events": [],
        "done": False,
        "started": False,
        "lock": threading.Lock(),
        "condition": threading.Condition(threading.Lock()),
    }
    _active_streams[stream_id] = state
    return state


def _publish_stream_event(state: dict, payload: dict) -> None:
    with state["condition"]:
        state["events"].append(payload)
        state["condition"].notify_all()


def _finish_stream_state(state: dict) -> None:
    with state["condition"]:
        state["done"] = True
        state["condition"].notify_all()
    _active_streams.pop(state.get("stream_id"), None)


def _body() -> dict:
    return request.get_json(silent=True) or {}


def _json_result(result: tuple[dict, int]):
    payload, status = result
    return jsonify(payload), status


# ── UI ────────────────────────────────────────────────────────────────────────

@blueprint.route("/")
def index():
    return render_template("index.html")


# ── Conversations ─────────────────────────────────────────────────────────────

@blueprint.route("/api/conversations", methods=["GET"])
def list_conversations():
    return jsonify(store.list_all())


@blueprint.route("/api/conversations", methods=["POST"])
def create_conversation():
    return jsonify(store.create(_body().get("title", "New Conversation"))), 201


@blueprint.route("/api/conversations/<conv_id>", methods=["GET"])
def get_conversation(conv_id: str):
    data = store.load(conv_id)
    if not data:
        return jsonify({"error": "Not found"}), 404
    data.setdefault("working_directory", str(store.working_directory(conv_id)))
    return jsonify(data)


@blueprint.route("/api/conversations/<conv_id>/workspace", methods=["GET"])
def get_conversation_workspace(conv_id: str):
    return jsonify({"working_directory": str(store.working_directory(conv_id))})


@blueprint.route("/api/conversations/<conv_id>/container", methods=["GET"])
def get_container_status(conv_id: str):
    return jsonify({
        "conv_id": conv_id,
        "container_name": container_service.container_name(conv_id),
        "status": container_service.get_status(conv_id),
        "workspace": str(store.working_directory(conv_id)),
    })


@blueprint.route("/api/conversations/<conv_id>", methods=["PUT"])
def update_conversation(conv_id: str):
    allowed_fields = {"title", "system_prompt"}
    body = _body()
    data = store.load(conv_id) or {"id": conv_id}
    for key in allowed_fields:
        if key in body:
            data[key] = body[key]
    data["id"] = conv_id
    return jsonify(store.save(conv_id, data))


@blueprint.route("/api/conversations/<conv_id>", methods=["DELETE"])
def delete_conversation(conv_id: str):
    if not store.delete(conv_id):
        return jsonify({"error": "Not found"}), 404
    container_service.stop_container(conv_id)
    container_service.delete_workspace(conv_id)
    return jsonify({"ok": True})


# ── MCP ───────────────────────────────────────────────────────────────────────

@blueprint.route("/api/mcp/config", methods=["GET"])
def get_mcp_config():
    return jsonify(mcp_service.load_config())


@blueprint.route("/api/mcp/config", methods=["POST"])
def save_mcp_config():
    try:
        mcp_service.save_config(_body())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True})


@blueprint.route("/api/mcp/tools", methods=["GET"])
def list_mcp_tools():
    requested_conv_id = request.args.get("conv_id", "")
    conv_id = requested_conv_id or container_service.DISCOVERY_CONTAINER_ID
    tools: list[dict] = []
    skipped: list[dict] = []
    discovery_mode = not requested_conv_id

    configs = mcp_service.load_config().get("mcpServers", {})
    if discovery_mode and configs:
        all_volumes: list[str] = []
        seen: set[str] = set()
        for cfg in configs.values():
            for volume in mcp_adapters.extract_host_mounts(cfg):
                if volume not in seen:
                    seen.add(volume)
                    all_volumes.append(volume)
        container_service.ensure_container(conv_id, extra_volumes=all_volumes)

    try:
        for name, cfg in configs.items():
            try:
                tools.extend(mcp_service.run_async(mcp_service.fetch_tools(name, cfg, conv_id=conv_id)))
            except ContainerConversationRequired as exc:
                skipped.append({"server": name, "reason": str(exc)})
    finally:
        if discovery_mode:
            container_service.stop_container_process(conv_id)

    return jsonify({"tools": tools, "skipped": skipped} if skipped else tools)


@blueprint.route("/api/mcp/call", methods=["POST"])
def call_mcp_tool():
    body = _body()
    server_name = body.get("server", "")
    server_config = mcp_service.find_server(server_name)
    if not server_config:
        return jsonify({"error": f"MCP server '{server_name}' not found"}), 404

    conv_id = body.get("conv_id", "")
    try:
        result = mcp_service.run_async(mcp_service.invoke_tool(
            server_name,
            server_config,
            body.get("tool", ""),
            body.get("arguments", {}),
            conv_id=conv_id,
        ))
    except ContainerConversationRequired as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"result": result})


# ── Workspace files ───────────────────────────────────────────────────────────

@blueprint.route("/api/conversations/<conv_id>/files", methods=["GET", "POST"])
def conversation_files(conv_id: str):
    if request.method == "GET":
        return _json_result(workspace_service.list_dir(conv_id, request.args.get("path", "")))

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files uploaded"}), 400
    return _json_result(workspace_service.save_uploads(conv_id, files))


@blueprint.route("/api/conversations/<conv_id>/files/content", methods=["GET"])
def get_conversation_file_content(conv_id: str):
    return _json_result(workspace_service.read_file(conv_id, request.args.get("path", "")))


@blueprint.route("/api/conversations/<conv_id>/files/download", methods=["GET"])
def download_conversation_file(conv_id: str):
    if not store.load(conv_id):
        return jsonify({"error": "Conversation not found"}), 404
    try:
        target, _ = workspace_service.resolve_workspace_path(conv_id, request.args.get("path", ""))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not target.exists() or not target.is_file():
        return jsonify({"error": "File not found"}), 404
    return send_file(target, as_attachment=True, download_name=target.name)


# ── Images ────────────────────────────────────────────────────────────────────

@blueprint.route("/api/images", methods=["POST"])
def upload_image():
    body = _body()
    try:
        name = store.save_image(body.get("data", ""), body.get("media_type", "image/png"))
        return jsonify({"ref": name, "url": f"/api/images/{name}"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@blueprint.route("/api/images/<name>", methods=["GET"])
def serve_image(name: str):
    path = store.get_image_path(name)
    if not path:
        return jsonify({"error": "Not found"}), 404
    ext = name.rsplit(".", 1)[-1]
    return send_file(path, mimetype=f"image/{'jpeg' if ext == 'jpeg' else ext}")


# ── Chat ──────────────────────────────────────────────────────────────────────

@blueprint.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    body = _body()
    stream_id = body.get("stream_id") or str(uuid.uuid4())
    conv_id = body.get("conv_id", "")
    attach_only = bool(body.get("attach"))

    if attach_only and stream_id not in _active_streams:
        return jsonify({"error": "Stream not found"}), 404

    cancel_event = _cancel_events.setdefault(stream_id, threading.Event())
    state = _stream_state(stream_id, conv_id)

    if not attach_only:
        with state["lock"]:
            if not state["started"]:
                state["started"] = True
                threading.Thread(
                    target=_run_chat_turn,
                    args=(state, body, cancel_event),
                    daemon=True,
                ).start()

    def event_stream():
        cursor = 0
        while True:
            with state["condition"]:
                while cursor >= len(state["events"]) and not state["done"]:
                    state["condition"].wait(timeout=15)
                pending = state["events"][cursor:]
                cursor += len(pending)
                done = state["done"] and cursor >= len(state["events"])

            for payload in pending:
                yield stream_module.sse_event(payload)
            if done:
                yield "data: [DONE]\n\n"
                break

    return stream_module.make_streaming_response(event_stream())


def _run_chat_turn(state: dict, body: dict, cancel_event: threading.Event) -> None:
    stream_id = state["stream_id"]
    publish = lambda payload: _publish_stream_event(state, payload)
    try:
        chat_turn_service.run_persistent_chat_turn(body, cancel_event, stream_id, publish)
    finally:
        _cancel_events.pop(stream_id, None)
        _finish_stream_state(state)


@blueprint.route("/api/chat/cancel", methods=["POST"])
def chat_cancel():
    stream_id = _body().get("stream_id", "")
    event = _cancel_events.get(stream_id)
    if not event:
        return jsonify({"ok": False, "reason": "stream not found"}), 404
    event.set()
    return jsonify({"ok": True})


@blueprint.route("/api/chat/approve", methods=["POST"])
def chat_approve():
    body = _body()
    stream_id = body.get("stream_id", "")
    call_id = body.get("call_id", "")
    approved = bool(body.get("approved", False))
    chat_turn_service.resolve_tool_approval(stream_id, call_id, approved)
    return jsonify({"ok": True})


# ── API provider settings ─────────────────────────────────────────────────────

@blueprint.route("/api/settings", methods=["GET"])
def get_api_settings():
    return jsonify(app_config.public_config())


@blueprint.route("/api/settings", methods=["POST"])
def save_api_settings():
    try:
        return jsonify(app_config.save_config(_body()))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


# ── Models ────────────────────────────────────────────────────────────────────

@blueprint.route("/api/models", methods=["POST"])
def fetch_models():
    try:
        models = sorted(m.id for m in chat_turn_service.openai_client(_body()).models.list())
        return jsonify({"models": models})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
