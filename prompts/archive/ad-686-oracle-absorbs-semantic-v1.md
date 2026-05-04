# AD-686 v1 — Oracle Absorbs SemanticKnowledgeLayer (Tier 5 + 3-Consumer Migration)

**Phase A, Foundation (Unified Knowledge Graph + Oracle Unification stack — `docs/research/unified-knowledge-graph.md` §Phase A).**
**Issue:** #380.
**Depends on:** AD-462e (Oracle Service — shipped, verified at `oracle_service.py:43` / `cognitive_services.py:495`).
**Standing conventions:** Wave 5 #1 (public attrs over private), #14 (default-False for transitional flags — N/A here, see Standing Conventions section), Wave 32 retrospective (`_<service_name>` collision check — passes; new attribute is `oracle`, no collision with `_oracle_service`).

---

## v1 Scope (one line)

Add `_query_semantic()` (Tier 5) to `OracleService`; introduce a public `runtime.oracle` accessor; migrate **all three** read-path consumers (`introspect.py`, `organizer_agents.py`, `experience/commands/commands_knowledge.py::cmd_search`) to query through Oracle. `SemanticKnowledgeLayer` is unchanged (instance, write methods, `stats()`, lifecycle).

**Hard limits (deferred):**
- Write-path migration (`index_agent`/`index_skill`/etc.) → AD-686b (forcing function: when consumers of write-path proliferate, currently 4 sites in `runtime.py` + 1 in `self_mod_manager.py`).
- Removing `runtime._semantic_layer` attribute → AD-686c (forcing function: zero remaining direct consumers; not yet — `/search` still uses `layer.stats()` for panel).
- Tier reordering / unifying tier name strings → AD-686d.
- Public `oracle.query_formatted` migration of any consumer → out of scope (no current callers in introspect/organizer/`/search`).

## Verify-First Findings (HEAD `af418f3`)

| Symbol | File:line | Note |
|---|---|---|
| `class OracleService` | `src/probos/cognitive/oracle_service.py:43` | ctor kwargs-only, all defaults `None` |
| `OracleService.__init__` kwargs | `oracle_service.py:50–67` | `episodic_memory, records_store, knowledge_store, archive_store, trust_network, hebbian_router, expertise_directory` |
| `OracleService.query` | `oracle_service.py:69–151` | `tiers: list[str] | None = None`; default active list `["episodic","records","operational","archive"]` (line 91) |
| `OracleResult` | `oracle_service.py:22–30` | frozen dataclass `(source_tier, content, score, metadata, provenance)` |
| `OracleService._query_episodic` | `oracle_service.py:202–260` | private tier-method shape to mirror |
| `class SemanticKnowledgeLayer` | `src/probos/knowledge/semantic.py:22` | |
| `SemanticKnowledgeLayer.search` | `semantic.py:256–331` | `async def search(self, query: str, types: list[str] | None = None, limit: int = 10) -> list[dict]` |
| `search()` result dict shape | `semantic.py:295–303` | `{"type", "id", "document", "score", "metadata"}` |
| `SemanticKnowledgeLayer.COLLECTIONS` | `semantic.py:34–40` | `{"agents", "skills", "workflows", "qa_reports", "events"}` |
| Oracle creation site | `startup/cognitive_services.py:492–509` | created BEFORE structural-services phase |
| Semantic creation site | `startup/structural_services.py:55–69` | created LATER; runtime stitches at `runtime.py:1525` |
| Oracle wired to runtime | `runtime.py:1323` | `self._oracle_service = cog.oracle_service` (private) — no public property today |
| Semantic wired to runtime | `runtime.py:1525` | `self._semantic_layer = semantic_layer` |
| Consumer 1 (introspect) | `src/probos/agents/introspect.py:761–770` | `layer = getattr(rt, "_semantic_layer", None)` then `await layer.search(query, types=types, limit=10)` |
| Consumer 2 (organizer) | `src/probos/agents/utility/organizer_agents.py:145–146` | `if hasattr(self._runtime, "_semantic_layer") and self._runtime._semantic_layer: results = self._runtime._semantic_layer.search(query, limit=5)` — **NOTE: missing `await` on async method (pre-existing bug); migration through Oracle implicitly fixes it.** |
| Consumer 3 (`/search` shell) | `src/probos/experience/commands/commands_knowledge.py:60–84` | `layer = getattr(runtime, "_semantic_layer", None)`; `results = await layer.search(query, types=types, limit=10)`; `stats = layer.stats()` (panel render — KEEP on `_semantic_layer`, not Oracle) |
| Consumers using `_oracle_service` | `runtime.py` (n/a — only the assignment), `cognitive_agent.py:5164–5168`, `routers/system.py:337` | All use `getattr(rt, "_oracle_service", None)` — backward-compat preserved by keeping the private attr |

**No public `runtime.oracle` property exists today** — Wave 5 convention #1 (public over private) gives v1 a small Open/Closed win.

## Phantom-API Pre-Check

```
$ ./scripts/phantom-api-precheck.ps1 prompts/ad-686-oracle-absorbs-semantic-v1.md
```

Expected output documented in `prompts/WAVE-36-DISPATCH.md`:
- `OracleService.attach_semantic_layer(...)` — flagged-and-skipped as intra-prompt-introduced (Section 3a). Same FP class as Waves 27–35.
- `OracleService._query_semantic(...)` — flagged-and-skipped as intra-prompt-introduced (Section 3b).
- `class:SimpleNamespace` / `class:MagicMock` from test-fixture sections — stdlib FPs (same class as Waves 28/30/31/32/33/34/35).
- **0 NEW phantoms.**

---

## Section 0 — Naming-Collision Check (Wave 32 retrospective)

| New symbol | Collision check | Verdict |
|---|---|---|
| `OracleService._query_semantic` | grep `_query_semantic` in `src/` → 0 hits | clean |
| `OracleService.attach_semantic_layer` | grep `attach_semantic_layer` in `src/` → 0 hits | clean |
| `OracleService._semantic_layer` (instance attr) | grep on `OracleService.*_semantic_layer` → 0 hits | clean |
| `runtime.oracle` (new public property) | grep `def oracle\b` in `src/probos/runtime.py` → 0 hits; grep `\.oracle\b` consumers (`cognitive_agent.py`, `source_governance.py`, `earned_agency.py`) all reference unrelated attrs (`oracle_used`, `RecallTier.ORACLE`, `KnowledgeSource.ORACLE`) — none collide with a property of the same name | clean |
| `"semantic"` tier-name string | grep on `"semantic"` in `oracle_service.py` → 0 tier-membership hits | clean |

## Section 1 — `OracleService` constructor and late-bind setter

**File:** `src/probos/cognitive/oracle_service.py`

### 1a. Constructor parameter (keyword-only, default `None`, backward-compat preserved)

`SEARCH:`
```python
    def __init__(
        self,
        *,
        episodic_memory: Any = None,
        records_store: Any = None,
        knowledge_store: Any = None,
        archive_store: Any = None,  # AD-524
        trust_network: Any = None,
        hebbian_router: Any = None,
        expertise_directory: Any = None,
    ) -> None:
        self._episodic_memory = episodic_memory
        self._records_store = records_store
        self._knowledge_store = knowledge_store
        self._archive_store = archive_store
        self._trust_network = trust_network
        self._hebbian_router = hebbian_router
        self._expertise_directory = expertise_directory
```

`REPLACE:`
```python
    def __init__(
        self,
        *,
        episodic_memory: Any = None,
        records_store: Any = None,
        knowledge_store: Any = None,
        archive_store: Any = None,  # AD-524
        trust_network: Any = None,
        hebbian_router: Any = None,
        expertise_directory: Any = None,
        semantic_layer: Any = None,  # AD-686 (Tier 5)
    ) -> None:
        self._episodic_memory = episodic_memory
        self._records_store = records_store
        self._knowledge_store = knowledge_store
        self._archive_store = archive_store
        self._trust_network = trust_network
        self._hebbian_router = hebbian_router
        self._expertise_directory = expertise_directory
        self._semantic_layer = semantic_layer  # AD-686 (Tier 5)

    def attach_semantic_layer(self, semantic_layer: Any) -> None:
        """AD-686: Late-bind the SemanticKnowledgeLayer.

        Used by the runtime because `SemanticKnowledgeLayer` is constructed
        in the structural-services phase (after the cognitive phase that
        builds `OracleService`). Idempotent — last write wins.
        """
        self._semantic_layer = semantic_layer
```

### 1b. Add `"semantic"` to default active tiers

`SEARCH:`
```python
        if not query_text:
            return []

        active_tiers = tiers or ["episodic", "records", "operational", "archive"]
        all_results: list[OracleResult] = []
```

`REPLACE:`
```python
        if not query_text:
            return []

        active_tiers = tiers or ["episodic", "records", "operational", "archive", "semantic"]
        all_results: list[OracleResult] = []
```

### 1c. Tier-5 dispatch block (insert AFTER Tier 4 archive block, BEFORE the "Merge & sort" block)

`SEARCH:`
```python
        # Tier 4: Ship's Archive (AD-524) — cross-reset knowledge
        if self._archive_store and "archive" in active_tiers:
            try:
                tier_results = await self._query_archive(query_text, k=k_per_tier)
                all_results.extend(tier_results)
            except Exception:
                logger.debug("Oracle: Tier 4 (archive) query failed", exc_info=True)

        # Merge & sort by score descending
        all_results.sort(key=lambda r: r.score, reverse=True)
```

`REPLACE:`
```python
        # Tier 4: Ship's Archive (AD-524) — cross-reset knowledge
        if self._archive_store and "archive" in active_tiers:
            try:
                tier_results = await self._query_archive(query_text, k=k_per_tier)
                all_results.extend(tier_results)
            except Exception:
                logger.debug("Oracle: Tier 4 (archive) query failed", exc_info=True)

        # Tier 5: Semantic Knowledge Layer (AD-686) — non-episode ChromaDB collections
        if "semantic" in active_tiers:
            try:
                tier_results = await self._query_semantic(query_text, k=k_per_tier)
                all_results.extend(tier_results)
            except Exception:
                logger.debug("Oracle: Tier 5 (semantic) query failed", exc_info=True)

        # Merge & sort by score descending
        all_results.sort(key=lambda r: r.score, reverse=True)
```

### 1d. `_query_semantic` private tier method (append AFTER `_query_archive`)

`SEARCH:`
```python
            results.append(OracleResult(
                source_tier="archive",
                content=f"[{entry.category}] {entry.title}\n{entry.content}",
                score=score,
                metadata={
                    "archive_id": entry.id,
                    "timeline_id": entry.timeline_id,
                    "category": entry.category,
                    "author": entry.author_callsign or entry.author_agent_type,
                    "archived_at": entry.archived_at,
                },
                provenance=f"Archive/{entry.category} (timeline {entry.timeline_id[:8]}...)",
            ))
        return results
```

`REPLACE:`
```python
            results.append(OracleResult(
                source_tier="archive",
                content=f"[{entry.category}] {entry.title}\n{entry.content}",
                score=score,
                metadata={
                    "archive_id": entry.id,
                    "timeline_id": entry.timeline_id,
                    "category": entry.category,
                    "author": entry.author_callsign or entry.author_agent_type,
                    "archived_at": entry.archived_at,
                },
                provenance=f"Archive/{entry.category} (timeline {entry.timeline_id[:8]}...)",
            ))
        return results

    async def _query_semantic(
        self,
        query_text: str,
        *,
        k: int,
        types: list[str] | None = None,
    ) -> list[OracleResult]:
        """AD-686: Query SemanticKnowledgeLayer (Tier 5).

        Delegates to the existing async `SemanticKnowledgeLayer.search()` and
        normalises each result dict into an `OracleResult` so the merged feed
        is uniform with the other tiers. When the layer is not attached
        (test/legacy bootstrap), returns `[]` and logs at debug.
        """
        layer = self._semantic_layer
        if layer is None:
            logger.debug("Oracle: Tier 5 (semantic) — no layer attached; returning []")
            return []

        raw = await layer.search(query_text, types=types, limit=k)
        results: list[OracleResult] = []
        for r in raw:
            doc_type = r.get("type", "semantic")
            results.append(OracleResult(
                source_tier="semantic",
                content=r.get("document", "") or "",
                score=float(r.get("score", 0.0) or 0.0),
                metadata={
                    "id": r.get("id", ""),
                    "type": doc_type,
                    **(r.get("metadata") or {}),
                },
                provenance=f"[semantic: {doc_type}]",
            ))
        return results
```

## Section 2 — Runtime stitching (public `oracle` property + late-bind call)

**File:** `src/probos/runtime.py`

### 2a. Add public `oracle` property (Wave 5 #1)

`SEARCH:` (immediately after the `_oracle_service` private assignment at line 1323)
```python
        self._oracle_service = cog.oracle_service  # AD-462e
        self._archive_store = cog.archive_store  # AD-524
```

`REPLACE:`
```python
        self._oracle_service = cog.oracle_service  # AD-462e
        self.oracle = cog.oracle_service  # AD-686 (public alias; same instance)
        self._archive_store = cog.archive_store  # AD-524
```

### 2b. Late-bind semantic layer onto Oracle

`SEARCH:` (immediately after the structural-services semantic_layer assignment at line 1525)
```python
        self._semantic_layer = semantic_layer
        self.sif = struct.sif
```

`REPLACE:`
```python
        self._semantic_layer = semantic_layer
        # AD-686: Stitch Tier 5 onto Oracle now that the semantic layer exists.
        if self._oracle_service is not None and semantic_layer is not None:
            try:
                self._oracle_service.attach_semantic_layer(semantic_layer)
            except Exception:
                logger.warning(
                    "AD-686: failed to attach semantic layer to OracleService; "
                    "Tier 5 semantic queries will return [] until restart",
                    exc_info=True,
                )
        self.sif = struct.sif
```

## Section 3 — Consumer migrations (3 sites)

### 3a. `src/probos/agents/introspect.py:761-770` — `_search_knowledge` migration

`SEARCH:`
```python
        # Search semantic layer (episodes, agents, skills, workflows)
        layer = getattr(rt, "_semantic_layer", None)
        if layer is not None:
            # Parse optional types filter
            types_str = params.get("types", "")
            types: list[str] | None = None
            if types_str:
                types = [t.strip() for t in types_str.split(",") if t.strip()]
            results = await layer.search(query, types=types, limit=10)
```

`REPLACE:`
```python
        # AD-686: Search via Oracle Tier 5 (semantic). Falls back to direct layer
        # if Oracle is not present (test/legacy paths).
        oracle = getattr(rt, "oracle", None) or getattr(rt, "_oracle_service", None)
        layer = getattr(rt, "_semantic_layer", None)
        types_str = params.get("types", "")
        types: list[str] | None = None
        if types_str:
            types = [t.strip() for t in types_str.split(",") if t.strip()]
        if oracle is not None:
            oracle_results = await oracle.query(
                query, k_per_tier=10, tiers=["semantic"],
            )
            # Project OracleResult → legacy dict shape consumers expect.
            results = [
                {
                    "type": r.metadata.get("type", "semantic"),
                    "id": r.metadata.get("id", ""),
                    "document": r.content,
                    "score": r.score,
                    "metadata": {k_: v for k_, v in r.metadata.items() if k_ not in ("id", "type")},
                }
                for r in oracle_results
            ]
        elif layer is not None:
            results = await layer.search(query, types=types, limit=10)
```

### 3b. `src/probos/agents/utility/organizer_agents.py:144-149` — `NoteTakerAgent` perceive

`SEARCH:`
```python
            query = obs.get("params", {}).get("query", "")
            # Try semantic search first
            if hasattr(self._runtime, "_semantic_layer") and self._runtime._semantic_layer:
                results = self._runtime._semantic_layer.search(query, limit=5)
                if results:
                    obs["fetched_content"] = f"Search results for '{query}':\n{json.dumps(results, default=str)}"
                    return obs
```

`REPLACE:`
```python
            query = obs.get("params", {}).get("query", "")
            # AD-686: Try semantic search via Oracle Tier 5. (Note: the prior
            # call site used `_semantic_layer.search(...)` synchronously on an
            # async method; routing through Oracle awaits properly.)
            oracle = getattr(self._runtime, "oracle", None) or getattr(
                self._runtime, "_oracle_service", None,
            )
            if oracle is not None:
                oracle_results = await oracle.query(
                    query, k_per_tier=5, tiers=["semantic"],
                )
                if oracle_results:
                    results = [
                        {
                            "type": r.metadata.get("type", "semantic"),
                            "id": r.metadata.get("id", ""),
                            "document": r.content,
                            "score": r.score,
                        }
                        for r in oracle_results
                    ]
                    obs["fetched_content"] = f"Search results for '{query}':\n{json.dumps(results, default=str)}"
                    return obs
```

### 3c. `src/probos/experience/commands/commands_knowledge.py:60-84` — `cmd_search`

`SEARCH:`
```python
async def cmd_search(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /search command."""
    from probos.experience import panels

    layer = getattr(runtime, "_semantic_layer", None)
    if layer is None:
        console.print("[yellow]Semantic knowledge layer not available[/yellow]")
        return

    # Parse optional --type filter
    query = args.strip()
    types: list[str] | None = None
    if query.startswith("--type "):
        parts = query.split(maxsplit=2)
        if len(parts) >= 3:
            types = [t.strip() for t in parts[1].split(",") if t.strip()]
            query = parts[2]
        else:
            console.print("[yellow]Usage: /search [--type agents,skills] <query>[/yellow]")
            return

    if not query:
        console.print("[yellow]Usage: /search [--type agents,skills] <query>[/yellow]")
        return

    results = await layer.search(query, types=types, limit=10)
    stats = layer.stats()
    console.print(panels.render_search_panel(query, results, stats))
```

`REPLACE:`
```python
async def cmd_search(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /search command."""
    from probos.experience import panels

    layer = getattr(runtime, "_semantic_layer", None)
    if layer is None:
        console.print("[yellow]Semantic knowledge layer not available[/yellow]")
        return

    # Parse optional --type filter
    query = args.strip()
    types: list[str] | None = None
    if query.startswith("--type "):
        parts = query.split(maxsplit=2)
        if len(parts) >= 3:
            types = [t.strip() for t in parts[1].split(",") if t.strip()]
            query = parts[2]
        else:
            console.print("[yellow]Usage: /search [--type agents,skills] <query>[/yellow]")
            return

    if not query:
        console.print("[yellow]Usage: /search [--type agents,skills] <query>[/yellow]")
        return

    # AD-686: Query via Oracle Tier 5 when available; fall back to direct
    # layer for legacy paths. Stats panel still reads `layer.stats()` —
    # stats migration is deferred (no Oracle equivalent in v1).
    oracle = getattr(runtime, "oracle", None) or getattr(runtime, "_oracle_service", None)
    if oracle is not None:
        oracle_results = await oracle.query(query, k_per_tier=10, tiers=["semantic"])
        results = [
            {
                "type": r.metadata.get("type", "semantic"),
                "id": r.metadata.get("id", ""),
                "document": r.content,
                "score": r.score,
                "metadata": {k_: v for k_, v in r.metadata.items() if k_ not in ("id", "type")},
            }
            for r in oracle_results
        ]
    else:
        results = await layer.search(query, types=types, limit=10)
    stats = layer.stats()
    console.print(panels.render_search_panel(query, results, stats))
```

## Section 4 — Tests

**File:** `tests/test_ad686_oracle_semantic_tier.py` (NEW)

11 focused tests (over the ≥7 floor by 4 — extras cover one-line-of-defence per consumer):

1. **`test_query_semantic_method_shape`** — `OracleService` exposes `_query_semantic` with the documented signature; `attach_semantic_layer` is callable, idempotent, accepts `None`.
2. **`test_query_semantic_happy_path_with_stub_layer`** — Stub layer returns 3 dicts (mixed `type` values: agents, skills, workflows); `_query_semantic` returns 3 `OracleResult`s with `source_tier="semantic"`, `provenance="[semantic: <type>]"`, `metadata` carries `id`/`type` plus original metadata flattened.
3. **`test_query_semantic_none_layer_returns_empty_and_logs`** — No semantic layer attached → `[]` returned; caplog captures one DEBUG line containing `"Tier 5"`.
4. **`test_query_semantic_types_passthrough`** — `types=["agents","skills"]` is forwarded to `layer.search(...)`; `limit=k` is forwarded as `limit=k`.
5. **`test_query_semantic_score_coercion`** — Stub layer returns `{"score": None}` and `{"score": "0.7"}` rows → both coerce cleanly (`0.0` and `0.7` floats; no exception).
6. **`test_semantic_in_default_active_tiers`** — `OracleService.query("anything")` with all tiers `None`-defaulted invokes `_query_semantic` exactly once (verified by spy on the layer).
7. **`test_attach_semantic_layer_late_bind_works`** — Construct Oracle with `semantic_layer=None`, call `attach_semantic_layer(stub)`, then `await query(...)` returns semantic results.
8. **`test_introspect_search_knowledge_uses_oracle`** — Patch `runtime.oracle` to a stub; call `IntrospectionAgent._search_knowledge` with a `search_knowledge` action; assert `oracle.query` was awaited with `tiers=["semantic"]` and the projected dict shape carries `type`/`id`/`document`/`score`/`metadata`.
9. **`test_organizer_note_taker_uses_oracle_and_awaits`** — Patch `self._runtime.oracle` to an `AsyncMock`; call `NoteTakerAgent.perceive` with `action=search`; assert `oracle.query` was awaited (regression on the missing-`await` bug); `obs["fetched_content"]` contains `"Search results for"`.
10. **`test_cmd_search_uses_oracle_and_keeps_stats_panel`** — Patch `runtime.oracle` and `runtime._semantic_layer` (for `stats()`); call `cmd_search`; `oracle.query` awaited with `tiers=["semantic"]`; `layer.stats()` called once; panel render receives the projected dict list.
11. **`test_end_to_end_query_returns_normalized_oracle_results`** — Real `OracleService` + stub semantic layer + stub episodic memory; `await oracle.query("foo")` returns merged list sorted by score; semantic entries have `source_tier="semantic"` and provenance prefix `"[semantic:"`.

**Test count baseline:** 10957 (Wave 35 baseline post-build).
**Expected after build:** 10968 (+11). _Drop targets if Builder finds count drift: tests #5 and #11 (lowest unique signal)._

## What This AD Does NOT Change

| Out | Where it lives next |
|---|---|
| `SemanticKnowledgeLayer` write methods (`index_agent`/`index_skill`/`index_workflow`/`index_qa_report`/`index_event`) | unchanged; consumer-side write migration → AD-686b |
| `SemanticKnowledgeLayer.stats()` and `reindex_from_store()` | unchanged; still callable on `runtime._semantic_layer` |
| `runtime._semantic_layer` attribute | preserved (still consumed by stats panel + warm-boot reindex) |
| Tier numbering / reordering | no change |
| New EventType | none |
| New Pydantic config | none |
| New router / API endpoint | none |
| New shell command | none |
| Federation / classification edges | AD-687–AD-694 (Phase B/C of unified-knowledge-graph stack) |
| Embedding model swap | AD-584a (already shipped) — out of scope |
| `oracle.query_formatted` migration | no current callers in the 3 migrated sites |

## Standing Conventions

- Wave 5 #1 (public over private): `runtime.oracle` is added as the public alias; `_oracle_service` is preserved for backward compat.
- Wave 5 #14 (default-False for transitional flags): N/A — this AD has no Pydantic config; the additive change is enabled when the semantic layer exists, which is the **already shipped** default behaviour.
- Wave 32 retrospective (`_<service_name>` collision): checked in Section 0 — no collision on `oracle`, `_query_semantic`, `attach_semantic_layer`.
- Wave 10 lesson (phantom-API method-shape): Builder must run `./scripts/phantom-api-precheck.ps1` before commit and confirm no NEW phantoms beyond the 2 documented intra-prompt FPs.

## Acceptance Criteria

1. Full parallel gate green at `pytest tests/ -q -n 8 --dist=loadfile`.
2. Test-count delta `+11` vs Wave 35 baseline 10957 → **10968**. (If +9 due to test #5 / #11 drop, document in build report.)
3. `OracleService._query_semantic` exists with the spec'd signature; `OracleService.attach_semantic_layer` is callable and idempotent; constructor accepts `semantic_layer=` kwarg with default `None`.
4. `runtime.oracle` is the same instance as `runtime._oracle_service` after startup.
5. All three migrated consumer sites pass through Oracle when present, fall back to legacy direct layer call when Oracle is absent (test/legacy paths).
6. `runtime._semantic_layer` is still attached to `runtime` (NOT removed); `layer.stats()` still callable from `cmd_search`.
7. Phantom-API pre-check exits 1 with **only** the 2 documented intra-prompt FPs (`OracleService.attach_semantic_layer`, `OracleService._query_semantic`) plus the standard stdlib `class:SimpleNamespace`/`class:MagicMock` FPs from the test sections — **0 NEW**.
8. PROGRESS.md flipped from `AD-686` planned → `AD-686 v1 CLOSED` with concrete one-line summary.
9. `docs/development/roadmap.md` AD-686 entry status flipped to `complete`.
10. DECISIONS.md AD-686 entry appended (no rewrite of prior entries).
11. Issue #380 closed on merge (or surfaced for manual close per EMU 403).
12. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Tracking

- `PROGRESS.md` line 1 (status flip + one-line summary).
- `docs/development/roadmap.md` AD-686 entry (status flip).
- `DECISIONS.md` (append AD-686 closure line; no rewrite).
- `prompts/wave-plan.yaml` id="36" (status `pending` → `done` after build report).
