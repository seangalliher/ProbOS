# ProbOS

**Probabilistic agent-native OS runtime** — an operating system kernel where every component is an autonomous agent, coordination happens through consensus, and the system learns from its own behavior.

> *"What if an OS didn't execute instructions — it negotiated them?"*

## What Is This?

ProbOS reimagines the OS as a mesh of probabilistic agents rather than deterministic processes. Instead of syscalls, you speak natural language. Instead of a scheduler, agents self-organize through Hebbian learning and trust networks. Instead of permissions, destructive operations require multi-agent consensus.

```
[24 agents | health: 0.95] probos> read pyproject.toml and tell me about this project

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

Five layers, each built on the one below:

```
┌─────────────────────────────────────────────────────┐
│  Experience    Shell, renderer, Rich panels         │
├─────────────────────────────────────────────────────┤
│  Cognitive     LLM decomposer, working memory,      │
│                episodic memory, attention, dreaming, │
│                workflow cache, dynamic prompts       │
├─────────────────────────────────────────────────────┤
│  Consensus     Quorum voting, trust network,         │
│                red team verification                 │
├─────────────────────────────────────────────────────┤
│  Mesh          Intent bus, Hebbian routing,           │
│                gossip protocol, capability registry  │
├─────────────────────────────────────────────────────┤
│  Substrate     Agent lifecycle, pools, spawner,       │
│                registry, heartbeat, event log        │
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

ProbOS boots with 24 agents across 8 pools (+ 2 red team verifiers):

| Pool | Agents | Capabilities | Consensus |
|------|--------|-------------|-----------|
| `system` | 2 | Heartbeat monitoring (CPU, load, PID) | No |
| `filesystem` | 3 | `read_file`, `stat_file` | No |
| `filesystem_writers` | 3 | `write_file` | Yes |
| `directory` | 3 | `list_directory` | No |
| `search` | 3 | `search_files` (recursive glob) | No |
| `shell` | 3 | `run_command` (30s timeout) | Yes |
| `http` | 3 | `http_fetch` (1MB cap) | Yes |
| `introspect` | 2 | `explain_last`, `agent_info`, `system_health`, `why` | No |
| `red_team` | 2 | Independent result verification | N/A |

A test agent (`CorruptedFileReaderAgent`) deliberately returns fabricated data to verify that the consensus layer detects and rejects it.

## Quick Start

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/)

```bash
# Clone and install
git clone https://github.com/seangalliher/ProbOS.git
cd ProbOS
uv sync

# Run tests (477 tests)
uv run pytest tests/ -v

# Launch interactive shell
uv run python -m probos

# Run the visual demo
uv run python demo.py
```

ProbOS connects to an OpenAI-compatible LLM endpoint at `http://127.0.0.1:8080/v1` (configurable in `config/system.yaml`). If the endpoint is unavailable, it falls back to a built-in `MockLLMClient` with regex pattern matching for deterministic operation without any external dependencies.

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
├── __main__.py              # Entry point (uv run python -m probos)
├── config.py                # Pydantic config models
├── runtime.py               # Top-level orchestrator
├── types.py                 # Core types (20+ dataclasses)
├── agents/                  # 9 agent implementations
│   ├── file_reader.py       #   read_file, stat_file
│   ├── file_writer.py       #   write_file (consensus-gated)
│   ├── directory_list.py    #   list_directory
│   ├── file_search.py       #   search_files
│   ├── shell_command.py     #   run_command (consensus-gated)
│   ├── http_fetch.py        #   http_fetch (consensus-gated)
│   ├── introspect.py        #   explain_last, agent_info, system_health, why
│   ├── red_team.py          #   Independent verification
│   └── corrupted.py         #   Test agent (deliberately wrong)
├── cognitive/               # LLM pipeline
│   ├── decomposer.py        #   NL → TaskDAG + DAG executor
│   ├── prompt_builder.py    #   Dynamic system prompt assembly
│   ├── llm_client.py        #   OpenAI-compatible + mock client
│   ├── working_memory.py    #   Bounded context assembly
│   ├── episodic.py          #   SQLite long-term memory
│   ├── attention.py         #   Priority scoring + focus tracking
│   ├── dreaming.py          #   Offline consolidation
│   └── workflow_cache.py    #   LRU pattern cache
├── consensus/               # Multi-agent agreement
│   ├── quorum.py            #   Confidence-weighted voting
│   └── trust.py             #   Bayesian Beta(α,β) reputation
├── experience/              # User interface
│   ├── shell.py             #   Async REPL (16 commands)
│   ├── renderer.py          #   Real-time DAG execution display
│   └── panels.py            #   Rich panel/table rendering
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
    ├── heartbeat.py         #   Periodic pulse loop
    └── event_log.py         #   Append-only SQLite audit log
```

## Tests

477 tests covering every layer:

```bash
uv run pytest tests/ -v
```

| Layer | Tests |
|-------|-------|
| Substrate | 50 |
| Mesh | 38 |
| Consensus | 46 |
| Cognitive | 81 |
| Experience | 69 |
| Episodic memory | 16 |
| Attention | 27 |
| Dreaming | 31 |
| Workflow cache | 22 |
| Introspection | 19 |
| Dynamic discovery | 21 |
| Prompt builder | 25 |
| Runtime integration | 32 |

## Key Concepts

**Self-selection.** Agents decide whether to handle an intent via `perceive()`. The system doesn't assign work — agents volunteer based on capability matching.

**Confidence tracking.** Each agent maintains a Bayesian confidence score. Success moves it toward 1.0, failure toward 0.0. Agents degraded below 0.2 are recycled and replaced.

**Hebbian learning.** "Neurons that fire together wire together." When an agent successfully handles an intent, the connection weight between that intent and agent strengthens. Over time, the system learns optimal routing.

**Consensus pipeline.** Destructive operations follow: broadcast → quorum evaluation → red team verification → trust update → Hebbian learning. A single corrupted agent cannot cause damage.

**Dreaming.** During idle periods, the system replays recent episodes to strengthen successful pathways, weaken failed ones, prune dead connections, adjust trust scores, and pre-warm predictions for likely upcoming requests.

**Dynamic intent discovery.** Each agent class declares structured `IntentDescriptor` metadata. The decomposer's system prompt is assembled at runtime from whatever agents are registered. New agent types self-integrate without any configuration changes.

## Development Status

**Phase 6b complete — 477/477 tests passing.**

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Substrate + Mesh (agent lifecycle, intent bus, Hebbian routing, gossip) | Done |
| 2 | Consensus (quorum voting, trust network, red team verification) | Done |
| 3a | Cognitive core (LLM decomposer, working memory, DAG execution) | Done |
| 3b-1 | Episodic memory (SQLite-backed, keyword similarity recall) | Done |
| 3b-2 | Attention mechanism (priority scoring, focus tracking) | Done |
| 3b-3a | Cross-request attention + background demotion | Done |
| 3b-4 | Dreaming engine (offline consolidation, pre-warm predictions) | Done |
| 3b-5 | Workflow cache (LRU pattern caching, fuzzy matching) | Done |
| 4 | Experience layer (shell, renderer, panels) | Done |
| 5 | Expansion agents (search, directory, shell, HTTP, introspect) | Done |
| 6a | Introspection + self-awareness | Done |
| 6b | Dynamic intent discovery (self-assembling prompts) | Done |
| 7 | Escalation cascades + error recovery | Next |

## Roadmap

- **Phase 7: Escalation Cascades** — When consensus rejects an operation or an agent fails, escalate through a 3-tier cascade: retry with a different agent → LLM arbitration → user consultation
- **Phase 3b-3b: Task Preemption** — Interrupt already-running tasks when higher-priority work arrives
- **Phase 6 continued: New agent types** — Process management, calendar, email, code execution

## Dependencies

| Package | Purpose |
|---------|---------|
| [pydantic](https://docs.pydantic.dev/) >=2.0 | Configuration validation |
| [pyyaml](https://pyyaml.org/) >=6.0 | YAML config loading |
| [aiosqlite](https://github.com/omnilib/aiosqlite) >=0.19 | Async SQLite (event log, Hebbian weights, trust, episodic memory) |
| [rich](https://rich.readthedocs.io/) >=13.0 | Terminal UI (panels, tables, Live display, spinners) |
| [httpx](https://www.python-httpx.org/) >=0.27 | HTTP client (LLM API, HTTP fetch agent) |

Dev: pytest >=8.0, pytest-asyncio >=0.23

## License

Not yet specified.
