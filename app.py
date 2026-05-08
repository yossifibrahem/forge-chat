"""
Lumen Chatbot — Flask entry point.

Wires together the app factory, CORS, and the single Blueprint
that owns all routes.  On startup, Docker availability and the
sandbox image are validated (both are required), then stale
containers from previous runs are cleaned up.
"""
import logging
import subprocess
import sys

from flask import Flask
from flask_cors import CORS

from routes import blueprint
import container_service

log = logging.getLogger(__name__)


def create_app() -> Flask:
    _require_docker()
    _require_sandbox_image()
    app = Flask(__name__)
    CORS(app)
    app.register_blueprint(blueprint)
    _cleanup_stale_containers()
    return app


def _require_docker() -> None:
    """Abort startup if the Docker daemon is unreachable."""
    result = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.error(
            "[startup] Docker is not available. "
            "Lumen requires Docker to run MCP servers.\n%s",
            result.stderr.strip(),
        )
        sys.exit(1)


def _require_sandbox_image() -> None:
    """Abort startup if the lumen-sandbox image has not been built."""
    image = container_service.SANDBOX_IMAGE
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.error(
            "[startup] Sandbox image '%s' not found. "
            "Build it first:\n\n    docker build -f Dockerfile.sandbox -t %s .\n",
            image,
            image,
        )
        sys.exit(1)
    log.info("[startup] sandbox image '%s' is present", image)


def _cleanup_stale_containers() -> None:
    """Remove lumen-chat-* Docker containers whose conversation no longer exists."""
    try:
        import store
        known_ids = [c["id"] for c in store.list_all()]
        removed = container_service.cleanup_stale(known_ids)
        if removed:
            log.info("[startup] removed %d stale container(s): %s", len(removed), removed)
    except Exception as exc:
        log.warning("[startup] stale container cleanup skipped: %s", exc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    create_app().run(debug=True, host="0.0.0.0", port=8080, threaded=True)
