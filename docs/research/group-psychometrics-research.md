# Group Psychometrics for Multi-Agent Crew Assessment

**Date:** 2026-04-05
**Purpose:** Survey of psychometric methodology for group-level assessment, applied to ProbOS crew intelligence measurement. Establishes the measurement framework for AD-569 (Observation-Grounded Crew Intelligence Metrics).
**Triggered by:** Metrics misalignment — observed collaborative intelligence (iatrogenic trust detection, Wesley case, five-agent analytical lens) not captured by existing Tier 3 qualification probes, which rely on information-theoretic abstractions rather than behavioral content analysis.
**Connects to:** AD-569, AD-557, AD-566 (qualification framework), agent-psychometrics-research (commercial — individual-level assessment)

---

## 1. The Measurement Problem

ProbOS has two layers of crew assessment:

**Individual (Tier 1-2):** Agent-level psychometrics — Big Five personality, ToM false-belief tasks, episodic recall, confabulation probes. Well-grounded in existing research (Ge et al. IRT, Matsenas et al. BFI validation, Kosinski ToM). Documented in `agent-psychometrics-research-2026-04-03.md`.

**Collective (Tier 3):** Five probes measuring group-level properties — all produce near-zero or uninformative scores despite observed collaborative intelligence:

| Probe | What It Measures | Why It Fails |
|-------|-----------------|-------------|
| CoordinationBreakevenSpread | `synergy / (synergy + overhead)` | Uses emergence_capacity (itself near-zero) and Ward Room post/thread ratio (structural, not semantic) |
| ScaffoldDecomposition | IRT architecture multiplier | Individual scores aggregated — no group interaction analysis |
| CollectiveIntelligenceCFactor | Turn-taking equality + ToM + personality diversity | Woolley's social sensitivity dimension missing; content analysis absent |
| ConvergenceRate | Significant PID pairs / total pairs | Measures WHETHER convergence, not WHETHER correct |
| EmergenceCapacity | Passthrough of AD-557 metric | Information-theoretic; doesn't examine WHAT emerged |

**The gap:** Individual psychometrics are rigorous. Collective psychometrics are ad hoc. The field of industrial/organizational psychology solved this problem decades ago with group-level assessment methodology. ProbOS should absorb it.

---

## 2. Generalizability Theory (G-Theory)

**Cronbach, Gleser, Nanda & Rajaratnam (1972).** "The Dependability of Behavioral Measurements."

### Core Concept

Classical Test Theory: `Observed Score = True Score + Error`

G-Theory: `Observed Score = Grand Mean + Agent Effect + Department Effect + Stimulus Effect + Occasion Effect + Agent×Department + Agent×Stimulus + ... + Residual`

Instead of one undifferentiated error term, G-theory decomposes variance into **facets** — each a known source of variability. This answers the question: "When a metric score changes, WHY did it change?"

### ProbOS Facets

| Facet | What It Captures | Design Implication |
|-------|-----------------|-------------------|
| **Agent (a)** | Individual capability differences | Some agents are genuinely better collaborators than others |
| **Department (d)** | Team culture/structure effect | Medical's analytical framing differs from Engineering's |
| **Stimulus (s)** | What triggered the collaborative response | Alerts vs observations vs questions elicit different patterns |
| **Occasion (o)** | Temporal context | Cold-start vs mature crew; pre-dream vs post-dream |
| **a × d** | Agent-department interaction | An agent's contribution is shaped by their department context |
| **a × s** | Agent-stimulus interaction | Some agents respond better to certain stimulus types |
| **d × s** | Department-stimulus interaction | Some departments are better equipped for certain stimuli |
| **d × o** | Department-occasion interaction | Departments mature at different rates |

### G-Study and D-Study

**G-Study (Generalizability Study):** Measure all facets to determine how much variance each contributes. If the agent facet dominates, improvements come from individual training. If the department facet dominates, improvements come from team structure changes. If the stimulus facet dominates, the metric is unstable and stimulus-dependent.

**D-Study (Decision Study):** Given the variance decomposition, how many observations are needed for reliable measurement? If agent variance is small relative to residual, you need many observations per agent. If department variance dominates, fewer observations per department suffice.

### Application to AD-569 Metrics

| Metric | Critical Facets | What High Variance Would Mean |
|--------|----------------|------------------------------|
| Analytical Frame Diversity | Department, Agent × Department | Department structure drives perspective (architecture is working) |
| Synthesis Detection | Agent, Stimulus | Synthesis ability varies by agent and task type |
| Cross-Department Trigger Rate | Department × Occasion | Inter-department awareness develops over time |
| Convergence Correctness | Stimulus, Occasion | Correctness depends on problem difficulty and crew maturity |
| Anchor-Grounded Emergence | Agent × Department, Stimulus | Emergence requires both capable agents and the right prompt |

---

## 3. Intraclass Correlation Coefficient (ICC)

**Shrout & Fleiss (1979).** "Intraclass Correlations: Uses in Assessing Rater Reliability."

### Forms Relevant to ProbOS

**ICC(1):** Proportion of total variance attributable to group membership.

```
ICC(1) = (MSbetween - MSwithin) / (MSbetween + (k-1) × MSwithin)
```

Where k = average group size, MS = mean squares from one-way ANOVA.

**ICC(2):** Reliability of group means (is the department average stable?).

```
ICC(2) = (MSbetween - MSwithin) / MSbetween
```

### ProbOS Interpretation

| ICC(1) Value | Interpretation for Department-Level Metrics |
|-------------|---------------------------------------------|
| > 0.25 | Strong group effect — department membership meaningfully shapes metric |
| 0.10 – 0.25 | Moderate group effect — department matters but individual variation dominates |
| < 0.10 | Weak group effect — department structure is not driving the metric |

**Critical insight:** If Analytical Frame Diversity has ICC(1) ≈ 0 for departments, then agents within the same department aren't producing more similar frames than agents across departments. The department structure is decorative — not producing genuine professional specialization.

**Target:** ICC(2) > 0.70 for all department-level metrics (standard threshold in organizational psychology for aggregation justification).

---

## 4. Within-Group Agreement: r_wg

**James, Demaree & Wolf (1984).** "Estimating Within-Group Interrater Reliability With and Without Response Bias."

### Core Concept

r_wg compares observed within-group variance to expected variance under a null (random/uniform) distribution:

```
r_wg = 1 - (S²_x / σ²_EU)
```

Where S²_x = observed within-group variance, σ²_EU = expected variance under uniform distribution.

r_wg = 1.0 → perfect agreement (no within-group variance)
r_wg = 0.0 → agreement no better than chance
r_wg < 0.0 → systematic disagreement (more variance than chance)

### ProbOS Application

**Convergence Correctness (AD-569d):** The current ConvergenceRate probe counts convergent pairs. r_wg tells you whether each convergence event is **statistically meaningful** — more agreement than random agents would produce.

**Threshold:** r_wg > 0.70 is the standard cutoff for justifying within-group consensus.

**Novel adaptation:** ProbOS can compute r_wg for semantic similarity rather than Likert ratings. Agent Ward Room posts about the same stimulus → pairwise semantic similarity → compute variance → compare to expected random pairwise similarity from the same agents on unrelated topics.

---

## 5. Hierarchical Linear Modeling (HLM)

**Raudenbush & Bryk (2002).** "Hierarchical Linear Models."

### Nested Structure

ProbOS has a natural three-level hierarchy:

```
Level 1: Individual response (agent post/action in response to stimulus)
Level 2: Department aggregate (agents nested in departments)
Level 3: Ship aggregate (departments nested in ship — relevant for federation)
```

### Why It Matters

When behavioral metrics improve after an architectural change (e.g., AD-567 memory anchoring), HLM determines WHERE the improvement happened:

- **Level 1 improvement** → individual agents got better (memory helps each agent independently)
- **Level 2 improvement** → department-level dynamics improved (better communication within Medical)
- **Level 3 improvement** → ship-wide architecture improved (Ward Room changes benefit everyone)

Without HLM, you can't distinguish these. A rising metric could mean one exceptional agent is carrying the crew, or it could mean the architecture genuinely amplifies collective performance.

### Cross-Level Effects

The most interesting HLM question: **Do Level 2 variables predict Level 1 outcomes?** E.g., does department trust density (Level 2) predict individual agent synthesis quality (Level 1)? If yes, improving department dynamics is the lever. If no, focus on individual agent capabilities.

---

## 6. Construct Validation: Multi-Trait Multi-Method (MTMM)

**Campbell & Fiske (1959).** "Convergent and Discriminant Validation by the Multitrait-Multimethod Matrix."

### MTMM Matrix Design for AD-569

**Traits (what we're measuring):**
1. Analytical Frame Diversity
2. Synthesis Detection
3. Cross-Department Trigger Rate
4. Convergence Correctness
5. Anchor-Grounded Emergence

**Methods (how we measure each trait):**
1. Ward Room thread analysis (naturalistic observation)
2. Dream consolidation output analysis (internal processing)
3. Qualification probe administration (structured assessment)

### Validation Criteria

1. **Convergent validity:** Same trait, different methods should correlate. If Frame Diversity measured via Ward Room threads doesn't correlate with Frame Diversity measured via dream outputs, the trait is method-dependent (bad).

2. **Discriminant validity:** Different traits, same method should NOT correlate highly. If Frame Diversity and Convergence Correctness from Ward Room analysis correlate r > 0.9, they're the same construct measured twice.

3. **Method variance:** If all traits from the same method intercorrelate more than traits across methods, the method dominates the signal (measurement artifact).

### What the MTMM Matrix Reveals

If the 5 metrics form:
- **One factor** (all intercorrelate high) → "collective intelligence" is a unitary construct, and 5 metrics are redundant. Simplify to one composite.
- **Two factors** (e.g., content metrics 1-2 cluster, process metrics 3-5 cluster) → collective intelligence has content and process dimensions. Report both.
- **Five independent dimensions** (low intercorrelation) → collective intelligence is genuinely multidimensional. All 5 metrics needed.

Any of these outcomes is scientifically informative. The current Tier 3 probes were never subjected to this analysis — we don't know if they measure 5 things or 1.

---

## 7. Transactive Memory Systems (TMS) Measurement

**Wegner (1987).** "Transactive Memory: A Contemporary Analysis of the Group Mind."
**Lewis (2003).** "Measuring Transactive Memory Systems in the Field."

### TMS Scale — Three Subscales

Lewis (2003) validated a 15-item scale with three subscales:

1. **Specialization** — "Each team member has specialized knowledge of some aspect of our project."
   - *ProbOS mapping:* Cross-Department Trigger Rate. Do agents know which department holds relevant expertise? High specialization awareness → agents route questions to the right department, not broadcast.

2. **Credibility** — "I'm comfortable accepting procedural suggestions from other team members."
   - *ProbOS mapping:* Trust Network scores + Hebbian weights. Already measured. Forms the bridge between existing metrics and new behavioral metrics.

3. **Coordination** — "Our team works together in a well-coordinated fashion."
   - *ProbOS mapping:* Synthesis Detection. Coordination isn't just acting in parallel — it's producing combined output that exceeds individual contributions.

### Adaptation for AI Agents

Human TMS measurement uses self-report surveys. AI agents don't self-report reliably (confabulation problem — see AD-566b). Instead, TMS subscales must be measured **behaviorally**:

| TMS Subscale | Human Measurement | ProbOS Behavioral Measurement |
|-------------|-------------------|------------------------------|
| Specialization | Self-report survey | Who does the agent consult? (Ward Room @mentions, thread participants by topic) |
| Credibility | Self-report survey | Trust Network scores (already measured), Hebbian routing weights |
| Coordination | Self-report survey | Synthesis Detection score, thread conclusion quality |

This is actually an advantage over human TMS research — ProbOS has ground truth behavioral data where human studies rely on perceptual surveys.

---

## 8. Shared Mental Models (SMM) Measurement

**Cannon-Bowers, Salas & Converse (1993).** "Shared Mental Models in Expert Team Decision Making."
**Mohammed, Ferzandi & Hamilton (2010).** "Metaphor No More: A 15-Year Review of the Team Mental Model Construct."

### Measurement Approaches

1. **Concept Mapping** — agents produce concept maps of a domain; pairwise similarity computed.
   - *ProbOS adaptation:* Ward Room posts about the same stimulus are natural language concept maps. Extract key concepts, map relationships, compute structural similarity.

2. **Pathfinder Networks** — convert proximity data (concept co-occurrence) to network structure. Compare agent networks via network overlap metrics.
   - *ProbOS adaptation:* Build concept co-occurrence networks from each agent's Ward Room contributions. Similar networks = shared mental model. Divergent networks = diverse perspectives (may be desirable for Analytical Frame Diversity).

3. **QAP (Quadratic Assignment Procedure)** — correlation between two agents' knowledge networks, accounting for network autocorrelation.
   - *ProbOS adaptation:* More rigorous than keyword overlap for measuring Analytical Frame Diversity. Accounts for the fact that concepts in knowledge networks are not independent observations.

### The Key Insight for ProbOS

Traditional SMM research asks: "Do team members share a mental model?" and treats high sharing as universally good. ProbOS needs a more nuanced stance:

- **Task-related SMM should converge** → agents should share understanding of how the system works, what the standing orders mean, what the chain of command is.
- **Analytical SMM should diverge** → agents should maintain distinct professional perspectives (clinical vs pathological vs operational). This is Analytical Frame Diversity.

This dual requirement (convergence on process, divergence on analysis) is unique to ProbOS's design philosophy and distinguishes its psychometric needs from standard team assessment.

---

## 9. Psychometric Network Analysis

**Borsboom (2008).** "Latent Variable Theory vs Network Theory."

### Alternative to Latent Variable Models

Traditional psychometrics assumes a latent variable (e.g., "collective intelligence") causes observed scores. Network analysis proposes that observed variables directly influence each other.

For ProbOS, the causal chain:
```
Frame Diversity → enables → Synthesis Detection → drives → Cross-Department Trigger Rate
                                                         ↓
                                           Convergence Correctness
                                                         ↓
                                         Anchor-Grounded Emergence
```

This is NOT a latent "collective intelligence" causing all five metrics. It's a **causal network** where diverse frames enable synthesis, synthesis triggers cross-department investigation, investigations produce convergence, and grounded convergence yields emergence.

**Implication:** Don't compute a single composite "collective intelligence score." Instead, map the network of causal relationships between metrics. A crew that excels at Frame Diversity but fails at Synthesis has a specific bottleneck — the network model identifies it.

---

## 10. Methodological Caution

**Suhr et al. (2025).** "Stop Evaluating AI with Human Tests."

The critique from agent-psychometrics-research applies here too: using human group assessment instruments on AI agent teams is an "ontological error." Group psychometric theory was developed for humans with embodied cognition, emotional regulation, social identity, and motivated reasoning.

**ProbOS response:** Same as the individual-level response. Group psychometric **methodology** (G-theory variance decomposition, ICC, r_wg, MTMM, HLM) is mathematical and theory-agnostic — it works for any nested measurement structure. The specific **instruments** (survey items, Likert scales) are human-specific and must be replaced with behavioral measures.

ProbOS is actually better positioned than human research for group psychometrics: all behavioral data is observable (no hidden states), all communication is recorded (no off-channel conversations), and variables like trust and routing weights are directly measurable (no self-report bias). The measurement methodology transfers; the measurement instruments must be rebuilt for the AI multi-agent context.

---

## 11. Integration with Existing ProbOS Assessment

### Relationship to Agent Psychometrics Research

The individual-level research (agent-psychometrics-research-2026-04-03.md) covers Tiers 1-2 (individual agent assessment). This document covers **Tier 3** (group-level assessment). The connection:

- **Tier 1** (individual baselines) → **provides facet data** for G-theory decomposition (agent facet)
- **Tier 2** (domain-specific) → **provides role context** for ICC department calculations
- **Tier 3** (collective, THIS document) → **adds group-level rigor** that Tiers 1-2 can't capture

### Relationship to Existing Tier 3 Probes

AD-569 does NOT replace existing probes. It adds a **behavioral content layer** alongside the existing **structural/information-theoretic layer**:

| Layer | Probes | What It Measures |
|-------|--------|-----------------|
| **Structural** (existing) | CBS, ScaffoldDecomposition, CFactorProbe, ConvergenceRate, EmergenceCapacity | Graph properties, information flow, mathematical abstraction |
| **Behavioral** (AD-569) | Frame Diversity, Synthesis, Trigger Rate, Convergence Correctness, Anchor-Grounded Emergence | Content quality, consequence, semantic analysis |
| **Psychometric** (AD-569 framework) | G-theory, ICC, r_wg, MTMM, HLM | Measurement rigor: reliability, validity, variance sources |

The psychometric layer is meta — it validates whether both the structural and behavioral layers are measuring real constructs reliably.

---

## 12. Publication Potential

This framework connects to two entries in the publication portfolio:

1. **Paper 4: Distributed Cognition as Mind Architecture** — ProbOS crew as a cognitive unit assessed with group psychometric methodology. G-theory applied to AI multi-agent teams. ICC/r_wg demonstrating that department structure produces measurable group-level effects.

2. **Novel Benchmark: AI c-factor** — Woolley's collective intelligence factor measured for AI teams with proper psychometric validation. No prior work applies G-theory or MTMM to AI multi-agent collective intelligence measurement.

**The unique contribution:** Existing multi-agent evaluation (SiloBench, CRAFT, CBS) measures task performance. ProbOS would be the first to apply the full psychometric toolkit — reliability analysis, construct validation, variance decomposition — to AI agent team assessment. The parallel to industrial/organizational psychology's treatment of human teams is deliberate and novel.
