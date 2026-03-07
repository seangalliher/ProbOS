# ProbOS — Progress Tracker

## Current Status: Phase 2 — Consensus Layer Complete (Milestone Achieved)

---

## What's Been Built

### Substrate Layer (complete)

| File | Status | Description |
|------|--------|-------------|
| `pyproject.toml` | done | Project config, deps (pydantic, pyyaml, aiosqlite, rich, pytest) |
| `config/system.yaml` | done | Pool sizes, mesh params, heartbeat intervals, consensus config |
| `src/probos/__init__.py` | done | Package root, version 0.1.0 |
| `src/probos/types.py` | done | `AgentState`, `AgentMeta`, `CapabilityDescriptor`, `IntentMessage`, `IntentResult`, `GossipEntry`, `ConnectionWeight`, `ConsensusOutcome`, `Vote`, `QuorumPolicy`, `ConsensusResult`, `VerificationResult` |
| `src/probos/config.py` | done | `PoolConfig`, `MeshConfig`, `ConsensusConfig`, `SystemConfig`, `load_config()` — pydantic models loaded from YAML |
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
| `src/probos/runtime.py` | done | `ProbOSRuntime` — orchestrates substrate + mesh + consensus, creates pools, spawns red team agents, `submit_intent()`, `submit_intent_with_consensus()`, `submit_write_with_consensus()` |
| `demo.py` | done | Full demo: consensus file read, corrupted agent injection, trust network display, agent-to-agent Hebbian weights, consensus-gated writes, event log |

---

## What's Working

**166/166 tests pass.** Test suite covers:

### Substrate tests (50 tests — unchanged)
- Agent creation, lifecycle, confidence tracking (16 tests)
- Config loading (3 tests)
- Registry: register, unregister, lookup (7 tests)
- Spawner: template registration, spawn, recycle (6 tests)
- Pool: target size, cleanup, recovery (4 tests)
- Heartbeat: pulse loop, listeners, confidence (7 tests)
- System heartbeat: metrics, type (2 tests)

### Mesh tests (38 tests — HebbianRouter evolved)
- SignalManager: track, untrack, TTL expiry, reaper loop (6 tests)
- IntentBus: broadcast, multi-subscriber, decline, error recording, unsubscribe (6 tests)
- CapabilityRegistry: exact/substring/keyword matching, scoring, multi-agent, unregister (8 tests)
- HebbianRouter: success/failure weights, clamping, preferred targets, decay pruning, SQLite persistence (8 tests — now with rel_type support)
- GossipProtocol: local update, receive/merge, batch, remove, active filter, random sample, loop (9 tests)
- EventLog: log/query, count by category, append-only persistence, noop without start (4 tests)
- FileReaderAgent: read, stat, missing file, decline unknown, missing path, confidence updates (8 tests)

### Consensus tests (46 tests — new)
- QuorumEngine: unanimous approval/rejection, insufficient votes, mixed votes, confidence weighting, unweighted mode, 2-of-3, 3-of-5, evaluate_values majority, insufficient values (12 tests)
- TrustNetwork: create, idempotent, success/failure scoring, repeated outcomes, weighted outcome, decay toward prior, remove, all_scores, summary, SQLite persistence, unknown agent prior (14 tests)
- RedTeamAgent: type, capabilities, verify correct read, verify corrupted read, missing file correct failure, missing file false success, unknown intent, lifecycle noop (8 tests)
- FileWriterAgent: type, capabilities, propose write, no path, no content, decline unhandled, commit write, commit creates dirs (8 tests)

### Runtime integration tests (32 tests — expanded from 20)

#### Substrate (5 tests — unchanged)
- Start/stop, idempotent, heartbeat active, filesystem pool created, pool recovery

#### Mesh (8 tests — unchanged)
- Intent bus subscribers, capabilities registered, gossip view populated, submit_intent read file (3 agents return matching results), missing file errors, unknown intent empty, Hebbian weights recorded, status includes mesh

#### Event log (3 tests — unchanged)
- System events on start, lifecycle events for agent wiring, mesh events for intent broadcast/resolve

#### Consensus integration (12 tests — new)
- Red team agents spawned and active (2 tests)
- Trust network initialized with agent records (1 test)
- Status includes consensus section (1 test)
- Gossip includes red team agents (1 test)
- Submit with consensus: correct read approved, trust updated, agent-to-agent weights recorded, consensus events logged (4 tests)
- Corrupted agent caught: injected corrupted agent detected by red team, corrupted trust lower than honest (1 test)
- Majority corrupted: 3 corrupted + 3 honest, red team catches all corrupted (1 test)
- Write with consensus: approved and committed (1 test)

### Phase 2 Milestone — Achieved

The following scenario works end-to-end:

1. `ProbOSRuntime.start()` boots the system with 2 heartbeat agents + 3 file reader agents + 2 red team agents.
2. All 7 agents appear in the gossip view; all have trust records initialized.
3. `runtime.submit_intent_with_consensus("read_file", ...)` broadcasts an intent.
4. All 3 file_reader agents self-select and independently read the file.
5. `QuorumEngine.evaluate()` checks confidence-weighted voting (3/3 approve → APPROVED).
6. Red team agents independently re-read the file and verify each agent's result.
7. `TrustNetwork` records outcomes: verified agents get alpha increments, corrupted agents get beta increments.
8. `HebbianRouter` records agent-to-agent weights (verifier → verified agent) with `rel_type="agent"`.
9. When a `CorruptedFileReaderAgent` is injected, red team catches the content mismatch.
10. Corrupted agent's trust score drops to 0.33 while honest agents rise to 0.75.
11. Agent-to-agent Hebbian weights show 0.0 for corrupted target vs ~0.10 for honest targets.
12. `submit_write_with_consensus()` proposes writes, evaluates quorum, runs verification, and only commits on approval.
13. Event log records `consensus/quorum_evaluated`, `consensus/verification_complete`, `consensus/write_committed` events.
14. Clean shutdown persists Hebbian weights and trust scores to SQLite.

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
- [ ] **Phase 3 (Cognitive):** LLM integration, intent decomposition, episodic memory, attention mechanism
- [ ] **Phase 4 (Experience):** Rich terminal interface, ambient state, natural language interaction
- [ ] **Phase 5 (Expansion):** Network agents, process management, calendar, email, code execution

---

## Environment

- **Platform:** Windows 11 Pro (10.0.26200)
- **Python:** 3.12.13 (installed via uv)
- **Toolchain:** uv 0.10.9
- **Key deps:** pydantic 2.12.5, pyyaml 6.0.3, aiosqlite 0.22.1, pytest 9.0.2, pytest-asyncio 1.3.0
- **Run tests:** `uv run pytest tests/ -v`
- **Run demo:** `uv run python demo.py`
