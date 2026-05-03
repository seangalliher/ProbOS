# Review: BF-246 — LLM Tier Recovery Deadlock

**Reviewer:** Architect
**Date:** 2026-04-29
**Verdict:** ⚠️ **Conditional Approval** — Diagnosis is correct and the design is sound,
but several spec gaps and one real bug in the proposed code need to be fixed before
building.

**Re-review (2026-04-29, second pass): ✅ Approved.** All Required items from the
first pass have been addressed. See the "Re-review" section at the end of this file.

---

## Summary

Real bug, well-diagnosed. Prior-art references (BF-069, BF-240, BF-108) check out. Code
references verified:

- `__main__.py:189` — `await client.check_connectivity()` ✓
- `llm_client.py:240` — `async def check_connectivity` ✓
- `llm_client.py:379` — `if self._tier_status.get(attempt_tier) is False and attempt_tier != tier:` ✓
- `proactive.py:702` — `await self._update_llm_status(failure=True)` ✓
- `proactive.py:3404` — `async def _update_llm_status(self, failure: bool)` ✓
- `config.py:163` — `llm_health_min_consecutive_healthy: int = 3` ✓

The fix architecture (dedicated background probe loop that only probes unhealthy tiers)
is correct and matches the AD-558 / BF-069 conventions.

---

## Required (must fix before building)

### 1. Bug in proposed `start_health_probe` — task field initialized inside the start method

```python
async def start_health_probe(self, ...) -> None:
    self._health_probe_task: asyncio.Task | None = None   # ← initialized here
    self._health_probe_emit = emit_fn
    self._health_probe_task = asyncio.create_task(...)    # ← then immediately overwritten
```

`stop_health_probe` and `close()` both call `getattr(self, "_health_probe_task", None)`,
which works only because the prompt acknowledges the attribute may not exist. That's
defensive coding for an avoidable bug.

**Fix:** Move the initialization to `__init__` (or a helper called from `__init__`):

```python
def __init__(self, ...):
    ...
    self._health_probe_task: asyncio.Task | None = None
    self._health_probe_emit: Callable[[str, dict], None] | None = None
```

Then `start_health_probe` only creates the task and `stop_health_probe`/`close` can call
`self._health_probe_task` directly (no `getattr` fallback needed).

This matches the user-memory anti-pattern: "Defensive `getattr(obj, 'method', None)` for
APIs defined in the same prompt."

### 2. `emit_fn` parameter is captured but never used

`start_health_probe` stores `self._health_probe_emit = emit_fn`, but `_health_probe_loop`
never reads it. The prompt's bullet "Emit `LLM_HEALTH_CHANGED` event when overall status
transitions" is unimplemented — there is no `emit_fn(...)` call anywhere in the loop body.

**Fix:** Either remove the `emit_fn` parameter and the `_health_probe_emit` attribute
(and update Section 3 to stop wiring it), OR add the actual emission call in the
transition branch:

```python
if old_overall != new_overall:
    logger.info("BF-246: ...")
    if self._health_probe_emit is not None:
        try:
            self._health_probe_emit(
                "llm_health_changed",
                {"old_status": old_overall, "new_status": new_overall, "source": "bf246_probe"},
            )
        except Exception as exc:
            logger.warning("BF-246: emit_fn raised: %s", exc)
```

If you go with emission, document why double-emit (probe + organic) is safe — the
existing `LlmHealthChangedEvent` listeners in `_wire_anomaly_window` are idempotent on
status transitions, so this should be fine, but the prompt should say so.

### 3. Section 3 wires through `runtime._emit_event` — collides with AD-680

```python
emit_fn = getattr(runtime, "_emit_event", None)
```

This perpetuates the exact private-attr access pattern AD-680 is meant to eliminate.
If AD-680 is rewritten (see that review) to promote `_emit_event` to a public method,
land BF-246 *after* AD-680 and use `runtime.emit_event` here. If AD-680 slips, leave a
`# TODO(AD-680)` marker so this site shows up when AD-680 finally lands.

### 4. Section 4 ("Cancel probe on shutdown") is under-specified

The prompt says "If `close()` already calls it (per Section 1), this is handled
automatically. Verify." Then doesn't tell the builder what to do if the verification
fails. State explicitly:

- Find the shutdown path (search for `await llm_client.close()` and `await runtime.shutdown()`).
- Confirm the test in Section 1 (`test_close_cancels_probe`) actually exercises the real
  shutdown path, not just `client.close()` in isolation.

### 5. `health_probe_interval_seconds` config location is unclear

The prompt says "find where `llm_health_min_consecutive_healthy` is configured." That
field lives on `SystemConfig` directly (config.py:163). Be explicit:

```
**File:** src/probos/config.py
**Class:** SystemConfig (around line 163, next to llm_health_min_consecutive_healthy)
Add: health_probe_interval_seconds: float = 30.0  # BF-246
```

Also add a `field_validator` matching the style of `llm_health_min_consecutive_healthy`
(must be > 0, probably >= 5 to avoid hammering a recovering proxy).

---

## Recommended

### R1. Add a "first probe is delayed" assertion to the test plan

`_health_probe_loop` calls `asyncio.sleep(interval)` *before* the first probe. That's
intentional (don't double-probe right after startup, where `__main__.py:189` already ran
a probe). State this explicitly in the prompt and add a test for it:

```python
async def test_first_probe_is_delayed():
    # Start probe with 0.05s interval, sleep 0.02s, verify check_connectivity not yet called
```

### R2. `unhealthy_tiers` calculation comparison string is loose

```python
if info["status"] not in ("operational",)
```

`("operational",)` is a one-tuple, fine but obscure. Use `!= "operational"` or define a
constant `_OPERATIONAL = "operational"` somewhere in the file. Also: `"recovering"` is a
real status — should the probe re-probe a tier in the recovering state? Document the
intent.

### R3. Surface a counter for observability

After each probe call, increment `self._probes_executed` and `self._probes_skipped` so
operators can verify the loop is alive without reading logs. Expose via
`get_health_status()`. Otherwise the only way to know the probe is working is grepping
logs for the INFO transition message, which only fires on actual recovery.

### R4. State the connection between BF-246 and the L379 fallback-skip logic

The prompt's "What This Does NOT Change" says "No changes to the fallback skip logic
(line 379)." That's correct, but the connection deserves explanation: BF-246 doesn't
need to touch line 379 because once the probe flips `_tier_status[fallback_tier]` back
to `True`, line 379's `is False` check stops triggering, and fallbacks resume
automatically. Adding one sentence to the "Why this works" section would close the
mental loop.

### R5. Config validator gap

`field_validator` on `health_probe_interval_seconds` should reject zero/negative values
to prevent CPU pinning if someone sets it to 0 in a config override.

---

## Nits

- "Use `asyncio.sleep(0.05)` for timing-sensitive tests, not wall-clock waits." — agreed,
  but state the test framework should use `pytest.mark.asyncio` and `freezegun` is *not*
  needed (the loop already uses `asyncio.sleep`, not `time.sleep`).
- Test 8 (`test_config_interval`) reads as redundant with Section 2 — Pydantic enforces
  the type at parse time. Consider replacing with a "validator rejects non-positive
  intervals" test, which has more value.

---

## Verified

- Three-tier exception handling discipline: probe loop catches `CancelledError` and exits
  cleanly. ✓
- `asyncio.create_task` (not `ensure_future`) used. ✓
- Task reference stored on the instance. ✓
- 8-test plan covers: lifecycle (1, 2, 7), behavior (3, 4, 5), observability (6),
  config (8). Solid coverage shape, but see R1 for a missing case.
- "Healthy tiers are not probed" requirement maps cleanly to Test 4.

---

## Recommended Disposition

**Approve after Required items 1-5 are addressed.** No need for another full re-review —
the diagnosis is correct, the architecture is sound, and the remaining issues are spec
hygiene rather than design. A targeted re-read of the affected code blocks is sufficient.

---

## Re-review (2026-04-29, second pass)

**Verdict:** ✅ **Approved — ready for builder.**

All five Required items resolved cleanly:

| # | Item | Resolution |
|---|---|---|
| 1 | Init bug (`_health_probe_task` initialized in start) | Step 1a moves both attributes to `__init__`. `stop_health_probe` now uses direct attribute access — no `getattr` fallback. |
| 2 | Unused `emit_fn` | Loop now calls `self._health_probe_emit(...)` inside the transition branch with try/except guarding emit_fn raising. Source field added (`"source": "bf246_probe"`). |
| 3 | Private `_emit_event` access | Section 3 uses `getattr(runtime, "emit_event", None)` — the public method. Verified `runtime.py:771` and `protocols.py:105` define `emit_event`. |
| 4 | Section 4 under-spec | Now lists explicit verification steps (search call sites, confirm shutdown path, fall back to explicit `stop_health_probe()` call if needed). |
| 5 | Config location | Pinpointed as `SystemConfig` near line 163. Field validator added with min `5.0` to prevent CPU-pinning. |

Recommended items also picked up:

- **R1 (first-probe delay):** New Test 8 (`test_first_probe_is_delayed`) covers it. Behavior documented in the "Why This Works" section.
- **R2 (status comparison):** Now uses `info["status"] != "operational"` (dropped the awkward one-tuple). "recovering" tiers are intentionally probed — documented inline.
- **R5 (validator gap):** Field validator added; new Test 9 exercises rejection of low values.
- **Double-emit safety:** Note added explaining anomaly window listener idempotency.

Verified against the live codebase (the prompt's own "Verified Against Codebase"
section):

- `runtime.emit_event` at `runtime.py:771` ✓
- `RuntimeProtocol.emit_event` at `protocols.py:105` ✓
- `_tier_status` at `llm_client.py:99`, `check_connectivity` at `llm_client.py:240`, `close` at `llm_client.py:745` ✓
- `Callable` import: `collections` is already imported (line 11); `from collections.abc import Callable` is the right addition.

### Nits remaining (non-blocking)

- The validator's error message says "to avoid hammering a recovering proxy" but accepts `5.0` exactly. Fine — just note the threshold is conservative; if telemetry shows recovery storms, raise it.
- Test 9's success-case (`SystemConfig(health_probe_interval_seconds=5.0)`) only validates that field. The full `SystemConfig` constructor likely requires other fields — make sure the test instantiates with a minimal valid config and not a bare `SystemConfig()`. Builder should match the existing pattern in `tests/test_config.py`.

**Ship it.**
