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
from mcp_session_pool import McpSessionPool

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


# ── Persistent cross-turn session pools ──────────────────────────────────────

_persistent_pools: dict[str, McpSessionPool] = {}
_persistent_pools_lock = threading.Lock()


def get_persistent_pool(conv_id: str) -> McpSessionPool:
    """Return the long-lived McpSessionPool for this conversation, creating it if needed."""
    with _persistent_pools_lock:
        pool = _persistent_pools.get(conv_id)
        if pool is None or pool._closed:
            pool = McpSessionPool(conv_id)
            pool.start()
            _persistent_pools[conv_id] = pool
        return pool


def close_persistent_pool(conv_id: str) -> None:
    """Close and discard the pool for a conversation.

    Call this whenever the conversation's container is stopped or recreated so
    the next tool call opens fresh sessions against the new container process.
    Safe to call even if no pool exists for the conversation.
    """
    with _persistent_pools_lock:
        pool = _persistent_pools.pop(conv_id, None)
    if pool is not None:
        try:
            pool.close()
        except Exception:
            log.exception("[mcp] error closing persistent pool for conv %s", conv_id)


def close_all_persistent_pools() -> None:
    """Close every persistent pool. Call once on app shutdown."""
    with _persistent_pools_lock:
        items = list(_persistent_pools.items())
        _persistent_pools.clear()
    for conv_id, pool in items:
        try:
            pool.close()
        except Exception:
            log.exception("[mcp] error closing persistent pool for conv %s on shutdown", conv_id)


# ── Sync bridge ───────────────────────────────────────────────────────────────

# Shared executor for bridging async MCP calls into sync Flask code.
_async_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mcp-async")


def run_async(coro) -> Any:
    """Run an async coroutine from sync code without spawning a new thread unless one is needed."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    return _async_executor.submit(asyncio.run, coro).result()
