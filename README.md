# ProbOS

> **Alpha** — ProbOS is under active development. APIs will change, features may break, and documentation may lag behind the code. Contributions and feedback welcome.

**Probabilistic agent-native OS runtime** — an operating system kernel where every component is an autonomous agent, coordination happens through consensus, and the system learns from its own behavior.

> *"What if an OS didn't execute instructions — it negotiated them?"*

## What Is This?

ProbOS reimagines the OS as a mesh of probabilistic agents rather than deterministic processes. Instead of syscalls, you speak natural language. Instead of a scheduler, agents self-organize through Hebbian learning and trust networks. Instead of permissions, destructive operations require multi-agent consensus.

```
[47 agents | health: 0.95] probos> read pyproject.toml and tell me about this project

  ✓ t1: read_file

  This project is ProbOS v0.1.0, a probabilistic agent-native OS runtime...
```

## Design Philosophy

Traditional operating systems use rigid, deterministic mechanisms: syscalls, schedulers, ACLs. ProbOS replaces each with a probabilistic, self-organizing equivalent:

| Traditional OS | ProbOS Equivalent |
|---------------|-------------------|
| Syscalls | Natural language decomposed into intent DAGs |
| Process scheduler | Attention-based priority scoring with Hebbian learning |
| File permissions / ACLs | Multi-agent consensus voting with red team verification |
| Process table | Agent registry with health monitoring and auto-recycling |
| IPC | Pub/sub intent bus with concurrent fan-out |
| Cron / scheduled tasks | Dreaming engine — offline consolidation during idle periods |
| Command history | Episodic memory with semantic recall |
| Shell aliases | Workflow cache — learned shortcuts for repeated patterns |

Every agent maintains a confidence score and trust reputation. The system doesn't just execute operations — it *deliberates*, *verifies*, and *learns*.

## Architecture

Five layers plus two cross-cutting concerns, each built on the one below:

```
┌─────────────────────────────────────────────────────┐
│  Experience    CLI shell, HXI (WebGL canvas),       │
│                FastAPI + WebSocket, Rich panels     │
├─────────────────────────────────────────────────────┤
│  Cognitive     LLM decomposer, working memory,      │
│                episodic memory, attention, dreaming, │
│                self-modification, agent design,      │
│                workflow cache, dynamic prompts       │
├─────────────────────────────────────────────────────┤
│  Consensus     Quorum voting, trust network,         │
│                Shapley attribution, escalation       │
├─────────────────────────────────────────────────────┤
│  Mesh          Intent bus, Hebbian routing,           │
│                gossip protocol, capability registry  │
├─────────────────────────────────────────────────────┤
│  Substrate     Agent lifecycle, pools, spawner,       │
│                registry, heartbeat, event log        │
├─────────────────────────────────────────────────────┤
│  Federation    ZeroMQ transport, node bridge,         │
│                intent router, gossip exchange        │
├─────────────────────────────────────────────────────┤
│  Knowledge     Git-backed store, ChromaDB semantic,   │
│                warm boot, per-artifact rollback      │
└─────────────────────────────────────────────────────┘
```

### Substrate

Agents follow a `perceive → decide → act → report` lifecycle. A spawner creates them from templates, resource pools maintain target sizes with auto-recycling of degraded agents, and a heartbeat system monitors liveness. Everything is logged to an append-only SQLite event log.

### Mesh

Agents discover each other through a capability registry with fuzzy matching. An intent bus does concurrent fan-out to all subscribers. A Hebbian router learns which agents handle which intents best — successful pairings get stronger, failures get weaker. A SWIM-style gossip protocol exchanges state between agents.

### Consensus

Destructive operations (file writes, shell commands, HTTP fetches) require multi-agent agreement. A quorum engine collects confidence-weighted votes. A Bayesian trust network (Beta distribution) tracks agent reliability over time. Red team agents independently re-execute operations to verify results.

### Cognitive

Natural language goes through: working memory assembly → episodic recall → workflow cache lookup → LLM decomposition into a DAG of intents → attention-based priority scoring → parallel/sequential execution → optional reflection synthesis.

The decomposer's system prompt is **self-assembling** — each agent class declares `IntentDescriptor` metadata, and the prompt is built dynamically from whatever agents are registered. Adding a new agent type makes its intents available to the LLM without editing any prompt, configuration, or routing table.

### Experience

A Rich-powered interactive shell with 16 slash commands, real-time DAG execution display with spinners, and formatted result panels.

## Agents

ProbOS boots with 47 agents across 20+ pools (+ 2 red team verifiers):

### Core Agents (always active)

| Pool | Count | Capabilities | Consensus |
|------|-------|-------------|-----------|
| `system` | 2 | Heartbeat monitoring (CPU, load, PID) | No |
| `filesystem` | 3 | `read_file`, `stat_file` | No |
| `filesystem_writers` | 3 | `write_file` | Yes |
| `directory` | 3 | `list_directory` | No |
| `search` | 3 | `search_files` (recursive glob) | No |
| `shell` | 3 | `run_command` (30s timeout) | Yes |
| `http` | 3 | `http_fetch` (1MB cap, per-domain rate limiting) | Yes |
| `introspect` | 2 | `explain_last`, `agent_info`, `system_health`, `why` | No |
| `red_team` | 2 | Independent result verification | N/A |

### Bundled Cognitive Agents (10 pools, "useful on Day 1")

| Pool | Capabilities |
|------|-------------|
| `web_search` | Search the web via mesh-routed HTTP |
| `page_reader` | Extract and summarize web page content |
| `weather` | Weather lookups via public APIs |
| `news` | News search and summarization |
| `translator` | Language translation |
| `summarizer` | Text summarization |
| `calculator` | Mathematical calculations |
| `todo_manager` | Task list management |
| `note_taker` | Note creation and retrieval |
| `scheduler` | Scheduling and reminders |

### System Agents (conditional)

| Pool | Purpose | When active |
|------|---------|-------------|
| `skills` | Dynamic skill execution (SkillBasedAgent) | Self-mod enabled |
| `system_qa` | Smoke tests for designed agents | QA enabled |
| `designed_*` | Self-designed agents (CognitiveAgent subclasses) | Created at runtime |

A test agent (`CorruptedFileReaderAgent`) deliberately returns fabricated data to verify that the consensus layer detects and rejects it.

## Quick Start

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/)

```bash
# Clone and install
git clone https://github.com/seangalliher/ProbOS.git
cd ProbOS
uv sync

# Run tests (1590 Python + 15 Vitest = 1605 total)
uv run pytest tests/ -v

# Launch interactive shell
uv run python -m probos

# Run the visual demo
uv run python demo.py
```

### LLM Backend

ProbOS connects to an OpenAI-compatible LLM endpoint (configurable in `config/system.yaml`). Three options:

| Option | Setup |
|--------|-------|
| **No LLM (default)** | Works out of the box — falls back to a built-in `MockLLMClient` with regex pattern matching. Good for exploring the architecture and running tests. |
| **Ollama (local)** | Install [Ollama](https://ollama.com/), pull a model (`ollama pull qwen3.5:35b`), update `config/system.yaml` endpoints to `http://127.0.0.1:11434`. |
| **OpenAI-compatible API** | Point `llm_base_url` in `config/system.yaml` to any OpenAI-compatible endpoint and set your API key. |

## Interactive Shell

```
probos> read /tmp/test.txt                   # Natural language → intent DAG
probos> list the files in /home/user/docs    # Directory listing
probos> write hello to /tmp/out.txt          # Consensus-verified write
probos> search for *.py in /home/user        # Recursive file search
probos> what just happened?                  # Introspection
probos> why did you use file_reader?         # Self-explanation
probos> how healthy is the system?           # System health assessment

probos> /status                              # Pool health, mesh, cognitive state
probos> /agents                              # Agent table with states and trust
probos> /weights                             # Hebbian connection weights
probos> /memory                              # Working memory snapshot
probos> /attention                           # Task priority queue + focus history
probos> /dream now                           # Force a dream consolidation cycle
probos> /cache                               # Workflow cache contents
probos> /explain                             # Explain last execution
probos> /history                             # Recent episodic memory entries
probos> /recall <query>                      # Search episodic memory
probos> /model                               # LLM client info
probos> /tier fast|standard|deep             # Switch LLM tier
probos> /debug                               # Toggle debug mode
probos> /help                                # All commands
```

## How It Works

When you type natural language:

1. **Working memory** assembles system state (agent health, trust scores, Hebbian weights, capabilities) within a token budget
2. **Episodic recall** finds similar past interactions for context (top-3 by keyword-overlap cosine similarity)
3. **Workflow cache** checks for previously successful DAG patterns (exact match, then fuzzy with pre-warm intents)
4. **LLM decomposer** converts text into a `TaskDAG` — a directed acyclic graph of typed intents with dependencies
5. **Attention manager** scores tasks: `urgency × relevance × deadline_factor × dependency_bonus`
6. **DAG executor** runs independent intents in parallel, respects dependency ordering
7. **Consensus** gates destructive operations through multi-agent voting + red team verification
8. **Reflection** (optional) sends execution results back to the LLM for synthesis
9. **Hebbian router** strengthens successful agent-intent pairings, weakens failures
10. **Episodic memory** stores the interaction for future recall
11. **Workflow cache** stores successful patterns to bypass the LLM on repeat queries
12. **Dreaming engine** consolidates learning during idle periods — replays episodes, prunes weak connections, adjusts trust scores, pre-warms likely upcoming intents

## Configuration

All tuning lives in [`config/system.yaml`](config/system.yaml):

| Section | Controls |
|---------|----------|
| **pools** | Target sizes (2-7), spawn cooldown, health check intervals |
| **mesh** | Gossip rate, Hebbian decay/reward rates, signal TTL |
| **consensus** | Min votes, approval threshold, trust priors (Beta distribution), decay rate |
| **cognitive** | LLM endpoint, model tiers (fast/standard/deep), token budget, concurrency limit, attention parameters |
| **memory** | Max episodes, relevance threshold |
| **dreaming** | Idle threshold, replay count, strengthening/weakening factors, prune threshold |

## Project Structure

```
src/probos/
├── __init__.py              # Package root
├── __main__.py              # Entry point (probos CLI)
├── api.py                   # FastAPI server + WebSocket events
├── config.py                # Pydantic config models
├── runtime.py               # Top-level orchestrator (~2500 lines)
├── types.py                 # Core types (30+ dataclasses)
├── agents/                  # Tool agents (deterministic)
│   ├── file_reader.py       #   read_file, stat_file
│   ├── file_writer.py       #   write_file (consensus-gated)
│   ├── directory_list.py    #   list_directory
│   ├── file_search.py       #   search_files
│   ├── shell_command.py     #   run_command (consensus-gated)
│   ├── http_fetch.py        #   http_fetch (rate-limited, consensus-gated)
│   ├── introspect.py        #   explain_last, agent_info, system_health, why
│   ├── system_qa.py         #   Smoke tests for designed agents
│   ├── red_team.py          #   Independent verification
│   ├── corrupted.py         #   Test agent (deliberately wrong)
│   └── bundled/             #   10 CognitiveAgent types ("useful on Day 1")
│       ├── web_agents.py    #     WebSearch, PageReader, Weather, News
│       ├── language_agents.py #   Translator, Summarizer
│       ├── productivity_agents.py # Calculator, Todo, NoteTaker
│       └── organizer_agents.py #  Scheduler
├── cognitive/               # LLM pipeline + self-modification
│   ├── decomposer.py        #   NL → TaskDAG + DAG executor
│   ├── prompt_builder.py    #   Dynamic system prompt assembly
│   ├── llm_client.py        #   OpenAI-compatible + mock client
│   ├── cognitive_agent.py   #   Instructions-first LLM agent base
│   ├── working_memory.py    #   Bounded context assembly
│   ├── episodic.py          #   ChromaDB semantic long-term memory
│   ├── attention.py         #   Priority scoring + focus tracking
│   ├── dreaming.py          #   Offline consolidation + pre-warm
│   ├── workflow_cache.py    #   LRU pattern cache
│   ├── agent_designer.py    #   LLM designs new agents from capability gaps
│   ├── self_mod.py          #   Self-modification pipeline orchestrator
│   ├── code_validator.py    #   Static analysis for generated code
│   ├── sandbox.py           #   Isolated execution for untrusted agents
│   ├── skill_designer.py    #   Skill template generation
│   ├── skill_validator.py   #   Skill safety validation
│   ├── behavioral_monitor.py #  Runtime behavior tracking post-deploy
│   ├── feedback.py          #   Human feedback → trust/Hebbian/episodic
│   ├── correction_detector.py # Distinguishes corrections from new requests
│   ├── agent_patcher.py     #   Hot-patches designed agent code
│   ├── strategy.py          #   StrategyRecommender (skill attachment)
│   ├── dependency_resolver.py # Auto-install agent dependencies (uv)
│   ├── emergent_detector.py #   5 algorithms for emergent behavior
│   ├── embeddings.py        #   Embedding utilities
│   └── research.py          #   Web research phase for agent design
├── consensus/               # Multi-agent agreement
│   ├── quorum.py            #   Confidence-weighted voting
│   ├── trust.py             #   Bayesian Beta(α,β) reputation
│   ├── shapley.py           #   Shapley value attribution
│   └── escalation.py        #   3-tier failure cascade
├── experience/              # User interface
│   ├── shell.py             #   Async REPL (20+ commands)
│   ├── renderer.py          #   Real-time DAG execution display
│   ├── panels.py            #   Rich panel/table rendering
│   ├── knowledge_panel.py   #   Knowledge store panels
│   └── qa_panel.py          #   QA result panels
├── federation/              # Multi-node mesh
│   ├── bridge.py            #   ZeroMQ node bridge
│   ├── router.py            #   Intent forwarding + loop prevention
│   └── transport.py         #   Transport abstraction
├── knowledge/               # Persistent storage
│   ├── store.py             #   Git-backed artifact persistence
│   └── semantic.py          #   SemanticKnowledgeLayer (5 ChromaDB collections)
├── mesh/                    # Agent coordination
│   ├── intent.py            #   Pub/sub bus with fan-out
│   ├── routing.py           #   Hebbian learning (SQLite)
│   ├── capability.py        #   Fuzzy matching registry
│   ├── gossip.py            #   SWIM-style state exchange
│   └── signal.py            #   TTL-enforced signals
└── substrate/               # Agent lifecycle
    ├── agent.py             #   BaseAgent ABC (perceive/decide/act/report)
    ├── registry.py          #   Async-safe agent index
    ├── spawner.py           #   Template-based factory
    ├── pool.py              #   Resource pools + health checks
    ├── scaler.py            #   Demand-based pool scaling
    ├── heartbeat.py         #   Periodic pulse loop
    ├── event_log.py         #   Append-only SQLite audit log
    ├── identity.py          #   Persistent agent identity
    └── skill_agent.py       #   SkillBasedAgent (dynamic skill dispatch)

ui/src/                      # HXI — Human Experience Interface (React + Three.js)
├── canvas/                  #   WebGL cognitive mesh visualization
├── components/              #   CognitiveCanvas, AgentTooltip, overlays
├── audio/                   #   TTS, speech input, sound engine
├── store/                   #   Zustand state management
└── hooks/                   #   WebSocket connection to runtime
```

## Tests

1605 tests covering every layer (1590 Python + 15 Vitest):

```bash
uv run pytest tests/ -v          # Python tests
cd ui && npx vitest run           # UI tests
```

## Key Concepts

**Self-selection.** Agents decide whether to handle an intent via `perceive()`. The system doesn't assign work — agents volunteer based on capability matching.

**Confidence tracking.** Each agent maintains a Bayesian confidence score. Success moves it toward 1.0, failure toward 0.0. Agents degraded below 0.2 are recycled and replaced.

**Hebbian learning.** "Neurons that fire together wire together." When an agent successfully handles an intent, the connection weight between that intent and agent strengthens. Over time, the system learns optimal routing.

**Consensus pipeline.** Destructive operations follow: broadcast → quorum evaluation → red team verification → Shapley attribution → trust update → Hebbian learning. A single corrupted agent cannot cause damage.

**Self-modification.** When ProbOS encounters a capability gap (no agent can handle a request), it designs a new agent: LLM generates code → CodeValidator static analysis → SandboxRunner isolation test → probationary trust → SystemQA smoke tests → BehavioralMonitor tracks post-deployment. Agents can also be designed collaboratively via `/design`.

**Correction feedback loop.** Human corrections are the richest learning signal. CorrectionDetector identifies when the user is correcting a previous result → AgentPatcher modifies the responsible agent → hot-reload → auto-retry → trust/Hebbian/episodic updates.

**Dreaming.** During idle periods, the system replays recent episodes to strengthen successful pathways, weaken failed ones, prune dead connections, adjust trust scores, and pre-warm predictions for likely upcoming requests.

**Dynamic intent discovery.** Each agent class declares structured `IntentDescriptor` metadata. The decomposer's system prompt is assembled at runtime from whatever agents are registered. New agent types self-integrate without any configuration changes.

**Federation.** Multiple ProbOS nodes form a Nooplex — a cognitive mesh of meshes. Each node is sovereign (its own agents, trust, memory). Nodes exchange capabilities via ZeroMQ gossip protocol and can forward intents across the federation.

**HXI (Human Experience Interface).** A WebGL visualization of the cognitive mesh rendered in Three.js. Agent nodes glow with trust-mapped colors, pulse with activity, and connect with Hebbian-weighted edges. Real-time WebSocket streaming from the runtime.

## Development Status

**Phase 27 complete — 1605 tests passing.**

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Substrate + Mesh (agent lifecycle, intent bus, Hebbian routing, gossip) | Done |
| 2 | Consensus (quorum voting, trust network, red team verification) | Done |
| 3a | Cognitive core (LLM decomposer, working memory, DAG execution) | Done |
| 3b | Episodic memory, attention, dreaming, workflow cache | Done |
| 4 | Experience layer (shell, renderer, panels) | Done |
| 5 | Expansion agents (search, directory, shell, HTTP, introspect) | Done |
| 6 | Introspection + dynamic intent discovery (self-assembling prompts) | Done |
| 7 | Escalation cascades + error recovery | Done |
| 8 | Adaptive pool scaling (demand-based sizing) | Done |
| 9 | Federation (ZeroMQ transport, router, gossip, multi-node) | Done |
| 10 | Self-modification (agent designer, code validator, sandbox, behavioral monitor) | Done |
| 11 | Skills + transparency + web research | Done |
| 12 | Per-tier LLM endpoints (fast/standard/deep) | Done |
| 13 | Workflow caching (LRU, exact + fuzzy matching, pre-warm) | Done |
| 14 | Persistent knowledge (Git-backed store, warm boot, rollback) | Done |
| 15 | CognitiveAgent base class + domain-aware skill attachment | Done |
| 16 | DAG proposal mode (/plan, /approve, /reject) | Done |
| 17 | Dependency resolution (auto-install agent imports) | Done |
| 18 | Feedback-to-learning loop + correction detection + agent patching | Done |
| 19 | Shapley value trust attribution + trust-weighted matching | Done |
| 20 | Emergent behavior detection (5 algorithms) | Done |
| 21 | Semantic Knowledge Layer (ChromaDB, 5 collections) | Done |
| 22 | Bundled agent suite + distribution (`pip install`, `probos serve`) | Done |
| 23 | HXI MVP (WebSocket events, React/Three.js cognitive canvas) | Done |
| 27 | Codebase knowledge graph + impact analysis | Done |

## Roadmap

| Phase | Title | Goal |
|-------|-------|------|
| 24 | Channel Integration | Discord, Slack, Telegram adapters + external tool connectors |
| 25 | Persistent Tasks | Long-running autonomous tasks with checkpointing, browser automation |
| 26 | Inter-Agent Deliberation | Structured multi-turn agent debates, agent-to-agent messaging |
| 28 | Meta-Learning | Workspace Ontology, dream cycle abstractions, session context, goal planning |
| 29 | Federation + Emergence | Knowledge federation, trust transitivity, TC_N measurement |

## Dependencies

| Package | Purpose |
|---------|---------|
| [pydantic](https://docs.pydantic.dev/) >=2.0 | Configuration validation |
| [pyyaml](https://pyyaml.org/) >=6.0 | YAML config loading |
| [aiosqlite](https://github.com/omnilib/aiosqlite) >=0.19 | Async SQLite (event log, Hebbian weights, trust, episodic memory) |
| [rich](https://rich.readthedocs.io/) >=13.0 | Terminal UI (panels, tables, Live display, spinners) |
| [httpx](https://www.python-httpx.org/) >=0.27 | HTTP client (LLM API, HTTP fetch agent) |
| [pyzmq](https://pyzmq.readthedocs.io/) >=27.1 | ZeroMQ transport (federation) |
| [chromadb](https://docs.trychroma.com/) >=1.0 | Vector database (semantic memory, knowledge layer) |
| [fastapi](https://fastapi.tiangolo.com/) >=0.115 | API server + WebSocket events (HXI backend) |
| [uvicorn](https://www.uvicorn.org/) >=0.34 | ASGI server |

Dev: pytest >=8.0, pytest-asyncio >=0.23, vitest (UI)

## License

Apache License 2.0. See [LICENSE](LICENSE).
