"""AD-1033: the ``CognitiveOrgan`` contract — a child component of an agent.

A *Cognitive Organ* is a bounded cognitive faculty (attention, memory,
valuation, perception-gating, ...) that a ``CognitiveAgent`` is **composed of**.
It is a **child component, not a mesh agent** (Design Principle #12; see
``docs/development/composable-cognition.md`` §2.1 and §7).

This module ships the **contract only** — a ``typing.Protocol`` plus a small
concrete base class and a child-identity helper. It constructs **no** organ (the
first organ, ``AttentionFaculty``, is AD-1029), drives **no** cycle (the spine is
AD-1034), and wires **nothing** into ``CognitiveAgent``, the registry, the
spawner, or the mesh. Importing it has **no runtime side effects**, so the running
system stays byte-identical.

Non-membership (the load-bearing discipline — §2.1). An organ:

* is **NOT** registered in the agent registry,
* is **NOT** addressable on the mesh,
* has **NO** independent trust score, vote, or consensus standing,
* is **born with its parent and dies with its parent**; its identity is *derived*
  and namespaced under the parent (``{parent_id}.{name}``).

Structurally, ``BaseCognitiveOrgan`` is a plain object — it does **not** subclass
``BaseAgent`` and has no ``tier`` / ``trust_score`` / ``capabilities`` /
``report`` / async ``start``/``stop``. That absence *is* the proof that an organ
is not a mesh peer (asserted in ``tests/test_ad1033_cognitive_organ_protocol.py``).

The organ cognitive cycle (``perceive → decide → act``) is **synchronous and
deterministic-by-default** (§2.1 part 3, §9): organs run every cycle *before* the
expensive LLM call and must not ``await`` a bus/network call on the cycle path.
This is intentionally distinct from ``BaseAgent``'s *async* mesh lifecycle — the
two operate at different scales (the spine vs. the mesh). Driving the cycle across
an agent's organs is the **spine's** job (AD-1034), not the organ's.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Callable, ClassVar, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


#: A thin, synchronous audit sink for per-cycle organ traces. Kept decoupled from
#: the cognitive journal (AD-431): the journal's ``record`` is *async*, but the
#: organ cycle is *synchronous*, so the emit callable is sync and the spine
#: (AD-1034) adapts it to the journal off the hot path. Defaults to a no-op so an
#: unwired organ stays silent (and byte-identical) today.
OrganAuditEmit = Callable[[Mapping[str, Any]], None]


def _noop_audit_emit(trace: Mapping[str, Any]) -> None:
    """Default audit sink — discards the trace. No journal coupling (AD-1033)."""
    return None


def make_organ_id(parent_id: str, name: str) -> str:
    """Derive a child organ id namespaced under its parent agent (AD-1033).

    An organ's identity is *derived*, never independent: it is the parent agent's
    id with the organ's ``name`` appended (``{parent_id}.{name}``), e.g.
    ``make_organ_id("agent-7", "attention") == "agent-7.attention"``. This id is
    **not** a mesh address and is **never** registered — it exists only for
    introspection of the parent's composition (Design Principle #12, §2.1).
    """
    return f"{parent_id}.{name}"


@runtime_checkable
class CognitiveOrgan(Protocol):
    """The contract for a cognitive organ — a child component of one agent.

    Captures the five-part organ test (composable-cognition.md §2.1):

    1. a distinct cognitive function (one thing a mind does),
    2. persistent state across cognitive cycles (carried by the concrete organ),
    3. the ``perceive → decide → act`` cognitive-cycle shape (sync, deterministic),
    4. 1:1 ownership — intrinsic to *one* agent (``attach``/``detach`` bind it),
    5. introspectability — ``organ_id`` + the audit sink expose its contribution.

    Marked ``@runtime_checkable`` so conformance is structural: any object that
    exposes these members (e.g. a ``BaseCognitiveOrgan`` subclass) satisfies
    ``isinstance(obj, CognitiveOrgan)``. Non-membership is part of the contract —
    an organ has no trust score, no vote, no mesh address, and is never registered.
    """

    @property
    def name(self) -> str:
        """The organ's kind (e.g. ``"attention"``) — the suffix of ``organ_id``."""
        ...

    @property
    def organ_id(self) -> str:
        """Derived child id ``{parent_id}.{name}`` — stable across the organ's life."""
        ...

    @property
    def parent_id(self) -> str:
        """Id of the owning agent; empty until ``attach`` binds the parent."""
        ...

    @property
    def attached(self) -> bool:
        """Whether the organ is currently bound to its parent (i.e. live)."""
        ...

    def attach(self, parent: Any) -> None:
        """Bind the organ to its parent at the parent's birth. Idempotent."""
        ...

    def detach(self) -> None:
        """Release the organ at the parent's teardown. Idempotent."""
        ...

    def set_audit_emit(self, emit: OrganAuditEmit | None) -> None:
        """Inject the per-cycle audit sink (no-op when ``None``); decoupled from AD-431."""
        ...

    def perceive(self, context: Any) -> Any:
        """Cycle step 1 — observe inputs for this turn. Sync, deterministic-by-default."""
        ...

    def decide(self, observation: Any) -> Any:
        """Cycle step 2 — compute this organ's contribution. Sync, deterministic-by-default."""
        ...

    def act(self, decision: Any) -> Any:
        """Cycle step 3 — apply/emit the contribution. Sync, deterministic-by-default."""
        ...


class BaseCognitiveOrgan:
    """Minimal concrete base for cognitive organs (AD-1033).

    Stores ``parent_id`` + ``name``, exposes ``organ_id``, and provides idempotent
    ``attach``/``detach`` so concrete organs (AD-1029) subclass it and override
    only the cycle steps (and the ``on_attach``/``on_detach`` hooks) they need.
    The default cognitive cycle is a deterministic no-op.

    This is **not** a mesh agent: it does not subclass ``BaseAgent`` and exposes no
    ``tier`` / ``trust_score`` / ``report`` / async lifecycle. See the module
    docstring for the non-membership discipline.
    """

    #: Default organ kind; subclasses (e.g. ``AttentionFaculty``, AD-1029) set
    #: this. A per-instance ``name=`` argument to ``__init__`` overrides it.
    default_name: ClassVar[str] = ""

    def __init__(self, *, name: str | None = None, emit: OrganAuditEmit | None = None) -> None:
        resolved = (name if name is not None else self.default_name).strip()
        if not resolved:
            raise ValueError(
                "BaseCognitiveOrgan requires a non-empty 'name' (set the "
                "'default_name' class attribute or pass name=...)."
            )
        self._name: str = resolved
        self._parent_id: str = ""
        self._attached: bool = False
        self._emit_audit: OrganAuditEmit = emit or _noop_audit_emit

    # -- identity (introspectable; never a mesh address) ----------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def parent_id(self) -> str:
        return self._parent_id

    @property
    def organ_id(self) -> str:
        return make_organ_id(self._parent_id, self._name)

    @property
    def attached(self) -> bool:
        return self._attached

    # -- lifecycle (born with / dies with the parent; idempotent) -------

    def attach(self, parent: Any) -> None:
        """Bind to ``parent`` at the parent's birth.

        Idempotent: a second ``attach`` is a no-op so ``organ_id`` stays stable for
        the organ's life. Re-attaching to a *different* parent while already
        attached is ignored with a warning (an organ is owned 1:1).
        """
        new_parent_id = _resolve_parent_id(parent)
        if self._attached:
            if new_parent_id != self._parent_id:
                logger.warning(
                    "Organ %s already attached to %r; ignoring re-attach to %r "
                    "(organ_id is stable for the organ's life).",
                    self._name,
                    self._parent_id,
                    new_parent_id,
                )
            return
        self._parent_id = new_parent_id
        self._attached = True
        self.on_attach(parent)

    def detach(self) -> None:
        """Release at the parent's teardown.

        Idempotent: a second ``detach`` (or a ``detach`` before any ``attach``) is a
        safe no-op. ``parent_id`` is retained so ``organ_id`` stays introspectable
        post-mortem; ``attached`` flips to ``False``.
        """
        if not self._attached:
            return
        self._attached = False
        self.on_detach()

    def on_attach(self, parent: Any) -> None:
        """Subclass hook — initialise organ state at attach. Default no-op."""
        return None

    def on_detach(self) -> None:
        """Subclass hook — release organ state at detach. Default no-op."""
        return None

    # -- audit (decoupled from the cognitive journal, AD-431) -----------

    def set_audit_emit(self, emit: OrganAuditEmit | None) -> None:
        """Inject the per-cycle audit sink; ``None`` restores the no-op default."""
        self._emit_audit = emit or _noop_audit_emit

    def _emit_audit_trace(self, phase: str, payload: Mapping[str, Any] | None = None) -> None:
        """Fire a per-cycle audit trace through the injected sink. Never raises.

        Builds a minimal trace (``organ_id`` + ``phase`` + optional ``payload``) and
        hands it to the sync sink. The sink is fire-and-forget: a failing sink is
        logged and swallowed so audit can never break the cognitive cycle.
        """
        trace: dict[str, Any] = {"organ_id": self.organ_id, "phase": phase}
        if payload:
            trace.update(payload)
        try:
            self._emit_audit(trace)
        except Exception:  # log-and-degrade: audit must never break the cycle
            logger.debug(
                "Organ %s audit sink raised for phase=%s; trace dropped.",
                self._name,
                phase,
                exc_info=True,
            )

    # -- cognitive cycle (sync, deterministic-by-default) ---------------

    def perceive(self, context: Any) -> Any:
        """Cycle step 1 — default no-op. Override in concrete organs (AD-1029)."""
        return None

    def decide(self, observation: Any) -> Any:
        """Cycle step 2 — default no-op. Override in concrete organs (AD-1029)."""
        return None

    def act(self, decision: Any) -> Any:
        """Cycle step 3 — default no-op. Override in concrete organs (AD-1029)."""
        return None


def _resolve_parent_id(parent: Any) -> str:
    """Derive the parent agent's id for namespacing.

    Prefers the AD-441 permanent ``sovereign_id`` when set; otherwise falls back to
    the runtime ``id``; finally to ``str(parent)``. Reads only the parent's own
    public attributes (no reaching-through), which is the defined purpose of
    ``attach`` — binding the child under its owner.
    """
    sovereign = getattr(parent, "sovereign_id", "") or ""
    if sovereign:
        return str(sovereign)
    runtime_id = getattr(parent, "id", "") or ""
    if runtime_id:
        return str(runtime_id)
    return str(parent)
