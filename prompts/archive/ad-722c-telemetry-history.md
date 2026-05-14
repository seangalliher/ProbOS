# AD-722c — Avatar telemetry history (JSONL, queryable)

**AD:** AD-722c. **GH issue closed:** [#569](https://github.com/seangalliher/ProbOS/issues/569).
**Parent ADs:** AD-722 (telemetry channel, Wave 138), AD-722b (WS push, Wave 142), AD-722a-5 (in-memory divergence ring buffer, Wave 145).
**Wave:** 159. **Estimated tests:** +6 pytest. **Estimated wall-time:** ~2h. **Risk:** LOW (additive, log-and-degrade).

---

## Solution Overview

Today `AvatarTelemetrySnapshot` (`src/probos/avatars/telemetry.py:345`) is point-in-time — built on demand, broadcast over WS, never persisted. Analytics surfaces (Captain's "Counselor's emotion-divergence rate over 7 days") have no time-series substrate. AD-722a-5 added an in-memory 100-entry ring buffer for divergence events, but it dies on restart and only covers divergence rows — not full snapshots.

This AD adds **append-only JSONL persistence** (one file per agent under `data/avatar_telemetry/<agent_id>.jsonl`) with a tiny query helper and a `GET /api/agent/{id}/avatar-telemetry/history` endpoint. The pattern mirrors AD-575 ship-records (append-only, human-inspectable, no new infrastructure). The issue body proposed SQLite-via-`ProtocolStore`; we choose JSONL because: (1) telemetry rows are small (~400 bytes) and write-once, no update pattern; (2) zero new infrastructure (no aiosqlite connection, no migration); (3) operator can `cat` the file. The Protocol-store pattern (AD-682 cloud-ready storage) applies when the commercial overlay swaps backends — file a forward marker.

The writer hooks the existing `runtime.avatar_event_bus.notify()` signal (which already fires on every WS broadcast trigger) — no new tick loop. Tier-2 log-and-degrade: a write failure never blocks the WS publish loop or the agent's reply.

**Folded:** none. This prompt does NOT touch `BUILDER-EXECUTION-PLAN.md`.

---

## Files to Modify

| File | Lines | Why |
|---|---|---|
| `src/probos/config.py` | ~1025 (`AvatarTelemetryConfig`) | Add `history_enabled: bool = True`, `history_retention_days: int = 30`, `history_dir: str = "data/avatar_telemetry"`. |
| `src/probos/avatars/telemetry_history.py` | NEW (~150 lines) | `TelemetryHistoryWriter` class + `query_history(agent_id, limit, since)` helper. Pure stdlib. |
| `src/probos/runtime.py` | ~430 (around `self.avatar_event_bus = AvatarEventBus()`) | Construct + start writer on enabled; expose `runtime.avatar_telemetry_history`. |
| `src/probos/routers/agents.py` | ~700 (WS publish loop after `snap = await build_telemetry_snapshot(...)`) | Tier-2 best-effort: `await writer.append(snap)` after `agent._last_self_avatar_snap = snap`. |
| `src/probos/routers/agents.py` | ~610 (after `agent_avatar_telemetry` GET handler, before WS) | New `@router.get("/{agent_id}/avatar-telemetry/history")` endpoint. |
| `tests/test_ad722c_telemetry_history.py` | NEW | 6 boundary tests. |

Live grep confirms:
- `runtime.avatar_event_bus` is constructed at `runtime.py:430` and named consistently across `routers/agents.py:678` and `cognitive_agent.py:1737`.
- WS broadcast already builds + sends snapshots inside `_publish_loop` at `routers/agents.py:719–741`. The new writer hook is one `await` call inside that loop, gated on config.
- `data/` directory is operator-writable; AD-575 ship-records already creates a subdir there.

---

## Section 1 — `AvatarTelemetryConfig` fields

In `src/probos/config.py`, in `AvatarTelemetryConfig` (around line 1025), add three fields just after `divergence_aggregate_window: int = 50`:

```python
    # AD-722c: append-only JSONL persistence under {history_dir}/<agent_id>.jsonl.
    # Operator opt-out via history_enabled=False. Retention is enforced lazily
    # at query time (rows older than now - history_retention_days are
    # filtered out; on-disk pruning is deferred to AD-722c-1 forward marker).
    history_enabled: bool = True
    history_retention_days: int = 30
    history_dir: str = "data/avatar_telemetry"
```

Add a `field_validator` that bounds `history_retention_days >= 1`. Pattern mirrors `_bound_divergence_history_counts` in the same class.

---

## Section 2 — `TelemetryHistoryWriter` module (NEW)

Create `src/probos/avatars/telemetry_history.py`:

```python
"""AD-722c: append-only JSONL persistence for avatar telemetry snapshots.

One file per agent under {history_dir}/<agent_id>.jsonl. Each line is a JSON
object: {"ts": float, "snap": <AvatarTelemetrySnapshot.to_dict() output>}.
Append-only — no in-place update, no rotation in v1 (AD-722c-1 forward marker
for size-based rotation when files exceed N MiB).

Tier-2 log-and-degrade everywhere — never raises out of public methods. The
WS publish loop and the broadcast trigger MUST NOT block on a write failure.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from probos.avatars.telemetry import AvatarTelemetrySnapshot

logger = logging.getLogger(__name__)

_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _sanitize_agent_id(agent_id: str) -> str | None:
    """Boundary defense — agent_id flows into a path component. Reject
    anything outside [A-Za-z0-9_.-]. Returns None on rejection.
    """
    if not isinstance(agent_id, str) or not agent_id:
        return None
    if not _AGENT_ID_RE.match(agent_id):
        return None
    return agent_id


class TelemetryHistoryWriter:
    """Per-agent append-only JSONL writer.

    Serializes writes via an asyncio.Lock keyed per agent_id (writes from
    different agents proceed in parallel; writes from the same agent are
    serialized to avoid interleaved JSON lines).
    """

    def __init__(self, history_dir: str) -> None:
        self._history_dir = Path(history_dir)
        self._locks: dict[str, asyncio.Lock] = {}

    def _path_for(self, agent_id: str) -> Path | None:
        safe = _sanitize_agent_id(agent_id)
        if safe is None:
            return None
        return self._history_dir / f"{safe}.jsonl"

    def _lock_for(self, agent_id: str) -> asyncio.Lock:
        lock = self._locks.get(agent_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[agent_id] = lock
        return lock

    async def append(self, snap: "AvatarTelemetrySnapshot") -> None:
        """Append one snapshot row. Tier-2 — logs+returns on any failure."""
        try:
            path = self._path_for(snap.agent_id)
            if path is None:
                logger.warning(
                    "AD-722c: rejecting telemetry write — invalid agent_id=%r",
                    snap.agent_id,
                )
                return
            lock = self._lock_for(snap.agent_id)
            async with lock:
                # Build line outside the I/O await to keep the lock window tight.
                row = {"ts": time.time(), "snap": snap.to_dict()}
                line = json.dumps(row, separators=(",", ":")) + "\n"
                # Synchronous write inside a thread executor — avoids needing
                # aiofiles and keeps the dependency footprint at zero. Pattern
                # mirrors records_store async-with-blocking-write usage.
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._sync_append, path, line)
        except Exception:
            logger.warning(
                "AD-722c: telemetry history append failed for agent=%s",
                snap.agent_id, exc_info=True,
            )

    def _sync_append(self, path: Path, line: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    async def query(
        self,
        agent_id: str,
        limit: int = 100,
        since: float | None = None,
        retention_days: int = 30,
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` most recent rows newer than ``since`` (or
        ``now - retention_days`` if since is None). Newest-first.

        Tier-2 — never raises. Missing file → []. Malformed line → skipped.
        """
        try:
            path = self._path_for(agent_id)
            if path is None or not path.exists():
                return []
            cutoff = since if since is not None else (
                time.time() - float(retention_days) * 86400.0
            )
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, self._sync_query, path, int(limit), float(cutoff),
            )
        except Exception:
            logger.warning(
                "AD-722c: telemetry history query failed for agent=%s",
                agent_id, exc_info=True,
            )
            return []

    def _sync_query(
        self, path: Path, limit: int, cutoff: float,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                try:
                    row = json.loads(raw)
                except Exception:
                    continue
                ts = row.get("ts")
                if not isinstance(ts, (int, float)) or float(ts) < cutoff:
                    continue
                rows.append(row)
        rows.sort(key=lambda r: float(r.get("ts", 0.0)), reverse=True)
        return rows[: max(0, int(limit))]
```

---

## Section 3 — Runtime construction

In `src/probos/runtime.py`, around line 430 where `AvatarEventBus` is constructed, add (in the same enabled block — gate on `cfg.avatar_telemetry.enabled AND cfg.avatar_telemetry.history_enabled`):

```python
        from probos.avatars.telemetry_history import TelemetryHistoryWriter
        # AD-722c: append-only JSONL writer; None when feature is disabled
        # so the WS publish loop's hasattr check degrades cleanly.
        self.avatar_telemetry_history: TelemetryHistoryWriter | None = None
        if (
            getattr(self.config, "avatar_telemetry", None) is not None
            and self.config.avatar_telemetry.enabled
            and self.config.avatar_telemetry.history_enabled
        ):
            self.avatar_telemetry_history = TelemetryHistoryWriter(
                self.config.avatar_telemetry.history_dir,
            )
```

(SEARCH on the existing line `self.avatar_event_bus = AvatarEventBus()` and insert the block immediately after.)

---

## Section 4 — Wire writer into WS publish loop

In `src/probos/routers/agents.py:_publish_loop` (around line 736 inside `agent_avatar_telemetry_stream`), after the existing `agent._last_self_avatar_snap = snap` line, add a Tier-2 best-effort write:

```python
                # AD-722c: best-effort persistence. Never blocks the publish.
                _hist = getattr(runtime, "avatar_telemetry_history", None)
                if _hist is not None:
                    try:
                        await _hist.append(snap)
                    except Exception:
                        logger.debug(
                            "AD-722c: history append raised in publish loop",
                            exc_info=True,
                        )
```

Apply the same 3-line guard after the `initial` snapshot send block (around line 707) so the first frame on connect also persists.

---

## Section 5 — `GET /api/agent/{id}/avatar-telemetry/history` endpoint

In `src/probos/routers/agents.py`, immediately after the `agent_avatar_telemetry` GET handler (line 609 area, before the WS handler at line 634), add:

```python
@router.get("/{agent_id}/avatar-telemetry/history")
async def agent_avatar_telemetry_history(
    agent_id: str,
    limit: int = 100,
    since: float | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-722c: query persisted telemetry snapshots for an agent.

    Returns {"agent_id": ..., "rows": [{"ts": float, "snap": {...}}, ...]}.
    Empty `rows` when feature disabled, agent not found, or no history yet.
    """
    cfg = getattr(runtime, "config", None)
    telemetry_cfg = getattr(cfg, "avatar_telemetry", None)
    if telemetry_cfg is None or not telemetry_cfg.enabled:
        raise HTTPException(status_code=503, detail="avatar_telemetry_disabled")
    if not telemetry_cfg.history_enabled:
        return {"agent_id": agent_id, "rows": []}

    # Boundary defense — clamp limit. Don't 4xx; just clamp.
    limit = max(1, min(int(limit), 1000))

    writer = getattr(runtime, "avatar_telemetry_history", None)
    if writer is None:
        return {"agent_id": agent_id, "rows": []}

    rows = await writer.query(
        agent_id,
        limit=limit,
        since=since,
        retention_days=telemetry_cfg.history_retention_days,
    )
    return {"agent_id": agent_id, "rows": rows}
```

---

## Test plan (boundary tests)

Create `tests/test_ad722c_telemetry_history.py` with 6 tests:

1. `test_writer_appends_and_queries_roundtrip` — write 3 snapshots, query returns 3 newest-first.
2. `test_writer_rejects_malicious_agent_id` — `"../evil"`, empty, non-string → no file created, no raise.
3. `test_query_respects_since` — write 5 rows with controlled `ts`, `since=...` filters correctly.
4. `test_query_respects_retention_window` — rows older than `retention_days` excluded.
5. `test_writer_tolerates_disk_failure` — patch `Path.open` to raise → `append()` returns normally (no exception bubbles).
6. `test_query_skips_malformed_lines` — pre-seed JSONL with one valid row + one corrupted line → query returns the valid row only.

Use `tmp_path` fixture for `history_dir`. Construct `TelemetryHistoryWriter` directly; build minimal `AvatarTelemetrySnapshot` instances inline (frozen dataclass — `AvatarTelemetrySnapshot(agent_id=..., expression_resting=None, current_signals=_empty_signals(), mouth_active=False, applied_modulation=None, dsl_summary=None, last_observed_at=0.0, degraded_reasons=(), sampling_rate_ms=2000, sampling_tier="normal")`).

No new test fixtures needed. No subprocess. No UI test (no UI change).

---

## What this does NOT change

- WS push frame shape — still `snap.to_dict()`. AD-722b-3 (separate prompt this wave) layers diff-emission ON TOP.
- AD-722a-5 in-memory divergence ring buffer — unchanged.
- ChromaDB / episodic memory — telemetry never enters episodic memory.
- Records / git history — not touched.
- Sampling rate logic.

---

## Verification commands

```powershell
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad722c_telemetry_history.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile
```

No UI changes in this prompt — `npm run build` not required (per AD-738b standing rule, only required when `git diff --name-only HEAD~1..HEAD -- ui/src/` is non-empty).

---

## Tracker updates

- `PROGRESS.md` — append closure line with test count delta.
- `docs/development/roadmap.md` — mark #569 closed; remove from bug-tracker; add AD-722c-1 forward marker (size-based JSONL rotation when files exceed configured MiB).
- `DECISIONS.md` — append AD-722c entry with the JSONL-vs-SQLite design choice rationale and the ProtocolStore deferral.

Commit message:
```
AD-722c: avatar telemetry JSONL history + query endpoint

Closes #569
```

---

## License Disposition

**All-internal Apache 2.0.** No new pip deps (uses stdlib `json`, `pathlib`, `re`, `asyncio.Lock`, `asyncio.get_running_loop`). No new npm deps. No model weights, no external binaries. Telemetry rows are operator-local under `data/`; the directory pattern matches existing AD-575 ship-records hygiene (gitignored under `data/`).

---

## Forward markers

- **AD-722c-1** — size-based JSONL rotation when per-agent files exceed N MiB (trigger: operator with > 30-day high-frequency telemetry runs into multi-GB file sizes).
- **AD-722c-2** — `TelemetryHistoryStore` Protocol so a queryable-backend deployment can swap JSONL for SQLite/Postgres (trigger: queryable analytics required; closes AD-682 cloud-ready compliance gap for this surface).

---

## Acceptance criteria

- All 6 new tests pass under `-n 0`.
- Full gate `pytest tests/ -q -n 4 --dist=loadfile` green.
- WS publish loop never blocks > 1 ms on history writes (verified by inspection — the await is to an executor; no fsync).
- Endpoint returns `[]` when feature is off (no 404, no 500).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-14)

```
grep -n "class AvatarTelemetryConfig" src/probos/config.py
  1025: class AvatarTelemetryConfig(BaseModel):

grep -n "class AvatarTelemetrySnapshot" src/probos/avatars/telemetry.py
  345: class AvatarTelemetrySnapshot:

grep -n "AvatarEventBus()" src/probos/runtime.py
  430:         self.avatar_event_bus = AvatarEventBus()

grep -n "agent_avatar_telemetry" src/probos/routers/agents.py
  609: @router.get("/{agent_id}/avatar-telemetry")
  610: async def agent_avatar_telemetry(...)
  634: @router.websocket("/{agent_id}/avatar-telemetry-stream")

grep -n "_last_self_avatar_snap = snap" src/probos/routers/agents.py
  707:             agent._last_self_avatar_snap = initial
  737:                 agent._last_self_avatar_snap = snap
```
