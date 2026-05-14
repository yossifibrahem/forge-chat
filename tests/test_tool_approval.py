"""
Tests for tool_approval.py — the bounded approval gate subsystem.

tool_approval was split out of chat_turn_service.py.  It owns:
  - _pending_approvals dict and its threading.Lock
  - request_tool_approval  — registers a pending slot and blocks until resolved
  - resolve_tool_approval  — unblocks a waiting slot with approve/deny decision

All tests are threaded to exercise the actual blocking/unblocking behavior.
No Flask context, network, or filesystem is needed.

Note: chat_turn_service re-exports resolve_tool_approval at module level so
routes_chat.py keeps its existing import path.  That re-export is verified in
test_chat_turn_service_reexport below.
"""
from __future__ import annotations

import threading
import time

import pytest

import tool_approval as svc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _noop_publish(event: dict) -> None:
    """Discard published events — used when we only care about the return value."""


def _make_cancel() -> threading.Event:
    return threading.Event()


# ---------------------------------------------------------------------------
# resolve_tool_approval
# ---------------------------------------------------------------------------

class TestResolveToolApproval:
    """resolve_tool_approval is a fire-and-forget unblock; it must be idempotent
    for unknown streams and call_ids."""

    def test_resolving_unknown_stream_does_not_raise(self):
        svc.resolve_tool_approval("no-such-stream", "no-such-call", approved=True)

    def test_resolving_unknown_call_id_does_not_raise(self):
        # Register a slot for stream-1 but try to resolve a different call_id.
        cancel = _make_cancel()
        slot_resolved = threading.Event()
        published: list[dict] = []

        def _request():
            svc.request_tool_approval(
                "stream-1", "call-A", "tool", {}, published.append, cancel
            )
            slot_resolved.set()

        t = threading.Thread(target=_request, daemon=True)
        t.start()
        time.sleep(0.05)  # let the thread block on wait_event

        # Resolve a *different* call_id — must not affect call-A or raise
        svc.resolve_tool_approval("stream-1", "call-Z", approved=True)

        # Cancel the real slot so the thread can exit
        cancel.set()
        t.join(timeout=2)
        assert slot_resolved.is_set()

    def test_resolving_twice_does_not_raise(self):
        cancel = _make_cancel()

        def _request():
            svc.request_tool_approval(
                "stream-dup", "call-1", "t", {}, _noop_publish, cancel
            )

        t = threading.Thread(target=_request, daemon=True)
        t.start()
        time.sleep(0.05)
        svc.resolve_tool_approval("stream-dup", "call-1", approved=True)
        t.join(timeout=2)
        # Second resolve against a now-gone slot must not raise
        svc.resolve_tool_approval("stream-dup", "call-1", approved=True)


# ---------------------------------------------------------------------------
# request_tool_approval
# ---------------------------------------------------------------------------

class TestRequestToolApproval:
    """
    request_tool_approval blocks until the call is resolved or the turn is
    cancelled.  It emits exactly one tool_approval_required event before blocking.
    """

    def test_returns_true_when_approved(self):
        cancel = _make_cancel()
        result: list[bool] = []

        def _request():
            result.append(
                svc.request_tool_approval(
                    "s1", "c1", "bash", {"cmd": "ls"}, _noop_publish, cancel
                )
            )

        t = threading.Thread(target=_request, daemon=True)
        t.start()
        time.sleep(0.05)
        svc.resolve_tool_approval("s1", "c1", approved=True)
        t.join(timeout=2)
        assert result == [True]

    def test_returns_false_when_denied(self):
        cancel = _make_cancel()
        result: list[bool] = []

        def _request():
            result.append(
                svc.request_tool_approval(
                    "s2", "c2", "bash", {}, _noop_publish, cancel
                )
            )

        t = threading.Thread(target=_request, daemon=True)
        t.start()
        time.sleep(0.05)
        svc.resolve_tool_approval("s2", "c2", approved=False)
        t.join(timeout=2)
        assert result == [False]

    def test_returns_false_when_cancel_event_fires(self):
        cancel = _make_cancel()
        result: list[bool] = []

        def _request():
            result.append(
                svc.request_tool_approval(
                    "s3", "c3", "bash", {}, _noop_publish, cancel
                )
            )

        t = threading.Thread(target=_request, daemon=True)
        t.start()
        time.sleep(0.05)
        cancel.set()
        t.join(timeout=2)
        assert result == [False]

    def test_emits_tool_approval_required_event(self):
        cancel = _make_cancel()
        events: list[dict] = []

        def _request():
            svc.request_tool_approval(
                "s4", "c4", "read_file", {"path": "/f"}, events.append, cancel
            )

        t = threading.Thread(target=_request, daemon=True)
        t.start()
        time.sleep(0.05)
        svc.resolve_tool_approval("s4", "c4", approved=True)
        t.join(timeout=2)

        assert len(events) == 1
        evt = events[0]
        assert evt["type"] == "tool_approval_required"
        assert evt["call_id"] == "c4"
        assert evt["name"] == "read_file"
        assert evt["args"] == {"path": "/f"}

    def test_pending_slot_cleaned_up_after_approval(self):
        """After a successful resolve the dict entry must be removed."""
        cancel = _make_cancel()

        t = threading.Thread(
            target=svc.request_tool_approval,
            args=("s5", "c5", "t", {}, _noop_publish, cancel),
            daemon=True,
        )
        t.start()
        time.sleep(0.05)
        svc.resolve_tool_approval("s5", "c5", approved=True)
        t.join(timeout=2)

        with svc._pending_approvals_lock:
            assert "s5" not in svc._pending_approvals

    def test_pending_slot_cleaned_up_after_cancel(self):
        """After a cancellation the dict entry must also be removed."""
        cancel = _make_cancel()

        t = threading.Thread(
            target=svc.request_tool_approval,
            args=("s6", "c6", "t", {}, _noop_publish, cancel),
            daemon=True,
        )
        t.start()
        time.sleep(0.05)
        cancel.set()
        t.join(timeout=2)

        with svc._pending_approvals_lock:
            assert "s6" not in svc._pending_approvals

    def test_multiple_concurrent_approvals_in_same_stream(self):
        """Two tool calls pending in the same stream must resolve independently."""
        cancel = _make_cancel()
        results: dict[str, bool | None] = {"c-a": None, "c-b": None}

        def _req_a():
            results["c-a"] = svc.request_tool_approval(
                "multi", "c-a", "tool_a", {}, _noop_publish, cancel
            )

        def _req_b():
            results["c-b"] = svc.request_tool_approval(
                "multi", "c-b", "tool_b", {}, _noop_publish, cancel
            )

        ta = threading.Thread(target=_req_a, daemon=True)
        tb = threading.Thread(target=_req_b, daemon=True)
        ta.start()
        tb.start()
        time.sleep(0.05)

        svc.resolve_tool_approval("multi", "c-a", approved=True)
        svc.resolve_tool_approval("multi", "c-b", approved=False)

        ta.join(timeout=2)
        tb.join(timeout=2)

        assert results["c-a"] is True
        assert results["c-b"] is False

    def test_multiple_concurrent_approvals_in_different_streams(self):
        """Two tool calls in different streams must not interfere."""
        cancel = _make_cancel()
        results: dict[str, bool | None] = {"sa": None, "sb": None}

        def _req(stream_id, call_id, key):
            results[key] = svc.request_tool_approval(
                stream_id, call_id, "t", {}, _noop_publish, cancel
            )

        ta = threading.Thread(target=_req, args=("stream-sa", "ca", "sa"), daemon=True)
        tb = threading.Thread(target=_req, args=("stream-sb", "cb", "sb"), daemon=True)
        ta.start()
        tb.start()
        time.sleep(0.05)

        svc.resolve_tool_approval("stream-sa", "ca", approved=False)
        svc.resolve_tool_approval("stream-sb", "cb", approved=True)

        ta.join(timeout=2)
        tb.join(timeout=2)

        assert results["sa"] is False
        assert results["sb"] is True


# ---------------------------------------------------------------------------
# Re-export contract
# ---------------------------------------------------------------------------

class TestReExport:
    """
    chat_turn_service re-exports resolve_tool_approval so routes_chat.py
    needs no additional import.  Verify the re-export is the same object.
    """

    def test_chat_turn_service_reexports_resolve_tool_approval(self):
        import chat_turn_service
        assert chat_turn_service.resolve_tool_approval is svc.resolve_tool_approval