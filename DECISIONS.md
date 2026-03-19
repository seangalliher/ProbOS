# ProbOS — Architectural Decisions

Append-only log of architectural decisions made during ProbOS development. Each AD documents the reasoning behind a design choice.

See [PROGRESS.md](PROGRESS.md) for project status. See [docs/development/roadmap.md](docs/development/roadmap.md) for future plans.

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

### AD-273: Conversation Context for Decomposer

**Problem:** Each message was stateless — the decomposer couldn't resolve references like "What about Portland?" after a Seattle weather query. The system felt "born 5 minutes ago" every time.

| AD | Decision |
|----|----------|
| AD-273 | HXI sends last 10 chat messages as `history` in ChatRequest. Runtime passes to decomposer as `conversation_history`. Decomposer injects last 5 messages (truncated to 200 chars) as CONVERSATION CONTEXT section in LLM prompt. LLM resolves references naturally. Optional parameter — backward compatible with shell/tests |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/api.py` | ChatMessage model, history field on ChatRequest, passed to process_natural_language() |
| `src/probos/runtime.py` | conversation_history parameter on process_natural_language(), passed to decomposer |
| `src/probos/cognitive/decomposer.py` | conversation_history parameter on decompose(), CONVERSATION CONTEXT prompt section |
| `ui/src/components/IntentSurface.tsx` | Sends last 10 messages as history in /api/chat request |

1578/1578 tests passing (+ 11 skipped). 3 new tests.

### E2E Self-Mod Pipeline Tests

Added `tests/test_selfmod_e2e.py` — 12 integration tests exercising the full self-mod chain through the FastAPI API layer using httpx AsyncClient with ASGITransport. Covers: capability gap detection, self-mod approve + agent creation, pool size 1, auto-retry message routing, QA ordering, hello response, conversation history passthrough, enrich endpoint, empty message, self-mod disabled, slash commands. No production code modified.

1590/1590 tests passing (+ 11 skipped). 12 new tests.

### Phase 24a: Discord Bot Adapter (AD-274 through AD-278)

**Problem:** ProbOS had no external channel integrations — users could only interact via CLI shell or HXI web UI. Phase 24 calls for channel adapters to bridge external messaging platforms.

| AD | Decision |
|----|----------|
| AD-274 | `ChannelAdapter` ABC + `ChannelMessage` dataclass + shared `extract_response_text()` in `src/probos/channels/`. Reusable base for Discord, Slack, email, Teams |
| AD-275 | `probos serve --discord` flag wires `DiscordAdapter` lifecycle into `_serve()`. Startup after app creation, shutdown before runtime.stop(). Token resolved from `PROBOS_DISCORD_TOKEN` env var or config |
| AD-276 | `discord.py>=2.0` added as optional dependency in pyproject.toml. Commented channel config section added to system.yaml |
| AD-277 | 14 tests in `test_channel_base.py`: response formatter (8), ChannelMessage (2), handle_message routing + history (4) |
| AD-278 | 8 tests in `test_discord_adapter.py`: message chunking (4), adapter init (2), config parsing (2) |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/channels/__init__.py` | Package init, re-exports |
| `src/probos/channels/base.py` | ChannelAdapter ABC, ChannelMessage, per-channel conversation history |
| `src/probos/channels/response_formatter.py` | Shared `extract_response_text()` extracted from api.py |
| `src/probos/channels/discord_adapter.py` | Full Discord bot: message routing, mention filtering, channel filtering, chunked replies |
| `src/probos/config.py` | DiscordConfig + ChannelsConfig models |
| `src/probos/api.py` | Refactored to use shared response formatter |
| `src/probos/__main__.py` | `--discord` flag, adapter lifecycle in _serve() |
| `pyproject.toml` | Optional `[discord]` dependency group |
| `config/system.yaml` | Commented channels config section |

1612/1612 tests passing (+ 11 skipped). 22 new tests.

### Phase 24b: Self-Assessment Bug Fixes (AD-279, AD-280)

**Problem:** ProbOS demonstrated functional self-awareness by diagnosing its own gaps via Discord conversation. Investigation of its self-assessment revealed two bugs causing partially inaccurate self-reporting.

| AD | Decision |
|----|----------|
| AD-279 | Fix key name mismatch in `_introspect_memory()`: reads `total_episodes` but `get_stats()` returns `total`. Same mismatch for `unique_intents` and `success_rate`. ProbOS always reports 0 episodes even when episodes are stored correctly |
| AD-280 | Add `TrustNetwork.reconcile(active_agent_ids)` called after warm boot. Removes stale trust entries from previous sessions. Fixes 72-vs-43 agent count discrepancy in self-assessment. `TrustNetwork.remove()` was dead code — never called anywhere |

**Status:** Complete — both bugs identified by ProbOS's own self-assessment via Discord. 9 new tests (4 introspect memory + 5 trust reconcile). Also fixed pre-existing bug where `_restore_from_knowledge()` used `create_with_prior()` (no-op if record exists) instead of force-setting alpha/beta on warm boot restore.

### Phase 24c: Lightweight Task Scheduler (AD-281 through AD-284)

**Problem:** ProbOS identified its own lack of background scheduling as an architectural gap during a Discord self-assessment conversation ("I don't have a background timer"). The existing `SchedulerAgent` stores reminders to file but cannot execute them on a timer.

| AD | Decision |
|----|----------|
| AD-281 | `TaskScheduler` engine in `cognitive/task_scheduler.py`: background asyncio loop (1s tick), `ScheduledTask` dataclass, one-shot and recurring tasks, session-scoped (does not survive restart) |
| AD-282 | Wire `TaskScheduler` into `ProbOSRuntime` lifecycle (start/stop), expose as property |
| AD-283 | Upgrade `SchedulerAgent`: remove "no background timer" disclaimer, `act()` calls `task_scheduler.schedule/cancel/list`, reminders.json reload on boot |
| AD-284 | Channel delivery for scheduled tasks: results sent to Discord/Slack channel when `channel_id` is set on the task |

**Scope boundary:** In-session scheduling only. Persistent tasks with checkpointing and resume-after-restart remain in Phase 25.

**Status:** Complete — 17 tests, 1705/1705 passing

---

### AD-293: Crew Team Introspection

**Problem:** Asking "tell me about the medical team" failed — `agent_info` searches by `agent_type` and no agent has type `"medical"`. Pool groups (AD-291) were invisible to the intent system.

| AD | Decision |
|----|----------|
| AD-293 | Add `team_info` intent to IntrospectionAgent. Lists all crew teams (no param) or returns detailed health/roster/pools for a specific team. Fuzzy substring matching on team names. Defense-in-depth: `agent_info` now falls back to pool name search when agent_type match fails |

| File | Change |
|------|--------|
| `src/probos/agents/introspect.py` | Added `team_info` IntentDescriptor, routing, `_team_info()` method (list all / specific with fuzzy match), pool name fallback in `_agent_info()` |
| `tests/test_team_introspection.py` | 6 tests: specific team, all teams, unknown team, fuzzy match, pool name fallback, core team |

**Status:** Complete — 6 tests, 1711/1711 passing

### AD-294: HXI Crew Team Sub-Clusters

**Problem:** Agents on the HXI canvas were on a flat Fibonacci sphere, sorted by group for adjacency but with no visual boundary. Users couldn't distinguish teams without hovering.

| AD | Decision |
|----|----------|
| AD-294 | Replace flat Fibonacci sphere layout with gravitational sub-clusters. Each pool group gets its own center on a spacing sphere (radius 6.0), agents orbit within on mini Fibonacci spheres. Cluster radius scales: `0.8 + √n × 0.4`. Faint wireframe boundary shell + BackSide solid glow + floating text label per team. `GROUP_TINT_HEXES` color map. Falls back to flat layout when no pool group data available |

| File | Change |
|------|--------|
| `ui/src/store/useStore.ts` | `GroupCenter` interface, `GROUP_TINT_HEXES`, group-aware `computeLayout()`, `groupCenters` in state |
| `ui/src/canvas/clusters.tsx` | New — `TeamClusters` component with wireframe shells and text labels |
| `ui/src/components/CognitiveCanvas.tsx` | Added `<TeamClusters />` to scene |
| `ui/src/__tests__/useStore.test.ts` | 5 tests: cluster grouping, groupCenters metadata, ungrouped agents, heartbeat center, state_snapshot |

**Status:** Complete — 5 Vitest tests, 20/20 Vitest passing

### AD-295: Causal Attribution for Emergent Behavior + Self-Introspection

**Problem:** ProbOS detects emergent patterns but cannot explain *why* they're happening. No causal trail for trust changes — `record_outcome()` updated alpha/beta without recording which intent, Shapley values, or verifier caused the change. Episodes lacked Shapley attribution. IntrospectionAgent couldn't examine ProbOS's own source code.

| AD | Decision |
|----|----------|
| AD-295a | `TrustEvent` dataclass + ring buffer (`deque(maxlen=500)`) in TrustNetwork. `record_outcome()` gains optional `intent_type`, `episode_id`, `verifier_id` kwargs. Old/new scores captured per event. Query methods: `get_recent_events()`, `get_events_for_agent()`, `get_events_since()` |
| AD-295b | `Episode` gains `shapley_values: dict[str, float]` and `trust_deltas: list[dict]`. `_build_episode()` captures from `_last_shapley_values` and `trust_network.get_events_since(t_start)`. ChromaDB serialization updated with `shapley_values_json` and `trust_deltas_json` |
| AD-295c | `detect_trust_anomalies()` adds `causal_events` list (last 5 trust events per anomalous agent) to `EmergentPattern.evidence`. `detect_routing_shifts()` adds `agent_trust` and `hebbian_weight` context to routing shift evidence |
| AD-295d | `introspect_design` intent on IntrospectionAgent. Uses `rt.codebase_index.query()` + `get_agent_map()` + `get_layer_map()` to answer architecture questions. Graceful fallback when CodebaseIndex unavailable |

| File | Change |
|------|--------|
| `src/probos/consensus/trust.py` | `TrustEvent` dataclass, `_event_log` deque, enriched `record_outcome()`, 3 query methods |
| `src/probos/types.py` | `Episode.shapley_values`, `Episode.trust_deltas` fields |
| `src/probos/runtime.py` | Causal context in verification `record_outcome()`, `_build_episode()` captures Shapley + trust deltas |
| `src/probos/cognitive/episodic.py` | Serialize/deserialize new Episode fields in ChromaDB metadata |
| `src/probos/cognitive/emergent_detector.py` | `causal_events` in trust anomaly evidence, trust/Hebbian context in routing shifts |
| `src/probos/agents/introspect.py` | `introspect_design` intent + `_introspect_design()` method |
| `tests/test_trust_events.py` | 6 tests |
| `tests/test_episode_attribution.py` | 4 tests |
| `tests/test_causal_attribution.py` | 3 tests |
| `tests/test_introspect_design.py` | 3 tests |

**Status:** Complete — 16 new tests

### AD-296: HXI Cluster Label Billboarding + Security Pool Group

**Problem:** Team name labels rotated with the 3D scene, becoming unreadable. Red team agents had no pool group, floating in "_ungrouped" cluster.

| AD | Decision |
|----|----------|
| AD-296 | Wrap team name `<Text>` in `<Billboard follow>` from `@react-three/drei` so labels always face the camera. Add `security` PoolGroup for `red_team` pool (not excluded from scaler). Add `security: '#c85068'` to `GROUP_TINT_HEXES`. 5 crew teams: Core, Bundled, Medical, Self-Mod, Security |

**Status:** Complete — 1 new Vitest test, 21 Vitest total

### AD-297: CodebaseIndex as Ship's Library

| AD | Decision |
|----|----------|
| AD-297 | Decouple CodebaseIndex from `config.medical.enabled` — build unconditionally at startup so all agents (including IntrospectionAgent) can access source knowledge. Enhance `_introspect_design()` to call `read_source()` on top 3 matching files (first 80 lines each) so ProbOS can analyze its own source code, not just metadata |

**Status:** Complete — 4 new Python tests, 1731 Python total

### AD-298: Word-Level Query Matching in CodebaseIndex

| AD | Decision |
|----|----------|
| AD-298 | Replace exact-substring matching in `CodebaseIndex.query()` with word-level keyword scoring. Split concept into keywords, filter stop words (`_STOP_WORDS` frozenset), score each keyword independently against file paths (+3), docstrings (+2), and class names (+2). Additive scoring ranks multi-keyword matches higher. Fallback to full string if all words are stop words |

**Status:** Complete — 4 new Python tests, 1735 Python total

### AD-299: Project Docs in CodebaseIndex

| AD | Decision |
|----|----------|
| AD-299 | Index whitelisted project Markdown files (`DECISIONS.md`, `PROGRESS.md`, roadmap, progress-era-* files) alongside Python source code. Store with `docs:` prefix in `_file_tree`. Parse `# title` as docstring and `## section` headings as searchable "classes". `read_source()` handles `docs:` paths against `_project_root` with path traversal protection. No changes to `_introspect_design()` — docs flow through existing `query()` → `read_source()` pipeline |

**Status:** Complete — 5 new Python tests, 1740 Python total

### AD-300: Section-Targeted Doc Reading in CodebaseIndex

| AD | Decision |
|----|----------|
| AD-300 | Store section line numbers in `_analyze_doc()` alongside section names. New `read_doc_sections(file_path, keywords, max_lines=200)` scores sections by keyword overlap and reads only matching sections. `_introspect_design()` uses section-targeted reading for `docs:` files instead of fixed 80-line read. Imports `_STOP_WORDS` to extract keywords from the question for section matching |

**Status:** Complete — 6 new Python tests, 1746 Python total

### AD-302: BuilderAgent — Code Generation via LLM

| AD | Decision |
|----|----------|
| AD-302 | BuilderAgent — CognitiveAgent (domain/Engineering) that generates code from BuildSpec via deep LLM tier. Parses file blocks from LLM output, returns for Captain approval. Registered as `builder` in `engineering` pool group with consensus required |
| AD-303 | Git integration — async git helpers (branch, commit, checkout) via asyncio.create_subprocess_exec. `execute_approved_build()` pipeline: branch → write → test → commit. ProbOS Builder as git co-author |

**Status:** Complete — 29 new Python tests, 1775 Python total

---

## Phase 32b: Builder API + HXI (AD-304–305)

*"Engineering to Bridge — the blueprints are ready for your review, Captain."*

| AD | Decision |
|----|----------|
| AD-304 | Builder API — `POST /api/build/submit` triggers BuilderAgent via intent bus, `/api/build/approve` executes `execute_approved_build()`. `/build` slash command parses `title: description` format. WebSocket events: build_started, build_progress, build_generated, build_success, build_failure. Fire-and-forget async pattern matching selfmod |
| AD-305 | Builder HXI — BuildProposal type, Zustand build_* event handlers, IntentSurface inline approval UI with file summary, code review toggle, Approve/Reject buttons. Transient buildProposal on ChatMessage (not persisted to localStorage) |

**Status:** Complete — 15 new Python tests, 1790 Python + 21 Vitest total

---

## Phase 32c: Architect Agent (AD-306–307)

*"The First Officer surveys the star charts, identifies the next heading, and drafts the orders."*

| AD | Decision |
|----|----------|
| AD-306 | ArchitectAgent — Science-team CognitiveAgent (deep tier) that analyzes roadmap and codebase to produce structured ArchitectProposal containing a BuildSpec. Parses ===PROPOSAL=== blocks from LLM output. `perceive()` gathers codebase context via CodebaseIndex (files, agents, layers, roadmap sections, DECISIONS tail). `requires_consensus=False`, `requires_reflect=True` |
| AD-307 | Runtime integration — architect template registered, `architect` pool (target_size=1), `science` PoolGroup, codebase_skill attached independently of medical config, HXI teal color `#50a0b0` |

**Status:** Complete — 25 new Python tests, 1815 Python + 21 Vitest total

---

## Phase 32d: Architect API + HXI (AD-308–309)

*"The First Officer presents the schematics; the Captain decides whether to build."*

| AD | Decision |
|----|----------|
| AD-308 | Architect API — `POST /api/design/submit`, `POST /api/design/approve`, `/design` slash command (supports `/design <feature>` and `/design phase N: <feature>`), `_run_design` background pipeline, `design_*` WebSocket events (design_started, design_progress, design_generated, design_failure). `_pending_designs` in-memory store. Approval forwards embedded BuildSpec to existing `_run_build` pipeline |
| AD-309 | Architect HXI — `ArchitectProposalView` TypeScript type, Zustand `design_*` event handlers with `designProgress` state, IntentSurface inline proposal review UI (teal theme `#50a0b0`) with summary/rationale/roadmap/priority/target-files/risks/dependencies card, collapsible full spec, Approve & Build / Reject buttons |

**Status:** Complete — 14 new Python tests, 1826 Python + 21 Vitest total

---

## Phase 32e: Architect Agent Quality (AD-310)

*"An officer who makes decisions without reading the ship's logs is no officer at all."*

| AD | Decision |
|----|----------|
| AD-310 | ArchitectAgent perceive() upgraded with 7 context layers (file tree with actual paths, source snippets of top-5 matches, slash commands from shell.py + inline API commands, API route extraction from @app decorators, pool group crew structure, documentation with 80-line DECISIONS tail, sample build prompt for format calibration). Instructions hardened with 5 verification rules preventing path hallucination, duplicate slash commands, duplicate API routes, duplicate agents, and ungrounded proposals |

**Status:** Complete — 12 new Python tests, 1838 Python + 21 Vitest total

## Phase 32f: Architect Deep Localize + CodebaseIndex Structured Tools (AD-311/312)

| AD | Decision |
|----|----------|
| AD-311 | ArchitectAgent Layer 2 replaced with 3-step localize pipeline: (2a) fast-tier LLM selects up to 8 most relevant files from 20 candidates, (2b) full source read of selected files with 4000-line budget and 500-line per-file cap, (2c) test file discovery via `find_tests_for()`, caller analysis via `find_callers()`, and verified API surface via `get_full_api_surface()`. Instructions hardened with rule #6 requiring API method verification against the API Surface section. |
| AD-312 | CodebaseIndex gains three structured query methods: `find_callers(method_name)` with caching for cross-file reference search, `find_tests_for(file_path)` using naming conventions, `get_full_api_surface()` exposing the complete `_api_surface` dict. `_KEY_CLASSES` expanded with CodebaseIndex, PoolGroupRegistry, Shell. |

**Status:** Complete — 22 new Python tests (15 architect + 7 codebase_index), 1860 Python + 21 Vitest total

## Phase 32g: CodebaseIndex Import Graph + Architect Pattern Discovery (AD-315)

| AD | Decision |
|----|----------|
| AD-315 | CodebaseIndex builds forward and reverse import graphs at startup using AST-extracted `import`/`from X import Y` statements (probos-internal only). New methods: `get_imports(file_path)` returns internal files imported by a file, `find_importers(file_path)` returns files that import a given file. ArchitectAgent Layer 2a+ traces imports of LLM-selected files and expands `selected_paths` up to 12 total. Layer 2c appends "Import Graph" section showing import/imported-by relationships. Instructions updated with import-awareness in context listing and DESIGN PROCESS step 3. |

**Status:** Complete — 11 new Python tests (3 architect + 8 codebase_index), 1871 Python + 21 Vitest total

## Phase 32h: Builder File Edit Support (AD-313)

| AD | Decision |
|----|----------|
| AD-313 | Builder MODIFY mode — search-and-replace (`===SEARCH===`/`===REPLACE===`/`===END REPLACE===`) execution for existing files. `_parse_file_blocks()` parses SEARCH/REPLACE pairs within MODIFY blocks. `execute_approved_build()` applies replacements sequentially (first occurrence only). `perceive()` reads `target_files` so the LLM sees current content for accurate SEARCH blocks. `_validate_python()` runs `ast.parse()` on .py files after write/modify. Old `===AFTER LINE:===` format deprecated with warning |

**Status:** Complete — 20 new Python tests, 1891 Python + 21 Vitest total

## Phase 32i: Ship's Computer Identity (AD-317)

| AD | Decision |
|----|----------|
| AD-317 | Ship's Computer Identity — The Decomposer's system prompt now carries a LCARS-era Ship's Computer identity: calm, precise, never fabricates. PROMPT_PREAMBLE in prompt_builder.py includes 6 grounding rules. Dynamic System Configuration section counts intents by tier. Hardcoded example responses no longer claim unregistered capabilities. runtime.py builds a lightweight runtime_summary (pool count, agent count, departments, intent count) injected into the decompose() user prompt as SYSTEM CONTEXT. Legacy prompt path unchanged. |

**Status:** Complete — 8 new Python tests, 1899 Python + 21 Vitest total

## Self-Knowledge Grounding Progression (AD-318, AD-319, AD-320)

The Ship's Computer Identity (AD-317) established Level 1: prompt-level grounding rules that prevent the worst confabulation. The following three ADs complete the progression from rules → data → verification → delegation, closing the gap between ProbOS's self-knowledge and the scaffolding quality of tools like Claude Code (which verify claims by reading files before responding).

| AD | Decision |
|----|----------|
| AD-318 | **SystemSelfModel** — A lightweight, always-current in-memory object maintained by runtime.py that holds verified facts: pool count, agent roster (name + type + tier), registered intents, recent errors (last 10), uptime, last capability gap event, department summary. Updated reactively on every pool/agent add/remove/change. Injected automatically into the Decomposer's working memory (WorkingMemorySnapshot) so the LLM never starts cold. Analogous to Claude Code's MEMORY.md but for live runtime state. Replaces the ad-hoc `runtime_summary` dict from AD-317 with a structured, typed dataclass. **Design note:** AD-317's `_build_runtime_summary()` in runtime.py (line ~1252) currently reaches into `self.decomposer._intent_descriptors` to count intents — a runtime → decomposer internal coupling. AD-318 should own intent counts directly (updated when agents register/deregister), so the Decomposer reads from SystemSelfModel instead of the reverse. The existing `_build_runtime_summary()` method and the `runtime_summary` parameter on `decompose()` should be replaced by SystemSelfModel injection. |
| AD-319 | **Pre-Response Verification** — Before the Decomposer returns a natural language response to the human, a fast validation pass checks the response text against the SystemSelfModel: (1) regex scan for capability claims not in the registered intent table, (2) agent name references not in the agent roster, (3) feature descriptions that reference unbuilt systems. For simple responses, this is a pure-Python string check against the SystemSelfModel (zero LLM cost). For complex reflective responses, optionally invoke a fast-tier LLM call with the response + SystemSelfModel to flag contradictions. Failed checks trigger rewording or an honest uncertainty qualifier. This is the "read before you speak" pattern — the Decomposer verifies its own output before the Captain sees it. |
| AD-320 | **Introspection Delegation** — For "how do I work?" and self-knowledge questions, the Decomposer routes to IntrospectionAgent first instead of answering directly. IntrospectionAgent queries SystemSelfModel + CodebaseIndex + episodic memory, assembles grounded facts, and returns a structured response. The Decomposer then synthesizes the final natural language answer from verified data rather than generating it from LLM training knowledge. Detection heuristic: intent classification tags self-referential queries ("what agents do you have", "how does trust work", "what can you do") as `introspect_self` intent type. The Decomposer becomes a dispatcher for self-knowledge, not the answerer. |

**Progression:** AD-317 (rules) → AD-318 (data) → AD-319 (verification) → AD-320 (delegation). Each level makes ProbOS's self-knowledge more reliable — not because the LLM gets smarter, but because the scaffolding gets richer.

**Status:** Planned

## Phase 32j: Builder Test-Fix Loop (AD-314)

| AD | Decision |
|----|----------|
| AD-314 | Builder Test-Fix Loop — `execute_approved_build()` now runs pytest in a retry loop: initial pass + up to `max_fix_attempts` (default 2) LLM-driven fix iterations. `_run_tests()` async helper extracted. `_build_fix_prompt()` feeds truncated (3000-char) test failure output back to the LLM with a minimal fix-only prompt. Fix responses parsed with existing `_parse_file_blocks()` and applied with existing MODIFY/CREATE logic. `fix_attempts` count added to `BuildResult`. Two flaky network tests fixed: `test_unreachable_returns_false` and `test_all_tiers_unreachable_falls_back_to_mock` now use mocked connections instead of real network calls. |

**Status:** Complete — 7 new Python tests (builder) + 2 fixed (network), 1906 Python + 21 Vitest total

## Phase 32k: Escalation Tier 3 Timeout (AD-325)

| AD | Decision |
|----|----------|
| AD-325 | Escalation Tier 3 Timeout — `_tier3_user()` now wraps the `user_callback` in `asyncio.wait_for()` with a configurable `user_timeout` (default 120s). On timeout, returns `EscalationResult(resolved=False, user_approved=None)` with descriptive reason. User-wait seconds still accumulated on timeout for accurate DAG deadline accounting. Prevents hung escalation cascades when user callback never returns. |

**Status:** Complete — 5 new Python tests, 1911 Python + 21 Vitest total

## Phase 32l: API Task Lifecycle & WebSocket Hardening (AD-326)

| AD | Decision |
|----|----------|
| AD-326 | API Task Lifecycle & WebSocket Hardening — `_background_tasks` set tracks all `asyncio.create_task()` pipelines with automatic done-callback cleanup. `_track_task()` helper replaces 7 bare `create_task()` calls (build, design, self-mod, execute pipelines). `_broadcast_event()` inner `_safe_send()` coroutine catches per-client `send_json()` failures and prunes dead WebSocket clients. `GET /api/tasks` endpoint for Captain visibility into active pipelines. FastAPI lifespan handler drains/cancels all tasks on shutdown. |

**Status:** Complete — 5 new Python tests, 1916 Python + 21 Vitest total

## Phase 32m: CodeValidator Hardening (AD-327)

| AD | Decision |
|----|----------|
| AD-327 | CodeValidator Hardening — (a) `_check_schema()` now rejects code with multiple `BaseAgent` subclasses (was silently picking first). (b) New `_check_class_body_side_effects()` scans class bodies for bare function calls, loops, and conditionals that execute at import time. Both are early-return patterns consistent with existing validator flow. |

**Status:** Complete — 4 new Python tests, 1920 Python + 21 Vitest total

## Phase 32n: Self-Mod Durability & Bloom Fix (AD-328)

| AD | Decision |
|----|----------|
| AD-328 | Self-Mod Durability & Bloom Fix — (a) Knowledge store and semantic layer post-deployment failures now logged with `logger.warning(exc_info=True)` instead of bare `except: pass`. Partial failure warnings propagated in `self_mod_success` WebSocket event and displayed to Captain. (b) `self_mod_success` event now includes `agent_id`. `pendingSelfModBloom` stores `agent_id` (falling back to `agent_type`). Bloom animation lookup uses `a.id || a.agentType` for accurate targeting when multiple agents share a type. |

**Status:** Complete — 3 new Python tests, 1 new Vitest, 1923 Python + 22 Vitest total

## Phase 32o: HXI Canvas Resilience & Component Tests (AD-329)

| AD | Decision |
|----|----------|
| AD-329 | HXI Canvas Resilience & Component Tests — (a) `connections.tsx` agents subscription replaced with ref + count-based re-render. Pool centers cached in `useMemo` keyed on agent count, eliminating O(agents×connections) per-state-change recomputation. (b) Unnecessary Zustand action subscriptions removed from `CognitiveCanvas.tsx` and `AgentTooltip.tsx` — stable action refs read via `getState()` instead. (c) Component-level Vitest tests for pool center computation, connection filtering, tooltip state, and animation event clearing. |

**Status:** Complete — 8 new Vitest tests, 1923 Python + 30 Vitest total

## Phase 32p: Architect Proposal Validation + Pattern Recipes (AD-316a)

| AD | Decision |
|----|----------|
| AD-316a | Architect Proposal Validation + Pattern Recipes — (a) New `_validate_proposal()` method with 6 programmatic checks: required field presence, non-empty test_files, target/reference file path verification against codebase_index file tree (with directory-prefix fallback for new files), priority value validation, and description minimum length (100 chars). Warnings are advisory (non-blocking) — `act()` returns `success: True` with optional `warnings` list. (b) Pattern Recipes section appended to instructions string with 3 reusable templates: NEW AGENT, NEW SLASH COMMAND, NEW API ENDPOINT — each with TARGET_FILES, REFERENCE_FILES, TEST_FILES, and CHECKLIST. |

**Status:** Complete — 14 new Python tests, 1937 Python + 30 Vitest total

## Phase 32q: SystemSelfModel (AD-318)

| AD | Decision |
|----|----------|
| AD-318 | SystemSelfModel — Structured runtime self-knowledge. (a) New `SystemSelfModel` dataclass in `src/probos/cognitive/self_model.py` with `PoolSnapshot` — compact snapshot of topology (pools, departments, intents), identity (version, mode), and health (uptime, recent errors, last capability gap). `to_context()` serializes to ~500 char text for LLM injection. (b) `_build_system_self_model()` on runtime replaces `_build_runtime_summary()` — builds model from live pool state, pool groups (departments), dream scheduler (mode), decomposer (intent count). (c) `_record_error()` caps at 5 recent errors, wired into reflect and episode storage failure handlers. Capability gap tracking stores first 100 chars of unhandled requests. |

**Status:** Complete — 9 new Python tests (1 updated), 1946 Python + 30 Vitest total

## Phase 32r: Pre-Response Verification (AD-319)

| AD | Decision |
|----|----------|
| AD-319 | Pre-Response Verification — Fact-check responses against SystemSelfModel. (a) New `_verify_response()` method on runtime — zero-LLM, regex-based string matching with 5 checks: pool count claims, agent count claims, fabricated department names (context-aware pattern matching), fabricated pool names (with generic word exclusion set), system mode contradictions. Non-blocking: appends correction footnote on violations, never suppresses responses. (b) Wired into two response paths: no-nodes path (dag.response) and reflection path (_execute_dag). `_execute_dag` signature extended with optional `self_model` parameter. Timeout/error fallback strings not verified (canned text, not LLM output). |

**Status:** Complete — 14 new Python tests, 1960 Python + 30 Vitest total

## Phase 32s: Introspection Delegation (AD-320)

| AD | Decision |
|----|----------|
| AD-320 | Introspection Delegation — Grounded self-knowledge answers. Level 4 of self-knowledge progression: rules (AD-317) → data (AD-318) → verification (AD-319) → **delegation** (AD-320). (a) New `_grounded_context()` method on IntrospectionAgent builds detailed text from `SystemSelfModel` — per-pool breakdowns grouped by department, full intent listing, health signals. (b) Enriched 4 intent handlers (`_agent_info()`, `_system_health()`, `_team_info()`, `_introspect_system()`) to include `grounded_context` key in output dicts for reflector consumption. (c) REFLECT_PROMPT rule 7: treat `grounded_context` as VERIFIED SYSTEM FACTS. (d) `_summarize_node_result()` preserves grounded_context outside truncation boundary, labeled as GROUNDED SYSTEM FACTS. |

**Status:** Complete — 12 new Python tests, 1972 Python + 30 Vitest total
