# AD-1296 — working-directory ownership without a liveness question

**Supersedes:** the ownership/sweep state model of AD-1265 (branch `ad-1265-handback`, `46d8347e`).
**Status:** ready to build · **Applies to:** branch `ad-1265-handback`, **not** `main`
**Dependencies:** the rest of AD-1265 (manifest, verify, coverage, retention, scheduler, CLI) is kept as built.
**Estimated tests:** ~22 (replaces the 13 in `tests/test_ad1265_working_dir_ownership.py`)
**Closes:** nothing on its own — it unblocks AD-1265, which closes #1313 and #1304.

---

## Why this exists

AD-1265 hit its own stop rule. Round 2 returned a Required finding *inside* the
machinery the AD introduced, which is the shape that got AD-1262 reverted. The
build is otherwise good — 99 focused tests, two mutation probes at 6/6 and 7/7,
every guard proven load-bearing. **Do not redo it.** This prompt replaces one
subsystem and deletes more code than it adds.

### The three measured failures, and the one thing they share

| # | Failure | Reached through |
|---|---|---|
| 1 | A peer's sweep deleted a live service's `.incomplete` directory | `_is_abandoned` |
| 2 | A path-keyed claim `set` let a rename-losing peer release the *winner's* claim | `_is_active` |
| 3 | An unreadable / truncated / zero-byte `owner.json` reads as abandoned and is swept while a handle is open | `_read_owner` → `_is_abandoned` |

Plus four disclosed non-guarantees — PID recycling makes a directory immortal;
`_OWNER_STALE_SECONDS` "can in principle delete a peer that is still writing";
the POSIX reservation rests on a working directory never being empty; nothing
works across two hosts on shared storage.

**Every one of those seven is reachable only through a sweep that judges
liveness.** They are not seven defects. They are one design decision, observed
seven times.

### The answer is already in the file

`_sweep_staging` (branch L608) decides ownership by **parsing the PID out of the
directory name**. It has no marker to read, therefore no parse-failure branch,
therefore no round-2 finding — and its default on an unparseable name is
`continue`, i.e. *keep*. That is the correct design and the correct default,
already written, already tested, in the same file.

`_stage_owned_dir` then **renames that directory to `<ts>.incomplete`**, which
moves identity out of the name (atomic, always present, unforgeable) and into
`owner.json` (readable, parseable, corruptible, absent-able). Every failure in
the table above lives downstream of that one rename.

### What the rename buys, priced

It reserves the `<ts>` name so two peers do not both build for a minute and one
lose at promotion. Measured on this machine — probe asserts its own premise
before testing the claim:

```
CONTROL: replace onto ABSENT target -> OK (premise holds)
NON-EMPTY target -> refused: PermissionError errno=13
EMPTY target     -> refused: PermissionError errno=13
platform: win32
```

`os.replace` already refuses a directory-onto-directory promotion on Windows
unconditionally, and on POSIX for any non-empty target — and a promoted
snapshot always holds its manifest, so it is never empty. **The reservation buys
no correctness that promotion does not already provide.** It buys one avoided
wasted build in a same-second race, and it costs the entire failure table.

---

## Decisions

**D1 — Identity goes in the name. There is no ownership marker.**
Working directories are `<ts>[-<micros>].<pid>-<runid>.incomplete`, created by a
single `mkdir(exist_ok=False)`. The name is complete the instant the directory
exists, so there is no window in which a peer sees an unowned directory — the
property `_stage_owned_dir` + rename exists to manufacture, obtained for free.
No `owner.json`, no `_read_owner`, no parse-failure branch. **Finding 3 becomes
unreachable rather than guarded.**

**D2 — The sweep makes no liveness judgement.**
It reclaims only what is decidable with certainty: a directory carrying *this
process's* PID and a run-id this process is *not currently writing*. That is
knowable from memory, exactly, with no syscall and no recycling risk. Everything
else — foreign PID, unparseable name, legacy `<ts>.incomplete` — is **kept and
reported, never deleted.** `is_pid_alive` leaves the decision path entirely.
Findings 1 and 2 and all four non-guarantees become unreachable.

**D3 — Unknown ownership means keep, count, and warn.**

| | Cost when wrong | Visibility | Bound |
|---|---|---|---|
| Delete on unknown | Destroys an in-flight snapshot **and** breaks a live peer mid-write (measured, round 1: peer failed `ENOENT` on a file it was copying) | Silent; surfaces as a confusing `ENOENT` in the *victim* | — |
| Keep on unknown | Disk | Loud, if counted | Operator reclaim |

These are not symmetric. One is a silent correctness loss **in the component
whose entire job is not losing data**; the other is a visible resource cost. The
existing code already agrees in spirit — `_OWNER_STALE_SECONDS` is set three
orders of magnitude beyond any snapshot duration precisely because deleting a
live directory was judged worse than leaking one. This decision removes the
branch that judgement was trying to make safe.

Accumulation is not a regime here: a foreign leftover requires a **crash inside
the snapshot window**, and each one needs a separate crash. The regime that does
accumulate — a process ticking hourly and failing every time — is exactly the
case D2 reclaims with certainty.

**D4 — Leaks must not be silent.** `prune()` enumerates promoted directories
only (`_SNAPSHOT_DIR_RE`), so a leaked working directory is invisible to the byte
ceiling. Count them, report them on every result, warn once per tick, and give
the operator a CLI reclaim. Do **not** fold their bytes into `max_total_bytes`:
that would prune healthy snapshots and fire the D2 retention warning with advice
("raise max_total_bytes") that misattributes the cause.

**D5 — Not chosen: an OS lock file.** A held `flock`/`LockFileEx` handle would
collapse liveness and readability into one question, which is the right instinct.
It is rejected because it adds new per-platform code *in the exact subsystem that
has now failed review twice*, and it is unreliable on the network filesystems
that motivate the cross-host case. D1+D2 reach the same guarantee by deleting
code instead of adding it. Revisit only if cross-host concurrent backup to shared
storage becomes a real requirement — it is not one today.

---

## Section 1 — delete the marker, the staging dance, and the claim registry

### 1a. Imports

```
===SEARCH===
from probos.infrastructure.snapshot_manifest import (
    INCOMPLETE_SUFFIX,
    OWNER_NAME,
    STATE_COPIED,
===REPLACE===
from probos.infrastructure.snapshot_manifest import (
    INCOMPLETE_SUFFIX,
    STATE_COPIED,
===END REPLACE===
```

Keep the `from probos.pidfile_guard import is_pid_alive` line — Section 4 uses it
for an operator-facing hint only, never for a decision.

### 1b. Replace the staging constants and the claim registry

Replace everything from `#: Where a working directory is assembled` (branch L80)
through the end of `_is_active` (branch L128) with:

```python
#: ``<ts>[-<micros>].<pid>-<runid>.incomplete``. The owner is in the *name*, so
#: it is present the instant the directory exists and cannot be truncated,
#: emptied or made unreadable. AD-1265 kept it in an ``owner.json`` instead;
#: review then measured a zero-byte marker reading as abandoned and the sweep
#: removing a directory another process held open. A name has no parse-failure
#: mode, so that branch does not exist here.
_WORKING_DIR_RE = re.compile(
    r"^(\d{8}-\d{6}(?:-\d{6})?)\.(\d+)-([0-9a-f]{8})" + re.escape(INCOMPLETE_SUFFIX) + r"$"
)

_LIVE_LOCK = threading.Lock()
#: Run ids this process is writing *right now*. Two BackupService instances in
#: one process share a PID, so the PID alone cannot tell a live sibling's
#: directory from one an earlier tick left behind; this can.
#:
#: Keyed on the run id, not the path. AD-1265 keyed it on the path and two
#: attempts racing for the same ``<ts>`` therefore shared one key, so the
#: loser's release revoked the winner's claim and the sweep ate a live
#: directory -- a defect reached from inside the fix for it. A run id is unique
#: per attempt by construction, so two attempts can never collide on a key and
#: no reference counting is needed. They also no longer contend for a directory
#: name at all: each gets its own.
_LIVE_RUNS: set[str] = set()


def _run_begin(run_id: str) -> None:
    with _LIVE_LOCK:
        _LIVE_RUNS.add(run_id)


def _run_end(run_id: str) -> None:
    with _LIVE_LOCK:
        _LIVE_RUNS.discard(run_id)


def _run_is_live(run_id: str) -> bool:
    with _LIVE_LOCK:
        return run_id in _LIVE_RUNS
```

Delete `_OWNER_STALE_SECONDS` (L86–94) with its comment. Nothing replaces it:
it existed solely to bound a PID-recycling case that D2 makes unreachable.

---

## Section 2 — create the working directory under its own name

Replace `_make_snapshot_dir` (branch L473–518) and delete `_stage_owned_dir`
(L520–532) entirely.

```python
def _make_snapshot_dir(
    self, started: float, run_id: str,
) -> tuple[Path | None, Path | None, tuple[str, str]]:
    """Create this run's private working directory and pick its promoted name.

    One ``mkdir``. No staging directory and no reservation rename: the name
    carries the owner, so it is never briefly unowned, and two peers in the
    same second get different directories instead of racing for one.

    ``final_dir`` is only *chosen* here. Promotion is what claims it, and
    ``os.replace`` refuses a directory onto an existing directory, so a peer
    that picks the same name loses at promotion and degrades down the
    already-tested ``promote_error`` path. The reservation this replaces bought
    one avoided wasted build and cost every failure in AD-1296 D1.
    """
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(started))
    for base in (
        timestamp,
        f"{timestamp}-{int((started % 1) * 1_000_000):06d}",
    ):
        final_dir = self._backup_root / base
        if final_dir.exists():
            continue
        working_dir = (
            self._backup_root
            / f"{base}.{os.getpid()}-{run_id}{INCOMPLETE_SUFFIX}"
        )
        try:
            working_dir.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            return None, None, (str(working_dir), f"mkdir failed: {exc}")
        return working_dir, final_dir, ("", "")
    return None, None, (
        str(self._backup_root / timestamp),
        "mkdir failed: both the timestamped and collision-suffixed names exist",
    )
```

In `snapshot()` (branch L245–255), mint the run id and swap the claim calls:

```
===SEARCH===
        started = time.time()

        working_dir, final_dir, failure = self._make_snapshot_dir(started)
        if working_dir is None or final_dir is None:
            return self._fail(failure[0], started, failure[1])
        try:
            return self._write_snapshot(started, working_dir, final_dir)
        finally:
            # The peer sweep consults these claims. Leaving one behind would
            # make a finished directory immortal, so it is released on every
            # path out -- promoted, failed or raised.
            _release_active(working_dir)
===REPLACE===
        started = time.time()
        run_id = uuid.uuid4().hex[:8]

        # Registered before the directory exists, never after: the sweep must
        # never see a directory of ours whose run is not yet marked live.
        _run_begin(run_id)
        try:
            working_dir, final_dir, failure = self._make_snapshot_dir(started, run_id)
            if working_dir is None or final_dir is None:
                return self._fail(failure[0], started, failure[1])
            return self._write_snapshot(started, working_dir, final_dir)
        finally:
            # Retired on every path out -- promoted, failed or raised. Leaving
            # one live would make this run's directory immortal.
            _run_end(run_id)
===END REPLACE===
```

In `_promote` (branch L534–556) delete the marker unlink and its docstring
paragraph — there is no marker to drop. Keep `os.replace` and the paragraph
explaining why the rename *is* promotion.

---

## Section 3 — a sweep that decides nothing it cannot prove

Replace `_sweep_incomplete` (L558–608), `_is_abandoned` (L610–656),
`_sweep_staging` (L658–681) and `_read_owner` (L683–691) with the following two
methods. Net: four methods to two, and no `is_pid_alive` in either.

```python
def _sweep_incomplete(self, *, exclude: Path) -> SweepResult:
    """Reclaim this process's finished working directories. Nothing else.

    A working directory can never be admitted -- promotion is the sole marker
    of completeness -- so one left behind is pure cost. But AD-1265 measured
    what reclaiming aggressively costs: a peer's sweep deleted a live
    service's directory and the victim failed ``ENOENT`` mid-copy, and a
    zero-byte ownership marker was enough to make a held-open directory read
    as abandoned.

    So this sweep answers only the question it can answer exactly. A directory
    naming *this* PID and a run id this process is not currently writing is
    finished, with certainty, from memory, with no syscall. Everything else is
    left alone and returned to the caller to report: a foreign PID cannot be
    judged (PIDs recycle and are not comparable across hosts), and neither can
    a name this code did not write.

    Deleting on "unknown" trades a silent correctness loss in the one
    component whose job is not losing data for a visible, operator-reclaimable
    disk cost. See AD-1296 D3, and ``probos backup-reclaim``.
    """
    try:
        children = list(self._backup_root.iterdir())
    except OSError:
        return SweepResult()

    result = SweepResult()
    mine: list[Path] = []
    for child in children:
        if child == exclude or not child.name.endswith(INCOMPLETE_SUFFIX):
            continue
        if not child.is_dir():
            continue
        match = _WORKING_DIR_RE.match(child.name)
        if match is None:
            # Predates this naming, or nothing this code wrote. Unknown owner.
            result.foreign_dirs.append(str(child))
            continue
        pid, run_id = int(match.group(2)), match.group(3)
        if pid != os.getpid():
            result.foreign_dirs.append(str(child))
            continue
        if _run_is_live(run_id):
            continue  # A sibling BackupService in this process is writing it.
        mine.append(child)

    # Oldest first, so a sweep interrupted part-way still made progress on the
    # directories abandoned longest. Names are timestamp-prefixed, so lexical
    # order is chronological order.
    mine.sort(key=lambda child: child.name)
    for child in mine:
        manifest = read_manifest(child)
        failed = [e.label for e in manifest.failed] if manifest else []
        try:
            shutil.rmtree(child)
        except OSError as exc:
            logger.warning(
                "AD-1296: could not remove this process's finished working "
                "directory %s (%s); it stays on disk and is retried next tick",
                child, exc,
            )
            continue
        result.reclaimed_dirs.append(str(child))
        logger.info(
            "AD-1296: reclaimed finished working directory %s "
            "(never promoted; failed files: %s)",
            child, ", ".join(failed) or "unrecorded",
        )

    result.foreign_bytes = sum(
        self._dir_size(Path(p)) for p in result.foreign_dirs
    )
    if result.foreign_dirs:
        # Retention cannot see these -- _SNAPSHOT_DIR_RE matches promoted names
        # only -- so without this line the leak is completely silent.
        logger.warning(
            "AD-1296: %d working director(ies) totalling %d bytes belong to "
            "another process or predate this naming and are NOT reclaimed "
            "automatically; retention cannot see them. Run "
            "'probos backup-reclaim --backup-root %s' to review them: %s",
            len(result.foreign_dirs), result.foreign_bytes, self._backup_root,
            ", ".join(result.foreign_dirs[:5]),
        )
    return result
```

Add the result type beside `PruneResult` (branch L161–171):

```python
@dataclass
class SweepResult:
    """What one working-directory sweep reclaimed, and what it refused to."""

    reclaimed_dirs: list[str] = field(default_factory=list)
    #: Working directories this process cannot prove are finished. Kept, never
    #: deleted, and reported so the leak is not silent. See AD-1296 D3.
    foreign_dirs: list[str] = field(default_factory=list)
    foreign_bytes: int = 0
```

Carry it out on `BackupResult` — add after `retention_bound` (L154):

```python
    #: Working directories left alone because ownership could not be proven.
    orphaned_working_dirs: list[str] = field(default_factory=list)
    orphaned_bytes: int = 0
```

`_write_snapshot` (L260) already calls `self._sweep_incomplete(exclude=working_dir)`;
capture the result and populate those two fields on the returned `BackupResult`
on **both** the success and failure paths.

---

## Section 4 — `probos backup-reclaim`

The operator's half of D3. Without it, "keep on unknown" has no bound.

Add to `src/probos/__main__.py`, beside the existing `verify-snapshot` handler
and parser (both added by AD-1265):

- `_cmd_backup_reclaim(args)` — lists every `*.incomplete` directory under
  `--backup-root` with its size, age, and parsed owner. For a parsed foreign
  PID, append an **advisory** `owner PID N is not running` using `is_pid_alive`.
  Label it as a hint, and say in the handler docstring that it is unreliable
  across hosts and under PID recycling — which is exactly why it informs a human
  and never an automatic delete.
- `--force` removes the listed directories; without it the command only reports.
  Exit `0` when nothing is orphaned, `1` when something is (so a health check can
  use it), `2` on bad arguments.
- Follow `verify-snapshot`'s precedent: no AD-816 pidfile guard for the read-only
  listing. **`--force` must take the pidfile guard** — it deletes, and a live
  vessel may own one of those directories.

---

## Section 5 — `snapshot_manifest.py`

Delete `OWNER_NAME` (L70) and its comment. Nothing references it after Section 1.
Leave `INCOMPLETE_SUFFIX`, `MANIFEST_NAME` and the `STATE_*` constants alone.

---

## Tests

Replace `tests/test_ad1265_working_dir_ownership.py` with
`tests/test_ad1296_working_dir_ownership.py`.

**Carry over, retargeted (3):**
1. `test_a_peer_sweep_does_not_destroy_an_in_flight_working_directory` — the
   round-1 regression. Now passes without any liveness call.
2. `test_this_process_earlier_finished_working_directory_is_reclaimed` — own PID,
   retired run id.
3. `test_a_promoted_snapshot_directory_name_carries_no_owner_segment`.

**Delete with the mechanism (5):** the live-foreign-PID case, the dead-PID case,
the `_OWNER_STALE_SECONDS` backstop, `marked_before_visible`, and the two staging
tests. Each asserted a behaviour of code that no longer exists. Record in the
build report that they were deleted **because their mechanism was deleted**, not
because they failed.

> One is a deliberate **behaviour inversion**, not a deletion: AD-1265 asserted
> a dead foreign PID's directory *is* swept. Under D3 it is not. State that
> inversion explicitly in the report and in `DECISIONS.md` — a reviewer must not
> have to infer it from a missing test.

**New (~19):**

| # | Test | Proves |
|---|---|---|
| 4 | An unreadable / truncated / **zero-byte** `owner.json` inside a working directory changes nothing | **The round-2 finding, structurally.** Assert the premise first: the same directory with a *valid* marker is also untouched, so "not swept" is not vacuous |
| 5 | A directory whose owner is a dead foreign PID **survives** the sweep and is reported in `foreign_dirs` | D3, the inversion |
| 6 | A legacy `<ts>.incomplete` (no owner segment) survives and is reported | Forward compatibility; unknown ⇒ keep |
| 7 | A name with a malformed owner segment survives and is reported | Unparseable ⇒ keep, not sweep |
| 8 | `foreign_bytes` is non-zero and reaches `BackupResult.orphaned_bytes` | The leak is visible |
| 9 | The warning fires when `foreign_dirs` is non-empty and **not** when empty | Not silent, not noisy |
| 10 | Two `BackupService` instances in one process, same second, both complete: both get their own directory, one promotes, the loser reports `promote_error` and **both** directories survive the sweep | The finding-2 regression. Must fail if `_LIVE_RUNS` is keyed by path |
| 11 | A sibling's in-flight run id is live ⇒ its directory is skipped | The one case a PID cannot decide |
| 12 | `_run_end` runs on the raising path (`_write_snapshot` raises) | No immortal directory |
| 13 | `_WORKING_DIR_RE` parses what `_make_snapshot_dir` writes, for plain **and** collision-suffixed bases | Drift guard — the failure mode is silent (everything reads foreign, nothing is ever reclaimed) |
| 14 | `_SNAPSHOT_DIR_RE` excludes every working-directory name shape | Retention and hard-link sourcing cannot see one |
| 15 | No `owner.json` is written anywhere during a full snapshot | The marker is gone, not merely unread |
| 16 | Promotion onto an existing promoted directory fails and does not promote | The property replacing the reservation. **Assert the premise:** promotion onto an absent name succeeds in the same test |
| 17 | `mkdir` failure returns a `_fail` result and retires the run id | Error path |
| 18–22 | `backup-reclaim`: lists without `--force`; deletes with it; exit codes 0/1/2; the liveness hint is advisory-only; `--force` takes the pidfile guard | Section 4 |

**Mutation probe** (per `.github/copilot-instructions.md` — targeted, because
this is the third attempt at a Critical-risk state model). Baseline green first;
in-place with a `.mutbak` sibling; **single-line anchors only** (CRLF tree);
an anchor that does not match is INERT, not killed; a timeout is INVALID, not
survived. Mutate at least:

- `pid != os.getpid()` → `pid == os.getpid()`
- `if _run_is_live(run_id): continue` → deleted
- `if match is None:` → `if False:`
- `_run_begin` moved to *after* `mkdir`
- `_run_end` removed from the `finally`
- `foreign_dirs.append` → `pass` in the unparsed branch

Before calling any survivor a weak test, check the mutant actually reaches the
behaviour it claims to break.

---

## What this does NOT change

- `snapshot_manifest.py` apart from deleting `OWNER_NAME` — **the path-traversal
  containment (`is_contained_label`, `resolve_contained`) is untouched.**
- `snapshot_verify.py`, `backup_inventory.py`, coverage, retention, `prune()`,
  the scheduler loop, `config.py`, `runtime.py`, `startup/`, `verify-snapshot`.
- `_backup_one` and the BF-849 `contextlib.closing` fix. If BF-849 has already
  landed on `main`, rebase; do not re-apply it.
- `pidfile_guard.is_pid_alive` stays public. Its AD-1265 docstring says the
  backup sweep uses it to decide abandonment — **that is now false. Rewrite it**
  to say it backs the pidfile guard and, in backup, an operator-facing hint only.
- Do **not** add a lock file, a lease, a renewal protocol, or cross-host
  coordination. D5 declined all four.
- Do **not** fold orphaned bytes into `max_total_bytes` (D4).

---

## Tracking

- `PROGRESS.md` — AD-1296 entry; note it supersedes AD-1265's ownership model.
- `DECISIONS.md` — D1–D5, including the D3 behaviour inversion, and the
  measured `os.replace` result that retires the reservation.
- `docs/development/roadmap.md` — AD-1296 row.
- **Correct the AD-1265 spec's issue labels**: it says "BF-842 (#1313)". #1313 is
  **BF-843**; BF-842 is #1312 and is closed and unrelated. Fix in
  `prompts/ad-1265-a-snapshot-worth-having.md`, `PROGRESS.md` and the Bug Tracker.

---

## Acceptance criteria

1. `owner.json` is never written or read; `OWNER_NAME` does not exist in `src/`.
2. `is_pid_alive` appears in `backup.py` only inside the `backup-reclaim` hint.
3. `_OWNER_STALE_SECONDS`, `_STAGING_PREFIX`, `_STAGING_RE`, `_stage_owned_dir`,
   `_sweep_staging`, `_read_owner`, `_is_abandoned`, `_ACTIVE_CLAIMS`,
   `_claim_active`, `_release_active`, `_is_active` are all gone.
4. `backup.py` is **net smaller** than on `ad-1265-handback`. Report both counts.
5. All ~22 new tests pass; the mutation probe kills every listed mutant, or a
   survivor is explained with evidence that the mutant reaches the behaviour.
6. Focused gate green, then the canonical broad gate on the committed tree:
   `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad-1296`
7. Adversarial review with a different model than the author.
   **The AD-1265 stop rule carries over:** a second-round Required finding inside
   this AD's own machinery means stop and hand back — do not patch.
8. Verify all changes comply with the Engineering Principles in
   `.github/copilot-instructions.md`.

---

## Verified against codebase (2026-08-31)

Branch `ad-1265-handback` @ `46d8347e`, extracted with `git show`. The AD-1265
spec's anchors had drifted up to +124 lines; these are read from the branch file.

```
$ python scripts/ad_ceiling.py
  git log --all subjects           AD-1295   1370 AD refs
  GitHub issue titles (all states) AD-1291   1343 issues, 680 AD-titled
  prompts/ad-*.md filenames        AD-1295   50 files
  CEILING: AD-1295   NEXT: AD-1296

$ git show ad-1265-handback:src/probos/infrastructure/backup.py   # 907 lines
  L58   OWNER_NAME,                      (import)
  L68   from probos.pidfile_guard import is_pid_alive
  L80   #: Where a working directory is assembled ...  (staging block start)
  L83   _STAGING_PREFIX = ".staging-"
  L84   _STAGING_RE = re.compile(...)
  L94   _OWNER_STALE_SECONDS = 24 * 3600
  L96   _ACTIVE_LOCK = threading.Lock()
  L107  _ACTIVE_CLAIMS: dict[str, int] = {}
  L110  def _claim_active   L116 _release_active   L126 _is_active
  L132  class BackupResult      L154 retention_bound
  L162  class PruneResult       L171 bound: str = ""
  L245  self._make_snapshot_dir(started)      L249 _write_snapshot
  L260  self._sweep_incomplete(exclude=working_dir)
  L335  self._promote(...)      L400 _existing_snapshots   L404 _dir_size
  L473  def _make_snapshot_dir  L520 _stage_owned_dir      L534 _promote
  L558  def _sweep_incomplete   L610 _is_abandoned
  L658  def _sweep_staging      L683 _read_owner
  L687  (working_dir / OWNER_NAME).read_text(...)
$ git show ad-1265-handback:src/probos/infrastructure/snapshot_manifest.py
  L70   OWNER_NAME = "owner.json"
  L64   INCOMPLETE_SUFFIX = ".incomplete"
  L84   def is_contained_label      L106 def resolve_contained   (untouched)
```

**Round-2 finding, confirmed by reading, two links:** `_read_owner` (L683) catches
`(OSError, ValueError, TypeError, KeyError)` → `(None, 0.0)`; `_is_abandoned`
(L636) `if pid is None: return True`. A zero-byte file gives `json.loads("")` →
`ValueError` → swept.

**Naming scheme, run:** premise asserted (`_SNAPSHOT_DIR_RE` matches a promoted
name), then `20260831-120000.4242-a1b2c3d4.incomplete` and its collision-suffixed
form are both **excluded** by `_SNAPSHOT_DIR_RE` and both **parse** under
`_WORKING_DIR_RE`. The legacy `20260831-120000.incomplete` parses under neither —
so it is reported, not swept, which is the D3 default.

**Absence verified.**
`CLAIM:` BF-849 has no GitHub issue.
`RUN:` `gh issue list --state all --limit 1000 --jq 'select(.title|test("BF-849"))'`
`FOUND:` `0`. BF-84x runs 840–848 (#1306–#1318) and stops. `HOLDS: yes` — file it
before closing anything against it.
