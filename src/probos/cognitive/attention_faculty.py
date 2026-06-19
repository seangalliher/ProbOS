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
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from probos.cognitive.attention import AttentionBid, ContextAssembler, estimate_tokens
from probos.cognitive.circuit_breaker import CognitiveZone
from probos.cognitive.organ import BaseCognitiveOrgan, OrganAuditEmit
from probos.cognitive.spine import EXOGENOUS_SIGNAL_KIND

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AD-1032: arousal model constants (Captain-approved policy, 2026-06-19).
#
# An exogenous EVENT raises a FACULTY-LOCAL cognitive zone (AD-588 ``CognitiveZone``
# is REUSED — AMBER is the policy's "YELLOW"); the zone NARROWS the bid competition
# (Yerkes–Dodson attentional narrowing) and DECAYS back to GREEN. This is the
# cognitive-layer mirror of HXI Design Principle #9 (LCARS Red-Alert). The zone is
# the faculty's OWN — it NEVER touches the agent's circuit-breaker zone.
# ---------------------------------------------------------------------------

#: Severity → zone, keyed on the NORMALIZED event_type (a leading ``exogenous_``
#: prefix is stripped, so both the EventType taxonomy values, e.g.
#: ``"exogenous_alert"``, and the short tags, e.g. ``"alert"``, map here).
#: alert/consensus/safety → RED; mention → AMBER; scene_change/gossip → GREEN
#: (GREEN only queues — a single low-severity event does not reconfigure; the same
#: low-severity type REPEATING within the window escalates GREEN→AMBER).
_SEVERITY_BY_EVENT: dict[str, CognitiveZone] = {
    "alert": CognitiveZone.RED,
    "consensus": CognitiveZone.RED,
    "safety": CognitiveZone.RED,
    "mention": CognitiveZone.AMBER,
    "scene_change": CognitiveZone.GREEN,
    "gossip": CognitiveZone.GREEN,
}

#: Optional explicit ``severity`` field on an event → zone (can only RAISE the
#: event_type baseline, never lower it; ``max`` by rank in :meth:`_zone_for_event`).
_ZONE_BY_SEVERITY: dict[str, CognitiveZone] = {
    "red": CognitiveZone.RED,
    "critical": CognitiveZone.RED,
    "high": CognitiveZone.RED,
    "amber": CognitiveZone.AMBER,
    "yellow": CognitiveZone.AMBER,
    "medium": CognitiveZone.AMBER,
    "green": CognitiveZone.GREEN,
    "low": CognitiveZone.GREEN,
}

#: Arousal-only ordering of the zones (CRITICAL is never set by arousal — the
#: severity table maxes at RED — but is ranked for completeness).
_ZONE_RANK: dict[CognitiveZone, int] = {
    CognitiveZone.GREEN: 0,
    CognitiveZone.AMBER: 1,
    CognitiveZone.RED: 2,
    CognitiveZone.CRITICAL: 3,
}

#: Ambient bid sources suppressed under arousal. RED suppresses ALL of these
#: (and applies the budget multiplier); AMBER suppresses only the ambient camera
#: bid (``camera_scene_ambient``). Pinned bids are NEVER dropped. ``"gossip"`` is
#: forward-looking — no bid emits that source today (the follow-up wiring will).
_AMBIENT_SOURCES: frozenset[str] = frozenset(
    {"camera_scene_ambient", "camera_scene", "telemetry", "gossip"}
)



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
        # AD-1032: the owning agent, bound at ``on_attach``. The faculty reads its
        # ``arousal_enabled`` (and the other arousal knobs) from the parent's live
        # AttentionConfig — when the parent/config is absent, arousal is fully bypassed.
        self._parent: Any = None
        # AD-1032: FACULTY-LOCAL arousal zone (NEVER the agent's circuit-breaker zone).
        # Raised UPWARD by exogenous events, decayed back toward GREEN each quiet turn.
        self._arousal_zone: CognitiveZone = CognitiveZone.GREEN
        # Monotonic timestamp of the most recent exogenous event (for full decay).
        self._last_event_at: float = 0.0
        # Whether an exogenous event arrived since the last ``arbitrate`` — a turn that
        # processed an event is NOT "quiet" and does not decay (it narrows at the raised
        # zone); a quiet turn steps the zone down one level.
        self._event_since_last_arbitrate: bool = False
        # Recent low-severity (scene_change/gossip) events, (monotonic_ts, event_type),
        # for the "same type repeats within the window ⇒ AMBER" rule.
        self._recent_low_severity: list[tuple[float, str]] = []

    # -- lifecycle (bind the parent so arousal can read its config) -----

    def on_attach(self, parent: Any) -> None:
        """AD-1032: bind the owning agent so the faculty can read its arousal config.

        The arousal model reads ``arousal_enabled`` (and the budget multiplier / decay /
        repeat-window knobs) from the parent's live ``AttentionConfig`` via the agent's
        own ``_attention_config`` resolver. AD-1029 never bound the parent (it had no
        need); arousal does, so the gate is the parent's LIVE config (mirroring how the
        budget is resolved fresh each turn). A parent without that resolver ⇒ arousal
        is bypassed (the AD-1029 fixtures stay byte-identical).
        """
        self._parent = parent

    # -- introspection --------------------------------------------------

    @property
    def pending_exogenous_count(self) -> int:
        """Number of exogenous bids accumulated since the last ``arbitrate`` drain."""
        return len(self._pending_exogenous)

    @property
    def arousal_zone(self) -> CognitiveZone:
        """AD-1032: the FACULTY-LOCAL arousal zone (NEVER the circuit-breaker zone).

        GREEN at rest; raised UPWARD by exogenous events (severity → zone) and decayed
        back toward GREEN each quiet ``arbitrate``. Introspection only — distinct from the
        AD-588 ``CognitiveZone`` the circuit breaker writes on the agent's working memory.
        """
        return self._arousal_zone

    @property
    def last_audit(self) -> dict[str, Any] | None:
        """A copy of the most recent bid-competition audit payload, or ``None``."""
        return dict(self._last_audit) if self._last_audit is not None else None

    # -- exogenous intake (mesh subscriber; between-turn salience) ------

    def on_signal(self, kind: str, payload: Any) -> None:
        """Receive a spine signal; stash exogenous salience as a pending bid.

        Spine convention (AD-1034): the agent-owned inlet ``deliver_exogenous`` forwards
        a mesh-sourced signal on the in-process channel under ``EXOGENOUS_SIGNAL_KIND``.

        AD-1032: a payload that is an arousal **event** (a Mapping carrying
        ``"event_type"``) is handled by the arousal model — and ONLY when
        ``arousal_enabled`` (the parent's live config). It RAISES the faculty-local zone
        UPWARD (severity → zone) and enqueues a PINNED threat-relevant bid so the event
        content survives RED narrowing. When arousal is OFF (default) an event payload
        contributes **nothing** (no zone change, no bid) ⇒ ``arbitrate`` stays
        byte-identical to AD-1029. Any NON-event payload takes the unchanged AD-1029
        coerce-to-bid path. Synchronous; never touches the bus.
        """
        if kind != EXOGENOUS_SIGNAL_KIND:
            return
        if self._is_arousal_event(payload):
            # An arousal EVENT is handled ONLY by the arousal model and ONLY when
            # enabled; OFF ⇒ it adds nothing (byte-identical AD-1029 even with an
            # event delivered).
            if self._arousal_enabled():
                self._ingest_arousal_event(payload)
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
        bids = observation.merged_bids
        budget = observation.token_budget
        # AD-1032: arousal — DECAY the faculty-local zone toward GREEN, then NARROW the
        # bid competition by the (post-decay) zone. Gated by ``arousal_enabled`` (read
        # from the parent's live config). GREEN / OFF ⇒ NO change ⇒ the assemble below is
        # byte-identical to AD-1029. RED suppresses ambient sources + shrinks the budget;
        # AMBER suppresses only the ambient camera bid; pinned bids are NEVER dropped.
        _cfg = self._arousal_config()
        if _cfg is not None and getattr(_cfg, "arousal_enabled", False):
            self._decay_if_quiet(float(getattr(_cfg, "arousal_full_decay_seconds", 300.0)))
            bids, budget = self._narrow_for_arousal(
                bids, budget, float(getattr(_cfg, "arousal_red_budget_multiplier", 0.5))
            )
        survivors = ContextAssembler.assemble(bids, token_budget=budget)
        bids_in = len(bids)
        used_tokens = sum(estimate_tokens(text) for text in survivors)
        return _Decision(
            assemble=True,
            survivors=survivors,
            bids_in=bids_in,
            survivor_count=len(survivors),
            dropped=bids_in - len(survivors),
            token_budget=budget,
            used_tokens=used_tokens,
            pinned_in=sum(1 for bid in bids if bid.pin),
            exogenous_drained=observation.exogenous_drained,
            sources=[bid.source for bid in bids],
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
            # AD-1032: the (post-decay) faculty-local arousal zone that drove this
            # turn's narrowing. Always GREEN when arousal is OFF (non-breaking — the
            # AD-1029 audit assertions check specific keys, never the whole dict).
            "arousal_zone": self._arousal_zone.value,
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

    # -- AD-1032: arousal model (faculty-local; gated by the parent's config) --

    def _arousal_config(self) -> Any | None:
        """The parent agent's live ``AttentionConfig`` (or ``None`` ⇒ arousal bypassed).

        Reuses the agent's own ``_attention_config`` resolver (DRY) — the same live config
        the token budget is resolved from each turn — so the gate reflects config changes
        without a snapshot. A parent without that resolver (the AD-1029 fixtures) or a
        read failure degrades to ``None`` ⇒ arousal is fully bypassed (byte-identical).
        """
        parent = self._parent
        if parent is None:
            return None
        getter = getattr(parent, "_attention_config", None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:  # log-and-degrade: a config-read failure must not arouse
            logger.debug(
                "AttentionFaculty(%s): parent _attention_config() raised; arousal bypassed.",
                self.organ_id,
                exc_info=True,
            )
            return None

    def _arousal_enabled(self) -> bool:
        """True only when the parent's live config sets ``arousal_enabled`` (OFF ⇒ AD-1029).

        The single gate every arousal code path is guarded behind.
        """
        cfg = self._arousal_config()
        return bool(cfg is not None and getattr(cfg, "arousal_enabled", False))

    @staticmethod
    def _is_arousal_event(payload: Any) -> bool:
        """True when ``payload`` is an arousal EVENT — a Mapping carrying ``event_type``.

        The only producer is ``CognitiveAgent.on_exogenous_event`` (the governed boundary).
        """
        return isinstance(payload, Mapping) and "event_type" in payload

    def _ingest_arousal_event(self, payload: Mapping[str, Any]) -> None:
        """Raise the faculty-local zone from an exogenous event + queue its (pinned) bid.

        Maps the event to a zone (severity table; an explicit ``severity`` can only RAISE
        the baseline, never lower it). A low-severity (GREEN) event only QUEUES — it does
        NOT reconfigure — UNLESS the same low-severity type repeats within
        ``arousal_repeat_window_seconds`` (⇒ AMBER). The zone moves UPWARD ONLY (decay is
        the only downward path). Records the event time (for full decay) and marks the
        turn non-quiet, then enqueues a PINNED threat-relevant bid so the event content
        survives RED narrowing. The caller (``on_signal``) has confirmed ``arousal_enabled``.
        """
        cfg = self._arousal_config()
        window = float(getattr(cfg, "arousal_repeat_window_seconds", 60.0)) if cfg else 60.0
        event_type = self._normalize_event_type(payload.get("event_type"))
        now = time.monotonic()
        target = self._zone_for_event(event_type, payload.get("severity"))
        if target == CognitiveZone.GREEN and self._record_low_severity(event_type, now, window):
            target = CognitiveZone.AMBER
        if _ZONE_RANK[target] > _ZONE_RANK[self._arousal_zone]:
            self._arousal_zone = target
        self._last_event_at = now
        self._event_since_last_arbitrate = True
        bid = self._build_event_bid(payload)
        if bid is not None:
            self._pending_exogenous.append(bid)

    @staticmethod
    def _normalize_event_type(event_type: Any) -> str:
        """Normalize to a short tag: lowercase + strip a leading ``exogenous_`` prefix
        (so ``"exogenous_alert"`` and ``"alert"`` both map to RED in the severity table)."""
        text = str(event_type or "").strip().lower()
        prefix = "exogenous_"
        return text[len(prefix):] if text.startswith(prefix) else text

    def _zone_for_event(self, event_type: str, severity: Any) -> CognitiveZone:
        """Resolve an event's target zone: the event_type baseline, RAISED (never lowered)
        by an explicit ``severity``. Unknown event_type ⇒ GREEN (queue-only)."""
        zone = _SEVERITY_BY_EVENT.get(event_type, CognitiveZone.GREEN)
        if severity is not None:
            sev = _ZONE_BY_SEVERITY.get(str(severity).strip().lower())
            if sev is not None and _ZONE_RANK[sev] > _ZONE_RANK[zone]:
                zone = sev
        return zone

    def _record_low_severity(self, event_type: str, now: float, window: float) -> bool:
        """Track recent low-severity events; return True when ``event_type`` already
        occurred within ``window`` (the repeat that escalates GREEN→AMBER). Prunes stale
        entries first so the window is a true sliding window."""
        self._recent_low_severity = [
            (ts, et) for (ts, et) in self._recent_low_severity if now - ts <= window
        ]
        repeated = any(et == event_type for (_ts, et) in self._recent_low_severity)
        self._recent_low_severity.append((now, event_type))
        return repeated

    def _build_event_bid(self, payload: Mapping[str, Any]) -> AttentionBid | None:
        """Build a PINNED, non-ambient bid carrying the event content so it survives RED
        narrowing. Uses an explicit ``text`` when present; else a concise event line."""
        text = payload.get("text")
        if not (isinstance(text, str) and text):
            event_type = str(payload.get("event_type", "exogenous")).strip() or "exogenous"
            severity = payload.get("severity")
            text = f"[exogenous:{event_type}]"
            if severity:
                text = f"{text} severity={severity}"
        source = str(payload.get("source", "exogenous_event"))
        return self._text_bid(source, text, modality="exogenous", pin=True)

    def _decay_if_quiet(self, full_decay_seconds: float) -> None:
        """Decay the faculty-local zone toward GREEN. A turn that processed an event is
        NOT quiet (narrow at the raised zone); a quiet turn steps DOWN one level, and a
        quiet period longer than ``full_decay_seconds`` resets straight to GREEN."""
        if self._event_since_last_arbitrate:
            self._event_since_last_arbitrate = False
            return
        if (
            self._last_event_at > 0.0
            and (time.monotonic() - self._last_event_at) > full_decay_seconds
        ):
            self._arousal_zone = CognitiveZone.GREEN
            return
        self._arousal_zone = self._step_down(self._arousal_zone)

    def _narrow_for_arousal(
        self, bids: list[AttentionBid], token_budget: int, red_multiplier: float
    ) -> tuple[list[AttentionBid], int]:
        """Narrow the competition by the current zone — pinned bids are NEVER dropped.

        RED ⇒ drop ALL ``_AMBIENT_SOURCES`` + multiply the budget by ``red_multiplier``;
        AMBER ⇒ drop ONLY the ambient camera bid (``camera_scene_ambient``); GREEN ⇒ no
        change (byte-identical broad context).
        """
        zone = self._arousal_zone
        if zone == CognitiveZone.RED:
            kept = [b for b in bids if b.pin or b.source not in _AMBIENT_SOURCES]
            return kept, max(1, int(token_budget * red_multiplier))
        if zone == CognitiveZone.AMBER:
            kept = [b for b in bids if b.pin or b.source != "camera_scene_ambient"]
            return kept, token_budget
        return bids, token_budget

    @staticmethod
    def _step_down(zone: CognitiveZone) -> CognitiveZone:
        """One level of arousal decay: RED→AMBER, AMBER→GREEN, GREEN stays GREEN."""
        if zone == CognitiveZone.RED:
            return CognitiveZone.AMBER
        if zone == CognitiveZone.AMBER:
            return CognitiveZone.GREEN
        return CognitiveZone.GREEN

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
