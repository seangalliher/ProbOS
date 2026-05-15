# AD-721d-4 — Persist avatar proposal history across runtime restart

**Wave:** 161
**Closes:** #620 (also closes #623 as a duplicate — both titled `AD-721d-4: Persist avatar proposal history across runtime restarts`).
**Status:** ready to build
**Dependencies:** AD-721d-1 (Wave 145 — module-level `_history` dict + 5 stable public functions).
**Estimated tests:** +5 pytest, 0 vitest.
**Scope tag:** Server-only. Pure internal change. No new pip deps. Apache 2.0.

---

## Problem

`src/probos/avatars/proposal_history.py` (AD-721d-1) stores the per-agent DSL-proposal session history in a module-level dict guarded by an `RLock`. Restart drops everything — in-flight iterations are lost, the Captain has to start over.

The module docstring explicitly anticipates this AD:

> "v1 is single-process; cluster-wide consistency, persistence across restarts, and quorum on the iteration counter are out of scope."

And the 5 public function signatures (`append`, `iteration_count`, `latest`, `clear`, `reset_all`) are documented as **stable** specifically to support a drop-in persistence swap.

This AD adds JSON-sidecar persistence behind the existing function signatures. **No signature changes.** Production callers (`routers/agents.py`) are not modified.

---

## Solution overview

1. Add a module-level `_persist_path: Path | None = None` initialized via a new `configure(path: Path | None)` function, called once at runtime startup.
2. On runtime boot, call `proposal_history.configure(Path(<data_dir>/proposal_history.json))` (or the path from a new `AvatarsConfig` field). The function also LOADS the on-disk state into `_history`.
3. Every mutation (`append` / `clear` / `reset_all`) writes the current state to disk. Tier-2 — disk failure logs and degrades; the in-memory `_history` remains authoritative for the live process.
4. Format: `{agent_id: [{"dsl": {...}, "captain_note": "...", "timestamp": 1234.5}, ...]}`.
5. Atomic write via tempfile + `os.replace` (same pattern as AD-730-2-1).
6. The `ProposalEntry` dataclass is frozen — reconstruct from dict on load via the dataclass constructor.

---

## Section 1 — Module additions (`src/probos/avatars/proposal_history.py`)

Add near the top (after the `_history` declaration, before `def append`):

```python
# AD-721d-4: optional disk persistence. ``configure`` is called once at
# runtime boot to set the sidecar path AND load any prior state. When the
# path is None, the module operates in pure in-memory mode (matches AD-721d-1
# behavior — required for tests and zero-config single-process operators).
_persist_path: "Path | None" = None
```

Also add `from pathlib import Path` to the imports at the top of the file (verify it's not already there).

Add three module-level helpers:

```python
def configure(path: "Path | None") -> None:
    """Set the on-disk sidecar path and load any pre-existing state.

    Idempotent — calling with the same path repopulates from disk
    (useful for tests that need to inspect the persisted state).
    Calling with None disables persistence and clears the in-memory
    state (test-only convenience; production should not pass None
    after a real path has been set).
    """
    global _persist_path
    with _lock:
        _persist_path = path
        _history.clear()
        if path is None:
            return
        _load_from_disk_locked()


def _load_from_disk_locked() -> None:
    """Internal — called under ``_lock``. Loads ``_persist_path`` into ``_history``.

    Tier-2: load failure leaves ``_history`` empty and logs WARNING.
    """
    import json
    if _persist_path is None or not _persist_path.exists():
        return
    try:
        raw = _persist_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception:
        logger.warning(
            "AD-721d-4: failed to load proposal history from %s; "
            "starting with empty in-memory state",
            _persist_path, exc_info=True,
        )
        return
    if not isinstance(data, dict):
        logger.warning(
            "AD-721d-4: %s contained non-dict root %r; starting empty",
            _persist_path, type(data).__name__,
        )
        return
    for agent_id, entries in data.items():
        if not isinstance(agent_id, str) or not isinstance(entries, list):
            continue
        loaded: list[ProposalEntry] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                loaded.append(ProposalEntry(
                    dsl=entry["dsl"],
                    captain_note=str(entry.get("captain_note", "")),
                    timestamp=float(entry["timestamp"]),
                ))
            except (KeyError, TypeError, ValueError):
                logger.warning(
                    "AD-721d-4: skipping malformed entry for agent=%s in %s",
                    agent_id, _persist_path,
                )
        if loaded:
            _history[agent_id] = loaded


def _persist_locked() -> None:
    """Internal — called under ``_lock``. Atomically writes ``_history`` to disk.

    Tier-2 — failures log and degrade; in-memory state is authoritative.
    """
    import json
    import os
    import tempfile
    if _persist_path is None:
        return
    try:
        _persist_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            agent_id: [
                {"dsl": e.dsl, "captain_note": e.captain_note, "timestamp": e.timestamp}
                for e in entries
            ]
            for agent_id, entries in _history.items()
            if entries
        }
        fd, tmp_path = tempfile.mkstemp(
            prefix=_persist_path.name + ".",
            suffix=".tmp",
            dir=str(_persist_path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, separators=(",", ":"))
            os.replace(tmp_path, _persist_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            raise
    except Exception:
        logger.warning(
            "AD-721d-4: failed to persist proposal history to %s; "
            "in-memory state remains authoritative",
            _persist_path, exc_info=True,
        )
```

Then modify each of the three mutators (`append`, `clear`, `reset_all`) to call `_persist_locked()` inside the existing `with _lock:` block, AFTER the mutation. Example for `append`:

```python
def append(agent_id: str, dsl: dict, captain_note: str) -> int:
    """Append a proposal entry; return the new iteration count (1-based)."""
    with _lock:
        entries = _history.setdefault(agent_id, [])
        entries.append(
            ProposalEntry(dsl=dsl, captain_note=captain_note, timestamp=time.time())
        )
        _persist_locked()
        return len(entries)
```

Same shape for `clear` and `reset_all`. `iteration_count` and `latest` are read-only and unchanged.

---

## Section 2 — Runtime boot wiring (`src/probos/runtime.py`)

Find where `avatars` config is first read (the avatars-feature gate path). After the avatars-feature initialization, configure proposal_history:

```python
# AD-721d-4: bind proposal_history to its on-disk sidecar so DSL
# iterations survive restart. Path is configurable via
# AvatarsConfig.proposal_history_path; defaults to
# ``<data_dir>/proposal_history.json``.
try:
    from probos.avatars import proposal_history as _ph
    _ph_cfg = getattr(self.config, "avatars", None)
    _ph_path_str = getattr(_ph_cfg, "proposal_history_path", None) if _ph_cfg else None
    if _ph_path_str:
        _ph_path = Path(_ph_path_str)
    else:
        _ph_path = Path(self.config.data_dir) / "proposal_history.json"
    _ph.configure(_ph_path)
except Exception:
    logger.warning(
        "AD-721d-4: proposal_history.configure failed; in-memory mode only",
        exc_info=True,
    )
```

Place the block after `self.config` is fully initialized and before any agent registration, so the first `propose_appearance` call sees the loaded state.

---

## Section 3 — Config field (`src/probos/config.py`)

Find `AvatarsConfig`. Add:

```python
    proposal_history_path: str | None = Field(
        default=None,
        description=(
            "AD-721d-4: filesystem path for the per-agent DSL proposal "
            "history JSON sidecar. When None, defaults to "
            "``<runtime.config.data_dir>/proposal_history.json``."
        ),
    )
```

---

## Section 4 — Tests `tests/test_ad721d_4_proposal_history_persist.py`

Five tests; use `tmp_path` fixture and `proposal_history.reset_all()` + `proposal_history.configure(None)` in `setUp`/`tearDown` (or pytest fixture with yield + cleanup) for isolation.

1. **`test_configure_with_no_existing_file_starts_empty`** — `configure(tmp_path / "missing.json")`; `iteration_count("ezri")` returns 0.
2. **`test_append_persists_to_disk`** — `configure(p)`, `append("ezri", {"name": "X"}, "note")`; assert `p.exists()` and JSON content has 1 entry under `"ezri"`.
3. **`test_load_roundtrips_existing_state`** — pre-write a valid JSON file with one agent and two entries; `configure(p)`; `iteration_count("ezri") == 2`; `latest("ezri").captain_note == "second-note"`.
4. **`test_clear_persists_removal`** — `configure(p)`; `append("ezri", {...}, "n")`; `clear("ezri")`; reload via `configure(p)` (re-reads disk); `iteration_count("ezri") == 0`.
5. **`test_malformed_disk_state_loads_empty_and_logs`** — write `"not json"` to the path; `configure(p)`; `iteration_count("anything") == 0`; assert WARNING logged via `caplog`.

**Test isolation gotcha:** `proposal_history` is module-level state. Every test MUST call `proposal_history.reset_all()` AND `proposal_history.configure(None)` in teardown so the NEXT test gets a clean module. Use a pytest fixture:

```python
@pytest.fixture(autouse=True)
def _isolate_proposal_history():
    yield
    from probos.avatars import proposal_history
    proposal_history.reset_all()
    proposal_history.configure(None)
```

---

## Standing rules (must comply)

- **BF-274** — Use single `replace_string_in_file` for each of the three mutator modifications (`append`, `clear`, `reset_all`). Don't combine into `multi_replace_string_in_file`.
- **BF-280** — N/A.
- **BF-282** — N/A.
- **BF-286** — N/A.
- **AD-731 invariant** — N/A; this AD touches no attachment paths.
- **AD-738b / UI gate** — N/A (no `ui/src/**` files modified).
- **AD-722c-3 forward-marker style** — technical triggers only.
- **Module-level state isolation** — confirmed in test fixture above.
- **Signature stability** — the 5 existing public functions (`append`, `iteration_count`, `latest`, `clear`, `reset_all`) keep their exact signatures. `configure` is a new function; it does NOT replace any existing function.
- **No emoji** — ASCII logs.

---

## Forward markers (file in `docs/development/roadmap.md`)

- **AD-721d-4a** — Migrate to SQLite-backed `ProfileStore` JSON-blob column (matches existing AvatarDSL persistence shape). **Trigger:** any of: (a) commercial overlay swaps storage backend via AD-697/698 `ConnectionFactory`; (b) JSON sidecar file size exceeds 1 MB; (c) a second module needs proposal-history-style restart-survival state and ConnectionFactory has shipped.
- **AD-721d-4b** — Add periodic compaction (purge entries older than 30 days with no terminal action — approve/clear). **Trigger:** observed sidecar file growth > 256 KB/week OR any single agent's history exceeds 100 entries.

---

## Acceptance criteria

1. `proposal_history.configure(path)` exists and behaves per Section 1 (load + path bind, or pure in-memory when None).
2. The 5 existing public functions retain their exact signatures.
3. Mutations (`append`, `clear`, `reset_all`) persist after the in-memory update, under the existing lock.
4. `AvatarsConfig.proposal_history_path: str | None = None` field added.
5. Runtime boots, configures proposal_history with the resolved path. Boot failure of the persistence layer logs WARNING and degrades to in-memory.
6. 5 new pytest tests pass.
7. **Existing AD-721d / AD-721d-1 tests still pass** (regression gate). The autouse fixture must apply globally OR be opt-in via conftest scoping — verify existing avatar tests do not break.
8. `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile` green.
9. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Tracking

- **PROGRESS.md** — Wave 161 in-flight; close #620 (and #623 as duplicate).
- **DECISIONS.md** — AD-721d-4 entry. Note duplicate issue resolution.
- **docs/development/roadmap.md** — forward markers per above.

---

## Hard-stop / surface-before-doing

- If the autouse fixture pattern breaks existing tests in `tests/test_ad721d_propose_appearance.py` / `tests/test_ad721d1_dsl_preview.py`, SURFACE — may need a narrower fixture scope (per-test-file) instead of `autouse=True`.

---

## Verified Against Codebase (2026-05-15)

```
src/probos/avatars/proposal_history.py:
  31: @dataclass(frozen=True)
  32: class ProposalEntry:
  39:     dsl: dict          # AvatarDSL.model_dump() snapshot
  40:     captain_note: str  # the revision hint used to produce this dsl
  41:     timestamp: float
  44: _lock = threading.RLock()
  45: _history: dict[str, list[ProposalEntry]] = {}
  48: def append(agent_id: str, dsl: dict, captain_note: str) -> int:
  56: def iteration_count(agent_id: str) -> int:
  61: def latest(agent_id: str) -> ProposalEntry | None:
  68: def clear(agent_id: str) -> int:
  75: def reset_all() -> None:

GH duplicate issues:
  #620 "AD-721d-4: Persist avatar proposal history across runtime restarts"
  #623 "AD-721d-4: Persist avatar proposal history across runtime restarts"
  (both bodies match; #620 is older — canonical. Close #623 as dup.)
```
