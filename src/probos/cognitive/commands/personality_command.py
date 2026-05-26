"""AD-809: /personality <name|list|clear> slash command."""

from __future__ import annotations

from typing import Any

from probos.cognitive.personality_registry import (
    list_personalities,
    resolve_personality_text,
)
from probos.threads import ChatThreadStore


def is_personality_command(message: str) -> bool:
    """True if the message starts with ``/personality`` (case-sensitive).

    NOTE: callers MUST strip leading @-mentions before testing (the
    inline-callsign branch in ``routers/chat.py`` receives raw
    ``@Ezri /personality formal``). The ``agent_chat`` handler in
    ``routers/agents.py`` receives stripped messages already (the
    agent identity is path-routed, not in the body).
    """
    return message.strip().startswith("/personality")


def handle_personality_command(
    message: str,
    *,
    thread_id: str,
    store: ChatThreadStore,
) -> dict[str, Any]:
    """Parse and apply a ``/personality`` command.

    Returns a dict with ``system_reply`` (text to surface to the
    operator), ``applied`` (the registry key that was set, or None),
    and ``available`` (the registry keys list for UI hints).
    """
    parts = message.strip().split(maxsplit=1)
    arg = parts[1].strip().lower() if len(parts) > 1 else ""

    if arg == "" or arg == "list":
        available = list_personalities()
        return {
            "system_reply": (
                "Available personalities: " + ", ".join(available) +
                ". Use `/personality <name>` to apply, or "
                "`/personality clear` to reset."
            ),
            "applied": None,
            "available": available,
        }

    if arg == "clear":
        store.set_personality_override(thread_id, override=None)
        return {
            "system_reply": (
                "Personality cleared; using the agent's default register."
            ),
            "applied": None,
            "available": list_personalities(),
        }

    text = resolve_personality_text(arg)
    if text is None:
        return {
            "system_reply": (
                f"Unknown personality `{arg}`. Available: " +
                ", ".join(list_personalities())
            ),
            "applied": None,
            "available": list_personalities(),
        }

    store.set_personality_override(thread_id, override=text)
    return {
        "system_reply": (
            f"Personality set to `{arg}` for this thread. The agent will "
            f"adopt this register on subsequent turns."
        ),
        "applied": arg,
        "available": list_personalities(),
    }
