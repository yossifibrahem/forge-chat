"""
Lumen Chatbot — Flask entry point.

Wires together the app factory, CORS, and the single Blueprint
that owns all routes.  On startup, Docker availability and the
sandbox image are validated (both are required), then stale
containers from previous runs are cleaned up.
"""
import atexit
import logging
import signal
import subprocess
import os
import sys

from flask import Flask
from flask_cors import CORS

from routes import blueprint
import container_service

log = logging.getLogger(__name__)

# Track whether we have already registered the shutdown handler so that
# multiple create_app() calls in tests do not stack duplicate registrations.
_shutdown_registered = False
_shutdown_done = False


def create_app() -> Flask:
    _require_docker()
    _require_sandbox_image()
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("LUMEN_MAX_CONTENT_LENGTH", str(60 * 1024 * 1024)))
    allowed_origins = [
        origin.strip()
        for origin in os.getenv(
            "LUMEN_CORS_ORIGINS",
            "http://localhost:8080,http://127.0.0.1:8080",
        ).split(",")
        if origin.strip()
    ]
    CORS(app, origins=allowed_origins)
    app.register_blueprint(blueprint)
    container_service.start_reaper()
    _cleanup_stale_containers()
    _register_shutdown_cleanup()
    return app


def _register_shutdown_cleanup() -> None:
    """Register container stop hooks for normal exit and SIGTERM.

    ``atexit`` fires on ``sys.exit()`` and ``KeyboardInterrupt`` (Ctrl-C) but
    *not* on ``SIGTERM``.  The explicit ``SIGTERM`` handler covers production
    deployments (gunicorn, systemd, Docker stop) where the process receives
    SIGTERM rather than a keyboard interrupt.
    """
    global _shutdown_registered
    if _shutdown_registered:
        return
    _shutdown_registered = True

    atexit.register(_shutdown_containers)

    original_sigterm = signal.getsignal(signal.SIGTERM)

    def _sigterm_handler(signum, frame):
        _shutdown_containers()
        # Restore the previous handler and re-raise so gunicorn / the shell
        # can observe the signal and perform its own teardown.
        signal.signal(signal.SIGTERM, original_sigterm)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _sigterm_handler)


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


def _shutdown_containers() -> None:
    """Kill all running lumen-chat-* containers on app shutdown.

    Non-fatal: a failure to reach Docker (e.g. Docker daemon itself was
    stopped) is logged as a warning and does not prevent the process from
    exiting cleanly.  The guard prevents double execution when both the
    SIGTERM handler and atexit fire in the same shutdown sequence.
    """
    global _shutdown_done
    if _shutdown_done:
        return
    _shutdown_done = True
    try:
        stopped = container_service.stop_all_containers()
        if stopped:
            log.info("[shutdown] stopped %d container(s): %s", len(stopped), stopped)
    except Exception as exc:
        log.warning("[shutdown] container stop failed: %s", exc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    create_app().run(debug=True, host="0.0.0.0", port=8080, threaded=True)