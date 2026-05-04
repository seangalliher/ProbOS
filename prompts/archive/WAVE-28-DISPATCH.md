# Wave 28 — AD-658 v1 Cognitive Chain Harness Metrics

**Closes:** #317. Standalone wave (depends on AD-632a chain framework + AD-649/639/638 modulation params, all shipped). v1 ships measurement substrate only — `ChainExecutionTrace` dataclass + `CognitiveJournal` chain_traces table + per-step emission hook in `SubTaskExecutor._execute_single_step` + read-only `GET /api/chain-traces` endpoint. No optimization (AD-659), no output-quality signals beyond `success`, no token split, no EventType, no WebSocket streaming, no sampling, no retroactive backfill.

**AD-652 dependency note:** AD-652 ("Cognitive Code-Switching: Unified Pipeline with Contextual Modulation") is a DESIGN PRINCIPLE recorded in `DECISIONS.md:1914`, not a discrete shipped module. Its concrete realisations (AD-649 communication context, AD-639 trust-band tuning, AD-638 boot-camp gate) are all already shipped in `cognitive_agent.py` and set the modulation keys on the observation dict that AD-658 v1 snapshots. Dependency is satisfied; no AD-652-named code change is required by AD-658.

**Prompt:** `prompts/ad-658-chain-harness-metrics-v1.md`

## Standing rules

- Test gate command: `pytest tests/ -q -n 4 --dist=loadfile`. Triage failures at `-n 0` if parallel-only.
- One AD = one commit. Commit message footer: `Closes #317`.
- Hard-stop on phantom-API in implementation (not just tests). Pre-check ran clean — see "Verified Against Codebase" section in the prompt body.
- Do NOT extend scope to AD-659 (optimization), output-quality signals, or token-split plumbing. Those are explicitly listed under "What This Does NOT Change."
- Tests min 6, target 8. Builder reports actual delta in PROGRESS.md entry.
- `prune()` extension to chain_traces uses `rowid` for the row-count cap ORDER BY (table PK is `(chain_id, step_index)` composite, not single-column). Don't substitute `id` — it doesn't exist on chain_traces.

## Per-build quality gates

- Section 1 (`ChainExecutionTrace`): frozen dataclass; `to_dict()` only; no methods that depend on runtime.
- Section 2 (`CognitiveJournal` extension): mirror existing `record(...)` / `get_reasoning_chain(...)` shape exactly — fire-and-forget, never raises, `if not self._db: return/[]`. Schema additions guarded by `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`.
- Section 3 (emission hook): `hasattr(journal, "record_chain_trace")` guard for non-CognitiveJournal mocks (e.g., MagicMock journals in pre-existing tests). Wrapped in try/except with `logger.debug(... exc_info=True)`. Inserted AFTER existing journal.record block, BEFORE the failure-raise.
- Section 4 (chain_source plumbing): both `_execute_single_step` call sites in `_execute_steps` (single-step branch + parallel-wave branch) gain the kwarg. Confirmed only 2 internal call sites exist.
- Section 5 (router): mirrors `routers/journal.py` shape exactly. Import + register tuples both updated. Insert in alphabetical position (between `chat` and `counselor`).

## Wave 28 reminders

- AD-657 (Wave 27) just landed at commit `59654ba`. Builder's first action should be `git pull` to confirm clean working tree at HEAD.
- The chain executor's existing journal call uses `await journal.record(... dag_node_id=...)` for per-LLM-call entries — do NOT remove or modify that block. AD-658 traces are an ADDITIVE second stream alongside it. The two streams cross-reference by `(chain_id, step_index)` ↔ `dag_node_id` (which encodes `f"st:{chain_id}:{step_index}:{spec.sub_task_type.value}"` at `sub_task.py:583`).
- Tests 6–8 use `MagicMock(spec=CognitiveJournal)` or `AsyncMock` for journal — no need for a real DB. Tests 3–5 require a real `CognitiveJournal` against `tmp_path` for round-trip assertions (AD-657 lesson: real DB for round-trip, mocks for emission-flow assertions).
- The PRIMARY KEY `(chain_id, step_index)` is intentional — chain steps are write-once. INSERT OR IGNORE in `record_chain_trace` is the correct collision strategy (same idiom as the existing `record(...)` at `journal.py:170`).

## Builder workflow

1. `git pull` — confirm at `59654ba` or later.
2. Implement Sections 1–5 in order. Section 1 first (introduces the dataclass that Sections 2c/3c construct).
3. Run focused gate: `pytest tests/test_ad658_chain_harness_metrics.py -v -n 0`.
4. Run full gate: `pytest tests/ -q -n 4 --dist=loadfile`. Verify delta is `+6` to `+8`.
5. Commit single change. Title: `AD-658 v1: Cognitive Chain Harness Metrics`. Footer: `Closes #317`.
6. Update PROGRESS.md with closure entry; update roadmap.md; push.

## Hard-stop conditions

- Modulation key absent from `context` at trace-construction time → trace records `None`/`False` per the dataclass defaults. Not a hard stop.
- `chain_source` plumb breaks an existing test → triage; check if a test asserted the old `_execute_single_step` signature directly. If so, update the test (kwarg-only addition is backward-compatible at call sites; only direct-invocation tests need updates). Not a hard stop.
- Real architectural change required (e.g., `SubTaskExecutor` needs to import `CognitiveJournal` directly, or `BaseAgent` protocol changes) → hard stop, surface to architect. **The prompt's design avoids this** by going through the existing `journal: Any | None` parameter and `hasattr` duck-typing.
- Trace storage failure cascades into chain failure → hard stop. Verify the try/except guard placement is INSIDE the new emission block, not OUTSIDE it.
