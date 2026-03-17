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

## Crew Structure

Agents aren't a flat pool — they're organized into specialized teams, like departments on a starship. Each team is a dedicated agent pool with distinct responsibilities: Medical monitors and heals the system, Engineering optimizes performance, Security detects threats, Operations manages resources, Communications handles external channels, Science drives research, and the Bridge coordinates strategy with human approval.

Each ProbOS instance is a ship. Multiple instances form a federation (see below). The [Roadmap](../development/roadmap.md) describes the full crew structure and team build phases.

## Federation

Multiple ProbOS nodes form a **Nooplex** — a cognitive mesh of meshes. Each node is sovereign (its own agents, trust, memory). Nodes exchange capabilities via ZeroMQ gossip protocol and can forward intents across the federation.

## HXI (Human Experience Interface)

A WebGL visualization of the cognitive mesh rendered in Three.js. Agent nodes glow with trust-mapped colors, pulse with activity, and connect with Hebbian-weighted edges. Real-time WebSocket streaming from the runtime.
