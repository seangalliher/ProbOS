# Review: AD-491 — Infodynamic Telemetry (Information Entropy)

**Reviewer:** Architect (verify-first review of own draft)
**Date:** 2026-05-01
**Verdict:** ⚠️ **Conditional** — one phantom kwarg (`event_log.query(since=...)`) makes the event-log signal silently constant; everything else is structurally clean. Single-line fix.

Smallest, lowest-risk Wave 6 prompt. Pre-flagged drafting decision (placement) is judgment-call sound. Section 0 EventType is unique and free.

---

## Required (must fix before building)

### 1. `event_log.query(since=...)` is a phantom kwarg

The probe's `_event_log_entropy()` (line 156) calls:

```python
events = await log.query(limit=10_000, since=since)
```

Verified — `EventLog.query()` does not accept `since`:

```
grep -n "async def query" src/probos/substrate/event_log.py
  132: async def query(
  170: async def query_structured(

view src/probos/substrate/event_log.py:132-137
  async def query(
      self,
      category: str | None = None,
      agent_id: str | None = None,
      limit: int = 100,
  ) -> list[dict]:
```

`query()` accepts `category`, `agent_id`, `limit`. No `since`. `query_structured()` adds `correlation_id`, `event`, `parent_event_id`. No time-window filter on either.

Behavior under build-as-written: Python keyword-only positional binding will fail because `since` does not exist as a parameter — `TypeError: query() got an unexpected keyword argument 'since'`. The defensive `except Exception` catches it (line 157), the signal returns `entropy=0.0`, and the operator sees a constant zero on the event-log channel forever. Theater per the Wave 5 retrospective convention #3.

**Action:** Pick one:

- **(a)** Drop the `since=` parameter and post-filter in Python:

  ```python
  events = await log.query(limit=10_000)
  cutoff = time.time() - self._event_window
  events = [e for e in events if e.get("timestamp", 0) >= cutoff]
  ```

  Trade-off: pulls 10K rows even when only the last hour is relevant.

- **(b)** Drop the windowing entirely in v1 — entropy over the latest 10K events is a reasonable proxy for "current" entropy without the window argument.

- **(c)** Add `since=` to `EventLog.query()` as a Section 1.5 of AD-491 (extends the substrate API). Larger blast radius but cleanest.

Recommended **(a)** — preserves the windowing semantics without expanding scope into substrate.

---

## Recommended

### 1. `event_log.query()` returns `category` field, not `event`

Section 1's `_event_log_entropy()` reads `e.get("category", "")` — verified that `query()` SELECTs `category, event` columns and returns both via `_row_to_dict()`. ✅ Correct field name. No change needed; flagging as confirmation.

### 2. Section 5 router-registration import block needs trailing-comma discipline

The SEARCH/REPLACE adds `infodynamic` to a multi-import tuple. The current block at `api.py:192-204` already uses trailing-comma style. The replacement preserves it. ✅ Confirmed.

Minor: the prompt's footer says `api.py:192–204`; actual import block is at `192-197`, the loop tuple is at `198-203`, and `app.include_router(r.router)` is at line 204. The dual-edit (import block + iteration tuple) is correct in the prompt body. Just clarify the line range in the footer for next reader.

### 3. Trust score quantization assumes `[0, 1]` range

Line 201:

```python
idx = min(self._trust_buckets - 1, int(s * self._trust_buckets))
```

Verified — `TrustNetwork.get_score()` (`consensus/trust.py:397`) returns the Beta(alpha, beta) mean, which IS bounded `[0, 1]`. ✅ Quantization is correct.

But: defensive programming would clamp to `[0, 1]` first in case a future trust subclass returns a different range. Add `s = max(0.0, min(1.0, s))` before the bucket index calculation. One line.

### 4. `agent.state` is an `AgentState` enum, `str()` works but `.value` is cleaner

Line 222:

```python
states[str(state)] += 1
```

Verified — `BaseAgent.state` is `AgentState` enum (`substrate/agent.py:43`). `str(AgentState.ACTIVE)` returns `"AgentState.ACTIVE"`, while `AgentState.ACTIVE.value` returns `"active"`. The latter matches the wire format used elsewhere (`substrate/agent.py:166: "state": self.state.value`).

Recommend: `states[state.value if state else "unknown"] += 1`. Keeps the entropy calculation aligned with the canonical state representation.

---

## Nits

### 1. `runtime.event_log` description says "audit log" in AD-459

AD-459's registry lists `event_log` with description `"audit log"`. AD-491 reads `event_log` but does not register it. No conflict — flagging as cross-prompt context.

### 2. Tracking note for placement decision

The footer says "DECISIONS.md: optional entry recording the placement choice (`cognitive/infodynamic.py` vs `telemetry/infodynamic.py`)." Recommend making this non-optional — the placement decision sets a precedent for future cognitive-vs-substrate-vs-telemetry layer questions. Future architects will look for the rationale.

### 3. `EntropySignal` dataclass field order

`name, entropy, sample_size, bucket_count` — first three are descriptive, last is structural. No ordering bug (frozen dataclass; positional construction not used). Style suggestion only.

### 4. Test 6 (`test_analyze_no_runtime_returns_empty_signals`) needs awaiting

The test description doesn't show the test body. The actual `analyze()` is `async`. Test must use `await`. Verify Test 6 is decorated `@pytest.mark.asyncio`.

---

## Verified

### Public-attribute wiring (Wave-5 convention #1) — ✅ Applied

```
runtime.infodynamic_probe = InfodynamicProbe(...)  # Section 4, finalize.py
```

No leading underscore. Public attribute. Verified compliant.

### stdlib-only persistence (Wave-5 convention #2) — ✅ Applied

No new pyproject dependencies. Uses `math`, `time`, `collections.Counter` — all stdlib. ✅

### Coordinator-then-dispatch (Wave-5 convention #3) — ✅ Applied (N/A)

AD-491 is read-only observability. No dispatch surface. v1 is final on the read path.

### Superset-filter discipline (Wave-5 convention #4) — ✅ Applied (N/A)

No insertion into existing flows. AD-491 is additive-only.

### `init_<phase>` startup signatures (Wave-5 convention #5) — ✅ Applied

Section 4 wires from `startup/finalize.py`, which receives `runtime` directly. Verified — `finalize.py` receives `runtime` (this is a finalization phase, not a `init_communication`-style emit_event_fn-only callback).

### Verify-first for anchors (Wave-5 convention #6) — ✅ Applied

Every concrete claim has grep evidence in the footer. The phantom kwarg `since=` is the one slip — flagged Required #1.

### Section 0 EventType — ✅ Clean

`INFODYNAMIC_REPORT = "infodynamic_report"` — verified absent in `events.py`. No collision with other Wave 6 EventTypes.

### Cross-prompt anchor chain — ✅ Clean

Section 2 anchors on `SERVICE_TIER_RESTORED = ... # AD-459`. Builder note correctly identifies the alternate anchor (`AGENT_SELF_NAMED`, line 190) for out-of-order execution.

### Pre-flagged drafting decision: cognitive/ vs telemetry/ placement — ✅ Sound

`substrate/telemetry.py` exists as a substrate primitive (`TelemetryService` for sample/bucket recording — operational metrics). AD-491 reads runtime cognitive state (event log entropy, trust distribution, agent state distribution) — these are cognitive-layer signals, not substrate primitives. `cognitive/infodynamic.py` is the correct placement.

If alternative placement were `substrate/`, AD-491 would import from `cognitive/` and `consensus/` — a layer-violation per the architecture rules. `cognitive/` is unambiguously correct.

### Distinct from AD-557 (`emergence_metrics.py`) — ✅ Verified

AD-557 PID/synergy at `cognitive/emergence_metrics.py:182,279,352` is within-thread collaboration decomposition. AD-491 is whole-system Shannon entropy trajectory (Vopson 2023). No surface overlap. Both can coexist.

### Test plan — ✅ Comprehensive

10 tests cover: 1 EventType existence, 1 config defaults, 3 entropy unit tests (uniform, empty, single-bucket), 4 analyze paths (no runtime, event-log, trust, emit), 1 endpoint 404. Boundary coverage holds: happy + error + edge.

### `get_runtime` import — ✅ Verified

`grep -n "def get_runtime" src/probos/routers/deps.py` → `13: def get_runtime(request: Request) -> ProbOSRuntime:`. ✅

### `runtime.emit_event` — ✅ Verified at line 775

Footer says line 771 (off by 4). Approximate line numbers per review-criteria #6. Not a blocker.

---

## Verdict Summary

**One blocking issue:** the phantom `since=` kwarg makes the event-log entropy signal a silent constant. Three-line fix (Section 1 `_event_log_entropy()`).

**4 Recommended findings:** minor robustness improvements (clamping, `state.value` not `str(state)`, line numbers).

**4 Nits:** cosmetic.

**Wave-5 conventions:** all 6 applied. ✅

**Build-readiness after fix:** ~5 minutes architect time. Re-review of Section 1 only.

Build readiness order: AD-491 first in Wave 6 (lowest blast radius, no dependencies).
