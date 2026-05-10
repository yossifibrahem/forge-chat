"""Docker-backed runtime for per-conversation MCP containers."""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
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
DISCOVERY_CONTAINER_ID = "__mcp_discovery__"

ContainerStatus = Literal["running", "stopped", "missing"]

_CONTAINER_LOCKS: dict[str, threading.Lock] = {}
_CONTAINER_LOCKS_GUARD = threading.Lock()


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


def _volume_source(spec: str) -> str:
    return spec.split(":", 1)[0]


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
    with _container_lock(conv_id):
        return _ensure_container_locked(conv_id, extra_volumes or [])


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
    return [
        "docker", "run",
        "--detach",
        "--name", name,
        *_volume_args(workspace, extra_volumes),
        "--workdir", "/workspace",
        "--memory", CONTAINER_MEMORY,
        "--cpus", CONTAINER_CPUS,
        "--network", CONTAINER_NETWORK,
        "--cap-drop", "ALL",
        "--cap-add", "CHOWN",
        "--cap-add", "DAC_OVERRIDE",
        "--cap-add", "SETUID",
        "--cap-add", "SETGID",
        "--security-opt", "no-new-privileges",
        SANDBOX_IMAGE,
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
    name = container_name(conv_id)
    if get_status(conv_id) != "running":
        return
    result = _run(["docker", "stop", name])
    if result.returncode != 0:
        log.warning("[container] could not stop %s: %s", name, result.stderr.strip())
    else:
        log.info("[container] stopped %s", name)


def stop_container(conv_id: str) -> None:
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
