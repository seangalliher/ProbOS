# BF-079 Phase 2/3: Mock Discipline — Inline Runtime & Service Mocks

## Context

Phase 1 (CLOSED) spec'd 18 mock factories across 14 test files. BF-085 (CLOSED) added 87 class-level type annotations to `ProbOSRuntime`, making `MagicMock(spec=ProbOSRuntime)` viable. This phase tackles inline mocks throughout the test suite.

**Proof spec=ProbOSRuntime works:** `test_decomposer.py` already uses it at 23 locations (lines 856-1282), all passing.

## Scope

~140 unspec'd `rt = MagicMock()` / `runtime = MagicMock()` across ~50 test files, plus ~200 service-level sub-mocks (`rt.trust_network = MagicMock()`, etc.) that should use their own specs.

## Phase 2: Shared Runtime Fixture + Runtime Mock Specs

### Step 1: Create `conftest.py` shared fixture

Add a `mock_runtime` fixture to `tests/conftest.py` that provides a properly spec'd runtime mock with all common service sub-mocks pre-configured. This eliminates the massive duplication of inline runtime mock setup.

```python
from unittest.mock import MagicMock, AsyncMock, PropertyMock

@pytest.fixture
def mock_runtime():
    """Shared spec'd ProbOSRuntime mock (BF-079 Phase 2)."""
    from probos.runtime import ProbOSRuntime
    from probos.substrate.registry import AgentRegistry
    from probos.consensus.trust import TrustNetwork
    from probos.ward_room import WardRoomService
    from probos.ward_room_router import WardRoomRouter
    from probos.cognitive.episodic import EpisodicMemory
    from probos.crew_profile import CallsignRegistry
    from probos.mesh.intent import IntentBus
    from probos.mesh.signal import SignalManager
    from probos.hebbian import HebbianRouter
    from probos.event_log import EventLog
    from probos.config import SystemConfig
    from probos.substrate.spawner import AgentSpawner
    from probos.substrate.pool import ResourcePool
    from probos.notification import NotificationQueue

    rt = MagicMock(spec=ProbOSRuntime)

    # Pre-configure common service sub-mocks with their own specs
    rt.registry = MagicMock(spec=AgentRegistry)
    rt.registry.all.return_value = []
    rt.registry.get.return_value = None

    rt.trust_network = MagicMock(spec=TrustNetwork)
    rt.trust_network.get_trust.return_value = 0.5
    rt.trust_network.get_or_create.return_value = MagicMock(trust_score=0.5)

    rt.ward_room = AsyncMock(spec=WardRoomService)
    rt.ward_room_router = MagicMock(spec=WardRoomRouter)

    rt.episodic_memory = AsyncMock(spec=EpisodicMemory)
    rt.episodic_memory.recall.return_value = []

    rt.callsign_registry = MagicMock(spec=CallsignRegistry)
    rt.callsign_registry.resolve.return_value = None
    rt.callsign_registry.all_callsigns.return_value = {}

    rt.intent_bus = MagicMock(spec=IntentBus)
    rt.signal_manager = MagicMock(spec=SignalManager)
    rt.hebbian_router = MagicMock(spec=HebbianRouter)
    rt.event_log = AsyncMock(spec=EventLog)

    rt.config = MagicMock(spec=SystemConfig)
    rt.config.onboarding = MagicMock()
    rt.config.onboarding.enabled = True
    rt.config.onboarding.naming_ceremony = True
    rt.config.proactive = MagicMock()
    rt.config.proactive.enabled = False

    rt.spawner = MagicMock(spec=AgentSpawner)
    rt.pools = {}
    rt.pool_groups = MagicMock()

    rt.notification_queue = MagicMock(spec=NotificationQueue)
    rt.llm_client = AsyncMock()

    # Deferred services (None by default, tests set as needed)
    rt.ontology = None
    rt.acm = None
    rt.bridge_alerts = None
    rt.dream_scheduler = None
    rt.proactive_loop = None
    rt.codebase_index = None
    rt.self_mod_pipeline = None
    rt.self_mod_manager = None
    rt.dream_adapter = None
    rt.onboarding = None
    rt.warm_boot = None
    rt.feedback_engine = None
    rt.sif = None
    rt.initiative = None
    rt.build_queue = None
    rt.build_dispatcher = None
    rt.task_tracker = None
    rt.service_profiles = None
    rt.directive_store = None
    rt.persistent_task_store = None
    rt.work_item_store = None
    rt.cognitive_journal = None
    rt.skill_registry = None
    rt.skill_service = None
    rt.identity_registry = None
    rt.conn_manager = None
    rt.watch_manager = None
    rt.federation_bridge = None
    rt.behavioral_monitor = None
    rt._records_store = None
    rt._knowledge_store = None
    rt._system_qa = None
    rt._semantic_layer = None

    # Boot state
    rt._cold_start = True
    rt._started = False
    rt._fresh_boot = True
    rt._start_time = 0.0
    rt._recent_errors = []

    return rt
```

**NOTE:** Check that `conftest.py` doesn't already have conflicting fixtures. Add imports as needed. If any import fails at test time, guard it or adjust the import path — check the actual module locations.

### Step 2: Replace inline runtime mocks

For each test file, replace `rt = MagicMock()` with either:
1. **Use the fixture:** If the test function can accept a pytest fixture, use `mock_runtime`
2. **Inline with spec:** If the test uses a local factory or has unusual setup, add `spec=ProbOSRuntime` directly

**Priority order (Tier A — 5+ runtime mocks each):**

| File | Runtime Mocks | Approach |
|------|--------------|----------|
| `test_proactive.py` | 19 | Mix of fixture + factory. Factory `_make_mock_runtime()` was spec'd in Phase 1, but 19 inline mocks remain. |
| `test_architect_agent.py` | 13 | All inline `mock_runtime = MagicMock()`. Convert to `MagicMock(spec=ProbOSRuntime)`. |
| `test_escalation.py` | 13 | All inline `runtime = MagicMock()`. Convert to `MagicMock(spec=ProbOSRuntime)`. |
| `test_ad437_action_space.py` | 6 | Convert inline runtime mocks. |
| `test_cognitive_agent.py` | 6 | Convert inline runtime mocks. `_make_crew_runtime()` stays (Phase 1). |
| `test_acm.py` | 5 | Convert inline runtime mocks. |
| `test_callsign_routing.py` | 5 | Convert inline runtime mocks. |
| `test_proactive_quality.py` | 5 | Convert inline runtime mocks. |
| `test_autonomous_operations.py` | 5 | Convert inline runtime mocks. |
| `test_duty_schedule.py` | 4 | Convert inline runtime mocks. |
| `test_ward_room_dms.py` | 4 | Convert inline runtime mocks. |

**Tier B (2-3 runtime mocks, handle alongside Tier A):**

`test_introspect_design.py` (3), `test_cognitive_journal.py` (3), `test_circuit_breaker.py` (2), `test_communications_settings.py` (2), `test_copilot_adapter.py` (2), `test_bf034_cold_start.py` (2), `test_quality_hardening.py` (2), `test_checkpoint.py` (2), `test_dispatch_wiring.py` (2), `test_decomposer.py` (2), `test_semantic_knowledge.py` (2), `test_onboarding.py` (2), `test_temporal_context.py` (2), `test_unread_dms.py` (2)

**Tier C (1 runtime mock each, ~26 files):**

Apply `spec=ProbOSRuntime` to all remaining single-mock files.

### Step 3: Add specs to service sub-mocks

When you add `spec=ProbOSRuntime` to a runtime mock, the existing `rt.some_service = MagicMock()` lines need specs too. Use this reference:

| Attribute | Spec Class | Import From |
|-----------|-----------|-------------|
| `rt.registry` | `AgentRegistry` | `probos.substrate.registry` |
| `rt.trust_network` | `TrustNetwork` | `probos.consensus.trust` |
| `rt.ward_room` | `WardRoomService` | `probos.ward_room` |
| `rt.ward_room_router` | `WardRoomRouter` | `probos.ward_room_router` |
| `rt.episodic_memory` | `EpisodicMemory` | `probos.cognitive.episodic` |
| `rt.callsign_registry` | `CallsignRegistry` | `probos.crew_profile` |
| `rt.ontology` | `VesselOntologyService` | `probos.ontology` |
| `rt.intent_bus` | `IntentBus` | `probos.mesh.intent` |
| `rt.hebbian_router` | `HebbianRouter` | `probos.hebbian` |
| `rt.event_log` | `EventLog` | `probos.event_log` |
| `rt.config` | `SystemConfig` | `probos.config` |
| `rt.spawner` | `AgentSpawner` | `probos.substrate.spawner` |
| `rt.bridge_alerts` | `BridgeAlertService` | `probos.bridge_alerts` |
| `rt.llm_client` | `BaseLLMClient` | `probos.cognitive.copilot_adapter` |
| `rt.notification_queue` | `NotificationQueue` | `probos.notification` |
| `rt.codebase_index` | `CodebaseIndex` | `probos.cognitive.codebase_index` |

**IMPORTANT:** Verify each import path is correct before using it. If a class doesn't exist at that path, search for it:
```bash
grep -rn "class AgentRegistry" src/probos/
```

## Phase 3: Non-Runtime Service Mocks

After runtime mocks are done, apply specs to standalone service mocks throughout the test suite:

- `agent = MagicMock()` → `MagicMock(spec=BaseAgent)` (~40 occurrences)
- `mock_llm = AsyncMock()` → `AsyncMock(spec=BaseLLMClient)` (~20 occurrences)
- `mock_index = MagicMock()` → `MagicMock(spec=CodebaseIndex)` (several)

## Critical Rules

### 1. Tests WILL break — that's the point

Each `AttributeError` from a spec'd mock reveals either:
- **A real bug** — code accesses a nonexistent attribute → fix the production code
- **A stale test** — test accesses a renamed/removed attribute → fix the test
- **Missing mock setup** — mock needs the attribute configured → add it with its own spec

### 2. Handle PropertyMock for properties

If a spec'd class uses `@property`, `MagicMock(spec=...)` won't let you set them directly:
```python
type(rt).records_store = PropertyMock(return_value=mock_records)
```

### 3. Don't change test behavior

Add `spec=` constraints only. Don't refactor tests, don't change what they test, don't remove mocks.

### 4. Handle config sub-attributes

`SystemConfig` uses nested dataclasses. When `rt.config = MagicMock(spec=SystemConfig)` is set, accessing `rt.config.proactive.enabled` will fail because `config.proactive` is a spec'd `MagicMock` that doesn't auto-create nested attributes. Fix by explicitly setting sub-configs:
```python
rt.config = MagicMock(spec=SystemConfig)
rt.config.proactive = MagicMock()
rt.config.proactive.enabled = False
```

### 5. Skip list (don't need spec)

- `MagicMock()` used as plain data objects (return values, simple dicts)
- `MagicMock()` used as callback functions
- `AsyncMock()` replacing individual async methods on already-spec'd mocks
- `SimpleNamespace` constructions
- `patch()` targets (these spec themselves from the target)

## Validation

### After each file:
```bash
.venv/Scripts/python.exe -m pytest tests/<file> -x -q
```

### After all files:
```bash
.venv/Scripts/python.exe -m pytest tests/ -x -q
```

### Compliance report:
```bash
# Count remaining unspec'd runtime mocks
grep -c "= MagicMock()" tests/*.py | sort -t: -k2 -rn | head -20

# Count spec'd mocks
grep -c "spec=" tests/*.py | sort -t: -k2 -rn | head -20
```

**Target:** >60% of system object mocks have `spec=` (up from 11.8% after Phase 1).

### Report findings:
Document any real bugs found (code accessing nonexistent attributes) as separate BFs.

## Execution Strategy

1. Start with the conftest.py fixture
2. Do Tier A files first (highest mock count = highest impact)
3. Run tests after each file — don't batch
4. Tier B and C can be done more aggressively (fewer mocks per file)
5. Phase 3 (non-runtime mocks) after all runtime mocks are done
6. Final compliance report

## Reference

- BF-079 Phase 1 prompt: `prompts/bf-079-mock-discipline-audit.md`
- BF-085 annotations: `runtime.py` lines 148-258 (class-level type annotations block)
- Existing exemplar: `test_decomposer.py` lines 856-1282 (23 spec=ProbOSRuntime instances)
- Engineering guidance: `.github/copilot-instructions.md` line 72 — mock discipline rule
