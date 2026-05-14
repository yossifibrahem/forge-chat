"""MCP service layer — config persistence, tool discovery, tool invocation."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from mcp_adapters import apply_workspace_process_options, expand_config_env, extract_host_mounts
from fs_utils import atomic_replace
from docker_path_utils import parse_volume_source

_MCP_CONFIG_DIR = Path.home() / ".lumen"
_MCP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
MCP_CONFIG_FILE = Path(os.getenv("LUMEN_MCP_CONFIG_FILE", str(_MCP_CONFIG_DIR / "mcp.json")))
log = logging.getLogger(__name__)

_config_cache: dict | None = None
_config_cache_at = 0.0
_config_cache_path: Path | None = None
_config_cache_lock = threading.Lock()
_CONFIG_TTL_SECONDS = float(os.getenv("LUMEN_MCP_CONFIG_CACHE_TTL", "5"))


# ── Config ────────────────────────────────────────────────────────────────────

def load_config(*, refresh: bool = False) -> dict:
    global _config_cache, _config_cache_at, _config_cache_path
    now = time.monotonic()
    with _config_cache_lock:
        if (
            not refresh
            and _config_cache is not None
            and _config_cache_path == MCP_CONFIG_FILE
            and now - _config_cache_at < _CONFIG_TTL_SECONDS
        ):
            return _config_cache

    if not MCP_CONFIG_FILE.exists():
        config = {"mcpServers": {}}
    else:
        try:
            config = json.loads(MCP_CONFIG_FILE.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("[mcp] could not read %s: %s", MCP_CONFIG_FILE, exc)
            config = {"mcpServers": {}}

    if not isinstance(config, dict) or not isinstance(config.get("mcpServers", {}), dict):
        config = {"mcpServers": {}}

    with _config_cache_lock:
        _config_cache = config
        _config_cache_at = time.monotonic()
        _config_cache_path = MCP_CONFIG_FILE
        return config


def save_config(config: dict) -> None:
    global _config_cache, _config_cache_at, _config_cache_path
    if not isinstance(config, dict):
        raise ValueError("MCP config must be a JSON object")
    config.setdefault("mcpServers", {})
    if not isinstance(config["mcpServers"], dict):
        raise ValueError("mcpServers must be a JSON object")

    tmp_path = MCP_CONFIG_FILE.with_suffix(f".tmp-{uuid.uuid4().hex}")
    tmp_path.write_text(json.dumps(config, indent=2))
    with _config_cache_lock:
        atomic_replace(tmp_path, MCP_CONFIG_FILE)
        _config_cache = config
        _config_cache_at = time.monotonic()
        _config_cache_path = MCP_CONFIG_FILE


def find_server(server_name: str) -> dict | None:
    return load_config().get("mcpServers", {}).get(server_name)


def collect_all_extra_volumes(server_names: list[str]) -> list[str]:
    """Return the union of host mount volumes needed by all given MCP servers.

    Called once at turn start so the container is created with every required
    volume upfront, preventing recreation mid-turn when the model switches
    between servers that reference different host paths.
    """
    servers = load_config().get("mcpServers", {})
    seen: set[str] = set()
    volumes: list[str] = []
    for name in server_names:
        for spec in extract_host_mounts(servers.get(name, {})):
            # Use container_service's parser so Windows drive-letter sources
            # like "D:/foo/bar" are extracted correctly (not just "D").
            src = parse_volume_source(spec)
            if src not in seen:
                seen.add(src)
                volumes.append(spec)
    return volumes


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_server_params(
    server_name: str,
    server_config: dict,
    *,
    conv_id: str = "",
) -> Any:
    from mcp import StdioServerParameters  # optional dependency

    env = {**os.environ, **expand_config_env(server_config.get("env", {}))}
    params = {
        "command": server_config.get("command", ""),
        "args": server_config.get("args", []),
        "env": env,
    }
    apply_workspace_process_options(
        params,
        env,
        server_name=server_name,
        server_config=server_config,
        conv_id=conv_id,
    )
    return StdioServerParameters(**params)


# ── Async operations ──────────────────────────────────────────────────────────

async def fetch_tools(server_name: str, server_config: dict, conv_id: str = "") -> list[dict]:
    """Connect to an MCP server and return its tool definitions."""
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    params = _build_server_params(server_name, server_config, conv_id=conv_id)
    tools: list[dict] = []
    try:
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                for tool in (await session.list_tools()).tools:
                    tools.append({
                        "server":      server_name,
                        "name":        tool.name,
                        "description": tool.description or "",
                        "inputSchema": getattr(tool, "inputSchema", {}),
                    })
    except Exception as exc:
        log.warning("[mcp] failed to list tools from %r: %s", server_name, exc)
    return tools


async def invoke_tool(server_name: str, server_config: dict, tool_name: str, arguments: dict, *, conv_id: str = "") -> str:
    """Call a single MCP tool and return its text output."""
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    params = _build_server_params(server_name, server_config, conv_id=conv_id)
    try:
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                text = "\n".join(
                    c.text if hasattr(c, "text") else str(c)
                    for c in result.content
                )
                return text
    except Exception as exc:
        return f"Error calling tool '{tool_name}': {exc}"


# ── Sync bridge ───────────────────────────────────────────────────────────────

# Shared executor for bridging async MCP calls into sync Flask code.
# One thread per concurrent caller is enough; each thread runs its own event
# loop via asyncio.run().  A module-level pool avoids creating and tearing down
# a ThreadPoolExecutor on every tool call (which was the previous behaviour).
_async_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mcp-async")


def run_async(coro) -> Any:
    """Run an async coroutine from sync code without spawning a new thread unless one is needed."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    return _async_executor.submit(asyncio.run, coro).result()

# ── Per-turn session pool ─────────────────────────────────────────────────────

class McpSessionPool:
    """Reuse MCP stdio sessions for multiple tool calls in one chat turn.

    AnyIO-backed MCP context managers must be exited from the same asyncio task
    that entered them. A naive ``run_coroutine_threadsafe`` call creates a new
    Task for every invocation, which works for calls but fails during cleanup
    with ``Attempted to exit cancel scope in a different task``. This pool uses
    one dedicated worker coroutine for the whole turn, so open, invoke, and
    close all happen in the same Task.
    """

    def __init__(self, conv_id: str = "") -> None:
        self.conv_id = conv_id
        self._jobs: "queue.Queue[tuple]" | None = None
        self._thread: threading.Thread | None = None
        self._sessions: dict[str, dict] = {}
        self._closed = False
        self._lock = threading.Lock()

    def __enter__(self) -> "McpSessionPool":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def start(self) -> None:
        if self._thread:
            return
        import queue

        self._jobs = queue.Queue()
        self._thread = threading.Thread(target=self._thread_main, name="mcp-session-pool", daemon=True)
        self._thread.start()

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._worker())
        except Exception:
            log.exception("[mcp] session pool worker crashed")

    async def _worker(self) -> None:
        if self._jobs is None:
            raise RuntimeError("MCP session pool was not started")

        while True:
            job = await asyncio.to_thread(self._jobs.get)
            op = job[0]
            if op == "invoke":
                _, server_name, server_config, tool_name, arguments, future = job
                try:
                    result = await self._invoke(server_name, server_config, tool_name, arguments)
                except Exception as exc:
                    future.set_exception(exc)
                else:
                    future.set_result(result)
            elif op == "close":
                _, future = job
                try:
                    await self._close_async()
                except Exception as exc:
                    future.set_exception(exc)
                else:
                    future.set_result(None)
                break

    async def _get_session(self, server_name: str, server_config: dict):
        if server_name in self._sessions:
            return self._sessions[server_name]["session"]

        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        params = _build_server_params(server_name, server_config, conv_id=self.conv_id)
        stdio_cm = stdio_client(params)
        reader, writer = await stdio_cm.__aenter__()
        session_cm = ClientSession(reader, writer)
        session = await session_cm.__aenter__()
        await session.initialize()
        self._sessions[server_name] = {
            "session": session,
            "session_cm": session_cm,
            "stdio_cm": stdio_cm,
        }
        return session

    async def _invoke(self, server_name: str, server_config: dict, tool_name: str, arguments: dict) -> str:
        session = await self._get_session(server_name, server_config)
        result = await session.call_tool(tool_name, arguments)
        return "\n".join(
            c.text if hasattr(c, "text") else str(c)
            for c in result.content
        )

    def invoke_tool(self, server_name: str, server_config: dict, tool_name: str, arguments: dict) -> str:
        if self._closed:
            raise RuntimeError("MCP session pool is closed")
        self.start()
        if self._jobs is None:
            raise RuntimeError("MCP session pool failed to start")

        from concurrent.futures import Future

        future: Future = Future()
        with self._lock:
            self._jobs.put(("invoke", server_name, server_config, tool_name, arguments, future))
        # Block *outside* the lock. Holding a lock while waiting on a future is a
        # deadlock risk: any code path that needs self._lock while this call is
        # in-flight (e.g. a concurrent close()) would be permanently blocked.
        return future.result()

    async def _close_async(self) -> None:
        for entry in reversed(list(self._sessions.values())):
            try:
                await entry["session_cm"].__aexit__(None, None, None)
            except Exception:
                log.exception("[mcp] error closing client session")
            try:
                await entry["stdio_cm"].__aexit__(None, None, None)
            except Exception:
                log.exception("[mcp] error closing stdio session")
        self._sessions.clear()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if not self._thread:
            return
        if self._jobs is None:
            raise RuntimeError("MCP session pool failed to start")

        from concurrent.futures import Future

        future: Future = Future()
        self._jobs.put(("close", future))
        future.result()
        self._thread.join(timeout=2)