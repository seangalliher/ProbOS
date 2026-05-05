# Wave 40 Dispatch — AD-690 v1: Dream Step 10 Relationship Inference

**Date:** 2026-05-04
**Wave:** 40
**Single-AD continuous-build wave.** No inter-AD pause.

---

## Inputs (read-first)

1. `prompts/ad-690-dream-step10-relationship-inference-v1.md` — the prompt.
2. `prompts/BUILDER-EXECUTION-PLAN.md` — standing rules.
3. `.github/copilot-instructions.md` — engineering principles.

---

## Build summary

Adds Dream Step 7i (titled "Dream Step 10" in spec/issue) to the dream consolidation pipeline. Pure-function service in `cognitive/relationship_inference.py` is invoked from `DreamingEngine.dream_cycle` between Step 7h and Step 8. Looks for AGENT→AGENT pairs that co-occur in this cycle's episodes but lack any `knowledge_edges` link; LLM classifier picks `REPORTS_TO`, `DEPENDS_ON`, or `null`. Anti-contamination: per-entity edge cap (default 5/run), `max_pairs_per_run` cap (default 50), min-confidence threshold (default 0.6), persistent rejection cache via new `SQLiteRejectionCache`.

Closes GH issue #384.

---

## Architect calls (from prompt — do not relitigate)

- **DLog #1**: Pipeline step is `7i`, not `10`. AD-555 already owns Step 10. Captain-facing label keeps "Dream Step 10" naming.
- **DLog #2**: Step 7i consumes the in-scope `episodes` variable used by other 7-tier steps. No `list_episodes(since=...)` call (no `since` parameter exists).
- **DLog #3**: Rejection cache is a dedicated SQLite table in new module `knowledge/rejection_cache.py`. Not an overloaded `CLASSIFIED_AS` sentinel.
- **DLog #4**: AGENT→AGENT relation whitelist for v1 is `{REPORTS_TO, DEPENDS_ON}` only. Other returned relations are treated as parse failures.

---

## Files touched

| File | Action |
|------|--------|
| `src/probos/knowledge/rejection_cache.py` | NEW (~110 lines) |
| `src/probos/knowledge/__init__.py` | append re-exports |
| `src/probos/cognitive/relationship_inference.py` | NEW (~250 lines) |
| `src/probos/config.py` | extend `DreamingConfig` (4 new fields) |
| `src/probos/types.py` | extend `DreamReport` (3 new counter fields) |
| `src/probos/cognitive/dreaming.py` | 4 SEARCH/REPLACE edits (ctor fields, setters, Step 7i block, report assembly) |
| `src/probos/startup/finalize.py` | new wirer + invocation site |
| `src/probos/runtime.py` | declare `self.rejection_cache: Any = None` |
| `tests/test_ad690_relationship_inference.py` | NEW (12 tests) |

---

## Verification done at draft (HEAD `b402fee`)

- AD-687 surface (`KnowledgeEdge`/`KnowledgeEdgeStorage`/`KnowledgeEntityType.AGENT`/`KnowledgeRelationType.REPORTS_TO`+`DEPENDS_ON`/`add_edge`/`find_edges`) confirmed at `src/probos/knowledge/edges.py:41,54,73,134,139,150,240,348`.
- AD-689 `EpisodicMemory.list_episodes(*, limit)` confirmed at `episodic.py:1132` (informational only — Step 7i uses in-scope `episodes` var).
- `Episode.agent_ids: list[str]` at `types.py:420`.
- `LLMRequest(prompt, system_prompt="", tier="standard", temperature=0.0, max_tokens=2048)` at `types.py:227`.
- Dream-cycle insertion site: `dreaming.py:1067` (Step 7h close) → `:1069` (Step 8 open).
- `DreamReport` last fields at `types.py:550-552` (`wm_priming_entries`).
- `DreamingConfig` last field at `config.py:632` (`trace_exemplars_per_procedure`).
- Wirer sibling: `_wire_chain_optimizer` at `startup/finalize.py:214`; `_wire_edge_backfill` at `:239` (the immediately-preceding wirer in the cascade).
- Wirer cascade insertion: between `:638` (`_wire_edge_backfill`) and `:641` (`_wire_causal_reasoner`).
- DreamingEngine setter pattern (`set_records_store`, `set_quality_router`) at `dreaming.py:145,164`.
- `runtime.knowledge_edges` declared at `runtime.py:428`, adopted at `:1615`.
- `extract_json` helper at `utils/json_extract.py:17`.
- `aiosqlite` used by AD-687/AD-689 — confirmed dep.

---

## Phantom-API pre-check (run at draft)

To run pre-build:

```
./scripts/phantom-api-precheck.ps1 -PromptPath prompts/ad-690-dream-step10-relationship-inference-v1.md
```

Expected FPs (intra-prompt introductions, same class as Waves 27/36/37/38/39):

- `RelationshipInferenceResult` (introduced)
- `SQLiteRejectionCache` (introduced)
- `RejectionCacheStorage` (introduced)
- `infer_relationships_from_episodes` (introduced)
- `runtime.rejection_cache` (introduced)
- `DreamingEngine.set_knowledge_edges` / `set_rejection_cache` (introduced)
- `DreamReport.inferred_relationships`/`relationship_pairs_rejected`/`relationship_pairs_capped` (introduced)
- `DreamingConfig.relationship_inference_*` (introduced)

If any NEW phantoms appear (not in this list), hard-stop and surface to architect.

---

## Test gate

Baseline (Wave 39 commit `a8a3e0e`): **11015 passed**, 15 skipped, 1 known xdist flake (`test_dreaming.py::test_nl_to_dream_cycle_changes_weights`, passes serial).

Expected after AD-690: **≥ 11025** (+10–12). Drop targets if drift: tests #5 (min-confidence) and #10 (whitelist) overlap in code path; #6 (per-entity cap) and #7 (max-pairs cap) overlap in loop control.

Commands:

- Per-prompt: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad690_relationship_inference.py -v -n 0`
- Full gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile`

---

## Hard-stop conditions

Surface to architect ONLY if:

1. Phantom-API pre-check flags a NEW phantom not in the expected FP list above.
2. A property collision is discovered at build time on any of the names listed in Section 0 of the prompt.
3. The Step 7i insertion anchor (lines 1067/1069) has drifted in HEAD between draft and build.
4. The `DreamingConfig` extension breaks Pydantic validation in any pre-existing test.
5. `aiosqlite` import fails (it shouldn't; it's already used by AD-687/AD-689).

Otherwise, fix-forward at build time. Document drift-fixes in build notes.

---

## Known fixture traps

- The `_AGENT_AGENT_RELATION_WHITELIST` is a TUPLE of `KnowledgeRelationType` enum values, not strings. Tests that compare via `relation in whitelist` must use the enum, not its `.value`.
- `Episode.agent_ids` may legitimately contain duplicates (same agent appears twice in a DAG). The pair-extractor must dedupe within a single episode, not just across episodes. (Already handled by `set(ep.agent_ids)` at extraction.)
- `KnowledgeEdge.__post_init__` raises `ValueError` if `confidence` or `weight` is outside `[0, 1]`. The `_classify_pair_with_llm` helper MUST clamp before returning, or the `add_edge` call inside `infer_relationships_from_episodes` will raise (which would still be caught by the tier-2 `try/except` but would skew the inferred-vs-rejected counters).
- The Step 7i block guards on `self._llm_client is not None` and `self._knowledge_edges is not None`. The `dreaming_engine` fixture in many existing tests passes `llm_client=None`, which is fine — Step 7i no-ops cleanly.

---

## Tracker updates (post-build)

- `PROGRESS.md`: prepend Era V entry following AD-689's format.
- `docs/development/roadmap.md`: flip AD-690 status to "Complete (v1)".
- No DECISIONS.md entry required (architect calls already documented in this dispatch and the prompt header).

---

## Single commit message

```
Wave 40: AD-690 v1 Dream Step 10 relationship inference (full v1) (#384)
```

Push to `origin/main`. GH issue #384 close blocked by EMU 403 (same as Waves 31–39); user closes manually.
