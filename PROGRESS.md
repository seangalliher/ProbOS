# ProbOS — Progress Tracker

## Current Status: Phase 12 — HttpFetch User-Agent + Search Strategy (787/787 tests + 11 live LLM)

---

## What's Been Built

### Substrate Layer (complete)

| File | Status | Description |
|------|--------|-------------|
| `pyproject.toml` | done | Project config, deps (pydantic, pyyaml, aiosqlite, rich, pytest) |
| `config/system.yaml` | done | Pool sizes, mesh params, heartbeat intervals, consensus config, memory config, dreaming config, scaling config, federation config, self-mod config, per-tier LLM endpoints (fast=qwen3.5:35b at Ollama localhost:11434 native API, standard=claude-sonnet-4.6 at Copilot proxy localhost:8080, deep=claude-opus-4.6 at Copilot proxy — AD-132), `default_llm_tier: "fast"` (AD-137), `llm_api_format_fast: "ollama"` (AD-145) |
| `src/probos/__init__.py` | done | Package root, version 0.1.0 |
| `src/probos/types.py` | done | `AgentState`, `AgentMeta`, `CapabilityDescriptor`, `IntentMessage`, `IntentResult`, `GossipEntry`, `ConnectionWeight`, `ConsensusOutcome`, `Vote`, `QuorumPolicy`, `ConsensusResult`, `VerificationResult`, `LLMTier`, `LLMRequest`, `LLMResponse`, `EscalationTier` (3-tier cascade levels: retry, arbitration, user), `EscalationResult` (escalation outcome with `to_dict()` for JSON-safe serialization, `tiers_attempted` tracking), `TaskNode` (with `background` field for background demotion, `escalation_result: dict | None` for serialized escalation data), `TaskDAG` (with `response` field for conversational LLM replies, `reflect` field for post-execution synthesis), `Episode` (episodic memory record), `AttentionEntry` (priority scoring for task scheduling), `FocusSnapshot` (cross-request focus history), `DreamReport` (dream cycle results), `WorkflowCacheEntry` (cached workflow pattern), `IntentDescriptor` (structured metadata for dynamic intent discovery: name, params, description, requires_consensus, requires_reflect), `Skill` (modular intent handler with descriptor, source_code, compiled handler — AD-128), `NodeSelfModel` (peer node capability/health snapshot for gossip), `FederationMessage` (wire protocol message between nodes) |
| `src/probos/config.py` | done | `PoolConfig`, `MeshConfig`, `ConsensusConfig`, `CognitiveConfig` (with `max_concurrent_tasks`, `attention_decay_rate`, `focus_history_size`, `background_demotion_factor`, per-tier endpoint fields: `llm_base_url_fast/standard/deep`, `llm_api_key_fast/standard/deep`, `llm_timeout_fast/standard/deep` — all `None` by default for backward compat, per-tier API format: `llm_api_format_fast/standard/deep` — `"ollama"` or `"openai"` (default) — AD-145, `tier_config()` helper returns resolved {base_url, api_key, model, timeout, api_format} per tier — AD-132, `default_llm_tier: str = "fast"` — AD-137), `MemoryConfig`, `DreamingConfig` (idle threshold, dream interval, replay count, strengthening/weakening factors, prune threshold, trust boost/penalty, pre-warm top-K), `ScalingConfig` (scale up/down thresholds, step sizes, cooldown, observation window, idle scale-down), `PeerConfig` (node_id + address for static peer list), `FederationConfig` (enabled, node_id, bind_address, peers, forward_timeout, gossip interval, validate_remote_results), `SelfModConfig` (enabled, require_user_approval, probationary_alpha/beta, max_designed_agents, sandbox_timeout, allowed_imports whitelist, forbidden_patterns regex list, research_enabled, research_domain_whitelist, research_max_pages, research_max_content_per_page — AD-130), `SystemConfig`, `load_config()` — pydantic models loaded from YAML |
| `src/probos/substrate/agent.py` | done | `BaseAgent` ABC — `perceive/decide/act/report` lifecycle, confidence tracking, state transitions, async start/stop, optional `_runtime` reference via `**kwargs`, `**kwargs` passthrough to subclasses, class-level `intent_descriptors: list[IntentDescriptor]` for dynamic intent discovery |
| `src/probos/substrate/registry.py` | done | `AgentRegistry` — in-memory index, lookup by ID/pool/capability, async-safe |
| `src/probos/substrate/spawner.py` | done | `AgentSpawner` — template registration, `spawn(**kwargs)`, `recycle()` with optional respawn, `**kwargs` forwarded to agent constructors |
| `src/probos/substrate/pool.py` | done | `ResourcePool` — maintains N agents at target size, background health loop, auto-recycles degraded agents, `**spawn_kwargs` forwarding for agent construction, `add_agent()`/`remove_agent()` with min/max bounds enforcement, trust-aware scale-down selection |
| `src/probos/substrate/scaler.py` | done | `PoolScaler` — demand-driven background loop, per-pool demand ratio evaluation, scale up/down with cooldown, `request_surge()` for escalation, `scale_down_idle()` for dreaming, pool exclusions, pinned pool detection, `scaling_status()` for shell/panel |
| `src/probos/substrate/heartbeat.py` | done | `HeartbeatAgent` — fixed-interval pulse loop, listener callbacks, gossip carrier |
| `src/probos/substrate/event_log.py` | done | `EventLog` — append-only SQLite event log for lifecycle, mesh, system, and consensus events |
| `src/probos/agents/heartbeat_monitor.py` | done | `SystemHeartbeatAgent` — collects CPU count, load average, platform, PID |

### Mesh Layer (complete)

| File | Status | Description |
|------|--------|-------------|
| `src/probos/mesh/signal.py` | done | `SignalManager` — TTL enforcement, background reaper loop, expiry callbacks |
| `src/probos/mesh/intent.py` | done | `IntentBus` — async pub/sub, concurrent fan-out to subscribers, result collection with timeout, error handling, per-broadcast demand tracking with sliding window, `per_pool_demand()` for scaler, `_federation_fn` callback for federated forwarding, `federated` parameter on `broadcast()` for loop prevention |
| `src/probos/mesh/capability.py` | done | `CapabilityRegistry` — semantic descriptor store, fuzzy matching (exact/substring/keyword), scored results |
| `src/probos/mesh/routing.py` | done | `HebbianRouter` — connection weights with `rel_type` (intent/agent), SQLite persistence, decay_all, preferred target ranking, `record_verification()` |
| `src/probos/mesh/gossip.py` | done | `GossipProtocol` — partial view management, entry injection/merge by recency, random sampling, periodic gossip loop |

### Consensus Layer (complete — new in Phase 2)

| File | Status | Description |
|------|--------|-------------|
| `src/probos/consensus/__init__.py` | done | Package root |
| `src/probos/consensus/quorum.py` | done | `QuorumEngine` — configurable thresholds (2-of-3, 3-of-5, etc.), confidence-weighted voting, `evaluate()` and `evaluate_values()` |
| `src/probos/consensus/trust.py` | done | `TrustNetwork` — Bayesian Beta(alpha, beta) reputation scoring, observation recording, decay toward prior, SQLite persistence, `create_with_prior()` for probationary agents with custom Beta prior (AD-110) |
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
| `src/probos/cognitive/llm_client.py` | done | `BaseLLMClient` ABC, `OpenAICompatibleClient` (per-tier endpoint routing: each tier gets its own base_url/api_key/model/timeout/httpx.AsyncClient, httpx clients deduplicated by base_url — AD-133, per-tier connectivity checks avoiding duplicate probes for shared endpoints — AD-134, response cache keyed by (tier, prompt_hash) — AD-136, `default_tier` read from `CognitiveConfig.default_llm_tier` when config provided — AD-137, `LLMResponse.tier` stores resolved tier not raw `None` — AD-138, backward-compatible legacy kwargs constructor, `tier_info()` for /model display, fallback chain: live → cache → error), `MockLLMClient` (regex pattern matching, canned responses for deterministic testing — supports read_file, write_file, list_directory, search_files, run_command, http_fetch, explain_last, system_health, agent_info, why patterns; escalation arbiter pattern returns reject for deterministic Tier 2 → Tier 3 fallthrough (AD-85); agent_design pattern generates valid BaseAgent source code with `__init__(**kwargs)` + LLM client injection template (AD-111, AD-115); intent_extraction pattern returns JSON with name/description/parameters, prefers general-purpose intents over narrow ones (AD-124); skill_design pattern generates valid async handler function with IntentResult (AD-128); research_query pattern returns JSON array of search queries; research_synthesis pattern returns reference section string (AD-130)) |
| `src/probos/cognitive/working_memory.py` | done | `WorkingMemorySnapshot` (serializable system state), `WorkingMemoryManager` (bounded context assembly from registry/trust/Hebbian/capabilities, token budget eviction) |
| `src/probos/cognitive/decomposer.py` | done | `IntentDecomposer` (NL text + working memory + similar episodes → LLM → `TaskDAG`, dynamic system prompt via `PromptBuilder` when `_intent_descriptors` populated (falls back to `_LEGACY_SYSTEM_PROMPT`), `refresh_descriptors()` for runtime to push new intent sets, aggressive JSON-only system prompt with `response` and `reflect` fields, markdown code fence extraction, `REFLECT_PROMPT` for post-execution synthesis with `[status]` prefix per node for LLM context (AD-121), `reflect()` method sends results back to LLM with payload cap ~8000 chars and truncation, `_summarize_node_result()` deduplicates identical output/result fields (AD-122), PAST EXPERIENCE section for episodic context, PRE-WARM HINTS section for dreaming integration, optional `workflow_cache` for cache-first decomposition with exact + fuzzy matching, `pre_warm_intents` property for runtime sync, `is_capability_gap()` function with `_CAPABILITY_GAP_RE` regex to distinguish capability-gap responses from conversational replies (AD-126), `last_tier`/`last_model` debug state tracking — AD-138, decompose/reflect use `tier=None` to respect configured default — AD-137), `DAGExecutor` (parallel/sequential DAG execution through mesh + consensus, dependency resolution, deadlock detection, `on_event` callback for real-time progress, attention-based priority batching when `AttentionManager` is provided, optional `escalation_manager` for 3-tier error recovery, consensus-rejected nodes now correctly marked "failed" instead of "completed", escalation events: escalation_start, escalation_resolved, escalation_exhausted) |
| `src/probos/cognitive/prompt_builder.py` | done | `PromptBuilder` — dynamically assembles decomposer system prompt from `IntentDescriptor` list. Generates intent table, consensus rules, reflect rules (broadened to include transformation/translation intents). Anti-echo rules for `run_command` (no echo/Write-Host/Write-Output to fake answers). Deterministic output (sorted by name). Constants: `PROMPT_PREAMBLE`, `PROMPT_RESPONSE_FORMAT`, `PROMPT_EXAMPLES` (updated with introspection + time examples) |
| `src/probos/cognitive/episodic.py` | done | `EpisodicMemory` — SQLite-backed long-term memory, `Episode` storage/recall, keyword-overlap similarity search (cosine over bag-of-words), `recall_by_intent()`, `recent()`, `get_stats()`, max_episodes eviction |
| `src/probos/cognitive/episodic_mock.py` | done | `MockEpisodicMemory` — in-memory episodic memory for testing, substring/keyword matching recall, no SQLite dependency |
| `src/probos/cognitive/attention.py` | done | `AttentionManager` — priority scorer and budgeter for task execution, scores = urgency × relevance × deadline_factor × dependency_depth_bonus, configurable concurrency limit (`max_concurrent_tasks`), cross-request focus history (ring buffer of `FocusSnapshot` entries, configurable max size), `_compute_relevance()` (keyword overlap between entry intent and recent focus, floor=0.3), background demotion (configurable factor, default 0.25), queue introspection |
| `src/probos/cognitive/dreaming.py` | done | `DreamingEngine` — offline consolidation: replay recent episodes to strengthen/weaken Hebbian weights, prune below-threshold connections, trust consolidation (boost/penalize agents by track record), pre-warm intent prediction via temporal bigram analysis, `idle_scale_down_fn` callback for pool scaler integration. `DreamScheduler` — background asyncio task monitors idle time, triggers dream cycles after configurable threshold, `force_dream()` for immediate cycles, `is_dreaming` property, `last_dream_report` for introspection |
| `src/probos/cognitive/workflow_cache.py` | done | `WorkflowCache` — in-memory LRU cache of successful DAG patterns, exact and fuzzy lookup (keyword overlap + pre-warm intent subset), deep copy with fresh node IDs on retrieval, popularity-based eviction, stores only fully-successful DAGs |
| `src/probos/cognitive/agent_designer.py` | done | `AgentDesigner` — generates agent source code via LLM for unhandled intents, template-based prompt construction with full `IntentResult`/`IntentMessage` signatures, `BaseAgent` attribute names (`self.id`, `self.pool`, `self.confidence`), `__init__(**kwargs)` with `self._llm_client = kwargs.get("llm_client")`, all 4 abstract lifecycle methods (perceive/decide/act/report), LLM ACCESS section for intelligence tasks (AD-115), `requires_reflect=True` on designed agent descriptors, class name derivation, allowed_imports whitelist enforcement |
| `src/probos/cognitive/code_validator.py` | done | `CodeValidator` — static analysis of generated agent code: syntax check (AST parse), import whitelist enforcement, forbidden pattern regex scan, schema conformance (BaseAgent subclass, intent_descriptors, handle_intent, agent_type, _handled_intents), module-level side effect detection |
| `src/probos/cognitive/sandbox.py` | done | `SandboxRunner` — test-executes generated agents in isolated context: temp file write, importlib dynamic loading, BaseAgent subclass discovery, synthetic IntentMessage test, IntentResult type verification, configurable timeout, LLM client forwarding to sandboxed agents |
| `src/probos/cognitive/behavioral_monitor.py` | done | `BehavioralMonitor` — monitors self-created agents for behavioral anomalies: execution time tracking, failure rate alerting (>50% over 5+ executions), slow execution detection (>5s avg), trust trajectory decline detection, removal recommendation (failure rate >50% over 10+ or consecutive trust decline) |
| `src/probos/cognitive/self_mod.py` | done | `SelfModificationPipeline` — orchestrates full self-modification flow: config check (max_designed_agents limit), optional user approval gate, AgentDesigner code generation, CodeValidator static analysis, SandboxRunner functional testing, agent type registration, pool creation, BehavioralMonitor tracking. `DesignedAgentRecord` dataclass for history (with `strategy` field: "new_agent" or "skill"). `handle_add_skill()` — skill design pipeline: SkillDesigner code generation, SkillValidator validation, importlib compilation, Skill object creation, add_skill_fn callback for pool injection (AD-129). Optional `ResearchPhase` integration when research_enabled=True (AD-131) |
| `src/probos/cognitive/strategy.py` | done | `StrategyRecommender` — heuristic-based strategy proposal for unhandled intents: keyword overlap between intent and existing descriptors, `add_skill` strategy with reversibility bonus, `new_agent` fallback. `StrategyOption` (strategy, label, reason, confidence, target_agent_type, is_recommended), `StrategyProposal` (options sorted by confidence, `.recommended` property). LLM-equipped types filtering (AD-127) |
| `src/probos/cognitive/skill_designer.py` | done | `SkillDesigner` — generates async skill handler functions via LLM, template-based prompt construction with IntentResult/IntentMessage signatures, LLM ACCESS section, research context injection, `_build_function_name()` conversion (AD-128) |
| `src/probos/cognitive/skill_validator.py` | done | `SkillValidator` — static analysis of generated skill code: syntax check, import whitelist, forbidden patterns, schema conformance (async function named handle_{intent_name}), module-level side effect detection (AD-128) |
| `src/probos/cognitive/research.py` | done | `ResearchPhase` — web research before agent/skill design: LLM-generated search queries, domain-whitelisted URL construction via urllib.parse, mesh-based page fetching (uses HttpFetchAgent + consensus), content truncation, LLM synthesis. Security: all fetches go through existing mesh, content truncated before LLM, output is context only (never executed — code still goes through CodeValidator + SandboxRunner) (AD-130, AD-131) |

### Experience Layer (complete — new in Phase 4)

| File | Status | Description |
|------|--------|-------------|
| `src/probos/experience/__init__.py` | done | Package root |
| `src/probos/experience/panels.py` | done | Rich rendering functions: `render_status_panel()` (with dreaming state section), `render_agent_table()`, `render_weight_table()`, `render_trust_panel()`, `render_gossip_panel()`, `render_event_log_table()`, `render_working_memory_panel()`, `render_attention_panel()` (with focus history display and background task indicator), `render_dag_result()` (displays `response` field for conversational replies), `render_dream_panel()` (dream cycle report with pre-warm intents), `render_workflow_cache_panel()` (cached workflow patterns with hit counts), `render_scaling_panel()` (pool scaling status with demand ratio, size range, cooldown), `render_federation_panel()` (federation node status, connected peers, forwarded/received counts), `render_peers_panel()` (peer self-model table: capabilities, agent count, health, uptime), `render_designed_panel()` (self-designed agent status table with sandbox time and behavioral alerts), `format_health()` — state-coloured agent displays (ACTIVE=green, DEGRADED=yellow, RECYCLING=red, SPAWNING=blue) |
| `src/probos/experience/renderer.py` | done | `ExecutionRenderer` — DAG execution display with status spinner (Rich Live removed — AD-92), `on_event` callback integration (including `scale_up`/`scale_down`/`federation_forward`/`federation_receive`/`self_mod_design`/`self_mod_success`/`self_mod_failure` events), conversational response display when LLM returns `response` field, execution snapshot for introspection (`_previous_execution`/`_last_execution`), debug mode (raw DAG JSON, individual agent responses, consensus details, **tier/model in debug panel title** — AD-138), DAG plan display in debug-only mode (AD-90), Params column in progress table, manually-managed spinner with `_stop_live_for_user` hook for Tier 3 escalation (AD-93). Self-mod UX: `StrategyRecommender` integration with numbered strategy menu (AD-127), `add_skill` strategy dispatch when available (AD-129), existing-agent re-routing when LLM extracts already-registered intent, capability-gap detection gates self-mod (AD-126), force `reflect=True` on designed-agent DAGs |
| `src/probos/experience/shell.py` | done | `ProbOSShell` — async REPL with slash commands (`/status`, `/agents`, `/weights`, `/gossip`, `/log`, `/memory`, `/attention`, `/history`, `/recall`, `/dream`, `/cache`, `/scaling`, `/federation`, `/peers`, `/designed`, `/explain`, `/model`, `/tier`, `/debug`, `/help`, `/quit`), NL input routing, ambient health prompt `[N agents | health: 0.XX] probos>`, user approval callback for self-mod agent creation (AD-123), `/model` shows per-tier endpoint/model/status with shared-endpoint notes (AD-135), `/tier` switch shows endpoint URL, graceful error handling |

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
| `src/probos/agents/introspect.py` | done | `IntrospectionAgent` — self-referential queries about ProbOS state, `intent_descriptors` with `requires_reflect=True` for all 4 intents: `explain_last`, `agent_info`, `system_health`, `why`. Reads `_runtime` reference, purely observational |
| `src/probos/substrate/skill_agent.py` | done | `SkillBasedAgent` — general-purpose agent dispatching intents to attached Skill objects, `add_skill()` updates both instance AND class-level `_handled_intents` and `intent_descriptors` (AD-128), `remove_skill()` cleans up both levels, `handle_intent()` passes `llm_client` to skill handlers, `skills` pool only spawned when `self_mod.enabled=True` (AD-129) |

### Runtime

| File | Status | Description |
|------|--------|-------------|
| `src/probos/runtime.py` | done | `ProbOSRuntime` — orchestrates substrate + mesh + consensus + cognitive + episodic memory + attention + dreaming + workflow cache + introspection + dynamic intent discovery + federation + self-modification + skills + research. Spawns pools: system (2 heartbeats), filesystem (3 file_readers), filesystem_writers (3 file_writers), directory (3 directory_list), search (3 file_search), shell (3 shell_command), http (3 http_fetch), introspect (2 introspection agents with runtime=self), skills (2 skill_agents with llm_client — only when self_mod.enabled), red_team (2 verifiers). 24-26 agents total. Federation: `FederationBridge` with `FederationRouter`, `_build_self_model()` (NodeSelfModel Psi with capabilities, pool sizes, health, uptime), `_validate_remote_result()` placeholder, wires `bridge.forward_intent` as `intent_bus._federation_fn`. Self-modification: creates `SelfModificationPipeline` with `SkillDesigner`/`SkillValidator`/`add_skill_fn` when `config.self_mod.enabled=True`, optional `ResearchPhase` when `research_enabled=True` (AD-131), `_extract_unhandled_intent()` via LLM (prefers general-purpose intents over narrow ones — AD-124), auto-design when decomposer returns empty DAG or capability-gap response (AD-126), `_register_designed_agent()`, `_create_designed_pool()`, `_set_probationary_trust()`, `_get_llm_equipped_types()` for strategy recommender, `_add_skill_to_agents()` for skill injection into skills pool (AD-129), LLM client injected into designed agent pools (AD-115). `register_agent_type()` registers new agent class and refreshes decomposer descriptors. `_collect_intent_descriptors()` deduplicates across all registered templates (including SkillBasedAgent class-level descriptors). Boot-time `refresh_descriptors()` call after pool creation syncs decomposer with all registered intents. `process_natural_language(text, on_event=None)` with event callback support, attention focus update, dream scheduler activity tracking, pre-warm intent sync to decomposer, execution snapshot pattern (`_previous_execution`/`_last_execution` for introspection without self-overwrite), post-execution reflect step, episodic episode storage, workflow cache storage on success, `recall_similar()` for semantic search. `DreamScheduler` created at start when episodic memory is available. `WorkflowCache` created at init, passed to decomposer, exposed in `status()` |
| `src/probos/__main__.py` | done | Entry point: `uv run python -m probos [--config path]` — boot sequence display with per-tier LLM connectivity checks (each tier checked independently, partial connectivity continues with warning, all-unreachable falls back to MockLLMClient — AD-134), creates `EpisodicMemory` (SQLite in temp dir), interactive shell launch, `--config` flag for node-specific YAML, `WindowsSelectorEventLoopPolicy` for pyzmq compatibility on Windows (AD-108), noisy INFO log suppression for interactive shell (AD-125) |
| `config/node-1.yaml` | done | Node 1 federation config: bind tcp://127.0.0.1:5555, peers=[node-2] |
| `config/node-2.yaml` | done | Node 2 federation config: bind tcp://127.0.0.1:5556, peers=[node-1] |
| `scripts/launch-cluster.sh` | done | Launches 2-node ProbOS federation cluster in background processes |
| `demo.py` | done | Full Rich demo: consensus reads, corrupted agent injection, trust/Hebbian display, NL pipeline with visual feedback, event log |

---

## What's Working

**736/736 tests pass.** Test suite covers:

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

### AD-48: Keyword-overlap embedding for episodic recall

Episodic memory uses a lightweight keyword-overlap similarity approach instead of a heavyweight embedding model (ChromaDB + Sentence Transformers). Text is tokenized into lowercase alphanumeric tokens with stop words removed, producing a sparse bag-of-words vector. Cosine similarity over these vectors provides recall. This trades recall precision for zero additional dependencies and fast startup. The `EpisodicMemory` class uses SQLite for persistence; `MockEpisodicMemory` uses an in-memory list with substring matching.

### AD-49: MockEpisodicMemory for testing

Same pattern as `MockLLMClient`: `MockEpisodicMemory` implements the same interface as `EpisodicMemory` but stores episodes in a plain list. Recall uses keyword-set overlap instead of cosine similarity over embeddings. This keeps the test suite deterministic and fast — no SQLite, no embedding computation.

### AD-50: Episode storage is fire-and-forget

Episode storage in `runtime.py` is wrapped in a try/except. If storage fails (SQLite error, serialization error, etc.), the failure is logged as a warning but never blocks the user's result. The execution result is always returned regardless of whether the episode was successfully stored.

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

`WorkflowCache.lookup_fuzzy()` requires BOTH conditions to return a hit: (1) at least one pre-warm intent must match an intent stored in the cached DAG, AND (2) keyword overlap between the query and cached pattern must be ≥50%. This dual requirement prevents false positives — a request for "fetch website data" won't match a cached "read the file" workflow just because both contain common words. Pre-warm intents provide semantic signal; keyword overlap provides lexical signal.

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

## What's Next

- [x] ~~Plan Phase 1 implementation~~
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
- [ ] **SystemQAAgent (Internal Self-Testing):** A runtime self-monitoring agent that validates designed agents after self-modification. On every successful self-mod pipeline, SystemQAAgent smoke-tests the newly designed agent with synthetic intents, verifies the output shape and content, records pass/fail outcomes in episodic memory, and uses the trust network to flag flaky agents for demotion or redesign. Complements the external `pytest -m live_llm` integration tests with always-on internal quality assurance — the system tests itself as it evolves.
- [ ] **Phase 3b-3b (Cognitive continued):** Preemption of already-running tasks
- [ ] **Phase 6 (Expansion continued):** Process management, calendar, email, code execution
- [x] ~~**Phase 11: Skills, Transparency & Web Research** — Strategy proposals with confidence scores, SkillBasedAgent with modular intent handlers, web research phase for agent design (see `prompts/phase-11-skills-transparency-research.md`)~~
- [x] ~~**Per-Tier LLM Endpoints:** Each LLM tier (fast/standard/deep) gets its own `base_url` + `api_key` + `model` (see `prompts/phase-12-per-tier-llm.md`)~~
- [ ] **Episodic Memory Upgrade (ChromaDB):** Replace keyword-overlap bag-of-words similarity in `EpisodicMemory` with ChromaDB vector store for true semantic recall. ChromaDB runs embedded (no external server), supports real embeddings, and enables similarity search that understands meaning ("find past tasks about deployment" matches "push to production"). The current SQLite store becomes the persistence layer; ChromaDB provides the retrieval layer. This also upgrades workflow cache fuzzy matching, capability registry matching, and strategy recommender keyword overlap — all currently using hand-rolled tokenization that ChromaDB embeddings would replace. (Original vision: `Vibes/probos-claude-code-prompt.md` line 123.)
- [ ] **Long-term Knowledge Store (Git-backed):** Replace volatile SQLite episodic memory (currently in temp dir, lost on reboot) with a Git-backed knowledge repository. Episodes, designed agents/skills, workflow cache entries, and trust snapshots become versioned artifacts — commits are episodes, diffs are self-modification audit trails, branches are experimental agent designs. Enables: durable history across restarts, federated knowledge sync via push/pull (complementing ZMQ gossip), self-mod rollback via `git revert`, and blame-based provenance ("which agent design introduced this behavior?"). The Git repo *is* the system's long-term memory — fractal with the rest of the architecture (nodes are repos, federations are remotes). ChromaDB provides fast semantic retrieval over the Git-stored episodes.
- [ ] **Semantic Knowledge Layer:** A query layer that sits above the storage tiers (ChromaDB for short-term retrieval, Git for long-term persistence) and exposes unified semantic search across all system knowledge — episodes, designed agents, skills, workflow cache entries, trust history, escalation outcomes, dream reports. Natural language queries like "what agents have I built for text processing?" or "show me tasks that failed due to missing permissions" search across all knowledge types with ranked results. This layer enables: agents to reason about the system's own history during planning (decomposer context), the strategy recommender to find precedent ("we built a similar skill last week"), research-informed design to check if a capability already exists before fetching docs, and user-facing commands (`/search`, `/knowledge`) for exploring system state. Implemented as a thin orchestrator over ChromaDB collections — each knowledge type (episodes, agents, skills, workflows, trust) is a collection with typed metadata, and the semantic layer fans out queries and merges results by relevance score.

### Design Principle: Probabilistic Agents, Consensus Governance

ProbOS must remain probabilistic at its core. There is a critical distinction between **deterministic logic** and **governance**. Agents are not deterministic automata — they are probabilistic entities with Bayesian confidence, stochastic routing (Hebbian weights), and non-deterministic LLM-driven decision-making. Like humans with free will who still follow rules in a society, agents in the ProbOS ecosystem are probabilistic but must still follow consensus.

Consensus is governance, not control. It constrains *outcomes* (quorum approval, trust-weighted voting, red team verification) without constraining the *process* by which agents arrive at those outcomes. An agent may choose how to handle an intent, how confident it is, and what it reports — but destructive actions require collective agreement. This mirrors how societies work: individuals think freely, but shared rules prevent harm.

As ProbOS evolves, every new capability must preserve this principle:
- **Agent behavior stays probabilistic:** Confidence is Bayesian (Beta distributions), routing is learned (Hebbian weights with decay), trust evolves from observations, attention is scored not prescribed, dreaming replays and consolidates stochastically.
- **Governance stays collective:** Consensus is quorum-based (not dictated by a single authority), escalation cascades through tiers, self-modification requires user approval, designed agents start with probationary trust and earn standing through repeated successful interactions.
- **No deterministic overrides:** Avoid hardcoded "always do X" logic. Prefer probabilistic priors that converge toward correct behavior through experience. The system should *learn* what works, not be *told* what works.

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
- **Key deps:** pydantic 2.12.5, pyyaml 6.0.3, aiosqlite 0.22.1, httpx 0.28+, rich 13.0+, pytest 9.0.2, pytest-asyncio 1.3.0
- **LLM endpoints:** Fast tier: Ollama at `http://127.0.0.1:11434/v1`, Standard/Deep tier: VS Code Copilot proxy at `http://127.0.0.1:8080/v1`
- **LLM models:** fast=qwen3.5:35b (local Ollama), standard=claude-sonnet-4.6 (Copilot proxy), deep=claude-opus-4.6 (Copilot proxy)
- **Run tests:** `uv run pytest tests/ -v`
- **Run demo:** `uv run python demo.py`
- **Run interactive:** `uv run python -m probos`
