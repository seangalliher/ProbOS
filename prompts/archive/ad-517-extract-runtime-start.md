# AD-517: Extract runtime.py start() into Startup Phases

## Context

`src/probos/runtime.py` is 4,102 lines. The `start()` method alone is **1,104 lines** (lines 793–1896) containing 44 sequential initialization steps, 15 private member patches (`obj._attr = value`), and 55 attribute assignments. The `__init__` is 289 lines declaring 93 attributes, 44 of which are initialized to `None` and assigned in `start()`.

AD-515 extracted 5 service modules (ward_room_router, agent_onboarding, self_mod_manager, dream_adapter, warm_boot). AD-516 extracted api.py into routers. AD-517 continues Wave 3 by decomposing `start()` into focused startup phase modules.

## Objective

Extract `start()` into a sequence of focused initializer functions grouped by subsystem. After extraction, `start()` should be ~60–80 lines — a readable sequence of phase calls that reads like a checklist. Each phase is a standalone module in `src/probos/startup/`.

**Target:** runtime.py reduced from 4,102 to ~3,000 lines. `start()` reduced from 1,104 lines to ~70 lines.

## Design Principles

1. **Zero behavior changes.** This is a pure structural refactor. Every initialization step must execute in the same order with the same effect.
2. **Each phase function receives explicit parameters.** No passing the entire runtime object. Each phase function takes exactly the dependencies it needs and returns the services it creates.
3. **Return dataclasses for phase outputs.** Each phase returns a typed result dataclass containing the services it created, so runtime can assign them to `self`.
4. **Eliminate private member patches where possible.** Where a phase creates an object that currently gets `_attr` patched later, prefer constructor injection or a `configure()` method with a public API. Where elimination isn't practical in this AD, document the remaining patches with `# PATCH: reason` comments.
5. **Constructor injection over post-hoc patching.** If service A needs service B, and both are created in the same phase, wire them through constructors.
6. **Type annotations throughout.** No `Any` parameters or return types in the new phase functions. Import concrete types.
7. **Structured logging.** Each phase logs its start and completion: `logger.info("Startup phase: %s", phase_name)`.

## Infrastructure (do this FIRST)

### 1. Create `src/probos/startup/__init__.py`

```python
"""ProbOS startup phase modules (AD-517).

Each module contains a single phase function that initializes a
subsystem group. Called sequentially by ProbOSRuntime.start().
"""
```

### 2. Create phase result dataclasses in `src/probos/startup/results.py`

Define typed result dataclasses for each phase's output. Each phase returns one of these so runtime can assign the created services to `self`. Example pattern:

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.substrate.event_log import EventLog
    # ... other concrete types

@dataclass
class InfrastructureResult:
    """Services created by the infrastructure boot phase."""
    identity_registry: Any  # AgentIdentityRegistry
    event_prune_task: Any   # asyncio.Task
    # ... etc
```

Use `TYPE_CHECKING` imports to avoid circular import issues at runtime. The actual types should be the concrete classes, not `Any` — use string annotations (`"AgentIdentityRegistry"`) if needed.

## Phase Extractions

Extract each phase as a standalone async function in its own module. The function takes explicit dependencies and returns a result dataclass.

### Phase 1: `src/probos/startup/infrastructure.py` — Infrastructure Boot

**Extract from:** Lines 802–815 (steps A–B in current start())

**Function signature:**
```python
async def boot_infrastructure(
    event_log: EventLog,
    hebbian_router: HebbianRouter,
    signal_manager: SignalManager,
    gossip: GossipProtocol,
    trust_network: TrustNetwork,
    data_dir: Path,
    config: SystemConfig,
) -> InfrastructureResult:
```

**Actions to move:**
- `event_log.start()`
- `hebbian_router.start()`
- `signal_manager.start()`
- `gossip.start()`
- `trust_network.start()`
- `data_dir.mkdir(parents=True, exist_ok=True)`
- Create event log prune loop task
- Lazy-import and create `AgentIdentityRegistry`, call `.start()`

**Returns:** `InfrastructureResult` with `identity_registry` and `event_prune_task`.

---

### Phase 2: `src/probos/startup/agent_fleet.py` — Agent Fleet Creation

**Extract from:** Lines 817–999 (steps C–H)

**Function signature:**
```python
async def create_agent_fleet(
    config: SystemConfig,
    registry: AgentRegistry,
    spawner: AgentSpawner,
    pools: dict[str, ResourcePool],
    identity_registry: ...,
    callsign_registry: CallsignRegistry,
    trust_network: TrustNetwork,
    hebbian_router: HebbianRouter,
    llm_client: BaseLLMClient,
    episodic_memory: ...,
    working_memory: WorkingMemoryManager,
    intent_bus: IntentBus,
    signal_manager: SignalManager,
    credential_store: CredentialStore,
    decomposer: IntentDecomposer,
    codebase_index_config: ...,
) -> AgentFleetResult:
```

**Actions to move:**
- Create `AgentOnboardingService` (with `ontology=None, ward_room=None, acm=None` — patched later)
- All pool creation calls (lines 836–929): 7 core pools + utility pools + cognitive pools
- `CodebaseIndex.build()` + codebase_skill attachment
- `decomposer.refresh_descriptors()`
- Strategy advisor wiring to CognitiveAgent instances
- `_spawn_red_team()`

**Returns:** `AgentFleetResult` with `onboarding_service`, `codebase_index`, `red_team_agents`.

**Important:** The pool creation block uses late imports and complex agent configuration. Move it as-is. Do NOT refactor the pool creation logic itself — that's a separate future AD.

---

### Phase 3: `src/probos/startup/fleet_organization.py` — Pool Groups, Scaler, Federation

**Extract from:** Lines 1001–1133 (steps I–K)

**Function signature:**
```python
async def organize_fleet(
    config: SystemConfig,
    pools: dict[str, ResourcePool],
    pool_groups: PoolGroupRegistry,
    escalation_manager: EscalationManager,
    intent_bus: IntentBus,
    trust_network: TrustNetwork,
    llm_client: BaseLLMClient,
) -> FleetOrganizationResult:
```

**Actions to move:**
- Register 8 pool groups (lines 1001–1071)
- Create `PoolScaler` (lines 1073–1089)
- **PATCH:** `escalation_manager._surge_fn = pool_scaler.request_surge` — document with comment, preserve for now
- Federation transport + bridge creation (lines 1093–1133, config-gated)
- **PATCH:** `intent_bus._federation_fn = bridge.forward_intent` — document with comment, preserve for now

**Returns:** `FleetOrganizationResult` with `pool_scaler`, `federation_bridge`, `federation_transport`.

---

### Phase 4: `src/probos/startup/cognitive_services.py` — Self-Mod, Feedback, Memory, Knowledge

**Extract from:** Lines 1135–1309 (steps L–R)

**Function signature:**
```python
async def init_cognitive_services(
    config: SystemConfig,
    data_dir: Path,
    registry: AgentRegistry,
    spawner: AgentSpawner,
    pools: dict[str, ResourcePool],
    llm_client: BaseLLMClient,
    trust_network: TrustNetwork,
    hebbian_router: HebbianRouter,
    episodic_memory: ...,
    intent_bus: IntentBus,
    working_memory: WorkingMemoryManager,
    codebase_index: ...,
    # ... other concrete deps
) -> CognitiveServicesResult:
```

**Actions to move:**
- Self-modification pipeline creation: designer, validator, sandbox, monitor, pipeline (lines 1135–1204)
- Skills pool + SystemQA pool creation
- `episodic_memory.start()` (line 1207)
- FeedbackEngine, CorrectionDetector, AgentPatcher (lines 1210–1228)
- KnowledgeStore initialization (lines 1230–1242)
- WarmBootService creation + `restore()` (lines 1244–1263)
- Lifecycle detection — session_last.json (lines 1265–1284)
- RecordsStore initialization (lines 1286–1298)
- StrategyAdvisor creation (lines 1300–1309)

**Returns:** `CognitiveServicesResult` with `self_mod_pipeline`, `behavioral_monitor`, `system_qa`, `feedback_engine`, `correction_detector`, `agent_patcher`, `knowledge_store`, `warm_boot_service`, `records_store`, `strategy_advisor`, `cold_start` flag, `fresh_boot` flag, `lifecycle_state`, `stasis_duration`, `previous_session`.

---

### Phase 5: `src/probos/startup/dreaming.py` — Dreaming, Detection, Scheduling

**Extract from:** Lines 1311–1420 (steps S–X)

**Function signature:**
```python
async def init_dreaming(
    config: SystemConfig,
    registry: AgentRegistry,
    trust_network: TrustNetwork,
    hebbian_router: HebbianRouter,
    episodic_memory: ...,
    knowledge_store: ...,
    llm_client: BaseLLMClient,
    cold_start: bool,
    ward_room: ...,
) -> DreamingResult:
```

**Actions to move:**
- DreamingEngine + DreamScheduler (lines 1311–1336)
- EmergentDetector (lines 1338–1361)
- Cold start announcement to Ward Room (lines 1363–1395) — only if `cold_start` is True
- Dream callback wiring (lines 1397–1402) — these will be RE-WIRED in Phase 8 to use DreamAdapter. For now, wire to placeholder lambdas or skip if DreamAdapter is created in same pass.
- TaskScheduler + scout scan (lines 1404–1417)
- Create periodic flush task (lines 1419–1420)

**Returns:** `DreamingResult` with `dream_scheduler`, `dreaming_engine`, `emergent_detector`, `task_scheduler`, `flush_task`.

---

### Phase 6: `src/probos/startup/structural_services.py` — SIF, Initiative, Build, Tasks, Profiles, Directives

**Extract from:** Lines 1422–1498 (steps Y–AF)

**Function signature:**
```python
async def init_structural_services(
    config: SystemConfig,
    data_dir: Path,
    registry: AgentRegistry,
    pools: dict[str, ResourcePool],
    trust_network: TrustNetwork,
    hebbian_router: HebbianRouter,
    knowledge_store: ...,
    emergent_detector: ...,
    sif_deps: ...,
) -> StructuralServicesResult:
```

**Actions to move:**
- SemanticKnowledgeLayer (lines 1422–1434)
- Manifest persistence + trust reconciliation (lines 1436–1443)
- StructuralIntegrityField creation + `.start()` (lines 1445–1453)
- InitiativeEngine (lines 1455–1464)
- BuildQueue, WorktreeManager, BuildDispatcher (lines 1466–1477)
- TaskTracker (lines 1479–1481)
- ServiceProfileStore (lines 1483–1488)
- DirectiveStore (lines 1490–1498)

**Returns:** `StructuralServicesResult` with `semantic_layer`, `sif`, `initiative`, `build_queue`, `build_dispatcher`, `task_tracker`, `service_profiles`, `directive_store`.

---

### Phase 7: `src/probos/startup/communication.py` — Ward Room, Assignments, Alerts, Journal, Skills, ACM, Ontology

**Extract from:** Lines 1500–1720 (steps AG–AO)

**Function signature:**
```python
async def init_communication(
    config: SystemConfig,
    data_dir: Path,
    registry: AgentRegistry,
    trust_network: TrustNetwork,
    identity_registry: ...,
    # ... other concrete deps
) -> CommunicationResult:
```

**Actions to move:**
- PersistentTaskStore (lines 1500–1532)
- WorkItemStore + resource registration (lines 1534–1548)
- WardRoomService creation + `.start()` + channel subscriptions + prune loop + DM archive loop (lines 1550–1613)
- AssignmentService (lines 1615–1624)
- BridgeAlertService (lines 1626–1634)
- CognitiveJournal (lines 1636–1644)
- SkillRegistry + AgentSkillService (lines 1646–1654)
- AgentCapitalService (lines 1656–1664)
- VesselOntologyService + ship commissioning + birth certificates (lines 1666–1720)

**Returns:** `CommunicationResult` with `persistent_task_store`, `work_item_store`, `ward_room`, `assignment_service`, `bridge_alerts`, `cognitive_journal`, `skill_registry`, `skill_service`, `acm`, `ontology`.

---

### Phase 8: `src/probos/startup/finalize.py` — Proactive Loop, Service Wiring, Finalization

**Extract from:** Lines 1722–1896 (steps AP–AR)

**Function signature:**
```python
async def finalize_startup(
    runtime: "ProbOSRuntime",  # Full runtime ref needed for service wiring
    config: SystemConfig,
    # ... service references from previous phases
) -> FinalizationResult:
```

**Note:** This phase is the one exception that receives the runtime reference, because it wires the AD-515 extracted services (WardRoomRouter, SelfModManager, DreamAdapter) which need many runtime attributes as constructor params. Passing individual deps would mean 30+ parameters.

**Actions to move:**
- ConnManager, NightOrdersManager, WatchManager (lines 1728–1730)
- ProactiveCognitiveLoop creation + `.start()` (lines 1740–1756)
- **PATCH:** `proactive_loop._knowledge_store` — document, preserve for now
- WardRoomRouter creation (line 1762)
- Onboarding late-dep patches (lines 1778–1781) — `_ontology`, `_ward_room`, `_acm`, `_start_time_wall`
- SelfModManager creation (line 1785)
- DreamAdapter creation (line 1810)
- **PATCH:** `dream_adapter._cold_start` — document, preserve for now
- Re-wire dream callbacks to DreamAdapter (lines 1835–1837)
- Re-wire flush task to DreamAdapter (line 1842)
- Mark `_started = True`
- Emit startup event + log startup announcement

**Returns:** `FinalizationResult` with `conn_manager`, `night_orders_mgr`, `watch_manager`, `proactive_loop`, `ward_room_router`, `self_mod_manager`, `dream_adapter`.

---

## Rewritten `start()` Method

After extraction, `start()` should look approximately like this:

```python
async def start(self) -> None:
    """Start all ProbOS subsystems in dependency order."""
    from probos.startup import (
        infrastructure, agent_fleet, fleet_organization,
        cognitive_services, dreaming, structural_services,
        communication, finalize,
    )

    # Phase 1: Infrastructure
    infra = await infrastructure.boot_infrastructure(
        event_log=self.event_log,
        hebbian_router=self.hebbian_router,
        signal_manager=self.signal_manager,
        gossip=self.gossip,
        trust_network=self.trust_network,
        data_dir=self._data_dir,
        config=self.config,
    )
    self.identity_registry = infra.identity_registry

    # Phase 2: Agent Fleet
    fleet = await agent_fleet.create_agent_fleet(...)
    self._onboarding = fleet.onboarding_service
    self.codebase_index = fleet.codebase_index
    self._red_team_agents = fleet.red_team_agents

    # Phase 3: Fleet Organization
    org = await fleet_organization.organize_fleet(...)
    self.pool_scaler = org.pool_scaler
    self.federation_bridge = org.federation_bridge

    # Phase 4: Cognitive Services
    cog = await cognitive_services.init_cognitive_services(...)
    self.self_mod_pipeline = cog.self_mod_pipeline
    self._knowledge_store = cog.knowledge_store
    # ... assign all cognitive service attrs

    # Phase 5: Dreaming & Detection
    dream = await dreaming.init_dreaming(...)
    self.dream_scheduler = dream.dream_scheduler
    self._emergent_detector = dream.emergent_detector

    # Phase 6: Structural Services
    struct = await structural_services.init_structural_services(...)
    self.sif = struct.sif
    self.build_dispatcher = struct.build_dispatcher

    # Phase 7: Communication
    comm = await communication.init_communication(...)
    self.ward_room = comm.ward_room
    self.ontology = comm.ontology

    # Phase 8: Finalization & Service Wiring
    final = await finalize.finalize_startup(runtime=self, ...)
    self._ward_room_router = final.ward_room_router
    self._self_mod_manager = final.self_mod_manager
    self._dream_adapter = final.dream_adapter

    self._started = True
```

## General Rules

1. **Zero behavior changes.** Every test must pass unchanged.
2. **Preserve initialization order exactly.** Dependencies flow forward — later phases depend on earlier phase outputs.
3. **One phase per file.** Each file in `src/probos/startup/` contains one async phase function + any helper functions it needs.
4. **No circular imports.** Use `TYPE_CHECKING` blocks for type annotations. Use lazy imports inside functions for heavy modules.
5. **Structured logging.** Each phase function: `logger.info("Startup [%s]: starting", phase_name)` at entry, `logger.info("Startup [%s]: complete", phase_name)` at exit.
6. **Comment every remaining `_private_attr` patch** with `# PATCH(AD-517): <reason>` so they're findable for future cleanup.
7. **Do NOT refactor the logic inside any step.** Move code blocks exactly as they are. The goal is extraction, not improvement.
8. **Test after EACH phase extraction.** Don't batch. Extract Phase 1, run tests, commit. Then Phase 2, etc.
9. **Update `stop()` if needed.** If any cleanup logic in `stop()` moves to a phase module, add a corresponding `teardown_*()` function. But prefer keeping `stop()` in runtime.py for now — it's only 257 lines and less critical.

## Build Order

1. Create `src/probos/startup/` package + `results.py` with all result dataclasses
2. Phase 1: infrastructure.py — extract and test
3. Phase 2: agent_fleet.py — extract and test
4. Phase 3: fleet_organization.py — extract and test
5. Phase 4: cognitive_services.py — extract and test
6. Phase 5: dreaming.py — extract and test
7. Phase 6: structural_services.py — extract and test
8. Phase 7: communication.py — extract and test
9. Phase 8: finalize.py — extract and test
10. Rewrite `start()` as phase-call sequence — final test

## Success Criteria

- `start()` is ≤80 lines — a readable phase checklist
- `runtime.py` reduced by ≥800 lines
- 8 new files in `src/probos/startup/`
- All existing tests pass with zero modifications (ideally) or minimal test helper updates
- Every `_private_attr` patch has a `# PATCH(AD-517)` comment
- No new `Any` type annotations in the new phase modules
