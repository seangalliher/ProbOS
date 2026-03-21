# Cognitive Layer

The Cognitive layer is the intelligence center — it handles natural language understanding, memory, learning, self-modification, and the builder/architect pipeline.

## Pipeline

Natural language goes through:

1. **Working memory** assembles system state (agent health, trust scores, Hebbian weights, capabilities) within a token budget
2. **Episodic recall** finds similar past interactions for context (top-3 by keyword-overlap cosine similarity)
3. **Workflow cache** checks for previously successful DAG patterns (exact match, then fuzzy)
4. **LLM decomposer** converts text into a `TaskDAG` — a directed acyclic graph of typed intents with dependencies
5. **Attention manager** scores tasks: `urgency × relevance × deadline_factor × dependency_bonus`
6. **DAG executor** runs independent intents in parallel, respects dependency ordering

## Dynamic Intent Discovery

Each agent class declares structured `IntentDescriptor` metadata. The decomposer's system prompt is assembled at runtime from whatever agents are registered. New agent types self-integrate without any configuration changes.

This means adding a new agent type makes its intents available to the LLM automatically — no prompt editing, no routing tables, no configuration files.

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

Agents can also be designed collaboratively via the `/design` command.

## Builder Pipeline (Transporter Pattern)

Complex builds are decomposed into parallel chunks for concurrent execution:

```
BuildSpec → BuildBlueprint → ChunkDecomposer (Dematerializer)
    → Parallel Chunk Execution (Matter Stream)
    → ChunkAssembler (Rematerializer)
    → InterfaceValidator (Heisenberg Compensator)
    → Test-Fix Loop → Code Review → Commit Gate
```

## Correction Feedback Loop

Human corrections are the richest learning signal:

1. **CorrectionDetector** identifies when the user is correcting a previous result
2. **AgentPatcher** modifies the responsible agent
3. Hot-reload the patched agent
4. Auto-retry the original request
5. Update trust, Hebbian weights, and episodic memory

## Dreaming

During idle periods, the dreaming engine:

- Replays recent episodes to strengthen successful pathways
- Weakens failed pathways
- Prunes dead connections
- Adjusts trust scores
- Pre-warms predictions for likely upcoming requests

## Source Files

| File | Purpose |
|------|---------|
| `cognitive/decomposer.py` | NL → TaskDAG + DAG executor |
| `cognitive/prompt_builder.py` | Dynamic system prompt assembly |
| `cognitive/llm_client.py` | OpenAI-compatible + mock client |
| `cognitive/cognitive_agent.py` | Instructions-first LLM agent base |
| `cognitive/working_memory.py` | Bounded context assembly |
| `cognitive/episodic.py` | ChromaDB semantic long-term memory |
| `cognitive/attention.py` | Priority scoring + focus tracking |
| `cognitive/dreaming.py` | Offline consolidation + pre-warm |
| `cognitive/workflow_cache.py` | LRU pattern cache |
| `cognitive/agent_designer.py` | LLM designs new agents |
| `cognitive/self_mod.py` | Self-modification pipeline orchestrator |
| `cognitive/code_validator.py` | Static analysis for generated code |
| `cognitive/sandbox.py` | Isolated execution for untrusted agents |
| `cognitive/skill_designer.py` | Skill template generation |
| `cognitive/skill_validator.py` | Skill safety validation |
| `cognitive/behavioral_monitor.py` | Runtime behavior tracking |
| `cognitive/feedback.py` | Human feedback → trust/Hebbian/episodic |
| `cognitive/correction_detector.py` | Distinguishes corrections from new requests |
| `cognitive/agent_patcher.py` | Hot-patches designed agent code |
| `cognitive/strategy.py` | StrategyRecommender (skill attachment) |
| `cognitive/dependency_resolver.py` | Auto-install agent dependencies (uv) |
| `cognitive/emergent_detector.py` | 5 algorithms for emergent behavior |
| `cognitive/embeddings.py` | Embedding utilities |
| `cognitive/research.py` | Web research phase for agent design |
| `cognitive/architect.py` | ArchitectAgent (First Officer / CSO) |
| `cognitive/builder.py` | BuilderAgent (Chief Engineer) |
| `cognitive/code_reviewer.py` | CodeReviewAgent (Standing Orders gate) |
| `cognitive/counselor.py` | CounselorAgent (Ship's Counselor) |
| `cognitive/codebase_index.py` | Codebase knowledge graph |
| `cognitive/codebase_skill.py` | Skill interface to codebase index |
| `cognitive/copilot_adapter.py` | Visiting officer (Copilot SDK) |
| `cognitive/standing_orders.py` | Instruction composition |
| `cognitive/self_model.py` | SystemSelfModel for grounding |
| `cognitive/task_scheduler.py` | Task scheduling |
