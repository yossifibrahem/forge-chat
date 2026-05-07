"""
Routes — one Blueprint containing all HTTP handlers.

Each handler is intentionally thin: parse the request, call a service
module, and return JSON.  No business logic lives here.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
import time
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

# Server-owned turns keep running even if the browser reloads or disconnects.
# Each entry stores replayable stream events for the currently connected client
# and writes snapshots to the conversation file as the turn progresses.
_active_streams: dict[str, dict] = {}


def _stream_state(stream_id: str, conv_id: str = "") -> dict:
    state = _active_streams.get(stream_id)
    if state:
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





# ── Workspace file browser ───────────────────────────────────────────────────

_TEXT_EXTENSIONS = {
    ".bash", ".bat", ".c", ".cfg", ".conf", ".cpp", ".cs", ".css", ".csv",
    ".dockerfile", ".env", ".go", ".h", ".hpp", ".htm", ".html", ".ini",
    ".java", ".js", ".json", ".jsx", ".log", ".lua", ".md", ".mjs",
    ".php", ".properties", ".py", ".rb", ".rs", ".sh", ".sql", ".svg",
    ".toml", ".ts", ".tsx", ".txt", ".xml", ".yaml", ".yml",
}
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


_MAX_PREVIEW_BYTES = _env_int("LUMEN_MAX_FILE_PREVIEW_BYTES", 512 * 1024)
_MAX_LIST_ENTRIES = _env_int("LUMEN_MAX_FILE_LIST_ENTRIES", 500)


def _workspace_root(conv_id: str) -> Path:
    return store.working_directory(conv_id).resolve()


def _workspace_relpath(path_value: str | None) -> str:
    raw = (path_value or "").strip().replace("\\", "/")
    if raw in {"", ".", "/", "/workspace"}:
        return ""
    if raw.startswith("/workspace/"):
        raw = raw[len("/workspace/"):]
    elif raw.startswith("/"):
        raise ValueError("Only /workspace paths are available")
    parts = [part for part in raw.split("/") if part and part != "."]
    if any(part == ".." for part in parts):
        raise ValueError("Parent path traversal is not allowed")
    return "/".join(parts)


def _resolve_workspace_path(conv_id: str, path_value: str | None) -> tuple[Path, str]:
    root = _workspace_root(conv_id)
    rel = _workspace_relpath(path_value)
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Path escapes the workspace")
    return target, rel


def _workspace_path(rel: str) -> str:
    return "/workspace" + (f"/{rel}" if rel else "")


def _parent_workspace_path(rel: str) -> str | None:
    if not rel:
        return None
    parent = Path(rel).parent.as_posix()
    return _workspace_path("" if parent == "." else parent)


def _is_text_file(path: Path) -> bool:
    if path.suffix.lower() in _TEXT_EXTENSIONS:
        return True
    mime, _ = mimetypes.guess_type(path.name)
    return bool(mime and (mime.startswith("text/") or mime in {
        "application/json", "application/javascript", "application/xml", "application/xhtml+xml",
    }))


def _file_entry(path: Path, root: Path) -> dict:
    stat = path.stat()
    rel = path.relative_to(root).as_posix()
    is_dir = path.is_dir()
    return {
        "name": path.name,
        "path": _workspace_path(rel),
        "relative_path": rel,
        "type": "directory" if is_dir else "file",
        "size": None if is_dir else stat.st_size,
        "modified": stat.st_mtime,
        "previewable": (not is_dir) and _is_text_file(path) and stat.st_size <= _MAX_PREVIEW_BYTES,
    }


def _list_workspace_dir(conv_id: str, path_value: str | None) -> tuple[dict, int]:
    if not store.load(conv_id):
        return {"error": "Conversation not found"}, 404
    try:
        target, rel = _resolve_workspace_path(conv_id, path_value)
    except ValueError as exc:
        return {"error": str(exc)}, 400
    if not target.exists():
        return {"error": "Path not found"}, 404
    if not target.is_dir():
        return {"error": "Path is not a directory"}, 400

    root = _workspace_root(conv_id)
    entries = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if len(entries) >= _MAX_LIST_ENTRIES:
            break
        entries.append(_file_entry(child, root))

    return {
        "path": _workspace_path(rel),
        "relative_path": rel,
        "parent": _parent_workspace_path(rel),
        "entries": entries,
        "limit": _MAX_LIST_ENTRIES,
        "truncated": len(entries) >= _MAX_LIST_ENTRIES,
    }, 200


def _read_workspace_file(conv_id: str, path_value: str | None) -> tuple[dict, int]:
    if not store.load(conv_id):
        return {"error": "Conversation not found"}, 404
    try:
        target, rel = _resolve_workspace_path(conv_id, path_value)
    except ValueError as exc:
        return {"error": str(exc)}, 400
    if not target.exists():
        return {"error": "File not found"}, 404
    if not target.is_file():
        return {"error": "Path is not a file"}, 400

    stat = target.stat()
    previewable = _is_text_file(target) and stat.st_size <= _MAX_PREVIEW_BYTES
    mime, _ = mimetypes.guess_type(target.name)
    data = {
        **_file_entry(target, _workspace_root(conv_id)),
        "mime_type": mime or "application/octet-stream",
    }
    if not previewable:
        data.update({"previewable": False, "content": None})
        return data, 200

    raw = target.read_bytes()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("utf-8", errors="replace")
    data.update({"previewable": True, "content": content})
    return data, 200

# ── Container file uploads ────────────────────────────────────────────────────

_SAFE_UPLOAD_NAME = re.compile(r"[^A-Za-z0-9._ -]+")
_MAX_UPLOAD_BYTES = _env_int("LUMEN_MAX_UPLOAD_BYTES", 50 * 1024 * 1024)


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


@blueprint.route("/api/conversations/<conv_id>/files", methods=["GET", "POST"])
def conversation_files(conv_id: str):
    """List or save files in the conversation workspace mounted at /workspace."""
    if request.method == "GET":
        payload, status = _list_workspace_dir(conv_id, request.args.get("path", ""))
        return jsonify(payload), status

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


@blueprint.route("/api/conversations/<conv_id>/files/content", methods=["GET"])
def get_conversation_file_content(conv_id: str):
    payload, status = _read_workspace_file(conv_id, request.args.get("path", ""))
    return jsonify(payload), status


@blueprint.route("/api/conversations/<conv_id>/files/download", methods=["GET"])
def download_conversation_file(conv_id: str):
    if not store.load(conv_id):
        return jsonify({"error": "Conversation not found"}), 404
    try:
        target, _ = _resolve_workspace_path(conv_id, request.args.get("path", ""))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not target.exists() or not target.is_file():
        return jsonify({"error": "File not found"}), 404
    return send_file(target, as_attachment=True, download_name=target.name)

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



# ── Chat ──────────────────────────────────────────────────────────────────────

@blueprint.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    body = _body()
    stream_id = body.get("stream_id") or str(uuid.uuid4())
    conv_id = body.get("conv_id", "")
    attach_only = bool(body.get("attach"))

    # Re-joining a live stream must never create a new empty backend turn.
    # If the stream no longer exists, let the client simply show the saved
    # conversation state instead of starting a duplicate worker that can
    # overwrite messages/title/tools with an empty payload.
    if attach_only and stream_id not in _active_streams:
        return jsonify({"error": "Stream not found"}), 404

    cancel_event = _cancel_events.setdefault(stream_id, threading.Event())
    state = _stream_state(stream_id, conv_id)

    if not attach_only:
        with state["lock"]:
            if not state["started"]:
                state["started"] = True
                threading.Thread(
                    target=_run_persistent_chat_turn,
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


def _parse_stream_payload(raw_event: str) -> dict | None:
    raw_event = raw_event.strip()
    if not raw_event.startswith("data: "):
        return None
    payload = raw_event[6:].strip()
    if payload == "[DONE]":
        return {"type": "done"}
    try:
        return json.loads(payload)
    except Exception:
        return None


def _save_turn(conv_id: str, title: str, messages: list, display_log: list, *, stream_id: str = "") -> None:
    if not conv_id:
        return
    data = store.load(conv_id) or {"id": conv_id, "created_at": ""}
    data.update({
        "title": title or data.get("title") or "Untitled",
        "messages": messages,
        "displayLog": display_log,
        "streaming": bool(stream_id),
        "working_directory": str(store.working_directory(conv_id)),
    })
    if stream_id:
        data["active_stream_id"] = stream_id
    else:
        data.pop("active_stream_id", None)
    store.save(conv_id, data)


def _log_with_partial(base_log: list, reasoning: str, text: str) -> list:
    return [
        *base_log,
        *([{"type": "thinking", "content": reasoning}] if reasoning else []),
        *([{"type": "message", "role": "assistant", "content": text}] if text else []),
    ]


def _tool_meta_by_name(body: dict) -> dict:
    return {tool.get("name"): tool for tool in body.get("mcp_tool_meta", []) if tool.get("name")}


def _tool_call_message(calls: list, content: str | None) -> dict:
    return {
        "role": "assistant",
        "content": content or None,
        "tool_calls": [
            {
                "id": call.get("id"),
                "type": "function",
                "function": {
                    "name": call.get("function", {}).get("name", ""),
                    "arguments": call.get("function", {}).get("arguments", "{}"),
                },
            }
            for call in calls
        ],
    }


def _safe_tool_args(raw_args: str) -> dict:
    try:
        return json.loads(raw_args or "{}")
    except Exception:
        return {}


def _run_mcp_call(conv_id: str, tool_meta: dict, call: dict) -> tuple[dict, str]:
    name = call.get("function", {}).get("name", "")
    args = _safe_tool_args(call.get("function", {}).get("arguments", "{}"))
    server_name = tool_meta.get("server", "")
    server_config = mcp_service.find_server(server_name)
    if not server_config:
        return args, f"Error calling tool '{name}': MCP server '{server_name}' not found"
    try:
        result = mcp_service.run_async(
            mcp_service.invoke_tool(
                server_name,
                server_config,
                name,
                args,
                working_dir=str(store.working_directory(conv_id)) if conv_id else None,
                conv_id=conv_id,
            )
        )
    except ContainerConversationRequired as exc:
        result = str(exc)
    except Exception as exc:
        result = f"Error calling tool '{name}': {exc}"
    return args, result


def _generate_title_for_turn(body: dict, messages: list) -> str | None:
    try:
        response = _openai_client(body).chat.completions.create(
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
                {"role": "user", "content": _messages_to_text(messages[:4])},
            ],
            tools=[_SET_TITLE_TOOL],
            tool_choice="required",
            max_tokens=256,
            temperature=0.7,
        )
        return _extract_title(response.choices[0].message)
    except Exception:
        return None


def _run_persistent_chat_turn(state: dict, body: dict, cancel_event: threading.Event) -> None:
    stream_id = state["stream_id"]
    conv_id = body.get("conv_id", "")
    title = body.get("title") or "Untitled"
    turn_messages = list(body.get("conversation_messages") or [])
    display_log = list(body.get("display_log") or [])
    api_messages = list(body.get("messages") or [])
    tool_meta = _tool_meta_by_name(body)
    is_first_message = len([m for m in turn_messages if m.get("role") == "user"]) == 1
    client = _openai_client(body)

    last_snapshot = {"at": 0.0, "size": -1}

    def save_active(base_log: list, reasoning: str = "", text: str = "", *, force: bool = False) -> None:
        # Persist enough state for reload recovery without writing the whole
        # conversation JSON for every token. Final/tool snapshots still force-save.
        now = time.monotonic()
        size = len(reasoning) + len(text) + len(base_log)
        if not force and now - last_snapshot["at"] < 0.75 and size - last_snapshot["size"] < 512:
            return
        last_snapshot.update({"at": now, "size": size})
        _save_turn(conv_id, title, turn_messages, _log_with_partial(base_log, reasoning, text), stream_id=stream_id)

    base_log = list(display_log)
    save_active(base_log, force=True)
    assistant_completed = False

    def finalize_partial_answer(reasoning: str, text: str) -> bool:
        """Append the current assistant chunk to the saved turn once.

        This is used for both normal completion and user cancellation so the
        final snapshot never erases text that was already streamed to the UI.
        """
        nonlocal assistant_completed
        if assistant_completed:
            return False
        if reasoning:
            base_log.append({"type": "thinking", "content": reasoning})
        if text:
            base_log.append({"type": "message", "role": "assistant", "content": text})
            turn_messages.append({"role": "assistant", "content": text})
        assistant_completed = bool(reasoning or text)
        return assistant_completed

    try:
        while not cancel_event.is_set():
            acc_text = ""
            acc_reasoning = ""
            tool_calls = []

            for raw in stream_module.stream_chat_completion(
                client,
                model=body.get("model", "gpt-4o"),
                messages=api_messages,
                tools=body.get("tools", []),
                cancel_event=cancel_event,
            ):
                event = _parse_stream_payload(raw)
                if not event:
                    continue
                etype = event.get("type")
                if etype == "done":
                    break
                if etype == "tool_calls":
                    tool_calls = event.get("calls") or []
                    continue

                if etype == "reasoning":
                    acc_reasoning += event.get("content", "")
                    save_active(base_log, acc_reasoning, acc_text)
                elif etype == "text":
                    acc_text += event.get("content", "")
                    save_active(base_log, acc_reasoning, acc_text)

                _publish_stream_event(state, event)

            if cancel_event.is_set():
                if finalize_partial_answer(acc_reasoning, acc_text):
                    save_active(base_log, force=True)
                break

            if tool_calls:
                if acc_reasoning:
                    base_log.append({"type": "thinking", "content": acc_reasoning})
                if acc_text:
                    base_log.append({"type": "message", "role": "assistant", "content": acc_text})
                turn_messages.append(_tool_call_message(tool_calls, acc_text or None))
                api_messages.append(_tool_call_message(tool_calls, acc_text or None))

                for call in tool_calls:
                    name = call.get("function", {}).get("name", "")
                    meta = tool_meta.get(name, {})
                    args, result = _run_mcp_call(conv_id, meta, call)
                    display_name = args.get("description") or name
                    event = {
                        "type": "tool_result",
                        "name": name,
                        "displayName": display_name,
                        "args": args,
                        "result": result,
                    }
                    base_log.append({"type": "tool_result", **{k: v for k, v in event.items() if k != "type"}})
                    turn_messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": result})
                    api_messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": result})
                    save_active(base_log, force=True)
                    _publish_stream_event(state, event)
                continue

            finalize_partial_answer(acc_reasoning, acc_text)

            # Persist the completed assistant answer while the stream is still
            # active. If the user reloads during slower post-processing, the
            # saved conversation already contains the finished response.
            save_active(base_log, force=True)

            # Let the browser finalize the visible assistant bubble immediately.
            # Title generation can take another model call; copy/regenerate must
            # not wait for that slower cosmetic step.
            _publish_stream_event(state, {
                "type": "assistant_done",
                "messages": turn_messages,
                "displayLog": base_log,
            })
            break

        if assistant_completed and is_first_message and not cancel_event.is_set():
            generated_title = _generate_title_for_turn(body, turn_messages)
            if generated_title:
                title = generated_title
                _publish_stream_event(state, {"type": "title", "title": title})
                save_active(base_log, force=True)

        _save_turn(conv_id, title, turn_messages, base_log)
    except Exception as exc:
        _publish_stream_event(state, {"type": "error", "message": str(exc)})
        _save_turn(conv_id, title, turn_messages, base_log)
    finally:
        _cancel_events.pop(stream_id, None)
        _finish_stream_state(state)


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