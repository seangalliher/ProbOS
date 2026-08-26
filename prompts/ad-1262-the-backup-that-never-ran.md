# AD-1262 — the backup that never ran: scheduling, coverage, retention, restore

**Status:** ready to build
**Closes:** BF-842 (#1313), BF-838 (#1304)
**Dependencies:** AD-466 (`BackupService`, `InfrastructureConfig`), AD-816 (pidfile guard), AD-819 (`rebuild-episodic` CLI precedent), AD-823/824/825 (`_episodic_backup_loop` scheduling precedent)
**Estimated tests:** 55–62 new across 5 new files; 11 existing amended in `tests/test_ad466_infrastructure.py`

---

## Numbering

`python scripts/gen_ad_ledger.py --check` → `AD/BF ledger is current`.
**The ledger is nonetheless STALE** and must not be used to mint here.

| Authority | AD ceiling | BF ceiling |
|---|---|---|
| Ledger (`docs/development/open-ads-report.md`) | "next free **AD-1251**" — **STALE** | "next free **BF-837**" — **STALE** |
| GitHub, all states (authoritative) | **AD-1261** filed (#1311) | **BF-842** filed (#1313) |
| Untracked in-flight prompts | `prompts/ad-125{1..5}-*.md`, `ad-12{57..61}-*.md` | max `bf-833-*` |

The ledger's issue layer cannot see untracked prompts, and its snapshot predates
#1307–#1313. Taking `AD-1251` would collide five ways.

- **This work is AD-1262.** Next free AD after this one: **AD-1263**.
- **Next free BF: BF-843** — but see the collision below first.

### ⚠ BF-842 is allocated twice — Captain decision required

```
#1313  BF-842: BackupService is wired but never invoked …            2026-08-24T06:17:28Z
#1312  BF-842: BF-707 fixed the capability-gap regex and left 16 …   2026-08-24T06:02:49Z
```

Two open issues, both minted `BF-842`, fifteen minutes apart, unrelated subjects.
**This prompt uses #1313 as BF-842** (it is the backup defect). #1312 was filed
first and is the comment-rot defect. Recommended resolution: **renumber #1312 to
BF-843**, which makes next free **BF-844**. Do not resolve this inside the build —
it is a tracker edit, not code. Until it is resolved, do not mint a new BF.

### Why an AD and not just the two BFs

BF-842 as filed is "add a caller." Verification below shows that adding a caller
to the current `snapshot()` writes ~1.6 GB per tick into a directory that is
inside its own source enumeration, with no retention and no way to get the data
back out. BF-838 asks "which databases are covered," and the answer at HEAD is
**none of them, because nothing runs**. Closing either honestly requires a
discovery model, a criticality tiering decision, a retention policy, and a restore
path — none of which exist. That is design. Both BFs close as a consequence.

---

## Problem

### 1. `BackupService` has never run — on this vessel or any vessel

`snapshot()` writes `backup_root / "%Y%m%d-%H%M%S"` and copies
`sorted(self._data_dir.glob("*.db"))` through SQLite's online `.backup` API.
It is constructed at startup and **called by nothing**.

```
$ Get-ChildItem -Path src -Recurse -Filter *.py | Select-String 'backup_service'
src\probos\startup\finalize.py:3586: runtime.backup_service = BackupService(
src\probos\startup\finalize.py:3601: runtime.backup_service = None
src\probos\startup\finalize.py:3603: runtime.backup_service = None
```

Three writes, **zero reads**. The attribute is not declared on the runtime class
either — `Select-String 'backup_service' src\probos\runtime.py` returns nothing.

```
$ Get-ChildItem -Path src,tests,scripts -Recurse -Filter *.py | Select-String '\.snapshot\(\)'
… 78 hits, all NotificationQueue / WorkItemStore / telemetry / ConcurrencyManager …
tests\test_ad466_infrastructure.py:64,80,96,126,145,166   ← the only BackupService.snapshot() calls
```

The class docstring states the gap plainly (`infrastructure/backup.py:36`):

> Caller is responsible for scheduling. **v1 does not run a background task.**

On the live vessel (`%LOCALAPPDATA%\ProbOS\data`, data back to March 2026),
`data/backups/` contains exactly one entry — `episodic/`. **Zero timestamped
snapshot directories.** `events.db` (1216 rows, 2026-08-23T06:25 → 2026-08-24T06:05)
has 0 rows matching `%backup%` in `event`, `category` or `detail`; controls
`agent_wired`=723 and `pool_created`=455 confirm the query works.
`BACKUP_COMPLETE` / `BACKUP_FAILED` (`events.py:321-322`) have never been emitted.

**Why the tests did not catch it.** All six `svc.snapshot()` calls in
`tests/test_ad466_infrastructure.py` supply the caller that production lacks. This
is the half-chain shape from `.github/copilot-instructions.md` — except there is no
consumer at all, only a test standing in for one.

### 2. A different, working backup system exists — do not conflate them

| | episodic (works) | `BackupService` (inert) |
|---|---|---|
| scheduler | `_episodic_backup_loop`, `runtime.py:3567` | **none** |
| spawned at | `runtime.py:3261`, `drain_on_shutdown=True` | — |
| config gate | `config.memory.backup_enabled` (`config.py:1095`) | `config.infrastructure.backup_enabled` (`config.py:3966`) |
| retention | `backup_retain_days` (`config.py:1096`), enforced at `episodic_backup.py:195` | **none** |
| covers | ChromaDB episodic footprint | `*.db` in data dir |
| output | `backups/episodic/`, 521 MB | **nothing, ever** |

`backups/episodic/` is why this looked alive. Use `_episodic_backup_loop` as the
scheduling **style** precedent; it is not the thing being fixed and must not change.

### 3. BF-838's coverage arithmetic is wrong, but its underlying gap is real

BF-838 lists 22 databases "not named anywhere near backup code." Naming is not
coverage — the glob is a pattern and matches files whose names appear nowhere.
Resolving all 22 against the live vessel:

```
TOP-LEVEL (14) — already inside glob(*.db) once something calls it
  action_approvals 20,480    activation_tracker 1,034,321,920   capability_requests 28,672
  clearance_grants 20,480    clinical_notes 16,384              cognitive_skills 12,288
  counselor 45,056           episode_fts 29,630,464             fault_reports 24,576
  intent_grants 24,576       participant_index 6,426,624        qualification_results 5,750,784
  skill_grants 24,576        tool_permissions 24,576

NESTED (1)   procedures.db → procedures\procedures.db      (declared runtime.py:2669)
ABSENT (7)   archive.db  assistant_audit.db  holodeck_scenarios.db  retrieval_practice.db
             schema_versions.db  skill_requests.db  team_simulations.db
```

**`schema_versions.db` — BF-838's headline risk — does not exist on this vessel.**
It is declared top-level at `startup/cognitive_services.py:389`
(`data_dir / "schema_versions.db"`), so it is glob-covered *when present*. The
migration-state risk is real in shape; the file is simply not there yet. Record
this, do not repeat the claim as-is.

**The four grant stores — confirmed, not inferred** (BF-838 acceptance #2 asked
for exactly this):

```
clearance_grants.db      clearance_grants=0
intent_grants.db         intent_access_grants=0
skill_grants.db          skill_access_grants=0
tool_permissions.db      tool_access_grants=1
action_approvals.db      action_approvals=0
```

They **are** authorization state — the schemas are real and correctly named. They
currently hold **one row in total**. So the restore-with-stale-authorization
hazard is genuine but presently near-empty, and all five are top-level, meaning
their fix is *the scheduler*, not coverage. Record the counts and the date; do not
promote "four grant stores are unprotected" into a coverage claim it cannot carry.

**What is genuinely outside the glob:**

| Path | Size | Disposition |
|---|---|---|
| `procedures/procedures.db` | 15.7 MB | real data, must be covered |
| `archive.db` (**outside `data_dir`**) | 20 KB | `cognitive_services.py:661/674` → `~/AppData/Local/ProbOS/archive/` |
| `archives/ward_room_*.db` × 23 | 91.4 MB | rotated history, immutable |
| `nats-jetstream/**/msgs/index.db` × 4 | 3.3 KB | broker internals, reconstructible |

### 4. Three hazards any naive fix walks into

1. **`backup_root` is inside `data_dir`** — `finalize.py:3583` builds it as
   `runtime.data_dir / config.infrastructure.backup_subdir` (`"backups"`,
   `config.py:3967`). A recursive glob snapshots previous snapshots; each one
   embeds its predecessors.
2. **~1.6 GB per full snapshot** — `activation_tracker.db` 1,034,321,920 B;
   `semantic_work.db` 164,708,352; `cognitive_journal.db` 152,322,048;
   `eviction_audit.db` 140,107,776. Top-level total 1530.7 MB across 43 files.
   Cadence × retention is a **capacity decision**, not a default.
3. **No restore path exists.** Enumerated:
   ```
   $ Get-ChildItem -Path src -Recurse -Filter *.py | Select-String 'def restore|restore_from|restore_snapshot'
   proactive.py:804 restore_cooldowns · warm_boot.py:75 restore · checkpoint.py:133 restore_dag
   procedure_store.py:1565 restore_procedure · session_manager.py:73,136 · workflow_cache.py:225
   routers/procedures.py:272 · security/pairing/service.py:238
   ```
   Nine hits, all unrelated domain restores. Nothing reads a `BackupService`
   snapshot. "We have backups" stays unproven until a round trip exists.

---

## Solution

Six sections. **§1–§4 close BF-842; §5–§6 close BF-838.** They are ordered so that
§1–§4 are independently shippable if the build must be split — BF-842 explicitly
says it should land first, and coverage work on a service nobody calls changes
0-of-49 into 0-of-49.

### Design decisions and why

**(a) Discovery is recursive under declared roots, with a hard exclusion.**
Neither pure model works. Pure recursion re-enters `backups/` (hazard 1) and
sweeps broker internals. A pure hand-maintained inventory is exactly what rots —
that rot *is* BF-838. So: mechanical recursive discovery (cannot go stale) under
an explicit, short list of roots, minus an explicit exclusion list (each entry
carrying a written reason), with a **drift test** (§6) binding the two. Pruning
`backup_root` is **unconditional and not configurable** — a config typo must not
be able to re-arm recursive self-inclusion. That is a correctness invariant, not a
preference.

**(b) `archive.db` is added as an extra root; it does NOT move.**
`config.archive.db_path` is operator-overridable (`cognitive_services.py:658`) and
the default is platform-branched (win32 / darwin / XDG, :660–672). Moving it is a
data migration with rollback and resume obligations on a path an operator may have
overridden, and it would break existing vessels. Adding a root is additive,
reversible and costs 20 KB. **Read the effective configured path, never recompute
the platform default** — otherwise an operator override silently goes unbacked.
Consequence: snapshots become **root-namespaced** (`<ts>/data/…`, `<ts>/archive/…`)
so two roots cannot collide on a filename. This changes the v1 flat layout and is
the reason the 11 existing AD-466 tests need amending.

**(c) Three criticality tiers, because 1.6 GB × N is the real blocker.**

| Tier | Members | Cadence | Mechanism |
|---|---|---|---|
| `critical` | every discovered `*.db` not otherwise classified — incl. all five grant/approval stores, `schema_versions.db` when present, `procedures/procedures.db`, `archive.db` | **every** snapshot | SQLite online `.backup` |
| `bulk` | large, high-churn, derived-or-regenerable (see below) | every `bulk_every_n`-th snapshot (default 4) | SQLite online `.backup` |
| `immutable` | `archives/ward_room_*.db` | every snapshot, but ~free | hard-link from prior snapshot when unchanged, else copy |

`critical` is the **default** — a file is bulk only by explicit declaration. A new
store therefore lands in the tier that is always protected.

*Verified bulk member:* `activation_tracker.db` — its sole table is
`episode_access_log` (`activation_tracker.py:292,304`); it is a derived ACT-R
access log with its own 180-day retention (`cleanup_old_accesses`, docstring line
36), and the episodes it scores live in ChromaDB, which AD-823 already snapshots.
Losing it degrades activation ranking; it destroys nothing.

*Candidates the builder must confirm before assigning:* `semantic_work.db`,
`cognitive_journal.db`, `eviction_audit.db`, `episode_fts.db`. **Do not assign any
of these to `bulk` on size alone.** For each, open it on the live vessel, read the
table names, find the writer in `src/`, and record a one-line reason in the tier
table. If reconstructibility cannot be established, it stays `critical`. An
unjustified demotion is a silent data-loss decision.

*Immutable is safe here and measurably so:* the newest ward-room archive is
`ward_room_2026-04-16_010400.db`, four months old. Hard-link only when
`(size, mtime_ns)` match the prior snapshot's copy **and** `mtime` predates that
snapshot's start time — so a same-size in-place rewrite cannot silently alias.
Hard-link failure (cross-device, unsupported FS) falls back to copy, never to
skip. A pleasant side effect: link count > 1 means pruning an old snapshot does
not destroy the bytes.

**(d) Retention is two bounds, and it can never delete your only backup.**
`backup_retain_days` (default 7, mirroring `memory.backup_retain_days`) **and**
`backup_max_total_bytes` (default 8 GiB), enforced oldest-first after each
*successful* snapshot; the tighter bound wins. Days alone does not bound bytes,
which is the whole of hazard 2. **The most recent successful snapshot is never
pruned, even if it alone exceeds the ceiling** — a retention policy that can prune
itself to zero is worse than no policy, because it looks like protection.

**(e) Cadence: every 6 h, first fire 120 s after boot.**
Episodic runs 24 h / 60 s. These stores are transactional and authorization state
where a day of loss is worse than episodic memory, which is itself reconstructible
from the ward room (AD-819). 6 h is affordable *only because of (c)*: the
per-tick cost is `critical` (~50 MB) plus hard links, with `bulk` amortized to
once per 24 h. The 120 s warmup (vs episodic's 60 s) staggers the two loops so
they do not contend for disk at boot. Both values are config fields, not literals.

---

## Implementation

### Section 0 — config fields

`src/probos/config.py`, `InfrastructureConfig` (:3962–3967). Every field needs a
default so the vessel boots with zero config, and validators at parse time.

```
===SEARCH===
class InfrastructureConfig(BaseModel):
    """Engineering infrastructure configuration (AD-466)."""

    enabled: bool = True
    backup_enabled: bool = True
    backup_subdir: str = "backups"
===REPLACE===
class InfrastructureConfig(BaseModel):
    """Engineering infrastructure configuration (AD-466 / AD-1262)."""

    enabled: bool = True
    backup_enabled: bool = True
    backup_subdir: str = "backups"

    # AD-1262: AD-466 shipped the service with no scheduler; these drive it.
    backup_interval_seconds: float = Field(default=21600.0, ge=300.0)
    backup_warmup_seconds: float = Field(default=120.0, ge=0.0)
    backup_retain_days: int = Field(default=7, ge=1, le=365)
    backup_max_total_bytes: int = Field(default=8 * 1024**3, ge=64 * 1024**2)
    backup_bulk_every_n: int = Field(default=4, ge=1, le=100)
    backup_include_archive_root: bool = True
===END REPLACE===
```

Mirror these into `config/system.yaml` under `infrastructure:` with the same
values and a comment naming AD-1262. Do not change `memory.backup_*`.

### Section 1 — inventory and discovery (new module)

**New file:** `src/probos/infrastructure/backup_inventory.py`

- `class BackupTier(StrEnum)`: `CRITICAL`, `BULK`, `IMMUTABLE`.
- `@dataclass(frozen=True) class BackupRoot`: `name: str`, `path: Path`.
  `name` becomes the snapshot subdirectory. Validate it is a single path
  segment matching `^[a-z0-9_-]{1,32}$` — it is used as a directory name.
- `EXCLUDED_DATABASES: Mapping[str, str]` — glob pattern → **reason**. Reason must
  be non-empty; §6 asserts it. Defaults:
  - `"nats-jetstream/**"` → `"broker internals; rebuilt from stream config on reconnect"`
  - `"**/backups/**"` → `"backup root; excluded unconditionally, see prune_backup_root"`
- `BULK_DATABASES: Mapping[str, str]` — filename → reason. Ships with exactly one
  verified entry (`activation_tracker.db`). The four candidates from (c) are added
  by the builder **only** with a confirmed reason.
- `def discover(roots, *, backup_root, exclude=EXCLUDED_DATABASES) -> list[DiscoveredDatabase]`
  - `rglob("*.db")` per root; **skip any path under `backup_root`
    unconditionally**, resolved and compared via `Path.is_relative_to` on resolved
    paths so a symlink or `..` cannot slip past;
  - apply `exclude` globs against the path relative to its root;
  - classify: `archives/ward_room_*.db` → `IMMUTABLE`; name in `BULK_DATABASES` →
    `BULK`; otherwise `CRITICAL`;
  - deterministic ordering (sort by `(root.name, relative_path)`) so two runs
    produce identical manifests;
  - a root that does not exist yields zero entries and logs at `info` — a fresh
    vessel is not an error.

### Section 2 — `BackupService` gains tiering, roots and retention

`src/probos/infrastructure/backup.py`. Keep the class focused (SRP): discovery
lives in §1, restore in §5. Additive constructor params, all keyword-only with
defaults, so the AD-466 signature still constructs.

- `__init__(..., roots: Sequence[BackupRoot] | None = None, bulk_every_n: int = 4, retain_days: int = 7, max_total_bytes: int = 8 * 1024**3)`.
  When `roots is None`, synthesize `[BackupRoot("data", data_dir)]` — preserves
  AD-466 construction.
- `snapshot(*, include_bulk: bool | None = None) -> BackupResult`
  - writes `<ts>/<root.name>/<relative_path>`, creating parent dirs;
  - `include_bulk=None` means "decide from the internal tick counter"; an explicit
    bool overrides (the restore round-trip test needs a forced full snapshot);
  - `IMMUTABLE`: `os.link` when `(size, mtime_ns)` match the prior snapshot's copy
    **and** `mtime_ns < prior_snapshot_started_ns`; on `OSError` fall back to
    `_backup_one`. Never skip.
  - a per-file failure logs at `warning` with the path and continues (log-and-
    degrade — one unreadable file must not void the whole snapshot); the result
    gains `files_failed: list[str]` and `succeeded` becomes
    `not files_failed or bool(files_copied)`. Record the choice in the docstring.
  - `BackupResult` gains `files_linked: list[str]`, `files_failed: list[str]`,
    `included_bulk: bool`. Existing fields keep their names and meanings.
- `prune(self) -> PruneResult` — enforce `retain_days` then `max_total_bytes`,
  oldest-first, **never the newest successful snapshot**. Called by `snapshot()`
  only after a snapshot with `succeeded=True`. Model the age math on
  `episodic_backup.py:203-231`.
- Extend the `BACKUP_COMPLETE` payload additively with `files_linked`,
  `files_failed`, `included_bulk`, `pruned_dirs`. Do not rename existing keys.

### Section 3 — the scheduler, and the seam it has to cross

**`src/probos/runtime.py`**

1. Declare the attribute next to `_episodic_backup_task` (:521) — it is currently
   a dynamic attribute set only by `finalize.py`:
   ```
   self.backup_service: "BackupService | None" = None
   self._sqlite_backup_task: asyncio.Task[None] | None = None
   ```
   (import under `TYPE_CHECKING` to avoid a cycle).
2. Add `async def _sqlite_backup_loop(self) -> None` modelled **exactly** on
   `_episodic_backup_loop` (:3567–3638):
   - return immediately if `not self.config.infrastructure.backup_enabled` or
     `self.backup_service is None`, logging why;
   - `asyncio.wait_for(self._shutdown_event.wait(), timeout=backup_warmup_seconds)`
     warmup, returning if it fires;
   - loop: shutdown pre-check → `await asyncio.to_thread(self.backup_service.snapshot)`
     — **`snapshot()` is synchronous and does blocking file I/O; calling it
     directly on the event loop would stall the runtime for the duration of a
     multi-GB copy**. This is the one deliberate divergence from the episodic
     precedent (which tars in-line) and must be stated in the docstring;
   - per-tick `try/except Exception` → `logger.warning(..., exc_info=True)` so a
     transient disk-full does not kill the task forever;
   - `finally:` shutdown re-check;
   - drain-aware idle via `asyncio.wait_for(self._shutdown_event.wait(), timeout=interval)`;
   - `except asyncio.CancelledError: logger.debug(...); raise`.
3. Spawn it immediately after the episodic spawn (:3261–3265):
   ```
   self._sqlite_backup_task = self._spawn_background(
       self._sqlite_backup_loop(),
       name="sqlite-backup-loop",
       drain_on_shutdown=True,
   )
   ```
   `drain_on_shutdown=True` is required: a snapshot cancelled mid-copy leaves a
   torn `.db` in the snapshot directory, and a torn backup is worse than none
   because it reads as protection.

**`src/probos/startup/finalize.py`** (:3582–3603) — pass the new params. Build
`roots` as `[BackupRoot("data", runtime.data_dir)]`, appending
`BackupRoot("archive", <effective archive dir>)` when
`config.infrastructure.backup_include_archive_root` and `config.archive.enabled`.
Derive the archive directory from the **effective configured path** — reuse the
same resolution as `cognitive_services.py:658-674`; extract it into a shared
helper rather than duplicating the platform branch (DRY). If resolution fails,
log at `warning` and continue with the data root only.

### Section 4 — retention, self-exclusion and the seam tests

**New file:** `tests/test_ad1262_backup_scheduler.py`

Seam tests (BF-842 acceptance 2 — these are the point of the section):

1. **A snapshot appears from runtime startup.** Boot the real startup path with
   `infrastructure.backup_enabled=True` and `backup_warmup_seconds≈0.05`,
   `backup_interval_seconds` small, against a `tmp_path` data dir. Wait on a
   condition (poll with a timeout, do not `sleep` a fixed span). Assert a
   timestamped directory exists. **The test must never call `snapshot()` and must
   not reference `BackupService` to trigger anything** — if it does, it has
   reproduced the bug it exists to prevent.
2. **`BACKUP_COMPLETE` reaches the event log.** Assert the row is queryable from
   the same surface the diagnosis used (`events.db` / `EventLog`), not that
   `emit_event` was called. The live evidence in #1313 was event-log rows; the
   test should be able to fail the way the vessel failed.
3. **Shutdown drains rather than tearing.** Trigger shutdown during a tick and
   assert the loop exits without leaving a partial snapshot directory.

Self-exclusion (BF-842 acceptance 4):

4. Snapshot twice; assert the second contains **no** entry from the first —
   recursively, and by path, not by count.
5. Assert `backup_root` exclusion holds even when `backup_subdir` is set to a
   nested value and when a symlink points into the backup root.

Retention (BF-842 acceptance 3):

6. `retain_days` prunes by age; 7. `max_total_bytes` prunes oldest-first;
8. the newest successful snapshot is never pruned even when alone over the ceiling;
9. pruning runs only after a successful snapshot.

Tiering: 10. `bulk_every_n=4` → bulk present on ticks 1 and 5, absent on 2–4
(first tick includes bulk so a fresh vessel is fully covered immediately);
11. an immutable file identical to the prior snapshot is hard-linked
(`st_nlink > 1`); 12. one whose `mtime` is newer than the prior snapshot start is
**copied, not linked**; 13. `os.link` raising `OSError` falls back to copy;
14. a per-file failure is recorded in `files_failed` and does not void the snapshot.

### Section 5 — restore (new module + CLI)

**New file:** `src/probos/infrastructure/restore.py`

`restore_snapshot(snapshot_dir, roots, *, dry_run=False) -> RestoreResult`

- **Refuse under a live runtime.** Use AD-816 `assert_no_other_instance(data_dir)`
  exactly as `__main__.py:1352-1363` does. Restoring beneath a running vessel
  corrupts both copies.
- **Verify before touching anything.** `PRAGMA integrity_check` every file in the
  snapshot; if **any** fails, abort the whole restore and write nothing. Never
  half-restore — a vessel with half-old and half-new databases is worse than an
  unrestored one, and is the failure mode most likely to be mistaken for success.
- **Move aside, never delete.** Existing targets go to
  `<root>/_pre_restore_<ts>/` preserving relative paths. Restore is then
  copy-to-temp-name → `os.replace` into place.
- **Roll back on any failure**, restoring from the move-aside, and report which
  phase failed. Cancellation is not applicable (sync CLI path), but a
  `KeyboardInterrupt` mid-restore must still leave the move-aside intact — do the
  rollback in a `finally`.
- Unknown root names in the snapshot are reported and skipped, not guessed.

**`src/probos/__main__.py`** — add `probos restore-snapshot`, modelled on
`rebuild-episodic`:
- handler `_cmd_restore_snapshot` beside `_cmd_rebuild_episodic` (:1331);
- subparser beside the AD-819 block (:2387-2400) with `--snapshot` (required),
  `--data-dir`, `--config`, `--dry-run`;
- dispatch beside :2484-2486;
- `--dry-run` prints the plan — files, sizes, integrity results, what moves aside —
  and writes nothing.

**New file:** `tests/test_ad1262_restore.py`

15. **The round trip** (BF-842 acceptance 5, BF-838 acceptance 4): create a db
    with a known row → force a full snapshot (`include_bulk=True`) → corrupt/
    truncate the live db → restore → assert the row is back, `integrity_check`
    returns `ok`, **and** the file opens through the normal
    `default_factory` connection path a runtime would use. Reading the bytes back
    is not proof the vessel is usable.
16. Restore refuses when the pidfile shows a live runtime.
17. A snapshot with one corrupt file aborts and writes nothing (assert the live
    db is byte-identical afterwards).
18. Move-aside contents are present and complete after a successful restore.
19. A mid-restore failure rolls back to the pre-restore state.
20. `--dry-run` writes nothing (assert mtimes unchanged).
21. Round trip across **both** roots, including `archive`.
22. An unknown root directory in the snapshot is reported and skipped.

### Section 6 — the drift test (BF-838 acceptance 1 and 3)

**New file:** `tests/test_ad1262_backup_coverage.py`

- Scan `src/` for quoted `*.db` literals; resolve each to its declared root and
  relative path. Assert every one is either (a) reachable by `discover()` under a
  declared root, or (b) matched by `EXCLUDED_DATABASES` **with a non-empty
  reason**. Failure message must name the offending file and the fix
  ("add to a covered root, or add to EXCLUDED_DATABASES with a reason").
- Assert `BULK_DATABASES` values are non-empty reasons.
- Assert `CRITICAL` is the default: a synthetic unknown `*.db` under a root
  classifies as `CRITICAL`, not `BULK`.
- Record the confirmed grant-store row counts and the measurement date in a module
  docstring — BF-838 acceptance 2 asked for a recorded decision, and a stale
  measurement presented as current is worse than none.

> **Caveat, stated because this repo has been bitten by it four times.** This is a
> **source-scan** test. A source scan cannot distinguish "this is required" from
> "this is what shipped." It is acceptable *here* only because it asserts against
> `EXCLUDED_DATABASES` — a deliberate, human-authored table — rather than against
> observed behaviour. If a future change touches this test, update the assertion
> and record why inline. **Never delete it to make a build green.**

---

## What this does NOT change

- `_episodic_backup_loop`, `snapshot_episodic`, `maintenance/episodic_backup.py`,
  `memory.backup_*`, `backups/episodic/`. Different system, works, out of scope.
- **AD-1256 (#1302) is not built here.** No store registry, no shared storage
  layer, no consolidation of the 34 bespoke connects. #1302 itself names complete
  backup/restore coverage as the step that must come *first*. `BULK_DATABASES` /
  `EXCLUDED_DATABASES` are deliberately plain module-level tables so AD-1256 can
  absorb them into a real registry later.
- `archive.db` does **not** move. No data migration.
- No new `EventType` values — `BACKUP_COMPLETE` / `BACKUP_FAILED` already exist
  (`events.py:321-322`) and are extended additively.
- No API route, no HXI surface, no WebSocket frame. Restore is CLI-only and must
  stay that way: a one-click "restore" in the UI is a destructive action with no
  consensus gate, and designing that gate is a separate AD.
- No compression, no encryption, no off-host replication.
- No change to `SQLiteStorageBackend` or `storage/sqlite_factory.py`.
- No renumbering of #1312/#1313. Tracker edit, Captain's call.

## Do not build

- A background *restore*, an auto-restore-on-corruption path, or any code that
  invokes restore without an operator. Automatic restore is a destructive action.
- A `BackupService` method that deletes anything outside `backup_root`.
- Retention that can prune the only remaining snapshot.
- A recursive glob without the unconditional `backup_root` prune, even temporarily.
- Assigning `semantic_work.db`, `cognitive_journal.db`, `eviction_audit.db` or
  `episode_fts.db` to `BULK` on size alone — see §Solution (c).
- Widening `snapshot()` to run on the event loop instead of `to_thread`.

---

## Tracking

- `PROGRESS.md` — AD-1262 entry; BF-842 (#1313) and BF-838 (#1304) CLOSED with the
  corrected coverage arithmetic (14 of 22 already top-level; `schema_versions.db`
  absent; grant stores hold 1 row total).
- `docs/development/roadmap.md` Bug Tracker — rows for BF-842 and BF-838.
- `DECISIONS.md` — AD-1262: tiering, retention floor, archive-as-root (not moved),
  and the recorded per-file bulk justifications.
- `python scripts/gen_ad_ledger.py` after the issues close.

## Acceptance criteria

1. `BackupService.snapshot()` is invoked on a schedule in production, gated by
   `config.infrastructure.backup_enabled`, off the event loop.
2. A test asserts a snapshot appears **from runtime startup**, never calling
   `snapshot()` itself; a second asserts `BACKUP_COMPLETE` is queryable from the
   event log.
3. Retention bounds both age and total bytes, never prunes the sole snapshot, and
   the per-snapshot footprint is an explicit recorded decision (the tier table).
4. Snapshot-twice proves the second excludes the first, including under a nested
   `backup_subdir` and through a symlink.
5. A restore round trip proves the restored database is usable through the normal
   connection path, across both roots.
6. Every `*.db` declared in `src/` is discovered or excluded-with-a-reason, and a
   test fails when a new one is neither.
7. The four grant/permission stores' contents are confirmed and the measurement
   recorded with its date.
8. Full gate green: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`.
   Focused: `pytest tests/test_ad1262_*.py tests/test_ad466_infrastructure.py -v -n 0`.
9. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
10. Run the `Diff Reviewer` subagent on the staged diff before committing, with a
    different model than the one that wrote the code, and address Required
    findings before the commit.

---

## Verified Against Codebase (2026-08-24)

```
git rev-parse --short HEAD
  83a7c798   BF-836: a verification defect no longer reads as a rejection

Select-String -Path src\probos\infrastructure\backup.py -Pattern 'glob|backup_root|does not run'
  36:  Caller is responsible for scheduling. v1 does not run a background task.
  54:  snapshot_dir = self._backup_root / timestamp
  67:  db_files = sorted(self._data_dir.glob("*.db"))

Select-String -Path src\probos\startup\finalize.py -Pattern 'BackupService|backup_service'
  3576: if config.infrastructure.enabled:
  3582:     if config.infrastructure.backup_enabled:
  3583:         backup_root = runtime.data_dir / config.infrastructure.backup_subdir
  3586:         runtime.backup_service = BackupService(
  3601/3603: runtime.backup_service = None

Select-String -Path src\probos\config.py -Pattern 'backup_enabled|backup_subdir|backup_retain_days'
  1095: backup_enabled: bool = True                       (MemoryConfig)
  1096: backup_retain_days: int = Field(default=7, ge=1, le=365)
  3966: backup_enabled: bool = True                       (InfrastructureConfig)
  3967: backup_subdir: str = "backups"

Select-String -Path src\probos\runtime.py -Pattern '_episodic_backup_loop|_shutdown_event|def _spawn_background|ProcedureStore|def data_dir'
  516:  self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
  521:  self._episodic_backup_task: asyncio.Task[None] | None = None
  1332: self._shutdown_event: asyncio.Event = asyncio.Event()
  1956: def data_dir(self) -> Path:
  2668: procedure_store = ProcedureStore(
  2669:     data_dir=self._data_dir / "procedures",
  3261: self._episodic_backup_task = self._spawn_background(
  3456: def _spawn_background(self, coro, name, *, drain_on_shutdown: bool = False) -> asyncio.Task
  3567: async def _episodic_backup_loop(self) -> None
  3593/3630: await asyncio.wait_for(self._shutdown_event.wait(), timeout=60.0 / 86400.0)

Select-String -Path src\probos\startup\cognitive_services.py -Pattern 'archive_base|archive_db_path|schema_versions.db'
  389:  schema_store = SchemaVersionStore(db_path=str(data_dir / "schema_versions.db"))
  658:  archive_db_path = config.archive.db_path
  661:  archive_base = Path.home() / "AppData" / "Local" / "ProbOS" / "archive"
  674:  archive_db_path = str(archive_base / "archive.db")

Select-String -Path src\probos\events.py -Pattern 'BACKUP'
  321: BACKUP_COMPLETE = "backup_complete"  # AD-466
  322: BACKUP_FAILED = "backup_failed"  # AD-466

Select-String -Path src\probos\maintenance\episodic_backup.py -Pattern 'prune|retain_days'
  195: _prune_old_snapshots(backups_dir, retain_days=retain_days, today=today)
  203-231: _prune_old_snapshots — age math + unlink, the retention precedent

Select-String -Path src\probos\__main__.py -Pattern 'rebuild-episodic|assert_no_other_instance'
  1331: def _cmd_rebuild_episodic(args) -> int
  1352-1363: AD-816 read-only check → assert_no_other_instance(data_dir), return 2
  2388: rebuild_parser = subparsers.add_parser("rebuild-episodic", …)
  2484-2486: dispatch

(Select-String tests\test_ad466_infrastructure.py -Pattern '^\s*def test_').Count → 11
```

### Absence Verified (2026-08-24)

```
CLAIM: nothing in src/ reads runtime.backup_service
RUN:   Get-ChildItem -Path src -Recurse -Filter *.py | Select-String 'backup_service'
FOUND: finalize.py:3586 (write), :3601 (write None), :3603 (write None)
HOLDS: yes — three writes, zero reads. Also undeclared on the runtime class:
       Select-String src\probos\runtime.py -Pattern 'backup_service' → no matches

CLAIM: BackupService.snapshot() has no production caller
RUN:   Get-ChildItem -Path src,tests,scripts -Recurse -Filter *.py | Select-String '\.snapshot\(\)'
FOUND: 78 hits; the only BackupService ones are tests/test_ad466_infrastructure.py
       :64 :80 :96 :126 :145 :166. All others are NotificationQueue,
       PersistentTaskStore, WorkItemStore, telemetry, ConcurrencyManager, protocol.
HOLDS: yes

CLAIM: no restore path exists for BackupService snapshots
RUN:   Get-ChildItem -Path src -Recurse -Filter *.py |
       Select-String 'def restore|restore_from|_restore_backup|restore_snapshot'
FOUND: proactive.py:804, warm_boot.py:75, checkpoint.py:133, procedure_store.py:1565,
       session_manager.py:73/136, workflow_cache.py:225, routers/procedures.py:272,
       security/pairing/service.py:238
HOLDS: yes — nine hits, none reads a snapshot directory
```

### Live vessel (2026-08-24, `%LOCALAPPDATA%\ProbOS\data`)

```
top-level *.db          : 43 files, 1530.7 MB
largest                 : activation_tracker 1,034,321,920 · semantic_work 164,708,352
                          cognitive_journal 152,322,048 · eviction_audit 140,107,776
                          ward_room 36,495,360 · episode_fts 29,630,464
nested *.db             : archives\ward_room_*.db × 23 (91.4 MB, newest 2026-04-16)
                          procedures\procedures.db (15,732,736 B)
                          nats-jetstream\jetstream\$G\streams\{COGNITIVE_CHAIN,
                            INTENT_DISPATCH,SYSTEM_EVENTS,WARDROOM}\msgs\index.db (3.3 KB total)
outside data_dir        : %LOCALAPPDATA%\ProbOS\archive\archive.db  20,480 B
data\backups\           : episodic\  ← only entry; ZERO timestamped snapshot dirs
grant stores            : clearance_grants=0 · intent_access_grants=0 · skill_access_grants=0
                          tool_access_grants=1 · action_approvals=0
schema_versions.db      : ABSENT (declared cognitive_services.py:389, not yet created)
activation_tracker      : sole table episode_access_log; 180-day self-retention
                          (activation_tracker.py:36, :286-296)
```
