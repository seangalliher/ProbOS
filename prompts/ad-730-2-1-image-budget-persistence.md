# AD-730-2-1 — Persist `image_budget_tracker` across restart

**Wave:** 161
**Closes:** #656
**Status:** ready to build
**Dependencies:** AD-730-2 (Wave 160 — `ImagePolicyEnforcer.check_budget` and `runtime.image_budget_tracker` in place).
**Estimated tests:** +5 pytest, 0 vitest.
**Scope tag:** Server-only. Pure internal change. No new pip deps. Apache 2.0.

---

## Problem

AD-730-2 ships the per-Captain 24h image budget as in-memory state at `runtime.image_budget_tracker: dict[str, deque[(timestamp, count)]]` (`src/probos/runtime.py:484`). Restart wipes the deque, so the Captain's 24h spend resets on every runtime boot — defeating the rate-limit's intent.

This AD persists the tracker to a JSON sidecar (`data/image_budget.json`), loaded on runtime startup and rewritten on every append. The persistence layer is intentionally simple — single-process write, fsync best-effort, log-and-degrade if disk I/O fails.

---

## Solution overview

1. New module `src/probos/attachments/image_budget_store.py` exposing two module-level functions: `load(path: Path) -> dict[str, deque]` and `save(path: Path, tracker: dict[str, deque]) -> None`. JSON format: `{captain_id: [[timestamp, count], ...]}`.
2. `runtime.py` boot path loads from `data/image_budget.json` (or the path from a new `AttachmentsConfig` field) if present, falling back to empty dict.
3. `ImagePolicyEnforcer.check_budget` writes after every successful `q.append((now, image_count))` AND after every `q.popleft()` cleanup. Writes are Tier-2 (log-and-degrade) — never block the DM.
4. Path is configurable via `AttachmentsConfig.image_budget_path: str | None = None`. When None, defaults to `data/image_budget.json` resolved against `runtime.config.data_dir` (the existing convention).

---

## Section 1 — New module `src/probos/attachments/image_budget_store.py`

```python
"""AD-730-2-1: persistence for the AD-730-2 per-Captain daily image budget.

Format: ``{captain_id: [[timestamp, count], ...]}``. Loaded on runtime
startup, saved on every mutation by ``ImagePolicyEnforcer.check_budget``.
Tier-2 throughout — disk I/O failure logs and degrades; the in-memory
tracker remains authoritative for the live process.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections import deque
from pathlib import Path

logger = logging.getLogger(__name__)


def load(path: Path) -> dict[str, deque]:
    """Load tracker from JSON sidecar. Missing/corrupt file returns {}.

    Each loaded captain's deque is reconstructed in chronological order;
    expired entries are NOT pruned here — that's the gate's job at
    check-budget time (one window-cutoff pass per call).
    """
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception:
        logger.warning(
            "AD-730-2-1: failed to load %s; starting with empty budget tracker",
            path, exc_info=True,
        )
        return {}
    if not isinstance(data, dict):
        logger.warning(
            "AD-730-2-1: %s contained non-dict root %r; starting empty",
            path, type(data).__name__,
        )
        return {}
    out: dict[str, deque] = {}
    for captain_id, entries in data.items():
        if not isinstance(captain_id, str) or not isinstance(entries, list):
            continue
        q: deque = deque()
        for entry in entries:
            if (
                isinstance(entry, list) and len(entry) == 2
                and isinstance(entry[0], (int, float))
                and isinstance(entry[1], int)
            ):
                q.append((float(entry[0]), int(entry[1])))
        out[captain_id] = q
    return out


def save(path: Path, tracker: dict[str, deque]) -> None:
    """Atomically write tracker to ``path``. Tier-2 — log-and-degrade.

    Writes to a sibling temp file then ``os.replace`` for atomicity.
    Empty captains (deque length 0) are skipped to keep the file compact.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            captain_id: [[ts, n] for (ts, n) in entries]
            for captain_id, entries in tracker.items()
            if entries  # skip empty deques
        }
        # Atomic write: temp file in same dir + os.replace.
        fd, tmp_path = tempfile.mkstemp(
            prefix=path.name + ".",
            suffix=".tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, separators=(",", ":"))
            os.replace(tmp_path, path)
        except Exception:
            # Clean up the temp file on failure so we don't leak.
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            raise
    except Exception:
        logger.warning(
            "AD-730-2-1: failed to persist budget tracker to %s; "
            "in-memory tracker remains authoritative for this process",
            path, exc_info=True,
        )
```

---

## Section 2 — Runtime boot wiring (`src/probos/runtime.py`)

Find the existing initialization line:

```
        self.image_budget_tracker: dict[str, "_deque"] = {}
```

Replace with:

```python
        # AD-730-2-1: load the per-Captain 24h image budget from disk if a
        # sidecar exists; otherwise start empty. Tier-2 — load failure
        # degrades to empty (logged in image_budget_store.load).
        from probos.attachments.image_budget_store import load as _ibs_load
        _ibs_cfg = getattr(self.config, "attachments", None)
        _ibs_path_str = getattr(_ibs_cfg, "image_budget_path", None) if _ibs_cfg else None
        if _ibs_path_str:
            self._image_budget_path = Path(_ibs_path_str)
        else:
            self._image_budget_path = Path(self.config.data_dir) / "image_budget.json"
        self.image_budget_tracker: dict[str, "_deque"] = _ibs_load(self._image_budget_path)
```

Ensure `from pathlib import Path` is present at module top (verify via grep first — `runtime.py` likely already imports it).

---

## Section 3 — Enforcer save hook (`src/probos/attachments/image_policy.py`)

In `ImagePolicyEnforcer.check_budget`, after the successful `q.append((now, image_count))` line and after the `q.popleft()` loop, persist. Wrap in Tier-2 — never propagate.

Find:

```python
            q.append((now, image_count))
        except ImagePolicyError:
            raise
        except Exception:
            logger.warning(
                "AD-730-2: budget tracker raised for captain=%s; proceeding without gate",
                captain_id, exc_info=True,
            )
```

Replace with:

```python
            q.append((now, image_count))
            self._persist_tracker(tracker)
        except ImagePolicyError:
            raise
        except Exception:
            logger.warning(
                "AD-730-2: budget tracker raised for captain=%s; proceeding without gate",
                captain_id, exc_info=True,
            )
```

Add the new helper method to `ImagePolicyEnforcer` (just below `check_budget`):

```python
    def _persist_tracker(self, tracker: dict) -> None:
        """AD-730-2-1: persist the budget tracker to disk. Tier-2 — never raises."""
        path = getattr(self.runtime, "_image_budget_path", None)
        if path is None:
            return
        try:
            from probos.attachments.image_budget_store import save as _ibs_save
            _ibs_save(path, tracker)
        except Exception:
            logger.warning(
                "AD-730-2-1: budget persistence raised unexpectedly; "
                "in-memory tracker remains authoritative",
                exc_info=True,
            )
```

Note: we also want to persist after the `while q and q[0][0] < cutoff: q.popleft()` prune, because pruning is a state change even when no new image is added. Add the persist call inside `check_budget` after the prune loop but only when the loop actually removed something — track with a local `pruned: bool` flag.

Find:

```python
            q = tracker.setdefault(captain_id, deque())
            while q and q[0][0] < cutoff:
                q.popleft()
            used = sum(n for _, n in q)
```

Replace with:

```python
            q = tracker.setdefault(captain_id, deque())
            pruned = False
            while q and q[0][0] < cutoff:
                q.popleft()
                pruned = True
            if pruned:
                self._persist_tracker(tracker)
            used = sum(n for _, n in q)
```

---

## Section 4 — Config field (`src/probos/config.py`)

Find `AttachmentsConfig`. Add field with sensible default:

```python
    image_budget_path: str | None = Field(
        default=None,
        description=(
            "AD-730-2-1: filesystem path for the per-Captain image-budget "
            "JSON sidecar. When None, defaults to "
            "``<runtime.config.data_dir>/image_budget.json``."
        ),
    )
```

---

## Section 5 — Tests `tests/test_ad730_2_1_image_budget_persistence.py`

Five tests, all using `tmp_path` fixture for isolation (no shared state).

1. **`test_load_missing_file_returns_empty`** — `load(tmp_path / "missing.json")` returns `{}`, no exception, no file created.
2. **`test_save_then_load_roundtrip`** — populate a `dict[str, deque]` with one Captain and three entries, call `save`, call `load` on the same path, assert the deques compare equal (entry-by-entry).
3. **`test_save_skips_empty_deques`** — Captain A with 2 entries, Captain B with empty deque; after save, the file's JSON top-level dict contains only Captain A.
4. **`test_corrupt_file_loads_empty`** — write `"not json"` to the path, `load` returns `{}` and logs a WARNING (capture via `caplog`).
5. **`test_enforcer_persists_on_append_and_prune`** — construct a `_FakeRuntime` with `_image_budget_path = tmp_path / "ib.json"` and `image_budget_tracker = {}`; construct `ImagePolicyEnforcer` with `cfg.daily_image_budget_per_captain = 50`; call `check_budget("captain_x", 1)`; assert the sidecar file exists and contains one entry for `"captain_x"`. Then monkey-patch `time.time` to return a value 25h in the future, call `check_budget("captain_x", 1)` again, and assert the prior entry has been pruned AND the file has been rewritten (mtime changed OR content updated).

Use `_FakeRuntime` stub class — do not boot a real `ProbOSRuntime` for these tests (boundary unit tests).

---

## Standing rules (must comply)

- **BF-274** — Use single `replace_string_in_file` for each of the two adjacent edits in Section 3 (the `q.append` block and the `q = tracker.setdefault` block). Don't combine into a `multi_replace_string_in_file` call.
- **BF-280** — No `asyncio.create_subprocess_*` introduced. (N/A; this AD is pure stdlib + JSON.)
- **BF-282** — No subprocess output captured via stdout. (N/A.)
- **BF-286** — N/A; no subprocess test scaffolding.
- **AD-731 invariant** — Image attachment SHA-256 refs still flow through `AttachmentStore`. This AD touches the BUDGET tracker only, not the attachment payload path.
- **AD-738b / UI gate** — N/A (no `ui/src/**` files modified).
- **AD-722c-3 forward-marker style** — technical triggers only (applied below).
- **No emoji.** ASCII log messages only.
- **Three-tier exceptions** — disk I/O failures are Tier-2 (log-and-degrade). The in-memory tracker is the live authority; the sidecar is best-effort durability.

---

## Forward markers (file in `docs/development/roadmap.md`)

- **AD-730-2-1a** — Throttle persistence writes (batch every N appends or every M seconds, whichever first). **Trigger:** observed write amplification on a heavy-image session exceeds 1 write per DM AND total file size > 64 KB.
- **AD-730-2-1b** — Migrate to AttachmentStore sidecar format (single ChromaDB collection) when commercial overlay swaps the storage backend. **Trigger:** the `ConnectionFactory` Protocol from AD-697/698 lands a non-SQLite backend AND a second runtime-state-with-disk-sidecar AD (e.g. AD-721d-4) is also shipped.

---

## Acceptance criteria

1. `src/probos/attachments/image_budget_store.py` exists with `load` and `save` functions per Section 1.
2. `runtime.py` loads from the configured path on boot; defaults to `<data_dir>/image_budget.json`.
3. `ImagePolicyEnforcer.check_budget` persists on append AND on prune.
4. `AttachmentsConfig.image_budget_path: str | None = None` field added with `Field(default=None, description=...)`.
5. 5 new pytest tests pass (`tests/test_ad730_2_1_image_budget_persistence.py`).
6. `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile` green (HEAD test count + 5).
7. Existing AD-730-2 tests (`tests/test_ad730_2_image_policy.py`) still pass — Section 5 should NOT modify them.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Tracking

- **PROGRESS.md** — Wave 161 in-flight block; close #656.
- **DECISIONS.md** — AD-730-2-1 entry.
- **docs/development/roadmap.md** — forward markers per above.

---

## Verified Against Codebase (2026-05-15)

```
src/probos/attachments/image_policy.py:
  11:    on ``runtime.image_budget_tracker`` (allocated in runtime startup).
  138:        budget = int(getattr(self.cfg, "daily_image_budget_per_captain", 0))
  145:        tracker = getattr(self.runtime, "image_budget_tracker", None)
  148:                "AD-730-2: runtime.image_budget_tracker missing; budget gate disabled",
  167:            q = tracker.setdefault(captain_id, deque())
  168:            while q and q[0][0] < cutoff:
  169:                q.popleft()
  170:            used = sum(n for _, n in q)
  186:            q.append((now, image_count))

src/probos/runtime.py:
  484:        self.image_budget_tracker: dict[str, "_deque"] = {}

src/probos/attachments/:
  __init__.py, filesystem_store.py, image_policy.py, mime.py, store.py
  (no image_budget_store.py — this AD creates it)
```
