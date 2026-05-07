"""
MCP service layer — config persistence, tool discovery, tool invocation.

The asyncio coroutines are executed safely from Flask's synchronous
context via `run_async`, which always spins up a dedicated thread to
avoid conflicts with any existing event loop.
"""
from __future__ import annotations

import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

MCP_CONFIG_FILE = Path("mcp.json")


# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if MCP_CONFIG_FILE.exists():
        return json.loads(MCP_CONFIG_FILE.read_text())
    return {"mcpServers": {}}


def save_config(config: dict) -> None:
    MCP_CONFIG_FILE.write_text(json.dumps(config, indent=2))


def find_server(server_name: str) -> dict | None:
    return load_config().get("mcpServers", {}).get(server_name)



# ── Internal helpers ──────────────────────────────────────────────────────────

def _expand_env(env: dict | None) -> dict:
    expanded = {}
    for key, value in (env or {}).items():
        expanded[key] = os.path.expanduser(str(value)) if isinstance(value, str) else value
    return expanded


def _resolve_working_dir(working_dir: str | None) -> str | None:
    """Expand and create a per-chat MCP workspace path."""
    if not working_dir:
        return None
    path = Path(os.path.expanduser(working_dir)).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _build_server_params(server_config: dict, *, working_dir: str | None = None) -> Any:
    from mcp import StdioServerParameters  # optional dependency

    resolved_working_dir = _resolve_working_dir(working_dir)
    env = {**os.environ, **_expand_env(server_config.get("env", {}))}
    if resolved_working_dir:
        # The bundled Bash/Filesystem servers read WORKING_DIR, while some
        # tools also inherit cwd/PWD. Set all three so there is no ambiguity.
        env["WORKING_DIR"] = resolved_working_dir
        env["PWD"] = resolved_working_dir

    params = {
        "command": server_config.get("command", ""),
        "args": server_config.get("args", []),
        "env": env,
    }

    # Newer Python MCP SDKs support `cwd` on StdioServerParameters. Older ones
    # do not, so fall back gracefully while still passing WORKING_DIR/PWD.
    if resolved_working_dir:
        params["cwd"] = resolved_working_dir

    try:
        return StdioServerParameters(**params)
    except Exception:
        # Some older SDK builds reject unknown fields such as `cwd`. Retry with
        # the portable env-only shape.
        params.pop("cwd", None)
        return StdioServerParameters(**params)


def _is_bundled_filesystem_tool(server_name: str, tool_name: str) -> bool:
    """Best-effort detection for the bundled filesystem MCP tools."""
    return (
        "filesystem" in (server_name or "").lower()
        or tool_name in {"view", "create_file", "str_replace"}
    )


def _workspace_relative_path(raw_path: str, working_dir: str | None) -> str:
    """Map all filesystem tool paths into the active chat workspace.

    The bundled filesystem server intentionally lets absolute paths escape
    WORKING_DIR. For this chatbot, each chat must be isolated, so `/temp`,
    `temp`, and `./temp` all become `<workspace>/temp`. `~` is also anchored
    to the workspace instead of the OS home when passed to filesystem tools.
    """
    resolved_working_dir = _resolve_working_dir(working_dir)
    if not resolved_working_dir or not isinstance(raw_path, str) or not raw_path.strip():
        return raw_path

    raw = raw_path.strip()
    root = Path(resolved_working_dir)

    if raw in {"/", ".", "./", "~", "~/"}:
        return str(root)

    # The desired UX is workspace-rooted paths, even if the model emits a
    # leading slash. This makes `/src/app.py` mean `<chat workspace>/src/app.py`,
    # not the host machine's `/src/app.py`.
    if raw.startswith("~/"):
        relative = raw[2:]
    elif raw.startswith("/"):
        relative = raw.lstrip("/")
    else:
        relative = raw

    candidate = (root / relative).resolve()

    # Prevent path traversal from escaping the chat workspace.
    try:
        candidate.relative_to(root)
    except ValueError:
        candidate = root / Path(relative).name

    return str(candidate)


def _normalize_tool_arguments(server_name: str, tool_name: str, arguments: dict, working_dir: str | None) -> dict:
    """Apply chatbot-specific workspace semantics before invoking MCP tools."""
    if not isinstance(arguments, dict):
        return arguments

    normalized = dict(arguments)
    if _is_bundled_filesystem_tool(server_name, tool_name) and "path" in normalized:
        normalized["path"] = _workspace_relative_path(normalized["path"], working_dir)
    return normalized


# ── Async operations ──────────────────────────────────────────────────────────

async def fetch_tools(server_name: str, server_config: dict) -> list[dict]:
    """Connect to an MCP server and return its tool definitions."""
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    params = _build_server_params(server_config)
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
        print(f"[MCP] Failed to list tools from '{server_name}': {exc}")
    return tools


async def invoke_tool(server_name: str, server_config: dict, tool_name: str, arguments: dict, *, working_dir: str | None = None) -> str:
    """Call a single MCP tool and return its text output."""
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    params = _build_server_params(server_config, working_dir=working_dir)
    try:
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                normalized_arguments = _normalize_tool_arguments(server_name, tool_name, arguments, working_dir)
                result = await session.call_tool(tool_name, normalized_arguments)
                text = "\n".join(
                    c.text if hasattr(c, "text") else str(c)
                    for c in result.content
                )
                return text
    except Exception as exc:
        return f"Error calling tool '{tool_name}': {exc}"


# ── Sync bridge ───────────────────────────────────────────────────────────────

def run_async(coro) -> Any:
    """Run an async coroutine from a synchronous Flask handler."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
