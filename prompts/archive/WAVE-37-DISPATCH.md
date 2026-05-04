# Wave 37 Dispatch — AD-687 v1 Knowledge Edge Store

**Status:** Pending
**Issue:** #381 (closes on merge)
**Prompt:** [`prompts/ad-687-knowledge-edge-store-v1.md`](ad-687-knowledge-edge-store-v1.md)
**Wave-plan slot:** id `"37"` (already populated, status `pending`)
**Predecessor:** Wave 36 (AD-686 v1 Oracle Tier 5, commit `48db252`, gate 10978 → baseline now 10994)
**Expected gate after build:** 11006 (+12)

---

## v1 Scope (one line)

Greenfield SQLite store for typed entity→relation→entity triples at `src/probos/knowledge/edges.py`: 8 entity types + 10 relation types + frozen `KnowledgeEdge` (with bounds-validated `confidence`/`weight`/`classification`) + `KnowledgeEdgeStorage` Protocol + `SQLiteKnowledgeEdgeStore` (CRUD + recursive-CTE bounded traversal with cycle protection) + Pydantic `KnowledgeEdgesConfig` + startup wiring + public `runtime.knowledge_edges` attribute.

**Captain's "complete v1" standing convention applies.** No deferral within AD-687 spec.

## Phase Context

Phase A (Foundation) of the Unified Knowledge Graph + Oracle Unification stack. AD-687 is the **second of four Phase-A ADs**: AD-686 ✅ (Oracle Tier 5, Wave 36) → **AD-687 (this) → AD-688 (Oracle Tier 6 graph + post-merge expansion) → AD-689 (edge backfill) → AD-690 (Dream Step 10)**. The remaining four are independent GitHub issues #382/#383/#384/#386 — not deferral.

## Dependencies — Verify-First Findings (HEAD `227240f`)

| Dep | Status | Used in v1? |
|---|---|---|
| `protocols.ConnectionFactory` / `DatabaseConnection` (AD-542 / AD-680) | Shipped (`protocols.py:186`, `:223`) | YES — REUSED (no new connection protocol) |
| `storage.sqlite_factory.default_factory` | Shipped (`sqlite_factory.py:28`) | YES — fallback in `SQLiteKnowledgeEdgeStore.__init__` |
| `CognitiveJournal` lifecycle pattern | Shipped (`journal.py:109–148`) | Mirrored exactly (db_path + factory + async start/stop + executescript schema + aiosqlite.Row) |
| Startup adoption pattern | Shipped (`startup/communication.py:309–315`, `runtime.py:425`/`:1608`) | Mirrored exactly (build in comm, slot in runtime, adopt from comm) |
| `_CLASSIFICATION_LEVELS` taxonomy | Shipped (`records_store.py:27`) | REUSED labels (`private/department/ship/fleet`) — no new taxonomy |
| AD-686 (Oracle Tier 5) | Shipped (Wave 36, commit `48db252`) | NOT consumed in v1 — that's AD-688's job |

**Zero existing references** to `knowledge_edges` / `KnowledgeEdge` / `KnowledgeEntityType` / `KnowledgeRelationType` / `KnowledgeEdgeStorage` in `src/` or `tests/` — fully greenfield.

## Decision Log (architect calls)

1. **REUSE `ConnectionFactory`/`DatabaseConnection` Protocols, do NOT define a new connection protocol.** They already exist for exactly this purpose (AD-542 cloud-ready abstraction). Adding a new `KnowledgeEdgeConnection` would be redundant.
2. **Service-layer Protocol IS in v1** (`KnowledgeEdgeStorage` ~25 lines). Two consumers (AD-688 Oracle, AD-689 backfill) are already designed; declaring the abstract surface now lets each depend on the Protocol, not the concrete class.
3. **Module location: `src/probos/knowledge/edges.py`** (not `cognitive/`). The `knowledge/` subpackage already groups graph-adjacent stores (`store.py`, `semantic.py`, `records_store.py`, `archive_store.py`, `embeddings.py`).
4. **`KnowledgeEdgeStore` is an alias for `SQLiteKnowledgeEdgeStore`** — public name in `__init__.py` exports stays SQL-implementation-agnostic; commercial overlays can rebind it.
5. **Default `enabled=True`** — DEVIATES from Wave-10 transitional-flag convention. Documented inline in config docstring with three justifications: (a) v1 has zero consumers (Oracle/backfill/dream arrive in AD-688/689/690), (b) boot cost is one CREATE TABLE IF NOT EXISTS, (c) sibling precedent: `CognitiveJournalConfig` is also default-True for the same "infrastructure store, invisible until consumed" reason.
6. **Cycle protection in CTE via `path` column + `instr()` check.** SQLite recursive CTEs need explicit cycle protection (no built-in `CYCLE` clause until SQLite 3.45+; ProbOS supports older). The `path` column accumulates `type:id>type:id>...` tokens; the recursive arm excludes a candidate edge whose target already appears via `instr(walk.path, ...) = 0`.
7. **Hard ceiling `MAX_HOPS_CEILING = 3`** at module level + Pydantic `field_validator` rejecting config values outside [1, 3]. The runtime method ALSO clamps `int(max_hops)` to ceiling — defense-in-depth (boundary validation at both API entry and config parse).
8. **`update_edge` raises `ValueError` on out-of-bounds, NOT log-and-degrade.** Defense-in-depth at the boundary; the dataclass validates at construction so the update path must mirror it. All other failure paths are log-and-degrade tier-2 (CRUD never raises `sqlite3.Error` to caller).
9. **`add_edge` uses `INSERT OR REPLACE`** — idempotent on `id`. AD-689 backfill needs idempotency; AD-690 dream inference needs upsert semantics. This decision lives in v1 because changing it later is breaking.
10. **`MAX_TRAVERSE_ROWS = 5000` safety cap** on traverse output. Prevents accidental graph-walk DOS if AD-689 backfill seeds dense subgraphs.

## Phantom-API Pre-Check

Run before commit:

```pwsh
./scripts/phantom-api-precheck.ps1 prompts/ad-687-knowledge-edge-store-v1.md
```

**Expected: 0 phantoms.** Every symbol referenced is either at HEAD `227240f` (verified table) or intra-prompt-introduced (Section 1). The script correctly handles intra-prompt symbols (Wave 27/28/29/31/33/35/36 precedent). If non-zero phantoms surface, document as FPs in build report; do NOT fix without architect review.

**Known FP class to expect (if any):** `class:KnowledgeEdgeStorage` — Protocol introduced in this prompt, may appear in test isinstance check. Document as FP.

## Test Plan (12 tests, complete v1 floor 10 + 2 margin)

1. `test_schema_creates_table_and_indexes` — startup creates `knowledge_edges` + 4 indexes.
2. `test_add_edge_returns_id_and_persists` — happy path + get_edge round-trip basic fields.
3. `test_get_edge_round_trip_all_fields` — full 13-field round-trip via `to_dict()` equality.
4. `test_find_edges_by_source` — filter by source_type + source_id, returns 2 of 3 inserted.
5. `test_find_edges_by_relation` — filter by relation alone.
6. `test_update_edge_advances_updated_at` — confidence + weight changed, updated_at advances.
7. `test_delete_edge` — succeeds + idempotent (second delete returns False).
8. `test_traverse_one_hop` — 2 single-edge paths from one source.
9. `test_traverse_two_hop_with_relation_filter` — chain of REPORTS_TO + noise MEMBER_OF; filter excludes noise.
10. `test_traverse_caps_at_max_hops_ceiling` — 5-link chain + caller passes max_hops=5 → returns ≤3-deep paths.
11. `test_traverse_cycle_terminates` — A↔B mutual DEPENDS_ON; cycle protection yields exactly one length-1 path.
12. `test_edge_validation_rejects_out_of_bounds` — confidence=1.5 / weight=-0.1 / classification="top_secret" all raise; SQLiteKnowledgeEdgeStore is a `KnowledgeEdgeStorage` Protocol instance.

**Test-count baseline:** 10994 (HEAD `227240f` collected count).
**Expected after build:** 11006 (+12 exact). Drop targets if drift: tests #6 (`time.sleep` clock-tick can flake on fast CI; switch to monkeypatched `time.time`) and #11 (cycle test depends on CTE `instr()` semantics — verify against SQLite version).

## Build Quality Reminders

- **Property collision (Wave 32 retrospective).** `SQLiteKnowledgeEdgeStore` is NOT a `CognitiveAgent` subclass; no `@property` shadowing risk on the runtime side. `runtime.knowledge_edges` collision-free per Section 0 grep.
- **Wirer ordering.** `knowledge_edges` is built in `startup/communication.py` AFTER cognitive_journal (Section 3a), adopted in `runtime.py:1608` adjacent to `self.cognitive_journal = comm.cognitive_journal` (Section 3d). No cross-phase dependencies.
- **MagicMock backward-compat.** No existing tests touch `knowledge_edges` (Section 0 grep). New code is fully isolated.
- **`field_validator` import.** Section 2a config edit uses `@field_validator`. Verify `field_validator` is in the existing `from pydantic import ...` line BEFORE editing — most likely already present (used by `DiagnosticContextConfig` per Wave 33 work). If missing, add it.
- **`Path` import in `communication.py`.** Section 3a uses `Path(config.knowledge_edges.db_path).name`. Verify `from pathlib import Path` is at the top of the file before editing.
- **`_db` attribute access in tests.** Test #1 reads `s._db.execute(...)` for schema introspection. This is a direct private-attribute read in test code only — acceptable for state inspection, mirrors `test_ad660_causal_reasoning.py` pattern that introspects `journal._db`. Do NOT promote `_db` to public; tests own this contract.
- **Cycle test (#11) SQLite compatibility.** `instr()` is SQLite stdlib (since 3.7.15) — fine for all supported aiosqlite versions. If cycle test fails on CI, check sqlite version with `python -c "import sqlite3; print(sqlite3.sqlite_version)"`.
- **Pre-commit deletion sanity.** Diff per file:
  - `src/probos/knowledge/edges.py`: ~440 added (NEW), 0 deleted.
  - `src/probos/knowledge/__init__.py`: ~10 added, 4 deleted (re-exports expansion).
  - `src/probos/config.py`: ~25 added, 0 deleted (one new model + one wiring line).
  - `src/probos/startup/communication.py`: ~10 added (build block) + ~2 added (dataclass field + return arg), 0 deleted.
  - `src/probos/runtime.py`: 4 lines added (slot + adoption), 0 deleted.
  - `tests/test_ad687_knowledge_edge_store.py`: ~280 added (NEW), 0 deleted.
  - Total: well below the 200-line single-file deletion threshold.
- **`update_edge` validation raises (not log-and-degrade).** Boundary defense per Engineering Principles three-tier exception model. Documented in Section 1 docstring + reflected in test #12 (covers dataclass `__post_init__`; if Builder wants to cover `update_edge` path, add 13th test).

## Out of Scope (Hard Limits)

| Out | Where it lives next |
|---|---|
| API endpoint `/api/knowledge/edges/...` | AD-688 Oracle Tier 6 (issue #382) |
| Oracle Tier 6 + post-merge expansion | AD-688 (issue #382) |
| Edge backfill from existing data | AD-689 (issue #383) |
| Dream Step 10 relationship inference | AD-690 (issue #384) |
| Classification enforcement | AD-692 (issue #386, **commercial**) |
| Federation cross-instance sync | AD-693 (issue #387, **commercial**) |
| Kùzu migration | AD-694 (issue #388, **commercial**) |
| Pruning / retention loop | AD-687-followup once consumers exist |
| Shell command, HXI surface | TBD once consumers exist |

## Success Criteria

1. Full parallel gate green at `pytest tests/ -q -n 8 --dist=loadfile`.
2. Test-count delta exactly +12 vs baseline 10994 → 11006 (tolerated drift: +10 if tests #6/#11 dropped).
3. New module `src/probos/knowledge/edges.py` exists with 8 entity types, 10 relation types, frozen `KnowledgeEdge`, `KnowledgeEdgeStorage` Protocol, `SQLiteKnowledgeEdgeStore`.
4. `runtime.knowledge_edges` is the same instance built in `startup/communication.py` (verified by code path, not test).
5. `KnowledgeEdgesConfig` field validator caps `max_traverse_hops` at 3.
6. `KnowledgeEdge.__post_init__` rejects out-of-bounds confidence/weight and unknown classification labels.
7. `traverse()` cycle-protects via `path` accumulator + `instr()` check; depth hard-capped at `MAX_HOPS_CEILING=3`.
8. Phantom-API pre-check exits with 0 phantom candidates (matches draft-time expectation; document any FPs in build report).
9. PROGRESS.md flipped from `AD-687` planned → `AD-687 v1 CLOSED`.
10. `docs/development/roadmap.md` AD-687 entry status flipped to `complete`.
11. DECISIONS.md AD-687 entry appended.
12. Issue #381 closed on merge (or surfaced for manual close per EMU 403).
