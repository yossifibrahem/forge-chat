"""Long-running chat turn orchestration and title generation."""
from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable

from openai import OpenAI

import app_config
from mcp_adapters import ContainerConversationRequired
import container_service
import mcp_service
import store
import streaming as stream_module

Publish = Callable[[dict], None]

# ── Tool approval ──────────────────────────────────────────────────────────────
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


def _request_tool_approval(
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
        _pending_approvals.get(stream_id, {}).pop(call_id, None)

    if cancel_event.is_set():
        return False
    return bool(slot["approved"])

_SET_TITLE_TOOL = {
    "type": "function",
    "function": {
        "name": "set_title",
        "description": "Set the conversation title.",
        "parameters": {
            "type": "object",
            "properties": {"title": {"type": "string", "description": "The conversation title."}},
            "required": ["title"],
        },
    },
}


def openai_client(body: dict | None = None) -> OpenAI:
    cfg = app_config.load_config()
    return OpenAI(
        api_key=cfg.get("api_key") or "sk-placeholder",
        base_url=cfg.get("api_base") or app_config.DEFAULT_API_BASE,
    )


def _messages_to_text(messages: list) -> str:
    lines = []
    for msg in messages:
        role = msg.get("role", "")
        if role not in {"user", "assistant"}:
            continue
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content if p.get("type") == "text")
        content = str(content).replace("\n\n", " ").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _extract_title(message) -> str:
    if message.tool_calls:
        return json.loads(message.tool_calls[0].function.arguments)["title"]

    reasoning = getattr(message, "reasoning_content", "") or ""
    json_match = re.search(r"<tool_call>\s*(\{.*?})\s*</tool_call>", reasoning, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))["arguments"]["title"]

    xml_match = re.search(r"<parameter=title>\s*(.*?)\s*</parameter>", reasoning, re.DOTALL)
    if xml_match:
        return xml_match.group(1).strip()

    raise ValueError("Model did not return a tool call")


def _generate_title(body: dict, messages: list) -> str | None:
    try:
        response = openai_client(body).chat.completions.create(
            model=body.get("model", "gpt-4o"),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Call set_title with a 2–5 word Title Case title for this conversation.\n"
                        "The title must name the specific subject, not describe the interaction.\n\n"
                        "Good: 'Fibonacci Sequence in Python', 'Docker Volume Permissions', 'JWT Token Expiry Bug'\n"
                        "Bad: 'Coding Help' (too vague), 'Asking About Docker' (action not topic), 'General Question' (meaningless)"
                    ),
                },
                {"role": "user", "content": _messages_to_text(messages[:4])},
            ],
            tools=[_SET_TITLE_TOOL],
            tool_choice="required",
            max_tokens=256,
            temperature=0.7,
        )
        return _extract_title(response.choices[0].message)
    except Exception:
        return None


def _parse_stream_payload(raw_event) -> dict | None:
    """Normalize a streaming event.

    streaming.stream_chat_completion now yields typed dicts internally. This
    helper keeps backwards compatibility with older tests/callers that still
    pass SSE strings.
    """
    if isinstance(raw_event, dict):
        return raw_event
    if not isinstance(raw_event, str):
        return None
    raw_event = raw_event.strip()
    if not raw_event.startswith("data: "):
        return None
    payload = raw_event[6:].strip()
    if payload == "[DONE]":
        return {"type": "done"}
    try:
        return json.loads(payload)
    except Exception:
        return None


def _save_turn(conv_id: str, title: str, messages: list, display_log: list, *, stream_id: str = "") -> None:
    if not conv_id:
        return
    data = store.load(conv_id) or {"id": conv_id, "created_at": ""}
    data.update({
        "title": title or data.get("title") or "Untitled",
        "messages": messages,
        "displayLog": display_log,
        "streaming": bool(stream_id),
        "working_directory": str(store.working_directory(conv_id)),
    })
    if stream_id:
        data["active_stream_id"] = stream_id
    else:
        data.pop("active_stream_id", None)
    store.save(conv_id, data)


def _log_with_partial(base_log: list, reasoning: str, text: str) -> list:
    return [
        *base_log,
        *([{"type": "thinking", "content": reasoning}] if reasoning else []),
        *([{"type": "message", "role": "assistant", "content": text}] if text else []),
    ]


def _tool_meta_by_name(body: dict) -> dict:
    return {tool.get("name"): tool for tool in body.get("mcp_tool_meta", []) if tool.get("name")}


def _tool_call_message(calls: list, content: str | None) -> dict:
    return {
        "role": "assistant",
        "content": content or None,
        "tool_calls": [
            {
                "id": call.get("id"),
                "type": "function",
                "function": {
                    "name": call.get("function", {}).get("name", ""),
                    "arguments": call.get("function", {}).get("arguments", "{}"),
                },
            }
            for call in calls
        ],
    }


def _safe_tool_args(raw_args: str) -> dict:
    try:
        return json.loads(raw_args or "{}")
    except Exception:
        return {}


def _run_mcp_call(conv_id: str, tool_meta: dict, call: dict, session_pool=None) -> tuple[dict, str]:
    name = call.get("function", {}).get("name", "")
    args = _safe_tool_args(call.get("function", {}).get("arguments", "{}"))
    server_name = tool_meta.get("server", "")
    server_config = mcp_service.find_server(server_name)
    if not server_config:
        return args, f"Error calling tool '{name}': MCP server '{server_name}' not found"
    try:
        if session_pool is not None:
            result = session_pool.invoke_tool(server_name, server_config, name, args)
        else:
            result = mcp_service.run_async(
                mcp_service.invoke_tool(
                    server_name,
                    server_config,
                    name,
                    args,
                    conv_id=conv_id,
                )
            )
    except ContainerConversationRequired as exc:
        result = str(exc)
    except Exception as exc:
        result = f"Error calling tool '{name}': {exc}"
    return args, result


class TurnRecorder:
    """Throttled persistence for a single assistant turn."""

    def __init__(self, conv_id: str, title: str, messages: list, stream_id: str) -> None:
        self.conv_id = conv_id
        self.title = title
        self.messages = messages
        self.stream_id = stream_id
        self.last_snapshot = {"at": 0.0, "size": -1}

    def update_title(self, title: str) -> None:
        self.title = title

    def save(self, display_log: list, reasoning: str = "", text: str = "", *, force: bool = False) -> None:
        now = time.monotonic()
        size = len(reasoning) + len(text) + len(display_log)
        if not force and now - self.last_snapshot["at"] < 0.75 and size - self.last_snapshot["size"] < 512:
            return
        self.last_snapshot.update({"at": now, "size": size})
        _save_turn(
            self.conv_id,
            self.title,
            self.messages,
            _log_with_partial(display_log, reasoning, text),
            stream_id=self.stream_id,
        )

    def finalize(self, display_log: list) -> None:
        _save_turn(self.conv_id, self.title, self.messages, display_log)


def run_persistent_chat_turn(body: dict, cancel_event: threading.Event, stream_id: str, publish: Publish) -> None:
    conv_id = body.get("conv_id", "")
    title = body.get("title") or "Untitled"
    turn_messages = list(body.get("conversation_messages") or [])
    display_log = list(body.get("display_log") or [])
    api_messages = list(body.get("messages") or [])
    tool_meta = _tool_meta_by_name(body)
    is_first_message = len([m for m in turn_messages if m.get("role") == "user"]) == 1
    recorder = TurnRecorder(conv_id, title, turn_messages, stream_id)
    assistant_completed = False
    session_pool = None

    def finalize_partial_answer(reasoning: str, text: str) -> bool:
        nonlocal assistant_completed
        if assistant_completed:
            return False
        if reasoning:
            display_log.append({"type": "thinking", "content": reasoning})
        if text:
            display_log.append({"type": "message", "role": "assistant", "content": text})
            turn_messages.append({"role": "assistant", "content": text})
        assistant_completed = bool(reasoning or text)
        return assistant_completed

    recorder.save(display_log, force=True)

    try:
        # Pre-mount host volumes for every enabled MCP server before the turn
        # begins. Without this, the container is set up lazily per-server and
        # gets recreated each time the model switches to a server whose host
        # path isn't yet mounted.
        if conv_id and body.get("mcp_tool_meta"):
            server_names = list({
                t.get("server", "") for t in body["mcp_tool_meta"] if t.get("server")
            })
            if server_names:
                extra_volumes = mcp_service.collect_all_extra_volumes(server_names)
                container_service.ensure_container(conv_id, extra_volumes)

        if conv_id and tool_meta:
            session_pool = mcp_service.McpSessionPool(conv_id)

        while not cancel_event.is_set():
            acc_text = ""
            acc_reasoning = ""
            tool_calls = []

            for raw in stream_module.stream_chat_completion(
                openai_client(body),
                model=body.get("model", "gpt-4o"),
                messages=api_messages,
                tools=body.get("tools", []),
                cancel_event=cancel_event,
                temperature=float(body.get("temperature", 0.7)),
            ):
                event = _parse_stream_payload(raw)
                if not event:
                    continue
                etype = event.get("type")
                if etype == "done":
                    break
                if etype == "tool_calls":
                    tool_calls = event.get("calls") or []
                    continue

                if etype == "reasoning":
                    acc_reasoning += event.get("content", "")
                    recorder.save(display_log, acc_reasoning, acc_text)
                elif etype == "text":
                    acc_text += event.get("content", "")
                    recorder.save(display_log, acc_reasoning, acc_text)

                publish(event)

            if cancel_event.is_set():
                if finalize_partial_answer(acc_reasoning, acc_text):
                    recorder.save(display_log, force=True)
                break

            if tool_calls:
                if acc_reasoning:
                    display_log.append({"type": "thinking", "content": acc_reasoning})
                if acc_text:
                    display_log.append({"type": "message", "role": "assistant", "content": acc_text})
                tool_message = _tool_call_message(tool_calls, acc_text or None)
                turn_messages.append(tool_message)
                api_messages.append(tool_message)

                for call in tool_calls:
                    name = call.get("function", {}).get("name", "")
                    meta = tool_meta.get(name, {})
                    call_id = call.get("id", "")
                    args_preview = _safe_tool_args(call.get("function", {}).get("arguments", "{}"))

                    # ── Approval gate ──────────────────────────────────────────
                    if not meta.get("autoApprove", False):
                        approved = _request_tool_approval(
                            stream_id, call_id, name, args_preview, publish, cancel_event
                        )
                        if not approved or cancel_event.is_set():
                            result = "Tool call denied by user."
                            deny_event = {
                                "type": "tool_result",
                                "name": name,
                                "args": args_preview,
                                "result": result,
                                "denied": True,
                            }
                            display_log.append({"type": "tool_result", **{k: v for k, v in deny_event.items() if k != "type"}})
                            turn_messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
                            api_messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
                            recorder.save(display_log, force=True)
                            publish(deny_event)
                            continue
                    # ──────────────────────────────────────────────────────────

                    # Let the client show the actual running state even when the
                    # server auto-approves the call and no approval UI is shown.
                    publish({"type": "tool_running", "name": name, "args": args_preview})

                    args, result = _run_mcp_call(conv_id, meta, call, session_pool)
                    # displayName is intentionally omitted here — the JS adapter system
                    # (tool_adapters/) is the single source of truth for display labels.
                    # Each adapter declares a `labelArg` (default: 'description') that
                    # getToolDisplayLabel() reads to pick the right argument, so adding
                    # a new tool with a different label key requires only a new adapter file.
                    event = {
                        "type": "tool_result",
                        "name": name,
                        "args": args,
                        "result": result,
                    }
                    display_log.append({"type": "tool_result", **{k: v for k, v in event.items() if k != "type"}})
                    turn_messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
                    api_messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
                    recorder.save(display_log, force=True)
                    publish(event)
                continue

            finalize_partial_answer(acc_reasoning, acc_text)
            recorder.save(display_log, force=True)
            publish({"type": "assistant_done", "messages": turn_messages, "displayLog": display_log})
            break

        if assistant_completed and is_first_message and not cancel_event.is_set() \
                and body.get("auto_generate_titles", True):
            generated_title = _generate_title(body, turn_messages)
            if generated_title:
                recorder.update_title(generated_title)
                publish({"type": "title", "title": generated_title})
                recorder.save(display_log, force=True)

        recorder.finalize(display_log)
    except Exception as exc:
        publish({"type": "error", "message": str(exc)})
        recorder.finalize(display_log)
    finally:
        if session_pool is not None:
            session_pool.close()
