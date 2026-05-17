"""HTTP routes for Lumen.

This module registers all route blueprints. Each route group lives in its
own module:
  routes_startup.py        – setup screen, health, Docker/image requirement checks
  routes_conversations.py  – conversation CRUD, workspace, container status
  routes_chat.py           – streaming chat, cancel, approve, settings, models
  routes_mcp.py            – MCP config, tool discovery, direct tool calls
  routes_files.py          – workspace files, image upload/serve

Routes stay thin: parse request data, call services, and return HTTP-friendly
responses. Long-running chat and workspace file logic live in dedicated modules.
"""
from __future__ import annotations

from flask import Blueprint

import routes_startup
import routes_conversations
import routes_chat
import routes_mcp
import routes_files

# Single top-level blueprint for backward compatibility with app.py which
# does `from routes import blueprint`.
blueprint = Blueprint("main", __name__)


def _register_all(app):
    """Register every route blueprint onto the Flask app."""
    app.register_blueprint(routes_startup.blueprint)
    app.register_blueprint(routes_conversations.blueprint)
    app.register_blueprint(routes_chat.blueprint)
    app.register_blueprint(routes_mcp.blueprint)
    app.register_blueprint(routes_files.blueprint)