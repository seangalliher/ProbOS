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

**Migration note (AD-644 Phase 3):** AD-644 Phase 3 migrates 7 environmental percepts (ward_room_activity, recent_alerts, recent_events, infrastructure_status, subordinate_stats, cold_start_note, active_game) into the cognitive chain via observation dict pass-through from `context_parts`. This is a temporary approach — `_gather_context()` in proactive.py already calls the underlying services, so creating QUERY operations that re-call the same services would violate DRY. When NATS decouples the pipeline (this AD), these 7 percepts should become native QUERY operations in `query.py` that subscribe to NATS subjects directly, replacing both the `_gather_context()` calls and the `_build_situation_awareness()` pass-through. The detection logic in `_build_situation_awareness()` is transport-agnostic and reusable.


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

---

### AD-644 — Agent Situation Awareness Architecture

**Date:** 2026-04-18
**Status:** Phase 1-4 Complete (full parity — 23/23 items). Phase 5 Design (deprecation).
**Issue:** #285

**Decision:** Migrate the ~23 context injections from the monolithic `_build_prompt_text()` into the cognitive chain architecture using a four-category model grounded in Endsley's Situation Awareness framework.

**Motivation:** When `proactive_think` was added to `_CHAIN_ELIGIBLE_INTENTS` (AD-632+), the chain path bypassed `_build_prompt_text()` — a 290-line function that had accumulated context injections across 15+ ADs. The chain's ANALYZE step receives standing orders (system prompt) but no dynamic data (user prompt). Result: agents return `intended_actions: ["silent"]` on every cycle, including scheduled duties. Zero duty reports produced in days of operation.

This is not a missing feature — it's an accidental regression. The cognitive chain provides better architecture than the single-call path, but the context it needs was never migrated.

**Design:** Four cognitive categories, each with a distinct mechanism:

| Category | What | Mechanism | Naval Analog |
|----------|------|-----------|-------------|
| **Innate Faculties** | Temporal awareness, working memory, self-monitoring, source attribution data, telemetry, ontology identity, orientation, confabulation guard, comm proficiency, trust/agency/rank | Populated into observation dict by agent before chain runs | Sailor knows the time, remembers what they just did, knows their chain of command, senses their own fatigue |
| **Situation Awareness** | Ward Room activity, infrastructure status, alerts, events, subordinate stats, crew status, cold-start notes, active games | QUERY step operations (`_QUERY_OPERATIONS` registry) | Sailor glances at status boards, hears bridge conversation, sees alert condition |
| **Watch Station Duties** | Active duty assignment, duty-specific instructions | `params.duty` → observation dict, ANALYZE renders duty context | Sailor reads their WQSB entry, holds their PMS card |
| **Standing Orders** | Self-monitoring rules, cognitive zones, communication protocols, source attribution policy, duty reporting expectations | `compose_instructions()` → system prompt (already works) | Sailor has memorized regulations and standing orders |

**Prompt consumers:** Both ANALYZE (`_build_situation_review_prompt`) and COMPOSE (`_build_proactive_compose_prompt`) are starved — both read `context.get("context", "")` which is empty. Both need updates: ANALYZE for full situation assessment, COMPOSE for duty framing, source attribution, confabulation guard, and comm proficiency.

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Four categories from cognitive science, not code organization | Endsley SA model (perception → comprehension → projection) maps to QUERY → ANALYZE → intended_actions. Categories scale independently |
| DD-2 | Innate faculties run for ALL chain executions, not just proactive_think | Temporal awareness and working memory are agent faculties, not intent-specific. A conscious agent always knows the time |
| DD-3 | Situation awareness via QUERY operations, not observation dict | QUERY operations are deterministic, dispatch-table registered, Open/Closed. New percepts added without modifying chain code |
| DD-4 | Duty context biases ANALYZE away from silence | When a duty is active, the agent has an obligation to report. Silence during duty requires explicit justification (inverted from free-form default) |
| DD-5 | Five implementation phases, independently deployable | Phase 1 (duty fix) is critical. Phases 2-4 restore full parity. Phase 5 deprecates `_build_prompt_text` proactive block |
| DD-6 | Standing orders additions are markdown-only, zero code changes | Source attribution and duty expectations are policy, not data |
| DD-7 | Source attribution split: policy (Cat 4) vs data (Cat 1) | Policy = behavioral guidance in standing orders. Data = episodic_count, procedural_count, oracle_used = innate self-knowledge |
| DD-8 | COMPOSE is a second consumer, not just ANALYZE | Both prompt templates render from the same observation dict. COMPOSE needs duty framing, source attribution, confabulation guard |

**Implementation phases:**
1. **Duty Context Restoration** — pass `params.duty` + trust/agency/rank through, update ANALYZE + COMPOSE prompts (critical fix)
2. **Innate Faculties** — `_build_cognitive_state()` populates temporal, working memory, self-monitoring, ontology, orientation, source attribution data, confabulation guard, comm proficiency
3. **Situation Awareness** — extend QUERY operations (ward_room_activity, infrastructure_status, recent_alerts, recent_events, subordinate_stats, cold_start_context, active_game)
4. **Standing Orders** — add source attribution policy + duty expectations to ship.md
5. **Deprecation** — mark `_build_prompt_text` proactive block as deprecated

**Parity:** 23-item checklist in research doc maps every `_build_prompt_text` injection to an AD-644 category and implementation phase.

**Research:** [docs/research/agent-situation-awareness-architecture.md](docs/research/agent-situation-awareness-architecture.md)

**Future:** Composes with AD-641g (NATS pipeline — percepts become NATS subscriptions), AD-618 (SOP Bills — duties become Bill triggers), AD-643a (intent routing — richer SA improves action decisions), AD-645 (Artifact-Mediated Chain — composition briefs replace routing slips).

---

### AD-645 — Artifact-Mediated Cognitive Chain

**Date:** 2026-04-18
**Status:** Phase 1-3 Complete (Composition Briefs + COMPOSE Enrichment + Metacognitive Storage)
**Parent:** AD-632 (Cognitive Chain Architecture)
**Related:** AD-644 (Situation Awareness), AD-641g (NATS Pipeline), AD-639 (Chain Personality Tuning), AD-573 (Working Memory)

**Decision:** Replace ANALYZE's thin routing-slip output (`intended_actions` + structured fields) with a **composition brief** — a structured plan that tells COMPOSE what to write about, what evidence to draw on, what tone to use, and what the response should cover. Additionally, pass environmental context (Phase 3 SA keys) through to COMPOSE so it has both the focused plan AND the raw material.

**Motivation:** AD-644 achieved full context parity (23/23 items) between the chain path and one-shot `_build_user_message()`, but chain-path responses remain measurably flatter, less confident, and less specific. Root cause: ANALYZE compresses its full situational understanding into a routing slip (~200 tokens of JSON), then COMPOSE works from that summary rather than the source material. The one-shot path gives the LLM everything at once; the chain loses information at the ANALYZE → COMPOSE handoff.

The architect/builder analogy: current ANALYZE is like saying "write a build prompt for phase 4" with no research. Proposed ANALYZE is like writing a detailed build prompt with evidence, scope, design decisions, and references. COMPOSE (the builder) reads the brief AND has access to the raw context — focused guidance + full material.

**Design:**

The composition brief contains:
- **situation** — what's happening (1-2 sentences)
- **key_evidence** — specific observations/data points COMPOSE should reference
- **response_should_cover** — what the response needs to address
- **tone** — audience-appropriate framing guidance
- **sources_to_draw_on** — which knowledge sources are relevant

`intended_actions` survives alongside the brief for programmatic skill routing (AD-643a).

**Artifact value beyond composition:**
- **Metacognitive memory** — stored in WorkingMemory as `category="reasoning"`, lets agent answer "What was I thinking?" Extends AD-573 from recording what happened to recording how the agent processed it.
- **Dream consolidation** — dreams can extract reasoning patterns, not just outcome patterns
- **Reinforcement signal** — EVALUATE assesses plan-to-output alignment: (brief, response, score) triples
- **Cognitive forensics** — trace whether failures are perception errors (bad brief) or execution errors (ignored brief)
- **Self-monitoring** — detect narrowing reasoning patterns before they manifest as output repetition
- **Privacy preserved** — Minority Report Principle: briefs are agent's private cognitive workspace, Counselor has no access

**NATS alignment:** Build briefs before NATS. The brief format becomes the NATS message payload on `chain.{agent_id}.analyze.complete` when AD-641g lands. No throwaway work.

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Build briefs before NATS | Higher-value change; pre-shapes NATS message format |
| DD-2 | Brief is part of ANALYZE JSON, not separate file | Flows through existing `prior_results` mechanism |
| DD-3 | SA keys flow to both ANALYZE and COMPOSE | COMPOSE needs raw material, not just brief's summary |
| DD-4 | Briefs are private (Minority Report Principle) | Agent's working memory, not Counselor surveillance |
| DD-5 | Brief is optional/backward compatible | Missing brief falls back to current behavior |
| DD-6 | Metacognitive storage uses existing WorkingMemory | No new infrastructure needed |
| DD-7 | EVALUATE alignment is additive, not gating | Signal without changing pass/fail threshold initially |

**Implementation phases:**
1. **Composition Brief** — ANALYZE prompt + output schema enrichment
2. **COMPOSE Context Enrichment** — render brief + pass SA keys to COMPOSE
3. **Metacognitive Storage** — store briefs in WorkingMemory post-chain
4. **EVALUATE Brief Alignment** — plan-to-output alignment criterion
5. **NATS Schema** (deferred to AD-641g) — brief dict becomes message payload

**Research:** [docs/research/ad-645-artifact-mediated-cognitive-chain.md](docs/research/ad-645-artifact-mediated-cognitive-chain.md)

---

### AD-646 — Universal Cognitive Baseline

**Date:** 2026-04-19
**Status:** Complete
**Issue:** #288
**Parent:** AD-644 (Situation Awareness), AD-632 (Cognitive Chain Architecture)
**Related:** AD-645 (Artifact-Mediated Chain), AD-641g (NATS Pipeline), AD-573 (Working Memory)

**Decision:** Split cognitive context assembly into a universal baseline (agent-intrinsic, runs for ALL chain executions) and intent-specific extensions (registered per intent type). The baseline provides temporal awareness, working memory, episodic recall, source attribution, ontology identity, trust/rank, and cognitive zone — regardless of what triggered the cycle.

**Motivation:** AD-644 Phase 2 added innate faculties to the proactive chain path, but the implementation depends on `context_parts` populated by `proactive.py`'s `_gather_context()`. Ward Room notifications bypass the proactive loop, so `context_parts` is empty — agents enter ANALYZE knowing the thread content but nothing about themselves. Result: chain-path Ward Room responses are activity-level ("I've been conducting wellness checks") while the one-shot path produces insight-level responses ("157/118/85 unread messages, cognitive load at 40-75% of crisis threshold") because `_build_user_message()` injects the full cognitive state directly.

The core design flaw: context assembly is intent-specific instead of layered. Every new chain-eligible intent will need its own AD-644-style migration. The fix should be applied once at the trunk, not per branch.

**Design:**

```
┌─────────────────────────────────────────┐
│  Universal Cognitive Baseline           │  ← ALL chain executions
│  (temporal, working memory, episodic,   │
│   source attribution, ontology,         │
│   trust/rank, cognitive zone)           │
├─────────────────────────────────────────┤
│  Intent Extensions                      │  ← Per intent type
│  proactive_think: SA sweep, self-mon    │
│  ward_room_notification: thread context │
│  (future intents: their own extensions) │
└─────────────────────────────────────────┘
```

Split `_build_cognitive_state()` into:
- `_build_cognitive_baseline()` — agent-intrinsic, zero external dependencies, zero async calls. Reads from agent attributes (working memory, temporal context, ontology). Called unconditionally.
- `_build_cognitive_extensions(context_parts)` — depends on externally-gathered data (self-monitoring, notebook index, telemetry). Called only when `context_parts` is available.

Update thread analysis prompt (`_build_thread_analysis_prompt`) and ward_room compose prompt to consume baseline keys. Proactive path unchanged (gets baseline + extensions + SA).

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Baseline is agent-intrinsic, not service-dependent | Zero async calls, zero latency impact. Working memory, temporal context, ontology are all in-memory agent state |
| DD-2 | Self-monitoring stays in extensions (not baseline) | Self-monitoring data (self-similarity, cooldowns) is gathered by proactive.py. Working memory already covers cognitive zone and recent actions for the baseline case |
| DD-3 | Baseline pre-shapes NATS message envelope | Universal baseline becomes the standard payload on `chain.{agent_id}.analyze`. Extensions are intent-specific fields |
| DD-4 | Apply once, works for all current and future intents | No more per-intent migration work. New chain-eligible intents inherit the baseline automatically |
| DD-5 | ~500-700 tokens added to ward_room ANALYZE prompt | Well within Sonnet's budget. Working memory capped at 1500 tokens |

**Scope:** ~100 lines across 3 files (cognitive_agent.py, analyze.py, compose.py). Zero new modules. Zero new infrastructure.

**Implementation phases:**
1. Split `_build_cognitive_state()` → baseline + extensions
2. Update thread analysis prompt to consume baseline keys
3. Update ward_room compose prompt to consume baseline keys
4. Regression verification (proactive path unchanged)

**Research:** [docs/research/ad-646-universal-cognitive-baseline.md](docs/research/ad-646-universal-cognitive-baseline.md)

### AD-646b — Chain Cognitive Parity (Close One-Shot Gaps)

**Date:** 2026-04-19
**Status:** Complete
**Issue:** #289
**Parent:** AD-646 (Universal Cognitive Baseline), AD-632 (Cognitive Chain Architecture)
**Related:** AD-588 (Introspective Telemetry), AD-623 (DM Self-Monitoring), AD-575 (Self-Recognition), AD-568a (Oracle Service), BF-102 (Cold-Start Note)

**Decision:** Close the remaining data gaps between the chain ward_room path and the one-shot ward_room path by adding two new QUERY operations, three baseline enhancements, and consuming already-present observation keys in chain prompts.

**Motivation:** AD-646 established the universal cognitive baseline, giving ward_room chains temporal awareness, working memory, trust metrics, ontology, and confabulation guards. But the one-shot ward_room path still injects six data sources the chain path lacks:

| # | Data Source | One-Shot Path | Chain Path (post AD-646) | Gap Type |
|---|-------------|--------------|--------------------------|----------|
| 1 | DM self-monitoring (AD-623) | `_build_dm_self_monitoring()` — async | Missing | Async — needs QUERY |
| 2 | Introspective telemetry (AD-588) | `IntrospectiveTelemetryService.get_full_snapshot()` — async | Missing | Async — needs QUERY |
| 3 | Cold-start note (BF-102) | `rt.is_cold_start` check | Missing | Sync — baseline |
| 4 | Rich source attribution (AD-568d) | `observation["_source_attribution"]` dataclass render | Simplified count only | Sync — baseline |
| 5 | Self-recognition (AD-575) | `_detect_self_in_content()` — sync regex | Missing | Sync — baseline |
| 6 | Oracle context (AD-568a) | `observation["_oracle_context"]` render | Key present but not consumed by prompts | Prompt consumption |

These gaps are why chain ward_room responses still confabulate more than one-shot — agents lack self-monitoring, telemetry grounding, and cross-tier knowledge context.

**Design:**

Four-part fix, each independently testable:

**Part A — New QUERY Operations (query.py):**
- `self_monitoring`: For DM threads, call `ward_room.get_posts_by_author()` + Jaccard similarity (same pattern as `_build_dm_self_monitoring()`). For all threads, check cognitive zone from VitalsMonitor. Returns warning string or empty.
- `introspective_telemetry`: Conditionally on `_is_introspective_query()` against thread text, call `IntrospectiveTelemetryService.get_full_snapshot()` + `render_telemetry_context()`. Returns rendered text or empty.

**Part B — Baseline Enhancements (cognitive_agent.py `_build_cognitive_baseline()`):**
- Cold-start note: `rt.is_cold_start` boolean → `_cold_start_note` key.
- Rich source attribution: Read `observation["_source_attribution"]` dataclass (set by perceive/recall at line 4327), render episodic_count, procedural_count, oracle_used, primary_source. Override the simplified count-only version.
- Self-recognition: `_detect_self_in_content(observation.get("context", ""))` → `_self_recognition_cue` key.

**Part C — Chain Definition Update (cognitive_agent.py `_build_chain_for_intent()`):**
- Ward room chain at line 1554: add `self_monitoring` and `introspective_telemetry` to `context_keys`.

**Part D — Prompt Consumption (analyze.py + compose.py):**
- Oracle context: Add `_oracle_context` rendering to thread analysis prompt and compose `_build_user_prompt()`. Key is already in observation from perceive's `_recall_relevant_memories()`.
- Self-monitoring and telemetry: Render structured sections in thread analysis prompt from QUERY results (not raw "Prior Data" dump).
- Self-recognition and cold-start: Consume new baseline keys in thread analysis prompt.

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Async data via QUERY ops, not baseline | Baseline is sync-only by design (AD-646 DD-1). DM self-monitoring and telemetry require async ward_room/service calls |
| DD-2 | Telemetry is conditional on introspective query | Avoids unnecessary service calls + token budget for non-self-referential threads |
| DD-3 | Oracle context already in observation — just consume it | perceive() already calls `_recall_relevant_memories()` which sets `_oracle_context`. Zero new async calls needed |
| DD-4 | Rich attribution overrides simplified baseline | AD-646 baseline does a count-only attribution. When the `_source_attribution` dataclass is present (from perceive), render the full version with primary_source and oracle_used |
| DD-5 | Self-recognition is sync (regex) — belongs in baseline | `_detect_self_in_content()` is a regex scan, no async. Fits baseline's zero-async contract |

**Scope:** ~150 lines across 4 files (query.py, cognitive_agent.py, analyze.py, compose.py). Zero new modules. Zero new infrastructure. Reuses existing methods and services.

### AD-647 — Process-Oriented Cognitive Chains

**Date:** 2026-04-19
**Status:** Scoped
**Issue:** #291
**Parent:** AD-632 (Cognitive Chain Architecture), AD-618 (Bill System)
**Depends on:** AD-618 (Bills/SOPs), AD-595 (Watch Bill / Billet Registry), AD-641g (NATS Pipeline)
**Related:** AD-643a (Intent Routing), BF-209 (Scout chain bypass)

**Decision:** Implement process-oriented cognitive chains as a distinct chain type from the communication chain. Different business processes require different cognitive step sequences — not all agent work is "read thread → analyze → compose reply."

**Motivation:** BF-209 exposed a fundamental category error: the scout's duty-triggered report generation (a structured data pipeline) was forced through the communication chain (QUERY → ANALYZE → COMPOSE). The communication chain bypasses `act()`, so the scout's structured pipeline (parse → enrich → filter → store → notify) never ran. The report was always empty while Ward Room posts appeared.

The scout report is the first case, but the pattern applies to any structured process: incident response, qualification testing, maintenance procedures, data collection. These are **processes** with their own step sequences, not conversations.

**Design direction:**

- Process chains define step types beyond communication: QUERY (data gathering), TRANSFORM (classification/enrichment), STORE (persistence), NOTIFY (routing)
- Each step has its own prompt template or deterministic handler
- AD-618 (Bills/SOPs) provides declarative YAML process definitions
- AD-595 (Billets) provides role-based process assignment
- AD-641g (NATS) enables async step decoupling with process-specific message subjects
- Scout report is the reference implementation

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Communication chain and process chain are distinct types | Communication is interactive (read/analyze/compose). Process is pipeline (gather/transform/store/notify). Forcing one through the other loses structure |
| DD-2 | BF-209 is the interim fix until dependencies land | ScoutAgent opts out of chain for structured duties. Clean, principled, replaceable |
| DD-3 | Bills (AD-618) are the process definition format | YAML declarative procedures with BPMN decision points already designed for multi-step agent processes |

### AD-648 — Post Capability Profiles (Ontology Grounding for Confabulation Prevention)

**Date:** 2026-04-19
**Status:** Design
**Issue:** #292
**Parent:** AD-429 (Vessel Ontology)
**Related:** AD-427 (ACM Core), AD-428 (Skill Framework), AD-496 (Workforce Scheduling), AD-592 (Confabulation Guard), BF-204 (Grounding Checks)

**Decision:** Extend the ship's ontology with structured per-post capability profiles — what each post *actually does*, what tools/processes it uses, and critically what it *does not have*. Inject into prompt context via `_ontology_context` so agents have grounded factual knowledge of their own and each other's capabilities.

**Motivation:** Confabulation audit (2026-04-19) found 628 contaminated Ward Room posts (11.8%), 90+ contaminated episodic memories, 10+ confabulated notebook entries, and 8 agents with contaminated working memory — all from a single false narrative: "the scout has sensors." The scout searches GitHub repos. There are no sensors, no telemetry, no scan coverage metrics. Six agents built an elaborate shared fiction including architecture specs, diagnostic protocols, and fabricated correlations.

Existing confabulation guards (BF-204 hex ID detection, AD-592 "don't fabricate numbers") catch *data confabulation* but not *conceptual confabulation* — agents inventing wrong mental models about what roles do. The ontology tells Wesley he's "Scout in Science department" but never says what the scout *actually does*. Agents fill that gap with plausible inference, and when they infer wrong, the false model self-reinforces through episodic memory contamination.

The same pattern appeared at identical 12% rate across two different crews (pre-reset and post-reset), confirming it's structural, not crew-specific.

**Design:**

Phase 1 — Post capability declarations in `organization.yaml`:

```yaml
posts:
  - id: scout_officer
    title: "Scout"
    department: science
    reports_to: chief_science
    capabilities:
      - id: github_search
        summary: "Search GitHub for trending/relevant repositories"
        tools: [search_github]
        outputs: [scout_report_json]
      - id: scout_report
        summary: "Classify findings as ABSORB/VISITING_OFFICER/SKIP and generate structured report"
        outputs: [scout_report_file, ward_room_notification]
    does_not_have:
      - "sensors or sensory arrays"
      - "telemetry or scan coverage metrics"
      - "detection thresholds or calibration"
      - "environmental scanning or reconnaissance hardware"
```

Phase 2 — Ontology service extension:
- New `PostCapability` dataclass in `models.py`
- `get_crew_context()` includes `capabilities` and `does_not_have` in returned dict
- New `get_post_capabilities(post_id)` method for cross-agent queries ("what does Wesley do?")

Phase 3 — Prompt injection:
- `_build_ontology_context()` renders capability profile into `_ontology_context`
- Format: "Your capabilities: [list]. You do NOT have: [list]."
- Cross-agent capability lookups available in QUERY step for "what does X do?" questions

**OSS/Commercial boundary:** Capability profiles are OSS — they're confabulation prevention infrastructure, not commercial value-add. Commercial ACM (AD-C-010+) and ASA (AD-C-015) build on this foundation:
- ACM reads `capabilities` for consolidated agent profiles, workforce analytics, skill-based compensation
- ASA reads `capabilities` for `ResourceRequirement` matching — schedule agent X because it has capability Y
- Commercial extensions add: dynamic capability discovery, proficiency ratings per capability, utilization tracking per capability, marketplace profile generation

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Capabilities attach to posts, not agent_types | Posts are the unit of organization. Multiple agent_types could fill the same post. Matches Navy billet model — the billet defines the job, not the person filling it |
| DD-2 | Negative grounding (`does_not_have`) is as important as positive | Agents confabulate by filling knowledge gaps. Explicitly closing gaps ("you do not have sensors") prevents the inference chain that creates false narratives |
| DD-3 | All 18 posts get capability profiles, not just scout | The scout was the first failure. Any post without grounded capabilities is vulnerable to the same pattern. Proactive, not reactive |
| DD-4 | Cross-agent capability visibility | Agents must know what *other* agents do, not just themselves. Sage demanded "sensor telemetry" from Wesley because Sage didn't know Wesley searches GitHub. Peer capability awareness prevents collaborative confabulation |
| DD-5 | OSS foundation, commercial overlay | Capability profiles prevent confabulation (OSS concern). ACM/ASA consume them for workforce management (commercial concern). Same data, different consumers |
| DD-6 | `tools` field links to actual tool registry | Each capability references the actual tools/functions used. Grounds the capability in verifiable system reality, not free-form description |

**Scope:** Design + implementation after AD-618, AD-595, AD-641g land. Scout report as first case.

### AD-649 — Communication Context Awareness for Cognitive Chain

**Date:** 2026-04-19
**Status:** Complete
**Issue:** #293
**Related:** AD-639 (Trust-Band Tuning), AD-645 (Composition Briefs), AD-646/646b (Cognitive Baseline/Parity)

**Decision:** Add prescriptive communication context (channel type, audience, register) to the cognitive chain so COMPOSE adapts output format based on where and to whom the agent is communicating. Brings chain output quality toward parity with the one-shot path.

**Motivation:** The chain produces formal, clinical output regardless of context. Two agents (Ezri/Counselor, Nova/Operations) independently diagnosed the same problem when shown their chain vs one-shot responses to the same question. Both identified that COMPOSE defaults to "the most formal register because that feels safer professionally" (Ezri) and produces "crisis management checklist" output instead of operational analysis (Nova). The one-shot path works well because the LLM natively handles audience adaptation — but this is a fragile dependency on emergent model capability. The chain must encode desired behavior prescriptively (LLM Independence Principle).

**Design:**

- Part A: Derive `_communication_context` from existing `channel_name`/`is_dm_channel` — five registers: private_conversation, bridge_briefing, casual_social, ship_wide, department_discussion
- Part B: Add communication context to ANALYZE composition_brief tone guidance — prescriptive register descriptions
- Part C: Add "Speak in your natural voice" to COMPOSE ward_room prompt (parity with one-shot). Register-specific framing per channel type. "Show your reasoning, not just conclusions."

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Five registers derived from channel_name | Maps to existing channel types (ship, department, dm, recreation, custom). No new infrastructure needed |
| DD-2 | Voice parity with one-shot path | Chain ward_room compose was missing "Speak in your natural voice" that one-shot has. Direct gap, direct fix |
| DD-3 | Prescriptive register guidance, not implicit | LLM Independence Principle: chain must produce good output with a less capable model. Encode register expectations explicitly so behavior doesn't depend on emergent model capability |
| DD-4 | "Show reasoning, not just conclusions" | Nova diagnosed that chain strips analytical reasoning. Conclusions without reasoning context are useless for decision-making |
| DD-5 | Department channel is default (no extra constraint) | Natural LLM behavior is correct for peer discussion. Only add constraints for specialized contexts (bridge, recreation, ship-wide) |

**Scope:** ~80 lines across 2 files (cognitive_agent.py, compose.py, analyze.py). 14 tests. Zero new modules.

### AD-650 — Analytical Depth Enhancement

**Date:** 2026-04-19
**Status:** Complete
**Issue:** #294
**Related:** AD-645 (Composition Briefs), AD-646/646b (Cognitive Baseline/Parity), AD-649 (Communication Context)

**Decision:** Enrich the composition brief with a narrative reasoning field and add depth instructions to COMPOSE so the cognitive chain surpasses one-shot output quality on analytical depth — counterarguments, meaning extraction, philosophical nuance.

**Motivation:** AD-649 brought the chain to functional parity on register and tone. But 7 A/B comparison tests revealed the chain consistently underperforms on depth: one-shot produces counterarguments ("fresh eyes" perspective), coined vocabulary ("cognitive load clustering"), and diagnostic insights (using game behavior to read leadership styles). The chain produces broader factual coverage but shallower reasoning. Root cause: the composition brief is an information bottleneck — ANALYZE reasons deeply then compresses to 5 structured fields, losing conditional logic ("because X, therefore Y matters more than Z"). Research grounding: Chain-of-Thought (Wei et al. — intermediate reasoning is load-bearing), DSPy (Stanford — field descriptions are optimization targets), Lost in the Middle (Liu et al. — context positioning matters), Self-Refine (Madaan et al. — can't recover info never passed through bottleneck), OpenMythos/COCONUT (input re-injection prevents representation drift).

**Design:**

- Part A: Add `analytical_reasoning` narrative field to composition_brief in all 3 ANALYZE modes. Reframe brief from "plan for composing" to "analytical reasoning and composition plan." Explicit "narrative prose, not bullets" instruction.
- Part B: COMPOSE renders `## Analytical Reasoning` section. Bold-header suppression for ALL Ward Room branches (was only in private_conversation and DM). Depth instruction ("Don't just summarize — interpret") in all compose modes.

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Narrative reasoning field, not more structured fields | CoT research: conditional logic ("because X, therefore Y") is lost in structured extraction. Narrative preserves the "because" relationships that make reasoning transferable |
| DD-2 | Reframe brief as "analytical reasoning + plan" | Current framing ("plan for composing") tells the LLM to plan, not reason. Framing shapes output |
| DD-3 | Bold-header suppression in ALL Ward Room branches | Testing showed headers regress on multi-point responses in department_discussion, bridge_briefing, etc. Only private_conversation and DM had suppression |
| DD-4 | "Don't just summarize — interpret" as prescriptive depth instruction | One-shot produces depth spontaneously. LLM Independence Principle: make it prescriptive so it works across models |
| DD-5 | Original context still flows to COMPOSE (no change) | Verified: COMPOSE already receives original thread via `context["context"]`. The bottleneck is brief content, not context availability (OpenMythos input re-injection is already in place) |

**Scope:** ~120 lines across 2 files (analyze.py, compose.py). 12 tests. Zero new modules.

### AD-651 — Standing Order Decomposition for Cognitive Chain Steps

**Date:** 2026-04-20
**Status:** Design
**Issue:** #299
**Parent:** AD-632 (Cognitive Chain Architecture)
**Depends on:** AD-647 (Process Chains), AD-641g (NATS Pipeline)
**Related:** AD-646 (Universal Baseline), BF-213 (Analyze Silence Bias)

**Decision:** Decompose monolithic standing orders into step-specific billet instructions for the cognitive chain. Standing orders were designed for the one-shot world — the chain decomposes cognition into steps but injects the same ~2K token document at multiple steps. Each chain step is a billet with its own task-specific instructions, decision space, and operational context.

**Motivation:** BF-213 exposed that standing orders' "When to act vs. observe" decision tree has no effect at the ANALYZE step because the step's own framing ("Silence is professionalism") overrides it. The decision tree is an assessment rubric that belongs in ANALYZE's prompt, not in a general document. The one-shot path never had this problem because assessment and composition happened in the same LLM call — standing orders influenced both simultaneously. The chain splits the cognitive function but doesn't split the instructions to match. AD-647 (Process Chains) already frames steps as billets with their own templates — this AD generalizes that pattern to the communication chain.

**Design:**

- Standing orders split into: identity-level guidance (character, federation/ship values, active directives — stays in standing orders, constitutional preamble at every step) + operational instructions (moves into step prompts as billet instructions)
- ANALYZE gets: decision tree, action vocabulary descriptions, authority scope
- COMPOSE gets: action tag syntax, communication discipline, register guidance
- EVALUATE/REFLECT gets: quality criteria
- Phase 1: extract decision tree into ANALYZE prompt (near-term, standalone)
- Phase 2: billet instruction format in Bill YAML (with AD-647)
- Phase 3: NATS envelope `billet_instructions` field (with AD-641g)

**Key insight:** In one-shot, the model sees everything and makes holistic judgments. In the chain, each step is a specialist. Giving every specialist the entire manual wastes tokens and buries relevant instructions. But over-decomposing risks steps that are too narrowly scoped — identity/values must remain at every step as a constitutional baseline.

**Research:** `docs/research/standing-order-decomposition.md`

### AD-652 — Cognitive Code-Switching: Unified Pipeline with Contextual Modulation

**Date:** 2026-04-20
**Status:** Design Principle (adopted)
**Issue:** #302
**Parent:** AD-632 (Cognitive Chain Architecture)
**Related:** AD-651 (Billet Instructions), AD-639 (Chain Personality Tuning), AD-647 (Process Chains)

**Decision:** The cognitive chain is a single unified pipeline, not parallel pipelines for different communication types. Different cognitive tasks (duty reports vs. casual observations vs. DM responses) are handled through contextual modulation of the same pipeline — variable chain depth, tenor-aware compose framing, and structured format overlays — not by branching into separate architectures.

**Motivation:** The chain pipeline (AD-632) introduced uniform rigidity — the same QUERY → ANALYZE → COMPOSE → EVALUATE → REFLECT sequence runs for duty reports and casual social posts alike. AD-639 identified that this strips personality. AD-651 introduced billet instructions to add structure for operational outputs. The question arose: should ProbOS maintain separate cognitive pipelines for structured vs. creative work?

Cognitive science research (Levelt, Halliday, Giles, Snyder, Weick/Sutcliffe) converges on a clear answer: humans use one language production system with contextual modulation, not parallel systems. Register switching (code-switching) adjusts parameters within a unified pipeline. Military formal protocols are trained overlays on natural language capacity, not separate cognitive systems.

**Design Principles:**

1. **Unified Pipeline** — one chain framework. Identity continuity requires architectural unity. An agent must sound like themselves across duty reports and mess-hall conversation.
2. **Contextual Modulation** — Halliday's field (topic), tenor (formality), and mode (channel) parameters modulate chain behavior: step composition, framing prescriptiveness, format overlays.
3. **Structured Format Overlays** — institutional outputs use billet instructions as cognitive scaffolding (per HRO research). Duty reports, proposals, formal briefings get prescriptive format templates.
4. **Variable Chain Depth** — high-structure tasks get more steps with prescriptive framing. Low-structure tasks get fewer steps with lighter framing. Same pipeline, different configurations.
5. **Character-Driven Self-Monitoring** — code-switching range is a personality parameter (Snyder's Self-Monitoring Theory), not a pipeline decision. Derived from Big Five traits.
6. **Process-Specific Chains** — fundamentally different cognitive tasks can have different step compositions and mode keys. But if two tasks are the same process with different context, they share the chain and modulate parameters.

**Key insight:** The situation selects the register, not a pipeline branch. Like a chat temperature slider from formal to friendly — but the modulation is in prompt context and instructions, not literal LLM temperature. Billet instructions are hard constraints that override for specific output types; tenor is the soft modulation for everything else.

**Research:** `docs/research/cognitive-code-switching-research.md`

### AD-653 — Dynamic Communication Register: Self-Monitored Register Shifting

**Date:** 2026-04-20
**Status:** Design
**Issue:** #303
**Parent:** AD-652 (Unified Pipeline / Contextual Modulation)
**Depends on:** AD-652, AD-504 (Self-Monitoring), AD-651 (Billet Instructions)
**Related:** AD-506 (Self-Regulation), AD-639 (Chain Personality Tuning)

**Decision:** Extend the unified cognitive pipeline (AD-652) with agent-initiated dynamic register shifting. Agents self-monitor their communication register, detect when the assigned register constrains important output, and request a temporary shift ("speak freely" protocol). The shift is trust-gated, temporally scoped, and observable by the Counselor.

**Motivation:** AD-652 established contextual modulation as a top-down mechanism — the system selects register based on context (duty → formal, social → casual). But situations arise where an agent recognizes that the assigned register is flattening something important: a duty report that needs a candid personal assessment, an observation that contradicts the expected structured format, or a finding too nuanced for template framing. In military protocol, "permission to speak freely" solves this — a recognized protocol for situations where protocol itself is the obstacle.

**Prior art survey (confirmed first-of-kind):** No existing multi-agent framework implements self-monitored register shifting. AutoGen/CrewAI/MetaGPT fix communication style at initialization. Reflexion/MARS/MUSE self-assess reasoning quality, never communication register. PromptBreeder evolves prompts across runs but not mid-task. DRESS controls style externally, not agent-initiated. CAMEL enforces role consistency, never escape. Stanford Generative Agents produce emergent style but agents have zero awareness of their own communicative constraints.

**Design:**

Three layers, each buildable independently:

1. **Register Classification Taxonomy** — finite label set (formal_report, professional, collegial, casual, speak_freely) with mapped chain parameters (depth, framing weight, format overlay, personality weight).

2. **Modulation Pattern Templates** — pre-defined configurations mapping (register × process) → chain parameters. Billet instructions (AD-651) are one component; templates bundle billet selection + framing weight + chain depth + personality weight.

3. **Dynamic Register Shift ("Speak Freely")** — ANALYZE detects register-task mismatch → outputs `"speak_freely"` in intended_actions → trust-gated authorization (≥0.7 auto-granted, 0.4-0.7 flagged, <0.4 denied) → COMPOSE receives minimal-constraint framing → shift scoped to single invocation → Counselor receives REGISTER_SHIFT event for pattern tracking.

**Novel contribution:** First implementation of agent self-aware communication register management. Structure AND emergence, not OR — the emergence escape hatch is itself structured, gated by trust, and observable. "Protocol for breaking protocol."

**Research:** `docs/research/dynamic-communication-register-research.md`
