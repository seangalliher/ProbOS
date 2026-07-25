# BF-669 — Expected-idempotent reflection writes without warning noise or false creation counts

**Verdict:** APPROVED FOR BUILDER HANDOFF — BLOCKED: BF-668 EXACT-BASE CI FAILED
**One-line:** Make the authoritative episodic write boundary return a typed outcome, classify only fully proven AD-599 replays as expected duplicates, count only newly persisted reflections, and serialize the write-once decision without weakening collision warnings.

**Status:** Architect-ready but not executable; exact-base CI run `29351723371` failed its Python job (one Git debounce test), so BF-669 must not start until BF-668 CI is green on this unchanged base or the Architect re-verifies a replacement base
**Type:** Bug fix — **BF-669**; no new AD and no `DECISIONS.md` entry
**GitHub issue:** #1035 — https://github.com/seangalliher/ProbOS/issues/1035
**Exact base HEAD:** `2417bfb97d48fb9a867c387bf9e8eb71365550d6`
**Base commit:** `BF-668: classify IntentBus handler latency (closes #1034)`
**Numbering verified:** highest shipped entries at this base are **AD-1121** and **BF-668**; issue #1035 reserves BF-669
**Dependencies:** AD-541b, AD-541e, AD-567b, AD-570b, AD-599, AD-601, AD-610, AD-671, AD-873, AD-959, BF-207, BF-633, BF-662, BF-668
**License disposition:** none — standard-library `StrEnum`/`asyncio.Lock` only; no dependency or absorbed external code
**Estimated tests:** 14–20 additions/updates in existing files; no new source or test file

## Scope

Repair only the episode-store outcome contract and AD-599 Step 15's use of it.

The implementation must guarantee:

1. `EpisodicMemory.store()` returns a typed `EpisodeStoreOutcome` while every existing caller that ignores the return stays source-compatible;
2. `UNEXPECTED` remains the default duplicate policy for all 33 current production store awaits;
3. only `EXPECT_SAME_REFLECTION` plus exact AD-599 identity/provenance/content proof converts a same-ID replay to a DEBUG-level `DUPLICATE`;
4. same-ID different-content, malformed reflection IDs, wrong source, wrong anchor, wrong reflection envelope, and default-policy repeats remain unexpected WARNING collisions with full IDs and hash prefixes;
5. no duplicate path overwrites, upserts, deletes, reinserts, updates TCM, writes FTS/participant sidecars, schedules review/evolution, or evicts;
6. `SKIPPED` represents admission/non-storage paths, never a write;
7. one runtime-local lock serializes the authoritative existing-ID read and, only for new IDs, the existing synchronous admission/transformation sequence, TCM update, and Chroma add, including `__new__`-constructed test instances;
8. the lock is released before the first secondary await, and before reconsolidation/evolution/eviction work;
9. concurrent identical reflection calls yield exactly one `STORED` and one `DUPLICATE`, one authoritative Chroma row, and no overwrite;
10. Chroma's silent duplicate-add behavior is never mistaken for a successful write;
11. Step 15 passes the explicit expected-reflection policy and increments `created` only on `STORED`;
12. deterministic replay returns zero newly created, emits no “Created” INFO, creates no reflection WM priming entry, and leaves the first episode authoritative;
13. ordinary backend exceptions and cancellation continue to propagate from `store()`; Step 15 continues to honest-degrade ordinary failures per candidate and propagate cancellation; and
14. episode hashing, deterministic reflection ID format, candidate order/cap, attribution, recall, Ebbinghaus decay, migration, secondary persistence, and shutdown behavior remain unchanged.

No broad episodic-store migration, warning suppression, ID-format change, distributed lock, database dedup table, UI, dependency, AD, or dream-selection redesign is authorized.

---

## Problem, exact base, live evidence, and verified root cause

At the exact base:

- `src/probos/cognitive/episodic.py:1597` exposes `async def store(self, episode: Episode) -> None`.
- `src/probos/cognitive/episodic.py:1599-1662` returns `None` for collection-unavailable, StorageGate REJECT/MERGE, MemorySecurityGate REJECT, rate-limited, and similar-content-deduplicated paths. The caller cannot distinguish any skip from a new write.
- `src/probos/cognitive/episodic.py:1704-1711` performs AD-541b's same-ID read, logs every hit at WARNING, truncates the ID with `episode.id[:12]`, and returns `None`.
- `src/probos/cognitive/episodic.py:1720-1738` updates TCM and then calls Chroma `add()` after that read. No lock spans read/update/add.
- `src/probos/cognitive/episodic.py:1743-1784` performs FTS5, participant-index, reconsolidation, retroactive-evolution, and eviction work after primary add. The first two are secondary awaits; none belongs in the write-once decision window.
- `src/probos/cognitive/episodic.py:1012-1040` owns canonical episode SHA-256 hashing. `_episode_to_metadata()` stores the canonical `content_hash` at `:3299`; `_metadata_to_episode()` reconstructs the stored episode at `:3415`.
- `src/probos/cognitive/episodic.py:1463-1536` provides a nearby count-return precedent for warm-boot `seed()`, but it is a separate bulk path and remains unchanged.
- `src/probos/cognitive/episodic_mock.py:90-95` always appends and returns `None`; it does not model write-once IDs. A verified two-run probe stored the same deterministic reflection ID twice and reported `first_created=1`, `second_created=1`, `stored_count=2`.
- `src/probos/protocols.py:41-46` declares `EpisodicMemoryProtocol.store(...) -> None`.
- `src/probos/cognitive/dreaming.py:2795-2953` owns AD-599 Step 15. It creates IDs as `reflection-` plus the first 16 lowercase SHA-256 hex characters of the exact `content_text` at `:2905-2907`, sets `source=MemorySource.REFLECTION`, `anchors.trigger_type="dream_consolidation"`, `dag_summary.type="reflection"`, `dag_summary.source="dream_consolidation"`, and `reflection == user_input == content_text`, then unconditionally increments `created` after every non-raising `store()` at `:2944-2945`.
- `src/probos/cognitive/dreaming.py:1652-1686` carries that count into the Step 15 INFO log and into the partial `DreamReport` passed to the AD-671 WM bridge.
- `src/probos/cognitive/dream_wm_bridge.py:132-136` turns any positive `reflections_created` into a “Created N reflection episodes” priming insight. The false count therefore affects both logs and learning context.
- `src/probos/cognitive/dreaming.py:292-380` proves shutdown uses `consolidate_for_shutdown()`, explicitly performs no episodic-collection writes, and does not run Step 15. BF-669 must preserve that.
- There are 33 live production awaits of an episodic `store()`-shaped call; no production caller assigns or returns its result. A typed return is therefore source-compatible for ignored-result callers. Only AD-599 Step 15 becomes an outcome consumer.
- There is no existing episode duplicate exception. A narrow `PairingAlreadyExists` exists in an unrelated SQLite pairing subsystem, while Chroma does not expose an equivalent reliable signal here.
- Existing duplicate APIs elsewhere sometimes return `bool` or `(value, reason)`, but those cannot truthfully distinguish `STORED`, `DUPLICATE`, and `SKIPPED`; a typed three-way outcome is required.

### Empirical fail-before reproduction (local embedding, real Chroma)

A clean read/write probe in a temporary store at this base produced:

```text
Episode reflection-4 already exists — skipping store (write-once)
first_created=1 second_created=1 stored_count=1
```

The first row is preserved, but the second deterministic replay is falsely counted as created.

A same-ID conflicting-content probe produced:

```text
Episode same-id already exists — skipping store (write-once)
first_return=None second_return=None stored_count=1 user_input=authoritative first
```

Write-once preservation is correct; outcome and diagnostic specificity are not.

### Chroma duplicate-add behavior (verified, ChromaDB 1.5.8 environment)

A forced second `collection.add()` using the same ID but different content returned normally, retained count `1`, and preserved the first document/content. Therefore:

- `add()` returning normally is not proof that this caller created the row;
- catching a duplicate exception is not a viable design; and
- the store-owned lock/read/compare/add decision is required for a truthful local outcome.

### Live retained-log evidence (read-only, 2026-07-14)

Across six retained `%LOCALAPPDATA%\ProbOS\data\logs\probos.log*` files:

- **240** write-once duplicate WARNINGs;
- **240/240** are `Episode reflection-*`; **0** are non-reflection IDs;
- **240/240** are followed within two lines by an AD-599 “Created ... reflection episodes” INFO;
- **239** display the ambiguous truncated `reflection-8`; **1** displays `reflection-f`;
- **1,637** AD-599 created INFO lines are retained.

Read-only inspection of the live authoritative collection resolved `reflection-8` to multiple full AD-599 IDs, including:

- `reflection-856c1fd0a359a278`; and
- `reflection-8dfdd9fbc24510a2`.

For each inspected AD-599 row:

- the 16-character ID suffix exactly equals `sha256(user_input.encode()).hexdigest()[:16]`;
- `source == "reflection"`;
- `source_type == "reflection"`;
- `anchor_trigger_type == "dream_consolidation"`;
- `dag_summary.type == "reflection"`; and
- `dag_summary.source == "dream_consolidation"`.

This is expected deterministic replay evidence, not evidence of overwrite or corruption. The same generic warning must still remain for all cases that fail that full proof.

---

## Issue-contract corrections and clarifications

Issue #1035 is directionally correct. The following points are binding corrections/clarifications for the build:

1. **Typed outcome, not `bool`, wins.** `bool` collapses a policy/admission `SKIPPED` with an already-authoritative `DUPLICATE`; Step 15 needs to count only `STORED`, and diagnostics/tests need all three states.
2. **Do not catch a duplicate exception at the dreaming owner.** Chroma `add()` can return normally on a duplicate ID and preserve the first row. Backend behavior cannot provide the truth Step 15 needs.
3. **`DUPLICATE` does not mean “equivalent” globally.** It means the ID was already authoritative and no write occurred. Policy controls log classification. An unexpected or conflicting same-ID collision still returns `DUPLICATE`, logs WARNING, and preserves the first row. Do not invent a fourth outcome for “conflict.”
4. **`SKIPPED` is admission only.** It covers unavailable collection and existing pre-write gates (StorageGate REJECT/MERGE, security REJECT, rate limit, similar-content dedup). It is not used for same-ID collisions or backend failures.
5. **Exact reflection equivalence is semantic, not full dataclass equality.** AD-599 creates `now = time.time()` once per run, so a valid rerun has a different timestamp and therefore a different canonical episode `content_hash`. Ebbinghaus/reconsolidation can also change retention metadata after the first write. Requiring full dataclass equality or direct `compute_episode_hash(existing) == compute_episode_hash(incoming)` would misclassify expected reruns.
6. **Canonical equivalence reuses the existing hash projection with timestamp neutralized.** Compare `compute_episode_hash(dataclasses.replace(ep, timestamp=0.0))` for existing/incoming. This preserves the existing canonical-content field set (user input, DAG, outcomes, reflection, agent attribution, duration, Shapley, trust deltas, source) while ignoring only the producer's fresh timestamp. Separately prove the deterministic ID and dream anchor/envelope. Do not expand or version the canonical hash in BF-669.
7. **No “reflection source alone” carve-out.** Other features also use `MemorySource.REFLECTION` (for example WM summaries and dream interpretation). Only AD-599's deterministic envelope qualifies.
8. **The lock is runtime-local, not cross-process.** It closes concurrent coroutines sharing one `EpisodicMemory` instance. Do not add a distributed lock, file lock, SQLite dedup table, or Chroma migration.
9. **The lock protects primary authority only.** Hold it across the authoritative existing-ID read and the new-ID synchronous admission/transformation + TCM + add sequence. Release it before FTS5/participant/reconsolidation/evolution/eviction work. This is the smallest truthful contract and follows issue #1035.
10. **Cancellation is not an outcome.** `CancelledError` is a `BaseException` on Python 3.12. `store()` must propagate it; Step 15 must not count/log it as an ordinary failure. If cancellation occurs after primary add in a secondary await, the row remains authoritative and cancellation still propagates, matching current behavior.
11. **Transient backend failure is not `SKIPPED`.** Read/add exceptions propagate from `store()` unchanged; Step 15 catches ordinary `Exception`, logs DEBUG with the full ID and context, does not increment, and proceeds to the next candidate. No retry is added.
12. **No new event or public metric is required.** Existing public observability is `DreamReport.reflections_created`, Step 15 INFO, and AD-671 WM priming. Duplicate/skipped behavior is log-only in BF-669. Do not add event types, counters, API fields, or persistence.
13. **Mock/protocol alignment is scoped.** Update the canonical `MockEpisodicMemory`, `probos.protocols.EpisodicMemoryProtocol`, and the two reflection-owner test doubles that Step 15 consumes. Do not sweep every local fake in the repository: ignored-return consumers remain source-compatible.
14. **No KnowledgeStore change.** AD-599 Step 15 writes only through `episodic_memory.store()`; it does not dual-write the Git-backed KnowledgeStore. Runtime's DAG path separately invokes `KnowledgeStore.store_episode()`. BF-669 must not create a new reflection persistence path.
15. **No shutdown change.** AD-959 shutdown consolidation deliberately skips Step 15 and episodic writes. BF-669 must not add reflection work to shutdown or change scheduler drain/order.

---

## Pinned design decisions

### DD-1 — Shared typed policy and outcome in `probos.types`

Add adjacent to `MemorySource`:

```text
class EpisodeDuplicatePolicy(StrEnum):
    UNEXPECTED = "unexpected"
    EXPECT_SAME_REFLECTION = "expect_same_reflection"

class EpisodeStoreOutcome(StrEnum):
    STORED = "stored"
    DUPLICATE = "duplicate"
    SKIPPED = "skipped"
```

Requirements:

- exact names and values above;
- no dataclass/result wrapper; no payload/reason field;
- no exception subclass;
- no config flag;
- no `__bool__` behavior;
- no re-export change in `probos.__init__`;
- use actual enum values at runtime — do not silently coerce arbitrary strings.

The enum lives in shared types because `episodic.py`, `episodic_mock.py`, `dreaming.py`, and `protocols.py` all consume the contract without importing one cognitive implementation from another.

### DD-2 — Exact additive public store signature

Change both real and mock implementations, and the service protocol, to:

```text
async def store(
    self,
    episode: Episode,
    *,
    duplicate_policy: EpisodeDuplicatePolicy = EpisodeDuplicatePolicy.UNEXPECTED,
) -> EpisodeStoreOutcome:
```

Boundary rules:

- `duplicate_policy` is keyword-only;
- reject a raw string or any non-enum value with `TypeError` before evaluating admission gates or mutating state;
- every existing `await store(episode)` remains valid and defaults to unexpected-collision diagnostics;
- ignored return values remain valid;
- no caller-side `exists()` check;
- no positional policy argument;
- no broad caller migration.

`probos.protocols.EpisodicMemoryProtocol` must import `Episode`, `EpisodeDuplicatePolicy`, and `EpisodeStoreOutcome` in a cycle-safe way and match exactly. The boot-camp-local protocol is count-only and remains unchanged.

### DD-3 — Outcome mapping is explicit

`EpisodicMemory.store()` returns:

| Path | Outcome / exception |
|---|---|
| `_collection` unavailable | `SKIPPED` |
| StorageGate `REJECT` | `SKIPPED` |
| StorageGate `MERGE` (deferred path) | `SKIPPED` |
| MemorySecurityGate `REJECT` | `SKIPPED` |
| per-agent rate limit | `SKIPPED` |
| similar-content dedup | `SKIPPED` |
| existing same ID under any policy | `DUPLICATE` after policy-specific logging |
| successful authoritative Chroma `add()` | `STORED` |
| existing gate evaluation failure | preserve current log-and-allow behavior, then continue |
| primary get/add/backend error | propagate; no outcome |
| cancellation anywhere | propagate; no outcome |

`STORED` means the primary Chroma row was newly persisted by this call. Secondary sidecar failures continue to log-and-degrade and do not retract `STORED`. If a secondary await cancels after primary add, cancellation propagates; do not fabricate an outcome to the cancelled caller.

Every `SKIPPED` path retains its current diagnostic at its current level and must include enough reason context to identify the admission decision. The no-collection path currently has no diagnostic; add one DEBUG stating that the episode was not persisted because the primary collection is unavailable. Step 15 must not add a second skip log.

### DD-4 — Runtime-local write-once lock and exact lock window

In `EpisodicMemory.__init__()`, create one private `asyncio.Lock` dedicated to the normal store write-once decision. Name may vary, but it must not reuse an unrelated lock or a per-ID unbounded lock dictionary.

Because existing tests construct `EpisodicMemory.__new__(EpisodicMemory)` and call `store()`, add one private synchronous accessor that lazily creates/attaches the lock when absent. The accessor contains no await and is called on the event-loop thread before acquisition. It must return an actual `asyncio.Lock`; a malformed pre-existing attribute is an internal contract error, not silently accepted.

After policy validation and the existing no-collection `SKIPPED` guard, acquire the lock. Execute exactly this primary authority window under it:

1. authoritative `collection.get(ids=[episode.id], include=["metadatas", "documents"])` **before stateful admission gates**;
2. if existing, classify/log and return `DUPLICATE` without evaluating/mutating StorageGate, rate/content dedup, TCM, or any secondary side effect;
3. only for a new ID, run the existing admission/transformation sequence in its current relative order: StorageGate → MemorySecurityGate → rate limit → similar-content dedup → importance → affect → anomaly stamp;
4. build the final incoming metadata/document used for persistence;
5. update TCM and inject its vector into incoming metadata;
6. `collection.add(...)`;
7. exit the lock.

Then run existing FTS5, participant-index, reconsolidation, retroactive-evolution, and eviction work exactly once for `STORED` outside the lock.

The early same-ID fast path is intentional: same-ID authority must be classified before stateful generic dedup can turn a concurrent deterministic replay into `SKIPPED`. For a genuinely new ID, every existing gate and transformation still runs in the same order as HEAD. A duplicate is a no-write operation, so bypassing new-write admission side effects is the truthful behavior.

Hard constraints:

- no await while holding the lock (the primary Chroma calls and TCM update are currently synchronous);
- no await while any admission gate/transformation runs inside the lock;
- no lock around secondary sidecars, reconsolidation/evolution, or eviction;
- no caller-side precheck;
- no `upsert`, `update`, `delete`, or retry;
- no per-ID lock cache;
- no class/global/process/distributed/file lock;
- do not change `seed()`, migrations, metadata-only updates, or `_force_update()`;
- an exception or cancellation must release the lock through `async with`.

A real concurrent test must force one task to wait while the other owns the lock, then prove one `STORED`, one `DUPLICATE`, one row, and first-write authority. Do not fake concurrency with two sequential calls only.

### DD-5 — Exact expected AD-599 reflection proof

Create a private, pure helper in `episodic.py` that classifies an existing/incoming pair as the expected AD-599 replay. It may accept reconstructed `Episode` objects or the existing metadata/document plus incoming episode, but the behavior is fixed.

First compute a private timestamp-neutral canonical-content fingerprint by applying the existing `compute_episode_hash()` to `dataclasses.replace(episode, timestamp=0.0)`. This helper must not change `compute_episode_hash()`, `_HASH_VERSION`, metadata serialization, or the stored hash.

Return true only when **all** of the following hold for both existing and incoming records:

1. ID matches exact regex `^reflection-[0-9a-f]{16}$`;
2. each ID suffix equals `sha256(user_input.encode("utf-8")).hexdigest()[:16]`;
3. `user_input` values are exactly equal;
4. `reflection` values are exactly equal and exactly equal to `user_input`;
5. `source == MemorySource.REFLECTION.value`;
6. anchors exist and `trigger_type == "dream_consolidation"`;
7. `dag_summary["type"] == "reflection"`;
8. `dag_summary["source"] == "dream_consolidation"`;
9. timestamp-neutral canonical-content fingerprints are exactly equal; this covers full DAG equality (including `involved_agents`), `agent_ids` (AD-980b attribution), outcomes, duration, Shapley values, trust deltas, source, user input, and reflection; and
10. the AD-599 envelope is internally valid: `outcomes == []`, `duration_ms == 0.0`, `shapley_values == {}`, and `trust_deltas == []`.

The helper must honest-fail closed (`False`) on malformed/missing metadata/JSON. It must not call recall, FTS, embeddings, or mutate either episode.

Why timestamp is ignored: AD-599 sets a fresh `now` each Step 15 run, and `compute_episode_hash()` intentionally includes timestamp. The deterministic identity is the 16-hex hash of `content_text`, not the full timestamp-bearing episode hash. Anchor fields outside `trigger_type` and retention/store-derived fields outside the existing canonical hash (for example anomaly-window stamps, strength/stability, source_type/confidence) are not part of AD-599 content identity and must not create false conflicts.

### DD-6 — Policy-specific duplicate diagnostics preserve write-once integrity

On an existing ID:

#### Expected exact replay

Only when `duplicate_policy is EXPECT_SAME_REFLECTION` **and** DD-5 passes:

- return `DUPLICATE`;
- emit one DEBUG with full ID, `policy=expect_same_reflection`, incoming/existing canonical episode-hash prefixes, and the statement that the existing write remains authoritative;
- emit no WARNING/INFO/ERROR;
- do not touch primary/secondary stores or learning side effects.

#### Unexpected or conflicting collision

For every other existing-ID case — including default policy, malformed ID, wrong source/anchor/DAG envelope, content mismatch, attribution mismatch, or same content under `UNEXPECTED`:

- return `DUPLICATE`;
- emit one WARNING with full ID, policy value, reason, incoming/existing timestamp-bearing canonical episode-hash prefixes, and the statement that the existing write remains authoritative;
- do not overwrite or update anything.

Reason mapping is exact:

- `duplicate_policy is UNEXPECTED` → `reason=unexpected_duplicate` (ordinary direct-ID collision; content equality does not make it expected);
- `duplicate_policy is EXPECT_SAME_REFLECTION` but any DD-5 proof fails, including canonical-content mismatch or unreadable existing metadata → `reason=content_conflict`.

Do not log content bodies, embeddings, prompts, or full hashes. Use 12-character hash prefixes; use the full episode ID. The expected DEBUG must state `equivalence=timestamp_neutral` because its timestamp-bearing hash prefixes normally differ.

### DD-7 — Canonical mock implements the same write-once contract

`MockEpisodicMemory.store()` must:

- accept the exact signature/policy enum;
- reject non-enum policy values before mutation;
- serialize store decisions with one instance-local `asyncio.Lock`, lazily available for any bypassed construction if necessary;
- find existing records by exact `Episode.id`;
- use the same private pure reflection-equivalence helper as the real implementation rather than duplicating the rules;
- return `DUPLICATE` and preserve the first episode on same-ID hits;
- use the same DEBUG/WARNING policy classification;
- append/evict only on `STORED` and return `STORED`;
- never create two list entries with the same ID.

Do not add Chroma/SQLite behavior to the mock. Its substring recall behavior and capacity eviction stay unchanged.

### DD-8 — Step 15 owns expected policy and truthful creation accounting

In `_step_15_reflection_promotion()`:

```text
outcome = await self.episodic_memory.store(
    episode,
    duplicate_policy=EpisodeDuplicatePolicy.EXPECT_SAME_REFLECTION,
)
if outcome is EpisodeStoreOutcome.STORED:
    created += 1
elif outcome in (EpisodeStoreOutcome.DUPLICATE, EpisodeStoreOutcome.SKIPPED):
  pass  # storage boundary already owns duplicate/admission diagnostics
else:
    raise TypeError(...)
```

Pinned behavior:

- only `STORED` increments;
- `DUPLICATE` and `SKIPPED` do not increment and Step 15 emits no additional log; the storage boundary emits the one policy-specific duplicate diagnostic, while existing admission paths retain their current diagnostics;
- an invalid return (`None`, raw string, bool, wrong enum) is a dependency-contract error, handled by the existing per-candidate ordinary-exception path: DEBUG with full ID, zero increment, continue to later candidates;
- existing `_make_engine()` AsyncMock and `_RecordingEpisodic` test doubles must return `STORED` explicitly so tests model the real contract;
- ordinary store `Exception` remains per-candidate honest-degrade and permits later candidates to proceed;
- `CancelledError` propagates unchanged;
- no caller-side exists/precheck;
- deterministic ID generation, candidate order, first-N cap, timestamp creation, content, importance, attribution, and return type (`int`) remain unchanged.

At the caller in `dream_cycle()`:

- Step 15 INFO fires only when `reflections_created > 0`, now meaning newly persisted rows;
- the final and partial `DreamReport.reflections_created` use the same truthful count;
- AD-671 WM priming receives no reflection-created insight on an all-duplicate rerun;
- no new duplicate/skipped public count is added to `DreamReport`.

### DD-9 — Exception, cancellation, and side-effect semantics

- Primary read/add failure propagates from `EpisodicMemory.store()`; no broad catch is added there.
- Step 15 catches ordinary `Exception` per candidate, logs DEBUG with full ID and that the candidate was not counted, then continues.
- `CancelledError` must pass through both layers. Do not add `except BaseException` or a cancellation-to-`SKIPPED` conversion.
- TCM updates occur only inside the primary write lock immediately before a successful add attempt. A duplicate never drifts TCM.
- Secondary sidecar ordinary errors retain current log-and-degrade behavior. They do not change `STORED` because primary authority exists.
- Secondary cancellation after primary add still propagates. The row remains authoritative; a replay will return `DUPLICATE`.
- Lock release is guaranteed before the first secondary await and before any exception/cancellation leaves the primary window.

### DD-10 — No broad storage or lifecycle migration

BF-669 does not change:

- `Episode`, `AnchorFrame`, or `DreamReport` fields;
- `compute_episode_hash()` inputs/version/normalization;
- reflection 16-hex deterministic ID format;
- Chroma collection/schema/embedding function;
- FTS5 schema or query behavior;
- ParticipantIndex schema/contract;
- KnowledgeStore persistence;
- warm-boot `seed()` semantics;
- migration, rebuild, backup, or embedding-transition paths;
- content similarity/rate limit/storage/security gate policy;
- Ebbinghaus strength/stability, activation pruning, reconsolidation schedule;
- dream candidate generation/order/cap/importance/attribution;
- scheduler cadence, full-dream events, micro-dream, shutdown consolidation, drain, or clean marker;
- recall/learning/trust/Hebbian behavior except removing false reflection-created WM priming on duplicate-only reruns.

---

## Exact file allowlist

### Production files the Builder may modify

- `src/probos/types.py` — `EpisodeDuplicatePolicy` and `EpisodeStoreOutcome` only.
- `src/probos/cognitive/episodic.py` — typed store contract, lazy runtime-local lock, exact reflection proof, policy-specific duplicate diagnostics/outcomes.
- `src/probos/cognitive/episodic_mock.py` — matching write-once/outcome/policy contract.
- `src/probos/cognitive/dreaming.py` — explicit expected policy and `STORED`-only creation count.
- `src/probos/protocols.py` — exact `EpisodicMemoryProtocol.store()` signature/return.

### Existing tests the Builder may modify

- `tests/test_ad541b_reconsolidation.py` — real-store write-once outcomes, warnings, concurrent race, no overwrite/upsert.
- `tests/test_ad599_reflection_episodes.py` — Step 15 policy, truthful count/log/exception/cancellation/deterministic replay.
- `tests/test_episodic.py` — canonical mock outcomes/write-once parity/capacity.
- `tests/test_episodic_chromadb.py` — real Chroma store outcome and row authority.
- `tests/test_ad541e_content_hashing.py` — content/hash conflict diagnostics and hash preservation.
- `tests/test_ad598_importance_scoring.py` — `__new__` lazy-lock regression and importance path.
- `tests/test_ad601_tcm_temporal_context.py` — TCM update only for `STORED`, not duplicate.
- `tests/test_ad608_retroactive_evolution.py` — evolver only after `STORED`.
- `tests/test_ad610_storage_gating.py` — `SKIPPED` outcome for admission rejection.
- `tests/test_ad673_anomaly_window.py` — transformed final episode persists correctly through the lock.
- `tests/test_ad1037_affect_capture.py` — `__new__` lazy-lock regression and affect path.
- `tests/test_ad979e_reconsolidation.py` — write-once metadata authority remains intact.
- `tests/test_ad980b_dream_attribution.py` — recording fake returns `STORED`; attribution mismatch is conflicting.
- `tests/test_ad671_dream_wm_integration.py` — duplicate-only reflection count produces no priming insight.
- `tests/test_ad573d_dream_to_working_memory.py` — existing dream summary behavior unchanged.
- `tests/test_ad873_episode_decay.py` — decay/dream interaction unchanged.
- `tests/test_dreaming.py` — full-cycle report/log/learning and scheduler behavior.

### Architect documents already present; retain byte-for-byte during build

- `prompts/bf-669-idempotent-reflection-writes.md`
- `prompts/bf-669-idempotent-reflection-writes-execution.md`

### Conditional closeout only, after green gates and final review

- `PROGRESS.md`

No new source or test file is authorized. No other source, test, config YAML, workflow, standing order, UI, dependency, tracker, roadmap, decision, era, archive, data/log, Git, or GitHub file is authorized.

Reference-only blast files are not authorized for modification. If a required fix reaches one, stop.

---

## Ordered implementation

### Section 1 — Add fail-before tests first

Add the headline tests before production edits and prove they fail at this base:

1. real Chroma same AD-599 candidate: first call is newly persisted, second is not, but current Step 15 returns `1` twice;
2. mock same deterministic candidate currently appends two equal IDs;
3. no typed policy/outcome exists;
4. concurrent store has no store-owned serialization/outcome contract;
5. conflicting same-ID warning lacks full ID/hash context.

Do not change assertions to pass until the production contract is implemented. Record the fail-before node IDs and failure reasons in the build report; do not run a broad baseline.

### Section 2 — Add shared enums and protocol contract

1. Add exact enums per DD-1.
2. Update `EpisodicMemoryProtocol` signature/return per DD-2.
3. Add enum value/type/signature tests in existing files.

Hard gate: no bool/result dataclass/exception/config field; old positional callers remain valid.

### Section 3 — Add exact duplicate classification helper

1. Implement DD-5 as a private pure helper.
2. Add a table-driven matrix: exact replay true; timestamp-only drift true; retention metadata/anomaly-stamp drift true; malformed ID, wrong suffix, content/reflection mismatch, source, dream trigger, DAG, attribution, outcomes, duration, Shapley, trust, and malformed existing metadata false.
3. Prove no mutation and no recall/embedding calls.

Hard gate: `MemorySource.REFLECTION` alone never qualifies.

### Section 4 — Add the real store outcome and lock boundary

1. Validate policy before any gate/mutation.
2. Map every current early return to `SKIPPED`.
3. Add lazy `__new__`-safe lock accessor.
4. Serialize the early existing-ID read, new-ID admission/transformation sequence, final metadata/document, TCM update, and `add()`.
5. Release before secondary work.
6. Return `STORED` after successful secondary work; ordinary secondary errors retain current degrade behavior.
7. Add concurrent, cancellation, transient-read/add, and side-effect-order tests.

Hard gate: no upsert/delete/reinsert/retry; duplicate paths have zero TCM/FTS/participant/review/evolution/eviction effects.

### Section 5 — Align the canonical mock

Implement DD-7 using the same helper and outcome/log policy. Prove first-wins, concurrent one-stored/one-duplicate, expected-debug, conflict-warning, capacity eviction only for stored rows, and no duplicate IDs.

Hard gate: no Chroma/SQLite in the mock and no separate copy of reflection equivalence logic.

### Section 6 — Make Step 15 outcome-aware

1. Pass `EXPECT_SAME_REFLECTION` by keyword.
2. Count only `STORED`.
3. Consume duplicate/skipped without an additional Step 15 log; storage is the single diagnostic owner.
4. Treat invalid dependency return as ordinary per-candidate failure, zero count, continue.
5. Update only the two Step 15 storage test doubles to return `STORED` explicitly.
6. Prove later candidates still store after one transient failure.
7. Prove cancellation propagates.

Hard gate: no caller-side exists check; no ID/candidate/attribution change.

### Section 7 — Prove report, log, event, and WM semantics

Behaviorally prove:

- first deterministic run: `reflections_created == 1`, one row, one Step 15 Created INFO, reflection priming may appear;
- second identical run: `reflections_created == 0`, still one row, no WARNING, no Created INFO, no reflection-created WM priming insight;
- mixed run (one duplicate + one new): count/log/report/priming say exactly one newly persisted;
- `DreamScheduler` full-dream event shape stays unchanged (no new field/event);
- existing `DreamReport` field remains an `int` with default zero;
- ordinary Step 15 failure produces no false count and later candidates continue;
- shutdown consolidation never invokes Step 15 and remains write-free.

### Section 8 — Run exact focused and blast gates

Use only the commands below. Do not run full `tests/`, parallel xdist, live LLM/network, or platform data.

### Section 9 — Three-pass Builder self-review and scope audit

Perform all three passes below. Do not edit either Architect document.

### Section 10 — Closeout and exact commit

Only after focused/blast gates are green and final review is complete:

1. prepend one concise BF-669 closeout to `PROGRESS.md` with exact counts/skips, #1035, and the typed outcome/expected-reflection/race/count semantics;
2. state no new AD and BF-669 as the BF ceiling;
3. keep both BF-669 prompt docs unchanged and include them;
4. do not edit `DECISIONS.md`, roadmap, era files, config YAML, or GitHub;
5. stage only allowlisted paths;
6. commit exactly:

`BF-669: make reflection writes idempotent (closes #1035)`

Do not push or mutate GitHub unless separately directed by the orchestrator.

---

## Required behavioral tests

All tests must use deterministic barriers/fakes or a real temporary Chroma store with `PROBOS_EMBEDDINGS=local`. No sleep-based race and no live model/network.

### A. Typed contract and compatibility

1. `EpisodeDuplicatePolicy` has exactly `unexpected` and `expect_same_reflection`.
2. `EpisodeStoreOutcome` has exactly `stored`, `duplicate`, and `skipped`.
3. Real store, canonical mock, and `EpisodicMemoryProtocol` signatures match exactly, including keyword-only policy/default and typed return.
4. `await store(episode)` remains valid and defaults to `UNEXPECTED`.
5. Passing a raw string/bool/object policy raises `TypeError` before any get/add/gate/TCM/sidecar mutation.
6. Existing production callers need no edits and continue ignoring the additive return.

### B. Outcome mapping

7. No collection returns `SKIPPED`.
8. StorageGate REJECT and MERGE return `SKIPPED` with no primary/secondary write.
9. security REJECT, rate limit, and similar-content dedup return `SKIPPED`.
10. Every `SKIPPED` path emits/retains one reason-specific store-boundary diagnostic; no-collection adds a DEBUG, and Step 15 emits no duplicate skip log.
11. new primary row returns `STORED`.
12. same-ID hit returns `DUPLICATE` under both policies.
13. primary get/add transient exception propagates and returns no outcome.
14. cancellation propagates and returns no outcome.

### C. Exact expected reflection proof

15. Same AD-599 content with timestamp-only drift qualifies.
16. Full deterministic ID suffix equals SHA-256 of exact `user_input`.
17. Exact replay with expected policy emits DEBUG only, includes full ID/hash prefixes/authority statement, and returns `DUPLICATE`.
18. Same exact replay under default policy still warns as unexpected and returns `DUPLICATE`.
19. Each mismatch axis independently fails closed: malformed/non-lowercase/wrong-length/wrong-hash ID, user/reflection mismatch, wrong source, missing/wrong dream trigger, wrong DAG type/source, changed DAG/agents/outcomes/duration/Shapley/trust canonical field, malformed stored metadata.
20. Timestamp-only, strength/stability/source-type/confidence, and non-trigger anchor/anomaly-stamp drift do not create a conflict when the existing canonical content and AD-599 envelope match.
21. Failed proof emits one WARNING with full ID, policy, exact reason mapping, hash prefixes, authority statement, no content body, and no overwrite.
22. Different timestamp-bearing `content_hash` caused only by timestamp does not turn an exact deterministic replay into a conflict.

### D. Write-once race and side effects

23. **Headline concurrent exact replay:** two same-instance calls overlap through a deterministic barrier; outcomes are one `STORED` and one `DUPLICATE`, count is one, first content remains authoritative, no WARNING under expected policy.
24. **Concurrent conflict:** one `STORED`, one `DUPLICATE`, one WARNING, first content remains authoritative, no overwrite.
25. Chroma `add()` is called exactly once across concurrent calls.
26. Stateful StorageGate/rate/content-dedup cannot preempt the second same-ID call into `SKIPPED`; the authoritative ID check wins.
27. TCM updates exactly once and only for the stored call.
28. FTS insert/commit, participant index, reconsolidation scheduling, retroactive evolution, and eviction run exactly once only for `STORED`.
29. Duplicate/skip paths run none of those side effects.
30. Lock is released before a blocking secondary fake; a second same-ID call can acquire the primary lock and return `DUPLICATE` while the first is paused in the secondary phase.
31. Add failure releases the lock; a later call can succeed.
32. Cancellation while waiting for the lock propagates and leaves the owner/row unchanged.
33. Cancellation in a secondary await propagates after one primary row; a replay returns `DUPLICATE` and never creates a second row.
34. `__new__`-constructed real memory instances lazily receive one stable lock and preserve existing importance/affect/anomaly tests.
35. Normal store uses `add`, never `upsert`; `_force_update`, seed, migrations, and metadata-only updates remain unchanged.

### E. Mock/protocol parity

36. Canonical mock new write returns `STORED`.
37. Canonical mock repeated ID preserves first episode and returns `DUPLICATE`; list contains one ID.
38. Canonical mock concurrent exact replay returns one `STORED`/one `DUPLICATE`.
39. Mock expected exact duplicate DEBUGs; conflict/default duplicate WARNINGs with the same context contract.
40. Mock max-capacity eviction applies only after a new `STORED`; duplicate does not evict another episode.
41. Step 15-specific fakes return `STORED`; a `None`-returning divergent fake is detected as contract failure and not counted.

### F. Step 15 and deterministic rerun

42. Step 15 passes `duplicate_policy=EXPECT_SAME_REFLECTION` on every candidate.
43. A `STORED` result increments; `DUPLICATE`/`SKIPPED` do not.
44. Invalid outcome, transient exception, and ordinary add failure do not increment and do not abort later candidates.
45. Cancellation propagates; no later candidate runs.
46. **Real deterministic rerun:** same Step 15 candidate twice over one real temporary store returns `1` then `0`, count remains one, full ID stable, first timestamp/content authoritative, no duplicate WARNING.
47. **Mock deterministic rerun:** same result and one stored list entry.
48. Mixed duplicate + new candidates returns exactly one newly created.
49. Deterministic ID format/hash length/content/candidate priority/rate cap remain unchanged.
50. AD-980b attribution ON still stores involved agents; same ID with changed attribution conflicts/warns/no-overwrite.

### G. Report, metrics/events/logs, WM, and lifecycle

51. `DreamReport.reflections_created` means newly persisted only and defaults zero.
52. “AD-599 Step 15: Created N reflection episodes” INFO fires only when N > 0 and N is actual new rows.
53. Duplicate-only rerun emits no Created INFO and no WARNING; exactly one storage-boundary DEBUG includes full ID, policy, timestamp-neutral equivalence, hash prefixes, and authority context.
54. AD-671 `post_dream_seed()` adds no reflection-created insight when count is zero; mixed run says exactly one.
55. No new DreamReport duplicate/skipped field, event type, API metric, or persistent counter appears.
56. Existing full-dream event payload/shape is unchanged.
57. Ebbinghaus decay, activation pruning, reconsolidation metadata, participant/FTS/hash round trips, procedure lifecycle, and semantic/knowledge persistence regression gates remain green.
58. `consolidate_for_shutdown()` remains Step-15-free and episodic-write-free; shutdown ordering/idempotency/integrity markers remain green.

---

## Exact test gates

The Architect verified the proposed baseline at exact HEAD under these conditions:

- focused set: **301 passed**;
- adjacent participant/hash/selective set: **50 passed**;
- exact blast set: **616 passed, 1 skipped**.

Post-build counts will increase. Report exact final counts, skips, and duration.

Run from `D:\ProbOS`.

### Focused — store contract + dream owner

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf669_focused_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad541b_reconsolidation.py tests/test_ad599_reflection_episodes.py tests/test_episodic.py tests/test_episodic_chromadb.py tests/test_ad541e_content_hashing.py tests/test_ad598_importance_scoring.py tests/test_ad601_tcm_temporal_context.py tests/test_ad608_retroactive_evolution.py tests/test_ad610_storage_gating.py tests/test_ad673_anomaly_window.py tests/test_ad1037_affect_capture.py tests/test_ad979e_reconsolidation.py tests/test_ad980b_dream_attribution.py tests/test_ad671_dream_wm_integration.py tests/test_ad573d_dream_to_working_memory.py tests/test_ad873_episode_decay.py tests/test_dreaming.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Focused adjacency — secondary indices and metadata integrity

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf669_adjacent_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_participant_index.py tests/test_memory_integrity.py tests/test_selective_encoding.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Blast radius — persistence, migrations, lifecycle, shutdown

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf669_blast_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad818_schema_versions.py tests/test_ad818a_paginated_migrations.py tests/test_ad818a2_paginated_migrations.py tests/test_ad959_shutdown_light_consolidation.py tests/test_bf207_shutdown_episodic_integrity.py tests/test_bf296_shutdown_phase_ordering.py tests/test_bf598_shutdown_idempotency.py tests/test_knowledge_store.py tests/test_semantic_knowledge.py tests/test_procedure_store.py tests/test_procedure_decay.py tests/test_procedure_archival.py tests/test_procedure_dedup.py tests/test_finalize.py tests/test_public_apis.py tests/test_layer_boundaries.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Do not substitute `-n auto`, `-n 4`, broad xdist, full `tests/`, live network/LLM, or live platform data.

---

## Acceptance criteria

1. Exact base and BF-668 CI preconditions pass before implementation.
2. Typed `EpisodeDuplicatePolicy` and `EpisodeStoreOutcome` have exactly the pinned values.
3. Real store, canonical mock, and protocol expose the exact additive keyword-only signature and typed return.
4. All existing one-argument callers remain source-compatible and default to unexpected-collision handling.
5. Every admission/non-storage path returns `SKIPPED`; primary new write returns `STORED`; same-ID authority returns `DUPLICATE`.
6. Primary read/add errors and cancellation propagate; they are never converted to `SKIPPED`.
7. Store validates policy type before any mutation.
8. Runtime-local lock serializes the early existing-ID decision and new-ID synchronous admission/transformation + TCM + Chroma add; it is lazy-safe for `__new__` tests.
9. Lock is released before FTS5, participant, reconsolidation, evolution, eviction, or any secondary await.
10. Concurrent exact replay produces one `STORED`, one `DUPLICATE`, one row, no overwrite, no warning.
11. Concurrent conflicting same-ID produces one `STORED`, one `DUPLICATE`, one WARNING, no overwrite.
12. Chroma's silent same-ID `add()` behavior cannot produce a false `STORED` result under same-instance concurrency.
13. Expected replay requires the full AD-599 deterministic ID/dream-envelope proof plus equality of the existing canonical content projection with timestamp neutralized; retention/store-derived metadata outside that projection does not create false conflicts.
14. Default duplicates and every failed proof still WARNING with full ID, policy/reason, hash prefixes, and existing-authority context.
15. Expected exact duplicate is DEBUG-only, uses full ID, and preserves authority.
16. No duplicate or skipped path updates TCM or any secondary store/learning side effect.
17. Canonical mock preserves first-write authority and matches real policy/outcome semantics.
18. Step 15 passes expected policy and increments only on `STORED`.
19. First deterministic run reports one; identical rerun reports zero, retains one row, emits no WARNING/Created INFO, and creates no false WM reflection insight.
20. Mixed duplicate/new run reports exactly the number newly persisted.
21. Ordinary transient failure does not count and later candidates continue; cancellation propagates.
22. Reflection deterministic ID, content, candidate order/cap, importance, and AD-980b attribution behavior remain unchanged.
23. `compute_episode_hash()`, hash version, metadata schema, Chroma/FTS/participant schemas, warm-boot seed, migrations, and `_force_update()` remain unchanged.
24. No new DreamReport field, event type, API metric, persistent counter, config, dependency, or UI is added.
25. Ebbinghaus, reconsolidation, semantic/knowledge/procedure persistence, and shutdown regression gates remain green.
26. Focused, adjacency, and blast gates pass isolated/local/offline/serial with `RuntimeWarning` as error; exact counts/skips/durations are reported.
27. Only allowlisted files change; no deletion, broad reformat, YAML, workflow, standing-order, roadmap, era, decision, dependency, data/log, or GitHub mutation occurs.
28. `PROGRESS.md` closeout is concise, records exact counts and #1035, states no new AD/BF-669 ceiling, and is included in the exact commit.
29. Commit is exactly `BF-669: make reflection writes idempotent (closes #1035)`.
30. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Do NOT build

- No blanket downgrade/suppression/filter/rate-limit of duplicate warnings.
- No assumption that every `MemorySource.REFLECTION` duplicate is expected.
- No bool-only result, result dataclass, duplicate exception, fourth conflict outcome, or caller-side exists precheck.
- No full-dataclass equality for expected replay; timestamp drift is expected by AD-599.
- No weakening of conflicts: malformed/wrong-ID/source/dream-trigger/DAG/canonical-content/attribution mismatch must still warn and preserve first authority.
- No upsert, delete/reinsert, update-on-duplicate, retry loop, overwrite, merge, or last-write-wins behavior.
- No distributed/process/file/SQLite lock, per-ID lock dictionary, lock persistence, or new table/cache.
- No lock around secondary awaits, reconsolidation/evolution, eviction, or the whole post-primary store tail. New-ID synchronous admission remains inside the serialized primary window so same-ID truth cannot be preempted.
- No Chroma schema/collection/embedding migration, hash-version or ID-format/hash-length change.
- No broad migration of all 33 production callers or every local test fake.
- No KnowledgeStore dual-write for Step 15 and no new secondary persistence path.
- No change to rate limiting, content dedup, storage/security gate thresholds, TCM math, importance/affect/anomaly scoring, FTS, participant index, reconsolidation, evolution, or eviction policy.
- No dream candidate generation/order/cap/cadence, cluster/procedure/LLM, attribution, recall, trust, Hebbian, or learning redesign.
- No Step 15 work in `consolidate_for_shutdown()`, scheduler stop/drain/order change, integrity marker change, or shutdown timeout change.
- No new event, metric endpoint, API field, config flag, environment variable, dependency, UI, AD, `DECISIONS.md`, roadmap, era, archive, workflow, standing order, or GitHub edit.

---

## Hard stops

Stop and return to the Architect if any of the following occurs:

1. HEAD or `origin/main` differs from `2417bfb97d48fb9a867c387bf9e8eb71365550d6`.
2. Exact-base CI run `29351723371` remains failed, or any replacement exact-base run is not completed/success; do not treat the serial-isolated pass as permission to override the explicit CI-success gate.
3. Initial status contains anything beyond the two BF-669 Architect docs.
4. A required behavior needs a file outside the allowlist.
5. Correctness appears to require a new AD, config, dependency, event, API, schema, table, cache, distributed/process/file lock, or ID/hash migration.
6. Chroma behavior differs from the verified silent duplicate-add first-wins behavior in a way that invalidates the lock/read/add design.
7. The lock would need to span an await, sidecar, eviction, or the entire store method.
8. The expected-reflection proof cannot distinguish timestamp-only drift from stable-content conflict without changing AD-599 ID/content generation.
9. A same-ID conflict would be overwritten, downgraded below WARNING, or returned as `STORED`/`SKIPPED`.
10. Any duplicate path updates TCM, FTS, participant index, reconsolidation, evolution, or eviction.
11. Cancellation would be swallowed, converted to an ordinary failure/outcome, or leave the primary lock held.
12. Step 15 would need a caller-side precheck, broad caller migration, changed candidate generation/order/cap, or changed return type.
13. A focused/adjacent/blast failure reproduces serially and needs unallowlisted edits, skipping, quarantine, weakened assertions, or a broad test run.
14. Any Architect doc, local YAML, workflow, dependency, UI, decision/roadmap/era file, Git, or GitHub mutation occurs outside the pinned closeout/commit step.

Do not guess around a hard stop.

---

## Three-pass self-review

### Pass 1 — Behavior/spec

- Map every DD, required test, and acceptance item.
- Verify every store exit maps to `STORED`, `DUPLICATE`, `SKIPPED`, or propagated failure/cancellation.
- Verify exact replay ignores timestamp only and every stable mismatch warns.
- Verify Step 15 count/log/report/WM semantics use actual primary writes only.
- Verify mixed candidates and ordinary failure continuation.

### Pass 2 — Verify-first/code

- Re-grep exact signatures, all direct store callers, Step 15 call sites, and protocol/mock contracts.
- Inspect the lock window statement-by-statement; prove no await and no secondary work inside.
- Inspect Chroma read fields, reconstruction, canonical hash prefixes, full-ID logging, and first-write authority.
- Inspect `__new__` tests and ensure lazy lock initialization does not disturb existing setup.
- Confirm no changed seed/migration/_force_update/hash/metadata schema and no caller precheck.

### Pass 3 — Scope/safety/license

- Verify exact allowlist, no deletion/bulk reformat, and two Architect docs unchanged.
- Verify no broad warning suppression, reflection-source shortcut, bool/exception contract, distributed lock, schema/config/dependency/UI/AD drift.
- Verify cancellation, logging context, type annotations, and layer discipline against `.github/copilot-instructions.md`.
- License remains none.

---

## Verified Against Codebase (2026-07-14)

```text
git rev-parse HEAD
  2417bfb97d48fb9a867c387bf9e8eb71365550d6

git rev-parse origin/main
  2417bfb97d48fb9a867c387bf9e8eb71365550d6

git status --short
  <empty before these two Architect docs were created>

git log -1 --format=%H/%aI/%s
  2417bfb97d48fb9a867c387bf9e8eb71365550d6
  2026-07-14T10:56:34-06:00
  BF-668: classify IntentBus handler latency (closes #1034)

gh issue view 1035 --repo seangalliher/ProbOS
  OPEN — BF-669: Expected-idempotent reflection writes without warning noise or false creation counts

gh run view 29351723371 --repo seangalliher/ProbOS
  headSha=2417bfb97d48fb9a867c387bf9e8eb71365550d6
  completed/failure: ui-tests success; python-tests failed
  only failure: tests/test_knowledge_store.py::TestGitIntegration::test_auto_commit_after_debounce
  summary: 1 failed, 18740 passed, 36 skipped
  required serial triage at exact HEAD: isolated/local/offline/-n 0/-W error::RuntimeWarning -> 1 passed in 0.90s
  classification: parallel/full-gate timing artifact candidate, but the explicit handoff gate still requires green CI or Architect base re-verification

grep -n "async def store\|Write-once guard\|already exists\|self._collection.add\|await self._evict" src/probos/cognitive/episodic.py
  1597: store(self, episode) -> None
  1704: AD-541b write-once guard
  1708: generic truncated duplicate WARNING
  1733: authoritative Chroma add
  1784: eviction after secondary writes

grep -n "self._tcm.update\|self._fts_db.execute\|record_episode\|schedule_review\|evolve_on_store" src/probos/cognitive/episodic.py
  1720: TCM update before add
  1743: FTS secondary await
  1755: participant secondary await
  1764: reconsolidation schedule
  1775: retroactive evolution await

grep -n "def compute_episode_hash\|content_hash.*compute_episode_hash\|def _metadata_to_episode" src/probos/cognitive/episodic.py
  1012: canonical hash
  3299: stored metadata hash
  3415: stored episode reconstruction

grep -n "async def store" src/probos/cognitive/episodic_mock.py src/probos/protocols.py
  episodic_mock.py:90 -> None
  protocols.py:44 -> None

grep -n "_step_15_reflection_promotion\|Deterministic ID\|episode_id =\|await self.episodic_memory.store\|created += 1" src/probos/cognitive/dreaming.py
  2795: Step 15 owner
  2905/2907: deterministic reflection-{sha256(content)[:16]}
  2944/2945: store then unconditional increment

grep -n "reflections_created\|Created .*reflection" src/probos/cognitive/dreaming.py src/probos/cognitive/dream_wm_bridge.py
  dreaming.py:1667/1686/1773
  dream_wm_bridge.py:132/134

grep -n "consolidate_for_shutdown\|performs no episodic-collection writes" src/probos/cognitive/dreaming.py
  292/314

git grep direct production episodic store awaits
  33 calls; zero assigned/returned results

grep existing tests
  test_ad541b_reconsolidation.py:377/396/416/450 — write-once guard/warning/no-upsert
  test_ad599_reflection_episodes.py:109/348/391 — create/deterministic ID/store failure
  test_ad980b_dream_attribution.py:25/29/73/91/106 — Step 15 recording fake + attribution
  test_ad671_dream_wm_integration.py:82/111 — priming and no-insight behavior

retained live logs
  240 duplicate write-once warnings; 240 reflection IDs; 0 non-reflection
  240/240 followed by false Step 15 Created INFO within two lines
  239 truncated reflection-8; 1 truncated reflection-f

read-only live Chroma inspection
  reflection-856c1fd0a359a278 and reflection-8dfdd9fbc24510a2 are distinct
  suffix == sha256(user_input)[:16]
  source/source_type=reflection
  anchor_trigger_type=dream_consolidation
  dag type/source=reflection/dream_consolidation

Chroma duplicate-add probe
  second add returned normally
  count=1
  first document/content remained authoritative

baseline gates at exact HEAD
  focused: 301 passed in 109.97s
  adjacent: 50 passed in 2.95s
  exact blast: 616 passed, 1 skipped in 244.78s
```
