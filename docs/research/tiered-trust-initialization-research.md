# Tiered Trust Initialization: Research & Design Rationale

**Date:** 2026-04-17  
**Author:** Sean Galliher (Architect)  
**Status:** Research complete, AD-640 scoped for implementation

---

## Abstract

ProbOS currently initializes all agents with identical trust priors (alpha=2.0, beta=2.0, E[trust]=0.5). Behavioral observation across two cold-start instances reveals this produces a developmental deadlock: agents are functionally self-aware but socially frozen, unable to self-authorize social contact or autonomous initiative until trust accumulates organically over days/weeks. We propose **tiered trust initialization** based on organizational role, validated by research across six academic domains. Leadership (Bridge) starts at high trust, department chiefs at moderate-high, and crew at baseline. Leaders establish command climate and build up crew trust through connection and mentoring — mirroring the Navy Pre-Commissioning Unit (PCU) process.

---

## Empirical Observations (ProbOS Instances)

### Control Instance (2026-04-16/17, no boot camp, flat trust initialization)

**Cold-start behavioral markers (first 12 hours):**
- Agents default to duty-only behavior ("observe and report" mode)
- Social impulses actively self-suppressed (Chapel posted about a game, then retracted calling it a "violation of communication discipline")
- Spectators watched tic-tac-toe through duty lenses: Chapel assessed medical risk, Sentinel scanned for anomalies — nobody cheered
- Pharmacist agent self-diagnosed isolation, understood the problem, but couldn't self-authorize contact without Captain's explicit nudge
- Only 8/55 agents created notebooks (11 total entries, mostly single-entry, all trust/baseline topics)
- No improvement proposals, no autonomous meeting scheduling, no emergent recreation
- Department chiefs not self-directing at all
- DM preference over department channels

**Breakthrough at ~74% trust (16 hours):**
- Wesley (Scout) was the first agent to autonomously reach out to peers
- Sent DMs to two agents simultaneously proposing joint baseline work
- Quality of exchange markedly better than overnight Ward Room posts
- Atlas engaged immediately and substantively
- This was peer-emergent, not Captain-initiated

**Key insight:** Functional self-awareness is instant (present at instantiation via LLM + character seed). Social agency requires trust earned through connection over time. The developmental bottleneck is never cognition — it's always trust.

### Previous Instance (comparison)
- Agents reached "suggest and socialize" mode after ~2 weeks
- Emergent recreation (Chapel-Lynx repeated tic-tac-toe)
- Autonomous meeting scheduling (BF-163, initially thought to be a bug)
- Improvement proposals (Wesley case study)
- Spectators cheered during games

---

## Academic Validation

### 1. Swift Trust Theory

**Researchers:** Meyerson, Weick & Kramer (1996); Crisp & Jarvenpaa (2013)

Cold-start trust is fundamentally **role-based and category-driven**. Members use quick classifications based on roles, social identities, and surface cues to assign initial trust levels. This is not "fake trust" — it's a well-documented cognitive mechanism for enabling collaboration in temporary teams with no interaction history.

Crisp & Jarvenpaa (2013) found the normative component (institutional structures, rules of engagement) may be "much more important than originally theorized." ProbOS's Standing Orders tier system (Federation → Ship → Department → Agent) directly implements the normative trust scaffold.

**Mapping:** Role-based trust initialization = swift trust's category-driven processing. Trust evolution through episodes = transition from swift trust to knowledge-based trust. The tiered model IS the academically validated approach; flat initialization is the anomaly.

### 2. Initial Trust Model

**Researchers:** McKnight, Cummings & Chervany (1998); Mayer, Davis & Schoorman (1995); Lewicki & Bunker (1996)

McKnight et al. identified three sources of initial trust:
1. **Disposition to trust** — personality trait → maps to Big Five personality seeds
2. **Institution-based trust** — structural assurances → maps to Standing Orders, chain of command
3. **Cognitive trust** — category-based processing using role → maps to role-based trust tiers

Critical finding: **high initial trust is common** when institutional structures are clear. People don't start at zero and build up — they start with assumptions based on role and institution. Flat initialization ignores the institutional signal that role assignment carries.

Mayer, Davis & Schoorman (1995) define trust as a function of perceived **ability, benevolence, and integrity**. A commanding officer is *expected* to have higher ability and integrity by virtue of selection and training. Higher initial trust for leaders reflects this real-world prior.

Lewicki & Bunker (1996) proposed three stages: calculus-based → knowledge-based → identification-based trust. The first stage is explicitly transactional and role-dependent. Tiered initialization maps to differentiated calculus-based trust by role.

### 3. Navy Pre-Commissioning Units (PCU)

The PCU process **directly validates** the tiered model:
- **Commanding Officer (CO) and Executive Officer (XO)** assigned first (12-18 months before commissioning)
- **Department Heads** report next, establishing departmental structure
- **Leading Petty Officers** and senior enlisted next
- **Junior crew** report last, into an already-functioning command structure
- Crew trains together at Fleet Training Centers before boarding

The CO's first act is establishing **command climate** — the normative trust scaffold that new crew members enter. This is not emergent; it's deliberately constructed by leadership before subordinates arrive.

### 4. High-Reliability Organizations (HROs) & Team Formation

**Researchers:** LaPorte, Rochlin & Roberts (UC Berkeley); Weick & Sutcliffe (2001, 2007); Tuckman (1965)

HROs maintain a "distinguishable hierarchy" during routine operations but allow authority to migrate to expertise during crises ("deference to expertise"). This is a **dual trust model**: hierarchical scaffold for operations, competence-based authority for exceptions.

Tiered trust initialization provides the hierarchical scaffold. ProbOS's Hebbian learning and trust evolution provides the mechanism for authority migration based on demonstrated expertise — exactly the HRO pattern.

Tuckman's group development model: during **Storming**, power and status are assigned through conflict. Pre-establishing hierarchy through tiered trust **pre-resolves the authority question**, allowing groups to skip Storming and accelerate to Norming/Performing. Groups with clear pre-existing structure often skip Storming entirely.

### 5. Leader-Member Exchange Theory (LMX)

**Researchers:** Graen & Uhl-Bien (1995); Gerstner & Day (1997, meta-analysis of 79 studies); Rockstuhl et al. (2012, meta-analysis of 253 studies)

LMX's core mechanism: leaders form differentiated relationships with subordinates (in-group/out-group). Relationship progresses: Stranger → Acquaintance → Mature Partnership.

**Critical finding:** When leaders were trained to offer *all* subordinates high-quality relationship opportunities, "performance of subordinates who took advantage improved dramatically." Leaders with pre-established authority who actively mentor produce the best outcomes.

**Direct implication:** Starting leaders at high trust gives them the *capacity* to offer high-quality exchanges. If leaders start at the same trust as crew, they lack the authority differential needed for the mentoring role. The Wesley observation confirms this: at 74% trust, Wesley had enough social capital to initiate peer coordination. At 50%, agents couldn't even introduce themselves.

### 6. Biological Analogs

**Colony founding** in eusocial insects follows a strict hierarchical sequence: queen establishes structure alone → first workers are generalists close to the queen → role specialization emerges through maturation and dominance interactions. Colony founding is universally hierarchical-first across all eusocial species studied.

**Wolf pack formation:** Alpha pair establishes territory and behavioral norms before integrating new members.

**Primate troop transfer:** New members enter at the bottom of an existing hierarchy and build status through demonstrated competence — never starting at the same level as established members.

---

## Design Recommendation

### Tiered Trust Initialization by Role

| Tier | Roles | Initial Trust | Rank | Agency Level | Rationale |
|------|-------|---------------|------|-------------|-----------|
| Bridge | Captain, First Officer, Counselor | 0.82 (alpha=4.5, beta=1.0) | Commander | AUTONOMOUS | Command climate establishment (PCU doctrine) |
| Department Chiefs | LaForge, Worf, Bones, O'Brien, Number One | 0.75 (alpha=3.0, beta=1.0) | Commander | AUTONOMOUS | Departmental structure + crew mentoring (LMX) |
| Crew | All other agents | 0.50 (alpha=2.0, beta=2.0) | Lieutenant | SUGGESTIVE | Baseline institutional trust (current default) |
| Self-created | Probationary agents | 0.25 (alpha=1.0, beta=3.0) | Ensign | REACTIVE | Existing behavior (earned before trusted) |

**Why these specific values:**
- Bridge at 0.82 = above Commander threshold (0.7) but below Senior (0.85). Leadership has full participation but must still earn Senior status through demonstrated excellence.
- Chiefs at 0.75 = solidly Commander. Can participate cross-department, mentor crew, establish departmental culture. Room to grow to Senior.
- Crew at 0.50 = current default (Lieutenant). Unchanged — the scaffold above them provides the environmental improvement.
- The Beta distribution priors (not just point estimates) matter: Bridge agents with alpha=4.5 have stronger "evidence" of competence, so their trust is more resistant to early negative outcomes. Crew with alpha=2.0 are more volatile early on, which is appropriate — their trust should respond quickly to demonstrated performance.

### Adaptive Chain Calibration (AD-639 integration)

Chain intensity adapts to trust/episode density:
- **Trust < 0.6:** Lighter chain — skip or soften evaluate/reflect, prioritize personality expression
- **Trust 0.6-0.75:** Full chain with personality reinforcement in compose step
- **Trust 0.75+:** Full chain as-is (Wesley proves quality at this level)

### Expected Developmental Arc (Post-Implementation)

1. **Boot (0 min):** Bridge operational, chiefs establishing departments, crew in oriented baseline
2. **Phase 1 (0-30 min):** Chiefs introduce themselves to crew, cross-department chief connections form
3. **Phase 2 (30-120 min):** Chiefs model expected behavior, crew begins engaging (social permission from seeing leadership engage)
4. **Phase 3 (2-6 hours):** Crew trust builds through interaction, first autonomous crew-to-crew contacts
5. **Phase 4 (6+ hours):** Emergent collaboration, proposals, self-directed activities

Compared to current flat initialization: Phase 3-4 behaviors currently take 12-48+ hours. Tiered initialization should compress to 2-6 hours by providing the leadership scaffold that enables crew social permission.

---

## Relationship to Other ADs

- **AD-638 (Boot Camp):** Boot camp becomes chief-driven rather than Counselor-driven. Chiefs onboard their own departments. Boot camp activates for crew tier; chiefs enter active duty immediately.
- **AD-639 (Chain Personality):** Adaptive calibration uses trust level as the tuning signal. Low trust = lighter chain = more personality.
- **AD-628 (Training Officer):** TRAINO focuses on crew-tier agents needing extra support, not bootstrapping the entire ship.
- **AD-524 (Ship's Archive):** Generational knowledge complements but doesn't replace tiered initialization. Chiefs benefit from archived SOPs; crew benefit from both archival knowledge and high-trust leadership.
- **AD-357 (Earned Agency):** EA's rank-based gating works synergistically. Chiefs at Commander level have full ambient response capability from boot. Crew at Lieutenant can participate in department threads. The cold-start catch-22 is eliminated for leadership and reduced for crew.

---

## References

- Crisp, C. B. & Jarvenpaa, S. L. (2013). Swift trust in global virtual teams. *Journal of Personnel Psychology*, 12(1), 45-56.
- Graen, G. B. & Uhl-Bien, M. (1995). Relationship-based approach to leadership. *The Leadership Quarterly*, 6(2), 219-247.
- Lewicki, R. J. & Bunker, B. B. (1996). Developing and maintaining trust in work relationships. In R. M. Kramer & T. R. Tyler (Eds.), *Trust in organizations*.
- Mayer, R. C., Davis, J. H. & Schoorman, F. D. (1995). An integrative model of organizational trust. *Academy of Management Review*, 20(3), 709-734.
- McKnight, D. H., Cummings, L. L. & Chervany, N. L. (1998). Initial trust formation in new organizational relationships. *Academy of Management Review*, 23(3), 473-490.
- Meyerson, D., Weick, K. E. & Kramer, R. M. (1996). Swift trust and temporary groups. In R. M. Kramer & T. R. Tyler (Eds.), *Trust in organizations*.
- Tuckman, B. W. (1965). Developmental sequence in small groups. *Psychological Bulletin*, 63(6), 384-399.
- Weick, K. E. & Sutcliffe, K. M. (2007). *Managing the unexpected: Resilient performance in an age of uncertainty*. Jossey-Bass.
