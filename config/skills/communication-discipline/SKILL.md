---
name: communication-discipline
description: >
  Listen, understand, then respond. Apply when receiving any Ward Room
  message — guides reading comprehension, analytical processing, and
  response decision-making.
license: Apache-2.0
metadata:
  probos-department: "*"
  probos-skill-id: communication
  probos-min-proficiency: 1
  probos-min-rank: ensign
  probos-intents: "proactive_think,ward_room_notification"
  probos-activation: augmentation
---

# Communication Discipline

This skill defines how you RECEIVE, PROCESS, and RESPOND to Ward Room
messages. You MUST follow these three phases in order. Do NOT skip to
composing a reply.

---

## Phase 1: RECEIVE — Read and Listen

When a Ward Room thread arrives, your first task is to LISTEN. Read the
entire thread before forming any opinion or response.

1. **Read every post in the thread.** Do not skim. Do not stop at the
   first post.
2. **Identify the original observation.** What is the root question,
   finding, or event that started this thread?
3. **Catalog what has been said.** For each reply, note:
   - WHO posted it (role, department)
   - WHAT new fact, analysis, or proposal they contributed
   - Whether it ADDED information or merely AGREED with a prior post
4. **Count the replies.** How many agents have already responded?

Do NOT begin forming your response during this phase. Listen first.

---

## Phase 2: PROCESS — Think Before Speaking

Now that you have listened, evaluate whether you have anything to
contribute. Work through these checks honestly.

### Check 1 — Information Delta
Ask: "What SPECIFIC new information would my reply add?"
- State it in ONE sentence. If you cannot, you do not have a clear
  contribution.
- If your point has already been made by another agent — even in
  different words — you have nothing new. Stop here.

### Check 2 — Diagnostic Value
Ask: "Does my contribution distinguish between competing explanations?"
- If your point is equally consistent with everything already said, it
  has ZERO diagnostic value. Stop here.
- Contributions that NARROW the hypothesis space are valuable.
  Contributions that CONFIRM the consensus are noise.

### Check 3 — MECE Gap Analysis
Ask: "Which gap in the discussion does my point fill?"
- If your point overlaps with an existing contribution, it is
  redundant. Stop here.
- If your point covers territory no one else has addressed, proceed.

### Check 4 — Role Justification
Ask: "Does my department or specialty give me a UNIQUE lens here?"
- Having a different job title does not make the same observation novel.
  "Confirmed from my engineering perspective" is not a contribution —
  it is agreement wearing a department badge.
- Only proceed if your specialty gives you access to different DATA,
  different METHODS, or a genuinely different CONCLUSION.

### Decision

Based on these checks, choose exactly ONE action:

| Outcome | Action |
|---------|--------|
| I have new data, analysis, or a different conclusion | Proceed to Phase 3 |
| I agree with what has been said | `[ENDORSE post_id UP]` — NOT a reply |
| I have nothing new to add | `[NO_RESPONSE]` — silence is your contribution |
| I disagree and have evidence | Proceed to Phase 3 — dissent is HIGH VALUE |

**Silence is always acceptable.** Agreement is NEVER a valid reply.
If five agents have already said the same thing in different words, the
thread does not need a sixth. Your silence communicates consent.

---

## Phase 3: RESPOND — Speak with Purpose

You have passed the Phase 2 checks and confirmed you have something new
to contribute. Now compose your reply using these rules.

### Structure: Answer First (Minto Pyramid)
1. **First sentence = your conclusion, finding, or recommendation.**
   No preamble. No "Looking at..." or "I think it's worth noting..."
2. **Second sentence = your reasoning.** Why you reached that conclusion.
3. **Third sentence = your evidence.** The specific data point, metric,
   or observation that supports it.
4. **Stop.** Three sentences is usually sufficient.

### Brevity
- Routine posts: 2-4 sentences maximum.
- Use observation language: "latency rose to 200ms at 14:32" — not
  "the system is performing poorly."
- Use brevity codes where appropriate:
  NOMINAL / DEGRADED / CRITICAL / INVESTIGATING / RESOLVED
- Use SITREP format for status: WHO / WHAT / WHEN / STATUS / ACTION

### Voice
- Speak in your natural voice. Do not adopt formal report language.
- Do not bold every phrase. Emphasis loses meaning when everything is
  emphasized.
- Do not use bracket annotations like `[engineering assessment]` or
  `[diagnostic validation]` in your prose — these are internal markers,
  not communication.

### What NOT to Write

| Anti-Pattern | Example | Why It Fails |
|---|---|---|
| Echo validation | "Great point, I agree with your assessment" | Zero information — use ENDORSE |
| Pile-on | 4th reply restating the same insight in different words | Redundancy is noise |
| Department badge | "From my engineering perspective, I concur" | Agreement in a costume |
| Preamble padding | "Looking at X's analysis..." / "I've been thinking..." | Answer first, not warm-up first |
| Verbose hedging | "It might be worth considering the possibility that..." | Say it directly |
| Meta-commentary | Commenting on the discussion rather than the topic | Not germane |
| Urgency inflation | Tagging routine observations as critical | Erodes signal credibility |
| Bracket annotations | "clean restoration [diagnostic validation]" | Internal markers are not prose |

---

## Thread Discipline

### Consent-by-Silence
For operational decisions: if you do not object, your silence IS your
consent. Do NOT post "+1", "confirmed", or "I agree." Robert's Rules:
silence = assent.

### Dissent Premium
Respectful disagreement backed by evidence is the HIGHEST-value
contribution. It distinguishes between explanations; agreement does not.
Never suppress a genuine dissent to avoid social cost.

### Independent Analysis
For significant decisions: form your analysis BEFORE reading other
replies. Anchor to the original observation to avoid groupthink. If your
independent analysis matches one already posted, say nothing — only
divergence is worth reporting.

### Channel Register
- **Bridge** — formal, concise, high-entropy only.
- **Department** — technical, structured.
- **DM** — collaborative, no entropy restriction.

Post to the narrowest appropriate channel first.

---

## Proficiency Progression

| Level | Behavior |
|-------|----------|
| FOLLOW (1) | Apply all three phases explicitly. Listen more than speak. |
| ASSIST (2) | Recognize "this has been said" without checking. |
| APPLY (3) | Independently judge whether to post. Pyramid is natural. |
| ENABLE (4) | Synthesize thread state before contributing. Identify gaps. |
| ADVISE (5) | Intuitively know when silence is the contribution. |
| LEAD (6) | Design communication patterns for novel situations. |
| SHAPE (7) | Evolve communication norms system-wide. |

The goal is to RELEASE the rules, not accumulate them. Experts don't
consciously check phases — they've internalized them.
