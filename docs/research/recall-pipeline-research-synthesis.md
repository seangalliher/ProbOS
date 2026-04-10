# Recall Pipeline Research Synthesis: Q→A Retrieval Gap

*Sean Galliher, 2026-04-09*
*Triggered by: BF-134 post-mortem — threshold + FTS floor fixes had no effect on qualification probe scores*

## Executive Summary

ProbOS's episodic recall pipeline fails on question→answer retrieval because `all-MiniLM-L6-v2` is a sentence-similarity model, not a QA model. Questions and factual statements occupy different embedding subspaces — cosine similarity between "What was the threshold?" and "The threshold was set to 0.7" is 0.10–0.35, regardless of threshold tuning.

Three parallel research tracks (RAG engineering, cognitive science, ProbOS architecture analysis) converge on a **layered fix with 4 tiers**, ordered by impact/effort ratio. The first two tiers require zero LLM calls at query time and should resolve the qualification probe failures.

---

## Root Cause Analysis

### Why BF-134 Failed

BF-134 lowered `agent_recall_threshold` to 0.15 and added `fts_keyword_floor` of 0.2. This was necessary (removed hardcoded values, added config) but **insufficient** because:

1. MiniLM Q→A cosine similarity is often below 0.15 for valid pairs
2. FTS5 keyword matching helps but only contributes 10% of composite score
3. The BF-029 "Ward Room {callsign}" prefix actively **pollutes** query embeddings, shifting them away from question semantics

### The 5 Contributing Factors (Architecture Exploration)

| # | Factor | File:Line | Impact |
|---|--------|-----------|--------|
| 1 | **Wrong model** — all-MiniLM-L6-v2 is STS-trained, not QA-trained | `embeddings.py:93` | Primary cause |
| 2 | **No query reformulation** — raw question text goes to ChromaDB | `cognitive_agent.py:2471` | No mitigation of #1 |
| 3 | **BF-029 prefix pollution** — "Ward Room {callsign}" prepended to every query | `cognitive_agent.py:2480` | Actively harmful |
| 4 | **Incomplete document embedding** — only `user_input` embedded, not `reflection`/`outcomes` | `episodic.py:626` | Reduces recall surface |
| 5 | **Low keyword weight** — 10% in composite score vs 35% semantic | `episodic.py:1379` | Keyword can't compensate |

---

## Research Findings

### Track 1: RAG Engineering

**Key finding: `multi-qa-MiniLM-L6-cos-v1` is a drop-in replacement.**

Same architecture (MiniLM-L6), same dimensions (384), same ONNX runtime, same inference speed. Trained on 215M question-answer pairs (MS MARCO, NQ, StackExchange, Yahoo Answers). Expected to shift Q→A cosine similarity from 0.10–0.35 to **0.50–0.75**.

| Model | Dims | Params | QA-Optimized | ONNX | Notes |
|-------|------|--------|-------------|------|-------|
| all-MiniLM-L6-v2 (current) | 384 | 22M | **NO** | Yes | STS/NLI trained. Poor Q→A. |
| **multi-qa-MiniLM-L6-cos-v1** | 384 | 22M | **YES** | Yes | Same arch, 215M QA pairs. Best ROI. |
| multi-qa-mpnet-base-v1 | 768 | 109M | YES | Yes | Higher quality, 5x larger |
| bge-small-en-v1.5 | 384 | 33M | Partial | Yes | Needs "Represent this sentence..." prefix |
| e5-small-v2 | 384 | 33M | Partial | Yes | Needs "query:"/"passage:" prefixes |
| gte-small | 384 | 33M | Yes | Yes | No prefixes needed |

**HyDE (Hypothetical Document Embeddings):** Generates a hypothetical answer via LLM, embeds that instead. Effective but costs one LLM call per query. **Template-based pseudo-HyDE** captures ~50-60% of the benefit at zero cost: detect question patterns, reformulate to declarative form.

**Hybrid retrieval research:** RRF (Reciprocal Rank Fusion) outperforms fixed-weight linear combination because it's rank-based, not score-based — immune to scale mismatch between BM25 and cosine. Current 0.10 keyword weight is too low; research suggests 0.20–0.25 for QA tasks.

### Track 2: Cognitive Science

**The brain doesn't do cosine similarity.** It uses multiple overlapping retrieval systems simultaneously:

1. **Encoding Specificity (Tulving 1973):** Retrieval depends on overlap between encoding and retrieval *context*, not content. AnchorFrame already implements this but is weighted at only 10%.

2. **Spreading Activation (Collins & Loftus 1975):** The brain bridges Q→A gaps via multi-hop concept traversal. "What was the threshold?" → "threshold" activates → "pool health" activates → "0.7" activates → the specific memory surfaces. **One-hop embedding search cannot do this. Two-pass retrieval can.**

3. **Pre-retrieval Question Decomposition (Graesser & Black 1985):** Before searching memory, the brain constructs an **expected answer template**. "What was the threshold?" → "the threshold was [VALUE]". This template, not the question, is what drives memory search. **The brain has been doing pseudo-HyDE for 200 million years.**

4. **Dual-Process Theory (Yonelinas 2002):** Familiarity (fast, cheap — embedding similarity) and Recollection (slow, precise — contextual reconstruction) are separate processes. Don't ask embeddings to do recollection's job.

5. **Reconstructive Memory (Bartlett 1932):** The brain doesn't find one perfect memory — it retrieves fragments and reconstructs. Widen the funnel, let more fragments through, trust the LLM to synthesize.

6. **Elaborative Encoding (Craik & Tulving 1975):** Richer encoding → better retrieval. Storing questions an episode could answer at write time permanently bridges the Q→A gap for that episode.

**Brain signals ProbOS doesn't use yet:**
- Emotional valence (trust deltas, alert conditions → higher retrievability)
- Encoding depth (episodes discussed/debated/consolidated → easier recall)
- Mismatch suppression (contradictory context → penalty, not just low score)

### Track 3: ProbOS Architecture Analysis

**14 intervention points identified.** Full pipeline:

```
Agent.act() → _recall_relevant_memories()
  → Query construction: "Ward Room {callsign} {captain_text}"[:200]
  → _try_anchor_recall() (structured metadata filters, regex-parsed)
  → classify_retrieval_strategy(intent_type, count, confab_rate)
  → recall_for_agent_scored() / recall_weighted()
    → ChromaDB.query(query_texts=[query], n_results=k*3)
    → keyword_search(query, k) via FTS5
    → score_recall() composite: 0.35*sem + 0.10*kw + 0.15*trust + 0.10*hebb + 0.20*rec + 0.10*anchor
    → Budget enforcement, threshold filtering
  → Fallback chain: weighted → basic → recent
  → Anchor merge (prepend, dedup)
  → Oracle service (ORACLE tier only)
  → Format episodes → inject into observation["recent_memories"]
```

**Critical finding:** Only `user_input` is embedded in ChromaDB (line 626). `reflection`, `outcomes`, `dag_summary` are NOT embedded. FTS5 indexes `user_input + reflection` — it has a richer search surface than the semantic channel.

---

## Recommended Fix: 4-Tier Approach

### Tier 1: Swap Embedding Model (Highest Impact, Lowest Effort)

**What:** Replace `all-MiniLM-L6-v2` with `multi-qa-MiniLM-L6-cos-v1` in `embeddings.py`.

**Why:** Same architecture, dimensions, ONNX runtime. Trained on 215M QA pairs. Expected cosine similarity improvement: 0.10–0.35 → 0.50–0.75 for Q→A queries.

**Cost:** One-time collection reindex at boot (migration pattern already exists from BF-103/BF-134).

**Files:**
- `src/probos/knowledge/embeddings.py` — change `DefaultEmbeddingFunction()` to `SentenceTransformerEmbeddingFunction("multi-qa-MiniLM-L6-cos-v1")` or equivalent ONNX wrapper
- `src/probos/cognitive/episodic.py` — migration: detect model mismatch, re-embed all episodes
- `src/probos/config.py` — `embedding_model: str = "multi-qa-MiniLM-L6-cos-v1"`

### Tier 2: Query Reformulation (High Impact, Low Effort)

**What:** Before sending to ChromaDB, transform questions into declarative expected-answer templates. Zero LLM cost.

**Why:** Cognitive science's "expected answer template" (Graesser & Black 1985). The brain does this before every memory search. Template-based pseudo-HyDE captures ~50-60% of full HyDE benefit at zero token cost.

**Implementation (~50 lines):**
```
"What is X?" → "X is"
"What was X?" → "X was"  
"How does X work?" → "X works by"
"Who did X?" → "[AGENT] did X"
"When did X?" → "X happened on"
"Why did X?" → "X because"
"How many X?" → "the number of X is" / "there are N X"
```

Embed BOTH the original query AND the reformulated template. Use the max similarity across both for the semantic score.

**Also:** Remove the BF-029 "Ward Room {callsign}" prefix from queries. It pollutes the embedding vector and was a workaround for a problem that multi-qa-MiniLM solves at the model level.

**Files:**
- `src/probos/cognitive/episodic.py` or new `src/probos/cognitive/query_reformulation.py`
- `src/probos/cognitive/cognitive_agent.py:2471-2484` — remove prefix, add reformulation call

### Tier 3: Scoring Rebalance (Medium Impact, Low Effort)

**What:** Adjust composite scoring weights and add convergence bonus.

**Changes:**
1. Increase keyword weight: 0.10 → 0.20 (QA tasks benefit from exact term matching)
2. Add convergence bonus: episodes found by BOTH semantic AND keyword channels get +0.10 (spreading activation — multi-pathway evidence accumulation)
3. Consider: anchor weight 0.10 → 0.15 (encoding specificity says context is a primary cue, not a tiebreaker)

**Revised formula:**
```
composite = 0.35 * semantic
          + 0.20 * keyword        (was 0.10)
          + 0.10 * trust          (was 0.15)
          + 0.05 * hebbian        (was 0.10)
          + 0.15 * recency        (was 0.20)
          + 0.15 * anchor         (was 0.10)
          + convergence_bonus     (new: +0.10 if found by ≥2 channels)
```

**Rationale:** With multi-qa-MiniLM, the semantic signal becomes more reliable, so keyword can share some weight. Trust and Hebbian are useful but shouldn't dominate over content relevance. Anchor deserves more weight per encoding specificity research.

**Files:**
- `src/probos/cognitive/episodic.py:1360-1406` — `score_recall()` weights
- `src/probos/config.py` — make weights configurable

### Tier 4: Enriched Embedding Document (Medium Impact, Medium Effort)

**What:** Embed `user_input + reflection` instead of just `user_input`. Optionally add question seeds at storage time.

**Why:** Currently ChromaDB only embeds `user_input` (line 626), while FTS5 indexes `user_input + reflection` (line 633). The reflection often contains the analytical insight that a question is looking for.

**Question seeding (elaborative encoding):** At `store()` time, generate 2-3 questions the episode could answer using simple heuristics. Append to FTS5 index (not to embedding document — keeps embedding clean). Bridges Q→A gap at write time, amortized across all future retrievals.

**Files:**
- `src/probos/cognitive/episodic.py:624-628` — change `documents=[episode.user_input]` to include reflection
- `src/probos/cognitive/episodic.py:631-639` — add question seeds to FTS5 content

---

## What NOT to Do

1. **Don't add LLM calls to the retrieval hot path.** Full HyDE costs one LLM call per recall. ProbOS agents recall on every `act()` cycle. This would dramatically increase latency and cost. Template-based reformulation captures most of the benefit at zero cost.

2. **Don't switch to ColBERT/SPLADE as primary index.** They require their own index format (not ChromaDB-compatible), add 200MB+ model weight, and increase complexity. Consider as a future reranker on top-50 candidates, not a primary replacement.

3. **Don't fine-tune a custom model.** GPL/InPars (domain-specific fine-tuning) produces the best results but requires significant compute, maintenance burden, and creates a non-standard model that's hard to update. The off-the-shelf multi-qa-MiniLM should be sufficient.

4. **Don't implement full spreading activation.** An entity-episode association graph would be powerful but is a significant new subsystem. The two-pass retrieval (retrieve → extract expansion terms → re-retrieve) captures most of the benefit without new infrastructure.

---

## Expected Impact on Qualification Probes

| Probe | Current Score | After Tier 1+2 | Rationale |
|-------|---------------|-----------------|-----------|
| seeded_recall_probe | 0.000–0.149 | 0.500–0.800 | Q→A cosine jumps to 0.50+ with multi-qa model; template reformulation eliminates residual gap |
| temporal_reasoning_probe | 0.000–0.012 | 0.200–0.500 | Improved semantic retrieval + better keyword weight for temporal terms |
| knowledge_update_probe | 0.000–0.500 | 0.400–0.800 | Multi-qa handles fact updates; convergence bonus helps when multiple episodes compete |
| retrieval_accuracy_benchmark | 0.300–0.550 | 0.400–0.650 | Already passes (statement→statement); slight improvement from better keyword weight |

---

## Cognitive Science Validation of Existing Architecture

The research validates that ProbOS's memory architecture is already more brain-informed than most AI systems:

| ProbOS Feature | Cognitive Science Validation |
|----------------|------------------------------|
| AnchorFrame (AD-567a) | Encoding specificity (Tulving) + source monitoring (Johnson & Raye) |
| ActivationTracker (AD-567d) | ACT-R base-level activation = retrieval fluency (Anderson) |
| FTS5 keyword sidecar | Dual-route retrieval (lexical access pathway) |
| Dream consolidation | Complementary learning systems (McClelland et al., 1995) |
| Hebbian router | Hebbian association strengthening |
| Cognitive JIT pipeline | Declarative → procedural memory transition (Anderson's ACT-R) |
| Episode dedup/merge (AD-538/550) | Interference reduction via consolidation |
| Composite scoring | Multi-cue retrieval (but needs mismatch suppression, convergence bonus) |

The gaps are incremental improvements, not architectural overhauls.

---

## Implementation Plan

**AD-584: Recall Pipeline Q→A Fix**
- **AD-584a:** Embedding model swap (Tier 1) — migration + model change
- **AD-584b:** Query reformulation (Tier 2) — template-based, remove BF-029 prefix
- **AD-584c:** Scoring rebalance (Tier 3) — weight adjustment + convergence bonus
- **AD-584d:** Enriched embedding document (Tier 4) — reflection in embedding + question seeds

Tiers 1+2 should be a single build prompt (they're interdependent — the model swap changes thresholds, reformulation depends on the new model's characteristics). Tiers 3+4 can be separate follow-up ADs.

---

## References

### RAG Engineering
- Gao, Ma, Chen (2022). "Precise Zero-Shot Dense Retrieval without Relevance Labels" (HyDE). arXiv:2212.10496
- Karpukhin et al. (2020). "Dense Passage Retrieval for Open-Domain QA" (DPR). arXiv:2004.04906
- Khattab & Zaharia (2020). "ColBERT: Efficient and Effective Passage Search" arXiv:2004.12832
- Formal et al. (2021). "SPLADE: Sparse Lexical and Expansion Model" arXiv:2107.05720
- Reimers & Gurevych (2019). "Sentence-BERT" arXiv:1908.10084
- Cormack et al. (2009). "Reciprocal Rank Fusion" SIGIR 2009
- Wang et al. (2022). "GPL: Generative Pseudo Labeling" arXiv:2112.07577

### Cognitive Science
- Tulving & Thomson (1973). Encoding specificity principle
- Collins & Loftus (1975). Spreading activation theory
- Graesser & Black (1985). Psychology of Questions — expected answer templates
- Bartlett (1932). Reconstructive memory
- Yonelinas (2002). Dual-process theory (familiarity vs. recollection)
- Craik & Tulving (1975). Elaborative encoding / levels of processing
- Bjork (1994). Desirable difficulties
- Howard & Kahana (2002). Temporal context model
- Anderson (1983, 2007). ACT-R theory
- McClelland et al. (1995). Complementary learning systems

### Full Cognitive Science Research
See: `docs/research/memory-retrieval-research.md`
