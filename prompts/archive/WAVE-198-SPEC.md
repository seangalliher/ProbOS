# Wave 198 — AD-828: Partial-shutdown diagnostic + startup-incomplete classification

**Target repo:** OSS (`d:\ProbOS`)
**Type:** BF-class hardening (diagnostic + prevention). Two sub-ADs, one commit.
**Highest AD verified against PROGRESS.md:** AD-827 (= AD-791a). AD-828/829/830 are free (grep-confirmed, zero matches).

---

## Section 0 — Conceptual frame (read first)

The runtime refuses to boot when `shutdown_status.json` says
`consolidation_result=skipped, status=partial`. This has now happened **three times in
seven days** (data dir holds `chroma-corrupted-2026-05-22-150712`; failures May 22 / May 26 /
May 29 — a ~4-day cadence consistent with Windows sleep/wake killing the runtime mid-startup).

**Root cause (high-confidence, file:line):** the consolidation gate in
[startup/shutdown.py](../../src/probos/startup/shutdown.py) —
`if runtime.dream_scheduler and runtime.episodic_memory:` — is **silent**. When EITHER attribute
is `None`, the entire Tier-3 consolidation block is skipped and `_consolidation_result` keeps its
initial value `"skipped"` (set at `_consolidation_result: str = "skipped"`). The marker is then
written via `mark_dirty_shutdown(... consolidation_result="skipped")`, `status="partial"`, and the
next boot's `check_previous_shutdown()` refuses to start.

The observed `phase1_elapsed=2.1s` is diagnostic: it ≈ the BF-296 Phase A `asyncio.sleep(2.0)` grace
+ nothing else, proving `dream_cycle()` never ran. The most likely trigger is **kill-during-startup-
before-wiring**: the shutdown handler runs from the `__main__.py` `finally:` block; if Ctrl+C /
TerminateProcess / laptop-sleep fires BEFORE Phase 5 (`runtime.py` `init_dreaming`, ~L1986) wires
`self.dream_scheduler`, that attribute is still `None` at shutdown, so the gate skips silently. The
marker is mislabeled `partial` even though the actual event was *startup never completed* — NOT a
torn HNSW.

**Two surgical fixes:**

- **AD-828a (diagnostic):** when the gate skips, log WHICH component was `None`. Confirms the
  hypothesis on the next recurrence; zero behavior change.
- **AD-828b (classification):** track `runtime._startup_complete`. When the gate skips AND startup
  never completed, stamp a new `consolidation_result="startup_incomplete"` instead of `"skipped"`,
  and teach the boot gate to allow boot for that value — **safe because** the shutdown handler still
  ran `episodic_memory.stop()` (graceful HNSW close), and AD-822/AD-822b's subprocess structural
  HNSW probe is the backstop that catches a *genuinely* torn index before the real ChromaDB open.

This is identity-preserving: a real consolidation failure mid-write still stamps `"failed"` and still
blocks boot. We only carve out the "killed before the cognitive layer was wired" case, which the
existing AD-822b probe already protects.

---

## Section 1 — AD-828b part 1: startup-complete flag (`runtime.py`)

### 1a. Initialize the flag in `__init__`

In [src/probos/runtime.py](../../src/probos/runtime.py), find the lifecycle-state init in
`__init__` (currently `self._lifecycle_state: str = "first_boot"`, ~L966). Add immediately after it:

```python
        # AD-828b: set True only at the very end of start() (Phase 8 finalize
        # complete). shutdown() reads this to distinguish "killed before the
        # cognitive layer was wired" (startup_incomplete — recoverable) from
        # a real consolidation failure (failed — blocks boot). Default False so
        # any kill before start() returns is correctly classified.
        self._startup_complete: bool = False
```

If the class has a type-annotation block near the top (e.g. `_lifecycle_state: str` at ~L339), add a
companion `_startup_complete: bool` annotation there for consistency. Do not add it if no such block
governs `_lifecycle_state` — match whatever pattern already exists.

### 1b. Set the flag at the end of `start()`

`start()` begins at ~L1648 and ends after the `self._episodic_backup_task = self._spawn_background(...)`
call (the last statement before `async def _initialize_semantic_work_layer`, ~L2350). Append as the
**final statement of `start()`**, after the backup-task spawn:

```python
        # AD-828b: startup fully complete — the cognitive layer (dream_scheduler,
        # episodic_memory) is wired. A shutdown after this point that still skips
        # consolidation is a real failure, not a killed-mid-boot event.
        self._startup_complete = True
```

Match the existing indentation (one method-body level inside `start()`). Do NOT place it inside any
`try`/`if` block — it must run unconditionally as the last line of the method body.

---

## Section 2 — AD-828a + AD-828b part 2: the skip-path else branch (`startup/shutdown.py`)

In [src/probos/startup/shutdown.py](../../src/probos/startup/shutdown.py), the Tier-3 consolidation
block is:

```python
    if runtime.dream_scheduler and runtime.episodic_memory:
        logger.info(
            "Consolidating session memories (budget=%.0fs)...",
            _shutdown_consolidation_timeout,
        )
        try:
            ...
            _consolidation_result = "full"
        except asyncio.TimeoutError:
            ...
            _consolidation_result = "partial"
        except (asyncio.CancelledError, Exception) as e:
            ...
            _consolidation_result = "failed"

    # BF-207: Close episodic memory (ChromaDB) immediately after dream
    # consolidation ...
    if runtime.episodic_memory:
        await runtime.episodic_memory.stop()
```

Add an `else:` branch attached to `if runtime.dream_scheduler and runtime.episodic_memory:`. It must
sit AFTER the final `except (asyncio.CancelledError, Exception) as e:` block (the one that sets
`_consolidation_result = "failed"`) and BEFORE the `# BF-207: Close episodic memory` comment.

```python
    else:
        # AD-828a: the consolidation gate skipped. Log WHICH component was
        # absent so the next recurrence is diagnosable instead of silent.
        _ds_present = runtime.dream_scheduler is not None
        _em_present = getattr(runtime, "episodic_memory", None) is not None
        # AD-828b: distinguish "killed before the cognitive layer was wired"
        # (startup_incomplete — recoverable, the shutdown handler below still
        # closes episodic memory cleanly and AD-822b's HNSW probe is the boot
        # backstop) from a deliberately disabled subsystem (leave "skipped").
        _startup_done = getattr(runtime, "_startup_complete", True)
        if not _startup_done:
            _consolidation_result = "startup_incomplete"
            logger.warning(
                "AD-828: consolidation skipped because startup never completed "
                "(dream_scheduler=%s episodic_memory=%s, _startup_complete=False). "
                "Classifying as startup_incomplete — boot will be permitted; the "
                "AD-822b HNSW structural probe remains the integrity backstop.",
                _ds_present, _em_present,
            )
        else:
            logger.warning(
                "AD-828: consolidation skipped with startup complete "
                "(dream_scheduler=%s episodic_memory=%s). Leaving "
                "consolidation_result=%r — subsystem appears disabled or "
                "torn down early.",
                _ds_present, _em_present, _consolidation_result,
            )
```

**Honest-degrade note:** `getattr(runtime, "_startup_complete", True)` defaults to **True** so a
transitional running process started BEFORE this AD shipped (no `_startup_complete` attribute) keeps
the pre-AD behavior (stays `"skipped"`, blocks boot) rather than being silently reclassified. This is
the BF-291 transitional-process convention.

Do NOT modify the marker-write block (`if _consolidation_result == "full": mark_clean_shutdown ... else
mark_dirty_shutdown`). It already routes any non-`full` result through `mark_dirty_shutdown`, which
now carries `"startup_incomplete"` — the boot-gate change in Section 3 makes that bootable.

---

## Section 3 — AD-828b part 3: literal + boot gate (`shutdown_integrity.py`)

In [src/probos/shutdown_integrity.py](../../src/probos/shutdown_integrity.py):

### 3a. Extend the literal

```python
ConsolidationResult = Literal["full", "partial", "skipped", "failed", "rebuilt"]
```

becomes:

```python
ConsolidationResult = Literal[
    "full", "partial", "skipped", "failed", "rebuilt", "startup_incomplete"
]
```

### 3b. Allow boot for `startup_incomplete` in `check_previous_shutdown`

The current clean-path check is:

```python
    if status == "clean" or consolidation == "rebuilt":
        logger.info(
            "AD-820: previous shutdown was %s (consolidation=%s) at %.0f",
            "clean" if status == "clean" else "rebuilt",
            consolidation,
            payload.get("last_shutdown_at", 0),
        )
        return
```

Add a SEPARATE recoverable branch immediately after it (do NOT fold it into the clean log line — the
operator-facing rationale differs):

```python
    # AD-828b: a shutdown that skipped consolidation purely because startup
    # never completed (killed before the cognitive layer was wired) is
    # recoverable: the shutdown handler still closed episodic memory cleanly,
    # so the on-disk HNSW reflects the last good state, and AD-822b's pre-open
    # structural probe (running in the AD-822 subprocess) is the backstop that
    # refuses boot if the index is actually torn. Permit boot with a WARNING.
    if consolidation == "startup_incomplete":
        logger.warning(
            "AD-828b: previous shutdown was startup_incomplete at %.0f — the "
            "runtime was killed before startup finished wiring the cognitive "
            "layer. Permitting boot; the AD-822b HNSW probe will refuse if the "
            "index is genuinely torn.",
            payload.get("last_shutdown_at", 0),
        )
        return
```

Do NOT touch `mark_clean_shutdown` / `mark_dirty_shutdown` — `startup_incomplete` correctly flows
through `mark_dirty_shutdown` (status stays `"partial"` for honest forensics; the gate special-cases
the consolidation value, exactly mirroring the existing BF-297 `"rebuilt"` precedent).

---

## Section 4 — Tests

New file `tests/test_ad828_startup_incomplete.py`. Follow the `_Fake*` stub style used in
`tests/test_ad820_shutdown_integrity.py` and `tests/test_ad825_drain_shutdown.py`. Minimum coverage:

**Boot gate (`check_previous_shutdown`) — `shutdown_integrity`:**
1. `startup_incomplete` marker → `check_previous_shutdown` returns (does NOT raise). Use `tmp_path`,
   write a `shutdown_status.json` with `status="partial", consolidation_result="startup_incomplete"`,
   and create a sentinel `events.db` so it isn't treated as first boot.
2. `failed` marker still raises `UncleanShutdownDetected` (regression guard — we did NOT widen the
   carve-out).
3. `skipped` marker still raises `UncleanShutdownDetected` (regression guard — pre-AD behavior intact
   for genuinely-skipped shutdowns where startup DID complete).
4. `startup_incomplete` marker round-trips through `read_shutdown_status` with the literal value
   preserved (serialization guard for the new Literal member).

**Shutdown classification (`shutdown.py` else branch):** Prefer a focused unit test over booting a
real runtime. Build a minimal fake runtime object exposing `dream_scheduler=None`,
`episodic_memory=<fake or None>`, `_startup_complete=False`, plus the attributes the surrounding
shutdown code reads up to the marker write (`intent_bus=None`, `_drain_tasks=None`,
`_background_tasks=None`, `_data_dir=tmp_path`, `_flush_task` absent, `red_team_lead=None`,
`_eviction_audit=None`, and a `config`/memory shim so `_memory_field` resolves defaults). Then call
`shutdown(runtime)` and assert `shutdown_status.json` was written with
`consolidation_result="startup_incomplete"`.
5. `dream_scheduler=None` + `_startup_complete=False` → marker `consolidation_result=="startup_incomplete"`.
6. `dream_scheduler=None` + `_startup_complete=True` → marker stays `"skipped"` (disabled-subsystem path).
7. Missing `_startup_complete` attribute entirely (transitional process) → honest-degrade defaults to
   True → marker stays `"skipped"`.

   If wiring a full `shutdown(runtime)` call proves too entangled for a unit test, it is acceptable to
   instead test the classification predicate in isolation by extracting the exact boolean logic into
   the test (replicating `getattr(runtime, "_startup_complete", True)` + the gate), but PREFER the
   real `shutdown()` call — it guards the actual code path. Document the choice in a test docstring.

**Runtime flag (`runtime.py`):**
8. A freshly constructed `ProbOSRuntime(...)` (before `start()`) has `_startup_complete is False`.
   Reuse whatever minimal construction pattern existing runtime tests use (e.g.
   `tests/test_runtime.py`); if construction is too heavy, assert the `__init__` default via a
   targeted read instead — but a real construction assertion is preferred.

Aim for 8+ pytest. All must pass.

---

## Section 5 — Acceptance criteria

1. `runtime._startup_complete` defaults `False` in `__init__`, set `True` as the unconditional final
   statement of `start()`.
2. The `shutdown.py` consolidation gate has an `else:` branch that (a) logs which component was None
   (AD-828a), (b) reclassifies to `"startup_incomplete"` ONLY when `_startup_complete` is falsy via
   `getattr(..., True)` honest-degrade (AD-828b).
3. `ConsolidationResult` literal includes `"startup_incomplete"`.
4. `check_previous_shutdown` permits boot for `consolidation == "startup_incomplete"` with a WARNING,
   and still raises for `"failed"` and `"skipped"`.
5. New `tests/test_ad828_startup_incomplete.py` with 8+ passing tests including the regression guards
   for `failed` and `skipped`.
6. Targeted regression GREEN (serial, `-o addopts=`):
   `tests/test_ad820_shutdown_integrity.py tests/test_ad822b_hnsw_validation.py tests/test_ad824_shutdown_hygiene.py tests/test_ad825_drain_shutdown.py tests/test_bf291_shutdown_field_absence.py tests/test_bf296_shutdown_phase_ordering.py tests/test_bf207_shutdown_episodic_integrity.py tests/test_ad819_rebuild_episodic.py tests/test_ad828_startup_incomplete.py`
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Section 6 — Do NOT change (scope boundaries)

- Do NOT touch the BF-296 Phase A intent-bus close, the AD-825 `stop_gracefully` quiesce, the
  consolidation `try/except` bodies, or the BF-303 shielded-dream-task logic. The ONLY shutdown.py
  edit is the new `else:` branch.
- Do NOT modify `mark_clean_shutdown` or `mark_dirty_shutdown`. `startup_incomplete` flows through the
  existing `mark_dirty_shutdown` path unchanged.
- Do NOT add a periodic HNSW checkpoint (that is forward marker AD-829), an atomic post-dream-cycle
  persist (AD-831), or a startup-timeout marker-skip (AD-830). Those are separate, later waves.
- Do NOT change the `__main__.py` `_serve` / `finally` shutdown invocation or the `check_previous_shutdown`
  call site arguments.
- Do NOT broad-kill python by name/path when running tests (would kill the live runtime started from
  the same venv). Use `scripts/kill-stale-pytest.ps1` or targeted `-Id` kills excluding `data/probos.pid`.
- No new dependencies. No schema changes. No config-model changes.

## Section 7 — Forward markers to file (do not implement)

- **AD-829** — periodic HNSW checkpoint (every ~5min tar.gz of the index; AD-822b boot probe restores
  from the latest checkpoint when the live index is torn). Eliminates the failure class; worst-case
  loss becomes ~5 min of episodes instead of a full rebuild-episodic.
- **AD-830** — startup-timeout marker-skip: if shutdown fires <10s after start began, skip the marker
  write entirely so the next boot attempts normal recovery.
- **AD-831** — atomic ChromaDB HNSW flush after every `dream_cycle()` (requires a ChromaDB private-API
  audit — flagged MEDIUM risk).
- **AD-828c** — record in the marker note WHICH of the two gate components was None (currently only the
  log carries it; promoting it into `shutdown_status.json` would let `probos doctor` summarize trigger
  frequency without log scraping).
