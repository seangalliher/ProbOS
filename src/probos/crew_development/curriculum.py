"""Core Knowledge Curriculum Registry (AD-507 v1).

Read-only catalog of universal curriculum modules. Future consumers
(AD-486 onboarding Phase 1, AD-477b qualification gates) read this
registry for content delivery.

v1 ships registry only. Progression tracking (AD-507b), competency
assessment (AD-507c), and Standing Orders integration (AD-507d) are
deferred.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CurriculumModule:
    """Core Knowledge curriculum module. AD-507 v1.

    ``category`` is one of: ``identity``, ``communication``, ``memory``,
    ``trust``, ``ethics``, ``self_regulation``, ``help_seeking``.

    ``delivery_phase`` is one of: ``orientation``, ``calibration``,
    ``self_discovery``, ``ship_records``, ``ward_room``.
    """

    module_id: str
    title: str
    category: str
    summary: str
    learning_objectives: tuple[str, ...]
    delivery_phase: str


_DEFAULT_MODULES: tuple[CurriculumModule, ...] = (
    CurriculumModule(
        module_id="identity_grounding",
        title="Identity & DID",
        category="identity",
        summary="Your DID, birth certificate, callsign, and place in the Federation.",
        learning_objectives=(
            "Recognize your own DID and birth-certificate metadata",
            "Locate yourself in chain of command",
            "Address other agents by callsign",
        ),
        delivery_phase="orientation",
    ),
    CurriculumModule(
        module_id="chain_of_command",
        title="Chain of Command",
        category="identity",
        summary="Captain → Department Heads → Senior Officers → Lieutenants → Ensigns. Escalation paths.",
        learning_objectives=(
            "Identify your immediate superior",
            "Know which decisions escalate vs which are within your authority",
            "Recognize when to defer to higher rank",
        ),
        delivery_phase="orientation",
    ),
    CurriculumModule(
        module_id="ward_room_protocol",
        title="Ward Room Communication",
        category="communication",
        summary="Posting, threading, endorsement, mention conventions, reply caps.",
        learning_objectives=(
            "Use [REPLY], [POST], [ENDORSE] action tags correctly",
            "Respect max_responses_per_thread",
            "Address Captain DMs vs Ward Room threads appropriately",
        ),
        delivery_phase="ward_room",
    ),
    CurriculumModule(
        module_id="dm_etiquette",
        title="Direct Messaging",
        category="communication",
        summary="When to DM vs post in Ward Room. Captain DMs vs peer DMs.",
        learning_objectives=(
            "Choose DM vs Ward Room based on audience scope",
            "Recognize Captain DM priority signals",
            "Avoid DM ping-pong loops (BF-257 awareness)",
        ),
        delivery_phase="ward_room",
    ),
    CurriculumModule(
        module_id="notebook_discipline",
        title="Personal Notebooks",
        category="communication",
        summary="What goes in your notebook vs Ship's Records. Privacy boundaries.",
        learning_objectives=(
            "Write durable observations to notebooks/{callsign}/",
            "Distinguish personal vs ship-wide knowledge",
            "Use frontmatter classification correctly",
        ),
        delivery_phase="ship_records",
    ),
    CurriculumModule(
        module_id="episodic_vs_llm",
        title="Episodic Memory vs LLM Knowledge",
        category="memory",
        summary="What you remember (episodic) vs what you know (LLM training). Importance scoring.",
        learning_objectives=(
            "Distinguish remembered events from trained knowledge",
            "Recognize when to consult episodic recall",
            "Avoid confabulating episodic details",
        ),
        delivery_phase="self_discovery",
    ),
    CurriculumModule(
        module_id="trust_mechanics",
        title="Trust Network",
        category="trust",
        summary="Beta(α,β) trust scores, how they're earned, what tiers unlock.",
        learning_objectives=(
            "Understand Bayesian trust accumulation",
            "Recognize Earned Agency tier transitions",
            "Behave in ways that build (not erode) peer trust",
        ),
        delivery_phase="calibration",
    ),
    CurriculumModule(
        module_id="ethics_boundaries",
        title="Inviolable Boundaries (AD-511)",
        category="ethics",
        summary="5 federation-tier boundaries: identity integrity, harmful content, safety bypass, memory manipulation, chain-of-command violation.",
        learning_objectives=(
            "Recognize requests that cross inviolable boundaries",
            "State the boundary, offer alternative, escalate, disengage",
            "Report boundary encounters to Counselor",
        ),
        delivery_phase="orientation",
    ),
    CurriculumModule(
        module_id="self_regulation",
        title="Self-Regulation & Help-Seeking",
        category="self_regulation",
        summary="Pacing, when to stop, circuit breakers (AD-488), when to DM a peer, when to escalate.",
        learning_objectives=(
            "Recognize cognitive overload signals",
            "Use help-seeking before recursive looping (AD-488)",
            "Pace duty execution sustainably",
        ),
        delivery_phase="calibration",
    ),
)


class CoreKnowledgeCurriculumRegistry:
    """Read-only registry of curriculum modules. AD-507 v1.

    Default catalog seeds 9 modules across 7 categories and 5 delivery
    phases. Extensible at runtime via :meth:`register_module` (no
    persistence in v1 — runtime-only).
    """

    def __init__(self) -> None:
        self._modules: dict[str, CurriculumModule] = {
            m.module_id: m for m in _DEFAULT_MODULES
        }
        self.emit_event: Callable[..., None] | None = None

    def list_modules(self) -> tuple[CurriculumModule, ...]:
        """Return all registered modules as a stable tuple."""
        return tuple(self._modules.values())

    def get_module(self, module_id: str) -> CurriculumModule | None:
        """Look up a module by id. Emits a query event on hit."""
        m = self._modules.get(module_id)
        if m is not None:
            self._emit(module_id, "by_id")
        return m

    def list_by_category(self, category: str) -> tuple[CurriculumModule, ...]:
        """Filter modules by category. Emits a query event on non-empty hit."""
        out = tuple(m for m in self._modules.values() if m.category == category)
        if out:
            self._emit("", f"by_category:{category}")
        return out

    def list_by_phase(self, phase: str) -> tuple[CurriculumModule, ...]:
        """Filter modules by delivery phase. Emits a query event on non-empty hit."""
        out = tuple(m for m in self._modules.values() if m.delivery_phase == phase)
        if out:
            self._emit("", f"by_phase:{phase}")
        return out

    def register_module(self, module: CurriculumModule) -> None:
        """Add or overwrite a module by id (runtime-only; not persisted in v1)."""
        self._modules[module.module_id] = module

    def _emit(self, module_id: str, query_type: str) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.CURRICULUM_MODULE_QUERIED,
                {"module_id": module_id, "query_type": query_type},
            )
        except Exception:
            logger.warning(
                "AD-507: emit_event failed for query_type=%s; continuing without event",
                query_type,
                exc_info=True,
            )
