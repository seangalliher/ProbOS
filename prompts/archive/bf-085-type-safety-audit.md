# BF-085: Type Safety Audit

**Priority:** Medium
**Wave:** 4 (Code Review Closure)
**Finding:** Code review #11 — ~70 remaining `Any` annotations (actual count: ~400 tightenable)
**Connects to:** BF-079 Phase 2/3 (blocked on ProbOSRuntime class-level annotations)

## Goal

Replace avoidable `Any` type annotations with concrete types using `TYPE_CHECKING` + string annotations. This is NOT about touching every `Any` — it's about fixing the ~400 that are lazy circular-import avoidance while leaving the ~500 legitimate `dict[str, Any]` JSON-shaped annotations alone.

**Critical secondary goal:** Add class-level type annotations to `ProbOSRuntime` so that `MagicMock(spec=ProbOSRuntime)` exposes all service attributes. This unblocks BF-079 Phase 2/3.

## Constraints

- **Pure type annotation changes.** No behavior changes, no logic changes, no refactoring.
- **Do NOT touch `dict[str, Any]`** — these are legitimate JSON/serialization boundaries.
- **Do NOT touch `**kwargs: Any`** — this is standard Python.
- **Use `from __future__ import annotations`** (already present in most files) + `TYPE_CHECKING` imports. This avoids circular import issues at runtime.
- **All tests must pass.** Type annotations are erased at runtime with `from __future__ import annotations`, so this should be zero-risk.

## Phased Approach

### Phase 1: ProbOSRuntime Class-Level Annotations (CRITICAL — unblocks BF-079)

**File:** `src/probos/runtime.py`

Add class-level type annotations for ALL 87 instance attributes. The values are still assigned in `__init__()`, but the class body declares the attribute names and types so `MagicMock(spec=ProbOSRuntime)` can see them.

**Pattern:**
```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.substrate.registry import AgentRegistry
    from probos.trust import TrustNetwork
    from probos.ward_room import WardRoomService
    # ... all other types

class ProbOSRuntime:
    # --- Class-level type annotations (enables spec= on mocks) ---

    # Constructor params
    config: SystemConfig

    # Substrate layer
    registry: AgentRegistry
    spawner: AgentSpawner
    pools: dict[str, ResourcePool]
    pool_groups: PoolGroupRegistry

    # Mesh layer
    signal_manager: SignalManager
    intent_bus: IntentBus
    capability_registry: CapabilityRegistry
    hebbian_router: HebbianRouter
    gossip: GossipProtocol

    # ... etc for all 87 attributes

    def __init__(self, config=None, ...):
        # Existing __init__ code unchanged
```

**Complete attribute list with correct types:**

Substrate layer:
- `registry: AgentRegistry` — from `probos.substrate.registry`
- `spawner: AgentSpawner` — from `probos.substrate.spawner`
- `pools: dict[str, ResourcePool]` — from `probos.substrate.pool`
- `pool_groups: PoolGroupRegistry` — from `probos.substrate.pool_group`

Mesh layer:
- `signal_manager: SignalManager` — from `probos.mesh.signal`
- `intent_bus: IntentBus` — from `probos.mesh.intent`
- `capability_registry: CapabilityRegistry` — from `probos.mesh.capability`
- `hebbian_router: HebbianRouter` — from `probos.routing`
- `gossip: GossipProtocol` — from `probos.mesh.gossip`

Consensus/Trust:
- `event_log: EventLog` — from `probos.event_log`
- `credential_store: CredentialStore` — from `probos.credential_store`
- `callsign_registry: CallsignRegistry` — from `probos.callsign_registry`
- `quorum_engine: QuorumEngine` — from `probos.consensus.quorum`
- `trust_network: TrustNetwork` — from `probos.trust`

Cognitive:
- `llm_client: BaseLLMClient` — from `probos.llm`
- `working_memory: WorkingMemoryManager` — from `probos.cognitive.working_memory`
- `workflow_cache: WorkflowCache` — from `probos.cognitive.workflow_cache`
- `decomposer: IntentDecomposer` — from `probos.cognitive.decomposer`
- `attention: AttentionManager` — from `probos.cognitive.attention`
- `escalation_manager: EscalationManager` — from `probos.consensus.escalation`
- `dag_executor: DAGExecutor` — from `probos.cognitive.dag_executor`

Deferred-init services (currently `Any`, need concrete types):
- `episodic_memory: EpisodicMemory | None` — from `probos.episodic` (or `probos.cognitive.episodic`)
- `ward_room: WardRoomService | None` — from `probos.ward_room`
- `ward_room_router: WardRoomRouter | None` — from `probos.ward_room_router`
- `assignment_service: AssignmentService | None` — from `probos.workforce`
- `bridge_alerts: BridgeAlertManager | None` — from `probos.bridge_alerts`
- `dream_scheduler: DreamScheduler | None` — from `probos.cognitive.dreaming`
- `task_scheduler: TaskScheduler | None` — look up actual class
- `persistent_task_store: PersistentTaskStore | None` — from `probos.persistent_tasks`
- `work_item_store: WorkItemStore | None` — from `probos.workforce`
- `cognitive_journal: CognitiveJournal | None` — from `probos.cognitive.journal`
- `skill_registry: SkillRegistry | None` — from `probos.cognitive.codebase_skill`
- `skill_service: SkillService | None` — from `probos.cognitive.codebase_skill`
- `acm: AgentCapitalManager | None` — from `probos.acm`
- `ontology: VesselOntology | None` — from `probos.ontology` or wherever it lives
- `identity_registry: IdentityRegistry | None` — from `probos.identity`
- `pool_scaler: PoolScaler | None` — from `probos.substrate.scaler`
- `federation_bridge: FederationBridge | None` — from `probos.federation.bridge`
- `self_mod_pipeline: SelfModPipeline | None` — from `probos.cognitive.self_mod`
- `behavioral_monitor: BehavioralMonitor | None` — look up actual class
- `onboarding: AgentOnboardingService | None` — from `probos.agent_onboarding`
- `warm_boot: WarmBootService | None` — from `probos.warm_boot`
- `self_mod_manager: SelfModManager | None` — from `probos.self_mod_manager`
- `dream_adapter: DreamAdapter | None` — from `probos.dream_adapter`
- `feedback_engine: FeedbackEngine | None` — from `probos.cognitive.feedback`
- `proactive_loop: ProactiveLoop | None` — from `probos.proactive`
- `codebase_index: CodebaseIndex | None` — from `probos.cognitive.codebase_index`
- `sif: StructuralIntegrityField | None` — from `probos.sif`
- `initiative: InitiativeEngine | None` — from `probos.initiative`
- `build_queue: BuildQueue | None` — from `probos.build_queue`
- `build_dispatcher: BuildDispatcher | None` — from `probos.build_dispatcher`
- `task_tracker: TaskTracker | None` — from `probos.task_tracker`
- `service_profiles: ServiceProfileStore | None` — look up actual class
- `directive_store: DirectiveStore | None` — from `probos.directives` or wherever
- `notification_queue: NotificationQueue` — from `probos.notifications` or wherever
- `conn_manager: ConnManager | None` — from `probos.conn`
- `watch_manager: WatchManager | None` — from `probos.watch_rotation`

Private attributes (also need class-level annotations for completeness):
- `_data_dir: Path`
- `_checkpoint_dir: Path`
- `_red_team_agents: list`
- `_cold_start: bool`
- `_start_time: float`
- `_recent_errors: list[str]`
- `_last_capability_gap: str`
- `_system_qa: SystemQAAgent | None` — look up actual type
- `_qa_reports: dict[str, Any]`
- `_knowledge_store: KnowledgeStore | None` — from `probos.knowledge.store`
- `_records_store: RecordsStore | None` — from `probos.knowledge.records_store`
- `_last_execution: dict[str, Any] | None`
- `_previous_execution: dict[str, Any] | None`
- `_pending_proposal: TaskDAG | None`
- `_pending_proposal_text: str`
- `_last_feedback_applied: bool`
- `_last_execution_text: str | None`
- `_last_shapley_values: dict[str, float] | None`
- `_correction_detector: CorrectionDetector | None` — from `probos.cognitive.correction_detector`
- `_agent_patcher: AgentPatcher | None` — from `probos.cognitive.agent_patcher`
- `_emergent_detector: EmergentDetector | None` — from `probos.cognitive.emergent_detector` or similar
- `_strategy_advisor: StrategyAdvisor | None` — look up actual class
- `_semantic_layer: SemanticKnowledgeLayer | None` — from `probos.knowledge.semantic`
- `_event_listeners: list[Callable]`
- `_started: bool`
- `_fresh_boot: bool`
- `_start_time_wall: float`
- `_session_id: str`
- `_lifecycle_state: str`
- `_stasis_duration: float`
- `_previous_session: dict | None`
- `_night_orders_mgr: NightOrdersManager | None` — from `probos.watch_rotation`
- `_federation_transport: FederationTransport | None` — from `probos.federation.transport`
- `_last_request_time: float`

**IMPORTANT:** Look up the actual class names and import paths before writing annotations. The names above are best guesses — verify each one against the actual codebase. Some may be slightly different (e.g., `WardRoomService` vs `WardRoom`, `EpisodicMemory` vs `EpisodicMemoryStore`).

**All TYPE_CHECKING imports go inside `if TYPE_CHECKING:` block** to avoid circular imports at runtime. With `from __future__ import annotations` at the top, string evaluation is deferred and circular imports never execute.

**Validation:** After adding class-level annotations, verify:
```python
# This should work now:
import inspect
members = set(dir(ProbOSRuntime)) | set(ProbOSRuntime.__annotations__)
assert 'registry' in members
assert 'trust_network' in members
assert 'ward_room' in members
```

### Phase 2: Protocol Tightening (Highest Leverage)

**File:** `src/probos/protocols.py` (~17 `Any` uses)

Fix the 7 tightenable `Any` annotations in protocol definitions. Since protocols propagate types to all implementations, this has the highest ROI.

**Changes:**
1. `EpisodicMemoryProtocol.recall() -> list[Any]` → `-> list[Episode]` (or appropriate type)
2. `TrustNetworkProtocol.get_or_create() -> Any` → `-> TrustRecord` (or appropriate type)
3. `WardRoomProtocol.set_ontology(ontology: Any)` → `set_ontology(ontology: VesselOntology)`
4. `KnowledgeStoreProtocol` methods: `record: Any` and `episode: Any` → concrete types
5. `EventEmitterProtocol.add_event_listener(fn: Callable[..., Any])` → tighten callable signature

**Leave alone:** `dict[str, Any]` in protocol methods (legitimate JSON data), `data: dict[str, Any]` params.

Use `TYPE_CHECKING` imports for the concrete types to avoid circular imports.

### Phase 3: Router Dependencies Gateway

**File:** `src/probos/routers/deps.py` (line 10)

Change:
```python
def get_runtime(request: Request) -> Any:
```
To:
```python
def get_runtime(request: Request) -> ProbOSRuntime:
```

This single change cascades type safety to all 16 router modules (~90 `Any` occurrences eliminated). Use `TYPE_CHECKING` import for `ProbOSRuntime`.

### Phase 4: Constructor Param Cleanup (Top 5 Files)

Fix the 5 worst offender files where ALL constructor params are `Any` purely to avoid imports:

1. **`self_mod_manager.py`** (lines 24-43) — 20 params, all `Any`. Every one has a known concrete type.
2. **`dream_adapter.py`** (lines 25-40) — 16 params, all `Any`.
3. **`agent_onboarding.py`** (lines 24-37) — 14 params, all `Any`.
4. **`ward_room_router.py`** (lines 28-39) — 12 params, all `Any`.
5. **`proactive.py`** (lines 44-78) — 10+ attrs typed `Any`.

**Pattern for each file:**
```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.trust import TrustNetwork
    from probos.routing import HebbianRouter
    # ... etc

class SelfModManager:
    def __init__(
        self,
        self_mod_pipeline: SelfModPipeline,  # was Any
        knowledge_store: KnowledgeStore | None,  # was Any | None
        trust_network: TrustNetwork,  # was Any
        # ... etc
    ):
```

### Phase 5: Command Module Runtime Params

**Files:** All 10 modules in `src/probos/experience/commands/`

Every command function takes `runtime: Any` as the first parameter. Change to `runtime: ProbOSRuntime` with `TYPE_CHECKING` import.

### Phase 6: BaseAgent Lifecycle Methods

**File:** `src/probos/substrate/agent.py`

Tighten the abstract lifecycle methods:
- `perceive(intent: Any)` → `perceive(intent: str | dict[str, Any])`  (or define an `Intent` type)
- `decide(perception: Any)` → `decide(perception: dict[str, Any])` (or define a `Perception` type)
- `act(decision: Any)` → `act(decision: dict[str, Any])` (or define a `Decision` type)
- `report(result: Any)` → `report(result: dict[str, Any])` (or define a `Result` type)

**Caution:** This cascades to ~20 agent subclasses. All overrides must match the new signatures. Check each agent's actual usage to determine the right type — some may need `str | dict` union types. If the types vary too much across agents, use a `TypeVar` or keep as-is and document why.

**If this phase proves too disruptive, skip it.** The other phases are more impactful.

### Phase 7: Remaining Scattered Fixes

Fix the remaining `[LAZY]` annotations across other files:
- `rt: Any` params in `agents/introspect.py` (11 uses) → `rt: ProbOSRuntime`
- SQL `row: Any` in `workforce.py` (5 uses) → `row: sqlite3.Row`
- `cognitive/builder.py` `llm_client: Any` (3 uses) → `llm_client: BaseLLMClient`
- `cognitive/decomposer.py` constructor params (5 uses)
- `cognitive/copilot_adapter.py` `runtime: Any` + `invocation: Any` (8 uses)

## What NOT to Touch

- `dict[str, Any]` — legitimate JSON boundaries (~500 occurrences). Leave all of these.
- `**kwargs: Any` — standard Python pattern (~60 occurrences). Leave all of these.
- `Callable[..., Any]` — acceptable for generic callbacks unless the signature is known.
- Third-party types (chromadb internals) — not our types to define.
- Test files — out of scope for this BF.

## Validation

1. **All tests pass.** Type annotations with `from __future__ import annotations` are erased at runtime, so this should be zero-risk. If any test breaks, it means the code was evaluating annotations at runtime (rare but possible with Pydantic, dataclasses, or `get_type_hints()`).

2. **Phase 1 spec= verification:** After ProbOSRuntime annotations are added, run this test:
```python
from unittest.mock import MagicMock
from probos.runtime import ProbOSRuntime

rt = MagicMock(spec=ProbOSRuntime)
# These should NOT raise AttributeError:
_ = rt.registry
_ = rt.trust_network
_ = rt.ward_room
_ = rt.episodic_memory
_ = rt.hebbian_router
_ = rt.event_log
_ = rt.config
```

3. **No behavior changes.** `git diff` should show ONLY:
   - `from __future__ import annotations` additions
   - `TYPE_CHECKING` import blocks
   - `Any` → concrete type name replacements in annotations
   - Class-level annotation blocks in ProbOSRuntime

## Execution Notes

- **Phase 1 is the priority.** If time is constrained, do Phase 1 only — it unblocks BF-079 Phase 2/3.
- **Phases 2-7 are independent** and can be done in any order.
- **Phase 6 is optional** — skip if BaseAgent lifecycle types prove too varied across subclasses.
- `from __future__ import annotations` must be the FIRST import in any file that uses string-form type annotations. Check it's present before adding `TYPE_CHECKING` imports.
- Some files already have `from __future__ import annotations` (runtime.py does at line 3). Don't duplicate.
- When looking up class names, use the actual imports in the source files — don't guess. The names in this prompt are best-effort.
