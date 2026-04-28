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

The simplest and most robust fix: configure `nats.enabled = False` in the test environment so `init_nats()` returns `None`. Tests that specifically test NATS behavior already use `MockNATSBus` directly.

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


@pytest.fixture(autouse=True)
def _disable_nats_in_tests(monkeypatch):
    """Prevent real NATS connections during tests.

    Integration tests that call ProbOSRuntime.start() would otherwise
    trigger init_nats() which creates JetStream streams. Under pytest-xdist,
    multiple workers racing to create/delete the same streams causes
    'stream name already in use' errors (BF-245).

    Tests that specifically test NATS behavior use MockNATSBus directly
    and don't go through init_nats().
    """
    monkeypatch.setenv("PROBOS_NATS_ENABLED", "false")
```

### Section 2: Honor environment override in NatsConfig

The `NatsConfig` default for `enabled` must respect the environment variable so the autouse fixture takes effect without requiring every test to mock config.

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
    """NATS event bus configuration (AD-637a)."""

    enabled: bool = Field(
        default=False,
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

### Section 4: Verify MockNATSBus parity

Verify that `MockNATSBus.recreate_stream()` exists and behaves correctly (it should — BF-232 added parity). No code changes expected; this is a verification step.

**File: `src/probos/mesh/nats_bus.py`**

Read the `MockNATSBus` class and confirm it has `recreate_stream()`. If missing, add it following the existing `ensure_stream()` pattern in `MockNATSBus`.

## What This Does NOT Change

- **Production NATS behavior**: `init_nats()` logic is unchanged. The env var override only fires when `PROBOS_NATS_ENABLED` is explicitly set.
- **MockNATSBus**: No changes to the mock. Tests that use `MockNATSBus` directly continue to work as-is.
- **NATS-specific test files**: `test_ad637a_nats_foundation.py`, `test_ad637c_wardroom_nats.py`, etc. use `MockNATSBus` directly and don't go through `init_nats()`. One test (`test_loads_from_yaml`) asserts `config.nats.enabled is True` after YAML load — Section 3 fixes this by clearing the env var in that test.
- **`-n auto` configuration**: xdist parallelism stays enabled. This fix makes parallelism safe rather than disabling it.
- **Stream name hardcoding**: Stream names remain hardcoded. Per-worker stream name suffixing is unnecessary complexity when the simpler fix (disable real NATS in tests) achieves the goal.

## Do Not Build

- **Do not add per-worker stream name suffixes** (e.g., `SYSTEM_EVENTS_worker0`). This adds complexity to production code for a test-only problem.
- **Do not start a NATS server per xdist worker.** Heavyweight, flaky, unnecessary.
- **Do not disable pytest-xdist.** Parallel tests are a standing engineering principle (BF-043). Fix the isolation, not the parallelism.
- **Do not add locking/coordination between xdist workers** for stream creation. Workers are separate processes — cross-process locking is fragile.

## Acceptance Criteria

- [ ] `pytest tests/ -n auto` completes with 0 NATS-related failures (xdist worker crashes eliminated)
- [ ] `pytest tests/test_runtime.py -v` passes (integration tests work without real NATS)
- [ ] `pytest tests/test_ad637a_nats_foundation.py -v` passes (NATS-specific tests unaffected)
- [ ] `pytest tests/test_new_crew_auto_welcome.py -v` passes (finalize tests unaffected)
- [ ] `test_ad637a_nats_foundation.py::TestNatsConfig::test_loads_from_yaml` passes (env var cleared for YAML test)
- [ ] No production behavior change when `PROBOS_NATS_ENABLED` is not set
- [ ] 6 new tests

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Tests

### Test 1: Environment override disables NATS
```python
def test_nats_config_env_override_disables(monkeypatch):
    """BF-245: PROBOS_NATS_ENABLED=false overrides config enabled=True."""
    monkeypatch.setenv("PROBOS_NATS_ENABLED", "false")
    from probos.config import NatsConfig
    cfg = NatsConfig(enabled=True)
    assert cfg.enabled is False
```

### Test 2: Environment override enables NATS
```python
def test_nats_config_env_override_enables(monkeypatch):
    """BF-245: PROBOS_NATS_ENABLED=true overrides config enabled=False."""
    monkeypatch.setenv("PROBOS_NATS_ENABLED", "true")
    from probos.config import NatsConfig
    cfg = NatsConfig(enabled=False)
    assert cfg.enabled is True
```

### Test 3: No environment variable preserves config value
```python
def test_nats_config_no_env_preserves_default(monkeypatch):
    """BF-245: Without env var, config value is used as-is."""
    monkeypatch.delenv("PROBOS_NATS_ENABLED", raising=False)
    from probos.config import NatsConfig
    cfg = NatsConfig(enabled=True)
    assert cfg.enabled is True
```

### Test 4: init_nats returns None when disabled
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

### Test 5: Autouse fixture sets environment variable
```python
def test_autouse_fixture_disables_nats():
    """BF-245: The autouse fixture sets PROBOS_NATS_ENABLED=false."""
    import os
    assert os.environ.get("PROBOS_NATS_ENABLED") == "false"
```

### Test 6: Runtime startup works without NATS
```python
@pytest.mark.asyncio
async def test_runtime_starts_without_nats(tmp_path):
    """BF-245: ProbOSRuntime.start() succeeds with NATS disabled."""
    from probos.runtime import ProbOSRuntime
    rt = ProbOSRuntime(data_dir=tmp_path / "data")
    await rt.start()
    assert rt._started
    assert rt.nats_bus is None
    await rt.stop()
```

**Test file:** `tests/test_bf245_nats_xdist_isolation.py`

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
BF-245 CLOSED. NATS/xdist stream isolation — autouse fixture sets PROBOS_NATS_ENABLED=false to prevent real NATS connections during tests. NatsConfig.enabled field_validator honors env override. Eliminates xdist worker crashes from JetStream stream name collisions. 6 tests.
```

### DECISIONS.md
Add entry:
```
### BF-245: NATS Test Isolation Strategy (2026-04-27)
**Decision:** Disable real NATS in tests via autouse fixture + env var override rather than per-worker stream name suffixing or xdist serialization.
**Rationale:** The problem is test-only — production code should not carry per-worker complexity. Tests that verify NATS behavior use MockNATSBus directly. Integration tests (ProbOSRuntime.start()) don't need real NATS to validate their concerns.
**Alternatives rejected:** (1) Per-worker stream name suffixes — pollutes production code. (2) Disable xdist — loses parallelism benefit (BF-043). (3) Cross-process locking — fragile IPC for a test concern. (4) Per-worker NATS server — heavyweight, flaky.
```

### docs/development/roadmap.md
Add to Bug Tracker table:
```
| BF-245 | NATS/xdist stream isolation. pytest-xdist workers race on hardcoded JetStream stream names (`SYSTEM_EVENTS`, `WARDROOM`, `INTENT_DISPATCH`), causing `recreate_stream()` error 10058 crashes. **Fix:** Autouse fixture disables real NATS in tests via `PROBOS_NATS_ENABLED=false` env var. `NatsConfig.enabled` `field_validator` honors override. | Medium | **Closed** |
```
