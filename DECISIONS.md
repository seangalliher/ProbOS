# ProbOS — Architectural Decisions

Append-only log of architectural decisions made during ProbOS development. Each AD documents the reasoning behind a design choice.

See [PROGRESS.md](PROGRESS.md) for project status. See [docs/development/roadmap.md](docs/development/roadmap.md) for future plans.

**Archives:** [Era I — Genesis](decisions-era-1-genesis.md) | [Era II — Emergence](decisions-era-2-emergence.md) | [Era III — Product](decisions-era-3-product.md) | [Era IV — Evolution](decisions-era-4-evolution.md)

---

## Era V — Civilization (Phases 31-36)

### AD-641g — Asynchronous Cognitive Pipeline via NATS

**Date:** 2026-04-17  
**Status:** Design  
**Parent:** AD-641 (Brain Enhancement Phase)  
**Depends on:** AD-637 (NATS Event Bus)

**Decision:** Decouple the cognitive chain steps (QUERY → ANALYZE → COMPOSE) via NATS message subjects rather than running them as a synchronous blocking sequence.

**Motivation:** The current chain pipeline adds cognitive depth (multi-step reasoning) but not perceptual depth (ability to see more). The QUERY step only receives what `_gather_context()` already fetched — a fixed sliding window of 5-10 recent items. Agents cannot browse deeper thread history or scan broadly across channels. Evidence: agent "Lyra" hallucinated a `[READ_CHANNEL]` command tag — the LLM expressing a genuine need the architecture doesn't provide.

**Design:**
- QUERY (browse) runs frequently, 0 LLM calls, publishes interesting items to `chain.{agent_id}.analyze`
- ANALYZE subscribes, processes selectively with LLM, gates whether a response is warranted
- COMPOSE only fires when ANALYZE says something is worth saying
- NATS provides backpressure, priority ordering, durable queues, and consumer groups
- Pattern is source-agnostic: same pipeline extends to document reading, web research, ship's state observation

**Research:** [docs/research/ad-641g-async-cognitive-pipeline.md](docs/research/ad-641g-async-cognitive-pipeline.md)


### AD-643a — Intent-Driven Skill Activation

**Date:** 2026-04-18
**Status:** Complete
**Issue:** #283

**Decision:** Move augmentation skill loading from before the cognitive chain to after ANALYZE. Skills declare `probos-triggers` metadata; ANALYZE outputs `intended_actions`. Only skills whose triggers match the agent's expressed intent are loaded.

**Motivation:** All augmentation skills loaded on every `proactive_think` cycle regardless of what the agent intended to do. ~1,500 wasted tokens/cycle × 30 agents × 5 cycles = ~225K tokens/session. Communication chain fired for notebooks, leadership reviews — wrong chain for the action.

**Design:**
- `CognitiveSkillEntry` gains `triggers: list[str]` field, parsed from `probos-triggers` YAML metadata
- `find_triggered_skills()` matches `intended_actions` to skill triggers (falls back to intent matching for skills without triggers)
- Two-phase execution: triage (QUERY + ANALYZE) → extract `intended_actions` → route → targeted skill loading → execute (COMPOSE + EVALUATE + REFLECT)
- Communication chain only fires when `intended_actions` contains a comm action (`ward_room_post`, `ward_room_reply`, `endorse`, `dm`)
- Non-comm actions (notebook, leadership_review) skip chain, fall through to `_decide_via_llm()` with targeted skills
- Silent short-circuit at triage phase (no COMPOSE/EVALUATE/REFLECT)
- External chains (`_pending_sub_task_chain`) bypass intent routing (backward compat)
- Missing `intended_actions` falls back to pre-AD-643 all-skills behavior (backward compat)

**Research:** BDI plan library (Rao & Georgeff), OODA loop, Dual Process Theory (Kahneman). ANALYZE = System 1/2 gate. All BDI limitations addressed by existing ProbOS architecture (episodic memory, Ward Room, trust, standing orders, workforce scheduling, SOPs).

**Key decisions:**
| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Triggers on skills, not on chains | Open/Closed — new skills register triggers without modifying chain code |
| DD-2 | Triage re-executes on full chain path | Avoids modifying SubTaskExecutor; ~200 token overhead acceptable; AD-643b eliminates this |
| DD-3 | Non-comm actions skip chain entirely | No compose/evaluate/reflect templates exist for notebooks yet — AD-643c adds them |
| DD-4 | `intended_actions` is a JSON array, not enum | Extensible vocabulary; new thought processes add new action tags without prompt changes |

**Future:** AD-643b (Thought Process Catalog — declarative `ThoughtProcess`/`ThoughtAction` definitions replace hardcoded chains), AD-643c (multi-action processes + sequential execution).

---

### AD-643b — Skill Trigger Learning: Adaptive Trigger Discovery & Graduation

**Date:** 2026-04-18
**Status:** Complete (Phase 1+2 of 3; Phase 3 graduation deferred)
**Issue:** #284

**Motivation:** AD-643a requires agents to declare `intended_actions` for skills to load, but agents sometimes take undeclared actions (e.g., writing a notebook without declaring `notebook`). Quality skills don't load, degrading output. At scale (100+ triggers), injecting full trigger lists into prompts defeats token savings.

**Design:** Three-phase trigger learning lifecycle:
1. **Trigger Awareness** — inject scoped trigger list into ANALYZE (filtered by department + rank). Training wheels.
2. **Post-Hoc Feedback** — detect undeclared actions in COMPOSE output, inject feedback into REFLECT → episodic memory → future recall. Closed learning loop.
3. **Trigger Graduation** — track declaration accuracy per agent. Consistently correct → graduate (remove from prompt). Dreyfus progression: novice→expert. Prompt overhead trends to zero.

**Research:** Metacognitive monitoring (Flavell 1979), scaffolding→fading (Wood/Bruner/Ross 1976), situated cognition (Lave & Wenger 1991). Extends AD-535 Dreyfus model to trigger declarations.

| Decision | Choice | Rationale |
|----------|--------|-----------|
| DD-1 | Per-agent scoping, not global injection | Eligible triggers filtered by department + rank; ~15-25 tags per agent, not 100+ |
| DD-2 | Post-hoc detection, not capability gating | Skills are guidance, not gates; agent can still write notebook without skill loaded |
| DD-3 | Episodic memory as learning medium | REFLECT feedback → episodic storage → future recall. No new infrastructure |
| DD-4 | Graduation reduces overhead over time | Training wheels self-remove; mature crews have zero trigger injection overhead |
| DD-5 | Three-phase delivery | Each phase independently valuable and backward compatible |
| DD-6 | Re-reflect is a synchronous workaround | NATS decoupling (AD-643d) replaces re-reflect with message-flow interception |

---

### AD-643d — NATS-Based Trigger Feedback Pipeline

**Date:** 2026-04-18
**Status:** Deferred — blocked on AD-637 (NATS Event Bus)
**Parent:** AD-643 (Intent-Driven Skill Activation)
**Depends on:** AD-637 (NATS), AD-643b (trigger learning)

**Decision:** Refactor AD-643b's re-reflect workaround into a native NATS message-flow pattern once the cognitive pipeline is decoupled via NATS subjects (AD-641g).

**Motivation:** AD-643b detects undeclared actions *after* the full chain completes, then re-runs REFLECT as a partial chain to inject feedback into episodic memory. This works but is a synchronous workaround — the chain runs, completes, then a second REFLECT fires. With NATS subjects decoupling each chain step, trigger detection becomes a natural consumer in the message flow rather than a post-hoc re-run.

**Design (sketch — refine when AD-637 lands):**

Three options, not mutually exclusive:

1. **Intercept consumer.** A trigger-detection consumer subscribes to `chain.{agent_id}.compose.complete`. It inspects compose output for undeclared actions, enriches the observation with `_undeclared_action_feedback`, and forwards to `chain.{agent_id}.evaluate`. REFLECT receives feedback naturally — no re-run.

2. **BPMN-style gateway.** Exclusive gateway after COMPOSE: clean path (no undeclared actions) routes directly to EVALUATE; feedback path routes through DETECT → ENRICH → EVALUATE. Maps to BPMN 2.0 (ISO 19510:2013) process modeling. The chain becomes a declarative flow graph, not imperative code.

3. **Retriggerable REFLECT.** REFLECT subscribes to `chain.{agent_id}.reflect`. On undeclared action detection, publish a second message to the same subject with feedback. Both reflections enter episodic memory. Zero chain modification.

**What survives from AD-643b:** `_detect_undeclared_actions()` detection logic, feedback format, `get_eligible_triggers()` awareness injection, graduation tracking (Phase 3). Only the orchestration wrapper (`_re_reflect_with_feedback`) gets replaced.

**What gets removed:** `_re_reflect_with_feedback()`, `_re_reflect_compose_output` observation key, `_get_compose_output()` fallback parameter.

| Decision | Choice | Rationale |
|----------|--------|-----------|
| DD-1 | Deferred until NATS lands | Re-reflect works; refactoring before NATS exists is premature |
| DD-2 | Option 1 (intercept) is likely default | Simplest, preserves single REFLECT execution, no duplicate episodic entries |
| DD-3 | AD-643b detection logic reused as-is | Pattern matching is transport-agnostic |
