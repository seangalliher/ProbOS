# Confabulation Scaling Research: Episode Accumulation and Recall Noise

*Sean Galliher, 2026-04-10*
*Triggered by: Observed confabulation worsens as agents accumulate episodes — Atlas fabricated "240+ false alerts/hour" (pattern cooldowns cap at 2-6/hour), Meridian fabricated stasis duration despite authoritative orientation text*

## Executive Summary

As ProbOS agents accumulate episodic memories over their lifetime, confabulation frequency and severity increases. The root cause is a **recall pipeline noise amplification loop**: more episodes means more marginal candidates enter the context window, providing the LLM with plausible-sounding but irrelevant fragments that it weaves into fabricated specifics.

Six structural weaknesses in the recall pipeline combine to create this effect. Each is individually minor but together they produce a scaling failure: the pipeline works well with 50-200 episodes but degrades noticeably at 1,000+ and severely at 3,000+.

This document proposes **4 ADs (AD-590 through AD-593)** to address the pipeline, ordered by impact/effort ratio.

---

## Observed Confabulation Instances

| Agent | Confabulation | Truth | Source |
|-------|--------------|-------|--------|
| Atlas | "240+ false alerts/hour" from emergence detector | Pattern cooldowns cap at 2-6/hour (`emergent_detector.py:126,177`) | Ward Room proposal |
| Meridian | Fabricated offline duration (claimed "2d 22h", then "3 minutes" when corrected) | Actual: 6m 19s (from `session_last.json`) | Ward Room post after warm boot |

Both instances share the same pattern: agent has authoritative data available (orientation text, system constants) but generates plausible-sounding numbers from accumulated episode fragments instead.

---

## Root Cause Analysis: The Noise Amplification Loop

```
More episodes → larger candidate pool
    → more marginal hits pass low similarity floor (0.15)
    → all candidates fit in generous budget (4000 chars)
    → LLM receives ~5 relevant + ~20 noise fragments
    → noise fragments provide plausible-sounding material
    → LLM confabulates specifics from noise
    → confabulated response creates new episode
    → episode count increases
    → [loop repeats]
```

### The 6 Contributing Factors

| # | Factor | Location | Scaling Impact |
|---|--------|----------|----------------|
| 1 | **Similarity floor too low** | `episodic.py:467` — `agent_recall_threshold = 0.15` | Linear: every new episode with sim > 0.15 enters candidate pool |
| 2 | **No composite score floor** | `episodic.py:1644-1654` — budget enforcement has no score cutoff | All scored candidates pass; sorting is correct but tail isn't cut |
| 3 | **Budget overly generous** | `config.py:306-311` — enhanced tier: k=5, budget=4000 chars | 4000 chars fits ~33 episodes at 120 chars avg; over-fetch produces ~25 candidates that ALL fit |
| 4 | **Recency decay too gentle** | `episodic.py:1622-1623` — `exp(-age_hours / 168.0)`, 7-day half-life | At 3 days old, recency weight = 0.65; weighted contribution only 0.0977 — not enough to suppress |
| 5 | **Pruning too conservative** | `dreaming.py:963` — `max_prune_fraction=0.10` per dream cycle | Net -19 episodes per dream cycle vs. accumulation rate of ~50-100/cycle. Pool grows faster than pruning clears it |
| 6 | **No confabulation guard in memory framing** | `cognitive_agent.py:1978` — "Do NOT confuse with training knowledge" | Warns about training/experience confusion but not about fabricating specifics from fragments |

### Numerical Analysis

**Scoring margins (enhanced tier, typical):**

A marginal episode (semantic similarity 0.18, 3 days old, no keyword match):
```
composite = 0.35*0.18 + 0.20*0.0 + 0.10*0.5 + 0.05*0.5 + 0.15*0.65 + 0.15*0.40
         = 0.063 + 0.0 + 0.05 + 0.025 + 0.0977 + 0.06
         = 0.296
```

A relevant episode (semantic similarity 0.40, 1 hour old, 2 keyword hits, convergence bonus):
```
composite = 0.35*0.40 + 0.20*0.67 + 0.10*0.5 + 0.05*0.5 + 0.15*0.99 + 0.15*0.60 + 0.10
         = 0.14 + 0.134 + 0.05 + 0.025 + 0.149 + 0.09 + 0.10
         = 0.688
```

**Sorting works correctly** — 0.69 ranks above 0.30. But since there's no floor and the budget fits all candidates, a typical recall returns:
- Top 5 episodes: composite 0.50-0.69 (relevant)
- Episodes 6-25: composite 0.20-0.40 (marginal noise)
- All 25 fit in 4000-char budget (25 × 120 = 3000 chars)

The bottom 20 episodes are noise that the LLM treats as source material.

### Episode Lifecycle Data (from `C:\Users\seang\AppData\Local\ProbOS\data\`)

| Metric | Value | Source |
|--------|-------|--------|
| Total episodes created | ~49,000 | eviction_audit.db |
| Pruned (activation_decay) | 38,777 | eviction_audit.db |
| Pruned (test cleanup) | 6,566 | eviction_audit.db |
| Currently active (FTS) | 3,905 | episode_fts.db |
| ChromaDB embeddings on disk | 0 | chroma.sqlite3 (in-memory during runtime) |
| Activation access log entries | 982,632 | activation_tracker.db (127MB) |
| Net pruned per dream cycle | ~19 | Shutdown log observation |
| Estimated new episodes per cycle | ~50-100 | Based on crew activity |

**Key insight:** The pool is growing faster than pruning can clear it. Dream Step 12 prunes max 10% of episodes older than 24h, and the activation threshold (-2.0) is too lenient.

### Relationship to Existing Research

The `recall-pipeline-research-synthesis.md` (2026-04-09) focused on the **Q→A retrieval gap** — the wrong embedding model (`all-MiniLM-L6-v2` vs `multi-qa-MiniLM-L6-cos-v1`). That's a complementary problem:

- **Q→A gap** (existing research): correct answers score LOW because similarity model is wrong → relevant episodes don't get retrieved
- **Confabulation scaling** (this research): irrelevant episodes score just HIGH ENOUGH to fill the budget → noise episodes DO get retrieved and cause confabulation

The Q→A model swap (when implemented) will raise relevant episode scores but won't fix the noise floor. Both problems need separate fixes.

### Relationship to AD-568b (Adaptive Budget)

`source_governance.py:110-199` already implements adaptive budget scaling. However:
- Low anchor confidence (< 0.2) only contracts to 0.6x — still 2400 chars, fits ~20 episodes
- Low recall quality (mean composite < 0.3) only contracts to 0.8x — still 3200 chars
- The signals are not aggressive enough to prevent noise accumulation
- No signal for "many candidates below a quality threshold" — the adaptation doesn't count how many are marginal

---

## Proposed ADs

### AD-590: Composite Score Floor (Recall Quality Gate)

**Problem:** No minimum composite score to enter agent context. All candidates that pass anchor gating and fit in budget are included.

**Fix:** Add a configurable `composite_score_floor` (default 0.35) to `recall_weighted()`. Episodes scoring below this floor are excluded from the budgeted results regardless of remaining budget space.

**Location:** `episodic.py:1644` — insert floor filter before budget enforcement loop.

**Config:** `config.py` — add `composite_score_floor: float = 0.35` to SystemConfig.

**Impact:** Immediately removes the bottom ~60% of marginal candidates. With a 0.35 floor, the marginal episode at 0.296 would be excluded. Only episodes with meaningful relevance enter the context.

**Risk:** Low. Floor is configurable. Worst case: agents recall slightly fewer memories in early lifecycle when episode count is low (but this is when confabulation risk is also low).

**Tests:** ~10-15 tests.

**Depends on:** Nothing. Can ship independently.

---

### AD-591: Aggressive Relevance-Aware Budget Enforcement

**Problem:** Budget enforcement only counts characters. It doesn't consider whether adding another episode improves or degrades context quality.

**Fix:** Replace simple character-count budget enforcement with quality-aware enforcement:
1. After sorting by composite score, compute the **score gap** between consecutive episodes
2. If adding the next episode would drop the mean composite score below a threshold (e.g., 0.40), stop — even if budget remains
3. Add a **max episodes** cap per recall (e.g., `k * 2` = 10 for enhanced tier) to prevent 25+ episodes regardless of budget

**Location:** `episodic.py:1646-1654` — replace budget loop.

**Config:** `config.py` — add `max_recall_episodes: int = 0` (0 = use k*2 default), `recall_quality_floor: float = 0.40`.

**Impact:** Even without AD-590's hard floor, this prevents the "long tail of noise" problem. Budget becomes quality-limited, not just size-limited.

**Risk:** Medium. Needs careful testing with low-episode agents to ensure they still recall useful memories.

**Tests:** ~12-18 tests.

**Depends on:** Nothing. Complementary to AD-590 but independent.

---

### AD-592: Confabulation Guard Instructions

**Problem:** Memory section framing (`cognitive_agent.py:1976-1982`) tells agents not to confuse ship memory with training knowledge, but says nothing about fabricating specific numbers, durations, or statistics from fragments.

**Fix:** Add explicit confabulation guard instructions to `_format_memory_section()`:
1. Add instruction: "Do NOT fabricate specific numbers, durations, measurements, or statistics from these fragments. If you cannot find an exact value in your memories, say you don't have that data."
2. Add instruction: "When orientation data conflicts with memories, orientation data is authoritative."
3. For AD-568c source-framed memories, calibrate instruction strength by source authority level.

**Location:** `cognitive_agent.py:1976-1982` — update instruction block in `_format_memory_section()`.

**Impact:** Direct mitigation of the confabulation behavior. LLMs are generally responsive to explicit instructions about what NOT to fabricate. This is the cheapest fix with potentially the highest immediate impact.

**Risk:** Very low. Instruction-only change.

**Tests:** ~5-8 tests (verify instruction presence in formatted output, verify source-authority-calibrated variants).

**Depends on:** Nothing. Independent.

---

### AD-593: Pruning Acceleration and Similarity Floor Tightening

**Problem:** (A) Pruning removes max 10% per dream cycle, insufficient to keep pace with episode creation. (B) Similarity floor of 0.15 admits nearly any episode as a candidate.

**Fix (two parts):**

**Part A — Pruning acceleration:**
1. Raise `max_prune_fraction` from 0.10 to 0.20 for episodes older than 48h
2. Add a secondary pruning tier: episodes older than 7 days with activation score below 0.0 (not just -2.0) are candidates for aggressive pruning (up to 30%)
3. Add episode count pressure: when active episodes exceed a threshold (e.g., 5000), increase pruning aggressiveness proportionally

**Part B — Similarity floor tightening:**
1. Raise `agent_recall_threshold` from 0.15 to 0.25 — still generous for the current STS model but eliminates the truly random matches
2. Make this configurable and monitor impact on qualification probe scores

**Location:**
- Part A: `dreaming.py:955-969` — Step 12 pruning logic. `config.py` — add `aggressive_prune_age_hours: int = 168`, `aggressive_prune_threshold: float = 0.0`, `aggressive_prune_fraction: float = 0.30`, `episode_pressure_threshold: int = 5000`.
- Part B: `episodic.py:467` — `agent_recall_threshold`. `config.py` — the value is already configurable, just change the default.

**Impact:** Part A reduces episode pool growth rate, addressing the root of the scaling problem. Part B reduces candidate pool per query. Together they shrink the noise surface from both directions.

**Risk:** Medium. Aggressive pruning could remove memories that would later prove relevant. Needs careful eviction audit logging. Higher similarity floor could reduce recall for borderline-relevant episodes. Both should be monitored via qualification probes.

**Tests:** ~15-20 tests.

**Depends on:** Nothing. Independent.

---

## Implementation Order

```
AD-592 (Confabulation Guard Instructions)     ← cheapest, highest immediate impact
    ↓
AD-590 (Composite Score Floor)                 ← precise surgical fix, low risk
    ↓
AD-591 (Quality-Aware Budget Enforcement)      ← complementary to AD-590
    ↓
AD-593 (Pruning Acceleration + Sim Floor)      ← addresses root scaling cause
```

AD-592 should ship first because it's pure instruction change — no algorithmic risk. AD-590 and AD-591 are the core algorithmic fixes. AD-593 addresses the long-term scaling problem but is highest risk.

All four are independent and could theoretically ship in parallel, but the ordering above minimizes regression risk.

---

## Relationship to Other Planned Work

| AD | Relationship |
|----|-------------|
| **AD-587 (Cognitive Manifest)** | Should ship AFTER AD-592 at minimum. Manifest orientation text won't help if recall noise drowns it out. |
| **Recall Pipeline Research** (embedding model swap) | Orthogonal. Model swap fixes Q→A gap; these ADs fix noise floor. Both needed. |
| **AD-568b (Adaptive Budget)** | AD-591 supersedes part of adaptive budget logic. Should be reconciled — AD-591 can extend adaptive budget with quality-floor signal. |
| **Qualification Probes** | All four ADs should be validated via qualification probes. Probe scores should IMPROVE because less noise = less confabulation in probe responses. |

---

## Metrics to Track

1. **Marginal episode ratio**: % of recalled episodes with composite score < 0.35. Target: < 20% (currently ~80%).
2. **Mean composite score of recalled set**: Target: > 0.45 (currently ~0.35).
3. **Active episode count growth rate**: Episodes added - episodes pruned per dream cycle. Target: net zero or negative.
4. **Confabulation rate in qualification probes**: Observable via scoring — confabulated answers should score lower.
5. **Agent accuracy on authoritative data**: Track whether agents correctly cite orientation data vs. fabricating from memories.
