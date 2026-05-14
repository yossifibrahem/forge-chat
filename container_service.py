"""Docker-backed runtime for per-conversation MCP containers."""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Literal

log = logging.getLogger(__name__)

SANDBOX_IMAGE = os.getenv("LUMEN_SANDBOX_IMAGE", "lumen-sandbox")
CONTAINERS_ROOT = Path(os.path.expanduser(os.getenv("LUMEN_CONTAINERS_ROOT", "~/.lumen/containers")))
CONTAINERS_ROOT.mkdir(parents=True, exist_ok=True)

CONTAINER_MEMORY = os.getenv("LUMEN_CONTAINER_MEMORY", "512m")
CONTAINER_CPUS = os.getenv("LUMEN_CONTAINER_CPUS", "1")
CONTAINER_NETWORK = os.getenv("LUMEN_CONTAINER_NETWORK", "bridge")
CONTAINER_PREFIX = os.getenv("LUMEN_CONTAINER_PREFIX", "lumen-chat-")
DISCOVERY_CONTAINER_ID = "mcp-discovery"
# Seconds of inactivity before a conversation container is stopped.
# Set to 0 to disable idle reaping entirely.
IDLE_TIMEOUT = int(os.getenv("LUMEN_CONTAINER_IDLE_TIMEOUT", "600"))  # default 10 min

ContainerStatus = Literal["running", "stopped", "missing"]

_CONTAINER_LOCKS: dict[str, threading.Lock] = {}
_CONTAINER_LOCKS_GUARD = threading.Lock()

# Last-activity timestamps for idle reaping (conv_id → monotonic seconds).
_last_used: dict[str, float] = {}
_last_used_lock = threading.Lock()

# In-process cache of confirmed-running containers and their mounted volume sources.
# Skips redundant docker-inspect calls when ensure_container is called multiple
# times for the same container within a turn (e.g. once at turn start, then once
# per new MCP server session opened by McpSessionPool._get_session).
_running_cache: dict[str, frozenset] = {}  # conv_id → confirmed mounted extra-volume sources
_running_cache_lock = threading.Lock()


@dataclass(frozen=True)
class ContainerInfo:
    conv_id: str
    name: str
    workspace: Path
    status: ContainerStatus


def _safe_id(conv_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", conv_id or "default")


def container_name(conv_id: str) -> str:
    return f"{CONTAINER_PREFIX}{_safe_id(conv_id)}"


def _container_lock(conv_id: str) -> threading.Lock:
    key = _safe_id(conv_id)
    with _CONTAINER_LOCKS_GUARD:
        return _CONTAINER_LOCKS.setdefault(key, threading.Lock())


def _workspace(conv_id: str) -> Path:
    path = CONTAINERS_ROOT / _safe_id(conv_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


from docker_path_utils import parse_volume_source
import advanced_config as _adv_cfg

# Internal alias kept so the rest of this module can call _volume_source
# without knowing about docker_path_utils.
_volume_source = parse_volume_source


def _get_mounted_sources(name: str) -> set[str]:
    result = _run([
        "docker", "inspect",
        "--format", "{{range .Mounts}}{{.Source}}\n{{end}}",
        name,
    ])
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _volume_args(workspace: Path, extra_volumes: list[str]) -> list[str]:
    specs = [f"{workspace}:/workspace", *extra_volumes]
    return [item for spec in specs for item in ("--volume", spec)]


def get_status(conv_id: str) -> ContainerStatus:
    result = _run(["docker", "inspect", "--format", "{{.State.Status}}", container_name(conv_id)])
    if result.returncode != 0:
        return "missing"
    return "running" if result.stdout.strip() == "running" else "stopped"


def ensure_container(conv_id: str, extra_volumes: list[str] | None = None) -> ContainerInfo:
    """Create/start the chat container, safely serialized per conversation."""
    _touch(conv_id)
    required = frozenset(_volume_source(v) for v in (extra_volumes or []))
    with _running_cache_lock:
        cached = _running_cache.get(conv_id)
    if cached is not None and required <= cached:
        return ContainerInfo(conv_id, container_name(conv_id), _workspace(conv_id), "running")
    with _container_lock(conv_id):
        info = _ensure_container_locked(conv_id, extra_volumes or [])
    if info.status == "running":
        with _running_cache_lock:
            _running_cache[conv_id] = _running_cache.get(conv_id, frozenset()) | required
    return info


def _ensure_container_locked(conv_id: str, extra_volumes: list[str]) -> ContainerInfo:
    name = container_name(conv_id)
    workspace = _workspace(conv_id)
    required_sources = {_volume_source(v) for v in extra_volumes}

    status = get_status(conv_id)
    if status in {"running", "stopped"}:
        missing = required_sources - _get_mounted_sources(name)
        if missing:
            log.info("[container] %s missing volume(s) %s; recreating", name, sorted(missing))
            stop_container(conv_id)
            status = "missing"
        elif status == "stopped":
            _start_existing(name)
            return ContainerInfo(conv_id, name, workspace, "running")
        else:
            return ContainerInfo(conv_id, name, workspace, "running")

    result = _run(_docker_run_command(name, workspace, extra_volumes))
    if result.returncode == 0:
        log.info("[container] created %s (%s)", name, result.stdout.strip()[:12])
        return ContainerInfo(conv_id, name, workspace, "running")

    # Python locks solve same-process races. This handles multi-process Flask or
    # a manual docker run that wins between inspect and create.
    if _is_name_conflict(result.stderr):
        return _reuse_conflicting_container(conv_id, required_sources)

    raise RuntimeError(f"Failed to create container {name}: {result.stderr.strip()}")


def _docker_run_command(name: str, workspace: Path, extra_volumes: list[str]) -> list[str]:
    cfg = _adv_cfg.load_advanced_config()
    return [
        "docker", "run",
        "--detach",
        "--name", name,
        *_volume_args(workspace, extra_volumes),
        "--workdir", "/workspace",
        "--memory", str(cfg["container_memory"]),
        "--cpus",   str(cfg["container_cpus"]),
        "--network", str(cfg["container_network"]),
        "--cap-drop", "ALL",
        "--cap-add", "CHOWN",
        "--cap-add", "DAC_OVERRIDE",
        "--cap-add", "SETUID",
        "--cap-add", "SETGID",
        "--security-opt", "no-new-privileges",
        str(cfg["sandbox_image"]),
    ]


def _start_existing(name: str) -> None:
    log.info("[container] starting stopped container %s", name)
    result = _run(["docker", "start", name])
    if result.returncode != 0:
        raise RuntimeError(f"Failed to start container {name}: {result.stderr.strip()}")


def _is_name_conflict(stderr: str) -> bool:
    text = stderr.lower()
    return "already in use" in text or "conflict" in text


def _reuse_conflicting_container(conv_id: str, required_sources: set[str]) -> ContainerInfo:
    name = container_name(conv_id)
    status = get_status(conv_id)
    if status == "missing":
        raise RuntimeError(f"Container {name} name conflict, but docker inspect cannot find it")

    missing = required_sources - _get_mounted_sources(name)
    if missing:
        raise RuntimeError(
            f"Container {name} already exists but is missing required volume(s): {sorted(missing)}"
        )
    if status == "stopped":
        _start_existing(name)
    log.info("[container] reused concurrently-created %s", name)
    return ContainerInfo(conv_id, name, _workspace(conv_id), "running")


def stop_container_process(conv_id: str) -> None:
    """Stop a running container but keep it available for quick reuse."""
    with _running_cache_lock:
        _running_cache.pop(conv_id, None)
    name = container_name(conv_id)
    if get_status(conv_id) != "running":
        return
    result = _run(["docker", "stop", name])
    if result.returncode != 0:
        log.warning("[container] could not stop %s: %s", name, result.stderr.strip())
    else:
        log.info("[container] stopped %s", name)


def stop_container(conv_id: str) -> None:
    with _running_cache_lock:
        _running_cache.pop(conv_id, None)
    name = container_name(conv_id)
    if get_status(conv_id) == "missing":
        return
    result = _run(["docker", "rm", "-f", name])
    if result.returncode != 0:
        log.warning("[container] could not remove %s: %s", name, result.stderr.strip())
    else:
        log.info("[container] removed %s", name)


def cleanup_stale(known_ids: list[str]) -> list[str]:
    result = _run([
        "docker", "ps", "-a",
        "--filter", f"name={CONTAINER_PREFIX}",
        "--format", "{{.Names}}",
    ])
    if result.returncode != 0:
        log.warning("[container] cleanup skipped: %s", result.stderr.strip())
        return []

    known_names = {container_name(cid) for cid in known_ids}
    known_names.add(container_name(DISCOVERY_CONTAINER_ID))
    removed: list[str] = []
    for name in (line.strip() for line in result.stdout.splitlines()):
        if not name.startswith(CONTAINER_PREFIX) or name in known_names:
            continue
        result = _run(["docker", "rm", "-f", name])
        if result.returncode == 0:
            removed.append(name[len(CONTAINER_PREFIX):])
        else:
            log.warning("[container] could not remove stale %s: %s", name, result.stderr.strip())
    return removed


def wrap_command_for_exec(
    conv_id: str,
    command: str,
    args: list[str],
    *,
    env: Mapping[str, str] | None = None,
) -> tuple[str, list[str]]:
    """Return a docker-exec stdio command for an MCP server process."""
    _touch(conv_id)
    docker_args = ["exec", "-i", "--workdir", "/workspace"]
    for key, value in (env or {}).items():
        docker_args += ["--env", f"{key}={value}"]
    docker_args += [container_name(conv_id), command, *args]
    return "docker", docker_args


def conversation_workspace(conv_id: str) -> Path:
    return _workspace(conv_id)


def delete_workspace(conv_id: str) -> None:
    path = CONTAINERS_ROOT / _safe_id(conv_id)
    if not path.exists():
        return
    if not path.is_dir():
        raise RuntimeError(f"Refusing to delete non-directory workspace: {path}")
    shutil.rmtree(path)
    log.info("[container] deleted workspace %s", path)


def stop_all_containers() -> list[str]:
    """Kill every running lumen-chat-* container.

    Called on app shutdown so containers are not left running indefinitely
    after the process exits.  Uses ``docker kill`` (immediate SIGKILL) rather
    than ``docker stop`` because the sandbox runs ``sleep infinity`` which
    ignores SIGTERM, making the grace period of ``docker stop`` pure wasted
    time.  Containers are left in the stopped state rather than removed so
    that ``ensure_container()`` can restart them quickly on the next launch;
    ``cleanup_stale()`` at startup handles any orphaned ones.
    """
    result = _run([
        "docker", "ps",
        "--filter", f"name={CONTAINER_PREFIX}",
        "--format", "{{.Names}}",
    ])
    if result.returncode != 0:
        log.warning("[container] shutdown cleanup skipped: %s", result.stderr.strip())
        return []

    names = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().startswith(CONTAINER_PREFIX)
    ]
    if not names:
        return []

    print(f"Stopping {len(names)} container(s)...", flush=True)
    r = _run(["docker", "kill", *names])
    if r.returncode == 0:
        log.info("[container] shutdown: killed %s", names)
    else:
        log.warning("[container] shutdown: could not kill containers: %s", r.stderr.strip())
    return names if r.returncode == 0 else []


# ---------------------------------------------------------------------------
# Idle reaper
# ---------------------------------------------------------------------------

def _touch(conv_id: str) -> None:
    """Record that conv_id was just active, resetting its idle clock."""
    with _last_used_lock:
        _last_used[conv_id] = time.monotonic()


def _reap_once() -> None:
    """Stop every conversation container that has been idle beyond the configured timeout.

    The discovery container is intentionally excluded — it is already managed
    by stop_container_process() in the /api/mcp/tools route.
    """
    idle_timeout = _adv_cfg.load_advanced_config()["container_idle_timeout"]
    if idle_timeout <= 0:
        return

    now = time.monotonic()
    with _last_used_lock:
        candidates = [
            (cid, ts) for cid, ts in _last_used.items()
            if cid != DISCOVERY_CONTAINER_ID and (ts <= 0 or now - ts > idle_timeout)
        ]

    for conv_id, candidate_ts in candidates:
        with _last_used_lock:
            current_ts = _last_used.get(conv_id)
            current_now = time.monotonic()
            if (
                current_ts is None
                or current_ts != candidate_ts
                or (current_ts > 0 and current_now - current_ts <= idle_timeout)
            ):
                continue

        if get_status(conv_id) == "running":
            log.info("[container] idle timeout reached for %s; stopping", conv_id)
            stop_container_process(conv_id)

        with _last_used_lock:
            if _last_used.get(conv_id) == candidate_ts:
                _last_used.pop(conv_id, None)


def _reap_idle_containers() -> None:
    """Background daemon loop: check for idle containers every 60 seconds."""
    while True:
        time.sleep(60)
        try:
            _reap_once()
        except Exception:
            log.exception("[container] error in idle reaper")


# Daemon thread — exits automatically when the main process exits. It is
# started explicitly from app.create_app() so tests can import this module
# without spawning background threads.
_reaper_thread: threading.Thread | None = None
_reaper_started = False
_reaper_lock = threading.Lock()


def start_reaper() -> None:
    global _reaper_thread, _reaper_started
    with _reaper_lock:
        if _reaper_started:
            return
        _reaper_thread = threading.Thread(
            target=_reap_idle_containers,
            name="container-idle-reaper",
            daemon=True,
        )
        _reaper_thread.start()
        _reaper_started = True