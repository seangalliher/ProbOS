"""AD-1035: the ``DreamingOrgan`` — a per-agent personal dreaming faculty.

The **DreamingOrgan** is the second concrete **Cognitive Organ** (AD-1033) of the
Composable-Cognition epic (#983), after the pilot ``AttentionFaculty`` (AD-1029). It
is the seam through which an individual ``CognitiveAgent`` gets its *own* offline
consolidation faculty — "a dream a dreamer can call its own" — distinct from the
ship-wide shared ``DreamingEngine`` + ``DreamScheduler`` wired on the runtime.

The discipline (the load-bearing properties — Design Principle #12, §2.1, §9):

* **Wrap, never reimplement.** The organ does **not** re-derive Hebbian replay, trust
  consolidation, pruning, or procedure extraction — that logic lives in the shared
  ``DreamingEngine`` (``cognitive/dreaming.py``). When (and only when) an engine is
  wired, :meth:`run_dream_cycle` returns **exactly** ``await engine.dream_cycle()`` —
  the *faithful-driver* guarantee (the AD-1029 ``arbitrate``==``assemble`` analogue).
* **Background organ — OFF the hot path.** Unlike the synchronous ``AttentionFaculty``,
  dreaming is *not* a per-turn faculty: the ``perceive → decide → act`` cycle steps are
  the inherited deterministic no-ops, so the spine's ``drive_cycle`` (run every turn)
  **never** does dream work. The organ's work is the **async** :meth:`run_dream_cycle`,
  which an out-of-band cadence driver invokes during idle — never on the cognitive cycle.
* **Inert in v1 (the Captain's non-disruptive mandate).** AD-1035 wires **no** live
  engine and **no** cadence driver: in production the organ owns no engine, so even when
  ``dreaming.organ_enabled`` is True the organ is inert (``run_dream_cycle`` no-ops to
  ``None``). The shared runtime ``DreamingEngine`` + ``DreamScheduler`` remain the single
  source of truth; the per-agent background-cognition scheduler is a deferred follow-on.
* **Never raises across the seam.** A wired engine that raises is logged-and-degraded to
  ``None`` (a dream failure must never crash the owning agent).
* **Non-membership.** Like every organ, ``DreamingOrgan`` is **NOT** a ``BaseAgent``,
  **NOT** registered, **NOT** mesh-addressable, has no trust score / vote / consensus
  standing; it is born with its parent, dies with its parent, and its identity is
  derived and namespaced under it (``{parent_id}.dreaming``).
"""

from __future__ import annotations

import logging
from typing import Any

from probos.cognitive.organ import BaseCognitiveOrgan, OrganAuditEmit

logger = logging.getLogger(__name__)


class DreamingOrgan(BaseCognitiveOrgan):
    """A per-agent background dreaming organ that *wraps* a shared ``DreamingEngine``.

    Composed onto a ``CognitiveAgent``'s spine (AD-1034) only when
    ``dreaming.organ_enabled`` is True; default-OFF it is never constructed and the agent
    is byte-identical to pre-AD-1035 (the shared runtime ``DreamingEngine`` remains the
    source of truth). It is a **background** organ: the ``perceive → decide → act`` cycle
    steps are the inherited no-ops (so the spine's per-turn ``drive_cycle`` never drives a
    dream), and its real work is the async :meth:`run_dream_cycle`, a faithful wrapper over
    the wired engine's ``dream_cycle`` (or a no-op when no engine is wired — the v1 default).
    """

    #: Organ kind → ``organ_id`` is ``{parent_id}.dreaming`` (AD-1033).
    default_name = "dreaming"

    def __init__(
        self,
        *,
        name: str | None = None,
        emit: OrganAuditEmit | None = None,
        engine: Any = None,
    ) -> None:
        super().__init__(name=name, emit=emit)
        # The owning agent, bound at ``on_attach`` (introspection only; the organ never
        # reaches through it). ``None`` until composed.
        self._parent: Any = None
        # The wrapped shared ``DreamingEngine`` (duck-typed: anything exposing an async
        # ``dream_cycle()``). ``None`` in v1 ⇒ the organ is inert (no engine wired here).
        self._engine: Any = engine
        # Most recent ``DreamReport`` from a successful cycle (introspection only).
        self._last_report: Any = None

    # -- lifecycle hooks (born with / dies with the parent) -------------

    def on_attach(self, parent: Any) -> None:
        """Bind the owning agent at compose time. Default-cycle organ — no other state."""
        self._parent = parent

    def on_detach(self) -> None:
        """Release the owning agent at the parent's teardown."""
        self._parent = None

    # -- introspection --------------------------------------------------

    @property
    def engine(self) -> Any:
        """The wrapped ``DreamingEngine`` (or ``None`` when no engine is wired)."""
        return self._engine

    @property
    def last_report(self) -> Any:
        """The most recent ``DreamReport`` from a successful cycle (or ``None``)."""
        return self._last_report

    def set_engine(self, engine: Any) -> None:
        """Wire (or replace) the shared engine this organ drives. ``None`` makes it inert."""
        self._engine = engine

    # -- the organ's work (async, OFF the cognitive cycle) --------------

    async def run_dream_cycle(self) -> Any:
        """Run one dream cycle by delegating to the wired engine — the faithful wrapper.

        With an engine wired, returns **exactly** ``await engine.dream_cycle()`` (and caches
        it as :attr:`last_report`). With **no** engine wired (the v1 default), it is a no-op
        returning ``None``. It **never raises across the seam**: a wired engine that raises is
        logged-and-degraded to ``None`` so a dream failure cannot crash the owning agent. This
        is the async, off-the-hot-path analogue of the ``AttentionFaculty``'s synchronous
        ``arbitrate`` faithful-driver guarantee.
        """
        engine = self._engine
        if engine is None:
            # v1 default: no engine wired ⇒ the organ is inert.
            self._emit_audit_trace("dream", {"status": "no_engine"})
            return None
        try:
            report = await engine.dream_cycle()
        except Exception:  # log-and-degrade: a dream failure must never crash the agent
            logger.warning(
                "DreamingOrgan %s: wrapped engine.dream_cycle() raised; degrading to no "
                "report this cycle.",
                self.organ_id,
                exc_info=True,
            )
            self._emit_audit_trace("dream", {"status": "error"})
            return None
        self._last_report = report
        self._emit_audit_trace("dream", {"status": "completed"})
        return report
