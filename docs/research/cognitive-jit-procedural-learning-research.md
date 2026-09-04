# Cognitive JIT / Procedural Learning — Landscape Research

**Date:** 2026-03-30
**Author:** Sean Galliher (Architect)
**Status:** Complete — findings incorporated into AD-464 decomposition (AD-531–539)

---

## The Gap

Every ProbOS agent invokes the LLM for every decision, regardless of whether it has solved an identical problem before. No mechanism exists to "compile" successful reasoning into replayable procedures. This wastes tokens, increases latency, and prevents the crew from building institutional expertise.

AD-430 (Action Memory, COMPLETE) closed the memory gap — agents now record every action as an episode. But episodes are raw experience, not distilled knowledge. The question: how do we get from "I remember doing this" to "I know how to do this"?

## Landscape Survey

15 projects surveyed across 5 tiers:

> **Reading the per-project rows.** This is a dated survey. Each Approach cell summarises
> how a project described its own design in published material read on 2026-03-30, and
> each row carries that project's publication year. These are descriptions, not
> evaluations, and not claims about what any project can or cannot do today. **Each
> project's own official documentation is the authority for its current capabilities**;
> every one of these projects is independently maintained and free to add or change a
> subsystem at any time, so consult that documentation rather than this row before relying
> on it. What each tier meant *for ProbOS* is stated in the prose after each table. Tier 5
> is stated as a deployment shape rather than per-product, for the reason given there.

### Tier 1: Code-as-Skills (Most Relevant)

| Project | Approach |
|---|---|
| **Voyager** (NVIDIA, 2023) | JavaScript function library built by LLM. Agent writes code to solve Minecraft tasks, stores as named functions, composes hierarchically. |
| **Cradle** (Tencent, 2024) | Environment-specific skill registry combining predefined skills with dynamically generated ones, which the agent then selects and parameterizes. |

**What ProbOS adds on top of code-as-skills:** multi-agent compound procedures, trust-gated promotion, observational learning across agents, and graduated compilation rather than a binary code/no-code split.

### Tier 2: Prompt/Pipeline Optimization

| Project | Approach |
|---|---|
| **DSPy** (Stanford, 2024) | Treats LLM pipelines as optimizable programs. Automatically tunes prompts, few-shot examples, and chain-of-thought structure via training data. |

**ProbOS connection:** Prompt and pipeline optimization is complementary to Cognitive JIT rather than an alternative to it. The same principles could enhance Level 2 (Guided) procedures — optimizing the hint prompts that guide LLM-assisted replay.

### Tier 3: Memory Systems

| Project | Approach |
|---|---|
| **Mengram** (2025) | Three-tier memory: semantic (facts), episodic (events), procedural (workflows). Auto-clusters episodes by embedding similarity (≥3 → extract procedure). Failure evolution via `procedure_feedback()`. Apache 2.0. |
| **Letta** (MemGPT team, 2024) | Self-editing memory blocks. Agent can modify its own system prompt, core memories, and archival storage. |

**What ProbOS took from memory-system research:**
- Episode clustering threshold (cosine similarity, ≥3 episodes) → adopted in AD-531
- Failure evolution (procedure feedback with step-level failure tracking) → adopted in AD-532 negative procedure extraction
- Procedure representation → ProbOS chose a structured `ProcedureStep` schema, which is what enables the Level 4 deterministic replay described below

### Tier 4: Reflection & Self-Improvement

| Project | Approach |
|---|---|
| **Reflexion** (2023) | Verbal reinforcement learning. Agent reflects on failures in natural language, stores reflections, uses them as guidance on retry. |
| **ExpeL** (2023) | Experience-driven rules. Extracts "insights" (rules) from batches of experiences. Rules injected as system prompt guidelines. |

**ProbOS connection:** Experience-derived rule extraction is conceptually close to AD-532 procedure extraction. The ProbOS chain runs rules → procedures → deterministic replay → graduated compilation.

### Tier 5: Orchestration and Role-Play Frameworks

Surveyed: AutoGen, CrewAI, LangGraph, Semantic Kernel, Agency Swarm and Claude MCP (orchestration and tooling); ChatDev and MetaGPT (multi-agent code generation).

This tier is described by **deployment shape**, not by per-product feature inventory. What can be described stably is a *way of assembling* a system, which the reader may or may not recognise in any given framework. In a **stateless step-composition** deployment, the orchestrator owns composition and control flow, and memory and persistence are wired in as a selected subsystem rather than being a property of the agent itself. In a **pipeline-scoped role** deployment, an agent is a role occupied for the duration of a pipeline, and continuity between pipelines is an integration concern layered outside the role. The AD-464 argument compares those two deployment shapes with the ProbOS one below; it does not depend on whether any framework named above supports either shape, and nothing here should be read as saying it does or does not.

That shape is what makes the ProbOS design choice worth stating. In ProbOS, sovereign agent identity is a core runtime service that outlives any single task, while episodic memory is an optional dependency wired in through the runtime: when it is enabled, execution paths are expected to record an episode, and that record is what gives procedure extraction (AD-532) a substrate to mine. The commitment is a design intent rather than an unconditional runtime guarantee — `ProbOSRuntime` accepts `episodic_memory=None`, and with the subsystem disabled the procedure-learning path has nothing to mine and the dreaming engine is not constructed at all. That dependency is precisely what the AD-531–539 decomposition is built around.

## ProbOS Design Commitments

The survey above motivated the AD-464 decomposition. These are the commitments it produced — stated as what ProbOS builds, not as a scorecard against anyone else:

| Capability | ProbOS (AD-464) |
|---|---|
| LLM → deterministic compilation | Yes (AD-535, graduated levels) |
| Trust-gated procedure promotion | Yes (AD-536, dept chief + Captain) |
| Multi-agent compound procedures | Yes (AD-532, cross-agent extraction) |
| Observational learning (learn by watching) | Yes (AD-537, Ward Room observation) |
| Negative procedures (what NOT to do) | Yes (AD-532, from contradiction detection) |
| Procedure lifecycle management | Yes (AD-538, decay/re-validate/dedup) |
| Knowledge gap → training pipeline | Yes (AD-539, gap → Holodeck scenarios) |
| Graduated compilation (5 levels) | Yes (AD-535, Novice→Expert) |

## Intellectual Lineage

| Theory | Author | ProbOS Mapping |
|---|---|---|
| ACT-R: Declarative→Procedural Compilation | Anderson (1983) | Episodes (declarative) → Procedures (compiled) → Replay (automatic) |
| Dreyfus Skill Acquisition Model | Dreyfus & Dreyfus (1986) | 5 compilation levels map to Dreyfus Novice→Expert stages |
| Social Learning Theory | Bandura (1977) | AD-537 observational learning — agents learn by watching others |
| Zone of Proximal Development | Vygotsky (1978) | Graduated compilation = scaffolding. Level 2 (Guided) is LLM-as-scaffold for developing autonomy |
| Situated Cognition | Lave & Wenger (1991) | Procedures are context-bound (preconditions, invariants). Learning is participation in practice, not abstract knowledge transfer |

## Key Decision: Ship's Records, Not KnowledgeStore

KnowledgeStore was the original intended backend for procedures. Analysis revealed KnowledgeStore has evolved into operational state persistence (trust snapshots, routing weights, agent source code) — not a shared knowledge library. The `_store_strategies()` path in `dreaming.py` writes JSON files that nothing ever reads.

**Decision:** Use Ship's Records (AD-434) as the procedure store backend. Rationale:
1. Git-backed — automatic version history and diff for procedure evolution
2. YAML frontmatter — structured metadata alongside procedure content
3. Classification access control — procedures can be ship-wide or department-scoped
4. Already built and tested
5. Clean separation: KnowledgeStore = operational state, Ship's Records = institutional knowledge

AD-531 replaces the dead `extract_strategies()` code path with cluster-based pattern detection that feeds into proper procedure extraction.

## Cautionary Tale: Dead Strategy Extraction

`DreamingEngine.extract_strategies()` (AD-383) runs during dream cycles and writes JSON files to `KnowledgeStore/strategies/`. Nothing in the codebase reads these files. The `REL_STRATEGY` Hebbian relationship type exists but is never written to by production code. This is write-only dead code — a reminder that building the write side without the read side produces zero value.

AD-531 through AD-534 are designed read-first: the replay dispatch mechanism (AD-534) that consumes procedures is designed before the extraction pipeline that produces them, ensuring every piece of learned knowledge has a consumer.
