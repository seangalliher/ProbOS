# Review: AD-677 — Context Provenance Metadata

**Verdict:** ✅ Approved
**Headline:** Core APIs verified; ready for builder.

## Required

None.

## Recommended

1. **Provenance Envelope lifecycle.** Document where the inline tag rendered by `render()` is visible — injected context only, or also stored in episodic memory? Clarity helps the builder verify all injection points.
2. **Hash collision risk.** `compute_content_hash()` slices to 8 chars (~16M unique values). Sufficient for dedup but worth a comment on the security boundary.
3. **`from_oracle_result()` retrieval timestamp semantics.** Currently uses `time.time()` (when fetched); document that vs. the oracle's own freshness timestamp.

## Nits

- Section 4 (tiered_knowledge.py emit events) is incomplete in the prompt — append the full SEARCH/REPLACE block referencing the existing `KnowledgeTierLoadedEvent` pattern.

## Verified

- `OracleResult` at [oracle_service.py:23](src/probos/cognitive/oracle_service.py#L23) with fields `source_tier`, `content`, `score`, `metadata`, `provenance`.
- `OracleService.query()` signature at [oracle_service.py:68](src/probos/cognitive/oracle_service.py#L68): `(query_text, agent_id="", intent_type="", k_per_tier=5, tiers=None)`.
- `TieredKnowledgeLoader` at [tiered_knowledge.py:51](src/probos/cognitive/tiered_knowledge.py#L51) — uses `KnowledgeSourceProtocol`, NOT OracleService directly. Standalone `query_with_provenance()` is the right entry point.
- `KnowledgeSourceProtocol` at [tiered_knowledge.py:25](src/probos/cognitive/tiered_knowledge.py#L25).
- `KNOWLEDGE_TIER_LOADED` at [events.py:169](src/probos/events.py#L169) — `CONTEXT_PROVENANCE_INJECTED` insertion confirmed.
- `ProvenanceTag` and `ProvenanceEnvelope` are frozen dataclasses (immutable, thread-safe) — correct.
