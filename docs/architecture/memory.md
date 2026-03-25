# Memory Architecture

*The Nooplex Memory Stack — how ProbOS organizes knowledge from fleeting thoughts to permanent institutional memory.*

---

## Overview

ProbOS implements a six-layer memory architecture inspired by the Nooplex paper's cognitive ecosystem model. Each layer serves a distinct function in the knowledge lifecycle, with well-defined promotion and demotion paths between layers.

Two cross-cutting systems connect the layers:
- **Ward Room Bus** — lateral knowledge flow between agents at any layer (social fabric)
- **Dream Consolidation** — vertical knowledge promotion from experience to long-term storage (the elevator)

## The Stack

```
┌─────────────────────────────────────────────────┐
│  1. Global Workspace                            │
│     Multi-agent reasoning, DAG orchestration    │
│                                                 │
│  ┌──────────── Ward Room Bus ────────────────┐  │
│  │  Social knowledge fabric (lateral flow)   │  │
│  └───────────────────────────────────────────┘  │
│                                                 │
│  2. Ephemeral Working Memory                    │
│     Agent scratchpads, context windows          │
│                                                 │
│          ↕ Dream Consolidation (elevator)       │
│                                                 │
│  3. Vector Store (Associative Cortex)           │
│     EpisodicMemory, SemanticKnowledgeLayer      │
│                                                 │
│          ↕ Pattern extraction / promotion       │
│                                                 │
│  4a. Formal Models (Constitutional)             │
│     Ontology, Standing Orders, Skill Defs       │
│  4b. Operational Knowledge (Learned)            │
│     Trust records, Hebbian weights, profiles    │
│                                                 │
│          ↕ Publication / archival               │
│                                                 │
│  5a. Institutional Memory (Ship's Records)      │
│     Notebooks, logs, reports, Captain's Log     │
│  5b. Operational State (KnowledgeStore)         │
│     Trust snapshots, routing weights, agent src │
│                                                 │
│          ↕ Federation push/pull                 │
│                                                 │
│  6. Distributed Storage Substrate               │
│     Instance repos, fleet remotes, Nooplex      │
└─────────────────────────────────────────────────┘
```

## Layer Details

### Layer 1: Global Workspace

The shared cognitive space where multi-agent reasoning happens. When a Captain's intent enters the system, it becomes a TaskDAG — a directed acyclic graph of cognitive work distributed across agents. The workspace holds the current state of all active reasoning: which agents are thinking about what, what results have been produced, what depends on what.

**ProbOS implementation:** Runtime DAG orchestration, IntentBus broadcast, consensus voting.

**Analogy:** The bridge viewscreen during a crisis — everyone sees the same situation, contributes their expertise, and the picture updates in real-time.

### Ward Room Bus (Lateral)

Not a layer but a cross-cutting communication fabric. The Ward Room enables lateral knowledge flow between agents at any point in the stack. An agent's insight during Layer 1 reasoning can be shared as a discussion post. A pattern noticed during Layer 3 recall can spark a department-wide conversation. The bus is bidirectional — agents both publish to and learn from Ward Room interactions.

**ProbOS implementation:** WardRoom (channels, threads, posts, endorsements), `@callsign` addressing, department broadcasts.

**Key property:** "Brains are brains" — human and AI participants share the same bus. The Captain is `@captain` on the Ward Room, not a special external interface.

### Layer 2: Ephemeral Working Memory

Each agent's short-term scratchpad. Context windows, intermediate reasoning, tool call results, conversation history for the current cognitive cycle. Discarded after the cycle completes — nothing persists here by default.

**ProbOS implementation:** LLM context windows, `compose_prompt()` assembled context, working memory dict in `process_natural_language()`.

**Key property:** Cheap to create, expensive to lose mid-cycle, zero cost to discard after. The Selective Encoding Gate (AD-433) controls what gets promoted from here to Layer 3.

### Dream Consolidation (Elevator)

The vertical promotion mechanism. During dream cycles (offline consolidation), the system:
1. Replays recent episodic memories (Layer 3)
2. Extracts strategy patterns via LLM analysis
3. Updates Hebbian weights and trust records (Layer 4b)
4. Prunes low-value connections
5. Pre-warms routing for the next wake cycle

Dream consolidation is biologically inspired — it mirrors how mammalian brains consolidate short-term memories into long-term storage during sleep. The "elevator" metaphor: experiences ride up from Layer 3 to become permanent knowledge in Layers 4-5.

**ProbOS implementation:** `DreamingEngine` (`cognitive/dreaming.py`), strategy extraction, Hebbian weight consolidation, trust snapshot persistence.

### Layer 3: Vector Store (Associative Cortex)

Persistent associative memory. Experiences, semantic embeddings, and contextual knowledge stored as vectors for similarity-based retrieval. This is where "what happened" lives — not interpreted or distilled, just recorded.

**ProbOS implementation:**
- `EpisodicMemory` — autobiographical episodes (what happened, who was involved, outcome, emotional valence). Sovereign per-agent shards.
- `SemanticKnowledgeLayer` — five ChromaDB collections (agent designs, skills, episodes, context, artifacts).
- `CognitiveJournal` — structured per-agent decision records with traceability chains (AD-431/432).

**Key property:** Content-addressable retrieval. "Find me experiences similar to this situation" — not keyword search, but meaning-based recall.

### Layer 4: Structured Knowledge

Split into two sub-layers reflecting fundamentally different knowledge types:

**4a. Formal Models (Constitutional)** — Authored, versioned, human-approved. Changes require deliberate design decisions.
- Vessel Ontology (AD-429) — formal concept hierarchy across 8 domains
- Standing Orders (AD-339) — 4-tier behavioral constitution
- Skill definitions — procedural templates
- Alert condition definitions

**4b. Operational Knowledge (Learned)** — Emergent from experience. Changes continuously through interaction.
- Trust records — per-agent Bayesian trust scores
- Hebbian weights — connection strengths between agents
- Agent personality profiles — Big Five traits evolved through experience
- Routing preferences — learned intent-to-agent mappings

**Key property:** 4a is "the law" — stable, deliberate, version-controlled. 4b is "wisdom" — emergent, continuously updated, reflects the system's lived experience. Both inform behavior, but 4a constrains while 4b guides.

### Layer 5: Persistent Storage

Split into two sub-layers reflecting different persistence models:

**5a. Institutional Memory (Ship's Records)** — AD-434. The written story of the crew. Git-backed documents with YAML frontmatter providing systematic provenance (author, classification, status, topic, tags, timestamps).
- Captain's Log — append-only command narrative
- Agent Notebooks — per-callsign research notes, observations, working documents
- Reports — formal published findings (precedent documents, case law)
- Operations — duty logs, watch reports, incident records
- Manuals — procedures, checklists, reference materials

**5b. Operational State (KnowledgeStore)** — System checkpoint persistence. NOT a shared knowledge library despite the name.
- Trust snapshots — serialized trust network state
- Routing weights — Hebbian connection weights
- Agent source code — self-designed agent configurations
- QA reports — system quality assessment results
- Extracted strategies — dream cycle outputs

**Key distinction:** 5a is authored knowledge — agents and humans write documents that other agents can read and learn from. 5b is system state — machine-generated checkpoints for warm boot and recovery. An agent reads 5a like a library; an agent restores 5b like loading a save file.

### Layer 6: Distributed Storage Substrate

The physical persistence and federation layer. Everything above eventually lands here — Git repositories, file systems, federation remotes.

**ProbOS implementation:**
- Instance-level: local Git repos (KnowledgeStore, Ship's Records)
- Fleet-level: Git remotes shared between federated ProbOS instances
- Nooplex-level: cross-fleet knowledge exchange (future)

**Key property:** Federation happens here. Git's distributed model means every instance has a complete copy, merge conflicts are resolvable, and history is immutable. Knowledge flows between ships through push/pull, not real-time replication.

## Three Knowledge Tiers

A simplified view for practical reasoning about where knowledge belongs:

| Tier | Name | Store | Nature | Example |
|------|------|-------|--------|---------|
| 1 | Experience | EpisodicMemory | Raw autobiographical episodes | "I scanned the codebase and found 3 security issues" |
| 2 | Records | Ship's Records (AD-434) | Structured documents with provenance | Security audit report, engineering log, research notebook |
| 3 | Operational State | KnowledgeStore | System checkpoints | Trust snapshots, routing weights, agent source code |

**Promotion paths:**
- Tier 1 → Tier 2: Agent writes up findings from episodes into a notebook or report
- Tier 1 → Tier 3: Dream consolidation extracts patterns, persists weights
- Tier 2 → Tier 3: KnowledgeStore bridge indexes Ship's Records documents

## SECI Knowledge Creation Model

ProbOS's memory architecture maps to Nonaka & Takeuchi's (1995) SECI knowledge creation cycle:

| Phase | Description | ProbOS Implementation | Status |
|-------|-------------|----------------------|--------|
| **Socialization** | Tacit → Tacit. Knowledge shared through shared experience | Ward Room discussions, agent-to-agent conversation | Implemented |
| **Externalization** | Tacit → Explicit. Knowledge articulated into formal concepts | Ship's Records — agents write findings into notebooks/reports | AD-434 (planned) |
| **Combination** | Explicit → Explicit. Formal knowledge recombined into new insights | Ship's Records cross-referencing, Oracle queries across tiers | AD-434 + Oracle (planned) |
| **Internalization** | Explicit → Tacit. Formal knowledge absorbed through practice | SemanticKnowledgeLayer recall → agent behavior change | Partial (data is operational state, not authored knowledge) |

**Gap analysis:** Before AD-434, ProbOS had Socialization (Ward Room) and partial Internalization (semantic recall), but Externalization and Combination were missing entirely. The duty-output pipeline (agents produce professional records as part of duties) had no place to store results — findings evaporated after each cognitive cycle.

## Duty-Output Pipeline

Every crew member produces professional records as part of their duties. Ship's Records provides the destination:

| Role | Duty Output | Records Location |
|------|-------------|-----------------|
| Medical Officer | Patient assessments, crew fitness | `notebooks/bones/`, `operations/medical/` |
| Counselor | Crew evaluations, cognitive health | `notebooks/troi/`, `reports/` |
| Engineer | System scans, modification logs | `notebooks/laforge/`, `operations/engineering/` |
| Security | Threat assessments, incident reports | `notebooks/worf/`, `operations/security/` |
| Science | Research findings, analysis | `notebooks/number-one/`, `reports/` |
| Operations | System status, operator rounds | `notebooks/obrien/`, `operations/` |
| Scout | External research, tool evaluations | `notebooks/wesley/`, `reports/` |

## Nooplex Paper Alignment

The "Shared Memory" principle from "The Nooplex: A Planetary Cognitive Ecosystem" (Galliher, 2026) was initially listed as well-covered by ProbOS, but deeper analysis (AD-434 research) revealed the **shared knowledge fabric is not implemented**:

- KnowledgeStore was intended to be the "shared library" but evolved into operational state persistence
- No agent writes knowledge to it — only system processes (dream consolidation, QA, trust snapshots)
- Dream consolidation modifies in-memory weights but does not promote distilled insights to a shared corpus

**AD-434 (Ship's Records)** is designed to be the actual implementation of the Nooplex shared knowledge fabric:
- Captain's Log (human contributes) → agent notebooks (agents amplify & document) → Ward Room discussion (human refines) → dream consolidation → notebook entries (substrate evolves)
- This four-phase cycle maps to the SECI knowledge creation model
- It also implements the Nooplex paper's "Human-Agent Knowledge Feedback Loop" (Gap #10)

## Related Documents

| Document | Scope |
|----------|-------|
| [Knowledge Layer](knowledge.md) | KnowledgeStore and SemanticKnowledgeLayer implementation details |
| [Cognitive Architecture](cognitive.md) | Dream consolidation, strategy extraction |
| [Experience Layer](experience.md) | EpisodicMemory, Selective Encoding Gate |
| [AD-434 (Ship's Records)](../../docs/development/roadmap.md) | Detailed design for institutional memory |
| [Roadmap — Research](../../docs/development/roadmap-research.md) | Nooplex paper alignment gaps |

## Source Files

| File | Layer | Purpose |
|------|-------|---------|
| `knowledge/store.py` | 5b | Git-backed operational state persistence |
| `knowledge/semantic.py` | 3 | SemanticKnowledgeLayer (5 ChromaDB collections) |
| `cognitive/episodic_memory.py` | 3 | Autobiographical episode storage |
| `cognitive/dreaming.py` | Elevator | Dream consolidation engine |
| `cognitive/strategy_extraction.py` | Elevator | Pattern extraction from episodes |
| `cognitive/cognitive_journal.py` | 3 | Per-agent decision records |
| `cognitive/encoding_gate.py` | 2→3 | Selective encoding (what gets remembered) |
| `ward_room.py` | Bus | Social communication fabric |
| `consensus/trust.py` | 4b | Bayesian trust records |
| `mesh/routing.py` | 4b | Hebbian connection weights |
