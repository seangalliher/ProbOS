# Architecture Overview

ProbOS is built as seven layers, each built on the one below, plus two cross-cutting concerns:

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

## Layer Responsibilities

Each layer has a single, clear purpose:

| Layer | Responsibility |
|-------|---------------|
| [**Substrate**](substrate.md) | Agent lifecycle — birth, health, death, recycling |
| [**Mesh**](mesh.md) | Agent coordination — discovery, routing, communication |
| [**Consensus**](consensus.md) | Safety — multi-agent agreement before destructive actions |
| [**Cognitive**](cognitive.md) | Intelligence — NL understanding, memory, learning, self-modification |
| [**Experience**](experience.md) | Interface — shell, visualization, API |
| [**Federation**](federation.md) | Scale — multi-node mesh of meshes |
| [**Knowledge**](knowledge.md) | Persistence — durable storage with semantic search |

## Data Flow

A typical request flows through the stack:

```
User input (natural language)
    │
    ▼
Experience ──── Shell parses input
    │
    ▼
Cognitive ───── Working memory + episodic recall + cache lookup
    │              │
    │              ▼
    │           LLM decomposes into TaskDAG
    │              │
    ▼              ▼
Mesh ────────── Intent bus fans out to matching agents
    │
    ▼
Substrate ───── Agents perceive → decide → act → report
    │
    ▼
Consensus ───── Destructive ops: quorum vote + red team verify
    │
    ▼
Cognitive ───── Hebbian update + episodic store + cache store
    │
    ▼
Experience ──── Render results to user
```

## Design Principles

1. **Agents all the way down.** There is no central controller. Every capability is an agent.
2. **Probabilistic over deterministic.** Confidence scores, Bayesian trust, weighted voting.
3. **Self-organizing.** Hebbian learning routes intents to the best agents without configuration.
4. **Self-healing.** Degraded agents are recycled. Pools scale to demand.
5. **Self-modifying.** Capability gaps trigger the design of new agents at runtime.
6. **Transparent.** Every decision can be explained via introspection commands.
