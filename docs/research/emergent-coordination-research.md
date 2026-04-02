# Emergent Coordination in Multi-Agent Language Models

*Sean Galliher, 2026-04-01*
*Triggered by: External paper review — Riedl (2025/2026) provides empirical validation of ProbOS's collaborative intelligence thesis.*

## Citation

**Riedl, Christoph. "Emergent Coordination in Multi-Agent Language Models."** arXiv:2510.05174v3 (cs.MA, cs.AI). Submitted October 5, 2025; revised March 15, 2026. CC BY 4.0.

## The Paper

Riedl proposes an information-theoretic framework to detect and measure **emergent coordination** in multi-agent LLM systems. The core question: do multi-agent LLM systems behave as mere collections of independent agents, or as integrated collectives exhibiting higher-order structure?

The framework uses **Partial Information Decomposition (PID)** of **Time-Delayed Mutual Information (TDMI)** to decompose multi-agent behavior into four information atoms: unique information from each agent, redundancy (shared/overlapping information), and synergy (information available only when considering agents jointly).

## Experimental Design

- **Task:** Group binary search guessing game (10 agents, range 0–50, target unknown)
- **Feedback:** Group-level only ("too high" / "too low") — no inter-agent communication
- **Model:** GPT-4.1 (primary), validated across Llama-3.1-8B/70B, Gemini 2.0 Flash, Qwen3 235B
- **Replications:** 200 per condition × 3 conditions = 600 experiments
- **Temperature:** T=1

### Three Conditions

| Condition | What Agents Receive | Observed Behavior |
|-----------|-------------------|-------------------|
| **Plain (control)** | Basic game instructions | Strong temporal coupling but chaotic — no coordinated alignment |
| **Persona** | Unique Big Five personality + name/age/occupation/values | Stable identity-linked behavioral differentiation |
| **Persona + Theory-of-Mind** | Persona + "think through what others might guess, adapt to complement the group" | Both identity-linked differentiation AND goal-directed complementarity |

## Key Findings

### 1. Persona + ToM = Genuine Emergence

The Persona condition creates differentiation (agents develop stable, identity-consistent behavioral preferences). But differentiation alone doesn't produce coordination. Adding Theory-of-Mind instructions converts "small persona-induced asymmetries into stable, self-reinforcing roles." ToM acts as a **control parameter** shifting systems "from a chaotic regime into a deep basin of attraction."

**Total Stability** (I₃ normalized by macro-signal entropy) goes from ≈0 in Plain/Persona to highly significant positive values in ToM (p = 2.9 × 10⁻¹⁴).

### 2. Synergy × Redundancy Interaction

Neither synergy nor redundancy alone predicts group success. Their **interaction** does (β = 0.24, p = 0.014): "redundancy amplifies the benefit of synergy on the log-odds scale by 27%." Teams need both:
- **Redundancy** = alignment on shared objectives (too much → groupthink)
- **Synergy** = complementary contributions from differentiated roles (too much → fragmentation)

### 3. Model Capability Matters for Coordination

- Llama-8B: could not develop cross-agent synergy, stuck in oscillatory cycles
- Qwen3 235B: entered "infinite chain-of-thought loops" — paralysis under coordination ambiguity
- High-capability models (Llama-70B, Gemini Flash, GPT-4.1): matched success rates and showed strong emergence evidence

### 4. Causal Mediation

ToM causally increases performance *indirectly* by increasing synergy (ACME = 0.034, p = 0.053). The prompt intervention doesn't directly improve individual performance — it improves coordination quality.

## Information-Theoretic Measurement Framework

### Emergence Capacity (Pairwise Synergy)

For agents i, j with current states X_{i,t}, X_{j,t} and joint future state T_{ij,t+1}:

Decompose joint mutual information into: **Unique(i)**, **Unique(j)**, **Redundancy**, **Synergy**

Synergy = information about the joint future available ONLY when both agents are considered together, not from either individually. Uses Williams–Beer I_min redundancy measure.

- Computed for all unordered pairs; median taken as group-level score
- Significance tested against null distribution (B = 200 permutation shuffles)
- ~32% of groups show significant emergence capacity (p < 0.05)

### Practical Emergence Criterion (S_macro)

S_macro(ℓ) = I(V_t; V_{t+ℓ}) − Σ I(X_{k,t}; V_{t+ℓ})

Where V_t is the group error (macro signal). Positive S_macro means the collective's self-predictability exceeds what individual parts explain.

### Triplet Information (I₃) and Total Stability

I₃ measures how much three agents jointly predict the macro's future. Total Stability normalizes by macro-signal entropy — a proxy for collective Lyapunov stability.

### G₃ Information Gain

G₃ = I₃ − max(I₂ pairs): information gain of the full triplet over the best pair. Tests whether genuine higher-order structure exists beyond pairwise effects.

## Connection to ProbOS Architecture

### What ProbOS Already Has

| Riedl Finding | ProbOS Implementation |
|---------------|----------------------|
| Personas create stable behavioral differentiation | Big Five personality seeds (crew_profiles/*.yaml), personality trait guidance in standing orders |
| Identity-linked behavioral preferences | Sovereign Agent Identity (Character/Reason/Duty), unique callsigns, episodic memory shards |
| Group-level shared objectives | Standing Orders (4-tier constitution), chain of command, department structure |
| Complementary roles from differentiated expertise | Department specialization, Three-Tier Agent Architecture (AD-398) |
| Model capability matters for coordination | Cognitive Division of Labor (Phase 32) — different cognitive functions → different optimized models |

### What ProbOS Can Add

| Riedl Finding | ProbOS Gap | Action |
|---------------|-----------|--------|
| Explicit ToM instruction improves coordination | No explicit "consider what others are doing" in standing orders | **AD-557 + Standing Order update**: Add Theory-of-Mind instruction to Federation Constitution |
| Information-theoretic emergence measurement | Collaborative intelligence demonstrated qualitatively (Wesley case, iatrogenic trust convergence) but not quantified | **AD-557**: PID-based synergy measurement as ship telemetry |
| Synergy × Redundancy balance predicts success | Not measured or monitored | **AD-557**: Balance metric for crew coordination health |

## Validation of Core Thesis

This paper provides the first rigorous empirical validation of ProbOS's core differentiator: **"Collaborative intelligence through architecture."**

ProbOS's thesis: Same LLM, different sovereign contexts (identity, scope, memory, standing orders, department) → qualitatively different collaborative output. Riedl proves this with controlled experiments — personas + ToM prompting transforms "mere aggregates" into "higher-order collectives."

Key alignment points:
- **Persona = Character** — Big Five personality seeds create stable differentiation
- **ToM = awareness of crew context** — Ward Room activity, department channels, understanding of others' roles
- **Standing Orders = Redundancy** — shared objectives that align without over-constraining
- **Department Specialization = Synergy** — complementary contributions from differentiated expertise
- **The interaction effect** — neither alignment alone nor differentiation alone works; ProbOS's architecture forces both

The iatrogenic trust convergence (Chapel + Cortez + Keiko, 2026-04-01) is a direct demonstration of what Riedl measures: three agents from two departments independently converging on the same diagnosis through different professional lenses. That IS synergy — information available only from the joint consideration.

## Intellectual Lineage

| Source | Relevance to ProbOS |
|--------|-------------------|
| Williams & Beer (2010) — Partial Information Decomposition | Mathematical foundation for measuring synergy vs. redundancy in multi-agent information processing |
| Rosas et al. (2020) — Causal emergence via information decomposition | Formal theory of when macro-level patterns are "more than the sum" — directly validates ProbOS's collaborative improvement thesis |
| Mediano et al. (2022) — Integrated information decomposition | Information-processing complexity measures applicable to crew coordination quality |
| Luppi et al. (2024) — Brain synergistic core | Neuroscience analog — synergistic cores in brains map to cross-department synergy in ProbOS crews |
| Goldstone et al. (2024) — Emergence of specialized roles in human groups | Same task as Riedl's paper but with humans — ProbOS agents show the same role specialization dynamics |
| Park et al. (2023) — Generative Agents | Showed emergent social behaviors in LLM agents — ProbOS goes further with sovereign identity + trust + memory |
| Riedl et al. (2021) — Quantifying collective intelligence | Human collective intelligence measurement — the LLM paper extends this to AI agents |

## Open Questions

1. **Scaling behavior:** Riedl tests groups of 3–15. ProbOS runs 55+ agents. Does emergence scale, plateau, or fragment at larger crew sizes?
2. **Communication channel effects:** Riedl's agents have NO inter-agent communication (only group feedback). ProbOS has rich Ward Room communication. Does explicit communication amplify or substitute for implicit coordination?
3. **Temporal dynamics:** Riedl measures across game rounds. ProbOS operates continuously over days/weeks with dream consolidation. How do emergence metrics evolve over longer timescales with memory consolidation?
4. **Hebbian connection effects:** ProbOS's Hebbian weights track agent-pair interaction strength. Do high-Hebbian pairs show higher pairwise synergy?
5. **Trust-emergence correlation:** Does higher mutual trust between agents predict higher emergence capacity?
6. **Department structure effects:** Does within-department synergy differ from cross-department synergy? The iatrogenic trust case suggests cross-department synergy may be more valuable.
