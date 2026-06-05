# Build Prompt — AD-867: `CrewOrchestrator` — wire the full pipeline behind one runtime entry point

**Repo:** OSS (`d:\ProbOS`). One AD = one commit (additive-only; corruption pre-check first).
**Parent epic:** `prompts/ad-863-chain-of-command-crew-collaboration.md`. **GitHub issue:** #837.
**Depends on:** AD-863, AD-864, AD-865, AD-866. Build all four first.

> Verified against live HEAD. **Four spec corrections are baked in** — read "Spec corrections" before you start. The config gate is the highest-risk item.

---

## Goal

Make the crew pipeline run end-to-end. One orchestrator threads resolve → delegate → fan-out → verify → synthesize, wired onto the runtime, gated behind a config flag (default **off**).

## New module

`src/probos/cognitive/crew_orchestrator.py` (Cognitive layer).

```python
class CrewOrchestrator:
    def __init__(self, *, assignment_resolver, delegator, crew_executor,
                 verifier, synthesizer, work_item_store, runtime,
                 emit_fn=None, config=None) -> None: ...
    async def run_crew_task(self, parent_id: str) -> SynthesisResult: ...
```

## Verified collaborator APIs (use exactly these)

- `WorkItemStore` lives in **`probos.workforce`** (`src/probos/workforce.py:905`), NOT `probos.work.store`. Import: `from probos.workforce import WorkItemStore`. Methods:
  - `async create_work_item(self, **kwargs) -> WorkItem` (workforce.py:992)
  - `async get_work_item(self, work_item_id) -> WorkItem | None` (1054)
  - `async list_work_items(self, ...)` (1066) — use to load a parent's children (grep its signature for the parent/status filter).
  - `async update_work_item(self, work_item_id, **updates) -> WorkItem | None` (1108) — this is how the orchestrator writes `assigned_to` + provenance metadata onto each child.
  - `async transition_work_item(self, ...)` (1139).
- `CrewTaskExecutor` drive method is **`async def run(self, parent_id) -> list[SubtaskResult]`** (crew_executor.py), **NOT `execute`**. Ctor keyword-only: `(*, work_item_store, agent_registry, agentic_executor, runtime, max_parallel_subtasks=3, emit_fn=None)`.
- `SubtaskVerifier.verify(self, result) -> VerificationVerdict` (async, crew_verifier.py:118). `VerificationVerdict` fields: `accepted`, `confidence`, `critique`, `verifier_agent_id` (crew_verifier.py:56). `ConvergenceOutcome` fields: `result`, `verdict`, `status`, `rounds=0` (crew_verifier.py:~71).
- `CrewSynthesizer.synthesize(self, parent_id, outcomes: list[ConvergenceOutcome]) -> SynthesisResult` (async, crew_synth.py:126) — **takes BOTH `parent_id` AND `outcomes`** (the epic spec step 4 wrote `synthesize(outcomes)` — that is wrong). `SynthesisResult` fields: `parent_id`, `final_output`, `completed`, `shapley_values`, `provenance_ref`, `accepted_count`, `total_count` (crew_synth.py:65).
- `AssignmentDecision` / `CrewAssignmentResolver.resolve(spec)` (AD-864). `DelegationDecision` / `CrewDelegator.delegate(decision)` (AD-865).
- `WorkItemSpec` is `from probos.consultation.dispatch import WorkItemSpec` (frozen dataclass; AD-863 added `capability`/`department`).

## `run_crew_task(parent_id)` flow

1. Load the parent's children (created by `ParallelDispatcher`) via `work_item_store.list_work_items(...)`. For each child:
   - Reconstruct a `WorkItemSpec`-shaped view from the persisted `metadata` (AD-863 persisted `capability`/`department`/`expected_output` there).
   - `decision = assignment_resolver.resolve(spec_view)` → `delegation = delegator.delegate(decision)`.
   - `await work_item_store.update_work_item(child_id, assigned_to=delegation.worker_agent_id, metadata={**existing, "chief_agent_id": delegation.chief_agent_id, "order_id": delegation.order_id, "delegated": delegation.delegated, "delegation_reason": delegation.reason})`.
   - Honest-degrade: an unresolved child stays unassigned; the executor fails just that child (existing AD-859 behavior) without aborting siblings.
2. `results = await crew_executor.run(parent_id)` → `list[SubtaskResult]`.
3. For each non-failed result: `verdict = await verifier.verify(result)`; build a `ConvergenceOutcome(result=..., verdict=..., status=..., rounds=...)` (use the AD-860 dataclass as-is).
4. `synthesis = await synthesizer.synthesize(parent_id, outcomes)` → `SynthesisResult`.
5. Emit lifecycle events through `emit_fn` (guard `if self._emit_fn:`). Honest-degrade **every** stage: a failed stage logs (Tier-2) and surfaces a partial `SynthesisResult`; **never raise** out of `run_crew_task`.

## Config gate — add to `AgenticDispatchConfig` (NOT a new `CrewConfig`)

> **CORRECTION (baked in):** there is **no `CrewConfig` class**. Crew settings live on `AgenticDispatchConfig` (config.py:~5034), mounted on `SystemConfig` as `agentic_dispatch` (config.py:5223). That class already has `enabled: bool = False`, `max_parallel_subtasks: int = 3` (AD-859), `max_convergence_rounds: int = 2` (AD-860).

Add to `AgenticDispatchConfig`:
```python
    orchestrator_enabled: bool = False  # AD-867: gate the end-to-end crew pipeline (default off; zero-config boot unchanged)
```
Read it as `config.agentic_dispatch.orchestrator_enabled`. Default **False** — zero-config boot is unchanged.

## Wiring — `_wire_crew_orchestrator` in `finalize.py`

Add a new wirer next to `_wire_consultation_dispatch` (**finalize.py:1406**, not ~1439). Mirror its exact pattern:
- `cfg = getattr(config, "agentic_dispatch", None); if not cfg or not getattr(cfg, "orchestrator_enabled", False): return False`.
- Resolve deps via `getattr` with Tier-2 log-and-degrade: `runtime.work_item_store`, the AD-864 resolver, AD-865 delegator, the existing crew executor/verifier/synthesizer (construct them here if they aren't already attached, mirroring how `_wire_consultation_dispatch` constructs `ParallelDispatcher` inline). `emit_fn = getattr(runtime, "emit_event", None)`.
- `runtime.crew_orchestrator = CrewOrchestrator(...)` — **public attr** (Wave 5 convention #1, same as `runtime.consultation_dispatcher`).
- Return `bool` (True when attached, False when skipped). Call the wirer from the same place `_wire_consultation_dispatch` is invoked in the finalize sequence.

## Trigger (held task reference — async hygiene)

When a dispatchable parent decomposes into **>1** child spec, schedule `runtime.crew_orchestrator.run_crew_task(parent_id)` as a **held** task (store in a `set[asyncio.Task]`, add a done-callback that discards it — **no fire-and-forget**). A single-spec task keeps the existing AD-856 single-agent path (no crew overhead). The whole trigger is a no-op when `orchestrator_enabled is False` (the orchestrator simply isn't attached).

---

## Tests — `tests/test_ad867_crew_orchestrator.py` (≥10) + a finalize wiring test

**BF-287 (HARD):** **real** `WorkItemStore` (tmp_path), real `AgentRegistry`, real `VesselOntologyService`, real `TrustNetwork`. Fakes only for the LLM client/executor.

1. End-to-end happy path: a 3-child DAG resolves → delegates → executes → verifies → synthesizes → parent done.
2. Unresolved child degrades without aborting siblings.
3. Verifier-refuted child handled (not counted as accepted; synthesis still completes).
4. Single-spec parent skips the crew path (no orchestration overhead).
5. `orchestrator_enabled=False` → `run_crew_task` not scheduled / orchestrator not attached (no-op).
6. Emit events fire through `emit_fn`.
7. Held task reference — assert the trigger stores the task (no fire-and-forget; task is awaitable/tracked).
8. Partial-stage failure (e.g. synthesizer raises) → surfaces a partial `SynthesisResult`, never raises.
9. `update_work_item` writes `assigned_to` + provenance metadata onto each resolved child.
10. `synthesize` is called with **both** `parent_id` and `outcomes`.
11. (finalize) the wirer attaches `runtime.crew_orchestrator` when deps + flag are present, and skips cleanly (returns False, no attr) when the flag is off or deps are missing — add to `tests/test_finalize.py` (or the relevant wiring test file; grep `_wire_consultation_dispatch` in `tests/` to find it).

Run:
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad867_crew_orchestrator.py tests/test_finalize.py -q -n 0
```

---

## Do NOT build / change

- The HXI surface — AD-862 already shipped the crew read endpoint/panel; reuse it.
- `CrewTaskExecutor` / `SubtaskVerifier` / `CrewSynthesizer` internals — orchestrate them as-is. (The AD-866 verifier change is its own AD; this AD only *passes* `ontology` into the verifier ctor when constructing it in the wirer.)
- **Do not auto-enable the flag.** It ships `False`.
- Do not invent a `CrewConfig` class.

## Highest-risk constraints (restated)

- The gate field goes on **`AgenticDispatchConfig`** → read `config.agentic_dispatch.orchestrator_enabled`. There is no `CrewConfig`.
- Executor method is **`run(parent_id)`**, not `execute`. Synthesizer is **`synthesize(parent_id, outcomes)`**, not `synthesize(outcomes)`.
- `WorkItemStore` imports from **`probos.workforce`**.
- The trigger task MUST be held (stored in a set + done-callback). No fire-and-forget `create_task`.
- Every stage honest-degrades; `run_crew_task` never raises.

## Tracking

PROGRESS.md AD-867 entry; commit impl; `docs(AD-867)` for corrections; close #837.

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Spec corrections (file:line evidence)

| Spec claim | Reality | Evidence |
|---|---|---|
| `CrewConfig.orchestrator_enabled` | No `CrewConfig`; add to `AgenticDispatchConfig`, read `config.agentic_dispatch.orchestrator_enabled` | config.py:~5034 (AgenticDispatchConfig), :5223 (mounted as `agentic_dispatch`) |
| `_wire_consultation_dispatch` at line ~1439 | Actually at line 1406 | finalize.py:1406 |
| `crew_executor.execute(...)` | Method is `run(parent_id)` | crew_executor.py (`async def run(self, parent_id)`) |
| `synthesize(outcomes)` | Signature is `synthesize(parent_id, outcomes)` | crew_synth.py:126 |
| `WorkItemStore` path implied elsewhere | `from probos.workforce import WorkItemStore` | workforce.py:905 |
