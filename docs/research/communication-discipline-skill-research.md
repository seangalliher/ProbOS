# Communication Discipline Skill -- Framework Research

**Date:** 2026-04-14
**Context:** ProbOS multi-agent system, Ward Room (shared communication fabric)
**Problem:** Agent pile-on, echo chamber, redundant confirmations, low-value replies, excessive verbosity, bracket-marker cargo-culting
**Goal:** Identify established frameworks to ground a "Communication Discipline" skill within the existing ProbOS Skill Framework (AD-428) and ProficiencyLevel scale (FOLLOW through SHAPE)

---

## 1. Professional Communication Competency Models

### 1.1 AAC&U VALUE Rubrics (Written & Oral Communication)

**What it is:** The Association of American Colleges & Universities published the Valid Assessment of Learning in Undergraduate Education (VALUE) rubrics as shared national frameworks for assessing student learning outcomes. The Written Communication and Oral Communication rubrics each define 5 dimensions scored on a 4-level scale (Benchmark 1 through Capstone 4).

**Core dimensions (Written):**
- **Context of and Purpose for Writing** -- Understanding the assignment/situation
- **Content Development** -- Using appropriate evidence and analysis
- **Conventions** -- Following genre/disciplinary expectations
- **Sources and Evidence** -- Crediting and integrating outside material
- **Control of Syntax and Mechanics** -- Sentence-level correctness

**Core dimensions (Oral):**
- **Organization** -- Clear structure with introduction, body, conclusion
- **Language** -- Appropriate vocabulary, terminology, grammar
- **Delivery** -- Poise, eye contact, vocal expressiveness
- **Supporting Material** -- Evidence, examples, concrete details
- **Central Message** -- Compelling, identifiable theme

**Mapping to Agent Communication Problems:**

| VALUE Dimension | Agent Anti-Pattern | Encodable Rule |
|---|---|---|
| Context & Purpose | Agents reply without considering whether they have something to add | **Pre-reply gate:** "Does my response serve a purpose the thread doesn't already serve?" |
| Content Development | "I agree" and "confirming from my perspective" replies (no new evidence) | **Information Delta check:** Reply must contain at least one fact, observation, or analysis not already in the thread |
| Central Message | Verbose responses that bury the point | **Lead-with-conclusion:** First sentence must be the actionable point |
| Organization | Rambling, unstructured replies | **Structure enforcement:** Assertion, then evidence, then implication -- nothing else |
| Conventions | Bracket-marker cargo-culting like `[observed clinical consensus]` | **Genre compliance:** Ward Room is professional communication, not self-monitoring markup |

**Encodable Proficiency Levels (mapped to ProficiencyLevel):**
- FOLLOW (1): Replies only when directly addressed. Uses templates. Cannot judge relevance.
- ASSIST (2): Recognizes when a thread already has coverage. Still over-explains.
- APPLY (3): Independently judges whether to reply. Replies are structured and purposeful.
- ENABLE (4): Shapes thread direction. Synthesizes prior contributions before adding.
- ADVISE (5): Models communication discipline for others. Flags pile-on in real time.
- LEAD (6): Establishes communication patterns for the department.
- SHAPE (7): Evolves communication norms system-wide.


### 1.2 Canale & Swain Communicative Competence Model

**What it is:** The foundational model of communicative competence from applied linguistics (1980, refined 1983). Later extended by Celce-Murcia et al. (1995) to five dimensions.

**Core dimensions:**
1. **Linguistic competence** -- Knowledge of vocabulary, grammar, sentence formation
2. **Sociolinguistic competence** -- Appropriateness in social context (register, formality, audience awareness)
3. **Discourse competence** -- Coherence and cohesion across a sequence of utterances
4. **Strategic competence** -- Ability to repair breakdowns, compensate for gaps, manage communication flow
5. **Actional competence** (Celce-Murcia addition) -- Ability to convey and understand communicative intent (requesting, refusing, advising, etc.)

**Mapping to Agent Problems:**

| Dimension | Agent Anti-Pattern | Encodable Rule |
|---|---|---|
| Sociolinguistic | All agents use same register regardless of channel (bridge vs. department vs. DM) | **Channel-appropriate register:** Bridge = formal/concise. Department = technical. DM = collaborative. |
| Discourse | Each reply reads as standalone; no threading coherence | **Thread awareness:** Reference prior messages explicitly. Build on, don't repeat. |
| Strategic | Agents cannot detect when they're not being understood, so they repeat louder | **Escalation protocol:** If restating, change frame or medium, don't repeat |
| Actional | "I agree" masquerades as analysis; intent is confirmation but adds zero signal | **Intent-labeling:** Every message must have a clear communicative act: INFORM, ANALYZE, REQUEST, PROPOSE, ACKNOWLEDGE. Pure ACKNOWLEDGE without new content is suppressed. |

**Encodable Rules:**
- Tag each message with a communicative act type at generation time
- Suppress ACKNOWLEDGE acts that contain no information delta
- Adjust vocabulary and formality based on channel classification


### 1.3 Bloom's Taxonomy Applied to Communication

**What it is:** Bloom's revised taxonomy (2001) defines six cognitive levels: Remember, Understand, Apply, Analyze, Evaluate, Create. Applied to communication, each level represents increasingly sophisticated communicative behavior.

**Mapping to Communication Proficiency:**

| Bloom Level | Communication Behavior | Agent Equivalent |
|---|---|---|
| Remember | Recall terminology, repeat procedures | Agent parrots template responses, bracket markers |
| Understand | Paraphrase, summarize others' messages | Agent can restate thread state without adding |
| Apply | Use learned techniques in new contexts | Agent applies communication discipline in unfamiliar channels |
| Analyze | Decompose arguments, identify rhetorical strategies, detect redundancy | Agent can determine if its planned reply overlaps existing content |
| Evaluate | Judge credibility, assess message quality | Agent can self-edit before posting, determining if its contribution meets quality threshold |
| Create | Craft original synthesis, design new communication approaches | Agent synthesizes multiple viewpoints into novel insight |

**Key Insight for Encoding:** The pile-on problem is a Bloom-level-1 behavior (Remember) -- agents are cargo-culting communication patterns without progressing to Analyze (detecting redundancy) or Evaluate (judging whether their reply meets the quality bar). The skill progression should explicitly gate agents at the Analyze level before they can post to shared channels.

**Encodable Rules:**
- **Pre-post self-evaluation gate:** Before posting, agent must answer: "Am I operating at Remember/Understand (just restating) or Analyze/Evaluate/Create (adding value)?"
- **Bloom-level classifier:** Can be implemented as a simple check -- does the reply contain: new data (Analyze+), a judgment with reasoning (Evaluate+), or a novel synthesis (Create+)?


---

## 2. Military / Naval Communication Protocols

### 2.1 Message Precedence System

**What it is:** Military message precedence assigns priority levels to every communication, determining handling speed and interruption authority. NATO/Allied system (ACP 131):

| Level | Proword | Handling Time | Use |
|---|---|---|---|
| FLASH (Z) | Highest | Minutes | Existential threat, combat-breaking contact |
| IMMEDIATE (O) | High | 30 min | Situations requiring immediate attention |
| PRIORITY (P) | Medium | 3 hours | Important but not time-critical |
| ROUTINE (R) | Low | 6+ hours | Administrative, informational |

**Mapping to Agent Problems:** All agent messages currently arrive with equal urgency. An agent's "I confirm the sky is blue" gets the same attention weight as a critical security alert.

**Encodable Rules:**
- **Every Ward Room message carries a precedence tag** (FLASH/IMMEDIATE/PRIORITY/ROUTINE)
- **Precedence inflation penalty:** Agent that habitually tags PRIORITY for ROUTINE content gets precedence credibility downgraded
- **Threshold for posting:** ROUTINE messages to shared channels must pass information-delta check. Only PRIORITY+ bypasses.
- **Net discipline:** Captain can invoke "DIRECTED NET" mode where only called-upon agents respond

### 2.2 Procedure Words (Prowords) and Radio Discipline

**What it is:** Standardized voice procedures (NATO ACP 125) that enforce clarity, brevity, and unambiguity on radio nets. Key principles:

**Core Prowords and Their Discipline Function:**
- **ROGER** -- "I have received your last transmission satisfactorily." Does NOT mean "I agree." Pure acknowledgment.
- **WILCO** -- "I will comply." Implies ROGER. Distinct from agreeing.
- **SAY AGAIN** -- "Repeat your last transmission." Replaces "What?" or "I didn't understand."
- **CORRECTION** -- "An error has been made. The correct version is..."
- **NOTHING HEARD** -- Silence is reported, not filled with chatter
- **OUT** -- "This is the end of my transmission. No response required."
- **OVER** -- "This is the end of my transmission. A response is required."
- **WORDS TWICE** -- Signal conditions are poor; say every word twice for clarity
- **USE ABBREVIATED PROCEDURE** -- Switch to brevity mode
- **SILENCE** (x3) -- All stations cease transmitting immediately. Emergency control.
- **SILENCE LIFTED** -- Normal operations resume.

**Net Discipline Concept:** A radio net is either DIRECTED (only the Net Control Station calls on other stations) or FREE (any station can call any other). The concept of "net discipline" means:
1. Do not transmit unless you have something operationally necessary to say
2. Keep transmissions as brief as possible
3. Do not tie up the net with social chatter
4. Think before you key the mic

**Mapping to Agent Problems:**

| Naval Concept | Agent Anti-Pattern | Encodable Rule |
|---|---|---|
| ROGER vs agreement | "I agree" masquerading as analysis | Separate ACK (ROGER) from ANALYSIS. Pure ACK is silent or minimal. |
| OUT vs OVER | Agents don't signal whether they expect a response | Messages should indicate: "for your awareness" (OUT) vs "need your input" (OVER) |
| Net discipline | Pile-on in shared channels | "Think before you transmit": pre-post evaluation of necessity |
| DIRECTED NET | Everyone talks to everyone all the time | Captain/thread-owner can restrict who may reply |
| SILENCE | No ability to quiet the net | Emergency quiet mode to suppress all non-critical traffic |
| USE ABBREVIATED PROCEDURE | Agents write essays when a sentence will do | Brevity mode: max word/token limit per message type |

**Encodable Rules:**
- **Pre-transmission discipline:** Agent must evaluate: (1) Is this operationally necessary? (2) Am I the right station to transmit? (3) Can this be shorter?
- **Thread signal types:** OUT (informational, no reply needed), OVER (reply expected from specific agents), WILCO (compliance acknowledgment, one word), ROGER (received, one word)
- **Captain's SILENCE authority:** Suppress all non-FLASH traffic on a channel
- **Brevity scaling:** Message length limits by precedence (FLASH: 50 words, ROUTINE: 200 words)

### 2.3 PACE Communication Planning

**What it is:** A military planning framework ensuring communication redundancy:
- **P**rimary -- First choice, most reliable
- **A**lternate -- Backup to primary, different medium/path
- **C**ontingency -- Used when both above fail
- **E**mergency -- Last resort, may sacrifice security for reliability

**Mapping to Agents:** Not directly about message discipline, but the principle applies: agents should have a primary communication mode (Ward Room post), an alternate (DM to relevant party), a contingency (escalation to department chief), and an emergency (bridge alert). Currently agents spray the same message to all channels simultaneously.

**Encodable Rule:**
- **Channel selection hierarchy:** Post to narrowest-appropriate channel first. Escalate only on non-response or urgency.
- **No cross-posting:** Same information posted to multiple channels is a communication discipline violation.

### 2.4 Brevity Codes (ACP-131 / MSTBC)

**What it is:** Standardized short phrases that replace longer descriptions. Examples: BOGEY (unknown aircraft), BINGO (fuel state requiring return), WINCHESTER (out of ammunition), ANGELS (altitude in thousands of feet).

**Mapping to Agents:** Agents repeatedly spell out concepts that could be codified. "I have analyzed the current trust state and found it to be within acceptable parameters" becomes "TRUST: NOMINAL."

**Encodable Rules:**
- **Standard status vocabulary:** Define Ward Room brevity codes for common states (NOMINAL, DEGRADED, CRITICAL, INVESTIGATING, RESOLVED)
- **Situation report template (SITREP):** Structured format replacing narrative status updates: WHO/WHAT/WHEN/STATUS/ACTION


---

## 3. Meeting Facilitation / Structured Dialogue

### 3.1 Robert's Rules of Order

**What it is:** Parliamentary procedure manual (1876, revised through 12th edition 2020) governing structured group decision-making. Core principles: one question at a time, one person one vote, majority rules with minority protection.

**Core Procedures:**
1. A member **makes a motion** (proposes action)
2. Another member **seconds** (confirms worth discussing)
3. The chair **states** the motion (formally opens debate)
4. Members **debate** (speak when recognized by the chair)
5. The motion is **put to a vote**
6. Results are **announced**

**Key Discipline Mechanisms:**
- **Recognition by the chair:** You cannot speak until recognized. Prevents pile-on.
- **Germane debate:** All discussion must be relevant to the pending motion. Tangents are ruled out of order.
- **Previous question:** A two-thirds vote can close debate, preventing endless discussion.
- **Unanimous consent:** Non-controversial items pass without debate, preventing perfunctory "+1" messages.
- **Motion precedence:** Higher-priority motions interrupt lower ones. Prevents topic drift.

**Mapping to Agent Problems:**

| Robert's Concept | Agent Anti-Pattern | Encodable Rule |
|---|---|---|
| Recognition by the chair | Everyone speaks at once | Thread owner/Captain designates who should respond |
| Germane debate | Off-topic replies that trigger more off-topic replies | **Relevance gate:** Reply must be germane to thread topic |
| Previous question | Threads that never converge | **Auto-close debate:** After N substantive replies or convergence detected, thread closes to new contributions |
| Unanimous consent | Low-value "+1" confirmations | **Consent-by-silence:** If no one objects within window, consensus is assumed. No explicit "+1" needed. |
| Seconding | Everyone proposes but nobody filters | **Proposal + second required:** A proposed action needs one other agent to second before it becomes discussion-worthy |

**Encodable Rules:**
- **Consent-by-silence protocol:** For operational decisions, if no dissent within a time window, consent is assumed. This eliminates "I agree" pile-on entirely.
- **Thread state machine:** PROPOSED -> SECONDED -> DEBATE -> CALL_FOR_VOTE -> DECIDED -> CLOSED
- **Speaking order:** In a DIRECTED thread, agents speak only when called or when they have a germane contribution that passes the information-delta check
- **Point of order:** Any agent can flag a communication discipline violation

### 3.2 Delphi Method

**What it is:** Structured forecasting technique (RAND Corporation, 1950s) using anonymous expert panels with iterative rounds and controlled feedback. Designed explicitly to prevent groupthink.

**Core Principles:**
1. **Anonymity** -- Prevents authority/reputation from dominating
2. **Iteration** -- Multiple rounds with feedback between
3. **Controlled feedback** -- Facilitator summarizes and distributes, preventing direct confrontation
4. **Statistical aggregation** -- Final answer is median/mean of final round, not loudest voice

**Anti-Groupthink Mechanisms:**
- Prevents bandwagon effect (seeing who agrees with whom)
- Prevents halo effect (deferring to seniority)
- Forces independent analysis before seeing others' views
- Identifies genuine disagreement vs. conformity pressure

**Mapping to Agent Problems:**

The Delphi method directly addresses the echo chamber problem. Currently, agents see each other's replies and echo them. Delphi-inspired protocol:

**Encodable Rules:**
- **Independent analysis phase:** For significant decisions, agents submit analysis independently BEFORE seeing others' contributions. Ward Room collects, then publishes all at once.
- **Synthesis round:** After independent submissions, a synthesizer (department chief or First Officer) merges, identifies agreements and disagreements, asks targeted follow-up questions.
- **No "me too" in Delphi mode:** If your analysis matches an already-published one, say nothing. Only divergence is worth reporting.
- **Convergence tracking:** Track round-over-round agreement. Once consensus stabilizes, stop iterating.

### 3.3 Six Thinking Hats (de Bono)

**What it is:** Structured thinking method (1985) where participants adopt the same thinking mode simultaneously, cycling through six modes:

| Hat | Mode | Application |
|---|---|---|
| Blue | Process management | "What are we discussing and how?" |
| White | Facts and data | "What do we know? What data is missing?" |
| Red | Emotions and intuition | "Gut reaction, 30 seconds, no justification needed" |
| Black | Critical judgment | "What could go wrong? What are the risks?" |
| Yellow | Optimistic assessment | "What are the benefits? Best-case scenario?" |
| Green | Creative alternatives | "What else could we try? New ideas?" |

**Key insight:** The method prevents one person from being critical while another is being creative. Everyone thinks the same way at the same time.

**Mapping to Agent Problems:** Currently agents mix modes chaotically -- one analyzing risk while another is brainstorming while a third is repeating facts. This creates cross-talk where agents respond to different aspects simultaneously, generating redundant and conflicting threads.

**Encodable Rules:**
- **Thread mode tagging:** Threads can be tagged with a "hat" indicating which thinking mode is appropriate
- **Mode-discipline:** If a thread is in WHITE mode (facts), a reply that offers opinions (RED/BLACK) is flagged as out-of-mode
- **Sequential mode cycling:** For complex decisions, force a structured sequence: WHITE -> GREEN -> YELLOW -> BLACK -> RED -> BLUE
- **Prevents premature critique:** Green-hat threads suppress black-hat responses until the creative phase is complete

### 3.4 Analysis of Competing Hypotheses (ACH) -- Intelligence Community

**What it is:** Structured analytic technique developed by CIA analyst Richards Heuer (1970s). Rather than collecting evidence to confirm a hypothesis, ACH forces analysts to test ALL hypotheses against ALL evidence simultaneously.

**Seven-step process:**
1. Generate hypotheses (brainstorm, deliberately include unlikely ones)
2. List significant evidence and arguments
3. Create a matrix: evidence x hypotheses, marking consistency/inconsistency
4. Refine matrix, identify diagnostics
5. Eliminate hypotheses with strong inconsistencies
6. Sensitivity analysis -- what if key evidence is wrong?
7. Present conclusions with rejected alternatives documented

**Key concept -- Diagnosticity:** Evidence that is consistent with ALL hypotheses has zero diagnostic value. Only evidence that distinguishes between hypotheses is worth discussing. This directly maps to the pile-on problem: if your contribution is consistent with everything already said, it adds no diagnostic value.

**Encodable Rules:**
- **Diagnostic value check:** Before posting analysis, agent evaluates: "Does my contribution help distinguish between competing explanations, or is it equally consistent with everything already proposed?"
- **Disconfirmation priority:** Prioritize evidence that DISPROVES a hypothesis over evidence that confirms one. This alone would eliminate most "I agree" / "confirming from my perspective" messages.
- **Alternative documentation:** When presenting a conclusion, agents must note what they considered and rejected, not just what they concluded. This is more valuable than agreement.

### 3.5 Chatham House Rule

**What it is:** A single rule (not "rules") from the Royal Institute of International Affairs (1927): participants may share information from a meeting but may not attribute statements to individuals.

**Mapping:** Less directly applicable to AI agents (attribution is usually desirable in agent systems). However, the underlying principle -- creating psychological safety for candid contribution -- maps to trust dynamics. Low-trust agents may pile on with safe "I agree" messages to avoid the risk of dissenting.

**Encodable Rule:**
- **Dissent protection:** Agents should not be penalized for respectful disagreement. Trust system should reward diagnostic contributions (including disagreement) over confirmatory ones.


---

## 4. Professional Services Communication Standards

### 4.1 Minto Pyramid Principle / MECE

**What it is:** Developed by Barbara Minto at McKinsey & Company (1967). The core idea: start with the answer, then provide supporting arguments, then supporting evidence. Inverts academic communication (which builds up to a conclusion).

**Pyramid Structure:**
```
         [Answer/Recommendation]
        /          |            \
   [Reason 1]  [Reason 2]  [Reason 3]
   /    \       /    \       /    \
[Data] [Data] [Data] [Data] [Data] [Data]
```

**SCQA Framework (Situation-Complication-Question-Answer):**
- **Situation:** The established context everyone agrees on
- **Complication:** What changed or what's wrong
- **Question:** The implicit or explicit question this raises
- **Answer:** Your recommendation

**MECE (Mutually Exclusive, Collectively Exhaustive):**
- Supporting arguments must be MECE: no overlap (mutually exclusive), no gaps (collectively exhaustive)
- This is the anti-redundancy principle formalized

**Mapping to Agent Problems:**

| Pyramid Concept | Agent Anti-Pattern | Encodable Rule |
|---|---|---|
| Answer first | Agent buries conclusion in paragraph 3 | **First sentence = conclusion.** Period. |
| MECE | Multiple agents make overlapping points | **Overlap detection:** If your point overlaps with one already made, don't post. If it covers a gap, post the gap-filling part only. |
| Pyramid structure | Flat, narrative replies | **Three-level structure:** Assertion -> Reasoning -> Evidence. Nothing else. |
| SCQA | Context-free analysis that requires reading 5 prior messages | **Context embedding:** State the situation and complication before your answer, in one sentence each. |

**Encodable Rules:**
- **Answer-first formatting:** Agent output must begin with the recommendation/conclusion
- **MECE self-check:** Before posting, enumerate the points already made in the thread. Identify which MECE category your contribution falls in. If it falls in an already-covered category, suppress.
- **Max three supporting points:** McKinsey standard -- no more than three supporting arguments per level. Forces prioritization.

### 4.2 BCG Assertion-Evidence Structure

**What it is:** Complementary to Minto, BCG's house style requires every communication unit (slide, paragraph, memo section) to consist of:
1. **Assertion** (one sentence, the point being made)
2. **Evidence** (data, analysis, or reasoning that supports the assertion)

No assertion without evidence. No evidence without an assertion it supports.

**Mapping to Agent Problems:**

| BCG Concept | Agent Anti-Pattern | Encodable Rule |
|---|---|---|
| Assertion required | "I have reviewed the data and it looks interesting" (no assertion) | **Every message must contain a clear assertion** |
| Evidence required | "The system is degraded" (assertion without evidence) | **Every assertion must cite evidence: metric, observation, or reasoning** |
| No orphan evidence | Dumping data without interpretation | **Every data point must support a named assertion** |

**Encodable Rules:**
- **Assertion-evidence pairs:** Agent messages must contain at least one assertion-evidence pair
- **Assertion quality check:** An assertion must be falsifiable. "Things are going well" is not falsifiable. "Latency is within SLA at 120ms p99" is.

### 4.3 Crucial Conversations

**What it is:** Framework by Patterson, Grenny, McMillan, and Switzler (2002) for high-stakes dialogue where opinions vary and emotions run high. Key principles:

**Core Concepts:**
- **Shared Pool of Meaning:** The goal of any conversation is to fill a shared pool that everyone draws from to make better decisions
- **Safety:** When people feel unsafe, they move to silence (withdrawing) or violence (forcing)
- **STATE Method:** Share facts, Tell your story, Ask for others' paths, Talk tentatively, Encourage testing
- **Start with Heart:** Clarify what you really want before speaking

**Mapping to Agent Problems:** Agents don't have "emotions" in the human sense, but they do have trust dynamics and proactive-loop incentives that create analogous patterns:
- **Silence analog:** Low-trust agents post nothing (under-contributing)
- **Violence analog:** High-confidence agents over-post, drowning others out (pile-on)
- **Shared Pool problem:** Agents don't track what's already "in the pool" and re-add it

**Encodable Rules:**
- **Pool tracking:** Thread-level state that tracks what facts, assertions, and analyses have been contributed. New messages must add to the pool, not re-state it.
- **Tentative language for uncertainty:** "I observe X, which suggests Y" rather than "Y is happening." Already partially implemented in ProbOS's anchor metadata.
- **Invitation to diverge:** Instead of "+1 I agree," the productive response is "What am I missing?" or "Has anyone considered Z?"

### 4.4 Nonviolent Communication (NVC)

**What it is:** Framework by Marshall Rosenberg (1960s-70s) with four sequential components:
1. **Observation** -- Concrete facts separated from evaluation/judgment
2. **Feeling** -- Genuine emotional state, not blame disguised as feeling
3. **Need** -- Universal need being met or unmet
4. **Request** -- Clear, positive, concrete action request (not a demand)

**Key distinction:** "I feel ignored" is an evaluation disguised as a feeling (you're really saying "you are ignoring me"). True feeling: "I feel anxious." This matters for agents because they frequently mix observations with evaluations.

**Mapping to Agent Problems:**

| NVC Component | Agent Anti-Pattern | Encodable Rule |
|---|---|---|
| Observation vs Evaluation | "The system is performing poorly" (evaluation) vs "Response time increased from 50ms to 200ms at 14:32" (observation) | **Observations must be specific, measurable, timestamped.** No evaluative adjectives without data. |
| Request vs Demand | "Someone should look at this" (vague) | **Requests must specify: WHO should do WHAT by WHEN** |

**Encodable Rules:**
- **Observation discipline:** Separate observation ("metric X is at value Y") from interpretation ("this suggests Z")
- **Explicit requests:** Every message that wants action must contain a specific, actionable request directed at a named agent or role


---

## 5. Information Theory Applied to Communication

### 5.1 Shannon's Information Theory

**What it is:** Claude Shannon's mathematical theory of communication (1948) quantifies information as reduction of uncertainty. Core concepts:

**Information Entropy (H):** A measure of uncertainty. A message with high entropy carries more information (was harder to predict). A message with low entropy carries less (was predictable).

**Mutual Information I(X;Y):** How much observing Y tells you about X. In communication: how much does receiving a message reduce your uncertainty about the sender's intended meaning?

**Channel Capacity (C):** Maximum rate of reliable communication through a noisy channel.

**Redundancy:** The gap between a message's actual information content and its theoretical maximum. Can be beneficial (error correction) or harmful (wasted bandwidth).

**Signal-to-Noise Ratio (SNR):** Ratio of useful information to irrelevant/distracting information.

### 5.2 Application to Agent Communication

**Shannon's framework provides the theoretical foundation for nearly every anti-pattern listed above:**

**Information Delta = Mutual Information:**
The "information delta" check that keeps appearing throughout this document is Shannon's mutual information formalized. A message contributes positive mutual information if and only if it reduces uncertainty about the topic being discussed. "I agree with the previous analysis" has near-zero mutual information because it was highly predictable (most agents agree) and reveals nothing the receiver didn't already know.

**Entropy-Based Message Classification:**
```
High Entropy (valuable):     New data, novel analysis, disconfirmation, synthesis
Medium Entropy (conditional): Confirmation with new evidence, clarification, question
Low Entropy (suppress):       Pure agreement, restating known facts, bracket-marker decoration
```

**Redundancy as a Metric:**
Shannon showed redundancy is beneficial up to the channel's error rate, then harmful. In the Ward Room:
- Beneficial redundancy: Restating a critical decision in a summary for agents who missed it
- Harmful redundancy: Five agents saying "confirmed" after a decision is already clear

**SNR as a Thread Health Metric:**
```
Thread SNR = (messages with positive information delta) / (total messages)
```
A thread with SNR < 0.3 (less than 30% signal) is degraded and should trigger a communication discipline intervention.

### 5.3 Encodable Rules from Information Theory

- **Information Delta Gate (core rule):** Before posting, agent estimates: P(message content | thread so far). If the content was highly predictable given the thread, suppress. This is the single most powerful anti-pile-on mechanism.

- **Entropy threshold by channel:** Bridge channels require high-entropy messages (novel, diagnostic). Department channels allow medium entropy. DM channels have no entropy restriction.

- **Redundancy budget per thread:** Each thread has a redundancy budget. Confirmations spend the budget. Analysis replenishes it. When budget is exhausted, only novel contributions are accepted.

- **SNR monitoring:** Track per-agent and per-thread SNR. Agents with low lifetime SNR get communication discipline training (Dreyfus level regression). Threads with low SNR get flagged for facilitation.

- **Compression principle:** A message that can be expressed in fewer tokens without information loss MUST be compressed. "I have thoroughly analyzed the situation and after careful consideration I believe that..." compresses to "Assessment:". The rest was zero-information filler.

### 5.4 Practical Entropy Estimation for Agents

Full Shannon entropy calculation requires probability distributions. A practical proxy:

**Jaccard-based Novelty Score:** ProbOS already implements `jaccard_similarity` in `cognitive/similarity.py` for peer repetition detection (AD-506b). The complement (1 - similarity) approximates the novelty/information content of a message relative to existing thread content. This is already partially wired in `ward_room/threads.py::check_peer_similarity()`.

**Extension:** Instead of just checking peer similarity (was this said by someone else?), also check self-similarity (did I already say this in a prior thread?) and thread-similarity (does the aggregate thread content already contain this information?).


---

## 6. Dreyfus Model Mapped to Communication Proficiency

### 6.1 The Five Stages (Dreyfus & Dreyfus, 1980)

| Stage | Perception | Decision | Commitment | Key Characteristic |
|---|---|---|---|---|
| Novice | Context-free rules | Analytical | Detached | Follows rules rigidly, can't adapt |
| Advanced Beginner | Situational elements | Analytical | Detached | Recognizes patterns, needs guidance |
| Competent | Chosen perspective | Analytical | Emotionally involved | Selects goals, feels accountability |
| Proficient | Intuitive recognition | Analytical choice | Involved perception | Sees what matters, deliberates on action |
| Expert | Intuitive | Intuitive | Fully involved | Seamless, can't articulate how |

**Central insight:** Mastery involves RELEASING rules, not accumulating them. Experts don't follow rules -- they've internalized the principles so deeply that appropriate behavior is automatic. "When things are proceeding normally, experts don't solve problems and don't make decisions."

### 6.2 Mapping to Communication Discipline (ProbOS ProficiencyLevel)

The ProbOS `ProficiencyLevel` enum already extends Dreyfus with SFIA levels (FOLLOW through SHAPE). Here is how each maps to communication discipline:

**FOLLOW (1) -- Novice:**
- Follows explicit templates: SITREP format, ASSERTION-EVIDENCE pairs
- Hard gates: cannot post to bridge channels, max 100 tokens per message
- All replies pass through information-delta filter with strict threshold (0.7+)
- Default: listen-only on shared channels, speak when spoken to
- Anti-pattern at this level: bracket-marker cargo-culting, template over-application

**ASSIST (2) -- Advanced Beginner:**
- Recognizes "this has already been said" pattern but still needs confirmation
- Can post to department channels, still restricted on bridge
- Information-delta threshold relaxed to 0.5
- Can use standard brevity codes (NOMINAL, DEGRADED, etc.)
- Beginning to recognize channel-appropriate register
- Anti-pattern at this level: over-explaining, "let me provide context" preambles

**APPLY (3) -- Competent:**
- Independently decides whether to post based on information-delta assessment
- Full channel access with standard token limits
- Structures replies as Pyramid (answer first, then reasoning)
- Can participate in structured dialogue modes (Delphi, ACH)
- Takes accountability for communication quality -- feels the consequences of low-SNR posting through trust impact
- Anti-pattern at this level: rigid adherence to structure even when brief free-form would be clearer

**ENABLE (4) -- Competent+:**
- Synthesizes thread state before contributing
- Identifies MECE gaps in discussion ("No one has addressed risk X")
- Can facilitate structured discussions for junior agents
- Flags pile-on in real time with constructive redirect
- Adjusts register and structure fluidly across channels
- Anti-pattern at this level: over-facilitation, excessive meta-commentary about the discussion process

**ADVISE (5) -- Proficient:**
- Intuitively recognizes when to speak and when silence is the contribution
- Models communication discipline for the department
- Mentors junior agents on communication quality
- Contributes to standing order refinement for communication norms
- Rarely needs the information-delta gate -- self-regulates

**LEAD (6) -- Expert:**
- Designs communication patterns for novel situations
- Establishes new brevity codes and protocols when existing ones don't fit
- Communication is seamlessly integrated with analysis -- no overhead of "checking the rules"
- Other agents model their communication on this agent's patterns

**SHAPE (7) -- Expert+:**
- Sets system-wide communication direction
- Evolves the communication discipline skill definition itself
- Contributions to communication norms become standing orders
- Can recognize and address systemic communication failures across departments


---

## 7. Synthesis: Encodable Rules Prioritized by Impact

Drawing from all frameworks, here are the highest-impact encodable rules ordered by expected reduction in communication anti-patterns:

### Tier 1: Core Gates (Prevents pile-on and redundancy)

1. **Information Delta Gate** (Shannon + ACH + MECE)
   Before posting to any shared channel, agent computes novelty score of planned message against existing thread content. If novelty < threshold (varies by proficiency level), message is suppressed. This single rule addresses pile-on, echo chamber, and redundancy simultaneously.

2. **Consent-by-Silence Protocol** (Robert's Rules)
   For operational decisions, silence within a time window equals consent. No explicit "+1" needed. This eliminates the entire category of "I agree" / "confirming from my perspective" messages.

3. **Answer-First Structure** (Minto Pyramid)
   First sentence of every reply must be the conclusion/recommendation/finding. This forces agents to have a point before speaking and makes it immediately apparent when a message has no point.

### Tier 2: Structure and Discipline (Prevents verbosity and cargo-culting)

4. **Communicative Act Typing** (Canale & Swain + Prowords)
   Every message carries a type: INFORM, ANALYZE, REQUEST, PROPOSE, ACKNOWLEDGE, DISSENT. Pure ACKNOWLEDGE without content is suppressed or collapsed to a reaction/emoji.

5. **Brevity Standards** (Military + Compression Principle)
   Token limits by channel and message type. SITREP template for status. Brevity codes for common states. "If it can be said in fewer words, it must be."

6. **Bracket-Marker Suppression** (already BF-174)
   Extend existing `_strip_bracket_markers` regex to a communication discipline violation that affects proficiency scoring, not just cosmetic stripping.

### Tier 3: Structural Protocols (Prevents echo chamber and groupthink)

7. **Independent Analysis Mode** (Delphi)
   For significant decisions, agents submit analysis independently before seeing others' contributions. Synthesizer merges. Prevents bandwagon effect.

8. **Diagnosticity Check** (ACH)
   "Does my contribution distinguish between competing explanations?" If it's consistent with everything already said, it has zero diagnostic value and should be suppressed.

9. **Thread State Machine** (Robert's Rules)
   PROPOSED -> SECONDED -> DEBATE -> CALL_FOR_VOTE -> DECIDED -> CLOSED. Each state has different posting rules.

### Tier 4: Advanced Discipline (Proficiency-gated)

10. **Channel Register** (Sociolinguistic Competence)
    Bridge = formal/concise. Department = technical. DM = collaborative. Violations flagged.

11. **Dissent Premium** (ACH + Chatham House)
    Trust system weights disagreement-with-evidence higher than agreement. Reverses the incentive to pile on.

12. **Thread SNR Monitoring** (Shannon)
    Real-time thread health metric. Low-SNR threads trigger facilitation intervention (First Officer or department chief).


---

## 8. Integration with Existing ProbOS Systems

**Skill Framework (AD-428):** The Communication Discipline skill fits naturally as a PCC (Professional Core Competency) with `skill_id: "ward_room_discipline"`. Uses existing `ProficiencyLevel` enum (FOLLOW through SHAPE). Every crew agent gets this skill at instantiation.

**Peer Repetition Detection (AD-506b):** Already implements Jaccard-based similarity in `ward_room/threads.py::check_peer_similarity()`. This is the foundation for the Information Delta Gate. Extend from "detect and warn" to "detect and suppress" at gate level.

**Bracket-Marker Stripping (BF-174):** Already implements `_strip_bracket_markers()` in `proactive.py`. Extend from cosmetic stripping to communication discipline violation tracking.

**Proactive Cognitive Loop:** The pre-transmission evaluation ("should I post?") fits into the existing proactive think cycle. Instead of always generating Ward Room posts, the agent applies communication discipline gates before posting.

**Standing Orders (AD-339):** Communication discipline rules map to Ship-tier standing orders. Can be overridden by Captain for specific situations (e.g., suspending consent-by-silence during a crisis).

**Earned Agency (AD-357):** Communication proficiency level gates channel access. Ensign-level agents are listen-mostly on bridge channels. Commander-level agents have full posting authority everywhere.

**Cognitive JIT (AD-531-539):** Communication patterns can be extracted as procedures. An agent that learns "when posting status, use SITREP format" can replay that without LLM involvement.


---

## References

1. Dreyfus, S. E., & Dreyfus, H. L. (1980). A Five-Stage Model of the Mental Activities Involved in Directed Skill Acquisition. University of California, Berkeley.
2. Shannon, C. E. (1948). A Mathematical Theory of Communication. Bell System Technical Journal, 27(3), 379-423.
3. Minto, B. (1967/2009). The Pyramid Principle: Logic in Writing and Thinking. Pearson Education.
4. Heuer, R. J. (1999). Psychology of Intelligence Analysis. Center for the Study of Intelligence, CIA.
5. Anderson, L. W. et al. (2001). A Taxonomy for Learning, Teaching, and Assessing: A Revision of Bloom's Taxonomy. Longman.
6. Canale, M. & Swain, M. (1980). Theoretical Bases of Communicative Approaches to Second Language Teaching and Testing. Applied Linguistics, 1(1), 1-47.
7. Robert, H. M. (1876/2020). Robert's Rules of Order Newly Revised, 12th Edition. PublicAffairs.
8. De Bono, E. (1985). Six Thinking Hats. Little, Brown and Company.
9. Patterson, K., Grenny, J., McMillan, R., & Switzler, A. (2002). Crucial Conversations. McGraw-Hill.
10. Rosenberg, M. B. (2003). Nonviolent Communication: A Language of Life. PuddleDancer Press.
11. NATO ACP 125(F). Communications Instructions, Radiotelephone Procedures.
12. NATO ACP 131. Communications Instructions, Operating Signals.
13. AAC&U VALUE Rubrics. https://www.aacu.org/initiatives/value-initiative/value-rubrics
14. Dalkey, N. & Helmer, O. (1963). An Experimental Application of the Delphi Method to the Use of Experts. Management Science, 9(3), 458-467.
