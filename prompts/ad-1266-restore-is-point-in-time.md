# AD-1266 — restore is point-in-time, or it is not restore

**Status:** blocked on AD-1265 — **do not start until AD-1265 is merged and green**
**Closes:** the restore half of BF-842 (#1313); completes the round trip AD-1265 could not prove
**Dependencies:** AD-1265 (snapshot unit, manifest, promotion protocol, `verify_snapshot`), AD-816 (`assert_no_other_instance`), AD-819 (`rebuild-episodic` CLI precedent)
**Estimated tests:** 26–30 new in 2 new files

---

## Numbering

Verified at HEAD `e97b9125` (2026-08-24): prompts ceiling `ad-1264`, HEAD commit
`BF-848`. Current highest **AD-1264, BF-848**. AD-1265 is the snapshot AD; **this
is AD-1266**. Next free after this pair: **AD-1267, BF-850.**

---

## Why this is a separate AD

AD-1262 built scheduling and restore together and was reverted. Round-2 review
found six blockers; three of them were the same unanswered question — *is restore
point-in-time reconstruction, or selective file replacement?* — and the other
three were consequences of restore having been allowed to define the snapshot unit
by accident.

AD-1265 settles the unit: every promoted snapshot is a self-sufficient
point-in-time image, digest-attested, promoted by atomic rename. **This AD is a
consumer of that contract and adds nothing to it.** If a requirement here would
change the snapshot unit, it is a defect in AD-1265, not a feature of this AD —
stop and say so.

---

## The decision this AD implements

> **Restore is point-in-time reconstruction of the declared roots. It is
> all-or-nothing across every root. It never leaves a database from a different
> generation in place, and it never destroys one.**

### Why not selective file replacement

The vessel's databases are not independent. `episode_fts` indexes episodes that
live in ChromaDB; the grant stores reference agents in the registry; `procedures`
references skills. Replacing one database with an older generation and leaving its
neighbours produces a vessel that is internally inconsistent **and reports
success** — which is worse than a vessel that is obviously broken, because nothing
will ever look at it again.

Review measured exactly this: a database created after the snapshot survived
restore beside the older restored ones, and restore reported success. That was not
a missing check. It was the selective-replacement model working as designed.

**Cost of point-in-time, stated plainly:** you cannot restore one database. If
`fault_reports.db` is corrupt, restore takes the whole vessel back to the snapshot
instant, losing everything written since across every root. That is a real cost
and it is the right one — a partial restore is a guess about coupling that nobody
in this codebase is in a position to make. An operator who genuinely wants one
file can copy it out of the snapshot directory by hand; that is a deliberate,
visible act rather than a tool that quietly produces a mixed-generation vessel.

### D1 — the file unit is the database **and its sidecars**

Review measured the failure and it is the sharpest one in the set: the snapshot
held `snapshot-v1`; the live database committed `live-v2` and the process died
without closing SQLite; restore replaced the main `.db`, **reported success**, and
the database then replayed the crash-left `-wal` and returned `live-v2`. The
restore was undone by a file it never looked at.

**The unit for both move-aside and placement is
`{X.db, X.db-wal, X.db-shm, X.db-journal}`, moved and placed together.**

- The snapshot side needs **no** change. `sqlite3.Connection.backup` produces a
  fully materialized, checkpointed database with no WAL. Capturing the *source's*
  WAL would capture a different generation's WAL — that is the corruption, not the
  cure. **Do not add sidecar capture to AD-1265.**
- The defect is entirely at the **destination**. Any sidecar beside a restore
  target belongs to the pre-restore generation and is by definition stale.
- Sidecars **move aside with their database**, they are not deleted. Deleting the
  `-wal` and then rolling back the `.db` would destroy the pre-restore
  generation's uncommitted data — the rollback must be able to put the vessel back
  exactly as it was found.
- After placement, **assert no sidecar exists beside any restored file** before
  reporting success. The measured failure becomes the test (§4.3).

### D2 — databases live but absent from the snapshot are moved aside

Four options; three are wrong.

| | verdict |
|---|---|
| Leave them | mixed-generation vessel reporting success — **the measured finding**. No. |
| Delete them | a restore that destroys data nobody asked it to touch. No. |
| Refuse the restore | a vessel that created one new database could never be restored. No. |
| **Move aside** | removed from the live generation, fully recoverable, same mechanism already used for replaced files. **Yes.** |

They go into the same `<root>/_pre_restore_<ts>/` tree, preserving relative paths,
and they are **named in the plan** under "will be moved aside (not in this
snapshot)" so `--dry-run` shows the operator exactly what leaves.

**Scope, stated because this is where point-in-time is deliberately partial:**
"absent from the snapshot" is judged using the **same `discover()` and the same
`EXCLUDED_DATABASES`** the snapshot used. Excluded databases — `nats-jetstream/**`,
`activation_tracker.db`, anything under `backup_root` — are **not part of the
point-in-time unit and are not touched.** Restore does not provide them and does
not remove them. This is the one partial guarantee in the contract, and an
unstated partial guarantee is the recorded-but-unverified class review already
named. State it in the docstring, print it in the plan, and test it (§4.9).

### D3 — all-or-nothing across every declared root

If the `archive` root fails after `data` succeeded, the vessel is
mixed-generation across roots — the same defect at a coarser grain. One
transaction:

```
plan     → resolve every root, every file, every move-aside, every orphan
verify   → digest-check every file in the snapshot against the manifest
             (AD-1265 §7 semantics; ANY mismatch aborts before anything moves)
move     → every target and its sidecars, and every orphan, into _pre_restore_<ts>/
place    → copy to temp name in the destination dir, then os.replace
confirm  → no sidecar survives beside a restored file; every file opens through
             the normal connection path
commit   → report; leave _pre_restore_<ts>/ on disk (the operator deletes it)
```

Failure at any phase rolls back **everything**, across all roots, from the
move-aside, in a `finally`. `KeyboardInterrupt` mid-restore must still leave the
move-aside intact and the rollback must run. Report which phase failed.

### D4 — admission: by name, then by manifest, then by digest

AD-1265 D4 makes the atomic rename the sole marker of promotion. Restore inherits
it and must not soften it:

1. the path's final component matches `_SNAPSHOT_DIR_RE` — an `.incomplete`
   directory is refused **before its manifest is read**, including when the
   operator points `--snapshot` straight at one;
2. `read_manifest` returns a manifest and `complete` is true;
3. every present entry's bytes match the recorded digest.

**Verification method comes from the manifest, never from the artifact**
(AD-1265 D3). Reuse `verify_snapshot` — do not write a second verification path.
A second path is how the first one gets bypassed.

### D5 — refuse under a live runtime

`assert_no_other_instance(data_dir)` exactly as `__main__.py:1352-1363` does.
Restoring beneath a running vessel corrupts both copies. This is the difference
from AD-1265 §7, which is read-only and deliberately runs live.

---

## Implementation

`.git/AD1262_restore.py` is preserved and its **plan / move-aside / rollback /
`render_plan` skeleton is sound** — review's findings were about semantics, not
structure. Port it, then apply D1–D4. Delete `verify_snapshot_file` outright: it
chose its verification path from the artifact's bytes, which is the AD-1265 D3
defect, and `verify_snapshot` replaces it.

### Section 1 — `src/probos/infrastructure/restore.py`

`restore_snapshot(snapshot_dir, roots, *, dry_run=False) -> RestoreResult`

- D5 guard first; D4 admission second; **nothing on disk is touched until the
  whole plan verifies.**
- Plan covers, per root: `to_place` (in snapshot), `to_move_aside` (live targets
  and their sidecars), `orphans` (live, discoverable, not in the snapshot — D2),
  `untouched_excluded` (reported, never moved).
- Place via copy-to-temp-name → `os.replace` in the destination directory (same
  filesystem, so the replace is atomic).
- Confirm phase per D1 and D3 before reporting success.
- Unknown root names inside the snapshot are **reported and refuse the restore** —
  AD-1262 skipped them, which is a silent partial restore under a point-in-time
  contract. Under D3 an unresolvable root means the plan is incomplete.
- Roll back in a `finally`; verify the rollback and report if it too failed
  (a failed rollback is the worst state and must be loud).

### Section 2 — CLI

`src/probos/__main__.py` — `probos restore-snapshot`, modelled on
`_cmd_rebuild_episodic` (:1331), subparser beside the AD-819 block (:2388),
dispatch beside :2484. Flags: `--snapshot` (required), `--data-dir`, `--config`,
`--dry-run`.

`--dry-run` prints the full plan — files, sizes, digest results, what moves aside,
**what is orphaned, and what is excluded-and-untouched** — and writes nothing.

### Section 3 — `RestoreResult` / `render_plan`

Port from the preserved attempt. `render_plan` must show orphans and excluded
files as their own sections; an operator reading the plan should be able to see
the whole delta without knowing the tier model.

### Section 4 — tests

**`tests/test_ad1266_restore_roundtrip.py`**

1. **The round trip.** Write a known row → promoted snapshot → corrupt the live db
   → restore → the row is back, `integrity_check` is `ok`, **and the file opens
   through the normal `default_factory` connection path a runtime would use.**
   Reading the bytes back is not proof the vessel is usable.
2. Round trip across **both** roots (`data` and `archive`).
3. **The sidecar case, exactly as measured.** Snapshot holds `snapshot-v1`; live
   commits `live-v2` and is abandoned with a crash-left `-wal`; restore; the
   database reads `snapshot-v1`, **and no `-wal`/`-shm` survives beside it.** This
   test is the reason D1 exists and must not be weakened.
4. Sidecars are present in `_pre_restore_<ts>/`, not deleted (the rollback source).
5. `--dry-run` writes nothing — assert mtimes unchanged across every root.

**`tests/test_ad1266_restore_safety.py`**

6. Refused when the pidfile shows a live runtime (D5).
7. Refused when `--snapshot` points at an `.incomplete` directory containing a
   valid `complete=true` manifest — **by name, before the manifest is read** (D4).
8. **The orphan case, exactly as measured.** A database created after the snapshot
   is moved aside, not left and not deleted; the live root afterwards contains no
   database absent from the manifest (D2).
9. An **excluded** database (e.g. `activation_tracker.db`) is untouched by restore
   and named in the plan as untouched — the stated partial guarantee (D2 scope).
10. A digest mismatch on **one** file aborts the whole restore and writes nothing —
    assert every live database is byte-identical afterwards, across both roots.
11. A failure during the place phase rolls back **every** root to the pre-restore
    state (D3).
12. `KeyboardInterrupt` mid-restore still runs the rollback and leaves the
    move-aside intact.
13. A failed rollback is reported loudly and distinguishably from a failed restore.
14. An unknown root directory inside the snapshot **refuses** the restore.
15. A manifest-less (AD-466-era) directory is refused.

---

## What this does NOT change

- **The snapshot unit.** No sidecar capture, no new tier, no manifest field, no
  change to promotion. If this AD seems to need one, that is an AD-1265 defect —
  stop and say so.
- `verify_snapshot` stays read-only and keeps its signature. Restore **calls** it.
- `_episodic_backup_loop` and the episodic backup system.
- No API route, no HXI surface, no WebSocket frame. **Restore is CLI-only and must
  stay CLI-only** — a one-click restore is a destructive action with no consensus
  gate, and designing that gate is a separate AD.

## Do not build

- A background restore, an auto-restore-on-corruption path, or any code that
  invokes `restore_snapshot` without an operator. Automatic restore is a
  destructive action.
- **Selective / single-file restore**, a `--only <db>` flag, or any partial mode.
  That is the model this AD exists to reject.
- A second verification path. `verify_snapshot` is the only one.
- Deleting anything outside `_pre_restore_<ts>/`. Restore never destroys; it moves.
- Skipping unknown roots. Under point-in-time, unknown means refuse.
- Restoring into a live runtime, or weakening the AD-816 guard to a warning.

---

## Tracking

- `PROGRESS.md` — AD-1266 entry; the round trip now exists, so the AD-1265 note
  "restore does not exist until it lands" is removed.
- `DECISIONS.md` — AD-1266: point-in-time over selective replacement and what it
  costs; the sidecar unit; orphans move aside; all-or-nothing across roots.
- `docs/development/roadmap.md` — BF-842 row updated to note the round trip.

## Acceptance criteria

1. A round trip proves the restored database is usable **through the normal
   connection path**, across both roots.
2. The measured sidecar failure is a test and passes: no crash-left `-wal`
   survives a restore, and the restored database reads the snapshot generation.
3. The measured orphan failure is a test and passes: after restore, no database
   under a declared root is absent from the manifest, and none was deleted.
4. Any single digest mismatch aborts the entire restore across every root, and
   every live file is byte-identical afterwards.
5. An `.incomplete` directory is refused by name, before its manifest is read.
6. Restore refuses under a live runtime; `--dry-run` writes nothing and names
   orphans and excluded-untouched files.
7. Rollback restores every root and is verified; a failed rollback is loud and
   distinguishable.
8. Full gate green: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`.
   Focused: `pytest tests/test_ad1266_*.py tests/test_ad1265_*.py -v -n 0`.
9. **Verify all changes comply with the Engineering Principles in
   `.github/copilot-instructions.md`.**
10. Run the `Diff Reviewer` subagent on the staged diff before committing, with a
    different model than the one that wrote the code, and address Required
    findings before the commit.

### Stop rule

Inherited from AD-1265 and tightened, because this AD is the one that failed
before:

> **If adversarial review returns a Required finding located inside the restore
> transaction — the plan, the move-aside, the place, the confirm, the rollback —
> for a *second* review round, stop. Do not patch. Commit nothing, record every
> measured finding with its reproduction, and hand back to Architect.**

And a second, specific to this AD:

> **If any finding can only be fixed by changing the snapshot unit, stop
> immediately — first round, no exceptions.** That is the failure mode that
> produced AD-1262's carry-forward: restore needed something the snapshot did not
> provide, and invented it. The correct response is an AD-1265 amendment reviewed
> on its own, not a restore-side workaround.

---

## Verified Against Codebase (2026-08-24)

```
git rev-parse --short HEAD
  e97b9125   BF-848: prove the crew-executor cap by rendezvous, not by wall-clock overlap

Select-String src\probos\__main__.py -Pattern 'rebuild-episodic|assert_no_other_instance'
  1331: def _cmd_rebuild_episodic(args) -> int
  1352-1363: AD-816 read-only check → assert_no_other_instance(data_dir), return 2
  2388: subparsers.add_parser("rebuild-episodic", …)
  2484-2486: dispatch

Preserved attempt (structure reused, semantics replaced):
  .git/AD1262_restore.py:131 verify_snapshot_file   ← DELETE (AD-1265 D3 defect)
  .git/AD1262_restore.py:186 restore_snapshot       ← port, apply D1–D4
  .git/AD1262_restore.py:331 _plan                  ← port, add orphans + excluded
  .git/AD1262_restore.py:461 _apply                 ← port, add sidecar unit
  .git/AD1262_restore.py:551 _rollback              ← port unchanged
  .git/AD1262_restore.py:581 _verify_rollback       ← port unchanged
  .git/AD1262_restore.py:622 render_plan            ← port, add orphan/excluded sections
```

### Absence Verified (2026-08-24)

```
CLAIM: no restore path for BackupService snapshots exists at HEAD
RUN:   Get-ChildItem -Path src -Recurse -Filter *.py |
       Select-String 'def restore|restore_from|restore_snapshot'
FOUND: proactive.py:804 restore_cooldowns · warm_boot.py:75 restore ·
       checkpoint.py:133 restore_dag · procedure_store.py:1565 restore_procedure ·
       session_manager.py:73/136 · workflow_cache.py:225 ·
       routers/procedures.py:272 · security/pairing/service.py:238
HOLDS: yes — nine hits, all unrelated domain restores; none reads a snapshot dir.
```

### Measured failures this AD must turn into passing tests (2026-08-24, AD-1262 round-2 review)

```
SIDECAR   snapshot held snapshot-v1; live committed live-v2 and died without
          closing SQLite; restore replaced the .db and reported success; the db
          then replayed the stale -wal and returned live-v2.        → test 3

ORPHAN    a database created after the snapshot survived restore beside the older
          restored ones; restore reported success.                  → test 8

ADMIT     the manifest is written before promotion, and restore admitted any
          directory with a complete manifest; process death after the manifest
          write leaves exactly that on disk, restorable.            → test 7
```
