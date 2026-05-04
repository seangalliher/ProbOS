# Wave 39 Dispatch — AD-689 v1 Edge Population from Existing Data

**Builder mode:** continuous-build (single-AD wave; no inter-AD pause).
**Closes:** GH issue #383.
**Prompt:** `prompts/ad-689-edge-population-v1.md`.
**Phase:** Unified Knowledge Graph — Phase A, fourth and final foundation prompt (after AD-686 Wave 36, AD-687 Wave 37, AD-688 Wave 38).

---

## Standing Conventions

- Pre-flight test gate: `pytest tests/ -q -n 8 --dist=loadfile`. Baseline 11004 (Wave 38 commit `24c9db4`). Expected after Wave 39: 11016 (+12), tolerating one absorption into the known `test_auto_commit_after_debounce` xdist flake.
- Hard-stops surface to the architect, not silently quarantine: phantom API in shipping code, BaseAgent/IntentMessage protocol change, scope expansion beyond §8 of the prompt, working-tree-pollution from un-tracked source code the builder didn't author.
- Captain "no trivial deferral" (banked 2026-05-04). All four data sources ship in this v1 — no a/b/c/d sub-issues.

## Decision Log

1. **Edge-ID determinism scheme** — SHA-256 of `f"{source_type}|{source_id}|{relation}|{target_type}|{target_id}"`, first 32 hex chars. Combined with `SQLiteKnowledgeEdgeStore.add_edge` INSERT OR REPLACE upsert (Wave 37 — `edges.py:248`), idempotency holds across re-runs without read-modify-write. `created_at` drifts on each upsert; `id` is the dedup key, row count is what tests assert.
2. **`Resolved by:` markdown pattern resolution** — Captain's spec mentioned `**Resolved by:** ...`; the actual structured marker in `DECISIONS.md` is **`Closes (GH issue )?#NNN`** (case-insensitive). Builder uses `Closes` as the RESOLVED_BY signal. `**Related:**` covers INFORMED_BY. No imaginary `Resolved by:` parser.
3. **Hebbian rel_type filter** — only `REL_INTENT` weights become `COMPETENT_IN` edges. `REL_AGENT`/`REL_SOCIAL`/`REL_BUILDER_VARIANT`/`REL_STRATEGY` are out of scope for v1 — they'd need a different relation enum (peer-trust, social affinity) which isn't in AD-687's 10-relation list. Source-of-edge: agent (HebbianRouter `target` field). Target-of-edge: capability/intent name (HebbianRouter `source` field). Direction is `agent COMPETENT_IN intent`.
4. **`reports_to` direction** — sub_post.reports_to → super_post (`models.py:37`). Edge: subordinate_agent_type → REPORTS_TO → superior_agent_type. Each post is mapped to all assignments that fill it (mirrors AD-630 reverse map at `service.py:178`); posts with no assignment skipped.
5. **`runtime.edge_backfill` slot placement** — runtime.py late-init block at `:425–432`, immediately after `self.knowledge_edges` (Wave 37 sibling). Public Wave 5 conv #1.
6. **`list_episodes` placement on `EpisodicMemory`** — inserted immediately BEFORE existing `get_by_ids` (currently `episodic.py:1132`). Same module, ordered logically next to its sibling read primitive. Demeter-clean: backfill consumes the public API, no `_collection` access.
7. **Wirer is async** — `_wire_edge_backfill` is `async def` (mirrors `_wire_self_distillation` at `:384`). Call site uses `await` (mirrors `await _wire_self_distillation(...)` at `:585`).
8. **Wirer placement** — between `_wire_chain_optimizer` and `_wire_causal_reasoner` (existing definition order `:214` → `:239`). Call site between matching log lines around `:585–589`. Phase ordering verified: `runtime.knowledge_edges` is set in communication-adoption phase BEFORE finalize runs; `runtime.ontology` / `runtime.hebbian_router` / `runtime.episodic_memory` all set before finalize as well.
9. **`EdgeBackfillConfig.enabled=True` default** — deviates from Wave-10 transitional-flag convention. Same precedent as `KnowledgeEdgesConfig` + `CognitiveJournalConfig`. The warm-boot wirer is itself a no-op once the table has any rows (idempotency-by-row-count guard via `find_edges(limit=1)`). Documented in the model docstring.

## File Paths

| Path | Status | Purpose |
|---|---|---|
| `src/probos/knowledge/backfill.py` | NEW | `EdgeBackfillService` + `EdgeBackfillResult` + module-private helpers |
| `src/probos/knowledge/__init__.py` | MODIFY | Re-export `EdgeBackfillResult`, `EdgeBackfillService` |
| `src/probos/cognitive/episodic.py` | MODIFY | Insert public `async def list_episodes(*, limit=None)` before `get_by_ids` |
| `src/probos/config.py` | MODIFY | Add `EdgeBackfillConfig` after `KnowledgeEdgesConfig`; add `edge_backfill` field after `knowledge_edges` field on `SystemConfig` |
| `src/probos/runtime.py` | MODIFY | Add `self.edge_backfill: Any = None` slot after `self.knowledge_edges` |
| `src/probos/startup/finalize.py` | MODIFY | Add `async def _wire_edge_backfill` + call site `if await _wire_edge_backfill(...)` |
| `tests/test_ad689_edge_backfill.py` | NEW | 12 tests |
| `PROGRESS.md` | MODIFY | Prepend AD-689 v1 entry under Era V |
| `DECISIONS.md` | MODIFY | Prepend AD-689 v1 entry at top of Era V |
| `docs/development/roadmap.md` | MODIFY | Flip AD-689 row Scoped → Complete |

## Verified Anchors (HEAD `46fa2cd`)

- `KnowledgeEdgeStorage.add_edge` (Protocol) at `src/probos/knowledge/edges.py:139`. Concrete impl `INSERT OR REPLACE` at `:248`.
- `KnowledgeEntityType` 8 values at `edges.py:41–51`. `KnowledgeRelationType` 10 values at `:54–66`.
- `runtime.knowledge_edges` slot at `runtime.py:428`; assignment at `:1612`.
- `runtime.ontology` assignment at `runtime.py:1645`. `get_all_assignments`, `get_post`, `get_posts` confirmed at `ontology/service.py:155, 156, 165, 174` (and `:114, 162` for `get_departments`/`get_crew_agent_types`).
- `Post.reports_to: str | None` and `Post.id: str` confirmed at `ontology/models.py:35–43`.
- `Assignment.agent_type: str` + `post_id: str` at `models.py:46–51`.
- `HebbianRouter.all_weights_typed() -> dict[(source, target, rel_type), float]` at `mesh/routing.py:248`. `REL_INTENT = "intent"` at `:28`.
- `Episode` frozen dataclass at `types.py:411–434` — has `id`, `agent_ids`, `timestamp`.
- Existing `get_by_ids` at `episodic.py:1132`. `_metadata_to_episode` referenced at `:1132/:2083`. `recent()` (structural sibling for new `list_episodes`) at `:1869`.
- `KnowledgeEdgesConfig` at `config.py:1743`. Field at `SystemConfig` at `:2078`.
- `_wire_self_distillation` (async wirer precedent) at `finalize.py:384`. Call site `await _wire_self_distillation(...)` at `:585`.
- `_wire_chain_optimizer` (sync precedent + insertion site) at `finalize.py:214–237`. Call site at `:582–583`.
- `DECISIONS.md` `**Related:**` markdown anchors confirmed (10 hits in Era V alone). `Closes GH issue #NNN` / `Closes #NNN` confirmed at `DECISIONS.md:28, 56, 129, 151, 178, 258`.
- Era archives `decisions-era-1-genesis.md` … `decisions-era-4-evolution.md` exist at workspace root.

## Phantom-API Pre-Check Result (architect-side, draft-time)

Run after draft commit:

```pwsh
pwsh scripts/phantom-api-precheck.ps1 -PromptPaths prompts/ad-689-edge-population-v1.md
```

Expected outcome: 0 NEW phantoms. Documented intra-prompt FPs (the script can't see definitions that haven't been written yet):

- `EdgeBackfillService`, `EdgeBackfillResult`, `EdgeBackfillConfig`, `_deterministic_edge_id`, `_make_edge`, `_wire_edge_backfill` — introduced by Sections 1/4/6 of this prompt.
- `EpisodicMemory.list_episodes` — introduced by Section 3.
- `runtime.edge_backfill` — introduced by Section 5.
- `SimpleNamespace` — stdlib `types.SimpleNamespace`, used in test fixtures (FP class — Waves 27–35 same pattern).

No kwarg phantoms — every method signature verified against the live target (`KnowledgeEdgeStorage` Protocol, `Episode` dataclass, ontology service methods, `HebbianRouter.all_weights_typed`).

## Build Sequence (Builder)

1. Apply Section 1 (NEW file `backfill.py`).
2. Apply Section 2 (re-exports in `knowledge/__init__.py`).
3. Apply Section 3 (insert `list_episodes` in `episodic.py`).
4. Apply Section 4 (config additions).
5. Apply Section 5 (runtime slot).
6. Apply Section 6 (wirer + call site in `finalize.py`).
7. Apply Section 7 (NEW test file).
8. Run `pytest tests/test_ad689_edge_backfill.py -v -n 0` — expect 12/12 pass.
9. Run full gate: `pytest tests/ -q -n 8 --dist=loadfile`. Expect ≥ 11014 passing (+10 floor; +12 target).
10. Update PROGRESS.md, DECISIONS.md, roadmap.md per §10.
11. Single commit "Wave 39 build: AD-689 v1 Edge population from existing data (#383)".
12. Push; close #383 (manually if EMU 403 persists, same constraint as Waves 31–38).

## Out of Scope (legitimate boundaries — NOT a-b-c-d sub-issues)

- AD-690 — Dream Step 10 relationship inference (issue #384, Wave 40).
- AD-691 — NL-to-graph LLM entity extraction (future).
- AD-692 — Classification enforcement on graph reads (commercial).
- AD-693 — Federation cross-instance edge sync (commercial).
- AD-694 — Kùzu/Postgres backend (commercial).
- Live event-driven incremental backfill — separate AD if signals justify.

## Sanity Banner

| Source | Mapping (verified) | Threshold |
|---|---|---|
| Ontology — reports_to | `AGENT(sub_agent_type) REPORTS_TO AGENT(super_agent_type)` via `Post.reports_to` chain + reverse post→agent map | n/a |
| Ontology — member_of | `AGENT(agent_type) MEMBER_OF DEPARTMENT(post.department_id)` | n/a |
| Hebbian — competent_in | `AGENT(target) COMPETENT_IN CAPABILITY(source)` for `REL_INTENT` weights | `weight >= cfg.hebbian_threshold` (default 0.5) |
| Episodes — involved_in | `AGENT(agent_id) INVOLVED_IN INCIDENT(episode.id)` per `Episode.agent_ids` | n/a |
| Decisions — informed_by | `DECISION(AD-N) INFORMED_BY DECISION(AD-M)` per `**Related:**` AD token | self-AD skipped |
| Decisions — resolved_by | `DECISION(AD-N) RESOLVED_BY INCIDENT(gh-X)` per `Closes (GH issue )?#X` | n/a |

End of dispatch.
