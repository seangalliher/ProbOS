# Epic AD-863 → AD-868: Chain-of-Command-Aware Crew Collaboration

**Status:** Architect-drafted, verify-first. Ready for per-AD review → Builder.
**Repo:** OSS (`d:\ProbOS`). This describes *how the product works* (crew mechanics), not how it makes money.
**Highest committed AD at draft time: AD-862.** This epic reserves **AD-863 → AD-868** sequentially.

---

## Why this epic exists

The Crew Collaboration epic (AD-858 → AD-862) shipped a **decompose → fan-out → adversarial-verify → converge → synthesize** pipeline. It works, but it is **structurally flat and disconnected from the ship's org chart**:

1. **No agent assignment at decomposition.** [`LLMPlanDecomposer._build_specs`](../src/probos/consultation/llm_decomposer.py) builds `WorkItemSpec` rows and **never sets `agent=`** (left default `""`). [`ParallelDispatcher.dispatch_workspace`](../src/probos/consultation/dispatch.py) then does `assigned_to=spec.agent or None` → `None`. Decomposition does **zero** department/rank/capability matching.
2. **An unassigned sub-task just fails.** [`CrewTaskExecutor._run_child`](../src/probos/cognitive/crew_executor.py) marks any child with no resolvable `assigned_to` as `failed`. The structured pipeline cannot run end-to-end today without something populating assignment.
3. **Verification is flat peer-to-peer.** [`crew_verifier.py`](../src/probos/cognitive/crew_verifier.py) picks the verifier from `registry.all()` *minus the producer* purely for independence — no department, rank, or authority consideration.
4. **The pipeline is built but not wired.** A grep of `runtime.py` for `CrewTaskExecutor|SubtaskVerifier|CrewSynthesizer` returns nothing. The three classes import only each other. There is **no runtime entry point** that runs the full pipeline.

Meanwhile the ship **already has a real, enforced chain of command** that the pipeline ignores:

- [`OrderManager`](../src/probos/cognitive/orders.py) (AD-440) — point-to-point delegation validated against ontology authority; rejects with `"out_of_chain"` unless `to_post_id in from_post.authority_over`.
- [`VesselOntologyService`](../src/probos/ontology/service.py) — `get_post_for_agent`, `get_subordinate_agent_types` (AD-630, reverse-maps `authority_over` → subordinate agent_types), `get_agents_for_post`, `get_agent_department`, `get_agent_capabilities` (AD-648), `Post.tier` (`"crew"`/`"utility"`/…), `Post.authority_over`.
- [`DepartmentDispatcher.route`](../src/probos/mesh/department_dispatcher.py) (AD-581a) — pure DIRECT-vs-BROADCAST decision over a candidate pool using Hebbian weight + department; honors a `work_item.assigned_to` direct hint.
- [`CapabilityRegistry.query`](../src/probos/mesh/capability.py) — intent → ranked `CapabilityMatch` list, trust-weighted (AD-225).
- `[ASSIGN @agent]…[/ASSIGN]` (AD-654d) in [`proactive.py`](../src/probos/proactive.py) — Lieutenant+ agents already self-originate peer assignments (rank-gated). The Hebbian/trust/episodic learning loop already strengthens successful pairings.

**The product vision:** ProbOS is not a subagent-spawner. These are persistent cognitive agents that *learn to work together*, have a *chain of command*, and *know how they collaborate*. This epic makes the structured crew pipeline respect the org chart the rest of the ship already runs on — turning the "natural but unstructured" collaboration the operator observes into **governed delegation**.

```
Captain task ─▶ decompose (DAG, with capability/dept hints)   ← AD-863
              ─▶ resolve each sub-task to a qualified agent     ← AD-864
                 (capability × trust × department)
              ─▶ route assignment THROUGH the dept chief        ← AD-865
                 (chief delegates to a subordinate via OrderManager)
              ─▶ fan-out + execute (AD-859, existing)
              ─▶ verify with a DEPARTMENT-INDEPENDENT judge      ← AD-866
              ─▶ synthesize + Shapley attribution (AD-861, existing)
              ─▶ all wired behind one runtime entry point        ← AD-867
   Lieutenant+ agent can ALSO originate a crew task on its own   ← AD-868
```

---

## Engineering-principles compliance (applies to every AD)

Every build prompt in this epic must include in its acceptance criteria:
> **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

Standing constraints for the whole epic:
- **Single Responsibility / Dependency Inversion**: new resolution and delegation logic lives in focused modules with constructor injection (mirror `SubtaskVerifier` / `CrewSynthesizer`). No new logic crammed into `LLMPlanDecomposer.decompose` beyond the schema/prompt change.
- **Open/Closed + Law of Demeter**: consume the ontology / capability / order primitives through their **public** methods. Never reach into `_private` ontology state.
- **Fail Fast → log-and-degrade**: every resolution/delegation/verification step must honest-degrade (leave unassigned / fall back to any-independent / synthesize accepted-only) rather than raise into the dispatch path. A crew task must never crash the runtime.
- **Minimal Authority / Safety Budget**: chain-of-command checks are *additive gates*, never bypasses. An `out_of_chain` delegation is refused, not silently forced.
- **Trust coherence**: keep storing raw `(alpha, beta)`; record outcomes through the existing sync keyword `trust.record_outcome(...)` signature. Successful delegations strengthen Hebbian routing; failures weaken it.
- **Episodic completeness**: every crew execution path already stores an episode in AD-861 — do not break that. New delegation events emit through the existing event log.
- **No MagicMock at substrate/storage boundaries (BF-287)**: use real `AgentRegistry`, real `VesselOntologyService` fixtures, real `WorkItemStore` (tmp_path), real `TrustNetwork`. Fakes only for the LLM client.

---

## AD-863 — Decomposer emits capability + department hints per sub-task

**Goal:** Give each `WorkItemSpec` an optional `capability` phrase and optional `department` hint so a downstream resolver can pick a qualified agent. The decomposer stays a pure NL→DAG mapper; it only *annotates* the kind of work.

**Files:**
- `src/probos/consultation/dispatch.py` — extend the frozen `WorkItemSpec` dataclass.
- `src/probos/consultation/llm_decomposer.py` — extend `_SYSTEM_PROMPT` + `_build_specs` + `_with_deps` + `_passthrough`.

**Changes:**
1. `WorkItemSpec` (dispatch.py:47): add two **defaulted** fields AFTER `expected_output` (defaulted-field-ordering rule):
   ```python
   capability: str | None = None   # AD-863: one-phrase "kind of work" for agent resolution
   department: str | None = None   # AD-863: optional department hint (engineering/science/medical/security/bridge/operations)
   ```
   Add both to `to_dict()`.
2. `_SYSTEM_PROMPT` (llm_decomposer.py:46): extend the per-element key list to request `"capability"` (a short phrase describing the kind of work, e.g. "web research", "write code", "analyze data") and `"department"` (one of the known department names, or null). Emphasize: hints are advisory; null is acceptable.
3. `_build_specs`: parse `capability`/`department` (same `str | None` normalization as `expected_output` — strip, empty→`None`); pass into the `WorkItemSpec(...)` constructor. `_with_deps` must thread both through (it reconstructs the frozen spec).
4. `_passthrough`: `capability=None, department=None` (the honest-degrade fallback carries no hints).
5. `ParallelDispatcher.dispatch_workspace` (dispatch.py:~451): persist both into the WorkItem `metadata` (`metadata["capability"] = spec.capability`, `metadata["department"] = spec.department`) alongside the existing `expected_output` line, so AD-864 can read them off the persisted WorkItem.

**Acceptance criteria:**
- `tests/test_ad863_decomposer_hints.py`: ≥6 tests with a fake LLM client — capability+department parsed and carried onto the spec; null/missing → `None`; `to_dict()` round-trips both; `_with_deps` preserves them through DAG repair; passthrough carries `None`; backward-compat (a spec dict with no `capability`/`department` keys still builds).
- Regression: `tests/test_ad858_llm_decomposer.py` + any `dispatch` spec tests stay green.
- **Do not build:** the resolver (AD-864). Do not assign `spec.agent` here. Do not touch `MarkdownPlanDecomposer` parsing beyond leaving its specs hint-free (defaults).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## AD-864 — `CrewAssignmentResolver`: capability × trust × department → agent_id

**Goal:** A focused, pure-decision resolver that maps each hint-annotated `WorkItemSpec` to a concrete `agent_id` using the live registry, capability registry, ontology department, and trust scores. This is the "agents know their scope and the capabilities they have, and that is factored into collaboration" piece.

**New module:** `src/probos/cognitive/crew_assignment.py` (Cognitive layer).

**Design (constructor injection, mirror `SubtaskVerifier`):**
```python
@dataclass(frozen=True)
class AssignmentDecision:
    spec_id: str
    agent_id: str | None        # None = unresolved (honest-degrade; executor will fail that child)
    department: str | None
    capability: str | None
    score: float                # 0.0 when unresolved
    reason: str                 # "capability_match" | "department_only" | "unresolved_no_candidate" | ...

class CrewAssignmentResolver:
    def __init__(self, *, capability_registry, ontology, trust_network, agent_registry): ...
    def resolve(self, spec: WorkItemSpec) -> AssignmentDecision: ...
    def resolve_all(self, specs: list[WorkItemSpec]) -> list[AssignmentDecision]: ...
```

**Resolution algorithm (pure, no LLM, no side effects):**
1. If `spec.capability` is set → `capability_registry.query(spec.capability, trust_scores=<live per-agent scores>)` → ranked `CapabilityMatch`. Filter to **alive** agents in the registry.
2. If `spec.department` is set → keep only candidates whose `ontology.get_agent_department(agent_type) == spec.department` (resolve agent_type via `registry.get(agent_id).agent_type`). If the department filter empties the list, fall back to the unfiltered capability ranking (reason `"capability_match_dept_unavailable"`).
3. Pick the top-scored candidate → `AssignmentDecision(agent_id=..., score=..., reason="capability_match")`.
4. If no capability hint but a department hint → pick the highest-trust **alive crew agent** in that department (reason `"department_only"`).
5. No hints / no candidates → `agent_id=None`, `score=0.0`, reason `"unresolved_no_candidate"` (honest-degrade; **do not raise**).

**Acceptance criteria:**
- `tests/test_ad864_crew_assignment.py`: ≥10 tests using a **real** `AgentRegistry` + **real** `VesselOntologyService` + **real** `TrustNetwork` (BF-287) and a real or lightweight `CapabilityRegistry` populated with descriptors — capability-only resolution; capability×department resolution; department filter that empties → capability fallback; department-only highest-trust pick; trust tie-break; no-hint → unresolved; dead agent excluded; `resolve_all` maps a DAG; unknown department → unresolved/fallback; reason strings correct.
- **Do not build:** chain-of-command delegation (AD-865) — this AD resolves to the *worker* directly. Do not wire into the runtime or the dispatcher yet. Do not mutate WorkItems (pure decision only).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## AD-865 — Route assignment through the department chief (chain of command)

**Goal:** Make the org chart load-bearing. When a sub-task resolves to a worker in a department, the **department chief** is the delegating authority: the chief issues a validated `Order` to the qualified subordinate via `OrderManager`, respecting `authority_over`. This is the "department chiefs manage requests and delegate to their subordinates" piece — replacing direct worker-assignment with governed delegation.

**New module:** `src/probos/cognitive/crew_delegation.py` (Cognitive layer).

**Design:**
```python
@dataclass(frozen=True)
class DelegationDecision:
    spec_id: str
    chief_agent_id: str | None      # the delegating authority (post with authority_over the worker)
    worker_agent_id: str | None     # the resolved subordinate
    order_id: str | None            # OrderManager order id when delegation succeeded
    delegated: bool                 # True only when an Order was issued and is in-chain
    reason: str                     # "delegated_via_chief" | "direct_no_chief" | "out_of_chain" | "self_assigned"

class CrewDelegator:
    def __init__(self, *, ontology, order_manager, agent_registry): ...
    def delegate(self, decision: "AssignmentDecision") -> DelegationDecision: ...
```

**Algorithm:**
1. Resolve the worker's post (`ontology.get_post_for_agent(worker_agent_type)`) and department.
2. Find the chief: the post in the same department whose `authority_over` includes the worker's `post_id`. Use `get_subordinate_agent_types` in reverse, or walk `get_chain_of_command(worker_post_id)` to the first superior in-department. Resolve the chief's live `agent_id` via `get_agents_for_post`.
3. If a chief is found and `worker_post_id in chief_post.authority_over` → `order_manager.issue_order(from_agent_id=chief_agent_id, to_post_id=worker_post_id, directive=<spec title/description>)`. On success → `delegated=True`, carry `order.id`, reason `"delegated_via_chief"`.
4. If the worker **is** the chief (no superior in-department) → `reason="self_assigned"`, `delegated=False`, worker keeps the assignment directly (a chief can execute its own department's leaf task).
5. If no chief / order rejected `out_of_chain` / OrderManager unavailable → honest-degrade to direct assignment (`reason="direct_no_chief"` / `"out_of_chain"`, `delegated=False`). The worker still gets the work; we just couldn't route it through a chief.

**Wiring note (for AD-867, not built here):** the delegation decision's `worker_agent_id` is what ultimately lands in `WorkItem.assigned_to`; the `chief_agent_id`/`order_id` are recorded into `WorkItem.metadata` for provenance.

**Acceptance criteria:**
- `tests/test_ad865_crew_delegation.py`: ≥9 tests with a **real** `VesselOntologyService` + **real** `OrderManager` (real `AgentRegistry`, BF-287) — chief delegates to a subordinate (Order issued, in-chain); worker-is-chief → self_assigned; cross-department target → out_of_chain degrade; no chief found → direct_no_chief; OrderManager unavailable → direct degrade; order_id carried; metadata-provenance fields present; `authority_over` actually enforced (a fabricated out-of-chain pair is rejected).
- **Do not build:** the runtime orchestrator (AD-867). Do not change `OrderManager`'s validation. Do not auto-acknowledge orders. Do not modify the duty state machine.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## AD-866 — Department-aware independent verifier selection

**Goal:** Verification should be judged by someone *qualified and independent* — prefer an independent agent within the relevant department's authority chain (a peer or the chief), not a random crew member from an unrelated department. This keeps adversarial verification meaningful while preserving the AD-860 independence invariant.

**File:** `src/probos/cognitive/crew_verifier.py` — modify only `_pick_independent_verifier`.

**Changes:**
- `SubtaskVerifier.__init__` gains an **optional** `ontology=None` constructor param (Dependency Inversion; default `None` keeps every existing call site and test byte-compatible and falls back to today's any-independent behavior).
- `_pick_independent_verifier(producer_id)` new selection order:
  1. **Department peer**: an alive agent ≠ producer in the **same department** as the producer (via `ontology.get_agent_department`) — the most qualified independent judge.
  2. **Authority chain**: the producer's chief (a superior post's agent) if no peer is available — a qualified supervisor can verify.
  3. **Any independent** (current behavior) — any alive agent ≠ producer.
  4. **None** → honest-degrade `unverified` (unchanged).
- When `ontology is None`, skip steps 1–2 and use today's any-independent path verbatim (no behavior change for un-wired callers).

**Acceptance criteria:**
- `tests/test_ad866_dept_verifier.py`: ≥7 tests with a **real** `AgentRegistry` + **real** `VesselOntologyService` — same-department peer preferred over cross-department; chief used when no peer; any-independent fallback when department has only the producer; `unverified` when no independent at all; `ontology=None` reproduces the AD-860 any-independent behavior exactly; producer never selected as its own verifier; dead agents excluded.
- Regression: `tests/test_ad860_crew_verifier.py` (11) stays green **unchanged** (the `ontology=None` default guarantees this).
- **Do not build:** changes to the verdict/convergence/trust-recording logic. Only `_pick_independent_verifier` and the constructor change.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## AD-867 — `CrewOrchestrator`: wire the full pipeline behind one runtime entry point

**Goal:** Make the crew pipeline actually run end-to-end. A single orchestrator threads resolve → delegate → fan-out → verify → synthesize, and is wired onto the runtime and triggered when a dispatched parent task decomposes into a multi-spec DAG. This is the structural layer that turns the dormant classes into a working crew.

**New module:** `src/probos/cognitive/crew_orchestrator.py` (Cognitive layer).
**Wiring file:** `src/probos/startup/finalize.py` (a new `_wire_crew_orchestrator` wirer near the existing `_wire_consultation_dispatch` at line ~1439), exposing `runtime.crew_orchestrator` (public attr).

**Design:**
```python
class CrewOrchestrator:
    def __init__(self, *, assignment_resolver, delegator, crew_executor,
                 verifier, synthesizer, work_item_store, runtime, emit_fn=None,
                 config=None): ...
    async def run_crew_task(self, parent_id: str) -> SynthesisResult: ...
```

**`run_crew_task(parent_id)` flow:**
1. Load the parent's children (already created by `ParallelDispatcher`). For each child, read its persisted `capability`/`department` hints (AD-863) → build a `WorkItemSpec`-shaped view (or reuse the spec metadata) → `assignment_resolver.resolve(...)` → `delegator.delegate(...)` → `work_item_store.update_work_item(child_id, assigned_to=worker_agent_id, metadata={...chief/order provenance...})`. Honest-degrade: unresolved child stays unassigned (executor fails it without aborting siblings — existing AD-859 behavior).
2. `await crew_executor.run(parent_id)` → `list[SubtaskResult]` (existing AD-859).
3. For each non-failed result: `await verifier.verify(result)` → `VerificationVerdict`; build `ConvergenceOutcome` (existing AD-860 dataclass).
4. `await synthesizer.synthesize(outcomes)` → `SynthesisResult` (existing AD-861) — parent completion + Shapley + episode + provenance.
5. Emit lifecycle events through `emit_fn`; honest-degrade every stage (a failed stage logs + surfaces a partial `SynthesisResult`, never raises).

**Trigger:** when a dispatchable parent task is decomposed into **>1** child spec, the dispatch path schedules `runtime.crew_orchestrator.run_crew_task(parent_id)` (held task reference per async-hygiene rule). A single-spec task keeps the existing AD-856 single-agent path (no crew overhead). Gate behind a config flag `CrewConfig.orchestrator_enabled: bool = False` (default off; zero-config boot unchanged — flip on in a follow-up once validated).

**Acceptance criteria:**
- `tests/test_ad867_crew_orchestrator.py`: ≥10 tests with **real** `WorkItemStore` (tmp_path) + real registry/ontology/trust, fakes only for LLM — end-to-end happy path (3-child DAG resolves → delegates → executes → verifies → synthesizes → parent done); unresolved child degrades without aborting siblings; verifier-refuted child handled; single-spec parent skips the crew path; `orchestrator_enabled=False` no-ops; emit events fire; held task reference (no fire-and-forget); partial-stage failure surfaces a partial result, never raises.
- `tests/test_finalize.py` (or the relevant wiring test): the wirer attaches `runtime.crew_orchestrator` when deps are present and skips cleanly when they aren't.
- **Do not build:** the HXI surface (AD-862 already shipped the read endpoint/panel — reuse it). Do not change `CrewTaskExecutor`/`SubtaskVerifier`/`CrewSynthesizer` internals — orchestrate them as-is (the AD-866 verifier change is its own AD). Do not auto-enable the flag.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## AD-868 — Self-originated crew tasks (Lieutenant+ agents)

**Goal:** Crew can originate structured collaboration on their own, not only relay Captain-originated tasks — answering "can they originate tasks on their own?" The existing `[ASSIGN]` primitive (AD-654d, Lieutenant+) is single-peer; this lets a qualified agent open a *crew task* (a decomposable parent) that flows through the same governed orchestrator.

**Files:**
- `src/probos/proactive.py` — extend the existing rank-gated action-extraction block (where `[ASSIGN]` is parsed, ~line 3316) with a new `[CREW]…[/CREW]` tag (or reuse `[ASSIGN]` with a multi-step body — Architect to confirm during review which is cleaner against the live parser).
- `src/probos/cognitive/crew_orchestrator.py` — add `async def originate_crew_task(self, *, origin_agent_id, goal, work_type="task") -> str` that creates a parent WorkItem (`created_by=origin_agent_id`), runs it through the AD-863 decomposer + AD-867 pipeline, and returns the parent_id.

**Design / guardrails:**
- **Rank gate:** reuse the exact AD-654d pattern — `Rank.LIEUTENANT` minimum (`_RANK_ORDER_ASSIGN`). An ensign cannot originate a crew task.
- **Consensus/Safety Budget:** a self-originated crew task is created in the normal WorkItem flow; destructive sub-tasks still hit consensus through the existing executor path. No new bypass.
- **Provenance:** the parent records `created_by=origin_agent_id` and `metadata["origin"]="self_originated"` so the Captain HXI (AD-862 panel) shows who started it.
- **Trust:** the originating agent earns/loses trust on the synthesized outcome through the existing AD-861 attribution — self-originated work is held to the same standard.
- Honest-degrade: orchestrator disabled / decompose fails → log + no-op (no partial parent left dangling).

**Acceptance criteria:**
- `tests/test_ad868_self_originated_crew.py`: ≥8 tests with real store/registry/ontology/trust — Lieutenant+ originates a crew task (parent created, `created_by` + origin metadata set); ensign blocked (rank gate); the originated parent flows through the orchestrator; orchestrator-disabled → no-op; the proactive tag is parsed and rank-gated; provenance metadata present; trust recorded on the originator.
- Regression: `tests/test_proactive*.py` action-extraction tests stay green (the new tag must not disturb existing `[ASSIGN]`/`[MOVE]`/etc. parsing).
- **Do not build:** a Captain-approval queue for self-originated tasks (that is a separate decision — file a forward marker if the operator wants pre-approval). Do not raise the rank gate to Commander. Do not let self-origination bypass consensus on destructive sub-tasks.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Out of scope (explicit — do not build in this epic)

- **Cross-department project teams / cross-department CoC** — flagged commercial (AD-581e) in `department_dispatcher.py`. This epic is single-department-chain delegation only.
- **Multi-ship / federation delegation** — orders crossing a federation boundary.
- **Re-opening completed sub-tasks** — `done` is terminal in the duty state machine; convergence re-runs through the public AD-859a executor (existing), not a `done→in_progress` transition.
- **New HXI panels** — AD-862 already ships the crew read surface; reuse it. A chain-of-command visualization is a separate future AD.
- **Auto-enabling `orchestrator_enabled`** — ships off; flip on in a follow-up AD after live validation.

## Review protocol (per the established cycle)

Each AD gets an independent **verify-first Architect review** against live HEAD (quote file:line, confirm every asserted API/seam exists and matches signatures) → apply spec corrections → Builder implements one AD = one commit (additive-only; corruption pre-check) → run focused + targeted regression gates → commit impl → commit spec correction as `docs(AD-XXX)` → push → close the GitHub issue. Specs are **leads, not ground truth** — grep before quoting.
