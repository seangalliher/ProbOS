# BF-662 Builder Execution — Embedding backend transition integrity

**Verdict:** APPROVED FOR BUILDER
**GitHub issue:** #1028 — https://github.com/seangalliher/ProbOS/issues/1028
**Exact base:** `d64920ac686c323a29feba561df24315955182a3` (refreshed 2026-07-11 after BF-659/660/663/661)
**Current highest shipped BF:** BF-663; BF-662 is already reserved; no new number
**Scope:** execute only `prompts/bf-662-embedding-backend-transition-integrity.md`.

## Read first

- `.github/copilot-instructions.md`
- `prompts/bf-662-embedding-backend-transition-integrity.md`
- `src/probos/knowledge/embeddings.py`
- `src/probos/cognitive/procedure_store.py`
- `src/probos/cognitive/self_improvement/evolution_store.py`
- `src/probos/cognitive/episodic.py`
- `src/probos/cognitive/episodic_mock.py`
- `src/probos/cognitive/schema_versions.py`
- `src/probos/startup/cognitive_services.py`
- `src/probos/startup/finalize.py`
- `src/probos/startup/shutdown.py`
- `src/probos/protocols.py`
- `src/probos/cognitive/procedures.py`

## Preflight

Before editing, verify `git rev-parse HEAD` is exactly `d64920ac686c323a29feba561df24315955182a3`. At initial dispatch the two BF-662 documents may be untracked; during final correction, `git status --short` may contain only the exact 17-file target set below. Any unrelated tracked/untracked change is a hard stop. Do not stash, restore, stage, or commit on the Architect's behalf.

## Current live anchors (2026-07-11)

- `embeddings.py`: `LocalHashEmbeddingFunction` line pattern 117; collection helper 211; active model helper 223.
- `procedure_store.py`: `start()` calls sync `_init_chroma()` at 156; `_init_chroma` is sync at 274; destructive delete at 314; `_save_to_chroma` at 434.
- `evolution_store.py`: `Lesson` at 24; `start()` at 56; `record_lesson` at 82; persisted recall sets `payload={}` at 169.
- `episodic.py`: `migrate_embedding_model` at 636; conflict sentinel at 1325; metadata-fill block at 1331.
- `cognitive_services.py`: `_run_one_migration` at 37; `is_current` skip at 68; AD-584 call at 413–427.
- `finalize.py`: `_wire_self_improvement` at 1832; phantom `_chroma_client` lookup at 1876; public `runtime.evolution_store` assignment at 1963.
- `runtime.py`: `evolution_store` public attribute at 947; `data_dir` public property at 1547.
- `shutdown.py`: episodic close at 421; ProcedureStore close at 810–813; no EvolutionStore close.
- Tests: 26 real ProcedureStore constructors/12 files; seven EvolutionStore constructors/one file; one `_init_chroma` patch at `test_procedure_store.py` line pattern 239.

## Exact target files — 17 total

- `src/probos/knowledge/embeddings.py`
- `src/probos/cognitive/procedure_store.py`
- `src/probos/cognitive/self_improvement/evolution_store.py`
- `src/probos/cognitive/episodic.py`
- `src/probos/cognitive/episodic_mock.py`
- `src/probos/startup/cognitive_services.py`
- `src/probos/startup/finalize.py`
- `src/probos/startup/shutdown.py`
- `tests/test_bf657_local_embedding_fallback.py`
- `tests/test_ad584_recall_qa_fix.py`
- `tests/test_procedure_store.py`
- `tests/test_ad482_self_improvement.py`
- `tests/test_ad818_schema_versions.py`
- `tests/test_bf296_shutdown_phase_ordering.py`
- **NEW:** `tests/fixtures/bf662_embedding_fakes.py`
- **NEW:** `prompts/bf-662-embedding-backend-transition-integrity.md`
- **NEW:** `prompts/bf-662-embedding-backend-transition-integrity-execution.md`

Reference only: `src/probos/cognitive/schema_versions.py`, `src/probos/cognitive/procedures.py`, `src/probos/protocols.py`, `src/probos/runtime.py`, `.github/workflows/ci.yml`, and the blast suites named in the build document.

These are exactly 14 modified source/test files plus three added files. Do not touch CI workflow, trackers, config, dependencies, embedding scoring/routing/quality, UI, model config, or any 18th file. Do not commit/push without separate Captain direction.

## Highest-risk instructions

1. Decorate `LocalHashEmbeddingFunction` with Chroma's official `@register_embedding_function`.
2. Persisted-backend ID is full SHA-256 over canonical JSON of actual EF `name()`+`get_config()` (`sort_keys`, tight separators, `allow_nan=False`). No `repr`, Python hash, private Chroma config, or old-model reconstruction/download.
3. Fresh-process regression spawns `sys.executable` with argv/`shell=False`, closes parent client first, imports the production embedding module in the child, opens without explicit EF, queries, closes in `finally`, and uses offline/local env. Same-process reopen is not evidence.
4. On any EF conflict/raw copy, use **exactly** `client.get_collection(name=..., embedding_function=None)`. Never omit the EF, never raw-open with get-or-create, and never text-query the raw handle.
5. AD-584 collection metadata and sidecar include active backend ID. A public typed `EpisodicMemory.embedding_migration_required(model, backend)` owns metadata access. Real memory, mock memory, startup, and the integration fake all require the exact two positional arguments; there is no optional backend or internal re-resolution. `force_run` bypasses only `_run_one_migration`'s current-version skip. Fresh/clean metadata prevents force-on-every-boot. The migration's internal broad swallow must not turn a failed force-run into a recorded clean no-op; operational failure propagates to the wrapper and leaves conflict-qualified metadata. Do not edit `SchemaVersionStore`.
6. ProcedureStore `_init_chroma` becomes async. SQLite reads are awaited through the abstract connection/cursor API and use bounded `(id, content_snapshot)` keyset pages. Normal first-create and rebuild start `procedure_index_state=rebuilding`; only verified completion writes `ready`, making missing/partial state retryable. Never call async DB methods from sync code/thread.
7. ProcedureStore owns/closes its Chroma client. Rebuild object snapshots via `Procedure.from_dict`, require reconstructed ID == SQLite row ID, and reuse the existing Chroma shape; malformed/non-object/ID-mismatched rows stay in SQLite; valid-row index failure cannot be swallowed as success.
8. Replace phantom `runtime._chroma_client` with an optional EvolutionStore-owned `chroma_path=runtime.data_dir`; add idempotent stop and critical-persistence shutdown before episodic close. Injected clients remain caller-owned.
9. EvolutionStore has no second authority: copy IDs/documents/entire metadata dict in bounded pages and exact-readback each batch. Before canonical→backup, tag source metadata with owner/txn/backup role; then rename shadow→canonical. Backup remains authoritative until active-EF + exact-content + non-empty-query proof. Proven/fresh canonical retains `bf662_state=stable` so same-backend boot does not remigrate. **Never call `delete_collection(canonical_name)`.**
10. Temp names are `bf662e-[sb]-{canonical_sha12}-{txn16}`, below 63 chars and independent of canonical length. Use `create_collection`, list collision check, and one exact ownership parser before touching a temp name. The parser requires every canonical-name/owner/txn/role/state/count field, a 16-character lowercase-hex txn, and native non-bool `int >= 0` count. Valid pairs are only backup/backup, shadow/copying|ready, and failed/failed; canonical markers are only backup/backup or shadow/ready. Never coerce.
11. Recovery authority: canonical during copy; backup after first rename and until candidate proof; canonical only after proof. Before every recovery rename/promotion/deletion, re-discover all owner-prefixed temporaries and require every owned shadow/failed entry to match the unique backup transaction and recorded source count. Partially owned names or any mismatch preserve the complete snapshot and degrade. Apply this to absent-canonical and candidate-canonical + backup states, including unrelated shadows. Canonical absent + shadow only, multiple backups, marker mismatch, or unprovable row mismatch means touch nothing and stop/degrade—never guess.
12. Preserve only actually persisted lesson fields: ID, summary document, and entire metadata dict (currently category/source_proposal_id/outcome/timestamp). Payload is already absent after Chroma reopen (`payload={}`); do not claim/add payload recovery.
13. Put both fake EFs in one `tests/fixtures/bf662_embedding_fakes.py` module and import them everywhere. Explicit `__init__`, unique stable names/configs, no duplicate decorators/registry mutation/model/network.
14. Same-backend and empty-store paths must be idempotent and leave no BF-662 temp collections. Every Chroma client/subprocess must close before Windows temp cleanup.
15. Existing `PROBOS_EMBEDDINGS=local` semantics remain untouched.
16. The exact blast must return naturally. Live thread/DB tracing verified lifecycle ownership only for: runtime activation tracker; episodic participant index (real and mock parity); runtime capability-request, knowledge-edge, personal-ontology-prober, and rejection-cache stores. Stop/clear those through their public contracts, and prove repeated stop/cleanup closes each underlying resource once. Do not infer any additional ownership.

## Evolution crash-state authority

| Shape | Authority | Required action |
|---|---|---|
| canonical only | canonical | prove; return if active or start transition |
| canonical + shadow | canonical | discard only owned stale shadow after canonical proof, or restart transition |
| backup + ready shadow; no canonical | backup | finish swap only if exact match/active; otherwise restore backup |
| candidate canonical + backup | backup | promote only after exact active proof; otherwise rename candidate aside and restore backup |
| no canonical + no unique proven backup | none selectable | touch nothing; stop/degrade |

The `failed/failed` state is written only after an invalid candidate has safely left the canonical name. Until that rename succeeds it retains the original paired `shadow/ready` marker, so either rename boundary remains restart-recoverable.

## Commands

### Focused

```powershell
Set-Location 'D:\ProbOS'
$gateDir = Join-Path $env:TEMP ("probos_bf662_focused_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $gateDir | Out-Null
$env:PROBOS_DATA_DIR = $gateDir
$env:PROBOS_EMBEDDINGS = 'local'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
try {
    & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_bf657_local_embedding_fallback.py tests/test_ad584_recall_qa_fix.py tests/test_ad818_schema_versions.py tests/test_procedure_store.py tests/test_ad482_self_improvement.py tests/test_bf296_shutdown_phase_ordering.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning
} finally {
    Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

### Blast radius

```powershell
Set-Location 'D:\ProbOS'
$gateDir = Join-Path $env:TEMP ("probos_bf662_blast_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $gateDir | Out-Null
$env:PROBOS_DATA_DIR = $gateDir
$env:PROBOS_EMBEDDINGS = 'local'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
try {
    & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad584_recall_qa_fix.py tests/test_ad605_enhanced_embedding.py tests/test_ad818_schema_versions.py tests/test_ad818a_paginated_migrations.py tests/test_ad818a2_paginated_migrations.py tests/test_episodic.py tests/test_episodic_chromadb.py tests/test_semantic_knowledge.py tests/test_procedure_store.py tests/test_graduated_compilation.py tests/test_procedure_archival.py tests/test_procedure_decay.py tests/test_procedure_dedup.py tests/test_ad482_self_improvement.py tests/test_finalize.py tests/test_bf296_shutdown_phase_ordering.py tests/test_bf598_shutdown_idempotency.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning
} finally {
    Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

Do not use `-n auto`. Do not leave a Chroma client, child process, or temp directory alive.

## Stop conditions

Stop if:

- HEAD is not exactly `d64920ac686c323a29feba561df24315955182a3` at dispatch, or unrelated tracked changes exist;
- Evolution canonical would be passed to `delete_collection`, or backup would be deleted before exact active-candidate proof;
- canonical is absent without exactly one proven backup authority, or ownership/row evidence is ambiguous;
- any owned or partially owned temporary disagrees with the unique backup transaction/source count before a recovery mutation;
- raw reads require anything other than `get_collection(..., embedding_function=None)` plus count/get;
- Chroma private fields, registry mutation, or a SchemaVersionStore schema/semantic change becomes necessary;
- ProcedureStore async SQLite work cannot stay on the awaited abstract connection/cursor seam;
- deterministic identity would require an extra model download or nondeterministic config serialization;
- tests need duplicate fake registration, cached/network models, sleeps, ordering, or leaked Windows handles;
- any file outside the exact 17-file target list is needed;
- or scope expands into quality/routing/scoring, payload persistence, generic migration infrastructure, UI/config/dependencies/trackers.

## Do not build

- No embedding algorithm/dimension/threshold/scoring/model-selection change.
- No AD-584 shadow-swap redesign; only identity, metadata, raw conflict open, and force semantics.
- No new DB/config/dependency/EventType/UI/CI change.
- No ProcedureStore restore from Ship's Records or SQLite row rewrite.
- No Evolution payload persistence/recovery and no copied embeddings.
- No production/test registry mutation; use official decorators once.
- No tracker edit, commit, or push.

## Acceptance criteria

1. All named acceptance behaviors and final-correction regressions in the build document are implemented or mapped explicitly to equivalent test names in the report.
2. Fresh-process local EF query, backend-qualified AD-584 force/skip, Procedure A→B→A rebuild, Evolution A→B→A + crash recovery, runtime persistence wiring, empty/same-backend idempotence, and Windows cleanup all pass.
3. Evolution canonical is never deleted; the report identifies the authoritative copy at every injected failure boundary.
4. The focused and blast commands above pass with `-p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning`.
5. Only exact target files changed; reference-only files and trackers remain untouched.
6. Mismatched/partially owned recovery states preserve exact names, counts, IDs, documents, collection metadata, and row metadata; the strict parser has parameterized rejection coverage.
7. Startup passes the exact `(active_model_name, active_backend_id)` pair to both real and fake predicate contracts.
8. Evolution, ProcedureStore, mock participant index, and runtime SQLite sidecar cleanup are idempotent; focused/blast runs return naturally and leave zero pytest processes.
9. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Builder handoff report

Report: exact 17 files changed; parent/child fresh-process result; backend IDs A/B; Procedure SQLite/Chroma counts before/after each direction; Evolution canonical/backup/shadow names and counts at every failure injection; which copy was authoritative; strict-parser/coherence snapshot results; focused/blast pass counts and natural exit; client/subprocess/SQLite cleanup evidence; zero pytest processes; deviations/stop conditions.

Do not edit trackers. Do not commit or push.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
