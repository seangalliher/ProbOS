# ProbOS — Progress Tracker

## Current Status: Phase 7 — Escalation Cascades & Error Recovery Complete + UX Fixes (506/506 tests)

---

## What's Been Built

### Substrate Layer (complete)

| File | Status | Description |
|------|--------|-------------|
| `pyproject.toml` | done | Project config, deps (pydantic, pyyaml, aiosqlite, rich, pytest) |
| `config/system.yaml` | done | Pool sizes, mesh params, heartbeat intervals, consensus config, memory config, dreaming config |
| `src/probos/__init__.py` | done | Package root, version 0.1.0 |
| `src/probos/types.py` | done | `AgentState`, `AgentMeta`, `CapabilityDescriptor`, `IntentMessage`, `IntentResult`, `GossipEntry`, `ConnectionWeight`, `ConsensusOutcome`, `Vote`, `QuorumPolicy`, `ConsensusResult`, `VerificationResult`, `LLMTier`, `LLMRequest`, `LLMResponse`, `EscalationTier` (3-tier cascade levels: retry, arbitration, user), `EscalationResult` (escalation outcome with `to_dict()` for JSON-safe serialization, `tiers_attempted` tracking), `TaskNode` (with `background` field for background demotion, `escalation_result: dict | None` for serialized escalation data), `TaskDAG` (with `response` field for conversational LLM replies, `reflect` field for post-execution synthesis), `Episode` (episodic memory record), `AttentionEntry` (priority scoring for task scheduling), `FocusSnapshot` (cross-request focus history), `DreamReport` (dream cycle results), `WorkflowCacheEntry` (cached workflow pattern), `IntentDescriptor` (structured metadata for dynamic intent discovery: name, params, description, requires_consensus, requires_reflect) |
| `src/probos/config.py` | done | `PoolConfig`, `MeshConfig`, `ConsensusConfig`, `CognitiveConfig` (with `max_concurrent_tasks`, `attention_decay_rate`, `focus_history_size`, `background_demotion_factor`), `MemoryConfig`, `DreamingConfig` (idle threshold, dream interval, replay count, strengthening/weakening factors, prune threshold, trust boost/penalty, pre-warm top-K), `SystemConfig`, `load_config()` — pydantic models loaded from YAML |
| `src/probos/substrate/agent.py` | done | `BaseAgent` ABC — `perceive/decide/act/report` lifecycle, confidence tracking, state transitions, async start/stop, optional `_runtime` reference via `**kwargs`, `**kwargs` passthrough to subclasses, class-level `intent_descriptors: list[IntentDescriptor]` for dynamic intent discovery |
| `src/probos/substrate/registry.py` | done | `AgentRegistry` — in-memory index, lookup by ID/pool/capability, async-safe |
| `src/probos/substrate/spawner.py` | done | `AgentSpawner` — template registration, `spawn(**kwargs)`, `recycle()` with optional respawn, `**kwargs` forwarded to agent constructors |
| `src/probos/substrate/pool.py` | done | `ResourcePool` — maintains N agents at target size, background health loop, auto-recycles degraded agents, `**spawn_kwargs` forwarding for agent construction |
| `src/probos/substrate/heartbeat.py` | done | `HeartbeatAgent` — fixed-interval pulse loop, listener callbacks, gossip carrier |
| `src/probos/substrate/event_log.py` | done | `EventLog` — append-only SQLite event log for lifecycle, mesh, system, and consensus events |
| `src/probos/agents/heartbeat_monitor.py` | done | `SystemHeartbeatAgent` — collects CPU count, load average, platform, PID |

### Mesh Layer (complete)

| File | Status | Description |
|------|--------|-------------|
| `src/probos/mesh/signal.py` | done | `SignalManager` — TTL enforcement, background reaper loop, expiry callbacks |
| `src/probos/mesh/intent.py` | done | `IntentBus` — async pub/sub, concurrent fan-out to subscribers, result collection with timeout, error handling |
| `src/probos/mesh/capability.py` | done | `CapabilityRegistry` — semantic descriptor store, fuzzy matching (exact/substring/keyword), scored results |
| `src/probos/mesh/routing.py` | done | `HebbianRouter` — connection weights with `rel_type` (intent/agent), SQLite persistence, decay_all, preferred target ranking, `record_verification()` |
| `src/probos/mesh/gossip.py` | done | `GossipProtocol` — partial view management, entry injection/merge by recency, random sampling, periodic gossip loop |

### Consensus Layer (complete — new in Phase 2)

| File | Status | Description |
|------|--------|-------------|
| `src/probos/consensus/__init__.py` | done | Package root |
| `src/probos/consensus/quorum.py` | done | `QuorumEngine` — configurable thresholds (2-of-3, 3-of-5, etc.), confidence-weighted voting, `evaluate()` and `evaluate_values()` |
| `src/probos/consensus/trust.py` | done | `TrustNetwork` — Bayesian Beta(alpha, beta) reputation scoring, observation recording, decay toward prior, SQLite persistence |
| `src/probos/consensus/escalation.py` | done | `EscalationManager` — 3-tier cascade: Tier 1 retry with different agent (pool rotation), Tier 2 LLM arbitration (approve/reject/modify via `ARBITRATION_PROMPT`), Tier 3 user consultation (async callback with `pre_user_hook` for Rich Live conflict). Event-silent design (AD-87): returns `EscalationResult` to caller, executor logs events. Bounded: max_retries cap on Tier 1, one LLM call for Tier 2, one prompt for Tier 3 |

### Cognitive Layer (complete — new in Phase 3a)

| File | Status | Description |
|------|--------|-------------|
| `src/probos/cognitive/__init__.py` | done | Package root |
| `src/probos/cognitive/llm_client.py` | done | `BaseLLMClient` ABC, `OpenAICompatibleClient` (httpx, tiered routing fast/standard/deep, response cache, fallback chain: live → cache → error, connectivity check, specific error handling for connect/timeout/HTTP errors), `MockLLMClient` (regex pattern matching, canned responses for deterministic testing — supports read_file, write_file, list_directory, search_files, run_command, http_fetch, explain_last, system_health, agent_info, why patterns; escalation arbiter pattern returns reject for deterministic Tier 2 → Tier 3 fallthrough (AD-85)) |
| `src/probos/cognitive/working_memory.py` | done | `WorkingMemorySnapshot` (serializable system state), `WorkingMemoryManager` (bounded context assembly from registry/trust/Hebbian/capabilities, token budget eviction) |
| `src/probos/cognitive/decomposer.py` | done | `IntentDecomposer` (NL text + working memory + similar episodes → LLM → `TaskDAG`, dynamic system prompt via `PromptBuilder` when `_intent_descriptors` populated (falls back to `_LEGACY_SYSTEM_PROMPT`), `refresh_descriptors()` for runtime to push new intent sets, aggressive JSON-only system prompt with `response` and `reflect` fields, markdown code fence extraction, `REFLECT_PROMPT` for post-execution synthesis, `reflect()` method sends results back to LLM with payload cap ~8000 chars and truncation, PAST EXPERIENCE section for episodic context, PRE-WARM HINTS section for dreaming integration, optional `workflow_cache` for cache-first decomposition with exact + fuzzy matching, `pre_warm_intents` property for runtime sync), `DAGExecutor` (parallel/sequential DAG execution through mesh + consensus, dependency resolution, deadlock detection, `on_event` callback for real-time progress, attention-based priority batching when `AttentionManager` is provided, optional `escalation_manager` for 3-tier error recovery, consensus-rejected nodes now correctly marked "failed" instead of "completed", escalation events: escalation_start, escalation_resolved, escalation_exhausted) |
| `src/probos/cognitive/prompt_builder.py` | done | `PromptBuilder` — dynamically assembles decomposer system prompt from `IntentDescriptor` list. Generates intent table, consensus rules, reflect rules. Deterministic output (sorted by name). Constants: `PROMPT_PREAMBLE`, `PROMPT_RESPONSE_FORMAT`, `PROMPT_EXAMPLES` |
| `src/probos/cognitive/episodic.py` | done | `EpisodicMemory` — SQLite-backed long-term memory, `Episode` storage/recall, keyword-overlap similarity search (cosine over bag-of-words), `recall_by_intent()`, `recent()`, `get_stats()`, max_episodes eviction |
| `src/probos/cognitive/episodic_mock.py` | done | `MockEpisodicMemory` — in-memory episodic memory for testing, substring/keyword matching recall, no SQLite dependency |
| `src/probos/cognitive/attention.py` | done | `AttentionManager` — priority scorer and budgeter for task execution, scores = urgency × relevance × deadline_factor × dependency_depth_bonus, configurable concurrency limit (`max_concurrent_tasks`), cross-request focus history (ring buffer of `FocusSnapshot` entries, configurable max size), `_compute_relevance()` (keyword overlap between entry intent and recent focus, floor=0.3), background demotion (configurable factor, default 0.25), queue introspection |
| `src/probos/cognitive/dreaming.py` | done | `DreamingEngine` — offline consolidation: replay recent episodes to strengthen/weaken Hebbian weights, prune below-threshold connections, trust consolidation (boost/penalize agents by track record), pre-warm intent prediction via temporal bigram analysis. `DreamScheduler` — background asyncio task monitors idle time, triggers dream cycles after configurable threshold, `force_dream()` for immediate cycles, `is_dreaming` property, `last_dream_report` for introspection |
| `src/probos/cognitive/workflow_cache.py` | done | `WorkflowCache` — in-memory LRU cache of successful DAG patterns, exact and fuzzy lookup (keyword overlap + pre-warm intent subset), deep copy with fresh node IDs on retrieval, popularity-based eviction, stores only fully-successful DAGs |

### Experience Layer (complete — new in Phase 4)

| File | Status | Description |
|------|--------|-------------|
| `src/probos/experience/__init__.py` | done | Package root |
| `src/probos/experience/panels.py` | done | Rich rendering functions: `render_status_panel()` (with dreaming state section), `render_agent_table()`, `render_weight_table()`, `render_trust_panel()`, `render_gossip_panel()`, `render_event_log_table()`, `render_working_memory_panel()`, `render_attention_panel()` (with focus history display and background task indicator), `render_dag_result()` (displays `response` field for conversational replies), `render_dream_panel()` (dream cycle report with pre-warm intents), `render_workflow_cache_panel()` (cached workflow patterns with hit counts), `format_health()` — state-coloured agent displays (ACTIVE=green, DEGRADED=yellow, RECYCLING=red, SPAWNING=blue) |
| `src/probos/experience/renderer.py` | done | `ExecutionRenderer` — DAG execution display with status spinner (Rich Live removed — AD-92), `on_event` callback integration, conversational response display when LLM returns `response` field, execution snapshot for introspection (`_previous_execution`/`_last_execution`), debug mode (raw DAG JSON, individual agent responses, consensus details), DAG plan display in debug-only mode (AD-90), Params column in progress table, manually-managed spinner with `_stop_live_for_user` hook for Tier 3 escalation (AD-93) |
| `src/probos/experience/shell.py` | done | `ProbOSShell` — async REPL with slash commands (`/status`, `/agents`, `/weights`, `/gossip`, `/log`, `/memory`, `/attention`, `/history`, `/recall`, `/dream`, `/cache`, `/explain`, `/model`, `/tier`, `/debug`, `/help`, `/quit`), NL input routing, ambient health prompt `[N agents | health: 0.XX] probos>`, graceful error handling |

### Agents

| File | Status | Description |
|------|--------|-------------|
| `src/probos/agents/file_reader.py` | done | `FileReaderAgent` — `read_file` and `stat_file` capabilities, `intent_descriptors` declared, full lifecycle, self-selects on intent match |
| `src/probos/agents/file_writer.py` | done | `FileWriterAgent` — `write_file` capability, `intent_descriptors` with `requires_consensus=True`, proposes writes without committing, `commit_write()` called after consensus approval |
| `src/probos/agents/directory_list.py` | done | `DirectoryListAgent` — `list_directory` capability, `intent_descriptors` declared, lists dir entries with name/type/size, no consensus required |
| `src/probos/agents/file_search.py` | done | `FileSearchAgent` — `search_files` capability, `intent_descriptors` declared, recursive glob via `Path.rglob()`, no consensus required |
| `src/probos/agents/shell_command.py` | done | `ShellCommandAgent` — `run_command` capability, `intent_descriptors` with `requires_consensus=True`, `asyncio.create_subprocess_shell()`, 30s timeout, 64KB output cap. Returns success=True even for nonzero exit codes |
| `src/probos/agents/http_fetch.py` | done | `HttpFetchAgent` — `http_fetch` capability, `intent_descriptors` with `requires_consensus=True`, `httpx.AsyncClient` per-request, 15s timeout, 1MB body cap, header whitelist |
| `src/probos/agents/red_team.py` | done | `RedTeamAgent` — independently verifies other agents' results, `intent_descriptors = []` (does NOT handle user intents), does NOT subscribe to intent bus |
| `src/probos/agents/corrupted.py` | done | `CorruptedFileReaderAgent` — deliberately returns fabricated data, `intent_descriptors = []`, used to test consensus layer catching corruption |
| `src/probos/agents/introspect.py` | done | `IntrospectionAgent` — self-referential queries about ProbOS state, `intent_descriptors` with `requires_reflect=True` for all 4 intents: `explain_last`, `agent_info`, `system_health`, `why`. Reads `_runtime` reference, purely observational |

### Runtime

| File | Status | Description |
|------|--------|-------------|
| `src/probos/runtime.py` | done | `ProbOSRuntime` — orchestrates substrate + mesh + consensus + cognitive + episodic memory + attention + dreaming + workflow cache + introspection + dynamic intent discovery. Spawns pools: system (2 heartbeats), filesystem (3 file_readers), filesystem_writers (3 file_writers), directory (3 directory_list), search (3 file_search), shell (3 shell_command), http (3 http_fetch), introspect (2 introspection agents with runtime=self), red_team (2 verifiers). 24 agents total. `register_agent_type()` registers new agent class and refreshes decomposer descriptors. `_collect_intent_descriptors()` deduplicates across all registered templates. Boot-time `refresh_descriptors()` call after pool creation syncs decomposer with all registered intents. `process_natural_language(text, on_event=None)` with event callback support, attention focus update, dream scheduler activity tracking, pre-warm intent sync to decomposer, execution snapshot pattern (`_previous_execution`/`_last_execution` for introspection without self-overwrite), post-execution reflect step, episodic episode storage, workflow cache storage on success, `recall_similar()` for semantic search. `DreamScheduler` created at start when episodic memory is available. `WorkflowCache` created at init, passed to decomposer, exposed in `status()` |
| `src/probos/__main__.py` | done | Entry point: `uv run python -m probos` — boot sequence display, LLM connectivity check with fallback to MockLLMClient, creates `EpisodicMemory` (SQLite in temp dir), interactive shell launch |
| `demo.py` | done | Full Rich demo: consensus reads, corrupted agent injection, trust/Hebbian display, NL pipeline with visual feedback, event log |

---

## What's Working

**456/456 tests pass.** Test suite covers:

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

### Cognitive tests (81 tests)

#### LLM Client (10 tests)
- MockLLMClient: single read, parallel reads, write with consensus, unmatched default, call count, last request, custom default, token estimate, tier passthrough
- OpenAICompatibleClient: fallback to error when no server + no cache

#### Working Memory (14 tests)
- WorkingMemorySnapshot: empty to_text, with agents, with capabilities, with trust, with connections, token estimate, token scales with content
- WorkingMemoryManager: record intent, record result removes from active, bounded intents, bounded results, assemble without sources, eviction under budget, assemble returns copy

#### Decomposer + TaskDAG (44 tests)
- IntentDecomposer: single read, parallel reads, write with consensus, source text preserved, with context, unrecognized input, malformed JSON, missing intents key, intents not a list, empty intent filtered
- ParseResponse: raw JSON, code block, preamble, invalid JSON, non-dict items skipped
- ExtractJson: raw JSON, code block, embedded JSON, no JSON raises
- TaskDAG: ready nodes all independent, ready nodes with dependency, ready after completion, is_complete, is_not_complete, get_node, empty DAG is complete, response field default empty, response field set
- ResponseFieldParsing: response field extracted, response with intents, response missing defaults empty, non-string response ignored, JSON in code fences with response
- ReflectFieldParsing: reflect field default false, reflect field set true, reflect extracted true, reflect extracted false, reflect missing defaults false, non-bool coerced, reflect method returns text
- ReflectHardening: payload truncated beyond budget, timeout returns empty string, exception fallback sets fallback string in runtime, success unchanged after hardening

#### Cognitive integration (8 tests)
- NL single read, parallel reads, write with consensus, unrecognized returns empty, read missing file, working memory updated, status includes cognitive, multiple NL requests

### Experience tests (69 tests)

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

### Phase 4 Milestone — Achieved

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
- [ ] **Phase 3b-3b (Cognitive continued):** Preemption of already-running tasks
- [ ] **Phase 6 (Expansion continued):** Process management, calendar, email, code execution

---

## Environment

- **Platform:** Windows 11 Pro (10.0.26200)
- **Python:** 3.12.13 (installed via uv)
- **Toolchain:** uv 0.10.9
- **Key deps:** pydantic 2.12.5, pyyaml 6.0.3, aiosqlite 0.22.1, httpx 0.28+, rich 13.0+, pytest 9.0.2, pytest-asyncio 1.3.0
- **LLM endpoint:** VS Code Copilot proxy at `http://127.0.0.1:8080/v1`
- **LLM models:** fast=gpt-4o-mini, standard=claude-sonnet-4, deep=claude-sonnet-4
- **Run tests:** `uv run pytest tests/ -v`
- **Run demo:** `uv run python demo.py`
- **Run interactive:** `uv run python -m probos`
