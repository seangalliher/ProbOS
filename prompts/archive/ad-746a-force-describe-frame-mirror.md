# AD-746a — Router-side latest-frame mirror for FORCE DESCRIBE (defense-in-depth)

**Status:** Ready
**Dependencies:** AD-733c-1 (latest-frame cache + `force_describe_current_frame`), AD-746 (VisionAggregator forward path)
**Estimated tests:** 2 pytest (public method populates cache; force-describe works after a router mirror with no `_handle` call)
**Issue:** #794
**Target repo:** OSS (`d:\ProbOS`)

## Problem

`VisionConsumer.force_describe_current_frame`
([`consumer.py:512`](../src/probos/perception/consumer.py)) reads its frame SHA from
`_latest_frame_by_session` / `_latest_frame_global`
([`consumer.py:533-536`](../src/probos/perception/consumer.py)). Those caches are populated
in exactly one place — `_handle` ([`consumer.py:318-321`](../src/probos/perception/consumer.py)):

```python
if isinstance(_sha, str) and _sha:
    if _session_id:
        self._latest_frame_by_session[_session_id] = (_sha, _captured_at)
    self._latest_frame_global = (_sha, _captured_at)
```

When the **VisionAggregator is wired** (the normal AD-746 path), the consumer's own
`subscribe()` is NOT called — the aggregator owns the `vision_observation` subscription,
**buffers/fuses** frames within a debounce window, and only then forwards to
`consumer._handle`. So the latest-frame cache is transitively dependent on the
aggregator's debounce/timer state machine being healthy. In **BF-323** the aggregator
deadlocked; frames were buffered but never forwarded, `_handle` was never called, the
cache stayed empty, and a Captain-initiated **FORCE DESCRIBE** silently returned `None`
(no vision LLM call, no error surfaced).

The router endpoint that admits the frame
([`routers/perception.py:131`](../src/probos/routers/perception.py),
`upload_camera_frame`) already holds `sha`, `captured_at`, and `session_id` at the moment
it accepts the upload — **before** the broadcast that feeds the aggregator. It can mirror
those into the consumer cache directly, giving FORCE DESCRIBE a path that does not depend
on the aggregator forward chain.

## Solution

Add a small **public** method on `VisionConsumer` and call it from the router endpoint
immediately **before** `intent_bus.broadcast(msg)`. The public method (Open/Closed + Law
of Demeter — no poking private attrs from the router) mirrors the same `(sha,
captured_at)` write that `_handle` already does.

This is **defense-in-depth only**: the existing `_handle` write is unchanged and remains
the primary populator on the happy path. The router mirror is an independent second
writer so the cache is warm even if the aggregator never forwards.

### Section 1 — Public mirror method on `VisionConsumer`

File: `src/probos/perception/consumer.py`

Add a public method (place it near `force_describe_current_frame`, with full type
annotations):

```python
def record_uploaded_frame(
    self, sha: str, session_id: str, captured_at: float
) -> None:
    """AD-746a: mirror the latest-frame cache at upload time.

    Defense-in-depth for FORCE DESCRIBE. The router endpoint calls this
    when it accepts a camera/screen frame, BEFORE broadcasting the
    ``vision_observation`` intent — so ``force_describe_current_frame``
    has a warm SHA even if the VisionAggregator buffers/deadlocks and
    never forwards the frame to ``_handle`` (BF-323). Idempotent with the
    ``_handle`` write: both store ``(sha, captured_at)`` keyed by session
    plus the global slot. No-op on empty sha.
    """
    if not sha:
        return
    if session_id:
        self._latest_frame_by_session[session_id] = (sha, captured_at)
    self._latest_frame_global = (sha, captured_at)
```

Rules:
- Mirror the EXACT shape of the `_handle` write (`dict[str, tuple[str, float]]` per
  session + `tuple[str, float] | None` global). Do not change `_handle`.
- No-op on falsy `sha` (matches the `_handle` guard).
- Public method — the router must NOT touch `_latest_frame_*` directly.

### Section 2 — Call the mirror from the router before broadcast

File: `src/probos/routers/perception.py`

In `upload_camera_frame`, immediately **before** the existing
`await runtime.intent_bus.broadcast(msg)` block (around
[`perception.py:241`](../src/probos/routers/perception.py)), mirror into the consumer
cache. Use the same `getattr(runtime, "vision_consumer", None)` accessor the file already
uses elsewhere ([`perception.py:293`](../src/probos/routers/perception.py),
[`perception.py:623`](../src/probos/routers/perception.py)):

```python
# AD-746a: mirror the latest-frame cache at admission time so FORCE
# DESCRIBE works even if the aggregator buffers/deadlocks and never
# forwards this frame to the consumer's _handle (BF-323).
_vc = getattr(runtime, "vision_consumer", None)
if _vc is not None:
    try:
        _vc.record_uploaded_frame(sha, session_id, captured_at)
    except Exception:
        logger.debug(
            "AD-746a: latest-frame mirror failed (session=%s, sha=%s)",
            session_id[:8], sha[:8], exc_info=True,
        )
```

Rules:
- Must run BEFORE `broadcast(msg)` so a deadlocked aggregator can never beat it.
- Tier-1 swallow with `logger.debug` — the mirror is best-effort; a failure here must
  never break frame admission (the frame is already stored at this point).
- Do NOT change the broadcast call, the params dict, or any status-code path.

## Tests

New file: `tests/test_ad746a_force_describe_mirror.py`

1. **Mirror populates cache** — construct a `VisionConsumer` (reuse the fixture pattern in
   `tests/test_*` that builds a consumer with a fake/stub runtime — find how the existing
   AD-733c-1 force-describe tests build it), call
   `record_uploaded_frame("sha123", "sess-A", 1234.5)`, assert
   `_latest_frame_by_session["sess-A"] == ("sha123", 1234.5)` and
   `_latest_frame_global == ("sha123", 1234.5)`.
2. **Force-describe reads the mirrored frame with no `_handle` call** — call
   `record_uploaded_frame(...)`, then `force_describe_current_frame(session_id="sess-A")`,
   and assert it resolves the mirrored SHA (not `None`) WITHOUT any prior `_handle`
   invocation. Mock/stub `_process` (or the LLM-describe path) so the test does not call a
   live model — assert `_process` received a synthetic `IntentMessage` whose
   `params["attachment_ref"] == "sha123"`. (Mirror whatever stubbing the existing
   force-describe tests use.)
3. (optional boundary) **Empty sha is a no-op** — `record_uploaded_frame("", "sess-A", 1.0)`
   leaves both caches untouched.

Run: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad746a_force_describe_mirror.py -v -n 0`

Use the existing `_reset_latest_frame_cache_for_tests(consumer)` helper
([`consumer.py:71`](../src/probos/perception/consumer.py)) for isolation if the fixture is
shared.

## What This Does NOT Change

- No change to `_handle` (it remains the happy-path populator).
- No change to the aggregator, the debounce/forward chain, or BF-323's separate fix.
- No change to the broadcast call, params shape, rate-limiting, or any HTTP status path.
- No change to `force_describe_current_frame`'s read logic — only its cache is now warmed
  from a second, independent writer.

## Tracking

- `PROGRESS.md` — add AD-746a CLOSED entry (bump the test count by the number of new tests).
- `decisions-era-5-unification.md` — append AD-746a: router-side latest-frame mirror so
  FORCE DESCRIBE survives an aggregator that buffers/deadlocks (BF-323 follow-up,
  defense-in-depth). Public `record_uploaded_frame` keeps the router off private attrs.

## Acceptance Criteria

1. `VisionConsumer.record_uploaded_frame(sha, session_id, captured_at)` exists, is fully
   type-annotated, no-ops on empty `sha`, and writes both the per-session and global slots.
2. `upload_camera_frame` calls it via the public method BEFORE `broadcast(msg)`, guarded so
   a failure cannot break frame admission.
3. The router never reads or writes `_latest_frame_*` directly (Law of Demeter / O/C).
4. `tests/test_ad746a_force_describe_mirror.py` passes.
5. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-31)

```
src/probos/perception/consumer.py:162-163  _latest_frame_by_session / _latest_frame_global declared
src/probos/perception/consumer.py:307-321  _handle records (sha, captured_at) BEFORE supervisor gate
src/probos/perception/consumer.py:512-536  force_describe_current_frame reads the two caches
src/probos/perception/consumer.py:71       _reset_latest_frame_cache_for_tests helper
src/probos/routers/perception.py:241       msg = IntentMessage(intent="vision_observation"); await broadcast(msg)
src/probos/routers/perception.py:293,623   getattr(runtime, "vision_consumer", None) accessor pattern
src/probos/startup/finalize.py:4148        runtime.vision_consumer = consumer
```
