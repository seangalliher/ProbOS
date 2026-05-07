# WAVE 90 DISPATCH — AD-462 Biological Memory Model: Umbrella Close (single AD, no-build)

**HEAD at draft:** `89d4fa7` (Wave 89 archive: AD-480 federation MCP + A2A)
**Baseline pytest:** 11916 → target 11916 (Δ = 0; tracker-only, zero source/test changes)
**Single AD:** AD-462 umbrella close (full closure of GH #111 — all six sub-ADs already shipped before Wave 90)
**Builder required:** Yes (6 SEARCH/REPLACE pairs across 3 MODIFY blocks — 2 in `docs/development/roadmap.md`, 3 in `decisions-era-4-evolution.md`, 1 in `prompts/wave-plan.yaml`; no code, no tests)

## Why this wave is one AD and no build

GH #111 names AD-462 as the "Biological Memory Model" umbrella decomposed into six pillars in `docs/development/roadmap.md:4168-4177`. Verify-first against HEAD `89d4fa7` finds **all six pillars shipped before Wave 90**:

| Pillar | Status at HEAD | Vehicle |
|---|---|---|
| 1. Biological memory staging | shipped (conceptual frame, no separate sub-AD) | `recent_for_agent` (`episodic.py:1815`) + ChromaDB short-term store + `ProcedureStore` (AD-533) + `RecordsStore` (AD-551) consolidated by `DreamingEngine` (`dreaming.py:72, 78, 105, 114`) |
| 2. Active Forgetting (AD-462b) | shipped | Absorbed by AD-567d — `ActivationTracker` (`activation_tracker.py:1`), dream Step 12 pruning (`dreaming.py:308, 1395`) |
| 3. Variable Recall Capability (AD-462c) | shipped | `RecallTier` enum (`earned_agency.py:54-58`), `resolve_recall_tier_params` (`episodic.py:635`), `MemoryConfig` recall tier params (`config.py:661`) |
| 4. Social Memory (AD-462d) | shipped | `SocialMemoryService` (`social_memory.py:1, 35`); also absorbed by AD-567f (`social_verification.py:4, 264`) |
| 5. Oracle Service (AD-462e) | shipped | `OracleService` (`oracle_service.py:1, 154`), startup wiring (`startup/cognitive_services.py:491-504`), runtime attach (`runtime.py:1391`) |
| 6. Optimized Memory Representation (AD-462f) | shipped | Wave 73 commit `f5bd612` — `MemoryRef` (`types.py:412-431`), `query_refs`/`resolve_ref`/`format_refs` (`oracle_service.py:434-514`), `MEMORY_REFS_DISPATCHED` EventType (`events.py:238`), `oracle_refs` QUERY op (`cognitive/sub_tasks/query.py:312-432`), 16 tests |
| AD-462a Salience-Weighted Episodic Recall | shipped (cross-listed for completeness) | Absorbed by AD-567b (`docs/development/roadmap.md:4322, 4340`) |

**The defect this wave closes:** Wave 73's Builder commit (`f5bd612`) shipped AD-462f code but skipped the tracker updates required by `prompts/archive/WAVE-73-DISPATCH.md:62-64` ("Final Tracker Updates"). At HEAD `89d4fa7`:

- `docs/development/roadmap.md:4168` still reads `**AD-462: Memory Architecture — Biological Memory Model** *(planned)*`
- `docs/development/roadmap.md:4177` still reads `**AD-462f: Optimized Memory Representation** *(planned)*`
- `decisions-era-4-evolution.md:2690` still reads `... AD-462f (concept graphs) deferred — AnchorFrame ... sufficient for now.`
- `decisions-era-4-evolution.md:2699` still reads `| AD-462f | DEFERRED — concept graphs, AnchorFrame sufficient for now |`

Wave 90 reconciles those four anchors and appends a new `### AD-462f` closure paragraph between the existing AD-462c/d/e cluster (`:2684-2699`) and the AD-570b heading (`:2701`).

## Reframe rationale

There is genuinely nothing to defer because there is nothing to add — the entire umbrella is already shipped. Captain rule "don't defer unless no choice" satisfied vacuously. Wave 90 is structurally identical to **Wave 71** (#415 AD-644b deprecation, no-build close) and **Wave 76** (#285 AD-644 SA architecture, no-build close): clean tracker reconciliation flipping entries to reflect work that already shipped under earlier ADs.

The four AD-462f carry-forward children (AD-462f-1 ToolRegistry, AD-462f-b ANALYZE intent + chain seam, AD-462f-c cross-conversation persistence, AD-462f-d per-tier metadata contracts) are **W73 deferrals, NOT W90 deferrals.** Their forcing functions live in `prompts/archive/WAVE-73-DISPATCH.md` lines 31, 49, 64, 90. The umbrella close cites them so #111 readers can trace the story; W90 mints **zero** new GH issues.

## Discipline reminders

- **No source code touched.** No `src/probos/`, no `tests/`. The full pytest gate is belt-and-braces only — expected delta is 0 (11916 → 11916).
- **No new GH issues.** Carry-forward children stay attached to W73's archive. If a W73 forcing function actually fires (e.g. `init_communication()` gets a runtime kwarg), AD-462f-1 lands as a follow-on AD on its own, not via #111.
- **No edits to the conceptual essay** at `roadmap.md:850-880`. That section is timeless framing of the Unified Cognitive Bottleneck principle; the status flip lives at the catalogue entry (`:4168`) and sub-AD bullet (`:4177`).
- **No edits to PROGRESS.md** — recent waves (87/88/89) have stopped appending umbrella-close paragraphs there. Canonical closure surface is `decisions-era-4-evolution.md`.

## No commercial leak

AD-462 is purely OSS cognitive architecture: 10-bit bottleneck principle, biological memory staging, ACT-R activation model, ward-room social memory, oracle cross-tier query, retrieval-as-pointers projection. Zero tier/pricing/SaaS surface anywhere in the umbrella, in either the existing roadmap entry or the new closure paragraph. Pre-commit hook 11 banned-pattern audit confirmed 0 literal hits across this dispatch + the per-AD prompt + the wave-plan W90 notes block (Wave 87/88/89 placeholder convention applied — descriptor-only forms such as "tier-noun phrase", "private commercial-repo path token", "monthly-price regex" used in any audit prose, never the literal forms themselves).

## Builder cycle

1. **Read** `prompts/ad-462-biological-memory-umbrella-close.md`.
2. **Apply** the 6 SEARCH/REPLACE pairs grouped into 3 MODIFY blocks:
   - 2 pairs in `docs/development/roadmap.md` (umbrella status flip + AD-462f sub-AD bullet flip).
   - 3 pairs in `decisions-era-4-evolution.md` (one MODIFY block, sequential pairs: prose reference at line 2690, table row at line 2699, new `### AD-462f` paragraph attached to the table close).
   - 1 pair in `prompts/wave-plan.yaml` (append W90 entry to W89 tail at line 1740).
3. **Verify** `git diff --stat` shows exactly three modified trackers + the two new prompt files (this dispatch + the per-AD prompt). Zero `src/probos/` or `tests/` paths.
4. **Pre-commit hook** runs naturally on commit (banned-pattern audit + deletion sanity).
5. **Full pytest gate** (`d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`) — belt-and-braces; expected `11916 passed`.
6. **Commit** with message `AD-462: Biological Memory umbrella close — tracker reconciliation (no-build, +0 tests)`.
7. **Archive** prompts: `git mv prompts/WAVE-90-DISPATCH.md prompts/archive/WAVE-90-DISPATCH.md` and `git mv prompts/ad-462-biological-memory-umbrella-close.md prompts/archive/ad-462-biological-memory-umbrella-close.md`.
8. **Close GH #111** with the verbatim comment in Section 4 of the per-AD prompt.

## Hard-stops (Builder must surface to architect, not improvise)

1. Any of the 5 SEARCH blocks fails to match (anchor drift since draft) → hard stop.
2. Pytest gate returns anything other than 11916 → hard stop. (Tracker-only changes cannot move the count; any delta means an unrelated regression entered between draft and build.)
3. Pre-commit hook flags a banned literal in any of: this dispatch, the per-AD prompt, the wave-plan W90 notes, or the new `### AD-462f` paragraph → hard stop.
4. Builder elects to ship AD-462f-1, AD-462f-b, AD-462f-c, or AD-462f-d "while we're here" — even partially, even as a stub → hard stop. Out of scope. Their forcing functions remain in the W73 archive.
5. Builder elects to mint a new GH issue for any carry-forward child → hard stop. The umbrella close cites them; it does not re-track them.

## Verify-First (highest-risk anchors repeated)

Full table is in the per-AD prompt's "Verified Against Codebase" footer. Repeated here for Builder pre-flight:

```
git rev-parse HEAD
  89d4fa7

grep -n "AD-462: Memory Architecture" docs/development/roadmap.md
  4168: **AD-462: Memory Architecture — Biological Memory Model** *(planned)* ...

grep -n "AD-462f: Optimized" docs/development/roadmap.md
  4177: > - **AD-462f: Optimized Memory Representation** *(planned)* — Structured metadata, concept graphs, retrieval-as-pointers.

grep -n "AD-462f" decisions-era-4-evolution.md
  2690: ... AD-462f (concept graphs) deferred ...
  2699: | AD-462f | DEFERRED — concept graphs, AnchorFrame sufficient for now |

wc -l prompts/wave-plan.yaml
  1740
```

## Per-AD prompt

`prompts/ad-462-biological-memory-umbrella-close.md`
