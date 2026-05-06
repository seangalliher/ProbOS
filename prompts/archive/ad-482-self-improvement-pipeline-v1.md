# AD-482 v1 — Self-Improvement Pipeline (Stage Contracts + Proposals + Approval + QA + Evolution + Versioning + Persistence)

**Closes:** GH issue #76
**HEAD:** `ccd1008`
**Baseline:** 11614 → target ≥ 11654 (Δ ≥ +40)
**OSS only.** No HXI surface. No router. No new Intent. No LLM call inside any v1 module. No commercial content.
**Sub-ADs in scope (concrete):** AD-482a (Stage Contracts), AD-482b (Capability Proposal), AD-482c (Approval Gate), AD-482d (Evolution Store), AD-482e (PIVOT/REFINE), AD-482f (QA Agent Pool + Shapley), AD-482g (Agent Versioning), AD-482h (`LocalDiskPersistence`).
**Sub-ADs in scope (Protocol seam only):** AD-482i (Shadow Deployment — `ShadowDeploymentPolicy` + `NoOpShadowDeploymentPolicy`).
**Sub-AD hard-deferred:** none (Captain rule honored — AD-482h-1 git/PR layer + AD-482i-1 parallel-pool comparator are forcing-function follow-ons, NOT v1 deferrals).

## Problem

ProbOS has a working agent-design pipeline (`SelfModificationPipeline`, `AgentDesigner`, `CodeValidator`, `SandboxRunner`, `BehavioralMonitor`, `SystemQAAgent`) but the closed-loop *improvement* infrastructure is missing. Today:

1. Discovered capabilities (research findings, scout reports, code reviewer suggestions) have no typed shape — they pass through chat as freeform strings or get bolted into `ArchitectProposal` (which is BuildSpec-shaped, not capability-shaped).
2. The Captain approval surface for self-mod is a single bool callback (`_user_approval_fn`). There's no queue, no audit trail, no modify-and-resubmit, no rejection-rationale persistence.
3. QA is a single `SystemQAAgent` instance per runtime — no pool, no Shapley contribution scoring across multiple QA voters.
4. Lessons learned from prior integrations vanish — there's no append-only "what we tried, what worked, why" store with time-decayed retrieval.
5. Self-modifications happen one shot — there's no PROCEED/REFINE/PIVOT decision primitive with iteration caps and artifact versioning.
6. Designed agents have no version history — `DesignedAgentRecord` carries one snapshot, no parent-version lineage, no per-version trust metadata.
7. Designed agents live only in the runtime evolution store — when promoted, there's no path to `src/probos/agents/designed/` for permanent crew membership.
8. Shadow deployment (run candidate alongside baseline, compare via Shapley) has no surface — even the Protocol shape doesn't exist.

GH #76 lists eight sub-ADs (a–h) plus the deferred-from-Phase-14c shadow-deployment item. Eight ship concretely (a/b/c/d/e/f/g/h). One ships as Protocol seam + NoOp default + stable dispatch entry point (i). Zero hard-deferrals.

## Solution

One new package + one existing-module extension + finalize wirer + Pydantic config.

1. **`src/probos/cognitive/self_improvement/`** — new package with six modules:
   - `stage_contract.py` — `StageContract` frozen dataclass + shape-only validators.
   - `proposal.py` — `CapabilityProposal` + `ProposalStore` + `PivotRefineDecision` enum + `IterationGuard`.
   - `approval_gate.py` — `ApprovalGate` queue with approve/reject/modify + audit emission.
   - `evolution_store.py` — `EvolutionStore` ChromaDB-backed lessons + time-decay retrieval.
   - `qa_pool.py` — `QAAgentPool` wrapper around `SystemQAAgent` + Shapley aggregator.
   - `versioning.py` — `AgentVersion` + `AgentVersionStore` + `AgentPersistence` Protocol + `LocalDiskPersistence` default + `ShadowDeploymentPolicy` Protocol + `NoOpShadowDeploymentPolicy` default.

2. **`src/probos/events.py`** — +6 EventType values.

3. **`src/probos/config.py`** — `SelfImprovementConfig` Pydantic model + `SystemConfig.self_improvement` field.

4. **`src/probos/startup/finalize.py`** — `_wire_self_improvement(*, runtime, config) -> bool`. Invocation immediately after `_wire_predictive_branching` (depends on `runtime._chroma_client`, optional `runtime.spawner`).

5. **`src/probos/runtime.py`** — public typed attribute declarations.

6. **`tests/test_ad482_self_improvement.py`** — 42 tests across 9 classes.

---

## Section 0 — EventTypes

### File: `src/probos/events.py`

Insert AD-482 events immediately after the AD-633 prediction block (line 67-70). Adjacent placement keeps cognitive-pipeline events together.

```text
===MODIFY: src/probos/events.py===
===SEARCH===
    PREDICTION_HIT = "prediction_hit"  # AD-633b cache served pre-computed analysis
    PREDICTION_MISS = "prediction_miss"  # AD-633d cache miss; fell to LLM
    PREDICTION_FLUSHED = "prediction_flushed"  # AD-633b cache entry evicted (TTL or capacity)
    PREDICTION_ERROR_RECORDED = "prediction_error_recorded"  # AD-633h prediction diverged from outcome
===REPLACE===
    PREDICTION_HIT = "prediction_hit"  # AD-633b cache served pre-computed analysis
    PREDICTION_MISS = "prediction_miss"  # AD-633d cache miss; fell to LLM
    PREDICTION_FLUSHED = "prediction_flushed"  # AD-633b cache entry evicted (TTL or capacity)
    PREDICTION_ERROR_RECORDED = "prediction_error_recorded"  # AD-633h prediction diverged from outcome

    # Self-improvement pipeline (AD-482)
    CAPABILITY_PROPOSAL_CREATED = "capability_proposal_created"  # AD-482b ProposalStore.submit
    CAPABILITY_PROPOSAL_APPROVED = "capability_proposal_approved"  # AD-482c ApprovalGate.approve
    CAPABILITY_PROPOSAL_REJECTED = "capability_proposal_rejected"  # AD-482c ApprovalGate.reject
    PIVOT_REFINE_DECIDED = "pivot_refine_decided"  # AD-482e ProposalStore.transition
    EVOLUTION_LESSON_RECORDED = "evolution_lesson_recorded"  # AD-482d EvolutionStore.record_lesson
    AGENT_VERSION_PROMOTED = "agent_version_promoted"  # AD-482g AgentVersionStore.register_version + 482h promote
===END REPLACE===
```

Verification: `grep -nE "CAPABILITY_PROPOSAL_(CREATED|APPROVED|REJECTED)|PIVOT_REFINE_DECIDED|EVOLUTION_LESSON_RECORDED|AGENT_VERSION_PROMOTED" src/probos/events.py` returns exactly 6 hits, all on enum lines.

---

## Section 1 — Pydantic config

### File: `src/probos/config.py`

Insert `SelfImprovementConfig` immediately after `PredictiveBranchingConfig` (line 1080). Add `SystemConfig.self_improvement` field adjacent to `SystemConfig.predictive_branching` (find the existing `predictive_branching: PredictiveBranchingConfig = Field(default_factory=PredictiveBranchingConfig)` line and insert after it).

```text
===MODIFY: src/probos/config.py===
===SEARCH===
    cheap_tier_min_confidence: float = Field(default=0.30, ge=0.0, le=1.0)
    standard_tier_min_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    anticipatory_tier_min_confidence: float = Field(default=0.85, ge=0.0, le=1.0)


class WorkingMemoryConfig(BaseModel):
===REPLACE===
    cheap_tier_min_confidence: float = Field(default=0.30, ge=0.0, le=1.0)
    standard_tier_min_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    anticipatory_tier_min_confidence: float = Field(default=0.85, ge=0.0, le=1.0)


class SelfImprovementConfig(BaseModel):
    """AD-482 v1: Self-improvement pipeline (proposal → approval → QA → evolution → versioning).

    Default-False — operator opt-in. The pipeline spawns real QA agents, opens a
    new ChromaDB collection, and writes promoted agents to
    ``src/probos/agents/designed/``. AD-633 / AD-695 default-False precedent.
    """

    enabled: bool = False
    qa_pool_size: int = Field(default=3, ge=1, le=8)
    iteration_cap: int = Field(default=5, ge=1, le=20)
    evolution_half_life_seconds: float = Field(default=2592000.0, ge=1.0)  # 30 days
    evolution_collection_name: str = "self_improvement_lessons"
    persistence_root_dir: str = "src/probos/agents/designed"


class WorkingMemoryConfig(BaseModel):
===END REPLACE===
```

Then add the field on `SystemConfig`. Find this anchor and extend:

```text
===SEARCH===
    predictive_branching: PredictiveBranchingConfig = Field(
        default_factory=PredictiveBranchingConfig
    )
===REPLACE===
    predictive_branching: PredictiveBranchingConfig = Field(
        default_factory=PredictiveBranchingConfig
    )
    self_improvement: SelfImprovementConfig = Field(
        default_factory=SelfImprovementConfig
    )
===END REPLACE===
```

**If the SEARCH anchor for `predictive_branching` field on `SystemConfig` does not match exactly** (the field may be on multiple lines, or already adjacent to other fields), use this fallback search:

```text
===FALLBACK SEARCH===
    predictive_branching: PredictiveBranchingConfig = Field(default_factory=PredictiveBranchingConfig)
===FALLBACK REPLACE===
    predictive_branching: PredictiveBranchingConfig = Field(default_factory=PredictiveBranchingConfig)
    self_improvement: SelfImprovementConfig = Field(default_factory=SelfImprovementConfig)
===END FALLBACK REPLACE===
```

Builder: try the multi-line form first; fall back to the single-line form if SEARCH misses.

---

## Section 2 — Package skeleton

### File: `src/probos/cognitive/self_improvement/__init__.py`

```text
===FILE: src/probos/cognitive/self_improvement/__init__.py===
"""AD-482 v1: Self-Improvement Pipeline package.

Stage Contracts (482a), Capability Proposals + PIVOT/REFINE (482b + 482e),
Approval Gate (482c), Evolution Store (482d), QA Agent Pool + Shapley (482f),
Agent Versioning + LocalDiskPersistence + Shadow Deployment seam (482g + 482h + 482i).

Forcing-function follow-ons:
- AD-482h-1: Git PR creation layer (subprocess git + GitHub MCP wiring).
- AD-482i-1: Concrete `ShadowDeploymentPolicy` impl (parallel-pool comparator with
  scaler-aware shadow workers — needs AD-280 territory).
"""

from probos.cognitive.self_improvement.approval_gate import ApprovalGate
from probos.cognitive.self_improvement.evolution_store import (
    EvolutionStore,
    Lesson,
)
from probos.cognitive.self_improvement.proposal import (
    CapabilityProposal,
    IterationGuard,
    PivotRefineDecision,
    ProposalState,
    ProposalStore,
)
from probos.cognitive.self_improvement.qa_pool import QAAgentPool, QAEvaluation
from probos.cognitive.self_improvement.stage_contract import StageContract
from probos.cognitive.self_improvement.versioning import (
    AgentPersistence,
    AgentVersion,
    AgentVersionStore,
    LocalDiskPersistence,
    NoOpShadowDeploymentPolicy,
    ShadowComparisonResult,
    ShadowDeploymentPolicy,
)

__all__ = [
    "AgentPersistence",
    "AgentVersion",
    "AgentVersionStore",
    "ApprovalGate",
    "CapabilityProposal",
    "EvolutionStore",
    "IterationGuard",
    "Lesson",
    "LocalDiskPersistence",
    "NoOpShadowDeploymentPolicy",
    "PivotRefineDecision",
    "ProposalState",
    "ProposalStore",
    "QAAgentPool",
    "QAEvaluation",
    "ShadowComparisonResult",
    "ShadowDeploymentPolicy",
    "StageContract",
]
===END FILE===
```

---

## Section 3 — AD-482a Stage Contract

### File: `src/probos/cognitive/self_improvement/stage_contract.py`

```text
===FILE: src/probos/cognitive/self_improvement/stage_contract.py===
"""AD-482a v1: Stage Contracts — typed I/O specs for inter-agent task handoffs.

A `StageContract` declares the shape of one stage in a multi-step workflow:
what inputs it expects, what outputs it produces, the definition of done, the
recoverable error codes, and the maximum retry count. Validation is shape-only
(structural keys + types) — no runtime coercion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StageContract:
    """Typed I/O specification for one stage in a self-improvement workflow.

    Args:
        name: Stage label (e.g. "discover", "evaluate", "qa", "promote").
        inputs: Required input keys mapped to expected Python types.
        outputs: Required output keys mapped to expected Python types.
        definition_of_done: Human-readable success criterion.
        error_codes: Recoverable error codes the caller may surface.
        max_retries: Maximum retry count before the stage fails terminal.
    """

    name: str
    inputs: dict[str, type]
    outputs: dict[str, type]
    definition_of_done: str
    error_codes: tuple[str, ...] = field(default_factory=tuple)
    max_retries: int = 3

    def validate_input(self, payload: dict[str, Any]) -> tuple[bool, str]:
        """Shape-check ``payload`` against ``self.inputs``.

        Returns (True, "") on conformance, or (False, reason) on the first miss.
        Type checks use ``isinstance`` on declared types; subclasses pass.
        """
        for key, expected_type in self.inputs.items():
            if key not in payload:
                return False, f"missing input key: {key!r}"
            if not isinstance(payload[key], expected_type):
                actual = type(payload[key]).__name__
                want = expected_type.__name__
                return False, f"input {key!r}: expected {want}, got {actual}"
        return True, ""

    def validate_output(self, payload: dict[str, Any]) -> tuple[bool, str]:
        """Shape-check ``payload`` against ``self.outputs``.

        Returns (True, "") on conformance, or (False, reason) on the first miss.
        """
        for key, expected_type in self.outputs.items():
            if key not in payload:
                return False, f"missing output key: {key!r}"
            if not isinstance(payload[key], expected_type):
                actual = type(payload[key]).__name__
                want = expected_type.__name__
                return False, f"output {key!r}: expected {want}, got {actual}"
        return True, ""
===END FILE===
```

---

## Section 4 — AD-482b + AD-482e Proposals + PIVOT/REFINE

### File: `src/probos/cognitive/self_improvement/proposal.py`

```text
===FILE: src/probos/cognitive/self_improvement/proposal.py===
"""AD-482b v1: Capability Proposals.
AD-482e v1: PIVOT/REFINE Decision Loops + IterationGuard.

A `CapabilityProposal` is a typed schema for "here's what was found, why it
matters, and how it fits." Submitted by any agent (research, scout, code
reviewer); flows through the `ApprovalGate` queue (AD-482c).

`PivotRefineDecision` is the autonomous decision primitive: PROCEED (advance to
next stage), REFINE (tweak and retry — counts against IterationGuard cap), or
PIVOT (abandon and try a different approach — terminal for this proposal).
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ProposalState(str, Enum):
    """Lifecycle state of a CapabilityProposal."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REFINING = "refining"
    PIVOTED = "pivoted"


class PivotRefineDecision(str, Enum):
    """AD-482e: autonomous decision primitive.

    PROCEED  — advance to next stage.
    REFINE   — tweak inputs and retry (counts against iteration cap).
    PIVOT    — abandon this approach (terminal for this proposal).
    """

    PROCEED = "proceed"
    REFINE = "refine"
    PIVOT = "pivot"


@dataclass(frozen=True)
class CapabilityProposal:
    """Typed proposal for a discovered capability.

    Mirrors roadmap.md:3672 — fields surface "what was found, why it matters,
    how it fits."
    """

    id: str
    source: str  # "repo", "paper", "api", "scout", "research", etc.
    source_url: str
    summary: str
    relevance: float  # 0.0 .. 1.0
    fit_assessment: str
    integration_effort_hours: float
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    license: str = ""
    submitted_at: float = 0.0
    submitter_agent_id: str = ""


@dataclass
class IterationGuard:
    """AD-482e: caps PIVOT/REFINE iterations and tracks artifact versions.

    Args:
        max_iterations: Hard cap on REFINE decisions before forcing PIVOT.
        decisions: Append-only log of (timestamp, decision) tuples.
        artifacts: Append-only log of (artifact_id, content_hash) tuples.
    """

    max_iterations: int
    decisions: list[tuple[float, PivotRefineDecision]] = field(default_factory=list)
    artifacts: list[tuple[str, str]] = field(default_factory=list)

    def register(self, decision: PivotRefineDecision, *, now: float | None = None) -> bool:
        """Register a decision. Returns False when REFINE cap exceeded."""
        ts = time.time() if now is None else now
        if decision is PivotRefineDecision.REFINE:
            refine_count = sum(1 for _, d in self.decisions if d is PivotRefineDecision.REFINE)
            if refine_count >= self.max_iterations:
                logger.warning(
                    "AD-482e: IterationGuard REFINE cap %d reached; rejecting",
                    self.max_iterations,
                )
                return False
        self.decisions.append((ts, decision))
        return True

    def record_artifact(self, artifact_id: str, content_hash: str) -> str:
        """Record an artifact version. Returns the artifact_id."""
        self.artifacts.append((artifact_id, content_hash))
        return artifact_id


class ProposalStore:
    """In-memory append-only registry of CapabilityProposals.

    Terminal decisions (APPROVED, REJECTED, PIVOTED) emit a lesson to the
    EvolutionStore via ``evolution_store_callback`` (optional dependency
    injection — None disables lesson emission).
    """

    def __init__(
        self,
        *,
        evolution_store_callback: Callable[[str, str, str, str, dict[str, Any]], str] | None = None,
        event_emit_fn: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.time,
        iteration_cap: int = 5,
    ) -> None:
        self._records: dict[str, CapabilityProposal] = {}
        self._states: dict[str, ProposalState] = {}
        self._guards: dict[str, IterationGuard] = {}
        self._evolution_callback = evolution_store_callback
        self._emit = event_emit_fn
        self._clock = clock
        self._iteration_cap = iteration_cap

    def submit(self, proposal: CapabilityProposal) -> str:
        """Register a new proposal in PENDING state. Returns the proposal id."""
        if proposal.id in self._records:
            logger.warning(
                "AD-482b: duplicate proposal id %r; replacing existing entry",
                proposal.id,
            )
        # Stamp submitted_at if caller left it default
        if proposal.submitted_at == 0.0:
            stamped = CapabilityProposal(
                id=proposal.id,
                source=proposal.source,
                source_url=proposal.source_url,
                summary=proposal.summary,
                relevance=proposal.relevance,
                fit_assessment=proposal.fit_assessment,
                integration_effort_hours=proposal.integration_effort_hours,
                dependencies=proposal.dependencies,
                license=proposal.license,
                submitted_at=self._clock(),
                submitter_agent_id=proposal.submitter_agent_id,
            )
        else:
            stamped = proposal
        self._records[stamped.id] = stamped
        self._states[stamped.id] = ProposalState.PENDING
        self._guards[stamped.id] = IterationGuard(max_iterations=self._iteration_cap)
        self._emit_event("CAPABILITY_PROPOSAL_CREATED", stamped.id, "submit")
        return stamped.id

    def get(self, proposal_id: str) -> CapabilityProposal | None:
        return self._records.get(proposal_id)

    def list_pending(self) -> list[CapabilityProposal]:
        return [
            self._records[pid]
            for pid, state in self._states.items()
            if state is ProposalState.PENDING
        ]

    def state(self, proposal_id: str) -> ProposalState | None:
        return self._states.get(proposal_id)

    def guard(self, proposal_id: str) -> IterationGuard | None:
        return self._guards.get(proposal_id)

    def transition(
        self,
        proposal_id: str,
        decision: PivotRefineDecision,
        *,
        rationale: str = "",
    ) -> bool:
        """Apply a PIVOT/REFINE/PROCEED decision. Returns False on cap exceeded
        or unknown proposal id."""
        if proposal_id not in self._records:
            return False
        guard = self._guards[proposal_id]
        accepted = guard.register(decision, now=self._clock())
        if not accepted:
            return False
        if decision is PivotRefineDecision.PIVOT:
            self._states[proposal_id] = ProposalState.PIVOTED
            self._record_lesson(proposal_id, "pivot", rationale)
        elif decision is PivotRefineDecision.REFINE:
            self._states[proposal_id] = ProposalState.REFINING
        # PROCEED leaves state at PENDING (caller advances via approve/reject)
        self._emit_event("PIVOT_REFINE_DECIDED", proposal_id, decision.value, rationale=rationale)
        return True

    def update_state(
        self,
        proposal_id: str,
        new_state: ProposalState,
        *,
        rationale: str = "",
    ) -> bool:
        """Force-set the proposal state (used by ApprovalGate)."""
        if proposal_id not in self._records:
            return False
        old_state = self._states[proposal_id]
        self._states[proposal_id] = new_state
        if new_state in (ProposalState.APPROVED, ProposalState.REJECTED):
            self._record_lesson(proposal_id, new_state.value, rationale)
        logger.info(
            "AD-482b: proposal %s %s -> %s (%s)",
            proposal_id,
            old_state.value,
            new_state.value,
            rationale[:80] if rationale else "no rationale",
        )
        return True

    def _record_lesson(self, proposal_id: str, outcome: str, rationale: str) -> None:
        if self._evolution_callback is None:
            return
        try:
            proposal = self._records.get(proposal_id)
            if proposal is None:
                return
            payload = {
                "source": proposal.source,
                "fit_assessment": proposal.fit_assessment,
                "rationale": rationale,
            }
            self._evolution_callback(
                outcome,  # category
                proposal.summary,  # summary
                proposal_id,  # source_proposal_id
                outcome,  # outcome
                payload,  # payload
            )
        except Exception:
            logger.warning(
                "AD-482b: evolution_callback failed for proposal %s; lesson lost",
                proposal_id,
                exc_info=True,
            )

    def _emit_event(self, name: str, proposal_id: str, action: str, **extra: Any) -> None:
        if self._emit is None:
            return
        try:
            self._emit(name, {"proposal_id": proposal_id, "action": action, **extra})
        except Exception:
            logger.warning("AD-482b: event_emit %s failed", name, exc_info=True)


def make_proposal_id() -> str:
    """Return a new random proposal id (uuid4 hex prefix)."""
    return uuid.uuid4().hex[:12]
===END FILE===
```

---

## Section 5 — AD-482c Approval Gate

### File: `src/probos/cognitive/self_improvement/approval_gate.py`

```text
===FILE: src/probos/cognitive/self_improvement/approval_gate.py===
"""AD-482c v1: Human Approval Gate.

A `ProposalStore`-backed queue surface with approve/reject semantics. Wraps
(does NOT replace) the existing ``SelfModificationPipeline._user_approval_fn``
callback. Designed-agent flow can keep the bool callback OR route through
ApprovalGate (operator choice via config).

Audit trail: every decision emits a typed event and persists the rationale
to the proposal lesson record (AD-482d EvolutionStore terminal-decision flow).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from probos.cognitive.self_improvement.proposal import (
    CapabilityProposal,
    ProposalState,
    ProposalStore,
)

logger = logging.getLogger(__name__)


class ApprovalGate:
    """Captain-facing approval queue for capability proposals."""

    def __init__(
        self,
        *,
        proposal_store: ProposalStore,
        event_emit_fn: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._proposals = proposal_store
        self._emit = event_emit_fn
        self._clock = clock
        # audit_log: append-only (proposal_id, decision, approver, ts, rationale)
        self._audit_log: list[tuple[str, str, str, float, str]] = []

    def enqueue(self, proposal: CapabilityProposal) -> str:
        """Add a proposal to the pending queue. Returns the proposal id.

        This is a thin wrapper over `ProposalStore.submit` for callers that
        prefer the queue-language API.
        """
        return self._proposals.submit(proposal)

    def pending_count(self) -> int:
        return len(self._proposals.list_pending())

    def list_pending(self) -> list[CapabilityProposal]:
        return self._proposals.list_pending()

    def approve(
        self,
        proposal_id: str,
        *,
        approver: str,
        modifications: dict[str, Any] | None = None,
    ) -> bool:
        """Approve a proposal. Optional modifications dict captured in audit.

        Returns False if proposal_id is unknown or not in PENDING state.
        """
        state = self._proposals.state(proposal_id)
        if state is None or state is not ProposalState.PENDING:
            logger.warning(
                "AD-482c: approve %s rejected — state is %s",
                proposal_id,
                state.value if state else "unknown",
            )
            return False
        rationale = "approved"
        if modifications:
            rationale = f"approved with modifications: {sorted(modifications.keys())}"
        ok = self._proposals.update_state(
            proposal_id, ProposalState.APPROVED, rationale=rationale,
        )
        if not ok:
            return False
        self._audit_log.append(
            (proposal_id, "approve", approver, self._clock(), rationale),
        )
        self._emit_event(
            "CAPABILITY_PROPOSAL_APPROVED",
            proposal_id=proposal_id,
            approver=approver,
            modifications=modifications or {},
        )
        return True

    def reject(self, proposal_id: str, *, approver: str, reason: str) -> bool:
        """Reject a proposal with a required rationale.

        Returns False if proposal_id is unknown or not in PENDING state.
        """
        state = self._proposals.state(proposal_id)
        if state is None or state is not ProposalState.PENDING:
            logger.warning(
                "AD-482c: reject %s rejected — state is %s",
                proposal_id,
                state.value if state else "unknown",
            )
            return False
        if not reason:
            logger.warning("AD-482c: reject %s requires non-empty reason", proposal_id)
            return False
        ok = self._proposals.update_state(
            proposal_id, ProposalState.REJECTED, rationale=reason,
        )
        if not ok:
            return False
        self._audit_log.append(
            (proposal_id, "reject", approver, self._clock(), reason),
        )
        self._emit_event(
            "CAPABILITY_PROPOSAL_REJECTED",
            proposal_id=proposal_id,
            approver=approver,
            reason=reason,
        )
        return True

    def audit_entries(self, *, proposal_id: str | None = None) -> list[tuple[str, str, str, float, str]]:
        """Return a copy of the audit log, optionally filtered by proposal_id."""
        if proposal_id is None:
            return list(self._audit_log)
        return [entry for entry in self._audit_log if entry[0] == proposal_id]

    def _emit_event(self, name: str, **payload: Any) -> None:
        if self._emit is None:
            return
        try:
            self._emit(name, payload)
        except Exception:
            logger.warning("AD-482c: event_emit %s failed", name, exc_info=True)
===END FILE===
```

---

## Section 6 — AD-482d Evolution Store

### File: `src/probos/cognitive/self_improvement/evolution_store.py`

```text
===FILE: src/probos/cognitive/self_improvement/evolution_store.py===
"""AD-482d v1: Evolution Store — append-only lessons learned with time-decay.

ChromaDB-backed semantic store mirroring `EpisodicMemory` construction shape,
but on a separate collection (``self_improvement_lessons``) and with a
time-decay weighting layered over cosine similarity.

Tier-2 log-and-degrade: when ``chroma_client`` is None the store keeps lessons
in an in-memory list and serves recall via plain substring matching. The
public API contract is identical in both modes.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Lesson:
    """One append-only lesson record."""

    id: str
    category: str  # "approved", "rejected", "pivot", custom
    summary: str
    source_proposal_id: str
    outcome: str
    timestamp: float
    payload: dict[str, Any] = field(default_factory=dict)


class EvolutionStore:
    """Append-only lessons store with time-decay recall."""

    def __init__(
        self,
        *,
        chroma_client: Any = None,
        collection_name: str = "self_improvement_lessons",
        clock: Callable[[], float] = time.time,
        half_life_seconds: float = 2592000.0,  # 30 days
        event_emit_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._client = chroma_client
        self._collection_name = collection_name
        self._clock = clock
        self._half_life = max(1.0, half_life_seconds)
        self._emit = event_emit_fn
        self._collection: Any = None
        self._fallback: list[Lesson] = []  # used when chroma is None

    def start(self) -> None:
        """Open the chroma collection. Tier-2 log-and-degrade on failure.

        Safe to call multiple times — idempotent.
        """
        if self._client is None:
            return
        if self._collection is not None:
            return
        try:
            from probos.knowledge.embeddings import get_embedding_function

            ef = get_embedding_function()
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                embedding_function=ef,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception:
            logger.warning(
                "AD-482d: failed to open chroma collection %r; falling back to in-memory",
                self._collection_name,
                exc_info=True,
            )
            self._collection = None

    def record_lesson(
        self,
        category: str,
        summary: str,
        source_proposal_id: str,
        outcome: str,
        payload: dict[str, Any],
    ) -> str:
        """Append a lesson. Returns the lesson id."""
        lesson = Lesson(
            id=uuid.uuid4().hex[:12],
            category=category,
            summary=summary,
            source_proposal_id=source_proposal_id,
            outcome=outcome,
            timestamp=self._clock(),
            payload=dict(payload),
        )
        if self._collection is not None:
            try:
                self._collection.add(
                    ids=[lesson.id],
                    documents=[lesson.summary],
                    metadatas=[
                        {
                            "category": lesson.category,
                            "source_proposal_id": lesson.source_proposal_id,
                            "outcome": lesson.outcome,
                            "timestamp": lesson.timestamp,
                        }
                    ],
                )
            except Exception:
                logger.warning(
                    "AD-482d: chroma add failed for lesson %s; falling back",
                    lesson.id,
                    exc_info=True,
                )
                self._fallback.append(lesson)
        else:
            self._fallback.append(lesson)
        self._emit_event(
            "EVOLUTION_LESSON_RECORDED",
            lesson_id=lesson.id,
            category=lesson.category,
            outcome=lesson.outcome,
        )
        return lesson.id

    def recall(
        self,
        query: str,
        *,
        top_k: int = 5,
        now: float | None = None,
    ) -> list[Lesson]:
        """Return top-k lessons ranked by ``similarity * time_decay``.

        Time decay: ``0.5 ** ((now - timestamp) / half_life)``.
        Older lessons fade; recent lessons retained.
        """
        when = self._clock() if now is None else now
        if self._collection is not None:
            try:
                hits = self._collection.query(query_texts=[query], n_results=max(top_k * 2, top_k))
                ids_batch = hits.get("ids") or [[]]
                docs_batch = hits.get("documents") or [[]]
                metas_batch = hits.get("metadatas") or [[]]
                dists_batch = hits.get("distances") or [[]]
                ids = ids_batch[0] if ids_batch else []
                docs = docs_batch[0] if docs_batch else []
                metas = metas_batch[0] if metas_batch else []
                dists = dists_batch[0] if dists_batch else [0.0] * len(ids)
                scored: list[tuple[float, Lesson]] = []
                for lid, doc, meta, dist in zip(ids, docs, metas, dists, strict=False):
                    similarity = max(0.0, 1.0 - float(dist))
                    ts = float(meta.get("timestamp", when))
                    age = max(0.0, when - ts)
                    decay = 0.5 ** (age / self._half_life)
                    score = similarity * decay
                    lesson = Lesson(
                        id=lid,
                        category=str(meta.get("category", "")),
                        summary=str(doc),
                        source_proposal_id=str(meta.get("source_proposal_id", "")),
                        outcome=str(meta.get("outcome", "")),
                        timestamp=ts,
                        payload={},
                    )
                    scored.append((score, lesson))
                scored.sort(key=lambda x: x[0], reverse=True)
                return [lesson for _, lesson in scored[:top_k]]
            except Exception:
                logger.warning(
                    "AD-482d: chroma query failed; using in-memory fallback",
                    exc_info=True,
                )
        # Fallback: substring match + time-decay
        scored: list[tuple[float, Lesson]] = []
        q_lower = query.lower()
        for lesson in self._fallback:
            similarity = 1.0 if q_lower in lesson.summary.lower() else 0.1
            age = max(0.0, when - lesson.timestamp)
            decay = 0.5 ** (age / self._half_life)
            scored.append((similarity * decay, lesson))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [lesson for _, lesson in scored[:top_k]]

    def _emit_event(self, name: str, **payload: Any) -> None:
        if self._emit is None:
            return
        try:
            self._emit(name, payload)
        except Exception:
            logger.warning("AD-482d: event_emit %s failed", name, exc_info=True)
===END FILE===
```

---

## Section 7 — AD-482f QA Agent Pool + Shapley

### File: `src/probos/cognitive/self_improvement/qa_pool.py`

```text
===FILE: src/probos/cognitive/self_improvement/qa_pool.py===
"""AD-482f v1: QA Agent Pool with Shapley contribution scoring.

Wraps the existing `SystemQAAgent` template (single-instance utility agent)
into an N-instance pool. Each agent independently evaluates a candidate
designed-agent record; per-agent Shapley contribution is computed via
``compute_shapley_values`` over synthetic Vote records keyed on pass-count.

No new QA logic — existing `SystemQAAgent` handles behavioral / regression /
performance testing. This module is the aggregator + Shapley layer only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

from probos.consensus.shapley import compute_shapley_values
from probos.types import Vote

if TYPE_CHECKING:
    from probos.agents.system_qa import SystemQAAgent
    from probos.cognitive.self_mod import DesignedAgentRecord

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QAEvaluation:
    """Aggregated QA outcome over a pool of QA agents."""

    proposal_id: str
    pass_count: int
    fail_count: int
    overall_pass: bool
    shapley_contributions: dict[str, float] = field(default_factory=dict)
    per_agent_outcomes: dict[str, bool] = field(default_factory=dict)


class QAAgentPool:
    """Pool of QA agents with Shapley contribution scoring.

    Args:
        qa_agents: List of ``SystemQAAgent`` instances. v1 caller (the wirer)
            requests N instances from the spawner; if only 1 is available the
            pool degrades gracefully and the Shapley contribution is
            ``{single_agent_id: 1.0}``.
        approval_threshold: Quorum threshold (0..1) for ``overall_pass``.
            Default 0.5 — majority pass = overall pass.
        shapley_fn: Injectable Shapley computation. Default uses
            ``probos.consensus.shapley.compute_shapley_values``.
    """

    def __init__(
        self,
        *,
        qa_agents: list[Any],  # list[SystemQAAgent]
        approval_threshold: float = 0.5,
        shapley_fn: Callable[..., dict[str, float]] = compute_shapley_values,
    ) -> None:
        if not qa_agents:
            raise ValueError("AD-482f: QAAgentPool requires at least one QA agent")
        self._qa_agents = list(qa_agents)
        self._threshold = max(0.0, min(1.0, approval_threshold))
        self._shapley_fn = shapley_fn

    @property
    def size(self) -> int:
        return len(self._qa_agents)

    async def evaluate_proposal(
        self,
        *,
        proposal_id: str,
        candidate_record: Any,  # DesignedAgentRecord
    ) -> QAEvaluation:
        """Run all QA agents against the candidate record. Aggregate via Shapley.

        Each QA agent's ``smoke_test_record(candidate_record)`` returns a
        ``QAReport`` with a ``passed: bool`` field. Synthesize one ``Vote``
        per QA agent (yes when passed, no otherwise; confidence=1.0).
        Compute Shapley contributions across the votes.
        """
        per_agent_outcomes: dict[str, bool] = {}
        votes: list[Vote] = []
        for qa in self._qa_agents:
            agent_id = getattr(qa, "id", None) or f"qa_unknown_{id(qa)}"
            try:
                report = await qa.smoke_test_record(candidate_record)
                passed = bool(getattr(report, "passed", False))
            except Exception:
                logger.warning(
                    "AD-482f: QA agent %s smoke_test_record raised; counting as fail",
                    agent_id,
                    exc_info=True,
                )
                passed = False
            per_agent_outcomes[agent_id] = passed
            votes.append(
                Vote(agent_id=agent_id, vote="yes" if passed else "no", confidence=1.0)
            )

        pass_count = sum(1 for v in per_agent_outcomes.values() if v)
        fail_count = len(per_agent_outcomes) - pass_count
        overall_pass = (pass_count / max(1, len(per_agent_outcomes))) >= self._threshold

        try:
            contributions = self._shapley_fn(
                votes,
                approval_threshold=self._threshold,
                use_confidence_weights=True,
            )
        except Exception:
            logger.warning(
                "AD-482f: shapley_fn failed; emitting equal contributions",
                exc_info=True,
            )
            n = max(1, len(per_agent_outcomes))
            contributions = {aid: 1.0 / n for aid in per_agent_outcomes}

        return QAEvaluation(
            proposal_id=proposal_id,
            pass_count=pass_count,
            fail_count=fail_count,
            overall_pass=overall_pass,
            shapley_contributions=contributions,
            per_agent_outcomes=per_agent_outcomes,
        )
===END FILE===
```

**Builder note on `SystemQAAgent.smoke_test_record`:** Verify-first against `src/probos/agents/system_qa.py` — if the smoke-test method has a different name (`run_smoke_test` / `validate_record` / `evaluate`), use that exact name in the QAAgentPool. The QAReport import is already in `system_qa.py`. Do NOT invent a method that does not exist; if no QA evaluation method exists at HEAD, surface this as a Gate-1 hard-stop. The Builder's `verify-first` script `scripts/phantom-api-precheck.ps1` should catch any mismatch.

---

## Section 8 — AD-482g + AD-482h + AD-482i Versioning + Persistence + Shadow Seam

### File: `src/probos/cognitive/self_improvement/versioning.py`

```text
===FILE: src/probos/cognitive/self_improvement/versioning.py===
"""AD-482g v1: Agent Versioning.
AD-482h v1: Git-Backed Agent Persistence — `LocalDiskPersistence` default impl.
AD-482i v1: Shadow Deployment Protocol seam + NoOp default.

Three converging concerns in one module:

* `AgentVersion` dataclass + `AgentVersionStore` track parent-version lineage
  and per-version trust metadata for designed agents.
* `AgentPersistence` Protocol + `LocalDiskPersistence` default impl write
  promoted agent source to ``src/probos/agents/designed/{agent_type}_v{N}.py``
  plus a ``{agent_type}_v{N}.meta.yaml`` sidecar. Git PR creation is the
  AD-482h-1 follow-on (subprocess git + GitHub MCP wiring is its own AD).
* `ShadowDeploymentPolicy` Protocol + `NoOpShadowDeploymentPolicy` default
  ship as Protocol seam. Concrete impl is AD-482i-1 (parallel-pool comparator
  with scaler-aware shadow workers — needs AD-280 territory).
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.cognitive.self_mod import DesignedAgentRecord

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentVersion:
    """Version metadata for a designed agent."""

    version: int
    parent_version: int | None
    designed_at: float
    designer: str
    trust_alpha_at_promotion: float
    trust_beta_at_promotion: float
    source_hash: str
    persisted_path: str | None = None


@dataclass(frozen=True)
class ShadowComparisonResult:
    """Result of a shadow comparison between baseline and candidate versions.

    Concrete impl in AD-482i-1; v1 only ships the dataclass shape so the
    NoOp default can return a typed `None` without consumers crashing on
    field access.
    """

    baseline_version: int
    candidate_version: int
    baseline_score: float
    candidate_score: float
    sample_size: int
    confident_winner: int | None  # version number of winner, or None if tie/insufficient


class AgentPersistence(Protocol):
    """AD-482h v1: write a promoted agent's source to a permanent location."""

    async def promote(
        self,
        record: Any,  # DesignedAgentRecord
        version: AgentVersion,
    ) -> str:
        """Persist the record's source. Return the persisted path or "" on degrade."""
        ...


class ShadowDeploymentPolicy(Protocol):
    """AD-482i v1 (Protocol seam): compare baseline vs candidate versions in shadow.

    NoOp default returns None; AD-482i-1 follow-on ships a concrete impl once
    the parallel-pool comparator (AD-280 territory) lands.
    """

    async def shadow_compare(
        self,
        *,
        baseline_version: AgentVersion,
        candidate_version: AgentVersion,
        runtime: Any,
    ) -> ShadowComparisonResult | None:
        ...


class NoOpShadowDeploymentPolicy:
    """Default ShadowDeploymentPolicy. Always returns None (no-op)."""

    async def shadow_compare(
        self,
        *,
        baseline_version: AgentVersion,
        candidate_version: AgentVersion,
        runtime: Any,
    ) -> ShadowComparisonResult | None:
        return None


def compute_source_hash(source_code: str) -> str:
    """Stable SHA-256 hex digest of source code (first 16 chars)."""
    return hashlib.sha256(source_code.encode("utf-8")).hexdigest()[:16]


class LocalDiskPersistence:
    """AD-482h v1: write promoted agent source to local disk.

    Args:
        root_dir: Directory under which agent files are written. Default
            ``src/probos/agents/designed`` per roadmap.md:3733.
        clock: Time source for sidecar metadata.
    """

    def __init__(
        self,
        *,
        root_dir: str = "src/probos/agents/designed",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._root = Path(root_dir)
        self._clock = clock

    async def promote(self, record: Any, version: AgentVersion) -> str:
        """Write {agent_type}_v{N}.py + sidecar. Tier-2 log-and-degrade.

        Returns the persisted path on success, or "" on failure.
        """
        agent_type = getattr(record, "agent_type", "")
        source_code = getattr(record, "source_code", "")
        if not agent_type or not source_code:
            logger.warning(
                "AD-482h: promote skipped — record missing agent_type or source_code",
            )
            return ""
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            file_path = self._root / f"{agent_type}_v{version.version}.py"
            meta_path = self._root / f"{agent_type}_v{version.version}.meta.yaml"
            file_path.write_text(source_code, encoding="utf-8")
            meta_lines = [
                f"agent_type: {agent_type}",
                f"version: {version.version}",
                f"parent_version: {version.parent_version if version.parent_version is not None else 'null'}",
                f"designed_at: {version.designed_at}",
                f"designer: {version.designer}",
                f"trust_alpha_at_promotion: {version.trust_alpha_at_promotion}",
                f"trust_beta_at_promotion: {version.trust_beta_at_promotion}",
                f"source_hash: {version.source_hash}",
                f"promoted_at: {self._clock()}",
            ]
            meta_path.write_text("\n".join(meta_lines) + "\n", encoding="utf-8")
            return str(file_path)
        except Exception:
            logger.warning(
                "AD-482h: LocalDiskPersistence.promote failed for %s",
                agent_type,
                exc_info=True,
            )
            return ""


@dataclass
class AgentVersionStore:
    """In-memory version history per agent_type.

    Optional `RecordsStore` write-through for persistence is the AD-482g-1
    follow-on; v1 ships in-memory only.
    """

    _versions: dict[str, list[AgentVersion]] = field(default_factory=dict)
    _emit: Callable[..., Any] | None = None

    def __init__(
        self,
        *,
        event_emit_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._versions = {}
        self._emit = event_emit_fn

    def register_version(self, agent_type: str, version: AgentVersion) -> int:
        """Append a version to the history. Returns the version number."""
        history = self._versions.setdefault(agent_type, [])
        history.append(version)
        if self._emit is not None:
            try:
                self._emit(
                    "AGENT_VERSION_PROMOTED",
                    {
                        "agent_type": agent_type,
                        "version": version.version,
                        "parent_version": version.parent_version,
                        "persisted_path": version.persisted_path or "",
                        "source_hash": version.source_hash,
                    },
                )
            except Exception:
                logger.warning(
                    "AD-482g: AGENT_VERSION_PROMOTED emit failed for %s v%d",
                    agent_type,
                    version.version,
                    exc_info=True,
                )
        return version.version

    def latest(self, agent_type: str) -> AgentVersion | None:
        history = self._versions.get(agent_type)
        if not history:
            return None
        return history[-1]

    def history(self, agent_type: str) -> list[AgentVersion]:
        return list(self._versions.get(agent_type, []))

    def known_types(self) -> list[str]:
        return sorted(self._versions.keys())

    def next_version_number(self, agent_type: str) -> int:
        """Return the next sequential version number for ``agent_type``."""
        history = self._versions.get(agent_type)
        if not history:
            return 1
        return max(v.version for v in history) + 1
===END FILE===
```

---

## Section 9 — Finalize wirer

### File: `src/probos/startup/finalize.py`

Insert `_wire_self_improvement` immediately after `_wire_predictive_branching`. Find the wirer at line 762 and insert after the function body. Then add the invocation in `finalize_startup` immediately after the AD-633 invocation block (line 2521).

**A. Wirer function** — insert at end of file or adjacent to `_wire_predictive_branching`:

```text
===MODIFY: src/probos/startup/finalize.py===
===SEARCH===
def _wire_predictive_branching(*, runtime: Any, config: "SystemConfig") -> bool:
===REPLACE===
def _wire_self_improvement(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-482 v1: wire the self-improvement pipeline.

    Constructs and attaches:
    * ``runtime.proposal_store`` — ProposalStore with evolution-store callback.
    * ``runtime.approval_gate`` — ApprovalGate over ProposalStore.
    * ``runtime.evolution_store`` — EvolutionStore (chroma if available).
    * ``runtime.qa_agent_pool`` — QAAgentPool over up to N SystemQAAgent
      instances pulled from the spawner.
    * ``runtime.agent_version_store`` — AgentVersionStore.
    * ``runtime.agent_persistence`` — LocalDiskPersistence default impl.
    * ``runtime.shadow_deployment_policy`` — NoOpShadowDeploymentPolicy default.

    Tier-2 log-and-degrade: missing chroma_client downgrades EvolutionStore to
    in-memory fallback; missing spawner downgrades QAAgentPool to a single
    in-process SystemQAAgent (Shapley still produces equal contributions).
    """
    cfg = config.self_improvement
    if not cfg.enabled:
        logger.info("AD-482: self_improvement disabled — skipping wiring")
        return False

    try:
        from probos.cognitive.self_improvement import (
            ApprovalGate,
            EvolutionStore,
            LocalDiskPersistence,
            NoOpShadowDeploymentPolicy,
            ProposalStore,
            QAAgentPool,
            AgentVersionStore,
        )
    except Exception:
        logger.warning(
            "AD-482: self_improvement package import failed — skipping wiring",
            exc_info=True,
        )
        return False

    emit = getattr(runtime, "emit_event", None)
    chroma_client = getattr(runtime, "_chroma_client", None)

    evolution_store = EvolutionStore(
        chroma_client=chroma_client,
        collection_name=cfg.evolution_collection_name,
        half_life_seconds=cfg.evolution_half_life_seconds,
        event_emit_fn=emit,
    )
    try:
        evolution_store.start()
    except Exception:
        logger.warning(
            "AD-482d: EvolutionStore.start raised; continuing in fallback mode",
            exc_info=True,
        )

    proposal_store = ProposalStore(
        evolution_store_callback=evolution_store.record_lesson,
        event_emit_fn=emit,
        iteration_cap=cfg.iteration_cap,
    )

    approval_gate = ApprovalGate(
        proposal_store=proposal_store,
        event_emit_fn=emit,
    )

    # Pull QA agents from the spawner. Degrade to single in-process agent on absence.
    qa_agents: list[Any] = []
    spawner = getattr(runtime, "spawner", None)
    if spawner is not None:
        for _ in range(cfg.qa_pool_size):
            try:
                agent = spawner.spawn("system_qa")
                qa_agents.append(agent)
            except Exception:
                logger.warning(
                    "AD-482f: spawner.spawn('system_qa') failed; pool size %d short",
                    cfg.qa_pool_size,
                    exc_info=True,
                )
                break
    if not qa_agents:
        try:
            from probos.agents.system_qa import SystemQAAgent

            qa_agents = [SystemQAAgent(qa_id="qa_default_0", config=None)]
        except Exception:
            logger.warning(
                "AD-482f: fallback SystemQAAgent construction failed; QAAgentPool disabled",
                exc_info=True,
            )
            qa_agents = []

    qa_agent_pool: Any = None
    if qa_agents:
        try:
            qa_agent_pool = QAAgentPool(qa_agents=qa_agents)
        except Exception:
            logger.warning(
                "AD-482f: QAAgentPool construction failed",
                exc_info=True,
            )
            qa_agent_pool = None

    agent_version_store = AgentVersionStore(event_emit_fn=emit)
    agent_persistence = LocalDiskPersistence(root_dir=cfg.persistence_root_dir)
    shadow_deployment_policy = NoOpShadowDeploymentPolicy()

    runtime.proposal_store = proposal_store
    runtime.approval_gate = approval_gate
    runtime.evolution_store = evolution_store
    runtime.qa_agent_pool = qa_agent_pool
    runtime.agent_version_store = agent_version_store
    runtime.agent_persistence = agent_persistence
    runtime.shadow_deployment_policy = shadow_deployment_policy

    logger.info(
        "AD-482: self_improvement wired — qa_pool_size=%d, iteration_cap=%d, "
        "evolution_collection=%r",
        len(qa_agents) if qa_agents else 0,
        cfg.iteration_cap,
        cfg.evolution_collection_name,
    )
    return True


def _wire_predictive_branching(*, runtime: Any, config: "SystemConfig") -> bool:
===END REPLACE===
```

**B. Invocation in `finalize_startup`** — add after the AD-633 try/except block:

```text
===SEARCH===
    # AD-633: Wire PredictiveBranching after SubTaskExecutor so speculation
    # can dispatch chains. Tier-2 log-and-degrade.
    try:
        _wire_predictive_branching(runtime=runtime, config=config)
    except Exception:
        logger.warning(
            "AD-633: _wire_predictive_branching raised; predictive_branching disabled",
            exc_info=True,
        )
===REPLACE===
    # AD-633: Wire PredictiveBranching after SubTaskExecutor so speculation
    # can dispatch chains. Tier-2 log-and-degrade.
    try:
        _wire_predictive_branching(runtime=runtime, config=config)
    except Exception:
        logger.warning(
            "AD-633: _wire_predictive_branching raised; predictive_branching disabled",
            exc_info=True,
        )

    # AD-482: Wire SelfImprovementPipeline after PredictiveBranching. Default-False;
    # operator opt-in. Tier-2 log-and-degrade.
    try:
        _wire_self_improvement(runtime=runtime, config=config)
    except Exception:
        logger.warning(
            "AD-482: _wire_self_improvement raised; self_improvement disabled",
            exc_info=True,
        )
===END REPLACE===
```

**Builder note on `SystemQAAgent.__init__` signature:** The fallback construction `SystemQAAgent(qa_id="qa_default_0", config=None)` MAY fail if `SystemQAAgent`'s real ctor takes different parameters. Verify-first against `src/probos/agents/system_qa.py` and adjust the fallback ctor call to match the live signature. If the spawner path succeeds (ctor parameters are well-known internally), the fallback path may never execute — but the test in Section 11 forces the fallback, so the ctor call MUST match HEAD. Use `SystemQAAgent(...)` with whatever kwargs the live `__init__` requires; if it requires positional args, pass `None` placeholders or skip the fallback (set `qa_agents = []` and accept `qa_agent_pool = None`).

---

## Section 10 — Runtime attribute declarations

### File: `src/probos/runtime.py`

Add the seven public typed attributes near the existing `predictive_branching` declarations. Find the existing AD-633 attribute declarations and insert after them:

```text
===MODIFY: src/probos/runtime.py===
===SEARCH===
    self_mod_pipeline: SelfModificationPipeline | None
===REPLACE===
    self_mod_pipeline: SelfModificationPipeline | None
    proposal_store: Any | None  # AD-482b ProposalStore
    approval_gate: Any | None  # AD-482c ApprovalGate
    evolution_store: Any | None  # AD-482d EvolutionStore
    qa_agent_pool: Any | None  # AD-482f QAAgentPool
    agent_version_store: Any | None  # AD-482g AgentVersionStore
    agent_persistence: Any | None  # AD-482h LocalDiskPersistence
    shadow_deployment_policy: Any | None  # AD-482i NoOpShadowDeploymentPolicy
===END REPLACE===
```

And initialize to None in `__init__` adjacent to `self.self_mod_pipeline = None` (line 503):

```text
===SEARCH===
        self.self_mod_pipeline: SelfModificationPipeline | None = None
===REPLACE===
        self.self_mod_pipeline: SelfModificationPipeline | None = None
        self.proposal_store: Any | None = None  # AD-482b
        self.approval_gate: Any | None = None  # AD-482c
        self.evolution_store: Any | None = None  # AD-482d
        self.qa_agent_pool: Any | None = None  # AD-482f
        self.agent_version_store: Any | None = None  # AD-482g
        self.agent_persistence: Any | None = None  # AD-482h
        self.shadow_deployment_policy: Any | None = None  # AD-482i
===END REPLACE===
```

---

## Section 11 — Tests

### File: `tests/test_ad482_self_improvement.py`

42 tests across 9 classes. Follow the Wave 82 test-class shape — each class targets one sub-AD module.

```text
===FILE: tests/test_ad482_self_improvement.py===
"""AD-482 v1: Self-Improvement Pipeline tests.

Test classes:
  - TestStageContract       (4 tests, AD-482a)
  - TestCapabilityProposal  (4 tests, AD-482b)
  - TestPivotRefine         (3 tests, AD-482e)
  - TestApprovalGate        (6 tests, AD-482c)
  - TestEvolutionStore      (6 tests, AD-482d)
  - TestQAAgentPool         (7 tests, AD-482f)
  - TestVersioning          (3 tests, AD-482g)
  - TestPersistence         (4 tests, AD-482h)
  - TestShadowSeam          (2 tests, AD-482i)
  - TestConfigAndWiring     (2 tests)
  - TestIntegration         (1 test)

Total: 42 tests.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.self_improvement import (
    AgentPersistence,
    AgentVersion,
    AgentVersionStore,
    ApprovalGate,
    CapabilityProposal,
    EvolutionStore,
    IterationGuard,
    Lesson,
    LocalDiskPersistence,
    NoOpShadowDeploymentPolicy,
    PivotRefineDecision,
    ProposalState,
    ProposalStore,
    QAAgentPool,
    QAEvaluation,
    ShadowComparisonResult,
    ShadowDeploymentPolicy,
    StageContract,
)
from probos.cognitive.self_improvement.versioning import compute_source_hash


# ---------------------------------------------------------------------------
# AD-482a StageContract
# ---------------------------------------------------------------------------

class TestStageContract:
    def test_validate_input_happy_path(self) -> None:
        contract = StageContract(
            name="discover",
            inputs={"query": str, "max_results": int},
            outputs={"hits": list},
            definition_of_done="At least one hit returned.",
        )
        ok, reason = contract.validate_input({"query": "foo", "max_results": 5})
        assert ok is True
        assert reason == ""

    def test_validate_input_missing_key(self) -> None:
        contract = StageContract(
            name="discover",
            inputs={"query": str},
            outputs={},
            definition_of_done="",
        )
        ok, reason = contract.validate_input({})
        assert ok is False
        assert "missing input key" in reason
        assert "'query'" in reason

    def test_validate_input_type_mismatch(self) -> None:
        contract = StageContract(
            name="discover",
            inputs={"query": str},
            outputs={},
            definition_of_done="",
        )
        ok, reason = contract.validate_input({"query": 42})
        assert ok is False
        assert "expected str" in reason
        assert "got int" in reason

    def test_validate_output_happy_path(self) -> None:
        contract = StageContract(
            name="discover",
            inputs={},
            outputs={"hits": list},
            definition_of_done="",
        )
        ok, reason = contract.validate_output({"hits": [1, 2, 3]})
        assert ok is True
        assert reason == ""


# ---------------------------------------------------------------------------
# AD-482b CapabilityProposal + ProposalStore
# ---------------------------------------------------------------------------

def _make_proposal(pid: str = "p1", **kwargs: Any) -> CapabilityProposal:
    defaults = dict(
        id=pid,
        source="repo",
        source_url="https://example.com/x",
        summary="A discovered capability.",
        relevance=0.8,
        fit_assessment="Good fit.",
        integration_effort_hours=4.0,
        dependencies=("foo", "bar"),
        license="Apache-2.0",
        submitted_at=0.0,
        submitter_agent_id="research_1",
    )
    defaults.update(kwargs)
    return CapabilityProposal(**defaults)


class TestCapabilityProposal:
    def test_submit_and_get(self) -> None:
        store = ProposalStore(clock=lambda: 1234.0)
        pid = store.submit(_make_proposal("p1"))
        assert pid == "p1"
        got = store.get("p1")
        assert got is not None
        assert got.summary == "A discovered capability."
        assert got.submitted_at == 1234.0  # stamped by clock

    def test_list_pending_filters_terminal(self) -> None:
        store = ProposalStore(iteration_cap=3)
        store.submit(_make_proposal("p1"))
        store.submit(_make_proposal("p2"))
        store.update_state("p1", ProposalState.APPROVED, rationale="ok")
        pending = store.list_pending()
        assert [p.id for p in pending] == ["p2"]

    def test_submit_emits_capability_proposal_created(self) -> None:
        events: list[tuple[str, dict[str, Any]]] = []
        store = ProposalStore(event_emit_fn=lambda name, payload: events.append((name, payload)))
        store.submit(_make_proposal("p1"))
        assert any(name == "CAPABILITY_PROPOSAL_CREATED" for name, _ in events)

    def test_submit_routes_terminal_lesson_to_callback(self) -> None:
        captured: list[tuple[str, str, str, str, dict[str, Any]]] = []

        def cb(category: str, summary: str, source_proposal_id: str,
               outcome: str, payload: dict[str, Any]) -> str:
            captured.append((category, summary, source_proposal_id, outcome, payload))
            return "lesson_1"

        store = ProposalStore(evolution_store_callback=cb)
        store.submit(_make_proposal("p1"))
        store.update_state("p1", ProposalState.APPROVED, rationale="captain approved")
        assert len(captured) == 1
        assert captured[0][0] == "approved"
        assert captured[0][2] == "p1"


# ---------------------------------------------------------------------------
# AD-482e PIVOT/REFINE + IterationGuard
# ---------------------------------------------------------------------------

class TestPivotRefine:
    def test_iteration_guard_caps_refine(self) -> None:
        guard = IterationGuard(max_iterations=2)
        assert guard.register(PivotRefineDecision.REFINE, now=1.0) is True
        assert guard.register(PivotRefineDecision.REFINE, now=2.0) is True
        assert guard.register(PivotRefineDecision.REFINE, now=3.0) is False
        assert len(guard.decisions) == 2

    def test_proposal_store_transition_emits_pivot_refine_decided(self) -> None:
        events: list[tuple[str, dict[str, Any]]] = []
        store = ProposalStore(event_emit_fn=lambda name, payload: events.append((name, payload)))
        store.submit(_make_proposal("p1"))
        ok = store.transition("p1", PivotRefineDecision.PIVOT, rationale="dead end")
        assert ok is True
        assert store.state("p1") is ProposalState.PIVOTED
        assert any(name == "PIVOT_REFINE_DECIDED" for name, _ in events)

    def test_artifact_versioning_records_history(self) -> None:
        guard = IterationGuard(max_iterations=5)
        guard.record_artifact("a1", "hash1")
        guard.record_artifact("a1", "hash2")
        assert guard.artifacts == [("a1", "hash1"), ("a1", "hash2")]


# ---------------------------------------------------------------------------
# AD-482c ApprovalGate
# ---------------------------------------------------------------------------

class TestApprovalGate:
    def test_enqueue_and_pending_count(self) -> None:
        store = ProposalStore()
        gate = ApprovalGate(proposal_store=store)
        gate.enqueue(_make_proposal("p1"))
        gate.enqueue(_make_proposal("p2"))
        assert gate.pending_count() == 2

    def test_approve_transitions_state(self) -> None:
        store = ProposalStore()
        gate = ApprovalGate(proposal_store=store)
        gate.enqueue(_make_proposal("p1"))
        ok = gate.approve("p1", approver="captain")
        assert ok is True
        assert store.state("p1") is ProposalState.APPROVED

    def test_approve_unknown_returns_false(self) -> None:
        gate = ApprovalGate(proposal_store=ProposalStore())
        assert gate.approve("missing", approver="captain") is False

    def test_reject_requires_reason(self) -> None:
        store = ProposalStore()
        gate = ApprovalGate(proposal_store=store)
        gate.enqueue(_make_proposal("p1"))
        assert gate.reject("p1", approver="captain", reason="") is False
        assert store.state("p1") is ProposalState.PENDING

    def test_reject_emits_capability_proposal_rejected(self) -> None:
        events: list[tuple[str, dict[str, Any]]] = []
        store = ProposalStore()
        gate = ApprovalGate(
            proposal_store=store,
            event_emit_fn=lambda name, payload: events.append((name, payload)),
        )
        gate.enqueue(_make_proposal("p1"))
        gate.reject("p1", approver="captain", reason="not aligned")
        assert any(name == "CAPABILITY_PROPOSAL_REJECTED" for name, _ in events)

    def test_audit_entries_filter_by_proposal_id(self) -> None:
        store = ProposalStore()
        gate = ApprovalGate(proposal_store=store, clock=lambda: 7.0)
        gate.enqueue(_make_proposal("p1"))
        gate.enqueue(_make_proposal("p2"))
        gate.approve("p1", approver="captain")
        gate.reject("p2", approver="captain", reason="duplicate")
        assert len(gate.audit_entries(proposal_id="p1")) == 1
        assert gate.audit_entries(proposal_id="p1")[0][1] == "approve"


# ---------------------------------------------------------------------------
# AD-482d EvolutionStore
# ---------------------------------------------------------------------------

class TestEvolutionStore:
    def test_record_lesson_in_memory_fallback(self) -> None:
        store = EvolutionStore(chroma_client=None)
        lid = store.record_lesson(
            "approved", "Integrated foo lib", "p1", "approved", {"k": "v"},
        )
        assert isinstance(lid, str) and len(lid) == 12

    def test_recall_substring_match_with_decay(self) -> None:
        clock_value = [1000.0]

        def clock() -> float:
            return clock_value[0]

        store = EvolutionStore(chroma_client=None, clock=clock, half_life_seconds=10.0)
        store.record_lesson("approved", "Integrated requests library", "p1", "approved", {})
        clock_value[0] = 1100.0  # 100s later (10 half-lives → ~1/1024 weight)
        store.record_lesson("approved", "Skipped numpy migration", "p2", "approved", {})
        # "requests" matches lesson 1 substring; lesson 2 is recent. Recent dominates.
        results = store.recall("foo", top_k=2)
        assert len(results) == 2
        # Lesson 2 is more recent → higher weight despite weaker similarity.
        assert results[0].source_proposal_id == "p2"

    def test_record_lesson_emits_evolution_lesson_recorded(self) -> None:
        events: list[tuple[str, dict[str, Any]]] = []
        store = EvolutionStore(
            chroma_client=None,
            event_emit_fn=lambda name, payload: events.append((name, payload)),
        )
        store.record_lesson("rejected", "X did not fit", "p3", "rejected", {})
        assert any(name == "EVOLUTION_LESSON_RECORDED" for name, _ in events)

    def test_start_with_chroma_client_opens_collection(self) -> None:
        client = MagicMock()
        store = EvolutionStore(chroma_client=client)
        store.start()
        assert client.get_or_create_collection.called

    def test_start_idempotent(self) -> None:
        client = MagicMock()
        store = EvolutionStore(chroma_client=client)
        store.start()
        store.start()
        # Only one collection-open call regardless of repeated start
        assert client.get_or_create_collection.call_count == 1

    def test_recall_returns_top_k_only(self) -> None:
        store = EvolutionStore(chroma_client=None)
        for i in range(7):
            store.record_lesson("approved", f"lesson {i}", f"p{i}", "approved", {})
        results = store.recall("lesson", top_k=3)
        assert len(results) == 3


# ---------------------------------------------------------------------------
# AD-482f QAAgentPool
# ---------------------------------------------------------------------------

class _FakeQAReport:
    def __init__(self, passed: bool) -> None:
        self.passed = passed


class _FakeQAAgent:
    def __init__(self, agent_id: str, passed: bool, *, raise_exc: bool = False) -> None:
        self.id = agent_id
        self._passed = passed
        self._raise = raise_exc

    async def smoke_test_record(self, candidate_record: Any) -> Any:
        if self._raise:
            raise RuntimeError("simulated qa failure")
        return _FakeQAReport(self._passed)


class TestQAAgentPool:
    def test_requires_at_least_one_agent(self) -> None:
        with pytest.raises(ValueError):
            QAAgentPool(qa_agents=[])

    @pytest.mark.asyncio
    async def test_evaluate_proposal_all_pass(self) -> None:
        pool = QAAgentPool(
            qa_agents=[_FakeQAAgent("qa1", True), _FakeQAAgent("qa2", True), _FakeQAAgent("qa3", True)],
        )
        eval_ = await pool.evaluate_proposal(
            proposal_id="p1", candidate_record=SimpleNamespace(),
        )
        assert eval_.pass_count == 3
        assert eval_.fail_count == 0
        assert eval_.overall_pass is True

    @pytest.mark.asyncio
    async def test_evaluate_proposal_majority_pass(self) -> None:
        pool = QAAgentPool(
            qa_agents=[_FakeQAAgent("qa1", True), _FakeQAAgent("qa2", True), _FakeQAAgent("qa3", False)],
        )
        eval_ = await pool.evaluate_proposal(
            proposal_id="p1", candidate_record=SimpleNamespace(),
        )
        assert eval_.pass_count == 2
        assert eval_.fail_count == 1
        assert eval_.overall_pass is True

    @pytest.mark.asyncio
    async def test_evaluate_proposal_minority_pass_overall_fail(self) -> None:
        pool = QAAgentPool(
            qa_agents=[_FakeQAAgent("qa1", True), _FakeQAAgent("qa2", False), _FakeQAAgent("qa3", False)],
        )
        eval_ = await pool.evaluate_proposal(
            proposal_id="p1", candidate_record=SimpleNamespace(),
        )
        assert eval_.overall_pass is False

    @pytest.mark.asyncio
    async def test_evaluate_proposal_qa_exception_counts_as_fail(self) -> None:
        pool = QAAgentPool(
            qa_agents=[_FakeQAAgent("qa1", True), _FakeQAAgent("qa2", True, raise_exc=True)],
        )
        eval_ = await pool.evaluate_proposal(
            proposal_id="p1", candidate_record=SimpleNamespace(),
        )
        assert eval_.per_agent_outcomes["qa2"] is False

    @pytest.mark.asyncio
    async def test_evaluate_proposal_shapley_contributions_sum_to_about_one(self) -> None:
        pool = QAAgentPool(
            qa_agents=[_FakeQAAgent("qa1", True), _FakeQAAgent("qa2", True), _FakeQAAgent("qa3", True)],
        )
        eval_ = await pool.evaluate_proposal(
            proposal_id="p1", candidate_record=SimpleNamespace(),
        )
        total = sum(eval_.shapley_contributions.values())
        assert 0.99 <= total <= 1.01

    @pytest.mark.asyncio
    async def test_size_property(self) -> None:
        pool = QAAgentPool(qa_agents=[_FakeQAAgent("qa1", True)])
        assert pool.size == 1


# ---------------------------------------------------------------------------
# AD-482g Versioning
# ---------------------------------------------------------------------------

def _make_version(version: int = 1, parent: int | None = None) -> AgentVersion:
    return AgentVersion(
        version=version,
        parent_version=parent,
        designed_at=1000.0,
        designer="captain",
        trust_alpha_at_promotion=1.0,
        trust_beta_at_promotion=3.0,
        source_hash=compute_source_hash(f"src_v{version}"),
    )


class TestVersioning:
    def test_register_and_latest(self) -> None:
        store = AgentVersionStore()
        store.register_version("foo_agent", _make_version(1))
        store.register_version("foo_agent", _make_version(2, parent=1))
        latest = store.latest("foo_agent")
        assert latest is not None
        assert latest.version == 2
        assert latest.parent_version == 1

    def test_history_returns_copy(self) -> None:
        store = AgentVersionStore()
        store.register_version("foo_agent", _make_version(1))
        history = store.history("foo_agent")
        history.append(_make_version(99))  # mutate copy
        assert len(store.history("foo_agent")) == 1

    def test_register_version_emits_agent_version_promoted(self) -> None:
        events: list[tuple[str, dict[str, Any]]] = []
        store = AgentVersionStore(event_emit_fn=lambda name, payload: events.append((name, payload)))
        store.register_version("foo_agent", _make_version(1))
        assert any(name == "AGENT_VERSION_PROMOTED" for name, _ in events)


# ---------------------------------------------------------------------------
# AD-482h LocalDiskPersistence
# ---------------------------------------------------------------------------

class TestPersistence:
    @pytest.mark.asyncio
    async def test_promote_writes_source_and_sidecar(self, tmp_path: Path) -> None:
        persistence = LocalDiskPersistence(root_dir=str(tmp_path))
        record = SimpleNamespace(agent_type="foo_agent", source_code="def x():\n    pass\n")
        version = _make_version(1)
        path = await persistence.promote(record, version)
        assert path
        assert (tmp_path / "foo_agent_v1.py").read_text() == "def x():\n    pass\n"
        meta_text = (tmp_path / "foo_agent_v1.meta.yaml").read_text()
        assert "agent_type: foo_agent" in meta_text
        assert "version: 1" in meta_text

    @pytest.mark.asyncio
    async def test_promote_skips_when_record_missing_fields(self, tmp_path: Path) -> None:
        persistence = LocalDiskPersistence(root_dir=str(tmp_path))
        record = SimpleNamespace(agent_type="", source_code="")
        version = _make_version(1)
        path = await persistence.promote(record, version)
        assert path == ""
        assert not list(tmp_path.iterdir())

    @pytest.mark.asyncio
    async def test_promote_handles_oserror_log_and_degrade(self, tmp_path: Path) -> None:
        # Point root_dir at an existing FILE so mkdir fails
        bad_path = tmp_path / "blocker"
        bad_path.write_text("blocker")
        persistence = LocalDiskPersistence(root_dir=str(bad_path / "designed"))
        record = SimpleNamespace(agent_type="foo_agent", source_code="x")
        version = _make_version(1)
        path = await persistence.promote(record, version)
        assert path == ""

    def test_compute_source_hash_stable(self) -> None:
        h1 = compute_source_hash("foo")
        h2 = compute_source_hash("foo")
        assert h1 == h2
        assert len(h1) == 16


# ---------------------------------------------------------------------------
# AD-482i Shadow Deployment seam
# ---------------------------------------------------------------------------

class TestShadowSeam:
    @pytest.mark.asyncio
    async def test_noop_returns_none(self) -> None:
        policy = NoOpShadowDeploymentPolicy()
        result = await policy.shadow_compare(
            baseline_version=_make_version(1),
            candidate_version=_make_version(2, parent=1),
            runtime=SimpleNamespace(),
        )
        assert result is None

    def test_shadow_comparison_result_dataclass_shape(self) -> None:
        result = ShadowComparisonResult(
            baseline_version=1,
            candidate_version=2,
            baseline_score=0.7,
            candidate_score=0.9,
            sample_size=50,
            confident_winner=2,
        )
        assert result.confident_winner == 2


# ---------------------------------------------------------------------------
# Config + wiring
# ---------------------------------------------------------------------------

class TestConfigAndWiring:
    def test_config_default_disabled(self) -> None:
        from probos.config import SelfImprovementConfig

        cfg = SelfImprovementConfig()
        assert cfg.enabled is False
        assert cfg.qa_pool_size == 3
        assert cfg.iteration_cap == 5
        assert cfg.evolution_collection_name == "self_improvement_lessons"

    def test_wirer_skips_when_disabled(self) -> None:
        from probos.config import SystemConfig
        from probos.startup.finalize import _wire_self_improvement

        runtime = SimpleNamespace(
            _chroma_client=None,
            spawner=None,
            emit_event=None,
            proposal_store=None,
            approval_gate=None,
            evolution_store=None,
            qa_agent_pool=None,
            agent_version_store=None,
            agent_persistence=None,
            shadow_deployment_policy=None,
        )
        config = SystemConfig()
        wired = _wire_self_improvement(runtime=runtime, config=config)
        assert wired is False
        assert runtime.proposal_store is None


# ---------------------------------------------------------------------------
# Integration — proposal → approve → evolution lesson → version → persist
# ---------------------------------------------------------------------------

class TestIntegration:
    @pytest.mark.asyncio
    async def test_full_lifecycle(self, tmp_path: Path) -> None:
        events: list[tuple[str, dict[str, Any]]] = []

        def emit(name: str, payload: dict[str, Any]) -> None:
            events.append((name, payload))

        # Wire pipeline manually (skip wirer; default-False)
        evolution = EvolutionStore(chroma_client=None, event_emit_fn=emit)
        proposals = ProposalStore(
            evolution_store_callback=evolution.record_lesson,
            event_emit_fn=emit,
        )
        gate = ApprovalGate(proposal_store=proposals, event_emit_fn=emit)
        versions = AgentVersionStore(event_emit_fn=emit)
        persistence = LocalDiskPersistence(root_dir=str(tmp_path))

        # Submit + approve
        proposal = _make_proposal(
            "p1", summary="Add foo_agent capability", submitted_at=0.0,
        )
        gate.enqueue(proposal)
        assert gate.approve("p1", approver="captain") is True
        assert proposals.state("p1") is ProposalState.APPROVED

        # Lesson should have been emitted on approval
        names = [n for n, _ in events]
        assert "CAPABILITY_PROPOSAL_CREATED" in names
        assert "CAPABILITY_PROPOSAL_APPROVED" in names
        assert "EVOLUTION_LESSON_RECORDED" in names

        # Register version + promote
        version = _make_version(1)
        versions.register_version("foo_agent", version)
        record = SimpleNamespace(agent_type="foo_agent", source_code="def x(): pass\n")
        persisted_path = await persistence.promote(record, version)
        assert persisted_path
        assert (tmp_path / "foo_agent_v1.py").exists()
        assert (tmp_path / "foo_agent_v1.meta.yaml").exists()

        # Recall should surface the approval lesson
        hits = evolution.recall("foo_agent capability", top_k=3)
        assert hits  # at least one lesson recalled
        assert hits[0].source_proposal_id == "p1"
===END FILE===
```

---

## What this AD does NOT change

- **No HXI surface.** `/api/proposals` router and HXI proposal-queue panel are AD-482-HXI follow-on (scope creep).
- **No new Intent.** Capability proposals are submitted via direct `runtime.proposal_store.submit(...)` API; decomposer integration is out of scope.
- **No `SelfModificationPipeline` ctor change.** The existing `register_fn` / `create_pool_fn` / `set_trust_fn` Callable shape predates Protocols; preserving back-compat. New abstractions (`AgentPersistence`, `ShadowDeploymentPolicy`) use Protocols per Engineering Principles.
- **No git PR creation.** `LocalDiskPersistence` writes to disk; AD-482h-1 follow-on adds subprocess-git + GitHub MCP wiring.
- **No parallel-pool comparator.** `ShadowDeploymentPolicy` is a Protocol seam with NoOp default; AD-482i-1 follow-on ships concrete impl after AD-280-style scaler-aware shadow-pool support lands.
- **No new QA agent class.** `SystemQAAgent` is reused as-is; `QAAgentPool` is the wrapper + Shapley aggregator.
- **No Shapley re-implementation.** `compute_shapley_values` is reused as-is.
- **No EpisodicMemory schema change.** `EvolutionStore` opens a separate ChromaDB collection (`self_improvement_lessons`) on the same client.
- **No `runtime.spawner` / `runtime.pools` API change.** Wirer reads existing public APIs.
- **No agent template re-registration.** `system_qa` template stays as-is; QAAgentPool reuses spawner output.
- **No `chat.py` router changes.** Self-mod approval flow continues to use `_user_approval_fn` for the existing designed-agent pathway.

## Tracking

- **`PROGRESS.md`** — append CLOSED entry for AD-482 v1 closure (Wave 83) with sub-AD breakdown (a-h concrete, i Protocol seam) and test count delta.
- **`docs/development/roadmap.md`** — no updates needed (AD-482 entry already lists all 8 sub-ADs; the closure note in GH #76 carries the v1 scope decision).
- **`DECISIONS.md`** — no new AD assignment in this wave (AD-482 is the umbrella; sub-AD letters pre-allocated by roadmap). DLog entries for follow-on AD-482h-1 / AD-482i-1 will be filed when those waves land.

## Acceptance Criteria

- [ ] Pytest baseline 11614 → ≥ 11654 (Δ ≥ +40). All 42 new tests in `tests/test_ad482_self_improvement.py` pass.
- [ ] All 6 new EventTypes present in `src/probos/events.py` and verified by grep.
- [ ] `SelfImprovementConfig.enabled` defaults to False; `qa_pool_size=3`, `iteration_cap=5`, `evolution_half_life_seconds=2592000.0`.
- [ ] `_wire_self_improvement` invoked immediately after `_wire_predictive_branching`; tier-2 log-and-degrade on missing chroma_client / spawner.
- [ ] `runtime.proposal_store` / `runtime.approval_gate` / `runtime.evolution_store` / `runtime.qa_agent_pool` / `runtime.agent_version_store` / `runtime.agent_persistence` / `runtime.shadow_deployment_policy` declared as public typed attributes.
- [ ] All 7 modules in `src/probos/cognitive/self_improvement/` import cleanly (smoke import test under wirer).
- [ ] Phantom-API pre-check on this prompt body returns 0 NEW phantoms (intra-prompt-introduction FPs are expected for the new Protocols / dataclasses / module functions).
- [ ] No `HXI` / vitest changes.
- [ ] No commercial language anywhere in dispatch, prompt, or wave-plan notes (the two banned phrases enforced by the pre-commit hook + `pricing` + `revenue` — 0 hits across all wave artifacts).
- [ ] Pre-commit deletion sanity: max ~5 deletions per existing source file (additive-only changes — events.py +6 enum lines, config.py +12 lines + 1 field, finalize.py +90 lines wirer + invocation block, runtime.py +14 lines).
- [ ] **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  ccd1008

# Highest AD stem in trackers (no new number minted by this wave):
grep -nE "AD-69[0-9]" PROGRESS.md progress-era-4-evolution.md | head
  AD-696 (Wave 72)
  AD-695 (Wave 73)
  AD-694, AD-693, AD-692, AD-691, AD-690, AD-689, AD-688

# AD-482 sub-AD letters from roadmap.md (verbatim):
docs/development/roadmap.md:3665    "Stage Contracts (Typed Agent Handoffs) (AD-482)"
docs/development/roadmap.md:3671    "Capability Proposal Format (AD-482)"
docs/development/roadmap.md:3677    "Human Approval Gate (AD-482)"
docs/development/roadmap.md:3684    "QA Agent Pool (AD-482)"
docs/development/roadmap.md:3692    "Evolution Store (AD-482)"
docs/development/roadmap.md:3699    "PIVOT/REFINE Decision Loops (AD-482)"
docs/development/roadmap.md:3720    "Agent Versioning + Shadow Deployment (deferred from Phase 14c) (AD-482)"
docs/development/roadmap.md:3732    "Git-Backed Agent Persistence (AD-482)"

# Existing self-mod substrate (verified shipped):
src/probos/cognitive/self_mod.py:27       # @dataclass DesignedAgentRecord
src/probos/cognitive/self_mod.py:42       # class SelfModificationPipeline
src/probos/cognitive/self_mod.py:69       # user_approval_fn: Callable[[str], Awaitable[bool]] | None

# Existing QA + Shapley (verified shipped):
src/probos/agents/system_qa.py:1          # SystemQAAgent — smoke-tests new agents
src/probos/runtime.py:619                 # spawner.register_template("system_qa", SystemQAAgent)
src/probos/consensus/shapley.py:37        # def compute_shapley_values(votes, approval_threshold, use_confidence_weights)

# Existing ChromaDB pattern (verified shipped):
src/probos/cognitive/episodic.py:651      # class EpisodicMemory
src/probos/cognitive/episodic.py:732      # chromadb.PersistentClient(path=...)
src/probos/cognitive/episodic.py:735      # get_or_create_collection(name="episodes", embedding_function=ef, metadata={"hnsw:space": "cosine"})

# Existing Vote dataclass (used in QAAgentPool synthetic vote construction):
src/probos/types.py                       # @dataclass Vote(agent_id, vote, confidence, ...)
                                          # consumed by consensus.shapley.compute_shapley_values

# Wirer insertion site (immediately after AD-633 wiring):
src/probos/startup/finalize.py:2521       # _wire_predictive_branching(runtime=runtime, config=config)
src/probos/startup/finalize.py:762        # def _wire_predictive_branching(*, runtime, config)

# Pydantic config insertion site (adjacent to AD-633 config):
src/probos/config.py:1061                 # class PredictiveBranchingConfig(BaseModel)

# EventType insertion site (adjacent to AD-633 prediction events):
src/probos/events.py:67-70                # PREDICTION_HIT/MISS/FLUSHED/ERROR_RECORDED block

# Greenfield (verified absent):
src/probos/cognitive/self_improvement/    # NOT PRESENT (collision-free package)
src/probos/agents/designed/               # NOT PRESENT (LocalDiskPersistence creates lazily)
runtime.proposal_store / approval_gate / evolution_store / qa_agent_pool /
agent_version_store / agent_persistence / shadow_deployment_policy
                                          # 0 grep hits at HEAD
```
