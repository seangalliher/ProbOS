# BF-598 — Shutdown is not idempotent: a re-entrant shutdown downgrades the clean AD-820 marker → recurring boot refusal

**Status:** Draft — pending Architect review
**Issue:** recurring AD-820 boot refusal (`consolidation_result="skipped"`, `status="partial"`); follows AD-828 / AD-828a / AD-828b
**Target repo:** OSS (`d:\ProbOS`)
**Wave:** 208
**One commit** titled: `fix(shutdown): BF-598 idempotent shutdown + non-regressive AD-820 marker (recurring boot refusal)`

---

## 1. Problem

The operator hits a recurring boot refusal (the third documented cluster — AD-828 logged May 22/26/29 on a
~4-day cadence consistent with Windows sleep/wake). On 2026-06-02 the runtime refused to start with:

```
✗ Previous shutdown was partial (consolidation_result=skipped at 2026-06-02 00:13:37 UTC).
```

**Forensic evidence (runtime data dir `%LOCALAPPDATA%\ProbOS\data`):**

- `shutdown_status.json` = `{"consolidation_result":"skipped","status":"partial","note":"phase1_elapsed=2.0s","last_shutdown_at":1780359217.998945}` → **2026-06-02 00:13:37 UTC**.
- `session_last.json` = session `14ab6c94`, `uptime_seconds=39060.6` (~10.85 h), `agent_count=74`, `reason="server_shutdown"`, `shutdown_time_utc=1780321723.62` → **2026-06-01 13:48:43 UTC**.

The marker is **~10.4 h LATER** than the last `session_last.json` write, yet `session_last.json` was **not**
updated for that later shutdown. That gap is the smoking gun. Reconstruction:

1. A graceful, startup-complete session (74 agents, `_startup_complete=True`) shut down. It ran
   consolidation and wrote a **clean** marker, then began Phase-2 teardown.
2. Phase-2 teardown did **not** reach the end — the process was killed / cancelled / hit the `__main__`
   5 s `stop()` timeout somewhere in the ~380 lines between the marker write and `runtime._started = False`.
   Because `runtime._started = False` is the **last statement of the function** (`shutdown.py:765`), `_started`
   stayed **True**.
3. A **second** `shutdown()` invocation fired (duplicate SIGTERM during Windows sleep/wake, or a retried
   `stop()`). It re-entered past the only guard (`if not runtime._started: return`, `shutdown.py:63`), found
   the cognitive subsystems already torn down (`dream_scheduler` / `episodic_memory` is `None`), so the
   consolidation gate at `shutdown.py:193` (`if runtime.dream_scheduler and runtime.episodic_memory:`) was
   False → `_consolidation_result` stayed `"skipped"`. Its `session_last.json` write at the top of
   `shutdown()` raised (registry already torn down → `registry.all()` fails → caught at `debug`), which is
   **why `session_last.json` shows the earlier 13:48 session**. The `phase1_elapsed=2.0s` note (vs the normal
   11–13 s in the logs) confirms the dream-cycle branch never ran.
4. The re-entrant shutdown reached the marker write at `shutdown.py:386` and called `mark_dirty_shutdown(...)`,
   which **unconditionally overwrote** the clean marker with `partial`/`skipped`. Next boot refuses.

**Why AD-828b does not cover this.** AD-828b only reclassifies `skipped → startup_incomplete` (recoverable,
boots) when `_startup_complete` is **falsy**. Here startup genuinely completed (`_startup_complete=True`,
74 agents), so the re-entrant skip stays the hard-blocking `"skipped"`.

**Two independent defects:**

- **D1 — `shutdown()` is not idempotent.** `runtime._started = False` is set only at the very end
  (`shutdown.py:765`), ~380 lines after the marker write (`shutdown.py:386`). Any failure/cancellation in
  Phase-2 teardown leaves `_started=True`, so a second invocation re-runs the whole sequence.
- **D2 — the AD-820 marker write is regressive.** `mark_dirty_shutdown` (`shutdown_integrity.py:159`) writes
  unconditionally; a `"skipped"` result (subsystems already absent → **nothing was torn**, so the HNSW index
  cannot be corrupted by this event) downgrades a prior `clean`/`rebuilt` marker to blocking `partial`.

---

## 2. Design

Two complementary fixes. D1 is the root-cause guard; D2 is defense-in-depth for the multi-process /
guard-bypassed case.

### 2.1 D1 — Idempotency guard (primary fix), `startup/shutdown.py`

Add a dedicated re-entrancy flag at the **very top** of `shutdown()`, BEFORE the BF-135/137 session-record
write (a re-entry is a duplicate, not a partial boot — the first call already persisted the session record):

```python
async def shutdown(runtime: ProbOSRuntime, reason: str = "") -> None:
    """Graceful shutdown of all pools, mesh services, and persistence."""
    # BF-598: idempotency guard. A second shutdown() invocation (a duplicate
    # SIGTERM during Windows sleep/wake, or a retried stop()) must NOT re-run
    # teardown. The first invocation already consolidated and wrote the AD-820
    # integrity marker; re-running finds the cognitive subsystems torn down,
    # skips consolidation, and would DOWNGRADE the clean marker to partial —
    # the root cause of the recurring boot refusal. Use getattr-with-default so
    # a process that started before this field existed still degrades safely.
    if getattr(runtime, "_shutdown_started", False):
        logger.info(
            "BF-598: shutdown() re-entered (reason=%r); first invocation already "
            "ran — skipping teardown and preserving the AD-820 marker.",
            reason,
        )
        return
    runtime._shutdown_started = True

    # BF-135: Persist session record FIRST ...
    ...
```

- Initialise the flag in `ProbOSRuntime.__init__` (`runtime.py`, next to `self._started = False` @963 /
  `self._startup_complete = False` @975): add `self._shutdown_started: bool = False`. The `getattr` default
  covers transitional processes (BF-291 pattern), but the explicit init is the canonical home.
- Do **not** repurpose `_started` for this — `_started` gates the heavy-teardown skip for never-started
  runtimes (BF-137) and is read elsewhere; a separate flag keeps the two concerns orthogonal.
- **Verify** (Builder): grep `shutdown.py` for every read of `runtime._started` and confirm none depends on
  the new early-return path. The existing `if not runtime._started: return` @63 stays unchanged (it still
  handles the never-started case after the session-record write).

### 2.2 D2 — Non-regressive marker write (defense-in-depth), `startup/shutdown.py` marker block @376–391

Only a `"skipped"` result is non-regressive (nothing was torn). `"partial"` and `"failed"` mean consolidation
**ran and was interrupted mid-write** → genuine torn-HNSW risk → they MUST still block. Scope the guard to
`"skipped"` only:

```python
from probos.shutdown_integrity import (
    mark_clean_shutdown, mark_dirty_shutdown, read_shutdown_status,
)
_data_dir = getattr(runtime, "_data_dir", None)
if _data_dir is not None:
    if _consolidation_result == "full":
        mark_clean_shutdown(_data_dir, consolidation_result="full", note="phase1_ok")
    elif _consolidation_result == "skipped":
        # BF-598: a SKIP means the cognitive subsystems were absent, so nothing
        # was written to the HNSW index — this event cannot corrupt it. Never let
        # a skip DOWNGRADE an existing clean/rebuilt marker (that is the recurring
        # boot-refusal bug). If no clean marker exists, fall through to the dirty
        # write so a genuinely-disabled-episodic first boot still surfaces honestly.
        _existing = read_shutdown_status(_data_dir)
        if _existing.get("status") == "clean" or _existing.get("consolidation_result") in ("full", "rebuilt"):
            logger.info(
                "BF-598: consolidation skipped but a clean marker already exists "
                "(consolidation=%s); preserving it — a skip cannot tear the index.",
                _existing.get("consolidation_result"),
            )
        else:
            mark_dirty_shutdown(_data_dir, consolidation_result="skipped",
                                note=f"phase1_elapsed={_phase1_elapsed:.1f}s")
    else:
        # partial / failed / startup_incomplete → unchanged behaviour
        mark_dirty_shutdown(_data_dir, consolidation_result=_consolidation_result,  # type: ignore[arg-type]
                            note=f"phase1_elapsed={_phase1_elapsed:.1f}s")
```

Keep the outer `try/except Exception: logger.warning("AD-820: failed to record shutdown integrity marker ...")`
unchanged. Do **not** change `mark_dirty_shutdown` / `mark_clean_shutdown` signatures in
`shutdown_integrity.py` — the non-regression policy lives at the call site (the only place that knows
`_consolidation_result`). `read_shutdown_status` already exists and is import-safe.

---

## 3. Tests — `tests/test_bf598_shutdown_idempotency.py` (new)

Use real fixtures, NOT MagicMock at the substrate boundary (per the no-MagicMock-at-substrate-boundary rule).
A `tmp_path` data dir + a minimal fake runtime object (real attributes: `_data_dir`, `_started`,
`_shutdown_started`, `_session_id`, `_start_time*`, `registry`, `dream_scheduler=None`, `episodic_memory=None`,
`config`, the service attrs `shutdown()` touches set to `None`). At minimum:

1. **`test_reentrant_shutdown_returns_early_and_preserves_marker`** — write a clean marker, set
   `_shutdown_started=True`, call `await shutdown(runtime)`; assert it returns immediately and the on-disk
   marker is still `status="clean"` (unchanged `last_shutdown_at`).
2. **`test_first_shutdown_sets_shutdown_started_flag`** — fresh runtime, `_shutdown_started` absent/False;
   after `shutdown()` the flag is True.
3. **`test_skipped_does_not_downgrade_clean_marker`** — pre-write a clean marker; drive the marker block with
   `_consolidation_result="skipped"` (real subsystems None); assert the marker stays `clean`.
4. **`test_skipped_with_no_prior_marker_writes_partial`** — empty data dir; `skipped` → marker is
   `status="partial"`, `consolidation_result="skipped"` (honest first-boot surfacing preserved).
5. **`test_failed_still_downgrades_and_blocks`** — pre-write a clean marker; `_consolidation_result="failed"`
   → marker becomes `partial`/`failed` (torn-index risk must still block; non-regression is `skipped`-only).
6. **`test_check_previous_shutdown_boots_after_preserved_clean_marker`** — end-to-end: after fix-3's preserved
   clean marker, `check_previous_shutdown(data_dir)` returns without raising.
7. **`runtime.py` init** — assert a freshly constructed `ProbOSRuntime` (or the lightweight path used by other
   runtime tests) has `_shutdown_started is False`.

If exercising the full `shutdown()` body is too heavy, factor the marker-write decision into a small pure
helper and unit-test that directly — but the idempotency early-return (tests 1–2) must be tested against the
real `shutdown()` entry, since that is the defect locus.

Run the scoped gate serially:
`d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf598_shutdown_idempotency.py tests/test_ad828*.py tests/test_bf207_shutdown_episodic_integrity.py -q -n 0`
then the full serial gate `.venv/Scripts/pytest.exe tests/ -q -n 0` must stay green.

---

## 4. Do NOT change (scope boundaries)

- Do **not** alter `mark_clean_shutdown` / `mark_dirty_shutdown` / `read_shutdown_status` signatures or the
  `ShutdownStatusPayload` schema. The non-regression policy is a call-site decision.
- Do **not** touch `check_previous_shutdown` gate logic (AD-820/828b/BF-297 carve-outs stay as-is). This BF
  prevents the bad marker from being written; it does not loosen the read gate.
- Do **not** change consolidation, `DreamScheduler.stop_gracefully` (AD-825), the BF-296 Phase-A bus close,
  the AD-824/825 drain/cancel sweep, or `_startup_complete` (AD-828b).
- Do **not** move `runtime._started = False` (`shutdown.py:765`) earlier as the fix — the dedicated
  `_shutdown_started` flag is the correct, lower-risk mechanism (moving `_started` risks the BF-137
  never-started semantics).
- Do **not** reclassify `partial`/`failed` as non-regressive — only `skipped` is provably index-safe.
- Repo hygiene: do not `git add -A`. Remove any scratch capture (`iso.txt`, `triage_runtime.txt`, `*err.txt`)
  before commit; stage only the three changed source files + the new test file.

---

## 5. Acceptance criteria

- `shutdown()` is idempotent: a second invocation returns early and never rewrites the AD-820 marker.
- A `skipped` consolidation result never downgrades an existing `clean`/`rebuilt` marker; `partial`/`failed`
  still block as before.
- `ProbOSRuntime._shutdown_started` initialised `False` in `__init__`.
- New `tests/test_bf598_shutdown_idempotency.py` (≥7 tests) green; `tests/test_ad828*` and
  `tests/test_bf207_shutdown_episodic_integrity` regress-clean; full serial gate green (report the count).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## 6. Files

| File | Change |
|------|--------|
| `src/probos/startup/shutdown.py` | D1 idempotency guard at top of `shutdown()`; D2 non-regressive `skipped` marker write at @376–391 (add `read_shutdown_status` to the import). |
| `src/probos/runtime.py` | `self._shutdown_started: bool = False` in `__init__` (next to `_startup_complete` @975). |
| `tests/test_bf598_shutdown_idempotency.py` | New — idempotency + non-regression coverage. |
