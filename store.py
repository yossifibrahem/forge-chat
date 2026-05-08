"""
Conversation store — file-system CRUD.

All persistence is isolated here.  Nothing in this module imports Flask;
routes call these functions and decide what HTTP status to return.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from mcp_adapters import conversation_working_directory

CONVERSATIONS_DIR = Path.home() / ".lumen" / "conversations"
CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)

IMAGES_DIR = Path.home() / ".lumen" / "images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)


_SAFE_IMAGE_EXTENSIONS = {'png', 'jpeg', 'webp', 'gif'}
_SAFE_NAME = re.compile(r'^[a-f0-9]{64}\.(png|jpeg|webp|gif)$')


# ── Image storage ─────────────────────────────────────────────────────────────

def save_image(data_b64: str, media_type: str) -> str:
    """Decode a supported image type, persist by SHA-256 hash, and return filename."""
    ext = (media_type.split("/")[-1].split(";")[0] or "png").lower()
    if ext == "jpg":
        ext = "jpeg"
    if ext not in _SAFE_IMAGE_EXTENSIONS:
        raise ValueError(f"Unsupported image type: {media_type or 'unknown'}")
    try:
        raw = base64.b64decode(data_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid image data") from exc

    name = hashlib.sha256(raw).hexdigest() + "." + ext
    path = IMAGES_DIR / name
    if not path.exists():
        path.write_bytes(raw)
    return name


def get_image_path(name: str) -> Path | None:
    """Return the Path for a stored image, or None if it doesn't exist / is unsafe."""
    if not _SAFE_NAME.match(name):
        return None
    path = IMAGES_DIR / name
    return path if path.exists() else None


# ── Internal helpers ──────────────────────────────────────────────────────────

def _path(conv_id: str) -> Path:
    return CONVERSATIONS_DIR / f"{conv_id}.json"


def working_directory(conv_id: str) -> Path:
    """Return the isolated MCP working directory for one conversation."""
    return conversation_working_directory(conv_id)


# ── Public API ────────────────────────────────────────────────────────────────

def list_all() -> list[dict]:
    """Return conversation summaries sorted by most-recently modified."""
    results: list[dict] = []
    for path in sorted(CONVERSATIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text())
            results.append({
                "id":            path.stem,
                "title":         data.get("title", "Untitled"),
                "updated_at":    data.get("updated_at", ""),
                "message_count": len(data.get("messages", [])),
                "working_directory": str(working_directory(path.stem)),
            })
        except Exception:
            pass
    return results


def load(conv_id: str) -> dict | None:
    path = _path(conv_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def save(conv_id: str, data: dict) -> dict:
    """Stamp updated_at, write atomically, and return the saved data."""
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = _path(conv_id)
    tmp_path = path.with_suffix(f".tmp-{uuid.uuid4().hex}")
    tmp_path.write_text(json.dumps(data, indent=2))
    tmp_path.replace(path)
    return data


def delete(conv_id: str) -> bool:
    path = _path(conv_id)
    if path.exists():
        path.unlink()
        return True
    return False


def create(title: str = "New Conversation") -> dict:
    """Create, persist, and return a blank conversation."""
    conv_id = str(uuid.uuid4())
    return save(conv_id, {
        "id":                conv_id,
        "title":             title,
        "messages":          [],
        "working_directory": str(working_directory(conv_id)),
        "created_at":        datetime.now(timezone.utc).isoformat(),
    })
