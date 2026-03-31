# BF-087 + BF-088: Reset Integration Tests & Test Sleep Cleanup

## Context

Two Wave 4 bug fixes combined into one build prompt because they are both test-only changes with no overlap.

**BF-087:** The tiered reset system (`__main__.py:522`) has tests that only check file deletion mechanics — create dummy file, run reset, assert file gone. No test creates *real subsystem state* (a trust score, an episodic memory, a ward room post), resets, and verifies the state is actually gone. Also: `assignments.db` is created at `startup/communication.py:176` but is not listed in any reset tier.

**BF-088:** Three test files contain `asyncio.sleep(10)` to simulate slow LLM calls in timeout tests. These inflate test runtime even when skipped, and are fragile (~10× longer than the 0.1s timeout they test against).

## Part 1: BF-087 — Reset Integration Tests

### 1a. Fix the `assignments.db` gap

In `src/probos/__main__.py`, add `"assignments.db"` to Tier 2's files list. It is a cognition/identity-era file (stores assignment state), so it belongs alongside `identity.db`, `acm.db`, etc.

```python
# BEFORE (line ~538):
"files": [
    # Cognition (former Shore Leave)
    "session_last.json", "chroma.sqlite3", "cognitive_journal.db",
    "hebbian_weights.db", "trust.db", "service_profiles.db",
    # Identity
    "identity.db", "acm.db", "skills.db", "directives.db",
],

# AFTER:
"files": [
    # Cognition (former Shore Leave)
    "session_last.json", "chroma.sqlite3", "cognitive_journal.db",
    "hebbian_weights.db", "trust.db", "service_profiles.db",
    # Identity
    "identity.db", "acm.db", "skills.db", "directives.db",
    "assignments.db",
],
```

### 1b. Create integration test

Create `tests/test_reset_integration.py`. This test creates *real state files with actual content* (not just `write_text("fake")`), runs each reset tier, and verifies post-reset invariants.

**Key design decisions:**

- Use `tmp_path` for data dir — do NOT touch real data.
- Create real SQLite databases where possible (at minimum: `import sqlite3; conn = sqlite3.connect(str(path)); conn.execute("CREATE TABLE t(x)"); conn.execute("INSERT INTO t VALUES(1)"); conn.commit(); conn.close()`).
- The test must call `_cmd_reset` directly (importing from `probos.__main__`), matching the existing test pattern in `test_proactive.py:TestResetScope`.
- Mock `_load_config_with_fallback` and `_default_data_dir` just like the existing tests do.

**Test structure:**

```python
"""BF-087: Reset integration tests — full state-create-reset-verify cycle."""

import argparse
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _create_sqlite_db(path: Path, table: str = "data", rows: int = 3) -> None:
    """Create a real SQLite database with a table and sample rows."""
    conn = sqlite3.connect(str(path))
    conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, value TEXT)")
    for i in range(rows):
        conn.execute(f"INSERT INTO {table} VALUES (?, ?)", (i, f"row_{i}"))
    conn.commit()
    conn.close()


def _db_has_data(path: Path, table: str = "data") -> bool:
    """Check if a SQLite database exists and has rows."""
    if not path.exists():
        return False
    conn = sqlite3.connect(str(path))
    try:
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
        return cursor.fetchone()[0] > 0
    except Exception:
        return False
    finally:
        conn.close()


def _reset_args(data_dir, **overrides):
    defaults = dict(
        yes=True, soft=False, full=False,
        dry_run=False, wipe_records=False, config=None, data_dir=data_dir,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _run_reset(data_dir, tmp_path, **flag_overrides):
    """Execute _cmd_reset with proper mocks."""
    from probos.__main__ import _cmd_reset

    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir(exist_ok=True)

    args = _reset_args(data_dir, **flag_overrides)
    mock_config = MagicMock()
    mock_config.knowledge.repo_path = str(knowledge_dir)

    with patch("probos.__main__._load_config_with_fallback", return_value=(mock_config, None)):
        with patch("probos.__main__._default_data_dir", return_value=data_dir):
            _cmd_reset(args)
```

**Required test cases (one test class per tier):**

#### Tier 1 (Reboot / --soft)

```python
class TestTier1RebootIntegration:
    """Tier 1: clears transients, preserves cognition + identity + records."""

    def test_clears_tier1_preserves_rest(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Tier 1 targets
        _create_sqlite_db(data_dir / "scheduled_tasks.db", "tasks")
        _create_sqlite_db(data_dir / "events.db", "events")
        cp_dir = data_dir / "checkpoints"
        cp_dir.mkdir()
        (cp_dir / "dag1.json").write_text("{}")

        # Tier 2 files (should survive)
        _create_sqlite_db(data_dir / "trust.db", "trust_scores")
        _create_sqlite_db(data_dir / "identity.db", "agents")
        _create_sqlite_db(data_dir / "hebbian_weights.db", "weights")
        (data_dir / "session_last.json").write_text('{"ts": 1}')

        # Tier 3 files (should survive)
        _create_sqlite_db(data_dir / "ward_room.db", "threads")
        _create_sqlite_db(data_dir / "workforce.db", "items")

        _run_reset(data_dir, tmp_path, soft=True)

        # Tier 1 targets: GONE
        assert not (data_dir / "scheduled_tasks.db").exists()
        assert not (data_dir / "events.db").exists()
        assert not list(cp_dir.glob("*.json"))

        # Tier 2 files: PRESERVED
        assert _db_has_data(data_dir / "trust.db", "trust_scores")
        assert _db_has_data(data_dir / "identity.db", "agents")
        assert _db_has_data(data_dir / "hebbian_weights.db", "weights")
        assert (data_dir / "session_last.json").exists()

        # Tier 3 files: PRESERVED
        assert _db_has_data(data_dir / "ward_room.db", "threads")
        assert _db_has_data(data_dir / "workforce.db", "items")
```

#### Tier 2 (Recommissioning / default)

```python
class TestTier2RecommissioningIntegration:
    """Tier 2: clears cognition + identity (cumulative with Tier 1), preserves records."""

    def test_clears_tier1_and_tier2_preserves_tier3(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Tier 1
        _create_sqlite_db(data_dir / "events.db", "events")

        # Tier 2 targets — ALL of these must be cleared
        for db_name in [
            "trust.db", "identity.db", "hebbian_weights.db",
            "cognitive_journal.db", "service_profiles.db",
            "acm.db", "skills.db", "directives.db", "assignments.db",
        ]:
            _create_sqlite_db(data_dir / db_name, "data")
        (data_dir / "session_last.json").write_text('{"ts": 1}')
        # chroma.sqlite3 (just a file for this test)
        (data_dir / "chroma.sqlite3").write_text("chroma data")
        # semantic dir
        sem_dir = data_dir / "semantic"
        sem_dir.mkdir()
        (sem_dir / "index.dat").write_text("index")

        # Tier 3 (should survive)
        _create_sqlite_db(data_dir / "ward_room.db", "threads")

        _run_reset(data_dir, tmp_path)  # default = Tier 2

        # Tier 1: GONE
        assert not (data_dir / "events.db").exists()

        # Tier 2: GONE
        for db_name in [
            "trust.db", "identity.db", "hebbian_weights.db",
            "cognitive_journal.db", "service_profiles.db",
            "acm.db", "skills.db", "directives.db", "assignments.db",
        ]:
            assert not (data_dir / db_name).exists(), f"{db_name} should be cleared"
        assert not (data_dir / "session_last.json").exists()
        assert not (data_dir / "chroma.sqlite3").exists()

        # Tier 3: PRESERVED
        assert _db_has_data(data_dir / "ward_room.db", "threads")
```

#### Tier 3 (Maiden Voyage / --full)

```python
class TestTier3MaidenVoyageIntegration:
    """Tier 3: clears everything including institutional knowledge."""

    def test_clears_all_tiers(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Tier 1
        _create_sqlite_db(data_dir / "events.db", "events")

        # Tier 2
        _create_sqlite_db(data_dir / "trust.db", "data")
        _create_sqlite_db(data_dir / "identity.db", "data")
        _create_sqlite_db(data_dir / "assignments.db", "data")

        # Tier 3
        _create_sqlite_db(data_dir / "ward_room.db", "threads")
        _create_sqlite_db(data_dir / "workforce.db", "items")
        records_dir = data_dir / "ship-records"
        records_dir.mkdir()
        (records_dir / "log.md").write_text("captain's log")

        _run_reset(data_dir, tmp_path, full=True)

        # ALL tiers: GONE
        assert not (data_dir / "events.db").exists()
        assert not (data_dir / "trust.db").exists()
        assert not (data_dir / "identity.db").exists()
        assert not (data_dir / "assignments.db").exists()
        assert not (data_dir / "ward_room.db").exists()
        assert not (data_dir / "workforce.db").exists()
        # ship-records dir should be cleared
        assert not records_dir.exists() or not list(records_dir.iterdir())

    def test_archives_ward_room_before_clearing(self, tmp_path):
        """Tier 3 archives ward_room.db before deletion (archive_first)."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _create_sqlite_db(data_dir / "ward_room.db", "threads")

        _run_reset(data_dir, tmp_path, full=True)

        assert not (data_dir / "ward_room.db").exists()
        archive_dir = data_dir / "archives"
        assert archive_dir.exists()
        archives = list(archive_dir.glob("ward_room_*.db"))
        assert len(archives) == 1
```

#### Cross-tier invariants

```python
class TestResetInvariants:
    """Cross-tier invariants that must always hold."""

    def test_archives_never_cleared(self, tmp_path):
        """Archives directory survives all tiers."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        archive_dir = data_dir / "archives"
        archive_dir.mkdir()
        (archive_dir / "old_backup.db").write_text("preserved")

        _run_reset(data_dir, tmp_path, full=True)

        assert (archive_dir / "old_backup.db").exists()

    def test_idempotent_reset(self, tmp_path):
        """Running reset twice doesn't crash on missing files."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _create_sqlite_db(data_dir / "trust.db", "data")

        _run_reset(data_dir, tmp_path)
        # Second reset on empty dir — should not crash
        _run_reset(data_dir, tmp_path)

    def test_assignments_db_in_tier2(self):
        """Verify assignments.db is declared in Tier 2 of RESET_TIERS."""
        from probos.__main__ import RESET_TIERS
        tier2_files = RESET_TIERS[2]["files"]
        assert "assignments.db" in tier2_files, (
            "assignments.db must be in Tier 2 — it stores assignment state "
            "which should be cleared on recommissioning"
        )
```

**Total: ~8-10 test functions across 4 classes.**

### Validation (1b)

```bash
uv run pytest tests/test_reset_integration.py -x -v
```

All tests must pass. No existing tests should break.

---

## Part 2: BF-088 — Test Sleep Cleanup

### Problem

Three test files use `asyncio.sleep(10)` inside mock LLM/handler classes to simulate timeout conditions. The actual test timeouts are 0.1s, so the 10s sleep is 100× longer than needed. This wastes time if timeout cancellation is delayed and makes the tests fragile.

### Fix pattern

Replace `asyncio.sleep(10)` with `asyncio.Event().wait()` — blocks forever (until cancelled by the test's timeout), uses zero CPU, cancels cleanly:

```python
# BEFORE:
await asyncio.sleep(10)

# AFTER:
await asyncio.Event().wait()  # blocks until cancelled by timeout
```

### Files to fix

#### 2a. `tests/test_builder_agent.py:657`

```python
# BEFORE (line 655-658):
class _SlowLLM:
    async def complete(self, request):
        await asyncio.sleep(10)
        return LLMResponse(content="")

# AFTER:
class _SlowLLM:
    async def complete(self, request):
        await asyncio.Event().wait()  # blocks until timeout cancels
        return LLMResponse(content="")  # never reached
```

#### 2b. `tests/test_decomposer.py:586`

```python
# BEFORE (line 584-587):
class SlowLLM(MockLLMClient):
    async def complete(self, request):
        await asyncio.sleep(10)
        return await super().complete(request)

# AFTER:
class SlowLLM(MockLLMClient):
    async def complete(self, request):
        await asyncio.Event().wait()  # blocks until timeout cancels
        return await super().complete(request)  # never reached
```

#### 2c. `tests/test_targeted_dispatch.py:61`

```python
# BEFORE (line 60-61):
async def slow_handler(msg):
    await asyncio.sleep(10)  # way too slow

# AFTER:
async def slow_handler(msg):
    await asyncio.Event().wait()  # blocks until timeout cancels
```

### Validation (Part 2)

```bash
uv run pytest tests/test_builder_agent.py::TestSingleChunkExecution::test_timeout tests/test_decomposer.py::TestReflectComplex::test_reflect_timeout_returns_empty tests/test_targeted_dispatch.py::TestTargetedDispatch::test_send_timeout -x -v
```

All three timeout tests must still pass with the same behavior (timeout fires, slow task cancelled, test asserts failure/empty result).

---

## Full validation

```bash
uv run pytest tests/test_reset_integration.py tests/test_builder_agent.py tests/test_decomposer.py tests/test_targeted_dispatch.py -x -v
```

Then run the full suite:

```bash
uv run pytest -n auto -x -q
```

## Critical Rules

1. **Do NOT touch production code** (except adding `"assignments.db"` to `RESET_TIERS` Tier 2).
2. **Do NOT change reset logic** — only add tests that verify existing behavior.
3. **Do NOT add `@pytest.mark.slow`** to the new integration tests — they use `tmp_path` and are fast.
4. **Do NOT change test behavior** in BF-088 — same assertions, same timeout values, just replace the sleep mechanism.
5. **Match existing test patterns** — look at `test_proactive.py:TestResetScope` for the reset test pattern (mock config, mock data dir, `_cmd_reset`).
6. **Use `spec=` on mocks** per BF-079 compliance. If you need a MagicMock for config, use `spec=` where the type is available. For `_load_config_with_fallback` return values, `MagicMock()` is fine (matches existing tests).
