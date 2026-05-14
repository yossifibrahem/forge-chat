"""Title generation for conversations."""
from __future__ import annotations

import json
import re


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


def generate_title(client, body: dict, messages: list) -> str | None:
    """Generate a short title for a conversation using the model.

    Returns the generated title string, or None on failure.
    """
    try:
        response = client.chat.completions.create(
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
