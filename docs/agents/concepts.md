# Key Concepts

## Self-Selection

Agents decide whether to handle an intent via `perceive()`. The system doesn't assign work — agents volunteer based on capability matching. This decentralized approach means no single point of failure in task routing.

## Confidence Tracking

Each agent maintains a Bayesian confidence score. Success moves it toward 1.0, failure toward 0.0. Agents degraded below 0.2 are recycled and replaced. This ensures the system maintains quality over time.

## Hebbian Learning

"Neurons that fire together wire together."

When an agent successfully handles an intent, the connection weight between that intent and agent strengthens. Over time, the system learns optimal routing without any configuration or hard-coded rules.

## Consensus Pipeline

Destructive operations follow a multi-step safety pipeline:

```
broadcast → quorum evaluation → red team verification
    → Shapley attribution → trust update → Hebbian learning
```

A single corrupted agent cannot cause damage.

## Self-Modification

When ProbOS encounters a capability gap (no agent can handle a request), it designs a new agent:

1. LLM generates agent code
2. `CodeValidator` performs static analysis
3. `SandboxRunner` tests in isolation
4. Probationary trust assigned
5. `SystemQA` runs smoke tests
6. `BehavioralMonitor` tracks post-deployment

Agents can also be designed collaboratively via `/design`.

## Correction Feedback Loop

Human corrections are the richest learning signal:

1. `CorrectionDetector` identifies when the user is correcting a previous result
2. `AgentPatcher` modifies the responsible agent
3. Hot-reload → auto-retry → trust/Hebbian/episodic updates

## Dreaming

During idle periods, the system replays recent episodes to strengthen successful pathways, weaken failed ones, prune dead connections, adjust trust scores, and pre-warm predictions for likely upcoming requests.

## Dynamic Intent Discovery

Each agent class declares structured `IntentDescriptor` metadata. The decomposer's system prompt is assembled at runtime from whatever agents are registered. Adding a new agent type makes its intents available to the LLM without editing any prompt, configuration, or routing table.

## Standing Orders

ProbOS has its own constitution system — a 4-tier instruction hierarchy: Federation Constitution (universal, immutable) → Ship Standing Orders (per-instance) → Department Protocols (per-department) → Agent Standing Orders (per-agent, evolvable). Instructions are composed at call time via `compose_instructions()` and injected into every LLM request. Standing orders are stored in `config/standing_orders/` as markdown files.

## Crew Structure

Agents aren't a flat pool — they're organized into specialized departments (PoolGroups), like departments on a starship:

| Department | Function |
|-----------|----------|
| **Medical** | System health monitoring, diagnosis, remediation |
| **Engineering** | Code generation, build pipeline, performance |
| **Science** | Architecture, research, codebase analysis |
| **Security** | Threat detection, trust integrity, red team |
| **Operations** | Resource management, scheduling, watch rotation |
| **Communications** | Channel adapters, federation, external interfaces |
| **Bridge** | Strategic decisions, human approval, counselor |

Each department has a Chief (promoted by trust score + Counselor fitness assessment + Captain approval). The Bridge crew includes the Captain (Human), First Officer (ArchitectAgent), and Ship's Counselor (CounselorAgent).

Each agent has a `CrewProfile` with rank (Ensign → Lieutenant → Commander → Senior), Big Five personality traits, and a performance review history.

See the [Roadmap](../development/roadmap.md) for the full crew structure and team build phases.

## Federation

Multiple ProbOS nodes form a **Nooplex** — a cognitive mesh of meshes. Each node is sovereign (its own agents, trust, memory). Nodes exchange capabilities via ZeroMQ gossip protocol and can forward intents across the federation.

## HXI (Human Experience Interface)

A WebGL visualization of the cognitive mesh rendered in React + Three.js. Agent nodes glow with trust-mapped colors, pulse with activity, and connect with Hebbian-weighted edges. Real-time WebSocket streaming from the runtime. Includes Mission Control Kanban dashboard for task lifecycle tracking.

## Transporter Pattern

ProbOS's approach to large-scale code generation — inspired by biological sensory processing. Complex builds are decomposed into parallel chunks (ChunkSpecs), executed concurrently via wave-based scheduling, assembled back together (rematerialized), and validated by the Heisenberg Compensator (interface validator). This enables builds larger than any single LLM context window.
