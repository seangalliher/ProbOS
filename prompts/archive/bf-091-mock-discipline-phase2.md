# BF-091: Mock Discipline Phase 2 — Spec Coverage (Top 20 Files)

## Context

Codebase scorecard graded Mock Discipline at **C-**. BF-079 Phase 1 achieved 301 spec'd MagicMock calls (27.9% compliance). 776 bare `MagicMock()` and 478 bare `AsyncMock()` remain across 80+ files. The BF-078 incident proved unspecced mocks cause real production bugs — Ward Room was dead for an entire release cycle because `MagicMock()` silently invented `rt._agents`.

## Problem

- **22.6% overall mock compliance** (367 spec'd / 1,621 total)
- `conftest.py` has an excellent `mock_runtime` fixture with 16 spec'd sub-services — but only 6 test files use it
- The dominant anti-pattern: `rt.service_name = MagicMock()` where the service class is well-known
- Zero `create_autospec` usage anywhere

## Strategy

Fix the **top 20 worst offender files** (261+ fixable bare mocks). This is the 80/20 play — these files account for ~1/3 of all bare mocks and contain the highest-blast-radius runtime service mocks.

## Part 1: Extend conftest.py mock_runtime Fixture

The existing `mock_runtime` in `tests/conftest.py` already specs 16 sub-services. Add any missing ones that the top 20 files need. Check if these are already spec'd in conftest — if not, add them:

```python
# These may need to be added to conftest.py's mock_runtime fixture:
rt.ontology = MagicMock(spec=VesselOntologyService)
rt.bridge_alerts = MagicMock(spec=BridgeAlertManager)
rt.conn_manager = MagicMock(spec=ConnManager)
rt.attention = MagicMock(spec=AttentionManager)
rt.working_memory = MagicMock(spec=WorkingMemory)
rt.self_mod_pipeline = MagicMock(spec=SelfModPipeline)
rt.decomposer = MagicMock(spec=Decomposer)
rt.dream_scheduler = MagicMock(spec=DreamScheduler)
rt._night_orders_mgr = MagicMock(spec=NightOrdersManager)
rt._records_store = MagicMock(spec=RecordsStore)
rt.skill_service = MagicMock(spec=AgentSkillService)
rt.capability_registry = MagicMock(spec=CapabilityRegistry)
rt.gossip = MagicMock(spec=GossipProtocol)
```

Check which of these the conftest already has before adding. Import the spec classes. If a class isn't easily importable (circular import risk), use `spec=True` as a fallback — still better than bare.

## Part 2: Fix Top 20 Files

For each file below, replace bare `MagicMock()` and `AsyncMock()` calls with spec'd versions. The approach for each file:

1. **If the file creates a local `mock_runtime`**: Switch to using the conftest `mock_runtime` fixture (add it as a pytest parameter) OR apply `spec=ProbOSRuntime` to the local mock and spec all sub-services.
2. **If the file mocks standalone services**: Add `spec=ServiceClass` to each mock.
3. **Skip**: Callbacks (`MagicMock()` used as `on_complete`, `emit_event`, etc.), method return values / side_effects on already-spec'd parent mocks, and data structure mocks with no meaningful class.

### File-by-file instructions:

**1. `test_proactive.py`** (59 bare) — Highest priority. Has a local `mock_runtime` fixture creating ~45 bare sub-service mocks. Replace with conftest `mock_runtime` or add spec= to each: `rt.registry=MagicMock(spec=AgentRegistry)`, `rt.trust_network=MagicMock(spec=TrustNetwork)`, `rt.ward_room=MagicMock(spec=WardRoomService)`, `rt.episodic_memory=AsyncMock(spec=EpisodicMemory)`, `rt.event_log=AsyncMock(spec=EventLog)`, `rt.ward_room_router=MagicMock(spec=WardRoomRouter)`, `rt.bridge_alerts=MagicMock(spec=BridgeAlertManager)`, `rt.callsign_registry=MagicMock(spec=CallsignRegistry)`.

**2. `test_bridge_alerts.py`** (39 bare) — Three test class setup methods each create a full set of bare service mocks. Apply spec= to: `ward_room`, `event_log`, `registry`, `intent_bus`, `trust_network`, `callsign_registry`, `config` (SystemConfig).

**3. `test_decomposer.py`** (31 bare) — Mocks `runtime.pool_groups`, `runtime.decomposer`, `runtime.dream_scheduler`, `runtime.registry`, `runtime.trust_network`, `runtime.hebbian_router`, `runtime.attention`. Add spec= for known classes.

**4. `test_onboarding.py`** (30 bare) — Mocks `rt.registry`, `rt.capability_registry`, `rt.gossip`, `rt.trust_network`, `rt.intent_bus`, `rt.ward_room`, `rt.event_log`. Add spec= for each.

**5. `test_cognitive_agent.py`** (24 bare) — Mocks `rt.ontology`, `rt.callsign_registry`, `rt.episodic_memory`. Episode data objects (`ep1`, `ep2`) are borderline — skip those.

**6. `test_ad437_action_space.py`** (22 bare) — Full runtime mock. Apply spec= to: `runtime.ward_room`, `runtime.trust_network`, `runtime.ward_room_router`, `runtime.callsign_registry`, `runtime._records_store`, `runtime.config`, `runtime.skill_service`.

**7. `test_public_apis.py`** (18 bare) — Mocks for `AgentRegistry`, `AgentSpawner`, `VesselOntologyService`, `KnowledgeStore`, `AgentDesigner`, `CodeValidator`, `SandboxRunner`, `BehavioralMonitor`, `SystemConfig`. Add spec= for each.

**8. `test_proactive_quality.py`** (17 bare) — Similar to test_proactive.py. Apply spec= to runtime sub-services.

**9. `test_copilot_adapter.py`** (17 bare) — `mock_router` should be spec'd. Copilot SDK protocol objects are external lib — skip those (borderline).

**10. `test_build_dispatcher.py`** (17 bare) — `wm` (WorktreeManager), `mock_adapter` (CopilotAdapter). Add spec= for ProbOS classes.

**11. `test_escalation.py`** (15 bare) — `esc_mgr` (EscalationManager), `mem` (EpisodicMemory). Data/result objects (`r`, `resp`) — skip.

**12. `test_builder_agent.py`** (14 bare) — `llm_client=MagicMock()` should be `MagicMock(spec=BaseLLMClient)` — 11 occurrences.

**13. `test_semantic_knowledge.py`** (13 bare) — `router` (HebbianRouter), `trust` (TrustNetwork), `store` (KnowledgeStore). ChromaDB collection mocks — skip (external).

**14. `test_self_mod_deps.py`** (13 bare) — `resolver` (DependencyResolver), `event_log` (EventLog). All should be spec'd.

**15. `test_acm.py`** (13 bare) — `rt.trust_network`, `rt.registry`, `rt.skill_service`, `rt.episodic_memory`. Conftest provides specs for all of these.

**16. `test_api_profile.py`** (12 bare) — `runtime.registry`, `runtime.callsign_registry`, `runtime.trust_network`, `runtime.hebbian_router`, `runtime.intent_bus`, `runtime.episodic_memory`.

**17. `test_dependency_resolver.py`** (11 bare) — **SKIP ENTIRELY.** All 11 simulate `importlib.util.find_spec()` results — no meaningful ProbOS class to spec against.

**18. `test_correction_runtime.py`** (11 bare) — `rt.self_mod_pipeline`, `rt.attention`, `rt.working_memory`, `rt.capability_registry`, `rt.registry`, `rt.trust_network`, `rt.hebbian_router`, `rt.decomposer`.

**19. `test_circuit_breaker.py`** (11 bare) — `rt.ward_room`, `rt.trust_network`, `rt.ward_room_router`, `rt._records_store`, `rt.callsign_registry`, `rt.config`, `rt.registry`.

**20. `test_autonomous_operations.py`** (11 bare) — `rt.registry`, `rt.trust_network`, `rt.ontology`, `rt.conn_manager`, `rt._night_orders_mgr`, `rt.bridge_alerts`.

## Spec Reference Table

Use this when adding spec= to mocks. Import from:

| Mock target | spec= | Import from |
|-------------|-------|-------------|
| `ProbOSRuntime` | `spec=ProbOSRuntime` | `probos.runtime` |
| `AgentRegistry` | `spec=AgentRegistry` | `probos.runtime` |
| `TrustNetwork` | `spec=TrustNetwork` | `probos.consensus.trust` |
| `WardRoomService` | `spec=WardRoomService` | `probos.ward_room` |
| `WardRoomRouter` | `spec=WardRoomRouter` | `probos.ward_room_router` |
| `EpisodicMemory` | `spec=EpisodicMemory` | `probos.cognitive.episodic` |
| `CallsignRegistry` | `spec=CallsignRegistry` | `probos.runtime` |
| `IntentBus` | `spec=IntentBus` | `probos.runtime` |
| `SignalManager` | `spec=SignalManager` | `probos.runtime` |
| `HebbianRouter` | `spec=HebbianRouter` | `probos.mesh.routing` |
| `EventLog` | `spec=EventLog` | `probos.substrate.event_log` |
| `SystemConfig` | `spec=SystemConfig` | `probos.config` |
| `AgentSpawner` | `spec=AgentSpawner` | `probos.runtime` |
| `PoolGroupRegistry` | `spec=PoolGroupRegistry` | `probos.runtime` |
| `NotificationQueue` | `spec=NotificationQueue` | `probos.runtime` |
| `BaseLLMClient` | `spec=BaseLLMClient` | `probos.substrate.llm` |
| `GossipProtocol` | `spec=GossipProtocol` | `probos.runtime` |
| `VesselOntologyService` | `spec=VesselOntologyService` | `probos.runtime` |
| `BridgeAlertManager` | `spec=BridgeAlertManager` | `probos.runtime` |
| `ConnManager` | `spec=ConnManager` | `probos.conn` |
| `AttentionManager` | `spec=AttentionManager` | `probos.runtime` |
| `SelfModPipeline` | `spec=SelfModPipeline` | `probos.cognitive.self_mod` |
| `Decomposer` | `spec=Decomposer` | `probos.runtime` |
| `DreamScheduler` | `spec=DreamScheduler` | `probos.runtime` |
| `RecordsStore` | `spec=RecordsStore` | `probos.knowledge.records_store` |
| `AgentSkillService` | `spec=AgentSkillService` | `probos.skill_framework` |
| `CapabilityRegistry` | `spec=CapabilityRegistry` | `probos.mesh.capability` |
| `KnowledgeStore` | `spec=KnowledgeStore` | `probos.knowledge.store` |
| `DependencyResolver` | `spec=DependencyResolver` | `probos.cognitive.dependency_resolver` |
| `EscalationManager` | `spec=EscalationManager` | `probos.runtime` |
| `CopilotAdapter` | `spec=CopilotAdapter` | `probos.cognitive.copilot_adapter` |
| `BaseAgent` | `spec=BaseAgent` | `probos.substrate.agent` |

**Note:** Some classes may need `TYPE_CHECKING` imports to avoid circular imports. If a direct import causes `ImportError`, use `if TYPE_CHECKING:` block and put `spec=` inside the test function body, or use string-based spec with `unittest.mock.patch`.

**Note:** If adding `spec=` causes a test to fail because the test was relying on a mock inventing a non-existent attribute (the exact bug BF-078 demonstrated), that is a REAL BUG in the test. Fix the test to use the correct attribute name. Do NOT remove the spec to make the test pass.

## Part 3: AsyncMock Spec Discipline

When the mock target's methods are async (e.g., `EpisodicMemory.store()`, `EventLog.log()`, `WardRoomService.post()`), use `AsyncMock(spec=ClassName)` instead of `MagicMock(spec=ClassName)`. This ensures:
1. Attribute existence enforcement (from spec=)
2. Proper `await` behavior (from AsyncMock)

The conftest already demonstrates this: `rt.episodic_memory = AsyncMock(spec=EpisodicMemory)`.

## Verification

After all changes:

1. **Compliance check**: Count spec'd vs bare mocks:
   ```bash
   # Spec'd (MagicMock + AsyncMock):
   grep -rn "spec=" tests/ --include="*.py" | grep -c "Mock"
   # Bare MagicMock():
   grep -rn "MagicMock()" tests/ --include="*.py" | wc -l
   ```
   Target: ≥50% compliance (up from 22.6%). The top 20 files should fix ~260 bare mocks.

2. **Run targeted tests** for each modified file:
   ```bash
   python -m pytest tests/test_proactive.py tests/test_bridge_alerts.py tests/test_decomposer.py tests/test_onboarding.py tests/test_cognitive_agent.py -x -q --tb=short
   ```
   Then the remaining 14 files.

3. **Run full suite**: `python -m pytest tests/ -q --tb=short` — expect 4240+ passing.

4. **If a test fails with `AttributeError: Mock spec does not allow...`**: This means the test was using a non-existent attribute on the mocked class. This is the EXACT class of bug that spec= is designed to catch. Fix the test by using the correct attribute name from the real class, not by removing spec=.

## What NOT to Do

- Do NOT modify production code — only test files and conftest.py
- Do NOT add spec= to callback mocks (`on_complete`, `emit_event`, etc.)
- Do NOT add spec= to `MagicMock(return_value=...)` or `AsyncMock(side_effect=...)` that are method-level stubs on already-spec'd parents
- Do NOT touch `test_dependency_resolver.py` — its bare mocks are justified
- Do NOT remove spec= to make failing tests pass — fix the test instead
- Do NOT introduce `create_autospec` in this pass — that's a future Phase 3 enhancement
- Line numbers are approximate — find the nearest matching pattern if lines have shifted

## Principles Compliance

- **Mock Discipline**: Spec coverage from 22.6% toward ≥50% in the top 20 files
- **Fail Fast**: Spec'd mocks catch attribute errors immediately (BF-078 class of bugs)
- **DRY**: Conftest fixture reuse eliminates repeated local mock setup
- **Cloud-Ready**: AD-542's Protocol types (DatabaseConnection, ConnectionFactory) are now available for spec= in DB-related test mocks
