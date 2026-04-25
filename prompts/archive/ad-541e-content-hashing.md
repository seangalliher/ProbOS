# AD-541e: Episode Content Hashing

**Status:** Ready for builder
**Lineage:** AD-541 (Consolidation Integrity) → AD-541b (Prevention) → AD-541c (Strengthening) → AD-541d (Detection/Treatment) → **AD-541e (Verification)** → AD-541f (Audit Trail)
**Depends:** AD-541b (frozen Episode, write-once guard)
**Branch:** `ad-541e-content-hashing`

---

## Context

The Memory Consolidation Integrity lineage protects episodic memory quality through
layered defenses:

| Pillar | AD | Role | Status |
|--------|----|------|--------|
| Prevention | AD-541b | Frozen Episode, write-once ChromaDB, READ-ONLY framing | Complete |
| Strengthening | AD-541c | Spaced retrieval therapy reinforces genuine traces | Complete |
| Detection/Treatment | AD-541d | Guided reminiscence classifies recall accuracy | Complete |
| **Verification** | **AD-541e** | **Cryptographic hash detects storage-layer tampering** | **This AD** |
| Audit Trail | AD-541f | Eviction logging for accountability | Planned |

AD-541b prevents Python-level mutation (`frozen=True`) and application-level
overwrites (write-once guard). But neither protects against:
- Direct ChromaDB/SQLite manipulation
- `_force_update()` migration path misuse
- Storage corruption

AD-541e adds **cryptographic content verification** — a SHA-256 hash computed at
episode creation and verified on recall. If the stored content doesn't match the
hash, the episode is flagged as potentially tampered.

### Existing Pattern to Reuse

The Identity Ledger (`identity.py`) already implements content hashing:

```python
# AgentBirthCertificate.compute_hash() — identity.py:135-148
content = {
    "agent_uuid": self.agent_uuid,
    "did": self.did,
    ...
}
canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

AD-541e follows the same pattern: canonical JSON serialization → SHA-256.

### Design Decision: Per-Episode Hash, Not Hash-Chain

AD-541b referenced "hash-chain similar to Identity Ledger." Episodes are independent
memories, not sequential blocks — ordering integrity doesn't apply. A per-episode
hash is sufficient. Hash-chains could be explored for federation provenance (future).

### Design Decision: Hash in Metadata, Not on Episode Dataclass

The content hash is a **storage integrity mechanism**, not a semantic property of the
memory. Storing it in ChromaDB metadata (alongside `agent_ids_json`, `source`, etc.)
avoids a chicken-and-egg problem (hash depends on content, but hash would be part of
content) and requires no change to the frozen Episode dataclass. The hash is computed
FROM the Episode, stored alongside it, and verified by recomputing on recall.

---

## Principles Compliance

- **SOLID (S):** `compute_episode_hash()` is a single-responsibility utility
- **SOLID (O):** Existing `_episode_to_metadata` / `_metadata_to_episode` extended, not replaced
- **SOLID (D):** Hash verification is config-gated, not hardcoded
- **Law of Demeter:** Hash utility takes an Episode, returns a string — no internal reaching
- **Fail Fast:** Tamper detection logs WARNING, does not crash. Degraded recall is better than no recall
- **DRY:** Follows existing `identity.py` hashing pattern. Uses same `hashlib.sha256` + canonical JSON
- **Cloud-Ready:** No storage changes — hash is a ChromaDB metadata field (str), works with any backend

---

## Deliverables

### D1 — `compute_episode_hash()` Utility (episodic.py)

Add a module-level utility function to `src/probos/cognitive/episodic.py`:

```python
def compute_episode_hash(episode: Episode) -> str:
    """Compute SHA-256 content hash for an episode.

    Uses canonical JSON serialization (sorted keys, compact separators)
    following the Identity Ledger pattern (identity.py:135-148).

    Includes all content fields. Excludes:
    - id (document key, not content)
    - embedding (computed by ChromaDB, not original content)
    """
```

**Hash input fields** (all content that constitutes the memory):
- `timestamp` (float)
- `user_input` (str)
- `dag_summary` (dict)
- `outcomes` (list)
- `reflection` (str or None → normalize to "")
- `agent_ids` (list)
- `duration_ms` (float)
- `shapley_values` (dict)
- `trust_deltas` (list)
- `source` (str)

**Excluded fields:**
- `id` — UUID document key, not content
- `embedding` — computed by ChromaDB ONNX, not original content

**Implementation:**
1. Build a dict of the included fields (normalize `reflection` None → `""`)
2. `json.dumps(content, sort_keys=True, separators=(",", ":"))` — canonical form
3. `hashlib.sha256(canonical.encode("utf-8")).hexdigest()` — SHA-256

**Import:** Add `import hashlib` to episodic.py (already used in identity.py, cognitive_agent.py).

**Determinism:** Same Episode content → same hash, always. `sort_keys=True` ensures
dict ordering. `separators=(",", ":")` eliminates whitespace variance. Float fields
use Python's default `repr()` via `json.dumps`, which is consistent within CPython
(same caveat as identity.py:130-133).

### D2 — Hash Computation at Store Time (episodic.py)

Modify `_episode_to_metadata()` (line 663) to compute and include the content hash:

```python
@staticmethod
def _episode_to_metadata(ep: Episode) -> dict:
    # ... existing metadata dict construction ...
    metadata["content_hash"] = compute_episode_hash(ep)
    return metadata
```

This ensures every new episode stored after AD-541e gets a content hash in metadata.
No separate store() changes needed — `_episode_to_metadata` is the single
serialization point.

### D3 — Hash Verification on Recall (episodic.py)

Add a verification helper:

```python
def _verify_episode_hash(
    episode: Episode, stored_hash: str
) -> bool:
    """Verify an episode's content matches its stored hash.

    Returns True if hash matches or no hash stored (legacy episode).
    Returns False only on hash mismatch (potential tampering).
    """
```

**Behavior:**
- If `stored_hash` is empty/missing → return `True` (legacy episode, no hash to verify — see D6)
- Recompute hash via `compute_episode_hash(episode)`
- Compare with `stored_hash`
- If mismatch → log `WARNING` with episode ID and return `False`
- If match → return `True`

**Integration into recall paths:**

Modify `_metadata_to_episode()` (line 689) signature to also return the stored
`content_hash` from metadata, OR add verification to the two recall methods:

**Option chosen:** Add verification in `recall_for_agent()` and `recent_for_agent()`
after episode reconstruction. This keeps `_metadata_to_episode()` a pure conversion
and puts verification logic at the API boundary.

In both `recall_for_agent()` and `recent_for_agent()`:

```python
ep = self._metadata_to_episode(doc_id, document, metadata)
stored_hash = metadata.get("content_hash", "")
if self._verify_on_recall and not _verify_episode_hash(ep, stored_hash):
    logger.warning(
        "Episode %s failed content hash verification — possible tampering",
        doc_id[:8],
    )
    # Still return the episode — degraded recall > no recall
```

The `self._verify_on_recall` flag is set from config (see D5).

**Important:** Verification failure does NOT omit the episode from results. The agent
still gets their memory — we just log the integrity concern. Fail-fast tier:
log-and-degrade. The SIF check (D4) escalates if the pattern is systemic.

### D4 — SIF Memory Integrity Enhancement (sif.py)

Extend `check_memory_integrity()` (line 291) to verify content hashes on sampled
episodes:

In the existing loop over sampled episodes (line 314), after the existing source
provenance check:

```python
# Existing checks (keep as-is):
if not doc_id:
    issues.append("Episode missing ID")
# source provenance: empty/missing source = legacy, not a violation
source = meta.get("source", "")
if not source:
    pass  # legacy or migrated episode — not a violation

# NEW — AD-541e content hash verification:
content_hash = meta.get("content_hash", "")
if content_hash:
    # Reconstruct episode to recompute hash
    document = documents[i] if documents and i < len(documents) else ""
    ep = EpisodicMemory._metadata_to_episode(doc_id, document, meta)
    recomputed = compute_episode_hash(ep)
    if recomputed != content_hash:
        issues.append(f"Episode {doc_id[:8]} content hash mismatch")
```

**Changes to the `get()` call** in SIF (line 312): Include `"documents"` in addition
to `"metadatas"`:

```python
result = collection.get(include=["metadatas", "documents"], limit=10)
```

**Import:** Add `from probos.cognitive.episodic import compute_episode_hash`
(lazy import inside the method to avoid circular imports — follow existing pattern
at line 311 `import json as _json`).

**Legacy handling:** Episodes without `content_hash` in metadata (pre-AD-541e) are
skipped — the `if content_hash:` guard handles this. No false alarms.

### D5 — Configuration (config.py)

Add one field to `MemoryConfig`:

```python
verify_content_hash: bool = True
```

Wire into `EpisodicMemory.__init__()`:

```python
self._verify_on_recall = getattr(config, "verify_content_hash", True) if config else True
```

If the constructor doesn't currently receive a config object, check how
`EpisodicMemory` is instantiated in `startup/cognitive_services.py` and thread the
config through. The field defaults to `True` — verification is on by default for
new installations.

### D6 — Legacy Episode Graceful Handling

**No migration.** Existing episodes will not have `content_hash` in their metadata.
This is handled gracefully at every verification point:

1. `_verify_episode_hash()` returns `True` if `stored_hash` is empty (D3)
2. SIF skips hash verification if `content_hash` not in metadata (D4)
3. No SIF spam for legacy episodes (learned from the source provenance issue — same
   pattern: legacy data grandfathered, only new data held to new standards)

**The BF-103 migration lesson:** Bulk upserts to backfill metadata trigger ONNX
re-embedding and can take 10+ minutes on large collections. Content hash backfill
would have the same cost for zero integrity benefit (we can't verify the hash of an
episode we didn't originally hash). Explicitly: do NOT add a backfill migration.

---

## Test Spec

**New file:** `tests/test_ad541e_content_hashing.py`

### D1 — Hash Utility (6 tests)

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_hash_deterministic` | Same Episode → same hash, every time |
| 2 | `test_hash_changes_on_content_change` | `dataclasses.replace(ep, user_input="different")` → different hash |
| 3 | `test_hash_excludes_id` | Two episodes with same content but different IDs → same hash |
| 4 | `test_hash_excludes_embedding` | Two episodes with same content but different embeddings → same hash |
| 5 | `test_hash_includes_all_content_fields` | Changing each included field (timestamp, user_input, dag_summary, outcomes, reflection, agent_ids, duration_ms, shapley_values, trust_deltas, source) → different hash |
| 6 | `test_hash_is_sha256_hex` | Hash is 64-char hex string |

### D2 — Store-Time Hashing (2 tests)

| # | Test | Asserts |
|---|------|---------|
| 7 | `test_metadata_includes_content_hash` | `_episode_to_metadata(ep)` result contains `content_hash` key |
| 8 | `test_stored_hash_matches_recomputed` | Store episode, retrieve metadata, recompute hash from episode — matches stored value |

### D3 — Recall Verification (5 tests)

| # | Test | Asserts |
|---|------|---------|
| 9 | `test_verify_hash_match_returns_true` | Correct hash → `True` |
| 10 | `test_verify_hash_mismatch_returns_false` | Wrong hash → `False` |
| 11 | `test_verify_empty_hash_returns_true` | Empty/missing hash (legacy) → `True` |
| 12 | `test_recall_logs_warning_on_mismatch` | Mock tampered metadata, recall episode, assert WARNING logged |
| 13 | `test_recall_still_returns_tampered_episode` | Even on hash mismatch, episode IS returned (degrade, not deny) |

### D4 — SIF Integration (3 tests)

| # | Test | Asserts |
|---|------|---------|
| 14 | `test_sif_passes_with_valid_hash` | Episode with matching hash → SIF passes |
| 15 | `test_sif_detects_hash_mismatch` | Episode with mismatched hash → SIF reports violation |
| 16 | `test_sif_skips_legacy_no_hash` | Episode without content_hash → SIF passes (no false alarm) |

### D5 — Config (2 tests)

| # | Test | Asserts |
|---|------|---------|
| 17 | `test_verify_on_recall_default_true` | Default config → verification enabled |
| 18 | `test_verify_disabled_skips_check` | `verify_content_hash=False` → no WARNING logged even on mismatch |

**Total: 18 tests** in 1 new test file.

---

## Files to Modify

| File | Action | Changes |
|------|--------|---------|
| `src/probos/cognitive/episodic.py` | Edit | D1: `compute_episode_hash()`, D3: `_verify_episode_hash()` + recall integration, D5: `_verify_on_recall` flag |
| `src/probos/cognitive/episodic.py` | Edit | D2: `_episode_to_metadata()` adds `content_hash` |
| `src/probos/sif.py` | Edit | D4: `check_memory_integrity()` hash verification |
| `src/probos/config.py` | Edit | D5: `MemoryConfig.verify_content_hash` field |
| `src/probos/startup/cognitive_services.py` | Edit | D5: Thread config into EpisodicMemory (if not already) |
| `tests/test_ad541e_content_hashing.py` | Create | 18 tests |

**6 files** (1 new, 5 edits). No dataclass changes. No migration. No new dependencies.

---

## Scope Exclusions

| Excluded | Reason | Future |
|----------|--------|--------|
| Hash-chain linking episodes | Episodes are independent, not sequential | Federation provenance |
| Digital signatures (asymmetric crypto) | Overkill for single-instance integrity | Federation trust |
| Backfill migration for existing episodes | Expensive (ONNX re-embed), zero benefit (can't retroactively verify) | N/A |
| `content_hash` field on Episode dataclass | Hash is storage concern, not domain — avoids chicken-and-egg | N/A |
| Composite `memory_integrity_score` aggregation | Requires all pillars (541a-f) complete | Post-541f AD |
| Notebook/Ship's Records hashing | Different storage layer, different integrity model | Separate AD |

---

## Builder Instructions

1. Read and understand the existing hashing pattern in `identity.py:135-148`
2. All code in `episodic.py` — hash utility, verification helper, metadata integration
3. SIF enhancement minimal — add to existing `check_memory_integrity()` loop
4. **Do NOT modify the Episode dataclass** — hash lives in ChromaDB metadata only
5. **Do NOT add a migration** — legacy episodes without hash are gracefully skipped
6. **Do NOT add `import hashlib` at module top if it would be the only use** — follow
   the lazy import pattern if appropriate, but `hashlib` is stdlib so top-level is fine
7. Run: `python -m pytest tests/test_ad541e_content_hashing.py -x -v`
8. Run: `python -m pytest tests/test_bf103_episode_id_mismatch.py tests/test_ad541b_reconsolidation.py -x -q` (regression)
9. Run: `python -m pytest tests/ -k "sif" -x -q` (SIF regression)
10. Update tracking files: `PROGRESS.md`, `DECISIONS.md`, `docs/development/roadmap.md`
