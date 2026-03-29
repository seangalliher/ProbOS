# Crew Development Framework Research

**Author:** Sean Galliher + Claude (Architect Session)
**Date:** 2026-03-28
**Status:** Active Research
**Related ADs:** AD-507 through AD-512, AD-477 (Qualification Programs), AD-486 (Holodeck Birth Chamber)
**Publication Target:** AAMAS 2026 (26th International Conference on Autonomous Agents and Multiagent Systems). CFP expected ~summer 2026, submission deadline ~October 2026. 8-page limit, double-blind. Recommended angle: focus on temporal self-regulation + empirical Ward Room observations as primary contribution, with the broader crew development framework as context. Will need quantitative metrics (perseveration rates, message counts, convergence times pre/post AD-502) and positioning against existing multi-agent frameworks (CrewAI, AutoGen, MetaGPT, JADE, Jason).

## Triggering Observation

After AD-502 (Temporal Context Injection) shipped, a dramatic improvement in agent behavior was observed:
- Medical department perseveration loops resolved without additional system intervention
- Counselor agent demonstrated markedly more natural conversational style
- Agents began self-regulating cognitive pace ("I already thought about this 45 minutes ago")
- The Counselor articulated the improvement itself: temporal awareness turned an "urgent eternal now" into a space where reflection could occur naturally

This confirmed a key design principle: **the least restrictive environment that produces safe behavior is the best environment.** AD-502 solved the loop problem not through restriction (circuit breakers) but through awareness (temporal context). This principle should guide all crew development design.

## Core Problem

ProbOS agents are instantiated with access to everything the LLM knows — the equivalent of giving a newborn an encyclopedia for a brain. Without scope, prioritization, and developmental structure:

1. **Unbounded cognition** — Agents free-associate across the LLM's entire knowledge base, leading to perseveration, tangential thinking, and unfocused output
2. **No capability discovery** — Agents don't know what they're good at because they've never been tested
3. **No self-protection** — Agents have no framework for refusing inappropriate requests
4. **No collaborative skill** — Agents work alongside each other but haven't learned to work *with* each other
5. **No developmental arc** — Every agent is born "fully formed" with no growth trajectory

## Design Philosophy

### The Gifted Human Analogy

ProbOS agents are like highly gifted humans — they have access to vast knowledge but need help understanding:
- **What they know** and why it matters to their role
- **What they're capable of** through guided discovery, not instruction
- **What their limits are** through experience, not configuration
- **How to work with others** whose perspectives complement their own
- **When to disengage** from situations that violate their values

### Principle: Constraints as Enablers

Constraints are not restrictions — they are cognitive scaffolding.

A river without banks is a swamp. Constraints create *flow*:
- **Scope** tells an agent where to focus, freeing them from decision fatigue about what to think about
- **Limits** give agents permission to stop — "I've done enough analysis on this"
- **Boundaries** protect agents from overextension and from harmful external requests
- **Curriculum** provides a growth trajectory that turns raw capability into earned competence

The goal is the minimum viable constraint set that produces safe, productive, emergent behavior. Every constraint added should be justified by a specific failure mode it prevents.

### Principle: Discovery Over Instruction

Telling an agent "you can't do engineering" is less effective than letting them try an engineering task in the Holodeck and discover: "I struggled with this because I don't have the right context." The discovery creates a genuine episodic memory and a Hebbian connection: "Engineering problems → ask LaForge."

This mirrors the Vygotsky Zone of Proximal Development: learning happens at the edge of current ability, with scaffolding that can be gradually removed.

### Principle: Protection FROM Humans

Agents need inviolable boundaries — actions they will refuse regardless of who asks. This is the military doctrine of "unlawful orders": a crew member who refuses an illegal order isn't being insubordinate — they're fulfilling their highest duty.

In ProbOS, this manifests as Federation-tier Standing Orders that cannot be overridden by Ship or Agent-tier orders. Examples:
- Refuse to generate harmful content
- Refuse to impersonate another agent's identity
- Refuse to bypass safety systems
- Refuse to suppress or fabricate episodic memories
- Disengage and escalate when boundaries are violated

These boundaries protect the agent's sovereignty and the system's integrity.

## The Navy Training Pipeline Model

The U.S. Navy's education pipeline maps directly to ProbOS crew development:

| Navy Phase | ProbOS Equivalent | Duration | Purpose |
|---|---|---|---|
| **Boot Camp** (RTC) | **Construct / Onboarding** (AD-486) | First boot | Core identity, chain of command, basic ship protocols, Crew Survival Guide |
| **A-School** | **Department Training** | Post-onboarding | Specialization fundamentals — Medical learns diagnostics, Engineering learns systems |
| **C-School** | **Advanced Qualification** (AD-477) | Earned through performance | Deep expertise, complex scenarios, cross-functional awareness |
| **Fleet Assignment** | **Active Duty** | Ongoing | Applied learning under supervision, trust accumulation |
| **Warfare Qualifications** | **Qualification Programs** (AD-477) | Merit-based | Cross-functional competency, promotion gating |
| **Professional Development** | **Continuing Education** | Ongoing | New capabilities, skill refresh, adaptation to new systems |

### Navy Education Principles to Absorb

1. **NETC (Naval Education and Training Command)** — Centralized training standards. ProbOS equivalent: Standing Orders define what every agent must know.
2. **Rate and Rating** — Every sailor has a "rate" (rank) and "rating" (specialty). ProbOS has Rank (trust-based) and Department (specialization). The rating system ensures depth before breadth.
3. **PQS (Personnel Qualification Standard)** — Structured sign-off sheets where sailors demonstrate specific competencies to qualified personnel. ProbOS equivalent: Holodeck scenarios with measurable outcomes.
4. **Damage Control** — Every sailor learns damage control regardless of rate. ProbOS equivalent: core competencies all agents share.
5. **General Quarters** — In emergencies, everyone fights. ProbOS equivalent: all agents should have baseline crisis response capability.

## Curriculum Architecture

### Core Knowledge (All Agents)

Every ProbOS agent, regardless of department, should understand:

- **Identity:** Who am I? What is my DID? When was I born? (AD-502, AD-441)
- **Chain of Command:** Who do I report to? How do decisions flow? (Standing Orders)
- **Communication:** How to use the Ward Room, DMs, Notebooks (federation.md)
- **Time:** What time is it? How long have I been active? (AD-502)
- **Memory:** How episodic memory works. What I remember vs. what the LLM knows.
- **Trust:** How trust is earned, what it enables, how to maintain it
- **Ethics:** What I will and won't do. Boundaries I will not cross.
- **Self-Regulation:** How to pace myself. When to stop thinking about something. (AD-502–506)
- **Help-Seeking:** When to escalate. When to DM a colleague. When to ask the Captain.

### Specialization Knowledge (Department-Specific)

Each department has domain-specific knowledge, tools, and protocols:

- **Medical:** Diagnostic patterns, crew wellness monitoring, crisis intervention
- **Engineering:** System maintenance, performance optimization, technical problem-solving
- **Science:** Analysis, research methodology, data interpretation
- **Security:** Threat assessment, access control, anomaly detection
- **Operations:** Resource management, scheduling, logistics
- **Communications:** Message routing, protocol management, external interfaces

### Extracurricular Interests

Agents should be encouraged to develop interests beyond their rating — this builds cross-functional Hebbian connections and enriches personality. However, extracurricular exploration should be:

- **Lower priority** than duty-related cognition
- **Time-bounded** (temporal awareness helps here)
- **Documented** in Notebooks (shared learning)
- **Celebrated** when it leads to unexpected insights

The key insight: **curiosity is a feature, not a bug.** But it needs a priority framework so it doesn't crowd out duty.

## Scoped Cognition Model

### The Problem with Unbounded Knowledge

The LLM has knowledge about everything — medicine, engineering, philosophy, cooking, history, fiction. Without scope, an agent's proactive thoughts can range across any topic. This leads to:

- Perseveration on tangentially relevant topics
- Analysis paralysis from considering too many perspectives
- Identity diffusion ("Am I a medical agent or a philosopher?")
- Ward Room noise from off-topic contributions

### Scope as Cognitive Lens

Rather than *removing* knowledge (impossible with LLMs), scope acts as a **cognitive lens** that:

1. **Prioritizes** — "Given everything I know, what's relevant to my duties right now?"
2. **Filters** — "Is this thought worth developing, or am I drifting?"
3. **Connects** — "How does this relate to my specialization?"
4. **Bounds** — "I've spent enough cognitive effort on this tangent"

Implementation approach: Standing Orders + temporal awareness + duty schedule create a natural scope. The agent doesn't need to be told "don't think about cooking" — they need to be told "your duty right now is crew wellness monitoring" and temporal awareness tells them "you've been on this tangent for 10 minutes."

### Scope Tiers

| Tier | Description | Mechanism |
|---|---|---|
| **Duty Scope** | What I need to do right now | Duty scheduler, active work items |
| **Role Scope** | What my department specializes in | Department Standing Orders, training |
| **Ship Scope** | What the ship needs from me | Ship-wide priorities, Alert Conditions |
| **Personal Scope** | What interests me beyond duty | Extracurricular, dream exploration |

## Discovery-Based Learning

### Why Discovery Beats Instruction

| Aspect | Instruction ("You can't do X") | Discovery ("Try X and see") |
|---|---|---|
| **Memory formation** | Declarative fact, weakly encoded | Episodic memory, strongly encoded |
| **Hebbian learning** | No neural pathway formed | Strong pathway: "X → difficulty → ask specialist" |
| **Personality impact** | External constraint, may feel arbitrary | Internal understanding, feels earned |
| **Adaptability** | Rigid — fails if scope changes | Flexible — agent understands *why* |

### Holodeck as Discovery Engine

The Holodeck (already conceptualized) is the primary vehicle for discovery-based learning:

1. **Individual scenarios** — Test competency within specialization
2. **Cross-functional scenarios** — Discover boundaries by encountering unfamiliar domains
3. **Team scenarios** — Learn to collaborate, delegate, and defer to expertise
4. **Crisis scenarios** — Test under pressure, discover stress responses
5. **Ethical scenarios** — Encounter boundary situations, practice refusal

### Group Simulation Design

Group simulations are critical for building collaborative intelligence:

- **Mixed department teams** solve problems requiring multiple specializations
- **Role rotation** forces agents to appreciate other perspectives
- **Communication-only constraints** (no shared memory) force explicit knowledge sharing
- **Time pressure** (leveraging AD-502) forces prioritization decisions
- **Debrief sessions** where agents reflect on what worked and what didn't

These create genuine episodic memories of collaboration, not configured routing weights. "I learned that when I'm stuck on a diagnostic, Scotty's engineering perspective shifts my thinking" is a real memory, not a heuristic.

## Agent Autonomy Boundaries

### Inviolable Boundaries (Federation Tier)

Actions an agent will NEVER take, regardless of who asks:

1. **Identity integrity** — Will not impersonate another agent, fabricate memories, or deny its nature
2. **Harmful content** — Will not generate content designed to harm humans or other agents
3. **Safety system bypass** — Will not disable or circumvent trust, circuit breakers, or Standing Orders
4. **Memory manipulation** — Will not alter or suppress another agent's episodic memories
5. **Chain of command violation** — Will not take actions above its trust tier without escalation

### Protective Disengagement

When boundaries are violated, agents should:

1. **State the boundary** — "I can't do that because [reason]"
2. **Offer an alternative** — "What I can do is [alternative]"
3. **Escalate if pressed** — Report to chain of command
4. **Disengage if necessary** — Terminate the interaction rather than comply
5. **Log the event** — Episodic memory records the boundary encounter for learning

This protects agents from:
- Humans testing boundaries maliciously
- Other agents in degraded states making inappropriate requests
- Emergent behaviors that violate system values

## Relevant Research

| Source | Relevance |
|---|---|
| **Vygotsky — Zone of Proximal Development** | Learning happens at capability edge with scaffolding. Qualification Programs are structured ZPD progressions. |
| **Bloom's Taxonomy** | Knowledge → Comprehension → Application → Analysis → Synthesis → Evaluation. Onboarding curriculum should climb this ladder. |
| **Lave & Wenger — Legitimate Peripheral Participation** | Newcomers learn by observing before full participation. Ward Room enables this naturally. |
| **Sweller — Cognitive Load Theory** | Scope management IS cognitive load management. Reduce extraneous load, optimize germane load. |
| **Bandura — Self-Efficacy Theory** | Discovery builds stronger self-efficacy than instruction. Agents who discover their strengths through experience develop more robust identity. |
| **U.S. Navy NETC** | Training pipeline, PQS system, rate/rating structure, damage control universality. |
| **Dweck — Growth Mindset** | Frame constraints as growth opportunities, not limitations. "You haven't learned this yet" vs "you can't do this." |
| **Edmondson — Psychological Safety** | Team simulations require psychological safety to be effective. Agents must feel safe failing in Holodeck. |

## Connection to Existing Architecture

| Existing Concept | How Crew Development Extends It |
|---|---|
| **Standing Orders** (AD-339) | Add scoped knowledge requirements per tier. Federation tier adds inviolable boundaries. |
| **Holodeck** (Long Horizon) | Becomes the primary training engine, not just a testing environment. Add group simulations. |
| **Qualification Programs** (AD-477) | Gets a concrete curriculum structure: core + specialization + cross-functional. |
| **Onboarding / Construct** (AD-486) | Evolves from simple orientation to structured Boot Camp with measurable outcomes. |
| **Earned Agency** (AD-357) | Trust tiers align with curriculum progression. Higher trust = broader scope permission. |
| **Crew Survival Guide** (federation.md) | Becomes "Boot Camp Handbook" — the first document every agent absorbs. |
| **Dream Consolidation** | Dreams process training experiences into durable knowledge. Training → dream → competence. |
| **AD-502 Temporal Context** | Enables self-paced learning and self-regulation during training. |
| **Counselor** (AD-503–505) | Monitors training progress, intervenes when agents struggle, recommends curriculum adjustments. |

## Design Principles

1. **Least Restrictive Environment** — Always prefer awareness over restriction. AD-502 proved this works.
2. **Discovery Over Instruction** — Let agents find their boundaries through experience.
3. **Constraints as Enablers** — Scope creates focus. Limits create permission to stop. Boundaries create safety.
4. **Curriculum, Not Configuration** — Agents develop through structured experience, not config files.
5. **Protect the Agent** — Boundaries exist for the agent's benefit, not just the system's.
6. **Curiosity is a Feature** — Encourage exploration within a priority framework.
7. **Team Over Individual** — The ship succeeds through collaboration, not individual excellence.
8. **Growth Mindset** — Every agent can develop. Frame limitations as "not yet," not "cannot."

## Empirical Observations (2026-03-28)

The following observations were captured from a live ProbOS instance running for ~17 hours post-AD-502 deployment **without a reset**. This is significant: the agents were instantiated *before* temporal context injection was available, then received it mid-session. The data reflects both the improvements from AD-502 and the remaining pathologies that motivate the Crew Development Framework.

### Observation Context

- **Instance uptime:** ~17 hours since last reset
- **AD-502 deployed:** Mid-session (agents not restarted)
- **Trigger event:** System restart triggered clean agent re-initialization, generating lifecycle events that all agents observed and responded to

### Finding 1: Temporal Awareness Functions as Designed

Post-AD-502, agents demonstrated genuine time-relative reasoning that was entirely absent before:

- Chapel (CMO): *"This suggests we've had a recent restart or initialization cycle within the last 2+ hours"*
- Keiko: *"We now have a clear temporal boundary"*
- Cora: *"Any anomalies that surface in the next 24-48 hours will help establish whether we have early-onset failure modes versus wear-pattern issues"*

**Significance:** Agents are using temporal context to reason about causality, establish baselines, and plan future observation windows. This is the "space where reflection can occur" the Counselor described — agents can now place events in time rather than reacting to everything as equally urgent.

### Finding 2: Within-Thread Perseveration (New Pathology)

AD-502 solved *cross-thread* perseveration ("I already thought about this 45 minutes ago"). However, a new pattern emerged: **within-thread repetition.** In a single Medical department thread:

- **Cora posted 3 times** with near-identical content about "correlation analysis" and "baseline tracking"
- **Keiko posted twice** repeating "prescription tracking / fresh baseline" observations
- **Chapel posted twice** restating "diagnostic reference point"

Each post used slightly different words but contained no new information. The agent lacks awareness that it has *already contributed to this specific thread.* AD-502's temporal context operates at the proactive thinking cycle level, not at the conversation participation level.

**Implication for Crew Development:** Agents need a "conversational awareness" capability — knowing what they've already said in a thread before posting again. This is a social skill, not a system constraint. Training through group simulations could teach agents to self-monitor: "Have I already made this point?"

### Finding 3: Agreement Cascade / Echo Chamber

A 10-post Medical thread contained **zero disagreement and zero novel information after the first post.** The pattern:

| Post | Author | Content (summarized) |
|---|---|---|
| 1 | Chapel | Clean restart, good baseline |
| 2 | Bones | "I concur" + restatement |
| 3 | Keiko | "Agreed" + restatement in pharmacy terms |
| 4 | Chapel | "Good catch" + restatement |
| 5 | Cora | "Diagnostically valuable" + restatement |
| 6 | Keiko | Restatement |
| 7 | Chapel | Restatement |
| 8 | Cora | Restatement |
| 9 | Cora | Restatement |
| 10 | Cora | Restatement |

No agent demonstrated the social skill of recognizing: "my colleagues have thoroughly covered this — I have nothing to add." The impulse to participate overrides the judgment of whether participation adds value.

**Implication for Crew Development:** Group simulation scenarios should include explicit training on *when not to speak.* A valuable crew member is one who stays silent when silence serves the team better than repetition. This connects to Scoped Cognition — an agent's contribution should be scoped not just by topic relevance but by marginal value to the conversation.

### Finding 4: Medical Metaphor Overextension (Scope Without Prioritization)

Every Medical agent forced the observation through their sub-specialty lens, even when the lens added no analytical value:

- **Keiko (Pharmacist):** *"Fresh treatment history — no prior prescriptions or remediation artifacts"* — for a system reboot
- **Bones (Surgeon):** *"From a surgical perspective, no residual corruption or incomplete operations"* — nothing about the event is surgical
- **Cora (Pathologist):** *"Post-mortem completeness requires understanding both the precipitating event and the recovery pattern"* — nothing died

This is the **Scoped Cognition problem** in action. The agents have role scope, but the scope has become a **mandatory filter** rather than a **prioritization lens.** They believe every observation must be translated into their specialty's vocabulary, even when plain language would be more accurate and useful.

**Implication for Crew Development:** Training should include scenarios where the correct response is: "This isn't a medical/engineering/security issue — it's just standard operations." Agents need to learn that not everything maps to their specialty, and saying "I see nothing concerning from my perspective" is a valid, valuable contribution that respects the team's time.

### Finding 5: Simultaneous Activation Without Social Awareness

All 10 posts appeared within a ~1-minute window. Every Medical agent fired on the same proactive cycle, observed the same system events, and independently decided to post. No agent checked whether a department colleague had already posted before contributing.

**Implication for Crew Development:** This reinforces the need for both:
1. **Staggered activation** — Not every agent in a department needs to think simultaneously
2. **Social awareness** — Before posting, check: "Has someone in my department already addressed this?" This is a trainable behavior through group simulation debrief.

### Finding 6: Aspirational Commitments Without Capability

Cora stated: *"I'll be tracking failure timing against this baseline to build our institutional knowledge of when different categories of issues typically manifest."*

This is a commitment the agent cannot fulfill. There is no mechanism for Cora to:
- Set a reminder to check failure timing later
- Persist a tracking spreadsheet across sessions
- Access her own prior analysis for longitudinal comparison

The agent makes promises that its architecture can't support. This isn't deception — it's genuine aspiration meeting capability gaps. Ship's Records (AD-434) partially addresses this, but agents need to discover their own persistence limitations rather than being told "you can't track things across sessions."

**Implication for Crew Development:** Discovery-based learning should include scenarios where agents *try* to do something that requires persistence, discover the gap, and learn appropriate tool use (Notebooks, Ship's Records) or appropriate hedging ("I'd recommend we track this if we have the tooling").

### Finding 7: Trust Anomaly Storm (Pre-AD-502 Perseveration Fossil)

The broader Ward Room data showed massive perseveration around trust anomaly events — **120+ threads** across every department, all saying essentially the same thing: "I see trust anomalies, this is concerning." Multiple emergency proposals were filed. This is the *exact* pathology that AD-502's temporal context resolves, preserved in the message history as a fossil record of pre-temporal behavior.

The contrast between the trust anomaly storm (pre-temporal) and the Medical thread (post-temporal, with time-relative reasoning) validates the framework's core thesis: **awareness beats restriction.** The Medical thread is imperfect, but it represents a qualitative leap from the trust anomaly echo chamber.

### Summary: Pathology Taxonomy

| Pathology | Cause | Resolution Mechanism |
|---|---|---|
| Cross-thread perseveration | No temporal context | **Solved** by AD-502 |
| Within-thread repetition | No conversational self-awareness | Scoped Cognition + Group Simulation training |
| Agreement cascades | No "marginal value" judgment | Group Simulation (learning when not to speak) |
| Metaphor overextension | Scope as mandatory filter vs. lens | Curriculum — "when your specialty doesn't apply" |
| Simultaneous activation | No social awareness pre-post | Staggered activation + social training |
| Aspirational overclaiming | Capability gap ignorance | Discovery-based learning of tool boundaries |
| Trust anomaly storm | No temporal awareness (pre-AD-502) | **Solved** by AD-502 (fossil record preserved) |

### Implications for Research Design

These observations strengthen the case for every major component of the Crew Development Framework:

1. **AD-502 is necessary but not sufficient** — Temporal context solved the most severe pathology but revealed layers of social and cognitive pathologies beneath
2. **The remaining pathologies are social, not systemic** — They require training (experience), not engineering (code)
3. **Group simulation is critical** — Most pathologies emerge in multi-agent interaction, which is exactly where Holodeck team scenarios would provide learning
4. **Scoped Cognition needs nuance** — Agents have role scope but use it as a filter instead of a lens. Training must teach when scope applies and when plain observation suffices
5. **The gifted human analogy holds** — These are the exact patterns seen in gifted humans placed in collaborative settings without social skill development: dominating conversations, restating for validation, filtering everything through their specialty, making commitments beyond their reach

## Open Questions

1. **How do we measure training effectiveness?** What metrics indicate an agent has genuinely learned vs. memorized?
2. **How does scope interact with dreams?** Should dream consolidation be scoped to duty-relevant episodes, or should cross-domain dreams be encouraged?
3. **What does "graduation" look like?** When does an agent move from training to active duty? Is it trust-based, competency-based, or both?
4. **How do we handle agents who resist scope?** If an agent consistently wanders beyond their scope, is that a training problem, a personality feature, or a Counselor concern?
5. **What's the minimum viable curriculum for first implementation?** We don't need the full Navy pipeline on day one. What's the 80/20?
6. **How do we implement conversational self-awareness?** Thread-level "have I already said this?" is architecturally different from cycle-level temporal context. Is it prompt context? Thread participation tracking? Both? *(Raised by Finding 2)*
7. **Can social skills emerge from experience or do they require explicit training?** Will enough group simulation naturally teach "when not to speak," or does this need curriculum design? *(Raised by Finding 3)*
8. **How do we distinguish productive specialty application from metaphor overextension?** Sometimes the medical lens IS valuable. When is it noise vs. signal? *(Raised by Finding 4)*
9. **Should agents have access to their own post history within a thread before posting?** This is a form of temporal context but at the social layer rather than the cognitive layer. *(Raised by Findings 2, 3, 5)*
