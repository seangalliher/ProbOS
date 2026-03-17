# Era I: Genesis — Building the Ship

*Phases 1-9: Substrate, Mesh, Consensus, Cognitive, Experience, Scaling, Federation*

This era established ProbOS's core architecture — the seven layers from Substrate to Experience, plus Federation. By the end of Genesis, ProbOS could decompose natural language into intent DAGs, execute them through a self-organizing mesh with consensus governance, learn from experience via Hebbian routing and episodic memory, consolidate during dreaming, and federate across multiple nodes.

---

## What's Been Built

### Substrate Layer (complete)

| File | Status | Description |
|------|--------|-------------|
| `pyproject.toml` | done | Project config, deps (pydantic, pyyaml, aiosqlite, rich, pytest) |
| `config/system.yaml` | done | Pool sizes, mesh params, heartbeat intervals, consensus config, memory config, dreaming config, scaling config, federation config, self-mod config, QA config (smoke_test_count, pass_threshold, timeout per test/total, trust reward/penalty weights — AD-153), per-tier LLM endpoints (fast=qwen3.5:35b at Ollama localhost:11434 native API, standard=claude-sonnet-4.6 at Copilot proxy localhost:8080, deep=claude-opus-4.6 at Copilot proxy — AD-132), `default_llm_tier: "fast"` (AD-137), `llm_api_format_fast: "ollama"` (AD-145) |
| `src/probos/__init__.py` | done | Package root, version 0.1.0 |
| `src/probos/types.py` | done | `AgentState`, `AgentMeta`, `CapabilityDescriptor`, `IntentMessage`, `IntentResult`, `GossipEntry`, `ConnectionWeight`, `ConsensusOutcome`, `Vote`, `QuorumPolicy`, `ConsensusResult`, `VerificationResult`, `LLMTier`, `LLMRequest`, `LLMResponse`, `EscalationTier` (3-tier cascade levels: retry, arbitration, user), `EscalationResult` (escalation outcome with `to_dict()` for JSON-safe serialization, `tiers_attempted` tracking), `TaskNode` (with `background` field for background demotion, `escalation_result: dict | None` for serialized escalation data), `TaskDAG` (with `response` field for conversational LLM replies, `reflect` field for post-execution synthesis), `Episode` (episodic memory record), `AttentionEntry` (priority scoring for task scheduling), `FocusSnapshot` (cross-request focus history), `DreamReport` (dream cycle results), `WorkflowCacheEntry` (cached workflow pattern), `IntentDescriptor` (structured metadata for dynamic intent discovery: name, params, description, requires_consensus, requires_reflect), `Skill` (modular intent handler with descriptor, source_code, compiled handler — AD-128), `NodeSelfModel` (peer node capability/health snapshot for gossip), `FederationMessage` (wire protocol message between nodes) |
| `src/probos/config.py` | done | `PoolConfig`, `MeshConfig`, `ConsensusConfig`, `CognitiveConfig` (with `max_concurrent_tasks`, `attention_decay_rate`, `focus_history_size`, `background_demotion_factor`, per-tier endpoint fields: `llm_base_url_fast/standard/deep`, `llm_api_key_fast/standard/deep`, `llm_timeout_fast/standard/deep` — all `None` by default for backward compat, per-tier API format: `llm_api_format_fast/standard/deep` — `"ollama"` or `"openai"` (default) — AD-145, `tier_config()` helper returns resolved {base_url, api_key, model, timeout, api_format} per tier — AD-132, `default_llm_tier: str = "fast"` — AD-137), `MemoryConfig`, `DreamingConfig` (idle threshold, dream interval, replay count, strengthening/weakening factors, prune threshold, trust boost/penalty, pre-warm top-K), `ScalingConfig` (scale up/down thresholds, step sizes, cooldown, observation window, idle scale-down), `PeerConfig` (node_id + address for static peer list), `FederationConfig` (enabled, node_id, bind_address, peers, forward_timeout, gossip interval, validate_remote_results), `SelfModConfig` (enabled, require_user_approval, probationary_alpha/beta, max_designed_agents, sandbox_timeout, allowed_imports whitelist, forbidden_patterns regex list, research_enabled, research_domain_whitelist, research_max_pages, research_max_content_per_page — AD-130), `QAConfig` (enabled, smoke_test_count, timeout_per_test_seconds, total_timeout_seconds, pass_threshold, trust_reward_weight, trust_penalty_weight, flag_on_fail, auto_remove_on_total_fail — AD-153), `SystemConfig`, `load_config()` — pydantic models loaded from YAML, None-section filtering for commented YAML |
| `src/probos/substrate/agent.py` | done | `BaseAgent` ABC — `perceive/decide/act/report` lifecycle, confidence tracking, state transitions, async start/stop, optional `_runtime` reference via `**kwargs`, `**kwargs` passthrough to subclasses, class-level `intent_descriptors: list[IntentDescriptor]` for dynamic intent discovery, `tier` classification (`core`/`utility`/`domain`, Phase 14d), `instructions: str | None = None` (Phase 15a — optional LLM instructions; CognitiveAgent requires them) |
| `src/probos/substrate/registry.py` | done | `AgentRegistry` — in-memory index, lookup by ID/pool/capability, async-safe |
| `src/probos/substrate/spawner.py` | done | `AgentSpawner` — template registration, `spawn(**kwargs)`, `recycle()` with identity-preserving respawn (Phase 14c), `**kwargs` forwarded to agent constructors |
| `src/probos/substrate/pool.py` | done | `ResourcePool` — maintains N agents at target size, background health loop, auto-recycles degraded agents, `**spawn_kwargs` forwarding for agent construction, `add_agent()`/`remove_agent()` with min/max bounds enforcement, trust-aware scale-down selection, deterministic agent IDs (Phase 14c) |
| `src/probos/substrate/identity.py` | done | `generate_agent_id()`, `generate_pool_ids()` — deterministic ID generation from deployment topology `hash(agent_type, pool_name, instance_index)` (Phase 14c). `_ID_REGISTRY` module-level registry populated on each `generate_agent_id()` call. `parse_agent_id()` — reverses ID to `{agent_type, pool_name}` via registry lookup first, then right-to-left regex parsing with hash verification fallback (AD-241) |
| `src/probos/substrate/scaler.py` | done | `PoolScaler` — demand-driven background loop, per-pool demand ratio evaluation, scale up/down with cooldown, `request_surge()` for escalation, `scale_down_idle()` for dreaming, pool exclusions, pinned pool detection, `scaling_status()` for shell/panel |
| `src/probos/substrate/heartbeat.py` | done | `HeartbeatAgent` — fixed-interval pulse loop, listener callbacks, gossip carrier |
| `src/probos/substrate/event_log.py` | done | `EventLog` — append-only SQLite event log for lifecycle, mesh, system, and consensus events |
| `src/probos/agents/heartbeat_monitor.py` | done | `SystemHeartbeatAgent` — collects CPU count, load average, platform, PID |

### Mesh Layer (complete)

| File | Status | Description |
|------|--------|-------------|
| `src/probos/mesh/signal.py` | done | `SignalManager` — TTL enforcement, background reaper loop, expiry callbacks |
| `src/probos/mesh/intent.py` | done | `IntentBus` — async pub/sub, concurrent fan-out to subscribers, result collection with timeout, error handling, per-broadcast demand tracking with sliding window, `per_pool_demand()` for scaler, `_federation_fn` callback for federated forwarding, `federated` parameter on `broadcast()` for loop prevention |
| `src/probos/mesh/capability.py` | done | `CapabilityRegistry` — semantic descriptor store, tiered matching (exact/substring/semantic/keyword), embedding-based semantic matching via `compute_similarity()` (Phase 14b), `semantic_matching` config flag, scored results, optional `trust_scores` parameter for trust-weighted matching: `final = score * (0.5 + 0.5 * trust)` — floor at 50%, never eliminates matches (AD-225) |
| `src/probos/mesh/routing.py` | done | `HebbianRouter` — connection weights with `rel_type` (intent/agent), SQLite persistence, decay_all, preferred target ranking, `record_verification()` |
| `src/probos/mesh/gossip.py` | done | `GossipProtocol` — partial view management, entry injection/merge by recency, random sampling, periodic gossip loop |

### Consensus Layer (complete — new in Phase 2)

| File | Status | Description |
|------|--------|-------------|
| `src/probos/consensus/__init__.py` | done | Package root |
| `src/probos/consensus/quorum.py` | done | `QuorumEngine` — configurable thresholds (2-of-3, 3-of-5, etc.), confidence-weighted voting, `evaluate()` and `evaluate_values()`, Shapley value computation on every non-INSUFFICIENT outcome (`ConsensusResult.shapley_values`) (AD-224) |
| `src/probos/consensus/shapley.py` | done | `compute_shapley_values()` — brute-force permutation algorithm for small coalitions (3-7 agents). Marginal contribution: does adding agent *i* change quorum outcome? Supports confidence-weighted and unweighted voting. Normalized to [0, 1] (AD-223) |
| `src/probos/consensus/trust.py` | done | `TrustNetwork` — Bayesian Beta(alpha, beta) reputation scoring, `record_outcome(agent_id, success, weight=1.0)` with weight parameter for Shapley-scaled updates, decay toward prior, SQLite persistence, `create_with_prior()` for probationary agents with custom Beta prior (AD-110, AD-224) |
| `src/probos/consensus/escalation.py` | done | `EscalationManager` — 3-tier cascade: Tier 1 retry with different agent (pool rotation, `surge_fn` for on-demand pool scale-up), Tier 2 LLM arbitration (approve/reject/modify via `ARBITRATION_PROMPT`), Tier 3 user consultation (async callback with `pre_user_hook` for Rich Live conflict). Event-silent design (AD-87): returns `EscalationResult` to caller, executor logs events. Bounded: max_retries cap on Tier 1, one LLM call for Tier 2, one prompt for Tier 3. Re-execution of original intent after user approval (AD-118), original agent results preserved on consensus-policy rejection (AD-119), user rejection marks node as failed (AD-120), `repr(e)` for non-empty exception messages |

### Cognitive Layer (complete — new in Phase 3a)

| File | Status | Description |
|------|--------|-------------|
| `src/probos/federation/__init__.py` | done | Package root, re-exports `MockFederationTransport`, `MockTransportBus`, `FederationRouter`, `FederationBridge` |
| `src/probos/federation/mock_transport.py` | done | `MockTransportBus` — shared in-memory message bus for test federation. `MockFederationTransport` — in-memory transport per node, `send_to_peer()`, `send_to_all_peers()`, `receive_with_timeout()`, `deliver_response()`, inbound handler callback |
| `src/probos/federation/router.py` | done | `FederationRouter` — routing function R: intent → set[peer_node_ids], `update_peer_model()` stores `NodeSelfModel` from gossip, `select_peers()` (Phase 9: returns all peers), `peer_has_capability()` for intent-level filtering |
| `src/probos/federation/bridge.py` | done | `FederationBridge` — connects IntentBus to transport: outbound `forward_intent()` sends to selected peers and collects results with timeout, inbound `handle_inbound()` dispatches by message type (intent_request → local broadcast with federated=False, intent_response → response queue, gossip_self_model → router update, ping → pong), gossip loop broadcasts `NodeSelfModel` at configurable interval, optional `validate_fn` for remote result validation, `federation_status()` for shell/panels |
| `src/probos/federation/transport.py` | done | `FederationTransport` — real ZeroMQ transport using DEALER-ROUTER sockets, JSON serialization, NOT tested in test suite (requires pyzmq). Same interface as `MockFederationTransport` for bridge interchangeability |

### Cognitive Layer (continued)

| File | Status | Description |
|------|--------|-------------|
| `src/probos/cognitive/__init__.py` | done | Package root |
| `src/probos/cognitive/llm_client.py` | done | `BaseLLMClient` ABC, `OpenAICompatibleClient` (per-tier endpoint routing: each tier gets its own base_url/api_key/model/timeout/httpx.AsyncClient, httpx clients deduplicated by base_url — AD-133, per-tier connectivity checks avoiding duplicate probes for shared endpoints — AD-134, response cache keyed by (tier, prompt_hash) — AD-136, `default_tier` read from `CognitiveConfig.default_llm_tier` when config provided — AD-137, `LLMResponse.tier` stores resolved tier not raw `None` — AD-138, backward-compatible legacy kwargs constructor, `tier_info()` for /model display, fallback chain: live → cache → error), `MockLLMClient` (regex pattern matching, canned responses for deterministic testing — supports read_file, write_file, list_directory, search_files, run_command, http_fetch, explain_last, system_health, agent_info, why, introspect_memory, introspect_system, system_anomalies (AD-238), emergent_patterns (AD-238), search_knowledge (AD-244) patterns; escalation arbiter pattern returns reject for deterministic Tier 2 → Tier 3 fallthrough (AD-85); agent_design pattern generates valid CognitiveAgent source code with `instructions` class attribute + `act()` override (AD-111, AD-115, AD-197 Phase 15a); cognitive_agent_decide pattern for CognitiveAgent.decide() LLM calls (AD-197); intent_extraction pattern returns JSON with name/description/parameters, prefers general-purpose intents over narrow ones (AD-124); skill_design pattern generates valid async handler function with IntentResult (AD-128); research_query pattern returns JSON array of search queries; research_synthesis pattern returns reference section string (AD-130)) |
| `src/probos/cognitive/working_memory.py` | done | `WorkingMemorySnapshot` (serializable system state), `WorkingMemoryManager` (bounded context assembly from registry/trust/Hebbian/capabilities, token budget eviction) |
| `src/probos/cognitive/decomposer.py` | done | `IntentDecomposer` (NL text + working memory + similar episodes → LLM → `TaskDAG`, dynamic system prompt via `PromptBuilder` when `_intent_descriptors` populated (falls back to `_LEGACY_SYSTEM_PROMPT`), `refresh_descriptors()` for runtime to push new intent sets, aggressive JSON-only system prompt with `response` and `reflect` fields, markdown code fence extraction, `REFLECT_PROMPT` for post-execution synthesis with `[status]` prefix per node for LLM context (AD-121), rule 6 for structured data extraction from XML/JSON/HTML/CSV results (AD-241), `reflect()` method sends results back to LLM with payload cap ~8000 chars and truncation, `_summarize_node_result()` deduplicates identical output/result fields (AD-122), PAST EXPERIENCE section for episodic context, PRE-WARM HINTS section for dreaming integration, optional `workflow_cache` for cache-first decomposition with exact + fuzzy matching, `pre_warm_intents` property for runtime sync, `is_capability_gap()` function with `_CAPABILITY_GAP_RE` regex to distinguish capability-gap responses from conversational replies (AD-126), `last_tier`/`last_model` debug state tracking — AD-138, decompose/reflect use `tier=None` to respect configured default — AD-137), `DAGExecutor` (parallel/sequential DAG execution through mesh + consensus, dependency resolution, deadlock detection, `on_event` callback for real-time progress, attention-based priority batching when `AttentionManager` is provided, optional `escalation_manager` for 3-tier error recovery, consensus-rejected nodes now correctly marked "failed" instead of "completed", escalation events: escalation_start, escalation_resolved, escalation_exhausted) |
| `src/probos/cognitive/prompt_builder.py` | done | `PromptBuilder` — dynamically assembles decomposer system prompt from `IntentDescriptor` list. Generates intent table, consensus rules, reflect rules (broadened to include transformation/translation intents). Anti-echo rules for `run_command` (no echo/Write-Host/Write-Output to fake answers). Deterministic output (sorted by name). Constants: `PROMPT_PREAMBLE`, `PROMPT_RESPONSE_FORMAT`, `PROMPT_EXAMPLES` (updated with introspection + time examples) |
| `src/probos/cognitive/episodic.py` | done | `EpisodicMemory` — ChromaDB-backed long-term memory with ONNX MiniLM semantic embeddings (Phase 14b), `Episode` storage/recall, semantic similarity search via `collection.query()`, `recall_by_intent()` with metadata filter, `recent()`, `get_stats()`, `seed()` for warm boot, max_episodes eviction |
| `src/probos/cognitive/episodic_mock.py` | done | `MockEpisodicMemory` — in-memory episodic memory for testing, substring/keyword matching recall, no SQLite dependency |
| `src/probos/cognitive/attention.py` | done | `AttentionManager` — priority scorer and budgeter for task execution, scores = urgency × relevance × deadline_factor × dependency_depth_bonus, configurable concurrency limit (`max_concurrent_tasks`), cross-request focus history (ring buffer of `FocusSnapshot` entries, configurable max size), `_compute_relevance()` (keyword overlap between entry intent and recent focus, floor=0.3), background demotion (configurable factor, default 0.25), queue introspection |
| `src/probos/cognitive/dreaming.py` | done | `DreamingEngine` — offline consolidation: replay recent episodes to strengthen/weaken Hebbian weights, prune below-threshold connections, trust consolidation (boost/penalize agents by track record), pre-warm intent prediction via temporal bigram analysis, `idle_scale_down_fn` callback for pool scaler integration. `DreamScheduler` — background asyncio task monitors idle time, triggers dream cycles after configurable threshold, `force_dream()` for immediate cycles, `is_dreaming` property, `last_dream_report` for introspection, `_post_dream_fn` callback for emergent detection analysis (AD-237) |
| `src/probos/cognitive/workflow_cache.py` | done | `WorkflowCache` — in-memory LRU cache of successful DAG patterns, exact and fuzzy lookup (semantic similarity via `compute_similarity()` + pre-warm intent subset — AD-173), deep copy with fresh node IDs on retrieval, popularity-based eviction, stores only fully-successful DAGs |
| `src/probos/cognitive/agent_designer.py` | done | `AgentDesigner` — generates CognitiveAgent subclass source code via LLM for unhandled intents (Phase 15a: instructions-first design — LLM generates `instructions` string + minimal `act()` override instead of full procedural code), template-based prompt construction, class name derivation, allowed_imports whitelist enforcement. AD-228: dual templates (pure LLM reasoning vs web-fetching); `perceive()` override allowed for real-time data fetching via httpx; explicit LLM-cannot-browse guard in prompt. AD-235: `execution_context` parameter — prior execution results passed to LLM so generated agents use known-working values instead of guessing |
| `src/probos/cognitive/cognitive_agent.py` | done | `CognitiveAgent(BaseAgent)` — agent whose `decide()` consults an LLM guided by per-agent `instructions`. Full perceive/decide/act/report lifecycle. `handle_intent()` checks skills first (AD-199), then falls through to cognitive lifecycle. `add_skill()`/`remove_skill()` with instance+class level descriptor sync (same pattern as SkillBasedAgent). `_resolve_tier()` defaults to "standard", overridable. Domain tier by default. `_build_user_message()` injects `fetched_content` from observation into LLM prompt (AD-228). Phase 15a — AD-191, Phase 15b — AD-199 |
| `src/probos/cognitive/code_validator.py` | done | `CodeValidator` — static analysis of generated agent code: syntax check (AST parse), import whitelist enforcement (incl. `probos.cognitive.cognitive_agent`), forbidden pattern regex scan, schema conformance (BaseAgent or CognitiveAgent subclass, intent_descriptors, handle_intent — inherited for CognitiveAgent subclasses, agent_type, _handled_intents), module-level side effect detection |
| `src/probos/cognitive/sandbox.py` | done | `SandboxRunner` — test-executes generated agents in isolated context: temp file write, importlib dynamic loading, BaseAgent/CognitiveAgent subclass discovery, synthetic IntentMessage test, IntentResult type verification, configurable timeout, LLM client forwarding to sandboxed agents |
| `src/probos/cognitive/behavioral_monitor.py` | done | `BehavioralMonitor` — monitors self-created agents for behavioral anomalies: execution time tracking, failure rate alerting (>50% over 5+ executions), slow execution detection (>5s avg), trust trajectory decline detection, removal recommendation (failure rate >50% over 10+ or consecutive trust decline) |
| `src/probos/cognitive/self_mod.py` | done | `SelfModificationPipeline` — orchestrates full self-modification flow: config check (max_designed_agents limit), optional user approval gate, AgentDesigner code generation, CodeValidator static analysis, SandboxRunner functional testing, agent type registration, pool creation, BehavioralMonitor tracking. `DesignedAgentRecord` dataclass for history (with `strategy` field: "new_agent" or "skill"). `handle_add_skill()` — skill design pipeline: SkillDesigner code generation, SkillValidator validation, importlib compilation, Skill object creation, add_skill_fn callback for pool injection (AD-129). Optional `ResearchPhase` integration when research_enabled=True (AD-131) |
| `src/probos/cognitive/strategy.py` | done | `StrategyRecommender` — heuristic-based strategy proposal for unhandled intents: keyword/embedding overlap between intent and existing descriptors, domain-aware cognitive agent scoring via `_find_best_skill_target()` (AD-200, AD-201) — scores cognitive agents' `instructions` against intent description, best match above 0.3 threshold becomes `target_agent_type`, falls back to `skill_agent`. Optional `agent_classes` dict for instructions lookup. `add_skill` strategy with reversibility bonus + domain match weight. `new_agent` fallback. Strategy label shows target agent name when cognitive. `StrategyOption`, `StrategyProposal` |
| `src/probos/cognitive/skill_designer.py` | done | `SkillDesigner` — generates async skill handler functions via LLM, template-based prompt construction with IntentResult/IntentMessage signatures, LLM ACCESS section, research context injection, `_build_function_name()` conversion (AD-128) |
| `src/probos/cognitive/skill_validator.py` | done | `SkillValidator` — static analysis of generated skill code: syntax check, import whitelist, forbidden patterns, schema conformance (async function named handle_{intent_name}), module-level side effect detection (AD-128) |
| `src/probos/cognitive/research.py` | done | `ResearchPhase` — web research before agent/skill design: LLM-generated search queries, domain-whitelisted URL construction via urllib.parse, mesh-based page fetching (uses HttpFetchAgent + consensus), content truncation, LLM synthesis. Security: all fetches go through existing mesh, content truncated before LLM, output is context only (never executed — code still goes through CodeValidator + SandboxRunner) (AD-130, AD-131) |
| `src/probos/cognitive/feedback.py` | done | `FeedbackEngine` — applies human feedback signals to trust, Hebbian routing, and episodic memory. `apply_execution_feedback()` with 2x Hebbian reward (0.10 vs 0.05), one trust `record_outcome()` per agent, feedback-tagged episode storage. `apply_rejection_feedback()` for `/reject` — episode only, no trust/Hebbian updates. `apply_correction_feedback()` — stores correction-tagged episodes with rich metadata (corrected_values, changes_description, retry_success), Hebbian strengthen/weaken on intent→agent route, trust bump on retry success, event log `feedback_correction_applied`/`feedback_correction_failed` (AD-234). `_extract_agent_ids()` handles dict results, IntentResult objects, None. Event log integration: `feedback_positive`, `feedback_negative`, `feedback_plan_rejected`, `feedback_hebbian_update`, `feedback_trust_update` (category: cognitive). `FeedbackResult` dataclass (AD-217, AD-218, AD-221, AD-222, AD-234) |
| `src/probos/cognitive/correction_detector.py` | done | `CorrectionDetector` — LLM-based classifier distinguishing user corrections from new requests. `CorrectionSignal` dataclass (correction_type, target_intent, target_agent_type, corrected_values, explanation, confidence). Conservative threshold (confidence ≥ 0.5). `_format_dag()` handles both TaskDAG objects and dicts from `_last_execution`. Detection prompt includes prior execution context + examples. Returns None when no prior execution, no DAG, low confidence, or LLM failure (AD-229) |
| `src/probos/cognitive/agent_patcher.py` | done | `AgentPatcher` — generates patched source via LLM, validates with same `CodeValidator` + `SandboxRunner` as self-mod. `PatchResult` dataclass (success, patched_source, agent_class, handler, error, original_source, changes_description). `CorrectionResult` dataclass (success, agent_type, strategy, changes_description, retried, retry_result). `_patch_agent()` for new_agent strategy (sandbox test), `_patch_skill()` for skill strategy (importlib compilation). `_clean_source()` strips markdown fences and `<think>` blocks. No new security surface (AD-230) |
| `src/probos/cognitive/emergent_detector.py` | done | `EmergentDetector` — population-level dynamics analyzer for emergent behavior patterns (AD-236). Monitors ALL agents (not just self-created like BehavioralMonitor): Hebbian weight topology → cooperation clusters (union-find connected components), trust score trajectories → z-score anomaly + hyperactive observation detection + change-point detection, routing patterns → new intent/connection detection + Shannon entropy over pool weight distribution, dream consolidation → baseline comparison for anomalous strengthening/pruning/trust adjustments. `EmergentPattern` dataclass (pattern_type, description, confidence, evidence, severity: info/notable/significant). `SystemDynamicsSnapshot` for point-in-time metrics. `compute_tc_n()` — total correlation proxy: fraction of intent types routing to 2+ pools. `compute_routing_entropy()` — Shannon entropy over Hebbian weights by pool. `summary()` JSON-serializable overview. Ring buffer history for trend analysis (AD-236). Phase 21 cleanup (AD-241): `_extract_pool()` rewritten to use `parse_agent_id()` with fallback, `_all_patterns` capped at 500 entries |

### Experience Layer (complete — new in Phase 4)

| File | Status | Description |
|------|--------|-------------|
| `src/probos/experience/__init__.py` | done | Package root |
| `src/probos/experience/panels.py` | done | Rich rendering functions: `render_status_panel()` (with dreaming state section), `render_agent_table()`, `render_weight_table()`, `render_trust_panel()`, `render_gossip_panel()`, `render_event_log_table()`, `render_working_memory_panel()`, `render_attention_panel()` (with focus history display and background task indicator), `render_dag_result()` (displays `response` field for conversational replies), `render_dream_panel()` (dream cycle report with pre-warm intents), `render_workflow_cache_panel()` (cached workflow patterns with hit counts), `render_scaling_panel()` (pool scaling status with demand ratio, size range, cooldown), `render_federation_panel()` (federation node status, connected peers, forwarded/received counts), `render_peers_panel()` (peer self-model table: capabilities, agent count, health, uptime), `render_designed_panel()` (self-designed agent status table with sandbox time, behavioral alerts, optional QA column — AD-153), `render_anomalies_panel()` (AD-239: emergent behavior panel — system dynamics metrics + pattern table with severity coloring), `render_search_panel()` (AD-245: semantic search results — stats section + ranked results table with type-based coloring), `format_health()` — state-coloured agent displays (ACTIVE=green, DEGRADED=yellow, RECYCLING=red, SPAWNING=blue) |
| `src/probos/experience/qa_panel.py` | done | `render_qa_panel()` — Rich table of QA results from in-memory report store (AD-157), shows agent type/verdict/score/duration/trust per designed agent. `render_qa_detail()` — detailed view for single agent with per-test breakdown (case type, result, error). Both functions follow the panels.py pattern: empty-state guard, Rich Table, Rich Panel with border styling |
| `src/probos/experience/knowledge_panel.py` | done | `render_knowledge_panel()` — artifact count table with repo status and schema version. `render_knowledge_history()` — recent commit log with hash/timestamp/message. `render_rollback_result()` — success/failure panel for /rollback command |
| `src/probos/experience/renderer.py` | done | `ExecutionRenderer` — DAG execution display with status spinner (Rich Live removed — AD-92), `on_event` callback integration (including `scale_up`/`scale_down`/`federation_forward`/`federation_receive`/`self_mod_design`/`self_mod_success`/`self_mod_failure` events), conversational response display when LLM returns `response` field, execution snapshot for introspection (`_previous_execution`/`_last_execution`), debug mode (raw DAG JSON, individual agent responses, consensus details, **tier/model in debug panel title** — AD-138), DAG plan display in debug-only mode (AD-90), Params column in progress table, manually-managed spinner with `_stop_live_for_user` hook for Tier 3 escalation (AD-93). Self-mod UX: `StrategyRecommender` integration with numbered strategy menu (AD-127), `add_skill` strategy dispatch when available (AD-129), existing-agent re-routing when LLM extracts already-registered intent, capability-gap detection gates self-mod (AD-126), force `reflect=True` on designed-agent DAGs |
| `src/probos/experience/shell.py` | done | `ProbOSShell` — async REPL with slash commands (`/status`, `/agents`, `/weights`, `/gossip`, `/log`, `/memory`, `/attention`, `/history`, `/recall`, `/dream`, `/cache`, `/scaling`, `/federation`, `/peers`, `/designed`, `/qa`, `/knowledge`, `/rollback`, `/explain`, `/model`, `/tier`, `/debug`, `/plan`, `/approve`, `/reject`, `/feedback`, `/correct`, `/anomalies`, `/search`, `/help`, `/quit`), NL input routing, ambient health prompt `[N agents | health: 0.XX] probos>`, user approval callback for self-mod agent creation (AD-123), `/model` shows per-tier endpoint/model/status with shared-endpoint notes (AD-135), `/tier` switch shows endpoint URL, `/qa` command shows QA status for designed agents with optional agent_type detail view (AD-157), `/designed` passes `qa_reports` for QA column, `/knowledge` shows artifact counts + commit count + repo status, `/knowledge history` shows recent commits, `/rollback <type> <id>` rolls back an artifact to previous version, `/feedback good\|bad` rates last execution — calls `runtime.record_feedback()`, displays agent count and update confirmation (AD-216, AD-220), `/correct <text>` explicit correction command — detects correction signal, patches designed agent, hot-reloads, auto-retries, displays results (AD-233), `/reject` updated to show "Feedback recorded for future planning" (AD-220), `/anomalies` shows emergent behavior panel — system dynamics metrics + detected anomaly patterns (AD-239), graceful error handling |

### Agents

| File | Status | Description |
|------|--------|-------------|
| `src/probos/agents/file_reader.py` | done | `FileReaderAgent` — `read_file` and `stat_file` capabilities, `intent_descriptors` declared, full lifecycle, self-selects on intent match |
| `src/probos/agents/file_writer.py` | done | `FileWriterAgent` — `write_file` capability, `intent_descriptors` with `requires_consensus=True`, proposes writes without committing, `commit_write()` called after consensus approval |
| `src/probos/agents/directory_list.py` | done | `DirectoryListAgent` — `list_directory` capability, `intent_descriptors` declared, lists dir entries with name/type/size, no consensus required |
| `src/probos/agents/file_search.py` | done | `FileSearchAgent` — `search_files` capability, `intent_descriptors` declared, recursive glob via `Path.rglob()`, no consensus required |
| `src/probos/agents/shell_command.py` | done | `ShellCommandAgent` — `run_command` capability, `intent_descriptors` with `requires_consensus=True`, `subprocess.Popen` via `loop.run_in_executor()` (AD-116: SelectorEventLoop compat), 30s timeout, 64KB output cap, `_strip_ps_wrapper()` strips redundant `powershell -Command` wrappers from LLM-generated commands, `_run_sync()` blocking subprocess method. Returns success=True even for nonzero exit codes. Uses PowerShell on Windows, `/bin/sh` elsewhere |
| `src/probos/agents/http_fetch.py` | done | `HttpFetchAgent` — `http_fetch` capability, `intent_descriptors` with `requires_consensus=True`, `httpx.AsyncClient` per-request, 15s timeout, 1MB body cap, header whitelist |
| `src/probos/agents/red_team.py` | done | `RedTeamAgent` — independently verifies other agents' results, `intent_descriptors = []` (does NOT handle user intents), does NOT subscribe to intent bus |
| `src/probos/agents/corrupted.py` | done | `CorruptedFileReaderAgent` — deliberately returns fabricated data, `intent_descriptors = []`, used to test consensus layer catching corruption |
| `src/probos/agents/introspect.py` | done | `IntrospectionAgent` — self-referential queries about ProbOS state, `intent_descriptors` with `requires_reflect=True` for all 8 intents: `explain_last`, `agent_info`, `system_health`, `why`, `introspect_memory`, `introspect_system`, `system_anomalies` (AD-238: reports detected anomalies — trust outliers, routing shifts, consolidation spikes), `emergent_patterns` (AD-238: reports system dynamics — TC_N, routing entropy, cooperation clusters, trends), `search_knowledge` (AD-244: semantic search across all knowledge types — agents, skills, workflows, QA reports, events, episodes). Reads `_runtime` reference, purely observational |
| `src/probos/substrate/skill_agent.py` | done | `SkillBasedAgent` — general-purpose agent dispatching intents to attached Skill objects, `add_skill()` updates both instance AND class-level `_handled_intents` and `intent_descriptors` (AD-128), `remove_skill()` cleans up both levels, `handle_intent()` passes `llm_client` to skill handlers, `skills` pool only spawned when `self_mod.enabled=True` (AD-129) |
| `src/probos/agents/system_qa.py` | done | `SystemQAAgent` — meta-agent that smoke-tests newly designed agents after self-modification (AD-153). `QAReport` dataclass with verdict/pass_rate/test_details/duration. `generate_synthetic_intents()` creates deterministic test cases from intent metadata — happy path (valid params), edge case (minimal/empty), error case (invalid). `_infer_param_type()` heuristic maps key names to param types (url/path/numeric/bool/default — AD-156). `validate_result()` checks outcomes per case type: happy must succeed, edge must not crash, error must fail gracefully or decline. `run_smoke_tests()` executes against pool agents with per-test and total timeout. Event log integration for started/passed/failed lifecycle events |

### Runtime

| File | Status | Description |
|------|--------|-------------|
| `src/probos/runtime.py` | done | `ProbOSRuntime` — orchestrates substrate + mesh + consensus + cognitive + episodic memory + attention + dreaming + workflow cache + introspection + dynamic intent discovery + federation + self-modification + skills + research + SystemQA + DAG proposal mode + semantic knowledge layer. Spawns pools: system (2 heartbeats), filesystem (3 file_readers), filesystem_writers (3 file_writers), directory (3 directory_list), search (3 file_search), shell (3 shell_command), http (3 http_fetch), introspect (2 introspection agents with runtime=self), skills (2 skill_agents with llm_client — only when self_mod.enabled), system_qa (1 SystemQAAgent — only when self_mod.enabled and qa.enabled — AD-153), red_team (2 verifiers). 25-27 agents total. Federation: `FederationBridge` with `FederationRouter`, `_build_self_model()` (NodeSelfModel Psi with capabilities, pool sizes, health, uptime), `_validate_remote_result()` placeholder, wires `bridge.forward_intent` as `intent_bus._federation_fn`. Self-modification: creates `SelfModificationPipeline` with `SkillDesigner`/`SkillValidator`/`add_skill_fn` when `config.self_mod.enabled=True`, optional `ResearchPhase` when `research_enabled=True` (AD-131), `_extract_unhandled_intent()` via LLM (prefers general-purpose intents over narrow ones — AD-124), auto-design when decomposer returns empty DAG or capability-gap response (AD-126), `_register_designed_agent()`, `_create_designed_pool()`, `_set_probationary_trust()`, `_get_llm_equipped_types()` for strategy recommender, `_add_skill_to_agents()` for skill injection into skills pool (AD-129), LLM client injected into designed agent pools (AD-115). SystemQA: `_run_qa_for_designed_agent()` runs non-blocking smoke tests via `asyncio.create_task()` after self-mod success (AD-154), trust updates with weight asymmetry (AD-155), episodic memory storage (AD-157), event log flagging, auto-remove on total failure, `_qa_reports` in-memory dict for `/qa` command (AD-157), `_EXCLUDED_AGENT_TYPES` set excludes `system_qa` and `red_team` from decomposer intent descriptors (AD-158), QA pool excluded from scaler. `register_agent_type()` registers new agent class and refreshes decomposer descriptors. `_collect_intent_descriptors()` deduplicates across all registered templates (including SkillBasedAgent class-level descriptors). Boot-time `refresh_descriptors()` call after pool creation syncs decomposer with all registered intents. `process_natural_language(text, on_event=None)` with event callback support, attention focus update, dream scheduler activity tracking, pre-warm intent sync to decomposer, execution snapshot pattern (`_previous_execution`/`_last_execution` for introspection without self-overwrite), post-execution reflect step, episodic episode storage, workflow cache storage on success, `recall_similar()` for semantic search. `_execute_dag()` extracted as shared execution path for `process_natural_language()` and `execute_proposal()` (AD-205). DAG Proposal Mode (AD-204): `propose()` decomposes NL into TaskDAG without executing, `execute_proposal()` runs pending proposal through `_execute_dag()`, `reject_proposal()` discards, `remove_proposal_node()` edits with dependency cleanup. `_pending_proposal`/`_pending_proposal_text` state. Event logging: `proposal_created`, `proposal_approved`, `proposal_rejected`, `proposal_node_removed` (AD-209). `DreamScheduler` created at start when episodic memory is available. `WorkflowCache` created at init, passed to decomposer, exposed in `status()` |
| `src/probos/__main__.py` | done | Entry point with subcommands: default (interactive shell), `probos init` (creates `~/.probos/` with config wizard — LLM endpoint, model, directory structure), `probos serve` (FastAPI/uvicorn HTTP + WebSocket server with `--host`, `--port`, `--interactive` for concurrent shell + API). `_boot_runtime()` shared boot logic for shell and serve modes. `_load_config_with_fallback()` tries `--config` → `~/.probos/config.yaml` → `config/system.yaml`. Boot sequence: Ollama auto-start, LLM connectivity checks, `EpisodicMemory`, pool creation display, `WindowsSelectorEventLoopPolicy` for Windows (AD-108), `--fresh` flag for cold start (AD-165) |
| `config/node-1.yaml` | done | Node 1 federation config: bind tcp://127.0.0.1:5555, peers=[node-2] |
| `config/node-2.yaml` | done | Node 2 federation config: bind tcp://127.0.0.1:5556, peers=[node-1] |
| `scripts/launch-cluster.sh` | done | Launches 2-node ProbOS federation cluster in background processes |
| `demo.py` | done | Full Rich demo: consensus reads, corrupted agent injection, trust/Hebbian display, NL pipeline with visual feedback, event log |

---


## What's Working

**1520/1520 tests pass.** Test suite covers:

### Substrate tests (50 tests — unchanged)
- Agent creation, lifecycle, confidence tracking (16 tests)
- Config loading (3 tests)
- Registry: register, unregister, lookup (7 tests)
- Spawner: template registration, spawn, recycle (6 tests)
- Pool: target size, cleanup, recovery (4 tests)
- Heartbeat: pulse loop, listeners, confidence (7 tests)
- System heartbeat: metrics, type (2 tests)

### Mesh tests (38 tests — unchanged)
- SignalManager: track, untrack, TTL expiry, reaper loop (6 tests)
- IntentBus: broadcast, multi-subscriber, decline, error recording, unsubscribe (6 tests)
- CapabilityRegistry: exact/substring/keyword matching, scoring, multi-agent, unregister (8 tests)
- HebbianRouter: success/failure weights, clamping, preferred targets, decay pruning, SQLite persistence (8 tests)
- GossipProtocol: local update, receive/merge, batch, remove, active filter, random sample, loop (9 tests)
- EventLog: log/query, count by category, append-only persistence, noop without start (4 tests)
- FileReaderAgent: read, stat, missing file, decline unknown, missing path, confidence updates (8 tests)

### Consensus tests (46 tests — unchanged)
- QuorumEngine: unanimous approval/rejection, insufficient votes, mixed votes, confidence weighting, unweighted mode, 2-of-3, 3-of-5, evaluate_values majority, insufficient values (12 tests)
- TrustNetwork: create, idempotent, success/failure scoring, repeated outcomes, weighted outcome, decay toward prior, remove, all_scores, summary, SQLite persistence, unknown agent prior (14 tests)
- RedTeamAgent: type, capabilities, verify correct/corrupted read, missing file, unknown intent, lifecycle noop (8 tests)
- FileWriterAgent: type, capabilities, propose write, no path, no content, decline unhandled, commit write, commit creates dirs (8 tests)

### Runtime integration tests (32 tests — unchanged)

#### Substrate (5 tests)
- Start/stop, idempotent, heartbeat active, filesystem pool created, pool recovery

#### Mesh (8 tests)
- Intent bus subscribers, capabilities registered, gossip view populated, submit_intent read file, missing file errors, unknown intent empty, Hebbian weights recorded, status includes mesh

#### Event log (3 tests)
- System events on start, lifecycle events for agent wiring, mesh events for intent broadcast/resolve

#### Consensus integration (12 tests)
- Red team agents spawned, trust network initialized, status includes consensus, gossip includes red team
- Submit with consensus: correct read approved, trust updated, agent-to-agent weights recorded, consensus events logged
- Corrupted agent caught, majority corrupted detected, write with consensus committed

### Cognitive tests (105 tests)

#### LLM Client (10 tests)
- MockLLMClient: single read, parallel reads, write with consensus, unmatched default, call count, last request, custom default, token estimate, tier passthrough
- OpenAICompatibleClient: fallback to error when no server + no cache

#### Working Memory (14 tests)
- WorkingMemorySnapshot: empty to_text, with agents, with capabilities, with trust, with connections, token estimate, token scales with content
- WorkingMemoryManager: record intent, record result removes from active, bounded intents, bounded results, assemble without sources, eviction under budget, assemble returns copy

#### Decomposer + TaskDAG (68 tests)
- IntentDecomposer: single read, parallel reads, write with consensus, source text preserved, with context, unrecognized input, malformed JSON, missing intents key, intents not a list, empty intent filtered
- ParseResponse: raw JSON, code block, preamble, invalid JSON, non-dict items skipped
- ExtractJson: raw JSON, code block, embedded JSON, no JSON raises
- TaskDAG: ready nodes all independent, ready nodes with dependency, ready after completion, is_complete, is_not_complete, get_node, empty DAG is complete, response field default empty, response field set
- ResponseFieldParsing: response field extracted, response with intents, response missing defaults empty, non-string response ignored, JSON in code fences with response
- ReflectFieldParsing: reflect field default false, reflect field set true, reflect extracted true, reflect extracted false, reflect missing defaults false, non-bool coerced, reflect method returns text
- ReflectHardening: payload truncated beyond budget, timeout returns empty string, exception fallback sets fallback string in runtime, success unchanged after hardening
- ReflectHardeningExtended: dedup identical output/result in reflect payloads, node status prefix in reflect data, reflect with mixed node statuses (3 tests)
- CapabilityGapDetection: positive detection for "I don't have", "no capability", "cannot help", "I can help with... but", "don't have a translation", "no built-in", "not equipped", "unable to", "outside my capabilities", "don't currently support", "no existing agent", "lack the ability", "I'm not able", "beyond my current", "not something I can", hedged "I can help with X but not Y" (16 positive tests); negative detection for concrete results, conversational replies, error messages, factual responses, short answers, questions, suggestions, empty strings (8 negative tests) — total 24 tests

#### Cognitive integration (8 tests)
- NL single read, parallel reads, write with consensus, unrecognized returns empty, read missing file, working memory updated, status includes cognitive, multiple NL requests

### Experience tests (70 tests)

#### Panels (13 tests)
- render_status_panel: shows ProbOS system info (1 test)
- render_agent_table: shows file_reader and system_heartbeat agents, colour-codes states (2 tests)
- render_weight_table: empty table, table with data showing weights (2 tests)
- render_trust_panel: shows trust scores (1 test)
- render_gossip_panel: shows gossip view (1 test)
- render_event_log_table: shows events after boot (1 test)
- render_working_memory_panel: renders snapshot (1 test)
- render_dag_result: empty result shows "No intents", result with response field displays it (2 tests)
- format_health: green for high values, red for low values (2 tests)

#### Shell Commands (12 tests)
- /status shows ProbOS info (1 test)
- /agents shows file_reader agents (1 test)
- /weights renders weight table (1 test)
- /gossip renders gossip panel (1 test)
- /log and /log with category show events (2 tests)
- /memory shows working memory (1 test)
- /help shows all commands including /model and /tier (1 test)
- /model shows MockLLMClient info (1 test)
- /tier warns about MockLLMClient (1 test)
- Unknown command shows error (1 test)
- Empty input produces no output (1 test)

#### Shell Debug Mode (3 tests)
- /debug on enables debug, /debug off disables, /debug toggles

#### Shell /model and /tier with OpenAICompatibleClient (4 tests)
- /model shows endpoint URL and model mapping (1 test)
- /tier shows current tier (1 test)
- /tier fast switches active tier and confirms model name (1 test)
- /tier with invalid name shows error (1 test)

#### Shell Quit (1 test)
- /quit sets _running to False

#### Shell NL Input (4 tests)
- NL read file processes without stack traces (1 test)
- Unrecognized input shows "No actionable intents" without crashing (1 test)
- Conversational response: LLM `response` field displayed instead of generic message (1 test)
- Error handling — no Traceback in output (1 test)

#### Shell Prompt (2 tests)
- Prompt format includes agents count and health (1 test)
- Health computation returns valid 0.0-1.0 value (1 test)

#### Renderer (5 tests)
- process_with_feedback: single read completes successfully (1 test)
- Empty DAG shows "No actionable intents" (1 test)
- Conversational response: displays LLM `response` field, returns it in result dict (1 test)
- Debug mode shows DEBUG section in output (1 test)
- Parallel reads execute both nodes (1 test)

#### Event Callback (2 tests)
- on_event callback fires decompose_start, decompose_complete, node_start, node_complete (1 test)
- Without on_event, process_natural_language works as before (1 test)

#### Reflect Capability (4 tests)
- render_dag_result with reflection text displays it (1 test)
- render_dag_result without reflection works normally (1 test)
- NL with reflect:true produces reflection key in result (1 test)
- NL without reflect has no reflection key (1 test)

#### Self-Mod / Designed Agent Reflect (1 test)
- Designed agent DAG forces reflect=true and produces reflection (1 test)

#### Episodic Memory Integration (4 tests)
- NL stores episode in memory with correct outcomes (1 test)
- Second request can recall first via recall_similar (1 test)
- Episode includes agent IDs and outcomes (1 test)
- Empty DAG produces no episode (1 test)

#### Episodic Shell Commands (6 tests)
- /history shows episodes after NL processing (1 test)
- /recall with query shows matching results (1 test)
- /status works with episodic memory enabled (1 test)
- /history without memory says not enabled (1 test)
- /recall without memory says not enabled (1 test)
- /help includes /history and /recall (1 test)

#### Attention Integration (3 tests)
- DAG executor respects attention budget (1 test)
- on_event payloads include attention_score (1 test)
- process_natural_language updates focus keywords (1 test)

#### Attention Experience (3 tests)
- /attention command renders panel (1 test)
- render_attention_panel with entries shows scores (1 test)
- render_attention_panel empty shows empty state (1 test)

### Episodic memory tests (16 tests — new in Phase 3b-1)

#### MockEpisodicMemory (7 tests)
- Store and recall single episode (1 test)
- Store multiple, recall returns ranked results (1 test)
- Recall with no matches returns empty (1 test)
- recall_by_intent filters correctly (1 test)
- get_stats returns correct distribution (1 test)
- Max episodes eviction (1 test)
- recent returns most recent first (1 test)

#### EpisodicMemory SQLite (5 tests)
- Store and recall with persistence (1 test)
- recall_by_intent filters correctly (1 test)
- get_stats on empty returns zero (1 test)
- Eviction beyond max_episodes (1 test)
- Episode round-trip (all fields survive store → recall) (1 test)

#### Keyword Embedding (4 tests)
- Embedding non-empty for text (1 test)
- Identical text similarity ≈ 1.0 (1 test)
- Different text similarity < 0.5 (1 test)
- Empty embedding similarity = 0.0 (1 test)

### Attention mechanism tests (12 tests — updated in Phase 3b-3a)
- Submit 3 tasks, get_next_batch returns sorted by score (1 test)
- Budget=3 limits batch to top 3 of 10 (1 test)
- Higher urgency → higher score (1 test)
- Task near TTL expiry gets boosted deadline factor (1 test)
- Higher dependency depth gets bonus (1 test)
- update_focus stores keywords, retrievable via current_focus (1 test)
- is_background flag demotes scores by background demotion factor (1 test)
- mark_completed removes from queue (1 test)
- mark_failed removes from queue (1 test)
- Empty queue returns empty batch (1 test)
- Focus update stores state and affects relevance scoring (1 test)
- Queue snapshot returns all tasks sorted by score (1 test)

### Cross-request attention tests (15 tests — new in Phase 3b-3a)

#### Focus history (3 tests)
- update_focus records snapshots in focus_history (1 test)
- Ring buffer evicts oldest entries when exceeding max size (1 test)
- New AttentionManager has empty focus_history (1 test)

#### Cross-request relevance (3 tests)
- Focus on "read file" boosts read_file intent over http_fetch (1 test)
- Zero keyword overlap still gets relevance floor ≥ 0.3 (1 test)
- Only last 3 focus snapshots affect relevance (1 test)

#### Background demotion (3 tests)
- Background task score is ~0.25x foreground task score (1 test)
- All foreground tasks sort before background tasks in batch (1 test)
- Custom background_demotion_factor is respected (1 test)

#### TaskNode background field (2 tests)
- TaskNode background defaults to False (1 test)
- TaskNode background can be set to True (1 test)

#### Config (2 tests)
- Default config focus_history_size == 10 (1 test)
- Default config background_demotion_factor == 0.25 (1 test)

#### Integration (2 tests)
- DAGExecutor attention_batch propagates background flag, foreground first (1 test)
- End-to-end: focus + relevance + background demotion + budget limiting (1 test)

### Dreaming tests (31 tests — new in Phase 3b-4)

#### DreamingEngine (10 tests)
- dream_cycle strengthens Hebbian weights for successful episodes (1 test)
- dream_cycle weakens Hebbian weights for failed episodes (1 test)
- Mixed success/failure episodes strengthen correct weights and weaken others (1 test)
- Prune removes connections below configured threshold (1 test)
- Trust consolidation boosts agents with multiple successful episodes (1 test)
- Trust consolidation penalizes agents with multiple failed episodes (1 test)
- Pre-warm identifies temporal intent sequences (bigram transitions) (1 test)
- Pre-warm intents stored on engine for decomposer access (1 test)
- Empty episodes produces no-op dream report (1 test)
- Dream report includes non-negative duration_ms (1 test)

#### DreamScheduler (6 tests)
- Triggers dream cycle after idle threshold is reached (1 test)
- Respects minimum interval between dream cycles (1 test)
- is_dreaming flag is False after cycle completes (1 test)
- force_dream() triggers immediate dream cycle (1 test)
- record_activity() prevents dream cycles by resetting idle timer (1 test)
- stop() cancels background monitor task (1 test)

#### Runtime dreaming integration (5 tests)
- Runtime status includes dreaming state (enabled, idle/dreaming) (1 test)
- Without episodic memory, dreaming is disabled in status (1 test)
- _last_request_time updates on NL processing (1 test)
- Dream scheduler activity tracked on NL processing (1 test)
- Status includes last dream report summary after dream cycle (1 test)

#### Shell /dream command (5 tests)
- /dream shows dream report after dream cycle (1 test)
- /dream shows "no cycles yet" before any dreams (1 test)
- /dream now forces an immediate dream cycle (1 test)
- /dream shows disabled message without episodic memory (1 test)
- /help includes /dream command (1 test)

#### Dream panel rendering (4 tests)
- render_dream_panel with report data shows all fields (1 test)
- render_dream_panel with None shows empty state (1 test)
- render_dream_panel with no pre-warm intents (1 test)
- render_status_panel includes dreaming section (1 test)

#### Full integration (1 test)
- NL requests → episodes → dream cycle → weights changed (1 test)

### Workflow cache tests (22 tests — new in Phase 3b-5)

#### WorkflowCache unit tests (12 tests)
- Store and exact lookup returns correct DAG (1 test)
- Lookup miss returns None (1 test)
- Lookup returns deep copy with different node IDs and pending status (1 test)
- Normalize is case insensitive (1 test)
- Normalize strips whitespace (1 test)
- Hit count increments on lookup (1 test)
- Max size evicts lowest hit_count entry (1 test)
- Only stores DAGs where all nodes completed successfully (1 test)
- Fuzzy lookup with pre-warm intent overlap and keyword overlap (1 test)
- Fuzzy lookup returns None when no keyword/intent overlap (1 test)
- Clear empties cache (1 test)
- Entries sorted by hit_count descending (1 test)

#### Decomposer integration (3 tests)
- Cache hit skips LLM (call_count == 0) (1 test)
- Cache miss falls through to LLM (call_count == 1) (1 test)
- Pre-warm intents appear in LLM prompt as PRE-WARM HINTS (1 test)

#### Runtime integration (3 tests)
- Successful NL stores DAG in workflow cache (1 test)
- Status includes workflow_cache key with size/entries (1 test)
- Failed DAG handling — status dict still includes workflow_cache (1 test)

#### Shell/panel tests (4 tests)
- /cache command renders Workflow Cache panel (1 test)
- /help includes /cache command (1 test)
- render_workflow_cache_panel with entries shows hit counts (1 test)
- render_workflow_cache_panel empty shows empty message (1 test)

### Introspection tests (19 tests — new in Phase 6a)

#### IntrospectionAgent unit tests (13 tests)
- Agent creates with runtime reference (1 test)
- Agent creates without runtime (runtime is None) (1 test)
- explain_last returns previous execution info (1 test)
- explain_last with no previous execution returns "No execution history" (1 test)
- explain_last falls back to episodic memory when no previous execution (1 test)
- agent_info returns agents matching type with trust scores (1 test)
- agent_info by specific agent ID (1 test)
- agent_info with unknown type returns empty list (1 test)
- agent_info includes Hebbian weight context (1 test)
- system_health returns structured dict (pool_health, trust_outliers, overall_health, cache_stats, hebbian_density) (1 test)
- why queries episodic memory and includes agent Hebbian/trust context (1 test)
- why without episodic memory returns graceful response (1 test)
- IntrospectionAgent has 'introspect' capability registered (1 test)

#### Decomposer introspection (2 tests)
- SYSTEM_PROMPT contains explain_last, agent_info, system_health, why (1 test)
- Mock LLM returns 'why' intent for a why question (1 test)

#### Runtime introspection integration (3 tests)
- Runtime creates introspect pool with 2 agents (1 test)
- Introspect agents have _runtime reference set (1 test)
- _previous_execution tracks correctly after two sequential NL requests (1 test)

#### Shell /explain command (1 test)
- /explain is in COMMANDS and dispatches without error (1 test)

### Dynamic Intent Discovery tests (21 tests — new in Phase 6b)

#### PromptBuilder unit tests (10 tests)
- Build prompt contains all 11 current intents (1 test)
- Consensus rules generated for write_file, run_command, http_fetch (1 test)
- Reflect rules generated for introspection intents (1 test)
- Empty descriptors produces valid prompt with no intent table entries (1 test)
- Custom descriptor appears in generated prompt (1 test)
- Prompt contains JSON-only instruction (1 test)
- Descriptors sorted alphabetically in output (1 test)
- Duplicate intent names deduplicated in intent table (1 test)
- Prompt contains static examples section (1 test)
- Prompt contains response format schema (1 test)

#### IntentDescriptor on agents (3 tests)
- All user-facing agents have non-empty intent_descriptors (1 test)
- Non-intent agents (RedTeam, Corrupted, Heartbeat) have empty descriptors (1 test)
- Descriptor names match _handled_intents for each agent (1 test)

#### Decomposer integration (3 tests)
- Decomposer with refresh_descriptors uses dynamic prompt successfully (1 test)
- Decomposer without refresh_descriptors falls back to legacy prompt (1 test)
- refresh_descriptors with custom descriptor adds intent to system prompt (1 test)

#### Runtime integration (5 tests)
- Runtime collects descriptors at boot (read_file, write_file, run_command present) (1 test)
- _collect_intent_descriptors returns deduplicated names (1 test)
- register_agent_type refreshes decomposer descriptors (1 test)
- Existing NL processing unchanged with dynamic discovery (1 test)
- End-to-end: register custom agent, verify decomposer prompt includes it (1 test)

### Expansion agent tests (33 tests — new in Phase 5)

#### DirectoryListAgent (7 tests)
- Agent type and capabilities (1 test)
- List populated directory with files and subdirs (1 test)
- List nonexistent directory (1 test)
- List empty directory (1 test)
- List path that is a file, not a directory (1 test)
- Missing path param (1 test)
- Declines unhandled intent (1 test)

#### FileSearchAgent (5 tests)
- Agent type and capabilities (1 test)
- Search matching glob with recursive results (1 test)
- Search with no matches (1 test)
- Search nonexistent base dir (1 test)
- Missing params (1 test)

#### ShellCommandAgent (4 tests)
- Agent type and capabilities (1 test)
- echo hello succeeds with exit_code=0 (1 test)
- Failing command (exit 42) returns success=True with nonzero exit_code (1 test)
- Empty command (1 test)

#### HttpFetchAgent (4 tests)
- Agent type and capabilities (1 test)
- Fetch with mocked httpx returns 200 and body (1 test)
- Fetch with mocked connection error (1 test)
- Missing URL (1 test)

#### Expansion integration (7 tests)
- All 4 new pools created at boot (1 test)
- NL "what files are in <path>" → list_directory (1 test)
- NL "find files named *.txt in <path>" → search_files (1 test)
- NL "run the command echo hello" → run_command with consensus (1 test)
- NL "fetch https://..." → http_fetch with consensus via mocked httpx (1 test)
- Direct submit_intent for list_directory returns 3 results (1 test)
- Direct submit_intent_with_consensus for run_command returns consensus (1 test)

#### Expansion error cases (3 tests)
- Nonexistent directory via runtime list_directory (1 test)
- Nonexistent directory via runtime search_files (1 test)
- Failing command (exit 42) via runtime — success=True with nonzero exit code (1 test)

### Scaling tests (34 tests — new in Phase 8)

- ScalingConfig defaults, custom values, SystemConfig integration (3 tests)
- IntentBus demand metrics: zeros, counting, pruning, per-pool demand (4 tests)
- Pool bounds: add at max, add below max, remove at min, remove above min (4 tests)
- Trust-aware scale-down: lowest trust removed, equal trust, no trust fallback (3 tests)
- PoolScaler scale-up: high demand, blocked by max, blocked by cooldown (3 tests)
- PoolScaler scale-down: low demand, blocked by min, blocked by cooldown (3 tests)
- PoolScaler surge: adds agent, false at max, bypasses cooldown (3 tests)
- PoolScaler idle scale-down: reduces pools, skips excluded (2 tests)
- PoolScaler exclusions: excluded not scaled, pinned not scaled (2 tests)
- Runtime: scaler when enabled, no scaler when disabled, status includes scaling (3 tests)
- Escalation surge: surge_fn called during tier1, works without surge_fn (2 tests)
- Shell: scaling command renders panel, help includes /scaling (2 tests)

### Federation tests (42 tests — new in Phase 9)

- FederationConfig: defaults, custom values, peer config roundtrip, SystemConfig inclusion (4 tests)
- Federation types: NodeSelfModel roundtrip, FederationMessage roundtrip, carries intent data (3 tests)
- MockTransportBus: send/receive, unregistered peer, send_to_all_peers, timeout returns None (4 tests)
- FederationRouter: select_peers returns all, update_peer_model, peer_has_capability true/false (4 tests)
- Bridge outbound: forward_collects_results, partial results from unresponsive, all unresponsive, increments stats, validate_fn (5 tests)
- Bridge inbound: broadcasts locally, federated=False, gossip updates router, ping/pong (4 tests)
- Loop prevention: inbound does not reforward, two-node ring no infinite loop (2 tests)
- IntentBus federation: broadcast calls federation_fn, federated=False skips, no fn unchanged (3 tests)
- Gossip: sends self-model, receiving updates router (2 tests)
- Runtime: creates bridge when enabled, no bridge when disabled, build_self_model, status includes federation (4 tests)
- Shell: /federation disabled, /peers disabled, /help includes both, panel rendering (7 tests)

## Milestones



- [x] ~~Build substrate layer (agent, registry, spawner, pool, heartbeat)~~
- [x] ~~Build mesh layer (intent bus, capability registry, gossip, Hebbian routing, signal decay)~~
- [x] ~~Build FileReaderAgent and wire into mesh~~
- [x] ~~Add append-only event log~~
- [x] ~~Achieve Phase 1 milestone (3 agents read same file independently)~~
- [x] ~~108/108 tests pass~~
- [x] ~~Build consensus layer (quorum engine, trust network, red team agents)~~
- [x] ~~Build FileWriterAgent gated by quorum~~
- [x] ~~Evolve HebbianRouter to agent-to-agent weights~~
- [x] ~~Inject corrupted agent, demonstrate detection~~
- [x] ~~166/166 tests pass~~
- [x] ~~Build Phase 3a cognitive core (LLM client, working memory, decomposer, DAG executor)~~
- [x] ~~Wire `process_natural_language()` into runtime~~
- [x] ~~224/224 tests pass~~
- [x] ~~Build Phase 4 experience layer (panels, renderer, shell, entry point)~~
- [x] ~~Update demo.py with Rich display~~
- [x] ~~261/261 tests pass~~
- [x] ~~Wire live LLM endpoint (VS Code Copilot proxy) with fallback~~
- [x] ~~Add /model and /tier commands~~
- [x] ~~Rewrite system prompt for real LLM decomposition~~
- [x] ~~267/267 tests pass~~
- [x] ~~Harden system prompt for JSON-only output, add response field for conversational replies~~
- [x] ~~277/277 tests pass~~
- [x] ~~Spawn FileWriterAgent pool so write intents reach consensus quorum~~
- [x] ~~Build Phase 5 expansion agents (DirectoryListAgent, FileSearchAgent, ShellCommandAgent, HttpFetchAgent)~~
- [x] ~~Extend red team verification for run_command and http_fetch~~
- [x] ~~310/310 tests pass~~
- [x] ~~Add reflect capability — post-execution LLM synthesis~~
- [x] ~~325/325 tests pass~~
- [x] ~~Harden reflect step — timeout, payload cap, graceful fallback~~
- [x] ~~325/325 tests pass~~
- [x] ~~Phase 3b-1: Episodic memory (Episode type, EpisodicMemory with SQLite, MockEpisodicMemory, runtime wiring, decomposer context, /history + /recall commands)~~
- [x] ~~351/351 tests pass~~
- [x] ~~Phase 3b-2: Attention mechanism (AttentionEntry type, AttentionManager, DAGExecutor priority batching, /attention command, focus tracking infrastructure)~~
- [x] ~~369/369 tests pass~~
- [x] ~~Phase 3b-3a: Cross-request attention & background demotion (FocusSnapshot type, focus history ring buffer, _compute_relevance with keyword overlap, background demotion factor, TaskNode.background field, config wiring, panels focus history display)~~
- [x] ~~384/384 tests pass~~
- [x] ~~Phase 3b-4: Dreaming engine (DreamReport type, DreamingConfig, DreamingEngine — replay/prune/trust consolidation/pre-warm, DreamScheduler — idle monitoring/forced dream, runtime wiring, /dream command, render_dream_panel, render_status_panel dreaming section)~~
- [x] ~~415/415 tests pass~~
- [x] ~~Phase 3b-5: Habit formation & workflow cache (WorkflowCacheEntry type, WorkflowCache — exact/fuzzy lookup/LRU eviction/deep copy, decomposer cache-first decomposition, pre-warm hints in LLM prompt, runtime cache storage & pre-warm sync, /cache command, render_workflow_cache_panel)~~
- [x] ~~437/437 tests pass~~
- [x] ~~Phase 6a: Introspection & self-awareness (IntrospectionAgent — explain_last/agent_info/system_health/why, BaseAgent **kwargs + _runtime, AgentSpawner/ResourcePool kwargs forwarding, execution snapshot pattern _previous_execution/_last_execution, MockLLMClient introspection patterns, decomposer system prompt introspection intents, /explain command, renderer execution snapshot wiring)~~
- [x] ~~456/456 tests pass~~
- [x] ~~Phase 6b: Dynamic intent discovery (IntentDescriptor type, intent_descriptors class var on BaseAgent and all agents, PromptBuilder dynamic prompt assembly, IntentDecomposer refresh_descriptors + dynamic/legacy fallback, runtime _collect_intent_descriptors + register_agent_type refresh, boot-time descriptor sync)~~
- [x] ~~477/477 tests pass~~
- [x] ~~Phase 7: Escalation Cascades & Error Recovery (EscalationTier enum, EscalationResult with to_dict() + tiers_attempted, EscalationManager 3-tier cascade: retry/arbitration/user, ARBITRATION_PROMPT, MockLLMClient arbitration pattern, DAGExecutor consensus-rejection bug fix + escalation wiring + event logging, runtime EscalationManager creation + status(), renderer escalation event handling + escalating status, shell user consultation callback with Rich Live conflict resolution, panels _format_escalation helper + render_dag_result escalation display)~~
- [x] ~~506/506 tests pass~~
- [x] ~~UX fixes: pre_user_hook wiring (AD-89), DAG plan to debug-only (AD-90), Tier 3 prompt enrichment (AD-91), Rich Live → spinner (AD-92), manually managed spinner for escalation (AD-93)~~
- [x] ~~506/506 tests pass (after UX fixes)~~
- [x] ~~Phase 8: Adaptive Pool Sizing & Dynamic Scaling (ScalingConfig, IntentBus demand tracking, ResourcePool add_agent/remove_agent with trust-aware selection, PoolScaler background loop with demand ratio evaluation, escalation surge_fn, dreaming idle_scale_down_fn, /scaling command, render_scaling_panel)~~
- [x] ~~540/540 tests pass~~
- [x] ~~Phase 9: Multi-Node Federation (FederationConfig + PeerConfig, NodeSelfModel + FederationMessage types, MockTransportBus + MockFederationTransport for testing, FederationRouter peer selection, FederationBridge outbound/inbound/gossip, loop prevention via federated=False, IntentBus _federation_fn callback, runtime wiring + _build_self_model, FederationTransport ZeroMQ, node configs + --config flag, /federation + /peers commands, render_federation_panel + render_peers_panel, launch-cluster.sh)~~
- [x] ~~582/582 tests pass~~
- [x] ~~Windows ZMQ fix: WindowsSelectorEventLoopPolicy for pyzmq compatibility (AD-108)~~
- [x] ~~582/582 tests pass (after Windows fix)~~
