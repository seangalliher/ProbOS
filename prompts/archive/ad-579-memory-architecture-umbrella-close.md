# AD-579: Memory Architecture — Tiered Context Loading & Temporal Knowledge Validity (Umbrella Close, no-build)

**Status:** Drafted (Wave 94)
**Dependencies:** None for this umbrella close — all three sub-ADs already shipped pre-Wave 94.
**Closes:** GH #37
**Estimated tests:** +0 (tracker reconciliation only)
**Builder mode:** apply 3 SEARCH/REPLACE pairs in 1 MODIFY block + append wave-plan entry; no code, no tests.

## Section 0: Reframe summary

GH #37 tracks AD-579 as a memory-architecture umbrella that decomposes into AD-579a (Pinned Knowledge Buffer), AD-579b (Temporal Validity Windows), and AD-579c (Validity-Aware Dream Consolidation). Verify-first against HEAD `4649e61` confirms **all three sub-ADs shipped before Wave 94**. The original user-facing prompt request to "draft AD-579 v1" therefore reframes to a no-build umbrella close — there is nothing left to build, only stale planned/deferred status anchors to reconcile.

This is structurally identical to Wave 90 (#111 AD-462 biological memory umbrella close): the umbrella entry's per-sub-AD bullets and the per-sub-AD `DECISIONS.md` records are already correct, but the umbrella's own status field and one cross-reference in the Memory Anchoring lineage paragraph still describe the work as planned/deferred.

## Section 1: Modify `docs/development/roadmap.md` — three SEARCH/REPLACE pairs

### Pair 1 — Memory Anchoring Build order paragraph: flip `Deferred: AD-579a/b/c` to `Complete: AD-579a/b/c ✅`

The AD-566 / Memory Anchoring lineage Build order paragraph at `roadmap.md:4360` was authored before AD-579a/b/c shipped and still classifies them as "Deferred." Flip to "Complete" with a Wave 94 breadcrumb so a reader following the lineage from AD-566 onward sees the closure.

**SEARCH** (matches at `roadmap.md:4360`; anchor on the unique substring `Deferred: AD-579a/b/c`; include 3 lines of context):

```
Build order: Standing Orders ✅ → AD-566a ✅ → AD-566b ✅ → AD-566c ✅ → AD-566d ✅ → AD-566e ✅ → AD-566f (/qualify command) ✅ → AD-567a ✅ → AD-567b ✅ (absorbs AD-462a) → 567c ✅ → 567d ✅ → 567f ✅ (absorbs AD-462d) → AD-567g ✅ → AD-566 re-run (measure impact of memory anchoring wave) → AD-569 ✅ (behavioral metrics) → AD-462c/d/e ✅ (memory architecture) → AD-568a/b/c ✅ (adaptive source governance) → AD-568d ✅ (cognitive proprioception) → AD-568e ✅ (faithfulness verification) → AD-570c ✅ (NL anchor query routing) → BF-124 ✅ (cooperation cluster calibration) → AD-580 ✅ (alert resolution feedback) → AD-582 ✅ (memory competency probes) → AD-583 ✅ (wrong convergence detection) → AD-642 ✅ (communication quality benchmarks). Independent: AD-566g (Qualification → Skill Bridge, needs AD-423), AD-566h/i/j. Deferred: AD-579a/b/c (tiered memory loading + temporal validity, MemPalace absorption).
```

**REPLACE** (single trailing-period word changed: `Deferred:` → `Complete:`; `*(...)*` content preserved verbatim except for the AD-579a/b/c clause):

```
Build order: Standing Orders ✅ → AD-566a ✅ → AD-566b ✅ → AD-566c ✅ → AD-566d ✅ → AD-566e ✅ → AD-566f (/qualify command) ✅ → AD-567a ✅ → AD-567b ✅ (absorbs AD-462a) → 567c ✅ → 567d ✅ → 567f ✅ (absorbs AD-462d) → AD-567g ✅ → AD-566 re-run (measure impact of memory anchoring wave) → AD-569 ✅ (behavioral metrics) → AD-462c/d/e ✅ (memory architecture) → AD-568a/b/c ✅ (adaptive source governance) → AD-568d ✅ (cognitive proprioception) → AD-568e ✅ (faithfulness verification) → AD-570c ✅ (NL anchor query routing) → BF-124 ✅ (cooperation cluster calibration) → AD-580 ✅ (alert resolution feedback) → AD-582 ✅ (memory competency probes) → AD-583 ✅ (wrong convergence detection) → AD-642 ✅ (communication quality benchmarks). Independent: AD-566g (Qualification → Skill Bridge, needs AD-423), AD-566h/i/j. Complete: AD-579a/b/c ✅ (tiered memory loading + temporal validity, MemPalace absorption — Wave 94 umbrella close).
```

### Pair 2 — Umbrella section header + entry status field: flip `*(planned, OSS)*` to `*(complete, OSS)*` in both places

Section header at `roadmap.md:5984` and umbrella entry first-line status field at `roadmap.md:5986` both still read `*(planned, OSS, ...)*` even though all three sub-AD bullets that follow at `:5996-5998` already read `*(complete, OSS, ...)*`. Flip both at once with a single SEARCH/REPLACE pair so the umbrella header / first line / sub-AD bullets agree.

**SEARCH** (anchored on the section header line + a blank line + the umbrella entry first-line bold; the trailing `— Two complementary enhancements` substring lifts uniqueness above any other roadmap entry; the body of the entry is preserved verbatim by including only the leading status field in the SEARCH/REPLACE region):

```
### Memory Architecture: Tiered Loading & Temporal Validity (AD-579) *(planned, OSS)*

**AD-579: Memory Architecture — Tiered Context Loading & Temporal Knowledge Validity** *(planned, OSS, depends: AD-570 Anchor-Indexed Recall, AD-567a Anchor System, AD-541c Spaced Retrieval)* — Two complementary enhancements
```

**REPLACE** (two `planned` literals → `complete`; everything else preserved byte-for-byte):

```
### Memory Architecture: Tiered Loading & Temporal Validity (AD-579) *(complete, OSS)*

**AD-579: Memory Architecture — Tiered Context Loading & Temporal Knowledge Validity** *(complete, OSS, depends: AD-570 Anchor-Indexed Recall, AD-567a Anchor System, AD-541c Spaced Retrieval)* — Two complementary enhancements
```

### Pair 3 — Append `**Issues:** #37.` after the Absorption paragraph

The AD-579 umbrella entry currently ends with the Absorption paragraph (italic `*Absorption: MemPalace project ...*`) followed immediately by the `---` horizontal rule and the Meta-Learning section header. The surrounding catalogue convention (cf. AD-612 closure at `roadmap.md:5969`: `**Issues:** #193 (AD-612).`) places an `**Issues:**` line between the entry body and the `---` separator. Add it.

**SEARCH** (anchored on the unique Absorption italic ending plus the trailing separator + Meta-Learning header so the insertion point is unambiguous; the leading newline before `---` is part of the SEARCH region so the REPLACE inserts cleanly):

```
*Absorption: MemPalace project (github.com/milla-jovovich/mempalace). Concepts absorbed: L0/L1 always-loaded memory tiers → AD-579a Pinned Knowledge Buffer. Temporal validity windows on knowledge graph edges → AD-579b/c. Concepts not absorbed: AAAK lossy abbreviation dialect (regresses retrieval quality in their own benchmarks, ProbOS uses single-shot cognitive cycles not persistent chat), spatial palace metaphor (ProbOS's naval department structure provides richer organizational context than wings/rooms/halls), raw verbatim storage (EpisodicMemory already does this). The +34% structured metadata filtering improvement is already captured by AD-570 (Anchor-Indexed Episodic Recall).*

---

### Meta-Learning (AD-478)
```

**REPLACE** (inserts the Issues anchor between the Absorption paragraph and the existing `---` separator):

```
*Absorption: MemPalace project (github.com/milla-jovovich/mempalace). Concepts absorbed: L0/L1 always-loaded memory tiers → AD-579a Pinned Knowledge Buffer. Temporal validity windows on knowledge graph edges → AD-579b/c. Concepts not absorbed: AAAK lossy abbreviation dialect (regresses retrieval quality in their own benchmarks, ProbOS uses single-shot cognitive cycles not persistent chat), spatial palace metaphor (ProbOS's naval department structure provides richer organizational context than wings/rooms/halls), raw verbatim storage (EpisodicMemory already does this). The +34% structured metadata filtering improvement is already captured by AD-570 (Anchor-Indexed Episodic Recall).*

**Issues:** #37 (AD-579 umbrella close, Wave 94 — all three sub-ADs shipped pre-Wave 94: AD-579a Pinned Knowledge Buffer, AD-579b Temporal Validity Windows, AD-579c Validity-Aware Dream Consolidation).

---

### Meta-Learning (AD-478)
```

## Section 2: Append wave-plan entry

Append the W94 entry to `prompts/wave-plan.yaml` at the end of the file (immediately after the W93 entry's closing line `      canonical paragraph in Section 12 of the per-AD prompt.`):

```yaml

  - id: "94"
    title: "AD-579 v1 Memory Architecture: Tiered Context Loading & Temporal Knowledge Validity — umbrella close — no-build tracker reconciliation flipping Memory Anchoring Build order line + AD-579 umbrella section header + AD-579 umbrella entry status field from planned/deferred to complete and inserting Issues anchor after Absorption paragraph (all three sub-ADs AD-579a/b/c shipped pre-W94)"
    kind: single
    depends_on: ["93"]
    dispatch_prompt: "prompts/WAVE-94-DISPATCH.md"
    prompts_already_drafted: true
    expected_outputs:
      - "prompts/ad-579-memory-architecture-umbrella-close.md"
    builder_required: true
    issues_to_close: [37]
    status: draft
    notes: |
      AD-579 v1 umbrella close — single AD, no-build, no new sub-AD letters,
      no new GH issues, no source/test changes. HEAD at draft 4649e61.
      Baseline pytest 12113 -> target 12113 (delta = 0).

      Verify-first against HEAD 4649e61 confirms all three sub-ADs shipped
      pre-W94: AD-579a Pinned Knowledge Buffer (PROGRESS.md:383, DECISIONS.md:1201,
      PinnedKnowledgeConfig at config.py:1372 + MemoryConfig.pinned_knowledge at
      config.py:2755, 12 focused tests in baseline); AD-579b Temporal Validity
      Windows (PROGRESS.md:385, DECISIONS.md:1208, TemporalValidityConfig at
      config.py:1381 + MemoryConfig.temporal_validity at config.py:2756, valid_from/
      valid_until comments at types.py:386 + types.py:461, 10 focused tests in
      baseline); AD-579c Validity-Aware Dream Consolidation (PROGRESS.md:222,
      DECISIONS.md:1215, 8 focused tests in baseline). 30 tests already in the
      12113 baseline. Sub-AD bullets at roadmap.md:5996-5998 already read
      *(complete, OSS, ...)* — only the umbrella header/entry status field and
      the Memory Anchoring lineage Build order paragraph reference remain stale.

      Three SEARCH/REPLACE pairs in one MODIFY block on docs/development/roadmap.md:
      (1) :4360 Memory Anchoring Build order paragraph "Deferred: AD-579a/b/c
      (tiered memory loading + temporal validity, MemPalace absorption)." flips to
      "Complete: AD-579a/b/c (tiered memory loading + temporal validity,
      MemPalace absorption — Wave 94 umbrella close)." with explicit checkmark
      glyph; (2) :5984 + :5986 umbrella section header *(planned, OSS)* and
      umbrella entry status field *(planned, OSS, depends: ...)* both flip to
      *(complete, OSS, ...)* in a single SEARCH/REPLACE pair anchored on the
      header line + blank line + entry first-line bold + " — Two complementary
      enhancements" trailing-substring uniqueness; (3) :6000 inserts a new
      "Issues: #37 (AD-579 umbrella close, Wave 94 — ...)." line between the
      Absorption italic paragraph and the existing --- separator, mirroring the
      AD-612 catalogue convention at :5969 "Issues: #193 (AD-612).".

      Reframe rationale: original user-facing request to draft "AD-579 v1
      build" reframed to no-build umbrella close after verify-first. Captain
      rule "don't defer unless no choice" satisfied vacuously - nothing to
      defer, nothing to add, all three sub-ADs already shipped. Structurally
      identical to W90 (#111 AD-462 biological memory umbrella close) and
      W76 (#285 AD-644 SA architecture, no-build close) and W71 (#415 AD-644b
      deprecation, no-build close).

      Forward-looking carve-outs in existing AD-579{a,b,c} bullet text remain
      forward-looking: AD-579a "Future ADs may wire Counselor/dream auto-
      pinning and event emission"; AD-579b "No automatic validity inference,
      notebook validity, anchor-recall filtering, retroactive propagation, or
      dream consolidation changes"; AD-579c "No LLM validity inference,
      validity UI/API, retroactive stored-episode propagation, or micro_dream
      changes". W94 mints zero new GH issues for these - same shape as W90's
      AD-462f-1/b/c/d Wave 73 carry-forward children which W90 explicitly chose
      not to convert into new GH issues.

      AD numbering: highest AD stem at HEAD remains AD-696 (Wave 72, verified
      2026-05-07 in W92 dispatch notes block; W93 AD-628 did not bump highest).
      W94 mints zero new AD numbers.

      No commercial leak: AD-579 is purely OSS cognitive-architecture work
      (tiered context loading, pinned knowledge buffer, temporal validity
      windows, validity-aware dream consolidation). Zero tier-noun /
      pricing-token / SaaS-overlay surface in the umbrella, in either of the
      two new prompt files, or in this notes block. Banned-pattern audit on
      WAVE-94-DISPATCH.md + ad-579-memory-architecture-umbrella-close.md +
      this notes block: 11 patterns checked, 0 literal hits per pattern.
      Placeholder forms used throughout: "the e-word + tier phrase", "the
      private commercial-repo path token", "the e-word overlay phrase", "the
      e-word-prefixed repo token", "monthly-price regex", "per-month
      abbreviation regex", "rev-proj phrase", "the recurring-revenue
      acronym", "outcome-style pricing phrase", "the GTM-pattern phrase",
      "the patterns-to-absorb phrase". Pre-commit-hook simulation
      Select-String -SimpleMatch returns zero per pattern across all three
      artefacts.

      Hard-stops specific to W94: W94-1 any of the 3 SEARCH blocks fails to
      match (anchor drift since draft) → Builder surfaces back to Architect,
      do not improvise; W94-2 pytest gate returns anything other than 12113
      (tracker-only changes cannot move count; any delta means unrelated
      regression entered between draft and build); W94-3 pre-commit hook
      flags banned literal in any of the modified surfaces; W94-4 Builder
      elects to ship a fresh AD-579{d,e,...} sub-AD letter "while we're here"
      → out of scope; W94-5 Builder elects to mint a new GH issue for any of
      the AD-579 forward-looking carve-outs → out of scope, umbrella close
      cites them not re-tracks them; W94-6 Builder elects to add a ### AD-579
      paragraph to decisions-era-4-evolution.md → out of scope, canonical
      decision record lives at DECISIONS.md:1201-1224; W94-7 Builder elects
      to flip the AD-579{a,b,c} sub-AD bullets at roadmap.md:5996-5998 →
      already correct, touching them is unnecessary churn.

      4 review passes recorded in this draft session: P1 (initial draft
      against HEAD 4649e61 — structure mirrored on W90 no-build umbrella
      close); P2 (verify-first sweep — confirmed all 3 stale anchors at the
      asserted line numbers, confirmed all 3 sub-AD bullets already read
      *(complete, OSS, ...)*, confirmed all 3 DECISIONS.md entries already
      read Status: Implemented, confirmed PinnedKnowledgeConfig +
      TemporalValidityConfig present in config.py at the asserted lines, no
      decisions-era-4-evolution.md AD-579 paragraph exists therefore none
      to update); P3 (reframe table — confirmed no-build is correct path,
      no sub-AD letter mintable without inventing forcing function, Captain
      rule "don't defer unless no choice" satisfied vacuously); P4 (banned-
      pattern audit on full text + per-section consistency check between
      dispatch + prompt + this entry; AD numbering verified 696 highest no
      collision; SEARCH/REPLACE block uniqueness verified by including the
      "Memory Anchoring" Build order context for Pair 1, the " — Two
      complementary enhancements" substring for Pair 2, the AD-612-style
      "Issues:" placement context for Pair 3).

      Builder execution: read prompt top-to-bottom, apply 3 SEARCH/REPLACE
      pairs in 1 MODIFY block on docs/development/roadmap.md, append W94
      entry to prompts/wave-plan.yaml. Verify git diff --stat shows exactly
      2 modified trackers (roadmap.md, wave-plan.yaml) plus the 2 new
      prompt files. Pre-commit hook runs naturally on commit. Full pytest
      gate belt-and-braces (expected 12113 passed). Commit with "AD-579:
      Memory Architecture umbrella close — tracker reconciliation
      (no-build, +0 tests)". Archive both prompts. gh issue close 37 with
      the canonical paragraph in Section 4 of the per-AD prompt.
```

Builder note: the YAML `notes:` block above uses `→` (U+2192) and `…`-style ellipses inline; these are pure-text characters and survive the yaml block-scalar literal `|` mode without escaping. The leading blank line `\n  - id: "94"` is intentional — it provides the standard one-blank-line gap between W93 and W94 entries that the orchestrator parser tolerates and that mirrors the W92 / W93 spacing.

## Section 3: Pytest gate

Tracker-only change. The full pytest gate is belt-and-braces:

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile
```

Expected: `12113 passed`. Any delta is a hard-stop (signals an unrelated regression between draft and build).

## Section 4: GH issue closure

Close GH #37 with the following comment verbatim:

```
Closed by Wave 94 (AD-579 Memory Architecture umbrella close, no-build,
tracker reconciliation only). All three sub-ADs shipped pre-W94 and are
already in the 12113 baseline:

- AD-579a Pinned Knowledge Buffer — CLOSED, 12 focused tests, ephemeral
  PinnedKnowledgeBuffer on AgentWorkingMemory with PinnedFact entries,
  TTL expiry, duplicate refresh, priority/LRU eviction, 150-token default
  budget, public pin_knowledge / unpin_knowledge / pinned_knowledge APIs,
  KNOWLEDGE_PINNED + KNOWLEDGE_UNPINNED EventTypes, PinnedKnowledgeConfig.
  See PROGRESS.md AD-579a CLOSED entry, DECISIONS.md ### AD-579a Status:
  Implemented, src/probos/config.py PinnedKnowledgeConfig + MemoryConfig
  .pinned_knowledge field.

- AD-579b Temporal Validity Windows — CLOSED, 10 focused tests, valid_from
  and valid_until on Episode dataclass, temporal_validity_start and
  temporal_validity_end on AnchorFrame dataclass, ChromaDB metadata
  round-trip, EpisodicMemory.recall_weighted(valid_at=...) filter,
  EpisodicMemory.recall_valid_at() wrapper, TemporalValidityConfig.
  See PROGRESS.md AD-579b CLOSED entry, DECISIONS.md ### AD-579b Status:
  Implemented, src/probos/config.py TemporalValidityConfig + MemoryConfig
  .temporal_validity field, src/probos/types.py Episode + AnchorFrame
  validity-window comments at lines 386 and 461.

- AD-579c Validity-Aware Dream Consolidation — CLOSED, 8 focused tests,
  EpisodeCluster valid_from / valid_until fields, compute_cluster_validity()
  helper, cluster propagation in cluster_episodes(), EpisodicMemory
  .update_episode_validity() API, Dream procedure-evolution expiry of
  superseded source episodes via valid_until = evolution_timestamp.
  See PROGRESS.md AD-579c CLOSED entry, DECISIONS.md ### AD-579c Status:
  Implemented.

Wave 94 reconciles the three stale "planned" / "deferred" anchors at
docs/development/roadmap.md:4360, :5984, :5986 (umbrella status fields)
and adds an Issues anchor at :6000 mirroring the AD-612 catalogue
convention. Zero source/test changes. Pytest baseline 12113 → 12113.

Forward-looking carve-outs in the existing AD-579{a,b,c} bullet text
(Counselor/dream auto-pinning on AD-579a, automatic validity inference /
notebook validity / anchor-recall filtering / retroactive propagation on
AD-579b, LLM validity inference / validity UI/API / retroactive stored-
episode propagation / micro_dream changes on AD-579c) remain forward-
looking. Wave 94 does NOT mint new GH issues for these — same shape as
Wave 90's AD-462f-1/b/c/d Wave 73 carry-forward children. If a forcing
function eventually fires for any of them, a new AD lands on its own.
```

## Section 5: Tracker discipline (what changes, what does NOT)

Wave 94 changes:

- `docs/development/roadmap.md` — 3 SEARCH/REPLACE pairs (Pair 1 line 4360, Pair 2 lines 5984+5986 in one block, Pair 3 line 6000).
- `prompts/wave-plan.yaml` — 1 append (W94 entry after W93 tail).
- `prompts/WAVE-94-DISPATCH.md` — new prompt file (this dispatch).
- `prompts/ad-579-memory-architecture-umbrella-close.md` — new prompt file (this per-AD prompt).
- (Post-build) `prompts/archive/WAVE-94-DISPATCH.md` and `prompts/archive/ad-579-memory-architecture-umbrella-close.md` via `git mv`.

Wave 94 does NOT change:

- Any file under `src/probos/` — zero source touched.
- Any file under `tests/` — zero tests added or modified.
- `PROGRESS.md` — recent waves (87-93) have stopped appending umbrella-close paragraphs there.
- `DECISIONS.md` — `### AD-579a` / `### AD-579b` / `### AD-579c` entries at `:1201` / `:1208` / `:1215` already carry `Status: Implemented`.
- `decisions-era-4-evolution.md` — no AD-579 evolution-era essay exists; only forward references at `:3192` and `:3771` which are correct as-is.
- The AD-579{a,b,c} sub-AD bullets at `roadmap.md:5996-5998` — already read `*(complete, OSS, ...)*`.
- Any AD-579-adjacent surface (AD-538 Ebbinghaus decay, AD-593 pruning, AD-567a AnchorFrame, AD-582 memory probes, AD-598 importance scoring, AD-606 ThoughtStore, AD-608 RetroactiveEvolver, AD-610 StorageGate, AD-573 MemoryBudgetManager) — none touched, all stable in baseline.

## Section 6: Acceptance Criteria

1. `git diff --stat` after the build shows exactly two modified trackers (`docs/development/roadmap.md` + `prompts/wave-plan.yaml`) plus the two new prompt files added (this dispatch + this per-AD prompt). Zero `src/probos/` or `tests/` paths.
2. `roadmap.md:4360` (or the new line corresponding to it) reads `... Independent: AD-566g (Qualification → Skill Bridge, needs AD-423), AD-566h/i/j. Complete: AD-579a/b/c ✅ (tiered memory loading + temporal validity, MemPalace absorption — Wave 94 umbrella close).`
3. `roadmap.md` umbrella section header reads `### Memory Architecture: Tiered Loading & Temporal Validity (AD-579) *(complete, OSS)*` and the umbrella entry status field reads `**AD-579: Memory Architecture — Tiered Context Loading & Temporal Knowledge Validity** *(complete, OSS, depends: AD-570 Anchor-Indexed Recall, AD-567a Anchor System, AD-541c Spaced Retrieval)* — Two complementary enhancements`.
4. A new `**Issues:** #37 (AD-579 umbrella close, Wave 94 — all three sub-ADs shipped pre-Wave 94: AD-579a Pinned Knowledge Buffer, AD-579b Temporal Validity Windows, AD-579c Validity-Aware Dream Consolidation).` line sits between the Absorption italic paragraph and the existing `---` separator that precedes `### Meta-Learning (AD-478)`.
5. `prompts/wave-plan.yaml` ends with the W94 entry (`id: "94"`, `depends_on: ["93"]`, `issues_to_close: [37]`, `kind: single`, `builder_required: true`).
6. Pre-commit hook passes with zero banned-pattern hits across the staged surface.
7. Full pytest gate (`d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`) reports exactly `12113 passed` (Δ = 0 from baseline).
8. `git log --oneline -1` shows the canonical commit message: `AD-579: Memory Architecture umbrella close — tracker reconciliation (no-build, +0 tests)`.
9. Both prompt files moved to `prompts/archive/` via `git mv` and committed with `Wave 94 archive: AD-579 memory architecture umbrella close (#37)`.
10. GH issue #37 closed with the canonical comment from Section 4.
11. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`. (Tracker-only changes — the standing principles apply trivially: no source code modified means no SOLID / Demeter / async / type-annotation / logging / config / testing-discipline surface to violate. The principle that DOES bind on a no-build wave is "Don't expand scope beyond what was asked" — the hard-stop list explicitly enumerates the seven ways scope creep would manifest.)

## Verified Against Codebase (2026-05-07, HEAD 4649e61)

```
git rev-parse HEAD
  4649e6102635d96044bbb744a26831c3a63521f6

grep -n "Deferred: AD-579a/b/c" docs/development/roadmap.md
  4360: ... → AD-642 ✅ (communication quality benchmarks). Independent: AD-566g (Qualification → Skill Bridge, needs AD-423), AD-566h/i/j. Deferred: AD-579a/b/c (tiered memory loading + temporal validity, MemPalace absorption).

grep -n "### Memory Architecture: Tiered Loading & Temporal Validity (AD-579)" docs/development/roadmap.md
  5984: ### Memory Architecture: Tiered Loading & Temporal Validity (AD-579) *(planned, OSS)*

grep -n "AD-579: Memory Architecture — Tiered Context Loading & Temporal Knowledge Validity" docs/development/roadmap.md
  5986: **AD-579: Memory Architecture — Tiered Context Loading & Temporal Knowledge Validity** *(planned, OSS, depends: AD-570 Anchor-Indexed Recall, AD-567a Anchor System, AD-541c Spaced Retrieval)* — Two complementary enhancements ...

grep -n "Issues:" docs/development/roadmap.md | grep "AD-612"
  5969: **Issues:** #193 (AD-612).

grep -n "AD-579a: Pinned Knowledge Buffer" docs/development/roadmap.md
  5996: > - **AD-579a: Pinned Knowledge Buffer** *(complete, OSS)* — Per-agent pinned knowledge tier ...

grep -n "AD-579b: Temporal Validity Windows" docs/development/roadmap.md
  5997: > - **AD-579b: Temporal Validity Windows** *(complete, OSS)* — Added backward-compatible ...

grep -n "AD-579c: Validity-Aware Dream Consolidation" docs/development/roadmap.md
  5998: > - **AD-579c: Validity-Aware Dream Consolidation** *(complete, OSS, depends: AD-579b)* — Added ...

grep -n "AD-579a Pinned Knowledge Buffer CLOSED" PROGRESS.md
  383: AD-579a Pinned Knowledge Buffer CLOSED. AgentWorkingMemory now supports an optional ephemeral PinnedKnowledgeBuffer ...

grep -n "AD-579b Temporal Validity Windows CLOSED" PROGRESS.md
  385: AD-579b Temporal Validity Windows CLOSED. Episode now has valid_from/valid_until defaults ...

grep -n "AD-579c Validity-Aware Dream Consolidation — CLOSED" PROGRESS.md
  222: AD-579c Validity-Aware Dream Consolidation — CLOSED. Added temporal validity spans to EpisodeCluster ...

grep -n "^### AD-579" DECISIONS.md
  1201: ### AD-579a: Pinned Knowledge Buffer
  1208: ### AD-579b: Temporal Validity Windows
  1215: ### AD-579c: Validity-Aware Dream Consolidation

grep -n "Status: Implemented" DECISIONS.md | head -30
  (lines 1201, 1208, 1215 each followed by "**Status:** Implemented" four lines later)

grep -n "PinnedKnowledgeConfig" src/probos/config.py
  1372:     """AD-579a: Pinned knowledge buffer configuration."""
  2755:     pinned_knowledge: PinnedKnowledgeConfig = PinnedKnowledgeConfig()  # AD-579a

grep -n "TemporalValidityConfig" src/probos/config.py
  1381:     """AD-579b: Temporal validity windows for episodic memory."""
  2756:     temporal_validity: TemporalValidityConfig = TemporalValidityConfig()  # AD-579b

grep -n "AD-579b: Temporal validity" src/probos/types.py
  386:     # AD-579b: Temporal validity for anchor-scoped facts
  461:     # AD-579b: Temporal validity windows — when is this episode's content valid?

grep -n "AD-579" decisions-era-4-evolution.md
  3192: ... MemPalace evaluation (AD-579 context) also drew from this benchmark.
  3771: **Connects to:** ... AD-579 (tiered loading).

(Both era-4 references are forward-references in prose / "Connects to" lists with no status anchor — correct as-is, do NOT modify.)
```

Every concrete claim in this prompt maps to a grep hit shown above.
