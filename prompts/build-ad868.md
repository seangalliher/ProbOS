# Build Prompt — AD-868: Self-originated crew tasks (`[CREW]` tag, Lieutenant+ rank gate)

**Repo:** OSS (`d:\ProbOS`). One AD = one commit (additive-only; corruption pre-check first).
**Parent epic:** `prompts/ad-863-chain-of-command-crew-collaboration.md`. **GitHub issue:** #838.
**Depends on:** AD-867 (`CrewOrchestrator`). Build AD-867 first. Capstone AD.

> Verified against live HEAD. **The file is `src/probos/proactive.py`, NOT `src/probos/cognitive/proactive.py`** — correction baked in. The rank gate reuses the EXACT existing `[ASSIGN]` machinery.

---

## Goal

Let a sufficiently-ranked agent originate its own crew task during proactive cognition: emit a `[CREW]…[/CREW]` directive, gated to **Lieutenant+** exactly like `[ASSIGN]`, that spins up a parent WorkItem and runs it through the AD-867 pipeline with full provenance. The mesh starts initiating multi-agent work, not only reacting to the Captain.

## Files

- `src/probos/proactive.py` — add a `[CREW]` tag handler after the existing `[ASSIGN]` block (~line 3315).
- `src/probos/cognitive/crew_orchestrator.py` — add `originate_crew_task(...)`.

## Verified current state of the `[ASSIGN]` block (proactive.py ~3315)

Inside the proactive-action method (scope has locals `rank`, `agent`, `rt`, `text`, `actions_executed`):

```python
# --- ASSIGN (AD-654d) — Lieutenant+ only ---
assign_min_rank = Rank.LIEUTENANT
_RANK_ORDER_ASSIGN = [Rank.ENSIGN, Rank.LIEUTENANT, Rank.COMMANDER, Rank.SENIOR]
can_assign = _RANK_ORDER_ASSIGN.index(rank) >= _RANK_ORDER_ASSIGN.index(assign_min_rank)
assign_pattern = r'\[ASSIGN\s+@([\w-]+)\]\s*(.*?)\s*\[/ASSIGN\]'
# re.finditer over text; resolve callsign via rt.callsign_registry.resolve(target_callsign) -> resolved.get("agent_id")
# dispatch via rt.dispatcher.dispatch(task_event_for_agent(...))  [from probos.activation]
# append to actions_executed
```
- `from probos.crew_profile import Rank` (proactive.py:32). `Rank(Enum)`: `ENSIGN`, `LIEUTENANT`, `COMMANDER`, `SENIOR` (crew_profile.py:30–35).
- A `[HANDOFF]` block (any rank) follows `[ASSIGN]`.

## Changes

### 1. `[CREW]` handler in `proactive.py` (after the `[ASSIGN]` block, ~3315)

Add a new block that **reuses the exact same rank gate** as `[ASSIGN]`:

```python
# --- CREW (AD-868) — Lieutenant+ only, self-originated multi-agent task ---
crew_min_rank = Rank.LIEUTENANT
can_originate_crew = _RANK_ORDER_ASSIGN.index(rank) >= _RANK_ORDER_ASSIGN.index(crew_min_rank)
crew_pattern = r'\[CREW\]\s*(.*?)\s*\[/CREW\]'
```
- Only when `can_originate_crew` is True: `re.finditer(crew_pattern, text, re.DOTALL)` for each goal:
  - `orchestrator = getattr(rt, "crew_orchestrator", None)`. If `None` (flag off / not wired) → Tier-2 log-and-degrade, skip (do **not** raise; do not fall back to a direct dispatch).
  - `parent_id = await orchestrator.originate_crew_task(origin_agent_id=agent.id, goal=<captured goal>)`.
  - Append a record to `actions_executed` (mirror the `[ASSIGN]` append shape).
- When `can_originate_crew` is False: an ensign emitting `[CREW]` is **silently ignored** (same as an under-ranked `[ASSIGN]` today) — optionally log at debug. No consensus bypass, no privilege escalation.

Reuse `_RANK_ORDER_ASSIGN` (already in scope from the `[ASSIGN]` block); do **not** redefine the rank order list.

### 2. `originate_crew_task` on `CrewOrchestrator` (crew_orchestrator.py)

```python
    async def originate_crew_task(self, *, origin_agent_id: str, goal: str, work_type: str = "task") -> str | None:
        ...
```
Flow (honest-degrade throughout; never raise):
1. If the orchestrator is effectively disabled (no work_item_store / decomposer unavailable) → log Tier-2, return `None`.
2. Create the parent WorkItem via `work_item_store.create_work_item(...)` with `created_by=origin_agent_id`, `title=goal`, and `metadata={"origin": "self_originated", "originator": origin_agent_id}` (provenance).
3. Decompose `goal` into children using the AD-863 decomposer + `ParallelDispatcher` path the Captain-initiated flow already uses (reuse, don't reimplement — grep how AD-867's normal entry creates children and call the same helper).
4. `await self.run_crew_task(parent_id)` (AD-867).
5. Return `parent_id` (or `None` on degrade).

The originator's trust is updated through the **existing AD-861 attribution** at synthesis time — do **not** add a second trust write here.

## Guardrails (do not weaken)

- **Rank gate:** Lieutenant+ only, via the same `_RANK_ORDER_ASSIGN` comparison. Ensign `[CREW]` is ignored.
- **No consensus bypass:** destructive sub-tasks still flow through the existing consensus/quorum gates inside the executor — the orchestrator does not exempt them.
- **Provenance:** every self-originated parent carries `metadata["origin"] == "self_originated"` and `originator`.
- **Honest-degrade:** orchestrator missing / disabled / decompose failure → log and skip; the proactive cycle continues.

---

## Tests — `tests/test_ad868_self_originated_crew.py` (≥8)

**BF-287 (HARD):** real `WorkItemStore` (tmp_path), real `AgentRegistry`, real `CrewOrchestrator` (or a thin real wrapper); fake only the LLM client. Build agent fixtures with real `Rank` values.

1. Lieutenant emits `[CREW]` → `originate_crew_task` invoked → parent WorkItem created.
2. Ensign emits `[CREW]` → ignored, no parent created (rank gate).
3. Commander and Senior also allowed (rank ≥ Lieutenant).
4. `metadata["origin"] == "self_originated"` and `originator` set on the parent.
5. `crew_orchestrator` absent on runtime (flag off) → log-and-skip, no raise.
6. `originate_crew_task` returns the `parent_id` and runs `run_crew_task`.
7. Decompose failure → returns `None`, proactive cycle continues (no raise).
8. No second trust write in `originate_crew_task` (attribution stays AD-861's job) — assert trust unchanged by `originate_crew_task` itself.

**Regression (must stay green):** the existing proactive tests — grep `tests/` for `test_proactive` and run them:
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad868_self_originated_crew.py tests/test_proactive*.py -q -n 0
```

---

## Do NOT build / change

- The `[ASSIGN]` and `[HANDOFF]` blocks — leave them byte-identical.
- The rank-order list — reuse `_RANK_ORDER_ASSIGN`, don't redefine.
- The consensus/quorum gates inside the executor.
- Any second trust-write path (AD-861 owns attribution).

## Highest-risk constraints (restated)

- The file is **`src/probos/proactive.py`** — NOT `src/probos/cognitive/proactive.py`. `Rank` imports from `probos.crew_profile`.
- Rank gate is **Lieutenant+**, computed with the existing `_RANK_ORDER_ASSIGN` index comparison. Ensign `[CREW]` is silently ignored.
- `crew_orchestrator` missing → honest-degrade skip; never raise, never bypass to a direct dispatch.
- No second trust write in `originate_crew_task`.

## Tracking

PROGRESS.md AD-868 entry (and mark the epic AD-863→868 complete); commit impl; `docs(AD-868)` for corrections; close #838.

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Spec corrections (file:line evidence)

| Spec claim | Reality | Evidence |
|---|---|---|
| edit `src/probos/cognitive/proactive.py` | File is `src/probos/proactive.py` (no cognitive/ copy) | file_search `**/proactive*.py` → `src/probos/proactive.py`; no `cognitive/proactive.py` |
| generic rank check | Reuse existing `_RANK_ORDER_ASSIGN` + `Rank.LIEUTENANT` gate | proactive.py:~3315 (`assign_min_rank = Rank.LIEUTENANT`, `_RANK_ORDER_ASSIGN = [...]`), :32 (`from probos.crew_profile import Rank`) |
