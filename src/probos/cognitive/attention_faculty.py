"""AD-1029: the ``AttentionFaculty`` — a per-agent, deterministic attention organ.

The **AttentionFaculty** is the pilot **Cognitive Organ** (AD-1033) of the
Composable-Cognition / Attention epic (#975, #983) and the heart of the answer to
"could the controller be a deterministic agent each cognitive agent is paired with?"
— **yes, as a paired cognitive organ, not a mesh peer**
(``docs/development/attention-architecture.md`` §3, §4).

It is a child component of one ``CognitiveAgent``: born with its parent, dies with its
parent, identity namespaced under it (``{parent_id}.attention``). It is **not**
registered in the agent registry, **not** addressable on the mesh, has **no** trust
score / vote / consensus standing. Its job is to *drive* the AD-1028
``ContextAssembler``: it collects the per-turn context **bids**, merges in any
**exogenous** bids accumulated between turns, selects/orders the survivors under the
global token budget, and writes an **audit trace** of the bid competition.

The discipline (the load-bearing properties — §2, §4, §7):

* **Deterministic — NO LLM.** Salience is the bid's existing fixed insertion priority
  (AD-1028); there is no salience *scoring* here (that is AD-1030). Arbitration is
  arithmetic, not reasoning.
* **Synchronous & in-process on the hot path.** ``arbitrate`` runs
  ``perceive → decide → act`` with **no** ``await`` and **no** intent-bus round-trip —
  a NATS hop inside prompt assembly would tax every reply.
* **Mesh subscriber for exogenous salience only.** Mentions/alerts/camera-change/gossip
  that arrive **between** turns enter through the agent-owned spine inlet
  (``deliver_exogenous`` → ``EXOGENOUS_SIGNAL_KIND`` → ``on_signal``) and update the
  faculty's *pending* state, visible to the **next** ``perceive``. The faculty never
  touches the intent bus itself (sovereignty / AD-397); wiring the real bus is AD-1032.
* **Behavior-preserving.** With the faculty composed, **no** pending exogenous, and v1
  fixed salience, ``arbitrate(bids, token_budget=B)`` returns **exactly**
  ``ContextAssembler.assemble(bids, token_budget=B)`` — the proof that the faculty is a
  faithful *driver* before any adaptivity lands. (Default-OFF, the faculty is not even
  constructed, so the AD-1028 inline path runs unchanged — see ``cognitive_agent.py``.)

What this AD deliberately does **not** do (kept for later phases so v1 is provably
behavior-preserving): real salience math (AD-1030), camera/visual-scene gating
(AD-1031), arousal/zone reconfiguration and real intent-bus wiring (AD-1032).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from probos.cognitive.attention import AttentionBid, ContextAssembler, estimate_tokens
from probos.cognitive.organ import BaseCognitiveOrgan, OrganAuditEmit
from probos.cognitive.spine import EXOGENOUS_SIGNAL_KIND

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal cycle-context objects. The faculty's ``perceive → decide → act`` is
# polymorphic on the context so it is safe to drive from BOTH:
#   (1) ``arbitrate`` — the per-turn synchronous entry point, which hands in an
#       ``_Arbitration`` carrying the per-turn bids + the global token budget; and
#   (2) the spine's generic ``drive_cycle`` — which hands in the raw observation
#       dict (no per-turn bids). For (2) the cycle is a deterministic no-op: no
#       drain, no assemble, no audit. Exogenous bids are accumulated by
#       ``on_signal`` and drained ONCE, at ``arbitrate`` time, so a between-turns
#       signal stays visible to the NEXT turn's arbitration.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Arbitration:
    """Per-turn arbitration context handed to ``perceive`` by ``arbitrate``."""

    bids: list[AttentionBid]
    token_budget: int


@dataclass(frozen=True)
class _Perception:
    """Output of ``perceive``: the merged bid set + the budget to assemble under.

    ``assemble`` is True only when this perception was produced from an
    ``_Arbitration`` (the real per-turn path); a generic ``drive_cycle`` observation
    yields ``assemble=False`` so ``decide``/``act`` short-circuit to a no-op.
    """

    assemble: bool
    merged_bids: list[AttentionBid]
    token_budget: int
    exogenous_drained: int


@dataclass(frozen=True)
class _Decision:
    """Output of ``decide``: the assembled survivor strings + competition metadata.

    The survivor strings are what ``arbitrate`` returns (the prompt). The remaining
    fields are the *audit* of the bid competition — a pure side-effect recorded by
    ``act`` that never changes the assembled prompt.
    """

    assemble: bool
    survivors: list[str]
    bids_in: int
    survivor_count: int
    dropped: int
    token_budget: int
    used_tokens: int
    pinned_in: int
    exogenous_drained: int
    sources: list[str]


class AttentionFaculty(BaseCognitiveOrgan):
    """A deterministic, per-agent attention organ that drives the AD-1028 assembler.

    Composed onto a ``CognitiveAgent``'s spine (AD-1034) only when
    ``memory.attention.enabled`` is True; default-OFF it is never constructed and the
    agent is byte-identical to pre-AD-1029. Subscribes to the spine's
    ``EXOGENOUS_SIGNAL_KIND`` for between-turn salience; arbitrates the per-turn context
    window synchronously via :meth:`arbitrate`.
    """

    #: Organ kind → ``organ_id`` is ``{parent_id}.attention`` (AD-1033).
    default_name = "attention"

    def __init__(self, *, name: str | None = None, emit: OrganAuditEmit | None = None) -> None:
        super().__init__(name=name, emit=emit)
        # Exogenous bids accumulated between turns (via ``on_signal``), drained at the
        # next ``arbitrate``. Persistent organ state across cognitive cycles (the
        # five-part organ test, §2.1 part 2).
        self._pending_exogenous: list[AttentionBid] = []
        # Most recent bid-competition audit payload (introspection only). The audit is
        # ALSO emitted through the injected ``OrganAuditEmit`` sink in :meth:`act`.
        self._last_audit: dict[str, Any] | None = None

    # -- introspection --------------------------------------------------

    @property
    def pending_exogenous_count(self) -> int:
        """Number of exogenous bids accumulated since the last ``arbitrate`` drain."""
        return len(self._pending_exogenous)

    @property
    def last_audit(self) -> dict[str, Any] | None:
        """A copy of the most recent bid-competition audit payload, or ``None``."""
        return dict(self._last_audit) if self._last_audit is not None else None

    # -- exogenous intake (mesh subscriber; between-turn salience) ------

    def on_signal(self, kind: str, payload: Any) -> None:
        """Receive a spine signal; stash exogenous salience as a pending bid.

        Spine convention (AD-1034): the agent-owned inlet ``deliver_exogenous`` forwards
        a mesh-sourced signal on the in-process channel under ``EXOGENOUS_SIGNAL_KIND``.
        We coerce the payload into an :class:`AttentionBid` and hold it *pending* until
        the next :meth:`arbitrate` drains it — so a signal delivered between turns is
        visible to the next turn's competition. Synchronous; never touches the bus.
        """
        if kind != EXOGENOUS_SIGNAL_KIND:
            return
        bid = self._coerce_exogenous_bid(payload)
        if bid is not None:
            self._pending_exogenous.append(bid)

    # -- the cognitive cycle (sync, deterministic, NO LLM / NO await) ---

    def perceive(self, context: Any) -> _Perception:
        """Cycle step 1 — drain pending exogenous bids and merge with the per-turn bids.

        Polymorphic: only an ``_Arbitration`` (the per-turn path) drains and merges; a
        generic ``drive_cycle`` observation yields a no-assemble perception so the rest
        of the cycle is a deterministic no-op (exogenous bids are drained ONCE, at
        ``arbitrate`` time, so they stay visible to the next turn).
        """
        if not isinstance(context, _Arbitration):
            return _Perception(assemble=False, merged_bids=[], token_budget=0, exogenous_drained=0)
        drained = self._drain_pending_exogenous(base=len(context.bids))
        merged = list(context.bids) + drained
        return _Perception(
            assemble=True,
            merged_bids=merged,
            token_budget=context.token_budget,
            exogenous_drained=len(drained),
        )

    def decide(self, observation: Any) -> _Decision:
        """Cycle step 2 — select/order/render the survivors under the token budget.

        Delegates the selection to the pure AD-1028 :meth:`ContextAssembler.assemble`
        (v1 salience = the bid's fixed insertion priority; NO salience scoring — AD-1030).
        With no pending exogenous, the merged set is exactly the per-turn bids, so the
        survivors are byte-identical to the inline ``assemble`` path. A no-assemble
        perception (the ``drive_cycle`` path) short-circuits to an empty decision.
        """
        if not isinstance(observation, _Perception) or not observation.assemble:
            return _Decision(
                assemble=False, survivors=[], bids_in=0, survivor_count=0, dropped=0,
                token_budget=0, used_tokens=0, pinned_in=0, exogenous_drained=0, sources=[],
            )
        survivors = ContextAssembler.assemble(
            observation.merged_bids, token_budget=observation.token_budget
        )
        bids_in = len(observation.merged_bids)
        used_tokens = sum(estimate_tokens(text) for text in survivors)
        return _Decision(
            assemble=True,
            survivors=survivors,
            bids_in=bids_in,
            survivor_count=len(survivors),
            dropped=bids_in - len(survivors),
            token_budget=observation.token_budget,
            used_tokens=used_tokens,
            pinned_in=sum(1 for bid in observation.merged_bids if bid.pin),
            exogenous_drained=observation.exogenous_drained,
            sources=[bid.source for bid in observation.merged_bids],
        )

    def act(self, decision: Any) -> None:
        """Cycle step 3 — write the bid-competition audit trace (a pure side-effect).

        Records "why did the agent attend to X?" — how many bids competed, how many won
        / lost, the budget and tokens used, and the competing sources — to the most
        recent-audit introspection slot AND through the injected ``OrganAuditEmit`` sink
        (default no-op; the agent wires a real sink). The audit NEVER changes the
        assembled prompt: ``arbitrate`` returns the survivors regardless. The
        ``drive_cycle`` no-assemble path records nothing.
        """
        if not isinstance(decision, _Decision) or not decision.assemble:
            return None
        payload: dict[str, Any] = {
            "bids_in": decision.bids_in,
            "survivors": decision.survivor_count,
            "dropped": decision.dropped,
            "token_budget": decision.token_budget,
            "used_tokens": decision.used_tokens,
            "pinned": decision.pinned_in,
            "exogenous": decision.exogenous_drained,
            "sources": list(decision.sources),
        }
        self._last_audit = payload
        # Inherited helper: wraps {organ_id, phase} + payload and hands it to the sync
        # ``OrganAuditEmit`` sink; never raises (log-and-degrade).
        self._emit_audit_trace("arbitrate", payload)
        return None

    # -- synchronous per-turn entry point (called by _build_user_message) --

    def arbitrate(self, bids: list[AttentionBid], *, token_budget: int) -> list[str]:
        """Run one synchronous arbitration and return the assembled survivor strings.

        Drives ``perceive`` (merge pending exogenous) → ``decide`` (assemble under the
        budget) → ``act`` (audit), and returns the survivors. With NO pending exogenous
        and v1 fixed salience this returns **exactly**
        ``ContextAssembler.assemble(bids, token_budget=token_budget)`` — the byte-identical
        "faithful driver" guarantee. NO ``await``, NO intent-bus call on this path.
        """
        perception = self.perceive(_Arbitration(bids=list(bids), token_budget=int(token_budget)))
        decision = self.decide(perception)
        self.act(decision)
        return list(decision.survivors)

    # -- internals ------------------------------------------------------

    def _drain_pending_exogenous(self, *, base: int) -> list[AttentionBid]:
        """Move the pending exogenous bids out and order them after the per-turn bids.

        v1 places each drained exogenous bid deterministically AFTER the per-turn bids
        by continuing the SAME fixed-insertion-priority scheme ``_build_user_message``
        uses (``salience == zone_floor == index``). This is fixed priority, NOT salience
        scoring (AD-1030) and NOT arousal/zone reconfiguration (AD-1032).
        """
        drained = self._pending_exogenous
        self._pending_exogenous = []
        for offset, bid in enumerate(drained):
            slot = base + offset
            bid.zone_floor = slot
            bid.salience = float(slot)
        return drained

    def _coerce_exogenous_bid(self, payload: Any) -> AttentionBid | None:
        """Coerce a mesh-sourced exogenous signal payload into an :class:`AttentionBid`.

        Boundary coercion (Defense in Depth): accepts a ready ``AttentionBid``, a plain
        string, or a mapping carrying ``render`` (callable) / ``text`` (str) plus optional
        ``source``/``modality``/``token_cost``/``pin``; otherwise renders ``str(payload)``.
        Returns ``None`` for an empty/None payload so a meaningless signal adds no bid.
        Richer intent-payload shapes are wired by AD-1032.
        """
        if payload is None:
            return None
        if isinstance(payload, AttentionBid):
            return payload
        if isinstance(payload, str):
            return self._text_bid("exogenous", payload, modality="exogenous") if payload else None
        if isinstance(payload, Mapping):
            source = str(payload.get("source", "exogenous"))
            modality = str(payload.get("modality", "exogenous"))
            pin = bool(payload.get("pin", False))
            render = payload.get("render")
            if callable(render):
                return AttentionBid(
                    source=source,
                    render=render,
                    modality=modality,
                    token_cost=int(payload.get("token_cost", 0)),
                    pin=pin,
                )
            text = payload.get("text")
            if isinstance(text, str) and text:
                return self._text_bid(source, text, modality=modality, pin=pin)
            return None
        text = str(payload)
        return self._text_bid("exogenous", text, modality="exogenous") if text else None

    @staticmethod
    def _text_bid(source: str, text: str, *, modality: str = "exogenous", pin: bool = False) -> AttentionBid:
        """Build a text :class:`AttentionBid` with a lazy renderer returning ``text``."""
        return AttentionBid(
            source=source,
            render=(lambda _t=text: _t),
            modality=modality,
            token_cost=estimate_tokens(text),
            pin=pin,
        )
