# Dynamic Communication Register — Research Synthesis

**Date:** 2026-04-20
**Author:** Sean Galliher (Architect)
**Status:** Research complete, AD scoped
**Related ADs:** AD-652 (Unified Pipeline / Contextual Modulation), AD-651 (Billet
Instructions), AD-504 (Self-Monitoring), AD-506 (Self-Regulation)

---

## 1. Problem Statement

AD-652 established that ProbOS's cognitive chain should be a unified pipeline
with contextual modulation — not parallel systems for different communication
types. But AD-652 frames modulation as **top-down**: the system determines
register based on context (duty → formal, social → casual). This leaves a
gap: what happens when the agent recognizes that the assigned register is
constraining something important it needs to communicate?

In military protocol, this is solved by "permission to speak freely" — a
subordinate recognizes that formal register is insufficient, requests a
temporary shift, and the superior grants or denies it. The shift is scoped,
temporary, and architecturally legitimate — not a protocol violation but a
designed protocol override.

**Question:** Can ProbOS agents dynamically shift their own communication
register through self-monitoring? Has anyone implemented this before?

---

## 2. Prior Art Survey

### 2.1 Multi-Agent Frameworks

| Framework | Communication Model | Dynamic Register? |
|-----------|--------------------|--------------------|
| AutoGen (Microsoft) | Static system messages at init | No — fixed at registration |
| CrewAI | Static persona at construction | No — no adaptation mechanism |
| MetaGPT (Hong et al., 2023) | Standardized Operating Procedures | No — SOPs are constraints, not overridable |
| CAMEL (Li et al., 2023) | Inception prompting for role consistency | No — designed to *prevent* role deviation |
| AgentVerse (Chen et al., 2023) | Dynamic group composition | Structural adaptation only, not register |
| Generative Agents (Park et al., 2023) | Memory-informed context → emergent style | No self-awareness of communicative constraints |

**Finding:** Every major framework either fixes communication style at
initialization or treats style as an emergent property the agent has no
awareness of. No framework provides agent-initiated register shifting.

### 2.2 Metacognitive Self-Assessment

| System | Self-Assessment Target | Communication Register? |
|--------|----------------------|------------------------|
| Reflexion (Shinn et al., 2023) | Reasoning quality via verbal reflection | No — never assesses communication |
| MARS Framework | Normative rules to avoid errors | No — targets reasoning, not expression |
| MUSE Framework | Competence self-assessment | No — strategy selection, not tone |
| LangGraph Reflection | Factual accuracy and completeness | No — never communication appropriateness |

**Finding:** Metacognitive loops exist for reasoning quality but have never
been applied to communication register detection.

### 2.3 Self-Adaptive Prompting

**PromptBreeder (Fernando et al., 2023):** Closest mechanism — self-referential
prompt evolution using LLM-generated mutations. But operates at the population
level across runs, not as a single agent deciding mid-conversation to shift
register. Targets task performance (reasoning benchmarks), not communication.

**Finding:** The mechanism of an agent modifying its own instructions exists
in research, but never for communication register and never as an in-context
decision.

### 2.4 Style-Controlled Generation

| System | Style Control | Agent-Initiated? |
|--------|-------------|-------------------|
| DRESS (2025) | Dynamically adjusts steering vectors in style subspace | No — external controller sets style |
| SAMAS (2025) | Assembles specialized agents based on style patterns | No — structural, not self-modulated |

**Finding:** Style control exists as an external capability but has never been
placed under the agent's own metacognitive control.

### 2.5 Sociolinguistic AI

A confirmed **research gap**: no published work applies Communication
Accommodation Theory (Giles), register theory (Halliday), or sociolinguistic
code-switching models to AI agent communication systems. The field studies
empathy, therapeutic dialogue, and task completion — not deliberate,
self-aware register shifting.

### 2.6 Military/Organizational Protocol Override

No published work models formal communication protocols with agent-initiated
override capability. Military simulation AI focuses on tactical decisions,
not communication protocol management. The concept of "I am in protocol mode
but need to break protocol because the situation demands it" is entirely
unaddressed.

---

## 3. Gap Analysis

The specific composite capability ProbOS would implement has no prior art:

1. **Self-monitoring of communication register** — agent knows what mode it
   is currently operating in (formal/collegial/casual)
2. **Detection of register-task mismatch** — agent recognizes the current
   register is constraining important output
3. **Agent-initiated register shift** — the agent itself requests or enacts
   the change, not an external controller
4. **Structured protocol for breaking protocol** — the shift is
   architecturally supported and legitimate
5. **Scoped and temporary** — the agent returns to baseline register after
   the need passes

Existing work covers isolated pieces:
- PromptBreeder evolves prompts (but not mid-task, not for communication)
- DRESS controls style (but externally, not agent-initiated)
- Reflexion self-assesses (but reasoning quality, not communication register)
- CAMEL enforces roles (but never lets agents escape them)

**Conclusion: ProbOS would be first-of-kind** in implementing dynamic
communication register shifting as a self-monitored, agent-initiated,
architecturally supported capability.

---

## 4. Design Implications for ProbOS

### 4.1 Register Classification Taxonomy

A finite set of register labels the system understands:

| Register | Tenor Level | Format Overlay | Use Case |
|----------|-------------|---------------|----------|
| `formal_report` | High | Findings/Assessment/Recommendation | Duty reports, formal briefings |
| `professional` | Moderate-high | Evidence-based, structured | Analytical observations, proposals |
| `collegial` | Moderate | Natural voice, analytical | Department channel discussion |
| `casual` | Low | Personality-forward, emergent | Social interaction, games, humor |
| `speak_freely` | Minimal | Unfiltered assessment | Agent-requested override |

### 4.2 Modulation Pattern Templates

Pre-defined configurations mapping (register × process) → chain parameters:

```
template:
  register: formal_report
  chain_depth: [QUERY, ANALYZE, COMPOSE]
  compose_framing: prescriptive
  format_overlay: duty_report_billet
  personality_weight: low
  self_monitoring_mode: compliance

template:
  register: casual
  chain_depth: [COMPOSE]
  compose_framing: minimal
  format_overlay: none
  personality_weight: high
  self_monitoring_mode: social
```

### 4.3 Dynamic Register Shift Protocol ("Speak Freely")

**Detection (ANALYZE step):**
The analysis identifies a register-task mismatch. Signals include:
- Finding contradicts the expected report structure
- Assessment requires personal opinion that formal framing would flatten
- Critical information would be lost or diluted in the assigned format
- Agent's self-monitoring flags "I have something important that doesn't fit"

**Request (new intended_action):**
ANALYZE outputs `"speak_freely"` in `intended_actions`. This is not an
action tag — it is a register shift request that modulates the COMPOSE step.

**Authorization (trust-gated):**
- Trust ≥ 0.7: auto-granted, logged for Counselor review
- Trust 0.4–0.7: granted but flagged to Counselor
- Trust < 0.4: denied, agent composes in assigned register, mismatch logged

**Scope:**
The shift applies to this one compose invocation only. The agent returns to
their default register for the next cycle. "Speak freely" is temporary and
scoped — not a mode change.

**Observability:**
- Counselor receives REGISTER_SHIFT events
- Frequency tracking: agents who never request shifts may be too constrained;
  agents who constantly request shifts may not be suited to their billet
- Pattern analysis feeds back into personality tuning and duty assignment

### 4.4 Self-Monitoring Integration

ProbOS already has self-monitoring (AD-504). The register shift detection
extends self-monitoring from "am I behaving well?" to "am I communicating
effectively?" This is a natural extension:

- AD-504 self-monitoring: behavioral compliance + output quality
- AD-653 extension: **communicative effectiveness** — is my register
  appropriate for what I need to express?

The self-monitoring context (already injected at ANALYZE via
`_query_self_monitoring`) gains a new signal: register satisfaction.

### 4.5 Character-Driven Defaults

Per Snyder's Self-Monitoring Theory (AD-652), each agent's Big Five traits
determine:
- **Default register** — high-conscientiousness agents default to professional,
  high-openness agents default to collegial
- **Shift range** — how far an agent shifts between duty and social contexts
- **Shift threshold** — how much register-task mismatch before requesting
  "speak freely" (low threshold = shifts easily, high threshold = stays
  in register longer)

---

## 5. Novel Contribution

What makes this architecturally significant:

**Structure AND emergence, not structure OR emergence.** Every existing
framework treats these as opposing forces — more structure means less
emergence. ProbOS would be the first to provide a **designed mechanism**
where the agent itself recognizes "this structure is constraining something
important" and shifts. The emergence isn't uncontrolled — it's gated by
trust, scoped temporally, and observable by the Counselor.

**Self-aware communication.** No existing agent system gives agents awareness
of their own communicative constraints. Agents in AutoGen/CrewAI/MetaGPT
don't know they're being formal — they just are. ProbOS agents would know
their current register, detect mismatches, and act on them.

**Protocol for breaking protocol.** The military analogy is precise:
"permission to speak freely" isn't insubordination — it's a recognized
protocol for situations where protocol itself is the obstacle. The protocol
override is itself part of the protocol.

---

## 6. Key Citations

| Researcher / System | Contribution | Relevance |
|---------------------|-------------|-----------|
| Giles (1973, 1991) | Communication Accommodation Theory | Theoretical foundation for register shifting |
| Halliday (1978) | Field/Tenor/Mode register theory | Classification framework |
| Snyder (1974, 1987) | Self-Monitoring Theory | Individual differences in code-switching range |
| Shinn et al. (2023) | Reflexion — verbal self-reflection | Metacognitive loop (reasoning, not communication) |
| Fernando et al. (2023) | PromptBreeder — self-adaptive prompts | Closest mechanism (prompt self-modification) |
| Park et al. (2023) | Generative Agents — memory-informed style | Emergent style without self-awareness |
| Hong et al. (2023) | MetaGPT — SOP-governed communication | Rigid protocol enforcement (opposite approach) |
| Li et al. (2023) | CAMEL — role consistency via inception | Role adherence, never role escape |
| Weick & Sutcliffe (2007) | HRO communication protocols | Formal register as cognitive scaffolding |
