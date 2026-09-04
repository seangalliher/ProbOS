# AD-1298 — Replace the CancelCleanup flag handshake with a lock-guarded state machine

Closes #1305 (BF-839). Split out of BF-788 (#1252) because the remaining work is a
**design decision, not an eleventh patch**. Ten adversarial review rounds each closed
one seam and found another *at the same seam*. **Do not propose or add another flag.**

## Premise — both residuals verified by execution, neither misstated

### Residual 1 — the RUNNING-but-not-`started` window

`ThreadPoolExecutor._WorkItem.run` calls `set_running_or_notify_cancel()` (the future
becomes uncancellable) **before** invoking the callable. So `cancel()` returns `False`
while `started` is still clear, the asyncio wrapper future cancels regardless, and
`CancelledError` reaches the caller — which then concludes it owns the directory.

Reproduced through the real `SubprocessSandbox`, premise asserted first (worker RUNNING
∧ `started` clear; the probe aborts otherwise):

```
premise_worker_running=True premise_started_clear=True
START_BOUNDARY_RACE cancellation=CancelledError
tool_predicate_says_tool_owns_dir=True
workdir_before_worker_entry=False
staged_input_before_worker_entry=False
child_outcome="FileNotFoundError: [Errno 2] No such file or directory: 'input.txt'" exit=1
```

**Natural frequency — the fact the issue did not establish:**

```
trials=6000 observed_RUNNING=5996 cancelled_while_queued=4
NATURAL_WINDOW running_but_callable_not_entered=30/5996
```

≈0.5 % of cancels landing on a RUNNING future, with **no artificial gating**. A real
production window. (An earlier coarser probe returned 0/400 and was correctly discarded
as non-discriminating rather than reported as absence.)

### Residual 2 — worse than stated: TWO unguarded exits, not one

```
FAILED_KILL              returned_ExecutionResult=True success=False timed_out=False child_alive_on_return=True
TIMEOUT_FOLLOWUP_FAILURE returned_ExecutionResult=True success=False timed_out=False child_alive_on_return=True
```

The `except BaseException` arm (`isolation.py:618-635`) kills, bounded-waits 5 s, warns
and re-raises; the outer `except Exception:  # honest-degrade` (~`:651`) converts it
straight back into an `ExecutionResult`. The post-`TimeoutExpired` retry at `:616` sits
**outside** the handler, so it also loses `timed_out=True`.

*Warning and then deleting is the original corruption with a log line added.*

### Sites

| Thing | Location |
|---|---|
| `class CancelCleanup` | `src/probos/execution/isolation.py:152` |
| `claim()` | `src/probos/execution/isolation.py:184` |
| executor submit | `src/probos/execution/isolation.py:486` |
| caller's cancel handler | `src/probos/execution/isolation.py:487-505` |
| `_run_sync` → `started.set()` | `src/probos/execution/isolation.py:513-520` |
| tool ownership predicate | `src/probos/tools/code_execution_tool.py:919-924` |
| sole production consumer | `src/probos/tools/code_execution_tool.py:675` |

## Already tried and DEAD — do not re-propose

| Approach | Why it died |
|---|---|
| `finally`-only retry in `SubprocessSandbox` | Inert — all 5 production call sites supply `workdir`, so `created_workdir=False` |
| `os.path.lexists` survival check | Swallows `OSError` → `PermissionError` read as "removed". This *was* the root cause |
| `Path.exists()` | Follows symlinks/junctions |
| Single flag | Worker reads it one instant before the loop sets it → neither cleans up |
| Two flags, no `claim()` | Both remove — `REMOVE_CALL_COUNT=2` on separate threads |
| Unconditional loop-side dispatch | Broke AD-1247 teardown tests |
| Claim-before-removal-is-guaranteed | `shutdown(cancel_futures=True)` → claimed, never removed |
| More `Event`s | Ten rounds; each closed one seam and opened another at the same seam |

## Decision — lock-guarded state machine; the worker honours the caller's abort

One `threading.Lock` guarding one state field:

```
QUEUED → {ABORTED | RUNNING} → {REAPED | UNSAFE}
```

- **Caller's cancel handler:** `with lock:` if `QUEUED` → set `ABORTED`, **caller owns
  teardown**; else → **worker owns**.
- **Worker, as the FIRST statement inside the executor callable:** `with lock:` if
  `ABORTED` → **return without spawning**; else → `RUNNING`.

The winner is whoever takes the lock first, and **the loser adapts instead of guessing**.
The decisive property: *the caller never needs to know whether the future was still
cancellable — it only needs the worker to honour the decision.* In the start-boundary
window the caller wins, deletes the directory, and the worker aborts **before** `Popen`,
so there is nothing to corrupt.

`ABORTED` is a **definite** "no child will ever exist" — strictly better evidence than
AD-1247's bounded `launch.resolved.wait()`, converting an "unknown" audit record into a
known zero. (Cf. the standing distinction: *nothing was sent* vs *sent and heard nothing*.)

### Rejected alternatives

- **B — don't cancel, join the worker.** Buys residual 1 by deleting cancellability —
  the exact "fix by removing a control" shape Design Principle 13(b) names. Blocks the
  unwinding turn for up to `timeout_seconds`, contradicts the BF-781 propagation
  contract, violates the async rule against swallowing cancellation, hangs shutdown.
  The bounded variant only *narrows* the window and adds delay on the cancellation path
  that BF-788 acceptance criterion #3 explicitly forbade. Does nothing for residual 2.
- **C — structural directory ownership.** A worker-minted subdirectory dies with the
  recursive `rmtree` of its parent. Truly structural means not staging into a shared
  directory — but staging **is** AD-1074d (the Cowork round-trip), so this trades the
  feature for the fix. **Fold in `mkdir(exist_ok=False)`** as the ownership boundary
  (it closes the separate UUID-collision residual); do not promote.
- **D — advisory lock file / held handle.** Windows blocks deletion of an open file,
  POSIX does not, so the arbiter means different things on the two CI platforms.
  Rejected by reasoning; POSIX not probed.

## Build

**Files:** `src/probos/execution/isolation.py`, `src/probos/tools/code_execution_tool.py`,
`tests/test_bf788_workdir_cleanup_retries.py` (16 references — the audit trail; **update,
never delete**).

**Symbols.** Keep the class name `CancelCleanup` (import stability at
`code_execution_tool.py:43`). Replace the three public `Event`s with a private lock +
state, exposing `begin_worker() -> bool`, `note_cancelled() -> bool`,
`note_worker_done(*, child_reaped)`, `mark_unsafe(reason)`, `safe_to_remove`,
`caller_owns_teardown`, `claim()`. **Remove `cancelled`/`finished`/`started`
outright** — leaving them as read-only properties invites the old reasoning back. **No
`release()`**: an ownerless reset is a way for a losing site to take the directory back
from the winner, so it waits for the tokenised recovery path that needs it.

The right-hand states are FINAL and the graph is **enforced, not merely drawn**. Reject
transitions out of `REAPED`/`UNSAFE` and out of `ABORTED` into `REAPED`; without that,
`UNSAFE -> begin_worker() -> RUNNING -> REAPED` un-records a live child and makes
`UNSAFE` non-sticky under reuse.

Add `ExecutionResult.child_reaped: bool = True`. The default keeps every path that never
spawned reading as before, and every enumerated in-repo consumer maps explicit fields —
but it is a dataclass, so `repr()` and `dataclasses.asdict()` both gain a key and
anything snapshotting one of those wholesale sees the difference. Do **not** call it
byte-identical. Add `_terminate_and_reap(proc) -> bool` and route **both** exceptional
`communicate()` exits through it, setting the `UNSAFE` terminal state that **both**
cleanup owners consult — plus the sandbox-owned `finally` in `_run_sync_inner`, which
neither owner can see because both are gated on `request.workdir is not None`.

**Must NOT change:** `remove_workdir` retry/backoff and `_still_present`; BF-840's
`remove_workdir_off_loop` shield; `run()` re-raising `CancelledError`; AD-1074d staging;
the AD-1247 audit contract **except** that `ABORTED` now resolves `launched=False` —
call that out explicitly and pin it with its own test. **No new config flag.** Do **not**
wire `code_runner`/`skill_forge` — that stays #1306.

## Acceptance criteria

1. **`test_bf839_start_boundary_worker_honours_caller_abort`** — the test that proves
   residual 1 is closed. Gate by wrapping the executor callable
   `SubprocessSandbox._run_sync`. That boundary is correct **only if** the state
   transition is the first **effectful** operation inside that callable — reading
   `request.cleanup_on_cancel` above it creates nothing, but **the build must keep
   everything that spawns or touches the filesystem below it, or the test silently stops
   discriminating.**
   - **Premise assertion, `pytest.fail` on violation:** wrapper entered ∧ `begin_worker()`
     not yet called (future RUNNING, state still `QUEUED`).
   - Stage `input.txt`; cancel the awaiting task; run the tool's real teardown predicate.
   - Release the gate; let the worker proceed.
   - Assert `launch_outcome.launched is False`, no child spawned, no staged file removed
     beside a live child.
   - **Against HEAD this must FAIL** (measured: `staged_input_before_worker_entry=False`,
     `child_outcome=FileNotFoundError`).
2. Mirror case: worker takes the lock first → caller hands off.
3. Residual 2: fake `Popen` with failing `kill`/`wait` → `child_reaped is False`,
   `timed_out is True` on the timeout variant, and **workdir still present** after
   teardown. Cover **both** exits, **and** the `workdir=None` path, where the arbiter
   sees nothing and `_run_sync_inner`'s own `finally` is the only guard — assert on the
   removal ATTEMPT, since removal is dispatched rather than awaited elsewhere and
   presence does not discriminate.
4. **Exactly-once is pinned to the ARBITER, not to `claim()`.** Instrument
   `_remove_workdir`, drive a real cancellation where both production sites observe, and
   assert **exactly one** removal. Deleting `claim()` from every site is **expected to
   leave the suite green** — the lock-guarded state makes the owners mutually exclusive
   by construction, so `claim()` is no longer what stands between one removal and two.
   Verify by mutation that mutating the **arbiter** turns it red (forcing
   `caller_owns_teardown` True makes the tool remove the directory beside the live
   child). `claim()` stays as a defensible second layer against a future site or a retry
   loop, and is unit-tested as that primitive in the BF-788 file. Earlier drafts of this
   criterion required a `claim()` mutation to turn the test red; the implementation
   knowingly does not provide that, and a spec asserting a property its code does not
   have is the exact defect this AD exists to remove.
5. Terminal states are terminal: forbidden-transition tests for `begin_worker` and
   `mark_unsafe` out of `REAPED`/`UNSAFE`, and for `note_worker_done` out of `ABORTED`.
6. Mutation checks kill. Full canonical gate green.
7. Verify all changes comply with the Engineering Principles in
   `.github/copilot-instructions.md`.

## Deferred to its own issue

The dedicated cleanup executor — `_remove_workdir` occupies a shared default-executor
thread ~9 s across 75 uses in 33 files. Real, but a different change.
