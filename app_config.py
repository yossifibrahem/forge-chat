"""Server-side application configuration for API provider settings.

Sensitive values such as API keys are stored on the server, not in browser
localStorage or chat request bodies.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

CONFIG_DIR = Path.home() / ".lumen"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = Path(os.getenv("LUMEN_CONFIG_FILE", str(CONFIG_DIR / "config.json")))

DEFAULT_API_BASE = "https://api.openai.com/v1"

_ALLOWED_KEYS = {"api_base", "api_key"}


def load_config() -> dict:
    """Load server-side config, with environment variables taking precedence."""
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            loaded = json.loads(CONFIG_FILE.read_text())
            if isinstance(loaded, dict):
                data.update({k: v for k, v in loaded.items() if k in _ALLOWED_KEYS})
        except (OSError, json.JSONDecodeError):
            data = {}

    env_key = os.getenv("OPENAI_API_KEY")
    env_base = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")
    if env_key:
        data["api_key"] = env_key
    if env_base:
        data["api_base"] = env_base

    data.setdefault("api_base", DEFAULT_API_BASE)
    data.setdefault("api_key", "")
    return data


def public_config() -> dict:
    """Return non-sensitive config metadata safe for the browser."""
    cfg = load_config()
    return {
        "api_base": cfg.get("api_base") or DEFAULT_API_BASE,
        "has_api_key": bool(cfg.get("api_key")),
    }


def save_config(update: dict) -> dict:
    """Persist allowed server-side settings atomically.

    An empty API key means "leave the existing saved key unchanged" so the UI
    can save the base URL without forcing users to re-enter their key.
    """
    if not isinstance(update, dict):
        raise ValueError("Config update must be a JSON object")

    current = {}
    if CONFIG_FILE.exists():
        try:
            loaded = json.loads(CONFIG_FILE.read_text())
            if isinstance(loaded, dict):
                current = {k: v for k, v in loaded.items() if k in _ALLOWED_KEYS}
        except (OSError, json.JSONDecodeError):
            current = {}

    if "api_base" in update:
        current["api_base"] = str(update.get("api_base") or DEFAULT_API_BASE).strip() or DEFAULT_API_BASE
    if "api_key" in update and str(update.get("api_key") or "").strip():
        current["api_key"] = str(update.get("api_key") or "").strip()

    current.setdefault("api_base", DEFAULT_API_BASE)
    tmp_path = CONFIG_FILE.with_suffix(f".tmp-{uuid.uuid4().hex}")
    tmp_path.write_text(json.dumps(current, indent=2))
    tmp_path.replace(CONFIG_FILE)
    return public_config()
