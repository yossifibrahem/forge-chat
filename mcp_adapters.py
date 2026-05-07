"""MCP adapter hooks for app-level MCP behavior.

Keep MCP integration behavior here instead of spreading it through routes,
storage, and invocation code. Server-side sandboxing/path interpretation should
remain inside the MCP server itself.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path.home() / ".lumen" / "working_directory"
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)


def conversation_working_directory(conversation_id: str) -> Path:
    """Return the isolated workspace for one conversation."""
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", conversation_id or "default")
    path = WORKSPACE_ROOT / safe_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_working_dir(working_dir: str | None) -> str | None:
    """Expand and create a workspace path, returning an absolute string."""
    if not working_dir:
        return None
    path = Path(os.path.expanduser(working_dir)).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def expand_config_env(env: dict | None) -> dict:
    """Expand ~ in user-provided MCP env values."""
    expanded = {}
    for key, value in (env or {}).items():
        expanded[key] = os.path.expanduser(str(value)) if isinstance(value, str) else value
    return expanded


def apply_workspace_process_options(params: dict[str, Any], env: dict[str, Any], working_dir: str | None) -> None:
    """Apply the chat workspace to local MCP process env/cwd.

    The app only provides workspace context. Filesystem sandboxing and path
    interpretation belong inside the MCP server implementation.
    """
    resolved = resolve_working_dir(working_dir)
    if not resolved:
        return
    env["WORKING_DIR"] = resolved
    env["PWD"] = resolved
    params["cwd"] = resolved
