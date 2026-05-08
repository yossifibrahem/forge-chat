"""Workspace file operations for each conversation's /workspace mount."""
from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path
from typing import Iterable

import store

_TEXT_EXTENSIONS = {
    ".bash", ".bat", ".c", ".cfg", ".conf", ".cpp", ".cs", ".css", ".csv",
    ".dockerfile", ".env", ".go", ".h", ".hpp", ".htm", ".html", ".ini",
    ".java", ".js", ".json", ".jsx", ".log", ".lua", ".md", ".mjs",
    ".php", ".properties", ".py", ".rb", ".rs", ".sh", ".sql", ".svg",
    ".toml", ".ts", ".tsx", ".txt", ".xml", ".yaml", ".yml",
}
_SAFE_UPLOAD_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


MAX_PREVIEW_BYTES = _env_int("LUMEN_MAX_FILE_PREVIEW_BYTES", 512 * 1024)
MAX_LIST_ENTRIES = _env_int("LUMEN_MAX_FILE_LIST_ENTRIES", 500)
MAX_UPLOAD_BYTES = _env_int("LUMEN_MAX_UPLOAD_BYTES", 50 * 1024 * 1024)


def workspace_root(conv_id: str) -> Path:
    return store.working_directory(conv_id).resolve()


def workspace_relpath(path_value: str | None) -> str:
    raw = (path_value or "").strip().replace("\\", "/")
    if raw in {"", ".", "/", "/workspace"}:
        return ""
    if raw.startswith("/workspace/"):
        raw = raw[len("/workspace/"):]
    elif raw.startswith("/"):
        raise ValueError("Only /workspace paths are available")

    parts = [part for part in raw.split("/") if part and part != "."]
    if any(part == ".." for part in parts):
        raise ValueError("Parent path traversal is not allowed")
    return "/".join(parts)


def resolve_workspace_path(conv_id: str, path_value: str | None) -> tuple[Path, str]:
    root = workspace_root(conv_id)
    rel = workspace_relpath(path_value)
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Path escapes the workspace")
    return target, rel


def workspace_path(rel: str) -> str:
    return "/workspace" + (f"/{rel}" if rel else "")


def _parent_workspace_path(rel: str) -> str | None:
    if not rel:
        return None
    parent = Path(rel).parent.as_posix()
    return workspace_path("" if parent == "." else parent)


def _is_text_file(path: Path) -> bool:
    if path.suffix.lower() in _TEXT_EXTENSIONS:
        return True
    mime, _ = mimetypes.guess_type(path.name)
    return bool(mime and (mime.startswith("text/") or mime in {
        "application/json", "application/javascript", "application/xml", "application/xhtml+xml",
    }))


def _file_entry(path: Path, root: Path) -> dict:
    stat = path.stat()
    rel = path.relative_to(root).as_posix()
    is_dir = path.is_dir()
    return {
        "name": path.name,
        "path": workspace_path(rel),
        "relative_path": rel,
        "type": "directory" if is_dir else "file",
        "size": None if is_dir else stat.st_size,
        "modified": stat.st_mtime,
        "previewable": (not is_dir) and _is_text_file(path) and stat.st_size <= MAX_PREVIEW_BYTES,
    }


def list_dir(conv_id: str, path_value: str | None) -> tuple[dict, int]:
    if not store.load(conv_id):
        return {"error": "Conversation not found"}, 404
    try:
        target, rel = resolve_workspace_path(conv_id, path_value)
    except ValueError as exc:
        return {"error": str(exc)}, 400
    if not target.exists():
        return {"error": "Path not found"}, 404
    if not target.is_dir():
        return {"error": "Path is not a directory"}, 400

    root = workspace_root(conv_id)
    children = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    visible_children = children[:MAX_LIST_ENTRIES]

    return {
        "path": workspace_path(rel),
        "relative_path": rel,
        "parent": _parent_workspace_path(rel),
        "entries": [_file_entry(child, root) for child in visible_children],
        "limit": MAX_LIST_ENTRIES,
        "truncated": len(children) > MAX_LIST_ENTRIES,
    }, 200


def read_file(conv_id: str, path_value: str | None) -> tuple[dict, int]:
    if not store.load(conv_id):
        return {"error": "Conversation not found"}, 404
    try:
        target, _ = resolve_workspace_path(conv_id, path_value)
    except ValueError as exc:
        return {"error": str(exc)}, 400
    if not target.exists():
        return {"error": "File not found"}, 404
    if not target.is_file():
        return {"error": "Path is not a file"}, 400

    stat = target.stat()
    previewable = _is_text_file(target) and stat.st_size <= MAX_PREVIEW_BYTES
    mime, _ = mimetypes.guess_type(target.name)
    data = {
        **_file_entry(target, workspace_root(conv_id)),
        "mime_type": mime or "application/octet-stream",
    }
    if not previewable:
        return {**data, "previewable": False, "content": None}, 200

    raw = target.read_bytes()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("utf-8", errors="replace")
    return {**data, "previewable": True, "content": content}, 200


def safe_upload_name(name: str) -> str:
    cleaned = _SAFE_UPLOAD_NAME.sub("_", Path(name or "file").name).strip(" ._")
    return cleaned or "file"


def _unique_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate

    stem = candidate.stem or "file"
    suffix = candidate.suffix
    for index in range(1, 1000):
        candidate = directory / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not create a unique filename for {filename!r}")


def save_uploads(conv_id: str, files: Iterable) -> tuple[dict, int]:
    if not store.load(conv_id):
        return {"error": "Conversation not found"}, 404

    upload_dir = store.working_directory(conv_id) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    saved: list[dict] = []
    for item in files:
        if not item or not item.filename:
            continue

        filename = safe_upload_name(item.filename)
        target = _unique_path(upload_dir, filename)
        total = 0

        with target.open("wb") as fh:
            while chunk := item.stream.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    fh.close()
                    target.unlink(missing_ok=True)
                    for previous in saved:
                        Path(previous["host_path"]).unlink(missing_ok=True)
                    return {"error": f"File '{filename}' exceeds the upload limit of {MAX_UPLOAD_BYTES} bytes"}, 413
                fh.write(chunk)

        saved.append({
            "name": target.name,
            "size": total,
            "path": f"/workspace/uploads/{target.name}",
            "host_path": str(target),
        })

    if not saved:
        return {"error": "No valid files uploaded"}, 400
    return {"files": saved}, 200
