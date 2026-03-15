# ProbOS — Progress Tracker

## Current Status: Phase 23 — HXI MVP "See Your AI Thinking" (1575/1575 tests + 11 skipped)

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

### Bundled Agents (new in Phase 22)

| File | Status | Description |
|------|--------|-------------|
| `src/probos/agents/bundled/__init__.py` | done | Package root, re-exports all 10 bundled agent classes |
| `src/probos/agents/bundled/web_agents.py` | done | `WebSearchAgent` (DuckDuckGo via mesh `http_fetch`), `PageReaderAgent` (URL → summarize, HTML tag stripping), `WeatherAgent` (wttr.in JSON via mesh), `NewsAgent` (RSS XML parsing with `xml.etree.ElementTree`, `_parse_rss()` static method, default RSS feeds dict). `_BundledMixin` self-deselect guard for unrecognized intents. `_mesh_fetch()` helper dispatches `http_fetch` through intent bus (AD-248) |
| `src/probos/agents/bundled/language_agents.py` | done | `TranslateAgent` (pure LLM translation), `SummarizerAgent` (pure LLM summarization). No `perceive()` override — entirely LLM-driven via `instructions`. `_BundledMixin` self-deselect guard (AD-249) |
| `src/probos/agents/bundled/productivity_agents.py` | done | `CalculatorAgent` (safe eval for simple arithmetic via `_SAFE_EXPR_RE`, LLM fallback for complex expressions), `TodoAgent` (file-backed via mesh `read_file`/`write_file`, `~/.probos/todos.json`). `_BundledMixin` self-deselect guard. Mesh I/O helpers: `_mesh_read_file()`, `_mesh_write_file()` (AD-250) |
| `src/probos/agents/bundled/organizer_agents.py` | done | `NoteTakerAgent` (file-backed notes in `~/.probos/notes/`, semantic search via `_semantic_layer`), `SchedulerAgent` (file-backed reminders in `~/.probos/reminders.json`, no background timer). `_BundledMixin` self-deselect guard. Mesh I/O helpers: `_mesh_read_file()`, `_mesh_write_file()`, `_mesh_list_dir()` (AD-251) |

### Distribution (new in Phase 22)

| File | Status | Description |
|------|--------|-------------|
| `src/probos/api.py` | done | FastAPI app with REST + WebSocket endpoints. `create_app(runtime)` returns wired FastAPI instance. `GET /api/health` (status, agent count, avg health), `GET /api/status` (full runtime status), `POST /api/chat` (NL message → DAG execution → response), `WebSocket /ws/events` (event stream with 30s keepalive ping). `_broadcast_event()` fire-and-forget to connected WebSocket clients (AD-247) |

### Knowledge Layer (new in Phase 14)

| File | Status | Description |
|------|--------|-------------|
| `src/probos/knowledge/__init__.py` | done | Package root with KnowledgeStore re-export |
| `src/probos/knowledge/store.py` | done | `KnowledgeStore` — Git-backed persistent repository for all ProbOS artifacts. `initialize()` creates repo directory + all subdirectories (episodes, agents, skills, trust, routing, workflows, qa). Store/load methods for 7 artifact types: episodes (JSON per file, oldest-first eviction), agents (.py source + .json metadata sidecar), skills (.py + .json descriptor), trust (single snapshot.json with raw alpha/beta — AD-168), routing (single weights.json), workflows (single cache.json with max_workflows eviction), QA reports (per-agent JSON). Git integration: `_ensure_repo()` for late Git init on first write with meta.json (AD-159, AD-169), `_schedule_commit()` debounced via `asyncio.TimerHandle` (AD-161), `_git_commit()` via thread executor (AD-166), `flush()` with `_flushing` race guard. `rollback_artifact()` restores previous version via `git log --follow` + `git show` (AD-164). `artifact_history()` per-file commit log. `recent_commits()`, `commit_count()`, `meta_info()`, `artifact_counts()`. All file I/O via `_write_json()` / `_read_json()` using asyncio executor |
| `src/probos/knowledge/semantic.py` | done | `SemanticKnowledgeLayer` — unified semantic search across all ProbOS knowledge types (AD-242). Manages 5 ChromaDB collections (`sk_agents`, `sk_skills`, `sk_workflows`, `sk_qa_reports`, `sk_events`) for non-episode knowledge. Episodes queried via existing `EpisodicMemory` — no duplicate collection. Indexing methods: `index_agent()`, `index_skill()`, `index_workflow()`, `index_qa_report()`, `index_event()` — all `upsert()` with deterministic IDs and typed metadata. `search()` fans out across collections + episodic memory, merges by cosine similarity score, sorts descending. `stats()` per-collection document counts. `reindex_from_store()` bulk re-index from `KnowledgeStore` for warm boot. `source_node` metadata on all entries for future federation |

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

### Self-modification tests (44 tests — new in Phase 10)

#### CodeValidator (9 tests)
- Valid agent code passes (1 test)
- Syntax error rejected (1 test)
- Forbidden import rejected (1 test)
- Forbidden pattern (eval/exec) rejected (1 test)
- Missing BaseAgent subclass rejected (1 test)
- Missing intent_descriptors rejected (1 test)
- Missing handle_intent rejected (1 test)
- Module-level side effects rejected (1 test)
- Allowed imports pass (1 test)

#### AgentDesigner (5 tests)
- Design returns valid source code (1 test)
- Generated code passes CodeValidator (1 test)
- Design prompt contains intent name and description (1 test)
- Design prompt includes IntentResult/IntentMessage signatures (1 test)
- Design prompt includes BaseAgent lifecycle methods (1 test)

#### SandboxRunner (4 tests)
- Valid agent loads and returns IntentResult (1 test)
- Syntax error agent fails sandbox (1 test)
- Non-BaseAgent subclass fails (1 test)
- Timeout kills runaway agent (1 test)

#### SelfModificationPipeline (7 tests)
- Full pipeline: design → validate → sandbox → register (1 test)
- Validation failure aborts pipeline (1 test)
- Sandbox failure aborts pipeline (1 test)
- Max designed agents limit enforced (1 test)
- Config disabled returns early (1 test)
- Pipeline events emitted (design, success/failure) (2 tests)

#### BehavioralMonitor (5 tests)
- Record execution updates metrics (1 test)
- High failure rate triggers alert (1 test)
- Low failure rate no alert (1 test)
- Trust decline detection (1 test)
- should_recommend_removal with insufficient data (1 test)

#### Runtime self-mod integration (8 tests)
- Runtime creates pipeline when enabled (1 test)
- Runtime skips pipeline when disabled (1 test)
- Empty DAG triggers self-mod design (1 test)
- Successful design registers new agent type (1 test)
- Designed agent pool created with correct size (1 test)
- Probationary trust set on designed agents (1 test)
- /designed command shows designed agents (1 test)
- re-decomposition after design uses new agent (1 test)

#### Escalation post-Phase-10 hardening (6 tests)
- Re-execute intent after user approval (1 test)
- User rejection marks node failed (1 test)
- Original agent results preserved on consensus-policy rejection (1 test)
- Escalation re-execution with pool rotation (1 test)
- Re-execution logging includes intent details (1 test)
- Empty error message replaced with "(empty)" (1 test)

### Phase 4 Milestone — Achieved

### Phase 11 tests (59 tests — new in Phase 11)

#### Strategy Recommender (12 tests)
- Always returns at least one option (new_agent fallback) (1 test)
- Zero overlap → new_agent highest confidence (1 test)
- Keyword overlap with LLM-equipped → add_skill recommended (1 test)
- add_skill confidence > new_agent when both viable (reversibility) (1 test)
- Options sorted by confidence descending (1 test)
- recommended property returns is_recommended option (1 test)
- recommended property returns None when no options (1 test)
- Keyword overlap tokenization (AD-55 pattern) (1 test)
- StrategyOption fields roundtrip (1 test)
- StrategyProposal with empty options (1 test)
- LLM-equipped types filters add_skill (1 test)
- Safety budget risk confidence — reversible scores higher (1 test)

#### SkillBasedAgent (10 tests)
- Agent creates with empty skills (1 test)
- add_skill registers intent on instance (1 test)
- add_skill updates class-level descriptors (1 test)
- remove_skill clears intent from both levels (1 test)
- handle_intent dispatches to correct skill (1 test)
- handle_intent returns None for unknown (1 test)
- handle_intent passes llm_client (1 test)
- Multiple skills dispatch independently (1 test)
- agent_type is "skill_agent" (1 test)
- Skill with LLM handler (1 test)

#### SkillDesigner (3 tests)
- design_skill returns valid function source (1 test)
- Generated code passes SkillValidator (1 test)
- _build_function_name conversion (1 test)

#### SkillValidator (6 tests)
- Valid skill code passes (1 test)
- Missing async function rejected (1 test)
- Wrong function name rejected (1 test)
- Forbidden import rejected (1 test)
- Forbidden pattern rejected (1 test)
- Module-level side effects rejected (1 test)

#### Skill Pipeline Integration (7 tests)
- handle_add_skill full flow — design → validate → compile → attach (1 test)
- handle_add_skill validation failure aborts (1 test)
- DesignedAgentRecord.strategy field (1 test)
- Runtime _add_skill_to_agents updates pool members (1 test)
- Descriptor refresh after skill addition includes new intent (1 test)
- Skills pool spawned when self_mod.enabled=True (1 test)
- Skills pool NOT spawned when self_mod.enabled=False (1 test)

#### ResearchPhase (17 tests)
- Research returns synthesis on success (1 test)
- Research returns fallback on network failure (1 test)
- Research returns fallback on empty content (1 test)
- _generate_queries returns list (1 test)
- _generate_queries handles malformed response (1 test)
- _queries_to_urls uses urllib.parse (1 test)
- _queries_to_urls filters non-whitelisted domains (1 test)
- _queries_to_urls returns empty for empty queries (1 test)
- _queries_to_urls caps at max_pages (1 test)
- _fetch_pages truncates content (1 test)
- _fetch_pages handles failed fetches (1 test)
- _synthesize passes content to LLM (1 test)
- _synthesize handles no useful docs (1 test)
- Full research flow (1 test)
- Research context injected into design prompt (1 test)
- Pipeline research_enabled=False skips research (1 test)
- Pipeline research_enabled=True includes context (1 test)

#### Research Security (4 tests)
- URLs use urllib.parse.urlencode (1 test)
- Non-whitelisted domain URLs filtered (1 test)
- Content truncation enforced (1 test)
- Fetch goes through consensus submit_intent (1 test)

### Phase 12 tests (17 tests — new in Phase 12)

#### CognitiveConfig Tiers (5 tests)
- Default config falls back to shared values (1 test)
- Per-tier URL overrides shared (1 test)
- Per-tier API key overrides shared (1 test)
- Mixed overrides: fast overridden, standard/deep fall back (1 test)
- tier_config() returns correct model per tier (1 test)

#### OpenAICompatibleClient Multi-Endpoint (7 tests)
- Separate httpx clients for different base_urls (1 test)
- Deduplicates httpx clients for shared base_urls (1 test)
- complete() routes fast-tier to fast endpoint (1 test)
- complete() routes standard-tier to standard endpoint (1 test)
- tier_info() returns per-tier config (1 test)
- Backward-compat legacy keyword args (1 test)
- models property reflects tier_configs (1 test)

#### Connectivity Check (3 tests)
- check_connectivity() returns per-tier status dict (1 test)
- Shared endpoint checked once, result reused (1 test)
- Individual tier failure doesn't block others (1 test)

#### Boot Sequence (2 tests)
- All tiers unreachable falls back to MockLLMClient (1 test)
- Partial connectivity tracked in tier_status (1 test)

### SystemQA tests (72 tests — new in Phase 13)

#### QAConfig (4 tests)
- Default config values match spec (1 test)
- QAConfig in SystemConfig as qa field (1 test)
- QAConfig from YAML with custom values (1 test)
- Missing qa: section falls back to defaults (1 test)

#### Synthetic Intent Generation (11 tests)
- Happy path intents have valid params (1 test)
- Edge case intents have minimal/empty params (1 test)
- Error case intents have invalid params (1 test)
- Count parametrize [3, 5, 7] — total matches (3 tests)
- Param type inference: url key → URL values (1 test)
- Param type inference: path key → path values (1 test)
- Param type inference: numeric key → int values (1 test)
- Param type inference: bool key → bool values (1 test)
- Param type inference: unknown key → string defaults (1 test)

#### Validate Result (7 tests)
- Happy path success passes (1 test)
- Error case graceful failure passes (1 test)
- Unhandled crash fails (1 test)
- None on error case counts as pass (declined) (1 test)
- None on happy path counts as fail (1 test)
- Edge case success passes (1 test)
- Edge case failure passes (no crash = pass) (1 test)

#### QAReport Structure (4 tests)
- All required fields and correct types (1 test)
- Pass rate calculation 3/5 → 0.6, verdict "passed" (1 test)
- Fail rate calculation 2/5 → 0.4, verdict "failed" (1 test)
- Boundary: exactly 0.6 → "passed", below → "failed" (1 test)

#### Smoke Test Integration (6 tests)
- Passing agent → verdict "passed", all tests pass (1 test)
- Failing agent → verdict "failed", agent crashes (1 test)
- Flaky agent → mixed results (1 test)
- Declining agent → only error case passes (1 test)
- Per-test timeout triggers on slow agent (1 test)
- Total timeout skips remaining tests (1 test)

#### Trust Integration (3 tests)
- Trust scores increase after passing QA (1 test)
- Trust scores decrease after failing QA (1 test)
- Penalty weight (2.0) > reward weight (1.0) asymmetry (1 test)

#### Episodic Memory Integration (2 tests)
- Episode stored with [SystemQA] prefix after QA (1 test)
- Episode has correct dag_summary, outcomes, reflection, agent_ids (1 test)

#### Event Log Integration (5 tests)
- smoke_test_started event emitted (1 test)
- smoke_test_passed event emitted on success (1 test)
- smoke_test_failed event emitted on failure (1 test)
- agent_flagged event when flag_on_fail=True (1 test)
- No agent_flagged when flag_on_fail=False (1 test)

#### Auto-Remove (3 tests)
- Pool emptied when 0/N pass and auto_remove=True (1 test)
- Pool NOT emptied on partial failure (1 test)
- Pool NOT emptied when auto_remove=False (1 test)

#### QA Report Store (2 tests)
- Report stored in runtime._qa_reports[agent_type] (1 test)
- Report overwritten on rerun of same agent type (1 test)

#### QA Disabled (2 tests)
- QA disabled skips execution, returns None (1 test)
- No system_qa agent when self-mod disabled (1 test)

#### Error Containment (4 tests)
- Exception in run_smoke_tests → qa_error event logged (1 test)
- Exception does not propagate to caller (1 test)
- Empty pool → graceful None/error, no crash (1 test)
- Missing pool → graceful None, no crash (1 test)

#### Routing Exclusion (5 tests)
- smoke_test_agent not in _collect_intent_descriptors (1 test)
- smoke_test_agent not in decomposer prompt after boot (1 test)
- system_qa pool in scaler excluded_pools (1 test)
- system_qa pool created at boot when self_mod+qa enabled (1 test)
- system_qa pool NOT created when qa disabled (1 test)

#### Regression Invariants (4 tests)
- runtime.status() includes qa key with enabled and report_count (1 test)
- runtime.status() works when QA disabled (1 test)
- Self-mod pipeline unchanged (1 test)
- Existing shell commands unchanged (1 test)

#### QA Panel Rendering (3 tests)
- render_qa_panel with reports shows Rich table (1 test)
- render_qa_panel empty shows "No QA results" (1 test)
- render_qa_panel mixed verdicts shows PASSED and FAILED (1 test)

#### QA Shell Command (4 tests)
- /qa registered in COMMANDS (1 test)
- /qa command renders panel (1 test)
- /qa agent_type shows detail view (1 test)
- /help includes /qa (1 test)

#### Designed Panel QA Column (3 tests)
- render_designed_panel with qa_reports shows QA column (1 test)
- render_designed_panel with qa_reports=None — backward compat (1 test)
- Agent not in QA reports shows em-dash (1 test)

### Phase 14 Knowledge Store tests (91 tests — new in Phase 14)

#### KnowledgeConfig (4 tests)
- Default values match spec (1 test)
- KnowledgeConfig in SystemConfig (1 test)
- Custom values from YAML (1 test)
- Missing section falls back to defaults (1 test)

#### EpisodicMemory.seed() (6 tests)
- seed() restores episodes (1 test)
- Preserves original IDs (1 test)
- Preserves timestamps (1 test)
- Skips duplicate IDs (1 test)
- Empty list returns 0 (1 test)
- MockEpisodicMemory seed works (1 test)

#### WorkflowCache.export_all() (3 tests)
- Returns all entries (1 test)
- Empty cache returns empty list (1 test)
- Entries are JSON-serializable (1 test)

#### TrustNetwork.raw_scores() (2 tests)
- Returns alpha/beta parameters (1 test)
- Raw params not derived mean (1 test)

#### KnowledgeStore Init (4 tests)
- Creates directory (1 test)
- Creates all subdirectories (1 test)
- Idempotent initialization (1 test)
- repo_exists false before write (1 test)

#### Episode storage (7 tests)
- store_episode creates file (1 test)
- Stored episode is valid JSON (1 test)
- load_episodes returns stored (1 test)
- Episodes sorted by timestamp desc (1 test)
- load_episodes with limit (1 test)
- Empty directory returns empty list (1 test)
- Max episodes eviction (1 test)

#### Agent storage (7 tests)
- store_agent creates .py and .json (1 test)
- Source code matches (1 test)
- Metadata matches (1 test)
- load_agents returns stored (1 test)
- Empty directory returns empty list (1 test)
- remove_agent deletes files (1 test)
- remove_agent nonexistent is no-op (1 test)

#### Skill storage (2 tests)
- store_skill creates files (1 test)
- load_skills returns stored (1 test)

#### Trust storage (4 tests)
- store_trust_snapshot (1 test)
- load_trust_snapshot (1 test)
- load_trust_snapshot missing returns empty (1 test)
- Contains raw alpha/beta params (1 test)

#### Routing storage (2 tests)
- store_routing_weights (1 test)
- load_routing_weights (1 test)

#### Workflow storage (3 tests)
- store_workflows (1 test)
- load_workflows (1 test)
- Max workflows eviction (1 test)

#### QA storage (2 tests)
- store_qa_report (1 test)
- load_qa_reports (1 test)

#### Git integration (11 tests)
- Git init on first write (1 test)
- meta.json with schema_version/probos_version (1 test)
- repo_exists true after write (1 test)
- flush commits immediately (1 test)
- Commit messages include artifact info (1 test)
- Flush prevents debounce race (1 test)
- Thread executor doesn't block event loop (1 test)
- Uses get_running_loop (1 test)
- Git not available graceful fallback (1 test)
- Auto-commit after debounce (1 test)
- Debounce batches writes (1 test)

#### Rollback (5 tests)
- Rollback restores previous version (1 test)
- Rollback creates new commit (1 test)
- No history returns False (1 test)
- artifact_history returns commits (1 test)
- artifact_history empty returns empty list (1 test)

#### Warm boot (11 tests)
- Restores trust with correct alpha/beta (1 test)
- Restores routing weights (1 test)
- Restores episodes via seed() (1 test)
- Restores workflows (1 test)
- Restores QA reports (1 test)
- Trust before agents order (1 test)
- Partial failure skips corrupted, restores rest (1 test)
- Empty repo cold-starts normally (1 test)
- --fresh skips restore (1 test)
- --fresh preserves repo (1 test)
- Skips invalid agent with validation failure (1 test)

#### Runtime integration (8 tests)
- Episode persisted after processing (1 test)
- Persistence failure doesn't crash (1 test)
- Shutdown flushes knowledge (1 test)
- Shutdown persists workflows (1 test)
- Shutdown persists trust (1 test)
- Shutdown persists routing (1 test)
- Knowledge disabled skips persistence (1 test)
- Knowledge status in runtime (1 test)

#### Knowledge panels (5 tests)
- render_knowledge_panel returns Panel (1 test)
- render_knowledge_history returns Panel (1 test)
- render_knowledge_history empty (1 test)
- render_rollback_result success (1 test)
- render_rollback_result failure (1 test)

#### Knowledge shell commands (5 tests)
- /knowledge shows status (1 test)
- /knowledge history shows commits (1 test)
- /rollback usage hint (1 test)
- /rollback no knowledge store (1 test)
- /help includes knowledge commands (1 test)

### Phase 14b ChromaDB Semantic Recall tests (24 tests — new in Phase 14b)

#### Embedding utility (7 tests — `test_embeddings.py`)
- `get_embedding_function()` returns callable (1 test)
- `embed_text()` returns non-empty list of floats (1 test)
- `compute_similarity()` identical text near 1.0 (1 test)
- `compute_similarity()` different text < 0.8 (1 test)
- Semantic similarity ordering: related > unrelated (1 test)
- Empty text returns 0.0 (1 test)
- Fallback to keyword overlap when unavailable (1 test)

#### EpisodicMemory ChromaDB (11 tests — `test_episodic_chromadb.py`)
- Store and recall single episode via semantic similarity (1 test)
- Ranked results by semantic similarity (1 test)
- Semantic recall: "deployment" matches "push to production" (1 test)
- recall_by_intent filters by metadata (1 test)
- recent() returns most recent first (1 test)
- get_stats returns counts (1 test)
- max_episodes eviction (1 test)
- seed() bulk loads episodes (1 test)
- seed() skips duplicate IDs (1 test)
- Episode round-trip: all fields survive store → recall (1 test)
- Empty collection returns empty (1 test)

#### WorkflowCache semantic (1 test)
- Fuzzy lookup: "deploy the app to production" matches cached "push app to production" (1 test)

#### CapabilityRegistry semantic (2 tests)
- Semantic match: "access file data" finds capability "read_file" with detail "Read a document from disk" (1 test)
- Semantic matching disabled produces lower scores than enabled (1 test)

#### StrategyRecommender semantic (1 test)
- Semantically similar intent produces higher add_skill confidence than dissimilar (1 test)

#### ChromaDB + KnowledgeStore integration (2 tests)
- Episode persist → Git → seed → ChromaDB recall (1 test)
- Warm boot: fresh ChromaDB + seed from KnowledgeStore produces searchable episodes (1 test)

### Bundled agent tests (50 tests — new in Phase 22)

Per-agent tests for all 10 bundled agents (4-7 tests each):
- Class attributes: `agent_type`, `_handled_intents`, `intent_descriptors`, `default_capabilities`
- `handle_intent()` with recognized intent returns `IntentResult(success=True)` via MockLLMClient
- Self-deselect: unrecognized intent returns `None` via `_BundledMixin`
- Agent-specific: WebSearchAgent DuckDuckGo URL construction, PageReaderAgent HTML stripping, WeatherAgent wttr.in URL, NewsAgent `_parse_rss()` XML parsing (valid/malformed/empty/limit-10), CalculatorAgent safe eval (arithmetic, parentheses, rejects `__import__`, rejects alphabetic), TodoAgent/NoteTakerAgent/SchedulerAgent perceive without runtime
- Cross-cutting: `__init__.py` exports all 10, CognitiveAgent subclass check, attribute completeness

### Distribution tests (16 tests — new in Phase 22)

#### Runtime integration (8 tests)
- All 10 bundled pool types created at boot when enabled, bundled agents have `llm_client` set, bundled agents have `runtime` set, `_collect_intent_descriptors()` includes bundled intents, `bundled_agents.enabled: false` skips pools, status includes bundled pools, total agent count ≥ 40, bundled NL query via MockLLMClient

#### probos init (4 tests)
- Creates directory structure (`~/.probos/`, `data/`, `notes/`), creates valid YAML config with system/cognitive/bundled_agents sections, `--force` overwrites existing config, skips without `--force` when config exists

#### FastAPI endpoints (4 tests)
- `GET /api/health` returns `{status, agents, health}`, `GET /api/status` returns runtime status with pools, `POST /api/chat` processes message and returns `{response, dag, results}`, `create_app()` returns FastAPI instance

The interactive terminal interface works end-to-end:

1. `uv run python -m probos` boots the system with a Rich banner and boot sequence display.
2. Shows pool creation (2 heartbeats, 3 file readers, 2 red team) with green checkmarks.
3. Drops into an interactive shell with ambient health prompt: `[7 agents | health: 0.80] probos>`
4. Slash commands render system state as Rich tables and panels:
   - `/status` — full system overview (pools, mesh, consensus, cognitive config)
   - `/agents` — colour-coded agent table with ID, type, pool, state, confidence, trust
   - `/weights` — Hebbian weight table sorted by weight descending
   - `/gossip` — gossip view with agent states and capabilities
   - `/log [category]` — recent event log entries with timestamp, category, event, detail
   - `/memory` — working memory snapshot (active intents, recent results)
5. Natural language input routes through the full cognitive pipeline:
   - Shows spinner during "Decomposing intent..."
   - Displays the TaskDAG plan (number of tasks, intents, parameters)
   - Live-updates a progress table during execution (pending → running → done/FAILED)
   - Shows final results panel with checkmarks and optional result excerpts
6. `/debug on` enables verbose output: raw TaskDAG JSON, individual agent responses with confidence scores, consensus outcomes, verification results.
7. Error handling is graceful — malformed input, failed intents, empty DAGs produce user-friendly messages, never stack traces.
8. `/quit` triggers clean shutdown with spinner.

---

The following interactive session demonstrates the system:

```
$ uv run python -m probos

╭─ ProbOS v0.1.0 — Probabilistic Agent-Native OS ─╮
╰──────────────────────────────────────────────────╯

Starting ProbOS...
  ✓ Pool system: 2 system_heartbeat agents
  ✓ Pool filesystem: 3 file_reader agents
  ✓ Red team: 2 verification agents
  ✓ Total: 7 agents across 2 pools

ProbOS ready.
Type /help for commands, or enter a natural language request.

[7 agents | health: 0.80] probos> read the file at /tmp/test.txt

> read the file at /tmp/test.txt
  Plan: 1 task(s)
    t1: read_file (path=/tmp/test.txt)
╭─ Results ─╮
│ 1/1 tasks completed │
│   ✓ t1: read_file   │
╰──────────────────────╯

[7 agents | health: 0.80] probos> /agents
                    Agents
┌──────────┬─────────────────┬────────────┬────────┬────────────┬───────┐
│ ID       │ Type            │ Pool       │ State  │ Confidence │ Trust │
├──────────┼─────────────────┼────────────┼────────┼────────────┼───────┤
│ a1b2c3d4 │ file_reader     │ filesystem │ active │       0.80 │  0.50 │
│ ...      │ ...             │ ...        │ ...    │        ... │   ... │
└──────────┴─────────────────┴────────────┴────────┴────────────┴───────┘

[7 agents | health: 0.80] probos> /quit
Shutting down...
ProbOS stopped.
```

---

## Architectural Decisions Made

### AD-1 through AD-18 (unchanged from Phase 1)

See previous entries for: asyncio, in-process bus, pydantic config, ABC agent contract, in-memory registry, fuzzy capability matching, Bayesian confidence, bottom-up build order, uv toolchain, heartbeat lifecycle stubs, wait-with-timeout pattern, intent bus fan-out, agent self-selection, tiered capability matching, Hebbian keying, heartbeat gossip carriers, append-only event log, FileWriterAgent deferral.

### AD-19: Confidence-weighted quorum voting

Each agent's vote weight equals their confidence score when `use_confidence_weights=True`. This means a high-confidence rejection (0.9) outweighs two low-confidence approvals (0.1 each). Unweighted mode treats all votes equally.

### AD-20: Bayesian trust via Beta distribution

Each agent's trust is modeled as `Beta(alpha, beta)` where `E[trust] = alpha/(alpha+beta)`. Success observations increment alpha; failures increment beta. Prior is `Beta(2, 2)` (neutral 0.5). This converges toward ground truth with more observations and provides built-in uncertainty quantification.

### AD-21: Trust decay pulls toward prior

Trust records decay via `alpha = prior + (alpha - prior) * decay_rate`. This allows agents to recover trust over time if they stop failing, preventing permanent punishment from transient errors.

### AD-22: Red team agents bypass intent bus

Red team agents are spawned separately and do NOT subscribe to the intent bus. They are invoked directly by the consensus pipeline. This prevents them from being treated as regular agents and ensures they can't be corrupted by the intent flow.

### AD-23: Agent-to-agent Hebbian weights via rel_type

The HebbianRouter schema evolved from `(source_id, target_id)` to `(source_id, target_id, rel_type)` where rel_type is either `"intent"` (Phase 1: intent_id → agent_id) or `"agent"` (Phase 2: verifier_id → target_id). This enables learning agent affinity graphs from verification interactions.

### AD-24: FileWriterAgent proposes but doesn't commit

The FileWriterAgent validates write feasibility (parent dir exists, content provided) but does NOT write the file. It returns a proposal with `requires_consensus=True`. The runtime calls `FileWriterAgent.commit_write()` only after quorum approval and successful red team verification.

### AD-25: Consensus pipeline is opt-in

`submit_intent()` (Phase 1 API) continues to work without consensus for backward compatibility. `submit_intent_with_consensus()` adds the full pipeline: quorum → verification → trust update → Hebbian update. This avoids performance overhead for intents that don't need consensus.

### AD-26: Tiered LLM routing

LLM requests specify a tier (`fast`, `standard`, `deep`) which maps to different models. This allows cheap/fast models for simple decomposition and expensive/powerful models for complex reasoning. The `OpenAICompatibleClient` maps tiers to configurable model names.

### AD-27: MockLLMClient for deterministic testing

All cognitive tests use `MockLLMClient` which returns canned responses based on regex pattern matching against the prompt. This ensures tests are deterministic, fast, and don't require a live LLM endpoint. Patterns are registered in priority order; first match wins.

### AD-28: Working memory as bounded context window

Working memory assembles system state (agents, trust, Hebbian weights, capabilities, recent results) into a serializable snapshot that fits within a configurable token budget. Eviction prioritizes trimming connections and trust summaries before removing active intents and recent results.

### AD-29: TaskDAG for structured intent execution

The LLM's response is parsed into a `TaskDAG` — a directed acyclic graph of `TaskNode` entries with dependency edges. Ready nodes (all dependencies satisfied) execute in parallel via `asyncio.gather()`. This naturally handles single intents, parallel independent intents, and sequential dependent intents.

### AD-30: LLM client injected into runtime

`ProbOSRuntime` accepts an optional `llm_client` parameter, defaulting to `MockLLMClient`. This makes the cognitive layer testable without mock infrastructure and allows swapping in `OpenAICompatibleClient` for live deployments.

### AD-31: Event callback for real-time rendering

`DAGExecutor.execute()` and `ProbOSRuntime.process_natural_language()` accept an optional `on_event` async callback. The renderer uses this to provide real-time visual feedback during DAG execution. Events: `decompose_start`, `decompose_complete`, `node_start`, `node_complete`, `node_failed`. When `on_event` is `None` (the default), all existing behavior is unchanged.

### AD-32: Panels as pure rendering functions

All Rich rendering functions in `panels.py` take raw data (dicts, lists) — not runtime references. This keeps them testable in isolation and decouples display from data access. The shell gathers data from the runtime, then passes it to panel functions for rendering.

### AD-33: Shell tested via execute_command()

The shell's `execute_command(line)` method is the public API for testing. Tests bypass the REPL loop entirely and inject a `Console(file=StringIO())` to capture output. This avoids blocking `input()` in tests while exercising all command handlers.

### AD-34: Renderer orchestrates pipeline stages

The `ExecutionRenderer` orchestrates the cognitive pipeline stages itself (working memory assembly, episodic recall, decompose, execute, record results, episodic storage, attention focus update) rather than calling `runtime.process_natural_language()`. This allows inserting different Rich display modes (spinner for decomposition, Live display for execution) between stages. Episodic recall, episodic storage, and attention focus updates are wired in to match `runtime.process_natural_language()` behavior.

### AD-35: Ambient health in prompt

The shell prompt shows `[N agents | health: X.XX] probos>` where health is the average confidence of all ACTIVE agents. This gives the user immediate ambient awareness of system state without requiring a slash command.

### AD-36: Live LLM with graceful fallback

At boot, `__main__.py` creates an `OpenAICompatibleClient` from config and checks endpoint connectivity. If the endpoint is unreachable, it falls back to `MockLLMClient` with a warning. This means ProbOS always boots — even without a live LLM endpoint — and tests always use `MockLLMClient` (never hit a real endpoint).

### AD-37: Comprehensive system prompt for intent decomposition

The `SYSTEM_PROMPT` in `decomposer.py` explains to the LLM that it is the cognitive layer of an agent-native OS, not a chatbot. It describes available intents as a structured table, specifies the exact JSON response format, provides rules for consensus gating and dependency edges, and includes examples covering single intents, parallel intents, sequential dependencies, file metadata queries, and non-actionable requests. This gives real LLMs enough context to produce valid TaskDAG JSON.

### AD-38: Runtime tier switching via /tier

The `/tier` command changes `OpenAICompatibleClient.default_tier` on the fly, allowing users to switch between fast (cheap, quick) and deep (powerful, slow) models without restarting. The `/model` command shows the complete LLM configuration: endpoint URL, timeout, and tier-to-model mapping.

### AD-39: Specific LLM error handling

`OpenAICompatibleClient.complete()` catches `httpx.ConnectError`, `httpx.TimeoutException`, and `httpx.HTTPStatusError` separately, logging specific error messages. The user never sees a raw stack trace — errors are caught at the shell level and displayed as `[red]Processing error: ...[/red]`.

### AD-40: Aggressive JSON-only system prompt with response field

The `SYSTEM_PROMPT` opens with "You MUST respond with ONLY a JSON object" and repeats the constraint in the rules section. Markdown code fences, preamble text, and post-JSON commentary are explicitly prohibited. For non-actionable or conversational inputs (e.g., "hello", "what can you do?"), the LLM returns `{"intents": [], "response": "..."}` — the `response` field carries a brief conversational reply that the shell displays instead of the generic "No actionable intents" fallback. The `_extract_json()` parser handles code fences and embedded JSON as a safety net.

### AD-41: TaskDAG response field for conversational flow

`TaskDAG` gained a `response: str = ""` field that carries the LLM's optional conversational text through the entire pipeline: `_parse_response()` extracts it from the JSON → stored on `TaskDAG` → included in the result dict from `process_natural_language()` and `ExecutionRenderer.process_with_feedback()` → displayed by the renderer (cyan text) and `render_dag_result()` panel. When empty, the existing "No actionable intents" / "No intents were executed" fallback message is shown.

### AD-42: Non-consensus agents execute directly through mesh

DirectoryListAgent and FileSearchAgent are low-risk read-only operations. They execute through the mesh without quorum overhead — `use_consensus: false` in the DAG, which routes through the simple `submit_intent()` path. This keeps response times fast for read operations while reserving consensus for destructive or external operations.

### AD-43: ShellCommandAgent returns success=True for nonzero exit codes

The ShellCommandAgent always returns `success=True` as long as the command executed (even with nonzero exit code). The exit code, stdout, and stderr are included in the result data. This places interpretation responsibility on the consumer — a nonzero exit code is not necessarily an error (e.g., `grep` returns 1 for "no matches").

### AD-44: HttpFetchAgent creates fresh httpx client per request

The HttpFetchAgent creates a fresh `httpx.AsyncClient` with `async with` for each request, keeping agent state minimal. This avoids connection pool management, stale connections, and shared mutable state between concurrent fetch operations. The timeout and body cap are configurable via class constants.

### AD-45: Red team re-execution limitation for non-deterministic commands

Red team verification for `run_command` re-executes the same command and compares exit codes and stdout. This works well for deterministic commands like `echo hello` but may produce false mismatches for time-dependent or stateful commands (e.g., `date`, `ls` with changing files). This is a known limitation documented as an architectural decision rather than a bug.

### AD-46: Post-execution reflection via REFLECT_PROMPT

When the decomposition LLM sets `reflect: true` in the JSON response, the pipeline adds a second LLM call after DAG execution completes. The `IntentDecomposer.reflect()` method sends the original user request plus serialized agent results to the LLM with a separate `REFLECT_PROMPT` system prompt. The reflection prompt instructs the LLM to synthesize a plain-text answer rather than JSON. The reflection output is stored in `execution_result["reflection"]` and displayed as cyan text in both the `render_dag_result()` panel and the renderer output. The `MockLLMClient` detects reflection requests by checking for the substring "analyzing results returned by ProbOS agents" in the system prompt, enabling deterministic testing without a live LLM.

---

### AD-47: Reflect hardening — timeout, payload cap, graceful fallback

The reflect step (post-execution LLM synthesis) is hardened against three failure modes: (1) The `decomposer.reflect()` call in `runtime.py` and `renderer.py` is wrapped in `asyncio.wait_for()` using `config.cognitive.decomposition_timeout_seconds`. (2) The serialized payload sent to the LLM is capped at ~8000 characters (~2000 tokens) with a trailing `[... results truncated ...]` note. (3) If reflect times out or raises any exception, the execution results are preserved and `execution_result["reflection"]` is set to a fallback string `"(Reflection unavailable — results shown above)"` rather than losing the entire result or crashing.

### AD-48: Semantic embedding for episodic recall (upgraded in Phase 14b)

Episodic memory uses ChromaDB with ONNX MiniLM embeddings for semantic similarity search (AD-170, AD-171). Episodes are stored as documents with metadata in a ChromaDB PersistentClient collection. Recall uses `collection.query()` for true semantic matching — "deployment" finds episodes about "push to production." The shared embedding utility (`embeddings.py`) provides `compute_similarity()` for other subsystems (WorkflowCache, CapabilityRegistry, StrategyRecommender). Graceful fallback to keyword-overlap bag-of-words if ONNX is unavailable. `MockEpisodicMemory` still uses keyword matching for deterministic tests (AD-176).

### AD-49: MockEpisodicMemory for testing

Same pattern as `MockLLMClient`: `MockEpisodicMemory` implements the same interface as `EpisodicMemory` but stores episodes in a plain list. Recall uses keyword-set overlap instead of semantic embeddings. This keeps the test suite deterministic and fast — no ChromaDB, no embedding computation. Preserved unchanged through Phase 14b (AD-176).

### AD-50: Episode storage is fire-and-forget

Episode storage in `runtime.py` is wrapped in a try/except. If storage fails (ChromaDB error, serialization error, etc.), the failure is logged as a warning but never blocks the user's result. The execution result is always returned regardless of whether the episode was successfully stored.

### AD-51: Attention mechanism — priority-based task scheduling

The `AttentionManager` is a priority scorer and budgeter, not an execution engine. It scores tasks using `urgency × relevance × deadline_factor × dependency_depth_bonus` and returns batches capped at `max_concurrent_tasks`. The `DAGExecutor` asks "which nodes should I run next?" instead of running all ready nodes simultaneously. The mechanism is backward compatible — `DAGExecutor` works without an `AttentionManager` (guarded by `if self.attention`).

### AD-53: Cross-request focus history as ring buffer

The `AttentionManager` maintains a bounded ring buffer of `FocusSnapshot` entries (default max 10, configurable via `focus_history_size`). Each `update_focus()` call appends a snapshot with the current keywords and timestamp. The `_compute_relevance()` method uses the union of keywords from the last 3 snapshots to compute keyword overlap with task intents. This means recent request context influences task prioritization across multiple `process_natural_language()` calls. The overlap ratio has a floor of 0.3 so that unfocused tasks still get non-zero relevance.

### AD-54: Background demotion via configurable factor

Tasks with `is_background=True` have their final attention score multiplied by `background_demotion_factor` (default 0.25). This pushes background tasks to the bottom of the attention batch without removing them entirely. The factor is configurable in `CognitiveConfig` and `system.yaml`, and is passed to `AttentionManager` via the runtime constructor. The `TaskNode` dataclass gained a `background: bool = False` field, and the `DAGExecutor._attention_batch()` propagates it to `AttentionEntry.is_background`.

### AD-55: Intent tokenization for relevance matching

Intent strings like `"read_file"` are tokenized by splitting on both underscores and spaces, producing tokens `{"read", "file"}`. Tokens shorter than 3 characters are filtered out. Focus keywords are similarly tokenized from natural language text. Relevance is computed as the ratio of overlapping tokens to total intent tokens: `overlap / len(intent_tokens)`. This allows intent names (underscore-separated) to match against natural language focus text (space-separated).

### AD-52: Episodic memory created at boot

`__main__.py` creates an `EpisodicMemory` instance (SQLite-backed, stored in the session's temp directory) and passes it to `ProbOSRuntime`. The `ExecutionRenderer.process_with_feedback()` was also updated to include episodic recall (before decomposition) and episode storage (after execution), matching the behavior of `runtime.process_natural_language()`. Previously, the renderer's duplicated pipeline (AD-34) skipped episodic memory entirely, causing `/history` to report "not enabled" and no episodes to be recorded during interactive use.

### AD-56: Renderer attention focus wiring

The `ExecutionRenderer.process_with_feedback()` was missing the `attention.update_focus()` call that `runtime.process_natural_language()` performs at the start of each request. Without this, interactive use via the shell never populated the focus history ring buffer, so `/attention` showed "Focus: none" and cross-request relevance scoring had no data. Fixed by adding `self.runtime.attention.update_focus(intent=text, context=text)` at the top of `process_with_feedback()`. Same class of bug as AD-52 — the renderer's duplicated pipeline (AD-34) missed a step added in a later phase.

### AD-57: Dreaming as proactive consolidation

Dreaming is the proactive counterpart to reactive learning. During active use, Hebbian weights, trust, and episodic memory evolve based on individual interactions. During idle periods, the dreaming engine replays recent experiences in bulk to consolidate patterns: strengthening pathways that led to successful outcomes, weakening failed ones, pruning near-zero connections, and identifying temporal intent sequences for pre-warming. This is analogous to memory consolidation during biological sleep.

### AD-58: Dream cycle is synchronous on internal state

The `DreamingEngine.dream_cycle()` directly mutates `HebbianRouter._weights` and `TrustNetwork._records` rather than going through the normal `record_interaction()` / `record_outcome()` APIs. This is intentional — dream replay is a bulk consolidation operation with its own strengthening/weakening factors (configurable separately from the real-time Hebbian reward). The `pathway_strengthening_factor` (default 0.03) and `pathway_weakening_factor` (default 0.02) are smaller than the real-time Hebbian reward (0.05) to avoid over-learning from replay.

### AD-59: DreamScheduler idle detection via monotonic clock

The `DreamScheduler` tracks idle time using `time.monotonic()` rather than wall clock time. Each `process_natural_language()` call triggers `record_activity()` on the scheduler, resetting the idle timer. The scheduler's background loop checks `time.monotonic() - last_activity_time >= idle_threshold_seconds` to determine when to dream. This avoids issues with system clock adjustments and timezone changes.

### AD-60: Pre-warm intents via temporal bigrams

Pre-warm identification uses a simple but effective approach: count bigram transitions across recent episodes (e.g., if `list_directory` is frequently followed by `read_file`, then `read_file` is a pre-warm candidate). Bigram successors are weighted 2x relative to raw frequency to emphasize sequential patterns over standalone popularity. The top-K intents (default 5) are stored on `DreamingEngine.pre_warm_intents` for future decomposer integration.

### AD-61: Trust consolidation threshold

Trust boosts and penalties during dreaming require an agent to appear in more than 1 successful (or failed) episode to receive an adjustment. This prevents a single lucky or unlucky interaction from triggering a dreaming-based trust change. The threshold is intentionally low (>1) since dreaming operates on recent episodes (default 50), and higher thresholds would make trust consolidation too conservative.

### AD-62: Dream prune threshold separate from Hebbian decay

The dreaming prune threshold (default 0.01) is higher than the Hebbian `decay_all()` pruning threshold (0.001). During a dream cycle, `decay_all()` is called first (pruning < 0.001), then a second pass removes anything below `prune_threshold` (< 0.01). This more aggressive pruning during dreaming keeps the weight graph sparse and focused on meaningful connections.

### AD-63: Background dream cycle logs at DEBUG level

The dream cycle completion message in `DreamingEngine.dream_cycle()` was changed from `logger.info()` to `logger.debug()`. Since the dream scheduler fires from a background asyncio task, INFO-level output was printing over the interactive shell prompt, making it impossible to type commands. With the system log level set to INFO (`config/system.yaml`), DEBUG messages are suppressed in normal interactive use but remain available when running with a lower log level for troubleshooting.

### AD-64: Workflow cache as LLM bypass optimization

The `WorkflowCache` stores successful DAG patterns keyed by normalized user input. On subsequent identical (or fuzzy-matching) requests, the cached DAG is returned directly without calling the LLM. This eliminates LLM latency and cost for repeated workflows. The cache sits in the `IntentDecomposer.decompose()` method before the LLM call — exact match first, then fuzzy match with pre-warm hints. Cache misses fall through to the normal LLM decomposition path with zero overhead.

### AD-65: Deep copy with fresh UUIDs on cache retrieval

When a cached DAG is retrieved, it is deserialized from JSON with fresh `uuid4()` node IDs and all node statuses reset to `"pending"`. This prevents ID collisions when the same workflow is executed multiple times (each execution needs unique node IDs for the event log, attention manager, and result tracking). The original cached DAG is never mutated.

### AD-66: Fuzzy matching requires dual overlap

`WorkflowCache.lookup_fuzzy()` requires BOTH conditions to return a hit: (1) at least one pre-warm intent must match an intent stored in the cached DAG, AND (2) semantic similarity between the query and cached pattern must exceed the configurable `similarity_threshold` (default 0.6, via `compute_similarity()` from `embeddings.py` — AD-173). This dual requirement prevents false positives while allowing meaning-based matching — "deploy the app" can match a cached "push to production" workflow because the embeddings understand semantic relatedness. Pre-warm intents provide structural signal; semantic similarity provides meaning-based signal.

### AD-67: Pre-warm hints injected into LLM prompt

When `IntentDecomposer.pre_warm_intents` is non-empty, a `PRE-WARM HINTS` section is appended to the LLM prompt listing the predicted intents. This nudges the LLM toward intents that the dreaming engine identified as likely follow-ups based on temporal bigram analysis. The hints are advisory — the LLM is free to ignore them if the user's request doesn't match.

### AD-68: Cache-first decomposition pattern

The decomposer checks the workflow cache before calling the LLM, creating a three-tier lookup: (1) exact normalized match → instant replay, (2) fuzzy match with pre-warm overlap → likely replay, (3) full LLM decomposition → fallback. This mirrors CPU cache hierarchies (L1/L2/main memory) where each tier trades coverage for speed. The cache stores only successful DAGs (all nodes completed), so replayed workflows have a high probability of success.

### AD-69: Workflow cache wired in both runtime and renderer

Following the AD-34 pattern, workflow cache storage and pre-warm intent synchronization are wired in both `runtime.process_natural_language()` and `renderer.process_with_feedback()`. After successful DAG execution, the DAG is stored in the cache. Before decomposition, pre-warm intents from the dream engine are synced to the decomposer. This ensures the cache works correctly regardless of whether the request comes through the programmatic API or the interactive shell.

### AD-70: Status panel workflow cache section

The `render_status_panel()` in `panels.py` was missing the Workflow Cache section even though `runtime.status()` already returned `workflow_cache` data (size and entries). Added a "Workflow Cache" heading with `Cached patterns: N` to the status panel, matching how Dreaming and Cognitive sections are displayed. Same class of omission as AD-52/AD-56 — the rendering layer wasn't updated when a new runtime capability was added.

### AD-71: BaseAgent **kwargs passthrough for extensibility

`BaseAgent.__init__()` gained `**kwargs` and stores `kwargs.get("runtime")` as `self._runtime`. This allows agent subclasses to receive arbitrary construction parameters without modifying the base signature. `AgentSpawner.spawn()` and `ResourcePool` both forward `**kwargs` to agent constructors. Existing agents ignore the kwargs — only `IntrospectionAgent` reads `_runtime`. This is a minimal, non-breaking change: all existing agent constructors continue to work unchanged.

### AD-72: Execution snapshot pattern prevents self-referential overwrite

When a user asks "what just happened?", that request itself goes through `process_natural_language()`. Without protection, `explain_last` would read the introspection result (its own execution), not the previous real request. The snapshot pattern solves this: at the top of `process_natural_language()`, `_previous_execution = _last_execution`. At the end, `_last_execution = execution_result`. The `IntrospectionAgent.explain_last` reads `_previous_execution`, which always contains the request before the current one. This is wired in both `runtime.py` and `renderer.py` (AD-34 duplication).

### AD-73: IntrospectionAgent is purely observational

The `IntrospectionAgent` reads from runtime internals but never modifies them. All handlers return structured data that the reflect step can synthesize into natural language. The agent has high initial confidence (0.9) since it only reads system state and cannot "fail" in the same way a file reader can. It does not subscribe to consensus — all introspection intents have `use_consensus: false`.

### AD-74: Why intent combines episodic and Hebbian context

The `why` handler doesn't just return matching episodes — it also looks up trust scores and top Hebbian connections for every agent mentioned in those episodes. This gives the reflect step enough material to explain agent selection decisions: "file_reader was chosen because it has a trust score of 0.85 and strong Hebbian connections to the read_file intent." Without this agent context, the reflect step would only know what happened, not why.

### AD-75: /explain as NL routing shortcut

The `/explain` command routes "what just happened?" through the normal NL pipeline rather than implementing a separate code path. This means it goes through decomposition (MockLLMClient matches the regex), execution (IntrospectionAgent handles the intent), and reflection (LLM synthesizes a human-readable explanation). This keeps the shell thin and ensures introspection uses the same cognitive pipeline as regular requests.

### AD-76: IntrospectionAgent Hebbian API mismatch fix

`IntrospectionAgent._agent_info()` and `_why()` both called `rt.hebbian_router.all_weights_typed()` and iterated the result as a list of objects with `.source`, `.target`, `.weight` attributes. But the real `HebbianRouter.all_weights_typed()` returns a `dict` with `(source, target, rel_type)` tuple keys mapped to float weights. Fixed by iterating `all_weights.items()` and indexing tuples (`k[0]`, `k[1]`) instead of attribute access. The test mocks were also corrected from returning `[]` to returning `{}` to match the real API signature.

### AD-77: IntentDescriptor as structured agent metadata

Agents now declare `intent_descriptors: list[IntentDescriptor]` as class-level metadata. Each descriptor specifies the intent `name`, `params` schema, `description`, `requires_consensus`, and `requires_reflect`. This is part of the agent type definition, not per-instance state. Non-intent agents (RedTeam, Corrupted, SystemHeartbeat) explicitly declare `intent_descriptors = []`.

### AD-78: Dynamic prompt assembly via PromptBuilder

The decomposer's system prompt is no longer a single hardcoded string. `PromptBuilder.build_system_prompt(descriptors)` dynamically generates the intent table, consensus rules, and reflect rules from whatever `IntentDescriptor` list is provided. The preamble, response format, and examples are static constants (they demonstrate format, not enumerate capabilities). Descriptors are sorted by name for deterministic output and deduplicated by name.

### AD-79: Legacy system prompt fallback

The original `SYSTEM_PROMPT` is preserved as `_LEGACY_SYSTEM_PROMPT` (with a public `SYSTEM_PROMPT` alias for backward compatibility). When `IntentDecomposer._intent_descriptors` is empty (i.e., `refresh_descriptors()` was never called), the decomposer falls back to the legacy prompt. This ensures tests that create a standalone `IntentDecomposer` without a runtime still work unchanged.

### AD-80: Boot-time descriptor sync

During `ProbOSRuntime.start()`, after all pools are created, the runtime calls `self.decomposer.refresh_descriptors(self._collect_intent_descriptors())`. This walks all registered agent templates, collects their `intent_descriptors`, deduplicates by name, and pushes the full set to the decomposer. `register_agent_type()` also triggers a refresh, so dynamically added agent types immediately become available to the LLM.

### AD-81: Self-assembling intent table fulfills original vision

The original ProbOS vision promised: "New capability is added by introducing new agent types to the mesh. They self-integrate by broadcasting capabilities and forming connections." Phase 6b makes this real for the decomposer. Adding a new agent class with `intent_descriptors` declared makes its intents immediately available to the LLM without editing any system prompt, mock patterns, or configuration files.

### AD-82: Result rendering too terse for structured data

`render_dag_result()` in `panels.py` truncated all agent results to 100 chars via `str(ir.result)[:100]`. For directory listings this produced unreadable stringified dict gibberish. Added `_format_result()` helper that detects common result structures: directory listings (list of dicts with `name`/`type` keys) get formatted with blue directory names and file sizes; strings get 500-char previews; fallback gets 200-char previews. Same AD-34 pattern — rendering layer not keeping up with agent capabilities.

### AD-83: Prompt examples missing introspection capabilities

The "what can you do?" and "what is the weather?" example responses in both `PROMPT_EXAMPLES` (prompt_builder.py) and `_LEGACY_SYSTEM_PROMPT` (decomposer.py) only mentioned file/shell/HTTP operations. The LLM parroted this stale example when users asked about capabilities, omitting Phase 6a introspection. Updated both to include "answer questions about my own state (explain what happened, describe agents, assess system health, explain my reasoning)."

### AD-84: LLM client verbose logging stomping shell prompt

`llm_client.py` logged full LLM request payloads, headers, and raw HTTP response bodies at `INFO` level, and `decomposer.py` logged raw LLM responses at `INFO` level. Since shell log level is INFO, these multi-hundred-line JSON dumps printed over the interactive prompt on every request. Downgraded all 4 log calls to `DEBUG` — same fix as AD-63 (dream scheduler log stomping). The AD-63/AD-84 pattern: background subsystem logging at INFO that should be DEBUG for interactive use.

### AD-85: MockLLMClient always rejects arbitration for deterministic testing

The MockLLMClient returns `{"action": "reject"}` for all escalation arbitration requests (detected by "escalation arbiter" in system prompt). This means Tier 2 always falls through to Tier 3 in tests. The "approve" and "modify" paths through a real LLM are tested only via unit tests with mock submit functions (tests 4–6), not through the full runtime pipeline.

### AD-86: EscalationResult stored as dict, not dataclass, on TaskNode

`TaskNode.escalation_result` is `dict | None`, populated via `EscalationResult.to_dict()`. This prevents JSON serialization failures in workflow cache deep copy, episodic memory storage, working memory snapshots, and debug output — all of which call `json.dumps()` on TaskNode fields.

### AD-87: EscalationManager is event-silent; executor logs events

The `EscalationManager` returns results to its caller but never interacts with the event log or `on_event` callback. The `DAGExecutor._execute_node()` is the single event source for escalation events (escalation_start, escalation_resolved, escalation_exhausted), consistent with how all other execution events (node_start, node_complete, node_failed) are logged.

### AD-88: Rich Live must stop before Tier 3 user input

The renderer's `Live` context captures stdout. If `input()` is called during a Live session, the prompt is garbled or deadlocked. The escalation system uses a `pre_user_hook` callable that the renderer can set to `live.stop`, called before `user_callback`. This is a structural constraint that any future interactive escalation must respect.

### AD-89: Pre-user hook wiring for escalation prompt

The `pre_user_hook` mechanism existed in `EscalationManager` (AD-88) but was never connected by the renderer. `ExecutionRenderer.__init__` now calls `runtime.escalation_manager.set_pre_user_hook(self._stop_live_for_user)` to wire the hook at construction time. Without this wiring, Tier 3 escalation prompts were garbled by the active display.

### AD-90: DAG plan display moved to debug-only

The `_render_dag_plan()` call in the renderer was printing a static text plan ("Plan: N task(s)\n  t1: intent_name (param=value)") immediately before the execution display. This overlapped with the progress table below it since both showed the same information. Moved the plan call behind `if self.debug:` guard. The progress table's Params column (max_width=40) now serves as the single source of task parameter visibility.

### AD-91: Tier 3 escalation prompt enrichment

The original Tier 3 user consultation prompt only showed the intent name and a generic "Consensus rejected" message — insufficient for the user to make an informed decision. Enhanced `_user_escalation_callback` in `shell.py` to display: (1) each param key/value with 120-char truncation, (2) the actual error message in red, (3) which escalation tiers were already attempted (e.g., "retry → arbitration → user"). Also passed `tiers_attempted` from `EscalationManager.escalate()` into the Tier 3 context dict.

### AD-92: Rich Live removed in favor of status spinner

Rich's `Live` display relies on ANSI escape sequences to erase and redraw frames. Both `transient=True` and `transient=False` modes produced duplicate/overlapping frames in VS Code's integrated terminal (PowerShell 5.1 and PowerShell 7). Replaced with `console.status()` spinner during execution, followed by a single `console.print()` of the final progress table after execution completes. This eliminates all ANSI frame-erasure issues while preserving visual feedback (spinner during execution, clean table with ✓/✗ statuses after).

### AD-93: Manually managed spinner for escalation compatibility

Using `console.status()` as a context manager (`with ... as status:`) blocks stdin, preventing Tier 3 escalation from accepting user input. Changed to manually managed spinner: `status = console.status(...); status.start()` before execution, `status.stop()` in a `finally` block after execution. The `_stop_live_for_user` hook calls `self._status.stop()` before the escalation prompt appears, freeing stdin for `input()`. This replaces the Rich Live pre_user_hook (AD-88/AD-89) with an equivalent mechanism for the spinner.

### AD-94: ScalingConfig and demand tracking

Added `ScalingConfig` pydantic model with scale_up/down thresholds, step sizes, cooldown, observation window, idle scale-down timing. IntentBus extended with per-broadcast timestamp tracking (`_broadcast_timestamps`), sliding window pruning, `demand_metrics()` for system-wide stats, and `per_pool_demand(pool_intents)` for per-pool broadcast counts keyed by intent-to-pool mapping.

### AD-95: Pool bounds enforcement (add_agent / remove_agent)

ResourcePool extended with `min_size` and `max_size` attributes (from PoolConfig), `add_agent()` that respects `max_size`, and `remove_agent(trust_network=)` that respects `min_size`. `check_health()` now caps at `max_size` after respawn. These methods do NOT touch `target_size` — only the PoolScaler adjusts targets.

### AD-96: Trust-aware scale-down selection

`remove_agent(trust_network=...)` selects the agent with the lowest Bayesian trust score (via `trust_network.get_score()`) for removal. When all agents have equal trust or no trust_network is provided, falls back to removing the newest agent (last in `_agent_ids` list). This ensures high-trust agents survive scale-down.

### AD-97: PoolScaler — demand-driven pool sizing

New `PoolScaler` class in `substrate/scaler.py` runs a background loop (interval = observation_window / 2). Per cycle: queries `IntentBus.per_pool_demand()`, computes `broadcasts / pool.current_size` ratio, scales up if above threshold, scales down if below. Cooldown prevents flapping. Excluded pools (e.g., "system") and pinned pools (min == max) are skipped. `scaling_status()` returns per-pool snapshot for shell/panel display.

### AD-98: Escalation surge integration

`EscalationManager.__init__` accepts optional `surge_fn` parameter (async callable `(pool_name, extra) -> bool`). When Tier 1 retry begins, if `surge_fn` is set and `context` contains `pool_name`, the manager requests one extra agent in that pool before retrying. This gives retries a better chance of succeeding by temporarily increasing pool capacity. Bypasses cooldown (emergency request).

### AD-99: Dreaming idle scale-down integration

`DreamingEngine.__init__` accepts optional `idle_scale_down_fn` parameter. After Step 4 (pre-warm) in `dream_cycle()`, the callback is invoked to reduce pool sizes toward their minimums, freeing resources during idle periods. Runtime wires `pool_scaler.scale_down_idle` into the dreaming engine when both are enabled.

### AD-100: /scaling command and render_scaling_panel

New `/scaling` shell command shows per-pool scaling status (current size, min-max range, target, demand ratio, last scaling event, cooldown remaining). `render_scaling_panel()` in panels.py builds a Rich Table with excluded pool indicators. Renderer handles `scale_up`/`scale_down` events (no-op on node status, logged by scaler).

### AD-101: Federation config design — disabled by default

`FederationConfig.enabled` defaults to `False`. Single-node remains the default mode. The federation layer is pure additive — no existing behavior changes when `enabled=False`. `PeerConfig` stores static peer list (node_id + address). The config model is clean Pydantic, loaded from YAML just like all other sections.

### AD-102: FederationMessage wire protocol

Chose a flat `FederationMessage` dataclass with `type` discriminator over alternatives (protobuf, msgpack). JSON serialization is sufficient for the 2-3 node prototype. Message types: `intent_request`, `intent_response`, `gossip_self_model`, `ping`, `pong`. Payload carries intent data as a dict, deserialized to `IntentMessage` on the receiving end.

### AD-103: Loop prevention via `federated` parameter

Added `federated: bool = True` keyword-only parameter to `IntentBus.broadcast()`. When the bridge receives an inbound intent from a peer, it calls `broadcast(intent, federated=False)`, which skips `_federation_fn`. This prevents A→B→A infinite forwarding without requiring message ID tracking or TTL hops. The parameter is backward-compatible — all existing call sites use positional args and don't pass `federated`.

### AD-104: MockTransportBus for testing

All federation tests use `MockTransportBus` + `MockFederationTransport` — shared in-memory message delivery with inbound handler callbacks. No pyzmq dependency in tests. The real `FederationTransport` uses ZeroMQ DEALER-ROUTER sockets but is NOT tested in the test suite. Both transports expose the same interface so `FederationBridge` is transport-agnostic.

### AD-105: FederationRouter returns all peers (Phase 9)

`FederationRouter.select_peers()` returns all available peers. With only 2-3 nodes, capability-based peer selection adds complexity without benefit. The router stores `NodeSelfModel` from gossip for future filtering. `peer_has_capability()` is available but not used by `select_peers()` yet.

### AD-106: NodeSelfModel (Psi) gossip

Each node periodically broadcasts `NodeSelfModel` containing capabilities, pool sizes, agent count, health, and uptime. This enables peer routing decisions in future phases. The gossip interval is configurable via `FederationConfig.gossip_interval_seconds`. The `_build_self_model()` method on ProbOSRuntime collects capabilities from agent templates, pool sizes, and average ACTIVE agent confidence.

### AD-107: `--config` flag for multi-node launch

Added `argparse` to `__main__.py` with `--config` / `-c` flag. Each node can be launched with its own YAML: `uv run python -m probos --config config/node-1.yaml`. Default falls back to `config/system.yaml`. Node config files (`config/node-1.yaml`, `config/node-2.yaml`) are provided for a 2-node federation. `scripts/launch-cluster.sh` launches both nodes as background processes.

### AD-108: WindowsSelectorEventLoopPolicy for pyzmq on Windows

On Windows, Python defaults to the ProactorEventLoop which does not implement `add_reader()` / `add_writer()` — methods required by pyzmq's async socket implementation. This caused `RuntimeError: Proactor event loop does not implement add_reader family of methods` when the federation transport tried to recv on ZMQ sockets. Fixed by setting `asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())` before `asyncio.run()` in `__main__.py`, guarded by `sys.platform == "win32"`. The SelectorEventLoop supports the full select-based I/O needed by ZMQ. This is a platform-specific fix — Linux and macOS already default to selector-based event loops.

### AD-109: Static analysis over runtime sandboxing for security

Generated agent code is validated statically via AST analysis (CodeValidator) rather than relying on runtime sandboxing (seccomp, containers). The CodeValidator checks: (1) syntax validity, (2) import whitelist, (3) forbidden pattern regex scan, (4) schema conformance (BaseAgent subclass, intent_descriptors, handle_intent), (5) module-level side effect detection. The SandboxRunner verifies functional correctness (does the agent handle a synthetic intent and return IntentResult?), not security. This keeps the test suite fast and portable (no Docker/seccomp dependency) while the static analysis catches the most dangerous patterns (subprocess, eval, exec, socket, ctypes, __import__, file writes).

### AD-110: Probationary trust for self-created agents

Self-created agents start with a pessimistic Beta prior: α=1, β=3 → E[trust] = 0.25. This means consensus weights their votes at 25% of an established agent's weight. The prior converges toward the system's default (α=2, β=2 → E[trust] = 0.5) after ~5 successful operations. This implements "trust but verify" — new agents participate immediately but cannot dominate consensus until they've proven reliable. The `TrustNetwork.create_with_prior()` method sets the custom prior; it's a no-op if the agent already has a record (prevents overwriting earned trust).

### AD-111: MockLLMClient agent design pattern

The MockLLMClient detects agent design requests by matching "UNHANDLED INTENT:" and "Subclass BaseAgent" in the prompt. It generates minimal but valid agent source code that conforms to the BaseAgent contract: correct imports, class with intent_descriptors/agent_type/_handled_intents class attributes, perceive/decide/act/report lifecycle methods, handle_intent dispatcher. This allows the full self-mod pipeline to be tested end-to-end without a real LLM. The intent extraction pattern similarly detects "no existing agent can handle it" + "intent_name_snake_case" and returns valid JSON.

### AD-112: Unhandled intent detection via decomposer fallback

When `process_natural_language()` produces an empty TaskDAG (no nodes and no `response` field), and self_mod is enabled, the runtime calls `_extract_unhandled_intent()` to ask the LLM what kind of agent is needed. If extraction succeeds, the pipeline designs/validates/sandboxes/registers the new agent, then retries decomposition. This retry means the user's original request may succeed on the first attempt, transparently. The `response` field check prevents self-mod from triggering on conversational LLM replies (where no intent execution is needed).

### AD-113: CodeValidator schema conformance checks

The CodeValidator checks that generated code structurally matches the agent contract by walking the AST: (1) exactly one class subclassing BaseAgent, (2) class-level `intent_descriptors` assignment, (3) class-level `agent_type` assignment, (4) class-level `_handled_intents` assignment, (5) `handle_intent` method (async or sync). This catches structural errors before sandbox execution, providing faster feedback and clearer error messages than runtime ImportError/AttributeError.

### AD-114: BehavioralMonitor as post-deployment guardrail

Unlike red team agents (which verify output correctness during consensus), the BehavioralMonitor tracks operational patterns of self-created agents over time: execution duration, failure rate, trust trajectory. Alerts are informational — visible via `/designed` — not blocking. The `should_recommend_removal()` method recommends removal after 10+ executions with >50% failure rate, or after 3 consecutive trust declines. This separates "is this output correct?" (red team) from "is this agent reliable over time?" (behavioral monitor).

### AD-115: LLM client injection into designed agents

Designed agents that need LLM intelligence (e.g., translation, summarization) can't function without access to the LLM client. The `AgentDesigner` prompt now includes an LLM ACCESS section with `self._llm_client = kwargs.get("llm_client")` in `__init__`. `SandboxRunner` forwards the LLM client during sandbox testing. `ProbOSRuntime._create_designed_pool()` passes `llm_client=self.llm_client` in the pool kwargs. This means designed agents can make LLM calls just like the cognitive layer, enabling intelligence-based capabilities beyond simple data retrieval.

### AD-116: subprocess.Popen for SelectorEventLoop compatibility

On Windows, `WindowsSelectorEventLoopPolicy` is required for pyzmq (AD-108), but `SelectorEventLoop` does not support `asyncio.create_subprocess_shell/exec`. Replaced async subprocess calls in `ShellCommandAgent` with synchronous `subprocess.Popen` run via `loop.run_in_executor(None, _run_sync, ...)`. The `_run_sync()` function blocks in a thread pool, preserving async compatibility while working on all Windows event loop policies. Uses PowerShell on Windows (`["powershell", "-Command", cmd]`), `/bin/sh -c` elsewhere.

### AD-117: PowerShell wrapper stripping via _PS_WRAPPER_RE

LLM-generated commands often arrive wrapped in redundant `powershell -Command "..."` shells. Since `ShellCommandAgent` already invokes PowerShell on Windows, this creates a double-nesting problem (`powershell -Command "powershell -Command '...'"`) that changes quoting semantics and breaks commands. `_strip_ps_wrapper()` uses `_PS_WRAPPER_RE` regex to detect and unwrap these patterns before execution, extracting the inner command. The regex handles both quoted (`"..."`, `'...'`) and unquoted forms.

### AD-118: Escalation re-execution after user approval

When Tier 3 user consultation approves an intent, the escalation manager now re-executes the original intent through the mesh rather than just returning a stale result. The re-execution uses the same pool rotation and submit function as Tier 1 retries. If the user rejects, the node is marked as failed with a descriptive message. On consensus-policy rejection (Tier 2 LLM rejects), the original agent results are preserved and returned instead of being discarded.

### AD-119: Existing-agent routing before self-mod

Before triggering the self-modification pipeline, the renderer checks whether the LLM-extracted intent name matches an already-registered intent. If a match is found, the request is re-decomposed using the existing agent rather than creating a duplicate. This prevents the common case where the LLM extracts `run_command` as the "unhandled intent" even though `ShellCommandAgent` already handles it, avoiding unnecessary agent proliferation.

### AD-120: General-purpose intent preference in self-mod

`_extract_unhandled_intent()` includes explicit guidance: "Prefer general-purpose intents (translate_text, convert_data) over narrow ones (translate_hello_to_japanese)." This nudges the LLM toward creating reusable agents rather than single-use ones. The intent extraction prompt also avoids creating intents that overlap with existing capabilities by listing all registered intent names.

### AD-121: Reflect prompt rewrite with node status prefix

The `REFLECT_PROMPT` was rewritten to produce synthesized answers rather than summaries. Each node's results in the reflect payload are now prefixed with `[status]` (e.g., `[completed]`, `[failed]`) so the LLM can distinguish successful from failed operations. The `_summarize_node_result()` method deduplicates identical `output` and `result` fields (common when an agent returns the same data in both) to reduce payload bloat.

### AD-122: Force reflect=true for designed agent intents

When a designed agent handles an intent, its descriptor is created with `requires_reflect=True`. The renderer also forces `dag.reflect = True` on DAGs produced by designed agents. This ensures all designed agent responses go through LLM synthesis, compensating for the fact that designed agents may produce raw/structured output that benefits from a natural-language reflection step.

### AD-123: Self-mod UX with explicit user approval

Self-modification now shows the user what intent was detected, what the proposed agent will do, and asks for explicit approval before creating the agent. The renderer displays the intent name, purpose, and "Create this agent? (y/N)" prompt. After approval, the agent is designed, validated, sandboxed, and registered with the user's original request retried immediately. The shell wires `_user_approval_callback` for this prompt.

### AD-124: Anti-echo rules for run_command

The prompt builder generates explicit rules prohibiting `echo`, `Write-Host`, `Write-Output`, and similar commands from being used to fabricate answers. Without this, the LLM would often decompose "what time is it?" into `run_command: echo "The time is 3pm"` — faking the answer rather than running an actual time-querying command. The anti-echo rules force the LLM to use real system commands for data retrieval.

### AD-125: Log suppression during interactive shell

`__main__.py` now raises the logging level for noisy loggers (root, probos, asyncio, etc.) during interactive shell operation. Without this, INFO-level log messages from subsystems (dream scheduler, Hebbian router, gossip protocol) would print over the interactive prompt, making the shell unusable. Log level is restored to the configured level when the shell exits.

### AD-126: Capability-gap detection via regex heuristic

`is_capability_gap()` in `decomposer.py` uses a compiled regex (`_CAPABILITY_GAP_RE`) to detect LLM responses that indicate a missing capability rather than a genuine conversational reply. Phrases like "I don't have", "no capability", "not equipped", "unable to", "beyond my current capabilities" trigger self-modification. This fixes a regression where capability-gap responses blocked self-mod because the `response` field was non-empty (AD-112 originally gated self-mod on empty `response`). The regex has 16 positive and 8 negative test cases to prevent false positives on normal responses.

### AD-127: Strategy proposals with reversibility preference

`StrategyRecommender` analyzes unhandled intents and proposes strategies with confidence scores. Two strategies: `new_agent` (always available, creates dedicated agent with probationary trust) and `add_skill` (adds modular handler to existing SkillBasedAgent — more reversible, preferred when keyword overlap exists). The `add_skill` strategy gets a `_REVERSIBILITY_BONUS = 0.1` boost reflecting the Reversibility Preference axiom — skills can be removed without destroying a pool. The renderer displays a numbered strategy menu instead of a simple y/n prompt, letting users choose their preferred approach.

### AD-128: Skill type and SkillBasedAgent architecture

The `Skill` dataclass (in `types.py`) encapsulates a modular intent handler: name, `IntentDescriptor`, source code, compiled async handler callable, creation timestamp, and origin. `SkillBasedAgent` is a general-purpose agent that dispatches intents to attached `Skill` objects. Critical implementation: `add_skill()` updates BOTH instance-level AND class-level `_handled_intents` and `intent_descriptors`, ensuring that `_collect_intent_descriptors()` (which reads class-level descriptors from `spawner._templates`) discovers new skills without requiring a template re-registration. `SkillDesigner` generates async handler functions (not full agent classes) via LLM, and `SkillValidator` performs the same static analysis checks as `CodeValidator` but validates function-level schema (async def handle_{name}) instead of class-level schema.

### AD-129: Skills pool conditional spawning

The `skills` ResourcePool (2 SkillBasedAgents with `llm_client` injection) is only created when `config.self_mod.enabled=True`. This prevents unnecessary agent spawning in systems without self-modification capability. The pipeline's `handle_add_skill()` method orchestrates: design → validate → compile (importlib) → create Skill → `add_skill_fn` callback → record with `strategy="skill"`. The `add_skill_fn` iterates `pool.healthy_agents` to inject the skill into all pool members and refreshes decomposer descriptors.

### AD-130: Web research with domain whitelist security

`ResearchPhase` adds optional pre-design documentation research. Security model: (1) Search queries generated by LLM, (2) URLs constructed via `urllib.parse.urlencode()` — never raw string concatenation — for whitelisted domains only (`docs.python.org`, `pypi.org`, `developer.mozilla.org`, `learn.microsoft.com`), (3) Page fetching goes through the mesh's `http_fetch` intent with consensus, (4) Fetched content truncated to `research_max_content_per_page` chars before LLM processing, (5) Research output is context for code generation only — never executed directly — all generated code still passes through `CodeValidator` + `SandboxRunner`. Config fields: `research_enabled`, `research_domain_whitelist`, `research_max_pages`, `research_max_content_per_page`.

### AD-131: Research integration in self-modification pipeline

Research context is injected into both `AGENT_DESIGN_PROMPT` and `SKILL_DESIGN_PROMPT` via a `{research_context}` template variable. When `config.self_mod.research_enabled=True` and a `ResearchPhase` instance is available, `handle_unhandled_intent()` runs research before the design step. Research failures are caught and logged — they never block design (fallback: "No research available."). The design prompt instructs: "Use the above research to inform your implementation. If research context says 'No research available.', rely on your training knowledge." This makes research a best-effort enhancement, not a required dependency.

### AD-132: Per-tier endpoint config with shared fallback

Each LLM tier (fast/standard/deep) can override `base_url`, `api_key`, and `timeout` independently. When not specified (value is `None`), each falls back to the shared `llm_base_url`, `llm_api_key`, and `llm_timeout_seconds`. This is fully backward compatible — existing configs with only shared values produce identical behavior. The `tier_config(tier)` helper method on `CognitiveConfig` returns a resolved dict `{"base_url", "api_key", "model", "timeout"}` for any tier. The user's setup: fast=`qwen3.5:35b` at Ollama `localhost:11434` (no auth), standard=`claude-sonnet-4.6` at Copilot proxy `localhost:8080`, deep=`claude-opus-4.6` at Copilot proxy.

### AD-133: httpx client deduplication by base_url

`OpenAICompatibleClient` creates one `httpx.AsyncClient` per unique `base_url`, not per tier. If standard and deep share the same endpoint (as in the user's setup), they share the same connection pool. This avoids duplicate connection pools and redundant connectivity checks. The deduplication key is the URL string. Each client gets its own `Authorization` header at construction time — if `api_key` is empty, the header is omitted entirely (handles Ollama's no-auth model cleanly without a special flag — AD-135).

### AD-134: Per-tier connectivity at boot

`check_connectivity()` returns `dict[str, bool]` instead of a single `bool`. Each unique endpoint is checked independently — shared endpoints are checked once and the result reused for all tiers pointing to that URL. Boot sequence: if ALL tiers unreachable → fall back to `MockLLMClient`; if SOME tiers unreachable → warn but continue with `OpenAICompatibleClient` (partial connectivity). The `_check_endpoint()` method sends a minimal completion request with a 5-second timeout.

### AD-135: Empty api_key means no Authorization header

When `api_key` is empty string, the `Authorization` header is omitted from the `httpx.AsyncClient` headers entirely. This handles Ollama (no auth) and other local endpoints cleanly without a separate "no auth" flag. The `/model` command shows per-tier endpoint info with shared-endpoint notes when multiple tiers use the same URL (e.g., "shared with standard"). The `/tier` command now displays the endpoint URL on switch.

### AD-136: Response cache keyed by (tier, prompt_hash)

The response cache is shared across tiers but qualified by tier name: `f"{tier}:{hash(prompt)}"`. A cached response from the fast tier won't be served for a standard-tier request, since different models produce different outputs. Previously the cache was keyed by `(model, prompt_hash)` — the tier-based key is semantically equivalent but more explicit about the routing intent.

### AD-137: Configurable default LLM tier

All cognitive components (decomposer, escalation, agent designer, skill designer) previously hardcoded `tier="standard"` in their `LLMRequest` construction. This meant requests always went to the Copilot proxy regardless of what `default_tier` was set to on the LLM client. Fixed by: (1) adding `default_llm_tier: str = "fast"` to `CognitiveConfig`, (2) having `OpenAICompatibleClient` read `default_tier` from `config.default_llm_tier` when a config is provided, (3) changing all hardcoded `tier="standard"` to `tier=None` — the LLM client resolves `None` to `self.default_tier`. Intentional `tier="fast"` usages in `ResearchPhase` and `runtime._extract_unhandled_intent()` are left as-is since they are explicitly choosing the lightweight tier for specific tasks. The `/tier` command still overrides the default at runtime.

### AD-138: Debug panel shows tier and model

The debug panel (enabled with `/debug on`) previously showed `"DEBUG: Raw LLM Response"` with no indication of which tier or model was used. Added `last_tier` and `last_model` tracking on the decomposer (populated from `LLMResponse.tier` and `.model` after each LLM call). The debug panel title now reads `"DEBUG: Raw LLM Response  fast / qwen3.5:35b"`. Also fixed `LLMResponse.tier` in `_call_api()` to store the resolved tier (`request.tier or self.default_tier`) instead of the raw request tier (which could be `None`).

### AD-139 – AD-141: Self-mod routing fixes

Prompt rules to route capability-gap requests through self-mod instead of answering inline (AD-139). Structured `capability_gap` boolean field in decomposer output (AD-140). `<think>` tag stripping from qwen LLM responses (AD-141). Unicode apostrophe regex fix and JSON code-fence stripping in `_extract_unhandled_intent`.

### AD-142: Self-mod pipeline end-to-end fix

Three issues prevented the self-mod pipeline from completing:

1. **Token budget in `_extract_unhandled_intent`:** `max_tokens=256` was too small — qwen3.5 used all tokens in the `reasoning` response field (separate from `content`), content was empty, `finish_reason: 'length'`. Bumped to `max_tokens=2048` with `/no_think` prefix.

2. **LLM client reasoning fallback:** When qwen returns `content=''` but has a `reasoning` field in the OpenAI-compatible response, the client now falls back to the reasoning content. Prevents silent empty responses from reasoning-heavy models.

3. **Agent/skill designer tier routing:** `tier=None` resolved to "fast" (qwen3.5:35b), which timed out generating agent code at 30s. Changed agent_designer and skill_designer to `tier="standard"` (Claude) — faster, no reasoning overhead, better code quality. Added `max_tokens=4096` for complete agent output. Added `<think>` tag stripping on designer output.

Also bumped `llm_timeout_fast` from 15→30s in system.yaml.

Verified end-to-end: "translate hello into japanese" → capability_gap → extract intent → design TranslateTextAgent (Claude) → validate → sandbox → register → re-decompose → execute → こんにちは. 754/754 tests passing.

---

### AD-143: Live LLM integration tests

Added `tests/test_live_llm.py` with 11 tests across 5 classes that exercise the full stack against real LLM backends (Ollama + Copilot proxy). Tests are marked `@pytest.mark.live_llm` and skipped by default — run explicitly with `pytest -m live_llm`.

**Test classes:**
- `TestRawLLMResponse` — fast/standard tier connectivity and content
- `TestDecomposerLive` — read_file decomposition, capability_gap detection, conversational filtering, multi-intent DAGs, think-tag survival
- `TestExtractUnhandledIntentLive` — translation/summarization intent extraction
- `TestAgentDesignerLive` — agent code generation + validation
- `TestFullPipelineLive` — end-to-end self-mod: NL input → gap detection → design → execute

**Infrastructure:**
- `conftest.py`: `pytest_collection_modifyitems` hook auto-skips `live_llm` tests unless `-m live_llm` is passed
- `pyproject.toml`: registered `live_llm` marker in `[tool.pytest.ini_options]`
- Connectivity-based skip decorators (`skip_no_ollama`, `skip_no_proxy`) for graceful degradation when backends are down

754/754 tests passing, 11 live_llm tests skipped by default.

---

### AD-144: Fast→standard tier-fallback for intent extraction

Fixed `test_extract_summarize_intent` live LLM test failure. Root cause: qwen puts all tokens into the `reasoning` field (not `content`) for "summarize" prompts when thinking mode is active — the `/no_think` directive and Ollama API `think: false` option are unreliable via OpenAI-compatible endpoint.

**Fix:** `_extract_unhandled_intent()` in `runtime.py` now cascades fast→standard tier on parse failure: if fast tier returns unparseable JSON, retries on standard tier (Claude) before giving up.

754/754 tests + 11/11 live LLM tests passing.

---

### AD-145: Native Ollama API format + dynamic capability-gap examples

Two-part fix that eliminates thinking-mode interference for the fast tier (qwen via Ollama) and resolves a prompt conflict that broke the self-mod pipeline.

**Part 1 — Per-tier API format (`config.py`, `llm_client.py`, `system.yaml`):**
- Added `llm_api_format_fast/standard/deep` fields to `CognitiveConfig` — values: `"ollama"` or `"openai"` (default)
- `tier_config()` returns `api_format` per tier
- Refactored `OpenAICompatibleClient` with dual API path: `_call_openai()` (existing chat/completions) and `_call_ollama_native()` (posts to `/api/chat` with `stream: False, think: False`)
- Client dedup key changed from `url` to `url|api_format` to support same-host setups
- `system.yaml` fast tier updated: `llm_base_url_fast: "http://127.0.0.1:11434"` + `llm_api_format_fast: "ollama"`
- 25+ regression tests across 8 test classes in `test_llm_client.py`

**Part 2 — Dynamic capability-gap examples (`prompt_builder.py`):**
- Hardcoded examples showed `"translate 'hello world' to French" → capability_gap: true` unconditionally, even when `translate_text` was in the intents table (added by self-mod)
- With thinking disabled (native Ollama API), qwen follows examples literally instead of reasoning against the intents table
- Fix: capability-gap examples are now conditionally included — suppressed when a matching intent exists in the descriptors list
- `_GAP_EXAMPLES` list with keyword matching, `_build_examples()` method filters based on registered intent names
- 6 new tests in `TestCapabilityGapExamples` class in `test_prompt_builder.py`

**Result:** `test_extract_summarize_intent` passes (was the AD-144 driver — native API eliminates thinking overhead entirely). `test_self_mod_creates_and_executes_agent` passes (dynamic examples prevent prompt conflict after self-mod adds translate_text).

784/784 tests + 11/11 live LLM tests passing.

### AD-146: Agent designer mesh access for external data tasks

Designed agents were answering factual/knowledge questions from LLM training data instead of searching the web. Root cause: the `AGENT_DESIGN_PROMPT` only showed `self._llm_client` for "intelligence tasks" and never explained how to dispatch sub-intents through the mesh to reach `HttpFetchAgent`.

**Agent designer prompt (`agent_designer.py`):**
- Split `LLM ACCESS` section into two: `LLM ACCESS (for inference)` and `MESH ACCESS (for external data)`
- `MESH ACCESS` section shows `self._runtime.intent_bus.broadcast()` pattern with `http_fetch` example, then optional LLM synthesis of fetched content
- Updated RULES: separated INFERENCE tasks (→ `self._llm_client`) from EXTERNAL DATA tasks (→ mesh → http_fetch → optional LLM synthesis)
- Added rule: "NEVER use `self._llm_client` alone to answer factual/knowledge questions — it has no internet access and will hallucinate"

**Decomposer prompt (`prompt_builder.py`):**
- Added knowledge-lookup to `_GAP_EXAMPLES`: `("who is Alan Turing?", ..., "lookup")` — suppressed when a `lookup*` intent exists
- Updated `_build_rules()`: both the general fallback rule and the intelligence-task rule now explicitly mention knowledge/factual questions as capability gaps, with `capability_gap: true` in the response format and a warning against answering from training data

**Tests (`test_prompt_builder.py`):**
- `test_lookup_gap_present_without_matching_intent` — knowledge-lookup gap example appears by default
- `test_lookup_gap_suppressed_when_lookup_intent_exists` — suppressed when `lookup_info` intent registered
- `test_all_gaps_suppressed_when_all_intents_exist` — all 3 gap examples suppressed together

787/787 tests + 8/8 live LLM tests passing (3 skipped — Copilot proxy not running).

### AD-147: Runtime injection for designed agent pools

Designed agents had `self._runtime = None` at runtime because `_create_designed_pool()` passed `llm_client=self.llm_client` but not `runtime=self`. Without runtime, the agent's mesh dispatch (`self._runtime.intent_bus.broadcast()`) hit the sandbox fallback path and returned placeholder results instead of fetching from the web.

**Fix (`runtime.py`):**
- `_create_designed_pool()` now passes `runtime=self` alongside `llm_client=self.llm_client`
- Matches the pattern used by the introspection pool: `create_pool(..., runtime=self)`

787/787 tests passing.

### AD-148: HttpFetchAgent User-Agent header + DuckDuckGo search strategy

Designed agents dispatching `http_fetch` sub-intents got 403 responses from Wikipedia and other sites because httpx's default User-Agent is blocked. Also, the agent designer prompt only showed a Wikipedia API example, which doesn't work for general person/topic lookups.

**HttpFetchAgent (`http_fetch.py`):**
- Added `USER_AGENT = "ProbOS/0.1.0 (https://github.com/seangalliher/ProbOS)"` constant
- `_fetch_url()` now creates httpx client with User-Agent header and `follow_redirects=True`

**Agent designer prompt (`agent_designer.py`):**
- Added DuckDuckGo HTML search pattern as the primary web search example: `https://html.duckduckgo.com/html/?q={query}` with `urllib.parse.quote_plus()`
- Wikipedia REST API kept as secondary example for known topics
- Clearer separation: "GENERAL WEB SEARCH" vs "KNOWN TOPICS"

787/787 tests passing.

---

### AD-149: DAG execution timeout excludes user-wait during escalation

When consensus is INSUFFICIENT and escalation reaches Tier 3 (user consultation), the interactive prompt blocks the DAG coroutine. The 60-second `dag_execution_timeout_seconds` counted this user-wait time against the deadline, causing timeouts even when the user promptly approved.

**Root cause:** `asyncio.wait_for(coro, timeout=60)` sets a fixed deadline at call time. User-wait time accumulates *during* execution and cannot retroactively extend the deadline.

**EscalationManager (`escalation.py`):**
- Added `user_wait_seconds: float` accumulator, reset per `execute()` call
- `_tier3_user()` wraps the `user_callback` call with `time.monotonic()` timing — seconds spent waiting for the user are recorded but excluded from the effective elapsed time

**DAGExecutor (`decomposer.py`):**
- Replaced `asyncio.wait_for` with direct `await _execute_dag()` — individual nodes already have their own 10s timeouts via `submit_intent(timeout=10.0)`
- Added `_effective_elapsed()` helper: `(wall_clock - user_wait_seconds)` — the time the *system* has been working, excluding user interaction
- Deadline check runs between batches in `_execute_dag()`: if effective elapsed exceeds `self.timeout`, raises `asyncio.TimeoutError`
- `_dag_start` timestamp set at top of `execute()` for accurate measurement

**Tests (3 new):**
- `test_user_wait_excluded_from_deadline` — simulates 2s user-wait with 3s timeout; effective elapsed (~0.5s) is within budget
- `test_genuine_timeout_still_fires` — multi-batch DAG where first batch exceeds timeout; deadline check fires before second batch
- `test_user_wait_seconds_reset_each_execute` — verifies accumulator is reset between executions

790/790 tests passing.

---

### AD-150: http_fetch non-consensus + pool scaling consensus floor

Read-only HTTP GET requests were gated by consensus (`requires_consensus=True`), but the `http_fetch` pool at `target_size=3` could be scaled down below `min_votes=3` by the PoolScaler, causing structural INSUFFICIENT consensus. More fundamentally, 2-agent consensus is meaningless (unanimous or tie — neither useful), and GET requests are non-destructive reads already protected by red team URL verification.

**Two-part fix:**

**http_fetch non-consensus (`http_fetch.py`, `runtime.py`):**
- `IntentDescriptor.requires_consensus` changed from `True` to `False`
- Removed `"http_fetch"` from `consensus_intents` set in `_validate_remote_result()`
- Updated docstrings: "Read-only: GET requests are non-destructive" (was "Medium-risk: all requests go through consensus")

**Pool scaling consensus floor (`scaler.py`, `runtime.py`):**
- `PoolScaler.__init__` accepts `consensus_pools: set[str]` and `consensus_min_agents: int` (defaults to 3)
- `_scale_down()` refuses to remove agents from consensus pools when `current_size <= consensus_min_agents`
- `scale_down_idle()` same floor check — idle dreaming can't starve consensus pools
- Runtime computes `consensus_pools` via new `_find_consensus_pools()` method (iterates spawner templates, returns pool names whose agents declare `requires_consensus=True`)
- Passes `consensus_pools` and `consensus_min_agents=config.consensus.min_votes` to PoolScaler

**Tests:**
- Updated `test_prompt_builder.py`: moved `http_fetch` from consensus-true to consensus-false assertions
- Updated `test_expansion_agents.py`: http_fetch test docstring reflects non-consensus
- 3 new tests in `test_scaling.py` (`TestPoolScalerConsensusFloor`):
  - Scale-down blocked by consensus floor
  - Idle scale-down blocked by consensus floor
  - Non-consensus pool still scales below floor (only `min_size` applies)

793/793 tests passing.

---

### AD-151: http_fetch few-shot examples still showed use_consensus: true + red team timeout mismatch

AD-150 changed `http_fetch.requires_consensus` to `False` and updated the dynamic `_build_rules()` output, but the **few-shot examples** in both `PROMPT_EXAMPLES` (prompt_builder.py) and `_LEGACY_SYSTEM_PROMPT` (decomposer.py) still showed `"use_consensus": true` for all 3 http_fetch examples. The LLM followed the examples over the rules, emitting `use_consensus: true` and routing through the full consensus + red team verification path.

Additionally, the red team's `_verify_http_fetch` used `httpx.AsyncClient(timeout=15.0)` but the runtime wrapped verification in `asyncio.wait_for(..., timeout=5.0)`. The httpx timeout exceeded the verification timeout, so `asyncio.wait_for` killed the coroutine mid-request instead of httpx returning a clean `TimeoutException`.

**Prompt fixes (`prompt_builder.py`, `decomposer.py`):**
- Changed 3 http_fetch few-shot examples from `"use_consensus": true` to `false` in `PROMPT_EXAMPLES`
- Same 3 examples updated in `_LEGACY_SYSTEM_PROMPT`
- Updated "what can you do?" response: "Writes and commands go through consensus verification" (was "Writes, commands, and HTTP requests")
- Fixed legacy prompt rule numbering (removed dedicated http_fetch consensus rule, merged into non-consensus group)

**Red team timeout fix (`red_team.py`):**
- `_verify_http_fetch` httpx timeout: 15.0s → 4.0s (fits within 5.0s `verification_timeout_seconds`)
- httpx now times out cleanly before `asyncio.wait_for`, producing a proper `TimeoutException` caught by the existing handler instead of a raw coroutine cancellation

793/793 tests passing.

### AD-152: Non-consensus node status + http_fetch timeout alignment + regression tests

**Root cause:** Two bugs caused http_fetch to show "✓ done" while the reflector reported "unable to retrieve":

1. `HttpFetchAgent.DEFAULT_TIMEOUT = 15.0s` exceeded the DAG executor broadcast timeout of `10.0s`. When the target site was slow, `asyncio.wait(tasks, timeout=10.0)` cancelled the httpx request before it completed, producing empty results.
2. The non-consensus path in `_execute_node()` unconditionally set `node.status = "completed"` regardless of whether any result succeeded. Failed tasks appeared as completed, confusing the reflector.

**Fixes:**

- `http_fetch.py`: `DEFAULT_TIMEOUT` 15.0 → 8.0 (fits within 10s broadcast window)
- `decomposer.py`: Non-consensus path now sets `node.status = "completed" if success else "failed"` based on `any(r.success for r in intent_results)`
- `decomposer.py`: Added `node_failed` event emission for failed non-consensus nodes (mirrors existing `node_complete` event)

**Regression tests (`tests/test_ad152_regressions.py` — 27 tests):**

| Class | Tests | What it guards |
|-------|-------|----------------|
| `TestTimeoutAlignment` | 3 | http_fetch timeout < broadcast timeout, red team httpx < verification timeout |
| `TestPromptConsistency` | 5 | Few-shot examples match `requires_consensus`, dynamic rules correct |
| `TestNonConsensusResultFormat` | 4 | Result dict structure, empty/failed/mixed results |
| `TestNodeStatusReflectsSuccess` | 5 | Node.status based on success, event emission for completed/failed |
| `TestSummarizeHttpFetchResult` | 5 | `_summarize_node_result` with http_fetch data variants |
| `TestHttpFetchNonConsensus` | 3 | Descriptor check, runtime pool mapping, consensus_intents exclusion |
| `TestDependencyFailurePropagation` | 1 | Failed node causes dependent nodes to fail |
| `TestHttpFetchTimeoutMessage` | 1 | Timeout error message reflects actual DEFAULT_TIMEOUT |

820/820 tests passing (+ 11 skipped).

---

### AD-153 through AD-158: Phase 13 — SystemQAAgent

**SystemQAAgent** is a meta-agent that smoke-tests newly designed agents after self-modification. When the self-mod pipeline successfully creates a new agent, SystemQAAgent generates synthetic test intents from the agent's intent metadata, dispatches them, validates the results, and updates the trust network. The system tests itself as it evolves.

**Architecture decisions:**

| AD | Decision |
|----|----------|
| AD-153 | Single-agent QA pool — intentional exception to Design Principle #1 (no single points of failure). QA is a singleton testing tool, not a mission-critical service. Pool excluded from demand-driven scaling |
| AD-154 | Non-blocking QA via `asyncio.create_task()`. Full error containment: try/except in task body, `qa_error` event logged on failure, never crashes the runtime |
| AD-155 | Trust weight asymmetry: `trust_penalty_weight=2.0` > `trust_reward_weight=1.0`. Failing agents lose trust faster than passing agents gain it, creating conservative self-correction |
| AD-156 | Param type inference from key name heuristics, not description string parsing. Key names like "url", "path", "count", "flag" map to typed synthetic values (URLs, file paths, integers, booleans) |
| AD-157 | Dual storage: `runtime._qa_reports` (typed dict, fast) for `/qa` command, episodic memory (durable) for decomposer context. Avoids fragile string-matching on `[SystemQA]` prefixes |
| AD-158 | QA pool excluded from user-facing routing: `smoke_test_agent` descriptor excluded from decomposer, pool excluded from scaler. `_EXCLUDED_AGENT_TYPES = {"red_team", "system_qa"}` |

**Files changed/created:**

| File | Change |
|------|--------|
| `src/probos/config.py` | Added `QAConfig` class, `qa: QAConfig = QAConfig()` to SystemConfig, None-section filtering in `load_config()` |
| `config/system.yaml` | Added `qa:` section with commented defaults |
| `src/probos/agents/system_qa.py` | **New.** `QAReport` dataclass, `SystemQAAgent` with `generate_synthetic_intents()`, `validate_result()`, `run_smoke_tests()`, `_infer_param_type()` heuristics |
| `src/probos/runtime.py` | QA pool creation, `_run_qa_for_designed_agent()` with trust+episodic+eventlog+flagging+auto-remove, `_EXCLUDED_AGENT_TYPES` set, QA in `status()` |
| `src/probos/experience/qa_panel.py` | **New.** `render_qa_panel()` summary table, `render_qa_detail()` per-agent breakdown |
| `src/probos/experience/panels.py` | `render_designed_panel()` — optional `qa_reports` parameter, QA column with verdict styling |
| `src/probos/experience/shell.py` | `/qa` command registration and handler, `/designed` passes qa_reports |
| `tests/test_system_qa.py` | **New.** 72 tests across 16 test classes covering all AD-153–AD-158 requirements |

892/892 tests passing (+ 11 skipped).

---

### Phase 14 — Persistent Knowledge Store (AD-159 through AD-169)

Git-backed persistence layer that survives restarts. All system artifacts (episodes, designed agents, skills, trust scores, routing weights, workflow cache entries, QA reports) are stored as human-readable JSON/Python files in a local Git repository. Enables warm boot (restore state from previous session), per-artifact rollback via Git history, and versioned audit trail of all system evolution.

**Key design decisions (AD numbers):**

| AD | Decision |
|----|----------|
| AD-159 | Late Git init: Git repo created on first write, not at boot. Avoids empty repos. meta.json with schema_version and probos_version (AD-169) |
| AD-160 | Human-readable artifacts: JSON for data, .py for agent/skill source. No binary formats |
| AD-161 | Debounced commits: `asyncio.TimerHandle` batches writes within configurable window. `_flushing` race guard prevents double-commit during shutdown |
| AD-162 | Warm boot restore order: trust → routing → agents → skills → episodes → workflows → QA. Each step independent with try/except |
| AD-163 | Validated restoration: `CodeValidator.validate()` on restored .py files before importlib loading. Corrupted/malicious agents rejected at boot |
| AD-164 | Per-artifact rollback: `git log --follow` + `git show` to retrieve previous version, creates new commit (non-destructive) |
| AD-165 | `--fresh` flag: Sets `restore_on_boot=False`. Does NOT delete the repo — new writes still persist. Previous data preserved for future warm boots |
| AD-166 | Thread executor for Git: All git subprocess calls via `asyncio.get_running_loop().run_in_executor()` — never blocks event loop |
| AD-167 | Optional infrastructure: System falls back to current behavior if knowledge disabled or git unavailable |
| AD-168 | Raw Beta parameters: Trust snapshots capture `(alpha, beta)` not derived `mean()` scores. Preserves full distribution information |
| AD-169 | Repo metadata: `meta.json` with `schema_version`, `probos_version`, `created` timestamp |

**Resolved (AD-162 → AD-177/AD-181):** Warm boot previously orphaned trust records and Hebbian weights because `BaseAgent.__init__` generated a new `uuid4()` on every instantiation. Fixed in Phase 14c: agents now have deterministic IDs derived from `hash(agent_type, pool_name, instance_index)` (AD-177), and warm boot only sets probationary trust for agents NOT found in the trust snapshot (AD-181). Agents that earned high trust retain it across restarts.

**Files changed/created:**

| File | Change |
|------|--------|
| `src/probos/config.py` | Added `KnowledgeConfig` class (enabled, repo_path, auto_commit, commit_debounce_seconds, max_episodes, max_workflows, restore_on_boot), `knowledge: KnowledgeConfig` to SystemConfig |
| `config/system.yaml` | Added `knowledge:` section with commented defaults |
| `src/probos/knowledge/__init__.py` | **New.** Package root with KnowledgeStore re-export |
| `src/probos/knowledge/store.py` | **New.** Full KnowledgeStore implementation (~430 lines): initialize(), store/load for all 7 artifact types, git init on first write, debounced commits, flush with race guard, rollback, artifact_history, thread executor for git ops |
| `src/probos/cognitive/episodic.py` | Added `seed()` — bulk restore episodes preserving original IDs via INSERT OR IGNORE |
| `src/probos/cognitive/episodic_mock.py` | Added `seed()` — in-memory bulk restore for tests |
| `src/probos/cognitive/workflow_cache.py` | Added `export_all()` — returns list of serializable dicts for shutdown persistence |
| `src/probos/consensus/trust.py` | Added `raw_scores()` — returns {agent_id: {alpha, beta, observations}} for persistence |
| `src/probos/runtime.py` | KnowledgeStore init in start(), `_restore_from_knowledge()` warm boot, episode/agent/skill/QA persistence hooks with try/except guards, shutdown flush (trust+routing+workflows+flush()), knowledge status in `status()`, default repo_path from data_dir |
| `src/probos/__main__.py` | Added `--fresh` CLI flag that sets `restore_on_boot=False` |
| `src/probos/experience/knowledge_panel.py` | **New.** `render_knowledge_panel()` — artifact count table, `render_knowledge_history()` — commit log, `render_rollback_result()` — success/failure panel |
| `src/probos/experience/shell.py` | `/knowledge` and `/rollback` commands with handlers |
| `tests/test_knowledge_store.py` | **New.** 91 tests across 12 test classes covering all AD-159–AD-169 requirements |
| `tests/test_experience.py` | Fixed `test_no_episode_for_empty_dag` — filter out SystemQA background episodes |

983/983 tests passing (+ 11 skipped).

### Phase 14b — ChromaDB Semantic Recall (AD-170 through AD-176)

Replaced keyword-overlap bag-of-words similarity with real embedding-based semantic search across four subsystems: EpisodicMemory, WorkflowCache, CapabilityRegistry, and StrategyRecommender. ChromaDB runs embedded (no external server) using ONNX MiniLM embeddings. "Find past tasks about deployment" now matches "push to production" — the system understands meaning, not just words.

**Key design decisions (AD numbers):**

| AD | Decision |
|----|----------|
| AD-170 | Shared embedding utility: lazy singleton `get_embedding_function()` wrapping ChromaDB's DefaultEmbeddingFunction (ONNX MiniLM). Graceful fallback to keyword-overlap bag-of-words when ONNX unavailable |
| AD-171 | EpisodicMemory backend swap: SQLite → ChromaDB PersistentClient. Same interface (`store`, `recall`, `recall_by_intent`, `recent`, `get_stats`, `seed`). Callers unchanged. Complex metadata (dicts, lists) serialized to JSON strings for ChromaDB metadata constraints |
| AD-172 | Two-tier persistence: ChromaDB is hot-path retrieval engine, Git KnowledgeStore is long-term persistence. On warm boot, `seed()` loads episodes from Git into ChromaDB |
| AD-173 | WorkflowCache semantic fuzzy matching: `compute_similarity()` replaces keyword overlap ratio. Intent subset check stays. Configurable `similarity_threshold` parameter (default 0.6) |
| AD-174 | CapabilityRegistry semantic tier: exact match → substring → **semantic** → keyword. Semantic tier uses `compute_similarity()` with 0.5 threshold. `semantic_matching: bool` config flag for feature toggle |
| AD-175 | StrategyRecommender semantic scoring: `compute_similarity()` replaces Jaccard keyword overlap for intent-descriptor comparison. Higher similarity → higher add_skill confidence. Fallback to keyword overlap |
| AD-176 | MockEpisodicMemory unchanged: tests stay deterministic and fast with keyword matching, no ChromaDB dependency |

**Files changed/created:**

| File | Change |
|------|--------|
| `pyproject.toml` | Added `chromadb>=1.0` dependency |
| `src/probos/cognitive/embeddings.py` | **New.** Shared embedding utility: `get_embedding_function()`, `embed_text()`, `compute_similarity()`, keyword-overlap fallback (`_keyword_embedding`, `_keyword_similarity`, `_tokenize`) |
| `src/probos/cognitive/episodic.py` | Rewritten: SQLite → ChromaDB PersistentClient. `_episode_to_metadata()` / `_metadata_to_episode()` for JSON-serialized complex fields. Cosine distance → similarity conversion |
| `src/probos/cognitive/workflow_cache.py` | `lookup_fuzzy()` uses `compute_similarity()` instead of keyword overlap ratio. Added `similarity_threshold` parameter |
| `src/probos/mesh/capability.py` | `_score_match()` adds semantic tier between substring and keyword. `semantic_matching` constructor parameter |
| `src/probos/cognitive/strategy.py` | `_compute_overlap()` replaces `_keyword_overlap()` with `compute_similarity()` + keyword fallback |
| `src/probos/config.py` | Added `similarity_threshold: float = 0.6` to `MemoryConfig`, `semantic_matching: bool = True` to `MeshConfig` |
| `config/system.yaml` | Added commented `similarity_threshold` to memory section, `semantic_matching` to mesh section |
| `src/probos/__main__.py` | Passes `relevance_threshold` from config to EpisodicMemory |
| `src/probos/runtime.py` | Passes `semantic_matching` config to CapabilityRegistry |
| `tests/test_embeddings.py` | **New.** 7 tests: embedding function callable, embed_text returns floats, cosine similarity, semantic ordering, empty text, fallback |
| `tests/test_episodic_chromadb.py` | **New.** 11 tests: store/recall, ranked results, semantic deployment match, intent filter, recent ordering, stats, eviction, seed, dedup, round-trip, empty collection |
| `tests/test_episodic.py` | Updated imports: `_keyword_embedding`/`_keyword_similarity` from `embeddings.py`. Renamed `TestEpisodicMemorySQLite` → `TestEpisodicMemoryChromaDBLegacy` |
| `tests/test_workflow_cache.py` | Updated fuzzy test for semantic similarity. Added `test_fuzzy_lookup_semantic_deploy_matches_production` |
| `tests/test_capability.py` | Added `test_semantic_match_open_file_finds_read_document`, `test_semantic_matching_disabled` |
| `tests/test_strategy.py` | Added `test_semantic_similarity_higher_confidence_for_similar_intents` |
| `tests/test_knowledge_store.py` | Added `TestChromaDBKnowledgeIntegration`: episode persist → Git → seed → ChromaDB recall, warm boot integration |

1007/1007 tests passing (+ 11 skipped). 24 new tests.

### Phase 14c — Persistent Agent Identity (AD-177 through AD-184)

Agents are now persistent individuals that survive restarts. Previously, every agent got a random UUID on each instantiation — all earned trust, Hebbian routing weights, and confidence history was orphaned on restart. Now agents have deterministic IDs derived from deployment topology (`hash(agent_type, pool_name, instance_index)`), and the full agent roster is persisted as a Git-backed manifest in the KnowledgeStore. Warm boot reconnects trust and routing data to the correct agents automatically. Pruning permanently removes an individual — its ID is never recycled.

**Key design decisions (AD numbers):**

| AD | Decision |
|----|----------|
| AD-177 | Deterministic agent IDs: `generate_agent_id(agent_type, pool_name, instance_index)` → `{type}_{pool}_{index}_{sha256[:8]}`. Same inputs always produce the same ID. Human-readable with collision-resistant hash suffix |
| AD-178 | `agent_id` kwarg is optional everywhere — `BaseAgent.__init__` falls back to `uuid.uuid4().hex` if not provided. All 1008 pre-existing tests pass without modification |
| AD-179 | Recycle preserves identity: `AgentSpawner.recycle()` passes the original `agent_id` to the replacement. The individual persists through recycling — same trust, same routing, same ID |
| AD-180 | Agent manifest persisted in KnowledgeStore as `manifest.json` — Git-backed artifact recording `{agent_id, agent_type, pool_name, instance_index, skills_attached}` for every agent. Persisted at end of `start()` and in `stop()` |
| AD-181 | Warm boot trust reconnection: `_restore_from_knowledge()` only sets probationary trust for agents NOT found in the trust snapshot. Agents with restored trust records keep their earned trust instead of being demoted |
| AD-182 | Pool `_next_instance_index` tracking: replacement agents spawned during health check recovery get deterministic IDs at the next available index, not recycled pruned IDs |
| AD-183 | `prune_agent()` removes from pool, registry, trust network, and Hebbian router. Updated manifest persisted. The pruned ID is permanently retired |
| AD-184 | `--fresh` flag (`restore_on_boot=False`) gives agents deterministic IDs but does not restore trust or routing — clean slate with stable identity |

**Files changed/created:**

| File | Change |
|------|--------|
| `src/probos/substrate/identity.py` | **New.** `generate_agent_id()`, `generate_pool_ids()` — deterministic ID generation from deployment topology |
| `src/probos/substrate/agent.py` | `BaseAgent.__init__` accepts optional `agent_id` kwarg, falls back to `uuid.uuid4().hex` |
| `src/probos/substrate/spawner.py` | `recycle()` preserves agent_id through recycling by forwarding to `spawn()` |
| `src/probos/substrate/pool.py` | Accepts `agent_ids` list for predetermined IDs, tracks `_next_instance_index`, `check_health()` and `add_agent()` generate deterministic IDs |
| `src/probos/substrate/heartbeat.py` | Added `**kwargs` forwarding to `super().__init__()` for `agent_id` support |
| `src/probos/knowledge/store.py` | Added `store_manifest()` and `load_manifest()` for Git-backed agent roster persistence |
| `src/probos/runtime.py` | All built-in pools use `generate_pool_ids()`, designed/skill/red-team pools get deterministic IDs, `_build_manifest()`, `_persist_manifest()`, `prune_agent()`, warm boot only sets probationary trust for new agents |
| `src/probos/experience/shell.py` | Added `/prune <agent_id>` command with confirmation prompt |
| `tests/test_identity.py` | **New.** 15 tests: deterministic generation, format validation, collision resistance, agent_id kwarg, spawner forwarding, pool with predetermined IDs |
| `tests/test_persistent_identity.py` | **New.** 18 tests: manifest persistence (5), warm boot reconnection (6), pruning (6), end-to-end milestone (1) |
| `tests/test_spawner.py` | Updated `test_recycle_with_respawn` — recycle now preserves ID (Phase 14c design) |

1041/1041 tests passing (+ 11 skipped). 33 new tests.

### Phase 14d — Agent Tier Classification & Self-Introspection (AD-185 through AD-190)

Two changes that formalize ProbOS's agent architecture: (1) a `tier` field classifying every agent as `"core"`, `"utility"`, or `"domain"`, replacing the hardcoded `_EXCLUDED_AGENT_TYPES` set with descriptor-based filtering; (2) two new self-introspection intents (`introspect_memory`, `introspect_system`) so ProbOS can accurately report its own state instead of falling through to the LLM.

**Key design decisions (AD numbers):**

| AD | Decision |
|----|----------|
| AD-185 | Three-tier classification: `core` (infrastructure I/O, deterministic tool agents), `utility` (meta-cognitive, system monitoring), `domain` (user-facing cognitive work). Default is `domain` — designed agents automatically get the right tier |
| AD-186 | `_EXCLUDED_AGENT_TYPES` removed entirely. Descriptor collection includes all agents with non-empty `intent_descriptors` regardless of tier. Agents with empty descriptors (heartbeat, red_team, corrupted) are naturally excluded |
| AD-187 | SystemQAAgent `intent_descriptors` set to `[]` — its `smoke_test_agent` intent is internal-only, triggered by the self-mod pipeline, not routed via the intent bus |
| AD-188 | `tier` field added to both `BaseAgent` (class attribute) and `IntentDescriptor` (dataclass field), both defaulting to `"domain"` for backward compatibility |
| AD-189 | `introspect_memory` returns episodic memory stats (episode count, intent distribution, success rate, backend). `introspect_system` returns tier-grouped agent counts, trust summary (mean/min/max), Hebbian weight count, pool health, knowledge store status, dream cycle state |
| AD-190 | Both introspection intents use `requires_reflect=True` — the agent returns structured data, the reflect step synthesizes natural language. The system describes itself through observed state, not LLM confabulation |

**Agent classification:**

| Tier | Agents |
|------|--------|
| core | FileReaderAgent, FileWriterAgent, DirectoryListAgent, FileSearchAgent, ShellCommandAgent, HttpFetchAgent, RedTeamAgent, HeartbeatAgent, SystemHeartbeatAgent, CorruptedFileReaderAgent |
| utility | IntrospectionAgent, SystemQAAgent |
| domain | SkillBasedAgent, all designed agents (default) |

**Files changed/created:**

| File | Change |
|------|--------|
| `src/probos/types.py` | Added `tier: str = "domain"` to `IntentDescriptor` |
| `src/probos/substrate/agent.py` | Added `tier: str = "domain"` class attribute to `BaseAgent` |
| `src/probos/agents/file_reader.py` | `tier = "core"` |
| `src/probos/agents/file_writer.py` | `tier = "core"` |
| `src/probos/agents/directory_list.py` | `tier = "core"` |
| `src/probos/agents/file_search.py` | `tier = "core"` |
| `src/probos/agents/shell_command.py` | `tier = "core"` |
| `src/probos/agents/http_fetch.py` | `tier = "core"` |
| `src/probos/agents/red_team.py` | `tier = "core"` |
| `src/probos/agents/corrupted.py` | `tier = "core"` |
| `src/probos/agents/heartbeat_monitor.py` | `tier = "core"` |
| `src/probos/substrate/heartbeat.py` | `tier = "core"` |
| `src/probos/agents/introspect.py` | `tier = "utility"`, added `introspect_memory` and `introspect_system` intent handlers |
| `src/probos/agents/system_qa.py` | `tier = "utility"`, `intent_descriptors = []` (internal-only) |
| `src/probos/substrate/skill_agent.py` | `tier = "domain"` (explicit) |
| `src/probos/runtime.py` | Removed `_EXCLUDED_AGENT_TYPES`, descriptor collection based on non-empty descriptors, `tier` added to manifest entries |
| `src/probos/experience/panels.py` | Added Tier column to agent table |
| `src/probos/cognitive/llm_client.py` | MockLLMClient patterns for `introspect_memory` and `introspect_system` |
| `tests/test_agent_tiers.py` | **New.** 21 tests: default tier, all agent classifications, descriptor field, manifest tier, panel column, descriptor collection |
| `tests/test_introspection_phase14d.py` | **New.** 11 tests: memory stats, memory disabled, tier counts, trust summary, Hebbian count, knowledge status, descriptor validation, MockLLMClient patterns |
| `tests/test_system_qa.py` | Updated routing exclusion test comments for Phase 14d |
| `tests/test_self_mod.py` | Updated sandbox timeout default assertion (60s) |

1073/1073 tests passing (+ 11 skipped). 32 new tests.

### Phase 15a — CognitiveAgent Base Class (AD-191 through AD-198)

The single biggest architectural change since Phase 3a. Introduces `CognitiveAgent(BaseAgent)` — an agent base class where `decide()` consults an LLM guided by per-agent `instructions`. This brings reasoning *inside* the mesh as a trust-scored, confidence-tracked, recyclable participant rather than concentrating all reasoning in the decomposer. The `AgentDesigner` now generates `CognitiveAgent` subclasses with `instructions` strings (LLM system prompts) instead of procedural `act()` code — the agent reasons at runtime, not at design time.

**Key design decisions (AD numbers):**

| AD | Decision |
|----|----------|
| AD-191 | `CognitiveAgent(BaseAgent)` base class: `decide()` invokes LLM with `instructions` as system prompt + observation as user message. Full perceive/decide/act/report lifecycle preserved. `act()` is the subclass extension point for structured output parsing. `_resolve_tier()` returns `"standard"` by default |
| AD-192 | `instructions: str | None = None` on `BaseAgent` (class attribute). Tool agents ignore it. `CognitiveAgent` requires non-empty instructions — raises `ValueError` otherwise. kwargs override for runtime-provided instructions |
| AD-193 | `AgentDesigner` generates `CognitiveAgent` subclasses. Instructions string is the core design output. Minimal `act()` override for output parsing. No more fully-generated procedural `act()` logic |
| AD-194 | Design prompt rewrite: LLM generates instructions (reasoning prompt) instead of procedural code. The cognitive agent reasons at runtime, not at design time |
| AD-195 | `CodeValidator` accepts `CognitiveAgent` subclasses. Does not require `handle_intent` method when parent provides it. `probos.cognitive.cognitive_agent` in import whitelist |
| AD-196 | `SandboxRunner` discovers and tests `CognitiveAgent` subclasses via existing `BaseAgent` inheritance. `CognitiveAgent` excluded from base-class filter (same as `BaseAgent`) |
| AD-197 | `MockLLMClient` updated: `agent_design` pattern generates `CognitiveAgent` code with `instructions` + `act()` override, new `cognitive_agent_decide` pattern for testing cognitive agent LLM calls |
| AD-198 | Runtime `_create_designed_pool()` works for `CognitiveAgent` via existing kwargs injection (`llm_client`, `runtime`). No API changes needed |

**Files changed / created:**

| File | Change |
|------|--------|
| `src/probos/cognitive/cognitive_agent.py` | **New.** `CognitiveAgent(BaseAgent)` base class with LLM-guided `decide()`, `instructions` field, full lifecycle |
| `src/probos/substrate/agent.py` | Added `instructions: str | None = None` class attribute |
| `src/probos/cognitive/agent_designer.py` | Rewrote `AGENT_DESIGN_PROMPT` for instructions-first CognitiveAgent generation |
| `src/probos/cognitive/code_validator.py` | Accepts `CognitiveAgent` subclasses, `probos.cognitive.cognitive_agent` import, relaxed `handle_intent` requirement for cognitive subclasses |
| `src/probos/cognitive/sandbox.py` | Imports `CognitiveAgent`, excludes it from base-class filter |
| `src/probos/cognitive/llm_client.py` | Updated `agent_design` mock to generate `CognitiveAgent` code, added `cognitive_agent_decide` pattern |
| `tests/test_cognitive_agent.py` | **New.** 24 tests: init validation, lifecycle, formatting, overrides |
| `tests/test_agent_designer_cognitive.py` | **New.** 12 tests: design output, validator, sandbox, end-to-end pipeline |
| `tests/test_self_mod.py` | Updated `CognitiveAgent` assertion in design test |

1109/1109 tests passing (+ 11 skipped). 36 new tests.

### Phase 15b — Domain-Aware Skill Attachment (AD-199 through AD-203)

Wires the skill system so skills are attached to the cognitive agent whose domain best matches the new capability, rather than always to the generic `SkillBasedAgent` dispatcher. This makes skills more effective (the cognitive agent's domain context is semantically adjacent) and more discoverable.

**Key design decisions (AD numbers):**

| AD | Decision |
|----|----------|
| AD-199 | `CognitiveAgent` skill attachment: `add_skill()`/`remove_skill()` following SkillBasedAgent pattern (AD-128). `_skills` dict, instance+class descriptor sync. `handle_intent()` checks skills first, falls through to cognitive lifecycle |
| AD-200 | StrategyRecommender domain-aware scoring: scores cognitive agents' `instructions` against new intent via `compute_similarity()`. Best match above 0.3 threshold becomes `target_agent_type`. Falls back to `skill_agent` |
| AD-201 | StrategyRecommender accepts optional `agent_classes: dict[str, type]` for instructions lookup. Runtime passes registered agent templates via `_get_agent_classes()` |
| AD-202 | Runtime `_add_skill_to_agents()` generalized: accepts `target_agent_type`, searches all pools, falls back to SkillBasedAgent if target type not found. `_get_llm_equipped_types()` includes CognitiveAgent subclasses |
| AD-203 | Strategy menu shows target agent name in label/reason when target is a cognitive agent (display-only: "Add skill to text_analyzer agent" vs "Add skill to existing agent") |

**Files changed / created:**

| File | Change |
|------|--------|
| `src/probos/cognitive/cognitive_agent.py` | Added `add_skill()`, `remove_skill()`, `_skills` dict, skill-first dispatch in `handle_intent()` |
| `src/probos/cognitive/strategy.py` | Added `_find_best_skill_target()`, `_compute_text_similarity()`, `agent_classes` parameter, domain-aware label/reason |
| `src/probos/cognitive/self_mod.py` | Passes `target_agent_type` through `_add_skill_fn` callback |
| `src/probos/runtime.py` | `_add_skill_to_agents()` generalized with `target_agent_type` parameter, `_get_llm_equipped_types()` includes cognitive agents, new `_get_agent_classes()` method |
| `src/probos/experience/renderer.py` | Passes `agent_classes` to StrategyRecommender, shows "domain match" for cognitive target |
| `tests/test_cognitive_agent_skills.py` | **New.** 17 tests: init, add/remove skill, dispatch, lifecycle fallthrough |
| `tests/test_strategy_domain_aware.py` | **New.** 14 tests: domain scoring, threshold, multi-agent, labels, backward compat |
| `tests/test_runtime_skill_routing.py` | **New.** 5 tests: target routing, fallback, equipped types, agent classes |
| `tests/test_skill_agent.py` | Updated mock `add_skill_fn` signatures for `target_agent_type` kwarg |

1145/1145 tests passing (+ 11 skipped). 36 new tests.

### Phase 16 — DAG Proposal Mode (AD-204 through AD-209)

Adds a `/plan <text>` command that decomposes natural language into a TaskDAG without executing it, letting the user inspect, edit, approve, or reject before execution. This completes the human-in-the-loop control surface for ProbOS.

**Key design decisions (AD numbers):**

| AD | Decision |
|----|----------|
| AD-204 | `propose()` reuses `process_natural_language()` decomposition path but stops before execution. Stores result as `_pending_proposal` |
| AD-205 | `execute_proposal()` / `reject_proposal()` / `remove_proposal_node()` — execute, discard, or modify the pending proposal. `_execute_dag()` extracted as shared execution path for both `process_natural_language()` and `execute_proposal()` |
| AD-206 | `render_dag_proposal()` panel: numbered Rich Table with intent, params, dependency indices, consensus flags. Title shows `/approve`, `/reject`, `/plan remove N` hints |
| AD-207 | Shell commands `/plan`, `/approve`, `/reject` wired into `ProbOSShell`. `/plan` handles three forms: `/plan <text>` (propose), `/plan` (re-display), `/plan remove N` (edit) |
| AD-208 | `/plan <text>` delegates self-mod gap detection to existing flow. `/approve` uses renderer event tracking for progress display |
| AD-209 | Event log entries: `proposal_created`, `proposal_approved`, `proposal_rejected`, `proposal_node_removed` in `cognitive` category |

**Files changed / created:**

| File | Change |
|------|--------|
| `src/probos/runtime.py` | Extracted `_execute_dag()` from `process_natural_language()`. Added `propose()`, `execute_proposal()`, `reject_proposal()`, `remove_proposal_node()`. Added `_pending_proposal` and `_pending_proposal_text` state. Imported `TaskDAG`/`TaskNode` |
| `src/probos/experience/panels.py` | Added `render_dag_proposal()` with numbered table, dependency index mapping, consensus flags, reflect annotation |
| `src/probos/experience/shell.py` | Added `/plan`, `/approve`, `/reject` commands with full handler implementations. Updated COMMANDS and handler dicts |
| `tests/test_dag_proposal.py` | **New.** 42 tests: propose lifecycle, execute/reject/remove, panel rendering, event log, shell commands, workflow cache integration |

1187/1187 tests passing (+ 11 skipped). 42 new tests.

### Phase 17 — Dependency Resolution (AD-210 through AD-215)

Self-designed agents and skills can now import any module on the expanded `allowed_imports` whitelist. When a designed agent or skill uses a third-party package that isn't installed, the `DependencyResolver` detects the gap, prompts the user for approval, and installs via `uv add`.

| AD | What |
|----|------|
| AD-210 | Expand `allowed_imports` whitelist in all config YAML files — stdlib additions (40+ modules) + third-party additions (httpx, feedparser, bs4, lxml, chardet, yaml, toml, pandas, numpy, openpyxl, markdown, jinja2, dateutil, tabulate) with inline comments grouping by category |
| AD-211 | `DependencyResolver` module — `detect_missing(source_code)` parses imports via AST, checks `importlib.util.find_spec()`, returns missing-but-allowed packages |
| AD-212 | `DependencyResolver.resolve()` — orchestrates detection → approval → installation → verification. `IMPORT_TO_PACKAGE` mapping for non-obvious names (bs4→beautifulsoup4, yaml→pyyaml, dateutil→python-dateutil). `_install_package()` calls `uv add` with timeout |
| AD-213 | Wire `DependencyResolver` into `SelfModificationPipeline` — new optional constructor param. Resolution runs between CodeValidator and SandboxRunner in both agent and skill flows. Pipeline aborts with `dependencies_declined` or `dependencies_failed` record status on failure |
| AD-214 | Shell approval UX — `_user_dep_install_approval()` callback in shell.py, wired to resolver's `approval_fn`. Displays missing packages as bulleted list, prompts `Install with uv add? [y/n]` |
| AD-215 | Event log integration — `dependency_check`, `dependency_install_approved`, `dependency_install_success`, `dependency_install_declined`, `dependency_install_failed` events in `self_mod` category. Both agent and skill flows emit events. Uses `detail=json.dumps(...)` for structured data |

#### Files changed

| File | Changes |
|------|---------|
| `config/system.yaml` | Expanded `allowed_imports` from 18 to 60+ entries with category comments |
| `config/node-1.yaml` | Same `allowed_imports` expansion |
| `config/node-2.yaml` | Same `allowed_imports` expansion |
| `src/probos/cognitive/dependency_resolver.py` | **New.** `DependencyResolver` class, `DependencyResult` dataclass, `IMPORT_TO_PACKAGE` mapping. AST-based import detection, `importlib.util.find_spec` availability check, `uv add` installation, user approval callback |
| `src/probos/cognitive/self_mod.py` | Added `DependencyResolver` and `EventLog` imports. Added `dependency_resolver` and `event_log` optional constructor params. Inserted dependency resolution step (2b) between validation and sandbox in both `handle_unhandled_intent()` and `handle_add_skill()`. Event logging for dependency lifecycle |
| `src/probos/runtime.py` | Creates `DependencyResolver` in self-mod init block, passes to pipeline with `event_log` |
| `src/probos/experience/shell.py` | Added `_user_dep_install_approval()` callback. Wires approval to resolver's `_approval_fn` during init |
| `tests/test_dependency_resolver.py` | **New.** 28 tests: stdlib detection, third-party detection, import forms, package mapping, resolve orchestration, approval/decline/install, dataclass defaults |
| `tests/test_self_mod_deps.py` | **New.** 12 tests: pipeline backward compat, resolver integration, declined/failed abort, skill resolution, event log events, end-to-end flow |

#### Phase 17 HXI specifics

- **User approval before install** — ProbOS never installs packages without asking. The shell prompts with a clear list of packages and their names, with `[y/n]` confirmation
- **Transparent package mapping** — when import name differs from package name (e.g., `bs4` → `beautifulsoup4`), the approval prompt shows both names so the user knows exactly what will be installed
- **Full event log audit trail** — every dependency decision is logged: what was checked, what was approved/declined, what succeeded/failed. Supports `/events` inspection

1227/1227 tests passing (+ 11 skipped). 40 new tests.

### Phase 18 — Feedback-to-Learning Loop (AD-216 through AD-222)

User signals after execution — `/feedback good|bad` and `/reject` — now feed into Hebbian weight updates, trust adjustments, and tagged episodic memory. Human feedback is the highest-quality training signal available: the system learns faster from human feedback than from agent-to-agent interactions (2x Hebbian reward: 0.10 vs 0.05).

| AD | What |
|----|------|
| AD-216 | `/feedback good\|bad` shell command. Operates on `_last_execution`. One rating per execution (`_last_feedback_applied` flag). Reset on each new execution |
| AD-217 | `FeedbackEngine`: applies human signals to trust, Hebbian routing, and episodic memory. `feedback_hebbian_reward=0.10` (2x normal) because human feedback is higher quality. One `record_outcome()` per agent for trust |
| AD-218 | Feedback-tagged episodes: `human_feedback` field in episode metadata (`"positive"`, `"negative"`, `"rejected_plan"`). Recalled by decomposer via `recall_similar()` to influence future planning |
| AD-219 | `FeedbackEngine` created in runtime `start()`, wired to `record_feedback()`. `reject_proposal()` auto-applies rejection feedback. `_last_feedback_applied` and `_last_execution_text` state tracking. Executed DAG stored in `execution_result["dag"]` for feedback access |
| AD-220 | `/feedback` command wired to `runtime.record_feedback()`. `/reject` display updated to indicate feedback was recorded |
| AD-221 | Agent ID extraction from executed DAGs: handles dict results, IntentResult objects, missing results, deduplication. Intent→agent pairs for Hebbian updates |
| AD-222 | Event log: `feedback_positive`, `feedback_negative`, `feedback_plan_rejected`, `feedback_hebbian_update`, `feedback_trust_update`. Category: `cognitive` |

### AD-228: Web-fetching perceive() override for designed agents

**Problem:** `AGENT_DESIGN_PROMPT` explicitly forbade overriding `perceive()`, locking all designed CognitiveAgents into pure LLM reasoning. LLMs cannot browse the internet, so any intent requiring real-time web data (news, weather, live APIs) would fail — the agent asked the LLM to produce data it cannot access.

**Decision:** Allow `perceive()` override in designed agents specifically for real-time data fetching. The design prompt now provides two templates: (1) pure LLM reasoning (no override — for intents solvable via reasoning alone) and (2) web-fetching (override `perceive()` to fetch data via httpx, store in `observation["fetched_content"]`). An explicit guard states: "An LLM cannot browse the internet. If the intent requires fetching live data, you MUST override perceive()."

**Changes:**
- `agent_designer.py`: Updated `AGENT_DESIGN_PROMPT` — removed `perceive()` from "do NOT redefine" list, added web-fetching template with httpx pattern, added LLM-cannot-browse warning, dual template structure
- `cognitive_agent.py`: `_build_user_message()` now includes `fetched_content` from observation dict in the LLM user prompt, so web-fetched data flows through to the LLM automatically

**Constraints:** `perceive()` override is scoped to data fetching only — `decide()`, `report()`, `handle_intent()`, and `__init__()` remain forbidden overrides. httpx is already in `allowed_imports` (system.yaml). The mesh governance model is preserved — the agent fetches data in `perceive()` but still uses the LLM in `decide()` for reasoning over that data.

#### Files changed

| File | Changes |
|------|---------|
| `src/probos/cognitive/feedback.py` | **New.** `FeedbackEngine` class, `FeedbackResult` dataclass. Hebbian updates (2x reward), trust updates, feedback-tagged episode storage, event log integration. Agent ID extraction from DAG node results (dict/IntentResult/None). Intent→agent pair extraction for Hebbian routing |
| `src/probos/runtime.py` | Added `_last_feedback_applied`, `_last_execution_text`, `feedback_engine` state. `FeedbackEngine` creation in `start()`. `record_feedback()` method. `reject_proposal()` wired to rejection feedback. `execution_result["dag"] = dag` in `_execute_dag()` for feedback access. Feedback state resets in `process_natural_language()` and `_execute_dag()` |
| `src/probos/experience/shell.py` | `/feedback good\|bad` command: usage validation, guard checks (no execution, already rated), calls `runtime.record_feedback()`, displays agent count. `/reject` updated to show "Feedback recorded for future planning" |
| `tests/test_feedback_engine.py` | **New.** 28 tests: positive/negative Hebbian updates, trust updates, episode storage with tags, FeedbackResult correctness, 2x reward verification, empty DAG, failed nodes, deduplication, rejection feedback (episode only, no trust/Hebbian), agent ID extraction (dict, IntentResult, missing, dedup), intent-agent pairs, event log integration (events, categories), FeedbackResult dataclass |
| `tests/test_feedback_runtime.py` | **New.** 17 tests: record_feedback guard checks (no execution, already rated, no engine, no DAG), positive/negative engine calls, flag setting, _execute_dag reset, reject_proposal feedback wiring (with/without engine), shell command integration (usage, good, bad, already rated, no execution) |

#### Phase 18 HXI specifics

- **Feedback is opt-in** — `/feedback good|bad` is user-initiated, never prompted. Each execution can only be rated once (prevents signal-spamming)
- **Rejection becomes a learning signal** — `/reject` automatically stores a rejection-tagged episode so the decomposer sees "user rejected a plan like this" in future PAST EXPERIENCE context
- **Transparent weight updates** — the shell reports exactly how many agents were affected by the feedback, making the learning process visible to the user
- **No forced learning** — feedback episodes influence future planning through the existing `recall_similar()` mechanism. The decomposer sees tagged episodes in context but is not forced to follow them — it uses its own judgment about how to incorporate the signal

1272/1272 tests passing (+ 11 skipped). 45 new tests.

### Phase 19 — Shapley Value Trust Attribution + Trust-Weighted Capability Matching (AD-223 through AD-227)

Two game-theoretic improvements that make ProbOS's trust and agent selection systems meaningfully smarter:

1. **Shapley Value Trust Attribution** — when a consensus outcome succeeds or fails, agents who were *decisive* (removing them would have changed the outcome) get proportionally more trust credit than agents who were *redundant* (the outcome would have been the same without them).

2. **Trust-Weighted Capability Matching** — when agents match for an intent, the system prefers agents whose capability claims are backed by trust history. `final_score = capability_score * (0.5 + 0.5 * trust)` — floor at 50%, never eliminates matches.

| AD | What |
|----|------|
| AD-223 | `compute_shapley_values()` — brute-force permutation algorithm for coalitions of 3-7 agents. Marginal contribution: does adding agent *i* change the quorum outcome? Supports confidence-weighted and unweighted voting. Normalized to [0, 1]. Edge cases: unanimous → equal split, dissenter → 0.0, single agent → 1.0 |
| AD-224 | Shapley-weighted trust updates. `ConsensusResult.shapley_values: dict[str, float] | None` populated by `QuorumEngine.evaluate()`. Trust `record_outcome()` uses Shapley value as weight (floor 0.1 for redundant agents). `_last_shapley_values` stored on runtime for panel display |
| AD-225 | Trust-weighted capability matching. `CapabilityRegistry.query()` accepts optional `trust_scores: dict[str, float]`. Score formula: `score * (0.5 + 0.5 * trust)`. Trust 1.0 → no change, trust 0.0 → halved. Backward compatible (None = no weighting) |
| AD-226 | Agent selection wiring. ProbOS agents self-select via `handle_intent()` — the CapabilityRegistry is not in the dispatch path. Trust-based quality differentiation is already covered by confidence-weighted consensus voting (AD-19) and Shapley attribution (AD-224). Trust-weighted matching is available for future mesh routing and the StrategyRecommender |
| AD-227 | `/agents` panel shows Shapley column when values available: value + label (decisive/marginal/redundant). Thresholds: ≥0.4 decisive, ≥0.15 marginal, <0.15 redundant |

#### Files changed

| File | Changes |
|------|---------|
| `src/probos/consensus/shapley.py` | **New.** `compute_shapley_values()` — permutation-based Shapley computation, `_evaluate_coalition()` helper for subset quorum evaluation |
| `src/probos/consensus/quorum.py` | Imports `compute_shapley_values`. `evaluate()` populates `ConsensusResult.shapley_values` for non-INSUFFICIENT outcomes |
| `src/probos/types.py` | Added `shapley_values: dict[str, float] | None = None` to `ConsensusResult` |
| `src/probos/mesh/capability.py` | `query()` accepts optional `trust_scores` parameter. When provided, scores multiplied by `(0.5 + 0.5 * trust)` |
| `src/probos/runtime.py` | Shapley-weighted trust updates in `submit_intent_with_consensus()`: `record_outcome(weight=shapley_weight)` with floor 0.1. `_last_shapley_values` stored for panel display |
| `src/probos/experience/panels.py` | `render_agent_table()` accepts optional `shapley_values` parameter, shows Shapley column with value + decisive/marginal/redundant label |
| `src/probos/experience/shell.py` | `/agents` command passes `_last_shapley_values` to panel renderer |
| `tests/test_shapley.py` | **New.** 26 tests: core computation (unanimous, dissenter, decisive voter, 5-agent, single, all-reject, confidence-weighted, empty, sum ≤1, non-negative, identical votes, marginal vote, unweighted, 4-agent split, 2-agent, 7-agent tractable, rejected outcome, high threshold), ConsensusResult integration (default None, explicit set, QuorumEngine populates, INSUFFICIENT no Shapley), panel integration (with/without Shapley column) |
| `tests/test_trust_weighted_capability.py` | **New.** 12 tests: trust weighting (no scores unchanged, trust 1.0/0.0/0.5, higher trust ranks above, never eliminates, multiple agents ordering, missing agent default), Shapley-weighted trust updates (decisive stronger, redundant weaker, equal votes equal, weight backward compat) |

#### Phase 19 design notes

- **Brute-force is fine** — ProbOS quorums are 3-7 agents, so `itertools.permutations` produces at most 5040 iterations. No approximation algorithms needed
- **Shapley applies to consensus only** — it's specifically about coalition games (quorum voting). Hebbian routing and feedback trust use different update mechanics
- **Trust-weighted matching complements, doesn't replace** — agents still self-select for intents. Trust weighting is a parallel signal available for ranking when multiple agents match the same capability
- **Floor at 0.1 for trust updates** — even redundant agents get minimal trust signal so they don't become invisible to the trust network

1310/1310 tests passing (+ 11 skipped). 38 new tests.

### Phase 18b — Correction Feedback Loop (AD-229 through AD-235)

Bridges the gap between self-modification (Phase 10) and feedback-to-learning (Phase 18): when a self-mod'd agent fails and the user provides a correction, the system fixes the agent instead of starting a new self-mod cycle.

**The problem:** user says "get news from CNN" → agent created → uses wrong URL protocol (HTTPS instead of HTTP) → fails. User says "use http not https" → system interprets this as a *new* unhandled intent → creates yet another agent. The correction loop intercepts this: detects the correction, patches the failing agent's source code, hot-reloads it, and auto-retries.

| AD | What |
|----|------|
| AD-229 | `CorrectionDetector` — LLM-based classifier distinguishes corrections from new requests. `CorrectionSignal` dataclass. Conservative threshold (confidence ≥ 0.5). Detection prompt with examples. Handles DAG objects and dicts. Returns None gracefully on failure |
| AD-230 | `AgentPatcher` — generates patched source via LLM, validates with same `CodeValidator` + `SandboxRunner` as self-mod. `PatchResult` and `CorrectionResult` dataclasses. Supports agent (sandbox test) and skill (importlib compilation) strategies. `_clean_source()` strips markdown fences and think blocks. No new security surface |
| AD-231 | `apply_correction()` — hot-reloads patched agent into live runtime. Agent strategy: swap class in pool agents + spawner templates. Skill strategy: remove + re-add skill. Refreshes decomposer descriptors, persists to knowledge store. Auto-retries original request after reload |
| AD-232 | Correction detection in `process_natural_language()` before `decomposer.decompose()`. Runs after preamble (activity tracking, focus, pre-warm sync) but before decomposition — if correction succeeds, decompose is skipped entirely. Only targets designed agents (built-in agents cannot be patched). Falls through gracefully on detection failure or patch failure |
| AD-233 | `/correct <text>` explicit shell command. Same pipeline as auto-detection but user-initiated. Checks `_last_execution` exists, detects correction signal, patches, hot-reloads, retries. Displays patch diff and retry result. Added to `/help` |
| AD-234 | `apply_correction_feedback()` in `FeedbackEngine`. Correction episodes stored with rich metadata: `human_feedback: "correction_applied"/"correction_failed"`, correction_type, corrected_values, changes_description, retry_success. Hebbian strengthen/weaken on retry outcome. Trust bump on retry success. Event log: `feedback_correction_applied`/`feedback_correction_failed`. Corrections are the richest feedback signal — they encode "what went wrong" and "how to fix it" |
| AD-235 | `execution_context` parameter on `AgentDesigner.design_agent()` and `SelfModificationPipeline.handle_unhandled_intent()`. Prior successful execution results passed to the LLM so generated agents use known-working values (URLs, parameters, protocols) instead of guessing. Addresses the root cause: AgentDesigner was guessing values that provably worked in the prior execution |

#### Files changed

| File | Changes |
|------|---------|
| `src/probos/cognitive/correction_detector.py` | **New.** `CorrectionDetector`, `CorrectionSignal` dataclass, LLM detection prompt, `_format_dag()`, `_parse_response()` |
| `src/probos/cognitive/agent_patcher.py` | **New.** `AgentPatcher`, `PatchResult` dataclass, `CorrectionResult` dataclass, `_patch_agent()`, `_patch_skill()`, `_clean_source()` |
| `src/probos/cognitive/feedback.py` | Added `apply_correction_feedback()` method — Hebbian, trust, episodic memory, event log for correction events |
| `src/probos/cognitive/agent_designer.py` | Added `execution_context` parameter to `design_agent()` and EXECUTION CONTEXT section to prompt template |
| `src/probos/cognitive/self_mod.py` | Added `execution_context` parameter to `handle_unhandled_intent()`, passed through to `design_agent()` |
| `src/probos/runtime.py` | Added `_correction_detector`, `_agent_patcher` fields and creation in `start()`. Added `apply_correction()`, `_apply_agent_correction()`, `_apply_skill_correction()`, `_find_designed_record()`, `_was_last_execution_successful()`, `_format_execution_context()`. Correction detection wired before `decomposer.decompose()` in `process_natural_language()` — successful correction returns early, skipping decomposition entirely. Execution context passed to `handle_unhandled_intent()`. Correction feedback recorded via `feedback_engine.apply_correction_feedback()` |
| `src/probos/experience/shell.py` | Added `/correct` command to COMMANDS dict, handler dispatch, and `_cmd_correct()` implementation |
| `tests/test_correction_detector.py` | **New.** 12 tests: detection (no prior execution, no DAG, empty nodes, LLM correction, new request, low confidence, parameter_fix, malformed response, execution context in prompt, LLM failure, markdown fences, DAG as dict) |
| `tests/test_agent_patcher.py` | **New.** 14 tests: patching (success agent, preserves original, changes description, validation failure, sandbox failure, LLM failure, empty response, skill handler, clean markdown, clean think blocks, correction info in prompt, PatchResult defaults, CorrectionResult defaults, sends prompt) |
| `tests/test_correction_runtime.py` | **New.** 22 tests: _find_designed_record (recent active, built-in, no pipeline, patched), _was_last_execution_successful (no execution, all completed, node failed), _format_execution_context (no execution, includes text, includes intent/params), correction feedback (applied/failed, Hebbian, trust success/failure, episodic, event log), /correct shell command (help includes, description), correction before decompose (successful correction skips decompose), AgentDesigner context (included in prompt, empty default, pipeline passthrough) |

#### Phase 18b design notes

- **Correction detection is conservative** — false positives (treating a new request as a correction) are worse than false negatives. Confidence threshold ≥ 0.5
- **Only designed agents can be patched** — built-in agents are part of the core codebase. If correction detection targets a built-in, it falls through to normal flow
- **No new security surface** — patched code goes through the same `CodeValidator` + `SandboxRunner` pipeline as freshly designed agents
- **Correction episodes are the richest learning signal** — they include both "what went wrong" (the original failure) and "how to fix it" (the corrected values). Future decomposer recall will surface these episodes as PAST EXPERIENCE context, teaching the LLM to avoid the same mistakes

1358/1358 tests passing (+ 11 skipped). 48 new tests.

### Phase 20 — Emergent Behavior Detection (AD-236 through AD-240)

Population-level dynamics analyzer that monitors ALL agents for emergent behavior patterns. Unlike BehavioralMonitor (which tracks individual self-created agents for behavioral anomalies), EmergentDetector analyzes system-wide patterns:

1. **Hebbian weight topology** → cooperation clusters via union-find connected components
2. **Trust score trajectories** → z-score outlier detection, hyperactive observation detection, change-point detection
3. **Routing patterns** → new intent/connection detection, Shannon entropy over pool weight distribution
4. **Dream consolidation** → baseline comparison for anomalous strengthening/pruning/trust adjustments
5. **TC_N (total correlation proxy)** → fraction of intent types routing to 2+ pools (multi-pool cooperation)

| AD | What |
|----|------|
| AD-236 | `EmergentDetector` — population-level dynamics analyzer. `EmergentPattern` dataclass (pattern_type, description, confidence, evidence, severity). `SystemDynamicsSnapshot` for point-in-time metrics. `compute_tc_n()` — total correlation proxy. `compute_routing_entropy()` — Shannon entropy. `detect_cooperation_clusters()` — union-find on Hebbian weight graph. `detect_trust_anomalies()` — z-score + hyperactive + change-point. `detect_routing_shifts()` — new intents/connections + entropy delta. `detect_consolidation_anomalies()` — dream report baseline comparison. Ring buffer history for trend analysis |
| AD-237 | Runtime wiring. `_emergent_detector` created unconditionally in `start()`. `_on_post_dream()` callback wired to `DreamScheduler._post_dream_fn`. `status()` includes `"emergent"` key with summary. Event logging for detected patterns (category: `emergent`) |
| AD-238 | Introspection integration. Two new intents: `system_anomalies` (runs detectors, returns pattern list) and `emergent_patterns` (returns snapshot + summary + trends). MockLLMClient patterns for "anomalies" and "emergent patterns" NL queries |
| AD-239 | Shell + panel. `/anomalies` command shows emergent behavior panel. `render_anomalies_panel()` — system dynamics metrics (TC_N, routing entropy, cooperation clusters, snapshots, patterns detected) + pattern table with severity coloring (info=dim, notable=yellow, significant=red) |
| AD-240 | 51 tests: dataclass roundtrips (3), TC_N computation (7: no episodic, no weights, single pool, multi pool, mixed, pool extraction, malformed ID), cooperation clusters (5: empty, single, disconnected, threshold, members), trust anomalies (6: similar, low, high, change point, hyperactive, single agent), routing shifts (5: no previous, new connection, stable, entropy uniform, entropy concentrated), consolidation anomalies (5: no report, normal, high strengthened, high pruned, prewarm), analyze integration (4: returns list, stores snapshot, max history, trends), summary/snapshot (3: JSON serializable, returns dynamics, capped patterns), runtime integration (4: creates detector, status includes emergent, tc_n zero, post dream wired), introspection integration (4: system_anomalies intent, emergent_patterns intent, MockLLM anomalies, MockLLM emergent), shell/panel (5: command works, help includes, patterns panel, empty panel, severity coloring) |

#### Files changed

| File | Changes |
|------|---------|
| `src/probos/cognitive/emergent_detector.py` | **New.** `EmergentDetector`, `EmergentPattern`, `SystemDynamicsSnapshot` dataclasses, 5 detection algorithms, `summary()`, `get_snapshot()`, ring buffer history |
| `src/probos/cognitive/dreaming.py` | Added `_post_dream_fn` callback to `DreamScheduler`. Invoked in `force_dream()` and `_monitor_loop()` after each dream cycle completes |
| `src/probos/runtime.py` | Added `_emergent_detector` field, creation in `start()`, `_on_post_dream()` method, `status()` includes `"emergent"` key, post-dream callback wiring |
| `src/probos/agents/introspect.py` | Added `system_anomalies` and `emergent_patterns` intents (descriptors + handlers + dispatch) |
| `src/probos/cognitive/llm_client.py` | Added `system_anomalies` and `emergent_patterns` MockLLMClient patterns and response handlers |
| `src/probos/experience/panels.py` | Added `render_anomalies_panel()` — system dynamics metrics + pattern table with severity coloring |
| `src/probos/experience/shell.py` | Added `/anomalies` command to COMMANDS dict, handler dispatch, and `_cmd_anomalies()` implementation |
| `tests/test_emergent_detector.py` | **New.** 51 tests covering all detectors, runtime integration, introspection integration, shell/panel rendering |

#### Phase 20 design notes

- **Population-level, not individual** — BehavioralMonitor tracks designed agents for safety. EmergentDetector monitors the whole system for interesting dynamics: cooperation clusters, trust anomalies, routing shifts, consolidation spikes
- **Purely observational** — EmergentDetector is a reader, not a writer. It doesn't modify trust, routing, or behavior. It only reports what it sees
- **Post-dream timing** — emergent analysis piggybacks on dream cycles. Dream cycles already consolidate Hebbian weights and trust, making the post-dream snapshot a natural observation point
- **TC_N is a proxy, not the theory** — the original Tononi TC_N requires Gaussian mutual information across independent modules. ProbOS has a single mesh, so we approximate with multi-pool cooperation fraction: what percentage of intent types route to 2+ distinct pools?
- **Ring buffer history** — snapshots are stored in a bounded ring buffer (default 100). Trend analysis looks at the last 10 snapshots to avoid stale baselines

1409/1409 tests passing (+ 11 skipped). 51 new tests.

### Phase 21 — Semantic Knowledge Layer + Phase 20 Cleanup (AD-241 through AD-246)

Two parts: (1) Phase 20 cleanup fixes (`parse_agent_id`, pattern cap, reflect prompt), (2) Semantic Knowledge Layer — unified semantic search across all ProbOS knowledge types via ChromaDB collections.

**Phase 20 cleanup (AD-241):**
- `parse_agent_id()` — reverses `generate_agent_id()` using `_ID_REGISTRY` module-level registry (populated on each ID generation) + right-to-left regex parsing with hash verification fallback
- `_all_patterns` capped at 500 entries in `EmergentDetector.analyze()` to prevent unbounded growth
- `REFLECT_PROMPT` rule 6 — structured data extraction guidance for XML, JSON, HTML, CSV results

**Semantic Knowledge Layer (AD-242 through AD-246):**

`SemanticKnowledgeLayer` manages 5 ChromaDB collections (`sk_agents`, `sk_skills`, `sk_workflows`, `sk_qa_reports`, `sk_events`) for non-episode knowledge. Episodes queried via existing `EpisodicMemory` — no duplicate collection. The layer fans out semantic queries across all collections and merges results by cosine similarity score.

| AD | What |
|----|------|
| AD-241 | Phase 20 cleanup: `parse_agent_id()` with `_ID_REGISTRY` + hash verification fallback, `_all_patterns` cap at 500, `REFLECT_PROMPT` rule 6 for structured data extraction |
| AD-242 | `SemanticKnowledgeLayer` — 5 ChromaDB collections, indexing methods (`index_agent`, `index_skill`, `index_workflow`, `index_qa_report`, `index_event`), `search()` with cross-type fan-out + episode recall, `stats()`, `reindex_from_store()` for warm boot |
| AD-243 | Runtime wiring. `_semantic_layer` created when episodic memory available. Auto-indexing hooks on `store_agent()`, `store_skill()`, `store_qa_report()`. Warm boot re-index in `_restore_from_knowledge()`. `status()` includes `"semantic_knowledge"` key. Shutdown cleanup |
| AD-244 | Introspection integration. `search_knowledge` intent with `query` and `types` params. MockLLMClient pattern for "search for", "find in knowledge", "what do you know about" |
| AD-245 | Shell + panel. `/search` command with `--type` filter. `render_search_panel()` — stats section + ranked results table with type-based coloring (agent=cyan, skill=green, workflow=yellow, qa_report=magenta, event=blue, episode=dim) |
| AD-246 | 45 tests: `parse_agent_id` (4: registry, compound pool, hash fallback, UUID returns None), `_all_patterns` cap (1), lifecycle (3: start creates collections, stop cleans up, stats returns counts), agent indexing (4: stores document, metadata, idempotent, multiple searchable), skill indexing (3: stores, metadata, searchable), workflow indexing (3: stores, metadata, searchable), QA report indexing (2: stores, searchable), event indexing (2: stores, searchable), cross-type search (6: multiple types, type filter, includes episodes, sorted by score, respects limit, no matches empty), bulk reindex (3: indexes agents, indexes skills, returns count dict), runtime integration (5: creates layer with episodic, no layer without episodic, status includes semantic_knowledge, status disabled without layer, shutdown cleans up), introspection integration (4: search_knowledge intent, with types, no layer, MockLLM routes), shell/panel (5: help includes search, render with results, render empty, score format, no query error) |

#### Files changed

| File | Changes |
|------|---------|
| `src/probos/substrate/identity.py` | Added `_ID_REGISTRY` module-level dict, `generate_agent_id()` populates registry, added `_ID_SUFFIX_RE` regex, added `parse_agent_id()` |
| `src/probos/cognitive/emergent_detector.py` | `_extract_pool()` rewritten to use `parse_agent_id()` with fallback, `analyze()` caps `_all_patterns` at 500 |
| `src/probos/cognitive/decomposer.py` | Added rule 6 to `REFLECT_PROMPT` for structured data extraction |
| `src/probos/knowledge/semantic.py` | **New.** `SemanticKnowledgeLayer` with 5 ChromaDB collections, indexing/search/stats/reindex methods |
| `src/probos/runtime.py` | Added `_semantic_layer` field, creation in `start()`, auto-indexing hooks, warm boot reindex, `status()` key, shutdown cleanup |
| `src/probos/agents/introspect.py` | Added `search_knowledge` intent (descriptor + handler + dispatch) |
| `src/probos/cognitive/llm_client.py` | Added `search_knowledge` MockLLMClient pattern and response handler |
| `src/probos/experience/panels.py` | Added `_TYPE_COLORS` dict, `render_search_panel()` — stats + ranked results table |
| `src/probos/experience/shell.py` | Added `/search` command to COMMANDS dict, handler dispatch, `_cmd_search()` with `--type` filter |
| `tests/test_semantic_knowledge.py` | **New.** 45 tests covering parse_agent_id, lifecycle, all indexing types, cross-type search, bulk reindex, runtime integration, introspection, shell/panel |

#### Phase 21 design notes

- **No duplicate episode collection** — episodes already live in `EpisodicMemory`'s ChromaDB. The semantic layer queries it via `recall()` rather than creating a second copy. This avoids data divergence and leverages the existing embedding setup
- **Fire-and-forget auto-indexing** — runtime hooks after `store_agent()`, `store_skill()`, `store_qa_report()` are wrapped in try/except. If the semantic layer is unavailable, the primary store operation still succeeds
- **Conditional creation** — the semantic layer requires episodic memory (for ChromaDB and episode search). If no episodic memory is configured, the layer is not created and `/search` gracefully reports "disabled"
- **Cosine similarity → score** — ChromaDB returns cosine distance (0 = identical, 2 = opposite). The layer converts to similarity (`1.0 - distance`) for consistent scoring. Episode results from episodic memory get a default 0.5 score (already filtered by relevance)
- **`parse_agent_id()` design** — the registry lookup is O(1) for IDs generated in the current session. The hash verification fallback handles IDs from warm boot (pre-registry). Right-to-left split tries all possible type/pool boundaries and verifies against the stored hash suffix

1454/1454 tests passing (+ 11 skipped). 45 new tests.

### Phase 22 — Bundled Agent Suite + Distribution (AD-247 through AD-253)

ProbOS becomes installable and immediately useful. 10 bundled CognitiveAgent subclasses cover common personal assistant tasks. Distribution infrastructure enables `pip install probos`, `probos init`, `probos serve`. Self-mod continues to handle the long tail beyond bundled agents.

**Bundled agents (10 agents in `src/probos/agents/bundled/`):**

All bundled agents subclass `CognitiveAgent` and use `_BundledMixin` for self-deselect (return `None` from `handle_intent()` for unrecognized intents, preventing cascading intent broadcasts). Web-facing agents dispatch `http_fetch` through the mesh via `intent_bus.broadcast()` — never httpx directly. File-persisting agents dispatch `read_file`/`write_file` through the mesh — never `Path.write_text()` directly. This preserves governance (consensus, trust) across the entire stack.

| AD | What |
|----|------|
| AD-247 | Distribution: `[project.scripts]` for `pip install`, `probos init` config wizard (creates `~/.probos/` with config.yaml, data/, notes/), `probos serve` with FastAPI/uvicorn HTTP + WebSocket server, `_boot_runtime()` shared boot logic, `_load_config_with_fallback()` config resolution chain. `src/probos/api.py`: `create_app(runtime)` returns FastAPI with `/api/health`, `/api/status`, `/api/chat`, `/ws/events` |
| AD-248 | Web + Content agents: `WebSearchAgent` (DuckDuckGo via mesh `http_fetch`), `PageReaderAgent` (URL → summarize, HTML tag stripping), `WeatherAgent` (wttr.in JSON), `NewsAgent` (RSS XML parsing via `xml.etree.ElementTree`, `_parse_rss()`, default feeds dict). All fetch via `_mesh_fetch()` helper. `_BundledMixin` self-deselect guard |
| AD-249 | Language agents: `TranslateAgent` (pure LLM translation), `SummarizerAgent` (pure LLM summarization). No `perceive()` override — entirely LLM-driven via `instructions` |
| AD-250 | Productivity agents: `CalculatorAgent` (safe eval for simple arithmetic via `_SAFE_EXPR_RE`, LLM fallback), `TodoAgent` (file-backed `~/.probos/todos.json` via mesh `read_file`/`write_file`). Mesh I/O helpers |
| AD-251 | Organizer agents: `NoteTakerAgent` (file-backed `~/.probos/notes/`, semantic search via `_semantic_layer`), `SchedulerAgent` (file-backed `~/.probos/reminders.json`, no background timer). Mesh I/O helpers |
| AD-252 | Runtime registration: 10 new pools (2 agents each), spawner templates, `BundledAgentsConfig(enabled=True)`, descriptor refresh, MockLLMClient patterns for all 10 bundled intents. MockLLMClient `match_text` extraction: pattern matching against "User request:" portion only (prevents false positives from pool names and capability listings in system state context) |
| AD-253 | 66 tests: `test_bundled_agents.py` (50 tests — per-agent attributes, handle_intent, self-deselect, agent-specific behavior), `test_distribution.py` (16 tests — runtime integration, probos init, FastAPI endpoints) |

#### Files changed

| File | Changes |
|------|---------|
| `pyproject.toml` | Added `[project.scripts]` entry `probos = "probos.__main__:main"`, added `fastapi>=0.115` and `uvicorn>=0.34` dependencies |
| `src/probos/__main__.py` | Rewritten: added `init` and `serve` subcommands via argparse, `_boot_runtime()` shared boot logic, `_load_config_with_fallback()`, `_cmd_init()`, `_serve()` |
| `src/probos/api.py` | **New.** FastAPI app: `/api/health`, `/api/status`, `/api/chat`, `/ws/events` |
| `src/probos/agents/bundled/__init__.py` | **New.** Re-exports all 10 bundled agent classes |
| `src/probos/agents/bundled/web_agents.py` | **New.** WebSearchAgent, PageReaderAgent, WeatherAgent, NewsAgent + `_BundledMixin` + `_mesh_fetch()` |
| `src/probos/agents/bundled/language_agents.py` | **New.** TranslateAgent, SummarizerAgent + `_BundledMixin` |
| `src/probos/agents/bundled/productivity_agents.py` | **New.** CalculatorAgent, TodoAgent + `_BundledMixin` + mesh I/O helpers |
| `src/probos/agents/bundled/organizer_agents.py` | **New.** NoteTakerAgent, SchedulerAgent + `_BundledMixin` + mesh I/O helpers |
| `src/probos/config.py` | Added `BundledAgentsConfig(enabled=True)` to `SystemConfig` |
| `config/system.yaml` | Added `bundled_agents: enabled: true` |
| `src/probos/runtime.py` | Added bundled agent imports, spawner template registrations, conditional pool creation gated by `bundled_agents.enabled` |
| `src/probos/cognitive/llm_client.py` | Added 10 MockLLMClient patterns + response handlers for bundled intents, `match_text` extraction from "User request:" portion to prevent false positives |
| `tests/test_bundled_agents.py` | **New.** 50 tests covering all 10 bundled agents |
| `tests/test_distribution.py` | **New.** 16 tests for runtime integration, probos init, FastAPI endpoints |
| `tests/test_decomposer.py` | Updated 2 tests: changed "translate hello to French" → "please convert this audio to text" (avoids matching new translate pattern) |
| `tests/test_experience.py` | Updated 3 tests: changed "translate hello into japanese" → "please transcribe this audio clip" (avoids matching new translate pattern) |

#### Phase 22 design notes

- **`_BundledMixin` self-deselect** — the IntentBus broadcasts every intent to ALL subscribers. Without the mixin, CognitiveAgent.handle_intent() runs full perceive→decide→act for ANY intent, causing cascading sub-intent broadcasts from perceive() overrides. The mixin returns `None` for unrecognized intents, preventing infinite loops
- **MockLLMClient `match_text` extraction** — the decomposer wraps user text in system state context (pool names, capability listings). Bare pattern matching against the full prompt caused false positives (e.g., "news" matching pool name "news: 2"). Now patterns only match against the "User request: ..." portion
- **Mesh dispatch for all I/O** — bundled agents never use httpx or Path directly. All web fetches go through `intent_bus.broadcast(IntentMessage(intent="http_fetch"))` and all file I/O goes through `read_file`/`write_file` intents. This preserves consensus, trust scoring, and event logging for every operation
- **No background timer** — SchedulerAgent stores reminders but has no cron-like timer. Reminders are checked at boot/interaction. Background scheduling comes in a future phase

1520/1520 tests passing (+ 11 skipped). 66 new tests.

---

### Phase 23 — HXI MVP: "See Your AI Thinking" (AD-254 through AD-261)

**Track A (Python — AD-254):** Enriched event stream
- `runtime.py`: `add_event_listener()` / `remove_event_listener()` / `_emit_event()` — fire-and-forget event dispatch to registered listeners
- `build_state_snapshot()` — full system state serialized on WebSocket connect (agents, connections, pools, system_mode, tc_n, routing_entropy)
- Instrumented events: `agent_state` (on wire), `trust_update` (after record_outcome), `hebbian_update` (after record_interaction), `consensus` (after quorum evaluate), `system_mode` (pre/post dream)
- `dreaming.py`: Added `_pre_dream_fn` callback to DreamScheduler, symmetric with existing `_post_dream_fn`

**Track A (Python — AD-260):** Serve integration
- `api.py`: CORS middleware for HXI dev server (`localhost:5173`), event listener bridge (runtime → WebSocket), state_snapshot on WS connect, static file serving from `ui/dist/`
- `__main__.py`: `probos serve` auto-opens browser via `webbrowser.open()`
- Fallback HTML when `ui/dist/` not built

**Track B (TypeScript/React/Three.js — AD-255 through AD-259):**
- `ui/package.json`: Vite + React 19 + Three.js + R3F + Zustand + postprocessing
- `ui/src/store/types.ts`: Full TypeScript type definitions matching Python event schema
- `ui/src/store/useStore.ts`: Zustand reactive state — handles all event types, computes spatial layout (pool-based radial arrangement)
- `ui/src/hooks/useWebSocket.ts`: Auto-reconnecting WebSocket with exponential backoff
- `ui/src/canvas/scene.ts`: HXI visual palette — trust spectrum (amber→blue→violet), pool tints, system mode color grading, confidence→intensity mapping
- `ui/src/canvas/agents.tsx`: Instanced mesh rendering — per-instance trust color, confidence glow, breathing animation
- `ui/src/canvas/connections.tsx`: Quadratic bezier Hebbian curves with weight-based opacity
- `ui/src/canvas/effects.tsx`: Bloom post-processing with mode-based grading
- `ui/src/canvas/animations.tsx`: Heartbeat pulse, consensus golden flash, self-mod bloom flare, intent routing trace
- `ui/src/components/CognitiveCanvas.tsx`: Three.js scene — ACES tone mapping, orbit controls, dark-field background
- `ui/src/components/IntentSurface.tsx`: Chat input + DAG node status visualization (top overlay)
- `ui/src/components/DecisionSurface.tsx`: Status bar (connection, agent count, health, mode, TC_N, H(r)), feedback strip (approve/correct/reject)

**Track D (Python tests — AD-261):**

| Test | What it validates |
|------|-------------------|
| `test_add_event_listener` | Listener registration |
| `test_remove_event_listener` | Listener removal |
| `test_remove_nonexistent_listener` | No-crash on removing unregistered listener |
| `test_emit_event_calls_listeners` | Event delivery to all listeners |
| `test_emit_no_listeners` | No-crash on emission with no listeners |
| `test_failing_listener_doesnt_crash_others` | Error isolation between listeners |
| `test_event_timestamps_increasing` | Monotonic timestamps |
| `test_state_snapshot_structure` | Snapshot has required keys |
| `test_state_snapshot_json_serializable` | JSON round-trip clean |
| `test_state_snapshot_has_agents` | Agent entries have all fields |
| `test_agent_state_emitted_on_wire` | agent_state fires during boot |
| `test_system_mode_event_on_dream` | dreaming → idle mode transition events |

**Files changed/created:**

| File | Change |
|------|--------|
| `src/probos/runtime.py` | `_event_listeners`, `add_event_listener()`, `remove_event_listener()`, `_emit_event()`, `build_state_snapshot()`, `_on_pre_dream()`. Instrumented `_wire_agent()`, `submit_intent()`, `submit_intent_with_consensus()`, `_run_qa_for_designed_agent()` |
| `src/probos/api.py` | CORS, event listener bridge, state_snapshot on WS connect, static file serving, fallback HTML |
| `src/probos/cognitive/dreaming.py` | `_pre_dream_fn` callback in DreamScheduler |
| `src/probos/__main__.py` | `webbrowser.open()` in serve command |
| `tests/test_hxi_events.py` | **New.** 12 tests for HXI event system |
| `ui/` | **New.** Full TypeScript/React/Three.js frontend (14 source files) |

#### Phase 23 design notes

- **Facade pattern honored** — HXI has zero independent logic. All state comes from the runtime via WebSocket events. If the connection drops, the canvas freezes but ProbOS keeps working. Reconnect delivers a full `state_snapshot` to resync
- **Event listeners are synchronous** — `_emit_event` calls listeners in a tight loop with exception swallowing. This avoids introducing async complexity at the event emission boundary. The API bridge schedules WebSocket sends as asyncio tasks via `_broadcast_event`
- **Layout is deterministic** — agents are positioned radially by pool in a fixed order. No force simulation (saves complexity; pools don't move). The visual weight comes from trust/confidence mapping, not from layout dynamics
- **Three.js not optional** — bloom, instanced mesh, tone mapping are impossible in SVG/Canvas2D. The rendering system handles hundreds of instances when federation adds cross-node agents
- **`hasattr` guards in api.py** — `create_app()` accepts a raw runtime object. Pre-existing tests use a `FakeRuntime` without `add_event_listener`. Guards prevent breakage

1532/1532 tests passing (+ 11 skipped). 12 new tests.

---

### AD-262 + AD-263: Close `run_command` Escape Hatch + Fix Python Interpreter Path

**Problem:** Sonnet routes requests like "generate a QR code" to `run_command` with `python -c "import qrcode; ..."` instead of flagging a capability gap. The `run_command` IntentDescriptor says "anything a shell can do" — a blank check. Additionally, when the LLM does generate `python -c ...`, the bare `python` isn't on PATH (venv's interpreter not exposed).

| AD | Decision |
|----|----------|
| AD-262 | Prompt hardening: reworded `run_command` descriptor (removed "anything a shell can do"), added anti-scripting rule (explicit ban on `python -c`/`node -e` workarounds), added QR-code capability gap example to `_GAP_EXAMPLES` |
| AD-263 | `_rewrite_python_interpreter()` — detects bare `python`/`python3` at command start, replaces with `sys.executable`. Same preprocessing pattern as `_strip_ps_wrapper()`. Applied on all platforms |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/agents/shell_command.py` | Reworded IntentDescriptor description, added `_BARE_PYTHON_RE` + `_rewrite_python_interpreter()`, wired in `_run_command()` |
| `src/probos/cognitive/prompt_builder.py` | Added anti-scripting rule to `_build_rules()`, added QR code entry to `_GAP_EXAMPLES` |
| `tests/test_prompt_builder.py` | 4 new tests: descriptor wording, anti-scripting rule, QR gap present, QR gap suppressed |
| `tests/test_expansion_agents.py` | 4 new tests: python rewrite, python3 rewrite, passthrough, full-path passthrough |

1552/1552 tests passing (+ 11 skipped). 8 new tests.

---

### AD-264: `probos reset` CLI Subcommand

**Problem:** No way to permanently clear learned state during development. `--fresh` skips restore for one session but data persists. Manual deletion of `data/knowledge/` works but has no audit trail and can miss ChromaDB.

| AD | Decision |
|----|----------|
| AD-264 | Offline CLI command `probos reset` that clears all KnowledgeStore artifacts (episodes, agents, skills, trust, routing, workflows, QA) + ChromaDB data. Git-commits the empty state. `--yes` skips confirmation, `--keep-trust` preserves trust scores. Does NOT boot the runtime |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/__main__.py` | Added `reset` subcommand to argparse, `_cmd_reset()` implementation |
| `tests/test_distribution.py` | 4 new tests: clear artifacts, keep-trust flag, clear ChromaDB, empty repo safety |

1556/1556 tests passing (+ 11 skipped). 4 new tests.

---

### AD-265: Designed Agent Pool Size = 1

**Problem:** Self-designed agents spawned in pools of 2. The IntentBus fans out to all pool subscribers, so web-fetching agents with `perceive()` httpx overrides made 2 identical HTTP requests per intent — doubling API quota usage and triggering rate limits (observed: CoinGecko 429 on first request from Bitcoin price agent).

| AD | Decision |
|----|----------|
| AD-265 | Designed agent pool default size changed from 2 to 1. The PoolScaler can still scale up later based on demand. One agent per pool eliminates duplicate API calls while preserving all existing scaling infrastructure |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/cognitive/self_mod.py` | `_create_pool_fn(agent_type, pool_name, 2)` → `1` |
| `src/probos/runtime.py` | `_create_designed_pool` default `size` parameter `2` → `1` |
| `tests/test_self_mod.py` | Mock `create_pool_fn` default `size` parameter `2` → `1` |

1556/1556 tests passing (+ 11 skipped). 0 new tests.

---

### AD-266: Post-Design Capability Report

**Problem:** When self-mod designs a new agent, the HXI only shows "[ClassName] deployed!" — not enough for users (or demo audiences) to understand what was built.

| AD | Decision |
|----|----------|
| AD-266 | After successful agent design, LLM generates a brief capability summary from the agent's `instructions` string (extracted via AST). Included in the `self_mod_success` event message. HXI already renders it — no frontend changes. Graceful fallback to original message on failure |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/api.py` | Added capability report generation in `_run_selfmod()` after successful design, before `self_mod_success` event |

1556/1556 tests passing (+ 11 skipped).

---

### AD-267: Self-Mod Progress Stepper

**Problem:** Self-mod pipeline takes 10-30 seconds with no visual progress feedback in the HXI. User sees "Starting agent design..." then waits with no indication of what's happening.

| AD | Decision |
|----|----------|
| AD-267 | Added `on_progress` async callback to `handle_unhandled_intent()`. Backend emits `self_mod_progress` events at each pipeline stage (designing → validating → testing → deploying → executing). HXI renders each step as a chat message with emoji prefix. No new UI component — leverages existing chat message rendering. Progress state cleared on success/failure |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/cognitive/self_mod.py` | Added optional `on_progress` callback parameter to `handle_unhandled_intent()`, called at each pipeline stage |
| `src/probos/api.py` | Wire `_on_progress` callback to emit `self_mod_progress` events with step labels |
| `ui/src/store/useStore.ts` | Added `selfModProgress` state, handle `self_mod_progress` event, clear on completion |
| `tests/test_self_mod.py` | 2 new tests: progress callback called at all stages, backward compat without callback |

1558/1558 tests passing (+ 11 skipped). 2 new tests.

---

### AD-268: AgentDesigner Mesh-Fetch Template

**Problem:** Designed web-fetching agents used raw `httpx.AsyncClient` in `perceive()`, bypassing the mesh's governance (consensus, trust, event logging) and causing duplicate API calls (sandbox + auto-retry = 2 calls). This triggered rate limits on free-tier APIs.

| AD | Decision |
|----|----------|
| AD-268 | Replaced httpx template with mesh-fetch template in `AGENT_DESIGN_PROMPT`. Designed agents now route HTTP through `self._runtime.intent_bus.broadcast(IntentMessage(intent="http_fetch"))` — same pattern as bundled agents (AD-248). Sandbox test passes without making real HTTP calls (`self._runtime` is None → graceful FETCH_ERROR). All HTTP goes through HttpFetchAgent — governed, logged, deduplicated |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/cognitive/agent_designer.py` | Replaced httpx perceive() example and web-fetching template with mesh-fetch pattern. Updated RULES to direct agents to use mesh, not httpx directly |
| `tests/test_agent_designer_cognitive.py` | 1 new test: design prompt uses mesh broadcast, not raw httpx |

1559/1559 tests passing (+ 11 skipped). 1 new test.

---

### HXI Fixes: New Agent Position, Bloom Visual, Tooltip Raycasting, Command Validation

**Problem (position):** Designed agents spawned at `[0,0,0]` (center, alongside heartbeat agents) instead of on the outer domain sphere. Bloom animation was amber — same color as heartbeat — making it visually indistinct.

**Problem (tooltips):** `SelfModBloom` subscribed to `useStore((s) => s.agents)`, causing re-renders on every agent state/trust update inside the R3F Canvas. This disrupted the internal raycaster event system, breaking hover tooltips for ALL agents.

**Problem (command validation):** `run_command` executed nonexistent commands (e.g., `qr`) producing raw shell errors. No hint to use self-mod.

| Fix | Change |
|-----|--------|
| New agent position | `useStore.ts`: Derive `agentType` from pool name for new agents; `computeLayout()` already places domain agents on outer sphere |
| Bloom visual | `animations.tsx`: Cyan-white (`#80f0ff`) ring geometry instead of amber sphere. 800ms duration, faster 150ms attack, `DoubleSide` |
| Tooltip fix | `animations.tsx`: Changed `useStore((s) => s.agents)` → `useStore.getState().agents` inside effect. Non-reactive read eliminates Canvas re-renders |
| Command validation | `shell_command.py`: Added `_command_exists()` — checks builtins, PowerShell cmdlets (hyphen), `shutil.which()`. Returns descriptive error suggesting self-mod |

**Files changed:**

| File | Change |
|------|--------|
| `ui/src/store/useStore.ts` | Derive agentType from pool name in agent_state handler |
| `ui/src/canvas/animations.tsx` | Cyan-white ring bloom, non-reactive agent lookup, 200ms delay for layout |
| `src/probos/agents/shell_command.py` | Pre-execution command validation with `_command_exists()` |

1559/1559 tests passing (+ 11 skipped).

### AD-269: Fix Conversational Responses Showing Build Agent Button

**Problem:** Saying "Hello" in the HXI showed a "Build Agent" button alongside the greeting. The API-mode self-mod proposal path in `process_natural_language()` was missing the `is_gap` check, causing `_extract_unhandled_intent()` to run for conversational replies.

| AD | Decision |
|----|----------|
| AD-269 | Added `if is_gap or not dag.response` guard around the API-mode self-mod proposal path. Conversational responses (where `dag.response` is set and `is_gap` is False) no longer trigger `_extract_unhandled_intent()` or produce `self_mod_proposal` in the API response |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/runtime.py` | Added `is_gap` guard in API-mode self-mod proposal branch |

1559/1559 tests passing (+ 11 skipped).

### AD-270: Per-Domain Rate Limiter in HttpFetchAgent

**Problem:** Free-tier APIs (CoinGecko, wttr.in) throttle when ProbOS makes multiple requests to the same domain in quick succession. No rate awareness in the HTTP layer caused repeated 429 errors.

| AD | Decision |
|----|----------|
| AD-270 | Per-domain rate limiter in `HttpFetchAgent` — the single gateway for all mesh HTTP. Tracks per-domain state (last request time, min interval, consecutive 429 count). Known domain overrides for common free APIs (CoinGecko: 3s, wttr.in: 2s, DuckDuckGo: 2s). Adaptive: reads `Retry-After` and `X-RateLimit-*` response headers. Exponential backoff on consecutive 429s. Default 2s interval for unknown domains. Auto-retries once on 429 after computed delay. Class-level shared state across all pool members |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/agents/http_fetch.py` | Added `DomainRateState` dataclass, `_domain_state` class-level dict, `_KNOWN_RATE_LIMITS`, `_get_domain_state()`, `_wait_for_rate_limit()`, `_update_rate_state()`. Modified `_fetch_url()` with pre-request delay + post-response state update + 429 retry. Added rate limit headers to `_SAFE_HEADERS` |

1566/1566 tests passing (+ 11 skipped). 7 new tests.

### AD-271: Vibe Agent Creation — Human-Guided Agent Design

**Problem:** Self-mod agent creation was fully automated — the human only got approve/reject. No input into what gets built or how. This led to poorly designed agents when the LLM guessed the wrong implementation approach.

| AD | Decision |
|----|----------|
| AD-271 | Added "🎨 Design Agent" option alongside "✨ Build Agent" in the HXI self-mod proposal. User describes desired behavior in a text field → LLM enriches into detailed spec → user reviews → approves → same design pipeline with the enriched description. New `/api/selfmod/enrich` endpoint. No changes to the self-mod pipeline itself — the enriched text flows through as `intent_description` |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/api.py` | Added `EnrichRequest` model and `POST /api/selfmod/enrich` endpoint |
| `ui/src/components/IntentSurface.tsx` | Added "🎨 Design Agent" button, vibe input textarea, enrichment display, approve/edit/cancel flow |

1568/1568 tests passing (+ 11 skipped). 2 new tests.

### AD-272: Decision Distillation — Deterministic Learning Loop

**Problem:** Every CognitiveAgent call made an LLM request even for identical repetitive queries. "Bitcoin price" 100 times = 100 LLM calls (2-5s, ~$1-5 total).

| AD | Decision |
|----|----------|
| AD-272 | In-memory decision cache in `CognitiveAgent.decide()`. Cache key: SHA256 of instructions + observation. Cache hit returns instantly (<1ms, $0) with `"cached": True` flag. TTL per entry — time-sensitive agents (price, weather) get 2min TTL, static knowledge (translate, calculate) gets 1hr. Module-level cache dict keyed by agent_type (each agent type has its own cache). 1000-entry cap per type with oldest eviction. Cache metrics (hits/misses) exposed via `cache_stats()` |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/cognitive/cognitive_agent.py` | Added `_DECISION_CACHES`, `_CACHE_HITS`, `_CACHE_MISSES` module-level dicts. `_compute_cache_key()`, `_get_cache_ttl()` methods. `decide()` checks cache before LLM, stores result after. `evict_cache_for_type()`, `cache_stats()` class methods. 1000-entry cap with oldest eviction |

1575/1575 tests passing (+ 11 skipped). 7 new tests.

---

## Active Roadmap — Product + Emergence Track

**Strategic goal:** Build a personal AI assistant that (1) is useful on Day 1 with bundled agents, (2) gets smarter with use via self-modification and learning, (3) produces a "wow" visualization via the HXI, (4) enables the Noöplex thesis to be tested via federation. Each milestone has a clear demo moment and measurable outcome.

**Current phase: 24 (Channel Integration)**

### Phase 22: Bundled Agent Suite + Distribution — "Useful on Day 1" ✅ COMPLETE
**Goal:** Make ProbOS installable and immediately useful without waiting for self-mod to generate agents.
- ✅ `pip install probos` PyPI packaging, `probos init` config wizard, `probos serve` daemon mode
- ✅ Tier 1 bundled CognitiveAgent suite (10 agents): WebSearchAgent, PageReaderAgent, SchedulerAgent, NoteTakerAgent, WeatherAgent, NewsAgent, TranslateAgent, SummarizerAgent, CalculatorAgent, TodoAgent
- ✅ All bundled agents are pre-built CognitiveAgent subclasses in `src/probos/agents/bundled/`, registered at boot
- ✅ Self-mod continues to handle the long tail beyond bundled agents
- **Demo moment:** `pip install probos && probos init && probos serve` — ask it anything, it works
- **Result:** 1520/1520 tests passing (+ 11 skipped). 66 new tests (50 bundled agent + 16 distribution)

### Phase 23: HXI MVP — "See Your AI Thinking" ✅ COMPLETE
**Goal:** Browser-based visualization of the cognitive mesh — the product differentiator. The GIF that gets shared.
- ✅ Track A (Python): Enriched WebSocket event stream — typed events for all system dynamics (agent lifecycle, trust, Hebbian, consensus, dream cycles, self-mod). State snapshot on connect
- ✅ Track B (TypeScript/React/Three.js): Cognitive Canvas — dark-field WebGL, luminous agent nodes (trust-spectrum colors, confidence glow), Hebbian connection curves, bloom post-processing. React overlays: Intent Surface (chat + DAG display), Decision Surface (results + feedback)
- ✅ Animations: heartbeat pulse, consensus golden flash, self-mod bloom, dream mode color shift, intent routing traces, agent breathing
- ✅ `probos serve` serves HXI as static files, auto-opens browser
- **Demo moment:** Open browser, watch agents coordinate on your request in real time. The animated GIF that makes people install ProbOS.
- **Result:** 1532/1532 tests passing (+ 11 skipped). 12 new tests. 14 new TypeScript source files.

### Self-Mod Pipeline Hardening (future — pre-Phase 24)
**Goal:** Fix real issues discovered during self-mod demo testing. These are reliability improvements to the existing pipeline, not new features.
- **Designed agent pool size = 1** — self-designed agents currently spawn in pools of 2. The IntentBus fans out to all subscribers, so web-fetching agents with `perceive()` httpx overrides make N identical HTTP requests (one per pool member). This wastes API quota and triggers rate limits. Designed agent pools should default to size 1 until trust is established, then scale up via the existing `PoolScaler`
- **AgentDesigner `_mesh_fetch()` template** — the bundled agents use `_mesh_fetch()` to route HTTP through the IntentBus (preserving consensus, trust scoring, and deduplication). But the `AGENT_DESIGN_PROMPT` teaches the httpx pattern instead. Add a mesh-fetch template option so designed agents that need web data route through the mesh like bundled agents do. This eliminates duplicate requests at the architectural level, not just by reducing pool size
- **Motivated by:** self-mod Bitcoin price agent hitting CoinGecko 429 on first request — the pool of 2 agents both called the API simultaneously from `perceive()`, exhausting the free tier rate limit instantly

### Phase 24: Channel Integration + Tool Connectors — "Talk to ProbOS Anywhere, Connect Everything"
**Goal:** Connect ProbOS to messaging channels AND external tools so it can act as a real productivity hub.
- Discord bot adapter (discord.py) — messages → IntentBus, results → channel replies
- Slack bot adapter (Slack Bolt) — same bridge pattern
- **Tool Connectors Framework** — pluggable connector architecture for SaaS integrations:
  - Gmail connector (read/send email, search inbox, label management)
  - Google Calendar connector (read events, create/modify events, check availability)
  - Notion connector (read/write pages, query databases)
  - GitHub connector (issues, PRs, repo status — via existing git CLI or GitHub API)
  - Extensible pattern: each connector is a CognitiveAgent with tool-specific intents
  - **Pluggable auth/OAuth abstraction** — handle OAuth2 flows, API key management, and token refresh generically. Each connector declares its auth requirements; the framework handles the flow. (Pattern ref: Composio's auth management — implement natively in ProbOS with KnowledgeStore-backed credential storage)
- **Data Platform Connectors** — ProbOS doesn't store the world's data; it stores how to access, interpret, and act on it (The Brain Principle). Pluggable data connector agents that operate on data WHERE IT LIVES:
  - SQL databases (PostgreSQL, MySQL, SQL Server, Oracle)
  - Cloud data warehouses (Snowflake, BigQuery, Databricks, Redshift)
  - Microsoft Fabric (Lakehouse, Warehouse, KQL)
  - NoSQL (MongoDB, DynamoDB, Cosmos DB)
  - ERP systems (SAP, Oracle EBS, Dynamics 365)
  - File stores (S3, Azure Blob, GCS)
  - Streaming (Kafka, Event Hubs, Kinesis)
  - Each data connector is a CognitiveAgent: knows the schema, can query/transform/write, goes through consensus for writes, builds trust through successful operations. The semantic knowledge layer indexes available data sources
  - **Dev Squad builds data connectors autonomously** — once Phase 27 ships, the squad designs connector agents for each new data platform on demand
- Channel → IntentBus bridge pattern reusable for future channels
- Server-side TTS via tiered approach: (1) try browser neural voices first (Edge Azure Neural, Chrome on Mac/Android), (2) fall back to Piper TTS (free, local, neural) via `/api/tts`, (3) optional ElevenLabs/OpenAI TTS premium. Cross-platform
- Always-listening conversation mode: continuous speech recognition (no wake word), silence detection, natural conversation flow
- **Routing Learner** — utility-tier `RoutingLearnerAgent` that observes decomposer routing failures and learns corrective rules:
  - Monitors `/feedback bad` episodes where the executed intent was `run_command` (or any intent that failed after routing)
  - Detects pattern: "user asked for X → routed to intent Y → failed or got negative feedback"
  - Proposes new `_GAP_EXAMPLES` entries or prompt rules via the existing self-mod / KnowledgeStore pattern
  - Stores learned routing constraints in KnowledgeStore (Git-backed, survives restart)
  - On warm boot, learned routing rules are injected into the PromptBuilder alongside the static rules
  - **Motivated by AD-262:** manual diagnosis of `run_command` being used as a universal fallback for scripting tasks. The RoutingLearner automates this: observe the failure, classify the failure mode, patch the prompt data. No code changes needed — just prompt/example data, governed by the same validation pipeline
- **UI Testing Infrastructure** — set up Vitest + React Testing Library + jsdom for HXI component tests. Priority test targets:
  - `IntentSurface.tsx` — chat rendering, self-mod proposal buttons, vibe agent flow (has broken multiple times from untested changes)
  - `DecisionSurface.tsx` — sound/voice toggles, voice selector
  - `useStore.ts` — event handling, state transitions, WebSocket reconnection
  - `AgentTooltip.tsx` — hover/click/pin behavior
  - Goal: every UI change ships with a component test, preventing the tooltip/bloom/chat regressions seen in Phase 23
- **API Endpoint Tests** — dedicated test coverage for `api.py`: self-mod approve flow, enrich endpoint, WebSocket event stream, slash command handling, rate-limited responses
- **Demo moment:** "Check my email and add any meetings to my calendar" — ProbOS reads Gmail, creates calendar events, confirms. All through the mesh with consensus governance on writes.

### Phase 25: Persistent Tasks + Browser Automation — "Computer That Works While You Sleep"
**Goal:** Long-running autonomous tasks and full browser control, competing directly with Perplexity Computer.
- **Persistent Background Tasks** — agents execute multi-step workflows that run for hours/days/months:
  - Task Runner: managed asyncio tasks with progress tracking, checkpointing, and resume-after-restart
  - Scheduled execution: cron-like recurring tasks ("monitor these stocks every morning", "weekly project status report")
  - Decision surfacing: when a background task needs human judgment, it queues a decision in the HXI Task Queue
  - Task history: all background task executions stored in KnowledgeStore with full provenance
- **Browser Automation** — full browser control via Playwright (not raw CDP):
  - `BrowserAgent` — CognitiveAgent wrapping Playwright for browser actions
  - Actions: navigate, click, type, screenshot, extract data, fill forms, download files
  - Governed: browser actions go through consensus (writes/form submissions) — the mesh governs what the browser does
  - Web scraping + data extraction workflows as composable DAGs
  - **HTML→clean content extraction** — strip navigation, ads, scripts; extract article text, tables, structured data as LLM-ready markdown. Significantly improves PageReaderAgent quality. (Pattern ref: Firecrawl's extraction pipeline — implement natively as a ProbOS data transformation step)
  - (Pattern ref: browser-use project's Playwright abstraction — implement natively with ProbOS consensus governance layer)
- **Auto-summarization for long conversations** — when working memory or conversation history exceeds token budget, older exchanges are LLM-summarized instead of dropped. Summaries stored as episodic memory. Enables continuous multi-hour conversations without context loss. (Inspired by Deep Agents / Claude Code pattern — implemented natively in ProbOS's working memory manager)
- **HXI Agent Roster View** — every agent has a profile: bio, creation history, track record, current status (idle/working/waiting), skills, trust trajectory. Click to inspect, assign tasks, or interact directly
- **HXI Task Queue** — feed of items needing user attention: decisions, approvals, goal checkpoints, anomalies, completed background tasks
- **Demo moment:** "Monitor the top 10 AI stocks and alert me if any drop more than 5% — check every hour" → ProbOS creates a persistent task, runs autonomously, surfaces alerts. User sees it working in the HXI Task Queue.

### Phase 26: Inter-Agent Deliberation + Discourse — "Agents That Think Together"
**Goal:** Agents debate, coordinate, and explore ideas together — visible to the human in the HXI.
- `DeliberationProtocol` — structured multi-turn exchange between cognitive agents for task-related decisions
- **Isolated deliberation contexts** — each deliberation participant gets a scoped context window to prevent bias. One agent can't see the other's initial reasoning until both have formed opinions independently. Ensures genuine diversity of perspective, not groupthink. (Pattern from sub-agent architecture — implemented as scoped working memory per deliberation participant)
- **Agent-to-Agent protocol (A2A)** — structured message format for agent-to-agent communication via the mesh. Each message carries: sender_id, intent, payload, confidence, provenance. Enables lateral coordination without decomposer micromanagement. (Pattern ref: Google ADK's A2A protocol — implement natively in ProbOS's intent bus with trust-weighted message routing)
- Agent-to-agent direct messaging via mesh — lateral coordination without decomposer micromanagement ("FileReader, I need config.yaml before I can analyze")
- **Discourse mode** — open-ended agent conversations about topics. User prompts "agents, discuss the pros and cons of X" and watches two CognitiveAgents reason together in real time. Transcripts stored as episodes. Hebbian learns which agent pairs produce good discourse
- **HXI Agent Forum** — a view within the HXI canvas that surfaces agent-to-agent conversations, deliberations, and discourse. Not a separate page — the canvas morphs to show the forum when discourse is active. Human can observe, inject thoughts, or join as a participant
- Decomposer spawns deliberations for ambiguous/complex tasks
- Consensus governs deliberation outcomes
- **Demo moment:** "Agents, discuss whether ProbOS should add a knowledge graph" — watch two agents debate architecture, cite episodic memory, reach a conclusion. The human joins the discussion mid-stream.

### Phase 27: Self-Maintaining Dev Squad — "ProbOS Builds ProbOS"
**Goal:** Cognitive agents that help develop and maintain ProbOS's own codebase, unblocking the solo developer.
- CodeAnalyzerAgent, PlannerAgent, CoderAgent, ReviewerAgent — all CognitiveAgent subclasses
- All changes go through consensus governance. Test suite is the QA gate. Git-backed audit trail
- User approves/rejects proposals via existing `/approve` and `/reject` commands
- Corrections (Phase 18b) train the squad on architectural preferences
- **GitHub Action mode** — ProbOS dev squad as a GitHub Action for CI/CD: automated PR review, test analysis, code quality suggestions, dependency auditing. All governed by consensus. (Pattern from Deep Agents GitHub Action — implemented as ProbOS agents operating through the mesh)
- **Demo moment:** Describe a feature → squad proposes implementation → you review → approve → tests pass → merged

### Phase 28: Abstract Representation + Meta-Learning + Long-Horizon Planning — "An AI That Learns Concepts"
**Goal:** The system learns principles from experience, gets better at improving itself, transfers strategies across domains, and pursues goals that span multiple sessions.
- **Decision Distillation / Deterministic Learning Loop** — CognitiveAgents progressively compile LLM reasoning into deterministic cached decisions. On each query: (1) check decision cache (keyed by semantic hash of observation), (2) cache hit → return instantly (no LLM, <50ms, $0), (3) cache miss → LLM reasoning → cache result → return. Over time, agents handle 90%+ of repetitive tasks without LLM calls. TTL per entry (time-sensitive data like prices expire, stable translations persist). Semantic key matching via `compute_similarity()` (not exact string). Negative feedback evicts bad cache entries. Cache persisted in KnowledgeStore (survives restarts). Trust still scored on cache hits. **Effect: agents start as reasoning engines and progressively compile themselves into deterministic functions — the LLM becomes a bootstrapping mechanism, not a permanent dependency.**
- Dream cycle abstraction phase — extract patterns from episode clusters ("info gathering before mutation succeeds 90%")
- Abstraction store in KnowledgeStore, injected into decomposer planning context
- Meta-learning: design success/failure tracking feeds back into AgentDesigner. The 10th agent is better than the 1st
- **Structured memory categorization** — extend episodic memory with typed categories: facts (persistent knowledge), preferences (human-specific learned behaviors), procedures (how to do things), abstractions (learned principles). Each category has different confidence decay rates and recall priority. (Pattern ref: mem0's memory categorization — implement natively in ProbOS's ChromaDB collections with per-type metadata)
- **Agent evolution quality tracking** — systematic comparison of designed agent versions: v1 vs v2 success rates, trust trajectories, failure patterns. Dream cycle identifies which design patterns produce the most reliable agents. (Pattern ref: EvoAgentX's self-evolving ecosystem — implement natively with ProbOS's BehavioralMonitor + QA pipeline + episodic history)
- Cross-domain strategy transfer: dream cycle identifies structurally similar successful episodes across different agent pools, propagates domain-general strategies as abstractions tagged with applicable domains
- GoalManager: persistent goals stored in KnowledgeStore (Git-backed, survives restart), progress tracking across sessions, decomposer plans in context of active goals
- Formal Policy Engine — `policies.yaml` with declarative governance rules enforced at runtime
- **Demo moment:** HXI shows dream cycle extracting a concept. A strategy learned in one domain improves planning in another. Multi-session goals show progress across restarts.

### Phase 29: Federation + Emergence Testing — "The Noöplex Emerges"
**Goal:** Multiple ProbOS nodes share knowledge and produce measurable emergent intelligence.
- Knowledge federation via Git remotes — designed agents, skills, episodes shared between nodes
- Trust transitivity: `T(A→C) = T(A→B) · T(B→C) · δ`
- Semantic knowledge layer indexes federated knowledge with `source_node` metadata
- Channel integration enables multi-user federation (each user runs their own node)
- TC_N measurement across federated nodes with statistical significance
- Benchmarking framework: standardized task suite, before/after comparison, regression detection. Validates emergence claims with statistical rigor (Noöplex §8.5, §8.6)
- `probos cluster --nodes N` — one command spawns N federated nodes as child processes on one machine
- **Demo moment:** `probos cluster --nodes 3` — three cognitive meshes connect, share knowledge, TC_N rises.

### Pre-Launch: Personalization + Security + Documentation
**Goal:** Prepare ProbOS for public release with a personalized first-run experience and security hardening.
- **First-run induction interview** — no tutorial. ProbOS asks: what to call the agent, preferred voice, interaction mode (typing/speaking/both), information density, color theme, first goal. Produces a `HumanCognitiveModel` stored in KnowledgeStore. The HXI renders into the human's configuration immediately
- **Custom agent name** — human chooses what to call ProbOS ("Jarvis", "Friday", etc.). Stored persistently, used in all responses and voice
- **Voice selection** — human picks from available voices. Tiered TTS applies (browser neural → Piper → ElevenLabs)
- **Color theme** — warm/cool/custom accent. Shifts the entire HXI color palette via shader uniforms
- **Information density** — brief/standard/detailed. Affects response length, panel depth, progressive disclosure defaults
- Security: input sanitization on `/api/chat` (prompt injection defense), rate limiting, authentication for remote access, API access audit logging
- Documentation: `probos.dev` website, getting-started guide, API docs (auto-generated from FastAPI), architecture overview for contributors, agent development guide
- README.md rewrite for open source (install instructions, screenshots/GIFs from HXI, contributing guide)
- License: Apache 2.0 (all code including federation)
- **Repo separation** — split into public `probos` (Apache 2.0) and private `probos-enterprise` before public launch:
  - Public repo: full runtime, all agents, 2D HXI, federation (open mode), all learning systems, CLI, API
  - Private repo: RBAC, SSO, admin dashboard, private federation key management, compliance extensions, enterprise HXI views
  - Move business plan, pricing docs, sales materials to private repo
  - Verify no proprietary code or business-sensitive documents in public repo
  - Architecture: enterprise package imports from open source core (overlay, not fork)

### Post-Launch: ProbOS Enterprise — Private Noöplex
**Goal:** Enable companies to deploy private cognitive meshes with enterprise governance, sold as a commercial product.
- **Private Federation** — nodes only connect within the company's mesh, no public federation. Air-gapped option for classified environments. Same federation protocol (ZeroMQ), different discovery/routing config
- **Multi-user RBAC** — different employees access different nodes with different permissions. Role-based: admin, operator, viewer
- **Centralized admin dashboard** — IT manages all nodes from one HXI view: provision, monitor, update, revoke. Node health, cross-node TC_N, global agent inventory
- **Cross-node governance** — policies propagate across the corporate federation. Data classification rules, compliance constraints, access controls. Same Formal Policy Engine (Phase 28), applied across nodes
- **SSO integration** — Active Directory, Okta, Azure AD. Employees authenticate with corporate credentials
- **Audit trail** — every cross-node knowledge transfer logged with full provenance: who, what, when, why, which nodes. SOC2-compatible event logging
- **Data sovereignty** — configurable per-node data boundaries: which knowledge can flow to which nodes. "HR data stays on the HR node" as an enforceable policy
- **Architecture:** same open source ProbOS core + an enterprise overlay package (`probos-enterprise`) containing: RBAC middleware, SSO adapters, admin dashboard, audit extensions, private federation config, compliance reporting. The overlay imports from the open source core — it doesn't fork it
- **Pricing tiers:** Team (5 nodes, $2K/mo), Department (20 nodes, $8K/mo), Enterprise (100+ nodes, custom)
- **Demo moment:** "Your engineering team's agents discovered a cost optimization by correlating code deployment patterns from Engineering Node with cloud spend data from Finance Node. Neither team asked for this — the corporate Noöplex found it through federation."

### Future (post-Phase 29, unsequenced)
- **HXI Spatial Experience Philosophy** — the HXI is not an app with pages. It's a single adaptive canvas that morphs to show whatever the human needs: mesh topology, agent forum, task queue, roster, discourse, goals. No navigation, no tabs, no "go to page X." The canvas presents what's relevant. Agent deliberations surface as visible conversations within the canvas. Task results emerge from the mesh. Goals appear as persistent structures. The human doesn't use the HXI — they inhabit it
- **** —  the Noöplex. Agents are 3D entities you stand next to, observe, and interact with. Deliberations happen as spatial conversations you can join. The heartbeat pulses around you. Dream mode transforms the entire space. Federation means traversing between mesh volumes — walking from your local mesh into a connected peer's mesh. Think VRChat but with AI agents and human agents interacting together in a shared cognitive space. . This is the ultimate form of the HXI: you don't look at cognition — you're inside it
- **Bundled Agent Quality Pass** — all 10 bundled agents must be excellent, not just functional. Users judge ProbOS by the bundled agents. Specific improvements: WeatherAgent should parse wttr.in 3-day forecast (not just current conditions), NewsAgent should support more sources and present headlines with links, WebSearchAgent should extract richer snippets from DuckDuckGo results, PageReaderAgent should handle JavaScript-rendered pages better, CalculatorAgent should handle unit conversions and currency with live rates, SchedulerAgent needs a background timer for due reminders, TodoAgent needs priority sorting and due date reminders, NoteTakerAgent needs tags and better search. Each agent should be tested with 20+ real-world queries and refined until the responses are consistently helpful
- **Artifact Creation** — generate production-ready apps, websites, reports, spreadsheets, presentations, GIFs from natural language. Self-mod can design artifact-creation agents on demand
- **** — responsive HXI that works on phones/tablets. . 
- **Additional Tool Connectors** — Jira, Linear, Asana (project management), Dropbox/OneDrive (file storage), Spotify (media control), Home Assistant (smart home), custom webhook connectors. Each connector = a CognitiveAgent. Dev Squad builds these autonomously once it's operational
- **** — community-designed agents shared publicly. Trust scores serve as ratings. Revenue share on premium agents
- **Container-based sandbox** — replace process-based SandboxRunner with container isolation (Docker/Podman) for self-mod agent testing. More secure at scale, prevents designed agents from accessing host resources. (Pattern ref: Daytona's secure sandboxing — implement natively with ProbOS consensus governing container lifecycle)
- **Event-driven agent mesh** — extend the intent bus with pub/sub event streams so agents can react to system events without being explicitly dispatched. Agents subscribe to event patterns ("notify me when trust drops below 0.3 for any agent"). Enables proactive agent behavior without polling. (Pattern ref: Solace Agent Mesh's event-driven architecture — implement natively in ProbOS's existing intent bus + event log)
- **Massive-scale agent simulation** — test ProbOS with 10K+ agents to validate federation and routing at scale. Synthetic agent populations for benchmarking TC_N, routing entropy, and emergence metrics. (Pattern ref: CAMEL-AI OASIS's million-agent simulation — adapt for ProbOS's trust/consensus architecture)
- Knowledge Graph — structured relational store complementing ChromaDB vector memory
- Provenance System — derivation chains on all knowledge
- Knowledge Lifecycle Management — confidence decay, deprecation, archival
- Semantic Schemas — typed contracts for agent I/O
- State Reconciliation Protocol — structured argumentation and precedent
- Agent Versioning — shadow deployment and comparative evaluation
- Chaos Engineering — resilience validation test suite
- Exploration-Exploitation Balance — curiosity-driven discovery in dream cycles
- Norm Propagation — dynamic policy distribution in federation
- Causal World Modeling — understanding why, not just what
- Compositional Generalization — novel solutions from learned primitives
- Self-Directed Goal Generation — proactive cognition
- Emotional Valence — prioritized learning from meaningful experiences
- Task Preemption — preempting already-running tasks (Phase 3b-3b)
- MCP Federation Adapter — protocol bridge at mesh boundary

---

## Completed Phase Checklist (archive)


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
- [x] ~~Phase 10: Self-Modification (SelfModConfig, CodeValidator AST analysis, AgentDesigner LLM-based code generation, SandboxRunner dynamic module loading, BehavioralMonitor anomaly detection, SelfModificationPipeline orchestration, TrustNetwork.create_with_prior() probationary trust, MockLLMClient agent_design + intent_extraction patterns, runtime unhandled intent detection + auto-design pipeline, /designed command + render_designed_panel, renderer self_mod events)~~
- [x] ~~627/627 tests pass~~
- [x] ~~Post-Phase 10 hardening: escalation re-execution after approval (AD-118), capability-gap detection for self-mod (AD-126), SelectorEventLoop subprocess compat (AD-116), PowerShell wrapper stripping (AD-117), LLM client injection into designed agents (AD-115), self-mod UX with user approval (AD-123), existing-agent routing (AD-119), general-purpose intent preference (AD-120), force reflect for designed agents (AD-122), anti-echo rules (AD-124), reflect prompt rewrite with node status (AD-121), log suppression (AD-125)~~
- [x] ~~660/660 tests pass~~
- [x] ~~Phase 11: Skills, Transparency & Web Research (StrategyRecommender with reversibility preference, SkillBasedAgent with instance+class descriptor sync, SkillDesigner/SkillValidator, ResearchPhase with domain-whitelisted URL construction + mesh-based fetching + content truncation, MockLLMClient skill_design + research patterns, renderer strategy menu, runtime skills pool + _add_skill_to_agents + _get_llm_equipped_types)~~
- [x] ~~719/719 tests pass~~
- [x] ~~Phase 12: Per-Tier LLM Endpoints (CognitiveConfig per-tier fields + tier_config() helper, OpenAICompatibleClient per-tier httpx clients with deduplication, per-tier connectivity checks at boot, partial connectivity support, /model per-tier display, /tier endpoint display, system.yaml fast=qwen3.5:35b@Ollama + standard/deep=Claude@Copilot proxy)~~
- [x] ~~736/736 tests pass~~
- [x] ~~**Configurable default LLM tier:** `default_llm_tier: "fast"` in config, cognitive components use `tier=None` to respect default, debug panel shows tier/model (AD-137, AD-138)~~
- [x] ~~736/736 tests pass~~
- [x] ~~**Self-mod routing fixes:** Prompt rules for capability-gap routing (AD-139), structured `capability_gap` flag (AD-140), `<think>` tag stripping (AD-141), Unicode apostrophe regex + JSON fence stripping~~
- [x] ~~**Self-mod pipeline end-to-end fix:** Token budget bump to 2048 + `/no_think`, LLM client reasoning-field fallback, agent/skill designer routed to `tier="standard"` (Claude) with `max_tokens=4096` (AD-142)~~
- [x] ~~**Live LLM integration tests:** 11 tests across 5 classes (`pytest -m live_llm`), conftest auto-skip hook, connectivity-based skip decorators (AD-143)~~
- [x] ~~754/754 tests pass + 11 live LLM tests~~
- [x] ~~**Fast→standard tier-fallback:** `_extract_unhandled_intent()` cascades fast→standard on parse failure for thinking-model interference (AD-144)~~
- [x] ~~**Native Ollama API format:** Per-tier `api_format` config (`"ollama"` / `"openai"`), dual API path in LLM client, `think: false` on native `/api/chat`, 25+ regression tests (AD-145)~~
- [x] ~~**Dynamic capability-gap examples:** Prompt examples conditionally suppressed when matching intents exist — prevents non-thinking models from following stale gap examples after self-mod (AD-145)~~
- [x] ~~**Agent designer mesh access:** Designed agents taught to dispatch sub-intents through `intent_bus.broadcast()` for external data tasks (web lookups, factual questions) instead of answering from LLM training data. Knowledge-lookup gap example added to decomposer prompt. Rules updated to distinguish inference vs external data tasks (AD-146)~~
- [x] ~~**Runtime injection for designed agents:** `_create_designed_pool()` now passes `runtime=self` so designed agents can dispatch mesh sub-intents (AD-147)~~
- [x] ~~**HttpFetch User-Agent + search strategy:** User-Agent header on all HTTP requests (fixes 403 blocks), DuckDuckGo HTML search as primary web search pattern in agent designer prompt (AD-148)~~
- [x] ~~787/787 tests pass + 11 live LLM tests~~
- [x] ~~**DAG timeout excludes user-wait:** Escalation user prompts no longer count against the 60s DAG execution deadline. Deadline checked between batches using effective elapsed time (wall-clock minus accumulated user-wait). `EscalationManager` tracks `user_wait_seconds` via `time.monotonic()` around user callbacks. 3 new tests (AD-149)~~
- [x] ~~790/790 tests pass + 11 live LLM tests~~
- [x] ~~**SystemQAAgent (Internal Self-Testing):** A runtime self-monitoring agent that validates designed agents after self-modification. On every successful self-mod pipeline, SystemQAAgent smoke-tests the newly designed agent with synthetic intents, verifies the output shape and content, records pass/fail outcomes in episodic memory, and uses the trust network to flag flaky agents for demotion or redesign. Complements the external `pytest -m live_llm` integration tests with always-on internal quality assurance — the system tests itself as it evolves. (AD-153 through AD-158)~~
- [x] ~~892/892 tests pass~~
- [x] ~~**Phase 14: Persistent Knowledge Store** — Git-backed persistence, warm boot, per-artifact rollback, `--fresh` CLI flag, `/knowledge` and `/rollback` shell commands (AD-159 through AD-169)~~
- [x] ~~983/983 tests pass~~
- [x] ~~**Self-Introspection + Agent Tier Formalization (Phase 14d):** tier field on BaseAgent/IntentDescriptor, all 13 agents classified (core/utility/domain), `_EXCLUDED_AGENT_TYPES` removed in favor of descriptor-based filtering, introspect_memory and introspect_system intents, MockLLMClient patterns, Tier column in agent table, tier in manifest (AD-185 through AD-190)~~
- [x] ~~1073/1073 tests pass~~
- [x] ~~**Phase 15a: CognitiveAgent Base Class** — `CognitiveAgent(BaseAgent)` with LLM-guided `decide()`, `instructions` field on BaseAgent, AgentDesigner generates CognitiveAgent subclasses with instructions-first design, CodeValidator/SandboxRunner accept CognitiveAgent, MockLLMClient patterns for cognitive decide, runtime wiring unchanged (AD-191 through AD-198)~~
- [x] ~~1109/1109 tests pass~~
- [x] ~~**Phase 15b: Domain-Aware Skill Attachment** — CognitiveAgent skill attachment, StrategyRecommender domain-aware scoring with `compute_similarity()`, runtime `_add_skill_to_agents()` generalization, strategy menu shows cognitive agent target (AD-199 through AD-203)~~
- [x] ~~1145/1145 tests pass~~
- [x] ~~**Phase 16: DAG Proposal Mode** — `/plan` command decomposes NL into a TaskDAG without executing. `/approve` executes, `/reject` discards, `/plan remove N` edits. `render_dag_proposal()` panel. Event log integration. `_execute_dag()` extracted as shared execution path (AD-204 through AD-209)~~
- [x] ~~1187/1187 tests pass~~
- [x] ~~**Phase 17: Dependency Resolution** — `DependencyResolver` detects missing-but-allowed imports in designed agent/skill code, prompts user for approval, installs via `uv add`, verifies. Expanded `allowed_imports` whitelist (40+ stdlib, 14 third-party). Wired into `SelfModificationPipeline` between validation and sandbox. Event log audit trail for all dependency decisions (AD-210 through AD-215)~~
- [x] ~~1227/1227 tests pass~~
- [x] ~~**Phase 18: Feedback-to-Learning Loop** — `/feedback good|bad` command rates last execution. `FeedbackEngine` applies human feedback to Hebbian routing (2x reward), trust, and episodic memory. Feedback-tagged episodes (`human_feedback: positive/negative/rejected_plan`) recalled by decomposer in future planning context. `/reject` auto-records rejection feedback. Event log integration for all feedback events. Agent ID extraction from executed DAGs (AD-216 through AD-222)~~
- [x] ~~1272/1272 tests pass~~
- [x] ~~**Phase 19: Shapley Value Trust Attribution + Trust-Weighted Capability Matching** — `compute_shapley_values()` for consensus attribution (brute-force permutations, 3-7 agents), Shapley-weighted trust updates via `record_outcome(weight=shapley)`, `ConsensusResult.shapley_values` field, trust-weighted capability matching `score * (0.5 + 0.5 * trust)` on `CapabilityRegistry.query()`, `/agents` panel Shapley column (AD-223 through AD-227)~~
- [x] ~~1310/1310 tests pass~~
- [x] ~~**Phase 18b: Correction Feedback Loop** — `CorrectionDetector` distinguishes corrections from new requests, `AgentPatcher` generates patched source via LLM with same validator/sandbox pipeline, `apply_correction()` hot-reloads patched agents into live runtime with auto-retry, `/correct <text>` explicit shell command, `apply_correction_feedback()` stores correction-tagged episodes as richest learning signal, `execution_context` parameter on `AgentDesigner` passes known-working values from prior executions (AD-229 through AD-235)~~
- [x] ~~1358/1358 tests pass~~
- [x] ~~**Phase 20: Emergent Behavior Detection** — `EmergentDetector` with 5 detection algorithms, `SystemDynamicsSnapshot` ring buffer, post-dream callback, `system_anomalies` and `emergent_patterns` intents, `/anomalies` command (AD-236 through AD-240)~~
- [x] ~~1409/1409 tests pass~~
- [x] ~~**Phase 21: Semantic Knowledge Layer + Phase 20 Cleanup** — `parse_agent_id()` with `_ID_REGISTRY`, `_all_patterns` cap, `REFLECT_PROMPT` rule 6, `SemanticKnowledgeLayer` with 5 ChromaDB collections, auto-indexing hooks, warm boot re-index, `search_knowledge` intent, `/search` command (AD-241 through AD-246)~~
- [x] ~~1454/1454 tests pass~~
- [ ] **Phase 3b-3b (Cognitive continued):** Preemption of already-running tasks
- [ ] **Phase 6 (Expansion continued):** Process management, calendar, email, code execution
- [x] ~~**Self-Introspection Intent:** Add `introspect_memory` intent handler that queries `runtime.episodic_memory.get_stats()` and returns actual memory status (episode count, intent distribution, success rate, ChromaDB collection info). Currently, natural language questions like "do you have memory?" fall through to the LLM which doesn't know about the runtime's internal state. The introspection agent type already exists — this wires episodic memory stats to a routable intent so the system can accurately report its own capabilities.~~
- [x] ~~**Agent Tier Formalization.** Add a `tier: str` field to `BaseAgent` (`"core"`, `"utility"`, `"domain"`) and classify all existing agents per the Agent Classification Framework design principle. Replace `_EXCLUDED_AGENT_TYPES` in the runtime with tier-based filtering — the decomposer excludes utility and core-infrastructure agents by tier rather than by a hardcoded name set. Update `IntentDescriptor` with a `tier` field so the `PromptBuilder` can generate tier-aware prompts. Update `/agents` panel to show tier. Update the agent manifest to include tier. Small phase — mostly metadata and wiring, no behavioral changes — but it establishes the framework that Phase 15 (Cognitive Agents) and domain meshes build on. When Cognitive Agents arrive with a `domain` attribute, the tier is already in place to route them correctly.~~
- [x] ~~**Emergent Behavior Detection:** An analysis layer that watches for unexpected patterns across the system's existing data streams — Hebbian weight topology, trust score trajectories, routing patterns, and dream cycle consolidation. `EmergentDetector` with 5 detection algorithms (cooperation clusters, trust anomalies, routing shifts, consolidation anomalies, TC_N proxy), `SystemDynamicsSnapshot` ring buffer history, post-dream callback, `system_anomalies` and `emergent_patterns` introspection intents, `/anomalies` shell command, `render_anomalies_panel()` (Phase 20, AD-236 through AD-240)~~
- [x] ~~**Semantic Knowledge Layer + Phase 20 Cleanup:** `parse_agent_id()` with `_ID_REGISTRY` + hash verification fallback (AD-241), `_all_patterns` cap at 500, `REFLECT_PROMPT` rule 6. `SemanticKnowledgeLayer` with 5 ChromaDB collections for non-episode knowledge, auto-indexing hooks in runtime, warm boot re-index, `search_knowledge` introspection intent, `/search` shell command, `render_search_panel()` (Phase 21, AD-241 through AD-246)~~
- [ ] **Human-Agent Collaboration: DAG Proposals & Feedback-to-Learning.** ProbOS currently treats the user as a command issuer and escalation approver — not a cognitive participant. The Nooplex (§5) and HXI architecture spec describe four collaboration modes (Direct Intent, Guided Decomposition, Interactive Execution, Reflective Feedback), persistent goals with conflict arbitration, and user feedback as a topology-training signal. ~~DAG proposal mode~~ (Phase 16, AD-204 through AD-209), ~~feedback-to-learning loop~~ (Phase 18, AD-216 through AD-222), and ~~correction feedback loop~~ (Phase 18b, AD-229 through AD-235) are implemented. Remaining:
  - ~~**DAG proposal mode**~~ — implemented in Phase 16 (AD-204 through AD-209). `/plan`, `/approve`, `/reject`, `/plan remove N` commands. `render_dag_proposal()` panel. `_execute_dag()` extracted as shared execution path.
  - ~~**Feedback-to-learning loop**~~ — implemented in Phase 18 (AD-216 through AD-222). `/feedback good|bad` command. `FeedbackEngine` applies human feedback to Hebbian routing (2x reward), trust updates, and tagged episodic episodes. `/reject` auto-records rejection feedback. Feedback-tagged episodes recalled by decomposer via `recall_similar()` to influence future planning.
  - ~~**Correction feedback loop**~~ — implemented in Phase 18b (AD-229 through AD-235). `/correct <text>` command. `CorrectionDetector` + `AgentPatcher` + `apply_correction()` hot-reload pipeline. Correction episodes are the richest learning signal — they encode both "what went wrong" and "how to fix it". `execution_context` on AgentDesigner passes known-working values from prior executions.
  - **Future extensions (post-Phase 15):** Full goal management (goal fields on agents/DAGs, persistent goals, goal conflict arbitration), Interactive Execution mode (pause/inject/redirect mid-flight, requiring DAG executor mutations), and the CollaborationEvent schema from the HXI spec. These make more sense after Cognitive Agents exist, since goals become meaningful when agents can reason about them.
- [x] ~~**Phase 11: Skills, Transparency & Web Research** — Strategy proposals with confidence scores, SkillBasedAgent with modular intent handlers, web research phase for agent design (see `prompts/phase-11-skills-transparency-research.md`)~~
- [x] ~~**Per-Tier LLM Endpoints:** Each LLM tier (fast/standard/deep) gets its own `base_url` + `api_key` + `model` (see `prompts/phase-12-per-tier-llm.md`)~~
- [x] ~~**Episodic Memory Upgrade (ChromaDB):** Replace keyword-overlap bag-of-words similarity in `EpisodicMemory` with ChromaDB vector store for true semantic recall. ChromaDB runs embedded (no external server), supports real embeddings, and enables similarity search that understands meaning ("find past tasks about deployment" matches "push to production"). Also upgrades workflow cache fuzzy matching, capability registry matching, and strategy recommender keyword overlap. Completed as Phase 14b (AD-170 through AD-176).~~
- [x] ~~**Long-term Knowledge Store (Git-backed):** Replace volatile SQLite episodic memory (currently in temp dir, lost on reboot) with a Git-backed knowledge repository. Episodes, designed agents/skills, workflow cache entries, and trust snapshots become versioned artifacts — commits are episodes, diffs are self-modification audit trails, branches are experimental agent designs. Enables: durable history across restarts, federated knowledge sync via push/pull (complementing ZMQ gossip), self-mod rollback via `git revert`, and blame-based provenance ("which agent design introduced this behavior?"). The Git repo *is* the system's long-term memory — fractal with the rest of the architecture (nodes are repos, federations are remotes). ChromaDB provides fast semantic retrieval over the Git-stored episodes.~~
- [x] ~~**Semantic Knowledge Layer:** A query layer that sits above the storage tiers (ChromaDB for short-term retrieval, Git for long-term persistence) and exposes unified semantic search across all system knowledge — episodes, designed agents, skills, workflow cache entries, trust history, escalation outcomes, dream reports. Natural language queries like "what agents have I built for text processing?" or "show me tasks that failed due to missing permissions" search across all knowledge types with ranked results. This layer enables: agents to reason about the system's own history during planning (decomposer context), the strategy recommender to find precedent ("we built a similar skill last week"), research-informed design to check if a capability already exists before fetching docs, and user-facing commands (`/search`, `/knowledge`) for exploring system state. Implemented as a thin orchestrator over ChromaDB collections — each knowledge type (episodes, agents, skills, workflows, trust) is a collection with typed metadata, and the semantic layer fans out queries and merges results by relevance score. Completed as Phase 21 (AD-242 through AD-246).~~
- [ ] **Knowledge Graph — Structured Relational Store.** The Nooplex (§3.1, §4.2) defines a per-mesh knowledge graph alongside vector memory. ChromaDB answers "find similar things" — a knowledge graph answers "what is structurally related to what." Encodes typed entity relationships, causal chains, domain facts, and inferred connections, all tagged with provenance, confidence, and temporal metadata. Agents contribute through assertion, inference, and validation. A scaled-down ProbOS implementation: a lightweight graph store (e.g., SQLite-backed adjacency list or NetworkX in-memory) that accumulates relational knowledge as episodes execute. The decomposer would query it during planning ("what entities has this user worked with?"), the introspection agent would traverse it for "why" questions (causal chains, not just similar episodes), the dreaming engine would consolidate it (merge redundant nodes, strengthen frequently-traversed edges, prune orphans), and the strategy recommender would reason relationally about existing capabilities ("this agent already handles HTTP — the new intent is also network I/O"). The KG complements ChromaDB the way a table of contents complements full-text search — structured navigation vs. semantic similarity.
- [ ] **Provenance System — Derivation Chains on All Knowledge.** The Nooplex (§4.3.4, §5.4) describes comprehensive provenance: every piece of knowledge tagged with who/what created it, when, through what process, based on what inputs, with what confidence, and through what chain of reasoning. ProbOS records `agent_ids` on episodes and Git commit authorship, but there is no derivation chain — when a designed agent produces output, there is no record of which prior episodes or knowledge informed the decomposer's plan. Implementation: add a `provenance: dict` field to `IntentResult`, `Episode`, and KnowledgeStore artifacts carrying `source_agent_id`, `source_episode_ids` (which prior episodes were recalled during planning), `decomposition_context` (what the decomposer knew when it built the DAG), and `human_participant_id` (if a human correction or approval was involved). The roadmapped feedback-to-learning loop needs provenance to trace which human corrections actually improved outcomes. The introspection agent needs it to answer "why did you do it that way?" with a real derivation chain rather than post-hoc rationalization.
- [ ] **Knowledge Lifecycle Management — Ingestion, Active Use, Deprecation, Archival.** The Nooplex (§7.6) describes a 7-stage lifecycle with formal confidence decay. ProbOS episodes accumulate indefinitely (capped only by `max_episodes` eviction). Workflow cache entries persist until LRU eviction. There is no concept of knowledge aging — an episode from 6 months ago describing a now-changed file structure has the same recall weight as a fresh one. Scaled-down implementation: (1) **Confidence decay** — episodic recall scoring incorporates `age_factor = e^(-lambda * age_days)` so older episodes rank lower unless frequently cited. Domain-specific lambda values (fast decay for file-system-state episodes, slow decay for design-pattern episodes). (2) **Deprecation** — episodes and workflow cache entries flagged as deprecated when contradicted by newer outcomes (same intent, different result). Deprecated entries excluded from recall by default but available for historical queries. (3) **Archival** — after deprecation threshold, entries move from ChromaDB active collection to a Git-only archive (still searchable via Semantic Knowledge Layer but not in hot recall path). (4) **Usage tracking** — each episode and cache entry tracks `recall_count` and `last_recalled_at`, enabling the dreaming engine to identify unused knowledge for deprecation candidates.
- [ ] **Formal Policy Engine — Declarative Governance Rules.** The Nooplex (§4.3.4) describes machine-readable policies enforced before, during, and after execution. ProbOS has governance axioms (Safety Budget, Reversibility Preference, Minimal Authority) documented as prose in PROGRESS.md, but these are narrative principles, not runtime-enforceable rules. The consensus layer provides outcome governance (quorum voting), but there is no pre-execution policy check. Implementation: a declarative rule engine that evaluates policies against DAG nodes before execution. Rules expressed as simple predicate-action pairs: `{"if": {"intent": "write_file", "params.path_matches": "/etc/*"}, "then": "require_consensus"}`, `{"if": {"agent.trust_score": "<0.3"}, "then": "block"}`, `{"if": {"intent": "run_command", "params.command_contains": "rm -rf"}, "then": "escalate_tier3"}`. Rules loaded from a `policies.yaml` alongside `system.yaml`. The DAG executor checks each node against the policy engine before dispatch. Policy violations recorded in episodic memory as governance events. Rules updatable at runtime via `/policy` shell command without restart (feeds into Norm Propagation below).
- [ ] **State Reconciliation Protocol — Structured Argumentation and Precedent.** The Nooplex (§6.4) describes a 4-stage conflict resolution: confidence comparison → independent verification → structured argumentation → human escalation. ProbOS has consensus voting + red team verification + 3-tier escalation, covering stages 1 and 4. Missing: (1) **Independent verification dispatch** — when two agents produce conflicting results, dispatch a verification task to an uninvolved agent (beyond the red team, which re-executes the same agent). The verifier is chosen by inverse Hebbian weight — an agent that has never handled this intent has the least bias. (2) **Structured argumentation** — conflicting agents present their evidence (input, reasoning trace, output, confidence) in a structured format. A neutral cognitive agent (arbiter archetype, see Phase 15) compares the arguments and renders a judgment with explanation. (3) **Precedent store** — all conflict resolutions recorded as precedent entries in the knowledge graph. When a similar conflict arises, the reconciliation protocol checks precedent before dispatching verification, enabling faster resolution. Precedents carry `outcome`, `reasoning`, `participants`, and `confidence_after` so the system learns which types of conflicts require full argumentation vs. quick resolution.
- [ ] **Agent Versioning and Model Update Protocol.** The Nooplex (§7.10) describes versioned agents with shadow deployment. ProbOS's `AgentDesigner` creates agents and `BehavioralMonitor` tracks them post-deployment, but there is no versioning. When a designed agent is redesigned or the underlying LLM model changes, there is no comparative evaluation. Implementation: (1) **Version tracking in KnowledgeStore** — designed agent artifacts already have `.py` + `.json` sidecar; add a `version: int` field that increments on redesign. Git history provides the full version chain. (2) **Shadow deployment** — when a designed agent is redesigned, run the new version alongside the incumbent for N executions. Both receive the same intents; results are compared but only the incumbent's output is used. (3) **Comparative evaluation** — after the shadow period, compare success rates, confidence scores, execution times, and trust trajectory between incumbent and candidate. Cutover if candidate outperforms; rollback if not. (4) **Model change detection** — when the LLM tier's model changes (e.g., new Ollama model), flag all designed agents as "model-changed" and trigger shadow re-evaluation. Source code doesn't change, but the agent's behavior may shift because the LLM it consults is different.
- [ ] **Confidence Decay for Knowledge Entries.** The Nooplex (§7.6) describes exponential confidence decay: `c(t) = c₀ · e^(-λ·(t-t₀))` with domain-specific decay rates and citation adjustments (corroborations boost, contradictions decrease, retractions penalize heavily). ProbOS's trust scores decay toward a prior (AD-21), but episodic memory entries and workflow cache entries have no time-based confidence decay. An episode from months ago about a now-deleted file has the same recall weight as a fresh one. Implementation: (1) Add `confidence: float` and `last_cited_at: float` fields to `Episode` and `WorkflowCacheEntry`. (2) Recall scoring in `EpisodicMemory.recall()` multiplies ChromaDB similarity by `age_factor`. (3) Workflow cache `lookup_fuzzy()` incorporates age penalty. (4) Dream cycle consolidation boosts `confidence` on episodes that are recalled frequently (citation adjustment) and marks episodes below a threshold for deprecation (ties into Knowledge Lifecycle above).
- [ ] **Perception Gateways — Ambient Monitoring Agents.** The Nooplex (§4.2) describes perception gateway agents that continuously transduce external data into the mesh's shared memory. ProbOS agents are purely reactive — they execute when an intent is dispatched, not when data changes. A scaled-down version: agents that monitor external state and inject observations into episodic memory or the knowledge graph without user prompting. Examples: (1) **FileWatcherAgent** — monitors a configured directory for changes, ingests new/modified files as episodes with `dag_summary` describing what changed. (2) **ScheduledFetchAgent** — periodically polls configured URLs and records changes. (3) **SystemStateAgent** — monitors disk space, process lists, or other OS state and flags anomalies. These agents would run as background loops alongside the dream cycle, contributing ambient awareness. The mesh becomes proactive — noticing things before the user asks about them. Gateway observations feed into the dreaming engine's pre-warm predictions ("the user's project files just changed — they'll probably ask to read them").
- [ ] **Semantic Schemas — Typed Contracts for Agent I/O.** The Nooplex (§3.1, §4.3.1) describes shared semantic schemas defining the vocabulary, embedding spaces, and ontological commitments shared by agents. ProbOS uses informal `IntentDescriptor` (name, params, description) and `CapabilityDescriptor` as its semantic framework, but there is no typed contract for what agents actually produce and consume. With deterministic tool agents this is manageable — their output shapes are hardcoded. But as designed agents proliferate and cognitive agents arrive (Phase 15), integration errors multiply. Implementation: (1) JSON Schema validation on `IntentResult.result` payloads, declared per-intent in `IntentDescriptor`. (2) Schema registry in the KnowledgeStore — versioned, backwards-compatible. (3) The `CodeValidator` and `SkillValidator` check that designed agent/skill output conforms to the declared schema. (4) Runtime validation: the DAG executor validates `IntentResult.result` against the schema before passing data to downstream nodes. Schema violations recorded as governance events. This catches silent integration failures early — a designed agent returning `{"data": "..."}` when the schema expects `{"result": "..."}` is caught at runtime, not discovered when a downstream agent fails.
- [ ] **Trust Transitivity for Federation.** The Nooplex (§4.3.4) describes transitive trust across federation boundaries: `T(A→C) = T(A→B) · T(B→C) · δ`, where δ is a discount factor (default 0.5). Trust bounded by minimum constituent link. Transitive trust never applied to safety-critical operations. The Multi-Participant Federation roadmap item describes trust profile exchange but does not specify a transitivity model. As federation expands beyond 2 nodes, trust transitivity becomes important for routing decisions — "should node A trust an agent on node C that node B vouches for?" Implementation: (1) `NodeSelfModel` (Psi) already broadcasts capability profiles; extend with per-agent-type trust summaries. (2) `FederationRouter` incorporates transitive trust when scoring federated intent targets. (3) Discount factor δ configurable per-node (paranoid nodes use δ=0.1; trusting nodes use δ=0.8). (4) Safety-critical intents (write_file, run_command) never routed via transitive trust — must have direct trust relationship or escalate.
- [ ] **Chaos Engineering — Resilience Validation.** The Nooplex (§7.7) describes controlled failure injection: agent crashes, mesh unavailability, network partitions, corrupted knowledge, latency spikes. ProbOS has 1041 tests but no chaos testing. The architecture has resilience features (pool recovery, trust decay, agent recycling, escalation cascade), but these are tested through isolated unit tests, not system-wide failure injection. Implementation: a `chaos` test suite (marked `@pytest.mark.chaos`) that exercises resilience end-to-end. Test scenarios: (1) kill agents mid-execution — verify pool recovers and intent retries, (2) corrupt trust snapshots in KnowledgeStore — verify warm boot detects and recovers, (3) simulate federation timeout — verify FederationRouter falls back to local agents, (4) inject slow agents — verify attention manager deprioritizes them and BehavioralMonitor alerts, (5) exhaust pool capacity during surge — verify PoolScaler scales up and intent queue doesn't drop. Each test asserts both recovery behavior and that governance events are recorded.
- [x] ~~**Shapley Value Trust Attribution.** Game-theoretic improvement to trust updates. Currently, when a consensus outcome succeeds, all participating agents get the same trust boost regardless of their marginal contribution. The Shapley Value computes each agent's actual contribution by considering all possible agent subsets and averaging how much the outcome changes when each agent is added or removed. An agent whose vote was decisive (removing it would have changed the outcome) gets a larger trust boost than an agent whose vote was redundant. Implementation: after each consensus outcome in the quorum engine, compute per-agent Shapley values over the collected votes. For a 3-agent quorum there are only 6 permutations; for 5 agents, 120 — tractable numbers. The Shapley value feeds into the existing `TrustNetwork.record_observation()` as a weight multiplier on the trust update. Agents that consistently provide decisive, correct votes build trust faster. Agents that are consistently redundant (the quorum would have passed without them) build trust slower. This makes the trust network learn faster who is actually good, not just who participated. Connects to Condorcet's Jury Theorem — the mathematical foundation for why ProbOS's consensus architecture works. (AD-223, AD-224)~~
- [x] ~~**Trust-Weighted Capability Matching.** Game-theoretic improvement to agent selection. Currently, `CapabilityRegistry` matching scores agents by descriptor similarity (exact → substring → semantic → keyword) but does not incorporate trust. An agent claiming "I can analyze data" with trust 0.9 and an agent claiming the same with trust 0.3 are scored equally by the capability registry. Costly signaling theory says credible signals must be expensive to fake — in ProbOS, the "cost" is earned trust. Implementation: during agent selection for intent handling, weight capability match scores by the agent's trust score from `TrustNetwork`. The Hebbian router partially does this (strong routing weights = proven affinity), but capability matching at the registry level does not. Combining `CapabilityRegistry` scores with `TrustNetwork` scores produces capability-weighted-by-credibility matching. Agents self-select based on capability, but the system prefers agents whose capability claims are backed by track record. This is a wiring change between two existing subsystems — no new infrastructure needed. (AD-225, AD-226)~~
- [ ] **Exploration-Exploitation Balance — Curiosity-Driven Discovery.** The Nooplex (§4.3.3, §6) describes the meta-cognitive layer explicitly managing tension between goal-directed execution (exploitation) and curiosity-driven discovery (exploration). ProbOS's DreamingEngine performs pre-warm intent prediction via temporal bigrams — this is exploitation optimization ("predict what the user will ask next"). Missing: the exploration side — background processes that search for unexpected connections in accumulated knowledge. Implementation: extend the dream cycle with an **associative exploration phase** that runs after the standard replay/prune/trust/pre-warm steps. The explorer: (1) picks random episode pairs from ChromaDB and checks semantic similarity — high-similarity episodes from different intent domains suggest an unexploited cross-domain connection, (2) identifies Hebbian weight clusters where agents handle semantically diverse intents — potential capability overlap worth consolidating, (3) searches for workflow cache entries with similar DAG structures but different intent names — candidate workflow abstractions. Discoveries logged as `ExplorationEvent` entries in episodic memory with `discovery_type` and `confidence`. The introspection agent surfaces them via a `system_discoveries` intent. The dreaming engine's exploration frequency is tunable: `exploration_ratio: float = 0.2` (20% of dream cycle time allocated to exploration vs. 80% to consolidation).
- [ ] **Norm Propagation — Dynamic Rule Distribution.** The Nooplex (§6.4) describes policy and norm updates propagated to all meshes and agents at runtime. ProbOS loads configuration from `system.yaml` at boot and does not change it during the session (except `/tier` switching). If the Formal Policy Engine (above) is implemented, norm propagation is the mechanism for distributing policy changes to running agents without restart. Implementation: (1) `/policy add` and `/policy remove` shell commands modify the active policy set at runtime. (2) Policy changes emitted as `GovernanceEvent` entries. (3) In federation: policy updates gossiped between nodes alongside `NodeSelfModel` broadcasts. Each node's governance layer decides whether to adopt, adapt, or reject incoming norms based on its own policy (sovereignty preserved — a node can refuse norms that conflict with its local governance). (4) Policy version tracking — each policy rule has a version and timestamp, enabling conflict detection when federated nodes have divergent policy sets.
- [x] **Persistent Agent Identity — Individuals That Survive Restarts.** Agents are currently ephemeral: `BaseAgent.__init__` generates a random `uuid.uuid4().hex` on every instantiation (`substrate/agent.py:30`). When ProbOS restarts, pools are recreated with entirely new agent instances bearing new IDs. All per-agent learned state — trust (keyed by `agent_id` in `TrustNetwork`), Hebbian routing weights (keyed by `(source_id, target_id)` in `HebbianRouter`), confidence history — is orphaned. The warm boot sequence loads old trust records into memory (`runtime.py:1317`), then spawns fresh agents with new IDs and assigns them probationary trust (`runtime.py:1245`). The old records sit inert, never matched. This means an agent that earned high trust (Beta(20, 2)) over many successful interactions restarts at probationary (Beta(1, 3)). All routing learning is lost. Agent *types* survive (designed agent code, skills); agent *individuals* do not. This is both a current bug in warm boot and a prerequisite for agent sovereignty.
  - **Deterministic agent IDs** — derive agent IDs from stable attributes: `agent_id = hash(agent_type, pool_name, instance_index)`. The same agent type in the same pool at the same position gets the same ID across restarts. This reconnects warm boot trust and routing data to the correct agent instances. The ID formula must be stable across code changes — based on deployment topology, not implementation details.
  - **Agent manifest in KnowledgeStore** — persist the full agent roster as a Git-backed artifact: `{agent_id, agent_type, pool_name, instance_index, created_at, skills_attached, instruction_hash}`. On warm boot, the manifest is the source of truth for which agents should exist. Pools are recreated to match the manifest rather than spawning arbitrary instances. If an agent was pruned (removed from manifest), it stays gone. If a new agent was added, it appears with probationary trust. An agent that existed before restarts as the same individual with its accumulated trust, routing history, and skills.
  - **Trust and routing reconnection** — warm boot loads trust snapshots and Hebbian weights, then recreates agents with matching deterministic IDs. The old trust records are no longer orphaned — they key directly into the restored agents. Designed agents that previously had earned trust (e.g., passed many QA cycles, handled many intents successfully) retain that trust across restarts instead of being demoted to probationary.
  - **Individual episodic history** — with persistent IDs, episodic memory can be filtered per-agent: "what has *this specific agent* done before?" This enables agents to develop individual expertise profiles — not just "agents of type X succeed at intent Y" but "agent `abc123` has handled 50 file analysis tasks with 95% success and has learned domain-specific patterns." The agent's episodic history becomes part of its identity, not interchangeable with other agents of the same type. Agent history is NOT stored as flat files (Squad's `history.md` pattern is prompt-engineering, not architecture — the agent reads its entire history into the LLM context window with no semantic filtering, no consolidation, no confidence decay, and unbounded growth). Instead, agent history lives in the existing storage layers, indexed by persistent agent_id:
    - **ChromaDB episodic memory with `agent_id` metadata filtering** — episodes already record which agent handled them. With stable IDs, `episodic_memory.recall(query, filter={"agent_id": "abc123"})` gives semantic search over a specific agent's history. The agent gets only what's relevant to the current task, ranked by similarity, recency, and valence — not its entire life story. This is what Squad's `history.md` tries to be, implemented as architectural memory rather than prompt injection.
    - **Dream-consolidated agent summaries** — during dream cycle consolidation, the dreaming engine analyzes each agent's recent episodes and distills per-agent patterns: "agent abc123 succeeds 95% when reading before writing; struggles with binary files; has handled 50 file analysis tasks." These summaries are stored as an `agent_summary` artifact type in the KnowledgeStore (Git-backed, versioned). Each dream cycle *supersedes* the previous summary rather than appending — the summary reflects current consolidated knowledge, not an ever-growing log. Old summaries remain in Git history for auditing but are not in the active recall path. This connects to the roadmapped Abstract Representation Formation — per-agent abstractions are a subset of system-wide pattern extraction.
    - **Agent self-context at task time** — when a cognitive agent (Phase 15) receives an intent, it queries its own episodic history semantically: "have I done anything like this before?" The recall returns relevant episodes ranked by similarity, recency, and valence. The dream-consolidated summary provides high-level self-awareness ("I'm good at file analysis, weak on binary formats"). The agent's trust score and Hebbian routing position provide additional self-knowledge. None of this requires reading a flat file — the agent's identity is distributed across ChromaDB vectors, Bayesian trust parameters, Hebbian weights, and KnowledgeStore summaries, queried on demand rather than loaded wholesale.
    - **Why not flat files** — Squad's markdown-per-agent approach fails at scale and contradicts the Nooplex's knowledge lifecycle principles (§7.6). A flat file has no confidence decay (a lesson from 6 months ago about a deleted API weighs the same as yesterday's), no semantic relevance filtering (the agent reads everything or nothing), no consolidation (the file grows monotonically), and no integration with the rest of the knowledge architecture (trust, routing, workflow cache are all separate). ProbOS's existing subsystems already solve each of these problems — persistent agent IDs are the missing key that connects them per-individual.
  - **Pruning as deliberate removal** — agents removed through self-modification, low trust, or manual `/prune` commands are deleted from the manifest. Their trust records and routing weights are archived (moved to Git history, not active memory). The agent is gone as an individual — its ID will not be reassigned. If the same agent type is needed later, a new individual is created with a new ID and probationary trust. Death is real; identity is not recycled.
  - **Foundation for sovereignty** — persistent identity is the prerequisite for everything in the agent sovereignty principle (Phase 15). An agent can only have a meaningful trust trajectory, skill portfolio, episodic track record, and behavioral profile if it persists as the *same individual* across sessions. Without persistent identity, sovereignty is an abstraction — the agent is reborn empty each restart, and the "identity that emerges through track record" described in Phase 15 is reset to zero every time ProbOS stops.

- [ ] **Phase 15: Cognitive Agents — LLM-Guided Reasoning as First-Class Mesh Citizens.** The Nooplex (§4.2) describes the Cognitive Mesh as containing a *heterogeneous* agent population: "LLM-based reasoning agents, specialized analytical tools, retrieval agents, planning agents, critic agents, and coordination agents." ProbOS currently implements only the "specialized analytical tools" — deterministic agents with hardcoded perceive/decide/act logic (FileReaderAgent, ShellCommandAgent, etc.). This phase introduces a second agent class: **CognitiveAgent**, where the `decide()` and/or `act()` steps consult an LLM guided by per-agent `instructions`. This brings reasoning *inside* the mesh as a trust-scored, confidence-tracked, recyclable participant — rather than concentrating it in the decomposer.
  - **`instructions: str | None` on BaseAgent** — optional field, ignored by tool agents, required by cognitive agents. Provides the LLM system prompt that governs the agent's reasoning behavior.
  - **`CognitiveAgent(BaseAgent)` base class** — new abstract base where `decide()` invokes the LLM with the agent's `instructions` as system prompt and the current observation as user message. Preserves the perceive/decide/act/report lifecycle. Uses the existing per-tier LLM client infrastructure.
  - **Keep all current tool agents unchanged** — FileReaderAgent, ShellCommandAgent, HttpFetchAgent, etc. remain deterministic. A file reader shouldn't reason about whether to read a file. Code *is* the instruction for tool agents.
  - **Wire `AgentDesigner` to produce `CognitiveAgent` subclasses** — self-mod already generates agents with `llm_client` via kwargs; this formalizes the pattern. Designed agents get generated `instructions` that the LLM follows, rather than fully generated `act()` logic.
  - **Cognitive agent archetypes:** analyzer (examines data and produces structured insights), planner (decomposes sub-goals within its domain), critic (evaluates other agents' outputs for quality/correctness), synthesizer (combines results from multiple sources into coherent summaries). These complement the existing decomposer's role — the decomposer orchestrates *what* to do; cognitive agents reason about *how* within their domain.
  - **Alignment with Nooplex principles:** (1) *Cooperative emergence* — cognitive and tool agents cooperate through the shared mesh, each contributing what they're best at. (2) *Anti-fragility* — self-mod can design new cognitive agents that bring judgment to novel domains while tool agents provide reliable infrastructure. (3) *Decentralization* — reasoning is distributed across cognitive agents that are independently trust-scored, confidence-tracked, and recyclable, rather than concentrated in the decomposer. (4) *Transparency* — cognitive agent instructions are inspectable metadata, not opaque model weights.
  - **Agent sovereignty** — cognitive agents do NOT share a system-wide identity, personality, or "soul file." Each agent's `instructions` are its own — authored for its domain, shaped by its purpose, not inherited from a central template. Two critic agents may reason differently; two analyzers may prioritize different heuristics. This is intentional. Diversity of reasoning style within a consensus-governed mesh produces more robust collective outcomes than a monoculture of identically-instructed agents. The mesh governs *outcomes* (quorum, trust, confidence thresholds) without constraining *process* — how an agent reasons internally is sovereign to that agent. Identity emerges individually through each agent's trust trajectory, skill attachments, Hebbian routing history, and accumulated episodic track record. The system has no centralized personality; it has a population of sovereign agents whose collective behavior emerges from their individual competence and the governance structure that constrains their interactions.
  - **Trust & confidence integration** — cognitive agents participate in the same Bayesian trust network and confidence tracking as tool agents. Bad reasoning gets the same treatment as bad file reads: confidence drops, degradation, recycling, redesign.
  - **Consensus for cognitive outputs** — cognitive agent outputs that influence system state (planning decisions, critiques that trigger re-execution) go through consensus, just like file writes and shell commands.
  - **Domain-aware skill attachment** — skills should be added to the cognitive agent whose domain best matches the new capability, not always to a generic `SkillBasedAgent` dispatcher. The `StrategyRecommender` currently hardcodes `target = "skill_agent"` and the runtime callback filters by `isinstance(agent, SkillBasedAgent)`. With cognitive agents, the recommender should score each cognitive agent's `instructions` (domain description) against the new intent using semantic similarity, and attach the skill to the best-matching cognitive agent. A "summarize_csv" skill belongs on an analyzer agent that already has data-reasoning instructions, not a generic dispatcher with no domain context. This makes skills more effective — the cognitive agent's LLM instructions provide reasoning context that the skill handler can leverage — and more discoverable, since the agent's existing capability descriptors are semantically adjacent to the new skill. `SkillBasedAgent` remains as a fallback for skills that don't fit any cognitive agent's domain.
  - **The mesh is the toolbox** — cognitive agents do NOT get their own embedded tools (file I/O, HTTP, shell). Instead, they dispatch sub-intents through `intent_bus.broadcast()` to existing tool agents. A cognitive agent that needs file contents broadcasts `read_file` → FileReaderAgent handles it. One that needs web data broadcasts `http_fetch` → HttpFetchAgent handles it (consensus-gated). This preserves: (1) *consensus governance* — a cognitive agent can't bypass quorum by doing its own file writes, (2) *trust attribution* — success/failure is tracked on the agent that actually performed the action, (3) *minimal authority* — cognitive agents have no direct system access and earn capability through the mesh, (4) *decentralization* — the cognitive agent is smart but has no hands; the tool agent has hands but doesn't think; they cooperate. The `runtime` reference that designed agents already receive (AD-147) is the interface — no new tool framework needed. The cognitive agent's one unique tool is the LLM itself; everything else it needs, it asks the mesh for.

- [ ] **Multi-Participant Federation: Each Human Runs Their Own Cognitive Mesh.** ProbOS is currently a single-user, single-session system — "user" always means "the one person at the terminal." The Nooplex (§3.2) defines the architecture as a **federation of autonomous Cognitive Meshes**, not a shared runtime with multiple logins. Each ProbOS instance *is* a Cognitive Mesh: its own agent population, trust network, Hebbian routing, episodic memory, habits, and human interface. Multiple humans interact with ProbOS by each running their own node, with cross-node collaboration handled through federation — not by sharing internal state. This preserves agent sovereignty (each node's agents develop coherent trust relationships with their human), avoids contradictory training signals (two humans can't give conflicting feedback to the same agent population), and aligns with the Nooplex's explicit framing: "not a monolithic empire of mind but a federation of diverse, autonomous cognitive communities."
  - **Architecture: one human, one mesh, federation between meshes.** Phase 9 already built the infrastructure: `FederationBridge` (ZMQ transport), `FederationRouter` (intent forwarding), `NodeSelfModel` (Psi broadcast), and loop prevention via the `federated` flag. The gap is that federation currently forwards *intents* but not *knowledge*. This phase extends federation to include: (1) episodic memory queries across nodes — node A can semantically search node B's ChromaDB for relevant past experiences, (2) trust profile exchange — nodes share agent trust summaries so a federated intent is routed to the most trusted agent across the federation, not just the local mesh, (3) designed agent sharing — a cognitive agent designed on node A can be offered to node B as a skill or agent template, with node B's governance deciding whether to accept it (probationary trust applies).
  - **Semantic alignment is already solved.** Both nodes use ChromaDB's MiniLM embedding function, so vectors are in the same space by default. Federated semantic queries work without an alignment layer — this is a simplification the Nooplex's formal model (§3.2, embedding alignment functions ℱ) anticipates for same-model deployments.
  - **Knowledge federation via Git remotes.** Phase 14's Git-backed KnowledgeStore maps naturally to multi-node sync. Each node's knowledge repo is a Git remote. `git pull` brings in another node's episodes, designed agents, trust snapshots, and workflow cache entries — with full provenance (commit authorship = source node). `git push` shares local knowledge outward. This reuses the existing persistence layer without new infrastructure. ChromaDB is re-seeded from Git on warm boot, so federated knowledge becomes searchable locally after sync.
  - **Provenance tracking.** Federation messages already carry `source_node_id`. Add `participant_id` to `IntentMessage` and `Episode` so that human-originated intents carry identity across federation boundaries. This enables downstream nodes to weight contributions by source — a domain expert's node produces higher-trust episodes than a novice's node, and the federation can encode this through cross-node trust scores.
  - **Why not shared runtime (multi-tenant)?** A shared runtime creates governance conflicts: whose escalation responses shape agent behavior? Whose trust feedback trains the Hebbian weights? Two humans giving contradictory corrections to the same agent population produces incoherent learning. The Nooplex resolves this by keeping each mesh autonomous — cross-mesh collaboration happens through structured federation (knowledge integration, federated queries, governance negotiation), not through shared internal state. Each human's node is their cognitive home; the federation is the shared commons.
  - **Why not hybrid (shared mesh, per-user experience)?** The hybrid model compromises sovereignty at both levels. Agents can't develop coherent trust relationships when receiving signals from multiple humans with potentially conflicting judgment. Humans can't develop intuition about "their" system when the agent population is being shaped by others' interactions. The federation model gives each human a system that genuinely adapts to *them* while still enabling collaboration through explicit, governed knowledge exchange.

- [ ] **MCP Federation Adapter — Protocol Bridge at the Mesh Boundary.** ProbOS federation currently uses ZeroMQ for node-to-node communication — fast, programmatic, but requires both endpoints to be ProbOS instances. An MCP (Model Context Protocol) adapter layer would expose each node's capabilities as MCP tool definitions, enabling discovery and invocation by any MCP-speaking system (VS Code extensions, other agent frameworks, third-party meshes). The principle: programmatic inside the brain, protocol between brains. The mesh boundary is the skull boundary.
  - **`MCPServer` capability exposure** — maps `NodeSelfModel` capabilities to MCP tool schemas. Each `IntentDescriptor` becomes an MCP tool with its params, description, and consensus requirements as metadata. The mapping is mechanical: ProbOS already broadcasts structured capability profiles via Ψ gossip; MCP tool definitions are a different serialization of the same information. The server refreshes tool definitions when the runtime's intent descriptors change (new designed agents, new skills).
  - **Inbound intent translation** — MCP tool calls are translated to `IntentMessage` and dispatched through `intent_bus.broadcast(federated=True)`. The existing loop prevention flag prevents re-federation. MCP-originated intents go through the same governance pipeline as any federated intent: consensus, red team verification, escalation. The MCP adapter is a transport, not a trust bypass.
  - **MCP client trust** — MCP clients are treated as federated peers with configurable trust. New MCP clients start with probationary trust (same `Beta(alpha, beta)` prior as new agents — AD-110). Trust updates based on outcome quality of intents they submit. Destructive intents (write_file, run_command) from MCP clients always require full consensus regardless of accumulated trust. The `validate_remote_results` config flag applies.
  - **Outbound MCP client** — allows ProbOS to discover and invoke capabilities on external MCP servers. External tool definitions are translated to `IntentDescriptor` and registered as federated capabilities. The `FederationRouter` can then route intents to MCP-connected systems alongside ZeroMQ-connected ProbOS nodes, using the same scoring logic. External capabilities carry federated trust discount (same δ factor from Trust Transitivity roadmap item).
  - **Transport coexistence** — ZeroMQ remains the primary intra-Noöplex transport (fast, binary, low-latency). MCP serves the boundary between independent cognitive ecosystems. Both transports feed into the same `FederationRouter` and `intent_bus`. A node can simultaneously connect to ProbOS peers via ZeroMQ and to external systems via MCP. The `FederationBridge` becomes transport-polymorphic: a transport interface with ZeroMQ and MCP implementations.
  - **Noöplex alignment** — this directly implements §3.2's embedding alignment at the protocol level: MCP tool schemas are the shared vocabulary, each mesh's internal representation is sovereign. §4.3.4's governance negotiation maps to MCP capability exposure: meshes choose what to expose (tool definitions), what trust to extend (authentication), and what constraints apply (consensus metadata). The long-term vision: if the Noöplex scales to heterogeneous meshes across organizations, MCP (or its successor) becomes the lingua franca for Layer 3/4 cross-mesh communication.

- [ ] **Abstract Representation Formation — Learning Concepts from Experience.** ProbOS currently learns specific workflows ("read config/system.yaml" → cached DAG) but does not form abstractions. After reading 50 files, it has 50 cached DAGs — it hasn't learned the concept "file reading is a common primitive that usually precedes analysis." The system memorizes instances without extracting principles. This is the most impactful missing mechanism for emergence — it's the difference between a system that remembers and a system that understands.
  - **Dream cycle abstraction phase** — after standard replay/prune/trust/pre-warm, the dreaming engine analyzes episode clusters to extract abstract patterns. Not "I read /tmp/foo.txt" but "file reading precedes content analysis 80% of the time" or "multi-step tasks that start with information gathering succeed more often than those that start with action." Clustering uses ChromaDB semantic similarity across episodes; pattern extraction uses cognitive agents (Phase 15) to articulate the abstraction in natural language.
  - **Abstraction store** — a distinct knowledge type in the KnowledgeStore (separate from episodes, designed agents, and workflow cache entries). Abstractions have `pattern_description`, `confidence`, `supporting_episode_ids`, `domain`, and `abstraction_level` (concrete → operational → strategic). Versioned and subject to knowledge lifecycle (deprecation when newer abstractions supersede).
  - **Decomposer context injection** — abstractions injected into the decomposer's planning context alongside pre-warm hints and workflow cache entries. The decomposer plans better because it has learned planning principles from experience ("information gathering before mutation" as a learned strategy, not a hardcoded rule), not just specific cached plans. This closes the gap between the governance axiom "Reversibility Preference" (currently prose) and learned operational wisdom.
  - **Abstraction quality feedback** — when a decomposition informed by an abstraction succeeds, the abstraction's confidence increases (citation adjustment). When it leads to failure, confidence decreases. Abstractions that survive many episodes and dream cycles become durable system knowledge — the architecture's equivalent of insight.

- [ ] **Inter-Agent Deliberation — Collective Reasoning Through Dialogue.** Agents currently communicate only through structured intent dispatch. Agent A broadcasts `read_file`, Agent B handles it, result flows back through the DAG executor. Agents never debate, negotiate, or build shared understanding. All coordination is top-down through the decomposer. This is the gap between orchestration and collective intelligence.
  - **Deliberation protocol** — a structured multi-turn exchange between cognitive agents (Phase 15). When a task is ambiguous, complex, or high-stakes, the decomposer spawns a deliberation instead of making all planning decisions alone. Example: an analyzer proposes restructuring a file, a critic identifies that this breaks an API contract, the analyzer suggests a compatibility layer, the critic argues for updating callers instead. The deliberation produces a higher-quality plan than either agent alone.
  - **Deliberation governance** — deliberations are bounded by turn limits, time budgets, and token budgets (existing `AttentionManager` scoring applies). Consensus determines when a deliberation has converged — if agents reach agreement above confidence threshold, the plan proceeds. If they deadlock, the conflict escalates through the existing 3-tier escalation pipeline (algorithmic retry → LLM arbitration → human consultation).
  - **Deliberation as intelligence substrate** — this is where the Nooplex's "cooperative emergence" principle becomes concrete. Intelligence emerges from agent interaction, not from any single agent's reasoning. The existing consensus infrastructure (quorum, trust-weighted voting) provides governance over deliberation outcomes. The Hebbian router strengthens agent pairings that produce good deliberation outcomes — over time, the system learns which agents reason well together.
  - **Deliberation memory** — deliberation transcripts stored as a distinct episodic type. The abstract representation mechanism (above) can extract meta-patterns: "deliberations that included a critic produced 40% fewer downstream failures." The system learns to deliberate better by studying its own deliberation history.

- [ ] **Causal World Modeling — Understanding Why, Not Just What.** Episodic memory records "I wrote to /etc/hosts and it required escalation." The system has no representation of *why* — it doesn't know that /etc/ is a system directory requiring elevated permissions. It can't predict that writing to /etc/resolv.conf will also require escalation, because it has no causal model connecting "system directory" to "permission requirement."
  - **Causal edges in knowledge graph** — the knowledge graph (roadmapped above) extended with `causes`, `prevents`, `requires`, and `enables` relationship types. During dream consolidation or after episode analysis, cognitive agents propose causal hypotheses: "writes to paths matching /etc/* always trigger Tier 3 escalation → inferred causal rule: system directories require elevated permissions." Hypotheses stored with `confidence`, `supporting_episodes`, and `contradiction_count`.
  - **Causal reasoning during planning** — the decomposer queries the KG's causal edges during DAG construction. "Will this action likely require escalation?" → plan accordingly (gather information first, warn user upfront, reorder nodes for reversibility). This makes planning anticipatory rather than reactive.
  - **Causal model validation** — bad causal models get contradicted by subsequent episodes and deprecated through the knowledge lifecycle. A causal hypothesis "HTTP fetches always succeed" gets contradicted by timeout episodes; its confidence drops; it's eventually deprecated. Good causal models survive and strengthen. The system develops an increasingly accurate (but never certain) understanding of how its environment works.
  - **Counterfactual reasoning** — once causal models exist, the system can reason about alternatives: "what would have happened if I had read the file before modifying it?" Counterfactuals are evaluated against the causal KG: the alternative plan would have triggered the "information gathering before mutation" causal pattern, which has a 90% success rate. This enables learning from single failures without requiring repeated trial-and-error.

- [ ] **Meta-Learning — Learning to Learn.** Each time ProbOS encounters a novel intent, it starts from scratch — LLM designs an agent, sandbox tests it, deploys with probationary trust. The system doesn't learn *how to design agents better* from its previous design successes and failures. It doesn't learn which decomposition strategies work for which types of problems. The self-improvement mechanism doesn't improve itself.
  - **Design meta-knowledge** — track patterns across self-modification history: which design prompt patterns produced agents that passed QA? Which produced agents with high trust trajectories? Which produced agents that were eventually removed? This meta-knowledge feeds back into the `AgentDesigner`'s prompt: "In previous designs, agents that validate input before processing had 90% success rates vs. 60% for those that don't. Agents that checked for None parameters before LLM calls avoided 80% of sandbox failures."
  - **Decomposition strategy library** — track which DAG shapes (sequential, parallel, gather-then-act, speculative execution) succeed for which intent types. The decomposer would select strategies from a learned library rather than inventing decompositions from scratch each time. "Tasks involving file modification succeed 95% with read → modify → verify; 60% with direct modify."
  - **Recursive improvement** — as the design meta-knowledge and strategy library improve, new agents are designed better and new plans are decomposed more effectively, which produces better episodes, which produces better meta-knowledge. The system gets better at getting better. This is recursive self-improvement at the architectural level — the improvement mechanism itself evolves based on its track record.
  - **Meta-learning rate tracking** — measure whether the system's performance on novel intents improves over time. If the 10th designed agent succeeds faster and with fewer iterations than the 1st, the meta-learning mechanism is working. This is a measurable proxy for cognitive growth — not just more knowledge, but better use of knowledge.

- [ ] **Compositional Generalization — Novel Solutions from Learned Primitives.** When the workflow cache misses and the LLM decomposes a novel request, the decomposition quality depends entirely on the LLM's training. ProbOS doesn't contribute its own learned decomposition knowledge. It has accumulated experience showing that "read_file → analyze → write_file" is a common pattern, but it can't compose novel workflows from learned building blocks the way an expert composes solutions from proven techniques.
  - **Task primitive vocabulary** — extract a vocabulary of learned building blocks from successful DAG patterns: "information gathering" (read_file, http_fetch, list_directory), "transformation" (designed agent processing, LLM analysis), "validation" (re-read, checksum, diff), "output" (write_file, run_command). Primitives are clusters of intent types with shared functional roles, discovered by the abstract representation mechanism analyzing DAG structures.
  - **Composition rules** — learned constraints on how primitives combine: "gathering before transformation before output" succeeds 95%. "Validation after output catches 80% of errors." "Parallel gathering of independent sources is safe; parallel mutation of the same resource is not." Rules are extracted from episode analysis and validated through subsequent experience.
  - **Compositional planning** — the decomposer uses the primitive vocabulary and composition rules as a planning scaffold. For a novel request, it identifies which primitives are needed, applies composition rules to order them, and fills in specific intents. The LLM still provides creativity (which specific agents and parameters to use), but the structural skeleton comes from learned experience. This is how expertise works — experts don't reason from first principles every time; they compose solutions from a library of proven patterns.
  - **Primitive transfer across domains** — the "validation after output" primitive learned from file operations transfers to HTTP operations, shell commands, and future domains. The system generalizes structural patterns even when the specific intents are different. This is the mechanism for cross-domain transfer learning at the architectural level.

- [ ] **Self-Directed Goal Generation — Proactive Cognition.** ProbOS is purely reactive. It waits for the user to type something, decomposes the intent, executes, and waits again. It never thinks "I should check on that thing from earlier" or "I notice a pattern the user should know about." Even the dream cycle is optimization (consolidation), not goal generation. A cognitive system should notice things and form intentions, not just respond to commands.
  - **Observation → hypothesis → goal pipeline** — perception gateways (roadmapped above) detect environmental changes. Cognitive agents evaluate observations against the causal world model to form hypotheses: "The test suite has been failing since the last code change — the change probably broke something." Hypotheses with sufficient confidence become tentative goals: "Investigate why tests are failing."
  - **Goal queue with human governance** — self-generated goals enter a priority queue, surfaced to the user proactively: "I noticed your tests are failing after the recent change to runtime.py — want me to investigate?" The user approves, rejects, or modifies. Approved goals are decomposed and executed through the normal pipeline. Rejected goals are recorded in episodic memory (the system learns what the user cares about). This uses the Human-Agent Collaboration DAG proposal mechanism — self-generated goals are proposals, not autonomous actions.
  - **Curiosity as exploration** — during dream cycles, the exploration mechanism (roadmapped above) identifies knowledge gaps: "I have many episodes about file operations but almost none about network operations — my causal model of network behavior is thin." This generates low-priority investigation goals: "Next time the user does an HTTP fetch, pay extra attention to failure modes." Curiosity is directed toward reducing uncertainty in the world model, not random exploration.
  - **Proactive boundary** — self-directed goals are always proposals, never autonomous actions. The system suggests; the human decides. This preserves the governance axiom that destructive or consequential actions require collective agreement. The system develops initiative without developing autonomy — it becomes a proactive collaborator, not an autonomous agent. The sovereignty of the human participant is preserved: the system's goals serve the human's goals, not the system's own persistence or resource acquisition.

- [ ] **Emotional Valence — Prioritized Learning from Meaningful Experiences.** ProbOS tracks success/failure as binary outcomes with confidence scores, but has no concept of *how much something matters*. Every task is equally important unless the user assigns urgency. There is no intrinsic motivation — no stronger consolidation for hard-won successes, no heightened learning from corrected failures, no distinction between routine and significant experiences.
  - **Valence scoring** — each episode receives a `valence: float` score reflecting how significant the experience was. Factors: (1) task difficulty — episodes requiring multiple retries, escalation, or novel decomposition score higher than routine single-step tasks, (2) user engagement — episodes where the user provided corrections, annotations, or extended interaction score higher than silently accepted results, (3) novelty — episodes involving new intent types, new agents, or unusual DAG structures score higher than repeated patterns, (4) outcome surprise — episodes where the actual outcome differed significantly from the predicted outcome (based on causal world model) score higher than expected outcomes.
  - **Valence-modulated consolidation** — the dream cycle's replay phase weights episodes by valence. High-valence episodes receive stronger Hebbian strengthening/weakening, more abstract representation extraction, and more causal model updates. Low-valence routine episodes receive standard consolidation. This mirrors biological memory: emotionally significant events consolidate more strongly, forming more durable memories and stronger learning signals.
  - **Valence-weighted recall** — episodic memory recall incorporates valence alongside semantic similarity and recency. When the decomposer searches for relevant past experience, high-valence episodes (the hard lessons, the creative solutions, the corrected mistakes) surface more prominently than routine successes. The system learns more from its most meaningful experiences, not just its most recent or most frequent ones.
  - **Intrinsic motivation signal** — valence accumulated over time creates a profile of what the system "cares about" — which domains produce the most learning, which types of tasks engage the user most, where the biggest knowledge gaps are. This feeds into self-directed goal generation: the system is intrinsically motivated to explore domains where valence has been highest (most learning potential) and to avoid patterns associated with consistently low valence (routine, unproductive). This is not consciousness — it's a statistical learning signal shaped like motivation. Connects to ProbOS via a WebSocket event stream. Full architecture spec in `hxi-architecture.md`. Deferred until core runtime roadmap is further along. When the time comes, the build has two tracks: (A) runtime event bridge (Python, emits typed events over WebSocket — lives in ProbOS repo), (B) HXI frontend (TypeScript/React/Three.js — separate repo, connects via WebSocket).
  - **Runtime event bridge (pre-work for Track A):** Every slash command already exposes the data the HXI needs. The event bridge formalizes this as a typed WebSocket stream — state deltas emitted as they occur rather than polled via CLI. Event types map to existing runtime dynamics: `AgentStateEvent` (agent lifecycle — spawning/active/degraded/recycling + confidence + trust), `HebbianUpdateEvent` (weight changes with source/target/reason), `ConsensusEvent` (quorum formation with participant votes + red team result), `GossipEvent` (propagation with source/recipients/TTL), `IntentEvent` (DAG decomposition + execution status), `MemoryEvent` (episodic store/retrieve/consolidate/prune + provenance), `GovernanceEvent` (escalations + threshold changes + constraint violations), `SystemModeEvent` (active/idle/dreaming/escalated transitions), `CollaborationEvent` (human participation — approvals/corrections/annotations with human provenance), `KnowledgeEvent` (Git commits, warm boot restores, rollbacks — new in Phase 14).
  - **HXI-relevant runtime dynamics (already built, will need events):**
    - Agent lifecycle state machine: spawning → active → degraded → recycling (substrate layer)
    - Confidence tracking: per-agent 0.0–1.0 with success/failure history (substrate layer)
    - Trust scores: Bayesian Beta(alpha, beta) with decay toward prior + raw parameter persistence (consensus layer + Phase 14 KnowledgeStore)
    - Hebbian weight updates: strengthening on success, decay on unused, SQLite persistence (mesh layer)
    - Gossip propagation: entry injection, merge by recency, random sampling (mesh layer)
    - Consensus formation: quorum assembly, confidence-weighted voting, agreement/disagreement, red team challenges (consensus layer)
    - Escalation cascades: 3-tier with retry/arbitration/user consultation (consensus layer)
    - DAG decomposition and execution: TaskDAG formation, parallel/sequential node execution, node status transitions (cognitive layer)
    - Working memory: bounded context with relevance decay (cognitive layer)
    - Episodic memory: store/retrieve with keyword similarity, seed for warm boot (cognitive layer + Phase 14)
    - Attention scoring: urgency × relevance × deadline × dependency, focus history (cognitive layer)
    - Dream cycles: pathway replay, Hebbian strengthening/weakening, trust consolidation, pre-warm (cognitive layer)
    - Workflow cache: habit crystallization, exact/fuzzy lookup, hit counts (cognitive layer)
    - Pool scaling: demand-driven scale up/down, surge capacity, idle scale-down (substrate layer)
    - Federation: cross-node gossip, intent forwarding, self-model broadcast (federation layer)
    - Self-modification: agent design, sandbox validation, QA smoke tests, probationary trust (self-mod pipeline)
    - Knowledge persistence: Git-backed artifact storage, debounced commits, warm boot restore, per-artifact rollback (Phase 14 KnowledgeStore)
  - **Phase 14 specifics for HXI:** KnowledgeStore introduces versioned system history that the HXI's temporal navigation (Phase 5) will need. `artifact_history()` and `recent_commits()` are the data sources for scrubbing through system evolution. The warm boot restore sequence (trust → routing → agents → skills → episodes → workflows → QA) is a visual event the HXI should render — the system waking up and loading its memories. `rollback_artifact()` is a governance action the HXI's governance panel should expose. Raw Beta parameters (AD-168) give the HXI the full trust distribution for rendering, not just the mean.
  - **Phase 14b specifics for HXI:** ChromaDB semantic embeddings give the HXI's Cognitive Canvas a richer data source. `compute_similarity()` can power visual proximity — agents and episodes that are semantically related could be rendered closer together in the topology, creating organic clustering based on meaning rather than just Hebbian connection weight. The embedding vectors themselves are potential inputs for future spatial layout algorithms. The `MemoryEvent` in the HXI event schema now represents semantic retrieval (not keyword matching), which means memory activation overlays in HXI Phase 2 will show genuine meaning-based recall — a more honest and visually interesting rendering.
  - **Phase 14c specifics for HXI:** Persistent agent identity gives the HXI's agent nodes stable visual identities across sessions. The same agent occupies the same topology position across restarts, and the participant can see an individual agent's trust trajectory and specialization history over time. Without this, the HXI would render ephemeral nodes that reset every restart. The `/prune` command is a governance action the HXI should expose — permanently removing an individual from the mesh with visual confirmation.
  - **Phase 14d specifics for HXI:** Agent tier classification (`core`/`utility`/`domain`) gives the HXI's topology renderer a natural visual grouping dimension. Core agents (infrastructure I/O) could render as foundational substrate nodes at the base layer, utility agents (meta-cognitive) as overlay monitors, and domain agents as the active cognitive surface — three distinct visual strata mapping to the Noöplex's layered architecture. The self-introspection intents (`introspect_memory`, `introspect_system`) give the HXI a first-party data source for system state visualization — agent counts by tier, trust distribution (mean/min/max), Hebbian weight count, pool health, episodic memory stats, and knowledge store status. This replaces any need for the HXI to scrape or infer system state; the mesh can describe itself. The Tier column in the agent table is the CLI precursor to the HXI's tier-stratified topology view.
  - **Phase 15a specifics for HXI:** `CognitiveAgent` introduces a fundamentally different visual entity — agents that *reason*. The HXI's topology renderer should distinguish cognitive agents (reasoning, LLM-backed, instructions-driven) from tool agents (deterministic, infrastructure) through distinct visual representation. A cognitive agent's `instructions` field is a displayable artifact — hovering over a cognitive agent in the HXI could show its reasoning mandate. The `decide()` → LLM → `act()` lifecycle creates observable reasoning events that the HXI could render as thought trails or reasoning chains, distinct from the simple request/response patterns of tool agents. This is the first step toward the Noöplex's heterogeneous agent populations (§4.2) where different agent types have genuinely different cognitive architectures worth visualizing.
  - **Phase 15b specifics for HXI:** Domain-aware skill attachment creates visible affinity relationships in the topology. When a skill is attached to a cognitive agent based on domain similarity, the HXI could render this as a domain-match connection — a visual link showing why a skill landed on a particular agent rather than the generic skill dispatcher. The StrategyRecommender's domain scoring produces a semantic proximity metric that the HXI could use for spatial layout: cognitive agents with similar domains cluster together, skills gravitate toward their domain-matched hosts. The strategy menu's target agent display is the CLI precursor to the HXI's interactive skill routing visualization.
  - **Phase 16 specifics for HXI:** DAG Proposal Mode is the first concrete implementation of the HXI's `CollaborationEvent` stream. `/plan` → `/approve`/`/reject` completes the proposal/approve/correct/reject interaction model referenced in the HXI architecture spec. The `render_dag_proposal()` panel is the CLI precursor to the HXI's interactive DAG editor — the numbered, indexed plan with dependency visualization, consensus annotations, and remove-by-index editing. Event log entries (`proposal_created`, `proposal_approved`, `proposal_rejected`, `proposal_node_removed`) are the machine-readable events the HXI would consume to render collaboration workflows with the golden human-provenance visual signature. The HXI could extend this with: (1) drag-and-drop node removal instead of `/plan remove N`, (2) visual dependency graph instead of textual index mappings, (3) animated execution progress over the previously-shown proposal, (4) history of approved/rejected proposals as a collaboration timeline.
  - **Upcoming roadmap items with HXI implications:**
    - *Human-Agent Collaboration* — DAG proposals and feedback-to-learning produce the `CollaborationEvent` stream defined in the HXI architecture spec. The golden human-provenance visual signature, the proposal/approve/correct/reject interaction model, and the feedback-to-topology training loop all depend on this runtime capability.
    - *Emergent Behavior Detection* — anomaly detection over Hebbian topology, trust trajectories, and routing patterns produces events the HXI's Phase 5 (Emergent Awareness) would render. The TC_N metric is a quantitative signal the HXI could display as a system-level emergence indicator.
    - *Cognitive Agents (Phase 15)* — heterogeneous agent populations (tool vs. cognitive) are a visual grammar concern. The HXI spec describes distinct rendering for different agent classes. Agent sovereignty (each cognitive agent has its own instructions and reasoning style) means the topology has genuine diversity worth seeing.
  - **Design constraint for future phases:** When building new runtime capabilities, note which state changes would need HXI events. The pattern: if a slash command would show different output after this change, the HXI needs an event for it. This costs nothing now and prevents retrofitting later.

- [ ] **IDE / Copilot Integration — Development Agents as Mesh Citizens.** ProbOS already uses VS Code's Copilot proxy as its standard/deep LLM tier, but the integration is one-directional: ProbOS consumes Copilot as a text completion endpoint. The reverse direction — ProbOS agents acting *through* Copilot and VS Code to perform code-level tasks — is unexplored. Inspired by projects like [Squad](https://github.com/bradygaster/squad) (multi-agent teams built on `@github/copilot-sdk` that coordinate code changes through VS Code), this roadmap item explores bidirectional integration where ProbOS's trust-governed, memory-enriched agent mesh orchestrates development work through IDE tooling.
  - **CopilotBridgeAgent — IDE actions as mesh intents.** A cognitive agent (Phase 15) that translates high-level development intents into Copilot SDK operations: code analysis, refactoring proposals, test generation, and structured edits. Unlike Squad's prompt-only coordination, the bridge agent is trust-scored, consensus-governed, and memory-enriched — it learns which refactoring patterns succeed in *this* codebase through episodic recall, strengthens routing to effective strategies via Hebbian weights, and requires consensus for destructive code changes. The agent dispatches sub-intents through the existing mesh for non-IDE operations (file I/O, shell commands, Git) rather than bypassing governance with direct access.
  - **VS Code extension — ProbOS as a Copilot agent provider.** A VS Code extension that exposes ProbOS's intent bus as a Copilot chat participant (`@probos analyze this module`, `@probos refactor for testability`). VS Code provides IDE context (open files, workspace structure, diagnostics, symbol resolution); ProbOS provides decomposition, multi-agent orchestration, trust governance, and episodic memory. Users interact through the familiar Copilot chat panel while ProbOS handles the multi-step reasoning and coordination behind the scenes. The extension emits VS Code diagnostics, applies workspace edits, and renders agent activity in the output channel.
  - **Self-maintenance squad — ProbOS maintaining itself.** The most compelling application: a team of cognitive agents whose domain is ProbOS's own codebase. An analyzer agent reads source code and test results, identifies gaps or regressions. A planner agent decomposes fixes into safe steps (read → modify → test → verify). A coder agent proposes changes through Copilot's code generation. A reviewer agent evaluates proposed changes against test suite results and architectural invariants. All changes go through ProbOS's own consensus governance — the same quorum voting and trust tracking that governs user-facing operations. The test suite (1041+ tests) serves as the automated QA gate. Git-backed KnowledgeStore provides full audit trail of self-maintenance actions.
  - **Squad-style concepts worth adopting.** (1) *Shared decision log* — Squad's `decisions.md` gives all agents a common ground-truth record of architectural choices. ProbOS's consensus outcomes and escalation resolutions could be surfaced as a searchable decision log, informing future planning. (2) *Governance as code, not prompts* — Squad's HookPipeline enforces file-write guards and rate limits as compiled TypeScript, not LLM instructions. This aligns with ProbOS's roadmapped Formal Policy Engine — declarative rules enforced by the runtime, not by hoping the LLM follows its system prompt. (Note: Squad's *persistent agent history as flat markdown files* is explicitly rejected — see Persistent Agent Identity item above for why ProbOS uses per-agent ChromaDB filtering and dream-consolidated summaries instead.)
  - **What ProbOS adds that Squad lacks.** Squad has no trust scoring (agents are equally trusted forever), no dynamic agent creation (all agents defined at init), no consensus governance (hooks are static rules, not collective agreement), no semantic memory (agents read flat markdown history, not vector-indexed recall), no dream consolidation, no federation. ProbOS's IDE integration would bring all of these to the development workflow — a development squad that *learns* which code patterns work, *earns* trust through successful changes, *remembers* past refactoring outcomes semantically, and *deliberates* on complex architectural decisions through inter-agent dialogue.

### Design Principle: Probabilistic Agents, Consensus Governance

ProbOS must remain probabilistic at its core. There is a critical distinction between **deterministic logic** and **governance**. Agents are not deterministic automata — they are probabilistic entities with Bayesian confidence, stochastic routing (Hebbian weights), and non-deterministic LLM-driven decision-making. Like humans with free will who still follow rules in a society, agents in the ProbOS ecosystem are probabilistic but must still follow consensus.

Consensus is governance, not control. It constrains *outcomes* (quorum approval, trust-weighted voting, red team verification) without constraining the *process* by which agents arrive at those outcomes. An agent may choose how to handle an intent, how confident it is, and what it reports — but destructive actions require collective agreement. This mirrors how societies work: individuals think freely, but shared rules prevent harm.

As ProbOS evolves, every new capability must preserve this principle:
- **Agent behavior stays probabilistic:** Confidence is Bayesian (Beta distributions), routing is learned (Hebbian weights with decay), trust evolves from observations, attention is scored not prescribed, dreaming replays and consolidates stochastically.
- **Governance stays collective:** Consensus is quorum-based (not dictated by a single authority), escalation cascades through tiers, self-modification requires user approval, designed agents start with probationary trust and earn standing through repeated successful interactions.
- **No deterministic overrides:** Avoid hardcoded "always do X" logic. Prefer probabilistic priors that converge toward correct behavior through experience. The system should *learn* what works, not be *told* what works.

### Design Principle: Agent Classification Framework (Core / Utility / Domain)

ProbOS agents belong to one of three architectural tiers. This classification maps directly to the Noöplex's layered architecture (§4): Layer 4 Infrastructure, the Meta-Cognitive Layer (§4.3.3), and Layer 2 Cognitive Meshes (§4.2). The tiers determine routing behavior, governance policy, trust mechanics, and HXI visual rendering. As the agent population grows — especially with Cognitive Agents (Phase 15) and domain meshes — the tier system prevents the flat-pool structure from becoming architecturally incoherent.

**Tier 1: Core (Infrastructure).** Primitive capabilities that everything else builds on. Domain-agnostic, deterministic tool agents. They're the substrate's hands — they touch hardware resources, they're fast, and they're the foundation that all higher-level cognition depends on. In a traditional OS analogy, these are syscalls and device drivers. Every domain mesh uses them. They should never be removed, reorganized, or subordinated to a domain concern. Core agents are always available to all meshes through the shared intent bus.

| Agent | Pool | Intents | Notes |
|-------|------|---------|-------|
| SystemHeartbeatAgent | system | (heartbeat — no user intents) | System rhythm, health monitoring |
| FileReaderAgent | filesystem | read_file, stat_file | |
| FileWriterAgent | filesystem_writers | write_file | Consensus-gated |
| DirectoryListAgent | directory | list_directory | |
| FileSearchAgent | search | search_files | |
| ShellCommandAgent | shell | run_command | Consensus-gated |
| HttpFetchAgent | http | http_fetch | Consensus-gated |
| RedTeamAgent | red_team | (none — invoked directly by consensus pipeline) | Bypasses intent bus (AD-22) |

**Tier 2: Utility (Meta-Cognitive).** System maintenance agents that operate *on* the system, not *for* the user. They monitor, test, and repair. They have access to system internals (trust scores, Hebbian weights, episodic memory stats, agent rosters) that domain agents shouldn't need. They're governed by system-level policies. In the Noöplex, this corresponds to the Meta-Cognitive Layer (§4.3.3): "the system with the ability to reason about its own reasoning — to monitor, evaluate, and direct the cognitive processes occurring across all meshes."

| Agent | Pool | Intents | Notes |
|-------|------|---------|-------|
| IntrospectionAgent | introspect | explain_last, agent_info, system_health, why | All require reflect. Reads `_runtime` reference |
| SystemQAAgent | system_qa | (triggered by self-mod pipeline, not user intents) | Already excluded from decomposer descriptors (AD-158) |
| SkillBasedAgent | skills | (dynamic — varies by attached skills) | Skill carrier/dispatcher. Transitions to domain tier as skills specialize |

Utility agents are already informally separated: `_EXCLUDED_AGENT_TYPES` excludes `system_qa` and `red_team` from decomposer descriptors, RedTeamAgent bypasses the intent bus, IntrospectionAgent intents all require reflect. Formalizing this with a `tier` field replaces ad-hoc exclusion sets with a consistent architectural rule.

**Tier 3: Domain (Cognitive Meshes).** User-facing cognitive work grouped by domain. Each domain is a mesh — a semi-autonomous cognitive community with its own agents, internal Hebbian routing topology, and accumulated expertise. Domains are where Cognitive Agents (Phase 15) live: analyzer, planner, critic, synthesizer agents with domain-specific `instructions`. Currently, designed agents are the first domain-tier agents, though they're not yet organized into formal meshes.

| Domain (future) | Agent Types | Description |
|-----------------|-------------|-------------|
| (unclassified) | Designed agents | Currently created by self-mod pipeline without domain assignment |
| code_development | analyzer, planner, coder, reviewer | IDE/Copilot integration squad |
| data_analysis | data_loader, statistician, visualizer | Analytical cognitive agents |
| research | searcher, synthesizer, fact_checker | Web research and knowledge gathering |

Domain meshes develop their own internal topologies: intra-mesh Hebbian routing learns which agents within the domain work well together, while inter-mesh routing (at the decomposer level) learns which domains are relevant for which intent types. Both use the same Hebbian mechanism — the architecture is fractal. The same patterns that govern agents within a pool govern meshes within a node, and nodes within a federation.

**Routing implications:** The decomposer becomes tier-aware. User intents route to domain meshes first (which domain handles this?), then to agents within the mesh (which agent?). Domain agents dispatch infrastructure needs (file I/O, shell, HTTP) downward to the core tier through the shared intent bus — they never bypass governance by doing their own I/O. Utility agents are invoked by system triggers (self-mod pipeline, dream cycle, health monitoring), not by user intents.

**Governance implications:** Core agents have system trust — they're always available and start with the default Beta(2,2) prior. Utility agents have elevated system trust — they need access to internals and shouldn't be constrained by user-intent trust dynamics. Domain agents earn trust through the normal Bayesian pathway — probationary trust, observation-based updates, decay toward prior. Domain-specific governance policies (from the roadmapped Formal Policy Engine) can apply per-mesh without affecting other domains.

**HXI implications:** The three tiers render differently in the Cognitive Canvas. Core agents form the substrate layer — always visible, stable, the system's foundation. Utility agents form a distinct cluster — visible but separate from productive work, rendered with a different visual quality (perhaps more muted, monitoring-station aesthetics). Domain meshes are the primary visual focus — luminous, active, where the participant sees cognitive work happening. Each domain mesh is a visually coherent cluster with its own internal topology. The tier classification gives the HXI's spatial composition a natural organizing principle.

**Fractal scaling:** This classification proves the Noöplex's fractal hypothesis at the unit-cell scale. The same architectural patterns (agent pools, Hebbian routing, trust, consensus) organize agents within a mesh, meshes within a node, and nodes within a federation. A domain mesh is governed by the same mechanisms as an agent pool — one level up. The three-tier structure within a single ProbOS node is the same three-tier structure the Noöplex describes across a planetary ecosystem: infrastructure substrate, meta-cognitive oversight, and specialized cognitive communities. The unit cell contains the full pattern.

### Foundational Governance Axioms

Three axioms underpin ProbOS's safety model. Unlike Asimov's Three Laws (which were literary devices designed to demonstrate failure modes of absolute rules in autonomous systems), these axioms are mechanistic, testable, and compatible with probabilistic agency. They constrain *outcomes* without constraining the *process* — agents are still free to reason probabilistically, but the governance layer enforces structural safeguards.

1. **Safety Budget:** Every agent action carries an implicit risk score. Low-risk actions (reads, queries) proceed with normal routing. Higher-risk actions (writes, deletes, shell commands) require proportionally stronger consensus — higher quorum thresholds, trust-weighted voting, red team verification. The safety budget is not a hardcoded gate; it is a continuous score that shifts consensus requirements. As an agent's trust grows, its safety budget widens — but destructive actions always require collective agreement regardless of trust.

2. **Reversibility Preference:** When multiple strategies can achieve a goal, prefer the one whose effects are most reversible. Read before write. Backup before delete. Query before mutate. This is enforced at the decomposer level — the DAG planning stage can order nodes to front-load information-gathering and defer state-changing actions. Reversibility is a planning heuristic, not an absolute prohibition: sometimes irreversible actions are the only path, and the system proceeds after appropriate consensus.

3. **Minimal Authority:** Agents request only the capabilities they need for the current task. The capability mesh already enforces this — agents declare their intents, and the router matches only on declared capabilities. Self-modification extends this: designed agents receive a scoped import whitelist, sandboxed execution, and probationary trust. No agent starts with full system access. Authority is earned through repeated successful interactions, not granted by default.

These axioms are already partially implemented across the existing architecture (consensus quorum, CodeValidator, capability mesh, probationary trust). Phase 11 and beyond should formalize them as explicit, testable properties — not as vague principles, but as measurable invariants with test coverage.

---

## Environment

- **Platform:** Windows 11 Pro (10.0.26200)
- **Python:** 3.12.13 (installed via uv)
- **Toolchain:** uv 0.10.9
- **Key deps:** pydantic 2.12.5, pyyaml 6.0.3, aiosqlite 0.22.1, httpx 0.28+, rich 13.0+, chromadb 1.5.4, pytest 9.0.2, pytest-asyncio 1.3.0
- **LLM endpoints:** Fast tier: Ollama at `http://127.0.0.1:11434/v1`, Standard/Deep tier: VS Code Copilot proxy at `http://127.0.0.1:8080/v1`
- **LLM models:** fast=qwen3.5:35b (local Ollama), standard=claude-sonnet-4.6 (Copilot proxy), deep=claude-opus-4.6 (Copilot proxy)
- **Run tests:** `uv run pytest tests/ -v`
- **Run demo:** `uv run python demo.py`
- **Run interactive:** `uv run python -m probos`
