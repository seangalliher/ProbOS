# Wave 41 Dispatch — AD-691 v1 NL-to-Graph Query

**Issue:** #385 · **Phase:** Unified Knowledge Graph — Phase B
**Builder reads:** `prompts/ad-691-nl-to-graph-query-v1.md`
**Test gate baseline:** 11028 (Wave 40) → expected 11040 (+12)

## Continuous-build mode

Single-AD wave. Continuous build — no inter-AD pause.

## Hard-stop conditions (narrow)

1. **Phantom API in implementation** (not just test fixtures). FPs documented
   in prompt §10 are NOT hard-stops.
2. **Architectural change required** — e.g. modifying `KnowledgeEdgeStorage`
   Protocol, `LLMRequest` dataclass, or `BaseLLMClient.complete` signature.
   Surface to architect.
3. **Decomposer integration creep** — if Builder is tempted to add an
   `IntentDescriptor` / new agent, STOP. That work is AD-691b. Pure callable
   surface is the v1 contract.

## Standing reminders for THIS wave

- **Twin-block in `api.py`** — import tuple + for-loop tuple. Use a single
  combined SEARCH/REPLACE per Wave 31/33 pattern. Disambiguating prefixes:
  `from probos.routers import (` vs `for r in (`.
- **`enabled=True` default** is intentional (deviation from Wave-10
  transitional-flag convention). DiagnosticContextConfig precedent. Do NOT
  flip to False.
- **Provenance citations** — the `_CITATION_RE` regex requires hex IDs of
  ≥16 chars. `KnowledgeEdge.id` defaults to `uuid.uuid4().hex` (32 chars) —
  matches.
- **Hop-proximity formula** — `0.6 ** (hop - 1)`. Hop=1 → 1.0, hop=2 → 0.6,
  hop=3 → 0.36. Matches AD-688 for hops 1 and 2.
- **`relation_filter` whitelist coercion** — drop unknown strings silently
  at debug log level (DLog #6). Empty post-coercion → pass `None` to
  `traverse()`.
- **Empty-extraction short-circuit** — if Phase 1 entities is `[]`, return
  immediately with `"No graph entities identified in query."` and SKIP
  Phase 2. Test #5 enforces this (`llm.calls == 1`).

## Deferred (do NOT smuggle into v1)

- AD-691b: decomposer integration (new agent + IntentDescriptor).
- AD-691c: embedding-based fuzzy entity match.
- AD-692: classification-aware filtering on graph reads.
- HXI graph visualization.
- Streaming response (WS).
- Persistence of query history.

## Acceptance summary

- 12 new tests pass at `tests/test_ad691_nl_graph_query.py`.
- Full gate green; +12 vs baseline 11028.
- No new phantoms beyond §10 FPs.
- Trackers updated (PROGRESS.md, roadmap.md, DECISIONS.md).
- File AD-691b tracking issue before closing AD-691.

## After build

GH issue close: BLOCKED by EMU 403 (consistent with Waves 31–40). Captain
must close #385 manually.
