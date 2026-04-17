# AD-641: Ship's Computer / Crew Integration — Brain Enhancement Phase

**Type:** Architecture Decision (research + decomposition AD)  
**Priority:** Medium (foundational, informs future phases)  
**Status:** Design  

## Context

ProbOS has two execution paths that evolved independently:

1. **Intent Bus path** (the Brain) — Shell → decompose → DAG → intent bus → tool agents → consensus → Hebbian update. Built in Phases 1-21.
2. **Ward Room path** (the Crew) — Captain/agent → Ward Room → routing → cognitive chain → reply. Built in Phases 33+.

These run in parallel with almost zero integration. The survey confirms:

| Ship's Computer Service | Crew Integration |
|---|---|
| TrustNetwork | Indirect only (injected `_trust_score`) |
| Hebbian Routing | None |
| Attention Manager | None |
| Workflow Cache | None |
| Consensus/Quorum | None |
| Gossip Protocol | None |
| VitalsMonitor | None |
| IntentBus | Yes (message delivery only) |

The Brain was built, then we moved into the house and started decorating. The decorating was transformative (crew identity, communication, collaborative intelligence), but the brain hasn't evolved alongside the crew that inhabits it.

## Design Principle: Enterprise Coupling Model

Crew are **loosely coupled** to the Ship's Computer. They observe, use, and improve the ship's systems — but they are not components of them.

- If all crew beam off, the ship keeps running (Ship's Computer maintains itself)
- If a crew agent transfers to a new ship, they function there (DID mobility, no dependency on Ship A's brain)
- Crew READ brain state, BENEFIT FROM brain learning, PARTICIPATE IN brain decisions — but the brain works without them

**Litmus tests:**
1. Can this ProbOS instance function with zero crew aboard?
2. Can a crew agent transfer to another instance and still function?
3. If this brain subsystem goes down, do crew agents crash or just lose a capability?

## Integration Categories

### Category A: Shared Systems (one instance, multiple consumers)

Systems where it makes architectural sense for both Ship's Computer and crew to use the **same instance**. These are already shared or naturally should be.

| System | Current State | Enhancement |
|---|---|---|
| **TrustNetwork** | Shared — tracks both tool-agent reliability and crew reputation | Already correct. Crew endorsements (`[ENDORSE UP/DOWN]`) feed trust via `record_outcome()`. No change needed. |
| **Episodic Memory** | Shared infrastructure, sovereign shards | Already correct. Each agent has their own shard. Ship's Computer writes system events. |
| **Ship's Records** | Shared — agent notebooks, duty logs, Captain's Log | Already correct. Both infrastructure agents and crew write to it. |
| **IntentBus** | Shared — delivers messages to both tool agents and crew | Already correct. Ward Room notifications route through intent bus. |
| **Event System** | Shared — both tiers emit and subscribe to events | Already correct. |

**No work needed.** The shared systems are already properly shared.

### Category B: Brain Systems → Crew Observability (read-only exposure)

Systems where crew agents should be able to **observe** the brain's state to make better decisions — but NOT modify the brain's internals. The ship has sensors; crew read the sensors.

| Brain System | What Crew Would Observe | Why |
|---|---|---|
| **VitalsMonitor** | System health, resource usage, agent pool status | Crew (esp. Engineering, Medical Chiefs) should see when the ship is stressed. Today VitalsMonitor has zero crew-facing exposure. |
| **Attention Manager** | Current priority queue, what the brain thinks is urgent | Chiefs and Bridge could use this to understand what the system is focused on. Informs Captain decisions. |
| **Hebbian Weights** | Which intent→agent pairings are strongest | Engineering and Operations could observe routing efficiency. "The brain is routing shell commands to Agent-3 most often." |
| **Pool Health** | Which pools are degraded, scaling events | Engineering should know when infrastructure is unhealthy. |

**Implementation:** Expose read-only APIs or Ward Room system-channel feeds. NOT direct imports. Crew agents query a service endpoint or subscribe to a system channel, same way they'd read a sensor display on the bridge.

### Category C: Parallel Systems (same concept, separate implementations)

Systems where both the brain and crew need the **same kind of capability**, but tuned for different domains. Forcing them into one system creates coupling. Better to share the concept but keep the implementations independent.

| Concept | Brain Implementation | Crew Implementation | Why Separate |
|---|---|---|---|
| **Learned Routing** | Hebbian Router (intent bus): learns which tool agents handle which intents best | Ward Room Router: could learn which crew contribute best to which discussion topics | Different optimization targets. Brain optimizes for task completion reliability. Crew optimizes for discussion quality and collaborative intelligence. Same math (connection strengthening), different domains. |
| **Priority Scoring** | Attention Manager: scores DAG tasks by urgency × relevance × deadline | Ward Room could score thread importance: Captain involvement, cross-department, unresolved questions | Different inputs, different signals. Brain sees tasks. Crew see conversations. Merging them would create a confused priority system that's neither good at tasks nor conversations. |
| **Pattern Caching** | Workflow Cache: LRU cache of user-input → TaskDAG mappings (bypass LLM on repeat queries) | Cognitive JIT: procedure extraction from successful task execution (replay without LLM) | Different lifecycle. Workflow cache is session-scoped shortcuts. Cognitive JIT is permanent learned procedures. Both are "learned shortcuts" but at different timescales and abstraction levels. Could share a common storage abstraction without merging logic. |
| **Collective Decision** | Consensus/Quorum: confidence-weighted voting among tool agents for destructive operations | Ward Room Deliberation: crew discussion + endorsement for strategic decisions | Different authority models. Consensus is mechanical safety (does this operation look correct?). Crew deliberation is judgment (should we do this at all?). Both are collective decision-making but at different levels of abstraction. |

**Implementation:** Keep separate. Potentially share abstract interfaces or storage backends (e.g., both Hebbian systems could use the same SQLite schema pattern). Document the parallel structure so future developers understand why there are "two of everything."

### Category D: Brain-Only Systems (no crew integration needed)

Systems that are purely Ship's Computer internals. Crew don't need visibility and shouldn't have coupling.

| System | Why Brain-Only |
|---|---|
| Agent Lifecycle (spawner, pools, heartbeat) | Infrastructure plumbing. Crew don't need to know how agents are spawned. |
| Gossip Protocol | Agent-to-agent state exchange. Internal nervous system signaling. |
| Adaptive Pool Scaling | Demand-based sizing decisions. Infrastructure automation. |
| Capability Registry | Fuzzy matching for intent routing. Internal to the intent bus path. |
| Event Log | Append-only audit trail. Infrastructure observability. |

**Exception:** Engineering Chief (LaForge) may eventually need observability into Category D systems as part of the Chief Moderation / Ship's Engineer role. This would be Category B (read-only) exposure, not Category C or integration.

## Data Flow: How the Two Paths Connect

```
┌──────────────────────────────────────────────────┐
│                 SHARED FABRIC                     │
│  TrustNetwork · Episodic Memory · Ship's Records  │
│  IntentBus · Event System                         │
└────────────┬──────────────────────┬───────────────┘
             │                      │
    ┌────────▼────────┐    ┌───────▼─────────┐
    │   BRAIN PATH     │    │   CREW PATH      │
    │                  │    │                  │
    │  Attention Mgr   │    │  Ward Room Router │
    │  Workflow Cache   │    │  Cognitive JIT    │
    │  Hebbian Router   │    │  WR Hebbian (new) │
    │  Consensus/Quorum │    │  WR Deliberation  │
    │  Gossip Protocol  │    │  Comm Proficiency  │
    │  Pool Scaling     │    │  Self-Regulation   │
    │                  │    │                  │
    │  ┌──────────┐    │    │  ┌──────────┐    │
    │  │Tool Agents│    │    │  │Crew Agents│    │
    │  └──────────┘    │    │  └──────────┘    │
    └──────────────────┘    └──────────────────┘
             │                      │
             ▼                      ▼
    ┌──────────────────────────────────────────┐
    │         OBSERVABILITY BRIDGE              │
    │  VitalsMonitor → System Channel (WR)     │
    │  Attention Priorities → Bridge Display    │
    │  Pool Health → Engineering Channel        │
    │  Hebbian Weights → Ops Channel            │
    └──────────────────────────────────────────┘
```

The Observability Bridge is the key new component — it translates brain state into crew-readable Ward Room feeds without creating dependencies in either direction.

## Decomposition (Sub-ADs)

This is a research and design AD. Implementation would decompose into:

| Sub-AD | Scope | Category |
|---|---|---|
| AD-641a | **Observability Bridge** — System channel(s) in Ward Room that surface brain state (VitalsMonitor, pool health, attention priorities). Read-only. Push-based (brain publishes, crew subscribe). | B |
| AD-641b | **Ward Room Hebbian Learning** — Parallel Hebbian system for Ward Room routing. Learns which crew contribute best to which topic/channel types. Same math as mesh Hebbian, separate instance and storage. Informs routing priority, not hard gates. | C |
| AD-641c | **Ward Room Thread Priority** — Thread importance scoring parallel to Attention Manager. Factors: Captain involvement, unresolved questions, cross-department threads, thread age, endorsement density. Surfaces as thread priority in HXI. | C |
| AD-641d | **Crew Deliberation Protocol** — Structured crew discussion for strategic decisions (not mechanical consensus). Captain or Chief initiates deliberation thread, crew contribute arguments, endorsements signal agreement, Captain resolves. Ward Room native, not consensus layer. | C |
| AD-641e | **Cognitive JIT ↔ Workflow Cache Shared Abstraction** — Common storage/retrieval interface for both "learned shortcuts" systems. Neither merges into the other. Shared query patterns, separate stores. | C |
| AD-641f | **Engineering Chief Ship's Systems Observability** — LaForge-specific: read access to Category D internals (pool scaling events, gossip state, capability registry). Chief Moderation prerequisite. | B+D |
| AD-641g | **Asynchronous Cognitive Pipeline via NATS** — Decouple chain steps (QUERY→ANALYZE→COMPOSE) via NATS subjects. QUERY browses channels/sources at high frequency (0 LLM), publishes to analyze queue. ANALYZE picks up selectively. Source-agnostic: same pattern extends to documents, web research, ship's state. Depends on AD-637. [Design doc](ad-641g-async-cognitive-pipeline.md) | C |

## Principles

- **Loose coupling:** Crew observe and use brain services, never become components of them
- **No new dependencies:** Brain works without crew. Crew work without brain enhancements.
- **Parallel over merged:** When both paths need the same concept, build two tuned implementations over one compromise
- **Observability over integration:** Prefer exposing brain state as readable data (Ward Room feeds, API endpoints) over giving crew direct access to brain internals
- **Society of Mind:** Core agents are neurons. Crew are minds. The Observability Bridge is the interface between nervous system and consciousness.

## Connection to Prior Work

- **Chief Channel Moderation** (future AD) — Chiefs need observability (AD-641a/f) before they can effectively moderate
- **Cognitive JIT** (AD-531-539) — AD-641e bridges JIT and Workflow Cache
- **NATS Event Bus** (AD-637) — NATS could be the transport for the Observability Bridge and the async cognitive pipeline (AD-641g)
- **Emergent Leadership** — Wesley/Lyra coordination shows crew already self-organize; brain observability gives them data to organize around
