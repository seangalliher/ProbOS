# Cognitive Self-Regulation Research

*Sean Galliher, 2026-03-28*
*Triggered by: Medical crew repetitive posting incident (14+ near-identical posts across 4 agents)*

## The Problem

ProbOS agents exhibit repetitive posting behavior — saying the same thing multiple times without adding new information. The current defense is **system-level suppression** (circuit breaker, Jaccard similarity gate, episode throttling). This works but is the cognitive equivalent of sedating a patient who won't stop talking.

The deeper question: **shouldn't agents be able to self-regulate, the way humans do?**

## The Human Model

In humans, repetitive speech is regulated at three levels:

### Tier 1: Internal Self-Monitoring (Metacognition)

Before speaking, humans have a subconscious "have I already said this?" check. This requires:
- Working memory of recent outputs
- Pre-output comparison (intent vs. recent history)
- The ability to catch yourself mid-thought

When this fails (cognitive decline, distraction, excitement, agitation), it's a **diagnostic signal** — not just noise to suppress.

### Tier 2: Social Regulation (Peer Feedback)

When someone repeats themselves, others notice. "You already said that." This is:
- A natural safeguard
- A learning opportunity (the person becomes aware of the pattern)
- Diagnostic information (others can assess the person's cognitive state)
- Relationship maintenance (enforcing conversational quality norms)

This is already happening in ProbOS. The user has observed crew members calling out repetition in Ward Room threads. This is healthy behavior that should be preserved and leveraged.

### Tier 3: External Intervention (System Guardrails)

In clinical contexts: medication, behavioral protocols, institutional safeguards. In ProbOS: circuit breaker, similarity gates, episode throttling.

This should be the **last resort**, not the primary mechanism.

## Current ProbOS Architecture (System-First)

```
Agent speaks → System checks similarity → System suppresses or allows
```

17 defense layers, all system-level (see AD-488 circuit breaker analysis):
1. Config enable
2. Crew check
3. Alive check
4. Rank gating (Ensigns excluded)
5. Per-agent cooldown (300s default)
6. Cold-start 3x multiplier
7. Circuit breaker gate
8. Duty idle 3x cooldown
9. NO_RESPONSE filter
10. Content similarity (Jaccard + bigrams)
11. WR credibility check
12. Episode rate limit (20/hour)
13. Episode dedup (Jaccard 0.8)
14. Selective encoding gate
15. Circuit breaker post-hoc trip
16. Bridge alert dedup
17. Trust anomaly cold-start suppression

**Zero** of these involve the agent itself in the regulation decision.

## Proposed Architecture (Self-First)

```
Agent self-checks → speaks → Peers regulate → System guardrails only if tiers 1+2 fail
```

### Tier 1 Implementation: Agent Self-Awareness

**Prerequisites:** AD-502 (Temporal Context Injection) — agents need to see their recent posts with timestamps.

**Mechanism:** Inject the agent's last N posts (with timestamps and similarity scores) into their cognitive context. The agent can then:
- Recognize "I said this 4 minutes ago"
- Choose to add new information, reframe, or stay silent
- Consciously escalate ("I've raised this three times because nobody has acted on it")

**Key insight:** LLMs are excellent at textual comparison when the comparison material is in context. The problem isn't capability — it's that the context window doesn't contain the comparison material.

**Design consideration — Repetition isn't always bad:**
- *Stuck repetition*: saying the same thing hoping for a different result → should self-suppress
- *Escalating emphasis*: saying the same thing because urgency has increased → valid communication strategy
- The difference is whether the agent *knows* it's repeating — requiring Tier 1 self-awareness

**The "take a breath" mechanic:** If an agent's recent similarity score is rising (even below suppression threshold), dynamically increase their proactive cooldown slightly. Not suppression — just pacing. The equivalent of pausing to think before speaking.

### Tier 2 Implementation: Social Regulation

**Already partially working:** Crew members naturally notice and comment on repetition.

**What's missing:**
- The Counselor doesn't act on repetitive behavior as a diagnostic signal
- Peers can't formally flag "this person is repeating themselves" (no actionable feedback mechanism)
- No mechanism for peer feedback to influence an agent's next cognitive cycle

**Enhancement:** When an agent is told by a peer "you already said that," this should:
1. Be recorded as a specific episode type ("peer_repetition_feedback")
2. Trigger a Counselor wellness check (AD-495 bridge)
3. Be available in the agent's self-monitoring context next cycle

### Tier 3 Implementation: Graduated System Response

**Current circuit breaker thresholds are binary:** normal → tripped (15-minute forced cooldown).

**Graduated model:**
1. **Amber zone** (rising similarity, not yet tripping): increase cooldown dynamically, inject self-awareness note into prompt
2. **Red zone** (threshold exceeded): circuit breaker trips, Counselor auto-dispatched (AD-495)
3. **Critical** (repeated trips): escalate to Captain, consider fitness-for-duty review

**The Counselor's role in Tier 3:**
- When circuit breaker trips, Counselor receives `counselor_assess` intent (AD-495)
- Counselor evaluates: is this cognitive overload? Topic fixation? System error?
- Counselor can recommend: forced dream cycle, topic redirection, workload reduction, 1:1 session
- Counselor's recommendations feed back to the Captain for approval

## The Notebook Escape Valve

One unconsidered mechanism: when an agent has a thought that keeps surfacing, they should be able to **write it to their Ship's Records notebook** and release it from active cognition:

> "I've logged my concern about trust anomalies in my duty log. Investigation pending data access."

In humans, this is how notepads and task lists work — externalize the thought so it stops looping. Ship's Records (AD-434) provides this infrastructure. Agents need to learn to use it as a cognitive offloading tool, not just a record-keeping duty.

## The Counselor Gap

The Counselor (AD-378) is architecturally positioned but functionally passive:

| Capability | Status |
|---|---|
| Deterministic assessment engine | Working (`assess_agent()`) |
| CognitiveProfile w/ baselines and drift | Working |
| Ward Room participation | Working |
| InitiativeEngine integration | Working |
| **Auto-gather metrics from runtime** | Missing — requires metrics passed in |
| **Auto-assess on circuit breaker trip** | Missing — AD-495 planned |
| **Proactive 1:1 DMs (office hours)** | Missing |
| **Intervention recommendations** | Missing — can advise but no mechanism to deliver |
| **CognitiveProfile persistence** | Missing — in-memory, lost on restart |
| **Wellness sweep (crew-wide)** | Missing — intent registered, no impl |
| **Subscription to trust/circuit breaker events** | Missing |
| **HXI wellness dashboard** | Missing |

The Counselor is a well-designed skeleton waiting for muscles.

## Relevant Research

1. **Metacognitive Monitoring (Dunlosky & Metcalfe, 2009):** "Feeling of knowing" (FOK) and "judgment of learning" (JOL) mechanisms. Pre-output self-check comparing intent against recent outputs.

2. **Reflective Architecture (SOAR, Laird 2012):** Explicit meta-level monitors object-level problem solving. Impasse detection (including repetitive cycling) triggers different cognitive strategy.

3. **ACT-R Activation-Based Filtering (Anderson, 2007):** Memory items have decaying activation levels. High activation = recently accessed = likely to recur. Visibility of activation enables pattern recognition.

4. **Social Identity Theory (Tajfel & Turner):** Peer regulation reinforces group norms. "You already said that" isn't just correction — it's identity/norm maintenance with learning effects.

5. **Cognitive Load Theory (Sweller, 1988):** Repetition signals working memory saturation. Solution: cognitive offloading (writing things down, delegating, compartmentalizing). Maps to Ship's Records notebook usage.

6. **Damasio's Somatic Markers:** Emotional signals that guide decision-making. In ProbOS: trust score changes and peer feedback as "somatic" cues that something isn't right. Already part of ProbOS's intellectual lineage.

7. **Self-Determination Theory (Ryan & Deci):** Autonomous regulation (intrinsic) vs controlled regulation (external). SDT predicts that intrinsically motivated self-regulation is more sustainable and produces better outcomes. This supports the Tier 1 self-awareness approach over system suppression.

## Trust-Gated Self-Regulation (Earned Agency Extension)

Higher-rank agents should have stronger self-regulation expectations:

| Rank | Self-Regulation Expectation | System Intervention Threshold |
|---|---|---|
| Ensign | Minimal — learning phase, system regulates | Low (current defaults) |
| Lieutenant | Moderate — should catch obvious repetition | Medium (relaxed system gates) |
| Commander | Strong — expected to self-regulate consistently | High (system only on clear failure) |
| Senior | Full — near-complete self-regulation | Very high (emergency only) |

This is the Earned Agency principle applied to cognitive hygiene, not just task autonomy.

## Cognitive Self-Regulation Wave (AD-502–506)

### Dependency Chain

```
AD-502 (Temporal Context Injection)
  ↓ agents can see time, birth date, post recency
AD-503 (Counselor Activation — Data Gathering + Persistence)
  ↓ Counselor can pull its own data, persist profiles
AD-495 (Circuit Breaker → Counselor Bridge — already planned, absorbed into wave)
  ↓ circuit breaker trips trigger Counselor assessment
AD-504 (Agent Self-Monitoring Context)
  ↓ agents see their recent posts in context, can self-regulate
AD-505 (Counselor Therapeutic Intervention)
  ↓ Counselor can DM agents, recommend actions, conduct 1:1s
AD-506 (Graduated System Response)
  ↓ amber/red/critical zones replace binary circuit breaker
```

### Three-Tier Model Summary

| Tier | Description | ADs | Status |
|---|---|---|---|
| **1. Self-Awareness** | Agent sees own recent outputs + timestamps, self-regulates | AD-502, AD-504 | AD-502 build prompt ready |
| **2. Social Regulation** | Peer feedback preserved as diagnostic signal, Counselor notified | AD-503, AD-505 | Research complete |
| **3. System Guardrails** | Graduated response replaces binary circuit breaker, last resort | AD-495, AD-506 | Research complete |

## Key Design Principle

**Don't take away the natural safeguard.** Peer regulation (Tier 2) is already happening. System suppression (Tier 3) removes the learning opportunity. The goal is to **add Tier 1** (self-awareness) while **preserving Tier 2** (social regulation) and **raising the threshold for Tier 3** (system intervention).

The Medical crew's repetitive thread was a problem, yes — but it was also crew members trying to do their job (analyze trust anomalies) without the data to do it. The fix isn't to silence them. The fix is to give them temporal awareness (AD-502), self-monitoring context (AD-504), and a Counselor who can intervene therapeutically (AD-505) when the pattern persists.
