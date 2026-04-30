# AD-682: Test Fixture Isolation for Full xdist Parallelization

**Status:** Ready for builder (build AFTER wave 1-4 completes)
**Dependencies:** None on the source side. Should not be built concurrently with the wave 1-4 sweep — it touches conftest.py and may surface latent test ordering bugs.
**Estimated tests added:** ~6 (fixture isolation smoke tests)
**Risk:** Medium — substrate-level test infrastructure change. Could surface latent ordering bugs in existing tests; that's the point.

---

## Problem

The full pytest gate cannot use full xdist parallelism (`-n auto`, 32 workers on dev machines) because heavy fixtures share global resources that race when many workers boot simultaneously:

1. **ChromaDB SQLite contention.** `EpisodicMemory.__init__` (line 732) opens `chromadb.PersistentClient(path=str(db_dir))` against the project's real `data/chroma.sqlite3`. Multiple workers → SQLite lock contention → timeouts → worker crash. Same problem in `knowledge/semantic.py:58` and `cognitive/procedure_store.py:280`.
2. **Filesystem races on `data/*`.** Tests touching `data/scout_seen.json`, `data/session_last.json`, ship-records dirs collide. Symptom: `TestScoutDataDirectory` 3-failure pattern under xdist that disappears under `-n 0`.
3. **Module-level singletons.** `_build_personality_block` `lru_cache` and other module-scoped caches mutate during tests; ordering-dependent failures appear under parallel.

Current workaround: `BUILDER-EXECUTION-PLAN` uses `-n 4 --dist=loadfile` and a "rerun failures serially to confirm environmental" rule. That gives ~5x speedup. With proper isolation, `-n auto` would give ~20x speedup on a 32-core box.

## Solution

Add per-xdist-worker resource isolation in `tests/conftest.py`. Each worker gets its own:
- ChromaDB persist directory
- `PROBOS_DATA_DIR` redirect
- Cleared module-level caches

Then add a small CI-mode helper to run the gate at `-n auto`.

## What This Does NOT Change

- No production source changes that affect runtime behavior. The `PROBOS_*` env-var overrides are *already honored* by the corresponding subsystems via `getattr(config, ...)` patterns; this AD just makes tests use them.
- No removal of the existing `real_nats` opt-in fixture or the `BF-245` `PROBOS_NATS_ENABLED` default.
- No changes to test logic — only fixture infrastructure.
- Does NOT delete `data/chroma.sqlite3` or other dev-environment state.

## Verified Against Codebase (2026-04-29)

```
grep -n "chromadb.PersistentClient" src/
  src/probos/cognitive/episodic.py:732
  src/probos/knowledge/semantic.py:58
  src/probos/cognitive/procedure_store.py:280

grep -n "PROBOS_NATS_ENABLED" tests/conftest.py
  16: os.environ.setdefault("PROBOS_NATS_ENABLED", "false")
  60: monkeypatch.setenv("PROBOS_NATS_ENABLED", "true")

grep -n "def _default_data_dir" src/probos/__main__.py
  38

grep -n "data_dir" src/probos/config.py
  687: repo_path: str = ""  # Empty = {data_dir}/ship-records/

grep -n "EpisodicMemory" src/probos/cognitive/episodic.py
  651: class EpisodicMemory:
  659:     def __init__(...)
  732:     self._client = chromadb.PersistentClient(path=str(db_dir))
```

`PROBOS_NATS_ENABLED` precedent confirms env-var-driven test isolation works in this codebase. AD-682 extends the pattern.

## Implementation

### Section 1: Add per-worker `PROBOS_DATA_DIR` isolation

**File:** `tests/conftest.py`

Add an autouse session-scoped fixture that creates a per-worker tmp dir and points all data-dir-derived paths at it.

SEARCH (around line 17, after the `HF_HUB_OFFLINE` setdefault):

```python
os.environ.setdefault("PROBOS_NATS_ENABLED", "false")
os.environ.setdefault("HF_HUB_OFFLINE", "1")


def pytest_collection_modifyitems(config, items):
```

REPLACE:

```python
os.environ.setdefault("PROBOS_NATS_ENABLED", "false")
os.environ.setdefault("HF_HUB_OFFLINE", "1")


@pytest.fixture(scope="session", autouse=True)
def _ad682_isolated_data_dir(tmp_path_factory, worker_id):
    """AD-682: Per-xdist-worker isolated data dir.

    Each xdist worker (or master in serial mode) gets its own tmp directory
    used as PROBOS_DATA_DIR. Subsystems that resolve paths from data_dir
    (ChromaDB, ship-records, scout_seen.json, session state) land in
    worker-private space. Eliminates SQLite lock contention and filesystem
    races at high parallelism (-n auto).

    The override is set via os.environ so it is visible to subprocess and
    to subsystems that read env directly (parity with BF-245 PROBOS_NATS_ENABLED).
    """
    suffix = worker_id if worker_id != "master" else "master"
    data_dir = tmp_path_factory.mktemp(f"probos_data_{suffix}", numbered=False)
    prior = os.environ.get("PROBOS_DATA_DIR")
    os.environ["PROBOS_DATA_DIR"] = str(data_dir)
    try:
        yield data_dir
    finally:
        if prior is None:
            os.environ.pop("PROBOS_DATA_DIR", None)
        else:
            os.environ["PROBOS_DATA_DIR"] = prior


def pytest_collection_modifyitems(config, items):
```

### Section 2: Wire `PROBOS_DATA_DIR` into the production resolver

**File:** `src/probos/__main__.py`

`_default_data_dir()` currently returns the platformdirs path. Honor an env-var override so the conftest fixture takes effect.

SEARCH (the body of `_default_data_dir`):

```python
def _default_data_dir() -> Path:
```

Read the function fully (~10 lines starting at line 38), then update so the first thing it does is check the env var. Pattern:

```python
def _default_data_dir() -> Path:
    """Return the default data directory.

    AD-682: Honor PROBOS_DATA_DIR env override (used by tests to isolate
    per-xdist-worker state).
    """
    override = os.environ.get("PROBOS_DATA_DIR")
    if override:
        return Path(override)
    # ... existing platformdirs body unchanged ...
```

Verify `os` is already imported (it is — `__main__.py` uses os elsewhere).

### Section 3: Add per-worker ChromaDB isolation

**File:** `tests/conftest.py` (immediately below the fixture from Section 1)

ChromaDB clients in three modules read paths derived from `data_dir`. With the AD-682 `PROBOS_DATA_DIR` redirect in place, they will already land in per-worker space — but verify by adding a fixture-scoped sanity check.

Add:

```python
@pytest.fixture(scope="session", autouse=True)
def _ad682_chroma_path_sanity(_ad682_isolated_data_dir):
    """AD-682: Assert ChromaDB lands inside the worker's isolated data dir.

    Catches regressions where a future code path constructs
    chromadb.PersistentClient against a hardcoded global path.
    """
    yield
    # Post-session: scan for any chroma.sqlite3 written outside the worker dir
    import glob
    rogue = [
        p for p in glob.glob("data/chroma.sqlite3*")
        if not p.startswith(str(_ad682_isolated_data_dir))
    ]
    if rogue:
        raise AssertionError(
            f"AD-682: ChromaDB wrote outside isolated data dir: {rogue}. "
            f"A subsystem is bypassing PROBOS_DATA_DIR resolution."
        )
```

### Section 4: Add per-worker module-cache reset

**File:** `tests/conftest.py`

Add an autouse function-scoped fixture that clears known module-level caches between tests. This is cheap (lru_cache.cache_clear() is O(1)) and fixes ordering-dependent failures.

```python
@pytest.fixture(autouse=True)
def _ad682_clear_module_caches():
    """AD-682: Reset module-level caches that mutate during tests.

    Without this, test execution order affects results when the standing
    orders cache or personality block cache picks up state from a prior test.
    Add new caches here as they are discovered.
    """
    from probos.cognitive import standing_orders
    if hasattr(standing_orders, "clear_cache"):
        standing_orders.clear_cache()
    if hasattr(standing_orders, "_build_personality_block"):
        try:
            standing_orders._build_personality_block.cache_clear()
        except AttributeError:
            pass  # Not an lru_cache after refactor
    yield
```

**Builder note:** if discovery turns up additional caches (grep for `lru_cache` and `_CACHE\s*=\s*{}` patterns under `src/probos/cognitive/`), add them to this fixture. Reference grep:

```pwsh
grep -rn "lru_cache\|^_[A-Z_]\+_CACHE\b" src/probos/
```

### Section 5: Update BUILDER-EXECUTION-PLAN gate command

**File:** `prompts/BUILDER-EXECUTION-PLAN.md`

Once the AD-682 fixtures are in, the full gate can use `-n auto`. Update the relevant lines.

SEARCH:

```markdown
- **Test gate:** the **full gate** uses `pytest tests/ -q -n 4 --dist=loadfile` (4 workers, file-level distribution). The **focused per-prompt gate** uses `pytest tests/test_<adNNN>_*.py -v -n 0` (serial, deterministic). `-n auto` is forbidden — it exhibits worker-crash loops on this codebase.
```

REPLACE:

```markdown
- **Test gate:** the **full gate** uses `pytest tests/ -q -n auto --dist=loadfile` (full parallelism via AD-682 fixture isolation). The **focused per-prompt gate** uses `pytest tests/test_<adNNN>_*.py -v -n 0` (serial, deterministic). If `-n auto` regresses, fall back to `-n 4 --dist=loadfile` and file a BF.
```

Apply parallel updates to the other `-n 4 --dist=loadfile` mentions in the plan (about 5 lines).

### Section 6: Update PROGRESS.md and roadmap

- `PROGRESS.md`: AD-682 CLOSED entry summarizing per-worker isolation, new fixtures, and the parallelism upgrade.
- `docs/development/roadmap.md`: AD-682 entry in the appropriate section (Test Infrastructure).
- `DECISIONS.md`: brief AD-682 note recording the env-var-redirect pattern as the standard for test isolation, citing BF-245 (`PROBOS_NATS_ENABLED`) as precedent.

## Tests

**File:** `tests/test_ad682_fixture_isolation.py`

6 tests:

1. `test_data_dir_is_isolated` — assert `os.environ["PROBOS_DATA_DIR"]` points at a tmp path, not the project's `data/`.
2. `test_default_data_dir_honors_env` — set `PROBOS_DATA_DIR` via `monkeypatch.setenv`, call `_default_data_dir()`, assert it returns the override.
3. `test_default_data_dir_falls_back_when_env_unset` — `monkeypatch.delenv("PROBOS_DATA_DIR")`, call `_default_data_dir()`, assert platformdirs path returned.
4. `test_chroma_writes_inside_isolated_dir` — instantiate a small `EpisodicMemory`, write one episode, assert the SQLite file landed under `PROBOS_DATA_DIR`.
5. `test_module_cache_cleared_between_tests` (paired with helper) — populate the standing-orders cache in this test, expect the next test in the file to see it cleared.
6. `test_two_pseudo_workers_dont_collide` — manually invoke the fixture twice with different `worker_id` values via `pytest.MonkeyPatch`, assert the resulting paths are distinct and writes to one don't affect the other.

## Verification Steps

After all sections land:

1. Focused: `pytest tests/test_ad682_fixture_isolation.py -v -n 0` — all 6 pass.
2. Full gate parallel: `pytest tests/ -q -n auto --dist=loadfile` — green, no worker-crash loop, total time ~2-3 min on a 32-core box.
3. Compare to baseline: `pytest tests/ -q -n 4 --dist=loadfile` — should still be green (regression check).
4. Full serial sanity: `pytest tests/ -q -n 0` — should still be green (no order dependencies introduced).

## Acceptance Criteria

- 6 new tests pass.
- Full xdist gate completes at `-n auto` without worker crashes on a 32-core machine in under 5 minutes.
- All previously-green tests stay green at `-n 0` (no order-dependent regressions).
- `BUILDER-EXECUTION-PLAN.md` updated to use `-n auto` as the default full gate.
- DECISIONS.md records the env-var-redirect pattern as the standard.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Tracking

- `PROGRESS.md`: AD-682 CLOSED.
- `docs/development/roadmap.md`: AD-682 entry under Test Infrastructure.
- `DECISIONS.md`: env-var-redirect pattern precedent.
- `BUILDER-EXECUTION-PLAN.md`: gate command update.

## Future Work (out of scope)

- Replace `data/chroma.sqlite3` development-state defaults with a CLI flag pattern, so contributors don't accidentally wipe local dev memory when running tests. Currently the per-worker isolation prevents test writes from polluting dev state; a separate AD could harden the inverse direction.
- A pre-test fixture that warm-loads the embedding model once per worker (instead of once per test that uses ChromaDB) could shave further time. File as AD-683 if telemetry shows embedding load dominates worker startup.
