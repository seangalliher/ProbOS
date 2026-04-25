# AD-617b: Per-Agent Hourly Token Budget

## Context

AD-617 added ship-wide LLM rate governance (RPM limits, 429 backoff, cache eviction). AD-617b adds **per-agent fairness** — no single agent should monopolize the LLM budget.

The original scoping considered adding `agent_id` to `LLMRequest` and enforcing budgets inside `OpenAICompatibleClient.complete()`. Research found this requires modifying 36 production call sites and 40+ test call sites — a disproportionate blast radius. Only 7 of 36 `.complete()` call sites even have access to an agent identity.

**Revised approach:** Enforce the budget at the **proactive loop gate** in `proactive.py`, following the circuit breaker pattern. This is where runaway LLM usage manifests (BF-163 flood: proactive think cycles generating cascading LLM calls). The Cognitive Journal already tracks per-agent tokens from `CognitiveAgent._decide_via_llm()` — the key proactive path. DMs, Ward Room notifications, and Captain-directed messages bypass the gate (communication reliability, same as BF-156/circuit breaker).

### Why proactive gate, not `.complete()`

1. **Proactive thinks drive the flood** — BF-163 was proactive think → LLM → post → proactive think → LLM. Blocking proactive thinks for over-budget agents breaks the loop.
2. **DM/WR delivery must never be throttled** — BF-156 established that DM delivery is communication reliability, not proactive agency. Budget exhaustion should degrade proactive initiative, not silence the agent.
3. **The Journal already has the data** — `CognitiveJournal.record()` captures `agent_id`, `total_tokens`, and `timestamp` for every `CognitiveAgent._decide_via_llm()` call. No new instrumentation needed.
4. **Follows established patterns** — Circuit breaker gate at `proactive.py:317-326` is the exact model: check → skip → continue.

## Dependencies

- **AD-617** (COMPLETE): LLMRateConfig, ship-wide RPM limits. AD-617b extends this config.
- **AD-431** (COMPLETE): Cognitive Journal with per-agent token tracking. AD-617b queries it.
- **AD-488** (COMPLETE): Circuit breaker gate in proactive loop. AD-617b adds a parallel gate.
- **BF-156** (COMPLETE): DM delivery before agency gates. Budget gate follows same ordering.

## Changes

### Part A — Hourly Token Query on CognitiveJournal (`journal.py`)

Add a new method to `CognitiveJournal` for querying per-agent token usage within a time window.

**What to add — new method after `get_token_usage()` (after line ~267):**

```python
async def get_token_usage_since(
    self, agent_id: str, since_timestamp: float
) -> int:
    """AD-617b: Get total tokens used by an agent since a given timestamp.

    Returns total_tokens (int). Used for hourly budget enforcement.
    Returns 0 on error (fail-open for queries, fail-closed for enforcement
    happens at the caller).
    """
    if not self._db:
        return 0
    try:
        cursor = await self._db.execute(
            """SELECT COALESCE(SUM(total_tokens), 0) as tokens
               FROM journal
               WHERE agent_id = ? AND timestamp >= ? AND cached = 0""",
            (agent_id, since_timestamp),
        )
        row = await cursor.fetchone()
        return int(row["tokens"]) if row else 0
    except Exception:
        logger.debug("Journal hourly query failed", exc_info=True)
        return 0
```

**Note:** The `journal` table already has indexes on `agent_id` (line 44) and `timestamp` (line 45), so this query is efficient.

### Part B — Budget Gate in Proactive Loop (`proactive.py`)

Add a per-agent token budget gate after the circuit breaker gate, following the same pattern.

**What to add in `__init__()` — after `self._circuit_breaker` initialization (around line 164):**

```python
# AD-617b: Per-agent token budget tracking
self._budget_exhausted: dict[str, float] = {}  # agent_id -> exhaustion timestamp
```

**What to add — new method `_is_over_token_budget()`:**

```python
async def _is_over_token_budget(self, agent_id: str) -> bool:
    """AD-617b: Check if agent has exceeded hourly token budget.

    Returns True if over budget, False otherwise.
    Fail-closed: if the journal query fails, returns False (allow the think).
    Uses a 60-second cache per agent to avoid hammering the journal DB.
    """
    rt = self._runtime
    if not rt:
        return False

    # Check config
    rate_config = getattr(getattr(rt, 'config', None), 'llm_rate', None)
    if not rate_config:
        return False
    hourly_cap = getattr(rate_config, 'per_agent_hourly_token_cap', 0)
    if hourly_cap <= 0:
        return False  # Disabled

    # Cache check: don't query journal every proactive cycle
    last_exhaustion = self._budget_exhausted.get(agent_id, 0.0)
    if last_exhaustion > 0 and time.monotonic() - last_exhaustion < 60.0:
        return True  # Still in exhaustion window

    # Query journal for hourly usage
    journal = getattr(rt, 'cognitive_journal', None)
    if not journal:
        return False

    since = time.time() - 3600.0  # 1 hour sliding window
    tokens_used = await journal.get_token_usage_since(agent_id, since)

    if tokens_used >= hourly_cap:
        self._budget_exhausted[agent_id] = time.monotonic()
        logger.info(
            "AD-617b: %s over token budget (%d/%d tokens in last hour)",
            agent_id[:8], tokens_used, hourly_cap,
        )
        return True

    # Clear exhaustion if recovered (new hour, tokens aged out)
    if agent_id in self._budget_exhausted:
        del self._budget_exhausted[agent_id]
    return False
```

**What to add in `_think_loop_body()` — after the circuit breaker gate (after line 326), before the ACM activation check (before line 328):**

```python
# AD-617b: Per-agent token budget gate — skip proactive if over budget
if await self._is_over_token_budget(agent.id):
    logger.debug(
        "AD-617b: %s proactive think skipped (token budget exhausted)",
        getattr(agent, 'callsign', agent.agent_type),
    )
    continue
```

**Important ordering:** The budget gate MUST come:
- AFTER `_check_unread_dms()` (line 300) — DMs always delivered
- AFTER agency gating (line 305) — Ensigns already filtered
- AFTER cooldown (line 314) — already throttled agents don't need budget check
- AFTER circuit breaker (line 326) — tripped agents don't need budget check
- BEFORE `_think_for_agent()` (line 342) — the gate's purpose

### Part C — Config Field (`config.py`)

Add per-agent hourly token cap to the existing `LLMRateConfig`.

**What to add in `LLMRateConfig` class (after `cache_max_entries` field, around line 267):**

```python
# AD-617b: Per-agent hourly token cap (0 = disabled)
per_agent_hourly_token_cap: int = 0
```

Default `0` means disabled. Operators set a positive value to enforce. This follows the existing ProbOS pattern of safe-by-default, opt-in governance (see `composite_score_floor` default 0.0 in AD-590).

### Part D — Budget Exhaustion Event (`proactive.py`)

Emit an event when an agent's budget is exhausted so the Counselor can be aware.

**What to add in `_is_over_token_budget()` — inside the `tokens_used >= hourly_cap` branch, after the logger.info line:**

```python
# Emit event for Counselor awareness (fire-and-forget)
if self._on_event:
    try:
        await self._on_event({
            "type": "token_budget_exhausted",
            "agent_id": agent_id,
            "tokens_used": tokens_used,
            "hourly_cap": hourly_cap,
            "data": {
                "agent_id": agent_id,
                "tokens_used": tokens_used,
                "hourly_cap": hourly_cap,
            },
        })
    except Exception:
        logger.debug("Budget exhaustion event emission failed", exc_info=True)
```

## Deliberate Exclusions

| What | Why |
|------|-----|
| `agent_id` on `LLMRequest` | Blast radius: 36 production + 40+ test call sites. Not needed for proactive gate enforcement. Future AD if `.complete()`-level enforcement is ever required. |
| Counselor budget override authority | The Counselor controls timing (cooldowns), not resource allocation. Budget limits are operational policy (config), not therapeutic. Future if needed. |
| VitalsMonitor budget metrics | Future integration — expose per-agent budget utilization in /vitals. |
| Bridge Alert on budget exhaustion | The event is emitted (Part D); a Counselor subscription + Bridge Alert can be added later. Keep this AD minimal. |
| Ship-wide hourly token cap | AD-617 already provides ship-wide RPM limits. A ship-wide hourly token cap is a different concern (cost control vs fairness). |
| Non-proactive call site budgets | Builder, dreamer, procedures, research etc. are infrastructure operations, not agent proactive behavior. They don't create feedback loops. |

## Files Modified

| File | What Changes |
|------|-------------|
| `src/probos/cognitive/journal.py` | `get_token_usage_since()` method |
| `src/probos/proactive.py` | `_budget_exhausted` tracking dict, `_is_over_token_budget()` method, budget gate in `_think_loop_body()` |
| `src/probos/config.py` | `per_agent_hourly_token_cap` field on `LLMRateConfig` |

## Files Created

| File | What |
|------|------|
| `tests/test_ad617b_per_agent_token_budget.py` | New test file |

## Tests

Create `tests/test_ad617b_per_agent_token_budget.py` with these test classes:

### Class 1: `TestGetTokenUsageSince`

```python
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.journal import CognitiveJournal


@pytest.fixture
async def journal(tmp_path):
    j = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
    await j.start()
    yield j
    await j.stop()
```

Tests:
1. `test_returns_zero_for_no_entries` — No entries for agent. Returns 0.
2. `test_sums_tokens_within_window` — Insert 3 journal entries for agent_id "a1" with known total_tokens at recent timestamps. Query with `since` before all. Returns sum.
3. `test_excludes_entries_before_window` — Insert entries before and after the `since` timestamp. Only the after entries are counted.
4. `test_excludes_cached_entries` — Insert entries with `cached=True`. Returns 0 (only non-cached counted).
5. `test_filters_by_agent_id` — Insert entries for agents "a1" and "a2". Query for "a1" only returns "a1"'s tokens.

### Class 2: `TestTokenBudgetGate`

```python
from probos.proactive import ProactiveLoop
from probos.config import LLMRateConfig
```

Tests (mock `cognitive_journal.get_token_usage_since()`):
6. `test_allows_when_disabled` — `per_agent_hourly_token_cap=0`. Returns False (allowed).
7. `test_allows_when_under_budget` — Cap=10000, usage=5000. Returns False.
8. `test_blocks_when_over_budget` — Cap=10000, usage=15000. Returns True.
9. `test_caches_exhaustion_for_60s` — First check returns over-budget. Second check within 60s doesn't re-query journal (returns True from cache).
10. `test_clears_exhaustion_when_recovered` — First check over-budget. Wait (mock time advance), tokens aged out, second check returns False and clears cache.
11. `test_budget_gate_ordering_after_circuit_breaker` — Verify the gate is called in `_think_loop_body()` after the circuit breaker gate and before `_think_for_agent()`.

### Class 3: `TestTokenBudgetConfig`

Tests:
12. `test_default_disabled` — `LLMRateConfig().per_agent_hourly_token_cap == 0`.
13. `test_custom_value` — `LLMRateConfig(per_agent_hourly_token_cap=50000).per_agent_hourly_token_cap == 50000`.

## Engineering Principles Compliance

- **Single Responsibility**: Budget enforcement is a proactive loop gate concern, separate from the LLM client's API calling (AD-617) and the journal's storage (AD-431). Each layer does one thing.
- **Open/Closed**: Extends `LLMRateConfig` with one new field. Extends `CognitiveJournal` with one new query. Extends proactive loop with one new gate. No existing behavior modified.
- **DRY**: Uses existing `CognitiveJournal` token data — no duplicate accounting. Gate follows the circuit breaker pattern exactly (check → log → continue).
- **Fail Fast / Log-and-Degrade**: Budget exhaustion = log info + skip proactive + emit event. Agent still receives DMs, Ward Room notifications, and Captain directives. Graceful degradation, not silence.
- **Defense in Depth**: Three layers of LLM governance: (1) AD-617 RPM caps (ship-wide throughput), (2) AD-617b per-agent token budget (fairness), (3) AD-488 circuit breaker (cognitive health). Independent, composable, defense-in-depth.
- **Law of Demeter**: Budget check reads config via `self._runtime.config.llm_rate` and journal via `self._runtime.cognitive_journal` — both are directly available services, not reached through chains.
