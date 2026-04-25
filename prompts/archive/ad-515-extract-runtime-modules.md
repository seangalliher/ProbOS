# AD-515: Extract runtime.py Modules

## Context

`src/probos/runtime.py` is a 5,321-line god object (`ProbOSRuntime` class) that violates Single Responsibility Principle. It handles ward room routing, agent onboarding, knowledge warm boot, self-modification management, dream callbacks, DAG proposals, and more — all in one class.

AD-514 added `typing.Protocol` definitions and public API methods to prepare for this extraction. Now we extract the first wave of modules — the highest-priority, most self-contained responsibility groups.

## Objective

Extract 5 responsibility groups from `ProbOSRuntime` into dedicated modules. Each extraction follows the same pattern:
1. Create a new class in a new file
2. Move the methods from runtime.py to the new class
3. The new class receives its dependencies via constructor injection
4. Runtime.py creates the new class in `__init__` or `start()`, passing dependencies
5. Runtime.py delegates to the new class (thin wrapper or direct reference)
6. All existing tests continue to pass — zero behavior changes

## Part A: Ward Room Router (~420 lines)

Create `src/probos/ward_room_router.py` with class `WardRoomRouter`.

**Move these methods from `ProbOSRuntime`:**
- `_route_ward_room_event` → `route_event`
- `_find_ward_room_targets` → `find_targets`
- `_find_ward_room_targets_for_agent` → `find_targets_for_agent`
- `_handle_propose_improvement` → `handle_propose_improvement`
- `_cleanup_ward_room_tracking` → `cleanup_tracking`
- `_extract_endorsements` → `extract_endorsements`
- `_process_endorsements` → `process_endorsements`
- `_deliver_bridge_alert` → `deliver_bridge_alert`

**Move this state from `ProbOSRuntime.__init__`:**
- `_ward_room_cooldowns: dict[str, float]`
- `_ward_room_thread_rounds: dict[str, int]`
- `_ward_room_round_participants: dict[str, set[str]]`
- `_ward_room_agent_thread_responses: dict[str, set[str]]`
- `_WARD_ROOM_COOLDOWN_SECONDS: float`

**Constructor dependencies (inject via `__init__`):**
- `ward_room: WardRoomProtocol`
- `registry` (AgentRegistry)
- `intent_bus` (IntentBus)
- `trust_network: TrustNetworkProtocol`
- `ontology` (VesselOntologyService)
- `callsign_registry` (CallsignRegistry)
- `episodic_memory: EpisodicMemoryProtocol`
- `event_emitter: EventEmitterProtocol`
- `event_log: EventLogProtocol`
- `config` (ProbOSConfig — for ward room settings)

**In runtime.py:**
- Create `self._ward_room_router = WardRoomRouter(...)` in `start()` after ward room is initialized
- Replace all calls to the moved methods with delegation: `self._ward_room_router.route_event(...)`, etc.
- The `_is_crew_agent` helper is used by the router — extract it as a module-level utility function in `ward_room_router.py` or pass a callable.

## Part B: Agent Onboarding (~320 lines)

Create `src/probos/agent_onboarding.py` with class `AgentOnboardingService`.

**Move these methods from `ProbOSRuntime`:**
- `_wire_agent` → `wire_agent`
- `_run_naming_ceremony` → `run_naming_ceremony`
- The nested `_is_valid_callsign` inside `_run_naming_ceremony` stays nested

**Constructor dependencies:**
- `callsign_registry` (CallsignRegistry)
- `capability_registry` (CapabilityRegistry)
- `gossip` (GossipProtocol or concrete type)
- `intent_bus` (IntentBus)
- `trust_network: TrustNetworkProtocol`
- `event_log: EventLogProtocol`
- `identity_registry` (IdentityRegistry)
- `ontology` (VesselOntologyService)
- `event_emitter: EventEmitterProtocol`
- `config` (ProbOSConfig — for onboarding settings)
- `llm_client` (for naming ceremony LLM calls)

**In runtime.py:**
- Create `self._onboarding = AgentOnboardingService(...)` in `start()`
- In `create_pool` / agent creation flow, delegate to `self._onboarding.wire_agent(agent)`

## Part C: Warm Boot / Knowledge Restore (~235 lines)

Create `src/probos/warm_boot.py` with class `WarmBootService`.

**Move these methods from `ProbOSRuntime`:**
- `_restore_from_knowledge` → `restore()`

**Constructor dependencies:**
- `knowledge_store: KnowledgeStoreProtocol`
- `trust_network: TrustNetworkProtocol`
- `hebbian_router: HebbianRouterProtocol`
- `episodic_memory: EpisodicMemoryProtocol`
- `workflow_cache` (WorkflowCache)
- `config` (ProbOSConfig — for self_mod and knowledge settings)

**In runtime.py:**
- Create `self._warm_boot = WarmBootService(...)` in `start()` before the restore call
- Replace `self._restore_from_knowledge()` with `self._warm_boot.restore()`

## Part D: Self-Modification Manager (~290 lines)

Create `src/probos/self_mod_manager.py` with class `SelfModManager`.

**Move these methods from `ProbOSRuntime`:**
- `apply_correction` → `apply_correction`
- `_apply_agent_correction` → `_apply_agent_correction`
- `_apply_skill_correction` → `_apply_skill_correction`
- `_find_designed_record` → `_find_designed_record`
- `_was_last_execution_successful` → `_was_last_execution_successful`
- `_format_execution_context` → `_format_execution_context`
- `_register_designed_agent` → `register_designed_agent`
- `_unregister_designed_agent` → `unregister_designed_agent`
- `_create_designed_pool` → `create_designed_pool`
- `_set_probationary_trust` → `set_probationary_trust`

**Constructor dependencies:**
- `self_mod_pipeline` (SelfModificationPipeline)
- `knowledge_store: KnowledgeStoreProtocol`
- `trust_network: TrustNetworkProtocol`
- `intent_bus` (IntentBus)
- `capability_registry` (CapabilityRegistry)
- `registry` (AgentRegistry)
- `pools` (dict of pools)
- `spawner` (AgentSpawner)
- `decomposer` (IntentDecomposer)
- `feedback_engine` (FeedbackEngine)
- `llm_client`
- `event_emitter: EventEmitterProtocol`
- `config` (ProbOSConfig)

**In runtime.py:**
- Create `self._self_mod_manager = SelfModManager(...)` in `start()`
- Delegate `apply_correction` and designed-agent methods to the manager

## Part E: Dream Adapter (~200 lines)

Create `src/probos/dream_adapter.py` with class `DreamAdapter`.

**Move these methods from `ProbOSRuntime`:**
- `recall_similar` → `recall_similar`
- `_on_pre_dream` → `on_pre_dream`
- `_on_post_dream` → `on_post_dream`
- `_store_strategies` → `_store_strategies`
- `_on_gap_predictions` → `on_gap_predictions`
- `_on_contradictions` → `on_contradictions`
- `_on_post_micro_dream` → `on_post_micro_dream`
- `_periodic_flush` → `periodic_flush`
- `_periodic_flush_loop` → `periodic_flush_loop`
- `_build_episode` → `build_episode`
- `_refresh_emergent_detector_roster` → `refresh_emergent_detector_roster`

**Constructor dependencies:**
- `dream_scheduler` (DreamScheduler)
- `emergent_detector` (EmergentDetector)
- `episodic_memory: EpisodicMemoryProtocol`
- `knowledge_store: KnowledgeStoreProtocol`
- `hebbian_router: HebbianRouterProtocol`
- `trust_network: TrustNetworkProtocol`
- `event_emitter: EventEmitterProtocol`
- `self_mod_pipeline` (SelfModificationPipeline)
- `bridge_alerts` (BridgeAlertManager)
- `ward_room: WardRoomProtocol`
- `registry` (AgentRegistry)
- `config` (ProbOSConfig)

**In runtime.py:**
- Create `self._dream_adapter = DreamAdapter(...)` in `start()`
- Wire dream callbacks to the adapter instead of `self`

## General Rules

1. **Zero behavior changes.** Every extraction is a pure structural refactor. Inputs, outputs, side effects all identical.
2. **Constructor injection only.** No global imports of runtime, no circular dependencies. Each new class receives exactly what it needs.
3. **Type annotations on all public methods.** Follow the Engineering Principles in `.github/copilot-instructions.md`.
4. **Structured logging.** Each new module gets its own logger: `logger = logging.getLogger(__name__)`.
5. **Preserve private method names internally.** Public API methods drop the `_` prefix. Internal helpers can keep `_` prefix within the new class.
6. **imports in runtime.py.** Add imports for the new classes at the top of runtime.py. Remove any imports that were only used by the extracted methods (if they're now imported in the new module instead).
7. **`_is_crew_agent` utility.** This helper is used by multiple extracted modules. Extract it as a standalone function (not in a class) — either in a shared utility module or duplicate it where needed (it's ~10 lines). Prefer a single location.

## Acceptance Criteria

- [ ] 5 new files created: `ward_room_router.py`, `agent_onboarding.py`, `warm_boot.py`, `self_mod_manager.py`, `dream_adapter.py`
- [ ] All methods moved from `ProbOSRuntime` to the appropriate new class
- [ ] `runtime.py` creates each new service in `start()` and delegates to them
- [ ] `runtime.py` reduced by ~1,400+ lines
- [ ] All existing tests pass — zero regressions
- [ ] All new classes use constructor injection — no imports of `ProbOSRuntime`
- [ ] Type annotations on all public method signatures
- [ ] Each new module has its own `logging.getLogger(__name__)`
- [ ] No circular imports
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Testing

Run the full test suite after each part extraction (A through E). If a test breaks, fix it before proceeding to the next part. The extraction should be invisible to tests — same behavior, different file locations.

After all parts complete, run: `python -m pytest tests/ -x -q`

Report: total tests passing, any failures, final line count of runtime.py.
