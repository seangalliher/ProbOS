# LoCoMo Benchmark Absorption + Harness Stub

**AD:** AD-716
**Issue:** [#497](https://github.com/seangalliher/ProbOS/issues/497) (subsumes closed-as-duplicate [#494](https://github.com/seangalliher/ProbOS/issues/494))
**Upstream:** [`NirDiamant/Agent_Memory_Techniques`](https://github.com/NirDiamant/Agent_Memory_Techniques) (Apache-2.0, ~214★, technique 29 = LoCoMo)
**Status:** Research complete. Harness stub ships skipped-by-default.
**Date:** 2026-05-08

## 1. What LoCoMo Measures

LoCoMo (Long Conversation Memory) is the de-facto open benchmark for agent memory architectures. It feeds a system multi-session conversations between two personas, then asks questions at the end of the run that require recalling facts, preferences, and events from earlier sessions. Both Mem0 and MemOS quote LoCoMo numbers as their headline metric.

The methodology produces five signals per question:

- **Precision** — was the right episode recalled?
- **Recall** — did all relevant episodes surface?
- **Staleness** — did stale facts override new ones?
- **Contradiction** — does the system surface contradictions or pick a side silently?
- **Answer correctness** — given the recalled context, did the system produce the ground-truth answer (exact-match or LLM-judge graded)?

LongMemEval is a companion benchmark with the same shape and a different scope. The dispatch directs us to capture both under one umbrella.

## 2. Why It Matters For ProbOS

A LoCoMo number gates three decisions:

1. **Memory-architecture absorption priority.** The Memvid (AD-712), magic-context (AD-715), and any future RAGFlow ingestion AD all claim to improve recall quality. Without a baseline, we cannot tell whether the absorption is worth the engineering cost.
2. **Dream-pipeline tuning.** Dream consolidation rewrites episodic content; if rewrites degrade LoCoMo precision, we should know before a regression ships to users.
3. **Recall threshold tuning.** AD-606 composite scoring exposes `composite_score_floor`, `recall_quality_floor`, `anchor_confidence_gate` knobs. LoCoMo gives a single objective for sweeping them.

## 3. What ProbOS Has

| LoCoMo metric | ProbOS recall surface | Citation | Notes |
|---|---|---|---|
| Answer correctness | `recall_weighted` (composite-scored) | `src/probos/cognitive/episodic.py:2509` | AD-606. Best entry point for "give me the most relevant K episodes." |
| Precision (structured) | `recall_by_anchor` | `src/probos/cognitive/episodic.py:2747` | AD-570. Direct lookup by anchor fields. |
| Recall (semantic breadth) | `recall(query, k)` | `src/probos/cognitive/episodic.py:1648` | Pure semantic. Lowest floor; useful for upper-bound recall. |
| Staleness | `AnchorFrame.temporal_validity_start/end` | `src/probos/types.py:391` | AD-579b. Episodes can be marked expired-after. |
| Contradiction | none | — | Open gap. ProbOS does not surface contradicting episodes today. |

## 4. Harness Design

**Fixture (micro-LoCoMo v1).** 3 sessions × 5+ turns each, 5 questions total. Each question's `expected_substring` is verbatim somewhere in the corresponding session's turns. Hand-authored realistic-but-synthetic content. Lives at `tests/benchmarks/data/micro_locomo.json`.

**Scoring function.** Exact-substring per question:
- For each question, run `EpisodicMemory.recall(question.question, k=3)`.
- Concatenate the recalled episodes' `user_input` fields, lowercased.
- A question scores 1 if its `expected_substring.lower()` appears in the concatenated text; 0 otherwise.
- `ratio = correct / total`.

**API choice (verified).** The prompt suggested `recall_weighted` but the live signature requires an `agent_id` positional argument — the harness uses `recall(query, k)` for v1 simplicity. The composite-scored path (`recall_weighted`) becomes a follow-up benchmark in AD-716-3 once the harness has scaffolding for an agent identity context.

**Skip semantics.** Default `pytest tests/` skips the harness via env-var gate. Opt-in via `PROBOS_BENCHMARK_LOCOMO=1`.

## 5. Limitations Of v1

- **Hand-authored, not real LoCoMo data.** The published LoCoMo dataset is multi-GB and license-encumbered. v1 ships a 3-session × 5-question micro fixture.
- **Exact-substring only.** No LLM-judge fuzzy correctness. The number is **directional**, not publishable. Two systems with identical LoCoMo scores under exact-match may diverge wildly under judge-graded scoring.
- **Recall surface is `recall`, not `recall_weighted`.** v1 measures the simplest path; AD-716-3 will benchmark all three recall surfaces (`recall` / `recall_by_anchor` / `recall_weighted`) so absorption ADs can pick the strongest baseline.
- **No contradiction surfacing.** ProbOS does not yet surface contradictions; that LoCoMo metric will read 0.0 until a contradiction-detection AD lands.

## 6. Recommended Follow-ups

| # | Title | Scope | AD candidate |
|---|---|---|---|
| 1 | Real LoCoMo dataset wired in | Subject to license review; replace micro fixture with full benchmark subset | AD-716-1 |
| 2 | LLM-judge scoring | Fuzzy answer correctness via cheap judge model | AD-716-2 |
| 3 | Per-metric breakdown | Precision / recall / staleness / contradiction / answer-correctness as five separate ratios | AD-716-3 |

## Status

Research complete. Harness stub at `tests/benchmarks/test_locomo_episodic.py` (opt-in). Baseline ratio is intentionally directional; do not publish externally without LLM-judge scoring (AD-716-2).
