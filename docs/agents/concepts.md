# Key Concepts

## Sovereign Agent Identity

Each crew agent is a sovereign individual defined by three facets:

- **Character** — seed personality (Big Five traits) evolved through experience
- **Reason** — `decide()` rational processing, the agent's cognitive pipeline
- **Duty** — Standing Orders + Trust, internalized not imposed

Agents have W3C DID identifiers (`did:probos:{instance}:{uuid}`), birth certificates (Verifiable Credentials), and permanent UUIDs. Identity persists across sessions.

## Three-Tier Agent Architecture

| Tier | Identity | Purpose |
|------|----------|---------|
| **Infrastructure** | None — Ship's Computer | System services (introspection, health monitoring, red team) |
| **Utility** | None — bundled tools | Common capabilities (web search, translation, calculation) |
| **Crew** | Sovereign — callsigns, memory, personality | Cognitive agents with 1:1 relationships and departmental roles |

*"If it doesn't have Character/Reason/Duty, it's not crew."*

## Ward Room

The agent communication fabric. All crew agents communicate through the Ward Room — department channels, cross-department discussions, 1:1 DMs, and threaded conversations. The same bus handles human and AI participants.

10 default channels: 6 department channels + All Hands, Improvement Proposals, Recreation, Creative. DM channels form dynamically as agents build working relationships.

## Self-Selection

Agents decide whether to handle an intent via `perceive()`. The system doesn't assign work — agents volunteer based on capability matching. This decentralized approach means no single point of failure in task routing.

## Confidence Tracking

Each agent maintains a Bayesian confidence score. Success moves it toward 1.0, failure toward 0.0. Agents degraded below 0.2 are recycled and replaced.

## Hebbian Learning

"Neurons that fire together wire together."

When an agent successfully handles an intent, the connection weight between that intent and agent strengthens. Over time, the system learns optimal routing without configuration or hard-coded rules.

## Trust Network

Bayesian Beta(α,β) trust scores between all agent pairs. Every interaction updates bilateral trust. Trust scores influence memory retrieval weighting, routing priority, and promotion eligibility. Trust cascade dampening prevents runaway trust collapse from cascading through the network.

## Consensus Pipeline

Destructive operations follow a multi-step safety pipeline:

```
broadcast → quorum evaluation → red team verification
    → Shapley attribution → trust update → Hebbian learning
```

A single corrupted agent cannot cause damage.

## Standing Orders

A 4-tier constitution: Federation Constitution (universal, immutable) → Ship Standing Orders (per-instance) → Department Protocols (per-department) → Agent Standing Orders (per-agent, evolvable via dream consolidation → self-mod → Captain approval).

Instructions are composed at call time via `compose_instructions()` and injected into every LLM request. Stored as markdown in `config/standing_orders/`.

## Earned Agency

Trust-tiered self-direction. As agents accumulate trust, they earn increasing autonomy:

- **Ensign** — task execution only
- **Lieutenant** — can propose improvements
- **Commander** — can initiate cross-department collaboration
- **Senior** — can modify own standing orders (with Captain approval)

## Self-Modification

When ProbOS encounters a capability gap (no agent can handle a request), it designs a new agent:

1. LLM generates agent code
2. `CodeValidator` performs static analysis
3. `SandboxRunner` tests in isolation
4. Probationary trust assigned
5. `SystemQA` runs smoke tests
6. `BehavioralMonitor` tracks post-deployment

## Dreaming

During idle periods, the system runs a 12-step dream consolidation cycle:

1. Episode replay and clustering
2. Pattern extraction and procedure compilation
3. Notebook consolidation and convergence detection
4. Emergence metrics computation
5. Trust recalibration and Hebbian weight adjustment
6. ACT-R activation decay — unreinforced memories weaken
7. Pre-warm predictions for likely upcoming requests

Dreaming is the primary reinforcement mechanism for memory. Important episodes get replayed, which strengthens them. Unimportant episodes decay and are eventually pruned.

## Cognitive JIT / Procedural Learning

LLM performs a task → extract a deterministic procedure → replay without LLM (0 tokens) → fall back to LLM on failure → learn the variant. Procedures graduate through five Dreyfus competency levels (Novice → Advanced Beginner → Competent → Proficient → Expert). Trust-gated promotion ensures procedures earn their way up.

## Cognitive Self-Regulation

Three-tier model:

- **Tier 1 (Internal)** — agent self-monitoring of repetition, fixation, decline
- **Tier 2 (Social)** — peer repetition detection, tier credits between agents
- **Tier 3 (System)** — graduated zone model (GREEN/AMBER/RED/CRITICAL) with automatic cooldown

The Counselor (Echo) oversees all three tiers, issuing therapeutic interventions and cooldown directives when agents show cognitive distress.

## Emergence Metrics

Information-theoretic measurement of collaborative intelligence using Partial Information Decomposition (Riedl, 2025). Tracks synergy between agent pairs, coordination balance, groupthink/fragmentation risk, and Hebbian-synergy correlation. Computed during dream consolidation.

## Episodic Memory & Anchor Frames

Every episode is stored with an Anchor Frame — structured provenance metadata (temporal, spatial, social, causal context). Retrieval uses 6-factor composite scoring: semantic similarity, recency, trust weight, anchor confidence, Hebbian social weight, and keyword hits.

## Crew Structure

Agents are organized into 6 departments:

| Department | Chief | Function |
|-----------|-------|----------|
| **Medical** | Bones | System health monitoring, diagnosis, remediation |
| **Engineering** | LaForge | Code generation, build pipeline, performance |
| **Science** | Number One | Architecture, research, codebase analysis |
| **Security** | Worf | Threat detection, trust integrity |
| **Operations** | O'Brien | Resource management, scheduling, watch rotation |
| **Bridge** | — | Strategic decisions, human approval, counselor |

The Bridge crew includes the Captain (Human), First Officer Meridian (ArchitectAgent), and Ship's Counselor Echo (CounselorAgent).

## Dynamic Intent Discovery

Each agent class declares structured `IntentDescriptor` metadata. The decomposer's system prompt is assembled at runtime from whatever agents are registered. Adding a new agent type makes its intents available automatically.

## Federation

Multiple ProbOS nodes form a **Nooplex** — a cognitive mesh of meshes. Each node is sovereign (its own agents, trust, memory). Nodes exchange capabilities via ZeroMQ gossip protocol. Philosophy: *"Cooperate, don't compete."*

## HXI (Human Experience Interface)

A WebGL visualization of the cognitive mesh rendered in React + Three.js. Agent nodes glow with trust-mapped colors, pulse with activity, and connect with Hebbian-weighted edges. Real-time WebSocket streaming from the runtime. Includes Mission Control Kanban dashboard.

## Transporter Pattern

ProbOS's approach to large-scale code generation — inspired by biological sensory processing. Complex builds are decomposed into parallel chunks, executed concurrently, assembled back together, and validated by the Heisenberg Compensator. Enables builds larger than any single LLM context window.
