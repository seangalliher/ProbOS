# AD-658a v1 — Chain Trace Token Input/Output Split

**Status:** ready
**Dependencies:** AD-658 (Wave 30, shipped — `ChainExecutionTrace` substrate), AD-431 (`LLMResponse.prompt_tokens` / `LLMResponse.completion_tokens` already populated), AD-660b (warm-boot ALTER TABLE migration precedent)
**Estimated tests:** 6 new (1 new test file `tests/test_ad658a_chain_trace_token_split.py`)
**Closes:** GH issue #408

---

## Problem

AD-658 (Wave 30) shipped `ChainExecutionTrace` with a single `tokens_used: int` field that conflates prompt-side and completion-side token counts. Downstream optimization (AD-659 detectors, AD-661 diagnostic context, AD-635 clinical telemetry) cannot distinguish between **expensive context assembly** (large prompt tokens, small completion) and **expensive generation** (small prompt, large completion) — the two failure modes warrant different remediations:

| Failure mode | Prompt-heavy remediation | Completion-heavy remediation |
|---|---|---|
| Prompt-side cost | trim context window, raise context-filter aggressiveness, drop low-trust prior_results | reduce `max_tokens`, switch to a higher-throughput tier, simplify the chain |

`LLMResponse` already exposes `prompt_tokens` and `completion_tokens` separately (AD-431, verified at `types.py:246-247`) but the split is **dropped at the SubTaskResult boundary** because the `SubTaskResult` dataclass collapses to a single `tokens_used`. The chain harness emit site (`sub_task.py:624`) then propagates only the collapsed value into `ChainExecutionTrace`, and the SQLite `chain_traces` table has no columns for the split.

This AD plumbs `prompt_tokens` / `completion_tokens` end-to-end:

```
LLMResponse  ───►  SubTaskResult  ───►  ChainExecutionTrace  ───►  chain_traces.{prompt_tokens,completion_tokens}
   (already)        (NEW fields)          (NEW fields)              (NEW columns + ALTER migration)
```

`tokens_used` is **preserved** as the sum (no consumer change). All downstream readers (`chain_optimizer` detectors, `diagnostic_context`, `clinical_telemetry`, `optimization_counselor`, `routers/chain_traces.py`) continue to function unchanged. New columns are exposed automatically through the existing `SELECT *` round-trip in `get_recent_chain_traces`.

## Solution

v1 ships a strictly additive producer-side split:

1. Add `prompt_tokens` / `completion_tokens` fields to `SubTaskResult` (frozen dataclass — append after `tier_used`, both default `0`).
2. Add `prompt_tokens` / `completion_tokens` fields to `ChainExecutionTrace` (frozen dataclass — append after `tokens_used`, both default `0`).
3. Extend `_SCHEMA_CHAIN_TRACES` with two new columns (default 0). Add an idempotent `ALTER TABLE` migration tuple for warm-boot DBs (precedent: AD-660b at journal.py:111-114).
4. Update `journal.record_chain_trace` INSERT to bind the new columns. `get_recent_chain_traces` is unchanged (its `SELECT *` + `dict(row)` projection automatically picks up the new columns).
5. Update the chain harness emit site at `sub_task.py:624` to forward `prompt_tokens` / `completion_tokens` from the producing `SubTaskResult`.
6. Update the 5 success-path `SubTaskResult(...)` construction sites in `sub_tasks/{analyze,compose,evaluate,reflect}.py` to populate the split from `LLMResponse.prompt_tokens` / `LLMResponse.completion_tokens`. Short-circuit / error / no-LLM paths remain at the dataclass default (`0` / `0`) and are NOT edited.

`tokens_used` is preserved everywhere as the sum and remains the canonical token counter for backwards compatibility — every existing consumer (8 production sites + 7 test sites verified) reads only `tokens_used` and continues to work.

### Scope

| Component | Status |
|---|---|
| `SubTaskResult.prompt_tokens` / `.completion_tokens` (frozen-dataclass fields, default `0`) | NEW |
| `ChainExecutionTrace.prompt_tokens` / `.completion_tokens` (frozen-dataclass fields, default `0`) | NEW |
| `_SCHEMA_CHAIN_TRACES` adds `prompt_tokens INTEGER NOT NULL DEFAULT 0` and `completion_tokens INTEGER NOT NULL DEFAULT 0` | EDIT |
| `_MIGRATIONS_CHAIN_TRACES_AD658A` tuple — 2 idempotent `ALTER TABLE ADD COLUMN` statements | NEW |
| `journal.start()` runs the new migrations (try/except `sqlite3.OperationalError`) | EDIT |
| `journal.record_chain_trace` INSERT binds the new columns | EDIT |
| `sub_task.py:624` chain trace emission forwards `prompt_tokens` / `completion_tokens` from `SubTaskResult` | EDIT |
| 5 handler success-path constructions in `analyze.py:600`, `compose.py:668`, `evaluate.py:670` (parse-fail-pass-by-default) + `evaluate.py:720` (success), `reflect.py:574` | EDIT |
| 6 new tests in `tests/test_ad658a_chain_trace_token_split.py` | NEW |

### Out of scope (legitimate boundaries — DO NOT BUILD)

- **Cached-response token attribution.** `LLMClient.complete()` cache hits restore only `tokens_used=cached.tokens_used` (verified at `llm_client.py:464,629` — `prompt_tokens` / `completion_tokens` are NOT cached). Cached chain steps will record `prompt_tokens=0, completion_tokens=0, tokens_used=N`. v1 accepts this — cache-hit token attribution is AD-658a-1 (forcing function: AD-658a v1 ships and Captain reviews split-field accuracy in production; cache hit ratio metrics will surface the gap).
- **`LLMResponse` schema changes.** Already has the fields (AD-431). No edit.
- **`ChainOptimizer` detector for completion-token regressions.** v1 plumbs the data only. New detectors are AD-658a-2 (forcing function: AD-658a v1 ships, Captain validates that prompt/completion split correlates with optimizer-relevant patterns; only then does a detector make sense).
- **HXI surface for prompt vs completion breakdown.** AD-658a-3.
- **Captain-facing `/api/chain-traces` filter / aggregation by token-split fields.** v1 exposes the columns via the existing `SELECT *` round-trip; no new query parameters. Aggregation surface is AD-658a-3.
- **`builder.py` BlueprintResult `tokens_used`** (verified at `builder.py:797,1176,1183`) — orthogonal subsystem (build pipeline, not chain harness). Not touched.
- **`CognitiveJournal.record()` `total_tokens`** (per-LLM-call journal table, not chain_traces). Not touched.
- **Pydantic config flag.** Token split is unconditional plumbing — no opt-in needed. Adds <0.1% to per-step trace overhead (two integer columns).
- **No new EventType. No new pool, agent, or module.**

---

## Verified Against Codebase (HEAD post-Wave-53, `6cbb0ac`, 2026-05-05)

| Symbol | Path | Line | Verifying line |
|---|---|---|---|
| `LLMResponse.prompt_tokens` | `types.py` | 246 | `prompt_tokens: int = 0       # AD-431: separate prompt token count` |
| `LLMResponse.completion_tokens` | `types.py` | 247 | `completion_tokens: int = 0   # AD-431: separate completion token count` |
| `LLMResponse.tokens_used` | `types.py` | 245 | `tokens_used: int = 0` |
| `SubTaskResult` frozen dataclass | `cognitive/sub_task.py` | 56 | `class SubTaskResult:` |
| `SubTaskResult.tokens_used` (last numeric field; insertion-anchor sibling) | `cognitive/sub_task.py` | 61 | `tokens_used: int = 0                # Prompt + completion tokens` |
| `SubTaskResult.tier_used` (last field — append point) | `cognitive/sub_task.py` | 64 | `tier_used: str = ""                 # Actual LLM tier used` |
| `ChainExecutionTrace` frozen dataclass | `cognitive/chain_trace.py` | 14 | `class ChainExecutionTrace:` |
| `ChainExecutionTrace.tokens_used` (insertion-anchor sibling) | `cognitive/chain_trace.py` | 35 | `tokens_used: int = 0` |
| `_SCHEMA_CHAIN_TRACES` table block | `cognitive/journal.py` | 56-89 | `_SCHEMA_CHAIN_TRACES = """` ... |
| `_MIGRATIONS_CAUSAL_TEMPLATES_AD660B` tuple (insertion-anchor sibling) | `cognitive/journal.py` | 111-114 | `_MIGRATIONS_CAUSAL_TEMPLATES_AD660B = (...)` |
| `journal.start()` AD-658 schema execution | `cognitive/journal.py` | 205 | `await self._db.executescript(_SCHEMA_CHAIN_TRACES)` |
| `journal.start()` AD-660b migration loop (precedent for the new try/except pattern) | `cognitive/journal.py` | 209-213 | `for stmt in _MIGRATIONS_CAUSAL_TEMPLATES_AD660B:` |
| `journal.record_chain_trace` INSERT site | `cognitive/journal.py` | 366-403 | `async def record_chain_trace(self, trace: Any) -> None:` |
| `journal.record_chain_trace` 24-column INSERT statement (current shape) | `cognitive/journal.py` | 377-385 | `INSERT OR IGNORE INTO chain_traces ...` |
| `journal.record_chain_trace` value tuple (current shape) | `cognitive/journal.py` | 386-400 | `trace.chain_id, trace.step_index, ...` |
| `journal.get_recent_chain_traces` (unchanged — `SELECT *` round-trips new columns automatically) | `cognitive/journal.py` | 404-437 | `async def get_recent_chain_traces(...)` |
| `sub_task.py` chain trace emit site (line 624 area) | `cognitive/sub_task.py` | 612-643 | `from probos.cognitive.chain_trace import ChainExecutionTrace` ... `trace = ChainExecutionTrace(...)` |
| `sub_tasks/analyze.py` success path | `cognitive/sub_tasks/analyze.py` | 600-608 | `return SubTaskResult(...)` with `tokens_used=response.tokens_used` |
| `sub_tasks/analyze.py` parse-fail return | `cognitive/sub_tasks/analyze.py` | 569-580 | `return SubTaskResult(...)` with `tokens_used=response.tokens_used` |
| `sub_tasks/compose.py` success path | `cognitive/sub_tasks/compose.py` | 668-674 | `return SubTaskResult(...)` with `tokens_used=response.tokens_used` |
| `sub_tasks/evaluate.py` parse-fail-pass-by-default | `cognitive/sub_tasks/evaluate.py` | 668-678 | `return SubTaskResult(...)` with `tokens_used=getattr(response, "tokens_used", 0)` |
| `sub_tasks/evaluate.py` success path | `cognitive/sub_tasks/evaluate.py` | 718-726 | `return SubTaskResult(...)` with `tokens_used=getattr(response, "tokens_used", 0)` |
| `sub_tasks/reflect.py` success path | `cognitive/sub_tasks/reflect.py` | 574-582 | `return SubTaskResult(...)` with `tokens_used=getattr(response, "tokens_used", 0)` |
| `chain_optimizer.py` reads only `tokens_used` (no consumer breakage) | `cognitive/chain_optimizer.py` | 264 | `traces = await journal.get_recent_chain_traces(limit=n)` |
| `routers/chain_traces.py` `SELECT *` round-trip (new columns auto-exposed) | `routers/chain_traces.py` | 33-37 | `traces = await runtime.cognitive_journal.get_recent_chain_traces(...)` |

`prompt_tokens` and `completion_tokens` on `SubTaskResult` and `ChainExecutionTrace`, `prompt_tokens` and `completion_tokens` columns in `chain_traces` table, `_MIGRATIONS_CHAIN_TRACES_AD658A` tuple — all greenfield, verified zero hits at HEAD `6cbb0ac`.

---

## Implementation

### Section 1 — `SubTaskResult` adds split fields

**File:** `src/probos/cognitive/sub_task.py`

`SEARCH` block (lines 55-65, the full `SubTaskResult` body):
```python
@dataclass(frozen=True)
class SubTaskResult:
    """Output of a single sub-task execution."""
    sub_task_type: SubTaskType
    name: str
    result: dict = field(default_factory=dict)  # Structured output (handler-specific)
    tokens_used: int = 0                # Prompt + completion tokens
    duration_ms: float = 0.0            # Wall clock time
    success: bool = True
    error: str = ""                     # Empty if success, error message if not
    tier_used: str = ""                 # Actual LLM tier used
```

`REPLACE`:
```python
@dataclass(frozen=True)
class SubTaskResult:
    """Output of a single sub-task execution."""
    sub_task_type: SubTaskType
    name: str
    result: dict = field(default_factory=dict)  # Structured output (handler-specific)
    tokens_used: int = 0                # Prompt + completion tokens (sum; backwards-compat)
    duration_ms: float = 0.0            # Wall clock time
    success: bool = True
    error: str = ""                     # Empty if success, error message if not
    tier_used: str = ""                 # Actual LLM tier used
    prompt_tokens: int = 0              # AD-658a: prompt-side token count
    completion_tokens: int = 0          # AD-658a: completion-side token count
```

---

### Section 2 — `ChainExecutionTrace` adds split fields

**File:** `src/probos/cognitive/chain_trace.py`

`SEARCH` block (the wall-clock + execution block, around line 33-38):
```python
    # Wall-clock + execution
    started_at: float = 0.0
    duration_ms: float = 0.0
    tokens_used: int = 0
    success: bool = True
    error_truncated: str = ""
```

`REPLACE`:
```python
    # Wall-clock + execution
    started_at: float = 0.0
    duration_ms: float = 0.0
    tokens_used: int = 0                # AD-658: prompt + completion (sum)
    prompt_tokens: int = 0              # AD-658a: prompt-side token count
    completion_tokens: int = 0          # AD-658a: completion-side token count
    success: bool = True
    error_truncated: str = ""
```

---

### Section 3 — `_SCHEMA_CHAIN_TRACES` adds two columns + warm-boot migration tuple

**File:** `src/probos/cognitive/journal.py`

#### Section 3a — Schema column addition

`SEARCH` block (the `tokens_used` column line in `_SCHEMA_CHAIN_TRACES`, around lines 70-72):
```python
    started_at          REAL NOT NULL DEFAULT 0.0,
    duration_ms         REAL NOT NULL DEFAULT 0.0,
    tokens_used         INTEGER NOT NULL DEFAULT 0,
    success             INTEGER NOT NULL DEFAULT 1,
    error_truncated     TEXT NOT NULL DEFAULT '',
```

`REPLACE`:
```python
    started_at          REAL NOT NULL DEFAULT 0.0,
    duration_ms         REAL NOT NULL DEFAULT 0.0,
    tokens_used         INTEGER NOT NULL DEFAULT 0,
    prompt_tokens       INTEGER NOT NULL DEFAULT 0,
    completion_tokens   INTEGER NOT NULL DEFAULT 0,
    success             INTEGER NOT NULL DEFAULT 1,
    error_truncated     TEXT NOT NULL DEFAULT '',
```

#### Section 3b — Warm-boot migration tuple (insert immediately after `_MIGRATIONS_CAUSAL_TEMPLATES_AD660B`)

`SEARCH` block (the AD-660b migration tuple, around lines 110-114):
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

# AD-658a: idempotent migration for warm-boot DBs created under AD-658 v1.
_MIGRATIONS_CHAIN_TRACES_AD658A = (
    "ALTER TABLE chain_traces ADD COLUMN prompt_tokens INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE chain_traces ADD COLUMN completion_tokens INTEGER NOT NULL DEFAULT 0",
)
```

#### Section 3c — `journal.start()` runs the new migrations

`SEARCH` block (the existing AD-660b migration loop + AD-659b CREATE block, around lines 207-216):
```python
        # AD-660b: idempotent ALTER TABLE for warm-boot DBs that pre-date AD-660b.
        for stmt in _MIGRATIONS_CAUSAL_TEMPLATES_AD660B:
            try:
                await self._db.execute(stmt)
            except Exception:
                pass
        # AD-659b: ChainOptimizer proposal persistence (idempotent CREATE).
        await self._db.executescript(_SCHEMA_OPTIMIZATION_PROPOSALS)
        # AD-659c: OptimizationCounselor watchdog decisions (idempotent CREATE).
        await self._db.executescript(_SCHEMA_OPTIMIZATION_DECISIONS)
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
        # AD-658a: idempotent ALTER TABLE for warm-boot DBs that pre-date AD-658a.
        for stmt in _MIGRATIONS_CHAIN_TRACES_AD658A:
            try:
                await self._db.execute(stmt)
            except Exception:
                pass
        # AD-659b: ChainOptimizer proposal persistence (idempotent CREATE).
        await self._db.executescript(_SCHEMA_OPTIMIZATION_PROPOSALS)
        # AD-659c: OptimizationCounselor watchdog decisions (idempotent CREATE).
        await self._db.executescript(_SCHEMA_OPTIMIZATION_DECISIONS)
        await self._db.commit()
```

---

### Section 4 — `journal.record_chain_trace` INSERT binds new columns

**File:** `src/probos/cognitive/journal.py`

`SEARCH` block (the full INSERT statement + value tuple in `record_chain_trace`, around lines 376-401):
```python
            await self._db.execute(
                """INSERT OR IGNORE INTO chain_traces
                   (chain_id, step_index, step_name, sub_task_type, tier,
                    chain_source, agent_id, agent_type, intent, intent_id,
                    started_at, duration_ms, tokens_used, success, error_truncated,
                    context_keys_declared, context_keys_passed, context_filter_applied,
                    communication_context, chain_trust_band, trust_score,
                    boot_camp_active, from_captain, is_dm)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trace.chain_id, trace.step_index, trace.step_name,
                    trace.sub_task_type, trace.tier, trace.chain_source,
                    trace.agent_id, trace.agent_type, trace.intent, trace.intent_id,
                    trace.started_at, trace.duration_ms, trace.tokens_used,
                    1 if trace.success else 0, trace.error_truncated,
                    trace.context_keys_declared, trace.context_keys_passed,
                    1 if trace.context_filter_applied else 0,
                    trace.communication_context, trace.chain_trust_band,
                    trace.trust_score,
                    1 if trace.boot_camp_active else 0,
                    1 if trace.from_captain else 0,
                    1 if trace.is_dm else 0,
                ),
            )
```

`REPLACE`:
```python
            await self._db.execute(
                """INSERT OR IGNORE INTO chain_traces
                   (chain_id, step_index, step_name, sub_task_type, tier,
                    chain_source, agent_id, agent_type, intent, intent_id,
                    started_at, duration_ms, tokens_used,
                    prompt_tokens, completion_tokens,
                    success, error_truncated,
                    context_keys_declared, context_keys_passed, context_filter_applied,
                    communication_context, chain_trust_band, trust_score,
                    boot_camp_active, from_captain, is_dm)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trace.chain_id, trace.step_index, trace.step_name,
                    trace.sub_task_type, trace.tier, trace.chain_source,
                    trace.agent_id, trace.agent_type, trace.intent, trace.intent_id,
                    trace.started_at, trace.duration_ms, trace.tokens_used,
                    # AD-658a: defensive getattr — tolerates pre-AD-658a trace objects
                    # produced by external test fixtures or stub journals.
                    getattr(trace, "prompt_tokens", 0),
                    getattr(trace, "completion_tokens", 0),
                    1 if trace.success else 0, trace.error_truncated,
                    trace.context_keys_declared, trace.context_keys_passed,
                    1 if trace.context_filter_applied else 0,
                    trace.communication_context, trace.chain_trust_band,
                    trace.trust_score,
                    1 if trace.boot_camp_active else 0,
                    1 if trace.from_captain else 0,
                    1 if trace.is_dm else 0,
                ),
            )
```

> **Column count audit:** old INSERT = 24 columns + 24 placeholders. New INSERT = 26 columns + 26 placeholders (two new). Counts must match before commit.

---

### Section 5 — Chain harness emit site forwards split

**File:** `src/probos/cognitive/sub_task.py`

`SEARCH` block (the `ChainExecutionTrace(...)` construction, around lines 612-642):
```python
                trace = ChainExecutionTrace(
                    chain_id=chain_id,
                    step_index=step_index,
                    step_name=spec.name,
                    sub_task_type=spec.sub_task_type.value,
                    tier=result.tier_used or spec.tier,
                    chain_source=chain_source,
                    agent_id=agent_id,
                    agent_type=agent_type,
                    intent=intent,
                    intent_id=intent_id,
                    started_at=step_started_at,
                    duration_ms=result.duration_ms,
                    tokens_used=result.tokens_used,
                    success=result.success,
                    error_truncated=(result.error or "")[:200],
                    context_keys_declared=len(spec.context_keys),
                    context_keys_passed=len(step_context),
                    context_filter_applied=bool(
                        spec.context_keys
                        and spec.sub_task_type != SubTaskType.QUERY
                    ),
                    communication_context=context.get("_communication_context"),
                    chain_trust_band=context.get("_chain_trust_band"),
                    trust_score=context.get("_trust_score"),
                    boot_camp_active=bool(context.get("_boot_camp_active")),
                    from_captain=bool(context.get("_from_captain")),
                    is_dm=bool(context.get("_is_dm")),
                )
```

`REPLACE`:
```python
                trace = ChainExecutionTrace(
                    chain_id=chain_id,
                    step_index=step_index,
                    step_name=spec.name,
                    sub_task_type=spec.sub_task_type.value,
                    tier=result.tier_used or spec.tier,
                    chain_source=chain_source,
                    agent_id=agent_id,
                    agent_type=agent_type,
                    intent=intent,
                    intent_id=intent_id,
                    started_at=step_started_at,
                    duration_ms=result.duration_ms,
                    tokens_used=result.tokens_used,
                    # AD-658a: forward prompt/completion split from SubTaskResult.
                    # Defensive getattr tolerates SubTaskResult instances built
                    # by older external fixtures that pre-date the field add.
                    prompt_tokens=getattr(result, "prompt_tokens", 0),
                    completion_tokens=getattr(result, "completion_tokens", 0),
                    success=result.success,
                    error_truncated=(result.error or "")[:200],
                    context_keys_declared=len(spec.context_keys),
                    context_keys_passed=len(step_context),
                    context_filter_applied=bool(
                        spec.context_keys
                        and spec.sub_task_type != SubTaskType.QUERY
                    ),
                    communication_context=context.get("_communication_context"),
                    chain_trust_band=context.get("_chain_trust_band"),
                    trust_score=context.get("_trust_score"),
                    boot_camp_active=bool(context.get("_boot_camp_active")),
                    from_captain=bool(context.get("_from_captain")),
                    is_dm=bool(context.get("_is_dm")),
                )
```

---

### Section 6 — Sub-task handler success-path constructions populate split

> **Pattern:** every site that already passes `tokens_used=response.tokens_used` (or `getattr(response, "tokens_used", 0)`) gains `prompt_tokens=` and `completion_tokens=` keyword args sourced from the same `response` object using the SAME defensive style as the existing `tokens_used` line in that handler. Sites that hard-code `tokens_used=0` (short-circuits, error paths, no-LLM paths) are NOT edited — the new fields default to `0` on `SubTaskResult` and the omission is correct.

#### Section 6a — `analyze.py` JSON-parse-failure return

**File:** `src/probos/cognitive/sub_tasks/analyze.py`

`SEARCH` block (around lines 569-580):
```python
            return SubTaskResult(
                sub_task_type=SubTaskType.ANALYZE,
                name=spec.name,
                result={},
                tokens_used=response.tokens_used,
                duration_ms=duration,
                success=False,
                error=f"Failed to parse analysis JSON from LLM response: {truncated}",
                tier_used=response.tier,
            )
```

`REPLACE`:
```python
            return SubTaskResult(
                sub_task_type=SubTaskType.ANALYZE,
                name=spec.name,
                result={},
                tokens_used=response.tokens_used,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                duration_ms=duration,
                success=False,
                error=f"Failed to parse analysis JSON from LLM response: {truncated}",
                tier_used=response.tier,
            )
```

#### Section 6b — `analyze.py` success path

`SEARCH` block (around lines 600-608):
```python
        duration = (time.monotonic() - start) * 1000
        return SubTaskResult(
            sub_task_type=SubTaskType.ANALYZE,
            name=spec.name,
            result=analysis,
            tokens_used=response.tokens_used,
            duration_ms=duration,
            success=True,
            tier_used=response.tier,
        )
```

`REPLACE`:
```python
        duration = (time.monotonic() - start) * 1000
        return SubTaskResult(
            sub_task_type=SubTaskType.ANALYZE,
            name=spec.name,
            result=analysis,
            tokens_used=response.tokens_used,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            duration_ms=duration,
            success=True,
            tier_used=response.tier,
        )
```

#### Section 6c — `compose.py` success path

**File:** `src/probos/cognitive/sub_tasks/compose.py`

`SEARCH` block (around lines 668-675 — the final composed-output return; verified at HEAD):
```python
        # Return composed output
        duration = (time.monotonic() - start) * 1000
        return SubTaskResult(
            sub_task_type=SubTaskType.COMPOSE,
            name=spec.name,
            result={"output": response.content or ""},
            tokens_used=response.tokens_used,
            duration_ms=duration,
            success=True,
            tier_used=response.tier,
        )
```

`REPLACE`:
```python
        # Return composed output
        duration = (time.monotonic() - start) * 1000
        return SubTaskResult(
            sub_task_type=SubTaskType.COMPOSE,
            name=spec.name,
            result={"output": response.content or ""},
            tokens_used=response.tokens_used,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            duration_ms=duration,
            success=True,
            tier_used=response.tier,
        )
```

#### Section 6d — `evaluate.py` parse-fail-pass-by-default

**File:** `src/probos/cognitive/sub_tasks/evaluate.py`

`SEARCH` block (around lines 668-678):
```python
            return SubTaskResult(
                sub_task_type=SubTaskType.EVALUATE,
                name=spec.name,
                result=dict(_PASS_BY_DEFAULT),
                tokens_used=getattr(response, "tokens_used", 0),
                duration_ms=duration,
                success=True,
                tier_used=getattr(response, "tier", ""),
            )
```

`REPLACE`:
```python
            return SubTaskResult(
                sub_task_type=SubTaskType.EVALUATE,
                name=spec.name,
                result=dict(_PASS_BY_DEFAULT),
                tokens_used=getattr(response, "tokens_used", 0),
                prompt_tokens=getattr(response, "prompt_tokens", 0),
                completion_tokens=getattr(response, "completion_tokens", 0),
                duration_ms=duration,
                success=True,
                tier_used=getattr(response, "tier", ""),
            )
```

#### Section 6e — `evaluate.py` success path

> **NOTE FOR BUILDER:** the verified line for the success-path `tokens_used=` is `evaluate.py:724`. The surrounding `SubTaskResult(...)` block builds the final structured verdict (`pass`/`score`/`criteria`/`recommendation`). If two distinct success-path returns both use `tokens_used=getattr(response, "tokens_used", 0)`, edit the one that does NOT match the parse-fail-pass-by-default block from Section 6d (which uses `result=dict(_PASS_BY_DEFAULT)`). Hard-stop only if the verified line moved more than ±10 lines.

`SEARCH` block (around lines 718-726 — the final structured-verdict return):
```python
        return SubTaskResult(
            sub_task_type=SubTaskType.EVALUATE,
            name=spec.name,
            result=result,
            tokens_used=getattr(response, "tokens_used", 0),
            duration_ms=duration,
            success=True,
            tier_used=getattr(response, "tier", ""),
        )
```

`REPLACE`:
```python
        return SubTaskResult(
            sub_task_type=SubTaskType.EVALUATE,
            name=spec.name,
            result=result,
            tokens_used=getattr(response, "tokens_used", 0),
            prompt_tokens=getattr(response, "prompt_tokens", 0),
            completion_tokens=getattr(response, "completion_tokens", 0),
            duration_ms=duration,
            success=True,
            tier_used=getattr(response, "tier", ""),
        )
```

#### Section 6f — `reflect.py` success path

**File:** `src/probos/cognitive/sub_tasks/reflect.py`

`SEARCH` block (around lines 574-582):
```python
        return SubTaskResult(
            sub_task_type=SubTaskType.REFLECT,
            name=spec.name,
            result=result,
            tokens_used=getattr(response, "tokens_used", 0),
            duration_ms=duration,
            success=True,
            tier_used=getattr(response, "tier", ""),
        )
```

`REPLACE`:
```python
        return SubTaskResult(
            sub_task_type=SubTaskType.REFLECT,
            name=spec.name,
            result=result,
            tokens_used=getattr(response, "tokens_used", 0),
            prompt_tokens=getattr(response, "prompt_tokens", 0),
            completion_tokens=getattr(response, "completion_tokens", 0),
            duration_ms=duration,
            success=True,
            tier_used=getattr(response, "tier", ""),
        )
```

---

### Section 7 — Tests

**File:** `tests/test_ad658a_chain_trace_token_split.py` (NEW — full file content):

```python
"""AD-658a: Chain trace token I/O split — tests."""

from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from probos.cognitive.chain_trace import ChainExecutionTrace
from probos.cognitive.journal import CognitiveJournal
from probos.cognitive.sub_task import SubTaskResult, SubTaskType


# ---------------------------------------------------------------------------
# Section 1 — Frozen-dataclass field additions
# ---------------------------------------------------------------------------

def test_sub_task_result_token_split_defaults_zero() -> None:
    """AD-658a: SubTaskResult adds prompt_tokens / completion_tokens (default 0)."""
    r = SubTaskResult(sub_task_type=SubTaskType.ANALYZE, name="x")
    assert r.prompt_tokens == 0
    assert r.completion_tokens == 0
    # tokens_used remains the canonical sum-style field
    assert r.tokens_used == 0
    # frozen contract preserved
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.prompt_tokens = 10  # type: ignore[misc]


def test_chain_execution_trace_token_split_defaults_and_round_trip() -> None:
    """AD-658a: ChainExecutionTrace exposes the split + to_dict round-trip."""
    trace = ChainExecutionTrace(
        chain_id="c", step_index=0, step_name="x",
        sub_task_type="analyze", tier="standard",
        tokens_used=128, prompt_tokens=80, completion_tokens=48,
    )
    assert trace.prompt_tokens == 80
    assert trace.completion_tokens == 48
    assert trace.tokens_used == 128
    d = trace.to_dict()
    assert d["prompt_tokens"] == 80
    assert d["completion_tokens"] == 48
    assert d["tokens_used"] == 128
    # Defaults preserved when omitted
    bare = ChainExecutionTrace(
        chain_id="c", step_index=0, step_name="x",
        sub_task_type="analyze", tier="standard",
    )
    assert bare.prompt_tokens == 0
    assert bare.completion_tokens == 0
    # Round-trip from dict
    again = ChainExecutionTrace(**d)
    assert again == trace


# ---------------------------------------------------------------------------
# Section 2 — Journal record + read round-trip with split
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_journal_record_chain_trace_persists_token_split(tmp_path) -> None:
    """AD-658a: record_chain_trace binds prompt_tokens / completion_tokens
    and get_recent_chain_traces returns them via SELECT * round-trip."""
    db_path = str(tmp_path / "j.db")
    journal = CognitiveJournal(db_path=db_path)
    await journal.start()
    try:
        trace = ChainExecutionTrace(
            chain_id="abc", step_index=0, step_name="analyze",
            sub_task_type="analyze", tier="fast",
            tokens_used=128, prompt_tokens=80, completion_tokens=48,
            success=True, started_at=10.0,
        )
        await journal.record_chain_trace(trace)
        rows = await journal.get_recent_chain_traces(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["tokens_used"] == 128
        assert row["prompt_tokens"] == 80
        assert row["completion_tokens"] == 48
    finally:
        await journal.stop()


# ---------------------------------------------------------------------------
# Section 3 — Warm-boot ALTER TABLE migration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_journal_warm_boot_adds_split_columns_for_pre_ad658a_db(tmp_path) -> None:
    """AD-658a: warm-boot DB created without the new columns is migrated
    by journal.start() via idempotent ALTER TABLE; subsequent INSERT of a
    trace with prompt_tokens / completion_tokens succeeds."""
    db_path = str(tmp_path / "warm.db")

    # 1. Create a pre-AD-658a chain_traces table — same shape as AD-658
    #    minus the two new columns.
    pre_ad658a_schema = """
    CREATE TABLE chain_traces (
        chain_id            TEXT NOT NULL,
        step_index          INTEGER NOT NULL,
        step_name           TEXT NOT NULL,
        sub_task_type       TEXT NOT NULL,
        tier                TEXT NOT NULL DEFAULT 'standard',
        chain_source        TEXT NOT NULL DEFAULT '',
        agent_id            TEXT NOT NULL DEFAULT '',
        agent_type          TEXT NOT NULL DEFAULT '',
        intent              TEXT NOT NULL DEFAULT '',
        intent_id           TEXT NOT NULL DEFAULT '',
        started_at          REAL NOT NULL DEFAULT 0.0,
        duration_ms         REAL NOT NULL DEFAULT 0.0,
        tokens_used         INTEGER NOT NULL DEFAULT 0,
        success             INTEGER NOT NULL DEFAULT 1,
        error_truncated     TEXT NOT NULL DEFAULT '',
        context_keys_declared INTEGER NOT NULL DEFAULT 0,
        context_keys_passed   INTEGER NOT NULL DEFAULT 0,
        context_filter_applied INTEGER NOT NULL DEFAULT 0,
        communication_context TEXT,
        chain_trust_band      TEXT,
        trust_score           REAL,
        boot_camp_active      INTEGER NOT NULL DEFAULT 0,
        from_captain          INTEGER NOT NULL DEFAULT 0,
        is_dm                 INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (chain_id, step_index)
    );
    """
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(pre_ad658a_schema)
        await conn.commit()

    # 2. Boot the journal — start() must idempotently add the split columns.
    journal = CognitiveJournal(db_path=db_path)
    await journal.start()
    try:
        # 3. Verify the columns now exist via PRAGMA table_info.
        async with aiosqlite.connect(db_path) as conn:
            cursor = await conn.execute("PRAGMA table_info(chain_traces)")
            cols = {row[1] for row in await cursor.fetchall()}
        assert "prompt_tokens" in cols
        assert "completion_tokens" in cols

        # 4. INSERT a trace with the split fields populated.
        trace = ChainExecutionTrace(
            chain_id="warm", step_index=0, step_name="x",
            sub_task_type="analyze", tier="standard",
            tokens_used=10, prompt_tokens=7, completion_tokens=3,
        )
        await journal.record_chain_trace(trace)
        rows = await journal.get_recent_chain_traces()
        assert len(rows) == 1
        assert rows[0]["prompt_tokens"] == 7
        assert rows[0]["completion_tokens"] == 3
        assert rows[0]["tokens_used"] == 10
    finally:
        await journal.stop()


@pytest.mark.asyncio
async def test_journal_warm_boot_migration_is_idempotent(tmp_path) -> None:
    """AD-658a: starting twice on the same DB does not raise — ALTER TABLE
    is wrapped in try/except OperationalError per the AD-660b precedent."""
    db_path = str(tmp_path / "twice.db")
    j1 = CognitiveJournal(db_path=db_path)
    await j1.start()
    await j1.stop()
    # Second boot must succeed even though the columns already exist.
    j2 = CognitiveJournal(db_path=db_path)
    await j2.start()
    try:
        async with aiosqlite.connect(db_path) as conn:
            cursor = await conn.execute("PRAGMA table_info(chain_traces)")
            cols = {row[1] for row in await cursor.fetchall()}
        assert "prompt_tokens" in cols
        assert "completion_tokens" in cols
    finally:
        await j2.stop()


# ---------------------------------------------------------------------------
# Section 4 — Executor emit-site forwards split from SubTaskResult
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_executor_chain_trace_emission_forwards_token_split() -> None:
    """AD-658a: when a SubTask handler returns a SubTaskResult populated with
    prompt_tokens / completion_tokens, the chain harness emits a
    ChainExecutionTrace carrying the same split. Mirrors the AD-658 executor
    emission test pattern (MagicMock journal; assert on awaited trace object)."""
    from probos.cognitive.sub_task import (
        SubTaskChain,
        SubTaskExecutor,
        SubTaskSpec,
    )

    async def handler(spec, ctx, prior):
        return SubTaskResult(
            sub_task_type=spec.sub_task_type, name=spec.name,
            tokens_used=200, prompt_tokens=140, completion_tokens=60,
            duration_ms=12.0, success=True, tier_used="standard",
        )

    executor = SubTaskExecutor()
    executor.register_handler(SubTaskType.ANALYZE, handler)
    chain = SubTaskChain(
        steps=[SubTaskSpec(
            sub_task_type=SubTaskType.ANALYZE,
            name="step-0", prompt_template="t",
            context_keys=("query",),
        )],
        source="skill",
    )
    journal = MagicMock()
    journal.record = AsyncMock()
    journal.record_chain_trace = AsyncMock()

    await executor.execute(
        chain, {"query": "X"},
        agent_id="agent-1", agent_type="counselor",
        intent="reply", intent_id="int-9",
        journal=journal,
    )

    journal.record_chain_trace.assert_awaited_once()
    trace = journal.record_chain_trace.await_args.args[0]
    assert isinstance(trace, ChainExecutionTrace)
    assert trace.tokens_used == 200
    assert trace.prompt_tokens == 140
    assert trace.completion_tokens == 60
```

> **NOTE FOR BUILDER on test 6 (executor emission):** the call shape (`executor.execute(chain, observation, agent_id=..., agent_type=..., intent=..., intent_id=..., journal=journal)`) and helper (`executor.register_handler`) match `tests/test_ad658_chain_harness_metrics.py:160+` verbatim. If the API has drifted further since HEAD `6cbb0ac`, copy the call shape from that file's `test_executor_emits_trace_per_step_with_modulation_snapshot` (line 165+); the assertion (`trace.prompt_tokens == 140`) is what AD-658a guarantees.

---

## What This Does NOT Change

- `tokens_used` field semantics anywhere — still the prompt+completion sum, still the canonical token counter for backwards compatibility. **Every existing consumer continues to work without modification.**
- `LLMResponse` (already has the split fields from AD-431).
- `LLMClient.complete()` cache restore path — cached responses still set only `tokens_used`; cached chain steps record `prompt_tokens=0, completion_tokens=0`. Deferred to AD-658a-1.
- `CognitiveJournal.record()` (per-LLM-call journal table — different table, different writer).
- Builder pipeline `BlueprintResult.tokens_used` — orthogonal subsystem.
- `chain_optimizer.py` detector logic — reads only `tokens_used` today.
- `routers/chain_traces.py` — `SELECT *` automatically exposes the new columns; no router change required.
- HXI surface for the prompt/completion breakdown — deferred to AD-658a-3.
- No new EventType. No new Pydantic config. No new pool, agent, or module.
- 4 short-circuit / no-LLM paths in `analyze.py` / `compose.py` / `evaluate.py` that hard-code `tokens_used=0` — left alone (the new fields default to `0`, so the omission is correct).

## Tracking

- **`PROGRESS.md`** — prepend AD-658a CLOSED entry.
- **`docs/development/roadmap.md`** — add AD-658a as a v1 entry under the AD-658 cluster; mark AD-658a-1 / AD-658a-2 / AD-658a-3 as deferred follow-ups with the forcing functions stated in "Out of scope".
- **`DECISIONS.md`** — prepend AD-658a entry at top of Era V.
- **GH issue #408** — close with reference to commit SHA.

## Acceptance Criteria

1. `SubTaskResult` exposes `prompt_tokens: int = 0` and `completion_tokens: int = 0` as frozen-dataclass fields.
2. `ChainExecutionTrace` exposes `prompt_tokens: int = 0` and `completion_tokens: int = 0` as frozen-dataclass fields; `to_dict()` round-trips them.
3. `chain_traces` SQLite table contains `prompt_tokens INTEGER NOT NULL DEFAULT 0` and `completion_tokens INTEGER NOT NULL DEFAULT 0` on both fresh CREATE and warm-boot ALTER paths.
4. `_MIGRATIONS_CHAIN_TRACES_AD658A` is a 2-statement tuple wrapped in a try/except `Exception` loop in `journal.start()` (matches AD-660b precedent).
5. `journal.record_chain_trace` INSERT binds 26 columns + 26 placeholders (was 24).
6. The chain harness emit site at `sub_task.py:624-area` forwards `prompt_tokens` / `completion_tokens` from the producing `SubTaskResult` using defensive `getattr(result, ..., 0)`.
7. The 5 success-path / parse-fail-pass-by-default `SubTaskResult(...)` constructions in `analyze.py` (×2), `compose.py`, `evaluate.py` (×2), `reflect.py` populate `prompt_tokens` / `completion_tokens` from the `LLMResponse` using the same defensive style as the existing `tokens_used=` line in that handler.
8. `tests/test_ad658a_chain_trace_token_split.py` ships with 6 tests, all passing.
9. No regression in any existing test — full gate test count moves from **11220** to **11226** (+6 net). Window: [11226, 11227].
10. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Decision Log (architectural calls)

- **DLog #1 — Additive only; `tokens_used` preserved as the sum.** No deprecation; no consumer breakage. The 8 production read sites of `tokens_used` (chain_optimizer detectors, diagnostic_context, clinical_telemetry, optimization_counselor, routers/chain_traces.py, builder.py, cognitive_agent.py) and 7 test read sites continue to function unchanged. Wave-10 reframe rule (defer when ≥6 consumer call sites) does NOT trigger because no consumer of `tokens_used` is being modified or removed.

- **DLog #2 — Producer-side full plumbing in v1.** Five `SubTaskResult` construction sites + one `ChainExecutionTrace` site + one INSERT site is below the Wave-10 entanglement threshold. Splitting consumer-side detection logic (e.g. ChainOptimizer rules over `prompt_tokens` p95) is AD-658a-2 with a clean forcing function: AD-658a v1 ships, Captain validates split-field accuracy in production traces, then a detector becomes specifiable.

- **DLog #3 — Frozen-dataclass field append (after `tier_used` for `SubTaskResult`, after `tokens_used` for `ChainExecutionTrace`).** Defaulted-after-non-defaulted rule satisfied (every appended field has a default). All existing call sites use kwargs (verified zero positional `SubTaskResult(...)` constructions beyond `sub_task_type` / `name`); positional-arg drift risk is zero. Trace insertion location chosen for proximity to `tokens_used`.

- **DLog #4 — `getattr(..., 0)` defensive style preserved across handlers.** `analyze.py` uses bare `response.tokens_used` (LLM response is guaranteed to be present at that branch); `compose.py` matches. `evaluate.py` and `reflect.py` use `getattr(response, "tokens_used", 0)` for stub-tolerant style. The new `prompt_tokens=` / `completion_tokens=` lines mirror the EXACT defensive style of the `tokens_used=` line directly above them — same handler, same style. No surprise.

- **DLog #5 — Idempotent `ALTER TABLE ADD COLUMN` migration tuple.** Pattern lifted verbatim from AD-660b at `journal.py:111-114`. Uses `try / except Exception: pass` (matches AD-660b's broad exception net at line 211-212; SQLite raises `OperationalError` on duplicate column but the broad net is what's already in the file). New tuple `_MIGRATIONS_CHAIN_TRACES_AD658A` declared as a module-level constant for symmetry.

- **DLog #6 — `journal.record_chain_trace` uses `getattr(trace, "prompt_tokens", 0)` not `trace.prompt_tokens`.** Defensive against external test fixtures that build raw stubs of `ChainExecutionTrace` predating the field add. Matches the broader pattern of fire-and-forget journaling — never raise from the journal write path.

- **DLog #7 — `get_recent_chain_traces` is unchanged.** Its query is `SELECT * FROM chain_traces ...`; the row factory is `aiosqlite.Row`; the projection is `dict(row)`. New columns automatically appear in the returned dicts. No edit needed.

- **DLog #8 — Cache-hit token attribution deferred (AD-658a-1).** `LLMClient` cache restore at `llm_client.py:464,629` only restores `tokens_used=cached.tokens_used`; the split fields are not cached. Cache hits will record `prompt_tokens=0, completion_tokens=0, tokens_used=N`. v1 accepts this — the split is "best effort over fresh LLM responses". Forcing function: AD-658a v1 ships and Captain reviews split-field signal-to-noise on a corpus that includes cache hits; AD-658a-1 then extends `LLMResponse` cache serialization to preserve the split.

- **DLog #9 — No structured `BaseEvent` subclass; no router edit.** The split is plumbing data, not a runtime event. `routers/chain_traces.py:33-37` uses `SELECT *` (verified) — new columns surface automatically through the existing `traces` payload. v1 deliberately ships no new query parameters (`?prompt_tokens_min=...`) — aggregation surface is AD-658a-3.

- **DLog #10 — No Pydantic config gate.** Token split is unconditional; the per-step overhead is two integer columns and two integer fields on a frozen dataclass that's already constructed. Conservative cost estimate: <0.1% per chain step. A flag would only delay adoption — not warranted.

- **DLog #11 — Phantom-API pre-check could not be auto-run.** Same recurring blocker as Waves 52 & 53 (DLog #14 in both). Manual verify-first pass performed at draft — see "Verified Against Codebase" table (24 verifying greps + line numbers + verifying lines, all confirmed against HEAD `6cbb0ac`). Net-new symbols (`SubTaskResult.prompt_tokens`, `SubTaskResult.completion_tokens`, `ChainExecutionTrace.prompt_tokens`, `ChainExecutionTrace.completion_tokens`, `chain_traces.prompt_tokens`, `chain_traces.completion_tokens`, `_MIGRATIONS_CHAIN_TRACES_AD658A`) are intra-prompt-introduction (Section 1 / Section 2 / Section 3a / Section 3b SEARCH/REPLACE). Same FP class as Waves 27-53. Tooling-hygiene-AD for the pre-check script remains pending in the backlog.

- **DLog #12 — Test file naming follows the `test_adNNNz_<topic>` convention** (`test_ad658a_chain_trace_token_split.py`); 6 tests within the +6/+7 window agreed in Section "Acceptance Criteria".
