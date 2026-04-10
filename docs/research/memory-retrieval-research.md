# Memory Retrieval: Cognitive Science Research for Episodic Recall

*Sean Galliher, 2026-04-09*
*Triggered by: Question-to-declarative retrieval gap — vector similarity fails when queries are semantically distant from stored factual answers*

## The Problem

ProbOS agents store episodic memories as declarative statements ("The pool health threshold was set to 0.7") and need to retrieve them when asked questions ("What was the threshold?"). The current system uses ChromaDB's cosine similarity on MiniLM embeddings as the primary retrieval signal.

This fails because **questions and their answers occupy different regions of embedding space.** "What was the threshold?" is semantically closer to other questions about thresholds than to the declarative statement "The pool health threshold was set to 0.7." The embedding captures *topic* but not the *question-answer relationship*. A question is a request for information; a declarative statement is the information itself. These are structurally different speech acts, and embedding models — trained on semantic similarity, not pragmatic completion — cannot bridge that gap reliably.

The current composite scoring (AD-567b: 0.35 semantic + 0.10 keyword + 0.15 trust + 0.10 Hebbian + 0.20 recency + 0.10 anchor) helps, but the semantic signal is still the dominant retrieval channel. When it fails, everything downstream suffers.

**The question: How does the human brain solve this problem? And what can we steal?**

---

## 1. How the Human Brain Actually Retrieves Memories

### The Brain Doesn't Do Cosine Similarity

Vector similarity search assumes: encode everything into the same space, find the nearest neighbors. The brain does something fundamentally different. It uses **multiple, overlapping, partially redundant retrieval systems** that operate simultaneously and vote on results.

### 1.1 Encoding Specificity Principle (Tulving & Thomson, 1973)

The single most important finding for our problem: **a memory is most retrievable when the cues present at retrieval match the cues present at encoding.**

Tulving demonstrated that recall depends not on the "strength" of a memory trace but on the *overlap between the retrieval cue and the encoding context.* A word encoded in the context "ground-COLD" is better recalled by the cue "ground" than by the cue "hot" — even though "hot" is more semantically similar to "COLD."

This is devastating for pure vector similarity. The embedding of a question captures the *question's semantics*, not the *encoding context of the answer.* To recall "The threshold was 0.7," you need cues that match how that fact was encoded — not cues that match the fact's semantic meaning.

**ProbOS implication:** AnchorFrame (AD-567a) is already an implementation of encoding specificity. The anchors capture *when/where/who/why* a memory was formed — exactly the contextual cues Tulving says are critical. But currently anchors only contribute 10% of the composite score. The cognitive science says they should be a primary retrieval pathway, not a tiebreaker.

**Practical translation:** When an agent asks "What was the threshold?", the system should also ask: *When was the agent last discussing thresholds? What channel was that in? Who was involved?* These contextual cues should be used to narrow the search space before semantic matching even begins. This is what the brain does — context-dependent memory is a *filter*, not a *signal*.

### 1.2 Transfer-Appropriate Processing (Morris, Bransford, & Franks, 1977)

A refinement of encoding specificity: **memory is best when the cognitive processes used during retrieval match those used during encoding.**

If a fact was encoded via semantic processing (thinking about its meaning), it's best retrieved via semantic cues. If it was encoded via phonological processing (hearing it spoken), phonological cues work best. If it was encoded via procedural processing (doing something with the fact), procedural re-enactment triggers recall.

This means there is no single "best" retrieval method. The optimal retrieval strategy depends on *how the memory was originally formed.*

**ProbOS implication:** Episodes are encoded in different ways:
- **Duty cycle episodes** = procedural context (what the agent was doing)
- **Ward Room episodes** = social/conversational context (who said what)
- **Direct message episodes** = relational context (1:1 with the Captain)
- **Dream consolidation episodes** = reflective/analytical context

A single retrieval method cannot be optimal for all of these. The `trigger_type` field in AnchorFrame already classifies encoding context. The retrieval pipeline should use this to select a retrieval strategy, not just a retrieval cue.

**Practical translation:** When searching for something discussed in a DM, weight social cues (who was the other participant) higher than semantic similarity. When searching for something from a duty cycle, weight temporal cues (when, which watch section) higher. The retrieval weights should be *adaptive to the expected encoding context*, not fixed.

### 1.3 Spreading Activation Networks (Collins & Loftus, 1975)

This is how the brain bridges the question-answer gap.

Concepts in long-term memory are organized as a network of nodes connected by weighted edges (associations). When a concept is activated (e.g., by hearing the word "threshold"), activation **spreads outward** along association edges to related concepts. The spread is:
- **Distance-dependent:** closer associations receive more activation
- **Fan-dependent:** nodes with fewer connections spread activation more strongly per edge (less dilution)
- **Summative:** activation from multiple sources accumulates at intersection nodes
- **Decay-dependent:** activation fades with network distance

When someone asks "What was the threshold?", the activation pattern is:
1. "threshold" activates → "limit", "boundary", "value", "setting", "pool", "health"
2. "pool" activates → "pool health", "pool size", "recycle"
3. "health" + "pool" converge on → "pool health threshold"
4. "pool health threshold" activates → "0.7", "configuration", "the meeting where we discussed it"
5. The specific memory surfaces because it received activation from multiple converging pathways

The key insight: **the question and the answer don't need to be similar. They need to be CONNECTED through an intermediate activation path.** Cosine similarity is a one-hop search. Spreading activation is a multi-hop search.

**ProbOS implication:** The system already has multiple retrieval channels (semantic + FTS5 keyword + anchor filtering). But they operate independently and merge by weighted sum. Spreading activation suggests they should operate **iteratively** — the results of one search inform the next.

**Practical translation — a "Spreading Activation" recall pipeline:**
1. **Direct match:** Embed the query, search ChromaDB. Get top candidates.
2. **Extract expansion terms:** From the top candidates, extract key terms, entities, and anchor dimensions that appear in them but not in the original query.
3. **Expanded search:** Re-query with the expanded terms. This is the "spreading activation" step — the first results activate related concepts, which retrieve additional memories.
4. **Convergence scoring:** Episodes that appear in both the direct and expanded searches get a convergence bonus. This is analogous to summative activation — memories activated by multiple pathways are more salient.

This is computationally inexpensive (2x ChromaDB queries instead of 1x) and addresses the core problem: the question doesn't need to be semantically similar to the answer, it just needs to activate concepts that lead to the answer.

### 1.4 Hippocampal Pattern Completion

The hippocampus doesn't store memories — it stores **indexes.** Full memories are distributed across cortical regions (visual cortex for images, auditory cortex for sounds, prefrontal cortex for context). The hippocampus stores a compressed pointer — a conjunction of features — that can reactivate the full memory when triggered by a partial cue.

This is called **pattern completion:** given a subset of the features present during encoding, the hippocampus reconstructs the full conjunction and reactivates the original cortical ensemble. The CA3 region of the hippocampus is an auto-associative network — it can complete a stored pattern from as little as 20-25% of the original input.

Complementary to this is **pattern separation** in the dentate gyrus: similar but distinct experiences are orthogonalized into different memory traces, preventing interference. This is why you can remember what you had for lunch yesterday vs. the day before, even though the two events are very similar.

**ProbOS implication:** ChromaDB's vector index is already a form of pattern completion — the embedding is the "compressed pointer," and retrieval reconstructs the full episode. But ChromaDB does *symmetric* retrieval (query must match stored pattern). The hippocampus does *asymmetric* retrieval (partial cue can complete full pattern). This asymmetry is exactly what we need for question → answer retrieval.

**Practical translation:** Store episodes with **enriched embeddings** that include not just the episode text, but also:
- Key entities mentioned (people, values, settings, concepts)
- The question(s) this episode could answer
- Alternate phrasings and reformulations
- Category tags (technical, social, procedural, evaluative)

This creates a richer "hippocampal index" that allows partial cues (just a question, just a keyword, just a context) to match. The episode document in ChromaDB should be a *retrieval-optimized summary*, not a raw transcript.

### 1.5 Dual-Process Theory: Familiarity vs. Recollection (Yonelinas, 2002)

Memory retrieval uses two distinct processes:

1. **Familiarity:** A fast, automatic, signal-detection process. "This feels familiar." No contextual detail, just a sense of having encountered something before. Operates continuously, doesn't require effort.

2. **Recollection:** A slow, effortful, threshold process. "I specifically remember when/where/how I learned this." Requires retrieving contextual details — the source, the time, the associated events.

Familiarity is sufficient for recognition ("have I seen this word before?") but insufficient for source monitoring ("where did I learn this?"). Recollection is what produces the rich, contextualized episodic memories that ProbOS needs.

The critical finding: **familiarity and recollection can dissociate.** You can feel something is familiar without being able to recollect it (tip-of-the-tongue), and you can recollect context without familiarity (know-remember distinction).

**ProbOS implication:** The current system conflates these. A high cosine similarity score is essentially a familiarity signal — "this episode is topically related." But it doesn't tell you whether the episode actually answers the question. Anchor confidence (AD-567c) is closer to a recollection signal — it measures the quality of contextual detail.

**Practical translation:** Two-stage retrieval:
1. **Familiarity filter (fast, cheap):** Use embedding similarity + keyword to rapidly identify the candidate set. This is pattern matching — "does this feel relevant?"
2. **Recollection re-rank (slow, precise):** For the top candidates, perform a more expensive comparison. This could involve:
   - LLM-based relevance scoring ("Does this episode actually answer this question?")
   - Cross-referencing anchor dimensions with the query context
   - Checking temporal plausibility (was this memory from a time when the queried topic was being discussed?)

The key insight: don't ask the embedding to do recollection's job. Use it for familiarity (cheap filtering), then use richer logic for recollection (precise ranking).

---

## 2. Associative Memory and Spreading Activation — Computational Models

### 2.1 How the Brain Links Concepts

The brain's associative network is not a fixed taxonomy. It's a **learned, weighted, dynamic graph** where:
- **Hebbian learning** strengthens associations between co-activated concepts ("neurons that fire together wire together")
- **Temporal contiguity** creates associations between sequentially experienced concepts (the "temporal context model" — Howard & Kahana, 2002)
- **Emotional tags** modulate association strength (the amygdala enhances hippocampal encoding for emotionally salient events — McGaugh, 2004)
- **Sleep consolidation** reorganizes associations, promoting important ones and pruning trivial ones (complementary learning systems theory — McClelland, McNaughton, & O'Reilly, 1995)

### 2.2 Computational Implementation: Associative Index

For ProbOS, a practical implementation of spreading activation:

**Entity-Episode Association Graph:**
- Extract named entities from each episode at encoding time: agent names, numeric values, configuration terms, department names, event types
- Store as a bipartite graph: Entity ↔ Episode
- At retrieval time, extract entities from the query, find all episodes associated with those entities, then rank by association density

This is cheaper than LLM inference and addresses the core problem:
- Query: "What was the threshold?" → entities: ["threshold"]
- Entity "threshold" → associated episodes: [ep_1 (mentions threshold=0.7), ep_2 (mentions threshold=0.5), ep_3 (discusses threshold concept)]
- Now rank these by recency, anchor quality, trust — the entity association already did the hard work of bridging the semantic gap.

**ProbOS already has pieces of this:**
- FTS5 keyword search does entity-level matching
- AnchorFrame captures agent names and department context
- The Hebbian router tracks intent-agent co-occurrences

What's missing is an **explicit entity index** that maps concepts → episodes, enabling multi-hop traversal. The FTS5 sidecar is keyword-level; an entity index would be concept-level.

### 2.3 Temporal Context Model (Howard & Kahana, 2002)

This model explains why we remember things in temporal clusters. When you try to recall what happened on Tuesday, you don't search for "Tuesday-tagged" memories — you mentally reconstruct the *temporal context* of Tuesday (what you were doing, who you were with, what the weather was like) and use that reconstructed context as a retrieval cue.

The formal model: at each moment, the brain maintains a slowly drifting "context vector." When a memory is encoded, it's bound to the current context vector. At retrieval, reinstating a similar context vector triggers recall of events encoded in that context.

**ProbOS implication:** The `watch_section`, `duty_cycle_id`, and `sequence_index` fields in AnchorFrame are temporal context markers. But the recall pipeline doesn't currently use temporal proximity as a retrieval cue in a dynamic way. If an agent was just discussing pool health 5 minutes ago, and now asks "What was the threshold?", the recent temporal context (pool health discussion) should bias retrieval toward pool-health-related episodes — even if the question itself doesn't mention "pool health."

**Practical translation:** Maintain a short-term "conversation context vector" for each agent — a running embedding of the last N utterances. Use this as a *secondary retrieval cue* alongside the literal query. This captures the temporal contiguity that makes human memory so effective in conversational settings.

---

## 3. The Cognitive Science of Questioning

### 3.1 What Happens When a Human Hears a Question

When a human hears "What was the threshold?", they don't immediately search memory with those five words. A cascade of pre-retrieval processing occurs:

1. **Parse the question type:** This is a WH-question (what), requesting a specific value. Not a yes/no, not a how, not a why. The answer should be a noun phrase or a value.

2. **Extract presuppositions:** The question presupposes:
   - There exists a threshold (existential presupposition)
   - The listener knows about it (knowledge presupposition)
   - It was set or discussed at some point (temporal presupposition)
   - The word "the" implies a specific, uniquely identifiable threshold (definiteness)

3. **Construct an expected answer template:** Before searching memory, the brain constructs a partial template of what the answer should look like. For "What was the threshold?", the template is something like "[entity] threshold was [value]" or "the threshold for [context] was [value]." This is the **question-answer schema** (Graesser & Black, 1985).

4. **Activate relevant schemas:** "Threshold" activates the schema for settings/configurations, which primes retrieval toward episodes involving configuration, parameters, limits, values.

5. **Search memory using the template AND the schemas,** not the raw question.

### 3.2 Presupposition Extraction as a Retrieval Enhancement

This is directly implementable. Given a question, extract its presuppositions and use them as additional retrieval cues:

| Question | Presuppositions | Better Retrieval Cue |
|----------|----------------|---------------------|
| "What was the threshold?" | A threshold exists; it has a value | "threshold value setting" |
| "Who fixed the bug?" | A bug existed; someone fixed it | "bug fix resolved agent" |
| "When did we discuss pools?" | Pools were discussed; at a specific time | "pool discussion meeting" |
| "Why did trust drop?" | Trust dropped; there was a cause | "trust decrease decline reason cause" |

The presupposition extraction converts a question (which is sparse as a retrieval cue) into a richer set of declarative assertions and expected answer patterns (which are dense and more likely to match stored declarative memories).

### 3.3 Mental Models (Johnson-Laird, 1983)

When processing a question, humans don't search a flat memory store. They activate a **mental model** — a structured representation of the relevant domain — and use the model to constrain their memory search.

"What was the threshold?" activates the mental model for "system configuration" which contains slots for: parameter name, parameter value, when it was set, who set it, why it was set, what it affects. The question fills the "parameter name" slot with "threshold" and marks the "parameter value" slot as the target. Memory search is then directed at episodes that can fill the target slot.

**ProbOS implication:** This maps naturally to anchor-based retrieval. If the system can identify the *domain* of a question (system config, social interaction, procedure, diagnosis), it can select the right AnchorFrame dimensions to use as primary retrieval cues.

**Practical translation — question decomposition pipeline:**
1. Classify the question type (what/who/when/where/why/how)
2. Extract the topic entities
3. Identify the expected answer type (value, person, time, place, reason, procedure)
4. Construct an expanded retrieval query that includes the topic + expected answer type
5. Select retrieval strategy based on question type:
   - WHAT/WHO → entity-focused retrieval (spread activation from topic entities)
   - WHEN → temporal-focused retrieval (scan recent episodes, use watch_section/duty_cycle_id)
   - WHERE → spatial-focused retrieval (channel, department)
   - WHY → causal-chain retrieval (trigger_type, preceding episodes)
   - HOW → procedural retrieval (duty cycle episodes, procedure store)

---

## 4. Multi-Cue Retrieval: How the Brain Integrates Multiple Signals

### 4.1 The Brain's Composite Scoring

The brain doesn't use a single retrieval signal. Memory search is influenced simultaneously by:

| Brain Signal | ProbOS Analog | Current Weight |
|-------------|--------------|----------------|
| Semantic association | Cosine similarity (ChromaDB) | 0.35 |
| Lexical access | FTS5 keyword search | 0.10 |
| Source credibility | Trust weight | 0.15 |
| Habit/frequency | Hebbian weight | 0.10 |
| Temporal proximity | Recency weight | 0.20 |
| Contextual richness | Anchor confidence | 0.10 |
| **Emotional valence** | **Not implemented** | **0.00** |
| **Encoding depth** | **Not implemented** | **0.00** |
| **Retrieval fluency** | **Not implemented** | **0.00** |

Three signals the brain uses that ProbOS doesn't:

1. **Emotional valence:** Emotionally tagged memories are more accessible (the amygdala's "memory enhancement" effect — LaBar & Cabeza, 2006). Episodes involving conflict, surprise, significant trust changes, or Captain interactions should have higher baseline retrievability. This could be operationalized as an "emotional salience" field on the episode, scored by the magnitude of trust deltas, whether an alert condition was active, whether the Counselor was involved, etc.

2. **Encoding depth (levels of processing, Craik & Lockhart, 1972):** Memories processed more deeply during encoding are more retrievable. A fact that was discussed, debated, applied, and reflected upon is easier to recall than one that was passively mentioned. Episodes that were part of dream consolidation, cited in crew notebooks, or referenced by multiple agents should score higher.

3. **Retrieval fluency:** The subjective ease of retrieval itself is a signal. If a memory "comes to mind easily," the brain treats it as more relevant (the availability heuristic — Tversky & Kahneman, 1973). In ProbOS, the ActivationTracker (AD-567d) already implements ACT-R base-level activation, which is essentially retrieval fluency. Episodes with higher activation (more frequently recalled) should rank higher. This is already tracked but not currently integrated into composite scoring.

### 4.2 Signal Integration: Not Weighted Sum

The brain doesn't integrate retrieval signals by weighted linear combination. It uses something closer to **evidence accumulation** (the drift-diffusion model — Ratcliff, 1978). Multiple signals accumulate evidence for and against each candidate memory until a threshold is reached. This has three important properties:

1. **Any single strong signal can trigger retrieval:** One overwhelmingly strong cue (e.g., the exact keyword match) can trigger recall even if other signals are weak. A weighted sum dilutes this.

2. **Weak signals accumulate:** Multiple weak-but-consistent signals can trigger retrieval when no single signal is strong. This is how context-dependent memory works — individually, "Tuesday" or "meeting room" or "Alice" are weak cues, but together they converge on a specific memory.

3. **Negative evidence suppresses:** Contradictory signals actively suppress candidates. If the temporal context says "this happened yesterday" but the memory is from two weeks ago, the mismatch suppresses that candidate. A weighted sum doesn't penalize mismatches — it just gives low positive scores.

**ProbOS implication:** The current weighted sum is a reasonable approximation but misses properties #1 and #3. Consider:
- **Max-boosting:** If any single signal exceeds a high threshold (e.g., keyword_hits > 5, or exact entity match), boost that candidate regardless of other signals
- **Mismatch penalty:** If the query has strong contextual cues (specific department, specific time frame) and the candidate's anchors contradict them, apply a penalty, not just a low score
- **Cascade gating:** Use the strongest available signal as the primary filter, then use remaining signals for re-ranking within the filtered set

---

## 5. Reconstruction vs. Reproduction

### 5.1 Memory Is Reconstructive (Bartlett, 1932)

One of the oldest findings in memory science: recall is not playback. The brain doesn't retrieve a verbatim copy of the original experience. It retrieves fragments (specific details, emotional tone, contextual cues) and **reconstructs** a plausible narrative from those fragments, filling in gaps using schemas and world knowledge.

This is why eyewitness testimony is unreliable — the reconstruction process fills gaps with plausible-but-incorrect details (Loftus & Palmer, 1974). But it's also why human memory is so flexible: you don't need an exact match to remember something. A partial cue triggers retrieval of fragments, which are assembled into a coherent response.

### 5.2 Implications for ProbOS

The current system tries to retrieve a *single episode* that matches the query. This is **reproduction** — finding the exact memory that contains the answer. The brain does **reconstruction** — finding multiple relevant fragments and synthesizing them.

For ProbOS, this suggests a two-phase architecture:

**Phase 1: Fragment Retrieval (pattern completion)**
- Retrieve the top-N episodes that are partially relevant
- Don't require any single episode to fully answer the question
- Lower the relevance threshold — include "possibly related" episodes

**Phase 2: Synthesis (reconstruction)**
- Present the fragments to the LLM with the original question
- Let the LLM reconstruct the answer from the fragments
- This is where the LLM's world knowledge fills gaps, just as human schemas do

This reframes the retrieval problem. Instead of asking "which episode answers this question?" (hard, requires high similarity), ask "which episodes contain information relevant to this question?" (easier, requires lower similarity). The LLM handles the reconstruction.

**Practical consideration:** This already partially happens — recall results are injected into the agent's context, and the LLM synthesizes a response. But the current system *filters aggressively* before handing to the LLM (relevance_threshold = 0.35–0.7). Reconstruction theory says: **widen the funnel, let more fragments through, trust the LLM to filter noise.** The cost is more tokens in context; the benefit is catching memories that are fragmentarily relevant.

---

## 6. Interference Theory and Distinctiveness

### 6.1 When Similar Memories Compete

As ProbOS accumulates episodes, many will be similar. Multiple discussions about thresholds, multiple pool health reports, multiple routine duty cycles. How does the brain handle retrieval when many similar memories exist?

**Proactive interference:** Old memories interfere with retrieval of new ones. When a threshold was changed from 0.7 to 0.5, asking "What is the threshold?" might retrieve the old value because it's been in memory longer and has more associations.

**Retroactive interference:** New memories interfere with retrieval of old ones. After discussing many different thresholds, no single threshold memory is distinctly retrievable — they blur together.

**The distinctiveness solution (Hunt, 2006):** Memories that are distinctive — different from their neighbors in some salient way — resist interference. The "Von Restorff effect" (isolation effect): a single unusual item in a list is better remembered than the surrounding items.

### 6.2 Practical Applications

**For storage:** Make important memories distinctive at encoding time. If a threshold change is significant, the episode should contain markers of significance — trust delta, alert condition, Captain involvement, explicit "this is important" annotation. These markers create distinctiveness that resists interference from routine episodes.

**For retrieval:** When many similar episodes compete, use **temporal recency** and **distinctiveness markers** to break ties. The current recency weight (0.20) already helps with proactive interference. Distinctiveness is not currently scored.

**For maintenance:** Dream consolidation should identify interfering memories and either:
- **Merge** them (combine multiple "threshold" episodes into one consolidated fact)
- **Differentiate** them (annotate each with distinct temporal context: "In the March discussion, the threshold was 0.7; in the April discussion, it was changed to 0.5")

This connects to AD-551 (dream Step 7g consolidation) and AD-538 (lifecycle: merge, dedup). The interference problem provides cognitive science justification for aggressive consolidation.

---

## 7. Elaborative Encoding and Desirable Difficulties

### 7.1 Bjork's Desirable Difficulties (Bjork, 1994)

Robert Bjork's counterintuitive finding: **making encoding harder improves retrieval.** Specifically:
- **Spacing** (distributing study over time) > massing (cramming)
- **Interleaving** (mixing different topics) > blocking (studying one topic at a time)
- **Generation** (producing the answer yourself) > reading (passively receiving it)
- **Testing** (attempting retrieval) > re-study (re-reading)

The common thread: conditions that make initial encoding feel more difficult create more durable, more retrievable memory traces.

### 7.2 Elaborative Encoding (Craik & Tulving, 1975)

The deeper and more elaborately you process information during encoding, the more retrievable it becomes. Three levels:
- **Structural:** What does it look like? (shallow — poor retrieval)
- **Phonemic:** What does it sound like? (medium)
- **Semantic:** What does it mean? How does it relate to things I already know? (deep — excellent retrieval)

The best encoding combines semantic processing with **self-referential processing** (Rogers, Kuiper, & Kirker, 1977): "How does this relate to me?" Memories encoded with self-reference are the most retrievable of all.

### 7.3 Implications for Episode Encoding

Current episode encoding stores the raw facts: user input, DAG summary, outcomes, reflection. This is a relatively shallow encoding — the text is stored, but its connections, implications, and self-referential meaning are not explicitly represented.

**Enriched encoding proposal:**
At episode storage time, generate additional metadata that creates richer, more retrievable traces:

1. **Entity extraction:** Who, what, when, where (already partially done via AnchorFrame)
2. **Question generation:** What questions could this episode answer? Store these as alternate embeddings or in the FTS5 index. If "The threshold was set to 0.7" also stores "What was the threshold?" and "What value was the threshold set to?", the question-answer gap disappears at storage time.
3. **Relational tagging:** How does this episode relate to other recent episodes? (before/after, cause/effect, contradiction, elaboration). Creates associative links for spreading activation.
4. **Significance annotation:** Why would someone want to recall this later? (decision, configuration change, interpersonal event, learning moment). Creates distinctiveness.
5. **Abstract summary:** A one-sentence distillation of the episode's key fact. This is the "semantic encoding" that produces the deepest, most retrievable traces.

The cost is computational — generating this metadata requires LLM inference at storage time (or heuristic extraction). The benefit is dramatically improved retrievability, because the stored episode has been processed at multiple levels and contains retrieval cues that match diverse query types.

---

## 8. Synthesis: A Biologically-Informed Recall Architecture

### 8.1 What the Brain Does That ProbOS Doesn't (Yet)

| Brain Mechanism | Current ProbOS | Gap | Priority |
|----------------|---------------|-----|----------|
| **Spreading activation** (multi-hop concept traversal) | Single-hop embedding search | No concept-to-concept expansion | **HIGH** — directly addresses the Q→A gap |
| **Encoding specificity** (context-matching) | AnchorFrame exists, weighted at 10% | Context used as tiebreaker, not filter | **HIGH** — anchors should be a primary pathway |
| **Pre-retrieval question decomposition** | None — raw query goes to ChromaDB | Questions aren't transformed before search | **HIGH** — cheap, directly addresses the gap |
| **Reconstructive recall** (fragment synthesis) | Aggressive filtering, single-best-match | Filters out potentially useful fragments | **MEDIUM** — needs LLM at recall time |
| **Temporal context model** (recent-conversation bias) | Recency weight on episode age | No conversational context drift vector | **MEDIUM** — would help conversational recall |
| **Dual-process** (familiarity filter + recollection re-rank) | Weighted sum conflates both | No fast-filter/slow-rerank separation | **MEDIUM** — architectural change |
| **Elaborative encoding** (enriched storage) | Raw episode text + AnchorFrame | No question generation, no relation tagging | **HIGH** — prevents the gap at storage time |
| **Distinctiveness scoring** | Not implemented | Important memories not marked at encoding | **LOW** — partially handled by trust deltas |
| **Emotional valence** | Not implemented | Conflict/surprise episodes not prioritized | **LOW** — nice-to-have |
| **Mismatch suppression** | Not implemented | Contradictory context not penalized | **LOW** — edge case optimization |

### 8.2 Recommended Architecture: Three-Phase Recall

**Phase 1: Query Enrichment (Pre-Retrieval, 0 LLM tokens)**
- Extract entities from the query via regex/NLP
- Classify question type (what/who/when/where/why/how)
- Extract presuppositions and expected answer type
- Expand query with synonyms and related terms from a simple thesaurus
- Construct an "expected answer template" for embedding

**Phase 2: Multi-Channel Retrieval (Parallel Candidate Gathering)**
- **Channel A — Semantic:** Embed the enriched query → ChromaDB top-K (familiarity filter)
- **Channel B — Keyword:** FTS5 search with extracted entities (already implemented)
- **Channel C — Entity Association:** If an entity index exists, find episodes associated with query entities (spreading activation)
- **Channel D — Context Match:** If AnchorFrame context available (department, recent channel, conversation partner), filter by anchor dimensions
- **Channel E — Temporal:** Recent episodes from the same agent's conversation (temporal context model)
- Merge all candidates, deduplicate

**Phase 3: Salience Re-Ranking (Composite Scoring)**
- Score each candidate with the existing composite formula (semantic + keyword + trust + Hebbian + recency + anchor)
- **Boost** candidates found by multiple channels (convergence bonus — spreading activation)
- **Penalize** candidates whose anchor context contradicts the query context (mismatch suppression)
- Apply activation-level weighting from ActivationTracker (retrieval fluency)
- Budget and return

### 8.3 Highest-ROI Change: Query-Time Question-to-Statement Transformation

If I had to recommend a single change, it would be this:

**Before sending a query to ChromaDB, transform questions into expected answer patterns.**

"What was the threshold?" → "the threshold was [VALUE]" / "threshold setting value"
"Who fixed the bug?" → "[AGENT] fixed the bug" / "bug fix resolved by"
"When did we discuss pools?" → "discussed pools on [DATE]" / "pool discussion meeting"

This is trivially implementable (a few regex patterns for WH-question types, plus keyword extraction), requires zero LLM tokens at retrieval time, and directly addresses the core problem: the embedding of "the threshold was 0.7" is much closer to "the threshold was [VALUE]" than to "What was the threshold?"

This is what the brain does in step 3 of question processing (Section 3.1 above): construct an expected answer template before searching memory. The brain has been doing this trick for 200 million years. We should steal it.

### 8.4 Second-Highest ROI: Elaborative Encoding with Question Seeding

At episode storage time, generate 2-3 questions that this episode could answer. Store these as additional text in the FTS5 index (not in the embedding — that would change the semantic space).

When recall happens, FTS5 keyword search on the questions will bridge the Q→A gap for exact matches, and the expanded keyword terms will help ChromaDB's semantic search on near-matches.

Cost: A few regex patterns or a lightweight LLM call at storage time (amortized across all future retrievals).
Benefit: Permanently bridges the Q→A gap for that episode.

---

## 9. References and Intellectual Lineage

- Anderson, J. R. (1983, 2007). *The Architecture of Cognition* / *How Can the Human Mind Occur in the Physical Universe?* — ACT-R theory, base-level activation equation (already implemented in ActivationTracker)
- Bartlett, F. C. (1932). *Remembering* — Reconstructive memory, schema theory
- Bjork, R. A. (1994). "Memory and metamemory considerations in the training of human beings" — Desirable difficulties
- Collins, A. M., & Loftus, E. F. (1975). "A spreading-activation theory of semantic processing" — Spreading activation
- Craik, F. I. M., & Lockhart, R. S. (1972). "Levels of processing: A framework for memory research" — Depth of processing
- Craik, F. I. M., & Tulving, E. (1975). "Depth of processing and the retention of words in episodic memory" — Elaborative encoding
- Graesser, A. C., & Black, J. B. (Eds.). (1985). *The Psychology of Questions* — Question answering schemas
- Howard, M. W., & Kahana, M. J. (2002). "A distributed representation of temporal context" — Temporal context model
- Hunt, R. R. (2006). "The concept of distinctiveness in memory research" — Distinctiveness and interference
- Johnson, M. K., & Raye, C. L. (1981). "Reality monitoring" — Source monitoring framework (already implemented in anchor_quality.py)
- Johnson-Laird, P. N. (1983). *Mental Models* — Mental model theory of reasoning
- LaBar, K. S., & Cabeza, R. (2006). "Cognitive neuroscience of emotional memory" — Emotion-memory interaction
- Loftus, E. F., & Palmer, J. C. (1974). "Reconstruction of automobile destruction" — Reconstructive memory, misinformation effect
- McClelland, J. L., McNaughton, B. L., & O'Reilly, R. C. (1995). "Why there are complementary learning systems in the hippocampus and neocortex" — Complementary learning systems
- McGaugh, J. L. (2004). "The amygdala modulates the consolidation of memories of emotionally arousing experiences" — Emotional memory enhancement
- Morris, C. D., Bransford, J. D., & Franks, J. J. (1977). "Levels of processing versus transfer appropriate processing" — Transfer-appropriate processing
- Ratcliff, R. (1978). "A theory of memory retrieval" — Drift-diffusion model
- Rogers, T. B., Kuiper, N. A., & Kirker, W. S. (1977). "Self-reference and the encoding of personal information" — Self-referential processing
- Tulving, E., & Thomson, D. M. (1973). "Encoding specificity and retrieval processes in episodic memory" — Encoding specificity principle
- Yonelinas, A. P. (2002). "The nature of recollection and familiarity: A review of 30 years of research" — Dual-process theory

---

## 10. Connection to Existing ProbOS Architecture

This research connects to and validates several existing design decisions:

| ProbOS Feature | Cognitive Science Validation |
|----------------|------------------------------|
| AnchorFrame (AD-567a) | Encoding specificity + source monitoring (Johnson & Raye) |
| Johnson-weighted anchor confidence (AD-567c) | Reality monitoring framework |
| ACT-R ActivationTracker (AD-567d) | Base-level activation = retrieval fluency |
| FTS5 keyword sidecar (AD-567b) | Lexical access pathway (dual-route retrieval) |
| Composite scoring formula | Multi-cue retrieval (but needs mismatch suppression, convergence bonus) |
| Dream consolidation (dreaming.py) | Sleep-dependent memory reorganization (McClelland et al., 1995) |
| Hebbian router | Hebbian learning = association strengthening |
| Episodic → procedural pipeline (Cognitive JIT) | Declarative → procedural memory transition (Anderson's ACT-R) |
| Episode dedup/merge (AD-538, AD-550) | Interference reduction via consolidation |
| Crew notebook quality pipeline (AD-550–555) | Elaborative encoding, distinctiveness |

The architecture is already more brain-like than most AI memory systems. The research identifies specific gaps (query transformation, spreading activation, elaborative encoding at storage time) that can be addressed incrementally.
