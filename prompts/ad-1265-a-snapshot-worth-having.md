# AD-1265 — a snapshot worth having: schedule it, complete it, attest it

**Status:** ready to build
**Closes:** BF-842 (#1313), BF-838 (#1304), BF-849 (new — see §1)
**Supersedes:** `prompts/ad-1262-the-backup-that-never-ran.md` (built, reviewed twice, reverted)
**Dependencies:** AD-466 (`BackupService`, `InfrastructureConfig`), AD-823/824/825 (`_episodic_backup_loop` scheduling precedent), AD-816 (pidfile guard, used by §7)
**Followed by:** AD-1266 (restore) — **not built here**
**Estimated tests:** 40–46 new across 4 new files; 11 existing amended in `tests/test_ad466_infrastructure.py`

---

## Numbering

Verified at HEAD `e97b9125` (2026-08-24):

```
Get-ChildItem prompts -Filter 'ad-*.md' | … max → 1264
git log --oneline -1 → e97b9125 BF-848: prove the crew-executor cap by rendezvous
```

Current highest: **AD-1264, BF-848.** This work is **AD-1265**; restore is
**AD-1266**; the handle leak in §1 is **BF-849**. Next free after this pair:
**AD-1267, BF-850.**

The `#1312`/`#1313` double-minting of BF-842 recorded in the superseded prompt is
**unresolved and still not this build's problem.** Use #1313 as BF-842. Do not
renumber anything in code.

---

## Why this prompt exists

AD-1262 built scheduling *and* restore in one AD. Round-1 review found four
blockers; all were fixed and verified. Round-2 review then found six more, and
they were not independent — three of them were the same unanswered question
wearing different clothes: **what is a snapshot, exactly?**

The tell was location, not severity. Every round-2 finding sat inside machinery
that existed *only to serve restore*: carry-forward existed because restore needed
the bulk tier from somewhere; the opaque/digest split existed because carry-forward
made hashing expensive; the `.incomplete` acceptance existed because restore's
admission test was "has a complete manifest" rather than "was promoted." Restore
had been allowed to define the snapshot unit by accident.

**So the unit gets defined first, on its own, with its guarantee stated and
tested. Restore lands next, as a consumer of a settled contract.** That is the
whole reason for the split, and it is the reason §7 exists (see below).

### The cost of splitting, and the thing that pays it

Between this AD and AD-1266 the vessel has backups it has never proved it can
read. That is *precisely* the "looks like protection" failure this line of work
exists to close, so the split is only defensible if something closes it.

**§7 is that something.** `probos verify-snapshot` opens every file in a promoted
snapshot through the normal connection path and checks it against the manifest.
It writes nothing, so it is not restore — but it converts "we have files" into
"we have files that open and match what was recorded." **§7 is not optional and
must not be deferred to AD-1266.** Without it this AD ships the exact defect it
claims to fix.

---

## Decisions

### D1 — a snapshot is a self-sufficient point-in-time image. There is no "sometimes" tier.

AD-1262 shipped three tiers: `critical` (every tick), `bulk` (every 4th tick,
carried forward by reference), `immutable` (hard-linked). Review measured the
consequence: tick N names tick N−1 as its `bulk_source`, retention deletes N−1,
and restore then reports success with the database simply absent.

The dependency is not a bug in retention. **A directory that is only restorable
in combination with another directory is not a snapshot.** It breaks every
operator instinct — copy this folder to safety, ship it to another host, keep the
one from before the bad migration — and it breaks them silently.

**`bulk` is deleted as a concept.** A database is one of two things:

| | meaning | mechanism |
|---|---|---|
| **included** (default) | restoring it is necessary for the vessel to be correct | online `.backup`, present in **every** snapshot |
| **excluded** | the vessel reconstructs it; restore explicitly does not provide it | never copied; requires a written reason |

`immutable` survives as an **optimization inside `included`**, not as a third
state. Hard-linking and carry-forward look alike and are opposites:

> **A hard link is data-present. A `bulk_source` reference is data-absent.**
> Pruning the snapshot a hard link was sourced from does not destroy the bytes
> (link count > 1). Pruning the snapshot a reference names destroys the data.

Say that in the module docstring. It is the distinction the reverted attempt
missed.

**`activation_tracker.db` moves from `BULK` to `EXCLUDED_DATABASES`**, keeping the
reason AD-1262 already verified: sole table `episode_access_log`
(`activation_tracker.py:292,304`), derived ACT-R access log with its own 180-day
retention (`activation_tracker.py:36`), and the episodes it scores live in
ChromaDB, which AD-823 snapshots separately. Losing it degrades activation
ranking; it destroys nothing. **This is the single largest decision in the AD by
bytes — 986 MiB per tick — and it is what makes self-sufficiency affordable.**

`semantic_work.db`, `cognitive_journal.db`, `eviction_audit.db` and
`episode_fts.db` stay **included**. Exclusion is a stronger claim than the old
`bulk` demotion was, and none of them has the evidence.

### D2 — the byte budget, and why the AD-1262 defaults were a decision nobody made

Measured (2026-08-24, `%LOCALAPPDATA%\ProbOS\data`): included tier ≈ **559 MiB**
per tick (1530.7 MB top-level − 986 MiB `activation_tracker` + 15.7 MB
`procedures` + 20 KB `archive`); immutable ≈ **91 MiB** on the first tick and
~0 after, via hard link.

AD-1262 shipped 6 h cadence, `retain_days=7`, `max_total_bytes=8 GiB`. At its own
footprint (~1.6 GiB/tick with bulk amortized) that is ~24.5 GiB over 28 ticks —
**the byte ceiling bound at roughly 2 days and the 7-day knob was decorative.**

At this AD's footprint the two bounds can be made to agree:

```
6 h cadence          → 4 ticks/day
retain_days = 3      → 12 ticks × 559 MiB ≈ 6.7 GiB
                       + 91 MiB immutable (linked once)
                       ≈ 6.8 GiB  <  8 GiB ceiling      ✓ days binds, bytes is the valve
```

**Defaults: `backup_interval_seconds=21600` (6 h), `backup_retain_days=3`,
`backup_max_total_bytes=8 GiB`.** Put the arithmetic above in the config comment
and in `config/system.yaml`, so the next person inherits the reasoning and not
just the number.

Three days is defensible: this tier is transactional and authorization state, the
episodic system retains its own 7 days separately (AD-823), and the alternative —
a 7 that silently means 2 — is worse than an honest 3.

**And the valve must announce itself.** When retention prunes for bytes rather
than age, log once per prune at `warning` naming both bounds and the effective
retention in ticks. A ceiling that quietly overrides the stated policy is how the
AD-1262 default became a lie. This is testable (§8.14) and therefore allowed.

### D3 — the integrity contract, stated as narrowly as it can be kept

Review measured two failures. A same-length payload edit to `TAMPERED` passed
`PRAGMA integrity_check` and restored. And an opaque entry's digest was bypassed
because verification **chose its method by looking at the bytes it was verifying**
— replace the payload with a valid SQLite file and it takes the SQLite path,
never reaching the recorded digest.

The second is the general lesson and belongs in the docstring:

> **Never infer the verification method from the artifact being verified.** The
> manifest is authoritative. If it records a digest, compute the digest and
> compare. Asking the file what kind of file it is hands the attacker (or the
> corruption) the choice of test.

**The guarantee, and nothing beyond it:**

> For every file listed in a promoted snapshot's manifest, the bytes on disk
> SHA-256 to the digest the manifest records, and that digest was computed from
> the bytes as written, after those bytes passed `PRAGMA integrity_check`.

What that buys: tamper-evidence, torn-write detection, silent-corruption
detection, and a check that does not depend on the artifact's own self-report.
What it does **not** buy, and must not be claimed: semantic correctness of the
database (nothing can), or that the copy matches the source at snapshot instant
(that is the online `.backup` API's contract, not the manifest's).

Consequences:

- **Digest every included file, unconditionally.** The opaque/non-opaque split is
  deleted along with `bulk` — hashing 559 MiB costs ~1.1 s at 500 MB/s inside
  `to_thread`, which is not a cost worth a branch. Deleting the split deletes
  three round-2 findings at once.
- **`integrity_check` runs at snapshot time, not restore time.** Right after
  `.backup`, before the digest. It catches a bad copy at the only moment a retry
  is possible, and it keeps the restore-side check purely a digest comparison.
  Snapshot proves structure; the digest proves the bytes have not changed since.
- **A digest that cannot be computed is a snapshot failure** (tier 3, propagate) —
  the entry is `failed`, the snapshot is incomplete, and it is never promoted.
  AD-1262 swallowed that failure into an opaque entry with no digest, promoted the
  snapshot as complete, and let restore refuse it later. Recorded-but-unverified
  is the failure class; do not reproduce it.

### D4 — promotion is an atomic rename, and nothing else means "complete"

AD-1262 wrote the manifest, then promoted, and restore admitted "any directory
with a complete manifest." Process death between those two steps leaves exactly
that on disk, and it is restorable.

The manifest attests completeness of **content**. The directory name attests
completeness of **the write**. Both are required, and only one of them can be
made atomic:

```
build in   <backup_root>/<ts>.incomplete/
  … copy · integrity_check · digest each file …
write      <ts>.incomplete/manifest.json   (staging file → os.replace)
fsync      the manifest file and the directory
rename     <ts>.incomplete  →  <ts>          ← this, and only this, means promoted
```

`_SNAPSHOT_DIR_RE` must match promoted names only. Retention counts promoted
directories only. Hard-linking sources from promoted directories only. Any
consumer that admits a snapshot must admit it **by name first**, and an
operator-supplied path whose final component fails the regex is refused before
its manifest is even read.

**Sweep stale `.incomplete` directories** at the start of each tick, oldest-first,
logging at `warning`. A crash leaves one behind and nothing else will ever collect
it.

### D5 — restore semantics are settled here, and built in AD-1266

Stated now because §3's manifest and §4's unit have to be shaped by them, and
because the whole point of the split is that restore does not get to invent them.
See `prompts/ad-1266-restore-is-point-in-time.md` for the full contract. In
summary: **restore is point-in-time reconstruction of the declared roots,
all-or-nothing across every root**; the file unit is
`{X.db, X.db-wal, X.db-shm, X.db-journal}`; databases live but absent from the
snapshot are **moved aside, not deleted and not left**; excluded databases are
never touched.

**Nothing in this AD may reference, import or anticipate a restore module.** The
manifest is written for a consumer that does not exist yet — that is intentional,
and §7 is its stand-in.

---

## Implementation

Reuse the preserved attempt where review already proved it. Do **not** redesign:

| Preserved | Reuse | Change required |
|---|---|---|
| `.git/AD1262_backup_inventory.py` | discovery, root validation, unconditional `backup_root` prune, `is_relative_to` on resolved paths, deterministic ordering | delete `BULK_DATABASES` and `BackupTier.BULK`; move `activation_tracker.db` into `EXCLUDED_DATABASES` |
| `.git/AD1262_snapshot_manifest.py` | dataclasses, atomic write, refuse-on-unreadable read | delete `bulk_source`, `STATE_DEFERRED`, `opaque`, `is_sqlite_file`; make `sha256` required |
| `_sqlite_backup_loop` (in `.git/AD1262_ATTEMPT.patch`) | **verbatim** — warmup, `to_thread` offload, per-tick `try/except`, drain-aware idle, `CancelledError` re-raise | none |
| `prune()` age/bytes math | the two bounds and the never-prune-newest floor | add the D2 warning; count promoted dirs only |

### Section 1 — BF-849: the backup's connections are never closed

**Prerequisite, and it is not cosmetic.** `backup.py:_backup_one`:

```python
with sqlite3.connect(str(src)) as src_conn, sqlite3.connect(str(dest)) as dest_conn:
    src_conn.backup(dest_conn)
```

`sqlite3.Connection.__exit__` commits or rolls back a **transaction**. It does not
close the connection. Both handles leak on every file, every tick. On Windows an
open handle blocks `unlink` and `os.replace`, so **retention cannot delete what
the previous tick left open** — this AD's §6 depends on the fix, and so does
AD-1266.

Fix with `contextlib.closing` around each connect (keeping the `sqlite3.Error →
shutil.copyfile` fallback), and test it directly: after `_backup_one`, the source
file can be renamed on Windows. Do not assert on `gc` or connection internals.

### Section 2 — config

`src/probos/config.py`, `InfrastructureConfig` (:3962–3967). Add, with the D2
arithmetic as a comment, and mirror into `config/system.yaml` under
`infrastructure:`:

```
===SEARCH===
class InfrastructureConfig(BaseModel):
    """Engineering infrastructure configuration (AD-466)."""

    enabled: bool = True
    backup_enabled: bool = True
    backup_subdir: str = "backups"
===REPLACE===
class InfrastructureConfig(BaseModel):
    """Engineering infrastructure configuration (AD-466 / AD-1265)."""

    enabled: bool = True
    backup_enabled: bool = True
    backup_subdir: str = "backups"

    # AD-1265: AD-466 shipped the service with no scheduler; these drive it.
    # Defaults are arithmetic, not taste. Measured 2026-08-24: the included
    # tier is ~559 MiB/tick (immutable adds 91 MiB once, then hard-links).
    # 6 h => 4 ticks/day; 3 days => 12 ticks => ~6.8 GiB, under the 8 GiB
    # ceiling. Both bounds agree at this footprint, so retain_days means what
    # it says. Raise max_total_bytes before raising retain_days.
    backup_interval_seconds: float = Field(default=21600.0, ge=300.0)
    backup_warmup_seconds: float = Field(default=120.0, ge=0.0)
    backup_retain_days: int = Field(default=3, ge=1, le=365)
    backup_max_total_bytes: int = Field(default=8 * 1024**3, ge=64 * 1024**2)
    backup_include_archive_root: bool = True
===END REPLACE===
```

`backup_bulk_every_n` from AD-1262 is **not** reintroduced. Do not change
`memory.backup_*`.

### Section 3 — inventory (new module)

**New file:** `src/probos/infrastructure/backup_inventory.py` — port from
`.git/AD1262_backup_inventory.py` with the D1 changes.

- `BackupTier(StrEnum)`: `INCLUDED`, `IMMUTABLE`. **No `BULK`.**
- `BackupRoot(name, path)` frozen; `name` validated against `^[a-z0-9_-]{1,32}$`
  (it becomes a directory name).
- `EXCLUDED_DATABASES: Mapping[str, str]` — glob → **reason**, non-empty:
  - `"nats-jetstream/**"` → broker internals; rebuilt from stream config on reconnect
  - `"**/backups/**"` → backup root; excluded unconditionally, see `prune_backup_root`
  - `"activation_tracker.db"` → **new**, reason per D1
- `discover(roots, *, backup_root, exclude=EXCLUDED_DATABASES)` — `rglob("*.db")`,
  unconditional `backup_root` prune on **resolved** paths via `is_relative_to`,
  exclusion globs relative to root, classify `archives/ward_room_*.db` →
  `IMMUTABLE` else `INCLUDED`, deterministic sort by `(root.name, relative_path)`,
  missing root → zero entries at `info`.
- `build_default_roots(data_dir, config)` — `data` always;
  `archive` when `backup_include_archive_root and config.archive.enabled`, read
  from the **effective configured path**, never recomputed from the platform
  branch (an operator override must not silently go unbacked). Resolution failure
  → `warning`, continue with `data` only.

### Section 4 — the manifest (new module)

**New file:** `src/probos/infrastructure/snapshot_manifest.py` — port from
`.git/AD1262_snapshot_manifest.py`, minus everything D1/D3 deleted.

- `ManifestEntry`: `label`, `tier`, `state`, `size_bytes`, `sha256` (**required,
  non-empty for every present entry**), `error`. **No `opaque`.**
- `SnapshotManifest`: `snapshot`, `created_at`, `entries`, `schema`.
  **No `bulk_source`, no `included_bulk`.** `complete` is `not self.failed`.
- States: `copied`, `linked`, `failed`. **No `deferred`.**
- `write_manifest` — staging file → `os.replace`, then **fsync the file and the
  containing directory**. Propagates on failure (tier 3).
- `read_manifest` — returns `None` on absent/unreadable/malformed; every caller
  treats `None` as refusal. Keep the AD-466-era note: pre-manifest snapshots are
  refused because nothing recorded what they were supposed to contain. (Live
  vessel has zero, so this is not a migration.)
- `sha256_file` — streaming, 1 MiB chunks.
- **Delete `is_sqlite_file`.** Its only caller chose a verification path from the
  artifact's own bytes, which is the D3 defect. Nothing may reintroduce it.

### Section 5 — `BackupService`

`src/probos/infrastructure/backup.py`. Discovery stays in §3, manifest in §4 (SRP).
Additive keyword-only constructor params with defaults so the AD-466 signature
still constructs; `roots=None` synthesizes `[BackupRoot("data", data_dir)]`.

`snapshot() -> BackupResult` implements D4 exactly:

1. sweep stale `*.incomplete` under `backup_root` (oldest-first, `warning`);
2. `mkdir <ts>.incomplete`;
3. for each discovered file, into `<ts>.incomplete/<root.name>/<relative_path>`:
   - `IMMUTABLE`: `os.link` from the newest **promoted** snapshot when
     `(size, mtime_ns)` match **and** `mtime_ns < that snapshot's start`; on
     `OSError` fall back to copy. **Never skip.**
   - otherwise `_backup_one` (online `.backup`);
   - `PRAGMA integrity_check` on the written file; then `sha256_file`;
   - any of those failing → entry `state="failed"` with the error, `warning`,
     **continue** (one unreadable file must not abort the pass — but see 5);
4. write the manifest, fsync file + dir;
5. **promote only when `manifest.complete`** — `os.replace(<ts>.incomplete, <ts>)`.
   Otherwise leave `.incomplete` on disk, emit `BACKUP_FAILED` naming the failed
   labels, and **do not run retention**;
6. on promotion emit `BACKUP_COMPLETE` and run `prune()`.

`BackupResult` gains `files_linked`, `files_failed`, `snapshot_promoted: bool`.
Existing fields keep their names and meanings. `succeeded` means **promoted** —
not "something copied". Say so in the docstring; the old
`succeeded = bool(files_copied)` shape is the defect the manifest exists to close.

`BACKUP_COMPLETE` payload extends additively: `files_linked`, `files_failed`,
`pruned_dirs`, `retention_bound` (`"days"` | `"bytes"`). No new `EventType`.

### Section 6 — retention

`prune(self) -> PruneResult`, called only after a **promoted** snapshot.

- Enumerate **promoted** directories only (`_SNAPSHOT_DIR_RE`); `.incomplete` is
  invisible to retention.
- Enforce `retain_days`, then `backup_max_total_bytes`, oldest-first. Age math
  modelled on `maintenance/episodic_backup.py:203-231`.
- **Never prune the newest promoted snapshot**, even alone over the ceiling. A
  retention policy that can prune itself to zero is worse than none, because it
  looks like protection.
- **D2 warning:** when the bytes bound removed anything the days bound would have
  kept, log once at `warning` with both bounds and the effective retention in
  ticks, and set `retention_bound="bytes"` in the event payload.
- Hard-linked immutables: pruning a source snapshot does not destroy bytes still
  linked elsewhere (link count > 1). No special handling — say it in the
  docstring so nobody adds any.

### Section 7 — `probos verify-snapshot` (the thing that pays for the split)

**New file:** `src/probos/infrastructure/snapshot_verify.py`, plus a CLI command.
**This writes nothing. It is not restore and must not grow into it.**

`verify_snapshot(snapshot_dir) -> VerifyReport`:

- refuse by **name** first (D4) — a path whose final component fails
  `_SNAPSHOT_DIR_RE` is rejected before its manifest is read;
- refuse when `read_manifest` returns `None` or `complete` is false;
- for every present entry: file exists · `size_bytes` matches ·
  **`sha256_file` matches the recorded digest** (never inferred from the bytes,
  D3) · the file **opens through the normal connection path a runtime would use**
  and answers a trivial query. Opening the bytes is the point: this is what
  converts "we have files" into "we have files that open."
- report per-file verdicts and one overall boolean; exit code 0 / 1.

`src/probos/__main__.py` — `probos verify-snapshot --snapshot <dir> [--data-dir]
[--config]`, modelled on `_cmd_rebuild_episodic` (:1331) with its subparser beside
the AD-819 block (:2388) and dispatch beside :2484. **No AD-816 pidfile guard —
this is read-only and must be runnable on a live vessel.** That is the difference
from AD-1266, and it is deliberate.

### Section 8 — scheduler

**`src/probos/runtime.py`** — port `_sqlite_backup_loop` from
`.git/AD1262_ATTEMPT.patch` **verbatim**; review verified it by execution.

1. Declare beside `_episodic_backup_task` (:521), `TYPE_CHECKING` import to avoid
   the cycle:
   ```python
   self.backup_service: "BackupService | None" = None
   self._sqlite_backup_task: asyncio.Task[None] | None = None
   ```
2. `async def _sqlite_backup_loop(self)` modelled on `_episodic_backup_loop`
   (:3567): config/None early return with a logged reason · warmup via
   `asyncio.wait_for(self._shutdown_event.wait(), timeout=backup_warmup_seconds)`
   · shutdown pre-check · **`await asyncio.to_thread(self.backup_service.snapshot)`**
   — `snapshot()` is synchronous and does blocking multi-hundred-MB file I/O;
   running it on the loop stalls the runtime for the duration. State that in the
   docstring as the one deliberate divergence from the episodic precedent ·
   per-tick `try/except Exception` → `logger.warning(..., exc_info=True)` ·
   `finally:` shutdown re-check · drain-aware idle · `except
   asyncio.CancelledError: logger.debug(...); raise`.
3. Spawn beside the episodic spawn (:3261) with
   `name="sqlite-backup-loop", drain_on_shutdown=True`. Drain is required: a tick
   cancelled mid-copy would otherwise leave a torn `.incomplete` — harmless under
   D4, but the sweep should not be the primary defence.

**`src/probos/startup/finalize.py`** (:3583–3603) — pass `roots` from
`build_default_roots`, plus `retain_days` and `max_total_bytes` from config.

### Section 9 — tests

**`tests/test_ad1265_backup_scheduler.py`**

1. A snapshot appears **from runtime startup** — boot the real startup path with
   `backup_warmup_seconds≈0.05` against `tmp_path`, poll on a condition with a
   timeout. **The test must never call `snapshot()` and must not reference
   `BackupService` to trigger anything.** If it does, it has reproduced the bug it
   exists to prevent.
2. `BACKUP_COMPLETE` is queryable from the **event log** (`events.db` / `EventLog`),
   not "`emit_event` was called" — the live evidence in #1313 was event-log rows,
   so the test must be able to fail the way the vessel failed.
3. Shutdown drains without leaving a promoted-looking directory.
4. Snapshot twice; the second contains **no** entry from the first, by path,
   recursively.
5. Self-exclusion holds under a nested `backup_subdir` and through a symlink into
   the backup root.
6. `BF-849`: after `_backup_one`, the source file can be renamed (Windows handle
   released).
7. Every tick contains **every** included database — the D1 self-sufficiency
   invariant. Take three consecutive ticks; assert identical label sets.
8. An immutable file identical to the prior **promoted** snapshot is hard-linked
   (`st_nlink > 1`); 9. one whose `mtime` is newer than that snapshot's start is
   **copied, not linked**; 10. `os.link` raising `OSError` falls back to copy.

**`tests/test_ad1265_snapshot_integrity.py`**

11. A failed file leaves the directory `.incomplete`, **unpromoted**, emits
    `BACKUP_FAILED`, and **does not run retention**.
12. A hand-built `.incomplete` directory containing a valid, `complete=true`
    manifest is **refused by `verify_snapshot`** — by name, before the manifest is
    read. This is the round-2 finding; it must fail loudly if promotion ever stops
    being the sole marker.
13. Stale `.incomplete` directories are swept on the next tick.
14. A promoted snapshot passes `verify_snapshot`; every file opens through the
    normal connection path.
15. A **same-length** payload edit inside a promoted snapshot is caught by
    `verify_snapshot`. This is the exact `TAMPERED` case `integrity_check` passed;
    it must now fail on the digest.
16. **Replacing an entry's file with a different but structurally valid SQLite
    database is caught.** The D3 finding: verification must not be able to take a
    path that skips the recorded digest.
17. A digest that cannot be computed marks the entry `failed` and blocks
    promotion — it does **not** produce a present-but-undigested entry.
18. `verify_snapshot` refuses a manifest-less (AD-466-era) directory.

**`tests/test_ad1265_retention.py`**

19. `retain_days` prunes by age; 20. `max_total_bytes` prunes oldest-first;
21. the newest promoted snapshot is never pruned even when alone over the ceiling;
22. retention runs only after a **promoted** snapshot; 23. `.incomplete`
    directories are invisible to retention; 24. **the bytes-bound warning fires and
    `retention_bound="bytes"` reaches the event payload** when bytes bind before
    days (D2); 25. pruning a snapshot whose immutable files are hard-linked
    elsewhere leaves those bytes readable.

**`tests/test_ad1265_backup_coverage.py`** (BF-838)

26. Scan `src/` for quoted `*.db` literals; every one is either reachable by
    `discover()` under a declared root, or matched by `EXCLUDED_DATABASES` **with a
    non-empty reason**. Failure names the file and the fix.
27. `INCLUDED` is the default: a synthetic unknown `*.db` under a root classifies
    `INCLUDED`.
28. **No `BULK` tier exists** — assert `BackupTier` has exactly `INCLUDED` and
    `IMMUTABLE`, and that `backup_inventory` exposes no `BULK_DATABASES`. This is
    a regression guard on D1, not decoration.
29. Record in the module docstring, with the 2026-08-24 date: grant-store counts
    (`clearance_grants=0`, `intent_access_grants=0`, `skill_access_grants=0`,
    `tool_access_grants=1`, `action_approvals=0`), `schema_versions.db` absent but
    glob-covered when created, 14 of BF-838's 22 already top-level.

> **Caveat — this repo has been bitten four times.** Test 26 is a **source scan**,
> and a source scan cannot distinguish "this is required" from "this is what
> shipped." It is acceptable here *only* because it asserts against
> `EXCLUDED_DATABASES`, a deliberate human-authored table, rather than against
> observed behaviour. If a future change touches it, **update the assertion and
> record why inline. Never delete it to make a build green.**

**`tests/test_ad466_infrastructure.py`** — amend the 11 existing tests for the
root-namespaced layout (`<ts>/data/<name>` rather than `<ts>/<name>`) and for
`succeeded` now meaning *promoted*. Amend; do not delete.

---

## What this does NOT change

- `_episodic_backup_loop`, `snapshot_episodic`, `maintenance/episodic_backup.py`,
  `memory.backup_*`, `backups/episodic/`. Different system, works, out of scope.
- **AD-1256 (#1302).** No store registry, no shared storage layer, no
  consolidation of the 34 bespoke connects. `EXCLUDED_DATABASES` stays a plain
  module-level table so AD-1256 can absorb it later.
- `archive.db` does not move. No data migration.
- No new `EventType` — `BACKUP_COMPLETE` / `BACKUP_FAILED` (`events.py:321-322`)
  extend additively.
- No API route, no HXI surface, no WebSocket frame.
- No compression, encryption or off-host replication.
- No change to `SQLiteStorageBackend` or `storage/sqlite_factory.py`.

## Do not build

- **Any restore path.** No `restore.py`, no `probos restore-snapshot`, no function
  that writes into a declared root. That is AD-1266. `verify_snapshot` is
  read-only and must stay read-only.
- **Any reintroduction of `bulk`**, `bulk_every_n`, `bulk_source`, `STATE_DEFERRED`,
  or any tier a tick can skip. If the byte budget hurts, change the cadence or the
  ceiling — both are config — and say so. Do not re-add a tier.
- **`is_sqlite_file`, or any verification that inspects the artifact to decide how
  to verify it.** The manifest decides.
- An `opaque` entry, or any present entry without a digest.
- Retention that can prune the only remaining snapshot, or that can see
  `.incomplete` directories.
- A recursive glob without the unconditional `backup_root` prune, even temporarily.
- Promotion by anything other than the atomic rename — no `.complete` marker file,
  no manifest flag, no mtime heuristic.
- Excluding `semantic_work.db`, `cognitive_journal.db`, `eviction_audit.db` or
  `episode_fts.db` on size alone.
- A background *verify*. §7 is operator-invoked. An automatic verifier that finds
  a bad snapshot has nothing it is allowed to do about it.

---

## Tracking

- `PROGRESS.md` — AD-1265 entry; BF-842 (#1313), BF-838 (#1304) and BF-849 CLOSED,
  with the corrected coverage arithmetic. Note AD-1266 as the open follow-on and
  that **restore does not exist until it lands.**
- `docs/development/roadmap.md` Bug Tracker — rows for BF-842, BF-838, BF-849.
- `DECISIONS.md` — AD-1265: D1 (no sometimes-tier; hard link ≠ carry-forward),
  D2 (the byte arithmetic behind the defaults), D3 (the integrity guarantee and
  its stated limits), D4 (promotion is the rename).
- `python scripts/gen_ad_ledger.py` after the issues close.

## Acceptance criteria

1. `snapshot()` is invoked on a schedule in production, gated by
   `config.infrastructure.backup_enabled`, off the event loop.
2. A test asserts a snapshot appears **from runtime startup**, never calling
   `snapshot()`; another asserts `BACKUP_COMPLETE` is queryable from the event log.
3. **Every promoted snapshot contains every included database** — proven across
   three consecutive ticks, with no tier that a tick may skip.
4. A snapshot is promoted **only** by atomic rename, only when its manifest is
   complete, and a hand-built `.incomplete` with a valid manifest is refused.
5. `verify_snapshot` catches a same-length payload edit **and** a substituted
   valid SQLite database, and opens every file through the normal connection path.
6. Retention bounds age and bytes, never prunes the sole snapshot, ignores
   `.incomplete`, and **announces at `warning` when bytes bind before days.**
7. Snapshot-twice proves the second excludes the first, under a nested
   `backup_subdir` and through a symlink.
8. Every `*.db` declared in `src/` is discovered or excluded-with-a-reason, and a
   test fails when a new one is neither. `BULK` does not exist.
9. BF-849: `_backup_one` releases both handles; proven by renaming the source on
   Windows.
10. Full gate green: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`.
    Focused: `pytest tests/test_ad1265_*.py tests/test_ad466_infrastructure.py -v -n 0`.
11. **Verify all changes comply with the Engineering Principles in
    `.github/copilot-instructions.md`.**
12. Run the `Diff Reviewer` subagent on the staged diff before committing, with a
    different model than the one that wrote the code, and address Required
    findings before the commit.

### Stop rule

AD-1262 was reverted after round-2 review found six findings, all located inside
machinery the AD itself had introduced. That is the signal, and it is **location,
not severity**.

> **If adversarial review returns a Required finding located inside machinery
> introduced by this AD — the manifest, the promotion protocol, the digest path,
> the sweep — for a *second* review round, stop. Do not patch. Commit nothing,
> record every measured finding with its reproduction, and hand the state model
> back to Architect.**

Two independent findings spread across the diff is a normal review. Two rounds
converging on one seam means the seam is wrong, and each patch will grow it. A
one-line fix that exposes an inadequate consumer is not a one-line job.

Corollary: **before adding any protocol to prevent something, price what it
actually costs if it happens.** AD-1262's opaque/digest split existed to avoid
hashing a tier this AD deleted. If a control's justification disappears, delete
the control rather than maintaining it.

---

## Verified Against Codebase (2026-08-24)

```
git rev-parse --short HEAD
  e97b9125   BF-848: prove the crew-executor cap by rendezvous, not by wall-clock overlap

Select-String src\probos\config.py -Pattern 'class InfrastructureConfig|backup_enabled|backup_subdir'
  1095: backup_enabled: bool = True                    (MemoryConfig — untouched)
  3962: class InfrastructureConfig(BaseModel):
  3966: backup_enabled: bool = True
  3967: backup_subdir: str = "backups"

Select-String src\probos\startup\finalize.py -Pattern 'BackupService|backup_service|backup_root'
  3575: # AD-466: Engineering Infrastructure (BackupService + StorageBackend)
  3583: backup_root = runtime.data_dir / config.infrastructure.backup_subdir
  3586: runtime.backup_service = BackupService(
  3601/3603: runtime.backup_service = None

Select-String src\probos\runtime.py -Pattern '_episodic_backup_task|_episodic_backup_loop|_spawn_background'
  521:  self._episodic_backup_task: asyncio.Task[None] | None = None
  3261: self._episodic_backup_task = self._spawn_background(
  3456: def _spawn_background(
  3567: async def _episodic_backup_loop(self) -> None:

Select-String src\probos\infrastructure\backup.py -Pattern 'with sqlite3.connect|glob|does not run'
  36:  Caller is responsible for scheduling. v1 does not run a background task.
  67:  db_files = sorted(self._data_dir.glob("*.db"))
  92:  with sqlite3.connect(str(src)) as src_conn, sqlite3.connect(str(dest)) as dest_conn:
        ^ BF-849: transaction manager, not a closer. Both handles leak.

Select-String src\probos\events.py -Pattern 'BACKUP'
  321: BACKUP_COMPLETE = "backup_complete"  # AD-466
  322: BACKUP_FAILED = "backup_failed"  # AD-466

Select-String src\probos\maintenance\episodic_backup.py -Pattern 'prune|retain_days'
  195: _prune_old_snapshots(backups_dir, retain_days=retain_days, today=today)
  203-231: age math + unlink — the retention precedent

Select-String src\probos\__main__.py -Pattern 'rebuild-episodic|assert_no_other_instance'
  1331: def _cmd_rebuild_episodic(args) -> int
  1352-1363: AD-816 assert_no_other_instance(data_dir) — used by AD-1266, NOT §7
  2388: subparsers.add_parser("rebuild-episodic", …)
  2484-2486: dispatch
```

### Absence Verified (2026-08-24)

```
CLAIM: nothing in src/ reads runtime.backup_service
RUN:   Get-ChildItem -Path src -Recurse -Filter *.py | Select-String 'backup_service'
FOUND: finalize.py:3586, :3601, :3603 — three writes
HOLDS: yes, zero reads. Also undeclared on the runtime class:
       Select-String src\probos\runtime.py -Pattern 'backup_service' → no matches

CLAIM: no restore path exists for BackupService snapshots at HEAD
RUN:   Select-String -Path src -Recurse 'def restore|restore_from|restore_snapshot'
FOUND: proactive.py:804, warm_boot.py:75, checkpoint.py:133, procedure_store.py:1565,
       session_manager.py:73/136, workflow_cache.py:225, routers/procedures.py:272,
       security/pairing/service.py:238
HOLDS: yes — nine hits, none reads a snapshot directory. The revert removed the
       AD-1262 attempt; the tree is clean at e97b9125.
```

### Live vessel (2026-08-24, `%LOCALAPPDATA%\ProbOS\data`)

```
top-level *.db      : 43 files, 1530.7 MB
largest             : activation_tracker 1,034,321,920  ← EXCLUDED by D1
                      semantic_work 164,708,352 · cognitive_journal 152,322,048
                      eviction_audit 140,107,776 · episode_fts 29,630,464  ← all INCLUDED
nested              : archives\ward_room_*.db × 23 (91.4 MB, newest 2026-04-16) → IMMUTABLE
                      procedures\procedures.db 15,732,736 → INCLUDED
                      nats-jetstream\**\index.db × 4 (3.3 KB) → EXCLUDED
outside data_dir    : %LOCALAPPDATA%\ProbOS\archive\archive.db 20,480 B → INCLUDED (root "archive")
data\backups\       : episodic\ only. ZERO timestamped snapshot dirs, ever.
events.db           : 1216 rows 2026-08-23T06:25 → 2026-08-24T06:05; 0 matching %backup%
                      (controls agent_wired=723, pool_created=455 confirm the query works)
grant stores        : clearance_grants=0 · intent_access_grants=0 · skill_access_grants=0
                      tool_access_grants=1 · action_approvals=0   (1 row in total)
schema_versions.db  : ABSENT (declared cognitive_services.py:389; glob-covered when created)

derived: INCLUDED tier ≈ 559 MiB/tick · IMMUTABLE ≈ 91 MiB once, then hard-linked
         6 h × 3 days = 12 ticks ≈ 6.8 GiB  <  8 GiB ceiling
```
