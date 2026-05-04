# Wave 31 — AD-659 v1 Cognitive Chain Self-Optimization Loop (ANALYSIS ONLY)

**Closes:** #318. Standalone wave (depends on AD-658 v1 shipped at Wave 28). v1 ships the **analysis surface only** — `OptimizationProposal` dataclass + three pure detector functions + `ChainOptimizer` service + `ChainOptimizerConfig` + finalize wirer + `/api/chain-optimizer` router with proposal listing and decision-recording endpoints.

**Hard limit:** v1 is **ANALYSIS ONLY**. `apply_proposal()` raises `NotImplementedError("AD-659b")`. Approving a proposal records the decision but does NOT mutate any runtime parameter. The Counselor regression watchdog and A/B framework execution are explicitly deferred to AD-659b/c.

**Prompt:** `prompts/ad-659-chain-self-optimization-v1.md`

## Standing rules

- Test gate command: `pytest tests/ -q -n 4 --dist=loadfile`. Triage failures at `-n 0` if parallel-only.
- One AD = one commit. Commit message footer: `Closes #318`.
- Hard-stop on phantom-API in implementation (not just tests). Pre-check ran clean — see "Phantom-API Pre-Check" below.
- Do NOT extend scope to: `apply_proposal()` body, persistence (SQLite table for proposals), A/B framework execution, Counselor regression monitoring, automatic prompt rewriting, background scheduler, EventType emission, proposal de-duplication, parallel run dispatch. All explicitly listed under "What This Does NOT Change."
- Tests min 7, target 8. Builder reports actual delta in PROGRESS.md entry.
- **Wave 30 baseline test count: 10927.** Expected post-build: 10934 (+7) to 10935 (+8).

## Per-build quality gates

- **Section 1** (`chain_optimizer.py` NEW): `OptimizationProposal` is **mutable** dataclass (NOT frozen — `decision`/`decided_at`/`decided_by` are populated post-construction by `decide()`). Three detectors are pure functions taking `list[dict]` + kwargs-only thresholds, returning `list[OptimizationProposal]`. No I/O, no runtime access. `ChainOptimizer.analyze()` reads via `runtime.cognitive_journal.get_recent_chain_traces(limit=n)` (verified shipped at AD-658). `apply_proposal()` body is exactly `raise NotImplementedError("v1 analysis-only; apply deferred to AD-659b")`.
- **Section 2** (`ChainOptimizerConfig`): `enabled: bool = False` per Wave 10 lesson. New config class adjacent to `ChainTuningConfig` at `config.py:325–333`. `SystemConfig` field registered immediately after `chain_tuning` at `config.py:2002`.
- **Section 3** (wirer): mirrors `_wire_duty_scope_provider` shape exactly (`finalize.py:200–214`). Sets `runtime.chain_optimizer` public attribute.
- **Section 4** (router): mirrors `routers/chain_traces.py` shape for the GET path; mirrors `routers/build.py:150–177` for the decision POST shape. `DecisionRequest` Pydantic model. 503 if optimizer disabled, 400 on bad decision string, 404 on missing proposal id. Explicit `"applied": False` in success response so Captain UI cannot mistake decision-recording for application.
- **Section 5** (api.py registration): twin-block SEARCH/REPLACE — both the `from probos.routers import (...)` tuple AND the `for r in (...)` tuple gain `chain_optimizer` alphabetically between `chain_traces` and `counselor`. **Bundled into a single combined SEARCH/REPLACE block** to disambiguate the byte-identical inner-tuple lines (the only differing prefix is `from probos.routers import (` vs `for r in (`).

## Wave 31 reminders

- AD-645b (Wave 30) just landed at commit `9b3abc7` and the wave plan was already pushed planning Waves 31–35. Builder's first action is `git pull` to confirm clean working tree.
- AD-658 v1 is the data source. The `chain_traces` table is fully populated at HEAD; `get_recent_chain_traces(limit=n)` returns `list[dict]` with all 24 fields from `ChainExecutionTrace`. Detectors read `step_name`, `tier`, `duration_ms`, `success`, `chain_trust_band`, `sub_task_type`, `chain_source` — all confirmed columns.
- The "Code-Switching modulation space" referenced in issue #318 is unevenly tunable: `ChainTuningConfig.low_trust_ceiling`/`high_trust_floor` are config-tunable; `_chain_trust_band`/`_trust_score`/`_communication_context`/`_boot_camp_active` are observation-derived (not directly tunable). v1 proposes adjustments to the **config** parameters only. Adjustments to derived keys would require apply-path infrastructure that is deferred to AD-659b.
- The Counselor agent (`routers/counselor.py:1–80`) ships crew-wellness summaries — NOT chain-trace anomaly monitoring. v1 does NOT integrate Counselor; AD-659c picks that up after apply lands.
- Tests use `SimpleNamespace` + `AsyncMock` for runtime stubs (matches existing AD-657/AD-683 fixture style). FastAPI `TestClient` pattern for API tests (Section 8).

## Builder workflow

1. `git pull` — confirm at `9b3abc7` or later.
2. Implement Sections 1–5 in order. Section 1 first (introduces `OptimizationProposal` and `ChainOptimizer` that subsequent sections wire).
3. Run focused gate: `pytest tests/test_ad659_chain_self_optimization.py -v -n 0`.
4. Run full gate: `pytest tests/ -q -n 4 --dist=loadfile`. Verify delta is `+7` to `+8` over the 10927 baseline.
5. Commit single change. Title: `AD-659 v1: Cognitive Chain Self-Optimization Loop (analysis only)`. Footer: `Closes #318`.
6. Update PROGRESS.md with closure entry; update roadmap.md with AD-659b/c forward-refs; push.

## Hard-stop conditions

- Builder tempted to implement `apply_proposal()` body → **HARD STOP**. v1 is analysis-only. Mutating `runtime.config.chain_tuning.low_trust_ceiling` from a service method is the AD-659b apply path and requires A/B scaffolding, rollback hooks, and Counselor monitoring all of which are out of scope here.
- Builder tempted to add a SQLite table for proposal persistence → **HARD STOP**. v1 limitation is documented; persistence is AD-659b.
- Builder tempted to add a background `asyncio.create_task` analyze loop → **HARD STOP**. v1 requires explicit invocation.
- Builder hits "twin-block SEARCH/REPLACE" failure on `api.py` import + for-loop tuples → use the single combined block from Section 5 of the prompt (both tuples in one SEARCH); the differing prefixes (`from probos.routers import (` vs `for r in (`) provide unique anchoring within the combined block.
- Detector function returns proposals against an unrecognised `chain_trust_band` value (e.g., `"unknown"` from older traces) → expected behaviour: `detect_success_rate_floor_breach` skips non-low/non-high bands. Not a hard stop.
- Real architectural change required (e.g., `ChainOptimizer` needs to import `cognitive_agent.py` symbols, or the `BaseAgent` protocol changes) → hard stop, surface to architect. The prompt's design avoids this.

## Phantom-API Pre-Check

Ran `./scripts/phantom-api-precheck.ps1 prompts/ad-659-chain-self-optimization-v1.md` against HEAD (commit `9b3abc7`). Result: **4 phantom candidates flagged, all false positives. 0 NEW phantoms in implementation surface.**

**Raw precheck output:**
```
=== prompts/ad-659-chain-self-optimization-v1.md ===
  4 phantom symbol(s):
    - [<Class>(...)] class:NotImplementedError
    - [<Class>(...)] class:APIRouter
    - [<Class>(...)] class:HTTPException
    - [kwarg_mismatch] decide(actor=...)
```

**All four are false positives:**
- `NotImplementedError` — Python builtin (`apply_proposal()` raises it as the v1 hard limit; same FP class as previous-wave `Exception` / `RuntimeError` flags)
- `APIRouter` — FastAPI stdlib alias (same FP class as Wave 28's APIRouter; recurs every router-introducing AD)
- `HTTPException` — FastAPI stdlib alias (same FP class as APIRouter)
- `decide(actor=...)` — `ChainOptimizer.decide()` is introduced by Section 1 of THIS prompt with signature `decide(self, proposal_id, decision, *, actor="captain")`; the precheck's class index does not see the not-yet-shipped class, so flags the kwarg as if the method existed elsewhere. Same "introduced-in-prompt-not-in-index" FP class as Waves 27/28/29 (`get_recent_chain_traces`, `get_by_ids`, etc.).

**Other false positive candidates documented (introduced symbols, not flagged but called out):**
- `OptimizationProposal` — Section 1 (NEW dataclass within prompt)
- `ChainOptimizer` (and methods `analyze`/`list_pending`/`decide`/`apply_proposal`/`pending_proposals`) — Section 1 (NEW class within prompt)
- `ChainOptimizerConfig` — Section 2 (NEW Pydantic class within prompt)
- `_wire_chain_optimizer` — Section 3 (NEW function within prompt)
- `routers.chain_optimizer` (module) — Section 4 (NEW module within prompt)
- `runtime.chain_optimizer` — Section 3 (NEW public attribute set by wirer)
- `DecisionRequest` — Section 4 (NEW Pydantic model in router module)
- `detect_latency_p95_regression`, `detect_success_rate_floor_breach`, `detect_high_error_rate_by_chain_source` — Section 1 (NEW functions within prompt)
- `BaseModel` / `Depends` — FastAPI/Pydantic stdlib (not flagged but in the same FP class as APIRouter)

**Verified live (existing surfaces this prompt depends on):**
- `runtime.cognitive_journal` (runtime.py:1597)
- `CognitiveJournal.get_recent_chain_traces` (journal.py:295) — kwargs-only `limit`/`agent_id`/`since`
- `ChainExecutionTrace` field set (chain_trace.py:14–50) — only column names referenced from rows in detectors
- `ChainTuningConfig.low_trust_ceiling`/`high_trust_floor` defaults `0.60` / `0.75` (config.py:331–332)
- `_wire_duty_scope_provider` shape (finalize.py:200–214) — wirer template
- `routers/chain_traces.py` GET pattern — read template
- `routers/build.py:150–177` — Captain approval REST template
- `runtime.emit_event` (runtime.py:807) — emit_event dependency for sibling-pattern parity
- `get_runtime` (`routers/deps.py`) — FastAPI dependency

All grep hits accounted for. No phantom APIs in implementation. 0 NEW phantoms.
