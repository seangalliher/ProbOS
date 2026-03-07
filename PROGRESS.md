# ProbOS — Progress Tracker

## Current Status: Phase 4+ — LLM JSON Hardening Complete (277/277 tests)

---

## What's Been Built

### Substrate Layer (complete)

| File | Status | Description |
|------|--------|-------------|
| `pyproject.toml` | done | Project config, deps (pydantic, pyyaml, aiosqlite, rich, pytest) |
| `config/system.yaml` | done | Pool sizes, mesh params, heartbeat intervals, consensus config |
| `src/probos/__init__.py` | done | Package root, version 0.1.0 |
| `src/probos/types.py` | done | `AgentState`, `AgentMeta`, `CapabilityDescriptor`, `IntentMessage`, `IntentResult`, `GossipEntry`, `ConnectionWeight`, `ConsensusOutcome`, `Vote`, `QuorumPolicy`, `ConsensusResult`, `VerificationResult`, `LLMTier`, `LLMRequest`, `LLMResponse`, `TaskNode`, `TaskDAG` (with `response` field for conversational LLM replies) |
| `src/probos/config.py` | done | `PoolConfig`, `MeshConfig`, `ConsensusConfig`, `CognitiveConfig`, `SystemConfig`, `load_config()` — pydantic models loaded from YAML |
| `src/probos/substrate/agent.py` | done | `BaseAgent` ABC — `perceive/decide/act/report` lifecycle, confidence tracking, state transitions, async start/stop |
| `src/probos/substrate/registry.py` | done | `AgentRegistry` — in-memory index, lookup by ID/pool/capability, async-safe |
| `src/probos/substrate/spawner.py` | done | `AgentSpawner` — template registration, `spawn()`, `recycle()` with optional respawn |
| `src/probos/substrate/pool.py` | done | `ResourcePool` — maintains N agents at target size, background health loop, auto-recycles degraded agents |
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

### Cognitive Layer (complete — new in Phase 3a)

| File | Status | Description |
|------|--------|-------------|
| `src/probos/cognitive/__init__.py` | done | Package root |
| `src/probos/cognitive/llm_client.py` | done | `BaseLLMClient` ABC, `OpenAICompatibleClient` (httpx, tiered routing fast/standard/deep, response cache, fallback chain: live → cache → error, connectivity check, specific error handling for connect/timeout/HTTP errors), `MockLLMClient` (regex pattern matching, canned responses for deterministic testing) |
| `src/probos/cognitive/working_memory.py` | done | `WorkingMemorySnapshot` (serializable system state), `WorkingMemoryManager` (bounded context assembly from registry/trust/Hebbian/capabilities, token budget eviction) |
| `src/probos/cognitive/decomposer.py` | done | `IntentDecomposer` (NL text + working memory → LLM → `TaskDAG`, aggressive JSON-only system prompt with `response` field for conversational replies, markdown code fence extraction, available intents, examples), `DAGExecutor` (parallel/sequential DAG execution through mesh + consensus, dependency resolution, deadlock detection, `on_event` callback for real-time progress) |

### Experience Layer (complete — new in Phase 4)

| File | Status | Description |
|------|--------|-------------|
| `src/probos/experience/__init__.py` | done | Package root |
| `src/probos/experience/panels.py` | done | Rich rendering functions: `render_status_panel()`, `render_agent_table()`, `render_weight_table()`, `render_trust_panel()`, `render_gossip_panel()`, `render_event_log_table()`, `render_working_memory_panel()`, `render_dag_result()` (displays `response` field for conversational replies), `format_health()` — state-coloured agent displays (ACTIVE=green, DEGRADED=yellow, RECYCLING=red, SPAWNING=blue) |
| `src/probos/experience/renderer.py` | done | `ExecutionRenderer` — real-time DAG execution display with Rich spinners and Live updates, `on_event` callback integration, conversational response display when LLM returns `response` field, debug mode (raw DAG JSON, individual agent responses, consensus details) |
| `src/probos/experience/shell.py` | done | `ProbOSShell` — async REPL with slash commands (`/status`, `/agents`, `/weights`, `/gossip`, `/log`, `/memory`, `/model`, `/tier`, `/debug`, `/help`, `/quit`), NL input routing, ambient health prompt `[N agents | health: 0.XX] probos>`, graceful error handling |

### Agents

| File | Status | Description |
|------|--------|-------------|
| `src/probos/agents/file_reader.py` | done | `FileReaderAgent` — `read_file` and `stat_file` capabilities, full lifecycle, self-selects on intent match |
| `src/probos/agents/file_writer.py` | done | `FileWriterAgent` — `write_file` capability, proposes writes without committing, `commit_write()` called after consensus approval |
| `src/probos/agents/red_team.py` | done | `RedTeamAgent` — independently verifies other agents' results (re-reads files, compares), does NOT subscribe to intent bus |
| `src/probos/agents/corrupted.py` | done | `CorruptedFileReaderAgent` — deliberately returns fabricated data, used to test consensus layer catching corruption |

### Runtime

| File | Status | Description |
|------|--------|-------------|
| `src/probos/runtime.py` | done | `ProbOSRuntime` — orchestrates substrate + mesh + consensus + cognitive, spawns pools: system (2 heartbeats), filesystem (3 file_readers), filesystem_writers (3 file_writers), red_team (2 verifiers). `process_natural_language(text, on_event=None)` with event callback support |
| `src/probos/__main__.py` | done | Entry point: `uv run python -m probos` — boot sequence display, LLM connectivity check with fallback to MockLLMClient, interactive shell launch |
| `demo.py` | done | Full Rich demo: consensus reads, corrupted agent injection, trust/Hebbian display, NL pipeline with visual feedback, event log |

---

## What's Working

**277/277 tests pass.** Test suite covers:

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

### Cognitive tests (65 tests)

#### LLM Client (10 tests)
- MockLLMClient: single read, parallel reads, write with consensus, unmatched default, call count, last request, custom default, token estimate, tier passthrough
- OpenAICompatibleClient: fallback to error when no server + no cache

#### Working Memory (14 tests)
- WorkingMemorySnapshot: empty to_text, with agents, with capabilities, with trust, with connections, token estimate, token scales with content
- WorkingMemoryManager: record intent, record result removes from active, bounded intents, bounded results, assemble without sources, eviction under budget, assemble returns copy

#### Decomposer + TaskDAG (33 tests)
- IntentDecomposer: single read, parallel reads, write with consensus, source text preserved, with context, unrecognized input, malformed JSON, missing intents key, intents not a list, empty intent filtered
- ParseResponse: raw JSON, code block, preamble, invalid JSON, non-dict items skipped
- ExtractJson: raw JSON, code block, embedded JSON, no JSON raises
- TaskDAG: ready nodes all independent, ready nodes with dependency, ready after completion, is_complete, is_not_complete, get_node, empty DAG is complete, response field default empty, response field set
- ResponseFieldParsing: response field extracted, response with intents, response missing defaults empty, non-string response ignored, JSON in code fences with response

#### Cognitive integration (8 tests)
- NL single read, parallel reads, write with consensus, unrecognized returns empty, read missing file, working memory updated, status includes cognitive, multiple NL requests

### Experience tests (47 tests)

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

The `ExecutionRenderer` orchestrates the cognitive pipeline stages itself (working memory assembly, decompose, execute, record results) rather than calling `runtime.process_natural_language()`. This allows inserting different Rich display modes (spinner for decomposition, Live display for execution) between stages. The duplicated logic is minimal (~15 lines).

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
- [ ] **Phase 3b (Cognitive continued):** Episodic memory, attention mechanism, richer NL understanding
- [ ] **Phase 5 (Expansion):** Network agents, process management, calendar, email, code execution

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
