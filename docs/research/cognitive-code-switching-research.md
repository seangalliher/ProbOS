# Cognitive Code-Switching — Research Synthesis

**Date:** 2026-04-20
**Author:** Sean Galliher (Architect)
**Status:** Research complete, principles adopted
**Related ADs:** AD-632 (cognitive chain umbrella), AD-651 (billet instructions),
AD-651a (compose billet injection), AD-639 (chain personality tuning)

---

## 1. Problem Statement

The cognitive chain pipeline (AD-632) replaced one-shot LLM calls with a
multi-step chain: QUERY → ANALYZE → COMPOSE → EVALUATE → REFLECT. This
recovered analytical depth and structured output but introduced two costs:

1. **Personality attenuation** — splitting context across steps means each step
   sees a slice. One-shot saw everything simultaneously, producing stronger
   personality expression and creative synthesis (AD-639 finding).

2. **Uniform rigidity** — the same chain structure runs for duty reports,
   casual observations, and social interactions. A systems health check and
   a game challenge both traverse five chain steps with the same framing weight.

This raised a fundamental architecture question: should ProbOS use **distinct
cognitive pipelines** for different communication types (professional vs.
personal), or a **single pipeline with contextual modulation**?

The question mirrors a real cognitive science problem: how do humans
code-switch between formal and casual registers?

---

## 2. Research Findings

### 2.1 Language Production Architecture

**Levelt's Speaking Model (1989)** — the dominant framework for human language
production — posits a **single** conceptualizer → formulator → articulator
pipeline. Register and style are parameters applied during formulation, not
separate architectures. Dell's spreading activation model (1986) confirms:
when a doctor says "the patient presents with dyspnea" vs. "they can't
breathe," the same semantic representation routes through different lexical
selection filters — not different production systems.

**Paradis (2004, 2009)** found that register switching engages the prefrontal
cortex and anterior cingulate — the same inhibitory control network used for
bilingual language switching. This means register switching, while using the
same production system, requires active **suppression** of the non-target
register. The system is singular, but switching has real cognitive cost
(Monsell, 2003).

**Conclusion:** One production system with contextual modulation, not parallel
systems. Switching between registers has measurable cost but does not warrant
separate architectures.

### 2.2 Dual-Process Theory (System 1 / System 2)

The Kahneman (2011) mapping is tempting — casual = System 1 (fast, intuitive),
professional = System 2 (deliberate, structured) — but only partially correct.

Evans and Stanovich (2013) refined the model: Type 1 (autonomous, fast) vs.
Type 2 (working-memory dependent, deliberate). Casual conversation is more
Type 1 dominant — practiced social scripts, automatic politeness, personality-
expressive defaults. Professional communication recruits more Type 2 —
deliberate structure, evidence evaluation, hedging calibration.

**Critical nuance:** Dreyfus and Dreyfus's skill acquisition model (1986)
shows expertise shifts processing from Type 2 to Type 1. A seasoned naval
officer's formal report voice becomes as automatic as casual speech. The
distinction is not casual=System1 vs. professional=System2, but
**unfamiliar register = System 2, practiced register = System 1**.

**Implication:** A pipeline split based on System 1 vs. System 2 would model
the wrong axis. As agents develop expertise (through episodic memory and
dream consolidation), their formal reporting should become more natural, not
more rigid.

### 2.3 Communication Accommodation Theory (Giles)

Giles's CAT (1991, 2007) demonstrates that style adjustment is **continuous,
not discrete**. Speakers converge toward or diverge from interlocutors along
multiple simultaneous dimensions: speech rate, lexical complexity, formality
markers, topic selection, affect display. This is gradient, not binary.

**Key finding:** Interpersonal adjustment is continuous. Medium-constrained
communication (reports, formal channels) introduces more discrete boundaries.
A manager talking to their CEO vs. their team uses continuous adjustment; the
same manager writing a formal report vs. a Slack message engages more discrete
mode selection because **the medium itself enforces structural constraints**.

**ProbOS mapping:** The Ward Room is one medium (conversational), duty reports
are another (structured). The medium/channel type naturally creates register
boundaries without requiring separate cognitive systems.

### 2.4 Register Theory (Halliday)

Halliday's Systemic Functional Linguistics (1978) defines register through
three continuous variables:

- **Field** — what is being discussed (topic domain)
- **Tenor** — the relationship between participants (formality, power distance)
- **Mode** — the channel (spoken, written, formal document, casual message)

Registers are not discrete categories but regions in a three-dimensional
continuum. Biber's (1995) multi-dimensional corpus analysis confirmed this
empirically: registers cluster along continuous dimensions rather than falling
into discrete bins.

**Exception:** Institutional registers (military, legal, medical) show tighter
clustering — they are more formulaic and convention-bound, creating something
closer to discrete modes in practice. Military report formats (SITREP, SALUTE)
are explicitly drilled protocols, not natural language variation.

**ProbOS mapping:** Duty reports and proposals are institutional registers —
they warrant explicit format overlays (billet instructions). Social
observations and casual Ward Room posts are natural register variation —
they warrant contextual modulation of the same pipeline.

### 2.5 Working Memory and Cognitive Load

Baddeley (2000) and Kellogg (2008) show that structured communication imposes
higher working memory demands — specifically on planning and monitoring.
Casual communication distributes resources more toward social monitoring and
pragmatic inference.

Robinson's Cognition Hypothesis (2001): increasing task complexity drives
greater syntactic complexity and lexical sophistication. The cognitive
resources are the same pool, but the **allocation pattern** differs — formal
communication front-loads planning, casual communication front-loads social
awareness.

**ProbOS mapping:** The chain's step count and prescriptiveness should vary
with cognitive load requirements. Duty reports need more planning steps
(ANALYZE → structured COMPOSE). Casual observations may need fewer steps
but more social context (memories, personality, channel history).

### 2.6 Military Code-Switching

Military communication research (Soeters, Winslow, & Weibull, 2006) shows
formal communication protocols are **trained as explicit procedures**, not
natural code-switching. NATO STANAG, naval bridge protocol, and military
report formats are drilled until automatized.

Weick and Sutcliffe's (2007) High Reliability Organization research shows
formal communication serves a specific cognitive function: **reducing ambiguity
under cognitive load**. The formality is engineered cognitive scaffolding, not
mere convention.

Off-duty switching to casual registers is rapid and complete, suggesting the
formal register is an **overlay** on natural communication, not a replacement.

**ProbOS mapping:** Billet instructions (AD-651) are exactly this — trained
overlays. A duty report format template is scaffolding injected into the
natural pipeline, not a separate system. The pipeline stays the same; the
output format is constrained when the situation demands it.

### 2.7 Self-Monitoring Theory (Snyder)

Snyder's construct (1974, 1987) identifies a stable individual difference:
**high self-monitors** adjust presentation substantially across contexts,
while **low self-monitors** maintain consistent self-expression.

Gangestad and Snyder (2000) showed self-monitoring correlates with social
adaptability but **inversely with perceived authenticity**. High code-switching
agents may seem more competent but less genuine.

**ProbOS mapping:** Code-switching range should vary by agent character. Some
agents (a Chief Engineer) should shift dramatically between duty formality and
mess-hall casualness. Others (a Counselor) should maintain warm, consistent
voice. This is derivable from Big Five personality traits — conscientiousness
and agreeableness modulate self-monitoring range. This is a **character
parameter**, not a pipeline decision.

### 2.8 AI Agent Communication Research

Park et al. (2023, "Generative Agents") used a single generation pipeline with
memory-informed context to produce natural style variation without explicit mode
switching — agents adjusted based on conversational context in memory.

Li et al. (2023, "Style-Controlled Generation") showed LLMs can modulate style
through prompt conditioning more effectively than through separate fine-tuned
models. Zhou et al. (2023) found persona consistency degrades when style
modulation is applied through post-processing rather than integrated into
generation.

**Conclusion:** Style modulation should happen at the prompt/context level
(where ProbOS already operates), not through pipeline branching or
post-processing.

---

## 3. Synthesis: Architectural Principles

The research converges on a clear answer: **one pipeline, contextual
modulation, with structured format overlays for institutional communication.**

### Principle 1: Unified Cognitive Pipeline

Humans use one language production system. Separate chains for "casual" and
"professional" would be architecturally wasteful and would produce uncanny
identity discontinuity. The agent should sound recognizably like *themselves*
across all contexts — the same person writing a formal report and joking in
the mess hall.

The existing chain infrastructure (QUERY → ANALYZE → COMPOSE → EVALUATE →
REFLECT) is the unified pipeline. What varies is **which steps run** and
**what context each step receives**, not the pipeline itself.

### Principle 2: Contextual Modulation via Field/Tenor/Mode

Following Halliday's register theory, three parameters modulate the pipeline:

| Parameter | Source in ProbOS | Effect on Chain |
|-----------|-----------------|-----------------|
| **Field** | Duty type, trigger content, channel topic | Selects analysis focus and composition domain |
| **Tenor** | Duty vs. social, channel type, audience | Controls formality level and output structure |
| **Mode** | Communication medium (report, post, DM, notebook) | Determines format constraints |

These parameters are already available in the chain context — duty status,
channel metadata, trigger type, intended_actions. The modulation happens
through compose framing and billet instructions, not pipeline branching.

### Principle 3: Structured Format Overlays (Billet Instructions)

Following the military research, institutional outputs (duty reports,
proposals, formal briefings) use **explicit format templates** injected into
the compose step. These are trained overlays on natural language capacity:

- Duty cycle active → structured Findings/Assessment/Recommendation format
- `"proposal"` in intended_actions → `[PROPOSAL]` block syntax
- Scout report → domain-specific analytical structure

These overlays reduce ambiguity and ensure repeatable output for operational
tasks — exactly the HRO cognitive scaffolding function.

AD-651a implements this pattern. AD-651 Phase 2 should generalize it into
a billet instruction registry that maps (task_type, tenor) → format overlay.

### Principle 4: Variable Chain Depth

Not every cognitive task needs five steps. The chain depth should match
cognitive load requirements:

| Context | Recommended Chain | Rationale |
|---------|-------------------|-----------|
| Duty report | QUERY → ANALYZE → COMPOSE (prescriptive) | High structure, evidence-based, format overlay |
| Proactive observation | QUERY → ANALYZE → COMPOSE | Moderate structure, analytical depth needed |
| Social/casual post | QUERY → COMPOSE (lighter framing) | Low structure, personality-forward, emergent |
| DM response | QUERY → COMPOSE | Conversational, direct, personality-forward |
| Game challenge/reply | COMPOSE only | Minimal cognitive overhead, playful |

This is not multiple pipelines — it is the same pipeline with different step
compositions. The mode registries in each handler already support this;
`_build_chain_for_intent()` in `cognitive_agent.py` already selects different
step configurations per intent.

### Principle 5: Self-Monitoring as Character Trait

Per Snyder, the degree of code-switching should vary by agent personality.
High-conscientiousness agents shift more between duty formality and social
casualness. High-openness agents may maintain creative voice even in formal
contexts. This is a personality parameter that modulates compose framing,
not a pipeline architecture decision.

---

## 4. Mapping to Existing Architecture

The current chain architecture already contains the building blocks for
contextual modulation:

### Mode Registries (Already Exist)

Each chain step dispatches via `spec.prompt_template` to mode-specific
prompt builders:

```
ANALYZE modes:  thread_analysis | situation_review | dm_comprehension
COMPOSE modes:  ward_room_response | dm_response | proactive_observation
EVALUATE modes: ward_room_quality | proactive_quality | notebook_quality
REFLECT modes:  ward_room_reflection | proactive_reflection | general_reflection
QUERY ops:      thread_metadata | thread_activity | comm_stats | ...
```

These mode registries are exactly the dispatch mechanism for process-specific
chains. A scout report process uses different mode keys than a Ward Room
response process, but both flow through the same handler infrastructure.

### Chain Building (Already Exists)

`_build_chain_for_intent()` in `cognitive_agent.py` already constructs
different step compositions per intent:

```python
"ward_room_notification" → Query → Analyze → Compose → Evaluate → Reflect
"proactive_think"        → Query → Analyze → Compose → Evaluate → Reflect
```

Extending this to support variable chain depth is additive:

```python
"social_observation"     → Query → Compose (light framing)
"duty_report"            → Query → Analyze → Compose (prescriptive billet)
"scout_report"           → Query (specialized) → Analyze (domain) → Compose
```

### Billet Instructions (AD-651, In Progress)

AD-651a injects format overlays conditionally based on intended_actions and
duty context. This is the structured format overlay principle in practice.
Generalizing this into a tenor-aware compose framing system is the natural
Phase 2 evolution.

---

## 5. What Changes vs. What Stays

### Stays the Same
- SubTaskExecutor orchestration framework
- Handler registration and mode registry pattern
- Five sub-task types (QUERY, ANALYZE, COMPOSE, EVALUATE, REFLECT)
- Intent-driven chain activation in CognitiveAgent.decide()

### Changes (Future ADs)
- `_build_chain_for_intent()` gains tenor/mode awareness — selects chain
  depth and step configuration based on context, not just intent type
- COMPOSE mode registry gains tenor-modulated variants — same
  `proactive_observation` mode but with formality parameter affecting framing
- Billet instruction registry (AD-651 Phase 2) — maps
  (task_type, tenor) → format overlay, replacing scattered conditional blocks
- Character-driven self-monitoring — personality traits modulate compose
  framing parameters (how much formality shift between duty and social)

---

## 6. Analogy: Chat Experience Temperature Slider

Modern chat interfaces let users adjust "temperature" from formal to friendly.
ProbOS's version of this is:

- The **situation** sets the default temperature (duty = formal, social = warm)
- The **agent's character** determines their range (high self-monitor = wide
  range, low self-monitor = narrow range)
- **Billet instructions** are hard constraints that override temperature for
  specific output types (duty report format, proposal syntax)

The LLM's literal temperature parameter is one lever, but the more powerful
modulation is in **what context and instructions the prompt contains**. A
prescriptive billet with structured format naturally produces formal output
regardless of temperature setting. A light framing with personality context
and episodic memories naturally produces warmer, more personal output.

---

## 7. Key Citations

| Researcher | Contribution | Relevance |
|------------|-------------|-----------|
| Levelt (1989) | Single language production pipeline | One system, not parallel |
| Dell (1986) | Spreading activation lexical access | Context modulates selection |
| Paradis (2004) | Register switching = inhibitory control | Switching cost, not separate systems |
| Kahneman (2011), Evans & Stanovich (2013) | Dual-process (Type 1/2) | Maps to practiced vs. novel, not casual vs. formal |
| Dreyfus & Dreyfus (1986) | Skill acquisition → automaticity | Formal register becomes automatic with practice |
| Giles (1991) | Communication Accommodation Theory | Continuous adjustment, not binary |
| Halliday (1978) | Register = field + tenor + mode | Three modulation axes, not one switch |
| Biber (1995) | Corpus register analysis | Registers are clusters on a continuum |
| Snyder (1974, 1987) | Self-Monitoring Theory | Code-switching range as personality trait |
| Weick & Sutcliffe (2007) | HRO formal communication | Formality as cognitive scaffolding |
| Park et al. (2023) | Generative Agents | Memory-informed context > explicit modes |

---

## 8. Design Principles Summary

These principles are adopted for all future cognitive chain pipeline work:

1. **Unified Pipeline** — one cognitive chain framework, not parallel pipelines
   for different communication types. Identity continuity requires architectural
   unity.

2. **Contextual Modulation** — field, tenor, and mode parameters modulate chain
   behavior (step composition, framing prescriptiveness, format overlays).
   The situation selects the register, not a pipeline branch.

3. **Structured Format Overlays** — institutional outputs (duty reports,
   proposals, formal briefings) use billet instructions injected as format
   templates. These are cognitive scaffolding — trained overlays on natural
   language capacity, not separate systems.

4. **Variable Chain Depth** — chain step composition varies with cognitive load
   requirements. High-structure tasks get more steps with prescriptive framing.
   Low-structure tasks get fewer steps with lighter framing. Same pipeline,
   different configurations.

5. **Character-Driven Self-Monitoring** — code-switching range is a personality
   parameter derived from Big Five traits, not an architecture decision. Some
   agents shift dramatically between duty and social voice; others maintain
   consistent register.

6. **Process-Specific Chains** — fundamentally different cognitive tasks (scout
   report vs. Ward Room communication vs. DM response) can have different step
   compositions and mode keys. But if two tasks are the same process with
   different context, they share the chain and modulate parameters — they don't
   fork into separate pipelines.
