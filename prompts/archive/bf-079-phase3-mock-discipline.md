# BF-079 Phase 3: Mock Discipline — Non-Runtime Service & Domain Mocks

## Context

Phase 1 (CLOSED) spec'd 18 factory functions across 14 files (3.5% → 11.8%).
Phase 2 (CLOSED) spec'd all 140 inline runtime mocks across 37 files (11.8% → 32.0%). Shared `mock_runtime` conftest fixture created with 16 pre-configured service sub-mocks.

This phase tackles the remaining **~300 actionable bare `MagicMock()`** instances that represent system objects (agents, LLM clients, services) without `spec=` enforcement.

## Scope

Six categories of non-runtime mocks, ordered by impact:

| Category | Count | Target Spec | Priority |
|----------|-------|-------------|----------|
| Agent mocks (`agent = MagicMock()`) | ~45 | `spec=BaseAgent` | A |
| LLM client mocks (`mock_llm = AsyncMock()`) | ~65 | `AsyncMock(spec=BaseLLMClient)` or use `MockLLMClient` | A |
| Inline runtime constructor args (`runtime=MagicMock()`) | ~32 | `spec=ProbOSRuntime` | A |
| CodebaseIndex mocks | ~7 | `spec=CodebaseIndex` | B |
| Conftest fixture gaps (4 un-spec'd attributes) | 4 | See below | B |
| Ad-hoc service sub-mocks on non-fixture runtimes | ~150 | Per service spec table | C |

**Out of scope (do NOT add spec):**
- `MagicMock()` used as plain data objects (return values, dicts, simple containers)
- `MagicMock()` used as callback functions
- `AsyncMock()` replacing individual async methods on already-spec'd mocks
- `SimpleNamespace` constructions
- `patch()` targets (these spec themselves from the target)
- `MagicMock(trust_score=0.5)` and similar data-carrier mocks

## Step 1: Fix conftest.py fixture gaps

The shared `mock_runtime` fixture at `tests/conftest.py` has 4 un-spec'd attributes. Fix these first since they propagate to 30+ test files:

```python
# Line 95 — add spec
from probos.substrate.pool import PoolGroupManager
rt.pool_groups = MagicMock(spec=PoolGroupManager)

# Line 98 — add spec
from probos.cognitive.llm_client import BaseLLMClient
rt.llm_client = AsyncMock(spec=BaseLLMClient)

# Line 101 — add spec
from probos.mesh.gossip import GossipProtocol
rt.gossip = MagicMock(spec=GossipProtocol)
```

**NOTE:** Verify `PoolGroupManager` exists at that path. If not, search:
```bash
grep -rn "class PoolGroupManager\|class PoolGroup" src/probos/
```
If no suitable class exists, leave `rt.pool_groups = MagicMock()` as-is (it's a dict-like container).

The `rt.config.onboarding` and `rt.config.proactive` are nested dataclass sub-configs — leave as `MagicMock()` (per Phase 2 Critical Rule #4).

## Step 2: Agent mocks — `spec=BaseAgent`

**~45 occurrences.** Replace bare agent mocks with `MagicMock(spec=BaseAgent)`.

Import: `from probos.substrate.agent import BaseAgent`

**Priority files (Tier A — 5+ agent mocks):**

| File | Agent Mocks | Notes |
|------|-------------|-------|
| `test_proactive.py` | 18 | Patterns like `agent = MagicMock()` with `agent.callsign`, `agent.agent_type` |
| `test_proactive_quality.py` | 7 | Similar agent mock patterns |
| `test_ad437_action_space.py` | 6 | Agent mocks in action space tests |
| `test_duty_schedule.py` | 4 | Agent in duty scheduling |
| `test_ward_room_dms.py` | 4 | Agent in DM tests |
| `test_circuit_breaker.py` | 3 | Agent in circuit breaker tests |

**Tier B (1-2 agent mocks each):**

`test_autonomous_operations.py` (2), `test_shapley.py` (2), `test_api_profile.py` (1), `test_ad429e_dict_migration.py` (1), `test_hebbian_social.py` (1), `test_identity_deterministic.py` (1), `test_records_store.py` (1), `test_temporal_context.py` (1)

**Common pattern to handle:**
```python
# BEFORE:
agent = MagicMock()
agent.callsign = "TestAgent"
agent.agent_type = "test_type"

# AFTER:
agent = MagicMock(spec=BaseAgent)
agent.callsign = "TestAgent"
agent.agent_type = "test_type"
```

**Watch for:** `BaseAgent` uses `@property` for some attributes. If `spec=BaseAgent` prevents setting an attribute directly, use `PropertyMock`:
```python
type(agent).callsign = PropertyMock(return_value="TestAgent")
```

If `agent.decide()` or `agent.act()` is called and needs to be async, use:
```python
agent = MagicMock(spec=BaseAgent)
agent.decide = AsyncMock(return_value=...)
```

## Step 3: LLM client mocks — `spec=BaseLLMClient`

**~65 occurrences.** Two sub-patterns:

### 3a. Standalone LLM mocks
Replace `mock_llm = AsyncMock()` with `AsyncMock(spec=BaseLLMClient)`.

Import: `from probos.cognitive.llm_client import BaseLLMClient`

| File | Count | Pattern |
|------|-------|---------|
| `test_builder_agent.py` | 18 | `mock_llm = AsyncMock()` |
| `test_architect_agent.py` | 12 | `mock_llm = AsyncMock()` |
| `test_code_reviewer.py` | 4 | `mock_llm = AsyncMock()` |
| `test_ward_room.py` | 2 | `mock_llm = AsyncMock()` |

### 3b. Inline `llm_client=MagicMock()` in agent constructors
Replace with `llm_client=AsyncMock(spec=BaseLLMClient)`.

| File | Count | Pattern |
|------|-------|---------|
| `test_ad398_crew_identity.py` | 15 | `SomeAgent(runtime=..., llm_client=MagicMock())` |
| `test_builder_agent.py` | 11 | Agent constructor args |
| `test_counselor.py` | 9 | `CounselorAgent(runtime=..., llm_client=MagicMock())` |
| `test_architect_agent.py` | 8 | Agent constructor args |
| `test_escalation.py` | 3 | `llm = MagicMock()` |
| `test_public_apis.py` | 3 | Agent constructors |
| `test_self_mod.py` | 1 | Agent constructor |
| `test_commands_llm.py` | 1 | Agent constructor |

**NOTE:** The codebase has `MockLLMClient` at `probos.cognitive.llm_client:439` which properly extends `BaseLLMClient`. Some tests already use it (~80 files). For Phase 3, `AsyncMock(spec=BaseLLMClient)` is preferred over `MockLLMClient` because:
- Mocks let tests control return values per-test
- `MockLLMClient` has canned responses that may not match what each test expects
- Consistency with the spec= pattern established in Phases 1-2

## Step 4: Inline runtime constructor args — `spec=ProbOSRuntime`

**~32 occurrences.** These are `SomeAgent(runtime=MagicMock(), ...)` calls where the runtime is not the main test subject but a constructor dependency.

Import: `from probos.runtime import ProbOSRuntime`

| File | Count | Pattern |
|------|-------|---------|
| `test_ad398_crew_identity.py` | 14 | `SomeAgent(runtime=MagicMock(), ...)` |
| `test_builder_agent.py` | 11 | Agent constructor args |
| `test_utility_agents.py` | 4 | Various utility agents |
| `test_cognitive_journal.py` | 2 | Journal tests |
| `test_public_apis.py` | 2 | API tests |

**IMPORTANT:** When adding `spec=ProbOSRuntime`, the resulting mock will reject attribute access for attributes not on `ProbOSRuntime`. If the agent constructor or its code accesses `runtime.registry`, `runtime.trust_network`, etc., those need to be set up:

```python
# BEFORE:
agent = SomeAgent(runtime=MagicMock(), llm_client=MagicMock())

# AFTER:
rt = MagicMock(spec=ProbOSRuntime)
rt.registry = MagicMock(spec=AgentRegistry)
rt.trust_network = MagicMock(spec=TrustNetwork)
# ... set up whatever this specific agent needs
agent = SomeAgent(runtime=rt, llm_client=AsyncMock(spec=BaseLLMClient))
```

If this gets verbose, consider whether the test can use the shared `mock_runtime` fixture instead.

## Step 5: CodebaseIndex mocks

**7 occurrences across 3 files.**

Import: `from probos.cognitive.codebase_index import CodebaseIndex`

| File | Lines | Notes |
|------|-------|-------|
| `test_architect_agent.py` | 319, 657, 692 | Already has spec'd versions at 448, 734 — make consistent |
| `test_introspect_design.py` | 17, 170, 198 | `rt.codebase_index = MagicMock()` |
| `test_api_system.py` | 24 | `runtime.codebase_index = MagicMock()` |

```python
# BEFORE:
mock_index = MagicMock()

# AFTER:
mock_index = MagicMock(spec=CodebaseIndex)
```

## Step 6: Ad-hoc service sub-mocks (Tier C — if time permits)

~150 occurrences where tests that do NOT use the `mock_runtime` fixture set up service sub-mocks without specs. These are lower priority because:
- Phase 2 already handled the runtime mock itself
- The fixture covers 30+ files automatically
- These are sub-attributes, not the primary mock

If you have bandwidth after Steps 1-5, apply specs to the most common service sub-mocks in non-fixture tests using this reference:

| Attribute | Spec Class | Import From |
|-----------|-----------|-------------|
| `rt.registry` | `AgentRegistry` | `probos.substrate.registry` |
| `rt.trust_network` | `TrustNetwork` | `probos.consensus.trust` |
| `rt.ward_room` | `WardRoomService` | `probos.ward_room` |
| `rt.ward_room_router` | `WardRoomRouter` | `probos.ward_room_router` |
| `rt.episodic_memory` | `EpisodicMemory` | `probos.cognitive.episodic` |
| `rt.callsign_registry` | `CallsignRegistry` | `probos.crew_profile` |
| `rt.intent_bus` | `IntentBus` | `probos.mesh.intent` |
| `rt.hebbian_router` | `HebbianRouter` | `probos.mesh.routing` |
| `rt.event_log` | `EventLog` | `probos.substrate.event_log` |
| `rt.config` | `SystemConfig` | `probos.config` |
| `rt.spawner` | `AgentSpawner` | `probos.substrate.spawner` |
| `rt.notification_queue` | `NotificationQueue` | `probos.task_tracker` |
| `rt.gossip` | `GossipProtocol` | `probos.mesh.gossip` |
| `rt.codebase_index` | `CodebaseIndex` | `probos.cognitive.codebase_index` |

**Top files for Tier C:**

| File | Un-spec'd service mocks | Notes |
|------|------------------------|-------|
| `test_ad437_action_space.py` | 6 trust_network + 6 ward_room | Convert both |
| `test_bridge_alerts.py` | 3 trust_network + 3 ward_room | Convert both |
| `test_proactive.py` | 5 trust_network + config | Convert (runtime factory handles most) |
| `test_acm.py` | 5 trust_network | Convert |
| `test_onboarding.py` | 4 trust_network | Convert |

## Critical Rules (same as Phase 2)

### 1. Tests WILL break — that's the point

Each `AttributeError` from a spec'd mock reveals either:
- **A real bug** — code accesses a nonexistent attribute → fix the production code
- **A stale test** — test accesses a renamed/removed attribute → fix the test
- **Missing mock setup** — mock needs the attribute configured → add it with its own spec

### 2. Handle PropertyMock for properties

If a spec'd class uses `@property`, `MagicMock(spec=...)` won't let you set them directly:
```python
type(agent).some_property = PropertyMock(return_value=value)
```

### 3. Don't change test behavior

Add `spec=` constraints only. Don't refactor tests, don't change what they test, don't remove mocks.

### 4. AsyncMock for async methods

When a spec'd mock has async methods that tests call:
```python
agent = MagicMock(spec=BaseAgent)
agent.decide = AsyncMock(return_value=AgentResult(...))
agent.act = AsyncMock()
```

### 5. Skip list (don't need spec)

- `MagicMock()` used as plain data objects (return values, simple dicts)
- `MagicMock()` used as callback functions
- `AsyncMock()` replacing individual async methods on already-spec'd mocks
- `SimpleNamespace` constructions
- `patch()` targets
- `MagicMock(trust_score=0.5)` and similar data-carrier mocks with keyword args

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
# Count remaining unspec'd system object mocks
grep -c "= MagicMock()" tests/*.py | sort -t: -k2 -rn | head -20

# Count spec'd mocks
grep -c "spec=" tests/*.py | sort -t: -k2 -rn | head -20

# Total compliance
echo "=== Total spec= ===" && grep -c "spec=" tests/*.py | awk -F: '{sum+=$2} END {print sum}'
echo "=== Total bare MagicMock() ===" && grep -c "= MagicMock()" tests/*.py | awk -F: '{sum+=$2} END {print sum}'
```

**Target:** >50% of all mock instances have `spec=` (up from 32.0% after Phase 2).

### Report findings:
Document any real bugs found (code accessing nonexistent attributes) in your completion summary.

## Execution Strategy

1. Start with conftest.py fixture fixes (Step 1) — propagates to 30+ files
2. Do agent mocks (Step 2) and LLM client mocks (Step 3) in parallel — highest impact
3. Inline runtime args (Step 4) and CodebaseIndex (Step 5) — smaller batches
4. Run full test suite between each step
5. Tier C service sub-mocks (Step 6) only if Steps 1-5 pass cleanly
6. Final compliance report

## Reference

- BF-079 Phase 1 prompt: `prompts/bf-079-mock-discipline-audit.md`
- BF-079 Phase 2 prompt: `prompts/bf-079-phase2-mock-discipline.md`
- Phase 2 conftest fixture: `tests/conftest.py` lines 44-155
- Existing exemplar: `test_decomposer.py` (heavily spec'd after Phase 2)
- Engineering guidance: `.github/copilot-instructions.md` line 72 — mock discipline rule
