# Cognitive JIT / Procedural Learning — Landscape Research

**Date:** 2026-03-30
**Author:** Sean Galliher (Architect)
**Status:** Complete — findings incorporated into AD-464 decomposition (AD-531–539)

---

## The Gap

Every ProbOS agent invokes the LLM for every decision, regardless of whether it has solved an identical problem before. No mechanism exists to "compile" successful reasoning into replayable procedures. This wastes tokens, increases latency, and prevents the crew from building institutional expertise.

AD-430 (Action Memory, COMPLETE) closed the memory gap — agents now record every action as an episode. But episodes are raw experience, not distilled knowledge. The question: how do we get from "I remember doing this" to "I know how to do this"?

## Landscape Survey

17 projects surveyed across 5 tiers:

### Tier 1: Code-as-Skills (Most Relevant)

| Project | Approach | Strengths | Gaps |
|---|---|---|---|
| **Voyager** (NVIDIA, 2023) | JavaScript function library built by LLM. Agent writes code to solve Minecraft tasks, stores as named functions, composes hierarchically. | Compositional — simple skills build complex ones. Code IS the procedure — deterministic by definition. Curriculum-driven: easy skills first. | Single-agent only. No trust/governance. Task-specific (Minecraft). No failure evolution. No multi-agent collaboration. |
| **Cradle** (Tencent, 2024) | Pre-authored skill library per game environment. Agent selects and parameterizes skills. | Clean abstraction between decision and execution. | Skills are hand-authored, not learned. No LLM-to-deterministic compilation. Environment-specific. |

**ProbOS differentiator:** Voyager's compositional approach is powerful but operates in a single-agent, single-domain (Minecraft) context with no governance. ProbOS adds: multi-agent compound procedures, trust-gated promotion, observational learning across agents, and graduated compilation (not binary code/no-code).

### Tier 2: Prompt/Pipeline Optimization

| Project | Approach | Strengths | Gaps |
|---|---|---|---|
| **DSPy** (Stanford, 2024) | Treats LLM pipelines as optimizable programs. Automatically tunes prompts, few-shot examples, and chain-of-thought structure via training data. | Systematic, reproducible optimization. Metric-driven. | Optimizes prompts, doesn't eliminate them. Still requires LLM at runtime. No zero-token replay. No agent identity. |

**ProbOS connection:** DSPy's optimization principles could enhance Level 2 (Guided) procedures — optimizing the hint prompts that guide LLM-assisted replay. Not a competitor; a complementary technique.

### Tier 3: Memory Systems

| Project | Approach | Strengths | Gaps |
|---|---|---|---|
| **Mengram** (2025) | Three-tier memory: semantic (facts), episodic (events), procedural (workflows). Auto-clusters episodes by embedding similarity (≥3 → extract procedure). Failure evolution via `procedure_feedback()`. | NL workflow versioning, not code. Failure evolution is novel — procedures learn from specific failure points. Apache 2.0 (~500 stars). | Single-agent. No trust governance. No compilation levels (procedures are always NL, never deterministic). No multi-agent collaboration. No observational learning. |
| **Letta** (MemGPT team, 2024) | Self-editing memory blocks. Agent can modify its own system prompt, core memories, and archival storage. | Novel approach: the agent controls its own memory. | Memory architecture, not procedural learning. No procedure extraction. No replay. |

**ProbOS absorption from Mengram:**
- Episode clustering threshold (cosine similarity, ≥3 episodes) → adopted in AD-531
- Failure evolution (procedure feedback with step-level failure tracking) → adopted in AD-532 negative procedure extraction
- NL workflow format → ProbOS uses structured `ProcedureStep` schema instead, enabling Level 4 deterministic replay that Mengram can't achieve

### Tier 4: Reflection & Self-Improvement

| Project | Approach | Strengths | Gaps |
|---|---|---|---|
| **Reflexion** (2023) | Verbal reinforcement learning. Agent reflects on failures in natural language, stores reflections, uses them as guidance on retry. | No gradient updates — pure text-based learning. Simple, effective. | Reflections are prompt injection, not procedures. No compilation. No persistence. Session-only. |
| **ExpeL** (2023) | Experience-driven rules. Extracts "insights" (rules) from batches of experiences. Rules injected as system prompt guidelines. | Explicit rule extraction from experience. Compositional with Reflexion. | Rules are guidelines, not executable procedures. Can't replay deterministically. No versioning. No trust. |

**ProbOS connection:** ExpeL's insight extraction is conceptually similar to AD-532 procedure extraction but stops at NL rules. ProbOS goes further: rules → procedures → deterministic replay → graduated compilation.

### Tier 5: Frameworks (No Learning)

| Project | Approach | Gaps |
|---|---|---|
| AutoGen, CrewAI, LangGraph, Semantic Kernel, Agency Swarm, Claude MCP | Orchestration/tooling frameworks | No learning, no memory, no procedure extraction |
| ChatDev, MetaGPT | Multi-agent code generation | Role-play, not sovereign identity. No memory. No learning. |

## What No One Does

After surveying 17 projects, ProbOS's Cognitive JIT occupies a unique niche:

| Capability | Any Existing Project? | ProbOS (AD-464) |
|---|---|---|
| LLM → deterministic compilation | No | Yes (AD-535, graduated levels) |
| Trust-gated procedure promotion | No | Yes (AD-536, dept chief + Captain) |
| Multi-agent compound procedures | No | Yes (AD-532, cross-agent extraction) |
| Observational learning (learn by watching) | No | Yes (AD-537, Ward Room observation) |
| Negative procedures (what NOT to do) | No | Yes (AD-532, from contradiction detection) |
| Procedure lifecycle management | No | Yes (AD-538, decay/re-validate/dedup) |
| Knowledge gap → training pipeline | No | Yes (AD-539, gap → Holodeck scenarios) |
| Graduated compilation (5 levels) | No (all binary) | Yes (AD-535, Novice→Expert) |

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
