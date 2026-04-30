# Review: AD-678 — Memory Transparency Mechanism

**Verdict:** ⚠️ Conditional
**Headline:** Depends on AD-677; no internal blockers.

## Required

None internal — only the AD-677 dependency.

## Recommended

1. **Episode field semantics.** `wrap_recall_results()` reads `episode.user_input` as "content." Confirmed correct (it's the original NL query). Document this so the builder doesn't second-guess.
2. **Distance→similarity inversion.** `similarity = 1.0 - distance` follows ChromaDB convention. Add an explicit comment.
3. **Two provenance types.** AD-677 = `ProvenanceTag` (context), AD-678 = `MemoryProvenance` (recalled episodes). Add a comment explaining the distinction so future reviewers don't conflate them.

## Nits

- `format_inline()` slices `agent_id[:12]`. Add defensive truncation if callsign is shorter.

## Verified

- `Episode` structure at [types.py:480+](src/probos/types.py#L480): `id`, `agent_ids`, `timestamp`, `user_input`, `anchors`.
- `AnchorFrame.channel` at [types.py:400+](src/probos/types.py#L400).
- `ProvenanceTag` / `ProvenanceEnvelope` are AD-677 dependencies — must merge first.
- Test count (7) reasonable: staleness, confidence labeling, similarity, filtering, formatting.
- Read-only service — no episode mutation.
- Type annotations complete on public methods.
