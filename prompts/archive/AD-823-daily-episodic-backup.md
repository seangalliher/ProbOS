# AD-823 — Daily episodic backup task

**Status:** Ready to build
**Dependencies:** AD-820 (shutdown_integrity), AD-819 (rebuild-episodic), AD-821 (hnsw config), AD-822 (episodic_health). Builder should dispatch AD-822 first; AD-823 can land in the same session immediately after.
**GH Issue:** #758
**Estimated tests:** 7+ (in a single new file)

## Problem

AD-819 (rebuild-episodic) reconstructs chroma from the ward room journal.
AD-822 (boot health probe) catches corruption before it segfaults the
runtime. Both work *only as long as the ward room and the chroma store
still exist on disk*. The class of failure neither covers:

- The operator deletes `data/` by mistake.
- An external sync (Dropbox / OneDrive) corrupts multiple files at once.
- A disk failure takes out both `chroma.sqlite3` and `ward_room.db` in
  the same event.

AD-823 is the third-line backup: a daily uncompressed tarball snapshot of
chroma's on-disk footprint, kept for a configurable retention window
(default 7 days). This is **not prevention** — AD-822 catches corruption,
AD-819 rebuilds from ward room, AD-823 is what's left when both fail.

## Live-environment constraint (read first)

**Do NOT touch the live operator runtime or any data dir under
`C:\Users\seang\AppData\Local\ProbOS\`.** Tests use `tmp_path`. The
backup task wires into the runtime startup pattern; the test for the
wiring must use a `tmp_path` data dir and a `Runtime` constructed with
test fixtures — NOT the operator's live runtime.

## Codebase facts verified before drafting

```
src/probos/config.py:797              class MemoryConfig(BaseModel):
src/probos/config.py:837-838          hnsw_sync_threshold + hnsw_batch_size (AD-821 fields, append below these)
src/probos/cognitive/episodic.py:858  chromadb.PersistentClient(path=str(db_dir))
src/probos/cognitive/episodic.py:860  collection name "episodes" (hardcoded)
src/probos/__main__.py:454-466        episodic_db = data_path / "episodic.db" (so chroma lives at data_path root)
src/probos/runtime.py:2365            async def _event_log_prune_loop(self) -> None: (canonical loop pattern)
src/probos/runtime.py:2378            async def _journal_prune_loop(self) -> None:
src/probos/startup/infrastructure.py:49 event_prune_task = asyncio.create_task(event_log_prune_loop_fn())
                                       canonical scheduling pattern: startup phase owns the create_task call
                                       and returns the task reference so finalize/cleanup can cancel it.
src/probos/runtime.py:1615            async def start(self) -> None: (top-level runtime boot)
src/probos/runtime.py:1672            event_log_prune_loop_fn=self._event_log_prune_loop, (passed to infra)
src/probos/runtime.py:2041            journal_prune_loop_fn=self._journal_prune_loop, (passed to communication)
src/probos/maintenance/rebuild_episodic.py exists (AD-819 layout precedent for new maintenance module)
```

Critical facts for the design:

1. **ChromaDB on-disk footprint = `chroma.sqlite3` + one or more
   UUID-named subdirectories of `data_dir`.** The UUID subdirs contain
   the HNSW index files (`header.bin`, `data_level0.bin`,
   `length.bin`, `link_lists.bin`, `index_metadata.pickle`). chroma lives
   at the `data_dir` root, NOT under `data_dir/'episodic'/`. The snapshot
   must therefore identify chroma's artifacts within `data_dir` and tar
   only those — NOT the whole `data_dir` (which would include
   `events.db`, `journal.db`, `ward_room.db`, audio cache, attachment
   blobs, etc., and balloon the tarball).
2. **No `.write_lock` file exists.** The original spec assumed one;
   verification shows chroma + EpisodicMemory do not write any such
   sentinel. The backup task uses an **open-probe fallback**: spawn an
   AD-822-style probe in a subprocess to confirm the store is openable
   before snapshotting. If the probe fails, skip the snapshot with a
   reason — taring a corrupted db is worse than no backup.
3. **Background task scheduling pattern**: define an `async def
   _xxx_loop(self)` method on Runtime, pass it to a startup phase
   function which calls `asyncio.create_task(fn())` and returns the task
   in its result dataclass. The simplest landing place for AD-823 is to
   add the new task adjacent to the existing prune loops (next to
   `_event_log_prune_loop` / `_journal_prune_loop`) and create the task
   inline in `runtime.start()` AFTER the existing phase calls, storing
   the reference on `self._episodic_backup_task`. That mirrors the
   refresh / consolidation tasks already on the runtime without
   requiring a new startup phase. (Reviewed: this is the
   smallest-blast-radius change.)

## Solution overview

1. **`src/probos/maintenance/episodic_backup.py`** — pure-function
   snapshot module:
   - Identifies chroma's on-disk artifacts inside `data_dir`.
   - Probes openability via `episodic_health.check_episodic_health` (AD-822).
   - Tars artifacts to `backups_dir/episodic-YYYY-MM-DD.tar`
     (uncompressed; speed > space for local recovery).
   - Skip-if-exists for same-day idempotency.
   - Retention: delete `episodic-*.tar` older than `retain_days`.
   - Returns a `SnapshotResult` dataclass.
2. **`MemoryConfig` fields in `src/probos/config.py`** — add
   `backup_enabled: bool = True` and
   `backup_retain_days: int = Field(default=7, ge=1, le=365)` directly
   below the AD-821 fields.
3. **Background task in `src/probos/runtime.py`** — add an
   `async def _episodic_backup_loop(self) -> None` method next to the
   existing `_journal_prune_loop`. Schedule it from `Runtime.start()` at
   the end of the existing phase orchestration. Hold the task reference
   on `self._episodic_backup_task`.
4. **Honest framing in docstrings** — the module header MUST state that
   AD-823 is the third-line backup after AD-822 and AD-819, not a
   prevention mechanism.

## Section 1 — Create `src/probos/maintenance/episodic_backup.py`

Create a NEW file. Full content:

```python
"""AD-823: daily episodic backup snapshot.

Third-line recovery primitive for the episodic store. Pairs with:

* AD-819 (``rebuild-episodic``): rebuild ChromaDB from surviving ward
  room threads when chroma is corrupt but the ward room is intact.
* AD-822 (``episodic_health``): refuse to boot when chroma is corrupt,
  pointing the operator at AD-819 or AD-823 for recovery.

This module is **not** prevention — corruption that happens between
snapshots is still lost. It's the fallback for the case where both
chroma and the ward room journal are gone (disk failure, accidental
``rm -rf data/``, external sync corruption).

What the snapshot captures:
    * ``data_dir/chroma.sqlite3`` — chroma's metadata store.
    * Every UUID-named subdirectory of ``data_dir`` that contains an
      HNSW marker file (``header.bin``). Those are chroma's per-collection
      index directories.

What the snapshot does NOT capture:
    * ``events.db``, ``journal.db``, ``ward_room.db`` — these have their
      own retention policies (BF-071 prune loops) and are not in scope
      for AD-823.
    * Attachment blobs, audio cache, knowledge store — also out of scope.

Format: uncompressed ``.tar`` (speed > space; local-only recovery store).

File naming: ``backups_dir/episodic-YYYY-MM-DD.tar``. Same-day re-runs are
idempotent (skip-if-exists).

Retention: delete ``episodic-*.tar`` files older than ``retain_days`` days
(default 7) after a successful snapshot. The cleanup runs only on success
so a failed snapshot doesn't take older healthy backups down with it.
"""

from __future__ import annotations

import logging
import re
import tarfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from probos.episodic_health import check_episodic_health

logger = logging.getLogger(__name__)

# Chroma's UUID collection directories use the standard 8-4-4-4-12 hex
# layout. Match defensively rather than parsing chroma internals.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_HNSW_MARKER = "header.bin"
_BACKUP_NAME_RE = re.compile(r"^episodic-(\d{4}-\d{2}-\d{2})\.tar$")


@dataclass(frozen=True)
class SnapshotResult:
    ok: bool
    path: Path | None
    bytes_written: int
    skipped_reason: str | None


def _find_chroma_artifacts(data_dir: Path) -> list[Path]:
    """Return absolute paths of chroma's on-disk footprint inside data_dir.

    Includes ``chroma.sqlite3`` (if present) and every UUID-named
    subdirectory whose contents look like a chroma HNSW collection
    (presence of ``header.bin``).
    """
    artifacts: list[Path] = []
    sqlite_path = data_dir / "chroma.sqlite3"
    if sqlite_path.exists():
        artifacts.append(sqlite_path)
    for child in data_dir.iterdir():
        if not child.is_dir():
            continue
        if not _UUID_RE.match(child.name):
            continue
        if (child / _HNSW_MARKER).exists():
            artifacts.append(child)
    return artifacts


def snapshot_episodic(
    data_dir: Path,
    backups_dir: Path,
    *,
    retain_days: int = 7,
    today: datetime | None = None,
) -> SnapshotResult:
    """Snapshot chroma's on-disk footprint to ``backups_dir``.

    Args:
        data_dir: per-instance data directory (chroma lives at root).
        backups_dir: where to write ``episodic-YYYY-MM-DD.tar``.
        retain_days: delete older snapshots after a successful new one.
            Clamp to ``>=1`` at the caller (config validation enforces).
        today: override the date stamp (testing seam). Defaults to UTC now.

    Returns:
        :class:`SnapshotResult`. ``ok=True`` on either successful new
        snapshot OR same-day skip. ``ok=False`` when the source is
        unopenable or unwritable.
    """
    data_dir = Path(data_dir)
    backups_dir = Path(backups_dir)

    today = today or datetime.now(timezone.utc)
    stamp = today.strftime("%Y-%m-%d")
    target = backups_dir / f"episodic-{stamp}.tar"

    if target.exists():
        logger.info(
            "AD-823: snapshot %s already exists; skipping", target,
        )
        return SnapshotResult(
            ok=True,
            path=target,
            bytes_written=0,
            skipped_reason="already-exists",
        )

    if not data_dir.exists():
        logger.info(
            "AD-823: data_dir %s does not exist; skipping snapshot", data_dir,
        )
        return SnapshotResult(
            ok=True, path=None, bytes_written=0,
            skipped_reason="data-dir-missing",
        )

    # Open-probe fallback (no lock file exists; AD-822 probe gives us a
    # cheap subprocess-isolated openability check). If the store is
    # corrupt, taring it would just snapshot the corruption. Skip with a
    # reason and let AD-822 surface the corruption on next boot.
    health = check_episodic_health(data_dir, timeout_s=30.0)
    if not health.ok:
        logger.warning(
            "AD-823: skipping snapshot — episodic health probe failed: %s",
            health.error,
        )
        return SnapshotResult(
            ok=False, path=None, bytes_written=0,
            skipped_reason=f"health-probe-failed: {health.error}",
        )

    artifacts = _find_chroma_artifacts(data_dir)
    if not artifacts:
        logger.info(
            "AD-823: no chroma artifacts found in %s; nothing to snapshot",
            data_dir,
        )
        return SnapshotResult(
            ok=True, path=None, bytes_written=0,
            skipped_reason="no-artifacts",
        )

    backups_dir.mkdir(parents=True, exist_ok=True)
    tmp_target = target.with_suffix(target.suffix + ".tmp")

    try:
        with tarfile.open(tmp_target, mode="w") as tar:
            for artifact in artifacts:
                # arcname relative to data_dir so restore can untar
                # straight back into data_dir/.
                arcname = artifact.relative_to(data_dir)
                tar.add(str(artifact), arcname=str(arcname))
        tmp_target.replace(target)
    except (OSError, tarfile.TarError) as exc:
        logger.error(
            "AD-823: snapshot write failed for %s: %r", target, exc,
        )
        try:
            tmp_target.unlink(missing_ok=True)
        except OSError:
            pass
        return SnapshotResult(
            ok=False, path=None, bytes_written=0,
            skipped_reason=f"write-failed: {exc!r}",
        )

    bytes_written = target.stat().st_size
    logger.info(
        "AD-823: snapshot %s written (%d bytes, %d artifacts)",
        target, bytes_written, len(artifacts),
    )

    # Retention: only after a successful write. Failures upstream
    # MUST NOT delete older backups.
    _prune_old_snapshots(backups_dir, retain_days=retain_days, today=today)

    return SnapshotResult(
        ok=True, path=target,
        bytes_written=bytes_written, skipped_reason=None,
    )


def _prune_old_snapshots(
    backups_dir: Path,
    *,
    retain_days: int,
    today: datetime,
) -> None:
    """Delete ``episodic-*.tar`` files older than retain_days."""
    cutoff = today.timestamp() - (retain_days * 86400)
    for child in backups_dir.iterdir():
        m = _BACKUP_NAME_RE.match(child.name)
        if not m:
            continue
        try:
            file_date = datetime.strptime(m.group(1), "%Y-%m-%d").replace(
                tzinfo=timezone.utc,
            )
        except ValueError:
            continue
        if file_date.timestamp() < cutoff:
            try:
                child.unlink()
                logger.info(
                    "AD-823: pruned old snapshot %s (older than %d days)",
                    child, retain_days,
                )
            except OSError:
                logger.warning(
                    "AD-823: failed to prune old snapshot %s", child,
                    exc_info=True,
                )
```

Engineering principles to verify:

- `SnapshotResult` is a frozen dataclass.
- All public functions fully typed.
- Exception handling tiering:
  - Tar write `(OSError, tarfile.TarError)` → log error + return non-ok
    (propagation tier — caller needs to know).
  - Tempfile cleanup `OSError` → swallow (cleanup tier).
  - Pruning `OSError` → log warning + continue (log-and-degrade —
    failing to prune one stale file should not block retention of others).
- Log messages always name the file path and the operation.
- No `asyncio.create_subprocess_*`. The only subprocess call is
  transitively via `check_episodic_health`, which already follows the
  rule.

## Section 2 — Add config fields to `src/probos/config.py`

Append to `MemoryConfig` (class definition starts at line 797).
Insert immediately after the AD-821 `hnsw_batch_size` field at line 838:

```
===MODIFY: src/probos/config.py===

===SEARCH===
    hnsw_sync_threshold: int = Field(default=64, ge=4, le=10000)
    hnsw_batch_size: int = Field(default=32, ge=1, le=10000)
    # AD-567b/AD-584c: Salience-weighted recall (rebalanced for QA-trained embeddings)
===REPLACE===
    hnsw_sync_threshold: int = Field(default=64, ge=4, le=10000)
    hnsw_batch_size: int = Field(default=32, ge=1, le=10000)
    # AD-823: daily uncompressed-tar snapshot of chroma's on-disk footprint.
    # Pairs with AD-822 (boot probe) + AD-819 (rebuild from ward room) as the
    # third-line recovery primitive when both chroma and ward room are gone.
    # Default-on because the storage cost is small (current chroma footprint
    # is ~10-50 MB) and the recovery upside is large. Retain 7 days by default;
    # operators on tight disks can lower to 1, paranoid operators can raise.
    backup_enabled: bool = True
    backup_retain_days: int = Field(default=7, ge=1, le=365)
    # AD-567b/AD-584c: Salience-weighted recall (rebalanced for QA-trained embeddings)
===END REPLACE===
```

Do NOT confuse with the existing `backup_enabled: bool = True` on
`InfrastructureConfig` at line 3114 — that's AD-466 (knowledge backup),
different system.

## Section 3 — Add background task to `src/probos/runtime.py`

### 3a. New method next to the existing prune loops

Add a new `_episodic_backup_loop` method immediately AFTER
`_journal_prune_loop` (which ends around line 2391, right before the
`_refresh_roster_bridge` method).

```
===MODIFY: src/probos/runtime.py===

===SEARCH===
    async def _journal_prune_loop(self) -> None:
        """Periodic cognitive journal retention cleanup."""
        cfg = self.config.cognitive_journal
        while True:
            await asyncio.sleep(cfg.prune_interval_seconds)
            try:
                await self.cognitive_journal.prune(
                    retention_days=cfg.retention_days,
                    max_rows=cfg.max_rows,
                )
            except Exception:
                logger.debug("Journal prune failed", exc_info=True)

    def _refresh_roster_bridge(self) -> None:
===REPLACE===
    async def _journal_prune_loop(self) -> None:
        """Periodic cognitive journal retention cleanup."""
        cfg = self.config.cognitive_journal
        while True:
            await asyncio.sleep(cfg.prune_interval_seconds)
            try:
                await self.cognitive_journal.prune(
                    retention_days=cfg.retention_days,
                    max_rows=cfg.max_rows,
                )
            except Exception:
                logger.debug("Journal prune failed", exc_info=True)

    async def _episodic_backup_loop(self) -> None:
        """AD-823: daily uncompressed-tar snapshot of chroma's on-disk footprint.

        First snapshot fires 60s after boot (warmup window so the runtime
        is past startup before any disk pressure from tar). Subsequent
        snapshots fire every 24h. Pairs with AD-822 (boot probe) and
        AD-819 (rebuild from ward room) as the third-line recovery
        primitive — not prevention, just the last line of defense if
        both chroma and the ward room go missing.

        Loop tolerates exceptions so a transient failure (disk full,
        permission flip) does not kill the task forever.
        """
        from probos.maintenance.episodic_backup import snapshot_episodic

        if not self.config.memory.backup_enabled:
            logger.info("AD-823: episodic backup disabled by config; loop exiting")
            return

        data_dir = Path(self._data_dir)
        backups_dir = data_dir / "backups" / "episodic"
        retain_days = self.config.memory.backup_retain_days

        # Warmup: 60s after start so we don't compete with boot I/O.
        await asyncio.sleep(60.0)
        while True:
            try:
                result = snapshot_episodic(
                    data_dir, backups_dir, retain_days=retain_days,
                )
                if result.ok:
                    logger.info(
                        "AD-823: snapshot tick ok path=%s bytes=%d skipped=%s",
                        result.path, result.bytes_written, result.skipped_reason,
                    )
                else:
                    logger.warning(
                        "AD-823: snapshot tick failed reason=%s",
                        result.skipped_reason,
                    )
            except Exception:
                logger.warning("AD-823: snapshot tick raised", exc_info=True)
            await asyncio.sleep(86400.0)  # 24h

    def _refresh_roster_bridge(self) -> None:
===END REPLACE===
```

### 3b. Schedule the task and store the reference

Locate `async def start(self) -> None:` at line 1615. After the last
existing startup phase call in `start()` (Phase 7 / communication-phase
results assignment), add the task creation. Use this SEARCH/REPLACE
which must match a stable point — the start of the
`communication`-phase line is fragile, so anchor on the existing
`journal_prune_loop_fn=self._journal_prune_loop,` parameter passed to
`init_communication`. The communication phase's startup function creates
its own journal-prune task; we just need to confirm the backup task is
also scheduled. Since AD-823 is NOT a startup-phase concern (no other
service depends on it, it has no dependencies on other services), the
simplest place is **inline at the end of `start()`** before any final
status logging.

Builder: read `runtime.py` lines 1615 through the END of `start()` to
find the actual end-of-method anchor. Add this block immediately before
the method returns / before the last log line:

```python
        # AD-823: schedule the daily episodic backup loop. Task reference
        # stored on self so cancellation in shutdown can reach it; this
        # avoids the fire-and-forget anti-pattern called out in the
        # standing engineering principles.
        self._episodic_backup_task = asyncio.create_task(
            self._episodic_backup_loop()
        )
```

If `self._episodic_backup_task` is not already declared as a class
attribute, declare it as `self._episodic_backup_task: asyncio.Task[None] | None = None`
in `Runtime.__init__` (grep for the existing `self._tcm` or other Task
attribute declarations to find the right place). Cancellation in
`stop()` / `shutdown` is NICE-TO-HAVE, not required for this AD —
asyncio will GC the task on event-loop teardown. Do NOT add a new
`stop()` cancellation path in this prompt; that's a follow-up AD if
needed.

If `_data_dir` is not directly accessible (some Runtime versions name
it `data_dir`), grep `self._data_dir` vs `self.data_dir` in runtime.py
and use whichever exists.

## Section 4 — Tests

Create a NEW file at `tests/test_ad823_episodic_backup.py` with at least
**7 tests**. Required cases:

1. `test_snapshot_creates_tar_with_expected_artifacts` — `tmp_path`,
   build a real chroma store (`chromadb.PersistentClient` +
   `get_or_create_collection("episodes")` + add rows). Call
   `snapshot_episodic(tmp_path, backups_dir)`. Assert tarfile exists,
   `result.ok is True`, `result.bytes_written > 0`. Open the tar and
   assert it contains `chroma.sqlite3` AND at least one UUID directory
   entry containing `header.bin`.
2. `test_same_day_snapshot_skipped` — call `snapshot_episodic` twice in
   the same day (pass `today=` to keep stamps identical). Assert second
   call returns `ok=True` with `skipped_reason="already-exists"` and
   does not rewrite the file (compare `stat().st_mtime`).
3. `test_retention_deletes_old_files_keeps_new` — populate `backups_dir`
   with `episodic-2026-04-01.tar`, `episodic-2026-04-15.tar`,
   `episodic-2026-05-19.tar`. Call `snapshot_episodic(..., retain_days=7,
   today=datetime(2026, 5, 22, tzinfo=timezone.utc))`. Assert
   `episodic-2026-04-01.tar` and `episodic-2026-04-15.tar` are deleted,
   `episodic-2026-05-19.tar` is preserved.
4. `test_open_probe_failure_skips_snapshot` — write garbage to
   `tmp_path/chroma.sqlite3` to make the AD-822 probe fail. Call
   `snapshot_episodic`. Assert `result.ok is False`, `result.path is
   None`, `result.skipped_reason` contains `health-probe-failed`. Assert
   no tar was written.
5. `test_no_artifacts_returns_skip_reason` — empty `tmp_path` with no
   chroma files. Call `snapshot_episodic`. Assert `result.ok is True`,
   `result.skipped_reason == "no-artifacts"`.
6. `test_config_validation_retain_days_bounds` — assert that
   `MemoryConfig(backup_retain_days=0)` raises pydantic `ValidationError`,
   that `MemoryConfig(backup_retain_days=400)` raises, and that
   `MemoryConfig(backup_retain_days=7)` accepts.
7. `test_backup_disabled_loop_exits` — construct a minimal test fixture
   for `Runtime._episodic_backup_loop` (build a real `SystemConfig`
   with `memory.backup_enabled=False`; do NOT use MagicMock for config
   per the user-memory "MagicMock auto-attribute trap" rule). Run the
   loop coroutine via `asyncio.wait_for(loop, timeout=2.0)` — it should
   exit cleanly without waiting for the 60s warmup.

Test discipline reminders:

- All tests use `tmp_path` — NO test may touch
  `C:\Users\seang\AppData\Local\ProbOS\` or `d:/ProbOS/data/`.
- Real `SystemConfig` / `MemoryConfig` instances, not MagicMock (BF-287
  lesson).
- `pytest.importorskip("chromadb")` at the top of tests 1, 2, 5 that
  build real chroma stores. Tests 3, 4, 6, 7 do not need chroma.
- Run with `pytest tests/test_ad823_episodic_backup.py -v -n 0 --timeout=60`.
- Do NOT add real-time sleeps. Use `today=` parameter for date control;
  use `monkeypatch` on `asyncio.sleep` if you need to test the loop's
  warmup behavior without waiting.

## Section 5 — Boundaries (do not change)

- Do NOT change `src/probos/cognitive/episodic.py`. The backup module
  only reads chroma's on-disk artifacts; it does NOT use the
  `EpisodicMemory` runtime object.
- Do NOT change `src/probos/maintenance/rebuild_episodic.py`. AD-823 is
  independent of AD-819.
- Do NOT add a CLI command (`probos snapshot-episodic` etc). Wait for
  operator demand; the scheduled task covers the recovery use case.
- Do NOT add cancellation in `Runtime.stop()` / shutdown path. That is a
  separate AD if needed; asyncio GC handles it for now and the loop
  awaits `asyncio.sleep(86400)` between ticks (cheap to abandon).
- Do NOT add a `restore-episodic` command. The recovery story is
  `tar -xf episodic-YYYY-MM-DD.tar -C data/` — operator-driven, no code
  required for this AD.
- Do NOT change `InfrastructureConfig.backup_enabled` (AD-466). The new
  field lives on `MemoryConfig`.
- Do NOT touch the operator's live data dir under
  `C:\Users\seang\AppData\Local\ProbOS\` at any point.

## Tracking

After Builder completes:

- `PROGRESS.md`: add `AD-823 — Daily episodic backup task` with commit
  SHA + test count.
- `docs/development/roadmap.md`: tick #758 closed.
- Do NOT append to `DECISIONS.md` unless explicitly requested.

## Acceptance criteria

- [ ] All 7+ tests pass with `pytest tests/test_ad823_episodic_backup.py -v -n 0 --timeout=60`.
- [ ] Full focused gate green:
      `pytest tests/test_ad819_rebuild_episodic.py tests/test_ad820_shutdown_integrity.py tests/test_ad821_hnsw_sync.py tests/test_ad822_episodic_health.py tests/test_ad823_episodic_backup.py -v -n 0 --timeout=60`.
- [ ] Full parallel gate green:
      `pytest tests/ -q -n 4 --dist=loadfile --timeout=60`.
- [ ] Boot the runtime against a `tmp_path` data dir; observe in logs
      that `AD-823: snapshot tick ok ...` fires within 60s of boot (or
      manually shorten the warmup in a one-off smoke).
- [ ] Tarfile is restorable: `tar -tf episodic-YYYY-MM-DD.tar` lists
      `chroma.sqlite3` and at least one UUID dir entry.
- [ ] Background task is referenced on `self._episodic_backup_task`
      (NOT fire-and-forget per async hygiene rule).
- [ ] No `asyncio.create_subprocess_*` introduced.
- [ ] No `chromadb` import added to runtime.py or config.py — only in
      `maintenance/episodic_backup.py` (transitively through AD-822 +
      tests).
- [ ] Cross-platform: tarfile + Path APIs throughout; no shell calls.
- [ ] Verify all changes comply with the Engineering Principles in
      `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-22)

```
grep -n "class MemoryConfig" src/probos/config.py
  797: class MemoryConfig(BaseModel):

grep -n "hnsw_batch_size" src/probos/config.py
  838:    hnsw_batch_size: int = Field(default=32, ge=1, le=10000)

grep -n "class InfrastructureConfig" src/probos/config.py
  ~3110: class InfrastructureConfig(BaseModel):
  3114:     backup_enabled: bool = True   # (AD-466 — different system, do not collide)

grep -n "async def _journal_prune_loop" src/probos/runtime.py
  2378: async def _journal_prune_loop(self) -> None:

grep -n "async def _event_log_prune_loop" src/probos/runtime.py
  2365: async def _event_log_prune_loop(self) -> None:

grep -n "async def start" src/probos/runtime.py
  1615: async def start(self) -> None:

grep -n "event_prune_task = asyncio.create_task" src/probos/startup/infrastructure.py
  49:     event_prune_task = asyncio.create_task(event_log_prune_loop_fn())

grep -n "PersistentClient" src/probos/cognitive/episodic.py
  858:    self._client = chromadb.PersistentClient(path=str(db_dir))

grep -n 'name="episodes"' src/probos/cognitive/episodic.py
  861:        name="episodes",

# Path confirmation: chroma lives at data_dir ROOT
grep -n 'episodic_db = data_path' src/probos/__main__.py
  454:    episodic_db = data_path / "episodic.db"
# -> db_dir = Path(db_path).parent = data_path. No "episodic/" subdir.

# Confirmed absent (new files):
file_search src/probos/maintenance/episodic_backup.py -> not found
file_search tests/test_ad823_episodic_backup.py       -> not found

# Confirmed absent on disk: no `.write_lock` sentinel under data/.
# Open-probe fallback is the right approach.
```
