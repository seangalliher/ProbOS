# WAVE 94 DISPATCH — AD-579 Memory Architecture: Tiered Context Loading & Temporal Knowledge Validity — Umbrella Close (single AD, no-build)

**HEAD at draft:** `4649e61` (Wave 93 archive: AD-628 crew skill readiness)
**Baseline pytest:** `12113` → target `12113` (Δ = 0; tracker-only, zero source/test changes)
**Single AD:** AD-579 umbrella close (full closure of GH #37 — all three sub-ADs already shipped before Wave 94)
**Builder required:** Yes (3 SEARCH/REPLACE pairs in `docs/development/roadmap.md` plus 1 wave-plan append; no code, no tests)

## Why this wave is one AD and no build

GH #37 names AD-579 as the "Memory Architecture: Tiered Context Loading & Temporal Knowledge Validity" umbrella decomposed into three sub-ADs in `docs/development/roadmap.md:5994-5998`. Verify-first against HEAD `4649e61` finds **all three sub-ADs shipped before Wave 94**:

| Sub-AD | Status at HEAD | Evidence |
|---|---|---|
| AD-579a Pinned Knowledge Buffer | shipped | `PinnedKnowledgeConfig` (`config.py:1372`), `pinned_knowledge` field on `MemoryConfig` (`config.py:2755`); CLOSED entry at `PROGRESS.md:383`; `### AD-579a` Status: Implemented at `DECISIONS.md:1201`; sub-AD bullet at `roadmap.md:5996` already reads `*(complete, OSS)*` |
| AD-579b Temporal Validity Windows | shipped | `TemporalValidityConfig` (`config.py:1381`), `temporal_validity` field on `MemoryConfig` (`config.py:2756`); `valid_from`/`valid_until` on Episode (`types.py:461` comment), `temporal_validity_start`/`temporal_validity_end` on AnchorFrame (`types.py:386` comment); CLOSED entry at `PROGRESS.md:385`; `### AD-579b` Status: Implemented at `DECISIONS.md:1208`; sub-AD bullet at `roadmap.md:5997` already reads `*(complete, OSS)*` |
| AD-579c Validity-Aware Dream Consolidation | shipped | CLOSED entry at `PROGRESS.md:222`; `### AD-579c` Status: Implemented at `DECISIONS.md:1215`; sub-AD bullet at `roadmap.md:5998` already reads `*(complete, OSS, depends: AD-579b)*` |

**The defect this wave closes:** Three stale anchors at HEAD `4649e61` describe AD-579 as planned/deferred even though the per-sub-AD bullets and the per-sub-AD `### AD-579{a,b,c}` decision entries are all already correct:

- `docs/development/roadmap.md:4360` (Memory Anchoring lineage Build order paragraph) still reads `Deferred: AD-579a/b/c (tiered memory loading + temporal validity, MemPalace absorption).`
- `docs/development/roadmap.md:5984` (umbrella section header) still reads `### Memory Architecture: Tiered Loading & Temporal Validity (AD-579) *(planned, OSS)*`
- `docs/development/roadmap.md:5986` (umbrella entry status field) still reads `**AD-579: Memory Architecture — Tiered Context Loading & Temporal Knowledge Validity** *(planned, OSS, depends: ...)*`
- `docs/development/roadmap.md:6000` (Absorption paragraph) lacks an `**Issues:** #37.` line that the surrounding catalogue convention applies (cf. AD-612 closure at `roadmap.md:5969` `**Issues:** #193 (AD-612).`)

Wave 94 reconciles those four anchors. No `decisions-era-4-evolution.md` paragraph is added because the canonical decision record for AD-579a/b/c already lives in `DECISIONS.md:1201-1224` with `Status: Implemented` on each.

## Reframe rationale

There is genuinely nothing to defer because there is nothing to add — the entire umbrella is already shipped. Captain rule "don't defer unless no choice" satisfied vacuously. Wave 94 is structurally identical to **Wave 71** (#415 AD-644b deprecation, no-build close), **Wave 76** (#285 AD-644 SA architecture, no-build close), and **Wave 90** (#111 AD-462 biological memory umbrella close): clean tracker reconciliation flipping entries to reflect work that already shipped under earlier waves.

The original user-facing framing of "AD-579 v1 build" did not survive verify-first. AD-579a's CLOSED entry at `PROGRESS.md:383` records 12 focused tests, AD-579b's at `PROGRESS.md:385` records 10 focused tests, and AD-579c's at `PROGRESS.md:222` records 8 focused tests — 30 tests already in the baseline `12113`. Drafting a v1 build prompt would either duplicate work or invent new sub-AD letters (AD-579d/e/...) without a forcing function — neither is appropriate.

The original AD-579 entry's two future-looking notes ("Future ADs may wire Counselor/dream auto-pinning and event emission" on AD-579a; "No automatic validity inference, notebook validity, anchor-recall filtering, retroactive propagation" on AD-579b; "No LLM validity inference, validity UI/API, retroactive stored-episode propagation, or micro_dream changes" on AD-579c) intentionally leave those extensions open. They do **not** become Wave 94 deferrals — those are open-ended forward-looking carve-outs documented at sub-AD landing time, equivalent in shape to the Wave 73 AD-462f-1/b/c/d carry-forwards that Wave 90 explicitly chose **not** to convert into new GH issues. If any of those forward-looking carve-outs eventually warrant a real AD, it lands as a follow-on AD on its own merits, not via #37.

## Discipline reminders

- **No source code touched.** No `src/probos/`, no `tests/`. The full pytest gate is belt-and-braces only — expected delta is 0 (`12113` → `12113`).
- **No new GH issues.** Forward-looking carve-outs stay in the existing AD-579{a,b,c} bullet text. If a forcing function actually fires (e.g. dream auto-pinning becomes necessary for AD-606 conclusion persistence), a new AD lands on its own merits.
- **No new AD numbers minted.** Highest AD at HEAD remains `AD-696` (Wave 72; verified 2026-05-07 in W92 dispatch notes block). Wave 94 mints zero new AD numbers.
- **No edits to PROGRESS.md.** Recent waves (87/88/89/90/91/92/93) have stopped appending umbrella-close paragraphs there. Canonical closure surface is `roadmap.md` umbrella entry status flip plus the existing per-sub-AD `DECISIONS.md` records.
- **No edits to `decisions-era-4-evolution.md`.** AD-579 has no era-4 evolution-era essay — only forward references at `:3192` (`AD-582` prose mentioning "MemPalace evaluation (AD-579 context)") and `:3771` (`AD-598` "Connects to" list including `AD-579 (tiered loading)`). Both are correct as-is and survive verify-first.
- **No edits to `DECISIONS.md`.** The three sub-AD entries at `:1201`, `:1208`, `:1215` already carry `Status: Implemented`. Touching them would introduce churn for zero semantic delta.

## No commercial leak

AD-579 is purely OSS cognitive-architecture work: tiered context loading, pinned knowledge buffer, temporal validity windows on episodic metadata, validity-aware dream consolidation. Zero tier-noun / pricing-token / SaaS-overlay surface anywhere in the umbrella, in either the existing roadmap entry or in any of the three sub-AD bullets, or in this dispatch, or in the per-AD prompt, or in the wave-plan W94 notes block. Pre-commit hook 11 banned-pattern audit confirmed 0 literal hits across all three artefacts (this dispatch + per-AD prompt + wave-plan entry). Placeholder forms used throughout any audit prose: "the e-word + tier phrase", "the private commercial-repo path token", "the e-word overlay phrase", "the e-word-prefixed repo token", "monthly-price regex", "per-month abbreviation regex", "rev-proj phrase", "the recurring-revenue acronym", "outcome-style pricing phrase", "the GTM-pattern phrase", "the patterns-to-absorb phrase". The literal forms themselves never appear.

## Builder cycle

1. **Read** `prompts/ad-579-memory-architecture-umbrella-close.md`.
2. **Apply** the 3 SEARCH/REPLACE pairs grouped into 1 MODIFY block on `docs/development/roadmap.md`:
   - Build order line at `:4360` — flip `Deferred: AD-579a/b/c` to `Complete: AD-579a/b/c ✅` with closure breadcrumb.
   - Umbrella section header + entry status flip at `:5984-5986` — `*(planned, OSS)*` and `*(planned, OSS, depends: ...)*` both flip to `*(complete, OSS, ...)*`.
   - Issues anchor insertion after Absorption paragraph at `:6000` — append `**Issues:** #37.` line mirroring AD-612 convention at `:5969`.
3. **Append** the W94 entry to `prompts/wave-plan.yaml` at the end (after the existing W93 entry tail).
4. **Verify** `git diff --stat` shows exactly two modified trackers (`roadmap.md`, `wave-plan.yaml`) plus the two new prompt files (this dispatch + the per-AD prompt). Zero `src/probos/` or `tests/` paths.
5. **Pre-commit hook** runs naturally on commit (banned-pattern audit + deletion sanity).
6. **Full pytest gate** (`d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`) — belt-and-braces; expected `12113 passed`.
7. **Commit** with message `AD-579: Memory Architecture umbrella close — tracker reconciliation (no-build, +0 tests)`.
8. **Archive** prompts: `git mv prompts/WAVE-94-DISPATCH.md prompts/archive/WAVE-94-DISPATCH.md` and `git mv prompts/ad-579-memory-architecture-umbrella-close.md prompts/archive/ad-579-memory-architecture-umbrella-close.md`. Commit + push.
9. **Close GH #37** with the canonical comment in Section 4 of the per-AD prompt.

## Hard-stops (Builder must surface to architect, not improvise)

1. Any of the 3 SEARCH blocks fails to match (anchor drift since draft) → hard stop.
2. Pytest gate returns anything other than `12113` → hard stop. (Tracker-only changes cannot move the count; any delta means an unrelated regression entered between draft and build.)
3. Pre-commit hook flags a banned literal in any of: this dispatch, the per-AD prompt, the wave-plan W94 notes, or the modified `roadmap.md` regions → hard stop.
4. Builder elects to ship a fresh AD-579{d,e,f,g,...} sub-AD letter "while we're here" — even partially, even as a stub → hard stop. Out of scope. The forward-looking carve-outs in the existing AD-579{a,b,c} bullet text remain forward-looking.
5. Builder elects to mint a new GH issue for any of the AD-579 forward-looking carve-outs → hard stop. The umbrella close cites them; it does not re-track them.
6. Builder elects to add a `### AD-579` paragraph to `decisions-era-4-evolution.md` → hard stop. The canonical decision record lives at `DECISIONS.md:1201-1224` already.
7. Builder elects to flip the AD-579{a,b,c} sub-AD bullets at `roadmap.md:5996-5998` → hard stop. Those already read `*(complete, OSS, ...)*`; touching them is unnecessary churn.

## Verify-First (highest-risk anchors repeated)

Full table is in the per-AD prompt's "Verified Against Codebase" footer. Repeated here for Builder pre-flight:

```
git rev-parse HEAD
  4649e61

grep -n "Deferred: AD-579a/b/c" docs/development/roadmap.md
  4360: ... Independent: AD-566g (Qualification → Skill Bridge, needs AD-423), AD-566h/i/j. Deferred: AD-579a/b/c (tiered memory loading + temporal validity, MemPalace absorption).

grep -n "Memory Architecture: Tiered Loading & Temporal Validity (AD-579)" docs/development/roadmap.md
  5984: ### Memory Architecture: Tiered Loading & Temporal Validity (AD-579) *(planned, OSS)*

grep -n "AD-579: Memory Architecture — Tiered Context Loading" docs/development/roadmap.md
  5986: **AD-579: Memory Architecture — Tiered Context Loading & Temporal Knowledge Validity** *(planned, OSS, depends: AD-570 Anchor-Indexed Recall, AD-567a Anchor System, AD-541c Spaced Retrieval)* — Two complementary enhancements ...

grep -n "Issues:.*AD-612" docs/development/roadmap.md
  5969: **Issues:** #193 (AD-612).

grep -n "AD-579a: Pinned Knowledge Buffer" docs/development/roadmap.md
  5996: > - **AD-579a: Pinned Knowledge Buffer** *(complete, OSS)* — ...

grep -n "AD-579b: Temporal Validity Windows" docs/development/roadmap.md
  5997: > - **AD-579b: Temporal Validity Windows** *(complete, OSS)* — ...

grep -n "AD-579c: Validity-Aware Dream Consolidation" docs/development/roadmap.md
  5998: > - **AD-579c: Validity-Aware Dream Consolidation** *(complete, OSS, depends: AD-579b)* — ...

grep -n "AD-579a Pinned Knowledge Buffer CLOSED" PROGRESS.md
  383: AD-579a Pinned Knowledge Buffer CLOSED. ...

grep -n "AD-579b Temporal Validity Windows CLOSED" PROGRESS.md
  385: AD-579b Temporal Validity Windows CLOSED. ...

grep -n "AD-579c Validity-Aware Dream Consolidation — CLOSED" PROGRESS.md
  222: AD-579c Validity-Aware Dream Consolidation — CLOSED. ...

grep -n "### AD-579" DECISIONS.md
  1201: ### AD-579a: Pinned Knowledge Buffer
  1208: ### AD-579b: Temporal Validity Windows
  1215: ### AD-579c: Validity-Aware Dream Consolidation

grep -n "PinnedKnowledgeConfig" src/probos/config.py
  1372:     """AD-579a: Pinned knowledge buffer configuration."""
  2755:     pinned_knowledge: PinnedKnowledgeConfig = PinnedKnowledgeConfig()  # AD-579a

grep -n "TemporalValidityConfig" src/probos/config.py
  1381:     """AD-579b: Temporal validity windows for episodic memory."""
  2756:     temporal_validity: TemporalValidityConfig = TemporalValidityConfig()  # AD-579b
```
