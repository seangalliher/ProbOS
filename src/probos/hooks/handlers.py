"""AD-1012: lifecycle-hook handlers that bridge ProbOS policy stores into the
:class:`~probos.hooks.bus.HookBus` (AD-1004).

The first handler is the **per-agent capability gate**: it turns the inline
AD-1007 :class:`~probos.cognitive.intent_grants.IntentGrantStore` check into a
pluggable ``PreDispatch`` hook, so Capability-Pack hooks (#948) and a future
consensus handler can gate at the same lifecycle point with
most-restrictive-wins aggregation.

The handlers are pure policy adapters — they read a context dict and return a
:class:`~probos.hooks.bus.HookResult` (or ``None`` to abstain). They never raise
for routine "no opinion" cases; the bus's own honest-degrade still protects the
loop if a store misbehaves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from probos.hooks.bus import HookDecision, HookResult

if TYPE_CHECKING:
    from probos.cognitive.intent_grants import IntentGrantStore
    from probos.hooks.bus import HookHandler

_CAPABILITY_GATE_ID = "capability_gate"


def make_capability_gate_handler(
    intent_grant_store: IntentGrantStore,
) -> HookHandler:
    """Build a ``PreDispatch`` handler enforcing the per-agent capability gate.

    The handler reads ``agent_id`` and ``intent_name`` (``intent`` is also
    accepted) from the hook context and consults
    :meth:`IntentGrantStore.resolve_sync`. An explicit ``restricted`` resolution
    — a Captain capability disable, which wins by agent-precedence — returns
    :attr:`HookDecision.DENY`; ``granted`` / ``no_opinion`` return
    :attr:`HookDecision.ALLOW` so the role/ship default falls through. A context
    missing either field returns ``None`` (abstain), so a malformed fire is
    treated as no-opinion rather than a spurious deny.
    """

    def capability_gate(ctx: dict[str, Any]) -> HookResult | None:
        agent_id = ctx.get("agent_id")
        intent_name = ctx.get("intent_name") or ctx.get("intent")
        if not agent_id or not intent_name:
            return None
        resolution = intent_grant_store.resolve_sync(agent_id, intent_name)
        if resolution == "restricted":
            return HookResult(
                decision=HookDecision.DENY,
                reason=f"capability '{intent_name}' is disabled for {agent_id}",
                handler_id=_CAPABILITY_GATE_ID,
            )
        return HookResult(
            decision=HookDecision.ALLOW, handler_id=_CAPABILITY_GATE_ID
        )

    return capability_gate
