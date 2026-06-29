"""AD-1081: room-Todo tag parser.

Agents drive the AD-1080 senior-validation Todo loop on a room's task work item
with four tags emitted in their room reply:

    [TODOS]                       a SENIOR seeds the plan (the room checklist)
    - Draft the API
    - Write the tests
    [/TODOS]

    [TODO_DONE n]                 a worker self-reports step n done (-> submitted)
    [TODO_CONFIRM n]              a SENIOR confirms step n (-> done)
    [TODO_REJECT n: reason]       a SENIOR rejects step n (-> rejected, back to work)

Step numbers are 1-based in the tags (human/agent friendly) and converted to
0-based indices here. This module is PURE (no I/O); the reply-pipeline step
applies the parsed result via the WorkItemStore and strips the tags.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_MAX_TODOS = 30

# BF-650: strip emoji/pictographs from agent-authored step labels (HXI #3).
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\u2705\u2714\u2728\u274C]"
)


def _clean_label(s: str) -> str:
    return _EMOJI_RE.sub("", s).replace("  ", " ").strip()

_TODOS_RE = re.compile(r"\[TODOS\](.*?)\[/TODOS\]", re.DOTALL | re.IGNORECASE)
_PLAN_RE = re.compile(r"\[PLAN\](.*?)\[/PLAN\]", re.DOTALL | re.IGNORECASE)
_DONE_RE = re.compile(r"\[TODO_DONE\s+(\d+)\]", re.IGNORECASE)
_CONFIRM_RE = re.compile(r"\[TODO_CONFIRM\s+(\d+)\]", re.IGNORECASE)
_REJECT_RE = re.compile(r"\[TODO_REJECT\s+(\d+)\s*:?\s*([^\]]*)\]", re.IGNORECASE)
# Any room-todo marker (cheap early-out before the per-tag work).
_ANY_RE = re.compile(
    r"\[/?(?:TODOS|PLAN|TODO_DONE|TODO_CONFIRM|TODO_REJECT)\b", re.IGNORECASE
)


@dataclass
class ParsedTodos:
    """The room-todo intents parsed from one reply. Indices are 0-based."""

    plan: list[str] | None = None
    submit: list[int] = field(default_factory=list)
    confirm: list[int] = field(default_factory=list)
    reject: list[tuple[int, str]] = field(default_factory=list)


def has_todo_tag(text: str) -> bool:
    """Cheap predicate: does ``text`` contain any room-todo marker?"""
    return bool(_ANY_RE.search(text or ""))


def _parse_plan_items(block: str) -> list[str]:
    items: list[str] = []
    for raw in re.split(r"[\n;]+", block or ""):
        line = raw.strip()
        line = re.sub(r"^[-*\u2022]\s+", "", line)        # markdown bullet
        line = re.sub(r"^\d+[.)]\s+", "", line).strip()   # ordered-list number
        line = _clean_label(line)                          # BF-650: drop emoji
        if line:
            items.append(line)
        if len(items) >= _MAX_TODOS:
            break
    return items


def parse_todo_tags(text: str) -> ParsedTodos:
    """Parse all room-todo tags from ``text``. Pure; never raises."""
    out = ParsedTodos()
    text = text or ""
    m = _TODOS_RE.search(text) or _PLAN_RE.search(text)
    if m:
        items = _parse_plan_items(m.group(1))
        if items:  # an empty tag is ignored (never silently clears the plan)
            out.plan = items
    for mm in _DONE_RE.finditer(text):
        n = int(mm.group(1))
        if n >= 1:
            out.submit.append(n - 1)
    for mm in _CONFIRM_RE.finditer(text):
        n = int(mm.group(1))
        if n >= 1:
            out.confirm.append(n - 1)
    for mm in _REJECT_RE.finditer(text):
        n = int(mm.group(1))
        if n >= 1:
            out.reject.append((n - 1, (mm.group(2) or "").strip()))
    return out


def strip_todo_tags(text: str) -> str:
    """Remove every room-todo tag from ``text`` (so they never reach the
    transcript). Returns the trimmed remainder."""
    text = text or ""
    for rx in (_TODOS_RE, _PLAN_RE, _DONE_RE, _CONFIRM_RE, _REJECT_RE):
        text = rx.sub("", text)
    return text.strip()


# AD-1085a: a numbered/bulleted plan line. ≥2 contiguous items are treated as
# an implicit plan when the agent narrated steps but never emitted [TODOS].
_NUM_ITEM_RE = re.compile(r"^\s*(?:\d+[.)]|[-*\u2022])\s+(.{3,200})$")


def derive_prose_plan(text: str, *, max_items: int = _MAX_TODOS) -> list[str]:
    """AD-1085a: derive an implicit plan from a numbered/bulleted list in prose.

    Returns the items only when there is ONE contiguous run of >=2 list lines
    (so a stray single bullet, or scattered numbers in prose, are ignored).
    Pure; never raises. Empty list = no confident plan found.
    """
    runs: list[list[str]] = []
    cur: list[str] = []
    for raw in (text or "").splitlines():
        m = _NUM_ITEM_RE.match(raw)
        if m:
            cur.append(_clean_label(m.group(1).strip()))
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    best = max(runs, key=len) if runs else []
    return best[:max_items] if len(best) >= 2 else []

