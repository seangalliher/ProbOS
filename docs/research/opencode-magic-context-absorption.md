# OpenCode magic-context — Compaction & Compression absorption study

**AD:** AD-715
**Issue:** [#492](https://github.com/seangalliher/ProbOS/issues/492)
**Upstream:** [`cortexkit/magic-context`](https://github.com/cortexkit/magic-context) (MIT, ~542★, v0.17.2; formerly `cortexkit/opencode-magic-context`)
**Status:** Research complete. No production code shipped (a measurement harness only).
**Date:** 2026-05-08

## 1. What It Does

`magic-context` is an OpenCode plugin (now also Pi-coding-agent compatible) that handles agent context entirely in the background. Every message, tool call, and file attachment receives a monotonic `§N§` tag persisted in SQLite. A separate lightweight "historian" model reads the eligible prefix and produces compartments (chronological structured blocks) and facts (durable categorized decisions). An overnight "dreamer" agent consolidates, verifies, archives stale memories, and rewrites verbose entries to terse operational form.

Three patterns differentiate it from a generic working-memory implementation:

- **Queued reductions** — `ctx_reduce(drop="3-5,12")` does not apply immediately. Two triggers fire the queue: cache TTL (default 5 min) or execute-threshold (default 65% of context). Recent tags (last 20) are protected.
- **Caveman age-tiered compression** — opt-in v0.15+. Oldest 20% → ultra-compressed; next 20% → full; next 20% → lite; newest 40% untouched. Tier shifts always recompress from the **pristine original**, never from an already-compressed intermediate. Cache-safe.
- **Cache-aware operation discipline** — every `ctx_*` operation is designed not to bust the LLM provider's prefix cache.

## 2. Architecture

`magic-context` persists state to a single SQLite database at `~/.local/share/opencode/storage/plugin/magic-context/context.db` containing 17 tables: tags, pending_ops, source_contents, compartments, session_facts, notes, session_meta, memories, memory_embeddings, dream_state, dream_queue, dream_runs, compression_depth, message_history_fts, message_history_index, recomp_compartments/facts, user_memory_candidates, user_memories.

Triggers and discipline:
- **Reduction triggers**: cache TTL (5 min) OR execute-threshold (65% context).
- **Recent tag protection**: last 20 tags are immune to reduction.
- **Tier-shift discipline**: caveman recompression always reads from `source_contents` (the pristine row), never the already-compressed intermediate.
- **Auto Search Hints** (experimental): before each turn, runs background `ctx_search` on the prompt; if top-score ≥ 0.55, appends a "vague recall" hint with caveman-compressed fragments.

The historian/dreamer split is the architectural backbone: synchronous-deferred (historian, runs queued reductions) vs. overnight (dreamer, runs verification/archival/rewrite).

## 3. What ProbOS Has

| magic-context primitive | ProbOS analogue | Citation | Coverage |
|---|---|---|---|
| Monotonic tagging (`§N§`) | episode `id` (UUID) — exists but not surfaced to the LLM as a compaction handle | `src/probos/types.py:445` | MISSING (no LLM-facing tag) |
| Queued reduction (TTL/threshold-driven) | none — Working Memory token-budgets reactively but does not queue ops | — | MISSING |
| Historian (synchronous-deferred consolidator) | dream consolidation pipeline (overnight only) | `src/probos/types.py:580` | PARTIAL |
| Caveman age-tiered compression | none — closest is LLM-summary in dream cycle | — | MISSING |
| Dreamer | AD-538 + dream consolidation | `src/probos/types.py:580` | PARTIAL |
| `ctx_search` | `recall` + `recall_weighted` | `src/probos/cognitive/episodic.py:1648` | YES (rough analog) |
| Composite-scored recall | `recall_weighted` (AD-606) | `src/probos/cognitive/episodic.py:2509` | PRESENT |
| Auto Search Hints | none | — | MISSING |
| Cache awareness | not modeled | — | MISSING |

## 4. Absorption Candidates

Ranked by gap-vs-effort:

1. **Caveman age-tiered compression as an opt-in dream-pipeline stage** — gap=high; effort=M (compression strategy registry + tier shift discipline reading from a pristine episode store); risk=MEDIUM (changes the dream summary contract). Proposed AD-715-1.
2. **Tagging-based addressable LLM context** — gap=high; effort=M (surface episode IDs as compaction handles + `ctx_reduce`-shaped tool); risk=LOW (additive). Proposed AD-715-2.
3. **Cache-aware LLM-client wrapper** — gap=high; effort=L (every existing call site must re-shape its prompt assembly); risk=HIGH (touches every cognitive path). Proposed AD-715-3.
4. **Queued reduction triggers (TTL + threshold)** — gap=high; effort=S; risk=LOW. Pair with absorption candidate #2 since the trigger logic is the policy layer above the tagging mechanism.

## 5. What We Reject

- **The OpenCode plugin layer itself.** ProbOS is not a coding-agent host; we don't run as a plugin to another agent's context.
- **The dual-harness SQLite share.** `magic-context` shares one SQLite DB across OpenCode and Pi; ProbOS does not split into multiple agent harnesses.
- **17-table proliferation.** ProbOS's storage is intentionally fewer tables. If we absorb caveman compression, the `source_contents` analog can be a column on `episodes`, not a separate table.

## 6. Recommended Follow-ups

| # | Title | Scope | AD candidate |
|---|---|---|---|
| 1 | Caveman age-tiered compression | Opt-in dream-pipeline stage; tier shifts read from pristine episode body | AD-715-1 |
| 2 | Tagging-based addressable context | Surface episode IDs as compaction handles + `ctx_reduce`-shaped tool | AD-715-2 |
| 3 | Cache-aware LLM-client wrapper | Preserve prefix cache across context updates; deferred until #1/#2 land | AD-715-3 |

## Status

Research complete. The compression-ratio harness (`tests/research/test_compression_ratio_harness.py`, opt-in via `PROBOS_RESEARCH_BENCH=1`) provides the baseline number future absorption ADs will quote ("ProbOS today compresses to R%; magic-context's caveman tier-shift compresses to ~X%; therefore the gap is/isn't worth M effort").

**Pinned dream-pipeline API for the harness:** the harness calls `EpisodicMemory.recall(query, k=...)` against ingested fixture episodes as the ProbOS-side compression proxy (each recalled episode's `user_input` is the "compressed" form). The full dream-cycle consolidation API (`DreamCycleStats` flush) is left for AD-715-1's implementation; v1 measurement uses the recall surface only.
