# ProbOS — Architectural Decisions: Era I — Genesis (Phases 1–9)

Archived decisions from the Genesis era. AD-1 through AD-108.

For current decisions, see [DECISIONS.md](DECISIONS.md).

---

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

