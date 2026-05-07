"""
Routes — one Blueprint containing all HTTP handlers.

Each handler is intentionally thin: parse the request, call a service
module, and return JSON.  No business logic lives here.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_file
from openai import OpenAI

import container_service
import mcp_service
from mcp_adapters import ContainerConversationRequired
import store
import streaming as stream_module

blueprint = Blueprint("main", __name__)

# Maps stream_id → threading.Event so POST /api/chat/cancel can stop generation.
_cancel_events: dict[str, threading.Event] = {}


# ── Request helpers ───────────────────────────────────────────────────────────

def _body() -> dict:
    return request.get_json(silent=True) or {}


def _openai_client(body: dict) -> OpenAI:
    return OpenAI(
        api_key=body.get("api_key") or "sk-placeholder",
        base_url=body.get("api_base") or "https://api.openai.com/v1",
    )


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
    if data:
        data.setdefault("working_directory", str(store.working_directory(conv_id)))
        return jsonify(data)
    return jsonify({"error": "Not found"}), 404


@blueprint.route("/api/conversations/<conv_id>/workspace", methods=["GET"])
def get_conversation_workspace(conv_id: str):
    return jsonify({"working_directory": str(store.working_directory(conv_id))})


@blueprint.route("/api/conversations/<conv_id>/container", methods=["GET"])
def get_container_status(conv_id: str):
    """Return the Docker container status for this conversation."""
    status = container_service.get_status(conv_id)
    return jsonify({
        "conv_id": conv_id,
        "container_name": container_service.container_name(conv_id),
        "status": status,
        "workspace": str(store.working_directory(conv_id)),
    })


@blueprint.route("/api/conversations/<conv_id>", methods=["PUT"])
def update_conversation(conv_id: str):
    data = store.load(conv_id) or {"id": conv_id}
    data.update(_body())
    data["id"] = conv_id  # guard against accidental id override
    return jsonify(store.save(conv_id, data))


@blueprint.route("/api/conversations/<conv_id>", methods=["DELETE"])
def delete_conversation(conv_id: str):
    ok = store.delete(conv_id)
    if ok:
        container_service.stop_container(conv_id)
        container_service.delete_workspace(conv_id)
        return jsonify({"ok": True})
    return jsonify({"error": "Not found"}), 404


# ── MCP ───────────────────────────────────────────────────────────────────────

@blueprint.route("/api/mcp/config", methods=["GET"])
def get_mcp_config():
    return jsonify(mcp_service.load_config())


@blueprint.route("/api/mcp/config", methods=["POST"])
def save_mcp_config():
    mcp_service.save_config(_body())
    return jsonify({"ok": True})


@blueprint.route("/api/mcp/tools", methods=["GET"])
def list_mcp_tools():
    conv_id = request.args.get("conv_id", "")
    servers = mcp_service.load_config().get("mcpServers", {})
    all_tools: list[dict] = []
    skipped: list[dict] = []

    for name, cfg in servers.items():
        try:
            all_tools.extend(
                mcp_service.run_async(
                    mcp_service.fetch_tools(name, cfg, conv_id=conv_id)
                )
            )
        except ContainerConversationRequired as exc:
            skipped.append({"server": name, "reason": str(exc)})
            continue

    # Keep backward compatibility: the frontend accepts both a raw array and
    # {tools: [...]}. Returning metadata here lets us skip container-only tools
    # gracefully when /api/mcp/tools is called before a chat exists.
    if skipped:
        return jsonify({"tools": all_tools, "skipped": skipped})
    return jsonify(all_tools)


@blueprint.route("/api/mcp/call", methods=["POST"])
def call_mcp_tool():
    body = _body()
    server_name: str = body.get("server", "")
    server_config = mcp_service.find_server(server_name)
    if not server_config:
        return jsonify({"error": f"MCP server '{server_name}' not found"}), 404
    conv_id = body.get("conv_id", "")
    working_dir = str(store.working_directory(conv_id)) if conv_id else None
    try:
        result = mcp_service.run_async(
            mcp_service.invoke_tool(
                server_name,
                server_config,
                body.get("tool", ""),
                body.get("arguments", {}),
                working_dir=working_dir,
                conv_id=conv_id,
            )
        )
    except ContainerConversationRequired as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"result": result})



# ── Container file uploads ────────────────────────────────────────────────────

_SAFE_UPLOAD_NAME = re.compile(r"[^A-Za-z0-9._ -]+")
_MAX_UPLOAD_BYTES = int(os.getenv("LUMEN_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))


def _safe_upload_name(name: str) -> str:
    """Return a filesystem-safe basename while preserving readable filenames."""
    cleaned = _SAFE_UPLOAD_NAME.sub("_", Path(name or "file").name).strip(" ._")
    return cleaned or "file"


def _unique_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate

    stem = candidate.stem or "file"
    suffix = candidate.suffix
    for index in range(1, 1000):
        candidate = directory / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not create a unique filename for {filename!r}")


@blueprint.route("/api/conversations/<conv_id>/files", methods=["POST"])
def upload_conversation_files(conv_id: str):
    """Save uploaded files into the conversation workspace mounted at /workspace."""
    if not store.load(conv_id):
        return jsonify({"error": "Conversation not found"}), 404

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files uploaded"}), 400

    upload_dir = store.working_directory(conv_id) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    saved: list[dict] = []
    for item in files:
        if not item or not item.filename:
            continue

        filename = _safe_upload_name(item.filename)
        target = _unique_path(upload_dir, filename)

        total = 0
        with target.open("wb") as fh:
            while True:
                chunk = item.stream.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_UPLOAD_BYTES:
                    fh.close()
                    target.unlink(missing_ok=True)
                    return jsonify({
                        "error": f"File '{filename}' exceeds the upload limit of {_MAX_UPLOAD_BYTES} bytes"
                    }), 413
                fh.write(chunk)

        saved.append({
            "name": filename,
            "size": total,
            "path": f"/workspace/uploads/{target.name}",
            "host_path": str(target),
        })

    if not saved:
        return jsonify({"error": "No valid files uploaded"}), 400
    return jsonify({"files": saved})

# ── Images ────────────────────────────────────────────────────────────────────

@blueprint.route("/api/images", methods=["POST"])
def upload_image():
    body = _body()
    data_b64   = body.get("data", "")
    media_type = body.get("media_type", "image/png")
    try:
        name = store.save_image(data_b64, media_type)
        return jsonify({"ref": name, "url": f"/api/images/{name}"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@blueprint.route("/api/images/<name>", methods=["GET"])
def serve_image(name: str):
    path = store.get_image_path(name)
    if not path:
        return jsonify({"error": "Not found"}), 404
    ext  = name.rsplit(".", 1)[-1]
    mime = f"image/{'jpeg' if ext == 'jpeg' else ext}"
    return send_file(path, mimetype=mime)


# ── Title generation ──────────────────────────────────────────────────────────

_SET_TITLE_TOOL = {
    "type": "function",
    "function": {
        "name": "set_title",
        "description": "Set the conversation title.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "The conversation title.",
                },
            },
            "required": ["title"],
        },
    },
}


def _messages_to_text(messages: list) -> str:
    """Flatten a message list to a plain role: content string for title prompting."""
    lines = []
    for msg in messages:
        role = msg.get("role", "")
        if role not in {"user", "assistant"}:
            continue
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content if p.get("type") == "text")
        content = content.replace("\n\n", " ").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _extract_title(message) -> str:
    """Extract the title from a completion message.

    Tries three formats in order:
      1. Structured tool_calls (standard OpenAI-compatible response)
      2. JSON inside <tool_call> in reasoning_content  (e.g. qwopus3.5)
      3. XML  inside <tool_call> in reasoning_content  (e.g. qwen3.5)
    """
    if message.tool_calls:
        args = json.loads(message.tool_calls[0].function.arguments)
        return args["title"]

    reasoning = getattr(message, "reasoning_content", "") or ""

    json_match = re.search(r"<tool_call>\s*(\{.*?})\s*</tool_call>", reasoning, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))["arguments"]["title"]

    xml_match = re.search(r"<parameter=title>\s*(.*?)\s*</parameter>", reasoning, re.DOTALL)
    if xml_match:
        return xml_match.group(1).strip()

    raise ValueError("Model did not return a tool call")


@blueprint.route("/api/generate-title", methods=["POST"])
def generate_title():
    body   = _body()
    client = _openai_client(body)
    try:
        response = client.chat.completions.create(
            model=body.get("model", "gpt-4o"),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Call set_title with a 2–5 word Title Case title for this conversation.\n"
                        "The title must name the specific subject, not describe the interaction.\n\n"
                        "Good: 'Fibonacci Sequence in Python', 'Docker Volume Permissions', 'JWT Token Expiry Bug'\n"
                        "Bad: 'Coding Help' (too vague), 'Asking About Docker' (action not topic), 'General Question' (meaningless)"
                    ),
                },
                {"role": "user", "content": _messages_to_text(body.get("messages", []))},
            ],
            tools=[_SET_TITLE_TOOL],
            tool_choice="required",
            max_tokens=256,
            temperature=0.7,
        )
        return jsonify({"title": _extract_title(response.choices[0].message)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


# ── Chat ──────────────────────────────────────────────────────────────────────

@blueprint.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    body = _body()
    client    = _openai_client(body)
    stream_id = body.get("stream_id") or str(uuid.uuid4())

    cancel_event = threading.Event()
    _cancel_events[stream_id] = cancel_event

    def generator_with_cleanup():
        try:
            yield from stream_module.stream_chat_completion(
                client,
                model=body.get("model", "gpt-4o"),
                messages=body.get("messages", []),
                tools=body.get("tools", []),
                cancel_event=cancel_event,
            )
        finally:
            _cancel_events.pop(stream_id, None)

    return stream_module.make_streaming_response(generator_with_cleanup())


@blueprint.route("/api/chat/cancel", methods=["POST"])
def chat_cancel():
    stream_id = _body().get("stream_id", "")
    event = _cancel_events.get(stream_id)
    if event:
        event.set()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "reason": "stream not found"}), 404


# ── Models ────────────────────────────────────────────────────────────────────

@blueprint.route("/api/models", methods=["POST"])
def fetch_models():
    body = _body()
    try:
        models = sorted(m.id for m in _openai_client(body).models.list())
        return jsonify({"models": models})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400