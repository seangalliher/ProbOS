# AD-666: Agent Sensorium Formalization

**Status:** Ready for builder
**Priority:** High (prerequisite for AD-667-672 Ambient Awareness wave)
**Depends:** None (consolidation of existing infrastructure)
**Unlocks:** AD-667 (Named Working Memory Buffers), AD-668-672 (Ambient Awareness wave)

**Files:**
- `src/probos/cognitive/cognitive_agent.py` — sensorium registry, token tracking, health check
- `src/probos/config.py` — `SensoriumConfig`
- `src/probos/events.py` — `SENSORIUM_BUDGET_EXCEEDED` event type
- `tests/test_ad666_sensorium.py` — new test file

## Problem

CognitiveAgent has ~15 context injection methods across 1000+ lines (around lines 2837-3910) that collectively build an agent's "self-state snapshot" before each LLM call. These methods are well-structured but unnamed as a system: there is no formal registry of what injections exist, which cognitive layer each belongs to, or how many tokens the combined injection consumes per cycle.

This creates three gaps:

1. **No inventory.** When adding new context injections (AD-667-672), there is no way to verify whether the new injection overlaps an existing one or what the total token cost is.
2. **No budget enforcement.** The combined injection can silently grow past model context limits. Nothing alerts when sensorium content exceeds a configurable threshold.
3. **No formal classification.** The three-layer model (proprioception/interoception/exteroception) exists in research but is not mapped to the actual code.

## Scope

**In scope:**
- A `SENSORIUM_REGISTRY` class-level dict mapping injection method names to their layer classification
- A `_track_sensorium_budget()` method that measures combined injection char count after state assembly
- A `SensoriumConfig` in config.py with a warning threshold
- A `SENSORIUM_BUDGET_EXCEEDED` event when the threshold is exceeded
- Inline documentation of the three-layer model via the registry itself
- 12 tests

**Out of scope:**
- Restructuring, renaming, or moving any existing injection methods
- Adding new injection content
- Changing injection ordering (audit only; changes deferred to AD-667+)
- Per-method token tracking (future AD — this tracks the aggregate only)
- Working memory changes (AD-667 scope)

### Design Principles

- **Formalization, not rewriting.** Every existing method keeps its name, signature, location, and behavior. This AD names the pattern and adds observability.
- **Single Responsibility.** The registry is data (a dict). The tracking is one method. The config is one class. No new modules.
- **Open/Closed.** Future ADs (667-672) add entries to the registry and new injection methods without modifying tracking logic.
- **Defense in Depth.** Budget tracking is log-and-degrade: emit event + log warning, never block the LLM call.
- **DRY.** The registry is the single source of truth for "what injections exist." No parallel lists.

---

## Section 1: Sensorium Registry

Add a class-level `SENSORIUM_REGISTRY` dict to `CognitiveAgent`. This is a static classification of every injection method, organized by the three-layer model.

**File:** `src/probos/cognitive/cognitive_agent.py`
**Location:** Around line 18-25 (module-level constants area, after imports but before the class), OR as a `ClassVar` inside the class body near the top. Prefer `ClassVar` inside the class to keep it co-located with the methods it describes.

Add this after the existing `ClassVar` declarations (there is `_INTROSPECTIVE_PATTERNS` around line 3643 — but that is deep in the file. Instead, add the registry near the other class-level attributes, around lines 95-110 where the class body begins).

Find the class body start and add:

```python
from enum import StrEnum

class SensoriumLayer(StrEnum):
    """AD-666: Three-layer classification for agent context injections."""
    PROPRIOCEPTION = "proprioception"    # Self-monitoring, identity, cognitive zone
    INTEROCEPTION = "interoception"      # Working memory, episodic recall, reasoning
    EXTEROCEPTION = "exteroception"      # Environment: WR activity, alerts, infrastructure
```

Place the `SensoriumLayer` enum at module level (near the other enum/constant definitions at the top of the file). Then add the registry as a `ClassVar` in the `CognitiveAgent` class body:

```python
# AD-666: Agent Sensorium Registry — formal inventory of all context injections.
# Maps method name -> (layer, description). The sensorium is the agent's
# structured self-state snapshot assembled before each LLM call.
# Three layers:
#   Proprioception: self-monitoring, identity, metrics, cognitive zone
#   Interoception:  working memory, episodic recall, reasoning state
#   Exteroception:  environment — WR activity, alerts, infrastructure, subordinates
SENSORIUM_REGISTRY: ClassVar[dict[str, tuple[str, str]]] = {
    # --- Proprioception (self-awareness) ---
    "_build_temporal_context":       (SensoriumLayer.PROPRIOCEPTION, "Time, age, uptime, crew complement"),
    "_get_comm_proficiency_guidance": (SensoriumLayer.PROPRIOCEPTION, "Communication tier guidance"),
    "_detect_self_in_content":       (SensoriumLayer.PROPRIOCEPTION, "Cross-context self-recognition"),
    "_build_dm_self_monitoring":     (SensoriumLayer.PROPRIOCEPTION, "DM repetition self-detection"),
    "_confabulation_guard":          (SensoriumLayer.PROPRIOCEPTION, "Authority-calibrated confab guard"),
    "_build_crew_complement":        (SensoriumLayer.PROPRIOCEPTION, "Anti-confabulation crew roster"),
    # --- Interoception (internal state) ---
    "_build_cognitive_baseline":     (SensoriumLayer.INTEROCEPTION, "Universal injection: temporal, WM, metrics, ontology"),
    "_build_cognitive_extensions":   (SensoriumLayer.INTEROCEPTION, "Proactive-conditional: self-mon, telemetry, overrides"),
    "_build_cognitive_state":        (SensoriumLayer.INTEROCEPTION, "Meta-method: merges baseline + extensions"),
    "_format_memory_section":        (SensoriumLayer.INTEROCEPTION, "Episodic memories with anchor context"),
    # --- Exteroception (environment) ---
    "_build_situation_awareness":    (SensoriumLayer.EXTEROCEPTION, "WR activity, alerts, events, infra, subordinates"),
    "_build_active_game_context":    (SensoriumLayer.EXTEROCEPTION, "Active game board state"),
    "_build_user_message":           (SensoriumLayer.EXTEROCEPTION, "Primary prompt assembly (DM/WR paths)"),
}
```

**Important:** Use `ClassVar[dict[str, tuple[str, str]]]` which requires importing `ClassVar` from `typing`. Check if it is already imported (it is — used for `_INTROSPECTIVE_PATTERNS` around line 3643). If the existing import is `from typing import ClassVar`, no change needed. If `ClassVar` is imported but the import line needs to be verified, check before adding.

## Section 2: Three-Layer Classification Documentation

No separate doc file. The registry itself IS the documentation. But add a module-level docstring addition to the `SensoriumLayer` enum explaining the three layers with references:

The `SensoriumLayer` enum definition shown in Section 1 already carries the inline comments. No additional file changes needed for this section — the registry dict comments serve as the formalized documentation.

Additionally, add a brief docstring block to `_build_cognitive_state()` (around line 3520) that references the sensorium model:

Find the existing docstring of `_build_cognitive_state`:
```python
def _build_cognitive_state(self, context_parts: dict, observation: dict | None = None) -> dict[str, str]:
    """AD-644 Phase 2 / AD-646: Populate innate faculty observation keys for chain prompts.

    Delegates to baseline (always runs) + extensions (context_parts-dependent).
    Baseline provides agent-intrinsic self-knowledge; extensions override with
    richer versions when proactive.py's context_parts is available.
    """
```

Replace with:
```python
def _build_cognitive_state(self, context_parts: dict, observation: dict | None = None) -> dict[str, str]:
    """AD-644 Phase 2 / AD-646: Populate innate faculty observation keys for chain prompts.

    Delegates to baseline (always runs) + extensions (context_parts-dependent).
    Baseline provides agent-intrinsic self-knowledge; extensions override with
    richer versions when proactive.py's context_parts is available.

    AD-666: This is the interoception hub of the Agent Sensorium — the agent's
    structured self-state snapshot. See SENSORIUM_REGISTRY for the full inventory.
    """
```

## Section 3: Token Budget Tracking

Add a `_track_sensorium_budget()` method to `CognitiveAgent` that measures the combined char count of all sensorium injections after `_build_cognitive_state()` and `_build_situation_awareness()` complete.

**File:** `src/probos/cognitive/cognitive_agent.py`
**Location:** Add the new method after `_build_cognitive_state()` (around line 3536, before `_build_situation_awareness`).

```python
def _track_sensorium_budget(self, cognitive_state: dict[str, str], situation: dict[str, str]) -> int:
    """AD-666: Measure combined sensorium injection size and emit warning if over budget.

    Returns the total char count of all sensorium injections. If the count
    exceeds the configured threshold, emits SENSORIUM_BUDGET_EXCEEDED and
    logs a warning. Never blocks the LLM call — this is observability only.
    """
    total_chars = 0
    for val in cognitive_state.values():
        if isinstance(val, str):
            total_chars += len(val)
    for val in situation.values():
        if isinstance(val, str):
            total_chars += len(val)

    # Check budget
    rt = getattr(self, '_runtime', None)
    threshold = 6000  # default
    if rt and hasattr(rt, 'config') and hasattr(rt.config, 'sensorium'):
        if not rt.config.sensorium.enabled:
            return total_chars
        threshold = rt.config.sensorium.token_budget_warning

    if total_chars > threshold:
        agent_id = getattr(self, 'id', 'unknown')
        callsign = self._resolve_callsign() or agent_id
        logger.warning(
            "AD-666: Sensorium budget exceeded for %s: %d chars (threshold: %d). "
            "Cognitive state: %d chars, situation: %d chars. "
            "Context may be crowding out instruction space.",
            callsign, total_chars, threshold,
            sum(len(v) for v in cognitive_state.values() if isinstance(v, str)),
            sum(len(v) for v in situation.values() if isinstance(v, str)),
        )
        if rt and hasattr(rt, '_emit_event'):
            rt._emit_event(EventType.SENSORIUM_BUDGET_EXCEEDED, {
                "agent_id": agent_id,
                "callsign": callsign,
                "total_chars": total_chars,
                "threshold": threshold,
                "cognitive_state_chars": sum(len(v) for v in cognitive_state.values() if isinstance(v, str)),
                "situation_chars": sum(len(v) for v in situation.values() if isinstance(v, str)),
            })

    return total_chars
```

**Call site:** Wire this method into the chain execution path. In `_execute_chain_with_intent_routing()`, around line 1963-1970, after both `_build_cognitive_state` and `_build_situation_awareness` complete, add the tracking call:

Find this block (around line 1961-1970):
```python
        # AD-646: Universal cognitive baseline — always runs
        _context_parts = _params.get("context_parts", {})
        _cognitive_state = self._build_cognitive_state(_context_parts, observation=observation)
        observation.update(_cognitive_state)

        # AD-644 Phase 3: Situation awareness — environmental perception
        # Only runs when context_parts available (proactive path)
        if _context_parts:
            _situation = self._build_situation_awareness(_context_parts)
            observation.update(_situation)
```

Replace with:
```python
        # AD-646: Universal cognitive baseline — always runs
        _context_parts = _params.get("context_parts", {})
        _cognitive_state = self._build_cognitive_state(_context_parts, observation=observation)
        observation.update(_cognitive_state)

        # AD-644 Phase 3: Situation awareness — environmental perception
        # Only runs when context_parts available (proactive path)
        _situation: dict[str, str] = {}
        if _context_parts:
            _situation = self._build_situation_awareness(_context_parts)
            observation.update(_situation)

        # AD-666: Sensorium budget tracking — observability, never blocks
        self._track_sensorium_budget(_cognitive_state, _situation)
```

**Important:** The `EventType` import must already be in scope. Check the existing imports at the top of `cognitive_agent.py`. There should already be `from probos.events import EventType` (used for `CONFABULATION_SUPPRESSED`, `SELF_MODEL_DRIFT`, etc.). Verify this import exists; if not, add it.

## Section 4: Sensorium Health Event

**File:** `src/probos/events.py`
**Location:** Add the new event type in the "Counselor / Cognitive Health" section, around line 159 (after the last event in that group).

Find the end of the cognitive health events block. The last entry is around line 159:
```python
    DM_CONVERGENCE_DETECTED = "dm_convergence_detected"  # AD-623: DM thread converged
```

After `DM_CONVERGENCE_DETECTED`, add:
```python
    SENSORIUM_BUDGET_EXCEEDED = "sensorium_budget_exceeded"  # AD-666: sensorium injection over char threshold
```

## Section 5: Sensorium Config

**File:** `src/probos/config.py`
**Location:** Add `SensoriumConfig` class after the existing `WorkingMemoryConfig` (around line 681), since sensorium is conceptually adjacent to working memory.

After the `WorkingMemoryConfig` class (ends around line 681), add:

```python
class SensoriumConfig(BaseModel):
    """AD-666: Agent Sensorium tracking configuration."""

    enabled: bool = True  # Track sensorium budget per cognitive cycle
    token_budget_warning: int = 6000  # Char threshold (~1500 tokens) for warning
```

Then register it in `SystemConfig` (around line 1143, near `working_memory`):

Find:
```python
    working_memory: WorkingMemoryConfig = WorkingMemoryConfig()
```

After that line, add:
```python
    sensorium: SensoriumConfig = SensoriumConfig()  # AD-666
```

## Section 6: Injection Ordering Audit

This section does NOT change code. It documents the current injection ordering for the three prompt paths as inline comments in the `_build_user_message` docstring. This gives future ADs a reference for where new injections should be inserted.

**File:** `src/probos/cognitive/cognitive_agent.py`
**Location:** Update the docstring of `_build_user_message` (around line 3793).

Find:
```python
    async def _build_user_message(self, observation: dict) -> str:
        """Build the user message from the observation dict.
        Override in subclasses for custom formatting."""
```

Replace with:
```python
    async def _build_user_message(self, observation: dict) -> str:
        """Build the user message from the observation dict.
        Override in subclasses for custom formatting.

        AD-666 Injection Ordering Audit — three prompt paths:

        Chain path (proactive, via _execute_chain_with_intent_routing):
          1. _build_cognitive_state (baseline + extensions) -> observation keys
          2. _build_situation_awareness -> observation keys
          3. _track_sensorium_budget -> observability
          4. Chain ANALYZE step renders observation keys into prompt

        DM path (direct_message):
          1. Temporal awareness (_build_temporal_context)
          2. Cognitive zone
          3. Introspective telemetry (conditional)
          4. Working memory (render_context)
          5. Episodic memories (_format_memory_section)
          6. Oracle cross-tier context
          7. Source attribution
          8. Session history
          9. Active game context
          10. Captain message

        WR path (ward_room_notification):
          1. Channel + thread header
          2. Temporal awareness (_build_temporal_context)
          3. Cognitive zone
          4. DM self-monitoring (dm- channels only)
          5. Introspective telemetry (conditional)
          6. Working memory (render_context)
          7. Episodic memories (_format_memory_section)
          8. Self-recognition cue
          9. Thread context
          10. Author message
        """
```

## Section 7: Tests

**File:** `tests/test_ad666_sensorium.py` (new file)

```python
"""AD-666: Agent Sensorium Formalization — Tests.

Verifies the sensorium registry, three-layer classification,
token budget tracking, and health event emission.
"""

import pytest
from unittest.mock import MagicMock, patch

from probos.cognitive.cognitive_agent import CognitiveAgent, SensoriumLayer
from probos.events import EventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(**kwargs) -> CognitiveAgent:
    agent = CognitiveAgent(agent_id="test-agent", instructions="Test instructions.")
    agent.callsign = "TestAgent"
    agent.agent_type = "test_agent"
    agent._runtime = kwargs.get("runtime", None)
    return agent


def _make_runtime_with_sensorium_config(enabled=True, threshold=6000):
    rt = MagicMock()
    rt.config.sensorium.enabled = enabled
    rt.config.sensorium.token_budget_warning = threshold
    rt._emit_event = MagicMock()
    return rt


# ---------------------------------------------------------------------------
# Test 1: SensoriumLayer enum has three layers
# ---------------------------------------------------------------------------

class TestSensoriumLayer:

    def test_layer_enum_has_three_values(self):
        assert len(SensoriumLayer) == 3
        assert SensoriumLayer.PROPRIOCEPTION == "proprioception"
        assert SensoriumLayer.INTEROCEPTION == "interoception"
        assert SensoriumLayer.EXTEROCEPTION == "exteroception"


# ---------------------------------------------------------------------------
# Test 2: Registry exists and has expected methods
# ---------------------------------------------------------------------------

class TestSensoriumRegistry:

    def test_registry_is_classvar_dict(self):
        assert isinstance(CognitiveAgent.SENSORIUM_REGISTRY, dict)
        assert len(CognitiveAgent.SENSORIUM_REGISTRY) >= 13

    def test_registry_entries_are_tuples_of_layer_and_description(self):
        for method_name, (layer, desc) in CognitiveAgent.SENSORIUM_REGISTRY.items():
            assert isinstance(method_name, str), f"Key {method_name} is not str"
            assert layer in (
                SensoriumLayer.PROPRIOCEPTION,
                SensoriumLayer.INTEROCEPTION,
                SensoriumLayer.EXTEROCEPTION,
            ), f"Method {method_name} has invalid layer: {layer}"
            assert isinstance(desc, str) and len(desc) > 0, f"Method {method_name} has empty desc"

    def test_all_registry_methods_exist_on_class(self):
        for method_name in CognitiveAgent.SENSORIUM_REGISTRY:
            assert hasattr(CognitiveAgent, method_name), (
                f"Registry references {method_name} but it does not exist on CognitiveAgent"
            )

    def test_registry_has_all_three_layers(self):
        layers_present = {layer for (layer, _) in CognitiveAgent.SENSORIUM_REGISTRY.values()}
        assert SensoriumLayer.PROPRIOCEPTION in layers_present
        assert SensoriumLayer.INTEROCEPTION in layers_present
        assert SensoriumLayer.EXTEROCEPTION in layers_present


# ---------------------------------------------------------------------------
# Test 3: Token budget tracking — under budget (no event)
# ---------------------------------------------------------------------------

class TestTrackSensoriumBudget:

    def test_under_budget_returns_count_no_event(self):
        rt = _make_runtime_with_sensorium_config(threshold=6000)
        agent = _make_agent(runtime=rt)
        cognitive = {"_temporal_context": "x" * 100, "_agent_metrics": "y" * 50}
        situation: dict[str, str] = {}
        result = agent._track_sensorium_budget(cognitive, situation)
        assert result == 150
        rt._emit_event.assert_not_called()

    def test_over_budget_emits_event(self):
        rt = _make_runtime_with_sensorium_config(threshold=100)
        agent = _make_agent(runtime=rt)
        cognitive = {"_temporal_context": "x" * 80, "_agent_metrics": "y" * 50}
        situation = {"_ward_room_activity": "z" * 30}
        result = agent._track_sensorium_budget(cognitive, situation)
        assert result == 160
        rt._emit_event.assert_called_once()
        call_args = rt._emit_event.call_args
        assert call_args[0][0] == EventType.SENSORIUM_BUDGET_EXCEEDED
        payload = call_args[0][1]
        assert payload["total_chars"] == 160
        assert payload["threshold"] == 100
        assert payload["callsign"] == "TestAgent"

    def test_disabled_config_skips_event(self):
        rt = _make_runtime_with_sensorium_config(enabled=False, threshold=10)
        agent = _make_agent(runtime=rt)
        cognitive = {"_big": "x" * 1000}
        result = agent._track_sensorium_budget(cognitive, {})
        assert result == 1000
        rt._emit_event.assert_not_called()

    def test_no_runtime_uses_default_threshold(self):
        agent = _make_agent(runtime=None)
        cognitive = {"_small": "x" * 100}
        result = agent._track_sensorium_budget(cognitive, {})
        assert result == 100  # Under default 6000, no crash

    def test_non_string_values_skipped(self):
        rt = _make_runtime_with_sensorium_config(threshold=6000)
        agent = _make_agent(runtime=rt)
        cognitive = {"_text": "hello", "_none_val": None, "_list_val": ["a", "b"]}
        result = agent._track_sensorium_budget(cognitive, {})
        assert result == 5  # Only "hello" counted

    def test_empty_dicts_returns_zero(self):
        agent = _make_agent(runtime=None)
        result = agent._track_sensorium_budget({}, {})
        assert result == 0


# ---------------------------------------------------------------------------
# Test 4: Event type exists in registry
# ---------------------------------------------------------------------------

class TestSensoriumEventType:

    def test_event_type_exists(self):
        assert hasattr(EventType, "SENSORIUM_BUDGET_EXCEEDED")
        assert EventType.SENSORIUM_BUDGET_EXCEEDED == "sensorium_budget_exceeded"


# ---------------------------------------------------------------------------
# Test 5: Config has sensorium field
# ---------------------------------------------------------------------------

class TestSensoriumConfig:

    def test_sensorium_config_exists(self):
        from probos.config import SensoriumConfig, SystemConfig
        cfg = SensoriumConfig()
        assert cfg.enabled is True
        assert cfg.token_budget_warning == 6000

    def test_system_config_has_sensorium(self):
        from probos.config import SystemConfig
        sc = SystemConfig()
        assert hasattr(sc, 'sensorium')
        assert sc.sensorium.enabled is True
        assert sc.sensorium.token_budget_warning == 6000
```

**Test commands:**
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad666_sensorium.py -v
```

After all tests pass, run the full suite:
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

## Section 8: Tracking Updates

After all tests pass:

**PROGRESS.md** — Add or update the AD-666 entry:
```
| AD-666 | Agent Sensorium Formalization | CLOSED | Sensorium registry, three-layer classification, budget tracking |
```

**docs/development/roadmap.md** — Find the AD-666 row and update status to CLOSED.

**DECISIONS.md** — Add entry:
```
### AD-666: Agent Sensorium Formalization (2026-04-26)
**Decision:** Formalized the existing ~15 context injection methods as a unified
"Agent Sensorium" with a three-layer classification (proprioception/interoception/
exteroception), a class-level SENSORIUM_REGISTRY mapping methods to layers,
char-based budget tracking with SENSORIUM_BUDGET_EXCEEDED event emission, and
SensoriumConfig. No methods were renamed or restructured — this is naming and
observability only. Prerequisite for AD-667-672 Ambient Awareness wave.
```
