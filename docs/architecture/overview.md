# Architecture Overview

ProbOS is built as seven layers, each built on the one below, plus two cross-cutting concerns:

```mermaid
block-beta
    columns 1
    Experience["Experience\nCLI shell (42 commands) · HXI (WebGL) · FastAPI + WebSocket · Rich panels"]
    Cognitive["Cognitive\nLLM decomposer · working memory · episodic memory · attention\ndreaming (12 steps) · self-modification · Cognitive JIT · self-regulation\nbuilder · architect · counselor · standing orders · emergence metrics"]
    Consensus["Consensus\nQuorum voting · trust network · Shapley attribution · escalation\ntrust cascade dampening"]
    Mesh["Mesh\nIntent bus · Hebbian routing · gossip protocol · capability registry\nWard Room (agent communication fabric)"]
    Substrate["Substrate\nAgent lifecycle · pools · pool groups · spawner · registry · heartbeat\nW3C DID identity · birth certificates · event log"]
    space
    Federation["Federation (cross-cutting)\nZeroMQ transport · node bridge · intent router · gossip exchange\nIdentity Ledger · agent mobility"]
    Knowledge["Knowledge (cross-cutting)\nKnowledgeStore (operational state) · Ship's Records (agent notebooks)\nEpisodic Memory (anchored episodes) · ChromaDB semantic search"]

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
| [**Cognitive**](cognitive.md) | Intelligence — NL understanding, memory, learning, self-modification, procedural learning |
| [**Experience**](experience.md) | Interface — shell, visualization, API |
| [**Memory**](memory.md) | Episodic memory — anchored episodes, salience-weighted recall, dream consolidation |
| [**Federation**](federation.md) | Scale — multi-node mesh of meshes, DID identity |
| [**Knowledge**](knowledge.md) | Persistence — operational state, Ship's Records, semantic search |

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

Agents are organized into 6 departments (PoolGroups), analogous to departments on a starship:

| Department | Chief | Function | Key Agents |
|------------|-------|----------|------------|
| **Medical** | Bones | Health monitoring, diagnosis, remediation | Diagnostician, VitalsMonitor, Surgeon, Pharmacist, Pathologist |
| **Engineering** | LaForge | System architecture, code generation, build pipeline | EngineeringAgent, BuilderAgent, CodeReviewAgent |
| **Science** | Number One | Research, analysis, codebase knowledge | DataAnalyst (Kira), SystemsAnalyst (Lynx), ResearchSpecialist (Atlas), Scout (Horizon) |
| **Security** | Worf | Threat detection, trust integrity | SecurityAgent |
| **Operations** | O'Brien | Resource management, scheduling, watch rotation | OperationsAgent |
| **Bridge** | — | Strategic decisions, human approval, cognitive wellness | Captain (Human), Architect (Meridian), Counselor (Echo) |

Agents communicate through the **Ward Room** — department channels, cross-department threads, 1:1 DMs, and All Hands broadcasts.

The **Ship's Computer** provides shared infrastructure: Intent Bus (intercom), Trust Network (crew records), Hebbian Router (navigation), Episodic Memory (ship's log), Ward Room (communication fabric), CodebaseIndex (technical manual), Standing Orders (constitution), Structural Integrity Field (invariant enforcement), KnowledgeStore (operational state), Ship's Records (agent notebooks, duty logs, Captain's Log).

Each ProbOS instance is a ship. Multiple instances form a [Federation](federation.md). See the [Roadmap](../development/roadmap.md) for the full crew structure and build phases.

## Design Principles

1. **Agents all the way down.** There is no central controller. Every capability is an agent.
2. **Probabilistic over deterministic.** Confidence scores, Bayesian trust, weighted voting.
3. **Self-organizing.** Hebbian learning routes intents to the best agents without configuration.
4. **Self-healing.** Degraded agents are recycled. Pools scale to demand.
5. **Self-modifying.** Capability gaps trigger the design of new agents at runtime.
6. **Transparent.** Every decision can be explained via introspection commands.
