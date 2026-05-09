# RESEARCH — opencode-magic-context absorption study

**Issue:** [#492](https://github.com/seangalliher/ProbOS/issues/492)
**Type:** Research AD (no production code; doc + 1 concrete artifact)
**Upstream:** https://github.com/cortexkit/magic-context (formerly `cortexkit/opencode-magic-context`; MIT, 542★, v0.17.2 latest 2026-05-07)
**Depends on:** AD-606 (Think-in-Memory), AD-538 (Ebbinghaus decay), Dream consolidation pipeline.
**Wave:** 130

## Goal

`cortexkit/magic-context` is an OpenCode plugin that handles agent context entirely in the background. Its absorbable contributions: **transparent context compaction via a background "historian" model**, **age-tiered text compression** (caveman-rules), **cross-session project memory**, and an **overnight "dreamer" agent** that consolidates / verifies / archives memories. ProbOS already has analogues for all four — Working Memory, Ebbinghaus decay, Episodic store, dream consolidation pipeline — but the magic-context formulation is more aggressive, more measured, and ships in production. AD-711's goal is to pin down precisely what magic-context does that ProbOS does not, and produce a research doc plus a measurement harness for ProbOS's current compression ratio so future absorption can be quantitatively justified.

## Architect-fetched upstream summary (2026-05-08)

Pulled from `cortexkit/magic-context` `README.md` (https://github.com/cortexkit/magic-context). Note: the repo recently renamed from `opencode-magic-context` to `magic-context` and broadened to support both OpenCode and the Pi coding agent, sharing the same SQLite database. The dispatch's `opencode-magic-context` URL still resolves but the canonical repo is now `cortexkit/magic-context`.

Key architectural pieces:

- **Tagging** — every message, tool output, and file attachment gets a monotonic `§N§` tag. Persisted in SQLite. Tags are how `ctx_reduce` references content for removal.
- **Queued reductions** — `ctx_reduce(drop="3-5,12")` does NOT apply immediately. Two triggers fire the queue: **cache TTL** (default 5 min) or **execute-threshold** (default 65% of context). Recent tags (last 20) are protected.
- **Background historian** — a separate, lightweight model that reads the eligible prefix and produces **compartments** (chronological structured blocks) and **facts** (durable categorized decisions). Async; main agent never waits.
- **Caveman text compression** (`packages/plugin/src/hooks/magic-context/caveman.ts`, opt-in v0.15+). Age-tiered: oldest 20% → ultra-compressed, next 20% → full, next 20% → lite, newest 40% untouched. Tier shifts always recompress from the **pristine original**, never from an already-compressed intermediate. Cache-safe.
- **Dreamer** — overnight agent: consolidate, verify (against current codebase), archive stale, improve (rewrite verbose memories to terse operational form), maintain ARCHITECTURE.md / STRUCTURE.md, evaluate smart-note conditions, promote recurring user-behavior observations.
- **`ctx_*` tools** exposed to the agent: `ctx_reduce`, `ctx_expand`, `ctx_note` (deferred intentions, includes `surface_condition` for dreamer-evaluated triggers), `ctx_memory` (write/delete cross-session memory), `ctx_search` (unified search across memories + facts + raw history, semantic with FTS fallback).
- **Storage** — SQLite at `~/.local/share/opencode/storage/plugin/magic-context/context.db`. 17 tables (tags, pending_ops, source_contents, compartments, session_facts, notes, session_meta, memories, memory_embeddings, dream_state, dream_queue, dream_runs, compression_depth, message_history_fts, message_history_index, recomp_compartments/facts, user_memory_candidates, user_memories).
- **Auto Search Hints** (experimental) — before each turn, runs background `ctx_search` on the prompt; if top-score ≥ 0.55, appends a "vague recall" hint with caveman-compressed fragments. The agent then decides to expand.
- **Cache awareness** — every operation is designed to NOT bust the LLM provider's prefix cache. Tier shifts recompress from pristine to keep cache stable.

ProbOS analogues:

| magic-context | ProbOS | Same? |
|---|---|---|
| Tagging (`§N§`) | None — events have IDs, but they're not surfaced to the LLM as compaction handles | NO |
| Queued reduction | None — Working Memory token-budgets but doesn't do queued drops | NO |
| Historian | Closest: dream consolidation. Different: dream is overnight, not synchronous-deferred | PARTIAL |
| Caveman compression | None — closest is summary-via-LLM in dream cycle | NO |
| Dreamer | AD-538 + dream pipeline | PARTIAL |
| `ctx_search` | `EpisodicMemory.recall` + `recall_weighted` | YES (rough analog) |
| Auto Search Hints | None | NO |
| Cache awareness | Not modeled — ProbOS LLM client does not preserve prefix cache | NO |

The absorbable subset: **(1) tagging-based addressable context, (2) queued reductions with TTL/threshold triggers, (3) caveman age-tiered compression as a rung on the existing dream pipeline, (4) cache-aware operation discipline**.

## Verified Against Codebase (2026-05-08)

- ✅ AD-606 think-in-memory composite scoring: `src/probos/cognitive/episodic.py:2509` `recall_weighted`. ProbOS does not currently expose a `ctx_search`-shaped tool to the LLM — the equivalent is decomposer-driven recall.
- ✅ AD-538 Ebbinghaus decay: verify-first the module (likely `src/probos/cognitive/forgetting.py` or in `episodic.py`).
- ✅ Dream consolidation pipeline: `src/probos/types.py:580–593` `DreamCycleStats` references `wm_entries_flushed`, `bridged_procedures`, `inferred_relationships`, etc. — confirms a working pipeline.
- ✅ No existing module named `compaction/`, `historian/`, `compression/`, `caveman/` in `src/probos/`.
- ✅ ProbOS LLM client does not currently track prefix-cache stability — verify-first `src/probos/cognitive/llm_client.py`.

## Scope

- Architect has fetched the README. **Builder reads (selectively, not exhaustively) `packages/plugin/src/hooks/magic-context/caveman.ts` for the compression rules and a representative SQL schema reference, plus the README of either OpenCode plugin or Pi plugin** to fill in implementation specifics.
- Builder writes the absorption doc and produces ONE measurement harness.

## Deliverables

### D1. `docs/research/opencode-magic-context-absorption.md`

Required section structure:

1. **What It Does** — paraphrase the upstream README in ProbOS's vocabulary.
2. **Architecture** — list the 17 SQLite tables, the queued-reduction triggers, the historian/dreamer split, the cache-awareness discipline.
3. **What ProbOS Has** — table mapping each magic-context primitive to a ProbOS analogue (or "missing"). Every claim must be backed by a `path/file.py:NNN` citation.
4. **Absorption Candidates** — ranked. Each row: pattern, ProbOS gap, proposed AD, S/M/L effort, LOW/MEDIUM/HIGH risk.
5. **What We Reject** — e.g. the OpenCode plugin layer itself (we are not a coding-agent host); the dual-harness SQLite share-arrangement.
6. **Recommended Follow-ups** — at most 3 issue stubs.

### D2. Concrete artifact: compression-ratio harness

Builder ships `tests/research/test_compression_ratio_harness.py`. Skipped by default (`pytest.mark.skipif(os.getenv("PROBOS_RESEARCH_BENCH") != "1", ...)`).

When opt-in:

1. **Pre-check (Recommended R2/R3):** Before the harness body, Builder verifies (a) `EpisodicMemory`'s constructor signature — the kwarg may be `persist_directory`, `data_dir`, or `persist_dir`; the spec snippet below uses `persist_directory` but the Builder MUST grep the live class first and adjust to the actual name; (b) the dream-cycle entry point used in step 2 — closest single-API candidates today are `dreaming.run_cycle()` and the working-memory flush; pin one in the absorption doc and use it in the harness.
2. Loads a small fixture conversation (10 user/assistant turns, ~3000 chars total) from `tests/research/data/sample_session.json`.
3. Runs ProbOS's existing dream-consolidation summary path on the conversation (the API pinned in step 1).
4. Computes `compression_ratio = compressed_chars / original_chars`.
5. Prints a single JSON line: `{"original_chars": N, "compressed_chars": M, "ratio": R, "method": "probos_dream_summary"}`.
6. Asserts the ratio is `> 0.0` (sanity — expansion above 1.0 is rare but legal when ProbOS adds metadata/anchors; document in section 5 of the doc if observed).

The fixture session lives in `tests/research/data/sample_session.json` as a list of `{"role": "user"|"assistant", "content": "..."}`. Builder authors it with realistic-but-synthetic content — no real conversation data.

The point is **not** to tune ProbOS's compression. The point is to have a baseline number we can quote when evaluating any future caveman-style absorption: "ProbOS today compresses to R%; magic-context's caveman tier-shift compresses to ~X%; therefore the gap is/isn't worth M effort."

## Hard constraints (do NOT do)

- Do **not** implement any caveman-style compression in production code in this AD. Pure measurement.
- Do **not** copy upstream TS code into the harness. Paraphrase rules in the doc; the harness measures ProbOS, not magic-context.
- Do **not** add a SQLite "compression_depth" table or any new schema in this AD.
- Do **not** assert ProbOS coverage without a grep-verified file:line citation.
- Do **not** add the harness to the default test gate — opt-in only.

## Acceptance criteria

- **Pre-flight (Wave 129 convention #20):** run `git diff --numstat | sort -k2nr | head -5`; >200 deletions on any tracked file = STOP and surface to the Architect before reading source.
- `docs/research/opencode-magic-context-absorption.md` exists with all six required sections.
- `tests/research/test_compression_ratio_harness.py` exists, is skipped by default, and runs successfully under `PROBOS_RESEARCH_BENCH=1`.
- Fixture file `tests/research/data/sample_session.json` exists with at least 10 turns.
- Focused gate: `PROBOS_RESEARCH_BENCH=1 d:/ProbOS/.venv/Scripts/pytest.exe tests/research/test_compression_ratio_harness.py -v -n 0` passes (harness completes, prints the JSON line, ratio > 0.0).
- Full gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile` — research test is skipped, no slowdown.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Forward markers

- **AD-711-1**: caveman-style age-tiered compression as an opt-in stage in the dream pipeline.
- **AD-711-2**: tagging-based addressable LLM context (`ctx_reduce` analog).
- **AD-711-3**: cache-aware LLM-client wrapper that preserves prefix stability across context updates.

## Revision (2026-05-08)

- **Recommended R2 (constructor signature):** Added explicit pre-check step in D2 — Builder verifies the live `EpisodicMemory.__init__` kwarg name (`persist_directory` vs `data_dir` vs `persist_dir`) before authoring the harness.
- **Recommended R3 (dream-pipeline API):** Added pre-check requirement to pin the single dream-cycle entry point (likely `dreaming.run_cycle()` or working-memory flush) in the absorption doc; harness uses the pinned API.
- **Recommended R4 (ratio bounds):** Loosened the assertion from `(0.0, 1.0]` to `> 0.0` so a rare expansion case (metadata/anchors added) does not spuriously fail the harness; documentation requirement added.
- **Cross-cutting:** Added pre-flight working-tree integrity reminder. No config.py edits — no Build Ordering Note required.
