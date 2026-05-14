"""Tool approval gate — blocking approval requests with per-stream state."""
from __future__ import annotations

import threading
from collections.abc import Callable

Publish = Callable[[dict], None]

# Keyed by stream_id → { call_id → {"event": Event, "approved": bool} }
_pending_approvals: dict[str, dict] = {}
_pending_approvals_lock = threading.Lock()


def resolve_tool_approval(stream_id: str, call_id: str, approved: bool) -> None:
    """Called from the /api/chat/approve route to unblock a waiting tool call."""
    with _pending_approvals_lock:
        slot = _pending_approvals.get(stream_id, {}).get(call_id)
    if slot:
        slot["approved"] = approved
        slot["event"].set()


def request_tool_approval(
    stream_id: str,
    call_id: str,
    name: str,
    args: dict,
    publish: Publish,
    cancel_event: threading.Event,
) -> bool:
    """Emit a tool_approval_required event and block until the client responds or the turn is cancelled."""
    wait_event = threading.Event()
    slot: dict = {"event": wait_event, "approved": False}

    with _pending_approvals_lock:
        _pending_approvals.setdefault(stream_id, {})[call_id] = slot

    publish({"type": "tool_approval_required", "call_id": call_id, "name": name, "args": args})

    while not wait_event.is_set() and not cancel_event.is_set():
        wait_event.wait(timeout=0.5)

    with _pending_approvals_lock:
        pending_for_stream = _pending_approvals.get(stream_id)
        if pending_for_stream is not None:
            pending_for_stream.pop(call_id, None)
            if not pending_for_stream:
                _pending_approvals.pop(stream_id, None)

    if cancel_event.is_set():
        return False
    return bool(slot["approved"])
