"""MCP service layer — config persistence, tool discovery, tool invocation."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from mcp_adapters import apply_workspace_process_options, expand_config_env, extract_host_mounts

MCP_CONFIG_FILE = Path("mcp.json")
log = logging.getLogger(__name__)


# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if not MCP_CONFIG_FILE.exists():
        return {"mcpServers": {}}
    try:
        config = json.loads(MCP_CONFIG_FILE.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("[mcp] could not read %s: %s", MCP_CONFIG_FILE, exc)
        return {"mcpServers": {}}
    return config if isinstance(config, dict) and isinstance(config.get("mcpServers", {}), dict) else {"mcpServers": {}}


def save_config(config: dict) -> None:
    if not isinstance(config, dict):
        raise ValueError("MCP config must be a JSON object")
    config.setdefault("mcpServers", {})
    if not isinstance(config["mcpServers"], dict):
        raise ValueError("mcpServers must be a JSON object")

    tmp_path = MCP_CONFIG_FILE.with_suffix(f".tmp-{uuid.uuid4().hex}")
    tmp_path.write_text(json.dumps(config, indent=2))
    tmp_path.replace(MCP_CONFIG_FILE)


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
            src = spec.split(":", 1)[0]
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

def run_async(coro) -> Any:
    """Run an async coroutine from sync code without spawning a thread unless one is needed."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
