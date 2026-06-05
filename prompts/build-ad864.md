# Build Prompt — AD-864: `CrewAssignmentResolver` (capability × trust × department → agent_id)

**Repo:** OSS (`d:\ProbOS`). One AD = one commit (additive-only; corruption pre-check first).
**Parent epic:** `prompts/ad-863-chain-of-command-crew-collaboration.md`. **GitHub issue:** #834.
**Depends on:** AD-863 (the `WorkItemSpec.capability`/`department` fields). Build AD-863 first.

> Verified against live HEAD. Signatures below are confirmed. Grep before quoting if anything drifted.

---

## Goal

A focused, **pure-decision** resolver that maps each hint-annotated `WorkItemSpec` to a concrete `agent_id` using the live registry, capability registry, ontology department, and trust scores. No LLM, no side effects, no WorkItem mutation. Honest-degrade to `agent_id=None` — never raise.

## New module

`src/probos/cognitive/crew_assignment.py` (Cognitive layer). Mirror the constructor-injection style of `SubtaskVerifier` (`src/probos/cognitive/crew_verifier.py`).

```python
from __future__ import annotations
from dataclasses import dataclass
from probos.consultation.dispatch import WorkItemSpec

@dataclass(frozen=True)
class AssignmentDecision:
    spec_id: str
    agent_id: str | None        # None = unresolved (honest-degrade; executor will fail that child)
    department: str | None
    capability: str | None
    score: float                # 0.0 when unresolved
    reason: str                 # "capability_match" | "capability_match_dept_unavailable"
                                # | "department_only" | "unresolved_no_candidate"

class CrewAssignmentResolver:
    def __init__(self, *, capability_registry, ontology, trust_network, agent_registry) -> None: ...
    def resolve(self, spec: WorkItemSpec) -> AssignmentDecision: ...
    def resolve_all(self, specs: list[WorkItemSpec]) -> list[AssignmentDecision]: ...
```

## Verified collaborator APIs (use exactly these)

- `CapabilityRegistry.query(intent: str, trust_scores: dict[str, float] | None = None) -> list[CapabilityMatch]` — returns **all** matches sorted by `(score, capability.confidence)` desc, trust-weighted as `score*(0.5+0.5*trust)`. (`src/probos/mesh/capability.py:22`, query method.)
- `CapabilityMatch` is `@dataclass`: fields `agent_id: str`, `capability: CapabilityDescriptor`, `score: float`. **There is NO `.trust` field.** (capability.py:13.)
- `TrustNetwork.all_scores(crew_only: bool = False) -> dict[AgentID, float]` (`src/probos/consensus/trust.py:462`) — use this to build the `trust_scores` dict for the capability query. Per-agent read: `TrustNetwork.get_score(agent_id) -> float` (trust.py:406).
- `AgentRegistry.get(agent_id) -> BaseAgent | None` (registry.py:51); `AgentRegistry.all() -> list[BaseAgent]` (registry.py:64).
- `BaseAgent.agent_type` (class attr, default `"base"`, substrate/agent.py:25) and `BaseAgent.id` (agent.py:34) — both available on every registered agent.
- `VesselOntologyService.get_agent_department(agent_type: str) -> str | None` (service.py:159) — **takes `agent_type`, not `agent_id`.** Resolve agent_type via `agent_registry.get(agent_id).agent_type`.
- `VesselOntologyService.get_crew_agent_types() -> set[str]` (service.py) — for the department-only branch if needed.

## Resolution algorithm (pure)

"Alive" = `agent_registry.get(agent_id) is not None`. Build the trust dict once per `resolve()` via `trust_network.all_scores()`.

1. **Capability hint set** → `capability_registry.query(spec.capability, trust_scores=all_scores)`. Filter the returned `CapabilityMatch` list to **alive** agents.
2. **Department hint also set** → keep only matches whose `ontology.get_agent_department(<agent_type of match.agent_id>) == spec.department`. If that filter empties the list → fall back to the unfiltered (alive) capability ranking with reason `"capability_match_dept_unavailable"`.
3. Pick the top-scored surviving candidate → `AssignmentDecision(agent_id=match.agent_id, score=match.score, reason="capability_match")` (or the `_dept_unavailable` reason from step 2).
4. **No capability hint but department hint set** → pick the highest-`get_score` **alive** agent whose `get_agent_department(agent_type) == spec.department`. Reason `"department_only"`. Tie-break deterministically (e.g. higher trust, then `agent_id` lexical).
5. **No hints / no candidates** → `AssignmentDecision(agent_id=None, score=0.0, reason="unresolved_no_candidate")`. **Honest-degrade — do not raise.**

`resolve_all(specs)` = `[self.resolve(s) for s in specs]`.

Every branch must be wrapped so an unexpected collaborator error logs (Tier-2 log-and-degrade) and returns the unresolved decision rather than propagating into a caller that will be the dispatch path.

---

## Tests — `tests/test_ad864_crew_assignment.py` (≥10)

**BF-287 (HARD):** use **real** `AgentRegistry`, **real** `VesselOntologyService`, **real** `TrustNetwork`. Build a real or lightweight `CapabilityRegistry` and register real `CapabilityDescriptor`s. **No MagicMock at these substrate/storage boundaries** — MagicMock auto-creates `.agent_type`/`.id`/`.score` and will pass even when the production code reads a phantom attribute.

1. Capability-only resolution picks the top capability match.
2. Capability × department resolution keeps only in-department candidates.
3. Department filter that empties → capability fallback, reason `"capability_match_dept_unavailable"`.
4. Department-only (no capability) → highest-trust in-department alive agent, reason `"department_only"`.
5. Trust tie-break is deterministic.
6. No hints → `agent_id=None`, reason `"unresolved_no_candidate"`.
7. Dead/unregistered agent excluded from candidates.
8. `resolve_all` maps a multi-spec DAG to the right number of decisions.
9. Unknown department → empties filter → fallback or unresolved (assert the exact reason).
10. `score=0.0` exactly when unresolved; non-zero when resolved.
11. (recommended) Collaborator raising mid-resolve → degrades to unresolved, does not propagate.

Run:
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad864_crew_assignment.py -q -n 0
```

---

## Do NOT build / change

- Chain-of-command delegation (AD-865) — this AD resolves to the **worker** directly.
- Any runtime/dispatcher wiring — that's AD-867.
- Any WorkItem mutation — this is a pure decision object.
- Do not add an LLM call. Resolution is deterministic.

## Highest-risk constraints (restated)

- `get_agent_department` takes **agent_type**, not agent_id. Always map `agent_id → registry.get(agent_id).agent_type → get_agent_department(...)`.
- `CapabilityMatch` has **no `.trust`** — trust enters only via the `trust_scores` arg to `query()`.
- Never raise out of `resolve` / `resolve_all`. Unresolved is a valid, logged outcome.

## Tracking

PROGRESS.md AD-864 entry; commit impl; `docs(AD-864)` for any correction; close #834.

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
