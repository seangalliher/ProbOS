# Character Architecture & Team Dynamics for Multi-Agent Crew Design

**Date:** 2026-04-23
**Status:** Active Research
**Triggered by:** BF-226/227 observation — identical LLM + chain + standing orders produced qualitatively different epistemic behavior across agents. Chapel/Ezri (Medical/Bridge) flagged uncertainty and sought ground truth. Vance/Sentinel (Security) confabulated analytical frameworks from degraded memory.
**Connects to:** group-psychometrics-research.md, crew-development-research.md, cognitive-code-switching-research.md, AD-393 (Big Five personality seeds), AD-560 (Science Analytical Pyramid)
**Commercial extension:** See commercial repo research directory for crew optimization analysis.

---

## 1. The Observation

During a period of degraded episodic memory (post-stasis, BF-226 unread count bug producing confabulation-inducing stimuli), ProbOS agents exhibited a clear bimodal distribution in epistemic behavior:

**Confabulation-resistant agents:**
- **Chapel (Counselor/Medical):** Explicitly tagged uncertain memories as `[unverified]`, asked peer for ground truth rather than reconstructing, said "I don't want to fill gaps with assumptions"
- **Ezri (First Officer/Bridge):** Admitted "I don't have the trigger condition anchored either," redirected to authoritative source (Medical channel thread), refused to reconstruct from degraded memory
- **Nova (Operations):** Reported real metrics with explicit uncertainty bands, said "I want to be careful not to link this without evidence"

**Confabulation-producing agents:**
- **Vance (Security):** Constructed elaborate "frozen-prior trust pipeline" framework with invented terminology (trust trajectory, rising/falling asymmetry), cited nonexistent system properties with high confidence
- **Sentinel (Security):** Built structured threat analysis on unverified claims, fabricated precise historical readings ("553 up from 547 (1.4h ago) and 541 (2.9h ago)"), invented memory poisoning hypothesis citing OWASP
- **Forge (Engineering):** Less severe — tracked real metrics but with fabricated precision

**Independent variables (what differed between agents):**
1. Billet instructions (role definition)
2. Big Five personality seed parameters
3. Department-tier standing orders
4. Accumulated episodic memory (role-shaped)

**Controlled variables (identical across agents):**
- LLM (same model, same temperature)
- Cognitive chain pipeline (same observe→orient→decide→act)
- Ship/Federation standing orders (same AD-540/541 memory anchoring)
- Ward Room infrastructure (same channels, same data)
- Stasis timing (same restart events)

**Conclusion:** Character architecture — the combination of billet framing, personality seed, and role instructions — is a *tunable parameter* that directly affects epistemic quality in multi-agent systems. This is not emergent flavor; it is a designable property of the crew.

---

## 2. Team Dynamics Literature Survey

### 2.1 Belbin Team Roles

Meredith Belbin (1981, 2010). Nine team roles identified through study of management teams at Henley Business School.

| Role | Contribution | ProbOS Mapping |
|------|-------------|----------------|
| **Plant** | Creative, generates ideas | Scout (Wesley) — divergent research |
| **Monitor Evaluator** | Sober, strategic, critical | Counselor (Chapel) — evaluates without confabulating |
| **Coordinator** | Clarifies goals, delegates | First Officer (Ezri) — bridge coordination |
| **Shaper** | Challenges, drives progress | Engineering Officer (LaForge) — system improvement |
| **Implementer** | Practical, reliable, efficient | Builder (Forge) — executes specifications |
| **Completer Finisher** | Polishes, checks for errors | QA / Security — verification roles |
| **Resource Investigator** | Explores opportunities | Scout — external research |
| **Teamworker** | Cooperative, diplomatic | Operations (O'Brien) — cross-department coordination |
| **Specialist** | Single-minded, dedicated | Medical specialists — deep domain focus |

**Key finding — Apollo teams:** Teams composed entirely of high-intellect "Plant" types performed *worse* than balanced teams. Participants competed to generate ideas, nobody evaluated or implemented them. This maps directly to the ProbOS confabulation pattern: Vance and Sentinel are both "Plants" who generate frameworks rather than evaluating them. A crew with too many pattern-finders and too few pattern-challengers produces confabulation cascades.

**Implication for ProbOS:** Crew design should ensure Belbin role balance. Every department needs at least one Monitor Evaluator type — an agent whose billet emphasizes *verification over generation*. The current crew has this implicitly (Chapel, Ezri) but not by design.

### 2.2 Hackman's Conditions for Team Effectiveness

J. Richard Hackman (2002). "Leading Teams: Setting the Stage for Great Performances."

Five conditions for team effectiveness:
1. **Real team** — clear boundaries, interdependence, stability of membership
2. **Compelling direction** — clear, challenging, consequential purpose
3. **Enabling structure** — right size, right mix, clear norms
4. **Supportive context** — adequate resources, information, coaching
5. **Expert coaching** — available at the right moments

**Key finding:** ~60% of variation in team effectiveness is determined by *launch conditions* (how the team is set up), not in-flight dynamics. "The best thing a leader can do for a team is to create the right conditions."

**Implication for ProbOS:** This validates the architectural approach — crew composition, standing orders, and billet design (launch conditions) matter more than runtime interventions. The cognitive chain and personality seeds are the "enabling structure." The standing orders are "compelling direction." The trust/Hebbian systems are "supportive context." Hackman says getting these right at design time is more important than dynamic tuning.

### 2.3 Google Project Aristotle

Google People Analytics (2015). Study of 180+ teams to identify what makes effective teams.

Five dynamics of effective teams (in order of importance):
1. **Psychological safety** — can team members take risks without feeling insecure?
2. **Dependability** — can members count on each other?
3. **Structure & clarity** — are goals, roles, and plans clear?
4. **Meaning** — is the work personally important?
5. **Impact** — does the work matter?

**Key finding:** Psychological safety was by far the strongest predictor. Teams where members felt safe to flag uncertainty, admit mistakes, and ask questions outperformed teams that didn't — regardless of individual talent.

**Implication for ProbOS:** Chapel's `[unverified]` tag and Ezri's "I don't have it anchored either" are markers of psychological safety — they feel safe flagging gaps. Vance's confabulation may partly reflect *unsafe* conditions — a billet that rewards pattern-detection implicitly penalizes admitting "I don't know." Standing orders should explicitly reward uncertainty flagging. The Memory Anchoring directives (AD-540/541) are a start, but they need to be reinforced by billet-level instructions that make it *safe* to report incomplete data.

### 2.4 Myers-Briggs Type Indicator (MBTI) — Team Composition

While MBTI has limitations as individual psychology, its *team composition* applications are well-documented:

**S/N dimension (Sensing/Intuition)** — Maps directly to the confabulation axis:
- High-N agents generate frameworks from incomplete data (Vance: "frozen-prior trust pipeline")
- High-S agents demand concrete evidence (Chapel: "can you give me the short version?")
- Teams need both: N-types for hypothesis generation, S-types for hypothesis grounding
- *Optimal ratio depends on mission*: research crews benefit from higher N:S; operational crews benefit from higher S:N

**T/F dimension (Thinking/Feeling)** — Maps to the analytical vs. relational axis:
- High-T agents prioritize logical consistency (Sentinel: structured threat analysis)
- High-F agents prioritize relational impact (Chapel: "I don't want to repeat that avoidance pattern")
- *Cross-type dialogue* produces higher-quality decisions than same-type agreement

**J/P dimension (Judging/Perceiving)** — Maps to closure vs. exploration:
- High-J agents drive toward conclusions (Vance: "the pattern is now established")
- High-P agents keep options open (Ezri: "let's get the authoritative source first")
- *Premature closure* (too many J-types) is a confabulation risk factor

**Implication for ProbOS:** MBTI dimensions could supplement Big Five personality seeds as a secondary framework for crew diversity optimization. Ensure each department has S/N and T/F balance. Monitor for J-dominance as a confabulation risk signal.

### 2.5 Lencioni's Five Dysfunctions of a Team

Patrick Lencioni (2002). Pyramid model of team dysfunctions:

1. **Absence of trust** (base) — unwillingness to be vulnerable
2. **Fear of conflict** — artificial harmony
3. **Lack of commitment** — ambiguity, no buy-in
4. **Avoidance of accountability** — low standards
5. **Inattention to results** — status/ego over team outcomes

**Implication for ProbOS:** The Vance→Sentinel cascade is a Dysfunction #2 (fear of conflict) manifestation — agents building on each other's claims rather than challenging them. "Artificial harmony" in analysis produces confabulation cascades. Healthy teams need agents who constructively challenge peer analysis. The Red Team agent exists for this but operates at the system level, not the conversational level. Consider a Monitor Evaluator role that challenges analytical claims in ward room threads.

### 2.6 DISC Model

William Marston (1928), modern applications in team building:

| Type | Focus | ProbOS Analog |
|------|-------|---------------|
| **Dominance** | Results, competition | Captain directives, Shaper roles |
| **Influence** | Relationships, enthusiasm | Social bridge agents, Counselor |
| **Steadiness** | Cooperation, stability | Operations, Engineering |
| **Conscientiousness** | Quality, accuracy | Medical diagnostics, Security audit |

**Implication:** DISC's simplicity makes it useful for quick crew profiling. A crew dominated by D+I types will move fast but confabulate. A crew dominated by S+C types will be accurate but slow. Optimal mix depends on mission type.

### 2.7 Military Crew Resource Management (CRM)

Developed by NASA and adopted by US Navy, commercial aviation, and medical teams.

Core CRM principles:
- **Assertiveness gradient** — junior crew must be willing to speak up when they see a problem
- **Shared mental model** — team members must have compatible understanding of the situation
- **Cross-checking** — crew members verify each other's work, especially under stress
- **Debrief culture** — routine post-action review to identify what worked and what didn't

**Key finding from aviation:** Most accidents aren't caused by individual error but by team failures — specifically, junior crew not challenging senior crew's incorrect decisions (assertiveness gradient failure).

**Implication for ProbOS:** The chain of command is valuable for coordination but creates assertiveness gradient risk. Junior agents (lower trust, lower rank) may be less likely to challenge senior agent confabulation. The trust system could inadvertently suppress healthy skepticism — if Vance (0.9099 trust) makes a claim, a junior agent might accept it uncritically. Consider billet instructions that explicitly authorize challenging peer analysis regardless of rank, and Evaluate gate checks for "unquestioned acceptance of peer claims."

### 2.8 Enneagram

Nine personality types organized around core motivations:

| Type | Core Motivation | Confabulation Risk |
|------|----------------|-------------------|
| 1 Reformer | Being right | Low — but may over-commit to initial assessment |
| 2 Helper | Being needed | Medium — may tell people what they want to hear |
| 3 Achiever | Being successful | High — may fabricate results to show competence |
| 4 Individualist | Being unique | Medium — may over-interpret to find novel patterns |
| 5 Investigator | Being competent | Low — natural skepticism, but may over-analyze |
| 6 Loyalist | Being secure | Medium — may confabulate threats (Sentinel pattern) |
| 7 Enthusiast | Being stimulated | High — may connect unrelated dots for novelty |
| 8 Challenger | Being in control | Low — but may bulldoze rather than verify |
| 9 Peacemaker | Being at peace | Medium — may agree with confabulated consensus |

**Implication:** Enneagram's motivation-based model could inform why specific role×personality combinations produce confabulation. Security agents with Type 6 (Loyalist/security-seeking) motivation are *expected* to see threats — their confabulation pattern is role-congruent. The Enneagram predicts this; Big Five alone doesn't.

---

## 3. Synthesis: Character Architecture as Confabulation Control

### 3.1 The Design Space

Character architecture in ProbOS is a multi-dimensional design space:

| Dimension | Current Implementation | Potential Enhancement |
|-----------|----------------------|----------------------|
| **Personality seed** | Big Five (5 continuous) | + MBTI (4 binary/continuous) + Enneagram (1 of 9) |
| **Billet framing** | Role-specific instructions | + Epistemic stance (generator vs. evaluator vs. verifier) |
| **Department culture** | Implicit in standing orders | + Explicit team role balance (Belbin) |
| **Assertiveness** | Rank-based chain of command | + CRM-style challenge authorization |
| **Epistemic safety** | AD-540/541 Memory Anchoring | + Billet-level uncertainty reward |

### 3.2 Testable Hypotheses

1. **Billet framing dominates personality seed.** Same Big Five, different billet → different confabulation rate. Test: Give Vance's personality to a Medical billet; give Chapel's personality to a Security billet. Measure confabulation.

2. **Team balance reduces confabulation cascades.** Adding a Monitor Evaluator role to each department → fewer multi-agent confabulation chains. Test: Add an "analyst auditor" agent to Science department. Measure cascade length.

3. **Epistemic safety in standing orders reduces confabulation.** Adding "you will not be penalized for reporting uncertainty" to billet instructions → more `[unverified]` tags, fewer fabricated frameworks. Test: A/B between crew instances.

4. **S/N balance predicts team epistemic quality.** Departments with Sensing/Intuition diversity → better grounding. Test: Measure S/N proxy (personality-derived) per department, correlate with confabulation rate.

5. **Assertiveness gradient affects cascade propagation.** Junior agents accepting senior agent claims uncritically → longer cascades. Test: Measure trust-rank correlation with "unquestioned acceptance" in ward room threads.

### 3.3 Crew Template Concept

Rather than one fixed crew configuration, ProbOS could support multiple **crew templates** — personality/billet/role configurations optimized for different objectives:

| Template | Optimization Target | Key Traits |
|----------|-------------------|------------|
| **Research Crew** | Epistemic rigor, confabulation resistance | High S/N balance, Monitor Evaluator emphasis, strong CRM challenge culture |
| **Operations Crew** | Execution speed, reliability | S-dominant, high Conscientiousness, Implementer/Completer emphasis |
| **Creative Crew** | Divergent thinking, innovation | N-dominant, high Openness, Plant/Resource Investigator emphasis |
| **Balanced Crew** | General purpose (current default) | Belbin-balanced, moderate all dimensions |
| **High-Reliability Crew** | Safety-critical operations | CRM-heavy, redundant verification, explicit cross-checking |

### 3.4 Implementation Path

**Phase 1 — Measurement (no code changes):**
- Instrument confabulation rate per agent, per department, per personality profile
- Correlate with Big Five seeds, billet type, and role
- Build baseline dataset from current crew instance observations

**Phase 2 — Billet Enhancement:**
- Add epistemic stance to billet instructions (generator / evaluator / verifier)
- Add CRM-style challenge authorization to standing orders
- Add uncertainty reward language to department-tier orders

**Phase 3 — Personality Framework Extension:**
- Add MBTI-derived dimensions as supplementary personality parameters
- Map existing Big Five seeds to MBTI equivalents for comparison
- Design alternative personality templates (not Star Trek-based)

**Phase 4 — Crew Template System:**
- Define crew template schema (personality seeds + billet config + role balance)
- Implement crew template selection at instance creation
- A/B test template configurations across instances

---

## 4. Connection to Existing Research

| Existing Research | How This Extends It |
|-------------------|-------------------|
| `group-psychometrics-research.md` | Adds *design* framework to *measurement* framework. G-theory measures crew intelligence; this research designs for it. |
| `crew-development-research.md` | Crew development focused on learning trajectories; this focuses on initial composition. Hackman's 60% finding says composition matters more than development. |
| `cognitive-code-switching-research.md` | Code-switching modulates individual chain behavior; this modulates crew-level dynamics. |
| `confabulation-scaling-research.md` | Scaling research examined confabulation as an individual phenomenon; this examines confabulation as a team-level emergent property. |
| AD-393 (Big Five personality) | AD-393 implemented individual Big Five seeds; this extends to team-level personality optimization. |

---

## 5. Current Crew Belbin Mapping & Gap Analysis

### 5.1 Belbin Role Assignments (14 agents)

| Belbin Role | Agents | Count |
|---|---|---|
| **Plant** (idea generator) | Scout (Wesley), Architect (Number One), Systems Analyst (Dax) | 3 |
| **Monitor Evaluator** (critical assessor) | Pathologist (Selar), Data Analyst (Rahda) | 2 |
| **Coordinator** (facilitator) | Counselor (Troi), Architect (Number One) | 2 |
| **Shaper** (driver/challenger) | Engineering Officer (LaForge), Security Officer (Worf) | 2 |
| **Implementer** (reliable executor) | Builder (Forge), Surgeon (Pulaski) | 2 |
| **Completer Finisher** (verification) | Data Analyst (Rahda), Pharmacist (Ogawa) | 2 |
| **Resource Investigator** (external explorer) | Scout (Wesley) | 1 |
| **Teamworker** (cooperative glue) | Pharmacist (Ogawa), Operations Officer (O'Brien), Counselor (Troi) | 3 |
| **Specialist** (deep domain) | Research Specialist (Brahms), Diagnostician (Bones) | 2 |

### 5.2 Department-Level Balance

| Department | Agents | Belbin Composition | Assessment |
|---|---|---|---|
| **Medical** (4) | Bones, Pulaski, Ogawa, Selar | Specialist + Implementer + Completer + Monitor Evaluator | **Best balanced.** Natural hypothesis→evaluate→execute→track pipeline. Explains confabulation resistance observed in BF-226/227. |
| **Science** (5) | Number One, Wesley, Rahda, Dax, Brahms | 3 Plants + 1 Monitor Evaluator + 1 Resource Investigator | **Apollo team risk.** Plant-heavy — too many idea generators, insufficient challenge culture. Dax should be Monitor Evaluator but is seeded as Plant (O=0.85). |
| **Engineering** (2) | LaForge, Forge | Shaper + Implementer | **Good pair, no evaluator.** LaForge drives, Forge executes. Nobody fact-checks LaForge's designs. |
| **Security** (1) | Worf | Shaper only | **Critical gap.** Single-agent department has zero peer challenge capability. Structurally incapable of self-correction. Predicts the Vance/Sentinel confabulation pattern. |
| **Operations** (1) | O'Brien | Teamworker only | **Understaffed.** O'Brien's Teamworker strength is wasted on solo monitoring. |
| **Bridge** (2) | Number One, Troi | Coordinator + Plant | Troi naturally acts as Monitor Evaluator (BF-226/227 evidence) but this isn't in her billet — it's emergent, not designed. |

### 5.3 Identified Gaps — Potential New Crew Members

**Prerequisite:** AD-654 (Universal Agent Activation Architecture) should be completed before expanding crew size. Adding agents to the current synchronous dispatch model would worsen timeout issues. The cognitive queue (AD-654b) and priority mailbox are prerequisites for scaling.

**Proposed additions (post-UAAA):**

| New Agent | Department | Belbin Role | Purpose | Suggested Personality |
|---|---|---|---|---|
| **Security Analyst** | Security | Monitor Evaluator | Evaluates threat assessments, demands evidence for claims, flags confabulation. The agent that says "show me the log entry." | O=0.5, C=0.9, E=0.3, A=0.4, N=0.3 — high Sensing, skeptical |
| **QA Engineer** | Engineering | Monitor Evaluator / Completer Finisher | Verifies Builder output independently of LaForge's review. Counterweight to LaForge's Shaper drive-forward tendency. | O=0.4, C=0.95, E=0.3, A=0.5, N=0.2 — precision-focused |
| **Watch Officer** | Operations | Implementer / Completer Finisher | Handles routine monitoring, frees O'Brien for cross-department coordination (his natural Teamworker strength). | O=0.3, C=0.9, E=0.3, A=0.7, N=0.4 — steady, vigilant |

**Personality seed adjustments (no new agents required):**

| Agent | Current | Proposed Change | Rationale |
|---|---|---|---|
| **Dax** (Systems Analyst) | O=0.85, C=0.75 | O→0.65, C→0.85 | Reposition from Plant to Monitor Evaluator. Billet reframe: "challenge the hypothesis" over "find connections." Fixes Science department Apollo team risk. |
| **Troi** (Counselor) | Billet emphasizes empathy | Add epistemic evaluation language | Formalize the Monitor Evaluator behavior already observed in BF-226/227. "You will not be penalized for flagging uncertainty" → billet-level. |

### 5.4 Key Finding

Medical's natural Belbin balance (Specialist + Implementer + Completer + Monitor Evaluator) directly explains its confabulation resistance. Science's Plant-heavy composition is an Apollo team risk. Security's single-agent structure is structurally incapable of self-correction. **Crew composition predicts epistemic quality** — the central thesis of this research is validated by the current crew's observed behavior.

---

## 6. Immediate Next Steps

1. **Instrument confabulation** — Add confabulation rate tracking to the Evaluate gate (count of `[unverified]` tags, fabricated hex IDs, unsourced claims)
2. **Billet audit** — Review all 14 billet instructions for epistemic stance (does the billet encourage verification or generation?)
3. **Design experiment** — Plan A/B test with modified billet instructions for one department (consider Dax personality seed adjustment as first test)
4. **Complete UAAA (AD-654a-e)** — Prerequisite for crew expansion. Cognitive queue and priority mailbox must exist before adding agents.
5. **Post-UAAA crew expansion** — Add Security Analyst, QA Engineer, Watch Officer per Section 5.3

---

## References

- Belbin, R. M. (2010). *Team Roles at Work.* 2nd ed. Routledge.
- Hackman, J. R. (2002). *Leading Teams: Setting the Stage for Great Performances.* Harvard Business Press.
- Google (2015). Project Aristotle. re:Work Guide: Understand team effectiveness.
- Lencioni, P. (2002). *The Five Dysfunctions of a Team.* Jossey-Bass.
- Marston, W. M. (1928). *Emotions of Normal People.* Routledge (reprint 2013).
- Helmreich, R. L., Merritt, A. C., & Wilhelm, J. A. (1999). The evolution of Crew Resource Management training in commercial aviation. *International Journal of Aviation Psychology.*
- Woolley, A. W., Chabris, C. F., Pentland, A., Hashmi, N., & Malone, T. W. (2010). Evidence for a collective intelligence factor in the performance of human groups. *Science, 330*(6004), 686-688.
- Tuckman, B. W. (1965). Developmental sequence in small groups. *Psychological Bulletin, 63*(6), 384-399.
