# AD-658 v1: Cognitive Chain Harness Metrics

**Status:** Drafted (Wave 28)
**Risk:** low (additive — new dataclass, new journal table + 2 new methods, new emission hook in chain executor wrapped in try/except, new read-only API router)
**Depends on:** `SubTaskExecutor` chain framework (shipped, AD-632a/h/f, BF-183, AD-636); `CognitiveJournal` (shipped, AD-431/432); `runtime.cognitive_journal` (shipped); modulation params set on observation by `cognitive_agent` (AD-649 `_communication_context`, AD-639 `_chain_trust_band`, AD-638 `_boot_camp_active`); router-registration pattern at `api.py:185`.
**Closes:** GitHub issue #317
**Source:** Meta-Harness research (Lee et al., Stanford/UW, arXiv:2603.28052) — "the cognitive chain IS a harness; you can't optimize what you can't measure." This AD ships the **measurement substrate** for AD-659 (chain optimization).

---

## AD-652 Status Note

**AD-652** ("Cognitive Code-Switching: Unified Pipeline with Contextual Modulation") is a **DESIGN PRINCIPLE adopted in DECISIONS.md:1914**, not a discrete shipped module. It is realised across multiple ADs already in the tree:

- **AD-649** (`derive_communication_context` at `cognitive_agent.py:59`; sets `observation["_communication_context"]` at `cognitive_agent.py:2058–2064`) — channel/recipient → register inference.
- **AD-639** (chain-trust-band tuning; sets `observation["_trust_score"]` and `observation["_chain_trust_band"]` at `cognitive_agent.py:2073–2086` and `1893–1899`) — trust-adaptive personality modulation.
- **AD-638** (boot camp gate; sets `observation["_boot_camp_active"]` at `cognitive_agent.py:2068–2071` and `1880–1883`) — relaxed quality threshold for new agents.
- **AD-632a/h/f** (`SubTaskExecutor` at `sub_task.py:172`) — the chain itself, the substrate AD-652 modulates.

**Implication for AD-658 v1:** the dependency is satisfied. The "active modulation parameters" enumerated in issue #317 are already present in the `context` dict passed to `SubTaskExecutor.execute()`. v1 captures them by snapshotting the `_communication_context`, `_chain_trust_band`, `_trust_score`, `_boot_camp_active`, `_from_captain`, and `_is_dm` keys at step start. **No changes to AD-649/639/638 wiring are required.**

---

## Solution Overview

The chain framework already records LLM calls to `CognitiveJournal` via `journal.record(... dag_node_id=...)` (`sub_task.py:582–600`), but those entries are flat LLM-call rows — they do not capture the **chain-shaped harness state** (which step, which chain, what modulation was active, what context was passed in vs. filtered out, how long the step actually ran end-to-end). This AD adds a **second, dedicated trace stream** alongside the existing journal entries.

v1 ships **dataclass + producer + storage + read API**:

1. **`ChainExecutionTrace` dataclass** (`src/probos/cognitive/chain_trace.py`, NEW module). Frozen. Captures one row per chain step. Field set is fully derivable from the existing `_execute_single_step` locals — no new instrumentation in handlers.
2. **`CognitiveJournal.record_chain_trace(...)` + `CognitiveJournal.get_recent_chain_traces(...)`** (additive on the existing `CognitiveJournal` class). New table `chain_traces` provisioned via `CREATE TABLE IF NOT EXISTS` in `start()`. Same fire-and-forget never-raises pattern as `record(...)`.
3. **Per-step emission hook** in `SubTaskExecutor._execute_single_step` (`sub_task.py:456`). Inserted AFTER the existing journal `await journal.record(...)` block (`sub_task.py:582–600`) and BEFORE the `if not result.success and spec.required: raise SubTaskStepError` abort (`sub_task.py:602`). Same try/except guard pattern: telemetry failure must not break the chain.
4. **`/api/chain-traces` GET endpoint** in NEW router `src/probos/routers/chain_traces.py` (mirrors `routers/journal.py` shape exactly). Registered in `api.py:185–205` alongside the other routers. Read-only; recent N traces with optional `agent_id` / `since` filters.

## Trace Field Set (v1, decided after verify-first against `sub_task.py`)

All fields are computable from existing locals in `_execute_single_step`. No new context plumbing required.

| Field | Type | Source |
|---|---|---|
| `chain_id` | str | local `chain_id` (`sub_task.py:289`) |
| `step_index` | int | param `step_index` |
| `step_name` | str | `spec.name` |
| `sub_task_type` | str | `spec.sub_task_type.value` (query/analyze/compose/evaluate/reflect) |
| `tier` | str | `result.tier_used or spec.tier` |
| `agent_id` | str | param `agent_id` |
| `agent_type` | str | param `agent_type` |
| `intent` | str | param `intent` |
| `intent_id` | str | param `intent_id` |
| `chain_source` | str | requires plumbing `chain.source` into `_execute_single_step` (see Section 3 — currently `chain.source` is in scope only at `_execute_chain` level; pass through as a new kwarg) |
| `started_at` | float | `time.time()` captured at top of `_execute_single_step` (alongside the existing `step_start = time.monotonic()` at `sub_task.py:514`) |
| `duration_ms` | float | `result.duration_ms` |
| `tokens_used` | int | `result.tokens_used` (total only — input/output split deferred; SubTaskResult does not carry the split, only `CognitiveJournal.record` does at the LLM-call layer) |
| `success` | bool | `result.success` |
| `error_truncated` | str | `result.error[:200]` (empty when success) |
| **Context composition** | | |
| `context_keys_declared` | int | `len(spec.context_keys)` |
| `context_keys_passed` | int | `len(step_context)` (after the existing filter at `sub_task.py:508–512`) |
| `context_filter_applied` | bool | `bool(spec.context_keys and spec.sub_task_type != SubTaskType.QUERY)` (mirrors the existing condition at `sub_task.py:510`) |
| **Modulation snapshot** (read from full `context` at step start) | | |
| `communication_context` | str \| None | `context.get("_communication_context")` (AD-649) |
| `chain_trust_band` | str \| None | `context.get("_chain_trust_band")` (AD-639) |
| `trust_score` | float \| None | `context.get("_trust_score")` (AD-639) |
| `boot_camp_active` | bool | `bool(context.get("_boot_camp_active"))` (AD-638) |
| `from_captain` | bool | `bool(context.get("_from_captain"))` |
| `is_dm` | bool | `bool(context.get("_is_dm"))` |

**Modulation params are read from `context` (the full observation), not `step_context` (the filtered view)** — they are properties of the run, not the step's prompt-context budget. If a step filters them out via `context_keys`, the trace still records what WAS active at the chain level. This matters for AD-659 attribution (e.g., "compose steps under `_chain_trust_band="low"` exhibit longer durations").

## What This Does NOT Change

- **No output quality signals beyond `success`** in v1. Output-quality scoring (semantic-coherence score, hallucination detection, instruction-following score) is the explicit scope of **AD-659** (optimization). v1 ships only the binary `success` flag from `SubTaskResult.success`.
- **No input/output token split.** `SubTaskResult` only carries `tokens_used` (total). Splitting requires an upstream LLM-client-level plumb that is out of scope; the LLM-call-level split already exists in `CognitiveJournal.journal` via `prompt_tokens`/`completion_tokens` columns and can be cross-referenced by `dag_node_id` if needed for analysis. Defer richer token attribution to AD-658a if AD-659 needs it.
- **No changes to handler signatures.** Handlers (`SubTaskHandler` Protocol at `sub_task.py:82`) receive the same `(spec, context, prior_results)`. Trace emission happens in the executor wrapper, not in handlers.
- **No new EventType.** Trace emission is to-DB only. No `CHAIN_STEP_TRACED` event in v1 (would multiply event-bus load with no current consumer). Defer to AD-658a if HXI / dashboard needs live streaming.
- **No WebSocket fan-out.** v1 is read-on-demand via REST. Live trace streaming is deferred.
- **No retroactive backfill.** Traces are forward-only from the moment AD-658 lands. No migration of historical journal entries into chain_traces.
- **No `prune()` extension.** v1 uses the same `prune()` retention policy already present on `CognitiveJournal` (`journal.py:109`) — extend it to the new `chain_traces` table in the same method (drop rows by `started_at < cutoff` mirroring the existing `timestamp < cutoff` block) so retention stays unified. Row-count cap likewise extended to apply to chain_traces by the same `max_rows` ceiling. **No new config knob in v1.**
- **No fallback-path emission.** When a chain fails mid-stream and the agent falls back to single-call `_decide_via_llm()` at `cognitive_agent.py:1379`, the steps that DID run before the failure are traced (the emission hook is per-step inside the executor); the fallback LLM call itself is captured by the existing `journal.record` path, not by `chain_traces`. Cross-referencing fallback-vs-chain is a downstream analysis concern.
- **No sampling.** v1 records every step of every chain. If volume becomes a load issue, AD-658a can add a `chain_trace_sample_rate` knob; v1 ships unsampled to maximise AD-659 signal.

## Dependencies (verified anchors)

- `src/probos/cognitive/sub_task.py:289` — `chain_id = uuid.uuid4().hex[:8]` in `_execute_chain`. Already in scope at the call to `_execute_single_step` (line ~410, see Section 3).
- `src/probos/cognitive/sub_task.py:456–608` — `_execute_single_step` body. Insertion point for the emission hook is between the existing `await journal.record(...)` block (lines 582–600) and the `if not result.success and spec.required: raise SubTaskStepError` block (line 602).
- `src/probos/cognitive/sub_task.py:508–512` — existing context filter. The new `context_keys_passed`/`context_filter_applied` fields read off `spec`, `step_context`, and `spec.sub_task_type` already in scope at the hook point.
- `src/probos/cognitive/sub_task.py:514` — `step_start = time.monotonic()`. The new wall-clock `started_at` is captured here as `time.time()` (added one line above — also already in scope at the hook point).
- `src/probos/cognitive/sub_task.py:69–73` — `SubTaskChain.source`. Currently NOT plumbed into `_execute_single_step`; Section 3 adds a `chain_source: str = ""` kwarg, threaded from `_execute_chain` (line ~292) → `_execute_steps` (line ~338) → `_execute_single_step` (line ~456). The two existing `_execute_single_step` invocations (one inside `if len(ready) == 1:` at line ~360 and one inside the parallel-dispatch wave at line ~377) both gain the kwarg.
- `src/probos/cognitive/journal.py:56–101` — `CognitiveJournal` class. New schema constant `_SCHEMA_CHAIN_TRACES` added at module top (mirrors `_SCHEMA_BASE`/`_SCHEMA_INDEXES` shape). New `await self._db.executescript(_SCHEMA_CHAIN_TRACES)` after the existing `_SCHEMA_INDEXES` execution at `journal.py:91`.
- `src/probos/cognitive/journal.py:148` — existing `record(...)` method. New `record_chain_trace(...)` follows the exact same fire-and-forget never-raises shape (`if not self._db: return; try: await self._db.execute(...); await self._db.commit(); except Exception: logger.debug(...)`).
- `src/probos/cognitive/journal.py:200` — existing `get_reasoning_chain(...)` query method. New `get_recent_chain_traces(...)` follows the same shape (build clauses, build params, fetchall, return `[dict(row) for row in rows]`).
- `src/probos/cognitive/journal.py:109` — existing `prune(...)` method. Extend to also delete from `chain_traces` by `started_at < cutoff` (and, for the row-count cap, by oldest `started_at`).
- `src/probos/cognitive/cognitive_agent.py:1922–1929` — `self._sub_task_executor.execute(... journal=self._cognitive_journal, ...)` call site. `self._cognitive_journal` already wired (no changes required to this call site).
- `src/probos/api.py:185–206` — router registration block. Section 5 adds `chain_traces` to both the `from probos.routers import (...)` tuple and the `for r in (...)` registration tuple.
- `src/probos/routers/journal.py:14` — `APIRouter(prefix="/api/journal", tags=["journal"])` template. Section 5 mirrors with `prefix="/api/chain-traces", tags=["chain-traces"]`.
- `src/probos/routers/deps.py` — `get_runtime` dependency (already shipped, used by every existing router).

## Sections

### Section 1 — `ChainExecutionTrace` dataclass (NEW module)

Create `src/probos/cognitive/chain_trace.py`:

```python
"""ChainExecutionTrace — per-step harness measurement record (AD-658).

One row per cognitive-chain step. Captures latency, token usage, context
composition breakdown, and active modulation parameters for downstream
optimization analysis (AD-659). Forward-only; not retroactive.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True)
class ChainExecutionTrace:
    """Single-step harness trace. Frozen — emit once at step completion."""

    # Chain / step identity
    chain_id: str
    step_index: int
    step_name: str
    sub_task_type: str
    tier: str
    chain_source: str = ""

    # Caller identity
    agent_id: str = ""
    agent_type: str = ""
    intent: str = ""
    intent_id: str = ""

    # Wall-clock + execution
    started_at: float = 0.0
    duration_ms: float = 0.0
    tokens_used: int = 0
    success: bool = True
    error_truncated: str = ""

    # Context composition breakdown
    context_keys_declared: int = 0
    context_keys_passed: int = 0
    context_filter_applied: bool = False

    # Modulation snapshot (AD-649 / AD-639 / AD-638)
    communication_context: str | None = None
    chain_trust_band: str | None = None
    trust_score: float | None = None
    boot_camp_active: bool = False
    from_captain: bool = False
    is_dm: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict projection for JSON serialization and DB row binding."""
        return asdict(self)
```

No methods beyond `to_dict()`. Frozen guards against mutation post-emission.

### Section 2 — `CognitiveJournal.record_chain_trace` + `get_recent_chain_traces` + schema + prune extension

In `src/probos/cognitive/journal.py`:

**2a. New schema constant** (insert after `_SCHEMA_INDEXES` at line ~52):

```python
_SCHEMA_CHAIN_TRACES = """
CREATE TABLE IF NOT EXISTS chain_traces (
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

CREATE INDEX IF NOT EXISTS idx_chain_traces_started_at ON chain_traces(started_at);
CREATE INDEX IF NOT EXISTS idx_chain_traces_agent ON chain_traces(agent_id);
CREATE INDEX IF NOT EXISTS idx_chain_traces_chain_id ON chain_traces(chain_id);
"""
```

**2b. Provision in `start()`** — append after the existing `await self._db.executescript(_SCHEMA_INDEXES)` line at `journal.py:91`:

```python
        # AD-658: chain harness traces (separate from per-LLM-call journal rows)
        await self._db.executescript(_SCHEMA_CHAIN_TRACES)
```

**2c. New `record_chain_trace` method** — insert after the existing `record(...)` method (after `journal.py:198`, before `get_reasoning_chain`):

```python
    async def record_chain_trace(self, trace: Any) -> None:
        """AD-658: Append a chain-step trace row. Fire-and-forget — never raises.

        Accepts a ChainExecutionTrace (or any object with the same field set
        accessible via attribute lookup). Conflicts on (chain_id, step_index)
        are silently dropped via INSERT OR IGNORE — chain steps are write-once.
        """
        if not self._db:
            return
        try:
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
            await self._db.commit()
        except Exception:
            logger.debug("Chain trace record failed", exc_info=True)
```

**2d. New `get_recent_chain_traces` method** — insert after `record_chain_trace`:

```python
    async def get_recent_chain_traces(
        self,
        *,
        limit: int = 50,
        agent_id: str | None = None,
        since: float | None = None,
    ) -> list[dict[str, Any]]:
        """AD-658: Return recent chain-step traces, most recent first.

        Args:
            limit: Max rows (capped by caller; default 50).
            agent_id: Optional filter by agent.
            since: Optional Unix-timestamp lower bound on started_at.
        """
        if not self._db:
            return []
        try:
            clauses: list[str] = []
            params: list[Any] = []
            if agent_id is not None:
                clauses.append("agent_id = ?")
                params.append(agent_id)
            if since is not None:
                clauses.append("started_at >= ?")
                params.append(since)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            params.append(limit)
            cursor = await self._db.execute(
                f"SELECT * FROM chain_traces {where} ORDER BY started_at DESC LIMIT ?",
                params,
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception:
            logger.debug("Chain trace query failed", exc_info=True)
            return []
```

**2e. Extend `prune(...)`** — inside the existing `prune` method (`journal.py:109`), after the existing age-based DELETE block on the `journal` table, add a sibling DELETE on `chain_traces` (insert before the `# Row-count cap` block):

```python
        # AD-658: extend retention to chain_traces
        if retention_days > 0:
            cursor = await self._db.execute(
                "DELETE FROM chain_traces WHERE started_at < ?", (cutoff,)
            )
            deleted += cursor.rowcount
```

And inside the row-count-cap block, add an analogous cap on chain_traces (after the existing journal row-count cap block, before the `if deleted > 0:` commit):

```python
        # AD-658: row-count cap on chain_traces
        if max_rows > 0:
            cursor = await self._db.execute("SELECT COUNT(*) FROM chain_traces")
            row = await cursor.fetchone()
            total_traces = row[0] if row else 0
            if total_traces > max_rows:
                excess = total_traces - max_rows
                cursor = await self._db.execute(
                    "DELETE FROM chain_traces WHERE rowid IN "
                    "(SELECT rowid FROM chain_traces ORDER BY started_at ASC LIMIT ?)",
                    (excess,),
                )
                deleted += cursor.rowcount
```

(Use `rowid` for the chain_traces ORDER BY because the table's primary key is `(chain_id, step_index)`, not a single `id` column like `journal`.)

### Section 3 — Per-step emission hook in `SubTaskExecutor`

In `src/probos/cognitive/sub_task.py`:

**3a.** Plumb `chain.source` into `_execute_single_step`. Add a new keyword argument `chain_source: str = ""` to `_execute_single_step`'s signature (around line 456). Update both call sites:

- The single-step path (`_execute_steps` line ~360, inside `if len(ready) == 1:`) — pass `chain_source=chain.source`.
- The parallel-dispatch wave (`_execute_steps` line ~377, inside the gather list comprehension) — pass `chain_source=chain.source`.

**3b.** Capture wall-clock `started_at` next to the existing monotonic `step_start`. In `_execute_single_step`, change:

```python
        step_start = time.monotonic()
```

to:

```python
        step_start = time.monotonic()
        step_started_at = time.time()  # AD-658: wall-clock for chain trace
```

**3c.** Insert the trace-emission block AFTER the existing journal-record block (after `sub_task.py:600`) and BEFORE the `if not result.success and spec.required: raise SubTaskStepError` block (`sub_task.py:602`):

```python
        # AD-658: Per-step harness trace (independent of per-LLM-call journal row)
        if journal is not None:
            try:
                from probos.cognitive.chain_trace import ChainExecutionTrace
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
                if hasattr(journal, "record_chain_trace"):
                    await journal.record_chain_trace(trace)
            except Exception:
                logger.debug(
                    "AD-658: chain trace emission failed for step '%s'",
                    spec.name, exc_info=True,
                )
```

The `hasattr(journal, "record_chain_trace")` guard is the standard graceful-degradation idiom for non-CognitiveJournal journal mocks (e.g., the existing test fixtures that pass `MagicMock()` as journal). It is **not** speculation about whether the method exists on production `CognitiveJournal` — Section 2 ships it.

### Section 4 — Wire `chain_source` through the inner executor

The two existing wave paths in `_execute_steps` (`sub_task.py:338–410`) both call `_execute_single_step`. Add `chain_source=chain.source` as a kwarg to BOTH (the single-step branch and the parallel-wave list comp). The `chain` variable is already in scope (`_execute_steps` receives it as a parameter at line 338).

No other call sites of `_execute_single_step` exist (verified — see Verified Against Codebase below).

### Section 5 — `/api/chain-traces` GET router

Create `src/probos/routers/chain_traces.py`:

```python
"""ProbOS API — Cognitive Chain Trace routes (AD-658)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chain-traces", tags=["chain-traces"])


@router.get("")
async def list_chain_traces(
    limit: int = 50,
    agent_id: str | None = None,
    since: float | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-658: Recent cognitive-chain step traces, most recent first.

    Args:
        limit: Max rows (default 50, hard-capped at 500).
        agent_id: Optional agent filter.
        since: Optional Unix-timestamp lower bound on started_at.
    """
    if not runtime.cognitive_journal:
        return {"traces": []}
    traces = await runtime.cognitive_journal.get_recent_chain_traces(
        limit=min(max(limit, 1), 500),
        agent_id=agent_id,
        since=since,
    )
    return {"traces": traces}
```

Register in `src/probos/api.py:185–206` — add `chain_traces` to BOTH the `from probos.routers import (...)` tuple AND the `for r in (...)` registration tuple. Insert in alphabetical position (between `chat` and `counselor`):

```python
    from probos.routers import (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, chain_traces, counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic,
    )
    for r in (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, chain_traces, counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic,
    ):
        app.include_router(r.router)
```

(SEARCH/REPLACE: take the full existing block; replacement adds `chain_traces` in BOTH tuples.)

## Tests

Create `tests/test_ad658_chain_harness_metrics.py`. Minimum 6 tests; v1 ships 8 to cover boundary branches.

1. **`test_chain_execution_trace_dataclass_defaults`** — instantiate `ChainExecutionTrace(chain_id="c", step_index=0, step_name="x", sub_task_type="analyze", tier="standard")`, assert defaults (`agent_id=""`, `success=True`, `tokens_used=0`, `context_filter_applied=False`, `communication_context=None`, etc.) and that `to_dict()` round-trips.

2. **`test_chain_execution_trace_is_frozen`** — assert `dataclasses.is_dataclass(trace)` and that mutation raises (`with pytest.raises(dataclasses.FrozenInstanceError): trace.duration_ms = 99.0`).

3. **`test_journal_record_and_get_recent_chain_traces_round_trip`** — open a real `CognitiveJournal` against a tmp_path SQLite DB, `await journal.start()`, build a trace, call `await journal.record_chain_trace(trace)`, call `await journal.get_recent_chain_traces(limit=10)`, assert the returned dict round-trips every field (cast int success/bool fields back; `success: 1 → True` checked via the dict value).

4. **`test_journal_get_recent_chain_traces_filters_and_ordering`** — record 3 traces (`agent_id="a"` × 2, `agent_id="b"` × 1) with monotonically increasing `started_at` (e.g., 1.0, 2.0, 3.0). Assert (a) `get_recent_chain_traces(limit=10)` returns all 3 most-recent-first; (b) `get_recent_chain_traces(agent_id="a")` returns 2 rows; (c) `get_recent_chain_traces(since=2.5)` returns 1 row; (d) `get_recent_chain_traces(limit=2)` returns 2 most-recent rows.

5. **`test_journal_record_chain_trace_no_db_short_circuits`** — `journal = CognitiveJournal(db_path=None)` (no `start()`), `await journal.record_chain_trace(trace)` returns `None` and does not raise. `await journal.get_recent_chain_traces()` returns `[]`.

6. **`test_executor_emits_trace_per_step_with_modulation_snapshot`** — build a tiny `SubTaskChain` with one ANALYZE step; register a stub handler returning `SubTaskResult(..., tokens_used=42, duration_ms=15.0, success=True, tier_used="fast")`; pass a `MagicMock()` journal with an async `record_chain_trace` and async `record`; pass observation containing `_communication_context="bridge_briefing"`, `_chain_trust_band="high"`, `_trust_score=0.82`, `_boot_camp_active=False`, `_from_captain=True`, `_is_dm=False`; execute; assert `journal.record_chain_trace` was awaited exactly once with a `ChainExecutionTrace` whose modulation fields match (`communication_context="bridge_briefing"`, `chain_trust_band="high"`, `trust_score==0.82`, `from_captain=True`) and whose execution fields match (`tokens_used==42`, `duration_ms==15.0`, `success==True`, `tier=="fast"`).

7. **`test_executor_context_composition_breakdown_records_filter`** — build an ANALYZE step with `context_keys=("query", "history")`; pass full observation `{"query": "X", "history": [...], "noise": "Y", "_internal": "Z"}` (4 keys); execute; assert the recorded trace has `context_keys_declared==2`, `context_keys_passed==3` (query + history + the leading-underscore "_internal" passes through per the existing filter at `sub_task.py:511`), and `context_filter_applied==True`. Add a parallel sub-test with QUERY type (no filter applied per `sub_task.py:510`) — assert `context_filter_applied==False` and `context_keys_passed==4`.

8. **`test_executor_trace_emission_failure_does_not_break_chain`** — pass a journal mock whose `record_chain_trace` is an `AsyncMock(side_effect=Exception("boom"))`; execute the chain; assert (a) the chain still completes, (b) `journal.record_chain_trace` was awaited (failure happened), (c) the SubTaskResult is what the handler returned (no SubTaskStepError raised). Validates the try/except guard in Section 3c.

**API tests** are intentionally not in this prompt (router is a 4-line passthrough; fully covered by tests 3+4 against `get_recent_chain_traces` and the existing FastAPI router-registration coverage in `tests/test_api.py`/equivalents). If reviewer demands API tests, add `test_chain_traces_router_happy_path` and `test_chain_traces_router_empty_when_journal_disabled` as a 9th and 10th — but v1 holds at 8.

## Standing Conventions Compliance

- **Convention #1 (Wave 5):** No private-attribute access. New router uses `runtime.cognitive_journal` (public). Trace emission uses `journal.record_chain_trace` (public method introduced by this AD).
- **Convention #3 (Wave 5):** Pre-deferral aggressive — output-quality signals, token split, EventType emission, WebSocket streaming, sampling, and retroactive backfill all explicitly deferred.
- **Convention #7 (Wave 5):** No theatre — every field has a verified source local; the `chain_source` plumbing is real (Section 3a/4) and not stubbed.
- **Convention #14:** v1 ships only the **measurement substrate**. Optimization (the consumer that reads `chain_traces` and decides which steps to tune) is the explicit scope of AD-659, not folded in.
- **Convention #15:** Three-tier exception handling — emission failure is **swallow** (justified: telemetry must never break a chain); journal storage failure is **log-and-degrade** (matches existing `record(...)` pattern); API errors propagate via FastAPI default.
- **Convention #16:** Phantom-API pre-check ran (see "Verified Against Codebase" below). All grep hits documented.
- **AD-682 fixture isolation:** Tests use `tmp_path` fixture for the SQLite DB, no shared state between tests.
- **Type annotations:** All public methods fully typed (`record_chain_trace`, `get_recent_chain_traces`, `list_chain_traces`, `to_dict`).
- **Logging:** All emission failures logged at `debug` level with `exc_info=True`, including the step name in the message context.

## Acceptance Criteria

1. New file `src/probos/cognitive/chain_trace.py` exists with `ChainExecutionTrace` frozen dataclass + `to_dict()`.
2. `src/probos/cognitive/journal.py` has new `_SCHEMA_CHAIN_TRACES` constant; `start()` provisions it; `record_chain_trace()` and `get_recent_chain_traces()` methods exist; `prune()` extended to chain_traces.
3. `src/probos/cognitive/sub_task.py` `_execute_single_step` accepts `chain_source` kwarg; both `_execute_steps` call sites pass it; per-step trace emission inserted after journal-record and before failure-raise; emission wrapped in try/except.
4. New file `src/probos/routers/chain_traces.py` exists with `GET /api/chain-traces`.
5. `src/probos/api.py` router-registration tuples include `chain_traces` (in BOTH the import and the for-loop).
6. ≥6 focused tests pass at `tests/test_ad658_chain_harness_metrics.py` (target: 8).
7. Full gate `pytest tests/ -q -n 4 --dist=loadfile` passes with delta `+8` over the wave-baseline (or `+6` if reviewer trims tests 7 and 8 to the floor — Builder reports actual).
8. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
9. PROGRESS.md gets a new top entry: `AD-658 v1 CLOSED. Cognitive Chain Harness Metrics (GH issue #317). [...]`.
10. `docs/development/roadmap.md` AD-658 row flipped to ✅ (verify the row exists; if not, append under Phase 28 / measurement substrate).
11. GitHub issue #317 closed via commit message footer `Closes #317`.

## Tracking

- **PROGRESS.md** — top of file: new AD-658 v1 CLOSED entry with field set, file paths, test count, and gate delta.
- **docs/development/roadmap.md** — flip AD-658 status (or append under measurement-substrate section if not yet enumerated).
- **DECISIONS.md** — NOT required for v1 (AD-658 is execution-of-design-already-recorded; AD-652 is the underlying design AD). Add a brief entry only if Builder hits an unexpected architectural fork.

## Verified Against Codebase (2026-05-04)

```
git log -1 --oneline
  59654ba (HEAD -> main) Wave 27 archive: AD-657 dream trace preservation (#316)

# AD-652 status
Select-String PROGRESS.md "AD-652"
  285: AD-652 DESIGN PRINCIPLE (adopted). Cognitive Code-Switching ...
Select-String DECISIONS.md "AD-652"
  1914: ### AD-652 — Cognitive Code-Switching: Unified Pipeline ...
Select-String src/probos -Recurse -Pattern "AD-652"
  (no matches — confirmed: no production-code marker; design-only)

# AD-649 / AD-639 / AD-638 modulation params (the things this AD measures)
src/probos/cognitive/cognitive_agent.py:59  derive_communication_context(...)
src/probos/cognitive/cognitive_agent.py:2058–2064  observation["_communication_context"] = derive_communication_context(...)
src/probos/cognitive/cognitive_agent.py:2073–2086  observation["_trust_score"], observation["_chain_trust_band"]
src/probos/cognitive/cognitive_agent.py:2068–2071  observation["_boot_camp_active"]

# Chain executor (AD-632a)
src/probos/cognitive/sub_task.py:172  class SubTaskExecutor
src/probos/cognitive/sub_task.py:289  chain_id = uuid.uuid4().hex[:8]
src/probos/cognitive/sub_task.py:456  async def _execute_single_step(...)
src/probos/cognitive/sub_task.py:514  step_start = time.monotonic()
src/probos/cognitive/sub_task.py:582–600  await journal.record(... dag_node_id=...)
src/probos/cognitive/sub_task.py:602  if not result.success and spec.required: raise SubTaskStepError
src/probos/cognitive/sub_task.py:69  @dataclass class SubTaskChain — has .source field

# Call sites of _execute_single_step
Select-String src/probos/cognitive/sub_task.py "_execute_single_step"
  (only 2 internal call sites in _execute_steps + 1 def — confirmed)

# CognitiveJournal
src/probos/cognitive/journal.py:56  class CognitiveJournal
src/probos/cognitive/journal.py:91  await self._db.executescript(_SCHEMA_INDEXES)  ← insertion point for _SCHEMA_CHAIN_TRACES
src/probos/cognitive/journal.py:148  async def record(...)  ← new record_chain_trace mirrors this shape
src/probos/cognitive/journal.py:200  async def get_reasoning_chain(...)  ← new get_recent_chain_traces mirrors this shape
src/probos/cognitive/journal.py:109  async def prune(...)  ← extended for chain_traces

# Runtime wiring
src/probos/runtime.py:213  cognitive_journal: CognitiveJournal | None
src/probos/runtime.py:425  self.cognitive_journal: CognitiveJournal | None = None
src/probos/runtime.py:1596  self.cognitive_journal = comm.cognitive_journal

# Executor receives journal
src/probos/cognitive/cognitive_agent.py:1922–1929  await self._sub_task_executor.execute(... journal=self._cognitive_journal, ...)

# Router-registration pattern
src/probos/api.py:185–206  from probos.routers import (... chat, counselor, ...) ; for r in (...): app.include_router(r.router)
src/probos/routers/journal.py:14  router = APIRouter(prefix="/api/journal", tags=["journal"])  ← template
src/probos/routers/journal.py:18,26,46  runtime.cognitive_journal usage pattern  ← template

# Phantom-API pre-check (introduced symbols, all defined within this prompt)
  ChainExecutionTrace                          — Section 1 (NEW module)
  CognitiveJournal.record_chain_trace          — Section 2c
  CognitiveJournal.get_recent_chain_traces     — Section 2d
  routers.chain_traces (module)                — Section 5 (NEW module)
  /api/chain-traces (route)                    — Section 5
  trace.{chain_id, step_index, ... 23 fields}  — Section 1 (NEW dataclass)
```

All grep hits accounted for. No phantom APIs in implementation. Test scaffolding mental model: `MagicMock` for journal in tests 6–8; real `CognitiveJournal(db_path=tmp_path/...)` in tests 3–5 (matching the AD-657 retrospective lesson — use real classes where DB round-trip is the assertion).
