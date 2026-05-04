# BF-238: Post Budget Telemetry Monitoring

**Status:** Ready for builder
**Priority:** Medium (follow-up to BF-237)
**Tracker:** PROGRESS.md, roadmap.md
**Issue:** GH #341
**Estimated tests:** 8 new

---

## Problem

BF-237 introduced `PostBudget` — a one-post-per-pipeline-invocation gate in
`src/probos/ward_room_pipeline.py`. When the action extractor already posted
inside `process_and_post()`, Step 7 is suppressed and a single
`pipeline_post_budget_exceeded` event is appended to `event_log`. That gives
us a row-level audit trail but **no aggregate signal**:

1. We cannot answer "how often is the budget exhausted in production, per
   agent, per thread?" without scanning the events.db.
2. We cannot detect the regression where the limit (1 post per pipeline
   invocation) is **too aggressive** — i.e. legitimate multi-post scenarios
   (game `[MOVE]` boards + accompanying narration; multi-`[REPLY]` triage)
   are being silently suppressed at high rates.
3. There is no operator-visible warning when exhaustion rate crosses an
   actionable threshold.

GH #341 acceptance criteria:

- Per-agent, per-thread exhaustion frequency surface
- Alert when exhaustion rate exceeds a configurable threshold (suggesting the
  limit is too low)
- Operator-readable list of recent suppressions to spot-check for false
  suppression of legitimate posts

---

## Solution Overview

Add a new in-process counter surface `PostBudgetTelemetry` (alongside
`PostBudget` in `ward_room_pipeline.py`) that:

1. Tracks `invocations` and `exhaustions` per `(agent_type, thread_id)`,
   plus per-agent and overall totals.
2. Exposes `exhaustion_rate(*, agent_type=None, thread_id=None)` returning
   `None` when sample count is zero, or `exhaustions / invocations` otherwise.
3. Logs a one-shot WARN per agent_type when its per-agent rate first
   crosses the configurable threshold AND the per-agent invocation count
   is at or above `min_samples_for_alert`.
4. Buffers the most recent N suppressions as
   `tuple[tuple[float, str, str], ...]` (timestamp, agent_type, thread_id)
   for ops review.

The pipeline calls `record_invocation()` at the top of `process_and_post()`
and `record_exhaustion()` inside the existing `if budget.spent:` Step-7
suppression branch.

The telemetry surface is **observational only**. It never mutates the
budget, never blocks posts, never modifies pipeline behavior. The `event_log`
emission introduced by BF-237 is preserved unchanged.

---

## Implementation

### Section 0: Verify Current State (read-only — no edits)

Confirm the following before starting:

```text
src/probos/ward_room_pipeline.py:24      class PostBudget:
src/probos/ward_room_pipeline.py:95      budget = PostBudget()
src/probos/ward_room_pipeline.py:152     if budget.spent:
src/probos/ward_room_pipeline.py:155     logger.warning("BF-237: Suppressing main post for %s ...
src/probos/ward_room_pipeline.py:161     event="pipeline_post_budget_exceeded",
src/probos/runtime.py:1665               # AD-654a: Wire up WardRoomPostPipeline ...
src/probos/runtime.py:1669               self.ward_room_post_pipeline = WardRoomPostPipeline(
src/probos/config.py:1278                class WardRoomConfig(BaseModel):
src/probos/config.py:1906                telemetry: TelemetryConfig = TelemetryConfig()  # AD-461
```

These are the integration points. If any line numbers have drifted, locate
the surrounding context anchor (the docstring or sibling line) and apply
the change there. Do **not** edit any other PostBudget call site.

### Section 1: Add `PostBudgetTelemetryConfig` (new Pydantic model)

**File:** `src/probos/config.py`

Add a new `BaseModel` class. Place it directly **after** the existing
`TelemetryConfig` definition (around line 736 — search for
`class TelemetryConfig(BaseModel):` and add the new class after its
closing brace).

**SEARCH:**

```python
class TelemetryConfig(BaseModel):
    """Ship's Telemetry configuration (AD-461)."""

    enabled: bool = True
    report_interval_seconds: float = 60.0
    max_samples_per_bucket: int = 1000


class ConfidenceConfig(BaseModel):
```

**REPLACE:**

```python
class TelemetryConfig(BaseModel):
    """Ship's Telemetry configuration (AD-461)."""

    enabled: bool = True
    report_interval_seconds: float = 60.0
    max_samples_per_bucket: int = 1000


class PostBudgetTelemetryConfig(BaseModel):
    """BF-238: Post-budget exhaustion telemetry configuration."""

    enabled: bool = True
    exhaustion_alert_threshold: float = 0.5  # Per-agent rate that triggers WARN
    min_samples_for_alert: int = 10          # Suppress alert below this invocation count
    recent_suppressions_max: int = 100       # Ring buffer size for ops review


class ConfidenceConfig(BaseModel):
```

Then attach the config to `SystemConfig`. Find the existing line:

**SEARCH:**

```python
    telemetry: TelemetryConfig = TelemetryConfig()  # AD-461
    confidence: ConfidenceConfig = ConfidenceConfig()  # AD-444
```

**REPLACE:**

```python
    telemetry: TelemetryConfig = TelemetryConfig()  # AD-461
    post_budget_telemetry: PostBudgetTelemetryConfig = PostBudgetTelemetryConfig()  # BF-238
    confidence: ConfidenceConfig = ConfidenceConfig()  # AD-444
```

### Section 2: Add `PostBudgetTelemetry` to `ward_room_pipeline.py`

**File:** `src/probos/ward_room_pipeline.py`

Add the new class **after** the existing `PostBudget` dataclass and
**before** the `WardRoomPostPipeline` class.

**SEARCH:**

```python
@dataclass
class PostBudget:
    """BF-237: Tracks whether a create_post has fired in the current pipeline invocation."""
    spent: bool = False


class WardRoomPostPipeline:
```

**REPLACE:**

```python
@dataclass
class PostBudget:
    """BF-237: Tracks whether a create_post has fired in the current pipeline invocation."""
    spent: bool = False


class PostBudgetTelemetry:
    """BF-238: Aggregate per-agent + per-thread counters for PostBudget exhaustion.

    Records every `process_and_post()` invocation and every Step-7 suppression
    triggered by an already-spent PostBudget. Exposes per-agent / per-thread
    / overall exhaustion rate plus a bounded ring buffer of recent
    suppressions for ops review.

    Observational only — never mutates pipeline state, never blocks posts.
    The event_log row written by BF-237 in `WardRoomPostPipeline` is the
    durable audit trail; this class is the in-memory aggregate surface.
    """

    def __init__(
        self,
        *,
        exhaustion_alert_threshold: float = 0.5,
        min_samples_for_alert: int = 10,
        recent_suppressions_max: int = 100,
    ) -> None:
        self._exhaustion_alert_threshold = float(exhaustion_alert_threshold)
        self._min_samples_for_alert = int(min_samples_for_alert)
        self._recent_suppressions_max = int(recent_suppressions_max)
        self._total_invocations = 0
        self._total_exhaustions = 0
        self._invocations_by_agent: dict[str, int] = {}
        self._exhaustions_by_agent: dict[str, int] = {}
        self._invocations_by_thread: dict[str, int] = {}
        self._exhaustions_by_thread: dict[str, int] = {}
        self._recent_suppressions: list[tuple[float, str, str]] = []
        # One-shot guard: agents that have already triggered a threshold alert.
        self._alerted_agents: set[str] = set()

    # --- Public read-only properties ---

    @property
    def total_invocations(self) -> int:
        return self._total_invocations

    @property
    def total_exhaustions(self) -> int:
        return self._total_exhaustions

    @property
    def alert_threshold(self) -> float:
        return self._exhaustion_alert_threshold

    @property
    def min_samples_for_alert(self) -> int:
        return self._min_samples_for_alert

    # --- Recording API (called by WardRoomPostPipeline) ---

    def record_invocation(self, agent_type: str, thread_id: str) -> None:
        """Increment per-agent + per-thread + total invocation counters."""
        self._total_invocations += 1
        if agent_type:
            self._invocations_by_agent[agent_type] = (
                self._invocations_by_agent.get(agent_type, 0) + 1
            )
        if thread_id:
            self._invocations_by_thread[thread_id] = (
                self._invocations_by_thread.get(thread_id, 0) + 1
            )

    def record_exhaustion(self, agent_type: str, thread_id: str) -> None:
        """Increment per-agent + per-thread + total exhaustion counters and
        append to the recent-suppressions ring buffer.

        Triggers a one-shot WARN alert when the per-agent rate first crosses
        the configured threshold AND per-agent invocations are at or above
        the min-samples gate.
        """
        self._total_exhaustions += 1
        if agent_type:
            self._exhaustions_by_agent[agent_type] = (
                self._exhaustions_by_agent.get(agent_type, 0) + 1
            )
        if thread_id:
            self._exhaustions_by_thread[thread_id] = (
                self._exhaustions_by_thread.get(thread_id, 0) + 1
            )
        # Append to ring buffer, bounded by recent_suppressions_max.
        self._recent_suppressions.append((time.time(), agent_type, thread_id))
        if len(self._recent_suppressions) > self._recent_suppressions_max:
            # Drop oldest entries to enforce the bound.
            overflow = len(self._recent_suppressions) - self._recent_suppressions_max
            self._recent_suppressions = self._recent_suppressions[overflow:]

        # One-shot threshold alert.
        self._maybe_alert(agent_type)

    # --- Read API ---

    def exhaustion_rate(
        self,
        *,
        agent_type: str | None = None,
        thread_id: str | None = None,
    ) -> float | None:
        """Return exhaustion rate as `exhaustions / invocations`.

        Scope precedence (mutually exclusive in v1; if both supplied,
        agent_type wins to keep the API single-axis):
          - agent_type given -> per-agent rate
          - thread_id given  -> per-thread rate
          - neither          -> overall rate

        Returns None when the corresponding invocation count is zero.
        """
        if agent_type:
            invocations = self._invocations_by_agent.get(agent_type, 0)
            exhaustions = self._exhaustions_by_agent.get(agent_type, 0)
        elif thread_id:
            invocations = self._invocations_by_thread.get(thread_id, 0)
            exhaustions = self._exhaustions_by_thread.get(thread_id, 0)
        else:
            invocations = self._total_invocations
            exhaustions = self._total_exhaustions
        if invocations == 0:
            return None
        return exhaustions / invocations

    def recent_suppressions(
        self, limit: int = 10
    ) -> tuple[tuple[float, str, str], ...]:
        """Return the most recent suppressions for ops spot-check.

        Each entry is `(timestamp, agent_type, thread_id)`. Newest last.
        `limit <= 0` returns an empty tuple.
        """
        if limit <= 0:
            return ()
        # Slice from the tail; preserves insertion order (newest last).
        return tuple(self._recent_suppressions[-limit:])

    # --- Internal ---

    def _maybe_alert(self, agent_type: str) -> None:
        """One-shot per-agent WARN when rate first crosses threshold."""
        if not agent_type or agent_type in self._alerted_agents:
            return
        invocations = self._invocations_by_agent.get(agent_type, 0)
        if invocations < self._min_samples_for_alert:
            return
        rate = self.exhaustion_rate(agent_type=agent_type)
        if rate is None or rate <= self._exhaustion_alert_threshold:
            return
        self._alerted_agents.add(agent_type)
        logger.warning(
            "BF-238: PostBudget exhaustion rate %.2f for agent_type=%s "
            "exceeds threshold %.2f over %d invocations; review whether "
            "post_budget limit is too aggressive for this agent",
            rate, agent_type, self._exhaustion_alert_threshold, invocations,
        )


class WardRoomPostPipeline:
```

### Section 3: Wire `PostBudgetTelemetry` into `WardRoomPostPipeline`

**File:** `src/probos/ward_room_pipeline.py`

Add a kwarg to the pipeline constructor and call the telemetry methods at
the two integration points.

**SEARCH:**

```python
    def __init__(
        self,
        *,
        ward_room: "WardRoomService",
        ward_room_router: Any,  # WardRoomRouter — for record_agent_response, cooldowns, endorsements
        proactive_loop: Any | None,  # ProactiveCognitiveLoop — for extract_and_execute_actions, similarity
        trust_network: Any | None,
        callsign_registry: Any | None,
        config: Any,
        runtime: Any | None = None,  # For skill_service access
        novelty_gate: "NoveltyGate | None" = None,  # AD-493
    ) -> None:
        self._ward_room = ward_room
        self._router = ward_room_router
        self._proactive_loop = proactive_loop
        self._trust_network = trust_network
        self._callsign_registry = callsign_registry
        self._config = config
        self._runtime = runtime
        self._novelty_gate = novelty_gate
```

**REPLACE:**

```python
    def __init__(
        self,
        *,
        ward_room: "WardRoomService",
        ward_room_router: Any,  # WardRoomRouter — for record_agent_response, cooldowns, endorsements
        proactive_loop: Any | None,  # ProactiveCognitiveLoop — for extract_and_execute_actions, similarity
        trust_network: Any | None,
        callsign_registry: Any | None,
        config: Any,
        runtime: Any | None = None,  # For skill_service access
        novelty_gate: "NoveltyGate | None" = None,  # AD-493
        post_budget_telemetry: "PostBudgetTelemetry | None" = None,  # BF-238
    ) -> None:
        self._ward_room = ward_room
        self._router = ward_room_router
        self._proactive_loop = proactive_loop
        self._trust_network = trust_network
        self._callsign_registry = callsign_registry
        self._config = config
        self._runtime = runtime
        self._novelty_gate = novelty_gate
        self._post_budget_telemetry = post_budget_telemetry  # BF-238
```

Now record an invocation at the top of `process_and_post()`. Find the
existing Step-1 sanitize block:

**SEARCH:**

```python
        # Step 1: Text sanitization (BF-199)
        from probos.utils.text_sanitize import sanitize_ward_room_text
        response_text = sanitize_ward_room_text(response_text)
        if not response_text or response_text == "[NO_RESPONSE]":
            return False
```

**REPLACE:**

```python
        # BF-238: Record every pipeline invocation BEFORE early-return guards
        # so the rate denominator includes empty-text returns.
        if self._post_budget_telemetry is not None:
            self._post_budget_telemetry.record_invocation(
                agent.agent_type if agent else "",
                thread_id,
            )

        # Step 1: Text sanitization (BF-199)
        from probos.utils.text_sanitize import sanitize_ward_room_text
        response_text = sanitize_ward_room_text(response_text)
        if not response_text or response_text == "[NO_RESPONSE]":
            return False
```

Now record an exhaustion inside the existing BF-237 suppression branch.

**SEARCH:**

```python
        # Step 7: Post to Ward Room
        # BF-237: If action extractor already posted, suppress the main post.
        if budget.spent:
            logger.warning(
                "BF-237: Suppressing main post for %s — action extractor already posted in this invocation",
                agent.agent_type,
            )
            # BF-237: Emit telemetry event for observability
            if self._runtime and getattr(self._runtime, 'event_log', None):
                try:
                    await self._runtime.event_log.log(
                        category="pipeline",
                        event="pipeline_post_budget_exceeded",
                        agent_id=agent.id,
                        agent_type=agent.agent_type,
                        detail=f"thread_id={thread_id}",
                    )
                except Exception:
                    logger.debug("BF-237: telemetry log failed", exc_info=True)
```

**REPLACE:**

```python
        # Step 7: Post to Ward Room
        # BF-237: If action extractor already posted, suppress the main post.
        if budget.spent:
            logger.warning(
                "BF-237: Suppressing main post for %s — action extractor already posted in this invocation",
                agent.agent_type,
            )
            # BF-238: Aggregate counter + threshold-alert surface.
            if self._post_budget_telemetry is not None:
                self._post_budget_telemetry.record_exhaustion(
                    agent.agent_type, thread_id,
                )
            # BF-237: Emit telemetry event for observability
            if self._runtime and getattr(self._runtime, 'event_log', None):
                try:
                    await self._runtime.event_log.log(
                        category="pipeline",
                        event="pipeline_post_budget_exceeded",
                        agent_id=agent.id,
                        agent_type=agent.agent_type,
                        detail=f"thread_id={thread_id}",
                    )
                except Exception:
                    logger.debug("BF-237: telemetry log failed", exc_info=True)
```

### Section 4: Construct + wire `runtime.post_budget_telemetry`

**File:** `src/probos/runtime.py`

Find the existing pipeline-construction block at line ~1665 and construct
the telemetry surface immediately before the pipeline (so it can be passed
into the constructor) and expose it as a public attribute.

**SEARCH:**

```python
        # AD-654a: Wire up WardRoomPostPipeline for agent self-posting
        from probos.ward_room_pipeline import WardRoomPostPipeline
        self.ward_room_post_pipeline: WardRoomPostPipeline | None = None
        if self.ward_room:
            self.ward_room_post_pipeline = WardRoomPostPipeline(
                ward_room=self.ward_room,
                ward_room_router=self.ward_room_router,
                proactive_loop=self.proactive_loop,
                trust_network=self.trust_network,
                callsign_registry=getattr(self, 'callsign_registry', None),
                config=self.config,
                runtime=self,
                novelty_gate=getattr(self, '_novelty_gate', None),
            )
```

**REPLACE:**

```python
        # AD-654a: Wire up WardRoomPostPipeline for agent self-posting
        # BF-238: Construct PostBudgetTelemetry first so the pipeline can
        # record invocation + exhaustion events.
        from probos.ward_room_pipeline import (
            PostBudgetTelemetry,
            WardRoomPostPipeline,
        )
        pbt_cfg = self.config.post_budget_telemetry
        self.post_budget_telemetry: PostBudgetTelemetry | None = None
        if pbt_cfg.enabled:
            self.post_budget_telemetry = PostBudgetTelemetry(
                exhaustion_alert_threshold=pbt_cfg.exhaustion_alert_threshold,
                min_samples_for_alert=pbt_cfg.min_samples_for_alert,
                recent_suppressions_max=pbt_cfg.recent_suppressions_max,
            )
        self.ward_room_post_pipeline: WardRoomPostPipeline | None = None
        if self.ward_room:
            self.ward_room_post_pipeline = WardRoomPostPipeline(
                ward_room=self.ward_room,
                ward_room_router=self.ward_room_router,
                proactive_loop=self.proactive_loop,
                trust_network=self.trust_network,
                callsign_registry=getattr(self, 'callsign_registry', None),
                config=self.config,
                runtime=self,
                novelty_gate=getattr(self, '_novelty_gate', None),
                post_budget_telemetry=self.post_budget_telemetry,
            )
```

### Section 5: Tests

**File:** `tests/test_bf238_post_budget_telemetry.py` (new)

Run under `pytest` + `pytest-asyncio` (`asyncio_mode = "auto"` per project
config). Tests should be order-independent and use `tmp_path` only if files
are needed (none are needed here).

#### Test 1: `test_record_invocation_increments_counters`

- Construct `PostBudgetTelemetry()` with defaults.
- Call `record_invocation("scout", "thread-A")` three times.
- Assert `total_invocations == 3`.
- Assert `exhaustion_rate() == 0.0` (rate computed from totals, not None,
  because invocations > 0).
- Assert `exhaustion_rate(agent_type="scout") == 0.0`.
- Assert `exhaustion_rate(agent_type="missing") is None`.

#### Test 2: `test_record_exhaustion_increments_counters_and_buffer`

- Telemetry with `recent_suppressions_max=100`.
- Call `record_invocation("scout", "thread-A")` then
  `record_exhaustion("scout", "thread-A")`.
- Assert `total_exhaustions == 1`.
- Assert `exhaustion_rate(agent_type="scout") == 1.0`.
- Assert `exhaustion_rate(thread_id="thread-A") == 1.0`.
- Assert `len(telemetry.recent_suppressions(limit=10)) == 1`.
- Unpack the tuple: `(ts, agent_type, thread_id)` — assert `agent_type ==
  "scout"` and `thread_id == "thread-A"` and `ts > 0`.

#### Test 3: `test_exhaustion_rate_returns_none_when_no_samples`

- Fresh telemetry, no calls.
- Assert `exhaustion_rate() is None`.
- Assert `exhaustion_rate(agent_type="scout") is None`.
- Assert `exhaustion_rate(thread_id="thread-A") is None`.

#### Test 4: `test_exhaustion_rate_per_agent_per_thread_overall`

- Record invocations: scout x4 on thread-A, scout x2 on thread-B,
  greeter x4 on thread-A.
- Record exhaustions: scout x2 on thread-A, greeter x1 on thread-A.
- Assert `exhaustion_rate() == 3 / 10`.
- Assert `exhaustion_rate(agent_type="scout") == 2 / 6`.
- Assert `exhaustion_rate(agent_type="greeter") == 1 / 4`.
- Assert `exhaustion_rate(thread_id="thread-A") == 3 / 8`.
- Assert `exhaustion_rate(thread_id="thread-B") == 0.0`.

#### Test 5: `test_threshold_alert_fires_once_when_rate_exceeds_threshold`

- Telemetry with `exhaustion_alert_threshold=0.5`,
  `min_samples_for_alert=10`.
- Record 10 invocations + 6 exhaustions for `"scout"` (rate 0.6 > 0.5).
- Use `caplog.at_level(logging.WARNING, logger="probos.ward_room_pipeline")`.
- Assert at least one record contains `"BF-238"` and `"scout"` and
  `"exceeds threshold"`.
- Trigger a 7th exhaustion. Assert no additional WARN appears (`alert_count`
  stays at 1) — proves one-shot guard.

#### Test 6: `test_threshold_alert_suppressed_below_min_samples`

- Telemetry with `exhaustion_alert_threshold=0.5`,
  `min_samples_for_alert=10`.
- Record 5 invocations + 5 exhaustions for `"scout"` (rate 1.0 but below
  min-samples gate).
- Assert no WARN with `"BF-238"` and `"scout"` was emitted.

#### Test 7: `test_recent_suppressions_bound_respected`

- Telemetry with `recent_suppressions_max=3`.
- Drive 5 (invocation, exhaustion) pairs for `("scout", f"thread-{i}")`.
- Assert `len(recent_suppressions(limit=10)) == 3`.
- Assert the three returned `thread_id` values are `"thread-2"`,
  `"thread-3"`, `"thread-4"` (newest 3, oldest dropped).
- Assert `recent_suppressions(limit=0) == ()`.

#### Test 8: `test_pipeline_records_invocation_and_exhaustion`

- Integration test for the wiring change in Section 3.
- Build a minimal `WardRoomPostPipeline` with all dependencies as
  `MagicMock` / `AsyncMock` (mirror the pattern in
  `tests/test_bf237_pipeline_post_budget.py` if present; otherwise build
  minimum stubs for `ward_room`, `ward_room_router`, `proactive_loop`).
- Inject a real `PostBudgetTelemetry()` instance via the new
  `post_budget_telemetry=` kwarg.
- Configure the `proactive_loop.extract_and_execute_actions` mock to set
  `budget.spent = True` (mirrors BF-237 Test 1 pattern).
- Build a stub `agent` with `id="a-1"`, `agent_type="scout"`.
- `await pipeline.process_and_post(agent=agent, response_text="hello",
  thread_id="thread-A", event_type="ward_room_thread_created")`.
- Assert `telemetry.total_invocations == 1` and
  `telemetry.total_exhaustions == 1`.
- Assert `telemetry.exhaustion_rate(agent_type="scout") == 1.0`.
- Assert `len(telemetry.recent_suppressions()) == 1` with
  `agent_type="scout"`, `thread_id="thread-A"`.

**Test count: 8 new tests.**

---

## What This Does NOT Change

- **`PostBudget` semantics** — `spent` flag, ctor, callers in
  `proactive.py` (lines 2902 / 2917 / 3223 / 3238): unchanged.
- **`event_log.log(category="pipeline", event="pipeline_post_budget_exceeded", ...)`**
  — BF-237 row-level audit trail preserved verbatim. BF-238 is
  **additive** in-process aggregation.
- **`process_and_post()` post-suppression / post-success behavior** —
  Steps 8–10 (record_response, skill_exercise, cooldown) unchanged.
- **`extract_and_execute_actions` signature** — `post_budget` kwarg
  unchanged.
- **No new EventType** — the existing `pipeline_post_budget_exceeded`
  event_log event is the only durable signal; aggregate state is in-process.
- **Threshold-alert behavior is one-shot per agent** — v1 does not reset
  the alert if the rate later drops below threshold. Re-alert / cooldown /
  decay deferred (potential BF-238b if needed).
- **No HTTP/REST surface** — telemetry is read by future ops tooling via
  `runtime.post_budget_telemetry.exhaustion_rate(...)` /
  `recent_suppressions(...)`. A `/system/post_budget_telemetry` REST route
  is **not** in scope.
- **Per-thread alerts** — only per-agent triggers a WARN in v1; per-thread
  rates are queryable but do not raise alerts (alerting on individual
  threads would be log-noisy).

---

## Engineering Principles Compliance

Verify all changes comply with the Engineering Principles in
`.github/copilot-instructions.md`:

- **SOLID (S):** `PostBudgetTelemetry` has one responsibility — counting +
  rate computation + threshold alerting for the budget surface.
- **SOLID (O):** Additive — no edits to `PostBudget`, no signature breaks
  on existing pipeline callers (`post_budget_telemetry=` defaults to None).
- **SOLID (D):** Constructor injection — pipeline receives the telemetry
  surface via kwarg; runtime constructs it from Pydantic config.
- **Law of Demeter:** Pipeline calls public `record_invocation()` /
  `record_exhaustion()` — no reach-through to private fields. Runtime
  exposes telemetry as `runtime.post_budget_telemetry` (public attribute,
  no leading underscore — Wave 5 convention #1).
- **Fail Fast / Log-and-degrade:** Threshold alert is a `logger.warning`
  with full context (rate, agent, threshold, sample count). Telemetry is
  optional (`None`-guarded in pipeline) — degrades silently if disabled.
- **DRY:** Counter pattern reused across agent / thread / total dimensions
  via shared `dict.get(...) + 1` increment. Single rate formula.
- **Configuration:** `PostBudgetTelemetryConfig` Pydantic model with all
  defaults set; system runs zero-config. Defaults at parse time.
- **Type annotations:** All public methods fully typed (parameters +
  return type).
- **Logging:** WARN message includes what (rate), where (agent_type),
  why it matters (threshold), what next (review limit).
- **Async hygiene:** No new tasks, no new async surface. Telemetry is
  synchronous in-process.
- **Testing discipline:** 8 boundary tests covering happy path, error
  case, edge cases (no samples, below min-samples, ring-buffer bound,
  k=0), and integration wiring.

---

## Verification

```powershell
# Targeted tests
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf238_post_budget_telemetry.py -v -n 0

# BF-237 regression check (the source of truth for the suppression branch)
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf237_pipeline_post_budget.py -v -n 0

# Full gate
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile
```

---

## Tracker Updates

### PROGRESS.md

Add a one-line CLOSED entry at the top mirroring the Wave 25 entry shape:

```text
BF-238 v1 CLOSED. PostBudget telemetry monitoring (GH issue #341,
follow-up to BF-237). New `PostBudgetTelemetry` in `ward_room_pipeline.py`
with per-agent / per-thread / overall invocation + exhaustion counters,
`exhaustion_rate(agent_type=, thread_id=)` accessor, bounded recent-
suppressions ring buffer, and one-shot per-agent WARN when rate exceeds
configurable threshold (default 0.5) and min-samples gate (default 10).
New `PostBudgetTelemetryConfig` wired onto `SystemConfig.post_budget_telemetry`.
Public attribute `runtime.post_budget_telemetry`. Constructor injection
into `WardRoomPostPipeline`. BF-237 `event_log` row-level audit trail
preserved unchanged. 8 focused tests pass; full gate +8 vs baseline.
Closes GH issue #341.
```

### docs/development/roadmap.md

Add `BF-238` to the Bug Tracker table with status `CLOSED v1`.

### DECISIONS.md

No new architectural-decision entry required — BF-238 is observational
aggregation of an existing BF-237 signal, not a new architectural surface.

---

## Acceptance Criteria

- All 8 new tests pass under `-n 0` and `-n 8 --dist=loadfile`.
- Full gate test count delta is exactly +8 vs the BF-238 baseline.
- BF-237 tests remain green.
- `runtime.post_budget_telemetry` is publicly accessible after startup
  (when `post_budget_telemetry.enabled=True`, the default).
- `runtime.post_budget_telemetry.exhaustion_rate(agent_type="...")`,
  `recent_suppressions(limit=N)`, and `total_invocations` /
  `total_exhaustions` are usable from a Python REPL connected to the
  running process.
- WARN is emitted exactly once per agent_type that crosses the threshold
  with sample count above the min-samples gate.
- No edits to `proactive.py`, `event_log.py`, `events.py`, or
  `cognitive_services.py`.
- Verify all changes comply with the Engineering Principles in
  `.github/copilot-instructions.md`.

---

## Standing Conventions

- **ASCII-only** in source code, including comments and docstrings. Em
  dash and similar typographic chars permitted only in markdown
  (this file).
- **Public-attribute wiring** (Wave 5 convention #1): `runtime.post_budget_telemetry`,
  not `runtime._post_budget_telemetry`. Mirrors the `runtime.event_log`,
  `runtime.ward_room_post_pipeline`, `runtime.curriculum_registry`,
  `runtime.boundary_registry` precedent.
- **Verify-first**: every concrete reference in this prompt (file, line,
  class name, method signature) was grep-confirmed against HEAD before
  drafting (see `## Verified Against Codebase` below).
- **No phantom APIs**: only methods that exist on `EventLog`,
  `PostBudget`, `WardRoomPostPipeline` are referenced. No new
  `EventType` enum value introduced.
- **No scope creep**: per-thread alerting, dashboard endpoints, REST
  surface, alert reset/decay, AD-461 `TelemetryService` integration are
  all out of scope. Listed under "What This Does NOT Change".
- **Pydantic config**: all knobs land on a `BaseModel` in `config.py`
  with sensible defaults; never read from env vars or raw dicts.
- **Fail-fast tier**: WARN-and-continue (log-and-degrade). Never raise
  from `record_invocation` / `record_exhaustion` — they are observers.
- **Order-independent tests**: each test creates its own `PostBudgetTelemetry`
  instance; no shared state.
- **Type annotations on every new public method.**

---

## Verified Against Codebase (2026-05-04)

```text
grep -n "class PostBudget" src/probos/ward_room_pipeline.py
  24: class PostBudget:

grep -n "PostBudget()" src/probos/ward_room_pipeline.py
  95:         budget = PostBudget()

grep -n "if budget.spent" src/probos/ward_room_pipeline.py
  152:        if budget.spent:

grep -n "BF-237: Suppressing main post" src/probos/ward_room_pipeline.py
  155:            logger.warning(

grep -n "pipeline_post_budget_exceeded" src/probos/ward_room_pipeline.py
  161:                        event="pipeline_post_budget_exceeded",

grep -n "WardRoomPostPipeline(" src/probos/runtime.py
  1669:            self.ward_room_post_pipeline = WardRoomPostPipeline(

grep -n "class TelemetryConfig" src/probos/config.py
  736: class TelemetryConfig(BaseModel):

grep -n "telemetry: TelemetryConfig = TelemetryConfig" src/probos/config.py
  1906:    telemetry: TelemetryConfig = TelemetryConfig()  # AD-461

grep -n "async def log" src/probos/substrate/event_log.py
  94:     async def log(

grep -n "post_budget=post_budget" src/probos/proactive.py
  2354: agent, text, post_budget=post_budget,

grep -n "post_budget.spent = True" src/probos/proactive.py
  2917:                                            post_budget.spent = True
  3238:                    post_budget.spent = True
```
