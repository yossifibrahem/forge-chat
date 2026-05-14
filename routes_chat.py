"""Chat streaming, cancel, approve, settings, and models routes."""
from __future__ import annotations

import threading
import uuid

from flask import Blueprint, jsonify, request

import app_config
import advanced_config
import chat_turn_service
import streaming as stream_module

blueprint = Blueprint("chat", __name__)

# stream_id -> cancellation event for POST /api/chat/cancel
_cancel_events: dict[str, threading.Event] = {}

# stream_id -> replayable state for reconnect/reload while a backend turn is active
_active_streams: dict[str, dict] = {}


def _body() -> dict:
    return request.get_json(silent=True) or {}


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


def _run_chat_turn(state: dict, body: dict, cancel_event: threading.Event) -> None:
    stream_id = state["stream_id"]
    publish = lambda payload: _publish_stream_event(state, payload)
    try:
        chat_turn_service.run_persistent_chat_turn(body, cancel_event, stream_id, publish)
    finally:
        _cancel_events.pop(stream_id, None)
        _finish_stream_state(state)


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


@blueprint.route("/api/settings", methods=["GET"])
def get_api_settings():
    return jsonify(app_config.public_config())


@blueprint.route("/api/settings", methods=["POST"])
def save_api_settings():
    try:
        return jsonify(app_config.save_config(_body()))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@blueprint.route("/api/advanced-settings", methods=["GET"])
def get_advanced_settings():
    return jsonify(advanced_config.public_advanced_config())


@blueprint.route("/api/advanced-settings", methods=["POST"])
def save_advanced_settings():
    try:
        return jsonify(advanced_config.save_advanced_config(_body()))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@blueprint.route("/api/models", methods=["POST"])
def fetch_models():
    try:
        models = sorted(m.id for m in chat_turn_service.openai_client(_body()).models.list())
        return jsonify({"models": models})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
