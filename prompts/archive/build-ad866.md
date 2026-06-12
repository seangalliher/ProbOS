# Build Prompt — AD-866: Department-aware independent verifier selection

**Repo:** OSS (`d:\ProbOS`). One AD = one commit (additive-only; corruption pre-check first).
**Parent epic:** `prompts/ad-863-chain-of-command-crew-collaboration.md`. **GitHub issue:** #836.
**Independent of AD-863–865** (touches only the verifier). Can build in any order relative to them, but before AD-867 wires the ontology in.

> Verified against live HEAD. The `ontology=None` default is the load-bearing invariant that keeps AD-860's 11 tests green.

---

## Goal

Verification should be judged by someone *qualified and independent* — prefer an independent agent within the relevant department's authority chain (a peer or the chief) over a random crew member from an unrelated department, while preserving the AD-860 independence invariant.

## File (single, surgical)

`src/probos/cognitive/crew_verifier.py` — modify **only**:
1. `SubtaskVerifier.__init__` — add one optional param.
2. `_pick_independent_verifier` (line 267) — new selection order.

**Do not touch** `verify` (118), `converge` (179), `_resolve_expected_output`, `_build_judge_prompt`, or any verdict/convergence/trust-recording logic.

## Verified current state

- `SubtaskVerifier.__init__(self, *, llm_client, work_item_store, agent_registry, trust_network, agentic_executor, runtime, max_convergence_rounds=2)` — keyword-only, **no `ontology` param today** (crew_verifier.py:89).
- `_pick_independent_verifier(self, producer_id: str) -> str | None` (crew_verifier.py:267): iterates `self._registry.all()`, returns the first agent whose `getattr(agent, "id", None) != producer_id`, else `None`. (The registry is stored as `self._registry` — confirm the exact attribute name when you read the ctor; use whatever the existing method already uses.)
- `VesselOntologyService.get_agent_department(agent_type: str) -> str | None` (service.py:159) — takes **agent_type**.
- `BaseAgent.agent_type` (agent.py:25) and `BaseAgent.id` (agent.py:34).

## Changes

### 1. Constructor — optional `ontology=None`

Add `ontology=None` as a keyword-only param (Dependency Inversion; default `None` keeps every existing call site and test byte-compatible). Store it as `self._ontology = ontology`.

```python
    def __init__(self, *, llm_client, work_item_store, agent_registry,
                 trust_network, agentic_executor, runtime,
                 max_convergence_rounds=2, ontology=None) -> None:
        ...
        self._ontology = ontology
```

### 2. `_pick_independent_verifier(producer_id)` — new selection order

When `self._ontology is None`: **skip steps 1–2 and run today's any-independent path verbatim** (no behavior change for un-wired callers — this is what guarantees AD-860's tests stay green).

When `self._ontology is not None`, select in this order:
1. **Department peer** — an alive agent (`registry.get(id) is not None`) with `id != producer_id` in the **same department** as the producer. Map producer → its `agent_type` (find the agent in `registry.all()` whose `.id == producer_id`, read `.agent_type`), then `producer_dept = ontology.get_agent_department(producer_agent_type)`. A candidate is a peer when `ontology.get_agent_department(candidate.agent_type) == producer_dept` and `producer_dept is not None`.
2. **Authority chain** — if no peer, the producer's chief (a superior post's agent). Reuse the chain-walk pattern (you may import or mirror AD-865's chief-resolution, but do NOT create a hard dependency that breaks the `ontology=None` path). Any alive superior-in-department agent ≠ producer qualifies.
3. **Any independent** — today's behavior: first alive agent in `registry.all()` with `id != producer_id`.
4. **None** → honest-degrade `unverified` (unchanged).

Wrap the ontology lookups in Tier-2 log-and-degrade: if an ontology call raises, fall through to step 3 (any-independent), never propagate.

---

## Tests — `tests/test_ad866_dept_verifier.py` (≥7)

**BF-287 (HARD):** **real** `AgentRegistry`, **real** `VesselOntologyService`. Fakes only for the LLM client / executor that the verifier ctor also needs.

1. Same-department peer preferred over a cross-department independent.
2. Chief used when the department has no non-producer peer.
3. Any-independent fallback when the department contains only the producer.
4. `unverified` (returns `None`) when there is no independent agent at all.
5. **`ontology=None` reproduces AD-860 any-independent behavior exactly** — same selection as today.
6. Producer is never selected as its own verifier (in every branch).
7. Dead/unregistered agents excluded from all candidate sets.

**Regression (must stay green, UNCHANGED):**
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad860_crew_verifier.py tests/test_ad866_dept_verifier.py -q -n 0
```
`tests/test_ad860_crew_verifier.py` has 11 tests; all must pass without modification. If any AD-860 test fails, the `ontology=None` default path was altered — revert and fix.

---

## Do NOT build / change

- `verify`, `converge`, verdict/convergence/trust-recording logic.
- Any other constructor param or call site.
- Do not make `ontology` required. Do not change existing AD-860 tests.

## Highest-risk constraints (restated)

- `ontology=None` MUST take the **exact** current any-independent code path — this is what keeps AD-860's 11 tests green unchanged. Do not refactor that path.
- `get_agent_department` takes **agent_type**, not agent_id — always map producer/candidate `id → agent_type → department`.
- Ontology lookups degrade to any-independent on error; never propagate into `verify`.

## Tracking

PROGRESS.md AD-866 entry; commit impl; `docs(AD-866)` for corrections; close #836.

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
