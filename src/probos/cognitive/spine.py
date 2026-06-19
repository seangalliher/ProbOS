"""AD-1034: the ``CognitiveSpine`` — an agent's in-process central nervous system.

The **spine** is the synchronous, in-process backbone a ``CognitiveAgent`` provides for
its **cognitive organs** (AD-1033, ``organ.py``). It is the agent's *central nervous
system*; the **mesh** (intent bus + gossip + routing) is the *ship's* nervous system.
Same "connective substrate over composed units" pattern at two scales, with
scale-appropriate properties (``docs/development/composable-cognition.md`` §2.2–§2.5):

* **Synchronous & in-process** — driving K organs is K cheap, deterministic calls;
  there is **no** ``await`` on a bus/network call on the cycle path (the
  discipline-erosion guard, §9, asserted in the AD-1034 tests).
* **Ungoverned & private** — organs are not sovereign: no quorum vote, no trust, no
  network hop between an agent's own faculties.
* **Sovereign boundary (AD-397)** — organs never touch the intent bus; the agent
  mediates. Exogenous signals enter through one agent-owned inlet
  (``deliver_exogenous``).

The spine does four things:

1. **Composition** — an ordered name→organ registry; ``attach_organ`` /
   ``detach_organ`` / ``detach_all`` bind organs to the parent at its birth and release
   them at its death (organs are *born with / die with* the parent — Design Principle
   #12).
2. **Cycle** — ``drive_cycle`` runs each organ's ``perceive → decide → act``
   synchronously, in attach order. **With zero organs it returns immediately** — the
   default for every existing agent, so the running system is byte-identical.
3. **Signaling** — a synchronous in-process observer channel (``subscribe`` /
   ``emit_signal``) by which one organ influences another within the same cycle (e.g. a
   valuation organ raises arousal → an attention organ narrows). This is **not** the
   intent bus.
4. **Governed inlet** — ``deliver_exogenous`` is the single agent-owned boundary for
   mesh-sourced signals (mentions/alerts/camera-change/gossip). AD-1034 **stubs** the
   routing: it stores the signal and forwards it on the in-process channel; wiring the
   inlet to the real intent bus is AD-1031/1032.

Behavior-preserving (the hard requirement). A spine with **zero organs registered** is
inert — ``drive_cycle`` and ``deliver_exogenous`` fan out to nobody, and ``detach_all``
releases nobody. AD-1034 builds **no** concrete organ (the first is the
``AttentionFaculty``, AD-1029) and never makes an organ a mesh peer.

Signal convention. To *receive* an intra-organ signal, an organ implements
``on_signal(kind, payload)``. This is a **spine convention**, deliberately *not* part of
the AD-1033 ``CognitiveOrgan`` contract: an organ opts in only if it wants signals, so
the organ protocol stays unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

from probos.cognitive.organ import CognitiveOrgan

logger = logging.getLogger(__name__)

#: The signal kind under which the governed inlet (``deliver_exogenous``) forwards a
#: mesh-sourced signal onto the spine's in-process channel. Organs that care about
#: exogenous input ``subscribe(EXOGENOUS_SIGNAL_KIND, organ)``; AD-1034 keeps the
#: routing strictly in-process (never the intent bus).
EXOGENOUS_SIGNAL_KIND = "exogenous"


class CognitiveSpine:
    """The synchronous in-process nervous system owned by one ``CognitiveAgent``.

    Owns organ composition, drives the organ cognitive cycle, carries the intra-organ
    signal channel, and exposes the single governed mesh-boundary inlet. Constructed
    empty and **inert until organs are attached** (byte-identical default). The spine is
    private to its parent agent — never registered, never mesh-addressable, and never
    touches the intent bus (sovereignty / AD-397).
    """

    def __init__(self, parent: Any) -> None:
        """Bind the spine to its parent agent (or any object exposing an id).

        ``parent`` is stored so the spine can pass it to ``organ.attach`` — the organ
        derives its own ``{parent_id}.{name}`` child id from it (AD-1033). Only the
        parent's public id attributes are ever read (no reaching-through).
        """
        self._parent: Any = parent
        # Insertion-ordered so the cognitive cycle runs organs in attach order.
        self._organs: dict[str, CognitiveOrgan] = {}
        # kind -> ordered, de-duplicated subscribers; the in-process signal channel.
        self._subscribers: dict[str, list[CognitiveOrgan]] = {}
        # Last signal handed in via the governed inlet (introspection only).
        self._last_exogenous: Any = None

    # -- identity / introspection ---------------------------------------

    @property
    def parent_id(self) -> str:
        """Id of the owning agent (AD-441 ``sovereign_id`` preferred, then ``id``).

        Mirrors ``organ._resolve_parent_id`` (the canonical resolution) by reading only
        the parent's own public attributes, so the spine imports only *public* organ
        symbols and never reaches into the agent's internals.
        """
        sovereign = getattr(self._parent, "sovereign_id", "") or ""
        if sovereign:
            return str(sovereign)
        runtime_id = getattr(self._parent, "id", "") or ""
        if runtime_id:
            return str(runtime_id)
        return str(self._parent)

    @property
    def organs(self) -> tuple[CognitiveOrgan, ...]:
        """The composed organs, in attach order (introspection; never a mesh view)."""
        return tuple(self._organs.values())

    @property
    def organ_names(self) -> tuple[str, ...]:
        """The names of the composed organs, in attach order."""
        return tuple(self._organs.keys())

    @property
    def has_organs(self) -> bool:
        """Whether any organ is composed. ``False`` ⇒ the spine is inert (the default)."""
        return bool(self._organs)

    @property
    def last_exogenous(self) -> Any:
        """The most recent signal handed to ``deliver_exogenous`` (introspection)."""
        return self._last_exogenous

    def get_organ(self, name: str) -> CognitiveOrgan | None:
        """Return the composed organ named ``name``, or ``None`` if not present."""
        return self._organs.get(name)

    # -- composition (born with / die with the parent) ------------------

    def attach_organ(self, organ: CognitiveOrgan) -> None:
        """Compose ``organ`` into this brain and bind it to the parent.

        Registers the organ by its ``name`` and calls ``organ.attach(parent)`` so the
        organ derives its child id. Names are unique per spine: re-attaching the *same*
        instance is an idempotent no-op; attaching a *different* organ under an existing
        name is refused (log-and-degrade) so ``organ_id`` stays 1:1 and stable.
        """
        name = organ.name
        existing = self._organs.get(name)
        if existing is not None:
            if existing is organ:
                return  # idempotent
            logger.warning(
                "Spine(%s) already composes an organ named %r; refusing a second "
                "instance (organ identity must stay 1:1 and stable).",
                self.parent_id,
                name,
            )
            return
        organ.attach(self._parent)
        self._organs[name] = organ

    def detach_organ(self, name: str) -> CognitiveOrgan | None:
        """Release and return the organ named ``name`` (or ``None`` if absent).

        Unsubscribes the organ from every signal kind, then calls ``organ.detach()``.
        Idempotent: detaching an unknown name is a safe no-op returning ``None``.
        """
        organ = self._organs.pop(name, None)
        if organ is None:
            return None
        self._unsubscribe_organ(organ)
        organ.detach()
        return organ

    def detach_all(self) -> None:
        """Release every composed organ at the parent's teardown (reverse attach order).

        With zero organs this is a no-op — the byte-identical default invoked from the
        agent's ``stop``. A failing ``detach`` is logged and swallowed so one organ
        cannot block the agent's teardown.
        """
        for organ in reversed(list(self._organs.values())):
            try:
                organ.detach()
            except Exception:  # log-and-degrade: teardown must not be blocked
                logger.warning(
                    "Spine(%s): organ %r raised during detach_all; continuing teardown.",
                    self.parent_id,
                    getattr(organ, "name", "?"),
                    exc_info=True,
                )
        self._organs.clear()
        self._subscribers.clear()

    # -- signaling (synchronous in-process observer channel) ------------

    def subscribe(self, kind: str, organ: CognitiveOrgan) -> None:
        """Subscribe ``organ`` to intra-organ signals of ``kind``.

        Delivery calls ``organ.on_signal(kind, payload)`` synchronously during
        ``emit_signal``. ``on_signal`` is a **spine convention** (not part of the
        AD-1033 organ contract): an organ implements it only to receive signals.
        Subscribing an organ without a callable ``on_signal`` is a wiring error and is
        refused (fail-fast). Re-subscribing the same organ to the same kind is
        idempotent.
        """
        handler = getattr(organ, "on_signal", None)
        if not callable(handler):
            raise ValueError(
                f"organ {organ.name!r} cannot subscribe to {kind!r}: it exposes no "
                "callable 'on_signal(kind, payload)' handler (spine signal convention)."
            )
        subscribers = self._subscribers.setdefault(kind, [])
        if organ not in subscribers:
            subscribers.append(organ)

    def emit_signal(self, kind: str, payload: Any) -> None:
        """Deliver an intra-organ signal to every subscriber of ``kind``, synchronously.

        Direct observer fan-out within the current cycle — **not** the intent bus.
        Iterates a snapshot so a handler may (un)subscribe re-entrantly. A failing
        subscriber is logged and swallowed so one organ cannot break the emitter's
        cycle.
        """
        for organ in tuple(self._subscribers.get(kind, ())):
            try:
                organ.on_signal(kind, payload)
            except Exception:  # log-and-degrade: a buggy organ must not break the cycle
                logger.warning(
                    "Spine(%s): subscriber %r raised handling signal %r; skipping.",
                    self.parent_id,
                    getattr(organ, "name", "?"),
                    kind,
                    exc_info=True,
                )

    # -- cognitive cycle (synchronous; NO await on a bus/network call) --

    def drive_cycle(self, context: Any) -> None:
        """Run ``perceive → decide → act`` across the composed organs, in attach order.

        Synchronous and deterministic-by-default: there is **no** ``await`` here, and
        organs must not block on a bus/network call (composable-cognition.md §9). **With
        zero organs this returns immediately** — the default for every existing agent, so
        the agent's lifecycle is byte-identical to pre-AD-1034. Each organ is isolated
        (log-and-degrade) so one faculty's failure degrades to no-contribution rather
        than crashing the agent's turn.
        """
        if not self._organs:
            return  # zero-organ no-op — the byte-identical fast path
        for organ in tuple(self._organs.values()):
            try:
                observation = organ.perceive(context)
                decision = organ.decide(observation)
                organ.act(decision)
            except Exception:  # log-and-degrade: a faculty failure must not crash the turn
                logger.warning(
                    "Spine(%s): organ %r raised during the cognitive cycle; skipping its "
                    "contribution this turn.",
                    self.parent_id,
                    getattr(organ, "name", "?"),
                    exc_info=True,
                )

    # -- governed mesh boundary (single agent-owned inlet) --------------

    def deliver_exogenous(self, signal: Any) -> None:
        """Hand a mesh-sourced signal to the organs — the single governed boundary.

        The **agent** calls this to deliver an exogenous signal (mention, alert,
        camera-change, gossip) to its organs between turns; organs never reach the intent
        bus themselves (sovereignty / AD-397). AD-1034 **stubs** the routing: it stores
        the signal (introspection) and forwards it on the spine's in-process channel
        under ``EXOGENOUS_SIGNAL_KIND``. Wiring this inlet to the real intent bus is
        AD-1031/1032 — the spine never reaches the bus directly.
        """
        self._last_exogenous = signal
        self.emit_signal(EXOGENOUS_SIGNAL_KIND, signal)

    # -- internals ------------------------------------------------------

    def _unsubscribe_organ(self, organ: CognitiveOrgan) -> None:
        """Remove ``organ`` from every signal kind it subscribed to (used on detach)."""
        empty_kinds: list[str] = []
        for kind, subscribers in self._subscribers.items():
            if organ in subscribers:
                subscribers.remove(organ)
            if not subscribers:
                empty_kinds.append(kind)
        for kind in empty_kinds:
            self._subscribers.pop(kind, None)
