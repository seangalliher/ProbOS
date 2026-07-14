# BF-666 — Evict expired force-describe frame references

**Verdict:** APPROVED FOR BUILDER
**One-line:** Make `VisionConsumer`'s latest-frame cache monotonic and compare-safe, then evict stale or missing candidates at force-describe selection and definitive failed reads so camera-off chats stop retrying reaped blobs.

**Status:** Ready to build
**Type:** Bug fix — **BF-666**; no new AD and no `DECISIONS.md` entry
**GitHub issue:** #1032 — https://github.com/seangalliher/ProbOS/issues/1032
**Exact base HEAD:** `2d595dad0df6d0a1daeed8d02d8e5d324cd483f5`
**Numbering verified:** highest shipped entries at this base are **AD-1121** and **BF-665**; issue #1032 reserves BF-666
**Dependencies:** AD-720/AD-731, AD-733/AD-733-1/AD-733a/AD-733c-1, BF-294, BF-304, AD-742f, AD-746/AD-746a, AD-978, AD-1055
**License disposition:** none — standard-library cache coordination only; no dependency or absorbed external code
**Estimated tests:** 23–27 new cases in one new BF-666 file plus one minimal fixture correction in the existing AD-746a mirror test

## Scope

Repair only the runtime-owned latest-frame cache and force-describe read path inside `VisionConsumer`. Preserve frame upload, `IntentMessage` wire shape, supervisor admission, force bypass, working-memory persistence, prompt rendering, group/DM callers, attachment retention, and the BF-304 describe singleflight.

The implementation must guarantee:

1. cache writes cannot regress a newer `(sha, captured_at)` candidate;
2. stale candidates are rejected without touching the attachment store or vision LLM;
3. absent candidates are evicted after at most one force-describe selection;
4. every session/global alias equal to the rejected complete candidate is cleared atomically;
5. a concurrent newer candidate, including the same SHA at a newer capture time, survives every clear path;
6. `exists()` is only a cheap preflight — a raced `read()` remains authoritative;
7. cancellation remains cancellation and never evicts a valid candidate merely because an in-flight describe was cancelled; and
8. concurrent force-describe calls collapse before storage selection rather than duplicating one missing-candidate attempt; and
9. fresh camera/screen uploads immediately restore normal force-describe behavior.

No UI work is authorized.

---

## Problem and verified root cause

At the exact base:

- `VisionConsumer.__init__()` owns `_latest_frame_by_session: dict[str, tuple[str, float]]` and `_latest_frame_global: tuple[str, float] | None` (`consumer.py:162–163`). They are in-memory only; `WorkingMemoryStore` persists described `VisionObservation` rows, not this latest-frame cache (`wm_store.py:26–37`, `80–120`).
- `_handle(msg)` records a non-empty `attachment_ref` in the session and global slots before `_process()` and before supervisor admission (`consumer.py:351–369`). The low-novelty behavior is intentional: force-describe must still see the latest captured frame even when the supervisor does not spend an ambient LLM call.
- `record_uploaded_frame(self, sha, session_id, captured_at) -> None` is the public upload-time second writer used by `upload_camera_frame()` before broadcast (`consumer.py:627–644`; `routers/perception.py:247`). This keeps force-describe alive even if the AD-746 aggregator buffers or fails to forward.
- Both writers overwrite unconditionally. A delayed `_handle()` of an older buffered frame can therefore replace a newer upload-time mirror. AD-746 same-source replacement and debounce make delayed delivery a real path (`aggregator.py:96–151`, `200–210`).
- `force_describe_current_frame(self, session_id: str | None = None, *, timeout_s: float = 4.0) -> str | None` selects the requested session candidate when present, otherwise the global candidate, and immediately calls `_process()` under `asyncio.wait_for()` (`consumer.py:560–625`). It performs no age or attachment validation and never clears a failed candidate.
- `_process(self, msg)` gets the shared store and wraps `await store.read(sha)` in a broad `except Exception`, logging `WARNING` with traceback and returning (`consumer.py:381–420`). Consequently an expected retention deletion is treated as an unexpected storage failure and the stale cache remains available to every later chat.
- The only production force-describe callers are the 1:1 DM path (`routers/agents.py:2981`) and the once-per-group-round helper (`routers/thread_fanout.py:345`). Neither passes a session ID, so current production normally selects the global slot; the public API's session-first/global-fallback contract remains tested and must be preserved.
- The only production `record_uploaded_frame()` caller is the camera/screen upload endpoint (`routers/perception.py:247`).
- `AttachmentStore` publicly exposes `read`, `exists`, `get_path`, `size`, `unlink`, `list_by_origin`, and `total_size_bytes` (`attachments/store.py:31–87`). BF-666 needs only public `exists()`/`read()`; it must not inspect `FilesystemAttachmentStore._index`, `_root`, `_lock`, or any private implementation detail.
- `FilesystemAttachmentStore.exists()` and `read()` each resolve the on-disk file independently (`filesystem_store.py:273–281`). Therefore `exists() == True` cannot prove the later read will succeed: `AttachmentReaper` may unlink in between. The authoritative missing signal is `FileNotFoundError` from `read()`.
- `AttachmentReaper` removes `origin="perception_frame"` entries older than `PerceptionConfig.frame_retention_seconds` and owns its task reference/start/stop lifecycle (`reaper.py:39–105`, `145–166`). `frame_retention_seconds` defaults to and is actively configured as 300 seconds (`config.py:2624`; `config/system.yaml:1315`). There is no reason to add a reaper callback or increase retention.
- `PerceptionConfig.prompt_freshness_seconds` defaults to 120 seconds (`config.py:2681`). `VisionWorkingMemory.render_for_prompt(..., freshness_s=...)` already turns a described observation older than that into the BF-294 camera-off sentinel (`working_memory.py:100–131`), but that render guard does not clear the separate latest-frame cache. Thus a camera-off chat can render honestly while force-describe still retries the expired blob first.
- BF-304's `_describe_lock` is the only lock currently in `VisionConsumer`; it protects LLM singleflight, not the latest-frame cache (`consumer.py:124`, `451–470`). It is acquired only after the initial attachment read, so it cannot prevent two concurrent force calls from selecting/preflighting the same missing candidate. BF-666 must not broaden or re-enter it; it needs separate cache ownership and a non-queuing force-call guard.

### Live evidence, reverified read-only on 2026-07-14

For SHA `832af3ee6406ab4f7495cad3286746356f5ece71d4be7d6d288ad9ee07e651bf`:

- the live log records supervisor low-novelty drop at 10:57:47;
- the current rotating log contains **19** `AttachmentStore.read failed sha=832af3ee` warnings from 11:29:26 through 18:10:49, each with a `FileNotFoundError` traceback;
- the attachment directory contains zero files whose basename is the full SHA;
- `.index.json` does not contain the full SHA (697 other entries at inspection time); and
- read-only SQLite query `SELECT count(*) FROM vision_observations WHERE attachment_ref=?` returned `0` from `%LOCALAPPDATA%\ProbOS\data\perception_wm.db` (51 total rows).

This corroborates the issue's core claim: the only demonstrated surviving reference is the live process's in-memory latest-frame cache. The exact warning count in the issue (16 through 16:34) was a snapshot; the same stale cache produced 19 warnings by 18:10. Counts are evidence, not a contract.

### Exact live signatures at the build base

```text
class VisionConsumer

def __init__(
    self,
    runtime: Any,
    *,
    min_interval_seconds: float = 5.0,
    novelty_threshold: float = 0.15,
    baseline_max_age_seconds: float = 30.0,
    working_memory_capacity: int = 8,
    vision_tier: str = "vision",
    vision_fast_tier: str = "vision_fast",
    max_describe_tokens: int = 220,
    describe_timeout_s: float = 30.0,
    supervisor_strategy_name: str = "ahash",
) -> None

async def _handle(self, msg: IntentMessage) -> IntentResult | None
async def _process(self, msg: IntentMessage) -> None

async def force_describe_current_frame(
    self,
    session_id: str | None = None,
    *,
    timeout_s: float = 4.0,
) -> str | None

def record_uploaded_frame(
    self,
    sha: str,
    session_id: str,
    captured_at: float,
) -> None

AttachmentStore.read(self, content_hash: str) -> bytes
AttachmentStore.exists(self, content_hash: str) -> bool
```

BF-666 preserves every public signature above. It may add one private keyword-only `cache_candidate: _LatestFrameCandidate | None = None` parameter to `_process()` so `_handle()` can carry the exact fallback timestamp it generated when inbound `captured_at` is absent. Existing one-positional-argument private callers remain valid. All other additions are module-private cache types/helpers and private state inside `VisionConsumer`.

---

## Issue-contract resolutions and corrections

These are live-code clarifications; they do not weaken #1032.

1. **Fix both selection and authoritative read failure.** Selection must validate age and public `exists()` before `_process()` to avoid routine stale work. `_process()` must still catch `FileNotFoundError` separately and compare-clear, because `exists()` then `read()` is a TOCTOU race and ambient `_handle()` also calls `_process()` without force-describe preflight.
2. **The post-process existence check is defense-in-depth, not proof of successful processing.** `_process()` currently returns `None` for success, low novelty/busy/empty LLM, and read failure. Force-describe therefore cannot infer why it returned. Rechecking `exists()` after bounded `_process()` catches deletion after a successful read/while later work ran; the separate `_process()` `FileNotFoundError` branch closes deletion before/during the initial read.
3. **Do not cancel a valid in-flight describe.** If the blob disappears after bytes have already been loaded, the current `_process()` can finish from those local bytes. A post-process `exists() == False` clears only future cache selection; it does not cancel or undo the completed observation/episode. Timeout still cancels through `asyncio.wait_for()` exactly as today and must not be converted into stale eviction unless independent stale/missing evidence exists.
4. **Cache candidate identity is the complete tuple.** The canonical compare token is `tuple[str, float]` (`(sha, captured_at)`), not SHA alone. Content-addressing means identical bytes legitimately reuse a SHA; a later capture with the same SHA must remain current.
5. **`captured_at` is wall-clock frame time, not index `written_at`.** Freshness uses `time.time() - captured_at`; it must not query attachment metadata. A future timestamp has age 0 via `max(0.0, ...)`, matching `VisionWorkingMemory`'s existing age guard.
6. **No persisted WM deletion belongs in BF-666.** A stale latest-frame candidate may never have produced a `VisionObservation` (the headline low-novelty frame did not). Existing described WM rows carry historical descriptions and already render through `prompt_freshness_seconds`; BF-666 clears only the latest-frame selection cache.
7. **No new supervisor lifecycle exists in `VisionConsumer`.** The consumer has no `start()`/`stop()` task. Attachment reaping, AD-746 aggregator timers, and perception-mode watchdogs have separate owners. BF-666 adds no task and no shutdown wiring.
8. **Lifecycle audit found a pre-existing unrelated gap.** `VisionAggregator.stop()` exists and holds/cancels timer references, but current runtime shutdown contains no `vision_aggregator.stop()` call. This is not causal to stale force-describe refs and is outside issue/allowlist; do not fold it into BF-666. Surface only if the BF-666 implementation unexpectedly requires lifecycle edits (it should not).
9. **The issue's “16 warnings” is not current final count.** Read-only recheck found 19 for the same SHA in the current log. No acceptance criterion should pin an exact production count.
10. **An inbound frame may omit `captured_at`.** `_handle()` currently synthesizes a wall-clock fallback for its cache write, but `_process()` cannot independently call `time.time()` and reconstruct the same tuple. Carry the exact incoming candidate privately from `_handle()`; otherwise the definitive missing-read clear can miss by microseconds.
11. **The existing AD-746a mirror test has an obsolete fixture, not a production contract.** It seeds malformed SHA `"sha123"`, stubs `_process()`, and has no stored blob. Public `exists()` correctly rejects that preflight before the stub. Update that one test to use a valid 64-hex SHA in a real `FilesystemAttachmentStore`; do not add a production bypass for malformed/test-only candidates.
12. **Compare-clear alone does not collapse simultaneous stale calls.** Two force calls can snapshot before the first asynchronous `exists()` returns. Add a separate bounded-acquire force-call lock around selection through postcheck; a concurrent caller returns `None` after at most the tiny permit budget. Do not serialize it into an unbounded queue and do not reuse `_describe_lock`.

---

## Pinned design decisions

### DD-1 — Typed complete candidate; synchronous cache lock plus non-queuing force guard

Add a module-private typed alias:

```text
_LatestFrameCandidate = tuple[str, float]
```

Use it for `_latest_frame_by_session`, `_latest_frame_global`, and every private helper. Do not introduce a public model/protocol or change the tuple stored by existing tests/callers.

Add exactly:

```text
from contextlib import asynccontextmanager
from threading import Lock

self._latest_frame_lock = Lock()
self._force_describe_lock = asyncio.Lock()
```

`_latest_frame_lock` owns only the two latest-frame slots. `_force_describe_lock` collapses concurrent public force calls across selection/preflight/process/postcheck. Neither is the BF-304 `_describe_lock`.

Rules:

- hold `_latest_frame_lock` only for in-memory lookup/write/clear;
- never await `AttachmentStore.exists/read`, `_process`, LLM, sleep, or cancellation cleanup while holding it;
- `record_uploaded_frame()` remains synchronous, so the shared cache lock is the pinned standard-library `threading.Lock`; no async public-signature churn is permitted;
- the synchronous critical sections are bounded dictionary operations only, so they do not block on I/O or other awaits;
- add a private `@asynccontextmanager async def _force_describe_permit(self) -> AsyncIterator[bool]` (import `AsyncIterator` from `typing`): use `asyncio.wait_for(self._force_describe_lock.acquire(), timeout=0.001)` as a bounded non-queueing acquire; on timeout yield `False`; on success yield `True` and release in `finally`;
- `force_describe_current_frame()` enters that permit first and returns DEBUG/`None` when not acquired; when acquired, hold it through the post-process existence check and WM result lookup;
- the tiny timeout closes the `locked()`-check/acquire scheduling race without allowing meaningful queueing; tests use an already-held permit/event, never timing assumptions;
- `_force_describe_lock` is intentionally held across awaits; the bounded permit preserves BF-304's best-snapshot/drop-not-queue policy while moving duplicate suppression before storage access;
- cancellation inside the force-call context releases `_force_describe_lock` and re-raises;
- `_reset_latest_frame_cache_for_tests()` must clear through the same lock or call a private reset helper, not bypass the new ownership rule.

### DD-2 — Centralize monotonic writes for both producers

Add one private synchronous helper, fully annotated, with semantics equivalent to:

```text
def _record_latest_frame(
    self,
    sha: str,
    session_id: str,
    captured_at: float,
) -> _LatestFrameCandidate | None
```

It must:

1. no-op for empty/non-string SHA (preserve `record_uploaded_frame("")` behavior);
2. normalize with `float(captured_at)` and reject non-finite (`NaN`, `+/-Inf`) timestamps before entering the lock; `_handle()` keeps its existing catch/log-and-degrade, while direct `record_uploaded_frame()` simply no-ops on invalid time rather than poisoning ordering;
3. construct `candidate = (sha, normalized_captured_at)` before entering the lock;
4. under the cache lock, update the named session slot only when `session_id` is non-empty and either no candidate exists or `captured_at >= current[1]`;
5. independently update the global slot only when absent or `captured_at >= global[1]`;
6. preserve arrival-order last-write-wins at equal `captured_at` because the issue requires “at least as new”; and
7. return the normalized incoming candidate even when monotonic comparison leaves newer cache state untouched; return `None` for an empty/invalid SHA or invalid/non-finite time; and
8. never read the attachment store, supervisor, working memory, or clock.

Both `_handle()` and `record_uploaded_frame()` must delegate to this helper. `_handle()` keeps its current defensive parse/log behavior, still records before supervisor admission, retains the returned exact incoming candidate, and passes it to `_process(msg, cache_candidate=...)`. This is load-bearing when `captured_at` was absent and `_handle()` generated the fallback. No router edit is needed.

The session and global decisions are independent: an incoming frame may be newest for one session but older than another session's global candidate. It may update the session slot without regressing global.

### DD-3 — Snapshot and compare-and-clear are atomic across all aliases

Add two private synchronous helpers plus the DD-1 async permit helper:

```text
def _select_latest_frame(
    self,
    session_id: str | None,
) -> _LatestFrameCandidate | None

def _clear_latest_frame_if_matches(
    self,
    candidate: _LatestFrameCandidate,
) -> int

@asynccontextmanager
async def _force_describe_permit(self) -> AsyncIterator[bool]
```

`_select_latest_frame()` must preserve exact selection semantics under the lock:

- if a non-empty `session_id` has a session slot, return it;
- otherwise return the global slot;
- otherwise return `None`.

`_clear_latest_frame_if_matches()` must, in one lock critical section:

1. remove **every** `_latest_frame_by_session` item whose complete tuple equals `candidate` (session aliasing may span multiple sessions);
2. set `_latest_frame_global = None` only when its complete tuple equals `candidate`;
3. return the total number of session/global slots removed.

Never clear by SHA alone. Never clear by session ID alone. Never clear all cache state. This is the compare-before-act barrier that protects:

- a newer different-SHA replacement;
- a same-SHA/newer-`captured_at` replacement;
- a global replacement written while an older session candidate is in flight; and
- aliases that still point to the exact stale candidate.

### DD-4 — Effective candidate age is bounded by retention and prompt freshness

Add a private helper such as:

```text
def _force_describe_max_age_seconds(self) -> float
```

Read the already injected real config from `self._runtime.config.perception`:

- `retention = float(frame_retention_seconds)`;
- `freshness = float(prompt_freshness_seconds)`;
- if `freshness <= 0`, return `retention`;
- otherwise return `min(retention, freshness)`.

`frame_retention_seconds` is Pydantic-bounded positive in production, but defend against incomplete test/runtime config without inventing a new setting: missing/invalid values use the existing model defaults (300 retention, 120 freshness). A non-positive retention from a malformed stub must not create infinite freshness; clamp/fall back to 300.

A candidate is stale only when:

```text
max(0.0, time.time() - captured_at) > effective_max_age
```

Use the existing strict `>` behavior from `VisionWorkingMemory.render_for_prompt()`; exactly on the boundary remains eligible.

On stale selection:

- call `_clear_latest_frame_if_matches(candidate)`;
- log at DEBUG only when one or more aliases were removed, with reason/age/max-age and SHA prefix;
- return `None` before store/LLM/WM work.

### DD-5 — Force-describe validates on selection, failed read, and post-process

Restructure `force_describe_current_frame()` in this order:

1. enter `async with self._force_describe_permit() as acquired`;
2. if `acquired` is false, DEBUG + return `None` without cache/store/LLM work; otherwise continue under the permit (released in `finally`);
3. atomically snapshot the session-first/global-fallback candidate;
4. empty cache → existing DEBUG/no-op behavior;
5. compute age and reject/compare-clear stale candidate per DD-4;
6. obtain the shared store through the existing accessor path; do not inspect private store state;
7. `await store.exists(sha)` as a cheap preflight:
   - `False` → compare-clear all exact aliases, DEBUG only if removed, return `None`;
   - `FileNotFoundError` (a legal absence-shaped fake/backend outcome) → same as `False`;
   - unexpected exception → WARNING with what/why/next, preserve candidate, return `None`;
   - `CancelledError` → re-raise, preserve candidate;
8. build the existing synthetic `IntentMessage` unchanged (`force=True`, ref-only, session/source/captured fields unchanged);
9. run bounded `await asyncio.wait_for(self._process(synthetic, cache_candidate=candidate), timeout=timeout_s)`;
10. preserve existing timeout WARNING and return `None`; do not clear solely for timeout;
11. explicitly re-raise `asyncio.CancelledError` before any broad exception branch;
12. preserve unexpected `_process` exception WARNING and candidate;
13. after `_process()` returns normally, call `await store.exists(sha)` again:
    - `False`/`FileNotFoundError` → compare-clear the original candidate; this closes reaping after the initial read or during later processing;
    - unexpected exception → WARNING, preserve candidate; the describe result may still be returned from WM;
    - cancellation → re-raise;
14. if the postcheck proves absence, return `None` after clearing; do not return an older same-SHA WM description, but do not delete/undo an observation that completed from already-loaded bytes;
15. otherwise return the just-written observer WM description using the existing exact-SHA check.

Important: selection preflight is both a performance guard and expected-absence classifier. It is not the TOCTOU proof. DD-6 is mandatory.

### DD-6 — `_process()` owns definitive initial-read absence handling

Change the private signature compatibly:

```text
async def _process(
  self,
  msg: IntentMessage,
  *,
  cache_candidate: _LatestFrameCandidate | None = None,
) -> None
```

At the initial `AttachmentStore.read(sha)` in `_process()` only:

```text
except asyncio.CancelledError:
    raise
except FileNotFoundError:
    removed = self._clear_latest_frame_if_matches((sha, captured_at))
    if removed:
        logger.debug(... expected absence ...)
    return
except Exception:
    logger.warning(... unexpected store failure; cache retained ..., exc_info=True)
    return
```

Requirements:

- use the exact `cache_candidate` supplied by `_handle()`/force-describe. For direct legacy `_process(msg)` callers, derive a candidate only when `msg.params["captured_at"]` is explicitly present and valid; do not synthesize a fresh wall-clock tuple that cannot match a prior cache write;
- compare-clear by the complete `(sha, captured_at)` candidate;
- expected absence emits no WARNING and no traceback;
- DEBUG is emitted only when at least one matching alias was actually removed (an ambient read may lose a blob whose cache was already replaced; that is a silent no-op);
- unexpected backend/storage errors continue to WARN with traceback and retain the candidate for a later transient recovery;
- a missing read produces no supervisor mutation, LLM call, WM append, `_last_observation` update, identity work, or episode;
- `CancelledError` must propagate and must not clear the cache;
- do not add absence handling to `_describe()`/`vision_dispatch.py` in this BF. The authoritative first read occurs before supervisor/LLM and is the scope's correct eviction seam.

This protects ambient `_handle()` as well as force-describe, while force-describe preflight prevents routine expected misses from entering `_process()` at all.

### DD-7 — Preserve low-novelty, upload, singleflight, and fallback semantics

The following are non-negotiable:

- `_handle()` still records the candidate **before** supervisor admission; low-novelty/throttled/never-strategy frames remain force-describable while fresh.
- `record_uploaded_frame()` remains public, synchronous, fully annotated, no-op on empty SHA, and called by the upload router unchanged.
- AD-746 session/global behavior remains: requested session first; absent session falls back global; no session uses global.
- BF-304's `_describe_lock` and “drop busy frame, do not queue” behavior are unchanged.
- A stale/missing candidate must not append or reanimate `VisionWorkingMemory`; existing stale persisted rows still render through AD-1055's sentinel.
- A valid fresh uploaded frame following eviction becomes the new session/global candidate and force-describes normally.
- No cache clear occurs for low novelty, busy singleflight, empty LLM response, timeout, unexpected store error, or caller cancellation unless a separate age/absence check independently proves the original candidate stale/missing.
- Concurrent force calls wait only for the tiny permit budget, never queue behind the full describe; only the admitted call may touch storage/process the selected candidate.

### DD-8 — No lifecycle, storage, or cross-layer redesign

BF-666 adds no task, callback, reaper subscription, polling loop, database column, retention field, or router API. It does not modify `AttachmentStore`, `FilesystemAttachmentStore`, `AttachmentReaper`, `WorkingMemoryStore`, startup, shutdown, aggregator, config, or callers.

Use the existing public storage seam only. Do not reach `store._index`, `store._root`, `store._lock`, `runtime._attachment_store`, or `_ATTACHMENT_STORE_CACHE` from production code.

---

## Ordered implementation

### Section 1 — Add typed cache ownership helpers

**Modify:** `src/probos/perception/consumer.py`

1. Add `_LatestFrameCandidate` and one private cache lock in `__init__()`.
2. Add the separate `_force_describe_lock` plus `_force_describe_permit()` bounded non-queuing guard.
3. Add `_record_latest_frame()`, `_select_latest_frame()`, `_clear_latest_frame_if_matches()`, and `_force_describe_max_age_seconds()` with full annotations.
4. Make `_reset_latest_frame_cache_for_tests()` honor the cache-lock ownership.
5. Do not change public exports or protocols.

### Section 2 — Route both writers through the monotonic helper

**Modify:** `src/probos/perception/consumer.py`

1. Replace `_handle()`'s direct session/global assignments with `_record_latest_frame()`.
2. Carry the exact returned candidate into `_process(..., cache_candidate=...)`.
3. Replace `record_uploaded_frame()`'s direct assignments with the same helper.
4. Keep `_handle()` cache-before-supervisor ordering and parsing honest-degrade.
5. Keep upload router code unchanged.

### Section 3 — Add selection freshness and public existence preflight

**Modify:** `src/probos/perception/consumer.py`

1. Snapshot through `_select_latest_frame()`.
2. Guard the whole public force call with `_force_describe_permit()` semantics.
3. Reject/compare-clear age-expired candidates before store work.
4. Call public `store.exists()` and classify expected absence vs unexpected store error.
5. Never hold the cache lock across these awaits.
6. Keep the synthetic message fields and bounded `_process()` behavior unchanged apart from the private candidate keyword.

### Section 4 — Make initial read absence expected and compare-safe

**Modify:** `src/probos/perception/consumer.py`

1. Add the backward-compatible private `cache_candidate` keyword and ensure `_process()` has the exact incoming tuple before read.
2. Add explicit `CancelledError`, `FileNotFoundError`, then broad `Exception` ordering.
3. Compare-clear every exact alias on missing read.
4. DEBUG only on a real removal; unexpected errors still WARN and preserve.

### Section 5 — Close the post-read retention race

**Modify:** `src/probos/perception/consumer.py`

1. After `_process()` returns normally, recheck public `store.exists()`.
2. Compare-clear the original candidate if the blob has disappeared.
3. Return `None` on proven post-process absence without deleting/undoing an observation produced from already-loaded bytes.
4. Preserve cancellation, timeout, and WM return behavior.

### Section 6 — Add one focused real-store regression file

**Create:** `tests/test_bf666_force_describe_cache_expiry.py`

Use a real `SystemConfig`, real `FilesystemAttachmentStore(tmp_path)`, real `VisionConsumer`, and real `VisionWorkingMemory` where relevant. Resolve the shared store through the existing test seam (`ProbOSRuntime.attachment_store` on a real runtime, or the established `_get_attachment_store(runtime)` fixture helper), then instrument only its **public** `exists`/`read`/`unlink` methods. Do not patch the helper itself, seed `_ATTACHMENT_STORE_CACHE`, set a phantom/private runtime store field, or reach any private store attribute. Use small typed `_Fake*`/delegating callables only for precise failure/race injection; do not use `MagicMock` to invent `AttachmentStore` methods. Every fake async method must remain async.

Required failing-before/passing-after tests (names may be tightened, behavior may not):

1. `test_stale_by_prompt_freshness_clears_all_aliases_without_store_or_llm` — same candidate in two sessions + global; age over prompt freshness but under retention; assert every exact alias cleared, `exists/read/_process/LLM` untouched, returns `None`.
2. `test_prompt_freshness_disabled_uses_retention_bound` — `prompt_freshness_seconds=0`; candidate younger than retention remains eligible and describes; candidate older than retention clears without store/LLM (parameterize or split if clearer).
3. `test_missing_preflight_clears_session_and_global_without_warning` — real store missing; session alias + global same tuple; no WARNING/traceback and no LLM/WM write.
4. `test_second_call_after_missing_is_silent_noop_without_store_reread` — counting store: first `exists()` miss; second call sees empty cache; exact total store selections remains one.
5. `test_session_global_alias_clear_removes_all_matching_sessions_only` — two matching session aliases + global clear; a nonmatching session candidate survives.
6. `test_concurrent_newer_different_sha_survives_missing_clear` — pause preflight/result, write a newer candidate, resume missing path; old clear removes no newer slot.
7. `test_same_sha_newer_capture_survives_missing_clear` — same as above with identical SHA and newer `captured_at`; complete-tuple compare is load-bearing.
8. `test_retention_toctou_exists_true_then_read_missing_clears_once` — fake/delegating store reports `exists=True`, then `read()` raises `FileNotFoundError`; `_process()` clears exact aliases, emits no WARNING/traceback, second chat does not reread.
9. `test_post_process_reap_clears_original_candidate_without_undoing_observation` — real/delegating store survives initial preflight/read, is removed during/after `_process`, postcheck false; the force call returns `None`, an already-written current WM description may remain, and future cache selection is empty. Include/assert that a newer tuple written before the postcheck clear survives.
10. `test_out_of_order_handle_cannot_regress_session_or_global_cache` — upload/record newer candidate, then deliver older `_handle()` through a real supervisor seeded to produce low novelty (no ambient LLM); session and global remain newer.
11. `test_older_other_session_updates_its_session_without_regressing_global` — proves session/global monotonic comparisons are independent.
12. `test_equal_captured_at_is_last_write_wins` — issue says “at least as new”; same timestamp replacement updates session/global.
13. `test_unexpected_exists_error_warns_and_preserves_candidate` — store `exists()` raises non-`FileNotFoundError`; one contextual WARNING, cache unchanged, no `_process`/LLM.
14. `test_unexpected_read_error_warns_and_preserves_candidate` — preflight true, read raises `OSError`/backend error; one contextual WARNING with traceback, cache unchanged.
15. `test_force_describe_cancellation_propagates_and_preserves_candidate` — parameterize or split cancellation while preflight awaits and while `_process()` awaits; in each branch `CancelledError` reaches caller, the candidate remains, `_force_describe_lock` is released/reusable by a later call, and no task leaks.
16. `test_stale_camera_off_candidate_cannot_reanimate_working_memory` — seed a stale candidate and a stale/persisted-style WM observation; force-describe returns `None`, does not append/LLM, and `render_for_prompt(freshness_s=...)` remains the BF-294 camera-off sentinel.
17. `test_fresh_uploaded_frame_after_eviction_restores_force_describe` — evict/miss an old candidate, write a fresh real blob through `record_uploaded_frame()`, force-describe returns the new description and caches point to the fresh tuple.
18. `test_fresh_low_novelty_frame_remains_cached_without_llm` — use the real supervisor with a seeded identical baseline so `_handle()` produces `reason="low_novelty"`; the complete fresh candidate remains in session/global cache and no ambient LLM call occurs. Existing force-success tests prove that a fresh cached candidate is force-describable. This protects AD-733c-1 cost discipline without requiring the same real supervisor baseline to describe one frame twice.
19. `test_empty_cache_with_none_or_empty_session_is_silent_noop` — parameterize `session_id` as `None` and `""`; no session/global candidate, no store/LLM work and no WARNING.
20. `test_none_session_and_missing_requested_session_preserve_global_fallback` — exercise both `session_id=None` and a requested session absent from the map against a fresh global candidate.
21. `test_concurrent_force_calls_drop_second_before_store_selection` — event-gate the admitted call's preflight; a concurrent call receives `acquired=False`, returns promptly, does not queue, and does not increment `exists/read/LLM` counts. Also prove cancellation while waiting in `_force_describe_permit()` propagates and does not over-release the holder's lock.
22. `test_handle_without_captured_at_uses_one_exact_fallback_candidate_for_missing_clear` — valid missing SHA, no inbound `captured_at`; `_handle()` passes its generated candidate so the definitive read failure clears it exactly and quietly.
23. `test_non_finite_captured_at_cannot_poison_cache_ordering` — `NaN`/`+Inf`/`-Inf` through the public writer are no-ops; a previously fresh session/global candidate remains selectable and age math stays finite.

Use Events/barriers for concurrency and cancellation. Do not rely on arbitrary timing sleeps. Tests that directly seed private cache tuples are acceptable inside this focused regression file, but production must use helpers and public storage APIs.

### Section 7 — Correct the one obsolete AD-746a fixture

**Modify:** `tests/test_ad746a_force_describe_mirror.py`

Update only `test_force_describe_resolves_mirrored_sha_without_handle` (and minimal helper/import plumbing it needs):

- use `tmp_path`, a real `FilesystemAttachmentStore`, and a valid 64-hex content hash whose blob is actually stored before force-describe;
- keep `_process()` stubbed so the test remains about the upload-time mirror and synthetic message rather than a live model;
- make the async stub signature fully annotated, accept/assert the new private `cache_candidate` keyword, and verify it equals `(sha, captured_at)`;
- retain the headline: no `_handle()` call is required and the synthetic message carries the mirrored SHA with `force=True`.

Do not weaken production preflight for `"sha123"`, and do not change the other two AD-746a tests' behavior.

### Section 8 — Tracking and commit only after gates, only when directed

Current BF-659/661/662/664/665 convention commits the two prompt files in place beside implementation and updates `PROGRESS.md`; it does not archive the pair, edit `DECISIONS.md`, or add a roadmap row.

If and only if the orchestrator explicitly directs closeout after green gates:

1. prepend one concise BF-666 shipped entry to `PROGRESS.md` with exact focused/blast counts and #1032;
2. leave `docs/development/roadmap.md`, all era files, and `DECISIONS.md` untouched;
3. keep both BF-666 prompt files at their current `prompts/` paths;
4. stage only the allowlist;
5. perform the deletion sanity check from the execution document; and
6. commit exactly:

```text
BF-666: evict expired force-describe frame refs (closes #1032)
```

Do not push, close/edit/comment on #1032, or otherwise mutate GitHub unless the orchestrator separately directs it. BF-665 CI state is unrelated to implementation semantics; if it finishes red and changes the base, stop for re-verification rather than folding a BF-665 repair into BF-666.

---

## Exact file allowlist

### Production — modify exactly one

- `src/probos/perception/consumer.py`

### Tests — create exactly one and modify exactly one

- `tests/test_bf666_force_describe_cache_expiry.py` (NEW)
- `tests/test_ad746a_force_describe_mirror.py` — replace the obsolete malformed/missing-store force fixture with a valid real-store candidate; no behavior weakening

### Architect documents — already present before Builder edits; include in an authorized final commit, do not rewrite/archive

- `prompts/bf-666-perception-force-describe-cache-expiry.md`
- `prompts/bf-666-perception-force-describe-cache-expiry-execution.md`

### Conditional closeout only

- `PROGRESS.md`

No other source, test, config, workflow, dependency, UI, tracker, roadmap, decision, archive, log, data, or issue file is authorized. Every other existing test remains unchanged. Any additional obsolete-contract edit is a hard stop for Architect authorization rather than an implicit allowlist expansion.

### Reference/run only

- `.github/copilot-instructions.md`
- `prompts/_TEMPLATE.md`
- `src/probos/attachments/store.py`
- `src/probos/attachments/filesystem_store.py`
- `src/probos/attachments/reaper.py`
- `src/probos/config.py`
- `config/system.yaml`
- `src/probos/perception/aggregator.py`
- `src/probos/perception/supervisor.py`
- `src/probos/perception/working_memory.py`
- `src/probos/perception/wm_store.py`
- `src/probos/routers/perception.py`
- `src/probos/routers/agents.py`
- `src/probos/routers/thread_fanout.py`
- `src/probos/runtime.py`
- `src/probos/startup/finalize.py`
- `src/probos/startup/shutdown.py`
- `tests/test_ad720_attachment_store.py`
- `tests/test_ad733_frame_endpoint.py`
- `tests/test_ad733_2_screen_source.py`
- `tests/test_camera_frame_origin.py`
- `tests/test_ad733a_vision_consumer.py`
- `tests/test_ad733c1_force_describe.py`
- `tests/test_ad742f_wm_persistence.py`
- `tests/test_ad746_vision_aggregator.py`
- `tests/test_ad746a_force_describe_mirror.py`
- `tests/test_ad978_group_perception.py`
- `tests/test_bf617_shared_meeting_vision.py`
- `tests/test_bf620_shared_meeting_vision_restart.py`
- `tests/test_bf624_stale_meeting_vision_refresh.py`
- `tests/test_attachment_reaper.py`

---

## Test commands

Run from `D:\ProbOS`. Use no live model endpoint and no broad suite.

### Focused BF-666 gate

```powershell
Set-Location 'D:\ProbOS'
$gateDir = Join-Path $env:TEMP ("probos_bf666_focused_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $gateDir | Out-Null
$env:PROBOS_DATA_DIR = $gateDir
$env:PROBOS_EMBEDDINGS = 'local'
try {
    & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_bf666_force_describe_cache_expiry.py tests/test_ad733c1_force_describe.py tests/test_ad746a_force_describe_mirror.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning
} finally {
    Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

### Perception/attachment blast-radius gate

```powershell
Set-Location 'D:\ProbOS'
$gateDir = Join-Path $env:TEMP ("probos_bf666_blast_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $gateDir | Out-Null
$env:PROBOS_DATA_DIR = $gateDir
$env:PROBOS_EMBEDDINGS = 'local'
try {
    & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_bf666_force_describe_cache_expiry.py tests/test_ad720_attachment_store.py tests/test_ad733_frame_endpoint.py tests/test_ad733_2_screen_source.py tests/test_camera_frame_origin.py tests/test_ad733a_vision_consumer.py tests/test_ad733c1_force_describe.py tests/test_ad742f_wm_persistence.py tests/test_ad746_vision_aggregator.py tests/test_ad746a_force_describe_mirror.py tests/test_ad978_group_perception.py tests/test_bf617_shared_meeting_vision.py tests/test_bf620_shared_meeting_vision_restart.py tests/test_bf624_stale_meeting_vision_refresh.py tests/test_attachment_reaper.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning
} finally {
    Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

Do not run `tests/` broadly, use xdist/`-n auto`, contact a live vision model, or inspect/mutate the operator's live `%LOCALAPPDATA%\ProbOS\data` during Builder tests.

---

## Acceptance criteria

1. `_handle()` and `record_uploaded_frame()` share one typed monotonic cache-write helper; finite incoming `captured_at >= current` replaces, older input cannot regress session/global, and non-finite timestamps cannot poison cache state.
2. Session and global monotonic decisions are independent; an older frame from another session may warm its session slot without regressing the newer global slot.
3. Force-describe preserves session-first/global-fallback selection and snapshots one complete `(sha, captured_at)` candidate atomically.
4. Effective max age is retention when prompt freshness is disabled, otherwise `min(retention, prompt_freshness)`; an over-age candidate is compare-cleared before any store/LLM/WM work.
5. Compare-clear removes every session alias and global slot equal to the complete candidate in one critical section, while preserving every nonmatching/newer candidate.
6. A same-SHA/newer-capture replacement survives every stale/missing clear path.
7. Public `AttachmentStore.exists()` preflight avoids routine missing reads, but a raced `read()` `FileNotFoundError` still compare-clears through `_process()`; no exists-then-read correctness claim remains.
8. Expected absence emits no WARNING/traceback. DEBUG is emitted only when an exact cache entry was actually removed.
9. Unexpected store/backend errors WARN with context and traceback, retain the candidate, and honestly degrade to `None` without LLM/WM mutation.
10. A post-process disappearance clears only the original candidate for future calls and does not cancel/undo an observation produced from already-loaded bytes.
11. A stale/reaped candidate is selected for attachment work at most once; the next DM/group round is a silent cache-empty no-op with no reread or vision call.
12. Concurrent force calls collapse through the cancellation-safe 1ms permit before storage selection: the second call never waits behind the full describe or touches store/LLM, while the admitted call retains BF-304's existing describe behavior.
13. BF-304 `_describe_lock` remains unchanged: no valid in-flight describe is cancelled or queued by cache eviction logic.
14. Cancellation while acquiring the force permit, at preflight, or in `_process()` propagates `CancelledError`, retains a still-valid candidate, never over-releases the force lock, releases it when owned, and leaves no task/lock leak.
15. Low-novelty/throttled fresh frames still populate the cache before supervisor admission without an ambient LLM call, including when inbound `captured_at` is absent; fresh cached candidates retain the existing force-describe path.
16. Uploaded camera/screen frames still warm session/global cache through public `record_uploaded_frame()`; a fresh upload after eviction restores normal force-describe.
17. Empty cache with `session_id=None` or `""` is a silent no-op; a missing requested session and either no-session form preserve fresh global fallback.
18. Stale candidates never append/reanimate working memory. AD-1055/BF-294 camera-off rendering, persisted historical WM rows, `_last_observation`, episodes, and session/global fallback remain otherwise unchanged.
19. `AttachmentStore`, retention, reaper, config, wire shapes, routers, startup/shutdown, aggregator, and public method signatures remain unchanged; only the private optional `_process` keyword is added.
20. Only the exact allowlist changes; no new dependency, protocol, database/schema, EventType, task, callback, polling loop, UI, AD, `DECISIONS.md`, roadmap, or retention extension appears.
21. Focused and blast-radius gates pass in serial with isolated `PROBOS_DATA_DIR`, `PROBOS_EMBEDDINGS=local`, cache disabled, timeout bound, and `RuntimeWarning` promoted to error.
22. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Do not build

- Do not persist the latest-frame cache or add a WM/cache schema column.
- Do not delete historical `VisionWorkingMemory`/`WorkingMemoryStore` rows when a frame blob expires.
- Do not add an `AttachmentReaper` callback, observer, event subscription, cache invalidation bus, storage polling, timer, or background task.
- Do not increase/disable `frame_retention_seconds`, change `reaper_interval_seconds`, or change `prompt_freshness_seconds` defaults/config.
- Do not add a camera-stop API, stream lifecycle API, upload endpoint, router hook, or group/DM call-site change.
- Do not change the `AttachmentStore` Protocol, `FilesystemAttachmentStore`, index format/semantics, `unlink()`, or reaper policy.
- Do not use private attachment-store state (`_index`, `_root`, `_lock`, `_find`) or runtime/router cache internals.
- Do not clear by SHA alone, session alone, or entire cache; compare the complete tuple and clear every exact alias only.
- Do not treat `exists()` as authoritative or omit the `read()` `FileNotFoundError` race closure.
- Do not clear on timeout, busy singleflight, low novelty, empty LLM output, unexpected store error, or cancellation without independent stale/missing proof.
- Do not cancel a valid in-flight describe or replace BF-304's drop-not-queue semantics; `_force_describe_permit()` extends the same policy before storage and must never let a second force call wait behind the full describe.
- Do not change force-describe/session/global/upload public signatures, synthetic message fields, attachment-ref wire shape, supervisor behavior, observer fan-out, identity, budget, anchoring, or prompt rendering.
- Do not repair the unrelated missing runtime `VisionAggregator.stop()` shutdown call in this BF.
- Do not edit existing tests beyond the explicitly authorized AD-746a fixture correction; stop if another obsolete contract requires an allowlist change.
- Do not edit UI, config, workflows, dependencies, logs/data, roadmap, era files, or `DECISIONS.md`.
- Do not mint an AD; this is BF-666.
- Do not archive the prompt pair.
- Do not commit, stage, push, or mutate GitHub unless the orchestrator explicitly directs it.

---

## Hard stops

Stop and return to the Architect if:

- HEAD is not exactly `2d595dad0df6d0a1daeed8d02d8e5d324cd483f5` at Builder start;
- the initial working tree is anything except the two untracked BF-666 prompt documents;
- BF-665 CI finishes red and remediation/base movement is proposed before BF-666 build;
- another production caller/writer/cache owner exists beyond the verified paths;
- a required fix needs any production file other than `src/probos/perception/consumer.py`;
- a required regression needs an existing test edit beyond the authorized AD-746a fixture or a second new test file;
- correctness requires changing `AttachmentStore`, config, router, runtime/startup/shutdown, aggregator, WM schema, or a public/sealed protocol;
- a design holds the cache lock over any await, lets `_force_describe_permit()` wait beyond its tiny bounded budget/over-release, or reuses `_describe_lock` for cache ownership;
- a synchronous `record_uploaded_frame()` cannot participate without public async signature churn;
- any clear can remove a complete tuple different from the snapshotted candidate;
- `exists()` is used without authoritative `read()` missing handling;
- cancellation is swallowed/converted to `None`, leaks a task/lock, leaves `_force_describe_lock` held, or clears a valid candidate;
- expected missing storage still logs at WARNING/traceback;
- unexpected backend errors would clear the candidate or be silently swallowed;
- low-novelty/upload/session-global/BF-304 behavior cannot be preserved;
- focused/blast failures reproduce serially and require behavior outside BF-666;
- any deletion/archive move appears; or
- any Git/GitHub mutation is requested without explicit orchestrator direction.

Do not guess through a hard stop.

---

## Verified against codebase (2026-07-14; exact HEAD `2d595dad0df6d0a1daeed8d02d8e5d324cd483f5`)

```text
src/probos/perception/consumer.py
  71–74: _reset_latest_frame_cache_for_tests directly clears both cache slots
  77: class VisionConsumer
  83–101: exact __init__ signature
  124: self._describe_lock = asyncio.Lock() (BF-304; only current consumer lock)
  162: _latest_frame_by_session: dict[str, tuple[str, float]]
  163: _latest_frame_global: tuple[str, float] | None
  351: async def _handle(self, msg: IntentMessage) -> IntentResult | None
  356–365: cache-before-supervisor direct unconditional session/global writes
  369: await self._process(msg)
  381: async def _process(self, msg: IntentMessage) -> None
  381–408: ref/source/session extraction; no captured_at local retained
  410–411: imports/gets shared attachment store
  413: frame_bytes = await store.read(sha)
  414–419: broad Exception → WARNING traceback, return; no invalidation
  422–445: force bypass vs supervisor; low-novelty returns before LLM
  451–470: BF-304 locked() drop + async with describe lock
  560–565: exact force_describe_current_frame signature
  581–584: session-first then global selection
  589–603: unchanged synthetic force=True IntentMessage + wait_for(_process)
  604–617: timeout/broad-exception warning paths; no CancelledError branch
  618–624: returns matching observer WM description by SHA
  627–629: exact record_uploaded_frame signature
  641–644: empty-SHA no-op then unconditional direct session/global writes

src/probos/attachments/store.py
  31: AttachmentStore Protocol
  39–55: write(..., origin=...)
  57: read(content_hash) -> bytes; FileNotFoundError contract
  61: exists(content_hash) -> bool
  65/69/73/79/85: get_path/size/unlink/list_by_origin/total_size_bytes public APIs

src/probos/attachments/filesystem_store.py
  273–277: read does _find then raises FileNotFoundError or reads path
  279–281: exists independently does _find
  289–314: unlink serializes file+index removal; raced FileNotFoundError is expected
  316–331: list_by_origin is index-backed/sorted
  375–388: mime_for also uses _find (not needed by BF-666 preflight)

src/probos/attachments/reaper.py
  39–58: AttachmentReaper owns store/config/task state
  62–70: start holds named task reference
  72–91: stop cancels/awaits/idempotently clears reference
  93–105: loop re-raises cancellation
  145–166: age TTL uses frame_retention_seconds then public list_by_origin/unlink

src/probos/config.py / config/system.yaml
  config.py:2576: class PerceptionConfig
  config.py:2624: frame_retention_seconds default=300, ge=30, le=86400
  config.py:2672: dm_force_describe_enabled default=True
  config.py:2681: prompt_freshness_seconds default=120, 0 disables prompt guard
  config/system.yaml:1301: active perception block
  config/system.yaml:1315: frame_retention_seconds: 300
  config/system.yaml:1326: dm_force_describe_enabled: true
  prompt_freshness_seconds is absent from YAML and therefore uses model default 120

src/probos/perception/working_memory.py / wm_store.py
  working_memory.py:35–44: frozen VisionObservation carries attachment_ref + timestamp
  working_memory.py:47: VisionWorkingMemory
  working_memory.py:100–131: render_for_prompt freshness guard; > window → BF-294 sentinel
  working_memory.py:124–127: stale entries are hidden for rendering, not deleted
  wm_store.py:26–37: SQLite vision_observations schema includes attachment_ref TEXT
  wm_store.py:41: WorkingMemoryStore
  wm_store.py:80–120: persisted rows load/append refs and descriptions; no latest-cache table

src/probos/perception/supervisor.py / aggregator.py
  supervisor.py:34: SupervisorStrategy protocol
  supervisor.py:382–389: VisionSupervisor.admit uses monotonic strategy clock
  aggregator.py:84–88: pending messages/timer refs + lock
  aggregator.py:96–151: debounce; same-source newer arrival replaces pending, original timer remains
  aggregator.py:200–210: delayed _forward calls consumer._handle
  aggregator.py:212–225: stop cancels/awaits timer refs (no runtime shutdown caller found)

src/probos/routers/perception.py / agents.py / thread_fanout.py
  perception.py:233–247: upload builds ref-only message then calls public record_uploaded_frame
  perception.py:247: only production record_uploaded_frame call
  agents.py:2963–2981: 1:1 force-describe gate; call passes timeout only (global selection)
  thread_fanout.py:325–345: group helper calls force-describe once per round, timeout only
  global grep found no other production force-describe or record-uploaded callers

src/probos/startup/finalize.py / shutdown.py
  finalize.py:484: _start_attachment_reaper
  finalize.py:502–513: shared store → AttachmentReaper → await start → runtime owner
  finalize.py:4344: reaper start invoked during finalize
  finalize.py:4969–4975: WorkingMemoryStore wired before VisionConsumer
  finalize.py:4988–5041: VisionConsumer + optional VisionAggregator construction/ownership
  shutdown.py:670–690: perception mode-controller task stop
  shutdown.py:701–705: attachment reaper stop
  no VisionConsumer task exists; no shutdown vision_aggregator.stop call found (unrelated, out of scope)

Existing tests inspected
  test_ad733c1_force_describe.py: 6 — cache-before-supervisor, session/global, empty, timeout, DM hook
  test_ad746a_force_describe_mirror.py: 3 — public upload writer, empty SHA, force resolve without _handle
  test_attachment_reaper.py: 8 — TTL/LRU/errors/task lifecycle/event
  test_ad978_group_perception.py: 13 — once-per-round, BF-294 sentinel, group injection/gates
  test_ad733a_vision_consumer.py: 34 — supervisor, WM freshness/sentinel, missing read, low novelty, BF-304
  test_ad733_frame_endpoint.py: 12 — upload/ref-only/rate/force/recent
  test_ad733_2_screen_source.py: 8 — screen/upload/source behavior
  test_camera_frame_origin.py: 2 — perception_frame retention origin
  test_ad742f_wm_persistence.py: 10 — persisted ref/text ring semantics
  test_ad720_attachment_store.py: 11 — public exists/read/missing contracts
  test_ad746_vision_aggregator.py: 11 — passthrough/fusion/delay/cancellation/BF-323
  test_bf624_stale_meeting_vision_refresh.py: 6 — shared latest vs stale/empty/fresher own rings
  no tests/test_bf666_force_describe_cache_expiry.py exists at base

Live read-only evidence
  C:/Users/seang/AppData/Local/ProbOS/data/logs/probos.log:43083 low-novelty drop sha=832af3ee
  same log: 19 missing-read WARNINGs; first 43432 at 11:29:26, last 49547 at 18:10:49
  attachment basename matches for full SHA: 0
  .index.json contains full SHA: false (697 entries inspected)
  perception_wm.db vision_observations rows with attachment_ref=full SHA: 0 (51 total)

Recent BF convention
  2d595dad BF-665: PROGRESS + prompt pair in place + source/tests; no DECISIONS/roadmap
  5e28b579 BF-664: same convention
  d64920ac BF-661: same convention
```

---

## Architect three-pass self-review

### Pass 1 — Required / recommended / nits / license / boundary

**Verdict:** ⚠️ Conditional before revision.

**Required findings:**

1. Issue wording could be read as `exists()` proving availability; live store semantics show a required `read()` race closure.
2. Clearing one requested session entry would leave global/other-session aliases alive; clear must scan every exact tuple under one lock.
3. SHA-only compare would erase an identical-byte newer capture; full tuple compare is mandatory.
4. Unconditional post-process clear would race a newer upload; postcheck must clear the original tuple only.
5. Reusing `_describe_lock` would hold/serialize unrelated cache operations around storage/LLM; cache ownership needs a separate tiny lock.
6. An `asyncio.Lock` cannot be cleanly used by synchronous public `record_uploaded_frame()` without signature churn; use one non-awaiting stdlib lock or stop.
7. Broad exception handlers can swallow `CancelledError` intent semantically; explicit cancellation propagation is required at new await boundaries and initial read.
8. Stale WM rows and latest-frame cache are different lifecycles; deleting persisted WM would be scope creep and historical-data loss.
9. Runtime shutdown lacks `VisionAggregator.stop()` despite the method existing; this is a verified unrelated lifecycle gap and must be named out-of-scope, not silently bundled.
10. `_handle()`'s missing-`captured_at` fallback would be impossible to compare-clear if `_process()` generated a second timestamp; the exact incoming tuple must be carried privately.
11. Simultaneous force calls can both snapshot before the first await completes; an early non-queuing force-call guard is required to make “attempted at most once” true under concurrency.
12. AD-746a's malformed, non-stored `"sha123"` fixture conflicts with the required real preflight; the fixture must be corrected rather than production weakened.
13. Raw `float(captured_at)` accepts `NaN`/infinities, which break total ordering and age comparisons; reject non-finite time before cache mutation.
14. A bare `lock.locked()` check followed by `async with lock` has a scheduling race that can queue a second caller; use a cancellation-safe bounded acquire that releases only after successful ownership.

**Recommended:** retain strict `>` freshness parity with AD-1055, test independent session/global monotonicity, test equal-timestamp last-write-wins, and use real/delegating store fakes rather than MagicMock auto-attributes.

**Nits:** production warning count has advanced from issue snapshot 16 to 19; avoid pinning it. Keep logs to SHA prefix, not full hash, unless debugging requires otherwise.

**License:** none.

**Boundary:** OSS is correct — this is runtime reliability/how the product works. No commercial detail or UI work.

### Pass 2 — Required findings revised

All fourteen required findings and recommendations are incorporated in DD-1 through DD-8, the ordered build, named regression matrix, exact allowlist, acceptance criteria, do-not-build list, and hard stops. The prompt now specifies eager selection validation plus authoritative failed-read invalidation, complete-tuple compare, all-alias atomic clearing, exact missing-timestamp propagation, finite-time validation, cancellation-safe bounded force singleflight, real-store fixture correction, and no persisted-WM deletion.

### Pass 3 — Final verify-first approval

**Verdict:** ✅ APPROVED FOR BUILDER.

Every concrete production signature, config field/default, public storage API, cache writer/caller, WM persistence seam, reaper/task owner, and relevant existing test named here maps to live code at exact HEAD. No phantom API is consumed; all new entities are introduced by this prompt. The smallest correct production diff remains one source file, one new focused test file, and one verified obsolete-fixture correction. No dependency/license, repository-boundary, sealed-protocol, UI, AD/decision, retention, storage-schema, or unresolved architecture stop remains.
