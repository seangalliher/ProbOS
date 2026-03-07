# Probabilistic OS — Claude Code Build Prompt

## Project Identity

**Name:** ProbOS (working title)  
**Tagline:** No kernel. No determinism. No apps. Just agents, all the way down.  
**Author:** Sean — Agentic AI Evangelism, Microsoft Dynamics 365  
**Conceptual Lineage:** The Noöplex framework, Minsky's Society of Mind, Argus AX architecture, Agent Experience (AX) paradigm

---

## Vision

Build a prototype **probabilistic agent-native operating system runtime** — a software layer that sits on top of Linux and replaces traditional OS abstractions (filesystem, process scheduler, IPC, shell, app launcher) with a fully agent-driven architecture where reliability emerges from redundancy, consensus, and statistical convergence rather than deterministic guarantees.

This is inspired by the biological brain: individual neurons are unreliable and probabilistic, yet the system achieves extraordinary reliability through population coding, Hebbian learning, redundancy, and graceful degradation. We apply these principles to computing.

**This is NOT a toy chatbot orchestrator.** This is an attempt to build a fundamentally new computing paradigm where the LLM is the cognitive substrate of the system and every function — file operations, process management, networking, scheduling, user interaction — is performed by agents operating probabilistically.

---

## Architecture — Five Layers

Build these bottom-up. Each layer enables the next.

### Layer 1: Substrate (≈ Neurons & Glia)
**Replaces:** Kernel, device drivers, HAL

Hardware abstraction through redundant agent pools. No single agent owns a resource.

**Build:**
- **Agent Runtime:** A lightweight agent container/executor. Each agent is a Python async process (or Rust if performance demands it) with a standard interface: `perceive()`, `decide()`, `act()`, `report()`.
- **Resource Pools:** For every system resource (filesystem, network, memory), maintain a pool of N redundant agents (configurable, default 3-5). All agents in a pool perform the same operation independently.
- **Heartbeat Agents:** Ultra-simple agents that maintain basic system rhythms — health monitoring, resource utilization tracking, temperature/load awareness. They don't reason. They pulse on fixed intervals and broadcast status.
- **Agent Spawner:** A factory that creates new agents from templates when pool members die or degrade. Tracks agent lifecycle: spawn → active → degraded → recycled.
- **Graceful Degradation:** If N of M pool agents fail, the system continues at reduced capability. No crashes. Ever. Log degradation state and auto-spawn replacements.

**Key Design Decisions:**
- Agent-to-hardware communication still uses syscalls underneath — we're not replacing the Linux kernel, we're building a cognitive layer above it. The agents wrap syscalls in probabilistic, redundant execution.
- Each agent maintains its own confidence score (0.0–1.0) that adjusts based on success/failure history.

### Layer 2: Mesh (≈ White Matter & Connectome)
**Replaces:** IPC, message queues, system bus, sockets

Communication between agents is associative and emergent, not routed through a central bus.

**Build:**
- **Capability Registry:** Agents register their capabilities as semantic descriptors (not rigid API signatures). Example: a file-read agent registers `{"can": "read_file", "formats": ["text", "binary", "structured"], "confidence": 0.95}`.
- **Gossip Protocol:** Agents share state through epidemic-style gossip. Each agent maintains a partial view of the mesh. No agent knows everything. Implement using a simple gossip protocol (e.g., SWIM-style failure detection + state dissemination).
- **Hebbian Routing:** Track connection weights between agents. When Agent A delegates to Agent B and the result is successful, increase the A→B weight. Future similar requests route preferentially along strong connections. Decay unused connections over time. `weight = weight * decay + reward` on each interaction.
- **Intent Broadcasting:** Requests are not sent to specific agents. They are broadcast as intent objects with context: `{"intent": "read_file", "path": "/data/report.csv", "urgency": 0.7, "context": "user requested quarterly data"}`. Agents self-select based on capability match and confidence.
- **Signal Decay:** Messages have a TTL (time-to-live). If no agent picks up a request within the TTL, it fades. This prevents queue buildup and deadlocks. Configurable decay rates per message priority.
- **Multicast Resolution:** When multiple agents respond to the same intent, the mesh collects all responses and forwards them to the consensus layer.

**Key Design Decisions:**
- Use an in-process message bus initially (asyncio queues or ZeroMQ for multi-process). The gossip protocol can be simulated in-process first and distributed later.
- Connection weights persist to disk so the system retains its learned topology across restarts.

### Layer 3: Consensus (≈ Neural Populations & Cortical Columns)
**Replaces:** Error handling, ACID transactions, permissions, validation

No single agent's output is trusted. Everything is verified statistically.

**Build:**
- **Quorum Engine:** For every action that modifies state (write, delete, send, allocate), require agreement from a quorum of agents. Configurable quorum size by risk level: low-risk (2-of-3), medium (3-of-5), high/destructive (5-of-7). The engine collects agent outputs, compares them, and commits only on quorum agreement.
- **Confidence-Weighted Voting:** Don't just count votes — weight them by each agent's historical accuracy, specialization relevance, and recency of last successful operation. A file agent that's been correct 99.7% of the time outweighs a freshly spawned one.
- **Disagreement Handling:** When quorum fails, implement escalation cascades:
  - Level 1: Re-run with fresh agent instances
  - Level 2: Expand the pool (spawn more agents, try again)
  - Level 3: Escalate to cognitive layer for LLM reasoning about the disagreement
  - Level 4: Surface to user with explanation ("I'm uncertain about this — here's what happened")
- **Adversarial Agents (Red Team):** Dedicated agents that don't produce work — they stress-test other agents' outputs. A red-team agent might re-read a file that was just written and verify contents match. Or hash a network response independently. These are the immune system.
- **Trust Network:** Agents build reputation through successful operations. New agents start sandboxed (low trust, outputs always double-checked). Trust is earned through consistent accuracy. Trust decays if not reinforced. Implement as a simple reputation score per agent with Bayesian updating.
- **Audit Trail:** Every consensus decision is logged with full context: which agents participated, what each produced, how the vote resolved, confidence scores. This replaces traditional logging/debugging.

**Key Design Decisions:**
- The quorum engine is the most critical component. Start here when building Layer 3. Without consensus, the system is just chaos.
- Risk levels should be configurable and the system should learn appropriate risk levels for operations over time.

### Layer 4: Cognitive (≈ Cortex & Prefrontal)
**Replaces:** Application logic, shell, scheduler, window manager

The LLM reasoning layer. This is where intelligence lives.

**Build:**
- **Intent Decomposition Engine:** Takes natural language user input and decomposes it into a directed acyclic graph (DAG) of agent tasks. Example: "Prepare my quarterly report" → [gather_data → analyze_trends → compose_document → format → stage_for_review]. Each node in the DAG is broadcast as an intent to the mesh.
- **Attention Mechanism (replaces process scheduler):** Instead of time-sliced scheduling, implement an attention system. Agents compete for compute resources by signaling urgency and relevance. The attention mechanism allocates resources proportional to: task urgency × user focus × deadline proximity × dependency chain position. Background tasks get sparse, intermittent attention.
- **Episodic Memory:** Store not just data but experiences — which agent compositions worked, which failed, what the user preferred. Implement as a vector store (could use ChromaDB, Qdrant, or simple embeddings + cosine similarity) of past workflows and their outcomes. Over time, the system develops "habits": frequently-used workflows get pre-composed and pre-warmed.
- **Working Memory:** Active context for the current user session. What tasks are in flight, what the user has been doing, what state the system is in. This is the equivalent of the brain's working memory / prefrontal cortex. Implement as a structured context object that the LLM receives with every reasoning call.
- **Dreaming / Defrag:** During idle periods (low user activity), the system replays recent operations, strengthens successful agent pathways (increase Hebbian weights), prunes weak connections, and pre-computes likely upcoming workflows based on temporal patterns. Schedule as a background process.
- **LLM Integration:** Use a capable LLM (Claude via API, or local models for latency-sensitive operations) as the reasoning engine. The LLM doesn't micromanage — it decomposes intent, resolves escalations from the consensus layer, and makes judgment calls. Simple, well-understood operations should route directly through the mesh without hitting the LLM.

**Key Design Decisions:**
- The LLM is called for reasoning, not for routine operations. A file read shouldn't require an LLM call. But deciding *which* file to read based on ambiguous user intent does.
- Implement a tiered decision system: fast heuristic agents handle routine operations, LLM handles novel or ambiguous ones. This manages latency.
- Working memory must be bounded. Implement eviction based on relevance decay (like human working memory).

### Layer 5: Experience (≈ Consciousness & Qualia)
**Replaces:** GUI, desktop, file explorer, app launcher, notifications

The user-facing surface. No apps. No windows. Just fluid, contextual experience.

**Build:**
- **Terminal Interface (Phase 1):** Start with a rich terminal interface. The user types natural language. The system responds with structured output (tables, progress indicators, summaries, confirmations). Use Rich (Python) or Ink (Node.js) for sophisticated terminal rendering.
- **Continuous Surface (Phase 2):** A web-based interface where the workspace morphs based on context. Working on data? Show tables and charts. Writing? Show a clean editor surface. Reviewing? Show diffs and annotations. The system decides what to show based on cognitive layer inference.
- **Ambient State Communication:** Instead of notification pop-ups, communicate system state through ambient signals — color shifts in the terminal/UI, subtle indicators of system health, confidence levels, active agent populations.
- **Intent as Interface:** Primary interaction is natural language. Secondary interaction is gesture/selection on the rendered surface. The user never navigates menus or launches apps.
- **Versioned State (No Save/Undo):** Everything is versioned by default. Not as files, but as states. "Go back to how this looked yesterday" is a valid command. The system maintains a continuous episodic record.

**Key Design Decisions:**
- Start with the terminal interface. Don't try to build the web UI until the underlying layers work.
- The experience layer is thin by design. It's a rendering surface for the cognitive layer's decisions, not an independent application.

---

## Technology Stack (Recommended)

- **Language:** Python 3.12+ for the agent runtime and orchestration. Rust for any performance-critical substrate components (optional, optimize later).
- **Python Toolchain:** [uv](https://docs.astral.sh/uv/) for Python version management, virtual environments, and dependency resolution. No system Python, pip, venv, or pyenv required — uv handles all of it in a single Rust-based tool. Install with `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- **Async Framework:** asyncio for agent concurrency. Each agent is an async task.
- **Message Passing:** In-process asyncio queues initially. ZeroMQ or NATS for multi-process/distributed later.
- **LLM Integration:** VS Code Copilot Proxy (see LLM Endpoint Configuration below). The cognitive layer communicates with the LLM through the GitHub Copilot language model API exposed via VS Code's built-in proxy. This provides access to multiple model backends (GPT-4o, Claude, etc.) through a single authenticated endpoint with no separate API key management.
- **Vector Store:** ChromaDB (embedded) for episodic memory. Lightweight, no external server.
- **State Persistence:** SQLite for agent trust scores, Hebbian weights, and audit trails. Simple, reliable, zero-config.
- **Terminal UI:** Rich (Python) for Phase 1 terminal interface.
- **Configuration:** YAML for system config, agent templates, risk level thresholds.

### LLM Endpoint Configuration — VS Code Copilot Proxy

ProbOS uses the VS Code GitHub Copilot proxy as its LLM endpoint. This means:

1. **The development VM runs VS Code** (or connects via VS Code Remote-SSH from the host).
2. **The Copilot extension** handles authentication, token management, and model routing.
3. **ProbOS connects to the local proxy** that Copilot exposes, treating it as a standard OpenAI-compatible chat completions endpoint.

**How to wire it:**

The cognitive layer should implement an `LLMClient` abstraction with a pluggable backend interface:

```python
class LLMClient:
    """Abstraction over LLM endpoint. Default: VS Code Copilot proxy."""
    
    def __init__(self, endpoint: str = "http://localhost:{copilot_port}/v1/chat/completions"):
        self.endpoint = endpoint
        
    async def reason(self, system_prompt: str, user_message: str, temperature: float = 0.3) -> str:
        """Send a reasoning request to the LLM via Copilot proxy."""
        # Standard OpenAI-compatible request format
        payload = {
            "model": "gpt-4o",  # or claude-sonnet via Copilot model picker
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "temperature": temperature,
            "max_tokens": 4096
        }
        # POST to Copilot proxy endpoint
        async with aiohttp.ClientSession() as session:
            async with session.post(self.endpoint, json=payload) as resp:
                data = await resp.json()
                return data["choices"][0]["message"]["content"]
```

**Tiered model routing (important for latency management):**

| Decision Type | Model | Why |
|---|---|---|
| Routine agent dispatch (well-known patterns) | No LLM call — use cached heuristic | Latency: ~0ms |
| Simple intent classification | GPT-4o-mini via Copilot | Fast, cheap, good enough |
| Complex decomposition / planning | GPT-4o or Claude via Copilot | Higher reasoning quality |
| Escalation from consensus layer | Best available model | Accuracy matters most here |
| Dreaming / background optimization | Any model, low priority | Runs during idle, latency irrelevant |

The `LLMClient` should accept a `tier` parameter that maps to model selection, so the cognitive layer can say `await llm.reason(prompt, message, tier="fast")` vs `tier="deep"`.

**Fallback chain:** If the Copilot proxy is unavailable (VS Code not running, extension crashed), the LLMClient should fall back to: (1) cached responses for known patterns, (2) heuristic-only mode where the cognitive layer operates on rules without LLM reasoning, (3) graceful degradation notification to the user. The system should never hard-fail because the LLM is unreachable — that would violate the core probabilistic design principle.

---

## VM Environment Setup

### VM Specification by Phase

| Phase | vCPUs | RAM | Disk | Notes |
|---|---|---|---|---|
| Phase 1-2 (Substrate + Consensus) | 4 | 8 GB | 40 GB SSD | No LLM calls yet, pure agent runtime |
| Phase 3 (Cognitive) | 4 | 16 GB | 60 GB SSD | ChromaDB + LLM context caching needs RAM |
| Phase 4-5 (Experience + Expansion) | 8 | 16-32 GB | 100 GB SSD | Full agent populations + episodic memory growth |
| Multi-node (Stretch) | 4 per node × N | 8 GB per node | 40 GB per node | Mesh spans VMs via NATS/ZeroMQ |

Any hypervisor works: Hyper-V (native on Windows), VirtualBox, VMware, or Azure VMs. For local development, Hyper-V is the path of least resistance since you're already on Microsoft's stack.

### Base VM Setup Script

Run this after a fresh Ubuntu 24.04 Server install:

```bash
#!/bin/bash
# probos-vm-setup.sh — ProbOS Development VM Bootstrap
set -euo pipefail

echo "=== ProbOS VM Setup ==="

# --- System updates ---
sudo apt update && sudo apt upgrade -y

# --- Core dependencies ---
sudo apt install -y \
    git curl wget htop tree jq \
    build-essential \
    sqlite3 libsqlite3-dev \
    openssh-server \
    tmux

# --- Install uv (Python toolchain manager) ---
# uv handles Python installation, virtual environments, and dependency resolution.
# No system Python, pip, venv, or pyenv needed.
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# --- Create project structure ---
mkdir -p ~/probos/{src,config,data,logs,templates,tests}
mkdir -p ~/probos/src/{substrate,mesh,consensus,cognitive,experience}
mkdir -p ~/probos/data/{episodic_memory,agent_state,audit_trail}
mkdir -p ~/probos/config/{agents,pools,risk_levels}

# --- Python setup via uv ---
cd ~/probos
uv python install 3.12
uv venv --python 3.12

# --- Python dependencies ---
# Install the project in editable mode with dev dependencies.
# All deps are declared in pyproject.toml — uv resolves and installs them.
uv pip install -e ".[dev]"

# --- VS Code Server (for Remote-SSH + Copilot proxy) ---
# If connecting via VS Code Remote-SSH from host, VS Code server installs automatically.
# If running VS Code directly in the VM (desktop environment):
# wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > packages.microsoft.gpg
# sudo install -o root -g root -m 644 packages.microsoft.gpg /etc/apt/trusted.gpg.d/
# sudo sh -c 'echo "deb [arch=amd64] https://packages.microsoft.com/repos/code stable main" > /etc/apt/sources.list.d/vscode.list'
# sudo apt update && sudo apt install -y code

# --- System tuning for agent populations ---
# Increase file descriptor limits (agents open many handles)
echo "* soft nofile 65536" | sudo tee -a /etc/security/limits.conf
echo "* hard nofile 65536" | sudo tee -a /etc/security/limits.conf

# Increase max async I/O
echo "fs.aio-max-nr = 1048576" | sudo tee -a /etc/sysctl.conf

# Increase inotify watches (agents monitor filesystem)
echo "fs.inotify.max_user_watches = 524288" | sudo tee -a /etc/sysctl.conf

sudo sysctl -p

# --- Initial config files ---
cat > ~/probos/config/system.yaml << 'EOF'
# ProbOS System Configuration
system:
  name: "ProbOS"
  version: "0.1.0"
  log_level: "DEBUG"  # DEBUG during development, INFO in production

# LLM Endpoint — VS Code Copilot Proxy
llm:
  endpoint: "http://localhost:1337/v1/chat/completions"  # Default Copilot proxy port — verify actual port
  timeout_seconds: 30
  retry_attempts: 3
  fallback_mode: "heuristic"  # Options: heuristic, cached, error
  tiers:
    fast:
      model: "gpt-4o-mini"
      temperature: 0.2
      max_tokens: 1024
    standard:
      model: "gpt-4o"
      temperature: 0.3
      max_tokens: 4096
    deep:
      model: "gpt-4o"  # or claude-sonnet if available via Copilot
      temperature: 0.4
      max_tokens: 8192

# Agent Pools
pools:
  default_pool_size: 3
  max_pool_size: 7
  min_pool_size: 2
  spawn_cooldown_ms: 500
  health_check_interval_seconds: 10

# Consensus
consensus:
  default_quorum: "majority"  # majority, supermajority, unanimous
  risk_levels:
    low:
      quorum_size: 2
      quorum_required: 2      # 2-of-2
      red_team: false
    medium:
      quorum_size: 3
      quorum_required: 2      # 2-of-3
      red_team: true
    high:
      quorum_size: 5
      quorum_required: 4      # 4-of-5
      red_team: true
    destructive:
      quorum_size: 5
      quorum_required: 5      # unanimous
      red_team: true
      user_confirmation: true

# Mesh
mesh:
  gossip_interval_ms: 1000
  hebbian_decay_rate: 0.995   # Per interaction cycle
  hebbian_reward: 0.05
  signal_ttl_seconds: 30
  capability_broadcast_interval_seconds: 5

# Episodic Memory
memory:
  vector_store: "chromadb"
  collection_name: "probos_episodes"
  max_episodes: 100000
  relevance_threshold: 0.7

# Dreaming / Defrag
dreaming:
  idle_threshold_seconds: 300  # Start dreaming after 5 min idle
  pathway_strengthening_factor: 1.1
  prune_threshold: 0.01       # Remove connections below this weight
EOF

cat > ~/probos/config/agents/file_reader.yaml << 'EOF'
# File Reader Agent Template
agent:
  type: "file_reader"
  pool: "filesystem"
  initial_confidence: 0.8
  capabilities:
    - can: "read_file"
      formats: ["text", "binary", "csv", "json", "yaml", "xml"]
      max_size_mb: 100
    - can: "stat_file"
      detail: "Return file metadata (size, modified, permissions)"
    - can: "search_content"
      detail: "Search within file contents by pattern"
  risk_classification: "low"  # Reading is non-destructive
  resource_requirements:
    max_memory_mb: 256
    max_open_handles: 10
EOF

cat > ~/probos/config/agents/file_writer.yaml << 'EOF'
# File Writer Agent Template
agent:
  type: "file_writer"
  pool: "filesystem"
  initial_confidence: 0.7     # Lower initial confidence — writes are riskier
  capabilities:
    - can: "write_file"
      formats: ["text", "binary", "csv", "json", "yaml"]
    - can: "create_directory"
    - can: "move_file"
    - can: "copy_file"
  risk_classification: "medium"  # Writes require consensus
  resource_requirements:
    max_memory_mb: 256
    max_open_handles: 5
EOF

cat > ~/probos/config/agents/red_team.yaml << 'EOF'
# Red Team (Adversarial) Agent Template
agent:
  type: "red_team_verifier"
  pool: "security"
  initial_confidence: 0.9     # High trust — verification is its specialty
  capabilities:
    - can: "verify_write"
      detail: "Re-read written data and verify integrity"
    - can: "verify_hash"
      detail: "Independently hash content and compare"
    - can: "challenge_result"
      detail: "Stress-test another agent's output for correctness"
  risk_classification: "low"   # Verification is non-destructive
  never_writes: true            # Red team agents NEVER modify state
  resource_requirements:
    max_memory_mb: 128
    max_open_handles: 5
EOF

echo ""
echo "=== ProbOS VM Setup Complete ==="
echo "Project structure: ~/probos/"
echo "Run commands with: uv run <command>"
echo "Run tests:         uv run pytest tests/ -v"
echo "Run demo:          uv run python demo.py"
echo ""
echo "Next: Connect VS Code via Remote-SSH, enable Copilot, then start building Phase 1."
echo ""
```

### Development Workflow

```
┌─────────────────────────────────────────────────┐
│  HOST MACHINE (Windows / macOS)                 │
│                                                 │
│  VS Code + Copilot Extension                    │
│    ├── Remote-SSH → ProbOS VM                   │
│    ├── Copilot Chat (for Claude Code prompting) │
│    └── Copilot Proxy (LLM endpoint for ProbOS)  │
│         ↓                                       │
│    http://localhost:1337/v1/chat/completions     │
│         │ (port-forwarded via SSH tunnel)        │
│         ↓                                       │
├─────────────────────────────────────────────────┤
│  PROBOS VM (Ubuntu 24.04)                       │
│                                                 │
│  ~/probos/                                      │
│    ├── src/substrate/    → Agent runtime         │
│    ├── src/mesh/         → Gossip + routing      │
│    ├── src/consensus/    → Quorum engine         │
│    ├── src/cognitive/    → LLM reasoning layer   │
│    │     └── llm_client.py → Hits Copilot proxy  │
│    ├── src/experience/   → Terminal UI           │
│    ├── config/           → YAML configs          │
│    ├── data/             → SQLite + ChromaDB     │
│    └── logs/             → Audit trails          │
│                                                 │
│  Toolchain: uv (Python, venv, deps)            │
│  Run: uv run python demo.py                    │
│  Test: uv run pytest tests/ -v                  │
│  ProbOS daemon runs as a tmux session           │
│  User interacts via terminal or web surface     │
└─────────────────────────────────────────────────┘
```

### Copilot Proxy Port Discovery

The Copilot proxy port is dynamically assigned. To find it from within the VM:

```python
# Add to probos/src/cognitive/llm_client.py
import json
import os
from pathlib import Path

def discover_copilot_port() -> int:
    """
    Discover the VS Code Copilot proxy port.
    When connected via Remote-SSH, VS Code forwards the proxy.
    The port may be in VS Code's forwarded ports or environment.
    
    Fallback: check common ports or read from config.
    """
    # Method 1: Environment variable (if VS Code sets it)
    port = os.environ.get("GITHUB_COPILOT_PORT")
    if port:
        return int(port)
    
    # Method 2: Read from ProbOS config (manually set after discovery)
    config_path = Path.home() / "probos" / "config" / "system.yaml"
    # ... parse yaml and return llm.endpoint port
    
    # Method 3: Probe common ports
    import socket
    for candidate in [1337, 3000, 8080, 11434]:
        try:
            with socket.create_connection(("localhost", candidate), timeout=1):
                return candidate
        except (ConnectionRefusedError, TimeoutError):
            continue
    
    raise RuntimeError("Could not discover Copilot proxy port. Is VS Code running with Copilot?")
```

### Important: SSH Port Forwarding for Copilot Proxy

If running VS Code on your host and connecting to the VM via Remote-SSH, the Copilot proxy runs on the **host**. You need to forward it into the VM so ProbOS can reach it:

```bash
# In VS Code settings.json, add:
# "remote.SSH.defaultForwardedPorts": [{"localPort": 1337, "remotePort": 1337}]

# Or manually via SSH:
# ssh -R 1337:localhost:1337 user@probos-vm
```

This makes the host's Copilot proxy available at `localhost:1337` inside the VM.

---

## Build Plan — Phased

### Phase 1: Substrate + Mesh (Foundation)
**Goal:** Agents can spawn, communicate, and discover each other.

Deliverables:
1. Agent base class with standard lifecycle (`perceive`, `decide`, `act`, `report`)
2. Agent spawner/factory with template system
3. Resource pool manager (maintain N agents per resource type)
4. Capability registry with semantic descriptors
5. Intent broadcasting and self-selection
6. Gossip protocol for state dissemination
7. Hebbian weight tracking on agent connections
8. Signal decay / TTL on messages
9. Basic file system agents (read, write, list, search) as first pool
10. Heartbeat agents for system health

**Milestone:** User can issue a file operation request. Multiple agents attempt it. Results are returned. Agents discover each other through capability broadcasting.

### Phase 2: Consensus (Reliability)
**Goal:** The system becomes trustworthy through statistical verification.

Deliverables:
1. Quorum engine with configurable thresholds
2. Confidence-weighted voting
3. Disagreement detection and escalation cascades
4. Adversarial (red team) agents
5. Trust network with Bayesian reputation scoring
6. Audit trail logging
7. Risk level classification for operations

**Milestone:** A file write operation is performed by 3 agents independently, verified by quorum, checked by a red-team agent, and committed only on consensus. A deliberately corrupted agent's output is caught and rejected.

### Phase 3: Cognitive (Intelligence)
**Goal:** The system can reason, plan, and learn.

Deliverables:
1. LLM integration with Claude API
2. Intent decomposition engine (NL → task DAG)
3. Attention-based resource allocation
4. Working memory management
5. Episodic memory with vector store
6. Dreaming/defrag background process
7. Tiered decision system (heuristic vs. LLM routing)

**Milestone:** User says "organize my downloads folder by project." The cognitive layer decomposes this into: scan files → infer project associations → create structure → move files → verify. Each step is performed by agents through the mesh with consensus verification. The system remembers this workflow for next time.

### Phase 4: Experience (Interface)
**Goal:** The system is usable.

Deliverables:
1. Rich terminal interface with natural language input
2. Structured output rendering (tables, progress, summaries)
3. Ambient state indicators
4. Versioned state / temporal navigation
5. Session context and continuity

**Milestone:** A user can sit at the terminal and accomplish real work — file management, data analysis, writing, scheduling — entirely through natural language, with the system learning their preferences over time.

### Phase 5: Expansion (Capability)
**Goal:** The system becomes genuinely useful for daily work.

Deliverables:
1. Network agents (HTTP, API calls, web fetching)
2. Process management agents (run programs, manage background tasks)
3. Calendar/scheduling agents
4. Email agents
5. Code execution agents (run scripts, compile, test)
6. Data analysis agents (CSV, JSON, databases)
7. Document agents (create, edit, format documents)

**Milestone:** The system can handle a full workday's worth of knowledge-worker tasks.

---

## Agent Template Specification

Every agent in the system conforms to this interface:

```
Agent:
  id: unique identifier (UUID)
  type: template type (e.g., "file_reader", "network_http", "red_team_verifier")
  pool: which resource pool this agent belongs to
  confidence: float 0.0–1.0 (self-assessed + externally calibrated)
  trust_score: float 0.0–1.0 (assigned by consensus layer)
  capabilities: list of semantic capability descriptors
  connections: dict of {agent_id: weight} (Hebbian routing table)
  state: enum (spawning, active, degraded, recycling)
  
  lifecycle:
    perceive(intent) → observation   # receive and interpret an intent from the mesh
    decide(observation) → plan        # determine action (may be "not my job" → decline)
    act(plan) → result                # execute the action
    report(result) → broadcast        # publish result to mesh for consensus
    
  meta:
    spawn_time: timestamp
    last_active: timestamp
    success_count: int
    failure_count: int
    total_operations: int
```

---

## Design Principles (Enforce These)

1. **No single points of failure.** Ever. Every function is performed by a pool. Every result is verified by consensus.
2. **No deterministic dependencies.** No agent should assume another specific agent exists. Agents discover capabilities, not addresses.
3. **Failure is expected.** The architecture assumes constant, ongoing failure of individual agents. This is not an error state — it is the normal operating condition.
4. **Reliability is statistical.** The system is reliable because the population is reliable, not because any individual is reliable.
5. **Learning is structural.** The system doesn't just store data — it reshapes its own topology. Successful pathways strengthen. Failed pathways weaken. The architecture itself is the learned model.
6. **The LLM reasons, agents execute.** The LLM is the prefrontal cortex. It plans and decides. Agents are the motor cortex. They act. Don't conflate these roles.
7. **Latency is managed, not eliminated.** Probabilistic systems are inherently slower than deterministic ones. Manage this through tiered decision-making, pre-warming, and learned shortcuts — not by reintroducing determinism.
8. **Transparency over opacity.** The system should be able to explain what it did, why, which agents were involved, and how consensus was reached. The audit trail is not optional.

---

## Stretch Goals / Future Considerations

- **Multi-node distribution:** The same architecture running across multiple machines, with the mesh spanning a network. This is the Noöplex at small scale.
- **Agent marketplace:** Third-party agents that can be introduced to the mesh. They self-integrate by broadcasting capabilities. No installation process.
- **Self-modification:** The cognitive layer can design and spawn new agent types it doesn't currently have. If it encounters a task with no capable agents, it reasons about what kind of agent would be needed and creates one.
- **Emotional valence:** Agents carry an urgency/importance signal analogous to emotional weighting in biological systems. Tasks connected to user-expressed frustration or urgency get amplified attention.

---

## What to Build First

Start with Phase 1. Build the agent runtime, spawner, and mesh communication. Get three file-system agents reading the same file independently and returning results. That single demo — three agents, same task, results compared — is the proof of concept for the entire paradigm.

Then add consensus (Phase 2) to verify those results. Then add the cognitive layer (Phase 3) to reason about intent. Then wrap it in a terminal interface (Phase 4).

**Do not skip ahead.** Each layer depends on the one below it. The substrate enables the mesh. The mesh enables consensus. Consensus enables cognition. Cognition enables experience.

---

*"They built arms. We built eyes."*  
*— Argus AX*
