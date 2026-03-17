# Architecture Overview

ProbOS is built as seven layers, each built on the one below, plus two cross-cutting concerns:

```mermaid
block-beta
    columns 1
    Experience["Experience\nCLI shell · HXI (WebGL) · FastAPI + WebSocket · Rich panels"]
    Cognitive["Cognitive\nLLM decomposer · working memory · episodic memory · attention\ndreaming · self-modification · agent design · workflow cache"]
    Consensus["Consensus\nQuorum voting · trust network · Shapley attribution · escalation"]
    Mesh["Mesh\nIntent bus · Hebbian routing · gossip protocol · capability registry"]
    Substrate["Substrate\nAgent lifecycle · pools · spawner · registry · heartbeat · event log"]
    space
    Federation["Federation (cross-cutting)\nZeroMQ transport · node bridge · intent router · gossip exchange"]
    Knowledge["Knowledge (cross-cutting)\nGit-backed store · ChromaDB semantic · warm boot · per-artifact rollback"]

    style Experience fill:#7c3aed,color:#fff
    style Cognitive fill:#6d28d9,color:#fff
    style Consensus fill:#5b21b6,color:#fff
    style Mesh fill:#4c1d95,color:#fff
    style Substrate fill:#3b0764,color:#fff
    style Federation fill:#b45309,color:#fff
    style Knowledge fill:#b45309,color:#fff
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

## Request Flow

A typical request flows through the stack:

```mermaid
flowchart TD
    A[User input\nnatural language] --> B[Experience\nShell parses input]
    B --> C[Cognitive\nWorking memory + episodic recall]
    C --> D{Workflow cache\nhit?}
    D -->|Yes| E[Reuse cached DAG]
    D -->|No| F[LLM decomposes\ninto TaskDAG]
    E --> G[Attention manager\nscores & prioritizes]
    F --> G
    G --> H[Mesh\nIntent bus fans out\nto matching agents]
    H --> I[Substrate\nAgents: perceive → decide → act]
    I --> J{Destructive\noperation?}
    J -->|Yes| K[Consensus\nQuorum vote +\nred team verify]
    J -->|No| L[Execute directly]
    K -->|Approved| L
    K -->|Rejected| M[Escalation cascade]
    L --> N[Cognitive\nHebbian update +\nepisodic store +\ncache store]
    N --> O[Experience\nRender results to user]

    style A fill:#7c3aed,color:#fff
    style B fill:#7c3aed,color:#fff
    style O fill:#7c3aed,color:#fff
    style C fill:#6d28d9,color:#fff
    style D fill:#6d28d9,color:#fff
    style F fill:#6d28d9,color:#fff
    style G fill:#6d28d9,color:#fff
    style N fill:#6d28d9,color:#fff
    style H fill:#4c1d95,color:#fff
    style I fill:#3b0764,color:#fff
    style K fill:#5b21b6,color:#fff
    style M fill:#5b21b6,color:#fff
```

## Consensus Pipeline

Destructive operations go through a multi-step safety pipeline:

```mermaid
flowchart LR
    A[Operation\nrequested] --> B[Broadcast to\nquorum pool]
    B --> C[Collect\nweighted votes]
    C --> D{Threshold\nmet?}
    D -->|Yes| E[Red team\nverification]
    D -->|No| H[Reject]
    E --> F{Red team\nagrees?}
    F -->|Yes| G[Execute +\nShapley attribution]
    F -->|No| H
    G --> I[Update trust\nscores]
    H --> J[Escalation\ncascade]

    style A fill:#4c1d95,color:#fff
    style B fill:#5b21b6,color:#fff
    style C fill:#5b21b6,color:#fff
    style E fill:#b45309,color:#fff
    style G fill:#059669,color:#fff
    style H fill:#dc2626,color:#fff
    style I fill:#059669,color:#fff
    style J fill:#dc2626,color:#fff
```

## Crew Organization

Agents are organized into specialized teams, analogous to departments on a starship. Each team is an agent pool with a distinct responsibility:

| Team | Function | Key Agents |
|------|----------|------------|
| **Medical** | Health monitoring, diagnosis, remediation | Vitals Monitor, Diagnostician, Surgeon, Pharmacist, Pathologist |
| **Engineering** | Performance optimization, maintenance, builds | Performance Monitor, Maintenance Agent, Builder Agent |
| **Science** | Research, discovery, architectural analysis | Research Agent, Architect Agent |
| **Security** | Threat detection, defense, trust integrity | Threat Detector, Trust Integrity Monitor, Red Team Lead |
| **Operations** | Resource management, scheduling, coordination | Resource Allocator, Scheduler, PoolScaler |
| **Communications** | Channel adapters, federation, external interfaces | Discord Adapter, Slack Adapter, Federation Bridge |
| **Bridge** | Strategic decisions, human approval gate | Introspection Agent, Human Approval Gate |

The **Ship's Computer** provides shared infrastructure across all teams: the Intent Bus (intercom), Trust Network (crew records), Hebbian Router (navigation), Episodic Memory (ship's log), and CodebaseIndex (technical manual).

Each ProbOS instance is a ship. Multiple instances form a [Federation](federation.md). See the [Roadmap](../development/roadmap.md) for the full crew structure and build phases.

## Design Principles

1. **Agents all the way down.** There is no central controller. Every capability is an agent.
2. **Probabilistic over deterministic.** Confidence scores, Bayesian trust, weighted voting.
3. **Self-organizing.** Hebbian learning routes intents to the best agents without configuration.
4. **Self-healing.** Degraded agents are recycled. Pools scale to demand.
5. **Self-modifying.** Capability gaps trigger the design of new agents at runtime.
6. **Transparent.** Every decision can be explained via introspection commands.
