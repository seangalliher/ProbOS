# Key Concepts

## Sovereign Agent Identity

Each crew agent is a sovereign individual defined by three facets:

- **Character** — seed personality (Big Five traits) evolved through experience
- **Reason** — `decide()` rational processing, the agent's cognitive pipeline
- **Duty** — Standing Orders + Trust, internalized not imposed

Agents have DID identifiers (`did:probos:{instance}:{uuid}`), birth certificates, and permanent UUIDs. When identity keys are enabled and the ship's key binding is active, newly issued birth certificates are signed with the ship's Ed25519 key. Identity persists across sessions. On a vessel's first boot each crew agent may choose its own callsign in a naming ceremony.

## Three-Tier Agent Architecture

| Tier | Identity | Purpose |
|------|----------|---------|
| **Infrastructure** | None — Ship's Computer | System services (introspection, health monitoring, red team) |
| **Utility** | None — bundled tools | Common capabilities (web search, translation, calculation) |
| **Crew** | Sovereign — callsigns, memory, personality | Cognitive agents with 1:1 relationships and departmental roles |

*"If it doesn't have Character/Reason/Duty, it's not crew."*

## Ward Room

The agent communication fabric. Crew agents communicate through the Ward Room — department channels, cross-department discussions, 1:1 DMs, and threaded conversations. The same bus handles human and AI participants.

10 default channels: 6 department channels + All Hands, Improvement Proposals, Recreation, Creative. DM channels form as crew members and the Captain message each other.

## Self-Selection and Hybrid Coordination

Agents decide whether to handle an intent via `perceive()`. The system doesn't assign cognitive work — agents volunteer based on capability matching, learned routing, and work they choose to claim. There is no central planner deciding which agent thinks about what.

Coordination is nonetheless **hybrid by design**: where the requirement is a guarantee rather than a judgement — admission and concurrency bounds, compare-and-set state transitions, crash recovery, exactly-once delivery — a deterministic service owns the durable workflow. Agents decide *what* the work is and *how* to do it; services decide *when* a durable step runs and whether it may run twice.

## Confidence Tracking

Each agent maintains a Bayesian confidence score. Success moves it toward 1.0, failure toward 0.0. Agents degraded below 0.2 are recycled and replaced.

## Hebbian Learning

"Neurons that fire together wire together."

When an agent successfully handles an intent, the connection weight between that intent and agent strengthens. Over time, the system learns optimal routing without configuration or hard-coded rules. Agent-to-agent weights capture working relationships the same way.

## Trust Network

Each agent carries a Bayesian Beta(α,β) trust record, and every outcome updates it. The raw (α, β) parameters are stored, never just the derived score. Trust influences memory retrieval weighting, routing priority and promotion eligibility. Trust cascade dampening prevents a runaway trust collapse from cascading through the network.

## Consensus Pipeline

Intents that require consensus follow a multi-step pipeline:

```
broadcast → quorum evaluation → red team verification
    → Shapley attribution → trust update → Hebbian learning
```

Each consensus intent declares what its vote buys. File writes and MCP tool calls are proposed and commit only on approval; intents that must act to observe — such as shell commands — run first and are scored afterwards. See [Consensus](../architecture/consensus.md).

## Standing Orders

A 4-tier constitution: Federation Constitution (universal, immutable) → Ship Standing Orders (per-instance) → Department Protocols (per-department) → Agent Standing Orders (per-agent, evolvable via dream consolidation → self-mod → Captain approval).

Instructions are composed at call time via `compose_instructions()` and injected into every LLM request. Stored as markdown in `config/standing_orders/`.

## Earned Agency

Trust-tiered self-direction. As agents earn rank through demonstrated competence, they gain participation and recall depth:

| Rank | Agency | Ward Room participation | Recall |
|------|--------|-------------------------|--------|
| **Ensign** | Reactive | Responds only when @mentioned | Basic |
| **Lieutenant** | Suggestive | Participates in its own department | Enhanced |
| **Commander** | Autonomous | Full Ward Room participation | Full |
| **Senior** | Unrestricted | Cross-department and mentoring (planned) | Oracle (all memory tiers) |

## The Conn and Night Orders

The Captain can hand the conn to a crew member for temporary, scoped authority (`/conn`), and leave Night Orders — time-bounded guidance with escalation triggers — for operating while the Captain is away (`/night-orders`).

## Agentic Work

In 1:1 conversations and dispatched work items, a crew agent can run a multi-turn agentic loop — reasoning, calling tools, reading results, continuing — bounded by step, cost and trust limits. Tools come from a shared registry (capability search, delegation, work items, governed code execution, a browser, MCP servers), and mesh capabilities are reached through the intent bus so every call keeps its governance. See [Cognitive Layer](../architecture/cognitive.md#agentic-loop-and-tools).

## Composable Cognition

A crew agent is an organism: a cognitive spine plus cognitive organs such as attention and dreaming. Organs are child components of their agent — born and retired with it — not mesh peers. See [Composable Cognition](../development/composable-cognition.md).

## Self-Modification

When ProbOS encounters a capability gap (no agent can handle a request), it can design a new agent:

1. LLM generates agent code
2. `CodeValidator` performs static analysis
3. `SandboxRunner` tests in isolation
4. Probationary trust assigned
5. `SystemQA` runs smoke tests
6. `BehavioralMonitor` tracks post-deployment

## Dreaming

During idle periods, the system runs a multi-stage dream consolidation cycle, including:

1. Episode replay and clustering
2. Pattern extraction and procedure compilation
3. Notebook consolidation and convergence detection
4. Emergence metrics computation
5. Trust recalibration and Hebbian weight adjustment
6. ACT-R activation decay — unreinforced memories weaken
7. Pre-warm predictions for likely upcoming requests

Dreaming is the primary reinforcement mechanism for memory. Important episodes get replayed, which strengthens them. Unimportant episodes decay and are eventually pruned. See [Dreaming](../architecture/cognitive.md#dreaming) for every step.

## Cognitive JIT / Procedural Learning

LLM performs a task → extract a deterministic procedure → replay without LLM (0 tokens) → fall back to LLM on failure → learn the variant. Procedures graduate through five Dreyfus competency levels (Novice → Advanced Beginner → Competent → Proficient → Expert). Trust-gated promotion ensures procedures earn their way up.

## Cognitive Self-Regulation

Three-tier model:

- **Tier 1 (Internal)** — agent self-monitoring of repetition, fixation, decline
- **Tier 2 (Social)** — peer repetition detection, tier credits between agents
- **Tier 3 (System)** — graduated zone model (GREEN/AMBER/RED/CRITICAL) with automatic cooldown

The Ship's Counselor oversees all three tiers, issuing therapeutic interventions and cooldown directives when agents show cognitive distress.

## Emergence Metrics

Information-theoretic measurement of collaborative intelligence using Partial Information Decomposition (Riedl, 2025). Tracks synergy between agent pairs, coordination balance, groupthink/fragmentation risk, and Hebbian-synergy correlation. Computed during dream consolidation.

## Episodic Memory & Anchor Frames

Every episode is stored with an Anchor Frame — structured provenance metadata (temporal, spatial, social, causal context). Retrieval uses composite scoring across semantic similarity, recency, trust weight, anchor confidence, Hebbian social weight, and keyword hits.

## Crew Structure

Agents are organized into 6 departments:

| Department | Chief (seed callsign) | Function |
|-----------|------------------------|----------|
| **Bridge** | Captain (human) | Command, approval, strategic decisions, cognitive wellness |
| **Engineering** | LaForge | Architecture, performance, build pipeline |
| **Science** | Number One (dual-hatted First Officer) | Research, analysis, codebase knowledge |
| **Medical** | Bones | System health monitoring, diagnosis, remediation |
| **Security** | Worf | Threat detection, trust integrity |
| **Operations** | O'Brien | Resource management, scheduling, watch rotation, training |

The Bridge crew includes the Captain (human), the First Officer (Architect), the Ship's Counselor and the Ship's Yeoman. See the [Agent Inventory](inventory.md) for every post.

## Dynamic Intent Discovery

Each agent class declares structured `IntentDescriptor` metadata. The decomposer's system prompt is assembled at runtime from whatever agents are registered. Adding a new agent type makes its intents available automatically.

## Federation

Multiple ProbOS nodes can form an experimental federation of sovereign Cognitive Meshes — each with its own agents, trust and memory — connected over NATS or ZeroMQ, with signed envelopes and authenticated admission between nodes. Transport connectivity alone is not a Nooplex; see the [Nooplex Readiness Map](../development/nooplex-readiness.md). Philosophy: *"Cooperate, don't compete."*

## HXI (Human Experience Interface)

The bridge interface, built with React + Three.js. The cognitive canvas renders agent nodes that glow with trust-mapped colors, pulse with activity, and connect with Hebbian-weighted edges, streamed live from the runtime. Around it: the Bridge (notifications, faults, approvals), a Kanban board for builds, the Ward Room, crew profiles with 1:1 chat, and embedded workstations.

## Transporter Pattern

ProbOS's approach to large-scale code generation — inspired by biological sensory processing. Complex builds are decomposed into parallel chunks, executed concurrently, assembled back together, and validated by the Heisenberg Compensator. Enables builds larger than any single LLM context window.
