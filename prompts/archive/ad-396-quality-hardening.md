# AD-396: Quality Hardening — Subprocess Encoding, Path Safety, Integration Tests

## Context

Dogfooding ScoutAgent (AD-394/395) on Windows exposed 9 integration bugs that unit tests with mocks couldn't catch. Root cause analysis identified four systemic issues:

1. **Windows subprocess encoding** — `text=True` uses `locale.getpreferredencoding()` which is `cp1252` on Windows, not UTF-8. GitHub API and other tools return UTF-8, causing `UnicodeDecodeError` crashes. Scout was fixed in the dogfooding session, but 7 other subprocess calls across 4 files have the same bug.

2. **Hardcoded data paths** — Scout computes `_DATA_DIR` from `__file__` instead of using the Runtime's `_data_dir`. This works when running from the repo root but breaks under installed packages, relocatable deployments, or tests that use `tmp_path`.

3. **Type mismatches at shell↔agent boundary** — `pool.healthy_agents` returns `list[AgentID]` (strings), not agent objects. Shell code was calling `.handle_intent()` on a string. Fixed in dogfooding, but the pattern should be tested.

4. **Personality trait type assumption** — `standing_orders.py` compares personality trait values with `>=` without verifying they're numeric. If a malformed profile passes a string, it crashes.

This AD fixes all known instances and adds integration tests to prevent regression.

## Objectives

### 1. Fix Subprocess Encoding (7 locations)

Replace `text=True` with `encoding="utf-8", errors="replace"` in all subprocess.run calls. This matches the pattern already used correctly in `scout.py` line 248.

**File: `src/probos/credential_store.py` (line ~142)**
```python
# BEFORE:
result = subprocess.run(
    spec.cli_command,
    capture_output=True, text=True, timeout=5,
)
# AFTER:
result = subprocess.run(
    spec.cli_command,
    capture_output=True, encoding="utf-8", errors="replace", timeout=5,
)
```

**File: `src/probos/knowledge/store.py` (line ~479-483)**
```python
# BEFORE:
lambda: subprocess.run(
    ["git", "-C", str(self._repo_path), *args],
    capture_output=True,
    text=True,
    timeout=30,
),
# AFTER:
lambda: subprocess.run(
    ["git", "-C", str(self._repo_path), *args],
    capture_output=True,
    encoding="utf-8",
    errors="replace",
    timeout=30,
),
```

**File: `src/probos/cognitive/dependency_resolver.py` (3 locations: lines ~185, ~202, ~216)**
```python
# All three subprocess.run calls in _install_package():
# BEFORE: capture_output=True, text=True, timeout=120,
# AFTER:  capture_output=True, encoding="utf-8", errors="replace", timeout=120,
```

**File: `src/probos/__main__.py` (2 locations: lines ~561, ~565)**
```python
# Both subprocess.run calls in _handle_reset():
# BEFORE: capture_output=True, text=True, timeout=30,
# AFTER:  capture_output=True, encoding="utf-8", errors="replace", timeout=30,
```

### 2. Fix Scout Data Directory Path

**File: `src/probos/cognitive/scout.py`**

The module-level constants `_DATA_DIR`, `_SEEN_FILE`, `_REPORTS_DIR` (lines 19-21) compute paths from `__file__`. The `_load_seen()` and `_save_seen()` functions (and `perceive()` / `act()` for reports) use these directly.

Change: Accept `data_dir` from the runtime and pass it through.

a) **Remove the module-level `_DATA_DIR` constant** and replace `_SEEN_FILE` / `_REPORTS_DIR` with methods or instance attributes:

```python
# REMOVE these module-level constants:
# _DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
# _SEEN_FILE = _DATA_DIR / "scout_seen.json"
# _REPORTS_DIR = _DATA_DIR / "scout_reports"

# KEEP as module-level fallback for testing:
_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
```

b) **Add `_data_dir` property to ScoutAgent:**

```python
@property
def _data_dir(self) -> Path:
    """Resolve data directory from runtime, falling back to project default."""
    if self.runtime and hasattr(self.runtime, '_data_dir'):
        return Path(self.runtime._data_dir)
    return _DEFAULT_DATA_DIR

@property
def _seen_file(self) -> Path:
    return self._data_dir / "scout_seen.json"

@property
def _reports_dir(self) -> Path:
    return self._data_dir / "scout_reports"
```

c) **Update `_load_seen()` and `_save_seen()` to accept a path parameter:**

```python
def _load_seen(seen_file: Path) -> dict[str, str]:
    """Load seen repos from disk."""
    if seen_file.exists():
        try:
            return json.loads(seen_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}

def _save_seen(seen: dict[str, str], seen_file: Path) -> None:
    """Persist seen repos (keep last 90 days)."""
    ...
    seen_file.parent.mkdir(parents=True, exist_ok=True)
    seen_file.write_text(json.dumps(pruned, indent=2), encoding="utf-8")
```

d) **Update all call sites** in `perceive()` and `act()` to pass `self._seen_file` and `self._reports_dir`.

### 3. Add Personality Trait Type Guard

**File: `src/probos/cognitive/standing_orders.py` (line ~156-162)**

Add a numeric check before comparison:

```python
value = personality.get(trait_name)
if value is None:
    continue
if not isinstance(value, (int, float)):
    continue  # skip malformed trait values
if value >= 0.7:
    guidance.append(f"- {bands['high']}")
elif value <= 0.3:
    guidance.append(f"- {bands['low']}")
```

### 4. Integration Tests

**File: `tests/test_quality_hardening.py`** (NEW)

These tests verify the patterns that dogfooding exposed — boundary interactions that mocks hid.

```python
"""Tests for AD-396: Quality hardening — encoding, paths, type boundaries."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from probos.cognitive.scout import ScoutAgent, _load_seen, _save_seen


# ── 1. Subprocess encoding tests ──

class TestSubprocessEncoding:
    """Verify all subprocess calls handle UTF-8 correctly on Windows."""

    def test_credential_store_uses_utf8(self):
        """CredentialStore CLI resolution uses encoding='utf-8'."""
        from probos.credential_store import CredentialStore, CredentialSpec
        store = CredentialStore(config=MagicMock(), event_log=None)
        spec = CredentialSpec(
            name="test_cred",
            cli_command=["echo", "héllo"],
        )
        store.register(spec)
        with patch("probos.credential_store.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "token123\n"
            mock_run.return_value = mock_result
            store.get("test_cred")
            # Verify encoding args
            call_kwargs = mock_run.call_args
            # Should NOT use text=True, SHOULD use encoding="utf-8"
            if call_kwargs.kwargs:
                assert call_kwargs.kwargs.get("encoding") == "utf-8"
                assert call_kwargs.kwargs.get("errors") == "replace"
                assert "text" not in call_kwargs.kwargs or call_kwargs.kwargs.get("text") is not True
            else:
                # positional — check in args tuple
                pass

    def test_knowledge_store_git_uses_utf8(self):
        """KnowledgeStore._git_run uses encoding='utf-8'."""
        from probos.knowledge.store import KnowledgeStore
        # Verify the _git_run implementation uses encoding param
        import inspect
        source = inspect.getsource(KnowledgeStore._git_run)
        assert "encoding" in source
        assert "text=True" not in source

    def test_dependency_resolver_uses_utf8(self):
        """DependencyResolver install commands use encoding='utf-8'."""
        import inspect
        from probos.cognitive.dependency_resolver import DependencyResolverAgent
        source = inspect.getsource(DependencyResolverAgent._install_package)
        # Count: should have encoding= and NOT text=True
        assert source.count("text=True") == 0
        assert "encoding" in source

    def test_main_reset_uses_utf8(self):
        """__main__ reset subprocess calls use encoding='utf-8'."""
        import inspect
        from probos.__main__ import _handle_reset
        source = inspect.getsource(_handle_reset)
        assert "text=True" not in source


# ── 2. Scout data directory tests ──

class TestScoutDataDirectory:
    """Verify Scout uses runtime data_dir, not hardcoded __file__ paths."""

    def test_scout_uses_runtime_data_dir(self, tmp_path: Path):
        """ScoutAgent resolves _data_dir from runtime when available."""
        mock_runtime = MagicMock()
        mock_runtime._data_dir = tmp_path / "data"
        agent = ScoutAgent(runtime=mock_runtime)
        assert agent._data_dir == tmp_path / "data"

    def test_scout_falls_back_to_default(self):
        """ScoutAgent falls back to project default when runtime is None."""
        agent = ScoutAgent(runtime=None)
        assert agent._data_dir.name == "data"

    def test_seen_file_uses_data_dir(self, tmp_path: Path):
        """_load_seen and _save_seen use provided path."""
        seen_file = tmp_path / "scout_seen.json"
        assert _load_seen(seen_file) == {}
        _save_seen({"owner/repo": "2026-03-22T00:00:00+00:00"}, seen_file)
        loaded = _load_seen(seen_file)
        assert "owner/repo" in loaded

    def test_reports_dir_uses_data_dir(self, tmp_path: Path):
        """ScoutAgent._reports_dir resolves from runtime data_dir."""
        mock_runtime = MagicMock()
        mock_runtime._data_dir = tmp_path / "data"
        agent = ScoutAgent(runtime=mock_runtime)
        assert agent._reports_dir == tmp_path / "data" / "scout_reports"


# ── 3. Standing orders personality type safety ──

class TestPersonalityTypeSafety:
    """Verify personality trait comparison handles non-numeric values."""

    def test_string_trait_skipped(self):
        """String personality trait values don't crash compose_agent_identity."""
        from probos.cognitive.standing_orders import compose_agent_identity
        profile = {
            "agent_type": "test",
            "personality": {
                "openness": "high",  # string instead of float
                "conscientiousness": 0.8,
            },
        }
        # Should not raise TypeError
        result = compose_agent_identity(profile)
        assert "test" in result.lower()

    def test_none_trait_skipped(self):
        """None personality trait values are skipped cleanly."""
        from probos.cognitive.standing_orders import compose_agent_identity
        profile = {
            "agent_type": "test",
            "personality": {
                "openness": None,
                "conscientiousness": 0.8,
            },
        }
        result = compose_agent_identity(profile)
        assert "test" in result.lower()

    def test_valid_traits_produce_guidance(self):
        """Valid numeric traits produce behavioral guidance."""
        from probos.cognitive.standing_orders import compose_agent_identity
        profile = {
            "agent_type": "test",
            "personality": {
                "openness": 0.9,
                "conscientiousness": 0.2,
            },
        }
        result = compose_agent_identity(profile)
        assert "Behavioral Style:" in result


# ── 4. Shell↔Agent boundary tests ──

class TestShellAgentBoundary:
    """Verify shell correctly constructs IntentMessage and looks up agents."""

    def test_intent_message_has_intent_attr(self):
        """IntentMessage dataclass has .intent attribute (not dict key)."""
        from probos.types import IntentMessage
        msg = IntentMessage(intent="test_intent", params={}, context="test")
        assert hasattr(msg, "intent")
        assert msg.intent == "test_intent"

    def test_healthy_agents_returns_ids(self):
        """pool.healthy_agents returns AgentID strings, not agent objects."""
        from probos.pools import AgentPool
        pool = AgentPool(
            pool_type="test",
            display_name="Test",
            llm_client=MagicMock(),
            min_agents=0,
            max_agents=1,
        )
        # healthy_agents should be iterable of agent IDs (strings)
        agents = pool.healthy_agents
        for aid in agents:
            assert isinstance(aid, str)
```

### 5. Update Existing Scout Tests

**File: `tests/test_scout.py`**

Update the `TestSeenTracking` test to pass `seen_file` as parameter to `_load_seen` and `_save_seen` (matching the new signatures from Section 2c):

```python
class TestSeenTracking:
    def test_seen_tracking(self, tmp_path: Path):
        seen_file = tmp_path / "scout_seen.json"
        from probos.cognitive.scout import _load_seen, _save_seen
        assert _load_seen(seen_file) == {}
        seen = {"owner/repo1": "2026-03-22T00:00:00+00:00"}
        _save_seen(seen, seen_file)
        loaded = _load_seen(seen_file)
        assert "owner/repo1" in loaded
```

Remove the `with patch("probos.cognitive.scout._SEEN_FILE", seen_file):` wrapper since `_SEEN_FILE` is no longer a module-level constant.

## Files to Create

| File | Purpose |
|------|---------|
| `tests/test_quality_hardening.py` | Integration tests for encoding, paths, types, boundaries |

## Files to Modify

| File | Change |
|------|--------|
| `src/probos/credential_store.py` | `text=True` → `encoding="utf-8", errors="replace"` |
| `src/probos/knowledge/store.py` | `text=True` → `encoding="utf-8", errors="replace"` |
| `src/probos/cognitive/dependency_resolver.py` | 3× `text=True` → `encoding="utf-8", errors="replace"` |
| `src/probos/__main__.py` | 2× `text=True` → `encoding="utf-8", errors="replace"` |
| `src/probos/cognitive/scout.py` | Replace hardcoded `_DATA_DIR` with runtime-resolved properties |
| `src/probos/cognitive/standing_orders.py` | Add `isinstance` type guard for personality traits |
| `tests/test_scout.py` | Update `TestSeenTracking` for new `_load_seen`/`_save_seen` signatures |

## Testing Requirements

Run existing tests first to confirm nothing breaks, then run the new test file:

```bash
python -m pytest tests/test_quality_hardening.py tests/test_scout.py tests/test_credential_store.py -v
```

All existing tests must continue to pass. New tests must all pass.

## What NOT to Change

- Do NOT refactor any code beyond the specific fixes listed above
- Do NOT add new features, docstrings, or comments to unchanged code
- Do NOT change subprocess calls that already use `encoding=` or manual `.decode()` (those are safe)
- Do NOT modify the builder.py subprocess calls (they already use raw bytes + `.decode()`)
- Do NOT change shell_command.py or red_team.py subprocess calls (they already use raw bytes)
- Do NOT add import statements beyond what's needed for the isinstance check
- Do NOT rename existing functions (keep `_load_seen` / `_save_seen` names)
