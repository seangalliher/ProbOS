# AD-659b v1 — Chain Optimizer: Apply Approved Proposals + Persistence + Dedup

**Status:** ready
**Dependencies:** AD-659 (Wave 31, shipped), AD-658 (Wave 30, shipped — chain trace surface)
**Estimated tests:** 10 new + 1 existing-test update (the AD-659 `apply_proposal_raises_not_implemented` test)
**Closes:** GH issue #409

---

## Problem

AD-659 (Wave 31) shipped the analysis half of the cognitive-chain self-optimization loop: pure detectors over `chain_traces`, an in-memory `pending_proposals` queue, a Captain-approval REST surface, and a hard `apply_proposal()` stub that raises `NotImplementedError("v1 analysis-only; apply deferred to AD-659b")`. Three follow-up gaps remain before approved proposals can do anything:

1. **No apply path.** `decide("approve")` records intent only. The mutating effect on `runtime.config.chain_tuning` never happens.
2. **No persistence.** Proposals live in memory. A restart wipes the pending queue and any decisions.
3. **No dedup.** Re-running `analyze()` over the same window appends a fresh batch, so the queue grows unbounded under repeated invocation.

The ChainOptimizer is opt-in at the config level (`ChainOptimizerConfig.enabled = False`) and is currently invisible in production. AD-659b flips the apply path on under a separate `apply_enabled: bool = False` gate so persistence and dedup can ship without granting live-mutation authority by default.

## Solution

v1 closes the three gaps with a hard scope boundary at *parameter-tuning targets only*. The two `chain_tuning.*` targets (`low_trust_ceiling`, `high_trust_floor`) are mutable on `runtime.config.chain_tuning`. The other two target families (`chain_step.tier[X]` and `chain_source.review[X]`) require infrastructure that does not exist (per-step tier override store; chain-source review registry) — those are explicitly deferred to AD-659b-1 with the forcing function documented in §"Out of scope".

### Scope

1. **`apply_enabled: bool = False` config gate + `analysis_interval_seconds: int = 0` scheduled-loop knob.** Default-False on both transitional flags (Wave-10 convention #14). Captain opts in once persistence is validated.
2. **SQLite persistence.** New table `optimization_proposals` on `CognitiveJournal`, provisioned via `CREATE TABLE IF NOT EXISTS` (no warm-boot migration needed — net-new table). Records every proposal at `analyze()` time. Updated on `decide()`, on `apply_proposal()`, and on `revert_proposal()`.
3. **Dedup keyed on `(detector_name, target_parameter)`.** During `analyze()`, before inserting a new proposal, check the live `pending_proposals` list and the journal for an undecided proposal with the same `(detector_name, target_parameter)` tuple. Skip if a duplicate pending exists.
4. **Apply path.** `apply_proposal(proposal_id)` — guarded by `apply_enabled`. On enabled + tunable target, mutates `runtime.config.chain_tuning.<field>`, captures `pre_apply_value`, sets `applied=True` + `applied_at` + `applied_by`, persists. On disabled, raises `RuntimeError("apply_enabled=False")`. On non-tunable target, raises `ValueError(f"target {target_parameter!r} is not apply-able in v1; deferred to AD-659b-1")`.
5. **Manual revert.** `revert_proposal(proposal_id)` — restores `pre_apply_value` on `runtime.config.chain_tuning`, sets `applied=False`, persists. No automatic regression detection — that is AD-659c's wiring of the Counselor watchdog.
6. **Scheduled analyze loop.** When `analysis_interval_seconds > 0`, the wirer creates a periodic background task that calls `await opt.analyze()` every `analysis_interval_seconds`. Task reference stored on `runtime.chain_optimizer_analyze_task` (mirrors `runtime._flush_task` pattern at `finalize.py:2135`). `ChainOptimizer.stop()` cancels the task; the wirer does NOT auto-call stop (consistent with other periodic services).
7. **REST endpoints `POST /apply` + `POST /revert`.** Decide endpoint stays unchanged — apply is a separate explicit step (clean revertibility surface; Wave-10 convention #14 about not conflating decide-with-execute).
8. **Update existing AD-659 test.** `test_chain_optimizer_apply_proposal_raises_not_implemented` flips: now asserts `apply_enabled=False` raises `RuntimeError`, and that with `apply_enabled=True` and a tunable target the path mutates the live `runtime.config.chain_tuning` field.

### Out of scope (legitimate boundaries — DO NOT BUILD)

- **Apply path for `chain_step.tier[X]` targets** (latency p95 detector). Per-step tier override storage does not exist. Deferred to AD-659b-1 with forcing function: AD-456b runtime sandbox (Wave 55) is the right surface to validate tier shifts cheaply because tier mutation changes the cost/latency profile of every subsequent invocation of that step. Without sandbox isolation, a bad tier shift degrades every chain in flight.
- **Apply path for `chain_source.review[X]` targets** (high-error-rate detector). These are observation-only by design (per AD-659 spec) — there is no `chain_source` parameter to mutate. AD-659b-1 will introduce a `runtime.chain_source_review_registry` so the review flag has somewhere to land; until then `apply_proposal()` raises `ValueError`.
- **A/B testing framework.** Without an apply path at all, A/B is moot. Now that v1 ships apply, AD-659b-1 will ship split-traffic A/B with statistical-significance gating. Forcing function: must wait for ≥ 2 production apply cycles to validate the persistence + revert surface before adding split-traffic complexity.
- **Counselor regression watchdog.** Already deferred to AD-659c per AD-659 spec. Watchdog requires apply (which v1 ships) + an `OPTIMIZATION_PROPOSAL_APPLIED` EventType (which AD-659b explicitly does NOT add — Wave 51 convention).
- **Automatic revert on regression.** Manual revert only in v1. Auto-revert needs the Counselor watchdog (AD-659c).
- **New EventType, new pool, new agent, new Pydantic config beyond the 2 new fields.**
- **Cross-restart in-flight task recovery.** If the scheduled loop is mid-iteration during shutdown, the iteration is cancelled. Persistence covers proposals; loop state is ephemeral.
- **Warm-boot replay of applied proposals.** Pydantic-model mutation on `runtime.config.chain_tuning` is in-memory only — a restart restores the field to its YAML/env value. The proposal record persists with `applied=1` + `pre_apply_value`, but v1 does NOT re-apply it on warm boot. Forcing function for AD-659b-1: warm-boot replay needs an idempotency contract (what if the YAML default was changed in the meantime?) and a re-validation hook (was this proposal still relevant?). Captain treats apply as best-effort-until-restart in v1; for durable changes Captain edits YAML directly. The persisted record is the audit trail.

---

## Verified Against Codebase (HEAD post-Wave-51, 2026-05-05)

| Symbol | Path | Line | Verifying line |
|---|---|---|---|
| `OptimizationProposal` mutable dataclass (10 fields) | `cognitive/chain_optimizer.py` | 22-43 | `@dataclass\nclass OptimizationProposal:` + ctor body |
| `OptimizationProposal.to_dict()` returns asdict() projection | `cognitive/chain_optimizer.py` | 45-47 | `def to_dict(self) -> dict[str, Any]: return asdict(self)` |
| `ChainOptimizer.__init__(runtime, *, analysis_window=100, ...)` | `cognitive/chain_optimizer.py` | 200-218 | ctor signature |
| `ChainOptimizer.analyze(*, window=None)` async, fire-and-forget, returns new batch only | `cognitive/chain_optimizer.py` | 220-254 | method body |
| `ChainOptimizer.list_pending() -> list[OptimizationProposal]` | `cognitive/chain_optimizer.py` | 256-258 | `[p for p in self.pending_proposals if p.decision is None]` |
| `ChainOptimizer.decide(proposal_id, decision, *, actor="captain")` mutates fields, returns proposal or None | `cognitive/chain_optimizer.py` | 260-273 | method body |
| `ChainOptimizer.apply_proposal(proposal_id)` raises NotImplementedError today | `cognitive/chain_optimizer.py` | 275-278 | `raise NotImplementedError("v1 analysis-only; apply deferred to AD-659b")` |
| `ChainOptimizerConfig` (`enabled=False`, 5 thresholds) | `config.py` | 336-346 | model body |
| `SystemConfig.chain_optimizer` field | `config.py` | 2273 | `chain_optimizer: ChainOptimizerConfig = ChainOptimizerConfig()  # AD-659` |
| `ChainTuningConfig.low_trust_ceiling: float = 0.60` | `config.py` | 331 | live read field |
| `ChainTuningConfig.high_trust_floor: float = 0.75` | `config.py` | 332 | live read field |
| `cognitive_agent.py` reads via `runtime.config.chain_tuning.<field>` | `cognitive/cognitive_agent.py` | 1902-1911, 2090-2099 | `_chain_cfg = getattr(getattr(_rt, 'config', None), 'chain_tuning', None)` then `_chain_cfg.low_trust_ceiling` / `_chain_cfg.high_trust_floor` |
| `_wire_chain_optimizer` wirer | `startup/finalize.py` | 214-238 | wirer body |
| `_wire_chain_optimizer` cascade slot | `startup/finalize.py` | 855 | `if _wire_chain_optimizer(runtime=runtime, config=config):` |
| `runtime.chain_optimizer = ChainOptimizer(runtime, ...)` (kwargs already passed) | `startup/finalize.py` | 222-232 | wirer body |
| Periodic-task precedent (`runtime._flush_task = asyncio.create_task(...)`) | `startup/finalize.py` | 2135 | `runtime._flush_task = asyncio.create_task(dream_adapter.periodic_flush_loop())` |
| Journal `_SCHEMA_*` literals + `await self._db.executescript(...)` chain | `cognitive/journal.py` | 21-115, 139-165 | schemas + start path |
| Idempotent ALTER pattern (warm boot) | `cognitive/journal.py` | 144-150, 158-163 | `try: ... except sqlite3.OperationalError: pass` and `try: ... except Exception: pass` |
| Journal `record_chain_trace` precedent (fire-and-forget INSERT OR IGNORE) | `cognitive/journal.py` | 312-345 | method body |
| Journal `get_recent_chain_traces` precedent (parameterized WHERE, dict rows) | `cognitive/journal.py` | 347-385 | method body |
| `routers/chain_optimizer.py` router (`prefix="/api/chain-optimizer"`) | `routers/chain_optimizer.py` | 20 | `router = APIRouter(prefix="/api/chain-optimizer", tags=["chain-optimizer"])` |
| `decide_proposal` endpoint shape | `routers/chain_optimizer.py` | 51-82 | endpoint body — `applied: False` hardcoded, mutate to read from proposal |
| Existing AD-659 test (`apply_proposal_raises_not_implemented`) | `tests/test_ad659_chain_self_optimization.py` | 188-191 | `with pytest.raises(NotImplementedError, match="AD-659b"):` |
| Existing AD-659 router test (TestClient pattern, dependency_overrides) | `tests/test_ad659_chain_self_optimization.py` | 197-230 | router test body |

`ChainOptimizerConfig` already has `enabled`, `analysis_window`, `latency_p95_ms_floor`, `success_rate_floor`, `error_rate_ceiling`, `min_samples_per_group`. AD-659b adds `apply_enabled` and `analysis_interval_seconds` only.

---

## Implementation

### Section 0 — Extend `ChainOptimizerConfig` with two new fields

**File:** `src/probos/config.py`

`SEARCH` block (around line 336-346):
```python
class ChainOptimizerConfig(BaseModel):
    """AD-659 v1: Cognitive Chain Self-Optimization analysis service.

    v1 is analysis-only — produces OptimizationProposal instances which
    require Captain approval. apply_proposal() raises NotImplementedError;
    automatic application is deferred to AD-659b.
    """

    enabled: bool = False  # opt-in until validated
    analysis_window: int = 100
    latency_p95_ms_floor: float = 10000.0
    success_rate_floor: float = 0.7
    error_rate_ceiling: float = 0.3
    min_samples_per_group: int = 20
```

`REPLACE`:
```python
class ChainOptimizerConfig(BaseModel):
    """AD-659 v1 + AD-659b: Cognitive Chain Self-Optimization service.

    v1 (AD-659) shipped analysis-only proposal generation + Captain approval
    REST surface. AD-659b adds the apply path (gated by `apply_enabled`),
    SQLite persistence, dedup keyed on (detector_name, target_parameter),
    manual revert, and an opt-in scheduled analyze loop.

    Both new flags default OFF. `apply_enabled=True` grants live-mutation
    authority over `chain_tuning.low_trust_ceiling` / `high_trust_floor`.
    `analysis_interval_seconds > 0` enables periodic background analysis.
    """

    enabled: bool = False  # opt-in until validated
    analysis_window: int = 100
    latency_p95_ms_floor: float = 10000.0
    success_rate_floor: float = 0.7
    error_rate_ceiling: float = 0.3
    min_samples_per_group: int = 20
    apply_enabled: bool = False  # AD-659b: apply path gate (default OFF)
    analysis_interval_seconds: int = 0  # AD-659b: 0 disables scheduled loop

    @field_validator("analysis_interval_seconds")
    @classmethod
    def _validate_interval(cls, v: int) -> int:
        if v < 0:
            raise ValueError("analysis_interval_seconds must be >= 0")
        return v
```

Verify `field_validator` is already imported at top of `config.py` — it is (used by `DiagnosticContextConfig`, `CausalReasoningConfig` per AD-660b).

---

### Section 1 — Extend `OptimizationProposal` with apply-tracking fields

**File:** `src/probos/cognitive/chain_optimizer.py`

`SEARCH` block (around line 22-47):
```python
@dataclass
class OptimizationProposal:
    """Single proposed adjustment to a Code-Switching modulation parameter.

    Mutable — `decision` and `decided_at`/`decided_by` are populated when
    the Captain approves or rejects via the API. Frozen would block that.
    """

    target_parameter: str          # e.g. "chain_tuning.low_trust_ceiling"
    current_value: Any             # e.g. 0.60
    proposed_value: Any            # e.g. 0.55
    rationale: str                 # human-readable reasoning
    supporting_metric: str         # e.g. "success rate 0.42 over last 100 traces"
    risk_level: str                # "low" | "medium" | "high"
    detector_name: str             # name of the detector that produced this
    proposal_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)
    decision: str | None = None    # None | "approve" | "reject"
    decided_at: float | None = None
    decided_by: str | None = None  # actor id (e.g. "captain")

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict projection for JSON serialization."""
        return asdict(self)
```

`REPLACE`:
```python
@dataclass
class OptimizationProposal:
    """Single proposed adjustment to a Code-Switching modulation parameter.

    Mutable — `decision`/`decided_at`/`decided_by` are populated by the
    Captain via the API; `applied`/`applied_at`/`applied_by`/`pre_apply_value`
    are populated by `ChainOptimizer.apply_proposal()` (AD-659b).
    """

    target_parameter: str          # e.g. "chain_tuning.low_trust_ceiling"
    current_value: Any             # e.g. 0.60
    proposed_value: Any            # e.g. 0.55
    rationale: str                 # human-readable reasoning
    supporting_metric: str         # e.g. "success rate 0.42 over last 100 traces"
    risk_level: str                # "low" | "medium" | "high"
    detector_name: str             # name of the detector that produced this
    proposal_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)
    decision: str | None = None    # None | "approve" | "reject"
    decided_at: float | None = None
    decided_by: str | None = None  # actor id (e.g. "captain")
    # AD-659b: apply-tracking fields (all defaulted; preserves field-order rule)
    applied: bool = False
    applied_at: float | None = None
    applied_by: str | None = None
    pre_apply_value: Any = None    # captured pre-mutation for revert

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict projection for JSON serialization."""
        return asdict(self)
```

---

### Section 2 — Add `optimization_proposals` schema + journal CRUD

**File:** `src/probos/cognitive/journal.py`

`SEARCH` block (the AD-660b migration block at lines 108-115):
```python
# AD-660b: idempotent migration for warm-boot DBs created under AD-660 v1.
_MIGRATIONS_CAUSAL_TEMPLATES_AD660B = (
    "ALTER TABLE causal_templates ADD COLUMN ranked_hypotheses_json TEXT",
    "ALTER TABLE causal_templates ADD COLUMN recommended_actions_json TEXT",
)
```

`REPLACE`:
```python
# AD-660b: idempotent migration for warm-boot DBs created under AD-660 v1.
_MIGRATIONS_CAUSAL_TEMPLATES_AD660B = (
    "ALTER TABLE causal_templates ADD COLUMN ranked_hypotheses_json TEXT",
    "ALTER TABLE causal_templates ADD COLUMN recommended_actions_json TEXT",
)

# AD-659b: ChainOptimizer proposal persistence (net-new table; no warm-boot migration).
_SCHEMA_OPTIMIZATION_PROPOSALS = """
CREATE TABLE IF NOT EXISTS optimization_proposals (
    proposal_id        TEXT PRIMARY KEY,
    detector_name      TEXT NOT NULL DEFAULT '',
    target_parameter   TEXT NOT NULL DEFAULT '',
    current_value_json TEXT NOT NULL DEFAULT 'null',
    proposed_value_json TEXT NOT NULL DEFAULT 'null',
    rationale          TEXT NOT NULL DEFAULT '',
    supporting_metric  TEXT NOT NULL DEFAULT '',
    risk_level         TEXT NOT NULL DEFAULT '',
    created_at         REAL NOT NULL DEFAULT 0.0,
    decision           TEXT,
    decided_at         REAL,
    decided_by         TEXT,
    applied            INTEGER NOT NULL DEFAULT 0,
    applied_at         REAL,
    applied_by         TEXT,
    pre_apply_value_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_optimization_proposals_created_at
    ON optimization_proposals(created_at);
CREATE INDEX IF NOT EXISTS idx_optimization_proposals_dedup_key
    ON optimization_proposals(detector_name, target_parameter, decision);
"""
```

Then in the `start()` method, after the existing AD-660b migration loop (around line 163, after `await self._db.commit()`), add the new schema execution.

`SEARCH` block (around line 158-163):
```python
        # AD-660b: idempotent ALTER TABLE for warm-boot DBs that pre-date AD-660b.
        for stmt in _MIGRATIONS_CAUSAL_TEMPLATES_AD660B:
            try:
                await self._db.execute(stmt)
            except Exception:
                pass
        await self._db.commit()
```

`REPLACE`:
```python
        # AD-660b: idempotent ALTER TABLE for warm-boot DBs that pre-date AD-660b.
        for stmt in _MIGRATIONS_CAUSAL_TEMPLATES_AD660B:
            try:
                await self._db.execute(stmt)
            except Exception:
                pass
        # AD-659b: ChainOptimizer proposal persistence (idempotent CREATE).
        await self._db.executescript(_SCHEMA_OPTIMIZATION_PROPOSALS)
        await self._db.commit()
```

Now add four new CRUD methods on `CognitiveJournal`. Insert them immediately after `get_recent_chain_traces` (around line 386 — before `record_causal_template`).

`SEARCH` block (around line 384-390 — find the end of `get_recent_chain_traces` and the start of `record_causal_template`):
```python
            return [dict(row) for row in rows]
        except Exception:
            logger.debug("Chain trace query failed", exc_info=True)
            return []

    async def record_causal_template(self, template: Any) -> None:
```

`REPLACE`:
```python
            return [dict(row) for row in rows]
        except Exception:
            logger.debug("Chain trace query failed", exc_info=True)
            return []

    async def record_optimization_proposal(self, proposal: Any) -> None:
        """AD-659b: Persist or update a single OptimizationProposal.

        Uses INSERT OR REPLACE keyed on `proposal_id` so the same call site
        handles initial creation and post-decide / post-apply / post-revert
        updates. Fire-and-forget — never raises.
        """
        if not self._db:
            return
        try:
            await self._db.execute(
                """INSERT OR REPLACE INTO optimization_proposals
                   (proposal_id, detector_name, target_parameter,
                    current_value_json, proposed_value_json,
                    rationale, supporting_metric, risk_level, created_at,
                    decision, decided_at, decided_by,
                    applied, applied_at, applied_by, pre_apply_value_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    proposal.proposal_id,
                    proposal.detector_name,
                    proposal.target_parameter,
                    json.dumps(proposal.current_value),
                    json.dumps(proposal.proposed_value),
                    proposal.rationale,
                    proposal.supporting_metric,
                    proposal.risk_level,
                    proposal.created_at,
                    proposal.decision,
                    proposal.decided_at,
                    proposal.decided_by,
                    1 if proposal.applied else 0,
                    proposal.applied_at,
                    proposal.applied_by,
                    json.dumps(proposal.pre_apply_value),
                ),
            )
            await self._db.commit()
        except Exception:
            logger.debug("AD-659b: optimization proposal record failed", exc_info=True)

    async def get_pending_optimization_proposals(
        self, *, detector_name: str | None = None,
        target_parameter: str | None = None,
    ) -> list[dict[str, Any]]:
        """AD-659b: Return undecided (decision IS NULL) proposals, oldest-first.

        Optional dedup-key filter for `(detector_name, target_parameter)` lookups.
        """
        if not self._db:
            return []
        try:
            clauses = ["decision IS NULL"]
            params: list[Any] = []
            if detector_name is not None:
                clauses.append("detector_name = ?")
                params.append(detector_name)
            if target_parameter is not None:
                clauses.append("target_parameter = ?")
                params.append(target_parameter)
            where = "WHERE " + " AND ".join(clauses)
            cursor = await self._db.execute(
                f"SELECT * FROM optimization_proposals {where} ORDER BY created_at ASC",
                params,
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception:
            logger.debug("AD-659b: pending proposals query failed", exc_info=True)
            return []

    async def get_optimization_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        """AD-659b: Fetch a single proposal by id."""
        if not self._db:
            return None
        try:
            cursor = await self._db.execute(
                "SELECT * FROM optimization_proposals WHERE proposal_id = ?",
                (proposal_id,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
        except Exception:
            logger.debug("AD-659b: proposal fetch failed", exc_info=True)
            return None

    async def record_causal_template(self, template: Any) -> None:
```

Verify the existing top-of-file imports include `json` — it is (used by `record_causal_template`'s `json.dumps`). Otherwise add `import json` to the imports block.

---

### Section 3 — Rewrite `ChainOptimizer` for persistence + dedup + apply + revert + scheduled loop

**File:** `src/probos/cognitive/chain_optimizer.py`

`SEARCH` block (around line 200-278 — the entire `class ChainOptimizer:` body from `class ChainOptimizer:` to the end of `apply_proposal`):
```python
class ChainOptimizer:
    """Analysis-only proposal service (AD-659 v1).

    Reads recent chain traces from runtime.cognitive_journal, runs detector
    functions, accumulates proposals in `pending_proposals`. Does NOT apply
    any proposal — `apply_proposal()` raises NotImplementedError until AD-659b.
    """

    def __init__(
        self,
        runtime: Any,
        *,
        analysis_window: int = 100,
        latency_p95_ms_floor: float = 10000.0,
        success_rate_floor: float = 0.7,
        error_rate_ceiling: float = 0.3,
        min_samples_per_group: int = 20,
        emit_event: Callable[..., None] | None = None,
    ) -> None:
        self._runtime = runtime
        self._analysis_window = analysis_window
        self._latency_p95_ms_floor = latency_p95_ms_floor
        self._success_rate_floor = success_rate_floor
        self._error_rate_ceiling = error_rate_ceiling
        self._min_samples_per_group = min_samples_per_group
        self.emit_event = emit_event
        self.pending_proposals: list[OptimizationProposal] = []

    async def analyze(
        self, *, window: int | None = None,
    ) -> list[OptimizationProposal]:
        """Read recent traces, run detectors, append new proposals.

        Returns the list of proposals produced by this analysis pass
        (NOT the cumulative `pending_proposals`). Idempotent in the sense
        that re-running over the same window appends a fresh batch — v1
        does NOT de-duplicate (deferred to AD-659b).
        """
        journal = getattr(self._runtime, "cognitive_journal", None)
        if journal is None:
            return []
        n = window if window is not None else self._analysis_window
        try:
            traces = await journal.get_recent_chain_traces(limit=n)
        except Exception:
            logger.warning(
                "AD-659: get_recent_chain_traces failed; skipping analysis",
                exc_info=True,
            )
            return []
        new_proposals: list[OptimizationProposal] = []
        new_proposals.extend(detect_latency_p95_regression(
            traces,
            p95_floor_ms=self._latency_p95_ms_floor,
            min_samples=self._min_samples_per_group,
        ))
        new_proposals.extend(detect_success_rate_floor_breach(
            traces,
            success_floor=self._success_rate_floor,
            min_samples=self._min_samples_per_group,
        ))
        new_proposals.extend(detect_high_error_rate_by_chain_source(
            traces,
            error_rate_ceiling=self._error_rate_ceiling,
            min_samples=self._min_samples_per_group,
        ))
        self.pending_proposals.extend(new_proposals)
        return new_proposals

    def list_pending(self) -> list[OptimizationProposal]:
        """Return all pending (undecided) proposals."""
        return [p for p in self.pending_proposals if p.decision is None]

    def decide(
        self, proposal_id: str, decision: str, *, actor: str = "captain",
    ) -> OptimizationProposal | None:
        """Record approve/reject on a proposal. v1 stores decision only —
        does NOT apply.
        """
        if decision not in ("approve", "reject"):
            raise ValueError(
                f"decision must be 'approve' or 'reject', got {decision!r}"
            )
        for p in self.pending_proposals:
            if p.proposal_id == proposal_id:
                p.decision = decision
                p.decided_at = time.time()
                p.decided_by = actor
                return p
        return None

    def apply_proposal(self, proposal_id: str) -> None:
        """v1 stub. Apply path is AD-659b; v1 is analysis-only."""
        raise NotImplementedError(
            "v1 analysis-only; apply deferred to AD-659b"
        )
```

`REPLACE`:
```python
class ChainOptimizer:
    """Cognitive-chain self-optimization service (AD-659 v1 + AD-659b).

    AD-659 shipped analysis-only proposal generation; AD-659b adds:
      - SQLite persistence via runtime.cognitive_journal
      - dedup keyed on (detector_name, target_parameter) for pending entries
      - apply_proposal() (gated by apply_enabled) for chain_tuning.* targets
      - revert_proposal() for manual rollback
      - opt-in scheduled analyze loop (analysis_interval_seconds > 0)

    Apply path is intentionally narrow: only `chain_tuning.low_trust_ceiling`
    and `chain_tuning.high_trust_floor` are mutated. Tier shifts and chain-
    source-review flags raise ValueError — those are AD-659b-1 territory.
    """

    # AD-659b: target_parameters that the apply path can mutate.
    _APPLYABLE_TUNING_FIELDS = ("low_trust_ceiling", "high_trust_floor")

    def __init__(
        self,
        runtime: Any,
        *,
        analysis_window: int = 100,
        latency_p95_ms_floor: float = 10000.0,
        success_rate_floor: float = 0.7,
        error_rate_ceiling: float = 0.3,
        min_samples_per_group: int = 20,
        apply_enabled: bool = False,
        analysis_interval_seconds: int = 0,
        emit_event: Callable[..., None] | None = None,
    ) -> None:
        self._runtime = runtime
        self._analysis_window = analysis_window
        self._latency_p95_ms_floor = latency_p95_ms_floor
        self._success_rate_floor = success_rate_floor
        self._error_rate_ceiling = error_rate_ceiling
        self._min_samples_per_group = min_samples_per_group
        self._apply_enabled = apply_enabled
        self._analysis_interval_seconds = analysis_interval_seconds
        self.emit_event = emit_event
        self.pending_proposals: list[OptimizationProposal] = []
        self._loop_task: Any = None  # asyncio.Task when scheduled loop active

    async def analyze(
        self, *, window: int | None = None,
    ) -> list[OptimizationProposal]:
        """Read recent traces, run detectors, append new proposals.

        AD-659b: dedup on (detector_name, target_parameter) — if an undecided
        proposal already exists in `pending_proposals` OR in the journal
        with the same key, the new proposal is dropped. Persists every
        retained proposal to `runtime.cognitive_journal`.
        """
        journal = getattr(self._runtime, "cognitive_journal", None)
        if journal is None:
            return []
        n = window if window is not None else self._analysis_window
        try:
            traces = await journal.get_recent_chain_traces(limit=n)
        except Exception:
            logger.warning(
                "AD-659: get_recent_chain_traces failed; skipping analysis",
                exc_info=True,
            )
            return []
        candidate_proposals: list[OptimizationProposal] = []
        candidate_proposals.extend(detect_latency_p95_regression(
            traces,
            p95_floor_ms=self._latency_p95_ms_floor,
            min_samples=self._min_samples_per_group,
        ))
        candidate_proposals.extend(detect_success_rate_floor_breach(
            traces,
            success_floor=self._success_rate_floor,
            min_samples=self._min_samples_per_group,
        ))
        candidate_proposals.extend(detect_high_error_rate_by_chain_source(
            traces,
            error_rate_ceiling=self._error_rate_ceiling,
            min_samples=self._min_samples_per_group,
        ))
        retained: list[OptimizationProposal] = []
        for proposal in candidate_proposals:
            if await self._is_duplicate_pending(journal, proposal):
                continue
            self.pending_proposals.append(proposal)
            retained.append(proposal)
            await journal.record_optimization_proposal(proposal)
        return retained

    async def _is_duplicate_pending(
        self, journal: Any, proposal: OptimizationProposal,
    ) -> bool:
        """AD-659b: True if an undecided proposal with the same dedup key exists."""
        # In-memory check (covers the current session)
        for existing in self.pending_proposals:
            if (
                existing.decision is None
                and existing.detector_name == proposal.detector_name
                and existing.target_parameter == proposal.target_parameter
            ):
                return True
        # Journal check (covers prior-restart entries)
        try:
            rows = await journal.get_pending_optimization_proposals(
                detector_name=proposal.detector_name,
                target_parameter=proposal.target_parameter,
            )
        except Exception:
            return False
        return bool(rows)

    def list_pending(self) -> list[OptimizationProposal]:
        """Return all pending (undecided) proposals."""
        return [p for p in self.pending_proposals if p.decision is None]

    async def decide(
        self, proposal_id: str, decision: str, *, actor: str = "captain",
    ) -> OptimizationProposal | None:
        """AD-659 v1 + AD-659b: Record approve/reject. Persists the update
        to the journal. Does NOT mutate `runtime.config` — call apply_proposal
        for that.
        """
        if decision not in ("approve", "reject"):
            raise ValueError(
                f"decision must be 'approve' or 'reject', got {decision!r}"
            )
        for p in self.pending_proposals:
            if p.proposal_id == proposal_id:
                p.decision = decision
                p.decided_at = time.time()
                p.decided_by = actor
                journal = getattr(self._runtime, "cognitive_journal", None)
                if journal is not None:
                    await journal.record_optimization_proposal(p)
                return p
        return None

    async def apply_proposal(
        self, proposal_id: str, *, actor: str = "captain",
    ) -> OptimizationProposal:
        """AD-659b: Apply an approved proposal to live `runtime.config`.

        Only `chain_tuning.low_trust_ceiling` and `chain_tuning.high_trust_floor`
        are mutable in v1. Tier shifts and chain-source review flags raise
        ValueError (deferred to AD-659b-1).

        Raises:
            RuntimeError: if `apply_enabled=False` (Captain has not opted in).
            ValueError: if proposal not found, not approved, or non-tunable target.
        """
        if not self._apply_enabled:
            raise RuntimeError(
                "AD-659b: apply_enabled=False; Captain must opt in via config"
            )
        proposal = next(
            (p for p in self.pending_proposals if p.proposal_id == proposal_id),
            None,
        )
        if proposal is None:
            raise ValueError(f"AD-659b: proposal {proposal_id!r} not found")
        if proposal.decision != "approve":
            raise ValueError(
                f"AD-659b: proposal {proposal_id!r} is not approved "
                f"(decision={proposal.decision!r})"
            )
        if proposal.applied:
            raise ValueError(
                f"AD-659b: proposal {proposal_id!r} already applied"
            )
        # Only chain_tuning.<applyable_field> targets are mutable in v1.
        if not proposal.target_parameter.startswith("chain_tuning."):
            raise ValueError(
                f"AD-659b: target {proposal.target_parameter!r} is not apply-able "
                f"in v1; deferred to AD-659b-1"
            )
        field_name = proposal.target_parameter.split(".", 1)[1]
        if field_name not in self._APPLYABLE_TUNING_FIELDS:
            raise ValueError(
                f"AD-659b: target {proposal.target_parameter!r} is not apply-able "
                f"in v1; deferred to AD-659b-1"
            )
        chain_tuning = getattr(
            getattr(self._runtime, "config", None), "chain_tuning", None,
        )
        if chain_tuning is None:
            raise ValueError(
                "AD-659b: runtime.config.chain_tuning unavailable"
            )
        proposal.pre_apply_value = getattr(chain_tuning, field_name)
        setattr(chain_tuning, field_name, proposal.proposed_value)
        proposal.applied = True
        proposal.applied_at = time.time()
        proposal.applied_by = actor
        journal = getattr(self._runtime, "cognitive_journal", None)
        if journal is not None:
            await journal.record_optimization_proposal(proposal)
        logger.info(
            "AD-659b: applied proposal %s — %s: %s -> %s (actor=%s)",
            proposal.proposal_id, proposal.target_parameter,
            proposal.pre_apply_value, proposal.proposed_value, actor,
        )
        return proposal

    async def revert_proposal(
        self, proposal_id: str, *, actor: str = "captain",
    ) -> OptimizationProposal:
        """AD-659b: Manually revert an applied proposal (restore pre_apply_value).

        Raises:
            ValueError: if proposal not found or not currently applied.
        """
        proposal = next(
            (p for p in self.pending_proposals if p.proposal_id == proposal_id),
            None,
        )
        if proposal is None:
            raise ValueError(f"AD-659b: proposal {proposal_id!r} not found")
        if not proposal.applied:
            raise ValueError(
                f"AD-659b: proposal {proposal_id!r} is not currently applied"
            )
        field_name = proposal.target_parameter.split(".", 1)[1]
        chain_tuning = getattr(
            getattr(self._runtime, "config", None), "chain_tuning", None,
        )
        if chain_tuning is None:
            raise ValueError(
                "AD-659b: runtime.config.chain_tuning unavailable"
            )
        setattr(chain_tuning, field_name, proposal.pre_apply_value)
        prior_value = proposal.proposed_value
        proposal.applied = False
        proposal.applied_at = time.time()
        proposal.applied_by = actor
        journal = getattr(self._runtime, "cognitive_journal", None)
        if journal is not None:
            await journal.record_optimization_proposal(proposal)
        logger.info(
            "AD-659b: reverted proposal %s — %s: %s -> %s (actor=%s)",
            proposal.proposal_id, proposal.target_parameter,
            prior_value, proposal.pre_apply_value, actor,
        )
        return proposal

    def start_scheduled_loop(self) -> None:
        """AD-659b: Start the periodic analyze loop if `analysis_interval_seconds > 0`.

        Idempotent — calling twice is a no-op. Stores the task on
        `self._loop_task` so the wirer can mirror it onto
        `runtime.chain_optimizer_analyze_task` for shutdown observability.
        """
        if self._analysis_interval_seconds <= 0:
            return
        if self._loop_task is not None and not self._loop_task.done():
            return
        import asyncio
        self._loop_task = asyncio.create_task(self._scheduled_loop())

    async def _scheduled_loop(self) -> None:
        """AD-659b: Periodic background analysis. Cancellation-safe."""
        import asyncio
        try:
            while True:
                try:
                    await self.analyze()
                except Exception:
                    logger.warning(
                        "AD-659b: scheduled analyze iteration failed",
                        exc_info=True,
                    )
                await asyncio.sleep(self._analysis_interval_seconds)
        except asyncio.CancelledError:
            logger.info("AD-659b: scheduled analyze loop cancelled")
            raise

    async def stop(self) -> None:
        """AD-659b: Cancel the scheduled loop if running. Idempotent."""
        if self._loop_task is None:
            return
        task = self._loop_task
        self._loop_task = None
        if task.done():
            return
        task.cancel()
        try:
            await task
        except BaseException:
            pass
```

Note: `decide()` becomes `async` because it now persists. The router will need to `await` it (Section 5).

---

### Section 4 — Wirer pass-through for new config fields + scheduled-loop start

**File:** `src/probos/startup/finalize.py`

`SEARCH` block (around line 214-238 — the current `_wire_chain_optimizer` body):
```python
def _wire_chain_optimizer(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-659 v1: Wire ChainOptimizer analysis-only proposal service."""
    cfg = getattr(config, "chain_optimizer", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.chain_optimizer import ChainOptimizer

    emit_fn = getattr(runtime, "emit_event", None)
    runtime.chain_optimizer = ChainOptimizer(
        runtime,
        analysis_window=cfg.analysis_window,
        latency_p95_ms_floor=cfg.latency_p95_ms_floor,
        success_rate_floor=cfg.success_rate_floor,
        error_rate_ceiling=cfg.error_rate_ceiling,
        min_samples_per_group=cfg.min_samples_per_group,
        emit_event=emit_fn,
    )
    logger.info(
        "AD-659: ChainOptimizer v1 initialized "
        "(analysis-only; apply path deferred to AD-659b)"
    )
    return True
```

`REPLACE`:
```python
def _wire_chain_optimizer(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-659 v1 + AD-659b: Wire ChainOptimizer with apply path + persistence."""
    cfg = getattr(config, "chain_optimizer", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.chain_optimizer import ChainOptimizer

    emit_fn = getattr(runtime, "emit_event", None)
    optimizer = ChainOptimizer(
        runtime,
        analysis_window=cfg.analysis_window,
        latency_p95_ms_floor=cfg.latency_p95_ms_floor,
        success_rate_floor=cfg.success_rate_floor,
        error_rate_ceiling=cfg.error_rate_ceiling,
        min_samples_per_group=cfg.min_samples_per_group,
        apply_enabled=getattr(cfg, "apply_enabled", False),
        analysis_interval_seconds=getattr(cfg, "analysis_interval_seconds", 0),
        emit_event=emit_fn,
    )
    runtime.chain_optimizer = optimizer
    if getattr(cfg, "analysis_interval_seconds", 0) > 0:
        optimizer.start_scheduled_loop()
        # Mirror task onto runtime for shutdown observability (matches
        # `runtime._flush_task` precedent).
        runtime.chain_optimizer_analyze_task = optimizer._loop_task
    logger.info(
        "AD-659b: ChainOptimizer initialized (apply_enabled=%s, "
        "analysis_interval_seconds=%s)",
        getattr(cfg, "apply_enabled", False),
        getattr(cfg, "analysis_interval_seconds", 0),
    )
    return True
```

---

### Section 5 — REST endpoints: `decide` becomes async; new `apply` + `revert`

**File:** `src/probos/routers/chain_optimizer.py`

`SEARCH` block (the entire `decide_proposal` endpoint, around line 51-82):
```python
@router.post("/proposals/{proposal_id}/decide")
async def decide_proposal(
    proposal_id: str,
    req: DecisionRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-659 v1: Record Captain's decision on a proposal.

    v1 records the decision in-memory only. Approved proposals are NOT
    applied — apply_proposal() raises NotImplementedError until AD-659b.
    """
    optimizer = getattr(runtime, "chain_optimizer", None)
    if optimizer is None:
        raise HTTPException(status_code=503, detail="ChainOptimizer not enabled")
    if req.decision not in ("approve", "reject"):
        raise HTTPException(
            status_code=400,
            detail="decision must be 'approve' or 'reject'",
        )
    proposal = optimizer.decide(proposal_id, req.decision, actor=req.actor)
    if proposal is None:
        raise HTTPException(
            status_code=404, detail=f"proposal {proposal_id} not found"
        )
    return {
        "status": "recorded",
        "applied": False,  # explicit v1 limitation
        "proposal": proposal.to_dict(),
    }
```

`REPLACE`:
```python
@router.post("/proposals/{proposal_id}/decide")
async def decide_proposal(
    proposal_id: str,
    req: DecisionRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-659 v1 + AD-659b: Record Captain's decision on a proposal.

    Decision is persisted but NOT applied — call POST /apply explicitly
    to mutate `runtime.config.chain_tuning` (gated by `apply_enabled`).
    """
    optimizer = getattr(runtime, "chain_optimizer", None)
    if optimizer is None:
        raise HTTPException(status_code=503, detail="ChainOptimizer not enabled")
    if req.decision not in ("approve", "reject"):
        raise HTTPException(
            status_code=400,
            detail="decision must be 'approve' or 'reject'",
        )
    proposal = await optimizer.decide(proposal_id, req.decision, actor=req.actor)
    if proposal is None:
        raise HTTPException(
            status_code=404, detail=f"proposal {proposal_id} not found"
        )
    return {
        "status": "recorded",
        "applied": proposal.applied,
        "proposal": proposal.to_dict(),
    }


class ActorRequest(BaseModel):
    actor: str = "captain"


@router.post("/proposals/{proposal_id}/apply")
async def apply_proposal(
    proposal_id: str,
    req: ActorRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-659b: Apply an approved proposal to runtime.config.chain_tuning.

    Returns 503 if ChainOptimizer disabled, 403 if `apply_enabled=False`,
    400 if proposal not approved or target not apply-able, 404 if missing.
    """
    optimizer = getattr(runtime, "chain_optimizer", None)
    if optimizer is None:
        raise HTTPException(status_code=503, detail="ChainOptimizer not enabled")
    try:
        proposal = await optimizer.apply_proposal(proposal_id, actor=req.actor)
    except RuntimeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        msg = str(exc)
        status = 404 if "not found" in msg else 400
        raise HTTPException(status_code=status, detail=msg) from exc
    return {
        "status": "applied",
        "applied": True,
        "proposal": proposal.to_dict(),
    }


@router.post("/proposals/{proposal_id}/revert")
async def revert_proposal(
    proposal_id: str,
    req: ActorRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-659b: Manually revert an applied proposal to its `pre_apply_value`."""
    optimizer = getattr(runtime, "chain_optimizer", None)
    if optimizer is None:
        raise HTTPException(status_code=503, detail="ChainOptimizer not enabled")
    try:
        proposal = await optimizer.revert_proposal(proposal_id, actor=req.actor)
    except ValueError as exc:
        msg = str(exc)
        status = 404 if "not found" in msg else 400
        raise HTTPException(status_code=status, detail=msg) from exc
    return {
        "status": "reverted",
        "applied": False,
        "proposal": proposal.to_dict(),
    }
```

---

### Section 6 — Update existing AD-659 test (apply_proposal no longer raises NotImplementedError)

**File:** `tests/test_ad659_chain_self_optimization.py`

`SEARCH` block (around line 188-191):
```python
def test_chain_optimizer_apply_proposal_raises_not_implemented():
    opt = ChainOptimizer(SimpleNamespace())
    with pytest.raises(NotImplementedError, match="AD-659b"):
        opt.apply_proposal("anything")
```

`REPLACE`:
```python
@pytest.mark.asyncio
async def test_chain_optimizer_apply_proposal_disabled_raises_runtime_error():
    """AD-659b: apply_enabled=False → RuntimeError from apply_proposal."""
    opt = ChainOptimizer(SimpleNamespace(), apply_enabled=False)
    with pytest.raises(RuntimeError, match="apply_enabled=False"):
        await opt.apply_proposal("anything")
```

Also: the existing `test_chain_optimizer_analyze_aggregates_all_detectors` test calls `opt.decide(...)` synchronously. AD-659b makes `decide` async. Update the call site.

`SEARCH` block (around line 187 in the `analyze_aggregates_all_detectors` test):
```python
    # decide flips fields
    target = pending[0]
    decided = opt.decide(target.proposal_id, "approve", actor="captain")
    assert decided is not None
```

`REPLACE`:
```python
    # decide flips fields (AD-659b: now async + persists)
    target = pending[0]
    decided = await opt.decide(target.proposal_id, "approve", actor="captain")
    assert decided is not None
```

The router test (`test_chain_optimizer_router_list_and_decide_endpoints`) calls `client.post(...)` against the FastAPI endpoint which itself awaits — the router test stays correct as-is. Verify before commit.

---

### Section 7 — New test file `tests/test_ad659b_chain_optimizer_apply.py`

Create the file with the following test cases. Net delta: **+10 tests** (10 new in this file; 1 update + 1 minor edit in the AD-659 file are field-additive).

```python
"""AD-659b — ChainOptimizer apply path, persistence, dedup, revert, scheduled loop.

Tests:
  1. Persistence roundtrip — analyze persists, restart-equivalent fetch returns same set.
  2. Dedup — re-running analyze() over identical traces does NOT append duplicates.
  3. Apply happy path (low_trust_ceiling) — config mutated, fields populated.
  4. Apply happy path (high_trust_floor) — config mutated, fields populated.
  5. Apply on un-approved proposal → ValueError.
  6. Apply on already-applied proposal → ValueError.
  7. Apply on non-tunable target (chain_step.tier[X]) → ValueError mentioning AD-659b-1.
  8. Revert restores pre_apply_value and clears applied flag.
  9. Scheduled loop fires at least once when interval > 0 (test uses tiny interval).
 10. API: apply endpoint returns 403 when apply_enabled=False; 200 when enabled.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.cognitive.chain_optimizer import (
    ChainOptimizer,
    OptimizationProposal,
)
from probos.routers import chain_optimizer as router_module
from probos.routers.deps import get_runtime


# Shared fixture builder ----------------------------------------------------

def _make_journal_stub(traces):
    """Build a journal stub that supports record + dedup query + trace fetch.

    Stores recorded proposals in a list and serves get_pending_optimization_proposals
    by filtering it. This mimics the SQLite-backed CognitiveJournal surface enough
    for unit-level testing of ChainOptimizer dedup + persistence behavior.
    """
    stored: list[OptimizationProposal] = []

    async def record(proposal):
        # If proposal_id already in stored, REPLACE semantics
        for i, p in enumerate(stored):
            if p.proposal_id == proposal.proposal_id:
                stored[i] = proposal
                return
        stored.append(proposal)

    async def get_pending(*, detector_name=None, target_parameter=None):
        return [
            p.to_dict() for p in stored
            if p.decision is None
            and (detector_name is None or p.detector_name == detector_name)
            and (target_parameter is None or p.target_parameter == target_parameter)
        ]

    async def get_proposal(proposal_id):
        for p in stored:
            if p.proposal_id == proposal_id:
                return p.to_dict()
        return None

    return SimpleNamespace(
        get_recent_chain_traces=AsyncMock(return_value=traces),
        record_optimization_proposal=record,
        get_pending_optimization_proposals=get_pending,
        get_optimization_proposal=get_proposal,
    ), stored


def _trace(**overrides):
    base = dict(
        chain_id="c", step_index=0, step_name="comprehend",
        sub_task_type="comprehend", tier="standard",
        chain_source="user_request", agent_id="a", agent_type="t",
        intent="x", intent_id="i",
        started_at=0.0, duration_ms=500.0, tokens_used=0,
        success=1, error_truncated="",
        context_keys_declared="", context_keys_passed="",
        context_filter_applied=0, communication_context="formal",
        chain_trust_band="mid", trust_score=0.5,
        boot_camp_active=0, from_captain=0, is_dm=0,
    )
    base.update(overrides)
    return base


def _failing_low_band_traces(n=25):
    return [
        _trace(
            sub_task_type="evaluate", chain_trust_band="low",
            success=1 if i % 4 == 0 else 0,  # 25% success → below floor
        )
        for i in range(n)
    ]


def _make_runtime_with_config():
    """Build a runtime stub carrying a real ChainTuningConfig instance."""
    from probos.config import ChainTuningConfig
    config = SimpleNamespace(chain_tuning=ChainTuningConfig())
    return config


# 1. Persistence ---------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_persists_proposals_to_journal():
    journal, stored = _make_journal_stub(_failing_low_band_traces())
    runtime = SimpleNamespace(
        cognitive_journal=journal,
        config=_make_runtime_with_config(),
    )
    opt = ChainOptimizer(runtime, min_samples_per_group=20)
    new = await opt.analyze()
    assert len(new) >= 1
    assert len(stored) == len(new)
    assert {p.proposal_id for p in stored} == {p.proposal_id for p in new}


# 2. Dedup ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_dedups_on_detector_and_target():
    traces = _failing_low_band_traces()
    journal, stored = _make_journal_stub(traces)
    runtime = SimpleNamespace(
        cognitive_journal=journal,
        config=_make_runtime_with_config(),
    )
    opt = ChainOptimizer(runtime, min_samples_per_group=20)

    first = await opt.analyze()
    second = await opt.analyze()
    assert len(first) >= 1
    assert second == []  # all candidates deduplicated against pending entries
    # Pending list and journal should NOT have grown
    assert len(opt.pending_proposals) == len(first)
    assert len(stored) == len(first)


# 3 & 4. Apply happy path -----------------------------------------------

@pytest.mark.asyncio
async def test_apply_proposal_low_trust_ceiling():
    journal, _ = _make_journal_stub([])
    config = _make_runtime_with_config()
    runtime = SimpleNamespace(cognitive_journal=journal, config=config)
    opt = ChainOptimizer(runtime, apply_enabled=True)

    proposal = OptimizationProposal(
        target_parameter="chain_tuning.low_trust_ceiling",
        current_value=0.60, proposed_value=0.65,
        rationale="r", supporting_metric="m",
        risk_level="medium", detector_name="success_rate_floor_breach",
    )
    proposal.decision = "approve"
    proposal.decided_by = "captain"
    opt.pending_proposals.append(proposal)

    applied = await opt.apply_proposal(proposal.proposal_id, actor="captain")
    assert applied.applied is True
    assert applied.applied_by == "captain"
    assert applied.pre_apply_value == 0.60
    assert config.chain_tuning.low_trust_ceiling == 0.65


@pytest.mark.asyncio
async def test_apply_proposal_high_trust_floor():
    journal, _ = _make_journal_stub([])
    config = _make_runtime_with_config()
    runtime = SimpleNamespace(cognitive_journal=journal, config=config)
    opt = ChainOptimizer(runtime, apply_enabled=True)

    proposal = OptimizationProposal(
        target_parameter="chain_tuning.high_trust_floor",
        current_value=0.75, proposed_value=0.80,
        rationale="r", supporting_metric="m",
        risk_level="medium", detector_name="success_rate_floor_breach",
    )
    proposal.decision = "approve"
    opt.pending_proposals.append(proposal)
    applied = await opt.apply_proposal(proposal.proposal_id)
    assert applied.applied is True
    assert applied.pre_apply_value == 0.75
    assert config.chain_tuning.high_trust_floor == 0.80


# 5 & 6 & 7. Apply error paths ------------------------------------------

@pytest.mark.asyncio
async def test_apply_unapproved_raises():
    journal, _ = _make_journal_stub([])
    runtime = SimpleNamespace(cognitive_journal=journal,
                              config=_make_runtime_with_config())
    opt = ChainOptimizer(runtime, apply_enabled=True)
    proposal = OptimizationProposal(
        target_parameter="chain_tuning.low_trust_ceiling",
        current_value=0.60, proposed_value=0.65,
        rationale="r", supporting_metric="m",
        risk_level="medium", detector_name="success_rate_floor_breach",
    )
    opt.pending_proposals.append(proposal)
    with pytest.raises(ValueError, match="not approved"):
        await opt.apply_proposal(proposal.proposal_id)


@pytest.mark.asyncio
async def test_apply_already_applied_raises():
    journal, _ = _make_journal_stub([])
    runtime = SimpleNamespace(cognitive_journal=journal,
                              config=_make_runtime_with_config())
    opt = ChainOptimizer(runtime, apply_enabled=True)
    proposal = OptimizationProposal(
        target_parameter="chain_tuning.low_trust_ceiling",
        current_value=0.60, proposed_value=0.65,
        rationale="r", supporting_metric="m",
        risk_level="medium", detector_name="success_rate_floor_breach",
    )
    proposal.decision = "approve"
    opt.pending_proposals.append(proposal)
    await opt.apply_proposal(proposal.proposal_id)
    with pytest.raises(ValueError, match="already applied"):
        await opt.apply_proposal(proposal.proposal_id)


@pytest.mark.asyncio
async def test_apply_non_tunable_target_defers_to_ad659b1():
    journal, _ = _make_journal_stub([])
    runtime = SimpleNamespace(cognitive_journal=journal,
                              config=_make_runtime_with_config())
    opt = ChainOptimizer(runtime, apply_enabled=True)
    proposal = OptimizationProposal(
        target_parameter="chain_step.tier[evaluate]",
        current_value="standard", proposed_value="fast",
        rationale="r", supporting_metric="m",
        risk_level="medium", detector_name="latency_p95_regression",
    )
    proposal.decision = "approve"
    opt.pending_proposals.append(proposal)
    with pytest.raises(ValueError, match="AD-659b-1"):
        await opt.apply_proposal(proposal.proposal_id)


# 8. Revert ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_revert_restores_pre_apply_value():
    journal, _ = _make_journal_stub([])
    config = _make_runtime_with_config()
    runtime = SimpleNamespace(cognitive_journal=journal, config=config)
    opt = ChainOptimizer(runtime, apply_enabled=True)
    proposal = OptimizationProposal(
        target_parameter="chain_tuning.low_trust_ceiling",
        current_value=0.60, proposed_value=0.65,
        rationale="r", supporting_metric="m",
        risk_level="medium", detector_name="success_rate_floor_breach",
    )
    proposal.decision = "approve"
    opt.pending_proposals.append(proposal)
    await opt.apply_proposal(proposal.proposal_id)
    assert config.chain_tuning.low_trust_ceiling == 0.65
    reverted = await opt.revert_proposal(proposal.proposal_id)
    assert reverted.applied is False
    assert config.chain_tuning.low_trust_ceiling == 0.60


# 9. Scheduled loop -------------------------------------------------------

@pytest.mark.asyncio
async def test_scheduled_loop_fires_at_least_once():
    journal, stored = _make_journal_stub(_failing_low_band_traces())
    runtime = SimpleNamespace(
        cognitive_journal=journal,
        config=_make_runtime_with_config(),
    )
    opt = ChainOptimizer(
        runtime, min_samples_per_group=20,
        analysis_interval_seconds=1,
    )
    opt.start_scheduled_loop()
    # Wait long enough for one iteration to complete (analyze, then sleep 1s).
    await asyncio.sleep(0.2)
    await opt.stop()
    # At least one proposal should have been written by the loop.
    assert len(stored) >= 1


# 10. REST: apply endpoint -----------------------------------------------

def test_router_apply_endpoint_403_when_disabled_and_200_when_enabled():
    journal_disabled, _ = _make_journal_stub([])
    config = _make_runtime_with_config()
    runtime_disabled = SimpleNamespace(
        cognitive_journal=journal_disabled, config=config,
    )
    opt_disabled = ChainOptimizer(runtime_disabled, apply_enabled=False)
    proposal = OptimizationProposal(
        target_parameter="chain_tuning.low_trust_ceiling",
        current_value=0.60, proposed_value=0.65,
        rationale="r", supporting_metric="m",
        risk_level="medium", detector_name="success_rate_floor_breach",
    )
    proposal.decision = "approve"
    opt_disabled.pending_proposals.append(proposal)
    runtime_disabled.chain_optimizer = opt_disabled

    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[get_runtime] = lambda: runtime_disabled
    client = TestClient(app)
    r = client.post(
        f"/api/chain-optimizer/proposals/{proposal.proposal_id}/apply",
        json={"actor": "captain"},
    )
    assert r.status_code == 403
    assert "apply_enabled=False" in r.json()["detail"]

    # Now enable apply and rerun
    journal_enabled, _ = _make_journal_stub([])
    config2 = _make_runtime_with_config()
    runtime_enabled = SimpleNamespace(
        cognitive_journal=journal_enabled, config=config2,
    )
    opt_enabled = ChainOptimizer(runtime_enabled, apply_enabled=True)
    proposal2 = OptimizationProposal(
        target_parameter="chain_tuning.low_trust_ceiling",
        current_value=0.60, proposed_value=0.65,
        rationale="r", supporting_metric="m",
        risk_level="medium", detector_name="success_rate_floor_breach",
    )
    proposal2.decision = "approve"
    opt_enabled.pending_proposals.append(proposal2)
    runtime_enabled.chain_optimizer = opt_enabled

    app2 = FastAPI()
    app2.include_router(router_module.router)
    app2.dependency_overrides[get_runtime] = lambda: runtime_enabled
    client2 = TestClient(app2)
    r2 = client2.post(
        f"/api/chain-optimizer/proposals/{proposal2.proposal_id}/apply",
        json={"actor": "captain"},
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["applied"] is True
    assert body["proposal"]["applied"] is True
    assert config2.chain_tuning.low_trust_ceiling == 0.65
```

---

## Tracker updates (post-build, single commit per ask)

- `PROGRESS.md` — prepend AD-659b CLOSED entry.
- `docs/development/roadmap.md` — AD-659 status update, AD-659b sub-entry filled in.
- `DECISIONS.md` — prepend AD-659b entry.

## Issues to close

GitHub MCP `issue_write` close on **#409** (expect EMU 403 per Wave 31-51 pattern; Captain closes manually).

## Commit message

`AD-659b: ChainOptimizer apply path + persistence + dedup + revert + scheduled loop (+10 tests)`

---

## Acceptance Criteria

1. `pytest tests/test_ad659b_chain_optimizer_apply.py tests/test_ad659_chain_self_optimization.py -v -n 0` — all green.
2. Full gate `pytest tests/ -q -n 8 --dist=loadfile` — at least **+10 tests** vs Wave 51 baseline (11198 → ≥ 11208).
3. No new EventType added.
4. `ChainOptimizerConfig.apply_enabled` and `analysis_interval_seconds` both default `False`/`0`.
5. Apply on `chain_step.tier[X]` or `chain_source.review[X]` raises `ValueError` mentioning `AD-659b-1`.
6. SQLite schema `optimization_proposals` provisioned via `CREATE TABLE IF NOT EXISTS` (cold-boot and warm-boot safe).
7. `runtime.config.chain_tuning.low_trust_ceiling` / `high_trust_floor` are mutated in place by apply; `cognitive_agent.py:1909/1911/2097/2099` will read the new values on the next chain step (no further wiring needed).
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## What This Does NOT Change

- AD-658 chain-trace schema (no migration to `chain_traces`).
- AD-660 / AD-660b causal-reasoning schema or behavior.
- `cognitive_agent.py` chain construction (already reads `runtime.config.chain_tuning.*` live; AD-659b inherits that path).
- `ChainTuningConfig` shape (still 3 fields: `enabled`, `low_trust_ceiling`, `high_trust_floor`).
- The dedup window is "everything currently pending" — no time-based cap. A proposal that is decided (approve OR reject) no longer blocks new ones with the same key.
- Counselor wiring (deferred AD-659c).
- A/B testing framework (deferred AD-659b-1).
- Tier-shift apply path (deferred AD-659b-1).
- Chain-source-review apply path (deferred AD-659b-1).
- Automatic regression-driven revert (deferred AD-659c).
