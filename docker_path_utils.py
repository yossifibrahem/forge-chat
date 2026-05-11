"""Cross-platform path utilities for Docker volume specs and container paths.

On Linux/macOS host paths can be mirrored directly inside containers
(``/foo/bar:/foo/bar:ro``).  On Windows that is impossible because:

* Windows paths contain a drive-letter colon (``D:\\foo``) which Docker's CLI
  misparses as a field separator, producing "too many colons" errors.
* Linux containers cannot have mount targets like ``D:\\foo``.

This module centralises the conversion logic so every other module can stay
platform-agnostic.

Public API
----------
host_path_to_docker_src(path_str)
    Convert a native host path to the *source* field of a Docker ``-v`` spec.

host_path_to_container_path(path_str)
    Return the absolute path at which a host directory appears inside the
    Linux container.

make_volume_spec(host_path, mode="ro")
    Build a complete ``source:target:mode`` volume spec string.

translate_arg_for_container(arg)
    Rewrite an absolute Windows path argument to its in-container equivalent.
    Returns the arg unchanged on non-Windows platforms and for non-path args.

parse_volume_source(spec)
    Extract the host-side source from a volume spec string, handling Windows
    drive-letter paths correctly.
"""
from __future__ import annotations

import sys


# ---------------------------------------------------------------------------
# Host → Docker source path
# ---------------------------------------------------------------------------

def host_path_to_docker_src(path_str: str) -> str:
    """Convert a native host path to the source field of a Docker volume spec.

    On Windows, Docker Desktop requires forward slashes.  The drive letter is
    kept (e.g. ``D:/foo/bar``) because Docker Desktop recognises a
    single-letter prefix followed by ``/`` as a drive letter, not a separator.

    On Linux/macOS the path is returned unchanged.

    Examples::

        # Linux/macOS
        host_path_to_docker_src("/home/user/mcp")  → "/home/user/mcp"

        # Windows
        host_path_to_docker_src("D:\\Tools\\mcp") → "D:/Tools/mcp"
    """
    if sys.platform == "win32":
        return path_str.replace("\\", "/")
    return path_str


# ---------------------------------------------------------------------------
# Host → container (Linux) path
# ---------------------------------------------------------------------------

def host_path_to_container_path(path_str: str) -> str:
    """Return the absolute path at which a host directory appears inside the Linux container.

    On Linux/macOS the container path mirrors the host path (identity).
    On Windows ``D:\\foo\\bar`` maps to ``/d/foo/bar`` so that:

    * the Docker volume spec has no colon ambiguity (``D:/foo:/d/foo:ro``),
    * the mount target is a valid Linux absolute path.

    Examples::

        # Linux/macOS
        host_path_to_container_path("/home/user/mcp")   → "/home/user/mcp"

        # Windows
        host_path_to_container_path("D:\\Tools\\mcp")  → "/d/Tools/mcp"
        host_path_to_container_path("D:/Tools/mcp")    → "/d/Tools/mcp"
    """
    if sys.platform == "win32":
        p = path_str.replace("\\", "/")
        # "D:/foo/bar" → "/d/foo/bar"
        if len(p) >= 2 and p[1] == ":" and p[0].isalpha():
            return "/" + p[0].lower() + p[2:]
    return path_str


# ---------------------------------------------------------------------------
# Volume spec builder
# ---------------------------------------------------------------------------

def make_volume_spec(host_path: str, mode: str = "ro") -> str:
    """Build a ``source:target:mode`` Docker volume spec from a host path.

    Handles Windows paths correctly; safe to call on any platform.

    Examples::

        # Linux/macOS
        make_volume_spec("/home/user/mcp")          → "/home/user/mcp:/home/user/mcp:ro"

        # Windows
        make_volume_spec("D:\\Tools\\mcp")          → "D:/Tools/mcp:/d/Tools/mcp:ro"
        make_volume_spec("D:\\Tools\\mcp", "rw")    → "D:/Tools/mcp:/d/Tools/mcp:rw"
    """
    docker_src = host_path_to_docker_src(host_path)
    container_path = host_path_to_container_path(host_path)
    return f"{docker_src}:{container_path}:{mode}"


# ---------------------------------------------------------------------------
# Arg translator (Windows paths → container paths)
# ---------------------------------------------------------------------------

def translate_arg_for_container(arg: str) -> str:
    """Rewrite an absolute Windows path argument to its in-container equivalent.

    Only strings that look like ``D:\\...`` or ``D:/...`` are rewritten.
    Relative paths, flags, and non-path strings are returned unchanged.
    On non-Windows platforms this is always a no-op.

    Examples::

        # Windows
        translate_arg_for_container("D:\\Tools\\mcp\\index.js") → "/d/Tools/mcp/index.js"
        translate_arg_for_container("--port")                   → "--port"
        translate_arg_for_container("relative/path")            → "relative/path"

        # Linux/macOS (always identity)
        translate_arg_for_container("/usr/local/bin/node")      → "/usr/local/bin/node"
    """
    if sys.platform != "win32":
        return arg
    # Matches "D:\..." or "D:/..." — single alpha letter, colon, then slash
    if (
        len(arg) >= 2
        and arg[1] == ":"
        and arg[0].isalpha()
        and (len(arg) == 2 or arg[2] in ("/", "\\"))
    ):
        return host_path_to_container_path(arg)
    return arg


# ---------------------------------------------------------------------------
# Volume spec parser
# ---------------------------------------------------------------------------

def parse_volume_source(spec: str) -> str:
    """Extract the host-side source path from a Docker volume spec string.

    A plain ``split(":", 1)[0]`` fails on Windows drive-letter paths such as
    ``D:/foo/bar:/d/foo/bar:ro`` — it returns ``"D"`` instead of ``"D:/foo/bar"``.
    This function detects a single-letter first segment (drive letter) and
    joins it with the following segment.

    Examples::

        parse_volume_source("/foo/bar:/foo/bar:ro")         → "/foo/bar"
        parse_volume_source("D:/foo/bar:/d/foo/bar:ro")     → "D:/foo/bar"
        parse_volume_source("D:/foo/bar:/d/foo/bar")        → "D:/foo/bar"
    """
    parts = spec.split(":")
    if len(parts) >= 2 and len(parts[0]) == 1 and parts[0].isalpha():
        return parts[0] + ":" + parts[1]
    return parts[0]