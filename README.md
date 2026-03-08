# ProbOS

**Probabilistic agent-native OS runtime** — an operating system kernel where every component is an autonomous agent, coordination happens through consensus, and the system learns from its own behavior.

## What Is This?

ProbOS reimagines the OS as a mesh of probabilistic agents rather than deterministic processes. Instead of syscalls, you speak natural language. Instead of a scheduler, agents self-organize through Hebbian learning and trust networks. Instead of permissions, destructive operations require multi-agent consensus.

```
[24 agents | health: 0.95] probos> read pyproject.toml and tell me about this project

  ✓ t1: read_file

  This project is ProbOS v0.1.0, a probabilistic agent-native OS runtime...
```

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

Agents follow a `perceive → decide → act → report` lifecycle. A spawner creates them from templates, resource pools maintain target sizes, and a heartbeat system monitors liveness. Everything is logged to an append-only SQLite event log.

### Mesh

Agents discover each other through a capability registry with fuzzy matching. An intent bus does concurrent fan-out to all subscribers. A Hebbian router learns which agents handle which intents best. A gossip protocol exchanges state between agents.

### Consensus

Destructive operations (file writes, shell commands, HTTP fetches) require multi-agent agreement. A quorum engine collects confidence-weighted votes. A Bayesian trust network tracks agent reliability over time. Red team agents independently verify results.

### Cognitive

Natural language goes through: working memory assembly → LLM decomposition into a DAG of intents → parallel/sequential execution → optional reflection. An episodic memory stores past interactions for recall. An attention manager prioritizes concurrent tasks. A dreaming engine consolidates learning during idle periods. A workflow cache remembers successful patterns.

The decomposer's system prompt is **self-assembling** — each agent class declares `IntentDescriptor` metadata, and the prompt is built dynamically from whatever agents are registered. Adding a new agent type makes its intents available to the LLM automatically.

### Experience

A Rich-powered interactive shell with 16 slash commands, real-time DAG execution display with spinners, and formatted result panels.

## Agents

ProbOS boots with 24 agents across 8 pools (+ 2 red team verifiers):

| Pool | Agents | Capabilities |
|------|--------|-------------|
| system | 2 | Heartbeat monitoring (CPU, load, PID) |
| filesystem | 3 | `read_file`, `stat_file` |
| filesystem_writers | 3 | `write_file` (consensus required) |
| directory | 3 | `list_directory` |
| search | 3 | `search_files` (recursive glob) |
| shell | 3 | `run_command` (consensus required, 30s timeout) |
| http | 3 | `http_fetch` (consensus required, 1MB cap) |
| introspect | 2 | `explain_last`, `agent_info`, `system_health`, `why` |
| red_team | 2 | Independent result verification |

## Quick Start

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/)

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest tests/ -v

# Launch interactive shell
uv run python -m probos
```

ProbOS connects to an OpenAI-compatible LLM endpoint at `http://127.0.0.1:8080/v1` (configurable in `config/system.yaml`). If the endpoint is unavailable, it falls back to a built-in `MockLLMClient` with regex pattern matching for deterministic operation.

## Interactive Shell

```
probos> read /tmp/test.txt                   # Natural language → intent DAG
probos> list the files in /home/user/docs    # Directory listing
probos> write hello to /tmp/out.txt          # Consensus-verified write
probos> what just happened?                  # Introspection
probos> why did you use file_reader?         # Self-explanation
probos> how healthy is the system?           # System health assessment

probos> /status                              # Pool health, mesh, cognitive state
probos> /agents                              # Agent table with states
probos> /weights                             # Hebbian connection weights
probos> /memory                              # Working memory snapshot
probos> /attention                           # Task priority queue + focus history
probos> /dream now                           # Force a dream consolidation cycle
probos> /cache                               # Workflow cache contents
probos> /explain                             # Explain last execution
probos> /recall <query>                      # Search episodic memory
probos> /debug                               # Toggle debug mode
probos> /help                                # All commands
```

## Configuration

All tuning lives in `config/system.yaml`:

- **Pools** — target sizes, spawn cooldown, health check intervals
- **Mesh** — gossip rate, Hebbian decay/reward, signal TTL
- **Consensus** — min votes, approval threshold, trust priors and decay
- **Cognitive** — LLM endpoint/models/timeouts, token budget, attention parameters
- **Memory** — max episodes, relevance threshold
- **Dreaming** — idle threshold, replay count, strengthening/weakening factors

## How It Works

When you type natural language:

1. **Working memory** assembles system state (agent health, trust scores, Hebbian weights, capabilities)
2. **Episodic recall** finds similar past interactions for context
3. **Workflow cache** checks for a previously successful DAG pattern
4. **LLM decomposer** converts text into a `TaskDAG` — a graph of typed intents with dependencies
5. **Attention manager** scores and prioritizes the tasks
6. **DAG executor** runs independent intents in parallel, respects dependency ordering
7. **Consensus** gates destructive operations through multi-agent voting + red team verification
8. **Hebbian router** learns from outcomes — successful agent-intent pairings get stronger
9. **Episodic memory** stores the interaction for future recall
10. **Dreaming engine** consolidates learning during idle periods

## Project Structure

```
src/probos/
├── __init__.py          # Package root
├── __main__.py          # Entry point
├── config.py            # Pydantic config models
├── runtime.py           # Orchestrator
├── types.py             # Core types (IntentMessage, TaskDAG, Episode, etc.)
├── agents/              # Agent implementations
│   ├── file_reader.py
│   ├── file_writer.py
│   ├── directory_list.py
│   ├── file_search.py
│   ├── shell_command.py
│   ├── http_fetch.py
│   ├── introspect.py
│   ├── red_team.py
│   └── corrupted.py     # Test agent (deliberately wrong)
├── cognitive/           # LLM pipeline
│   ├── decomposer.py    # NL → TaskDAG + DAG executor
│   ├── prompt_builder.py # Dynamic system prompt assembly
│   ├── llm_client.py    # OpenAI-compatible + mock
│   ├── working_memory.py
│   ├── episodic.py      # SQLite long-term memory
│   ├── attention.py     # Priority scoring
│   ├── dreaming.py      # Offline consolidation
│   └── workflow_cache.py
├── consensus/           # Multi-agent agreement
│   ├── quorum.py
│   └── trust.py         # Bayesian reputation
├── experience/          # User interface
│   ├── shell.py         # REPL
│   ├── renderer.py      # DAG execution display
│   └── panels.py        # Rich panels
├── mesh/                # Agent coordination
│   ├── intent.py        # Pub/sub bus
│   ├── routing.py       # Hebbian learning
│   ├── capability.py    # Fuzzy matching registry
│   ├── gossip.py        # State exchange
│   └── signal.py        # TTL signals
└── substrate/           # Agent lifecycle
    ├── agent.py         # BaseAgent ABC
    ├── registry.py
    ├── spawner.py
    ├── pool.py
    ├── heartbeat.py
    └── event_log.py     # SQLite audit log
```

## Tests

477 tests covering every layer. Run with:

```bash
uv run pytest tests/ -v
```

## License

Not yet specified.
