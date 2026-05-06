# WAVE 73 DISPATCH — AD-462f v1 Memory Architecture: Optimized Memory Representation (single AD)

**Wave id:** 73
**Single AD:** AD-462f v1 (full closure of GH #58 — pillars 1+2 already shipped via prior ADs; pillar 3 ships here)
**Closes:** GH issue #58
**Baseline test count:** 11447 (HEAD `a63aa3e`, post-Wave-72) → expected **11461** (+14 net), window **[+11, +15]** = [11458, 11462]
**HEAD at draft:** `a63aa3e`, working tree clean
**Builder:** required

## Summary

GH #58 names AD-462f as "Optimized Memory Representation" with three pillars: **structured metadata, concept graphs, retrieval-as-pointers.** When AD-462a–e shipped in 2026-04 (Era 4 cluster), 462f was deferred with the rationale *"AnchorFrame (AD-567a) covers near-term structured metadata needs"* (`decisions-era-4-evolution.md:2699`). That deferral reasoning is half-correct, half-stale at HEAD `a63aa3e`:

- **Pillar 1 — Structured metadata:** ✅ Already shipped. `AnchorFrame` (AD-567a, `types.py:352`), `MemorySource` (AD-541), `Episode.importance` (AD-598), `Episode.valid_from`/`valid_until` (AD-579b). **No new code in v1.**
- **Pillar 2 — Concept graphs:** ✅ Already shipped. `KnowledgeEdgeStorage` (AD-688) + typed-triple traversal (AD-692) + post-merge graph expansion (`oracle_service.py:392`). Tier 6 in `OracleService.query()`. **No new code in v1.**
- **Pillar 3 — Retrieval-as-pointers:** ❌ Not yet. Every Oracle/recall path materializes full content into the prompt before the agent decides which results matter. `OracleService.query_formatted()` concatenates up to ~2KB across 7 tiers per dispatch. **This is the v1 work.**

**v1 ships pillar 3 in one wave, closing GH #58 entirely.** PROGRESS.md / roadmap entries explicitly cite the AD coverage of pillars 1+2 — this is recognition, not deferral. Per Captain rule "don't defer unless no choice," only AD-462f-1/b/c/d remain (each with concrete forcing functions in DLog #14 and elsewhere of the per-AD prompt).

The full scope:

- **`MemoryRef` dataclass** (NEW in `types.py`) — frozen 7-field projection of an `OracleResult`: `ref_id`, `tier`, `score`, `snippet ≤200 chars`, `provenance`, `timestamp`, `metadata` (tier-stable identifying keys only).
- **`OracleService.query_refs(...)`** — calls existing `query()`, projects to refs, populates instance LRU cache.
- **`OracleService.resolve_ref(ref_id)`** — cache-backed re-hydration, returns `OracleResult | None`. Tier-2 log-and-degrade on miss.
- **`OracleService.format_refs(refs, max_lines=10)`** — short prompt-ready block (`max_lines=10`, 120 char/line cap). Half the token cost of `query_formatted`.
- **LRU cache:** 256 entries, `OrderedDict`-backed, instance-scoped, no TTL (LRU eviction is sufficient bound).
- **`oracle_refs` QUERY op** in `sub_tasks/query.py` (parallel to AD-696's `oracle_lookup`). Gated at `RecallTier.ENHANCED` (Lieutenant+) — refs are cheaper than lookups so access opens one rank earlier.
- **One new EventType:** `MEMORY_REFS_DISPATCHED` immediately after `ORACLE_LOOKUP_DISPATCHED` at `events.py:235`.
- **14 boundary tests** in `tests/test_ad462f_memory_refs.py`.

**Discipline:** v1 is a stateless projection from the chain's perspective. Cache is bounded and per-instance. Cross-conversation persistence is AD-462f-c. ANALYZE intent signal + chain dispatch seam is AD-462f-b. ToolRegistry registration is AD-462f-1 (same root cause as AD-696-1: `init_communication()` startup signature). Per-tier metadata contracts are AD-462f-d.

**No commercial leak.** AD-462f is OSS plumbing — one dataclass, one EventType, three OracleService methods, one QUERY op, one cache. All deferred children remain OSS.

## Architect calls (Decision Log)

The full 15-item DLog lives in `prompts/ad-462f-memory-refs-v1.md`. Highest-risk items repeated for Builder pre-flight:

- **DLog #1 — Refs are an OPT-IN projection.** `query()` and `query_formatted()` keep their AD-462e contracts byte-for-byte. AD-696's `oracle_lookup` op continues using `query_formatted` unchanged.
- **DLog #2 — `MemoryRef` lives in `types.py`, NOT `oracle_service.py`.** Canonical shared-types home; refs may eventually cross module boundaries. Frozen dataclass, hashable.
- **DLog #3 — `ref_id = f"{tier}:{stable_key}"`** with per-tier metadata key derivation (`episode_id`, `path`, `edge_id`, etc.). Empty keys fall back to `idx{i}`.
- **DLog #4 — `OrderedDict` LRU, 256 entries, instance-scoped.** No async lock — single-thread asyncio mutex semantics. No TTL.
- **DLog #5 — `resolve_ref` returns `None` on miss, NOT raises.** Cache miss is normal degradation.
- **DLog #6 — `format_refs` cap is `max_lines=10`, 120 chars/line.** Worst-case ~1.2KB output.
- **DLog #7 — `oracle_refs` gates at `RecallTier.ENHANCED`, not ORACLE.** Lieutenant+ rank gets snippet preview; full content still requires ORACLE-tier `oracle_lookup` (AD-696). Tier gradient is the v1 governance lever.
- **DLog #8 — Use `runtime.oracle` public alias (AD-686).** Mirrors AD-696 pattern at `query.py:269`.
- **DLog #10 — No new Pydantic config.** Inline module constants (`_MEMORY_REF_CACHE_SIZE=256`, `_FORMAT_REFS_DEFAULT_LINES=10`, `_FORMAT_REFS_LINE_CHAR_CAP=120`).
- **DLog #13 — No ANALYZE intent signal in v1.** No chain dispatch site benefits yet at HEAD. Skill agents and slash commands call `runtime.oracle.query_refs(...)` directly. AD-462f-b adds the intent signal once the chain seam exists.
- **DLog #14 — No ToolRegistry registration in v1.** Same root cause as AD-696-1 — `init_communication()` lacks `runtime` parameter. Forcing function: AD-462f-1 lands once that signature is updated.
- **DLog #15 — Commercial-leak audit: clean.**

## Builder workflow (standard)

1. **Pre-flight gate:** `pytest tests/ -q -n 4 --dist=loadfile` → confirm 11447 collected at HEAD `a63aa3e`.
2. Apply Section 0 (`events.py` 1 new EventType line). No tests should regress — additive only.
3. Apply Section 1 (`types.py` `MemoryRef` insertion). Run `pytest tests/test_*types* -n 0 -q` — no regressions expected (additive).
4. Apply Section 2.1 (oracle_service module constants). Apply Section 2.2 (OrderedDict import + `__init__` cache field). Apply Section 2.3 (`_derive_ref_id` helper). Apply Section 2.4 (`query_refs` / `resolve_ref` / `format_refs` methods). Run `pytest tests/test_*oracle* -n 0 -q` — no regressions expected.
5. Apply Section 3.1 (`_query_oracle_refs` op handler). Apply Section 3.2 (dispatch table entry). Run `pytest tests/test_*query* tests/test_*sub_task* tests/test_ad696* -n 0 -q` — no regressions expected.
6. Apply Section 4 (NEW test file `tests/test_ad462f_memory_refs.py`). Add the 14 tests one at a time; confirm each passes before adding the next.
7. **Final gate:** `pytest tests/ -q -n 4 --dist=loadfile` → expect 11461 (+14 net target; window [11458, 11462]).
8. **Update tracking:**
   - `PROGRESS.md` — append CLOSED paragraph for AD-462f v1.
   - `docs/development/roadmap.md` — flip the AD-462f entry per Section 5.2 of the per-AD prompt.
   - `decisions-era-4-evolution.md` — replace the existing `| AD-462f | DEFERRED ... |` table row + append `### AD-462f` paragraph per Section 5.5.
   - `prompts/wave-plan.yaml` (id 73) — `status: done`.
   - GH issue #58 — close with comment listing the three pillars (with AD coverage), the new public surface, the four deferred children with forcing functions, and the commit hash.

## Hard-stop conditions

1. Test count delta lands outside [+11, +15]. → Triage which class over/under-shot.
2. Existing Oracle / sub_tasks / events tests fail. → SEARCH/REPLACE blocks may have drifted from live anchors at HEAD `a63aa3e`. Re-grep before retrying.
3. Real working-tree changes appear in source files NOT named in this dispatch (`src/probos/events.py`, `src/probos/types.py`, `src/probos/cognitive/oracle_service.py`, `src/probos/cognitive/sub_tasks/query.py`, `tests/test_ad462f_memory_refs.py`, plus tracking files). → Hard stop, surface to Captain.
4. Any source change to `src/probos/cognitive/cognitive_agent.py`, `src/probos/cognitive/sub_tasks/analyze.py`, `src/probos/cognitive/sub_tasks/compose.py`, `src/probos/runtime.py`, `src/probos/startup/communication.py`, `src/probos/startup/finalize.py`, `src/probos/earned_agency.py`, or any tier-side file (`episodic.py`, `records*.py`, `knowledge_graph*.py`, `semantic_layer.py`, `archive.py`). → Hard-stop. (DLog #1 + #13 + #14: v1 ships no chain wiring, no tier-side `get_by_id` API, no tool registration.)
5. Any new Pydantic config field, any change to `src/probos/config.py`, any change to `config/system.yaml`, or any new `*Config` class. → DLog #10 violation. Hard-stop.
6. Any test boots a real `ProbOSRuntime` to validate Section 3. → Use `MagicMock` per Wave 13/66/67/68/69/70/72 fixture precedent (matches AD-696 Section 5 pattern). Hard-stop on any `ProbOSRuntime(...)` boot in this test file.
7. The `RecallTier.ENHANCED` gate is changed to `RecallTier.ORACLE` OR removed entirely. → DLog #7 violation. The ENHANCED gate is the v1 governance lever — refs democratize access while full lookups stay restricted. Hard-stop.
8. The LRU cache TTL is added, OR the cache is moved out of the OracleService instance into a global, OR the cache is async-locked. → DLog #4 violation. v1 is bounded LRU only, instance-scoped, single-thread asyncio mutex. Hard-stop.
9. The `MemoryRef` dataclass is moved out of `types.py` into `oracle_service.py`. → DLog #2 violation. Hard-stop.
10. The Builder elects to ship AD-462f-1 (ToolRegistry), AD-462f-b (ANALYZE intent + chain seam), AD-462f-c (cross-conversation persistence), or AD-462f-d (per-tier metadata contracts) "while we're here" — even partially, even as a stub. → Out of scope. Hard-stop.

## Acceptance criteria

1. Full gate passes at 11461 ± 2 (target +14; window [11458, 11462]).
2. All Section 0–4 SEARCH/REPLACE / CREATE blocks applied byte-for-byte as specified.
3. 14 new tests in `tests/test_ad462f_memory_refs.py` all pass.
4. No file outside the dispatch's named set is modified (other than tracking files: `PROGRESS.md`, `docs/development/roadmap.md`, `prompts/wave-plan.yaml`, `decisions-era-4-evolution.md`).
5. The Builder build report cites the test count delta + the ten "what this AD does NOT change" verifications.
6. The Builder build report explicitly cites:
   - That pillars 1 and 2 of GH #58 are documented as covered by prior ADs (no new code required).
   - The four deferred children (AD-462f-1 ToolRegistry, AD-462f-b ANALYZE/chain seam, AD-462f-c cross-conversation persistence, AD-462f-d per-tier metadata contracts) and their forcing functions.
7. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-05, HEAD `a63aa3e`)

The full verify-first table lives in the per-AD prompt at `prompts/ad-462f-memory-refs-v1.md` "Verified Against Codebase" footer. Highest-risk anchors repeated here:

```
grep -n "ORACLE_LOOKUP_DISPATCHED" src/probos/events.py
  235:    ORACLE_LOOKUP_DISPATCHED = "oracle_lookup_dispatched"  # AD-696
  (Section 0 SEARCH anchor; MEMORY_REFS_DISPATCHED collision-free)

grep -n "class RecallScore\|class Episode" src/probos/types.py
  397: class RecallScore:
  411: class Episode:
  (Section 1 insertion site — between RecallScore and Episode)

grep -n "_GRAPH_MIN_TOKEN_LEN\|def _format_age" src/probos/cognitive/oracle_service.py
  44: _GRAPH_MIN_TOKEN_LEN = 3
  103: def _format_age(timestamp: float) -> str:
  (Section 2.1 anchor for module constants; Section 2.3 anchor for _derive_ref_id)

grep -n "self._health_provider = health_provider" src/probos/cognitive/oracle_service.py
  (Section 2.2 anchor for cache field on __init__)

grep -n "=== END ORACLE RESULTS ===" src/probos/cognitive/oracle_service.py
  (Section 2.4 anchor — insert after query_formatted)

grep -n "return {\"oracle_lookup\": formatted}\|\"oracle_lookup\": _query_oracle_lookup" src/probos/cognitive/sub_tasks/query.py
  306:    return {"oracle_lookup": formatted}
  359:    "oracle_lookup": _query_oracle_lookup,                       # AD-696
  (Section 3.1 + 3.2 anchors)

grep -n "class RecallTier\|_TIER_ORDER" src/probos/earned_agency.py
  53: class RecallTier(str, Enum):
  92: _TIER_ORDER: dict[RecallTier, int] = {
  94:     RecallTier.ENHANCED: 1,
  (DLog #7 — RecallTier.ENHANCED gate; _TIER_ORDER is the live ordering helper at HEAD a63aa3e)

grep -n "self.oracle = cog.oracle_service" src/probos/runtime.py
  1349:    self.oracle = cog.oracle_service  # AD-686 (public alias; same instance)
  (DLog #8 — public seam exists at HEAD; matches AD-696 precedent)

grep -rn "test_ad462f" tests/
  (no matches — net-new test file confirmed)

grep -n "AD-462f" docs/development/roadmap.md
  4177: > - **AD-462f: Optimized Memory Representation** *(planned)* — Structured metadata, concept graphs, retrieval-as-pointers.
  (roadmap entry; flip per Section 5.2 of per-AD prompt)

grep -n "AD-462f" decisions-era-4-evolution.md
  2699: | AD-462f | DEFERRED — concept graphs, AnchorFrame sufficient for now |
  (Era-4 decisions table row; replace per Section 5.5)
```

---

## Per-AD prompt path

`prompts/ad-462f-memory-refs-v1.md`
