# AD-1138 — Semantic index over Ship's Records (Σ discoverable) (knowledge / Oracle Tier 2)

**Issue: #1059 · Epic #1057 (Σ / Cognitive Mesh) · depends on BF-675 (#1058, in-tree).**
**Repo: OSS (`d:\ProbOS`). This AD = **AD-1138** (#1059). AD-1144–1151 assigned (#1069–#1076). No new BF.**

Make the Ship's Records commons semantically discoverable by indexing records into the existing `SemanticKnowledgeLayer` and retrieving them through Oracle Tier 2 with classification-scoped filtering. Default-OFF.

---

## Why / context

Ship's Records (AD-434) is the Nooplex Σ and already carries the right publication model — `_CLASSIFICATION_LEVELS = {"private":0,"department":1,"ship":2,"fleet":3}` (`src/probos/knowledge/records_store.py:27`), enforced on read (`:706`) and on search (`:841`).

But it is discoverable only by literal word overlap:

```python
raw_lower = raw.lower()
matches = sum(1 for w in query_words if w in raw_lower)
```
`records_store.py:837` — normalised by the Oracle as `min(r.get("score", 0) / 10.0, 1.0)` (`oracle_service.py:704`).

A note titled "deployment rollback lessons" is invisible to a query for "how do we revert a bad release." Nooplex §3.1 specifies Σ as *"vector stores, relational data, and episodic logs"* — ChromaDB is already wired in five other places but not here.

**Reuse, do not rebuild:** `SemanticKnowledgeLayer` already has a `COLLECTIONS` registry, per-type `index_*` methods, an AD-584 embedding-migration path, and (post-BF-675) an `include_episodes` gate.

---

## Pinned design decisions

### DD-1 — Extend `SemanticKnowledgeLayer`; do not build a new store
Add `"records": "sk_records"` to `SemanticKnowledgeLayer.COLLECTIONS` (`src/probos/knowledge/semantic.py:34`) and an `index_record(...)` method mirroring `index_event` (`:229`). The AD-584 migration loop iterates `COLLECTIONS`, so the new collection inherits migration for free — **verify that at build**.

### DD-2 — Classification travels in the metadata and is enforced at query time (LOAD-BEARING)
Every indexed record carries its `classification` in ChromaDB metadata. Retrieval **must** filter by scope, or semantic search becomes a bypass around `records_store.py:841`'s existing enforcement — turning a discoverability feature into a disclosure bug.

Use a ChromaDB `where` clause rather than post-filtering, so `limit` remains meaningful (post-filtering can return an empty page while matching records exist).

**ChromaDB 1.5.8 gotcha:** a flat multi-key `where` raises `Expected where to have exactly one operator`. Use `{"$and": [...]}` for multiple predicates; keep a single predicate flat. Scope is a *level* comparison (`<= requested level`), so express it as an `$in` over the permitted classification labels, not a range.

### DD-3 — Tier 2 keeps its result shape
`_query_records` (`oracle_service.py:700`) returns `OracleResult(source_tier="records", metadata={"path":…, "frontmatter":…}, provenance="[ship's records]")`. Keep that shape exactly — downstream consumers and the AD-677 `ProvenanceEnvelope` depend on it. Only the *retrieval mechanism* and the *score* change.

### DD-4 — Default-OFF, with keyword fallback retained
New flag; when off, Tier 2 uses the existing `records_store.search(...)` path verbatim ⇒ byte-identical. When on, semantic retrieval is used. If the semantic layer is unattached or the collection is empty, **fall back to keyword** rather than returning nothing (honest-degrade).

### DD-5 — Backfill existing records
Records written before this AD are not in the collection. Provide a reindex path mirroring `reindex_from_store` (`semantic.py:351`). Run it at wire time when the collection is empty; bound the work and honest-degrade.

### DD-6 — Local-EF safety
CI runs `PROBOS_EMBEDDINGS=local` (BF-657), where the EF is lexical, not semantic. Any test asserting *semantic* quality (synonym matching) must skip when `get_embedding_function() is None`. Structural tests (indexing, classification filtering, fallback) must run in both modes.

---

## Build

1. **`semantic.py`** — add `"records"` to `COLLECTIONS`; add `index_record(path, content, classification, author, updated_at, **meta)` mirroring `index_event`; extend `search()` to accept an optional classification scope applied as a `where` filter for the records collection.
2. **`records_store.py`** — no behaviour change. Optionally expose a small helper to enumerate records for backfill if one does not already exist (`list_entries` may suffice — verify).
3. **`oracle_service.py`** — `_query_records` branches: semantic when enabled and available, keyword otherwise. Result shape unchanged (DD-3).
4. **Config** — `RecordsConfig` (`src/probos/config.py:3362`) gains `semantic_index_enabled: bool = False`.
5. **Wiring + backfill** — index on write and backfill when empty; find the existing records/semantic wiring site and follow it.
6. **Tests** — `tests/test_ad1138_records_semantic_index.py`.

## Acceptance

- A record is retrievable by a query that does **not** lexically overlap its text (skipped under local EF per DD-6).
- **Classification enforced in retrieval:** a `private` record is not returned to a `ship`-scoped query; a `department` record is not returned cross-department. Assert with real records at three levels.
- Scope filtering uses a `where` clause (not post-filtering) — assert the filter is passed to Chroma.
- Tier 2 result shape unchanged: `source_tier="records"`, `metadata` keys `path`/`frontmatter`, `provenance="[ship's records]"`.
- Default-OFF ⇒ Tier 2 byte-identical to the keyword path.
- Semantic layer unattached or collection empty ⇒ keyword fallback, no exception.
- Backfill indexes pre-existing records.
- BF-675 interop: Tier 2 changes do not reintroduce episodes into Tier 5 (`include_episodes=False` still passed).
- Real fixtures per BF-287 — real `RecordsStore` + real `SemanticKnowledgeLayer` on `tmp_path`.
- Verify compliance with `.github/copilot-instructions.md`.

## Validation plan — targeted only

- **Focused:** `tests/test_ad1138_records_semantic_index.py -q -n 0`
- **Adjacent ONCE:** `tests/test_bf675_oracle_tier5_sovereignty.py tests/test_ad686_oracle_semantic_tier.py tests/test_ad686b_oracle_write_semantic.py tests/test_ad686c_semantic_stats.py tests/test_semantic_knowledge.py -q -n 0` (verify each exists; drop any that do not).
- **Do NOT run the full suite.**

## Do NOT build here

❌ The agent-facing Oracle tool (AD-1139 #1060). ❌ The publish path (AD-1140 #1061). ❌ Crew wiring (AD-1141 #1062). ❌ Changing the classification vocabulary or `_CLASSIFICATION_LEVELS`. ❌ Changing `records_store.search`'s existing keyword behaviour or its scope semantics. ❌ Touching Tier 1 episodic or the AD-607e policy. ❌ A new store. ❌ A new AD or BF number.

## Files (verify each at build)

- `src/probos/knowledge/semantic.py` — collection, `index_record`, scope filter.
- `src/probos/cognitive/oracle_service.py` — `_query_records` branch.
- `src/probos/config.py` — `RecordsConfig.semantic_index_enabled`.
- wiring/backfill site (locate at build).
- `tests/test_ad1138_records_semantic_index.py` (NEW).

## Done-when

Acceptance green; focused + adjacent gates green; default-OFF byte-identity proven; classification enforcement asserted at three levels; **verify compliance with `.github/copilot-instructions.md`.**
