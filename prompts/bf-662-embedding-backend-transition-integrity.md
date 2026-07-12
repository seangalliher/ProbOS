# BF-662 — Embedding backend transition integrity

**Verdict:** APPROVED FOR BUILDER
**One-line:** Register BF-657's local EF for fresh-process reconstruction, qualify embedding state by deterministic backend identity, and make ProcedureStore and EvolutionStore transitions recoverable from their actual authorities.

**Status:** Ready to build
**Type:** Bug fix — **BF-662**; current highest shipped BF is BF-663; BF-662 is already reserved; no new AD/BF
**GitHub issue:** #1028 — https://github.com/seangalliher/ProbOS/issues/1028
**Exact build base / HEAD verified:** `d64920ac686c323a29feba561df24315955182a3` (2026-07-11)
**Original verification base:** `509e8cd7`; refreshed after BF-659 (`d0a6a50b`), BF-660 (`21cf4b77`), BF-663 (`f097f924`), and BF-661 (`d64920ac`)
**Dependencies:** BF-657, AD-584, AD-818/818a
**Installed contract verified:** ChromaDB 1.5.8
**Estimated tests:** 31+ focused additions/rewrites plus strict-parser parameter cases and existing-call updates

## Problem

Five confirmed persistence/lifecycle failures remain after BF-657:

1. **Fresh-process reconstruction:** `LocalHashEmbeddingFunction` is not registered with Chroma's global embedding-function registry. A collection created with it can be counted after reopen, but query-time configuration reconstruction in a process that has not imported the class fails: `ValueError: Embedding function probos-local-hash-v1 not found. Add @register_embedding_function...`.
2. **ProcedureStore transition loss:** `_init_chroma()` handles an EF conflict by omitting the active EF argument (not the verified explicit-`None` raw API), setting `__ef_conflict__`, deleting/recreating `procedures`, but never reindexes from authoritative SQLite. Reproduced Chroma count 1→0 while `ProcedureStore.get("p1")` still succeeds from SQLite.
3. **EvolutionStore transition loss:** `start()` catches the EF conflict as a generic exception and falls back to a fresh empty in-memory list. Reproduced persisted Chroma count 1→recall 0. The live wirer also reads phantom `runtime._chroma_client`; `ProbOSRuntime` never defines or assigns it, so standard runtime wiring passes `None` even before a transition.
4. **Episodic schema-version skip:** `EpisodicMemory.start()` marks collection metadata `embedding_model="__ef_conflict__"`, but startup's AD-818 sidecar can still skip AD-584 solely because static `MIGRATION_VERSIONS["AD-584"] == "1"`. The required re-embed is then bypassed.
5. **Exact blast does not exit naturally:** the prescribed blast reached its pytest summary but retained non-daemon `aiosqlite` workers. Live thread-to-database tracing identified the activation tracker, participant index, capability-request store, knowledge-edge store, personal-ontology prober, and rejection cache. This is in scope because BF-662's required exact gate is not complete unless it returns naturally and releases the Windows handles it opened.

Transitions must work in both directions (local→real and real→local), use registered test EFs, and never download a model in tests. CI must remain forced-local.

## ChromaDB 1.5.8 contract — load-bearing

Use only these verified public APIs:

| Need | Exact API / behavior |
|---|---|
| Register a custom EF | `@register_embedding_function` from `chromadb.utils.embedding_functions`; registration stores `cls.name()`, and reconstruction calls `build_from_config(config)`. |
| Normal open/create | `get_or_create_collection(name=..., embedding_function=active_ef, metadata=...)`; an existing different EF raises `ValueError` containing `Embedding function conflict`. Metadata arguments are ignored for an existing collection. |
| Raw open of an EF-conflicted source | **Exactly** `client.get_collection(name=..., embedding_function=None)`. Do not omit the argument and do not use get-or-create: omission supplies Chroma's default EF, while get-or-create can create a missing legacy collection. |
| Raw copy | `count()` and `get(..., include=["documents", "metadatas"])` work on the explicit-`None` handle. `query(query_texts=...)` requires an EF/config reconstruction and is forbidden on the raw source. |
| Temporary candidate | `create_collection(...)`, never get-or-create, so a collision fails instead of attaching to stale state. |
| Enumerate/open/delete | `list_collections()` returns Collection objects; use public `.name`, reopen selected entries explicitly, and expect missing `get_collection`/`delete_collection` to raise `NotFoundError`. |
| Rename | `Collection.modify(name=new_name)` preserves rows/metadata; target collision raises. This is the EvolutionStore swap primitive. |
| Configuration reconstruction | Text query/config access resolves the persisted known EF by name and invokes `build_from_config`; raw `count/get` deliberately avoids that path. |
| Names | Active 1.5.8 accepts 3–512 characters, alphanumeric endpoints, otherwise alphanumeric/`.`/`_`/`-`, and rejects `..` and IPv4-looking names. BF-662 temp names use lowercase alphanumeric/hyphen only and remain below 63 characters for active+legacy compatibility. |

Do not read `Collection._model.configuration_json`, mutate `known_embedding_functions`, or use any other Chroma private member.

## Architecture decisions

### DD-1 — Register `LocalHashEmbeddingFunction` at class definition

Import `register_embedding_function` from `chromadb.utils.embedding_functions` and decorate the class with `@register_embedding_function`.

ChromaDB 1.5.8's exact API calls `cls.name()` and stores the class in `known_embedding_functions`; persisted config reconstruction later calls `build_from_config(config)`. BF-657 already implemented `name`, `get_config`, and `build_from_config`, so registration is the missing seam.

Do not manually mutate Chroma internals. The decorator is the supported API.

### DD-2 — One backend identity helper drives metadata and AD-818 versioning

Add fully typed helpers in `knowledge/embeddings.py`:

- `get_embedding_backend_id(embedding_function: EmbeddingFunction[Documents]) -> str` (pure);
- `get_active_embedding_backend_id() -> str` (resolves through `get_collection_embedding_function()`).

Canonical input is exactly the EF's `name()` plus `get_config()`, serialized with `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)` and SHA-256. Return a stable string containing the EF name and full digest. Do not use `repr`, object identity, Python `hash()`, truncated config, or `default=str`. The active helper does not invoke the EF on sample text and must not reconstruct/download the old persisted backend. `get_active_embedding_model_name()` remains human-readable metadata.

Every new/rebuilt BF-662 collection carries both `embedding_model` and `embedding_backend_id`. Missing metadata, either `__ef_conflict__` sentinel, model mismatch, or backend-ID mismatch requires migration/rebuild. New collections receive complete metadata in the creation call; do not create them incomplete and then force every boot.

When calling `Collection.modify(metadata=...)`, remove keys beginning with `hnsw:`. Chroma rejects setting `hnsw:space` through modify even when unchanged. Preserve other safe metadata.

Use this identity to make the AD-584 schema version dynamic at the call site:

`version_hash = f"{MIGRATION_VERSIONS['AD-584']}:{backend_id}"`

Do not change `SchemaVersionStore` schema or semantics. The sidecar row naturally becomes stale whenever the active backend name/config changes.

### DD-3 — Episodic conflict/mismatch must force migration even with a matching sidecar

Episodic first creation includes both DD-2 keys in its initial `get_or_create_collection`. On EF conflict, open `episodes` with **`get_collection(name="episodes", embedding_function=None)`**, preserve safe metadata, and write both metadata keys as `__ef_conflict__`. Never text-query this raw handle.

Add a fully typed public query on `EpisodicMemory`:

`embedding_migration_required(active_model_name: str, active_backend_id: str) -> bool`

It returns true for missing metadata, either sentinel, or either mismatch; false for no collection or exact match; metadata-read failure returns true (safe retry). Extend `migrate_embedding_model(...)` with `active_backend_id`; its no-op check requires both values and empty/rebuilt collections write both.

The startup layer calls that public method immediately before AD-584 and passes the result as `force_run` to a new keyword-only `force_run: bool = False` on private `_run_one_migration()`. When true, bypass only `is_current()`; timeout/exception handling and record-on-clean-success remain unchanged. The AD-584 call uses `version_hash=f"{MIGRATION_VERSIONS['AD-584']}:{backend_id}"`.

`migrate_embedding_model` must not swallow an operational failure and return zero to this wrapper: that would falsely record the qualified sidecar as current. Let the wrapper own honest-degrade, and keep conflict-qualified collection metadata until the re-add completes and active identity is written.

Do not reach from `startup/cognitive_services.py` into `episodic_memory._collection`; that would violate the repository's public-API rule. This guard covers a store whose sidecar accidentally already contains the same backend-qualified value but whose collection is explicitly in conflict recovery.

Why this does not force every boot: fresh collections are born complete; a legacy/conflicted/mismatched collection runs once; clean completion writes active model/backend plus the qualified sidecar; the next same-backend boot matches and skips. Do not inspect a pre-initialization `None` and force forever.

Do not delete the AD-818 sidecar row preemptively. Keep `MIGRATION_VERSIONS["AD-584"] == "1"` as the static base and do not modify `SchemaVersionStore` schema/semantics.

### DD-4 — ProcedureStore rebuilds semantic index from SQLite before startup returns

`ProcedureStore.start()` is async and initializes SQLite before calling `_init_chroma()`. Change `_init_chroma()` to `async def` and `await` it from `start()` so a transition rebuild can query the abstract `DatabaseConnection`.

Required mechanism:

1. Retain the Chroma client on `self._chroma_client` on every successful initialization. If initialization fails before ownership is attached, close the local client in the exception path. `stop()` closes the retained client and clears client/collection so Windows releases persistent-store handles.
2. Use active EF/model/backend metadata. On conflict, use exact raw `get_collection(name="procedures", embedding_function=None)` only to prove/inspect the old index before dropping it; SQLite is the copy authority.
3. Rebuild on conflict, model/backend mismatch, missing backend ID, or `procedure_index_state != "ready"`.
4. Pass `procedure_index_state="rebuilding"` in normal get-or-create metadata too: Chroma applies it only to a newly created collection and ignores it for an existing ready collection. A missing canonical therefore always rebuilds from SQLite, including after a crash between delete/create. Recreated transition collections also start `rebuilding`.
5. Read deterministic bounded keyset pages: `SELECT id, content_snapshot FROM procedure_records WHERE id > ? ORDER BY id LIMIT ?`. The row shape is `(id, content_snapshot)`.
6. Keep every DB operation async: `cursor = await self._db.execute(...)`; `rows = await cursor.fetchall()`. Do not call an async connection/cursor from a sync callback, executor thread, or Chroma helper.
7. Parse via `json.loads`, require an object, reconstruct via `Procedure.from_dict()`, and require `procedure.id ==` the SQLite primary-key ID (never accept `from_dict`'s generated default or a mismatched snapshot ID). Reuse `_save_to_chroma()`'s exact document/metadata construction. Tighten that private method to report success, or factor an exception-raising core used by its normal log-and-degrade wrapper, so a valid-row write failure cannot look complete.
8. Malformed/non-object/ID-mismatched snapshot: log its SQLite ID and skip only that row. Valid-row index failure: abort, leave SQLite untouched, set the in-memory semantic collection to `None`, and leave on-disk state `rebuilding` so next start retries.
9. Verify Chroma count equals the number of valid reconstructed rows; then safely mark `procedure_index_state="ready"` with active model/backend and indexed count.
10. Empty SQLite creates an empty ready collection. Same-backend ready startup neither recreates nor reindexes.

The startup method returns only after a successful rebuild or explicit semantic-index degradation. Never delete/rewrite any SQLite row, including malformed snapshots.

Do not rebuild from Ship's Records.

### DD-5 — EvolutionStore gets real live persistence ownership

The current `getattr(runtime, "_chroma_client", None)` is phantom. Correct the live path:

1. Add optional `chroma_path: str | Path | None` to `EvolutionStore`, preserving all seven existing `chroma_client=` constructors.
2. Injected client: use it but do not own/close it. No client + path: `start()` creates and owns a `chromadb.PersistentClient` at that path. Neither: current in-memory fallback stays unchanged.
3. `_wire_self_improvement()` passes public `runtime.data_dir` as `chroma_path` and removes all `_chroma_client` access.
4. Add typed idempotent `EvolutionStore.stop()`: close only a client it created, clear references, permit restart.
5. If `start()` degrades after an unrecovered/ambiguous failure, preserve disk state, close and clear an owned client immediately, and retain caller ownership of an injected client.
6. Shutdown stops the owned EvolutionStore client in critical persistence before episodic Chroma shutdown, ensuring two clients on the same data root release deterministically.

No new config/database is introduced. The configured collection remains in the existing Chroma data root.

### DD-6 — EvolutionStore uses a verified shadow-copy transaction

`EvolutionStore` has no SQLite/Git source of truth. It must migrate from the existing Chroma collection itself.

Transition triggers on conflict, missing identity/stable-state, model/backend mismatch, or an interrupted BF-662 transaction. A fresh or proven canonical carries `bf662_state="stable"`; legacy missing state migrates once. Use raw `get_collection(..., embedding_function=None)` for source/recovery reads and let the active EF recompute embeddings.

#### Collision-safe temporary names

For canonical `C`:

- `owner = sha256(C.encode("utf-8")).hexdigest()[:12]`;
- `txn = uuid.uuid4().hex[:16]`;
- shadow = `bf662e-s-{owner}-{txn}`;
- backup = `bf662e-b-{owner}-{txn}`.

Names are independent of `len(C)`, below 63 characters, and use lowercase alphanumeric/hyphen only. Check `list_collections()` and regenerate on collision (bounded attempts), then still use `create_collection` so a race fails rather than reuses state.

Temporary metadata includes the full canonical name plus `bf662_owner`, `bf662_txn`, `bf662_role`, `bf662_state`, `bf662_source_count`, active model, and active backend ID. A matching name without matching metadata is not owned and must not be touched.

#### Exact persisted lesson shape

Copy exactly what is persisted today:

- ID = lesson ID;
- document = `Lesson.summary`;
- entire stored metadata dict (currently `category`, `source_proposal_id`, `outcome`, `timestamp`).

`payload` is not persisted; Chroma recall reconstructs `payload={}`. BF-662 must not claim payload recovery or add payload persistence. Copy the entire metadata dict so future keys survive.

#### Copy/swap/proof

1. Capture source count; page raw source with `get(limit=..., offset=..., include=["documents", "metadatas"])`.
2. Fail closed if a persisted row lacks the ID/document required to re-embed; do not synthesize content.
3. Add each page to a newly created active-EF shadow.
4. Read each batch back by ID and compare ID→(document, metadata) exactly; do not assume response order.
5. Recheck source count, shadow count, and exact contents. Mark shadow `ready` only after all checks pass.
6. Before the first rename, safely modify the source canonical's collection metadata to include this owner/txn, `bf662_role="backup"`, and verified source count while preserving model/backend. This makes the renamed backup self-identifying after a crash. Then rename canonical→backup and shadow→canonical via `Collection.modify(name=...)`. If a crash occurs after tagging but before rename, canonical remains authoritative; recovery clears/restarts that incomplete transaction.
7. Open canonical with active EF; verify active model/backend, count, exact rows against raw backup, and one text query when non-empty.
8. Only then is new canonical authoritative. While its transaction markers still pair it to the backup, delete the proven backup; then persist active identity with `bf662_state="stable"` and remove owner/txn/role markers. If a crash lands between those two cleanup steps, canonical/no-backup recovery proves it and finalizes stable metadata. Never copy old embeddings.

### DD-7 — EvolutionStore crash recovery authority

Recovery runs before normal open/create and verifies name plus full ownership metadata.

| On-disk phase | Authoritative copy |
|---|---|
| canonical only | canonical |
| canonical + copying/ready shadow | canonical; shadow is disposable |
| backup + ready shadow, canonical absent | backup |
| candidate canonical + backup | backup until candidate passes full active/content proof |
| proof complete | canonical |

Deterministic rules:

1. Canonical/no backup: prove raw readability; canonical remains authority. Delete only owned stale shadows after proof. If backend is old/missing, begin a fresh transition.
2. Canonical+matching backup: backup is rollback authority. If canonical opens active and exactly matches backup rows, promote/cleanup. Otherwise rename candidate canonical to a fresh owned failed-shadow name, rename backup→canonical, prove restoration, then delete failed candidate.
3. Canonical absent/exactly one owned backup: backup is authority. If one same-transaction ready shadow exactly matches and opens active, finish shadow→canonical and prove before deleting backup. Otherwise restore backup→canonical, prove, then delete only the invalid owned shadow.
4. Shadow without backup while canonical is absent, multiple plausible backups, marker disagreement, or unresolvable row mismatch: touch nothing, log-and-degrade to memory, and surface the stop condition. Never guess.
5. Rename collision/interruption re-enters this state machine. Never call `delete_collection(canonical_name)`.

Every ownership proof uses one strict parser. A transaction ID is exactly 16 lowercase hexadecimal characters. `bf662_source_count` is a native `int` (never `bool`) and is non-negative; strings, floats, and coercion are rejected. Required canonical-name, owner, transaction, role, state, and count fields must all exist. Valid role/state pairs are exactly `backup/backup`, `shadow/copying`, `shadow/ready`, and the refreshed rollback state `failed/failed`; a canonical transaction marker may only be `backup/backup` or `shadow/ready`.

Before any recovery rename, promotion, or deletion, re-discover the complete owner-prefixed temporary set. When a unique backup exists, every owned shadow/failed temporary must carry that backup's exact transaction and recorded source count. Any partially owned name, mismatched transaction, mismatched count, or malformed canonical marker preserves the complete collection snapshot and degrades without mutation. This applies equally to canonical-absent backup recovery and candidate-canonical + backup recovery. A rollback candidate keeps its paired `shadow/ready` marker until it has safely left the canonical name, then becomes `failed/failed`; this preserves pair-consistent restart authority at both rename boundaries.

`EvolutionStore.start()` remains synchronous because all Chroma calls are synchronous.

### DD-8 — One shared registered fake-EF module

Add `tests/fixtures/bf662_embedding_fakes.py` containing exactly two explicit-`__init__`, protocol-compliant, deterministic network-free EFs with unique fixed names/configs. Decorate each once there and import those same classes from every BF-662 test file. Exercise A→B and B→A.

Do not duplicate decorators/classes across test modules, mutate Chroma's registry, or use `SentenceTransformerEmbeddingFunction`, `DefaultEmbeddingFunction`, cached models, or network.

### DD-9 — Preserve CI forced-local behavior

`.github/workflows/ci.yml` already sets `PROBOS_EMBEDDINGS: local`. Do not change that workflow or `PROBOS_EMBEDDINGS` semantics. BF-662 must make forced-local more reconstructable, not replace it.

### DD-10 — Close only verified BF-662 lifecycle owners

The exact blast's non-exit authorizes lifecycle completion in the files already touched by BF-662:

- `runtime._activation_tracker` is the verified runtime owner exported from `CognitiveServicesResult`; the existing shutdown stop remains authoritative and idempotent.
- `ParticipantIndex` is injected through `episodic_memory.set_participant_index(...)`; real `EpisodicMemory.stop()` already owns it. `MockEpisodicMemory.stop()` must mirror that contract by stopping once, clearing the reference, and making a second stop a no-op.
- `runtime.capability_request_store`, `runtime.knowledge_edges`, `runtime.personal_ontology_prober`, and `runtime.rejection_cache` are live runtime-owned SQLite services with public async `stop()` methods and no other shutdown owner. Stop and clear each during service cleanup; one failure must not prevent the remaining services from closing.
- `EvolutionStore.stop()` and `ProcedureStore.stop()` are idempotent: two calls close each underlying owned client/database exactly once.

Do not infer or add lifecycle ownership for any other service. These six SQLite resources are included only because the exact BF-662 blast empirically retained their worker threads and live wiring verifies the ownership paths above.

## Implementation

### Section 1 — Register local EF and expose backend identity

Modify `src/probos/knowledge/embeddings.py`:

- Add the official registration import/decorator.
- Add `get_embedding_backend_id(embedding_function)` plus `get_active_embedding_backend_id()` with the exact deterministic name+config serialization in DD-2.
- Keep local name `probos-local-hash-v1`, dimension 384, stable BLAKE2 token hashing, and all existing BF-657 protocol methods.
- Do not alter `embed_text`, `compute_similarity`, or the forced-local switch.

### Section 2 — Make AD-584 sidecar backend-aware and sentinel-aware

Modify:

- `src/probos/startup/cognitive_services.py`
- `src/probos/cognitive/episodic.py`
- `src/probos/cognitive/episodic_mock.py`

Reference `src/probos/cognitive/schema_versions.py`; do not edit it. Keep the static base version and exact migration ID set.

Implementation:

- Add keyword-only `force_run: bool = False` to private `_run_one_migration()` and bypass only the version-current early return when true.
- Add `EpisodicMemory.embedding_migration_required(active_model_name, active_backend_id) -> bool`; it owns collection metadata inspection and safe-retries when metadata cannot be trusted.
- Require both positional arguments on real and mock implementations. Startup passes the exact active model/backend pair; no optional backend or internal re-resolution remains.
- At the AD-584 call, compute active backend ID and ask that public method whether migration is required.
- Extend `migrate_embedding_model` with backend identity; fresh/empty/rebuilt collections write both identity keys.
- Pass `version_hash=f"{MIGRATION_VERSIONS['AD-584']}:{backend_id}"` and `force_run=migration_required`.
- Remove/adjust `migrate_embedding_model`'s broad internal swallow so an operational failure reaches `_run_one_migration`; that wrapper owns honest-degrade. Keep migration metadata conflict-qualified until all re-adds finish, then write active model/backend. A failed force-run must not be reported/recorded as a clean zero-row migration.
- Record the qualified hash only after clean migration success.

Update `tests/test_ad818_schema_versions.py`:

- existing five migration IDs remain exactly unchanged;
- matching qualified hash skips when no sentinel;
- backend ID change runs and updates row;
- `force_run=True` runs despite a matching row;
- exception/timeout still records nothing.

### Section 3 — Lossless ProcedureStore reindex

Modify `src/probos/cognitive/procedure_store.py`:

- `start()` awaits `_init_chroma()`.
- `_init_chroma()` becomes async and owns conflict/recreate/reindex.
- Retain/close the owned Chroma client and use `procedure_index_state=rebuilding|ready` so an interrupted rebuild retries.
- Add one private async keyset-page helper and one async rebuild helper over the existing abstract connection/cursor API.
- Reuse `Procedure.from_dict()` and `_save_to_chroma()`'s document/metadata construction; make write success observable.
- Verify valid-row count before marking ready; malformed rows remain in SQLite and are logged/skipped.
- Ensure empty SQLite yields an empty ready collection; same-backend ready startup is idempotent.

Update `tests/test_procedure_store.py`; `tests/test_graduated_compilation.py` is blast-radius reference only:

- local fake A save → stop → fake B start: Chroma count remains 1, `find_matching`/collection query sees the row, SQLite still returns procedure;
- B→A transition same result;
- malformed one-row snapshot skips while valid rows reindex;
- same backend does not recreate/reindex;
- no network; real `tmp_path` SQLite and Chroma.

Any existing test patching `_init_chroma` must use `AsyncMock` after the signature change.

### Section 4 — Lossless EvolutionStore shadow transition

Modify `src/probos/cognitive/self_improvement/evolution_store.py`, `src/probos/startup/finalize.py`, and `src/probos/startup/shutdown.py`:

- Add active model/backend metadata and optional owned `chroma_path` lifecycle.
- Replace phantom runtime `_chroma_client` wiring with public `runtime.data_dir`; add shutdown cleanup before episodic Chroma close.
- Catch only recognized transition conditions for migration; generic failures preserve on-disk state and retain log-and-degrade.
- Implement DD-6 bounded copy/exact readback, rename swap, proof, cleanup, and DD-7 interrupted-state recovery.
- Preserve every persisted lesson ID/document/metadata key; payload is not persisted and remains out of scope.
- Do not copy embeddings; re-add documents so the active EF recomputes them.
- Use the one strict transaction parser and complete temporary-set coherence proof from DD-7 before every recovery rename/promotion/deletion.
- Close only the verified runtime-owned SQLite services from DD-10 so the exact blast exits naturally; repeated cleanup must not double-close.

Update `tests/test_ad482_self_improvement.py`:

- A→B and B→A preserve lesson count and recall;
- failures at copy and either rename boundary preserve/restore the authoritative copy;
- canonical+shadow, backup+shadow, and candidate-canonical+backup recover deterministically;
- same-backend start remains idempotent;
- empty-store transition succeeds;
- fallback with `chroma_client=None, chroma_path=None` remains unchanged.

### Section 5 — Fresh-process reconstruction regression

Add the shared fake module and update `tests/test_bf657_local_embedding_fallback.py`:

- assert `LocalHashEmbeddingFunction.name()` is present in Chroma's supported registry through the public reconstruction behavior, not by mutating internals;
- create a persistent local-EF collection, then run a **fresh Python subprocess** that imports `probos.knowledge.embeddings` and queries it without passing an EF explicitly; assert query succeeds and count/ID preserved;
- use `sys.executable`, `tmp_path`, argv list, `shell=False`, bounded timeout, repo-root `cwd`, copied offline/local env, and machine-readable child output;
- close the parent client before spawn and the child client in `finally` before Windows cleans `tmp_path`;
- compare backend identity across parent/child.

A same-process reopen alone is insufficient because creation auto-registers the class in that process and masks the bug.

## Do Not Build

- Do **not** change embedding algorithms, dimensions, similarity thresholds, recall scoring, or model selection.
- Do **not** download models or use network EFs in tests.
- Do **not** alter CI's `PROBOS_EMBEDDINGS=local` setting.
- Do **not** add a new database or SchemaVersionStore column/table.
- Do **not** make EvolutionStore dual-persist to SQLite; shadow migration is the scoped repair.
- Do **not** call `delete_collection` on the EvolutionStore canonical name at any phase.
- Do **not** rebuild procedures from Ship's Records when SQLite already contains `content_snapshot`.
- Do **not** persist/recover EvolutionStore payloads or claim they currently survive restart.
- Do **not** copy old embeddings, build a generic Chroma transaction framework, or redesign AD-584 into a shadow swap.
- Do **not** use Chroma private configuration/model fields or mutate its registry.
- Do **not** define fake A/B EF classes in more than the one shared fixture module.
- Do **not** add config, dependencies, UI, event types, or edit `config/system.yaml`.
- Do **not** add a new AD or edit `PROGRESS.md`/`DECISIONS.md`.
- Do **not** commit or push unless the Captain separately directs it.

## Tracking

- GitHub issue: #1028 remains the sole work item for BF-662.
- Do not edit `PROGRESS.md`, `docs/development/roadmap.md`, `DECISIONS.md`, or any era tracker in this build.
- No new AD/BF number and no issue close/comment are part of Builder execution.

## Files — exact 17-file intended commit

**Modify:**
- `src/probos/knowledge/embeddings.py`
- `src/probos/cognitive/episodic.py`
- `src/probos/cognitive/episodic_mock.py`
- `src/probos/startup/cognitive_services.py`
- `src/probos/cognitive/procedure_store.py`
- `src/probos/cognitive/self_improvement/evolution_store.py`
- `src/probos/startup/finalize.py`
- `src/probos/startup/shutdown.py`
- `tests/test_bf657_local_embedding_fallback.py`
- `tests/test_ad584_recall_qa_fix.py`
- `tests/test_ad818_schema_versions.py`
- `tests/test_procedure_store.py`
- `tests/test_ad482_self_improvement.py`
- `tests/test_bf296_shutdown_phase_ordering.py`

**Add:**
- `tests/fixtures/bf662_embedding_fakes.py`
- `prompts/bf-662-embedding-backend-transition-integrity.md`
- `prompts/bf-662-embedding-backend-transition-integrity-execution.md`

**Reference only:**
- `src/probos/cognitive/schema_versions.py`
- `src/probos/cognitive/procedures.py`
- `src/probos/protocols.py`
- `src/probos/runtime.py`
- `.github/workflows/ci.yml`
- `tests/test_graduated_compilation.py`
- `tests/test_ad818a_paginated_migrations.py`
- `tests/test_ad818a2_paginated_migrations.py`

The intended uncommitted patch is exactly these 17 files (14 modified source/test files plus three added files). If any other file is required, stop and return to the Architect before expanding scope.

## Exact acceptance tests

The Builder may share fixtures/helpers, but these named behaviors are required.

### `tests/test_bf657_local_embedding_fallback.py`

1. `test_local_ef_registered_once_and_reconstructable`
2. `test_backend_id_is_deterministic_and_config_sensitive`
3. `test_fresh_process_queries_registered_local_ef_without_explicit_argument`

### `tests/test_ad584_recall_qa_fix.py`

4. `test_embedding_migration_required_for_conflict_missing_and_mismatch`
5. `test_embedding_migration_required_same_backend_is_false`
6. `test_embedding_migration_writes_model_and_backend_identity`
7. `test_embedding_migration_failure_leaves_conflict_identity_and_propagates`

Update every existing `migrate_embedding_model(...)` call for the backend-ID parameter.

### `tests/test_ad818_schema_versions.py`

8. `test_matching_backend_qualified_version_skips`
9. `test_backend_change_runs_and_updates_qualified_version`
10. `test_force_run_bypasses_matching_qualified_version`
11. `test_force_run_failure_records_nothing`

The existing timeout/exception tests and exact-five-ID assertion remain green.

### `tests/test_procedure_store.py`

12. `test_transition_a_to_b_rebuilds_from_sqlite_losslessly`
13. `test_transition_b_to_a_rebuilds_from_sqlite_losslessly`
14. `test_rebuild_skips_malformed_snapshot_and_keeps_valid_rows`
15. `test_interrupted_rebuild_marker_retries_next_start`
16. `test_same_backend_ready_index_is_idempotent`
17. `test_empty_sqlite_transition_marks_empty_index_ready`
18. `test_stop_closes_owned_chroma_client`

Successful transitions assert Chroma count, `find_matching`, full SQLite `Procedure.from_dict` round-trip, and unchanged SQLite rows.

### `tests/test_ad482_self_improvement.py`

19. `test_runtime_wiring_uses_public_data_dir_not_phantom_client`
20. `test_transition_a_to_b_preserves_persisted_lesson_fields`
21. `test_transition_b_to_a_preserves_persisted_lesson_fields`
22. `test_mid_copy_failure_preserves_original_canonical`
23. `test_recovery_without_canonical_finishes_or_restores_from_backup`
24. `test_recovery_candidate_with_backup_validates_before_cleanup`
25. `test_invalid_candidate_rolls_back_to_backup`
26. `test_same_backend_start_is_idempotent_without_temp_collections`
27. `test_empty_store_transition_succeeds`
28. `test_shadow_names_are_bounded_valid_and_collision_safe`
29. `test_payload_remains_explicitly_unpersisted_across_transition`
30. `test_stop_closes_only_owned_client`

Failure tests inspect `list_collections()` and prove the authoritative canonical/backup still contains every persisted lesson ID/document/metadata field.

### `tests/test_bf296_shutdown_phase_ordering.py`

31. `test_shutdown_stops_evolution_store_before_episodic_memory`
32. `test_runtime_sqlite_sidecars_close_and_clear_despite_one_failure` (invoke cleanup twice; each service closes once)

### Final-correction regressions

33. `test_no_canonical_backup_with_mismatched_ready_shadow_degrades_without_mutation`
34. `test_candidate_backup_with_unrelated_shadow_degrades_without_mutation`
35. parameterized `test_no_canonical_partially_owned_temporary_degrades_without_mutation`
36. `test_mock_episodic_memory_participant_index_stop_is_idempotent`
37. `test_current_qualified_sidecar_with_required_predicate_runs_ad584` (fake requires and records both positional arguments)

Existing `test_stop_closes_only_owned_client` and `test_stop_closes_owned_chroma_client` are extended to call stop twice and assert each underlying owned close occurs exactly once.

## Test commands

Use a unique isolated data directory. All commands are serial and warnings-as-errors.

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

Do not use `-n auto`. Close every Chroma client and subprocess before test cleanup.

## Acceptance criteria

1. A fresh process that imports `probos.knowledge.embeddings` can reconstruct and query a persisted `probos-local-hash-v1` collection without explicitly passing an EF.
2. Backend identity is deterministic across process restart/JSON key order, changes with EF name/config, and invokes no model beyond existing active resolution.
3. AD-584 uses a backend-qualified sidecar; missing/mismatched/conflict metadata forces one run despite a matching sidecar; clean same-backend boots skip thereafter.
4. ProcedureStore preserves SQLite rows, valid semantic count, and queryability across A→B→A; malformed rows isolate; interrupted rebuild retries; empty/same-backend paths are idempotent.
5. EvolutionStore is persistent in standard runtime wiring through public `runtime.data_dir`, not phantom `_chroma_client`.
6. EvolutionStore preserves every persisted lesson ID/document/metadata field across A→B→A and failure/restart. It makes no claim to recover unpersisted payload.
7. Evolution canonical is never passed to `delete_collection`; backup stays authoritative until candidate active-EF and exact-content proof succeeds.
8. Canonical+shadow, backup+shadow, and candidate-canonical+backup crash states recover deterministically; ambiguous states touch nothing and degrade safely.
9. Temporary names are valid, bounded independent of canonical length, owner/transaction verified, and collision-safe.
10. Same-backend and empty-store startup are idempotent and leave no temp collections.
11. All Chroma clients/subprocesses close; unique test paths clean on Windows with warnings promoted to errors.
12. CI remains forced-local; A/B tests import the one shared registered fake-EF module; no model/network dependency is introduced.
13. Public methods are fully typed; `_init_chroma()` callers/tests match its async contract; existing episodic/procedure/evolution/finalize/shutdown suites pass.
14. Strict transaction parsing rejects coercion, malformed role/state pairs, and partial ownership; every temporary in a backup recovery transaction coheres before mutation, otherwise names/counts/IDs/documents/metadata remain byte-for-byte unchanged.
15. The real and mock migration predicates require the exact `(active_model_name, active_backend_id)` positional pair; a missing public API remains visibly failing.
16. The exact focused and blast commands return naturally with zero retained pytest processes; verified lifecycle owners close once across repeated cleanup.
17. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Stop conditions

Stop and return to the Architect if:

- an Evolution transition would call `delete_collection(canonical_name)`,
- no canonical exists and exactly one proven backup authority cannot be identified,
- a shadow/backup would be trusted by name alone without matching ownership metadata and exact row proof,
- any owned/partially owned temporary disagrees with the unique backup transaction or recorded source count before a recovery mutation,
- raw copy would open a conflicted collection with an EF/default rather than explicit `embedding_function=None`,
- Chroma private state, registry mutation, or a SchemaVersionStore schema change becomes necessary,
- ProcedureStore rebuild cannot remain inside the async abstract connection/cursor API,
- deterministic identity would require an extra model download or nondeterministic serialization,
- tests require a cached/network model, duplicate fake registration, sleeps, order dependence, or leaked Windows handles,
- any file outside the exact 17-file intended commit is required,
- unrelated tracked changes appear,
- or scope expands into embedding quality/routing/scoring, payload persistence, or a generic migration framework.

## Verified Against Codebase (2026-07-11, HEAD `d64920ac686c323a29feba561df24315955182a3`)

### Live repository evidence

```text
rg -n "class LocalHashEmbeddingFunction|def get_collection_embedding_function|def get_active_embedding_model_name" src/probos/knowledge/embeddings.py
    117 class LocalHashEmbeddingFunction(EmbeddingFunction[Documents]):
    211 def get_collection_embedding_function() -> Any:
    223 def get_active_embedding_model_name() -> str:

rg -n "self._init_chroma\(\)|def _init_chroma|delete_collection\(\"procedures\"\)|def _save_to_chroma" src/probos/cognitive/procedure_store.py
    156 self._init_chroma()
    274 def _init_chroma(self) -> None:
    314 client.delete_collection("procedures")
    434 def _save_to_chroma(self, procedure: "Any") -> None:

rg -n "class Lesson|def start|def record_lesson|payload=\{\}" src/probos/cognitive/self_improvement/evolution_store.py
    24 class Lesson:
    56 def start(self) -> None:
    82 def record_lesson(
    169 payload={},

rg -n "migrate_embedding_model|__ef_conflict__|Ensure collection metadata" src/probos/cognitive/episodic.py
    636 async def migrate_embedding_model(
    1325 self._collection.modify(metadata={"embedding_model": "__ef_conflict__"})
    1331 # AD-584: Ensure collection metadata includes embedding model name

rg -n "_run_one_migration|schema_store.is_current|AD-584: Embedding model migration|version_hash=MIGRATION_VERSIONS" src/probos/startup/cognitive_services.py
    37 async def _run_one_migration(
    68 if await schema_store.is_current(migration_id, version_hash):
    413 # AD-584: Embedding model migration (re-embed if model changed)
    427 version_hash=MIGRATION_VERSIONS["AD-584"],

rg -n "_wire_self_improvement|_chroma_client|runtime.evolution_store" src/probos/startup/finalize.py src/probos/runtime.py
    src/probos/startup/finalize.py:1832 def _wire_self_improvement(...)
    src/probos/startup/finalize.py:1876 chroma_client = getattr(runtime, "_chroma_client", None)
    src/probos/startup/finalize.py:1963 runtime.evolution_store = evolution_store
    src/probos/runtime.py:947 self.evolution_store: Any | None = None
    src/probos/runtime.py:1547 def data_dir(self) -> Path:
```

`git log 509e8cd7..HEAD` contains BF-659/660/663/661. In the BF-662 target set, those commits changed only `startup/finalize.py` and `startup/shutdown.py`; both were reread at current HEAD.

AST audit found 26 real `ProcedureStore(...)` constructors across 12 test files, seven `EvolutionStore(...)` constructors in `tests/test_ad482_self_improvement.py`, and exactly one `_init_chroma` test patch (`tests/test_procedure_store.py`, current line pattern 239).

`DatabaseConnection.execute()` and cursor `fetchall()` are async protocol seams (`src/probos/protocols.py`, current line patterns 199–222). `Procedure.from_dict()` is at current line pattern 132 and reconstructs the fields emitted by `Procedure.to_dict()`.

Evolution persistence today stores summary as the document and metadata `category`, `source_proposal_id`, `outcome`, `timestamp`; recall explicitly returns `payload={}`. Runtime shutdown closes episodic memory at current line pattern 421 and ProcedureStore at 810–813, but has no EvolutionStore stop. CI still sets `PROBOS_EMBEDDINGS: local` at `.github/workflows/ci.yml` line pattern 27.

### Installed ChromaDB 1.5.8 evidence

Read-only temporary probes established:

- official registration stores `cls.name()`; persisted config loading calls `build_from_config` and emits decorator guidance when absent;
- same-process creation auto-registers an EF type, so same-process reopen masks the fresh-process defect;
- explicit `get_collection(name, embedding_function=None)` returned raw `count/get` after removing the persisted EF class from the registry;
- implicit/default query then failed reconstruction, and explicit wrong-EF open raised the verified conflict;
- `list_collections`, `get_collection`, `delete_collection`, and missing-collection errors behaved as specified;
- `Collection.modify(name=...)` preserved rows/metadata; rename collision raised uniqueness failure;
- canonical→backup plus shadow→canonical preserved exact rows and active-EF queryability before backup deletion;
- active name validation accepted lengths 3/63/64/512 and rejected 2/513, bad endpoints, `..`, and IPv4-looking names; BF-662 names stay below 63;
- `Collection.configuration` reconstructed registered `name/config`, while raw copy avoided it;
- `Client.close()` is public/idempotent and releases persistent resources needed for Windows temp cleanup.
