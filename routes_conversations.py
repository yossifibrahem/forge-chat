"""Conversation CRUD routes."""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

import container_service
import store

blueprint = Blueprint("conversations", __name__)


def _body() -> dict:
    return request.get_json(silent=True) or {}


def _bad_conv_id(conv_id: str):
    import re
    _UUID_RE = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        re.IGNORECASE,
    )
    if not _UUID_RE.match(conv_id):
        return jsonify({"error": "Not found"}), 404
    return None


@blueprint.route("/")
def index():
    return render_template("index.html")


@blueprint.route("/health")
def health():
    """Minimal liveness probe for container orchestrators and load balancers."""
    return jsonify({"ok": True})


@blueprint.route("/api/conversations", methods=["GET"])
def list_conversations():
    return jsonify(store.list_all())


@blueprint.route("/api/conversations", methods=["POST"])
def create_conversation():
    return jsonify(store.create(_body().get("title", "New Conversation"))), 201


@blueprint.route("/api/conversations/<conv_id>", methods=["GET"])
def get_conversation(conv_id: str):
    if err := _bad_conv_id(conv_id):
        return err
    data = store.load(conv_id)
    if not data:
        return jsonify({"error": "Not found"}), 404
    data.setdefault("working_directory", str(store.working_directory(conv_id)))
    return jsonify(data)


@blueprint.route("/api/conversations/<conv_id>/workspace", methods=["GET"])
def get_conversation_workspace(conv_id: str):
    if err := _bad_conv_id(conv_id):
        return err
    return jsonify({"working_directory": str(store.working_directory(conv_id))})


@blueprint.route("/api/conversations/<conv_id>/container", methods=["GET"])
def get_container_status(conv_id: str):
    if err := _bad_conv_id(conv_id):
        return err
    return jsonify({
        "conv_id": conv_id,
        "container_name": container_service.container_name(conv_id),
        "status": container_service.get_status(conv_id),
        "workspace": str(store.working_directory(conv_id)),
    })


@blueprint.route("/api/conversations/<conv_id>", methods=["PUT"])
def update_conversation(conv_id: str):
    if err := _bad_conv_id(conv_id):
        return err
    allowed_fields = {"title", "system_prompt"}
    body = _body()
    data = store.load(conv_id)
    if data is None:
        return jsonify({"error": "Not found"}), 404
    for key in allowed_fields:
        if key in body:
            data[key] = body[key]
    data["id"] = conv_id
    return jsonify(store.save(conv_id, data))


@blueprint.route("/api/conversations/<conv_id>", methods=["DELETE"])
def delete_conversation(conv_id: str):
    if err := _bad_conv_id(conv_id):
        return err
    if not store.delete(conv_id):
        return jsonify({"error": "Not found"}), 404
    container_service.stop_container(conv_id)
    container_service.delete_workspace(conv_id)
    return jsonify({"ok": True})


@blueprint.route("/api/danger/delete-all", methods=["POST"])
def danger_delete_all():
    """Delete every conversation, its container, and its workspace directory."""
    conversations = store.list_all()
    errors = []
    for conv in conversations:
        conv_id = conv.get("id")
        if not conv_id:
            continue
        try:
            store.delete(conv_id)
            container_service.stop_container(conv_id)
            container_service.delete_workspace(conv_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{conv_id}: {exc}")
    if errors:
        return jsonify({"ok": False, "errors": errors}), 500
    return jsonify({"ok": True, "deleted": len(conversations)})
