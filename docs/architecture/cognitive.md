# Cognitive Layer

The Cognitive layer is the intelligence center — it handles natural language understanding, memory, learning, self-modification, procedural learning, self-regulation, and the builder/architect pipeline.

## Pipeline

Natural language goes through:

1. **Working memory** assembles system state (agent health, trust scores, Hebbian weights, capabilities) within a token budget
2. **Episodic recall** finds similar past interactions for context (6-factor composite scoring)
3. **Workflow cache** checks for previously successful DAG patterns (exact match, then fuzzy)
4. **LLM decomposer** converts text into a `TaskDAG` — a directed acyclic graph of typed intents with dependencies
5. **Attention manager** scores tasks: `urgency x relevance x deadline_factor x dependency_bonus`
6. **DAG executor** runs independent intents in parallel, respects dependency ordering

## Dynamic Intent Discovery

Each agent class declares structured `IntentDescriptor` metadata. The decomposer's system prompt is assembled at runtime from whatever agents are registered. New agent types self-integrate without any configuration changes.

## Standing Orders

A 4-tier instruction hierarchy composed at call time:

1. **Federation Constitution** — universal, immutable rules
2. **Ship Standing Orders** — per-instance configuration
3. **Department Protocols** — per-department standards
4. **Agent Standing Orders** — per-agent, evolvable through self-mod

`compose_instructions()` assembles the complete system prompt for each `CognitiveAgent.decide()` call.

## Self-Modification

When ProbOS encounters a capability gap (no agent can handle a request), it designs a new agent:

```
Capability gap detected
    → LLM generates agent code
    → CodeValidator static analysis
    → SandboxRunner isolation test
    → Probationary trust assigned
    → SystemQA smoke tests
    → BehavioralMonitor tracks post-deployment
```

## Builder Pipeline (Transporter Pattern)

Complex builds are decomposed into parallel chunks for concurrent execution:

```
BuildSpec → BuildBlueprint → ChunkDecomposer (Dematerializer)
    → Parallel Chunk Execution (Matter Stream)
    → ChunkAssembler (Rematerializer)
    → InterfaceValidator (Heisenberg Compensator)
    → Test-Fix Loop → Code Review → Commit Gate
```

## Cognitive JIT / Procedural Learning

A 9-stage pipeline (AD-531 through AD-539, 618 tests) that converts LLM-driven task execution into replayable deterministic procedures:

1. **Episode Clustering** — group similar episodes by semantic similarity
2. **Procedure Extraction** — extract deterministic steps from clustered episodes
3. **Procedure Store** — persist compiled procedures with provenance metadata
4. **Replay Engine** — execute procedures without LLM (0 tokens), fall back on failure
5. **Graduated Compilation** — five Dreyfus competency levels (Novice → Expert)
6. **Trust-Gated Promotion** — procedures earn promotion through demonstrated reliability
7. **Observational Learning** — agents learn from watching peers (three Bandura pathways)
8. **Lifecycle Management** — Ebbinghaus decay, archival, ChromaDB dedup, merge
9. **Gap Detection** — identify skill gaps, trigger qualification programs

## Dreaming (12-Step Consolidation)

During idle periods, the dreaming engine runs a full consolidation cycle:

| Step | Function |
|------|----------|
| 1 | Episode replay and clustering |
| 2 | Pattern extraction |
| 3 | Procedure compilation |
| 4 | Trust score recalibration |
| 5 | Hebbian weight adjustment |
| 6 | Workflow cache refresh |
| 7 | Notebook consolidation + cross-agent convergence detection |
| 8 | Pre-warm predictions for likely upcoming requests |
| 9 | Emergence metrics computation (PID-based) |
| 10 | Standing order evolution proposals |
| 11 | Prune dead connections |
| 12 | ACT-R activation decay — unreinforced memories weaken, low-activation episodes pruned |

Dreaming literally strengthens memories — episodes replayed during consolidation record activation events, increasing their recall priority. The same mechanism as sleep replay in neuroscience (Rasch & Born, 2013).

## Cognitive Self-Regulation

Three-tier model (AD-502 through AD-506):

- **Tier 1 (Internal)** — Agent self-monitoring: detects repetition, fixation, cognitive decline within each agent's own processing
- **Tier 2 (Social)** — Peer regulation: cross-agent repetition detection, tier credit system between agents
- **Tier 3 (System)** — Graduated zone model: GREEN (normal) → AMBER (warning) → RED (intervention) → CRITICAL (cooldown). Automatic escalation with Counselor oversight

The Counselor (Echo) subscribes to trust updates, circuit breaker trips, dream completions, self-monitoring concerns, and peer repetition events. Issues therapeutic interventions, cooldown directives, and wellness sweeps.

## Trust Cascade Dampening

Three-layer protection against runaway trust collapse (AD-558):

1. **Progressive dampening** — geometric decay (1.0 / 0.75 / 0.5 / 0.25) prevents rapid cascading
2. **Hard trust floor** — 0.05 minimum prevents trust from reaching zero
3. **Network circuit breaker** — triggers when too many agents in too many departments are affected simultaneously

## Emergence Metrics

Information-theoretic measurement of collaborative intelligence using Partial Information Decomposition (Riedl, 2025). Computed during dream Step 9:

- Pairwise synergy between agent pairs
- Emergence Capacity (median synergy across crew)
- Coordination Balance (synergy x redundancy)
- Groupthink and fragmentation risk detection
- Hebbian-synergy correlation

## Correction Feedback Loop

Human corrections are the richest learning signal:

1. **CorrectionDetector** identifies when the user is correcting a previous result
2. **AgentPatcher** modifies the responsible agent
3. Hot-reload the patched agent
4. Auto-retry the original request
5. Update trust, Hebbian weights, and episodic memory

## Key Source Files

| File | Purpose |
|------|---------|
| `cognitive/cognitive_agent.py` | Instructions-first LLM agent base |
| `cognitive/decomposer.py` | NL → TaskDAG + DAG executor |
| `cognitive/episodic.py` | Episodic memory with Anchor Frames |
| `cognitive/dreaming.py` | 12-step dream consolidation |
| `cognitive/standing_orders.py` | 4-tier instruction composition |
| `cognitive/trust_dampening.py` | Trust cascade dampening |
| `cognitive/emergence_metrics.py` | PID-based emergence measurement |
| `cognitive/self_regulation.py` | 3-tier cognitive self-regulation |
| `cognitive/qualification_tests.py` | Cognitive qualification probes |
| `cognitive/architect.py` | ArchitectAgent (Meridian) |
| `cognitive/builder.py` | BuilderAgent (Transporter Pattern) |
| `cognitive/counselor.py` | CounselorAgent (Echo) |
| `cognitive_jit/` | Procedural Learning pipeline (9 modules) |
