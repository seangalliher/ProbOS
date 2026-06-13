"""AD-1004: lifecycle-hook bus — deterministic interception at agent-loop points.

The cross-tool hook model (VS Code / Claude Code / GitHub Copilot) expressed in
ProbOS terms: named lifecycle events (``SessionStart``, ``PreToolUse``,
``PostToolUse``, ``PreDispatch``, …) where handlers run, and on the *pre* gates
return an ``allow`` / ``ask`` / ``deny`` verdict aggregated **most-restrictive-
wins** (``deny`` > ``ask`` > ``allow``) — exactly the VS Code precedence.

This is the substrate two larger pieces plug into:

* The **per-agent capability gate** (epic #944): a ``PreDispatch`` handler checks
  whether the *originating* agent is granted a write intent (authorization),
  layered with — not replacing — the consensus gate (per-call safety).
* **Capability Packs** (AD-1003): packs attach lifecycle hooks; this bus is where
  they fire.

**Scope of this slice = the BUS MECHANISM only.** It is intentionally NOT wired
into the live dispatch path yet (mechanism-first / conservative-wiring
discipline — cf. the AD-979b/c retrieval-mechanism precedent). Firing an event
with no registered handlers is a no-op, so the bus is inert until handlers and
wiring land in a follow-up. Command-based (shell) hooks for portable packs are
also a later concern; this slice is in-process callable handlers.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


class HookEvent(str, Enum):
    """Lifecycle points where hooks fire.

    Mirrors the cross-tool hook event set (VS Code / Claude — ``SessionStart``,
    ``UserPromptSubmit``, ``PreToolUse``, ``PostToolUse``, ``SubagentStart``,
    ``SubagentStop``, ``Stop``) for Capability-Pack portability, plus ProbOS's
    mesh-dispatch points (``PreDispatch`` / ``PostDispatch``) — the natural home
    for the per-agent write-intent gate.
    """

    SESSION_START = "session_start"
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    PRE_TOOL_USE = "pre_tool_use"        # gate: before a tool invocation
    POST_TOOL_USE = "post_tool_use"      # observational
    PRE_DISPATCH = "pre_dispatch"        # gate: before a mesh intent is dispatched
    POST_DISPATCH = "post_dispatch"      # observational
    SUBAGENT_START = "subagent_start"
    SUBAGENT_STOP = "subagent_stop"
    STOP = "stop"


# The "gate" events where a deny/ask verdict is meaningful. For all other events
# handlers still run (side effects: logging, metrics, pack hooks) but their
# return value is ignored.
_GATE_EVENTS = frozenset({HookEvent.PRE_TOOL_USE, HookEvent.PRE_DISPATCH})


class HookDecision(str, Enum):
    """A pre-gate handler's verdict."""

    ALLOW = "allow"
    ASK = "ask"      # surface to the human (Captain) for approval
    DENY = "deny"


# Restrictiveness ordering for aggregation: higher wins (deny > ask > allow).
_DECISION_ORDER: dict[HookDecision, int] = {
    HookDecision.ALLOW: 0,
    HookDecision.ASK: 1,
    HookDecision.DENY: 2,
}


@dataclass(frozen=True)
class HookResult:
    """One handler's verdict on a gate event. ``None`` from a handler means
    "no opinion" (observational / abstain)."""

    decision: HookDecision = HookDecision.ALLOW
    reason: str = ""
    handler_id: str = ""


@dataclass(frozen=True)
class AggregateDecision:
    """The bus's aggregated verdict for a gate event.

    ``decision`` is the most-restrictive verdict across all handlers;
    ``reasons`` / ``handler_ids`` carry the non-allow contributors so the
    caller (and the HXI) can explain *why* something was asked/denied.
    """

    decision: HookDecision = HookDecision.ALLOW
    reasons: list[str] = field(default_factory=list)
    handler_ids: list[str] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.decision == HookDecision.ALLOW

    @property
    def asked(self) -> bool:
        return self.decision == HookDecision.ASK

    @property
    def denied(self) -> bool:
        return self.decision == HookDecision.DENY


# A handler: sync or async callable taking a context dict, returning a
# ``HookResult`` (or ``None`` = no opinion / observational-only).
HookHandler = Callable[
    [dict[str, Any]], "HookResult | None | Awaitable[HookResult | None]"
]


class HookBus:
    """In-process lifecycle-hook dispatcher.

    Register handlers per event; :meth:`fire` runs them all in registration
    order. For gate events (``PRE_TOOL_USE`` / ``PRE_DISPATCH``) the verdicts
    aggregate most-restrictive-wins (``deny`` > ``ask`` > ``allow``). For
    observational events the return values are ignored (handlers run purely for
    side effects).

    **Tier-2 honest-degrade:** a handler that raises is logged and contributes
    NO verdict — the bus must never brick the agent loop, and the real safety
    gate (consensus) is a separate, independent control. The bus is neutral
    plumbing; policy lives in the handlers.
    """

    def __init__(self) -> None:
        self._handlers: dict[HookEvent, list[tuple[str, HookHandler]]] = {}

    # ------------------------------------------------------------------
    # registration
    # ------------------------------------------------------------------

    def register(
        self, event: HookEvent, handler: HookHandler, *, handler_id: str = "",
    ) -> str:
        """Register ``handler`` for ``event``. Returns the resolved handler id
        (the given ``handler_id``, else the callable's ``__name__``)."""
        hid = handler_id or getattr(handler, "__name__", "") or "anonymous_hook"
        self._handlers.setdefault(event, []).append((hid, handler))
        return hid

    def unregister(self, event: HookEvent, handler_id: str) -> bool:
        """Remove all handlers registered under ``handler_id`` for ``event``.
        Returns True if anything was removed."""
        lst = self._handlers.get(event)
        if not lst:
            return False
        kept = [(hid, h) for hid, h in lst if hid != handler_id]
        removed = len(kept) < len(lst)
        self._handlers[event] = kept
        return removed

    def handler_count(self, event: HookEvent) -> int:
        return len(self._handlers.get(event, []))

    # ------------------------------------------------------------------
    # dispatch
    # ------------------------------------------------------------------

    async def fire(
        self, event: HookEvent, context: dict[str, Any] | None = None,
    ) -> AggregateDecision:
        """Run every handler registered for ``event``.

        For gate events, returns the aggregated most-restrictive verdict. For
        observational events (or when no handlers are registered), returns a
        default ``ALLOW`` — so an unwired bus never blocks anything.
        """
        ctx = context or {}
        handlers = list(self._handlers.get(event, []))
        is_gate = event in _GATE_EVENTS
        worst = HookDecision.ALLOW
        reasons: list[str] = []
        ids: list[str] = []

        for hid, handler in handlers:
            try:
                res = handler(ctx)
                if asyncio.iscoroutine(res):
                    res = await res
            except Exception:
                logger.warning(
                    "AD-1004: hook handler %r raised on %s; skipped (contributes "
                    "no verdict). The independent consensus gate still applies.",
                    hid, event.value, exc_info=True,
                )
                continue
            if not is_gate or res is None:
                continue
            if _DECISION_ORDER[res.decision] > _DECISION_ORDER[worst]:
                worst = res.decision
            if res.decision != HookDecision.ALLOW:
                reasons.append(res.reason or hid)
                ids.append(res.handler_id or hid)

        return AggregateDecision(decision=worst, reasons=reasons, handler_ids=ids)
