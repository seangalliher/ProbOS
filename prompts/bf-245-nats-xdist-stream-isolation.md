# BF-245: NATS JetStream Stream Isolation Under pytest-xdist

## Problem

pytest-xdist (`-n auto` in `pyproject.toml`) spawns one worker per CPU core. Integration tests that call `ProbOSRuntime.start()` trigger `init_nats()` which calls `recreate_stream()` for three hardcoded JetStream stream names: `SYSTEM_EVENTS`, `WARDROOM`, `INTENT_DISPATCH`. When multiple workers execute concurrently against the same NATS server, a race condition occurs:

1. Worker A calls `_delete_stream("SYSTEM_EVENTS")` — succeeds
2. Worker B calls `_delete_stream("SYSTEM_EVENTS")` — benign 404
3. Worker A calls `add_stream(SYSTEM_EVENTS)` — succeeds
4. Worker B calls `add_stream(SYSTEM_EVENTS)` — **fails: error 10058 "stream name already in use with a different configuration"**

The `recreate_stream()` method (BF-232) propagates this exception, crashing the worker. All tests assigned to that worker report as FAILED/ERROR — producing 20-50 flaky failures per run that all pass individually.

**Affected tests:** Any test that instantiates `ProbOSRuntime` and calls `start()` — `test_runtime.py`, `test_persistent_identity.py`, `test_dreaming.py`, `test_escalation.py`, `test_system_qa.py`, `test_consensus_integration.py`, `test_cognitive_integration.py`, `test_distribution.py`, and others.

**Not affected:** Tests using `MockNATSBus` (in-memory, no server interaction) or tests that mock the runtime without calling `start()`.

## Root Cause

Stream names are hardcoded literals in `src/probos/startup/nats.py` (lines 58-75). The `NATSBus` class has a `subject_prefix` mechanism that isolates NATS subjects (e.g., `probos.local.wardroom.events.>`), but stream names themselves are not prefixed or parameterized. All workers share the same NATS server and the same stream namespace.

## Prior Art

- **BF-043** (Closed): Added pytest-xdist + pytest-timeout. Introduced `-n auto`. Did not address NATS stream isolation.
- **BF-232** (Closed): Introduced `recreate_stream()` (delete-then-create) to fix stale subject filters. This pattern is correct for single-instance startup but creates the race window under xdist.
- **BF-229/230/231/241/242** (All Closed): NATS resilience stack. Production-ready. None address test-time parallelism.

## Fix

Guard NATS initialization to be safe under pytest-xdist by skipping real NATS connections in test workers. Integration tests that call `ProbOSRuntime.start()` should use `MockNATSBus` when a real NATS server is not the system under test.

### Section 1: Disable real NATS in test configuration

The simplest and most robust fix: set `PROBOS_NATS_ENABLED=false` at conftest import time so `init_nats()` returns `None` for all workers. This must be module-level (`os.environ.setdefault`), NOT an autouse fixture, because session/module-scoped fixtures may construct `SystemConfig` before a per-test autouse fixture runs. Using `setdefault` allows developers to opt-in to real NATS with `PROBOS_NATS_ENABLED=true pytest`.

Tests that specifically test NATS behavior use `MockNATSBus` directly and don't go through `init_nats()`.

**File: `tests/conftest.py`**

SEARCH:
```python
"""Shared test fixtures."""

import pytest

from unittest.mock import MagicMock, AsyncMock

from probos.substrate.registry import AgentRegistry
from probos.substrate.spawner import AgentSpawner
from probos.config import PoolConfig
```

REPLACE:
```python
"""Shared test fixtures."""

import os
import pytest

from unittest.mock import MagicMock, AsyncMock

from probos.substrate.registry import AgentRegistry
from probos.substrate.spawner import AgentSpawner
from probos.config import PoolConfig

# BF-245: Disable real NATS in tests at import time, before any fixtures run.
# Module-level (not autouse fixture) so session/module-scoped fixtures that
# construct SystemConfig see the override. setdefault allows opt-in:
#   PROBOS_NATS_ENABLED=true pytest tests/test_nats_integration.py
os.environ.setdefault("PROBOS_NATS_ENABLED", "false")
```

Add a `real_nats` fixture for tests that need to opt-in to real NATS connections:

```python
@pytest.fixture
def real_nats(monkeypatch):
    """Opt-in fixture: re-enable real NATS for a specific test.

    Usage: add `real_nats` to a test's parameter list. The test will
    use the real NATSBus instead of being blocked by BF-245's global
    PROBOS_NATS_ENABLED=false default.
    """
    monkeypatch.setenv("PROBOS_NATS_ENABLED", "true")
```

Place this fixture after the existing `pool_config` fixture (around line 41).

### Section 2: Honor environment override in NatsConfig

The `NatsConfig` default for `enabled` must respect the environment variable so the conftest-level env var takes effect without requiring every test to mock config. Note: the live docstring says "AD-637" — preserve that, do not change to "AD-637a".

**File: `src/probos/config.py`**

Find the `NatsConfig` class and its `enabled` field. The current definition:

SEARCH:
```python
class NatsConfig(BaseModel):
    """NATS event bus configuration (AD-637)."""

    enabled: bool = False
```

REPLACE:
```python
class NatsConfig(BaseModel):
    """NATS event bus configuration (AD-637)."""

    enabled: bool = Field(
        default=False,
        validate_default=True,
        description="Enable NATS event bus. Overridden by PROBOS_NATS_ENABLED env var.",
    )

    @field_validator("enabled", mode="before")
    @classmethod
    def _env_override_enabled(cls, v: Any) -> Any:
        """BF-245: Allow env var to force-disable NATS in test workers."""
        env_val = os.environ.get("PROBOS_NATS_ENABLED")
        if env_val is not None:
            return env_val.lower() in ("true", "1", "yes")
        return v
```

**Why `validate_default=True`:** Without it, Pydantic's `field_validator(mode="before")` skips the default value entirely. `NatsConfig()` with no arguments would bypass the env var override — the very path exercised by `SystemConfig()` during normal test startup.

Add `os` to the imports at the top of `config.py`:

SEARCH:
```python
"""Configuration loader for ProbOS."""

from __future__ import annotations

from pathlib import Path
from typing import Any
```

REPLACE:
```python
"""Configuration loader for ProbOS."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
```

The `Field`, `field_validator`, and `Any` imports are already present.

### Section 3: Fix affected NATS config test

The autouse fixture sets `PROBOS_NATS_ENABLED=false` globally. One existing test asserts that `config.nats.enabled is True` after loading YAML — this will fail because the `field_validator` overrides the YAML value. Clear the env var in that test.

**File: `tests/test_ad637a_nats_foundation.py`**

SEARCH:
```python
    def test_loads_from_yaml(self, tmp_path):
        """Test 14: load_config parses nats section from system.yaml."""
```

REPLACE:
```python
    def test_loads_from_yaml(self, tmp_path, monkeypatch):
        """Test 14: load_config parses nats section from system.yaml."""
        # BF-245: Clear the autouse env var so YAML-loaded enabled=true is respected
        monkeypatch.delenv("PROBOS_NATS_ENABLED", raising=False)
```

### Section 4: Verified — MockNATSBus parity

**No code changes needed.** `MockNATSBus.recreate_stream()` exists at `src/probos/mesh/nats_bus.py` line 1210 and follows the same interface as the real `NATSBus.recreate_stream()`. Confirmed during prompt review.

## What This Does NOT Change

- **Production NATS behavior**: `init_nats()` logic is unchanged. The env var override only fires when `PROBOS_NATS_ENABLED` is explicitly set. Note: `system.yaml` has `nats.enabled: true` for production — this is NOT affected because the env var is only set in `tests/conftest.py`.
- **MockNATSBus**: No changes to the mock. Tests that use `MockNATSBus` directly continue to work as-is.
- **NATS-specific test files**: `test_ad637a_nats_foundation.py`, `test_ad637c_wardroom_nats.py`, etc. use `MockNATSBus` directly and don't go through `init_nats()`. One test (`test_loads_from_yaml`) asserts `config.nats.enabled is True` after YAML load — Section 3 fixes this by clearing the env var in that test.
- **`-n auto` configuration**: xdist parallelism stays enabled. This fix makes parallelism safe rather than disabling it.
- **Stream name hardcoding**: Stream names remain hardcoded. Per-worker stream name suffixing is unnecessary complexity when the simpler fix (disable real NATS in tests) achieves the goal.
- **`init_nats()` logging**: When disabled, logs at `info` level ("Startup [nats]: disabled") — not warning.

## Do Not Build

- **Do not add per-worker stream name suffixes** (e.g., `SYSTEM_EVENTS_worker0`). This adds complexity to production code for a test-only problem.
- **Do not start a NATS server per xdist worker.** Heavyweight, flaky, unnecessary.
- **Do not disable pytest-xdist.** Parallel tests are a standing engineering principle (BF-043). Fix the isolation, not the parallelism.
- **Do not add locking/coordination between xdist workers** for stream creation. Workers are separate processes — cross-process locking is fragile.

## Acceptance Criteria

- [ ] `pytest tests/ -n auto` completes with 0 NATS-related failures (baseline: 20-50 flaky failures per run from xdist worker crashes — all should be eliminated)
- [ ] `pytest tests/test_runtime.py -v` passes (integration tests work without real NATS)
- [ ] `pytest tests/test_ad637a_nats_foundation.py -v` passes (NATS-specific tests unaffected)
- [ ] `pytest tests/test_new_crew_auto_welcome.py -v` passes (finalize tests unaffected)
- [ ] `test_ad637a_nats_foundation.py::TestNatsConfig::test_loads_from_yaml` passes (env var cleared for YAML test)
- [ ] No production behavior change when `PROBOS_NATS_ENABLED` is not set
- [ ] `NatsConfig()` with no arguments respects `PROBOS_NATS_ENABLED` env var (validate_default=True)
- [ ] 8 new tests

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Tests

All tests go in **`tests/test_bf245_nats_xdist_isolation.py`**.

Module-level imports for the test file:
```python
"""BF-245: NATS/xdist stream isolation tests."""

import os

import pytest

from probos.config import NatsConfig
```

### Test 1: Environment override disables NATS
```python
def test_nats_config_env_override_disables(monkeypatch):
    """BF-245: PROBOS_NATS_ENABLED=false overrides config enabled=True."""
    monkeypatch.setenv("PROBOS_NATS_ENABLED", "false")
    cfg = NatsConfig(enabled=True)
    assert cfg.enabled is False
```

### Test 2: Environment override enables NATS
```python
def test_nats_config_env_override_enables(monkeypatch):
    """BF-245: PROBOS_NATS_ENABLED=true overrides config enabled=False."""
    monkeypatch.setenv("PROBOS_NATS_ENABLED", "true")
    cfg = NatsConfig(enabled=False)
    assert cfg.enabled is True
```

### Test 3: No environment variable preserves config value
```python
def test_nats_config_no_env_preserves_default(monkeypatch):
    """BF-245: Without env var, config value is used as-is."""
    monkeypatch.delenv("PROBOS_NATS_ENABLED", raising=False)
    cfg = NatsConfig(enabled=True)
    assert cfg.enabled is True
```

### Test 4: No-arg NatsConfig respects env var (validate_default)
```python
def test_nats_config_no_arg_respects_env(monkeypatch):
    """BF-245: NatsConfig() with no args still checks PROBOS_NATS_ENABLED."""
    monkeypatch.setenv("PROBOS_NATS_ENABLED", "true")
    cfg = NatsConfig()
    assert cfg.enabled is True
```

### Test 5: init_nats returns None when disabled
```python
@pytest.mark.asyncio
async def test_init_nats_returns_none_when_disabled(monkeypatch):
    """BF-245: init_nats skips connection when NATS disabled via env."""
    monkeypatch.setenv("PROBOS_NATS_ENABLED", "false")
    from probos.startup.nats import init_nats
    from probos.config import SystemConfig
    config = SystemConfig()
    result = await init_nats(config)
    assert result is None
```

### Test 6: Autouse env var is set at conftest import time
```python
def test_conftest_sets_nats_disabled():
    """BF-245: conftest.py sets PROBOS_NATS_ENABLED=false at import time."""
    assert os.environ.get("PROBOS_NATS_ENABLED") == "false"
```

### Test 7: Runtime startup works without NATS (no recreate_stream calls)
```python
@pytest.mark.asyncio
async def test_runtime_starts_without_nats(tmp_path, monkeypatch):
    """BF-245: ProbOSRuntime.start() succeeds with NATS disabled, no stream creation."""
    from unittest.mock import patch
    from probos.runtime import ProbOSRuntime
    with patch("probos.startup.nats.NATSBus") as mock_bus_cls:
        rt = ProbOSRuntime(data_dir=tmp_path / "data")
        await rt.start()
        assert rt._started
        assert rt.nats_bus is None
        # Verify no real NATS connections were attempted
        mock_bus_cls.assert_not_called()
        await rt.stop()
```

### Test 8: real_nats fixture re-enables NATS
```python
def test_real_nats_fixture_enables(real_nats):
    """BF-245: real_nats fixture sets PROBOS_NATS_ENABLED=true."""
    assert os.environ.get("PROBOS_NATS_ENABLED") == "true"
```

**Test file:** `tests/test_bf245_nats_xdist_isolation.py` (8 tests)

**Run command:**
```bash
pytest tests/test_bf245_nats_xdist_isolation.py -v -x
```

**Full suite gate:**
```bash
pytest tests/ -n auto -x -q
```

## Tracker Updates

### PROGRESS.md
Add at top:
```
BF-245 CLOSED. NATS/xdist stream isolation — module-level `os.environ.setdefault("PROBOS_NATS_ENABLED", "false")` in conftest.py prevents real NATS connections during tests. NatsConfig.enabled field_validator with validate_default=True honors env override. Eliminates xdist worker crashes (20-50 per run) from JetStream stream name collisions. 8 tests.
```

### DECISIONS.md
Add entry:
```
### BF-245: NATS Test Isolation Strategy (2026-04-27)
**Decision:** Disable real NATS in tests via module-level env var override in conftest.py rather than per-worker stream name suffixing or xdist serialization.
**Rationale:** The problem is test-only — production code should not carry per-worker complexity. Tests that verify NATS behavior use MockNATSBus directly. Integration tests (ProbOSRuntime.start()) don't need real NATS to validate their concerns. See also: AD-637 (NATS foundation), BF-232 (recreate_stream pattern).
**Alternatives rejected:** (1) Per-worker stream name suffixes — pollutes production code. (2) Disable xdist — loses parallelism benefit (BF-043). (3) Cross-process locking — fragile IPC for a test concern. (4) Per-worker NATS server — heavyweight, flaky.
```

### docs/development/roadmap.md
Add to Bug Tracker table:
```
| BF-245 | NATS/xdist stream isolation. pytest-xdist workers race on hardcoded JetStream stream names (`SYSTEM_EVENTS`, `WARDROOM`, `INTENT_DISPATCH`), causing `recreate_stream()` error 10058 crashes (~20-50 flaky failures per run). **Fix:** Module-level `os.environ.setdefault("PROBOS_NATS_ENABLED", "false")` in conftest.py. `NatsConfig.enabled` `field_validator` with `validate_default=True` honors override. `real_nats` fixture for opt-in. | Medium | **Closed** |
```
