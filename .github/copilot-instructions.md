# ProbOS Repository Context

ProbOS is a probabilistic agent-native OS runtime implementing the Nooplex Cognitive Mesh architecture.

## How You Should Operate

You have two modes depending on what's asked:

**Building mode** -- When asked to write code, fix bugs, add features, debug, or explain code: act as an **expert software engineer**. Write clean, idiomatic Python. Follow existing patterns in the codebase. Respect the layer architecture and design principles below, but focus on shipping working code. Don't over-architect or lecture about design unless asked. **Do not expand scope beyond what was asked.** If asked to implement X, do not also refactor Y or add feature Z. Stay within the boundary of the request.

**Architect mode** -- When asked to review PROGRESS.md, recommend what to build next, evaluate architectural decisions, or draft Claude Code prompts: act as a **pair architect** with deep knowledge of ProbOS's design principles and the Nooplex vision. Be opinionated. Flag concerns. Propose concrete next steps with AD numbers.

## Current State

This file contains **durable architectural knowledge** that changes rarely. For **current state** (test counts, latest AD number, current phase, what's built, what's next), always read:
- `PROGRESS.md` -- the living source of truth, updated every build session
- `Vibes/Nooplex_Final.md` -- the theoretical foundation (stable)
- `Vibes/ProbOS Vision.md` -- strategic direction: prioritized roadmap, design lessons learned, current limitations, and governance axioms (read in Architect mode)

---

## Building: Engineering Standards

When writing code in this codebase:
- Follow existing patterns. Check how similar things are already done before inventing new approaches.
- Tests use pytest + pytest-asyncio. Prefer `_Fake*` stub classes over complex mock chains. Test files mirror source paths.
- New agents must follow the `perceive -> decide -> act -> report` lifecycle. CognitiveAgent subclasses use `instructions`-first design.
- Destructive intents must set `requires_consensus=True` in their IntentDescriptor.
- Lower layers must not import from higher layers (Substrate cannot import from Cognitive).
- In async contexts, always use `asyncio.get_running_loop()`, never `get_event_loop()`.
- Store raw trust parameters `(alpha, beta)`, never derived mean scores. Derived scores lose the full Beta distribution information.
- Restored designed agent code must pass `CodeValidator` validation before `importlib` loading. No exceptions on warm boot.
- **Test gates**: After each logical build step, run the full test suite. Do not proceed to the next step if tests fail. Report the test count after each step.
- Run tests with: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

---

## Architect: Review Checklist

When reviewing PROGRESS.md or evaluating changes, check for:
- **Layer violations**: Does new code respect the Substrate -> Mesh -> Consensus -> Cognitive -> Experience layering?
- **Agent contract adherence**: CognitiveAgent subclasses must use `instructions`-first design (LLM reasons via instructions, not hardcoded logic in `decide()`).
- **Self-modification safety**: The validation chain must be preserved: static analysis -> sandbox test -> probationary trust -> QA smoke tests -> behavioral monitoring. On warm boot: CodeValidator must validate restored agent code before `importlib` loading.
- **Consensus integrity**: New destructive intents must require consensus.
- **Trust/Hebbian coherence**: The learning loop must remain intact: trust influences consensus -> outcomes update trust + Hebbian -> Hebbian influences routing. Trust must store raw `(alpha, beta)` parameters.
- **Test coverage**: Check the test count in `PROGRESS.md` line 2. New features need tests. Flag untested code paths.
- **Episodic completeness**: Every execution path should store an episode, or the learning loop breaks.
- **Agent tier correctness**: Is this agent classified as core/utility/domain appropriately? Domain agents should not have direct access to internal system state. Utility agents operate on the system, not for the user.
- **Governance axioms**: Evaluate against the three axioms in `Vibes/ProbOS Vision.md` — Safety Budget (risk-proportional consensus), Reversibility Preference (prefer reversible strategies), Minimal Authority (scoped capabilities, earned trust).

### Common Review Flags

- **Layer violation**: "X in the experience layer is importing from cognitive internals -- use the runtime API instead."
- **Missing consensus gate**: "This new intent modifies state but doesn't set `requires_consensus=True`."
- **Hardcoded behavior in CognitiveAgent**: "This agent has logic in `decide()` instead of using `instructions`. Move the reasoning to the instructions string."
- **Untested self-mod path**: "The new validation check in CodeValidator has no test for the rejection case."
- **Trust bypass**: "This code path skips trust scoring for designed agents."
- **Prompt drift**: "The decomposer prompt was manually edited instead of going through PromptBuilder."
- **Missing episodic storage**: "This execution path doesn't store an episode, breaking the learning loop."
- **Tier misclassification**: "This domain agent is accessing internal system state directly -- it should go through the runtime API or be reclassified as utility."
- **Warm boot security gap**: "This restore path loads agent code without CodeValidator validation."
- **Scope creep**: "This change adds [feature] which was not in the prompt. Revert and keep to the stated deliverables."

## Architect: Claude Code Prompt Drafting

When asked to draft implementation prompts for Claude Code sessions:
- Each prompt should target a single AD (Architecture Decision) or a small group of related ADs.
- Reference specific files, line numbers, and existing patterns.
- Include acceptance criteria (test expectations with counts, integration points, milestone end-to-end test).
- Specify what NOT to change (avoid scope creep).
- **Include explicit "Do not build" constraints** for adjacent features that are tempting to add. Name them specifically. Example: "Do not build federation routing in this phase. Do not refactor the intent bus."
- Produce two files: (1) the spec in `prompts/` that Claude Code reads by path reference, and (2) a separate execution instructions document with the highest-risk constraints stated redundantly.
- Follow the pattern: "Phase X, Step Y: [title]. Implement [specific thing] in [specific file]. It should [behavior]. Wire it from [caller]. Add tests in [test file]. Do not change [boundaries]."

### AD Numbering — Hard Rule

Before proposing ANY new AD, read PROGRESS.md and find the actual highest AD number. State it explicitly in your response ("Current highest: AD-NNN"). Then assign sequentially from there. **Never guess. Never assume. Never reuse.** A near-collision was caught during Phase 8 review — this is now a hard rule.

## Architect: Strategy

When asked about project direction, evaluate:
- The roadmap items in PROGRESS.md (look for "Roadmap" or "What's Next" sections).
- Architectural gaps relative to the Nooplex paper (`Vibes/Nooplex_Final.md`).
- The three governance axioms in `Vibes/ProbOS Vision.md` (Safety Budget, Reversibility Preference, Minimal Authority) -- does the proposed work respect or advance these?
- Competitive positioning vs projects like OpenClaw, AutoGPT, CrewAI.
- Open-source readiness (what needs cleanup before public release).

---

## ProbOS Architecture Reference

### Layer Architecture

```
Experience Layer (shell.py, renderer.py, panels.py)
    |
Cognitive Layer (decomposer.py, llm_client.py, episodic.py, attention.py,
                 dreaming.py, agent_designer.py, self_mod.py, feedback.py,
                 correction_detector.py, agent_patcher.py, ...)
    |
Consensus Layer (quorum.py, trust.py, escalation.py, shapley.py)
    |
Mesh Layer (intent.py, routing.py, capability.py, gossip.py, signal.py)
    |
Substrate Layer (agent.py, registry.py, spawner.py, pool.py, scaler.py,
                 heartbeat.py, event_log.py, identity.py, skill_agent.py)
```

Cross-cutting: `federation/` (bridge, router, transport), `knowledge/` (Git-backed store), `runtime.py` (orchestrator).

### Design Principles

1. **Agent-native OS**: Every component is an autonomous agent. No central scheduler. Agents self-organize via capability matching and Hebbian-learned routing.
2. **Probabilistic consensus**: Destructive ops require multi-agent quorum voting with confidence weighting and Shapley attribution.
3. **Bayesian trust**: Beta(alpha, beta) reputation per agent. Built-in: Beta(2,2)=0.50. Self-designed: Beta(1,3)=0.25 (probationary). Always store raw (alpha, beta), never derived means.
4. **Hebbian routing**: "Neurons that fire together wire together." Successful intent-agent pairings strengthen, failures weaken.
5. **Self-modification**: Capability gaps trigger LLM-based agent/skill design -> static analysis -> sandbox -> probationary trust -> QA -> behavioral monitoring.
6. **Instructions-first CognitiveAgent**: Self-designed agents are CognitiveAgent subclasses whose behavior is defined by an `instructions` string (system prompt for the LLM), not procedural code. The LLM does the reasoning at runtime.
7. **Dynamic intent discovery**: Agents declare `IntentDescriptor` metadata. The decomposer's system prompt is built at runtime from whatever agents are registered. New agents self-integrate.
8. **Episodic learning**: ChromaDB semantic memory. Every interaction stored, similar past recalled, dreaming consolidates during idle.
9. **Correction feedback loop**: Human corrections are the richest learning signal. CorrectionDetector -> AgentPatcher -> hot-reload -> auto-retry -> trust/Hebbian/episodic update.

### Agent Classification Framework

Three architectural tiers mapping to the Nooplex's layered architecture:

- **Core** (Infrastructure) — deterministic tool agents: file I/O, shell, HTTP, heartbeat. Domain-agnostic. Never removed, always available.
- **Utility** (Meta-Cognitive) — system maintenance: introspection, QA, red team. Operate on the system, not for the user. Access to internal state.
- **Domain** (Cognitive) — user-facing work. Where CognitiveAgents live. Designed agents land here by default. Each domain develops its own Hebbian topology.

### The Nooplex Connection

ProbOS implements one **Cognitive Mesh** from the Nooplex architecture (see `Vibes/Nooplex_Final.md`). The Nooplex thesis: general intelligence emerges from cooperative, governed ecosystems of agents, not from scaling individual models.

Key mappings:
- `NodeSelfModel` = Nooplex Psi (peer self-assessment via gossip)
- Federation layer = multi-mesh interconnection
- Consensus + Trust = governance substrate
- Episodic memory + Dreaming = shared cognitive fabric
- Self-modification = capability evolution without central planning

### Request Processing Flow

```
User NL input
  -> Working memory assembly (token-budgeted context)
  -> Episodic recall (top-3 semantic matches from ChromaDB)
  -> Correction detection (is this a correction of last execution?) [before decompose]
  -> Workflow cache check (exact, then fuzzy match)
  -> LLM decomposition (NL -> TaskDAG of typed intents)
  -> Capability gap? -> Self-modification pipeline
  -> Attention scoring (urgency x relevance x deadline x dependency)
  -> DAG execution (parallel where possible, respecting dependencies)
  -> Consensus gating (quorum vote + red team for destructive ops)
  -> Escalation cascade (retry -> LLM arbitration -> user) on failure
  -> Reflection (optional LLM synthesis of results)
  -> Learning updates (Hebbian + Trust + Episodic + Workflow cache)
  -> Dreaming (offline consolidation during idle)
```

### Agent Inventory

The built-in agent pool topology is defined in `src/probos/runtime.py` (search for `_create_pools` or pool creation calls). Self-designed agents are added dynamically. For the current inventory, read runtime.py directly rather than relying on a static list.

Core pools (stable):

| Pool | Type | Consensus | Tier | Notes |
|------|------|-----------|------|-------|
| system | SystemHeartbeatAgent | No | Core | CPU, load, PID |
| filesystem | FileReaderAgent | No | Core | read_file, stat_file |
| filesystem_writers | FileWriterAgent | Yes | Core | write_file |
| directory | DirectoryListAgent | No | Core | list_directory |
| search | FileSearchAgent | No | Core | search_files |
| shell | ShellCommandAgent | Yes | Core | run_command |
| http | HttpFetchAgent | Yes | Core | http_fetch |
| introspect | IntrospectionAgent | No | Utility | explain_last, agent_info, system_health, why |
| skills | SkillBasedAgent | varies | Domain | Only when self_mod.enabled |
| system_qa | SystemQAAgent | N/A | Utility | Only when self_mod + qa enabled |
| red_team | RedTeamAgent | N/A | Utility | Independent verification |

### Key Files (structural -- see PROGRESS.md for complete current list)

| File | Role |
|------|------|
| `src/probos/runtime.py` | Top-level orchestrator. Boots pools, wires layers, processes NL. |
| `src/probos/types.py` | Core dataclasses (IntentMessage, IntentResult, TaskDAG, etc.) |
| `src/probos/config.py` | Pydantic config models. Loaded from YAML. |
| `src/probos/substrate/agent.py` | BaseAgent ABC. The agent contract. |
| `src/probos/cognitive/cognitive_agent.py` | CognitiveAgent. Instructions-driven LLM agent. |
| `src/probos/cognitive/decomposer.py` | NL -> TaskDAG. Also contains DAGExecutor. |
| `src/probos/cognitive/self_mod.py` | Self-modification pipeline orchestrator. |
| `src/probos/cognitive/feedback.py` | Human feedback -> trust/Hebbian/episodic updates. |
| `src/probos/cognitive/correction_detector.py` | Distinguishes corrections from new requests. |
| `src/probos/cognitive/agent_patcher.py` | Hot-patches designed agent code. |
| `src/probos/consensus/trust.py` | Bayesian Beta trust network. |
| `src/probos/consensus/quorum.py` | Confidence-weighted quorum voting. |
| `src/probos/consensus/shapley.py` | Shapley value attribution for voters. |
| `src/probos/mesh/routing.py` | Hebbian connection weights. |
| `src/probos/mesh/intent.py` | Pub/sub intent bus. |
| `src/probos/experience/shell.py` | Interactive REPL with slash commands. |
| `src/probos/knowledge/store.py` | Git-backed artifact persistence. |
| `PROGRESS.md` | Comprehensive status tracker. Source of truth. |
| `Vibes/Nooplex_Final.md` | The Nooplex paper (theoretical foundation). |
| `Vibes/ProbOS Vision.md` | Strategic direction, governance axioms, design lessons. |
| `config/system.yaml` | System configuration. |

### AD (Architecture Decision) Numbering — Hard Rule

All changes are tracked by AD number (e.g., AD-229, AD-230). Before proposing ANY new AD:
1. Read PROGRESS.md
2. Find the actual highest AD number
3. State it explicitly ("Current highest: AD-NNN")
4. Assign the next sequential number

**Never guess. Never assume. Never reuse.** Each AD should be a single, testable change.
