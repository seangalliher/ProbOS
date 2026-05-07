# AD-462 Biological Memory Model — Umbrella Close (no-build, tracker reconciliation)

**Status:** Ready for Builder
**Dependencies:** Wave 73 (AD-462f shipped 2026-05-05; tracker updates were never committed)
**Estimated tests:** **0** (no source/test changes — tracker-only close, zero pytest delta)
**Issue closed:** GH #111
**Baseline pytest:** 11916 → target 11916 (Δ = 0)

## Problem

GH #111 ("AD-462: Biological Memory Model (Umbrella)") tracks a 6-pillar memory architecture umbrella (`docs/development/roadmap.md:4168`). All six sub-ADs are shipped at HEAD `89d4fa7`:

| Sub-AD | Pillar | Status at HEAD | Vehicle |
|---|---|---|---|
| AD-462a | Salience-Weighted Episodic Recall | shipped | Absorbed by AD-567b (`docs/development/roadmap.md:4172, 4322`) |
| AD-462b | Active Forgetting (ACT-R) | shipped | Absorbed by AD-567d — `src/probos/cognitive/activation_tracker.py:1`, `dreaming.py:308, 1395` |
| AD-462c | Variable Recall Tiers | shipped | `src/probos/earned_agency.py:54-58`, `episodic.py:635`, `config.py:661` |
| AD-462d | Social Memory | shipped | `src/probos/cognitive/social_memory.py:1, 35`; also absorbed by AD-567f (`social_verification.py:4, 264`) |
| AD-462e | Oracle Service | shipped | `src/probos/cognitive/oracle_service.py:1, 154`; `startup/cognitive_services.py:491-504`; `runtime.py:1391` |
| AD-462f | Optimized Memory Representation | shipped | Wave 73 (commit `f5bd612`) — `MemoryRef` (`types.py:412-431`), `OracleService.query_refs` (`oracle_service.py:434-446`), `resolve_ref` (`:491`), `format_refs` (`:511`), `MEMORY_REFS_DISPATCHED` EventType (`events.py:238`), `oracle_refs` QUERY op (`cognitive/sub_tasks/query.py:312-432`) |

**Pillar 1 (Biological memory staging)** is the conceptual frame for the other five pillars and is realised across:
- working memory: `cognitive/cognitive_agent.py` LLM context assembly
- sensory buffer: `EpisodicMemory.recent_for_agent()` (`episodic.py:1815`)
- short-term: ChromaDB via `EpisodicMemory.store()`
- long-term: `ProcedureStore` (AD-533) and `RecordsStore` (AD-551) consolidated by `DreamingEngine` (`dreaming.py:72, 78, 105, 114`)

There is no separate sub-AD for pillar 1 — the umbrella explicitly framed it as the staging concept that the other five pillars implement.

**The defect this AD closes:** Wave 73's Builder commit (`f5bd612`) shipped AD-462f code (`src/probos/`, `tests/`) but **skipped the tracker updates** required by the W73 dispatch:

```
grep -n "AD-462f" docs/development/roadmap.md
  4177: > - **AD-462f: Optimized Memory Representation** *(planned)* — Structured metadata, concept graphs, retrieval-as-pointers.

grep -n "AD-462f" decisions-era-4-evolution.md
  2690: AD-462f (concept graphs) deferred — AnchorFrame (AD-567a) covers near-term structured metadata needs.
  2699: | AD-462f | DEFERRED — concept graphs, AnchorFrame sufficient for now |

grep -n "AD-462" PROGRESS.md
  100: Wave 5-8 architect decisions 2026-04-30: ...      (no AD-462f closure entry)
  365: BF-203 CLOSED ...                                   (no AD-462f closure entry)
```

These three trackers still describe AD-462f as `planned` / `DEFERRED` even though the code shipped a wave ago, and the AD-462 umbrella main entry at `roadmap.md:4168` still reads `*(planned)*` despite all six pillars being live.

## Solution

**No code, no tests.** Single tracker reconciliation pass:

1. Flip `roadmap.md` AD-462 umbrella status from `*(planned)*` → `*(complete via AD-462a–f)*` and refresh the AD-462f sub-AD bullet from `*(planned)*` → `*(COMPLETE)*` with a one-line summary of the W73 ship. (2 pairs in one MODIFY block.)
2. In one MODIFY block on `decisions-era-4-evolution.md`, apply three sequential SEARCH/REPLACE pairs: (a) update the obsolete prose at line 2690 (the trailing "AD-462f (concept graphs) deferred — AnchorFrame ... sufficient for now" sentence) so future readers don't see contradictory status; (b) flip the obsolete table row at line 2699 (`| AD-462f | DEFERRED ... |`) to the W73 closure shape; (c) attach a new `### AD-462f` closure paragraph between that table close and the existing `### AD-570b` heading at line 2701, documenting the W73 ship (date, commit, surfaces, four W73-tracked carry-forward children with their forcing functions).
3. Append a Wave 90 entry to `prompts/wave-plan.yaml` (1 pair attaching to the W89 tail).

Total: 6 SEARCH/REPLACE pairs across 3 MODIFY blocks.

Carry-forward children **AD-462f-1 / AD-462f-b / AD-462f-c / AD-462f-d** are NOT new W90 deferrals — they are W73's deferrals (see `prompts/archive/WAVE-73-DISPATCH.md:31, 49, 64, 90`). The umbrella close cites them so #111 readers can trace the story; it does NOT mint new GH issues for them or change their forcing functions.

### Section 1 — Update `docs/development/roadmap.md`

Two SEARCH/REPLACE pairs in one MODIFY block. Anchors verified at HEAD `89d4fa7` (line numbers from `read_file` 4168-4180).

```
===MODIFY: docs/development/roadmap.md===
===SEARCH===
**AD-462: Memory Architecture — Biological Memory Model** *(planned)* — Apply the 10-bit bottleneck principle to memory: (1) **Biological memory staging** — working memory (LLM context) → sensory buffer (`recent_for_agent()`) → short-term (ChromaDB) → long-term (KnowledgeStore via dream consolidation). (2) **Active Forgetting** — unreinforced memories degrade, low-activation episodes pruned during dreaming (ACT-R activation model). (3) **Variable Recall Capability** — Basic (vector only) / Enhanced (vector+keyword, trust 0.7+) / Full (LLM-augmented, Chiefs+Bridge). (4) **Social Memory** — "Does anyone remember?" queries via Ward Room. (5) **Oracle Service** — Ship's Computer memory retrieval across all three knowledge tiers. (6) **Optimized Memory Representation** — structured metadata, concept graphs, retrieval-as-pointers. *Connects to: EpisodicMemory, KnowledgeStore, AD-434 (Ship's Records), Dream consolidation, Ward Room, Earned Agency.*
===REPLACE===
**AD-462: Memory Architecture — Biological Memory Model** *(complete via AD-462a–f, Wave 90 close)* — Applied the 10-bit bottleneck principle to memory across six pillars: (1) **Biological memory staging** — working memory (LLM context) → sensory buffer (`EpisodicMemory.recent_for_agent()`, `episodic.py:1815`) → short-term (ChromaDB via `EpisodicMemory.store()`) → long-term (`ProcedureStore` AD-533 + `RecordsStore` AD-551) consolidated by `DreamingEngine`. (2) **Active Forgetting** — `ActivationTracker` ACT-R model, dream Step 12 pruning (AD-462b absorbed by AD-567d). (3) **Variable Recall Capability** — `RecallTier` enum BASIC/ENHANCED/FULL/ORACLE parallels `AgencyLevel` (AD-462c). (4) **Social Memory** — "Does anyone remember?" Ward Room queries via `SocialMemoryService` (AD-462d, also absorbed by AD-567f). (5) **Oracle Service** — `OracleService` cross-tier unified memory query (AD-462e). (6) **Optimized Memory Representation** — `MemoryRef` retrieval-as-pointers projection (AD-462f, Wave 73). *Connects to: EpisodicMemory, KnowledgeStore, AD-434 (Ship's Records), Dream consolidation, Ward Room, Earned Agency.*
===END REPLACE===
===SEARCH===
> - **AD-462f: Optimized Memory Representation** *(planned)* — Structured metadata, concept graphs, retrieval-as-pointers.
===REPLACE===
> - **AD-462f: Optimized Memory Representation** *(COMPLETE — Wave 73, 2026-05-05)* — Pillar 3 (retrieval-as-pointers) shipped: `MemoryRef` lightweight projection (`types.py:412-431`), `OracleService.query_refs()` / `resolve_ref()` / `format_refs()` (`oracle_service.py:434-514`), `MEMORY_REFS_DISPATCHED` EventType (`events.py:238`), `oracle_refs` QUERY op gated to ENHANCED+ recall tier (`cognitive/sub_tasks/query.py:312-432`), 16 focused tests (`test_ad462f_memory_refs.py`). Pillars 1+2 (structured metadata, concept graphs) covered by AD-567a (`AnchorFrame`) and AD-688/692 (`KnowledgeEdge` graph) per W73 dispatch §1. Four sub-children remain tracked under W73 forcing functions, NOT new deferrals: AD-462f-1 (`ToolRegistry` registration of `oracle_refs` — gated on `init_communication()` runtime kwarg, same root cause as AD-696-1), AD-462f-b (ANALYZE intent signal + chain dispatch seam — gated on chain seam landing), AD-462f-c (cross-conversation ref persistence), AD-462f-d (per-tier metadata contracts).
===END REPLACE===
===END MODIFY===
```

### Section 2 — Update `decisions-era-4-evolution.md`

**Single MODIFY block with three sequential SEARCH/REPLACE pairs** — applied in order: (1) flip prose reference at line 2690, (2) flip table row at line 2699, (3) attach new `### AD-462f` closure paragraph between the table close and the next `### AD-570b` heading at line 2701. The third pair's SEARCH includes the table row as written by pair (2), so the pairs MUST execute in the order given within a single MODIFY block.

```
===MODIFY: decisions-era-4-evolution.md===
===SEARCH===
**Decision:** Three final Memory Architecture sub-ADs delivered together. (1) **AD-462c Variable Recall Tiers** — `RecallTier` enum (`BASIC`/`ENHANCED`/`FULL`/`ORACLE`) parallels `AgencyLevel` (Ensign=BASIC, Lieutenant=ENHANCED, Commander=FULL, Senior=ORACLE). `resolve_recall_tier_params()` DRY helper centralizes tier→parameter mapping (k, context_budget, anchor_confidence_gate, cross_agent_access). Wired into both `_recall_relevant_memories()` and `_gather_context()` in cognitive_agent.py. (2) **AD-462d Social Memory** — `SocialMemoryService` implements "does anyone remember?" protocol via Ward Room `thread_mode="memory_query"`. Agents detect memory queries in proactive cycle and respond from their sovereign episodic shard. Protocol-based, not infrastructure — uses existing Ward Room + recall pipeline. (3) **AD-462e Oracle Service** — `OracleService` aggregates all 3 knowledge tiers (EpisodicMemory vector search, RecordsStore keyword search, KnowledgeStore filesystem search) with normalized scoring and source provenance tags. Trust-gated: only ORACLE tier (Senior officers) gets Oracle access. Ward Room wiring done in runtime.py (not cognitive_services.py) due to startup phase ordering — Ward Room initializes in finalize.py (Phase 7), cognitive services initialize in Phase 5. AD-462f (concept graphs) deferred — AnchorFrame (AD-567a) covers near-term structured metadata needs.
===REPLACE===
**Decision:** Three final Memory Architecture sub-ADs delivered together. (1) **AD-462c Variable Recall Tiers** — `RecallTier` enum (`BASIC`/`ENHANCED`/`FULL`/`ORACLE`) parallels `AgencyLevel` (Ensign=BASIC, Lieutenant=ENHANCED, Commander=FULL, Senior=ORACLE). `resolve_recall_tier_params()` DRY helper centralizes tier→parameter mapping (k, context_budget, anchor_confidence_gate, cross_agent_access). Wired into both `_recall_relevant_memories()` and `_gather_context()` in cognitive_agent.py. (2) **AD-462d Social Memory** — `SocialMemoryService` implements "does anyone remember?" protocol via Ward Room `thread_mode="memory_query"`. Agents detect memory queries in proactive cycle and respond from their sovereign episodic shard. Protocol-based, not infrastructure — uses existing Ward Room + recall pipeline. (3) **AD-462e Oracle Service** — `OracleService` aggregates all 3 knowledge tiers (EpisodicMemory vector search, RecordsStore keyword search, KnowledgeStore filesystem search) with normalized scoring and source provenance tags. Trust-gated: only ORACLE tier (Senior officers) gets Oracle access. Ward Room wiring done in runtime.py (not cognitive_services.py) due to startup phase ordering — Ward Room initializes in finalize.py (Phase 7), cognitive services initialize in Phase 5. AD-462f (retrieval-as-pointers) shipped subsequently in Wave 73 — see the AD-462f closure paragraph below.
===END REPLACE===
===SEARCH===
| AD-462f | DEFERRED — concept graphs, AnchorFrame sufficient for now |
===REPLACE===
| AD-462f | COMPLETE (Wave 73, 2026-05-05) — `MemoryRef` retrieval-as-pointers projection over OracleService; pillars 1+2 covered by AnchorFrame (AD-567a) + KnowledgeEdge graph (AD-688/692) |
===END REPLACE===
===SEARCH===
| AD-462f | COMPLETE (Wave 73, 2026-05-05) — `MemoryRef` retrieval-as-pointers projection over OracleService; pillars 1+2 covered by AnchorFrame (AD-567a) + KnowledgeEdge graph (AD-688/692) |

### AD-570b: Episode Participant Index
===REPLACE===
| AD-462f | COMPLETE (Wave 73, 2026-05-05) — `MemoryRef` retrieval-as-pointers projection over OracleService; pillars 1+2 covered by AnchorFrame (AD-567a) + KnowledgeEdge graph (AD-688/692) |

### AD-462f: Optimized Memory Representation — Retrieval-as-Pointers (Wave 73 closure)

**Date:** 2026-05-05 (W73 build commit `f5bd612`); tracker reconciliation 2026-05-06 (Wave 90).
**Status:** Complete. Closes the AD-462 umbrella (GH #111) together with the previously-shipped AD-462a (absorbed by AD-567b), AD-462b (absorbed by AD-567d), and AD-462c/d/e cluster above.
**Scope:** Small | **Type:** Cognitive Architecture

**Decision:** Pillar 3 of AD-462 ("Optimized Memory Representation") shipped as a stateless lightweight projection over `OracleService` results rather than a new index or storage tier. `MemoryRef` is a frozen dataclass (`types.py:412-431`) carrying `ref_id = f"{tier}:{stable_key}"` with `metadata` excluded from hash/eq (DLog #12 — projections must be stable across re-queries). `OracleService.query_refs()` (`oracle_service.py:436`) returns `list[MemoryRef]` from the same per-tier search the existing `query()` and `query_formatted()` paths use; `resolve_ref()` (`:491`) re-hydrates a `MemoryRef` to its full `OracleResult` via an instance-scoped LRU bounded by inline caps (DLog #10 — caps NOT in config); `format_refs()` (`:511`) renders a prompt-ready block with line/char limits. `oracle_refs` QUERY op (`cognitive/sub_tasks/query.py:312-432`) is gated to RecallTier.ENHANCED+ and emits `MEMORY_REFS_DISPATCHED` (`events.py:238`) for telemetry. Pillars 1 + 2 (structured metadata, concept graphs) were re-mapped against HEAD before W73 build: pillar 1 covered by `AnchorFrame` (AD-567a) + AD-541/598/579b; pillar 2 covered by `KnowledgeEdge` graph (AD-688/692). 16 focused tests at `tests/test_ad462f_memory_refs.py`. Existing `query()` / `query_formatted()` contracts preserved byte-for-byte (DLog #1 — refs are an opt-in projection); AD-696's `oracle_lookup` QUERY op continues using `query_formatted` unchanged.

**Carry-forward children (W73 forcing functions, NOT W90 deferrals):**

| Child | Forcing function (per `prompts/archive/WAVE-73-DISPATCH.md`) |
|---|---|
| AD-462f-1 — `ToolRegistry` registration of `oracle_refs` | Same root cause as AD-696-1 — gated on `init_communication()` startup signature gaining a `runtime` parameter. |
| AD-462f-b — ANALYZE intent signal + chain dispatch seam | Gated on a chain dispatch seam between triage and execute phases existing for non-trivial chains; skill agents and slash commands already call `runtime.oracle.query_refs(...)` directly. |
| AD-462f-c — Cross-conversation `ref_id` persistence | Gated on a use case for re-resolving refs across runtime restarts; v1 LRU is per-instance. |
| AD-462f-d — Per-tier `MemoryRef.metadata` contract documentation | Gated on a second consumer surface beyond the chain — the contract is currently single-consumer (the formatter). |

**Architect calls:**

| AD | Decision |
|----|----------|
| AD-462f umbrella close | Wave 73 Builder skipped tracker updates (`docs/development/roadmap.md`, `decisions-era-4-evolution.md`, `PROGRESS.md` per W73 dispatch §"Final Tracker Updates"). Wave 90 reconciles by flipping the umbrella + sub-AD entries and appending this closure paragraph. No code, no tests, zero pytest delta. |
| Carry-forward children | NOT minted as W90 deferrals — they remain attached to the W73 archive. Citing them in the umbrella close gives #111 readers a single trace point; the forcing functions live in `prompts/archive/WAVE-73-DISPATCH.md` lines 31, 49, 64, 90. |

### AD-570b: Episode Participant Index
===END REPLACE===
===END MODIFY===
```

### Section 3 — Append `prompts/wave-plan.yaml`

Append at the end of file (current tail line `~6).` at line 1740). Use this SEARCH/REPLACE attaching to the W89 entry's tail:

```
===MODIFY: prompts/wave-plan.yaml===
===SEARCH===
      TestProbationaryTrustWiring ~6, TestFederationRouterPolymorphism
      ~6, TestFederationConfigSchema ~4, TestSlashFederationPeersCommand
      ~6, TestStartupWiring ~6).
===REPLACE===
      TestProbationaryTrustWiring ~6, TestFederationRouterPolymorphism
      ~6, TestFederationConfigSchema ~4, TestSlashFederationPeersCommand
      ~6, TestStartupWiring ~6).
  - id: "90"
    title: "AD-462 Biological Memory Model — Umbrella Close (no-build, tracker reconciliation)"
    kind: single
    depends_on: ["89"]
    dispatch_prompt: "prompts/WAVE-90-DISPATCH.md"
    prompts_already_drafted: true
    prompt_paths:
      - "prompts/ad-462-biological-memory-umbrella-close.md"
    builder_required: true
    issues_to_close: [111]
    status: pending
    notes: |
      No-build close of GH #111 (AD-462 umbrella). All six sub-ADs
      shipped at HEAD 89d4fa7: AD-462a absorbed by AD-567b
      (salience-weighted recall), AD-462b absorbed by AD-567d
      (ActivationTracker), AD-462c (RecallTier enum), AD-462d
      (SocialMemoryService — also absorbed by AD-567f), AD-462e
      (OracleService cross-tier unified query), AD-462f (MemoryRef
      retrieval-as-pointers, Wave 73 commit f5bd612). Pillar 1
      biological memory staging is the conceptual frame realised across
      EpisodicMemory.recent_for_agent (sensory buffer at episodic.py:
      1815), ChromaDB store (short-term), and ProcedureStore + Records
      Store consolidated by DreamingEngine (long-term, dreaming.py:72,
      78, 105, 114) — no separate sub-AD. Wave 73 Builder shipped AD-
      462f code but skipped the tracker updates required by the W73
      dispatch — at HEAD roadmap.md:4168 still says AD-462 *(planned)*,
      roadmap.md:4177 still says AD-462f *(planned)*, decisions-era-4-
      evolution.md:2699 still says "AD-462f DEFERRED", decisions-era-4-
      evolution.md:2690 still says "AD-462f (concept graphs) deferred".
      Wave 90 reconciles by flipping the umbrella status to *(complete
      via AD-462a-f)*, refreshing the AD-462f sub-AD bullet to
      *(COMPLETE — Wave 73, 2026-05-05)* with a one-line summary,
      flipping the era-4 table row at :2699, updating the era-4 prose
      at :2690, and appending a new ### AD-462f closure paragraph
      between the existing AD-462c/d/e cluster and the AD-570b heading
      at :2701. Carry-forward children AD-462f-1 (ToolRegistry
      registration), AD-462f-b (ANALYZE intent signal + chain dispatch
      seam), AD-462f-c (cross-conversation ref persistence), AD-462f-d
      (per-tier metadata contracts) are W73 deferrals NOT W90 deferrals
      — their forcing functions live in prompts/archive/WAVE-73-
      DISPATCH.md lines 31, 49, 64, 90. The umbrella close cites them
      so #111 readers can trace the story; W90 mints zero new GH
      issues. No code touched, no tests added, no pytest delta (target
      11916 -> 11916). No commercial leak — AD-462 is purely OSS
      cognitive architecture (10-bit bottleneck principle, biological
      memory staging, ACT-R activation model, ward-room social memory,
      oracle cross-tier query, retrieval-as-pointers projection); zero
      tier/pricing/SaaS surface anywhere in the umbrella. Pre-commit-
      hook 11 banned-pattern audit on dispatch + prompt + this notes
      block: 0 literal hits across all forms (Wave 87/88/89 placeholder
      convention applied — audit prose uses descriptor-only language,
      e.g. "tier-noun phrase" / "private commercial-repo path token" /
      "monthly-price regex" without invoking the literal forms).
      Reframe rationale: there is genuinely nothing to defer because
      there is nothing to add — the entire umbrella is already
      shipped. Captain rule "don't defer unless no choice" satisfied
      vacuously. Wave 90 is structurally identical to Wave 71 (#415
      AD-644b) and Wave 76 (#285 AD-644 SA architecture) — both clean
      no-build closes flipping tracker entries to reflect work that
      already shipped under earlier ADs. Builder cycle: read prompt,
      apply 6 SEARCH/REPLACE pairs grouped into 3 MODIFY blocks (2
      pairs in roadmap.md, 3 sequential pairs in decisions-era-4-
      evolution.md, 1 pair in wave-plan.yaml — the wave-plan one is
      this entry attached to the W89 tail), no test runs needed since
      no source touched, full gate as belt-and-braces should pass at
      11916 unchanged, gh issue close 111 with the canonical paragraph
      provided in Section 4 of the per-AD prompt.
===END REPLACE===
===END MODIFY===
```

### Section 4 — GH #111 close comment (Builder pastes verbatim)

```
Closed by Wave 90 (AD-462 umbrella tracker reconciliation, no-build, +0 tests).

All six sub-ADs shipped before W90:
- AD-462a: Salience-Weighted Episodic Recall — absorbed by AD-567b (RecallScore composite, FTS5 keyword sidecar, recall_weighted, dynamic query derivation, context budget enforcement)
- AD-462b: Active Forgetting — absorbed by AD-567d (ActivationTracker ACT-R model, dream Step 12 pruning, micro-dream replay reinforcement)
- AD-462c: Variable Recall Tiers — RecallTier enum BASIC/ENHANCED/FULL/ORACLE parallels AgencyLevel; resolve_recall_tier_params DRY helper
- AD-462d: Social Memory — SocialMemoryService Ward Room "does anyone remember?" protocol; also absorbed by AD-567f for cross-agent claim verification
- AD-462e: Oracle Service — cross-tier unified memory query across EpisodicMemory + RecordsStore + KnowledgeStore with normalized scoring; trust-gated to ORACLE tier
- AD-462f: Optimized Memory Representation — Wave 73 (commit f5bd612): MemoryRef retrieval-as-pointers projection, OracleService.query_refs / resolve_ref / format_refs, MEMORY_REFS_DISPATCHED EventType, oracle_refs QUERY op gated to ENHANCED+; pillars 1+2 (structured metadata, concept graphs) covered by AnchorFrame (AD-567a) + KnowledgeEdge graph (AD-688/692)

Pillar 1 (biological memory staging) is the conceptual frame for the other five pillars — realised across EpisodicMemory.recent_for_agent (sensory buffer), ChromaDB (short-term), ProcedureStore + RecordsStore consolidated by DreamingEngine (long-term). No separate sub-AD.

Wave 90 reconciled three trackers that were not updated when AD-462f shipped in Wave 73:
- docs/development/roadmap.md AD-462 umbrella entry flipped from *(planned)* to *(complete via AD-462a–f)*
- docs/development/roadmap.md AD-462f sub-AD bullet flipped from *(planned)* to *(COMPLETE — Wave 73, 2026-05-05)*
- decisions-era-4-evolution.md AD-462c/d/e cluster table row at :2699 flipped from "DEFERRED" to "COMPLETE (Wave 73)" + new ### AD-462f closure paragraph appended

Four AD-462f carry-forward children remain tracked under their original W73 forcing functions (NOT new W90 deferrals): AD-462f-1 (ToolRegistry registration — gated on init_communication() runtime kwarg), AD-462f-b (ANALYZE intent + chain dispatch seam), AD-462f-c (cross-conversation ref persistence), AD-462f-d (per-tier metadata contracts). See prompts/archive/WAVE-73-DISPATCH.md lines 31, 49, 64, 90.

Pytest delta: 0 (11916 → 11916, no source/test changes). Closes GH #111.
```

## What This AD Does NOT Change

- No source code under `src/probos/` is touched.
- No tests are added or modified.
- No new GH issues minted for the four AD-462f carry-forward children — they remain attached to the W73 archive's forcing functions.
- No new EventType, no Pydantic config field, no slash command, no API route, no HXI surface.
- `PROGRESS.md` is left untouched — recent waves have stopped appending umbrella-close paragraphs there (last AD-462 mention is line 100 from Wave 5-8 architect notes; the canonical closure surface is `decisions-era-4-evolution.md`).
- No edits to `docs/development/roadmap.md:850-880` (the conceptual essay framing AD-462's biological memory model). The status flip lives at the catalogue entry at `:4168` and the sub-AD bullet at `:4177`; the essay is timeless framing.

## Acceptance Criteria

1. Six SEARCH/REPLACE pairs apply cleanly across 3 MODIFY blocks (2 pairs in `roadmap.md`, 3 sequential pairs in `decisions-era-4-evolution.md`, 1 pair in `prompts/wave-plan.yaml` attaching W90 to the W89 tail).
2. `git diff --stat` shows three files modified plus the two new prompt files (this prompt + the dispatch); zero `src/probos/` or `tests/` paths.
3. Full pytest gate (`d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`) passes at 11916 unchanged. Belt-and-braces only — no expected delta.
4. Pre-commit hook (11 banned-pattern audit) passes with zero literal hits across this prompt + the dispatch + the wave-plan notes block.
5. GH #111 closed with the verbatim comment from Section 4.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (HEAD `89d4fa7`, 2026-05-06)

```
git rev-parse HEAD
  89d4fa7 (Wave 89 archive: AD-480 federation MCP + A2A (#74))

gh issue view 111 --json title,state
  AD-462: Biological Memory Model (Umbrella) | OPEN

# AD-462a (absorbed by AD-567b)
grep -n "absorbs AD-462a" docs/development/roadmap.md
  4322: ... *(complete, OSS, depends: AD-567a, absorbs AD-462a)* ...
  4340: AD-567b (Recall + Scoring) ─── Absorbs AD-462a ✅

# AD-462b (absorbed by AD-567d)
grep -n "AD-462b" src/probos/cognitive/activation_tracker.py
  1: """AD-567d / AD-462b: ACT-R activation-based memory lifecycle tracker.
grep -n "AD-462b" src/probos/cognitive/dreaming.py
  308:  12. Activation-based memory pruning (AD-567d / AD-462b / AD-593)
  1395: # Step 12: Activation-Based Memory Pruning (AD-567d / AD-462b / AD-593)

# AD-462c (RecallTier)
grep -n "AD-462c" src/probos/earned_agency.py
  54:  """Memory recall capability tier — mapped from Earned Agency rank (AD-462c)."""
  58:  ORACLE = "oracle"          # All recall paths + Oracle Service (AD-462e)
grep -n "AD-462c" src/probos/cognitive/episodic.py
  635: """Resolve recall parameters for a given tier (AD-462c).
grep -n "AD-462c" src/probos/config.py
  661: # AD-462c: Variable Recall Tiers

# AD-462d (SocialMemoryService + AD-567f absorption)
grep -n "AD-462d" src/probos/cognitive/social_memory.py
  1: """Social Memory -- Cross-Agent Memory Query Protocol (AD-462d).
  35: """Cross-agent memory query protocol (AD-462d).
grep -n "AD-462d" src/probos/cognitive/social_verification.py
  4: Absorbs AD-462d (Social Memory) — provides cross-agent episodic query

# AD-462e (OracleService)
grep -n "AD-462e" src/probos/cognitive/oracle_service.py
  1: """Oracle Service -- Cross-Tier Unified Memory Query (AD-462e).
  154: """Cross-tier unified memory query service (AD-462e).
grep -n "AD-462e" src/probos/startup/cognitive_services.py
  491: # AD-462e: Oracle Service — cross-tier unified memory query
  504:    logger.info("AD-462e: OracleService initialized")
grep -n "AD-462e" src/probos/runtime.py
  1391: self._oracle_service = cog.oracle_service  # AD-462e

# AD-462f (Wave 73)
git log --oneline --grep="AD-462f"
  4d0242a Wave 73 archive: AD-462f memory refs (#58)
  f5bd612 AD-462f: Memory retrieval-as-pointers (+16 tests)
  9243d6e Wave 73 draft: AD-462f v1 memory retrieval-as-pointers
grep -n "AD-462f" src/probos/types.py
  412: """AD-462f: Lightweight projection of an OracleResult — retrieval-as-pointers.
  425: ref_id: str               # f"{tier}:{stable_key}" — see AD-462f DLog #3
  431: # AD-462f DLog #12: metadata is excluded from hash/eq so the dataclass
grep -n "AD-462f" src/probos/cognitive/oracle_service.py
  20: from probos.types import MemoryRef  # AD-462f
  434: # AD-462f: Retrieval-as-pointers — lightweight projection layer.
  445: """AD-462f: Query and return lightweight ``MemoryRef`` projections.
  491: """AD-462f: Re-hydrate a ``MemoryRef`` to its full ``OracleResult``.
  511: """AD-462f: Render ``MemoryRef`` list as a short prompt-ready block.
grep -n "MEMORY_REFS_DISPATCHED" src/probos/events.py
  238: MEMORY_REFS_DISPATCHED = "memory_refs_dispatched"  # AD-462f

# Pillar 1 (biological staging) — no separate sub-AD
grep -n "recent_for_agent" src/probos/cognitive/episodic.py
  1815: async def recent_for_agent(self, agent_id: str, k: int = 5) -> list[Episode]:
grep -n "procedure_store\|records_store" src/probos/cognitive/dreaming.py | head
  72:  procedure_store: Any = None,  # AD-533: persistent procedure storage
  78:  records_store: Any = None,  # AD-551: Ship's Records for notebook consolidation
  105: self._procedure_store = procedure_store  # AD-533: persistent procedure storage
  114: self._records_store = records_store  # AD-551: Ship's Records

# Stale tracker entries to flip
grep -n "AD-462" docs/development/roadmap.md | head
  4168: **AD-462: Memory Architecture — Biological Memory Model** *(planned)* ...
  4177: > - **AD-462f: Optimized Memory Representation** *(planned)* — Structured metadata, concept graphs, retrieval-as-pointers.
grep -n "AD-462f" decisions-era-4-evolution.md
  2690: ... AD-462f (concept graphs) deferred — AnchorFrame (AD-567a) covers near-term structured metadata needs.
  2699: | AD-462f | DEFERRED — concept graphs, AnchorFrame sufficient for now |

# Wave 73 dispatch carry-forward children
grep -n "AD-462f-1\|AD-462f-b\|AD-462f-c\|AD-462f-d" prompts/archive/WAVE-73-DISPATCH.md
  31, 49, 64, 90 (forcing functions documented)

# Wave-plan tail
wc -l prompts/wave-plan.yaml
  1740
grep -n 'id: "89"' prompts/wave-plan.yaml
  1605
```
