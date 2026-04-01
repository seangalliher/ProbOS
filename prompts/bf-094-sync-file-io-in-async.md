# BF-094: Sync File I/O in Async Methods

## Context

Codebase scorecard graded async discipline at **B+**. Three modules perform sync file I/O inside async methods, blocking the event loop. The codebase already uses `asyncio.get_running_loop().run_in_executor(None, ...)` in 22+ call sites (builder.py, records_store.py, shell_command.py, red_team.py, store.py) — this fix follows the established pattern.

**Do NOT add `aiofiles` as a dependency.** The project uses `run_in_executor` exclusively. Follow that pattern.

## Problem

| File | Async Method | Sync I/O | Impact |
|------|-------------|----------|--------|
| `ward_room.py` | `prune_old_threads()` | `os.makedirs()`, `open()` + `.write()` in loop | **High** — blocks event loop during periodic runtime pruning |
| `crew_profile.py` | called from `agents.py:agent_profile()` | `open()` + `yaml.safe_load()` | **Medium** — blocks event loop on every agent profile API request |
| `ontology.py` | `initialize()` | 7× `open()` + `yaml.safe_load()` + pathlib read/write | **Low** — startup only, single-threaded at that point |

## Part 1: ward_room.py — Async Thread Pruning Archive

**Priority: HIGH.** This blocks the event loop during normal operation.

### 1a. Fix `prune_old_threads()` archive write

The method at line ~267 has sync I/O in the archive section (around lines 342-362):

```python
# CURRENT (sync, blocks event loop):
if archive_path:
    import os
    os.makedirs(os.path.dirname(archive_path) if os.path.dirname(archive_path) else ".", exist_ok=True)
    with open(archive_path, "a", encoding="utf-8") as f:
        # ... writes records in loop
```

**Fix:** Extract the sync archive write into a helper and run via executor:

```python
def _write_archive_sync(self, archive_path: str, records: list[dict]) -> None:
    """Write pruned thread records to JSONL archive (sync, run in executor)."""
    import os
    os.makedirs(os.path.dirname(archive_path) if os.path.dirname(archive_path) else ".", exist_ok=True)
    with open(archive_path, "a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
```

Then in `prune_old_threads()`, collect the records into a list first, then:

```python
if archive_path and records:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, self._write_archive_sync, archive_path, records)
```

**Key:** Collect ALL records to write into a `list[dict]` during the DB query phase, then write them all at once in the executor. Don't mix DB reads and file writes in the sync helper.

### 1b. Fix `_build_stats()` — `os.path.getsize()`

Line ~436:
```python
# CURRENT:
db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
```

**Fix:**
```python
loop = asyncio.get_running_loop()
db_size = await loop.run_in_executor(None, lambda: os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0)
```

### 1c. Fix `_prune_loop()` — `Path.mkdir()`

Line ~486:
```python
# CURRENT:
Path(self._archive_dir).mkdir(parents=True, exist_ok=True)
```

**Fix:**
```python
loop = asyncio.get_running_loop()
await loop.run_in_executor(None, lambda: Path(self._archive_dir).mkdir(parents=True, exist_ok=True))
```

### Add import

Add `import asyncio` to the top of `ward_room.py` if not already present.

## Part 2: crew_profile.py — Async Profile Loading

**Priority: MEDIUM.** Called from a FastAPI endpoint handler.

### 2a. Make `load_seed_profile()` async-safe

The function at line ~400 does `open()` + `yaml.safe_load()`. It's called from:
- `async agent_profile()` in `routers/agents.py` line ~64 ← **this is the problem**
- `_build_personality_block()` in `standing_orders.py` (sync caller, leave as-is)

**Fix:** Create an async wrapper rather than modifying the sync function (since it has sync callers too):

```python
async def load_seed_profile_async(agent_type: str) -> dict[str, Any] | None:
    """Async wrapper for load_seed_profile — runs file I/O in executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, load_seed_profile, agent_type)
```

Add `import asyncio` to `crew_profile.py` if not already present.

### 2b. Update the FastAPI caller

In `src/probos/routers/agents.py`, update the `agent_profile()` endpoint to use the async wrapper:

```python
# BEFORE:
from probos.crew_profile import load_seed_profile
...
seed = load_seed_profile(agent.agent_type)

# AFTER:
from probos.crew_profile import load_seed_profile_async
...
seed = await load_seed_profile_async(agent.agent_type)
```

## Part 3: ontology.py — Async YAML Loading

**Priority: LOW.** Runs once at startup in single-threaded context. Include for completeness but this is the least impactful fix.

### 3a. Create sync helper for YAML loading

The 7 `_load_*` methods each follow the same pattern:
```python
with open(path, "r", encoding="utf-8") as f:
    data = yaml.safe_load(f)
```

**Fix:** Add a shared helper at module or class level:

```python
@staticmethod
def _read_yaml_sync(path: str) -> dict:
    """Read and parse a YAML file (sync, for use with run_in_executor)."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
```

Then in `initialize()`, wrap the calls:

```python
loop = asyncio.get_running_loop()
data = await loop.run_in_executor(None, self._read_yaml_sync, str(vessel_path))
```

### 3b. Apply to each `_load_*` method

Each of the 7 `_load_*` methods should replace its `with open(...) ... yaml.safe_load()` block with:

```python
data = await loop.run_in_executor(None, self._read_yaml_sync, str(path))
```

Since the `_load_*` methods are private and only called from `initialize()`, they can be made `async` safely. The `loop` variable should be obtained once in `initialize()` and passed or captured.

### 3c. Fix `_load_or_generate_instance_id()`

This method does `id_file.read_text()` and `id_file.write_text()`. Extract the sync portion:

```python
@staticmethod
def _load_or_generate_instance_id_sync(id_file: Path) -> str:
    """Load or generate instance ID (sync, for run_in_executor)."""
    if id_file.exists():
        return id_file.read_text().strip()
    instance_id = str(uuid.uuid4())
    id_file.parent.mkdir(parents=True, exist_ok=True)
    id_file.write_text(instance_id)
    return instance_id
```

Then call via executor in the async loader.

## Part 4: Tests

### 4a. Ward Room archive test

Extend `tests/test_ward_room.py` (or relevant existing test file):
- Test that `prune_old_threads()` still writes correct JSONL to archive path
- Test that `_build_stats()` returns valid stats (including db_size)
- No need to test that executor was used — behavior test, not implementation test

### 4b. Crew profile async test

Add a test that `load_seed_profile_async()` returns the same result as `load_seed_profile()`.

### 4c. Ontology test

Existing `initialize()` tests should still pass — the YAML loading produces the same result.

## Verification

```bash
uv run pytest tests/ -k "ward_room or crew_profile or ontology" -v
```

Search for remaining sync file I/O in async methods:
```bash
grep -n "open(" src/probos/ward_room.py src/probos/crew_profile.py src/probos/ontology.py
```
All `open()` calls should now be inside `_sync` helpers or `run_in_executor` lambdas.

## Principles Compliance

- **DRY:** Shared `_read_yaml_sync` helper for ontology's 7 identical patterns
- **Fail Fast:** No behavior change — same errors, same validation, just non-blocking
- **Cloud-Ready:** Async I/O is mandatory for production async services
- **Law of Demeter:** Sync helpers are private methods on the owning class
