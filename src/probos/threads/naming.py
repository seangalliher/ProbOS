"""AD-794 + AD-809: thread naming + personality resolution helpers.

These two ride on the AD-791 substrate and stay deliberately small.

AD-794 — auto-name
    ``suggest_title(body)`` synthesizes a thread title from the first
    user message. v1 is a heuristic (strip, collapse, truncate); an
    LLM-backed variant lands in AD-794a once the substrate has real
    usage data to compare against.

AD-809 — personality override
    ``resolve_personality(thread, default)`` returns the agent's
    rendered personality for a given thread. Consumers (channel
    adapters, wardroom router, /api/agent/{id}/chat handler) call this
    in their prompt-assembly path. v1 returns the per-thread override
    if set, else the supplied default. The full per-channel/per-agent
    matrix is AD-809a.
"""

from __future__ import annotations

import re

from probos.threads import ChatThread

_WHITESPACE_RE = re.compile(r"\s+")
_TITLE_MAX_LEN = 60


def suggest_title(body: str, *, max_len: int = _TITLE_MAX_LEN) -> str:
    """Return a short title derived from the first message body.

    Strategy: take the first sentence (split on ``.``/``!``/``?``),
    collapse whitespace, strip leading punctuation, truncate with
    ellipsis if longer than ``max_len``. Empty bodies fall back to
    ``"New thread"`` so the UI always has something to render.
    """
    if not body or not body.strip():
        return "New thread"
    text = body.strip()
    # First sentence
    for term in (". ", "! ", "? ", "\n"):
        idx = text.find(term)
        if 0 < idx < max_len * 2:
            text = text[:idx]
            break
    text = _WHITESPACE_RE.sub(" ", text).strip(" \t\r\n.!?,:;-—\"'`")
    if not text:
        return "New thread"
    if len(text) <= max_len:
        return text
    cutoff = text.rfind(" ", 0, max_len - 1)
    if cutoff < max_len // 2:
        cutoff = max_len - 1
    return text[:cutoff].rstrip() + "…"


def resolve_personality(thread: ChatThread | None, *, default: str = "") -> str:
    """Resolve which personality string to apply for ``thread``.

    Returns ``thread.personality_override`` when set + non-empty;
    otherwise the ``default`` (typically the agent's standing
    personality from its CrewProfile). Returns ``default`` when
    ``thread`` is None so callers can use this in the legacy
    "no-thread implicit chat" path too.
    """
    if thread is None:
        return default
    override = thread.personality_override
    if override and override.strip():
        return override
    return default
