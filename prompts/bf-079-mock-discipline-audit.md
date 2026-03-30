# BF-079: Mock Discipline Audit — `spec=` on All Mock Factories

## Problem

~800 `MagicMock()`/`AsyncMock()` instances across ~60 test files create mocks without `spec=`, meaning they silently invent attributes on access. This is the #1 cause of refactoring bugs surviving the test suite (see BF-078 — `rt._agents` passed tests for months because `MagicMock()._agents` returns another `MagicMock()` instead of raising `AttributeError`).

Current compliance: **~3.4%** (28 compliant out of ~800 system object mocks).

## Scope

This BF targets **mock factories and high-impact runtime mocks** — the places where a missing `spec=` has the highest probability of hiding real bugs. It does NOT require converting every single `MagicMock()` in the codebase (that would be ~800 changes with diminishing returns).

## Phased Approach

### Phase 1: Mock Factories (HIGHEST IMPACT)

Every shared mock factory that creates system objects must use `spec=`. These are the single-point-of-failure functions — fix once, all tests that use the factory benefit.

**Runtime factories — add `spec=ProbOSRuntime`:**

| File | Function | Line |
|------|----------|------|
| `tests/test_proactive.py` | `_make_mock_runtime()` | 82 |
| `tests/test_escalation.py` | `_make_mock_runtime()` | 40 |
| `tests/test_decomposer.py` | `_make_mock_runtime()` | 1294 |
| `tests/test_ward_room_agents.py` | `_make_mock_runtime()` | 572 |
| `tests/test_identity_persistence.py` | `_make_runtime()` | 45 |
| `tests/test_onboarding.py` | `_make_runtime()` | 35 |
| `tests/test_circuit_breaker.py` | `_make_loop()` | 243 |
| `tests/test_proactive_quality.py` | `_make_engine_and_rt()` | 12 |
| `tests/test_cognitive_agent.py` | `_make_crew_runtime()` | 460, 578, 811, 886 |

**Pattern:**
```python
# BEFORE (BF-078 blind spot):
def _make_mock_runtime():
    rt = MagicMock()
    rt.registry.all.return_value = []
    return rt

# AFTER:
def _make_mock_runtime():
    rt = MagicMock(spec=ProbOSRuntime)
    rt.registry = MagicMock(spec=AgentRegistry)
    rt.registry.all.return_value = []
    return rt
```

**Other service factories — add appropriate `spec=`:**

| File | Function | Spec class |
|------|----------|------------|
| `test_architect_agent.py` | `_make_mock_index()` | `spec=CodebaseIndex` |
| `test_architect_agent.py` | `_make_mock_index_with_source()` | `spec=CodebaseIndex` |
| `test_proactive.py` | `_make_mock_agent()` | `spec=BaseAgent` |
| `test_feedback_engine.py` | `_make_trust()` | `spec=TrustNetwork` |
| `test_feedback_engine.py` | `_make_hebbian()` | `spec=HebbianRouter` |
| `test_feedback_engine.py` | `_make_episodic()` | `spec=EpisodicMemory` |
| `test_feedback_engine.py` | `_make_event_log()` | `spec=EventLog` |
| `test_sif.py` | `_make_trust_network()` | `spec=TrustNetwork` |
| `test_sif.py` | `_make_hebbian_router()` | `spec=HebbianRouter` |
| `test_sif.py` | `_make_spawner()` | `spec=AgentSpawner` |
| `test_sif.py` | `_make_pool()` | `spec=AgentPool` |
| `test_identity_persistence.py` | `_make_agent()` | `spec=BaseAgent` |
| `test_onboarding.py` | `_make_agent()` | `spec=BaseAgent` |
| `test_introspect.py` | `_make_agent()` | `spec=BaseAgent` |
| `test_team_introspection.py` | `_make_agent()` | `spec=BaseAgent` |
| `test_team_introspection.py` | `_make_pool()` | `spec=AgentPool` |
| `test_ward_room_agents.py` | `_make_agent()` | `spec=BaseAgent` |
| `test_ward_room_agents.py` | `_make_channel()` | appropriate channel type |

### Phase 2: Inline Runtime Mocks in Top-10 Files

These files create inline `rt = MagicMock()` at the test level (not via factory). Add `spec=ProbOSRuntime` to the inline mock.

**Top 10 by mock count (fix these files):**

1. `test_proactive.py` — ~60 bare mocks
2. `test_bridge_alerts.py` — ~35 bare mocks
3. `test_ad437_action_space.py` — ~35 bare mocks
4. `test_onboarding.py` — ~30 bare mocks
5. `test_builder_agent.py` — ~24 bare mocks
6. `test_ad398_crew_identity.py` — ~24 bare mocks
7. `test_escalation.py` — ~23 bare mocks
8. `test_cognitive_agent.py` — ~23 bare mocks
9. `test_architect_agent.py` — ~20 bare mocks
10. `test_decomposer.py` — ~20 bare mocks

**For each file, the pattern is:**

```python
# Find all: rt = MagicMock() or runtime = MagicMock()
# Replace with: rt = MagicMock(spec=ProbOSRuntime)

# Find all: llm = MagicMock() or mock_llm = MagicMock() (used as LLM client)
# Replace with: llm = MagicMock(spec=OpenAICompatibleClient)

# Find all: AsyncMock() used as service methods
# These are OK — AsyncMock() replacing individual methods doesn't need spec
# because the parent mock's spec already constrains which methods exist
```

### Phase 3: Remaining Test Files

Apply the same pattern to the remaining ~50 test files. These have fewer mocks each (1-15) so the risk is lower, but we should still fix them for consistency.

**Skip list (don't need spec):**
- `MagicMock()` used to create plain data objects (return values, simple dicts)
- `MagicMock()` used as callback functions (these aren't pretending to be classes)
- `AsyncMock()` used to replace individual async methods on already-spec'd mocks
- `SimpleNamespace` constructions (not MagicMock at all)

## Critical Implementation Notes

### 1. Tests WILL break — that's the point

When you add `spec=ProbOSRuntime` to a mock, any test that accesses an attribute that doesn't exist on ProbOSRuntime will raise `AttributeError`. **This is the purpose of the audit.** Each broken test reveals one of:

- **A real bug** (like BF-078's `rt._agents`) — the code is wrong, fix the code
- **A stale test** — the test accesses an attribute that was renamed/removed, fix the test
- **A missing attribute setup** — the mock factory doesn't configure all needed attributes, add the attribute to the factory with its own spec

### 2. Nested service mocks need their own specs

When `spec=ProbOSRuntime` is added, nested attributes like `rt.ward_room` will be constrained. If the test does `rt.ward_room.create_thread()`, you need:

```python
rt.ward_room = MagicMock(spec=WardRoomService)
rt.ward_room.create_thread = AsyncMock()
```

Or use `AsyncMock(spec=WardRoomService)` if all methods are async.

**Key service specs to use:**

| Attribute | Spec Class | Import From |
|-----------|-----------|-------------|
| `rt.registry` | `AgentRegistry` | `probos.substrate.registry` |
| `rt.trust_network` | `TrustNetwork` | `probos.trust` |
| `rt.ward_room` | `WardRoomService` | `probos.ward_room` |
| `rt.ward_room_router` | `WardRoomRouter` | `probos.ward_room_router` |
| `rt.episodic_memory` | `EpisodicMemory` | `probos.episodic` |
| `rt.callsign_registry` | `CallsignRegistry` | `probos.callsign_registry` |
| `rt.ontology` | `Ontology` | `probos.ontology` |
| `rt.intent_bus` | `IntentBus` | `probos.intent` |
| `rt.hebbian_router` | `HebbianRouter` | `probos.hebbian` |
| `rt.event_log` | `EventLog` | `probos.event_log` |
| `rt.knowledge_store` | `KnowledgeStore` | `probos.knowledge_store` |
| `rt.skill_service` | `SkillService` | `probos.skills.skill_service` |
| `rt.bridge_alerts` | `BridgeAlerts` | `probos.bridge_alerts` |
| `rt.config` | `ProbOSConfig` | `probos.config` |
| `rt.dream_adapter` | `DreamAdapter` | `probos.dream_adapter` |
| `rt.self_mod_manager` | `SelfModManager` | `probos.self_mod_manager` |
| `rt.records_store` | `RecordsStore` | `probos.knowledge.records_store` |

### 3. Don't change test behavior — only add specs

This is a structural hardening pass. Don't refactor tests, don't change what they test, don't remove mocks. Just add `spec=` constraints so the mocks enforce attribute existence.

### 4. Handle `PropertyMock` for properties

If a spec'd class has `@property` attributes, `MagicMock(spec=...)` won't let you set them directly. Use `type(mock).property_name = PropertyMock(return_value=...)` for those cases.

### 5. Common pattern: `spec=True` shortcut

If a mock is instantiated from a real object, `spec=True` infers the spec automatically:
```python
# Instead of: mock = MagicMock(spec=ProbOSRuntime)
# You can use (if you have an instance):
mock = MagicMock(spec_set=ProbOSRuntime)  # Even stricter — blocks setting nonexistent attrs too
```

Prefer `spec=` over `spec_set=` for this audit (less strict, easier migration).

## Validation

### Phase 1 Validation
1. All factories updated with spec: `grep -n "def _make_mock\|def _make_runtime\|def _make_agent\|def _make_loop\|def _make_engine" tests/*.py` — verify all have `spec=`
2. All existing tests pass: `pytest tests/ -x -q`
3. Count of spec-compliant factories: should be ~30+ (up from 0)

### Phase 2 Validation
1. Top-10 files have zero bare `MagicMock()` representing `ProbOSRuntime`
2. All existing tests pass: `pytest tests/ -x -q`

### Phase 3 Validation
1. `grep -c "MagicMock()" tests/*.py | sort -t: -k2 -rn` — verify count is significantly reduced
2. All existing tests pass: `pytest tests/ -x -q`
3. Full suite: `pytest tests/ -n auto -q`

### Final Compliance Check
Report the new compliance rate. Target: >80% of system object mocks have `spec=`.

## Execution Strategy

**Recommended:** Do Phase 1 first, run tests, fix breaks, commit. Then Phase 2 (one file at a time if needed — the top-10 files will cause the most breakage). Phase 3 can be batched more aggressively since the remaining files have fewer mocks.

**If a test break reveals a real bug** (code accesses an attribute that doesn't exist on the real class), file a separate BF and fix the code — don't work around it in the test.

## Reference

- BF-078: The bug that motivated this audit — `rt._agents` hidden by unspec'd mock
- Engineering guidance: `.github/copilot-instructions.md` line 72 — mock discipline rule
- Existing compliant examples: `test_decomposer.py` lines 856-1282 (23 instances of `spec=ProbOSRuntime`)
- `test_unread_dms.py` lines 144, 186 (`AsyncMock(spec=WardRoomService)`)
