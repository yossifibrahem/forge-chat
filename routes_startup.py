"""Startup and runtime-environment routes.

Handles Docker availability checks, sandbox image builds, and the setup
screen served before the main app is ready. Kept separate from conversation
routes because these routes are about the host environment, not user data.

Routes
------
GET  /                                      – app shell or setup screen
GET  /health                                – liveness probe
GET  /api/startup/requirements              – current requirement status (JSON)
POST /api/startup/build-sandbox-image       – blocking build (JSON result)
GET  /api/startup/build-sandbox-image/stream – streaming build log (SSE)
"""
from __future__ import annotations

import json

from flask import Blueprint, Response, jsonify, render_template, stream_with_context

import runtime_requirements

blueprint = Blueprint("startup", __name__)


@blueprint.route("/")
def index():
    status = runtime_requirements.check_requirements()
    if not status.ok:
        return render_template("startup_requirements.html", status=status.as_dict())
    return render_template("index.html")


@blueprint.route("/health")
def health():
    """Minimal liveness probe for container orchestrators and load balancers."""
    return jsonify({"ok": True})


@blueprint.route("/api/startup/requirements", methods=["GET"])
def startup_requirements():
    status = runtime_requirements.check_requirements()
    http_status = 200 if status.ok else 503
    return jsonify(status.as_dict()), http_status


@blueprint.route("/api/startup/build-sandbox-image", methods=["POST"])
def build_sandbox_image():
    """Blocking build — kept for programmatic / CLI use."""
    status = runtime_requirements.build_sandbox_image()
    http_status = 200 if status.ok else 500
    if status.code in {"docker_unavailable", "docker_not_running"}:
        http_status = 503
    return jsonify(status.as_dict()), http_status


@blueprint.route("/api/startup/build-sandbox-image/stream", methods=["GET"])
def build_sandbox_image_stream():
    """Stream docker build output line-by-line as SSE.

    Event types emitted:
      log    – one line of docker build stdout/stderr
      done   – build finished successfully; data is a RequirementStatus JSON
      error  – build failed;              data is a RequirementStatus JSON
    """
    def _generate():
        for event, data in runtime_requirements.build_sandbox_image_stream():
            yield f"event: {event}\ndata: {json.dumps(data)}\n\n"

    return Response(
        stream_with_context(_generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )