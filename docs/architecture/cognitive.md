# Cognitive Layer

The Cognitive layer is the intelligence center — natural-language understanding, crew cognition and agentic tool use, memory, learning, self-modification, procedural learning, self-regulation, and the builder/architect pipeline.

## Ship's Computer Pipeline

A natural-language request to the Ship's Computer goes through:

1. **Working memory** assembles system state (agent health, trust scores, Hebbian weights, capabilities) within a token budget
2. **Episodic recall** finds similar past interactions for context
3. **Workflow cache** checks for previously successful DAG patterns (exact match, then fuzzy)
4. **LLM decomposer** converts text into a `TaskDAG` — a directed acyclic graph of typed intents with dependencies
5. **Attention manager** scores tasks: `urgency x relevance x deadline_factor x dependency_bonus`
6. **DAG executor** runs independent intents in parallel, respects dependency ordering

## Dynamic Intent Discovery

Each agent class declares structured `IntentDescriptor` metadata. The decomposer's system prompt is assembled at runtime from whatever agents are registered. New agent types self-integrate without any configuration changes.

## Crew Agents and Standing Orders

Crew agents are instructions-first `CognitiveAgent`s: their behavior is defined by instructions the LLM reasons over, not by hard-coded logic. Those instructions come from a four-tier hierarchy composed at call time:

1. **Federation Constitution** — universal, immutable rules
2. **Ship Standing Orders** — per-instance configuration
3. **Department Protocols** — per-department standards
4. **Agent Standing Orders** — per-agent, evolvable through self-modification

`compose_instructions()` assembles the complete system prompt for each crew agent's LLM call.

## Agentic Loop and Tools

When a crew member replies to a 1:1 direct message — a shell `@callsign` session or a 1:1 chat in the HXI — or works a dispatched work item, it can run a multi-turn **agentic loop**: the agent reasons, calls tools, reads their results and continues until the work is done. The loop is bounded by step, cost and trust limits; reaching the step limit becomes a checkpoint that asks whether to continue, and a turn that outgrows a reply becomes a task. Tool calls and their outputs are recorded in a durable trace. Both loops are opt-in (`dm_agentic.enabled` and `agentic_dispatch.enabled`) and on in the reference `config/system.yaml`; group, Ward Room, proactive and vision turns keep a single LLM pass.

Tools come from a shared **tool registry**:

| Tool family | Examples |
|-------------|----------|
| Discovery and delegation | Capability search, task delegation to other agents |
| Durable work | Work-item discovery and claiming, status and steps, work permits, action approvals |
| Knowledge | Recall of produced artifacts, oracle queries, event-log queries, self-queries, published findings |
| Code execution | Governed Python in per-agent workspaces; missing libraries become approval-gated install requests |
| Browser | An agent-driven Chromium browser (Playwright), offered to the loop read-only and behind a URL allowlist |
| MCP | Tools from registered MCP servers, authorized per agent and per tool, with consensus for high-risk invocations |

Agents also reach mesh capabilities — file reads, HTTP fetches, office documents and more — through the intent bus, so every call keeps its trust, consensus and audit properties. Code execution, the browser tool and MCP agent tools are each opt-in, and on in the reference configuration.

## Composable Cognition

A cognitive agent is an organism: a **cognitive spine** — the agent's private nervous system for composing organs and running the cognitive cycle — plus **cognitive organs**, bounded faculties such as attention (`AttentionFaculty`) and dreaming (`DreamingOrgan`). Organs are child components that are born and die with their agent and are namespaced under it; they are not mesh-registered agents. The mesh is the same pattern at ship scale: asynchronous and governed where the spine is synchronous and private. The migration is incremental and behavior-preserving. See [Composable Cognition](../development/composable-cognition.md).

## Self-Modification

When ProbOS encounters a capability gap (no agent can handle a request), it can design a new agent:

```
Capability gap detected
    → LLM generates agent code
    → CodeValidator static analysis
    → SandboxRunner isolation test
    → Probationary trust assigned
    → SystemQA smoke tests
    → BehavioralMonitor tracks post-deployment
```

Designs need approval: an attended shell asks the Captain, and without an approver unapproved designs are refused. On warm boot, restored agent code passes `CodeValidator` again before it is loaded.

## Builder Pipeline (Transporter Pattern)

Complex builds are decomposed into parallel chunks for concurrent execution:

```
BuildSpec → BuildBlueprint → ChunkDecomposer (Dematerializer)
    → Parallel Chunk Execution (Matter Stream)
    → ChunkAssembler (Rematerializer)
    → InterfaceValidator (Heisenberg Compensator)
    → Test-Fix Loop → Code Review → Commit Gate
```

The code-review step is a `CodeReviewAgent` the Builder runs against Standing Orders, and builds wait for the Captain's approval before they land.

## Cognitive JIT / Procedural Learning

A pipeline (AD-531 through AD-539) that converts LLM-driven task execution into replayable deterministic procedures:

1. **Episode Clustering** — group similar episodes by semantic similarity
2. **Procedure Extraction** — extract deterministic steps from clustered episodes
3. **Procedure Store** — persist compiled procedures with provenance metadata
4. **Replay Engine** — execute procedures without LLM (0 tokens), fall back on failure
5. **Graduated Compilation** — five Dreyfus competency levels (Novice → Expert)
6. **Trust-Gated Promotion** — procedures earn promotion through demonstrated reliability
7. **Observational Learning** — agents learn from watching peers (three Bandura pathways)
8. **Lifecycle Management** — Ebbinghaus decay, archival, ChromaDB dedup, merge
9. **Gap Detection** — identify skill gaps, trigger qualification programs

## Dreaming

Between full cycles, a **micro-dream** replays the most recent episodes. During idle periods, the dreaming engine runs a full consolidation cycle:

| Step | Function |
|------|----------|
| 0 | Flush un-consolidated episodes through the micro-dream (Hebbian replay) |
| 2 | Prune — decay all weights and remove below-threshold connections |
| 3 | Trust consolidation from recent track records; contradiction detection |
| 4 | Pre-warm — learn temporal intent sequences for faster routing |
| 5 | Idle pool scale-down |
| 6 | Episode clustering; expertise directory update |
| 7 | Procedure extraction, evolution and lifecycle; failure distillation; fallback and observational learning; notebook consolidation and cross-agent convergence; relationship inference |
| 8 | Capability gap prediction |
| 9 | Emergence metrics (PID-based) |
| 10 | Notebook quality metrics |
| 11 | Spaced retrieval practice; reconsolidation reviews |
| 12 | Activation-based memory pruning — unreinforced memories weaken, low-activation episodes are pruned |
| 13 | Behavioral metrics |
| 14 | Source attribution consolidation |
| 15 | Reflection episode promotion |

Dreaming literally strengthens memories — episodes replayed during consolidation record activation events, increasing their recall priority. The same mechanism as sleep replay in neuroscience (Rasch & Born, 2013).

## Cognitive Self-Regulation

Three-tier model (AD-502 through AD-506):

- **Tier 1 (Internal)** — Agent self-monitoring: detects repetition, fixation, cognitive decline within each agent's own processing
- **Tier 2 (Social)** — Peer regulation: cross-agent repetition detection, tier credit system between agents
- **Tier 3 (System)** — Graduated zone model: GREEN (normal) → AMBER (warning) → RED (intervention) → CRITICAL (cooldown). Automatic escalation with Counselor oversight

The Ship's Counselor subscribes to trust updates, circuit breaker trips, dream completions, self-monitoring concerns, and peer repetition events, and issues therapeutic interventions, cooldown directives, and wellness sweeps.

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
| `cognitive/standing_orders.py` | 4-tier instruction composition |
| `cognitive/agentic_dispatch.py` | Agentic dispatch for crew work |
| `cognitive/crew_orchestrator.py` | Durable crew workflow orchestration |
| `cognitive/spine.py`, `cognitive/organ.py` | Cognitive spine and organ contract |
| `tools/registry.py` | Shared tool registry |
| `cognitive/episodic.py` | Episodic memory with Anchor Frames |
| `cognitive/dreaming.py` | Dream consolidation |
| `cognitive/procedures.py`, `cognitive/procedure_store.py` | Cognitive JIT procedures |
| `cognitive/circuit_breaker.py` | Cognitive zone model and circuit breaker |
| `cognitive/emergence_metrics.py` | PID-based emergence measurement |
| `cognitive/architect.py` | ArchitectAgent (First Officer) |
| `cognitive/builder.py` | BuilderAgent (Transporter Pattern) |
| `cognitive/counselor.py` | CounselorAgent (Ship's Counselor) |
| `cognitive/correction_detector.py`, `cognitive/agent_patcher.py` | Correction feedback loop |
