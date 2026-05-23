# BF-288 — `probos rebuild-episodic` must reset AD-820 shutdown marker on success

**Issue:** https://github.com/seangalliher/ProbOS/issues/761
**Status:** Ready to build
**Dependencies:** none (AD-819 + AD-820 already shipped)
**Estimated tests:** +2 in `tests/test_ad819_rebuild_episodic.py`
**Bundling:** Ships as its own commit. Pair commit is BF-289 (`prompts/bf-288-289/bf-289-chunk-migration-upsert.md`). Independent files, independent test files — two commits, clean bisect.

## Problem

AD-819's `probos rebuild-episodic` reconstructs ChromaDB from the surviving `ward_room.db` after a #750-class corruption + reset event. AD-820's `shutdown_status.json` integrity marker refuses to boot when the previous shutdown recorded `consolidation_result=failed`.

These two interact badly today: after a successful rebuild, the marker still says `failed`, so the next `probos serve` keeps refusing to boot. Reproduced on 2026-05-22 — rebuild restored 11,539 episodes, next serve still blocked, only workaround was to delete `shutdown_status.json` manually.

The rebuild SUCCEEDING IS the signal that recovery is complete. The marker must reflect that.

## Solution

After a successful (non-dry-run, errors-free) rebuild, write a fresh `shutdown_status.json` via `shutdown_integrity.mark_clean_shutdown(data_dir, consolidation_result="rebuilt", note="...")`. On failure or dry-run, leave the marker untouched so the operator still sees AD-820's warning and can retry or fall back to backup.

### Why the CLI handler, not `rebuild_from_wardroom`

`src/probos/maintenance/rebuild_episodic.py:175` `rebuild_from_wardroom()` has no `data_dir` parameter today and intentionally has no filesystem coupling beyond `wardroom_db`. The CLI handler `_cmd_rebuild_episodic` in `src/probos/__main__.py:1200` already owns `data_dir` (line 1219). The marker reset is a CLI-level "I finished a recovery action" concern, not a rebuild-mechanics concern. Keeps the maintenance module pure and unit-testable without filesystem mocking.

## Section 0: ConsolidationResult literal

`ConsolidationResult` is currently `Literal["full", "partial", "skipped", "failed"]` (`src/probos/shutdown_integrity.py:42`). Extend with `"rebuilt"` so forensics can distinguish a normal clean shutdown from a recovery rebuild.

### File: `src/probos/shutdown_integrity.py`

```
### SEARCH
ShutdownStatus = Literal["clean", "partial", "aborted", "unknown"]
ConsolidationResult = Literal["full", "partial", "skipped", "failed"]

STATUS_FILENAME = "shutdown_status.json"
### REPLACE
ShutdownStatus = Literal["clean", "partial", "aborted", "unknown"]
ConsolidationResult = Literal["full", "partial", "skipped", "failed", "rebuilt"]

STATUS_FILENAME = "shutdown_status.json"
### END REPLACE
```

Note: `mark_clean_shutdown` (line 125) already branches `status="clean" if consolidation_result == "full" else "partial"` (line 134). With `"rebuilt"`, the status will be `"partial"`, which is the right semantic — recovery happened, the data plane is now consistent, but it wasn't a normal full consolidation. AD-820's boot check (`check_previous_shutdown`) accepts `clean` and `partial` as non-blocking; `failed` is the one that blocks. Confirmed by reading lines 65–75 of `shutdown_integrity.py` — the boot-blocking condition is `consolidation_result == "failed"`, not the `status` field.

## Section 1: CLI handler resets the marker on success

### File: `src/probos/__main__.py`

The current end of `_run()` inside `_cmd_rebuild_episodic` is:

```python
        console.print(render_report(report))
        return 0 if not report.errors else 1
```

(near line 1313). Replace with a version that calls `mark_clean_shutdown` when the rebuild produced episodes and had no errors.

```
### SEARCH
            report = await rebuild_from_wardroom(
                wardroom_db=wardroom_db,
                store_episode=_store,
                existing_episode_ids=existing_ids,
                since_ts=since_ts,
                dry_run=False,
            )
        finally:
            await em.stop()

        console.print(render_report(report))
        return 0 if not report.errors else 1

    return _asyncio.run(_run())
### REPLACE
            report = await rebuild_from_wardroom(
                wardroom_db=wardroom_db,
                store_episode=_store,
                existing_episode_ids=existing_ids,
                since_ts=since_ts,
                dry_run=False,
            )
        finally:
            await em.stop()

        console.print(render_report(report))

        # BF-288: a successful rebuild IS the recovery signal. Reset the
        # AD-820 marker so the next `probos serve` is not blocked by the
        # `consolidation_result=failed` left over from the crash that
        # forced the rebuild. On failure (errors present), leave the
        # marker untouched so the operator still sees AD-820's warning.
        if not report.errors and report.episodes_written > 0:
            try:
                from probos.shutdown_integrity import mark_clean_shutdown
                mark_clean_shutdown(
                    data_dir,
                    consolidation_result="rebuilt",
                    note=(
                        f"AD-819 rebuild from {report.source}: "
                        f"{report.episodes_written} episodes written"
                    ),
                )
                console.print(
                    "[green]✓[/green] AD-820 shutdown marker reset "
                    "(consolidation_result=rebuilt)"
                )
            except Exception:
                # Marker write failure is non-fatal — operator can re-run
                # or delete the marker manually. Log via Console so the
                # signal isn't lost in the rebuild summary.
                console.print(
                    "[yellow]![/yellow] Could not reset shutdown_status.json "
                    "(rebuild itself succeeded; you may need to delete "
                    "the marker manually before the next boot)."
                )

        return 0 if not report.errors else 1

    return _asyncio.run(_run())
### END REPLACE
```

Note: the dry-run path (around line 1262) is intentionally NOT touched. Dry runs don't write episodes; they shouldn't claim recovery.

## Section 2: Tests

### File: `tests/test_ad819_rebuild_episodic.py`

Add a new class `TestShutdownMarkerReset` at the end of the file. The existing tests exercise `rebuild_from_wardroom` directly with a stub `store_episode`; these new tests exercise `_cmd_rebuild_episodic` end-to-end against a temp `data_dir`, since the marker reset is a CLI-handler concern.

Pattern follows the existing fixture (`_build_wardroom_fixture`). The CLI handler needs `args.data_dir` and `args.config` to be set; pass an `argparse.Namespace` with the minimal fields. The handler also calls `_load_config_with_fallback` for `cfg.memory.*` — supply `config=None` so it uses the default fallback.

```python
class TestShutdownMarkerReset:
    """BF-288: successful rebuild must reset AD-820 shutdown_status.json."""

    def test_successful_rebuild_resets_marker(self, tmp_path, monkeypatch):
        """After a successful rebuild, marker should reflect consolidation_result='rebuilt'."""
        import argparse
        import json as _json
        from probos.__main__ import _cmd_rebuild_episodic
        from probos.shutdown_integrity import mark_dirty_shutdown, STATUS_FILENAME

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _build_wardroom_fixture(data_dir / "ward_room.db")

        # Simulate the pre-rebuild state: previous shutdown was dirty.
        mark_dirty_shutdown(
            data_dir,
            consolidation_result="failed",
            note="simulated #750 crash",
        )
        marker = data_dir / STATUS_FILENAME
        assert _json.loads(marker.read_text())["consolidation_result"] == "failed"

        args = argparse.Namespace(
            data_dir=data_dir,
            config=None,
            since=None,
            dry_run=False,
        )
        rc = _cmd_rebuild_episodic(args)
        assert rc == 0

        payload = _json.loads(marker.read_text())
        assert payload["consolidation_result"] == "rebuilt"
        # status flips from "partial" (dirty) — note that mark_clean_shutdown
        # writes status="partial" for any consolidation_result != "full",
        # which is correct: recovery happened, data plane is consistent,
        # but it was not a normal full consolidation. AD-820's boot gate
        # only blocks on consolidation_result=="failed", so "rebuilt" boots.
        assert payload["status"] in ("clean", "partial")
        assert "rebuild" in payload.get("note", "").lower()

    def test_dry_run_does_not_touch_marker(self, tmp_path):
        """Dry-run must NOT reset the marker (no real recovery happened)."""
        import argparse
        import json as _json
        from probos.__main__ import _cmd_rebuild_episodic
        from probos.shutdown_integrity import mark_dirty_shutdown, STATUS_FILENAME

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _build_wardroom_fixture(data_dir / "ward_room.db")
        mark_dirty_shutdown(
            data_dir,
            consolidation_result="failed",
            note="simulated #750 crash",
        )

        args = argparse.Namespace(
            data_dir=data_dir,
            config=None,
            since=None,
            dry_run=True,
        )
        rc = _cmd_rebuild_episodic(args)
        assert rc == 0

        payload = _json.loads((data_dir / STATUS_FILENAME).read_text())
        assert payload["consolidation_result"] == "failed"
```

If the existing fixture only seeds threads + posts (which it does — confirmed at lines 70–95 of the test file), the rebuild should write a small positive number of episodes, satisfying `report.episodes_written > 0`. If the in-memory `EpisodicMemory` start-up in the CLI is too heavyweight for the test environment (ChromaDB cold-start), use `monkeypatch` to swap `EpisodicMemory.store` for a coroutine that just appends to a list — but try the direct path first.

If ChromaDB cold-start is unavoidable in the test environment, an acceptable alternative is to split: keep the `test_dry_run_does_not_touch_marker` test as-is (cheap, no ChromaDB) and replace the first test with one that monkeypatches `rebuild_from_wardroom` to return a synthetic `RebuildReport(source="wardroom", dry_run=False, rows_scanned=10, episodes_written=10, errors=[])`. Both shapes prove the BF.

## What This Does NOT Change

- `rebuild_from_wardroom` signature stays unchanged. No `data_dir` parameter added.
- AD-820's boot-time check (`check_previous_shutdown`) untouched. Existing rules still apply.
- `mark_clean_shutdown` / `mark_dirty_shutdown` callers in the shutdown path untouched.
- Dry-run semantics unchanged.

## Tracking

- `PROGRESS.md` — add BF-288 entry under the open-bug list, then move to closed in the same commit if landing here.
- `docs/development/roadmap.md` Bug Tracker — add row.
- Do NOT touch `DECISIONS.md` (this is a bugfix, not an architectural decision).

## Acceptance Criteria

- New `Literal["rebuilt"]` accepted by `ConsolidationResult`.
- `_cmd_rebuild_episodic` writes `shutdown_status.json` with `consolidation_result="rebuilt"` after a successful rebuild.
- Dry-run path leaves the marker untouched.
- Failed-rebuild path (any `report.errors`) leaves the marker untouched.
- Marker write failure inside the handler is non-fatal and logs via Console.
- Both new tests pass.
- Full test suite green: `D:\ProbOS\.venv\Scripts\pytest.exe -n 0 --timeout=60 tests/test_ad819_rebuild_episodic.py`
- Then: `D:\ProbOS\.venv\Scripts\pytest.exe -q -n 4 --dist=loadfile` returns the same pre/post test count delta as the new tests (+2).
- Verify all changes comply with Engineering Principles in `.github/copilot-instructions.md`.

## Standing Constraint

- Do NOT touch the live runtime (PID at `C:\Users\seang\AppData\Local\ProbOS\data\probos.pid`).
- Do NOT touch anything under `C:\Users\seang\AppData\Local\ProbOS\`.

## Commit Message

```
BF-288: probos rebuild-episodic resets AD-820 shutdown marker on success

Successful rebuild now writes shutdown_status.json with
consolidation_result="rebuilt" so the next `probos serve` is not blocked
by AD-820's boot gate. Dry-run and failed-rebuild paths leave the marker
untouched, preserving the operator-visible warning.

Closes #761
```

## Verified Against Codebase (2026-05-22)

```
grep -n "def mark_clean_shutdown" src/probos/shutdown_integrity.py
  125: def mark_clean_shutdown(

grep -n "ConsolidationResult = " src/probos/shutdown_integrity.py
  42: ConsolidationResult = Literal["full", "partial", "skipped", "failed"]

grep -n "def _cmd_rebuild_episodic" src/probos/__main__.py
  1200: def _cmd_rebuild_episodic(args: argparse.Namespace) -> int:

grep -n "data_dir = " src/probos/__main__.py | head -3
  1219:    data_dir = (getattr(args, "data_dir", None) or _default_data_dir()).resolve()

grep -n "return 0 if not report.errors" src/probos/__main__.py
  1280:            return 0
  1313:        return 0 if not report.errors else 1

grep -n "def rebuild_from_wardroom" src/probos/maintenance/rebuild_episodic.py
  175: async def rebuild_from_wardroom(

ls tests/test_ad819_rebuild_episodic.py
  exists; contains _build_wardroom_fixture (line 25) and existing test classes
```
