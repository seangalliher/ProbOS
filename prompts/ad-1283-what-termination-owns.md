# AD-1283 / BF-861 (#1331): what termination owns

Bound the AD-1278 overflow spill by deciding what `_terminate_stream` **owns**, rather than by waiting for a wedged writer to let go.

| | |
|---|---|
| **Status** | Ready to build |
| **Issue** | BF-861 / #1331 |
| **Depends on** | AD-1278 (BF-780, `d5d644ec`) — the spill and the termination path this bounds |
| **Files** | `src/probos/security/audit.py`, `src/probos/config.py`, `src/probos/startup/finalize.py`, `docs/development/config-reference.md` (generated), `tests/test_ad1278_audit_durability.py` |
| **Estimated tests** | +7 |
| **AD ceiling enumerated** | 1282 — `git log --all --format='%s'` subjects top at AD-1282, `prompts/ad-*.md` filenames top at 1282. Next free: **1283**. Not taken from `open-ads-report.md`. |

---

## 0. Read this first — the worktree is dirty with a rejected attempt

Two earlier attempts at BF-861 are **unstaged** in the worktree and were rejected in review. Every SEARCH block below matches **HEAD (`4ebe770a`)**, not the worktree. Revert those four files before starting:

```powershell
git restore src/probos/security/audit.py src/probos/config.py src/probos/startup/finalize.py tests/test_ad1278_audit_durability.py
```

Do not revert anything else — the worktree carries unrelated in-flight work in other files. Leave `README.md`, `docs/architecture/federation.md`, `docs/development/roadmap.md` and `config/system.yaml` alone.

---

## 1. Problem

AD-1278 made the persisted audit chain hole-free: an entry that cannot enter the write queue **spills** rather than dropping, because a dropped sequence leaves the next persisted row's `prior_hash` pointing at an absent predecessor — a chain that reports `broken` at every future boot.

#1331 is the cost. The spill is unbounded, and once the durable stream terminates the `max_entries` cap stops applying entirely, because nothing above `_persisted_through` is evictable and the watermark never advances again. Measured on HEAD (`audit.py:676` `_enforce_cap`, `audit.py:483` `_schedule_persist`):

| Scenario | `spill_maxsize` | `max_entries` | Result on HEAD |
|---|---|---|---|
| Wedged sink, 5 000 appends | n/a | 3 | `len(entries)` = **5000** |
| Wedged sink, queue of 1 | n/a | 3 | spill = **1999** |

### The two rejected attempts, and why both were wrong in the same way

**Round 1** added a spill ceiling that calls `_terminate_stream`, and let `_enforce_cap` evict once the stream was terminated. Review raised a High: the ceiling terminates from the **append** path while the writer may still hold an in-flight batch, so eviction could "destroy an entry that was still persistable."

**Round 2** applied the prescribed guard — evict only when `_stream_broken_at is not None and self._inflight == 0 and not self._retry_batch`. Review raised a new High: against a permanently wedged writer `_inflight` never returns to zero, so the gate never opens and `entries` grows without bound again. Measured 2 020 entries.

Both rounds asked *"when is it safe to evict?"* and answered *"once the writer lets go."* That makes the memory bound depend on the liveness of the one component already known to be stuck. The question was wrong.

### The premise both rounds shared is false — measured

Eviction removes list slots from `entries`. It does **not** remove entries from the writer's batch. `_next_batch` (`audit.py:558`) builds `batch: list[AuditEntry]` as its own list, `AuditEntry` is a frozen dataclass, and `_evict` does `del self.entries[:count]`. The two are independent references to the same immutable objects.

Probe against HEAD + the round-1 eviction, wedged sink released afterwards:

```
at ceiling : broken_at=2 inflight=1 entries=[0..19]
forced evict: entries=[17, 18, 19] truncated_at=(16, 'a29aa811…')
after release: disk=[0]      <-- sequence 0 reached disk AFTER being evicted
```

Sequence 0 was evicted from `entries` and **still landed on disk**. There is nothing to protect. The round-1 High is refuted by the reviewer's own measurement (`persisted_after_release [0]`) read the other way up: that entry persisted *because* eviction cannot touch the writer's batch.

### Two further defects neither review round found

Both are introduced by the ceiling itself and must be fixed here.

**Defect A — `_terminate_stream` is not idempotent, and moves backwards.** With two call sites, the second overwrites the first. Measured cleanly (ceiling at 2, then the in-flight batch exhausts its retries):

```
ceiling fired at        : 2
after retries exhausted : 0        <-- _stream_broken_at moved 2 -> 0
```

The in-flight batch always starts at `_persisted_through + 1`, which is at or below the ceiling's sequence, so the second termination *always* moves backwards or stays. `_stream_broken_at` is the one number an operator reads to learn where the on-disk chain ends.

**Defect B — the ceiling's reported sequence overstates durability.** The rejected attempt passed `self._spill[0].sequence`. But `_terminate_stream` also drains and discards everything sitting in the **queue**, and those sequences are *below* `spill[0]`. Measured: `broken_at=2` while the queue held sequence 1, which was dropped, and disk ended at 0. With the default `write_queue_maxsize` of 1000, the reported end can overstate the durable end by up to 1000 sequences.

---

## 2. Solution

`_terminate_stream` **disowns** what the writer is holding, instead of waiting for the writer to hand it back.

Termination already means "no further entry is enqueued." Make it also mean "the log no longer accounts for the in-flight batch." Then the eviction predicate is `_stream_broken_at is not None` alone — true the instant termination happens, with no dependency on writer liveness. The batch keeps its own reference and may still commit; if it does, the disk chain simply ends one batch later, still contiguous.

Four coupled changes:

1. **Ceiling** (`_note_spill`) — when the spill exceeds `spill_maxsize`, end the stream. Report `self._persisted_through + 1`, not `spill[0].sequence` (Defect B).
2. **Forward-only** (`_terminate_stream`) — first termination wins (Defect A).
3. **Disown** (`_terminate_stream`) — clear `_inflight` and `_retry_batch`.
4. **Predicate** (`_enforce_cap`) — key on termination alone; no writer-state guard.

### Why not the two alternatives

Enumerated across the three sink states that matter.

| | **(a) cancel the writer** | **(b) bounded grace period** | **(c) disown — chosen** |
|---|---|---|---|
| **Slow but recovering** | Batch cancelled mid-`persist_entries`. aiosqlite runs the work on a worker thread, so the rows may land while the confirmation is discarded and `AUDIT_PERSISTED` may not fire for them. Bounded. | Waits N seconds doing nothing, then declares loss anyway. Growth continues for N seconds. | Batch still commits (measured: `disk=[0]`); disk chain contiguous; `entries` at cap immediately. |
| **Permanently wedged** | `task.cancel()` is delivered at the next await; a genuinely hung `persist_entries` may never reach one. **The bound does not come from the cancel** — it comes from the accounting reset that has to accompany it. | Bounded only after N seconds. At the append rate needed to reach a 10 000 spill, N=5s is thousands of entries. | `entries` = 3 at cap 3 after 5 000 appends (measured; HEAD gives 5000). Bound is immediate. |
| **Refusing batches** | Cancel lands at the retry backoff; writer dies; `_commit_batch`'s `finally` clears state. Works. | Same time-boxed growth. | `entries` = 3, `_stream_broken_at` stays at the ceiling value (measured). |
| **Cost** | A cross-task cancellation race, for a literal docstring. Must be path-specific — `_commit_batch` calls `_terminate_stream` from inside the writer, where self-cancelling is wrong. | A timer scheduled from a synchronous `append` path. Does not remove unbounded growth; it time-boxes it. | The wedged task lingers holding one batch until `drain` cancels it at shutdown. Bounded by the batch size at termination. |

**(b) is rejected** because it does not solve the stated defect — it rate-limits it. **(a) is rejected** because the memory bound it appears to deliver is actually delivered by the accounting reset bundled with it; the cancel itself adds risk and buys only a docstring. **(c) is chosen** because it is the only option whose bound does not depend on the liveness of the component that is already wedged.

### Is "terminate on the ceiling" right at all?

Yes. The alternatives, enumerated:

1. **Drop from the spill head** — the oldest unwritten entries vanish while newer ones are written. That is precisely the hole BF-780 exists to prevent.
2. **Drop from the spill tail** — behaviourally identical to terminating, except it lies: `durable_stream_open()` keeps returning True while nothing is written.
3. **Backpressure (block or fail `append`)** — contradicts the module's stated contract, which the docstring makes explicit: making the sink a precondition "would turn the accountability trail into a new way to lose work."
4. **Spill to a second file** — a second durability surface with its own failure modes, added while the first one is wedged.
5. **Grow forever** — the defect.

Termination is the only bounded action that preserves "no hole." Keep it. The two review findings were never about the ceiling; they were about what termination leaves behind.

### Note on FIFO eviction and `mark_truncated`

The constraint is real as stated: `_evict` is prefix-only (`del self.entries[:count]`) and `mark_truncated` is forward-only, so a protected head range cannot be evicted around. Suffix eviction would additionally rewind `_next_sequence()` — which reads `entries[-1].sequence + 1` — colliding with persisted rows, a hazard the module already calls out; and it would discard the newest records, the wrong end of an accountability trail. The in-flight batch does sit at the head of the unpersisted region: `batch[0].sequence == _persisted_through + 1` always, because `persist_entries` is all-or-nothing and `_advance_persisted` walks contiguously.

The constraint is simply **not binding**, because the batch does not need protecting. See the measurement above.

---

## 3. Implementation

### Section 1 — config field (`src/probos/config.py`, `SecurityInfraConfig`, HEAD :4378)

```
===SEARCH===
    audit_write_max_retries: int = 3


class PermissionsConfig(BaseModel):
===REPLACE===
    audit_write_max_retries: int = 3
    # BF-861 (#1331): ceiling on the overflow buffer that holds entries the
    # write queue could not take. Reaching it means the sink is not merely
    # slow, so the durable stream ENDS rather than shedding entries -- dropping
    # would restore the chain hole the buffer exists to prevent. The resulting
    # memory bound is this plus `audit_write_queue_maxsize` unpersisted entries
    # on top of `audit_max_entries`, because an unpersisted entry is not
    # evictable. `<= 0` removes the ceiling and restores unbounded growth.
    audit_spill_maxsize: int = 10_000


class PermissionsConfig(BaseModel):
===END REPLACE===
```

### Section 2 — the reason constant (`src/probos/security/audit.py`, HEAD :78)

```
===SEARCH===
_QUIESCE_POLL_SECONDS = 0.005


@dataclass
class AuditLog:
===REPLACE===
_QUIESCE_POLL_SECONDS = 0.005

# BF-861 (#1331): why the stream ended, when it ended at the spill ceiling
# rather than at a refusing sink. The operator's remedy differs -- a slow sink
# versus a broken one -- so the two causes are not collapsed into one message.
_SPILL_CEILING_REASON = (
    "the overflow spill reached its ceiling, so the sink is not merely slow"
)


@dataclass
class AuditLog:
===END REPLACE===
```

### Section 3 — the dataclass field (`src/probos/security/audit.py`, HEAD :124)

```
===SEARCH===
    write_queue_maxsize: int = 1000
    # AD-1278: ``(sequence, entry_hash)`` of the last entry evicted from
===REPLACE===
    write_queue_maxsize: int = 1000
    # BF-861 (#1331): ceiling on the overflow spill. Reached means the sink has
    # fallen this far behind, and the stream ENDS rather than sheds -- dropping
    # would restore the chain hole the spill exists to prevent. ``<= 0``
    # disables the ceiling and restores the unbounded behaviour.
    spill_maxsize: int = 10_000
    # AD-1278: ``(sequence, entry_hash)`` of the last entry evicted from
===END REPLACE===
```

### Section 4 — the ceiling (`src/probos/security/audit.py`, `_note_spill`, HEAD :524-536)

```
===SEARCH===
                "not there. The sink is not keeping up with appends.",
                queue.maxsize, entry.sequence,
            )

    def _ensure_writer(self, loop: asyncio.AbstractEventLoop) -> "asyncio.Queue[AuditEntry]":
===REPLACE===
                "not there. The sink is not keeping up with appends.",
                queue.maxsize, entry.sequence,
            )
        ceiling = int(self.spill_maxsize)
        if ceiling > 0 and len(self._spill) > ceiling:
            # BF-861 (#1331): spilling instead of dropping is what keeps the
            # chain hole-free, and it is also what made this buffer unbounded.
            # At the ceiling the stream ENDS rather than shedding: dropping
            # here would put back the hole the spill exists to prevent, so the
            # only bounded option that keeps the guarantee is to stop.
            #
            # Reported at `_persisted_through + 1`, NOT at the spill head:
            # terminating also discards the queue, whose sequences sit BELOW
            # the spill's. Naming the spill head would claim those queued
            # sequences reached disk when they were dropped -- overstating the
            # durable end by up to `write_queue_maxsize`.
            self._terminate_stream(
                self._persisted_through + 1, _SPILL_CEILING_REASON,
            )

    def _ensure_writer(self, loop: asyncio.AbstractEventLoop) -> "asyncio.Queue[AuditEntry]":
===END REPLACE===
```

### Section 5 — the refusing-sink call site (`src/probos/security/audit.py`, HEAD :606)

```
===SEARCH===
            self._terminate_stream(batch[0].sequence, attempts + 1)
            return ()
===REPLACE===
            # `batch[0].sequence` IS `_persisted_through + 1`: `persist_entries`
            # is all-or-nothing and `_advance_persisted` walks contiguously, so
            # the two call sites report the same quantity by construction.
            self._terminate_stream(
                batch[0].sequence,
                f"the sink refused it on {attempts + 1} consecutive attempts",
            )
            return ()
===END REPLACE===
```

### Section 6 — forward-only, and disown (`src/probos/security/audit.py`, `_terminate_stream`, HEAD :611-630)

```
===SEARCH===
    def _terminate_stream(self, sequence: int, attempts: int) -> None:
        """End the durable stream rather than write past a gap.

        Deliberately terminal, and the trade is the point: a durable chain with
        a hole is worth LESS than one that stops. The first lies about its own
        integrity at every future boot -- every row after the gap reports
        ``broken`` -- while the second says plainly where it ended and
        rehydrates cleanly. Recovery needs a restart; every run until then
        labels itself ``in-memory-only``.
        """
        self._stream_broken_at = int(sequence)
        logger.error(
            "AD-1278: the audit sink refused sequence %d on %d consecutive "
            "attempts; ENDING the durable stream there. Nothing further is "
            "written, so the persisted chain stops cleanly instead of gaining "
            "a hole that would report as tampering forever. Every execution "
            "from now on is labelled in-memory-only; restart to recover.",
            sequence, attempts,
        )
        self._spill.clear()
===REPLACE===
    def _terminate_stream(self, sequence: int, cause: str) -> None:
        """End the durable stream rather than write past a gap.

        Deliberately terminal, and the trade is the point: a durable chain with
        a hole is worth LESS than one that stops. The first lies about its own
        integrity at every future boot -- every row after the gap reports
        ``broken`` -- while the second says plainly where it ended and
        rehydrates cleanly. Recovery needs a restart; every run until then
        labels itself ``in-memory-only``.

        ``cause`` distinguishes the two ways to get here -- a sink that refused
        a batch, or the BF-861 spill ceiling -- because the operator's remedy
        differs and a single message would send them after the wrong one.

        FIRST TERMINATION WINS (BF-861). With two call sites the second would
        overwrite the first, and it can only move the sequence BACKWARDS: the
        in-flight batch starts at ``_persisted_through + 1``, at or below the
        ceiling's sequence. Measured before the guard: a ceiling at 2 became 0
        once the held batch exhausted its retries. This number is what an
        operator reads to learn where the on-disk chain ends.
        """
        if self._stream_broken_at is not None:
            return
        self._stream_broken_at = int(sequence)
        logger.error(
            "AD-1278: ENDING the durable audit stream at sequence %d (%s). "
            "Nothing further is enqueued, so the persisted chain stops cleanly "
            "instead of gaining a hole that would report as tampering forever. "
            "Every execution from now on is labelled in-memory-only; restart "
            "to recover.",
            sequence, cause,
        )
        self._spill.clear()
        # BF-861: DISOWN whatever the writer is still holding. The alternative
        # -- waiting for it to fall idle -- makes the memory bound depend on
        # the liveness of the component that is already wedged, which is how
        # the second attempt at this reintroduced unbounded growth.
        #
        # Safe because eviction cannot reach the batch: `_next_batch` holds it
        # in its own list and `AuditEntry` is frozen, so `del self.entries[:n]`
        # drops slots, not entries. A disowned batch that goes on to commit
        # simply ends the disk chain one batch later, still contiguous -- which
        # is why the log message says ENQUEUED rather than written.
        self._inflight = 0
        self._retry_batch = []
===END REPLACE===
```

### Section 7 — the eviction predicate (`src/probos/security/audit.py`, `_enforce_cap`, HEAD :683)

```
===SEARCH===
        if self._persistence is None:
            # Persistence off BY CONFIGURATION: nobody was promised a durable
            # copy, so this is a ring buffer the operator chose and the
            # truncation watermark keeps the remainder verifiable. Refusing
            # here would make `max_entries` decorative in the commonest
            # deployment, which is the memory bound quietly not existing.
            self._evict(excess)
            return
===REPLACE===
        if self._persistence is None or self._stream_broken_at is not None:
            # Persistence off BY CONFIGURATION: nobody was promised a durable
            # copy, so this is a ring buffer the operator chose and the
            # truncation watermark keeps the remainder verifiable. Refusing
            # here would make `max_entries` decorative in the commonest
            # deployment, which is the memory bound quietly not existing.
            #
            # BF-861 (#1331): a TERMINATED stream is the same situation arrived
            # at by failure rather than by choice. Nothing further is enqueued,
            # so holding these entries preserves no durable copy that eviction
            # would destroy -- it only trades the hole AD-1278 prevents for an
            # unbounded heap. Measured before the fix: 5000 entries at a cap
            # of 3 against a wedged sink.
            #
            # Deliberately NOT guarded on writer state. A guard reading
            # `_inflight` or `_retry_batch` never opens against a permanently
            # wedged writer, which is unbounded growth wearing a safety
            # costume; and it guards nothing, because `_terminate_stream` has
            # already disowned the batch and eviction could not reach it
            # anyway.
            self._evict(excess)
            return
===END REPLACE===
```

### Section 8 — wiring (`src/probos/startup/finalize.py`, HEAD :3900)

```
===SEARCH===
            write_max_retries=config.security_infra.audit_write_max_retries,
        )
===REPLACE===
            write_max_retries=config.security_infra.audit_write_max_retries,
            spill_maxsize=config.security_infra.audit_spill_maxsize,
        )
===END REPLACE===
```

### Section 9 — regenerate the config reference

Adding a config field **without** this makes `tests/test_config_reference_current.py::test_the_reference_matches_the_models` fail. That is what turned the previous attempt's gate red (1 failed, 25283 passed).

```powershell
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py
```

Commit the regenerated `docs/development/config-reference.md` with the change.

---

## 4. Tests

Add to `tests/test_ad1278_audit_durability.py`. Use a fake sink with an `asyncio.Event` gate and a `mode` of `wedge` / `refuse` / `serve`; run each case in its own event loop so an orphaned writer from one case cannot bleed into the next (this confounded an early probe).

| # | Test | Pins |
|---|---|---|
| 1 | `test_the_spill_is_bounded_by_ending_the_stream_not_by_dropping` | Wedged sink, `spill_maxsize=5`: the spill stops growing, `_stream_broken_at` is set, and no sequence is silently dropped from a still-open stream. |
| 2 | `test_a_terminated_stream_lets_the_cap_apply_again` | Wedged sink, 5 000 appends, `max_entries=3` → `len(log.entries) == 3`. **Must fail on HEAD with 5000.** |
| 3 | `test_eviction_does_not_take_the_in_flight_batch_off_the_disk` | The crux. Fire the ceiling, let the cap evict past the in-flight batch, release the sink; assert the batch's sequences reached the sink and the persisted sequences are contiguous. Guards against a future "protect the writer" regression. |
| 4 | `test_termination_is_forward_only` | Ceiling fires at S; a refusing writer then exhausts its retries; `_stream_broken_at` is still S. **Must fail without Section 6 with S → 0.** |
| 5 | `test_the_reported_end_never_overstates_the_durable_end` | Every sequence at or below `_stream_broken_at - 1` that was discarded from the queue would break this; assert `_stream_broken_at <= min(sequence not persisted)`. **Must fail if Section 4 reports `spill[0].sequence`.** |
| 6 | `test_a_zero_ceiling_restores_the_unbounded_buffer` | `spill_maxsize=0` → no termination, spill grows. The documented opt-out. |
| 7 | `test_the_ceiling_does_not_fire_while_the_sink_keeps_up` | Serving sink, appends well past `spill_maxsize` in total but never that far behind → `_stream_broken_at is None`, chain intact. No false termination. |

Each of 2, 4 and 5 must be shown failing against reverted-to-HEAD source before the fix is applied. A test that passes both before and after is pinning nothing.

Focused gate:

```powershell
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1278_audit_durability.py tests/test_config_reference_current.py -q -p no:randomly
```

---

## 5. What this does NOT change

- **No writer cancellation.** `_terminate_stream` does not call `task.cancel()`. Rejected in §2; a wedged writer is reaped by the shutdown `drain`.
- **No timer, no grace period.** Nothing schedules work from the synchronous `append` path.
- **The retry path.** `_commit_batch`'s in-place retry, `write_max_retries`, and the backoff constant are untouched.
- **`mark_persisted_through`.** Its monotonic-and-contiguous guard, and the refusal to jump, stay exactly as they are.
- **`verify_chain` / `chain_state` / `mark_truncated`.** Truncation semantics are unchanged; a terminated-then-capped log still reports `truncated`, not `broken`.
- **`durable_stream_open()`.** Still admission-only, still returns False once terminated. Callers still say "queued", never "durable".
- **The shutdown sequence.** `startup/shutdown.py` phases 1 and 2 are untouched. Note that `_unflushed()` correctly reads 0 after termination, because the log no longer accounts for the disowned batch — the loss is announced once, by `_terminate_stream`'s ERROR, with its cause. Do **not** add a second loss report in `drain`.
- **`_note_spill`'s existing one-shot warning.** The ceiling check is appended after it, not merged into it.
- Nothing outside the four source files, the generated config reference, and the one test file.

---

## 6. Tracking

- `PROGRESS.md` — CLOSED entry for BF-861 (#1331) with a one-line cause.
- `docs/development/roadmap.md` Bug Tracker — **skip.** That file carries unrelated unstaged work in this worktree; do not touch it in this change.
- `DECISIONS.md` — add AD-1283 recording the decision that termination disowns rather than waits, and why the two alternatives were rejected.

---

## 7. Acceptance criteria

1. Wedged sink, 5 000 appends, `max_entries=3` → `len(entries) == 3`.
2. Refusing sink after a ceiling termination → `_stream_broken_at` unchanged from the ceiling value.
3. The reported termination sequence never exceeds the lowest sequence that failed to reach the sink.
4. An in-flight batch evicted from `entries` still reaches the sink when it recovers, and the persisted sequences stay contiguous.
5. `spill_maxsize <= 0` restores the pre-BF-861 unbounded behaviour, documented as such.
6. `docs/development/config-reference.md` regenerated; `tests/test_config_reference_current.py` green.
7. Tests 2, 4 and 5 demonstrated red against HEAD before the fix.
8. Full repository gate green, run **after** the change is frozen: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`. Expected +7 tests.
9. Adversarial review (`Diff Reviewer`, a different model than the author) run on the staged diff, with findings addressed before commit.
10. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## 8. Verified against codebase (2026-08-28, HEAD `4ebe770a`)

```
git show HEAD:src/probos/security/audit.py | Select-String ...
   78: _QUIESCE_POLL_SECONDS = 0.005
  124: write_queue_maxsize: int = 1000
  483: if self._persistence is None:              (_schedule_persist early-return region)
  524: def _note_spill(
  527: self._spilled += 1
  558: async def _next_batch(                     (builds `batch` as its own list)
  606: self._terminate_stream(batch[0].sequence, attempts + 1)
  611: def _terminate_stream(self, sequence: int, attempts: int) -> None:
  621: self._stream_broken_at = int(sequence)
  630: self._spill.clear()
  676: def _enforce_cap(self) -> None:
  683: if self._persistence is None:

git show HEAD:src/probos/config.py | Select-String ...
 4378: audit_write_max_retries: int = 3
 4381: class PermissionsConfig(BaseModel):

git show HEAD:src/probos/startup/finalize.py | Select-String ...
 3900: write_max_retries=config.security_infra.audit_write_max_retries,
 3938: runtime.audit_log.entries.extend(loaded)
 3939: runtime.audit_log.mark_persisted_through(loaded[-1].sequence)   <-- watermark IS seeded
       at boot, so `_persisted_through + 1` is correct on a rehydrated log too.

tests/test_config_reference_current.py:37 -> "python scripts/gen_config_reference.py"

AD ceiling: git log --all --format='%s' -> 1277,1278,1279,1280,1281,1282
            prompts/ad-*.md            -> 1277,1278,1279,1280,1281,1282
            combined maximum 1282; next free 1283.
```

### Absence verified

```
CLAIM: nothing re-reads `entries` to persist at teardown, so eviction cannot
       destroy a copy that shutdown would otherwise have saved.
RUN:   grep_search "audit_log\.(drain|flush|entries)|\.audit_log\b.*entries" over src/probos/**/*.py
FOUND: finalize.py:3938 (boot rehydrate, extends), shutdown.py:94 (flush),
       shutdown.py:128 (drain). Both shutdown calls drain the WRITER
       (queue/spill/in-flight); neither reads `entries`.
HOLDS: yes.

CLAIM: no AD is already allocated to BF-861 / #1331 (allocated-but-unbuilt check).
RUN:   grep_search "BF-861|#1331|1331" over prompts/**
FOUND: 18 hits in 10 files, all incidental line numbers or issue counts
       (`_cmd_rebuild_episodic (:1331)`, "1331 issues scanned", test-count 11331).
       No prompt for this issue.
HOLDS: yes -- AD-1283 is a fresh allocation, not a revision.
```

### Measurements (probes, HEAD source, isolated event loops)

```
E unfixed wedge, 5000 appends : entries=5000  (cap 3)          <-- the defect
C   fixed wedge, 5000 appends : entries=3                      <-- bounded
D   fixed wedge then released : entries=3  disk=[0]            <-- batch still landed
B   fixed refusing sink       : entries=3  broken_at=2         <-- forward-only held
A unfixed refusing sink       : ceiling 2 -> broken_at 0       <-- Defect A
  unfixed, queue held seq 1, dropped; disk ended at 0, broken_at=2  <-- Defect B
```
