# AD-686b v1 — Oracle Owns SemanticKnowledgeLayer Write-Path

**Status:** Ready for build.
**Dependencies:** AD-686 v1 (Wave 36, read-path migration through Oracle Tier 5) — SHIPPED.
**Estimated tests:** 12 new in `tests/test_ad686b_oracle_write_semantic.py`. Test-count baseline 11158 (Wave 49) → expected 11170.

---

## Problem

AD-686 v1 (Wave 36) migrated the **read** path through `OracleService` Tier 5 (`semantic`): three direct `SemanticKnowledgeLayer.search()` consumers (`IntrospectionAgent._search_knowledge`, `NoteTakerAgent.perceive`, `cmd_search`) now route through `runtime.oracle.query(..., tiers=["semantic"])` and project results back. Wave 36 explicitly deferred the **write** path — five `SemanticKnowledgeLayer.index_*` call sites continue to reach the layer directly:

```
src/probos/runtime.py:2508          self._semantic_layer.index_agent(...)        # AD-243 designed-agent persist
src/probos/runtime.py:3309          self._semantic_layer.index_skill(...)        # AD-243 skill persist
src/probos/runtime.py:3358          self._semantic_layer.index_qa_report(...)    # QA report persist
src/probos/self_mod_manager.py:142  self._semantic_layer.index_agent(...)        # patched-agent re-index
src/probos/routers/chat.py:419      rt._semantic_layer.index_agent(...)          # chat-driven design indexing
```

This means: (1) the OSS surface for "Oracle owns the semantic feed" is **half-built**; (2) future commercial overlays (audit, RBAC, multi-tenant) that wrap `OracleService` cannot intercept writes — they only see reads; (3) any write-side governance change (rate-limit, classification tag injection, deferred indexing queue) has five places to land instead of one.

AD-686b closes this seam: every write to the semantic feed flows through `OracleService.write_semantic(...)`. `SemanticKnowledgeLayer.index_*` methods remain callable (Oracle delegates to them) so internal calls (`reindex_from_store` at `semantic.py:360/376/397/413`) and any ad-hoc test rigs continue to work. No deletions in this AD.

---

## Verified Against Codebase (HEAD `d0f2eab`, 2026-05-05)

```
grep -n "attach_semantic_layer\|semantic_layer\|_query_semantic\|active_tiers" src/probos/cognitive/oracle_service.py
  131:        semantic_layer: Any = None,  # AD-686 (Tier 5)
  142:        self._semantic_layer = semantic_layer  # AD-686 (Tier 5)
  146:    def attach_semantic_layer(self, semantic_layer: Any) -> None:
  153:        self._semantic_layer = semantic_layer
  201:        active_tiers = tiers or [
  207:        if self._episodic_memory and "episodic" in active_tiers:
  260:        if "semantic" in active_tiers:
  262:            tier_results = await self._query_semantic(query_text, k=k_per_tier)
  470:    async def _query_semantic(

grep -n "^\s*async def index_" src/probos/knowledge/semantic.py
  123:    async def index_agent(self, agent_type, intent_name, description, strategy, source_snippet="", source_node="") -> None
  152:    async def index_skill(self, intent_name, description, target_agent="", source_node="") -> None
  176:    async def index_workflow(self, pattern, intent_names, hit_count=0, source_node="") -> None
  201:    async def index_qa_report(self, agent_type, verdict, pass_rate, source_node="") -> None
  226:    async def index_event(self, category, event, detail, source_node="") -> None

grep -n "_semantic_layer\.index_" src/probos/**/*.py
  src/probos/runtime.py:2508             await self._semantic_layer.index_agent(...)
  src/probos/runtime.py:3309             await self._semantic_layer.index_skill(...)
  src/probos/runtime.py:3358             await self._semantic_layer.index_qa_report(...)
  src/probos/self_mod_manager.py:142     await self._semantic_layer.index_agent(...)
  src/probos/routers/chat.py:419         await rt._semantic_layer.index_agent(...)
  src/probos/knowledge/semantic.py:360,376,397,413  (internal reindex_from_store; out of scope)

grep -n "self\.oracle\b\|self\._oracle_service" src/probos/runtime.py
  1343:        self._oracle_service = cog.oracle_service       # AD-462e (legacy private)
  1344:        self.oracle = cog.oracle_service                # AD-686  (public alias; same instance)
  1549,1551:  attach_semantic_layer late-bind
  1632,1634:  attach_knowledge_graph late-bind
```

**Findings.**

1. SemanticKnowledgeLayer has **no uniform `add()` method** — its write surface is five distinct typed `async def index_*` methods with collection-specific kwargs. Captain spec's `write_semantic(entries, *, collection)` shape would force callers to pack dicts that the layer would then unpack, which is a regression in type safety. Decision: ship `OracleService.write_semantic(kind, /, **fields) -> bool` — keyword-dispatched by `kind` to the matching `layer.index_<kind>` method. Returns `bool` (True=delegated, False=dropped). See **DLog #1**.
2. Five external write-path call sites identified (above). Two SemanticKnowledgeLayer write methods (`index_workflow`, `index_event`) have **no external caller at HEAD** — only `reindex_from_store` invokes them internally. v1 still ships `kind="workflow"` and `kind="event"` dispatch for completeness; no migration sites for those two. See **DLog #2**.
3. Oracle is publicly available as `runtime.oracle` (Wave 36, `runtime.py:1344`); `runtime._oracle_service` is the legacy private alias, same instance. Migration sites use `runtime.oracle` directly when on `runtime.py`, and `getattr(rt, "oracle", None) or getattr(rt, "_oracle_service", None)` chain when on a router/manager that may receive a stub runtime in tests (Wave 36 pattern at `introspect.py:761` / `commands_knowledge.py:60` / `organizer_agents.py:144`).
4. **SemanticKnowledgeLayer cannot be made internal in v1.** Even after this AD's 5 migrations land, `runtime._semantic_layer` is still consumed by:
   - `agents/introspect.py:764` — read-path fallback when `runtime.oracle` is missing on a stub
   - `runtime.py:2973-2974` — `_semantic_layer.stats()` for the system-status panel (no Oracle stats surface today)
   See **DLog #3**.

---

## Solution

### Section 0 — `OracleService.write_semantic` dispatcher

Add one new public async method on `OracleService` immediately after `attach_health_provider` (the last setter in the attach-cluster). Five-kind keyword dispatcher; tier-2 log-and-degrade.

```python
async def write_semantic(self, kind: str, /, **fields: Any) -> bool:
    """AD-686b: Write a record to SemanticKnowledgeLayer through the Oracle.

    Five supported kinds map to the corresponding ``SemanticKnowledgeLayer``
    method:

    - ``"agent"``    → ``layer.index_agent(agent_type, intent_name, description, strategy, source_snippet="", source_node="")``
    - ``"skill"``    → ``layer.index_skill(intent_name, description, target_agent="", source_node="")``
    - ``"workflow"`` → ``layer.index_workflow(pattern, intent_names, hit_count=0, source_node="")``
    - ``"qa_report"``→ ``layer.index_qa_report(agent_type, verdict, pass_rate, source_node="")``
    - ``"event"``    → ``layer.index_event(category, event, detail, source_node="")``

    Tier-2 log-and-degrade: returns ``False`` and logs at debug if the
    semantic layer is not attached, returns ``False`` and logs a warning
    if ``kind`` is unknown, returns ``False`` and logs a warning if
    delegation raises (never propagates to caller). Returns ``True`` only
    when the underlying ``index_<kind>`` call completes successfully.

    Mirrors ``attach_semantic_layer`` shape: stays narrow, depends only on
    the layer's existing typed write surface. No new fields, no new kinds
    in v1 — adding a kind requires an enum extension here AND a matching
    ``index_<kind>`` on ``SemanticKnowledgeLayer``.
    """
    layer = self._semantic_layer
    if layer is None:
        logger.debug(
            "Oracle: write_semantic(%s) — no semantic layer attached; dropping", kind,
        )
        return False
    method = getattr(layer, f"index_{kind}", None)
    if method is None:
        logger.warning(
            "Oracle: write_semantic(%s) — unknown kind (no layer.index_%s)", kind, kind,
        )
        return False
    try:
        await method(**fields)
        return True
    except Exception:
        logger.warning(
            "Oracle: write_semantic(%s) — delegation failed", kind, exc_info=True,
        )
        return False
```

**SEARCH/REPLACE in `src/probos/cognitive/oracle_service.py`** — anchor on the closing line of `attach_health_provider` (`self._health_provider = health_provider`):

```python
# SEARCH (3 lines context above + 3 below):
        BEFORE the cognitive phase that builds OracleService. Idempotent —
        last write wins.
        """
        self._health_provider = health_provider

    # ------------------------------------------------------------------
    # AD-462e: query() — cross-tier dispatch
```

```python
# REPLACE:
        BEFORE the cognitive phase that builds OracleService. Idempotent —
        last write wins.
        """
        self._health_provider = health_provider

    # ------------------------------------------------------------------
    # AD-686b: write_semantic — Oracle owns the semantic write feed
    # ------------------------------------------------------------------
    async def write_semantic(self, kind: str, /, **fields: Any) -> bool:
        """AD-686b: Write a record to SemanticKnowledgeLayer through the Oracle.

        Five supported kinds: ``"agent"`` / ``"skill"`` / ``"workflow"`` /
        ``"qa_report"`` / ``"event"``. Tier-2 log-and-degrade: returns
        ``False`` (and logs) if the layer is not attached, the kind is
        unknown, or delegation raises. Returns ``True`` only when the
        underlying ``layer.index_<kind>(**fields)`` completes successfully.
        Mirrors the existing read-path Tier 5 (``_query_semantic``) shape.
        """
        layer = self._semantic_layer
        if layer is None:
            logger.debug(
                "Oracle: write_semantic(%s) — no semantic layer attached; dropping", kind,
            )
            return False
        method = getattr(layer, f"index_{kind}", None)
        if method is None:
            logger.warning(
                "Oracle: write_semantic(%s) — unknown kind (no layer.index_%s)",
                kind, kind,
            )
            return False
        try:
            await method(**fields)
            return True
        except Exception:
            logger.warning(
                "Oracle: write_semantic(%s) — delegation failed", kind, exc_info=True,
            )
            return False

    # ------------------------------------------------------------------
    # AD-462e: query() — cross-tier dispatch
```

### Section 1 — Migrate `runtime.py:2508` (designed-agent index_agent)

**SEARCH** (anchor on the `# Auto-index for semantic search (AD-243)` comment block at the designed-agent persist site):

```python
                            # Auto-index for semantic search (AD-243)
                            if self._semantic_layer:
                                try:
                                    await self._semantic_layer.index_agent(
                                        agent_type=record.agent_type,
                                        intent_name=record.intent_name,
                                        description=record.intent_name,
                                        strategy=record.strategy,
                                        source_snippet=record.source_code[:200] if record.source_code else "",
                                    )
                                except Exception:
                                    logger.debug("Semantic layer indexing failed", exc_info=True)
```

**REPLACE**:

```python
                            # AD-686b: route through Oracle write-path
                            await self.oracle.write_semantic(
                                "agent",
                                agent_type=record.agent_type,
                                intent_name=record.intent_name,
                                description=record.intent_name,
                                strategy=record.strategy,
                                source_snippet=record.source_code[:200] if record.source_code else "",
                            )
```

The `if self._semantic_layer:` gate and the inline try/except are no longer needed — `Oracle.write_semantic` returns `False` + logs at debug when the layer is unattached, and wraps the delegation in its own try/except.

### Section 2 — Migrate `runtime.py:3309` (skill index_skill)

**SEARCH**:

```python
        # Auto-index skill for semantic search (AD-243)
        if self._semantic_layer:
            try:
                await self._semantic_layer.index_skill(
                    intent_name=skill.name,
                    description=skill.descriptor.description if skill.descriptor else skill.name,
                    target_agent=getattr(skill, "target_agent", ""),
                )
            except Exception:
                logger.debug("Semantic skill indexing failed", exc_info=True)
```

**REPLACE**:

```python
        # AD-686b: route through Oracle write-path
        await self.oracle.write_semantic(
            "skill",
            intent_name=skill.name,
            description=skill.descriptor.description if skill.descriptor else skill.name,
            target_agent=getattr(skill, "target_agent", ""),
        )
```

### Section 3 — Migrate `runtime.py:3358` (QA report index_qa_report)

**SEARCH**:

```python
            # Auto-index QA report for semantic search (AD-243)
            if self._semantic_layer:
                try:
                    await self._semantic_layer.index_qa_report(
                        agent_type=record.agent_type,
                        verdict=report.verdict,
                        pass_rate=report.passed / report.total_tests if report.total_tests > 0 else 0.0,
                    )
                except Exception:
                    logger.debug("Semantic QA report indexing failed", exc_info=True)
```

**REPLACE**:

```python
            # AD-686b: route through Oracle write-path
            await self.oracle.write_semantic(
                "qa_report",
                agent_type=record.agent_type,
                verdict=report.verdict,
                pass_rate=report.passed / report.total_tests if report.total_tests > 0 else 0.0,
            )
```

### Section 4 — Migrate `self_mod_manager.py:142` (patched-agent index_agent)

`SelfModManager` already holds `self._runtime` (line 83). Use the public alias with a defensive fallback (Wave 36 pattern) to tolerate stub runtimes in older tests.

**SEARCH**:

```python
        # Auto-index for semantic search (AD-243)
        if self._semantic_layer:
            try:
                await self._semantic_layer.index_agent(
                    agent_type=original_record.agent_type,
                    intent_name=original_record.intent_name,
                    description=original_record.intent_name,
                    strategy=original_record.strategy,
                    source_snippet=patch_result.patched_source[:200] if patch_result.patched_source else "",
                )
            except Exception:
                logger.debug("Semantic layer indexing failed", exc_info=True)
```

**REPLACE**:

```python
        # AD-686b: route through Oracle write-path
        oracle = getattr(self._runtime, "oracle", None) or getattr(self._runtime, "_oracle_service", None)
        if oracle is not None:
            await oracle.write_semantic(
                "agent",
                agent_type=original_record.agent_type,
                intent_name=original_record.intent_name,
                description=original_record.intent_name,
                strategy=original_record.strategy,
                source_snippet=patch_result.patched_source[:200] if patch_result.patched_source else "",
            )
```

The `if self._semantic_layer:` ctor field stays (other consumers may still touch it; cleanup is AD-686c territory). The migration just stops reaching the layer directly here.

### Section 5 — Migrate `routers/chat.py:419` (chat-driven design index_agent)

This site sets a `semantic_indexed` bool fed back into the response payload. `Oracle.write_semantic` returning `bool` is exactly the signal needed.

**SEARCH**:

```python
            semantic_indexed = False
            if rt._semantic_layer:
                try:
                    await rt._semantic_layer.index_agent(
                        agent_type=record.agent_type,
                        intent_name=record.intent_name,
                        description=record.intent_name,
                        strategy=record.strategy,
                        source_snippet=record.source_code[:200] if record.source_code else "",
                    )
                    semantic_indexed = True
                except Exception:
                    logger.warning(
                        "Failed to index agent '%s' in semantic layer",
                        record.agent_type, exc_info=True,
                    )
```

**REPLACE**:

```python
            # AD-686b: route through Oracle write-path
            oracle = getattr(rt, "oracle", None) or getattr(rt, "_oracle_service", None)
            semantic_indexed = False
            if oracle is not None:
                semantic_indexed = await oracle.write_semantic(
                    "agent",
                    agent_type=record.agent_type,
                    intent_name=record.intent_name,
                    description=record.intent_name,
                    strategy=record.strategy,
                    source_snippet=record.source_code[:200] if record.source_code else "",
                )
```

### Section 6 — Tests (`tests/test_ad686b_oracle_write_semantic.py`, NEW)

12 focused tests over the 10 floor by 2.

```python
"""AD-686b: OracleService.write_semantic — semantic write-path migration."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.oracle_service import OracleService


def _oracle_with_layer(layer: object) -> OracleService:
    return OracleService(semantic_layer=layer)


# 1. Method shape — async, present, returns bool.
@pytest.mark.asyncio
async def test_write_semantic_method_shape() -> None:
    layer = MagicMock()
    layer.index_agent = AsyncMock()
    oracle = _oracle_with_layer(layer)
    assert hasattr(oracle, "write_semantic")
    result = await oracle.write_semantic("agent", agent_type="x", intent_name="y",
                                          description="d", strategy="s")
    assert isinstance(result, bool)


# 2. agent kind delegates with kwargs forwarded.
@pytest.mark.asyncio
async def test_write_semantic_agent_delegates() -> None:
    layer = MagicMock()
    layer.index_agent = AsyncMock()
    oracle = _oracle_with_layer(layer)
    ok = await oracle.write_semantic(
        "agent", agent_type="ax", intent_name="iy", description="dz",
        strategy="strat", source_snippet="snip",
    )
    assert ok is True
    layer.index_agent.assert_awaited_once_with(
        agent_type="ax", intent_name="iy", description="dz",
        strategy="strat", source_snippet="snip",
    )


# 3. skill kind delegates.
@pytest.mark.asyncio
async def test_write_semantic_skill_delegates() -> None:
    layer = MagicMock()
    layer.index_skill = AsyncMock()
    oracle = _oracle_with_layer(layer)
    ok = await oracle.write_semantic("skill", intent_name="i", description="d",
                                      target_agent="t")
    assert ok is True
    layer.index_skill.assert_awaited_once_with(intent_name="i", description="d",
                                                target_agent="t")


# 4. workflow kind delegates (no external caller at HEAD; surface still ships).
@pytest.mark.asyncio
async def test_write_semantic_workflow_delegates() -> None:
    layer = MagicMock()
    layer.index_workflow = AsyncMock()
    oracle = _oracle_with_layer(layer)
    ok = await oracle.write_semantic("workflow", pattern="p",
                                      intent_names=["a", "b"], hit_count=3)
    assert ok is True
    layer.index_workflow.assert_awaited_once()


# 5. qa_report kind delegates.
@pytest.mark.asyncio
async def test_write_semantic_qa_report_delegates() -> None:
    layer = MagicMock()
    layer.index_qa_report = AsyncMock()
    oracle = _oracle_with_layer(layer)
    ok = await oracle.write_semantic("qa_report", agent_type="ax",
                                      verdict="pass", pass_rate=0.9)
    assert ok is True
    layer.index_qa_report.assert_awaited_once()


# 6. event kind delegates (no external caller at HEAD).
@pytest.mark.asyncio
async def test_write_semantic_event_delegates() -> None:
    layer = MagicMock()
    layer.index_event = AsyncMock()
    oracle = _oracle_with_layer(layer)
    ok = await oracle.write_semantic("event", category="c", event="e", detail="d")
    assert ok is True
    layer.index_event.assert_awaited_once()


# 7. None layer returns False + logs at debug + does NOT raise.
@pytest.mark.asyncio
async def test_write_semantic_none_layer_returns_false(caplog: pytest.LogCaptureFixture) -> None:
    oracle = OracleService(semantic_layer=None)
    with caplog.at_level(logging.DEBUG, logger="probos.cognitive.oracle_service"):
        ok = await oracle.write_semantic("agent", agent_type="x", intent_name="y",
                                          description="d", strategy="s")
    assert ok is False
    assert any("no semantic layer attached" in r.message for r in caplog.records)


# 8. Unknown kind returns False + warning + does NOT call layer.
@pytest.mark.asyncio
async def test_write_semantic_unknown_kind_returns_false(caplog: pytest.LogCaptureFixture) -> None:
    layer = MagicMock()
    oracle = _oracle_with_layer(layer)
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.oracle_service"):
        ok = await oracle.write_semantic("nonexistent", foo=1)
    assert ok is False
    assert any("unknown kind" in r.message for r in caplog.records)


# 9. Delegation exception → False + warning, never propagates.
@pytest.mark.asyncio
async def test_write_semantic_delegation_exception_caught(caplog: pytest.LogCaptureFixture) -> None:
    layer = MagicMock()
    layer.index_agent = AsyncMock(side_effect=RuntimeError("layer is on fire"))
    oracle = _oracle_with_layer(layer)
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.oracle_service"):
        ok = await oracle.write_semantic(
            "agent", agent_type="x", intent_name="y", description="d", strategy="s",
        )
    assert ok is False
    assert any("delegation failed" in r.message for r in caplog.records)


# 10. Late-bind (attach_semantic_layer): write_semantic is False before attach,
#     True after.
@pytest.mark.asyncio
async def test_write_semantic_late_bind_via_attach() -> None:
    oracle = OracleService(semantic_layer=None)
    ok_before = await oracle.write_semantic("agent", agent_type="x",
                                             intent_name="y", description="d",
                                             strategy="s")
    assert ok_before is False
    layer = MagicMock()
    layer.index_agent = AsyncMock()
    oracle.attach_semantic_layer(layer)
    ok_after = await oracle.write_semantic("agent", agent_type="x",
                                            intent_name="y", description="d",
                                            strategy="s")
    assert ok_after is True
    layer.index_agent.assert_awaited_once()


# 11. Backward compat — SemanticKnowledgeLayer write methods unchanged.
def test_semantic_layer_write_methods_unchanged() -> None:
    """AD-686b ships ZERO changes to SemanticKnowledgeLayer.

    Locks down: the five typed write methods still exist with the same names
    so the Oracle dispatcher's getattr-by-kind continues to resolve them, and
    so internal `reindex_from_store` (semantic.py:360/376/397/413) keeps
    working. Asserts presence by name + async-callable shape.
    """
    import inspect
    from probos.knowledge.semantic import SemanticKnowledgeLayer
    for name in ("index_agent", "index_skill", "index_workflow",
                 "index_qa_report", "index_event"):
        method = getattr(SemanticKnowledgeLayer, name, None)
        assert method is not None, f"AD-686b regression: {name} missing"
        assert inspect.iscoroutinefunction(method), f"{name} no longer async"


# 12. Migration smoke — each of the 5 sites now imports `oracle.write_semantic`.
def test_migrated_sites_use_oracle_write_semantic() -> None:
    """Static smoke: every migrated source file references
    `oracle.write_semantic(` and no longer calls
    `_semantic_layer.index_*` directly outside the legacy ctor field gate.

    Locks the migration in place so a future refactor does not silently
    revert one of the five sites.
    """
    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent
    sites = [
        repo / "src" / "probos" / "runtime.py",
        repo / "src" / "probos" / "self_mod_manager.py",
        repo / "src" / "probos" / "routers" / "chat.py",
    ]
    for path in sites:
        text = path.read_text(encoding="utf-8")
        # Must contain at least one Oracle write-path call.
        assert "oracle.write_semantic(" in text, (
            f"AD-686b regression: {path.name} no longer routes through Oracle"
        )
    # Strong invariant: count of direct `_semantic_layer.index_*` writes in
    # the three migrated files is ZERO. semantic.py's internal reindex calls
    # are excluded by file scope.
    direct = 0
    for path in sites:
        text = path.read_text(encoding="utf-8")
        for kind in ("index_agent", "index_skill", "index_workflow",
                     "index_qa_report", "index_event"):
            direct += text.count(f"_semantic_layer.{kind}(")
    assert direct == 0, (
        f"AD-686b regression: {direct} direct _semantic_layer.index_* writes "
        "remain in migrated files"
    )
```

---

## What This AD Does NOT Change

- **No deletion of `SemanticKnowledgeLayer`** — Oracle delegates to it. `reindex_from_store` (`semantic.py:360/376/397/413`) keeps invoking `self.index_*` internally.
- **No deletion of `runtime._semantic_layer` attribute** — `agents/introspect.py:764` still uses it as a read-path fallback when `runtime.oracle` is missing on a stub, and `runtime.py:2973-2974` calls `_semantic_layer.stats()` for the system-status panel (no Oracle stats surface today). Both are AD-686c territory. See **DLog #3**.
- **No new EventType, no new Pydantic config, no new module, no new public attribute on runtime.** All edits land inside existing files.
- **No write-path classification gating** — that's AD-692-style work and applies to `KnowledgeEdge`, not the semantic feed. AD-692 already ships for edges; semantic gating is out of scope.
- **No deferred-write queue, no rate-limit, no audit emission** on `write_semantic`. Tier-2 log-and-degrade is the entire policy in v1. Forcing functions for any of those would be AD-686b-{a/b/c} grandchildren if signal emerges.
- **No migration of `index_workflow` / `index_event` — neither has an external caller at HEAD.** Dispatcher still ships those two kinds for completeness (and for `reindex_from_store` parity if a future Oracle-aware reindex routes through `write_semantic`).

---

## Architect Decision Log

**DLog #1 — `write_semantic(kind, /, **fields)` instead of Captain's `(entries, *, collection)`.**
SemanticKnowledgeLayer has no uniform `add()` method. Five typed methods, five different kwarg sets. Forcing callers to pack dicts (`{"agent_type": ..., "intent_name": ...}`) that the layer then unpacks would be a regression in type safety and would require either (a) per-kind validators inside the dispatcher (re-implementing what the typed methods already check), or (b) silently dropping unknown fields. Keyword dispatch by `kind` is the closest faithful mirror and stays narrow. Captain's spec acknowledged this: *"or async equivalent — match SemanticKnowledgeLayer.add signature"*. We match the actual surface.

**DLog #2 — `index_workflow` / `index_event` ship with no migration site.**
At HEAD, both methods are only invoked internally by `reindex_from_store`. They're real surfaces (the schema includes `workflows` and `events` collections), so the dispatcher supports them for completeness. No migration tests exist for those two paths in this AD; if a future caller appears, it routes through `oracle.write_semantic("workflow"|"event", ...)` from day one.

**DLog #3 — SemanticKnowledgeLayer cannot be made internal in v1.**
Captain spec said *"evaluate whether SemanticKnowledgeLayer can be made internal (`_` prefixed) — IF the only remaining external callers are tests and Oracle itself"*. After this AD's 5 migrations, two non-test external consumers remain:

1. `agents/introspect.py:764` — `getattr(rt, "_semantic_layer", None)` read-path fallback when `runtime.oracle` is missing on a stub runtime (the migration here in Wave 36 already prefers `runtime.oracle` first; the `_semantic_layer` fallback is for legacy test rigs only — but it's a real reference).
2. `runtime.py:2973-2974` — `self._semantic_layer.stats()` feeding the `/system` shell command stats panel. Oracle has no stats surface today (Wave 36 explicitly deferred this — *"no Oracle stats surface in v1 → `runtime._semantic_layer` preserved"*). Migrating this without an Oracle stats method would force calling `runtime.oracle._semantic_layer.stats()`, which is worse Demeter than current state.

Conclusion: do **not** rename `SemanticKnowledgeLayer` → `_SemanticKnowledgeLayer` in this AD. The rename can land in **AD-686c** once: (a) `OracleService.semantic_stats() -> dict` surface is added, (b) `cmd_search` migrates to use it, and (c) the `introspect.py:764` fallback is dropped or replaced with an `oracle`-aware read.

**DLog #4 — `write_semantic` returns `bool`, not `int`.**
Captain spec mentioned `int` ("1 if written, 0 if dropped"). For a single-record dispatcher there's no aggregation — bool is the cleaner type. `routers/chat.py:419` migration consumes the return as a bool flag (`semantic_indexed = await oracle.write_semantic(...)`); `int` would force `bool(result)` everywhere. Switched to `bool`.

**DLog #5 — Migration sites drop the `if self._semantic_layer:` guard.**
The Wave 36 read-path migration kept the legacy direct-layer fallback to handle MagicMock-based test rigs (test files that mock `_semantic_layer` directly without setting up an Oracle). Write-path is different: every migrated site already had its own try/except → `logger.debug` swallow. `Oracle.write_semantic` now provides that exact behaviour internally, so the site's local guard + try/except becomes redundant. Drop both. Existing tests that mock `runtime._semantic_layer.index_*` directly (none exist at HEAD per `tests/` grep) would need to mock `runtime.oracle.write_semantic` instead — handled by Test #12's static lock.

**DLog #6 — `self_mod_manager.py` keeps its `_semantic_layer` ctor field.**
The migration at Section 4 only touches the call site. The ctor still receives `semantic_layer=...` and stores `self._semantic_layer`. Future cleanup (drop the field entirely once nothing references it) is AD-686c. v1 stays narrow on the call surface.

---

## Phantom-API Pre-Check

Run from prompt body (Wave 27+ pattern). Expected results: only intro-not-yet-in-index FPs.

- `OracleService.write_semantic` — introduced in Section 0. **Standard intro-FP.**
- `runtime.oracle.write_semantic` — public alias (`runtime.oracle`, AD-686, line 1344) reaching new method. Pre-check cannot trace through public-attr aliases (Wave 36/38/41/42 documented FP class). **Standard skip.**
- `oracle.write_semantic` (in `self_mod_manager.py` and `routers/chat.py`) — same intro-FP.
- `getattr(rt, "oracle", None) or getattr(rt, "_oracle_service", None)` — explicit getattr fallback, no class resolution required.
- `layer.index_agent` / `layer.index_skill` / `layer.index_workflow` / `layer.index_qa_report` / `layer.index_event` — all live at HEAD per verify-first grep above. **Not phantoms.**
- `MagicMock` / `AsyncMock` / `pytest.LogCaptureFixture` — stdlib / pytest. **Not phantoms.**

**0 NEW phantoms expected.** Same FP class as Waves 27–49.

---

## Tracking

- **PROGRESS.md** — prepend AD-686b CLOSED entry above the existing AD-647c entry. Use anchor on the leading sentence of the AD-647c paragraph. Long single-line format consistent with prior entries.
- **docs/development/roadmap.md** — flip AD-686b from `Scoped` to `Complete` (or add the row if absent).
- **DECISIONS.md** — prepend AD-686b entry above `### AD-686` (or above the latest Era V header anchor in the same pattern as Wave 49).

---

## Acceptance Criteria

1. `OracleService.write_semantic(kind, /, **fields) -> bool` exists, async, dispatch-by-kind across the 5 SemanticKnowledgeLayer write methods, tier-2 log-and-degrade.
2. All 5 external `_semantic_layer.index_*(...)` write call sites (runtime.py:2508/3309/3358, self_mod_manager.py:142, routers/chat.py:419) route through `runtime.oracle.write_semantic(...)`.
3. SemanticKnowledgeLayer write methods (`index_agent`/`index_skill`/`index_workflow`/`index_qa_report`/`index_event`) are unchanged in shape and remain async-callable. `reindex_from_store` continues to work without modification.
4. `runtime._semantic_layer` attribute is preserved (DLog #3 documents why) — read-path fallback in `introspect.py` and stats-panel call in `runtime.py:2974` continue to work.
5. 12 new tests pass at `tests/test_ad686b_oracle_write_semantic.py`. AD-686 v1 read-path tests at `tests/test_ad686_oracle_semantic_tier.py` continue to pass without modification.
6. Full gate test count: 11158 (Wave 49 baseline) + 12 = 11170. Acceptable range 11168–11171 (xdist flake variance).
7. Phantom-API pre-check: 0 NEW phantoms. Only intro-not-in-index FPs documented in this prompt.
8. Pre-commit deletion sanity: any single file ≤ 200 deletions. Expected actual delta: ~25 ins / ~50 del across `oracle_service.py` + `runtime.py` + `self_mod_manager.py` + `routers/chat.py`, plus ~250 ins / 0 del for the new test file.
9. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase

```
HEAD: d0f2eab93012800c2f212bfb03e9304615077cfa  (post Wave 49)

grep -n "attach_semantic_layer\|_query_semantic\|active_tiers\|attach_health_provider\|_health_provider = health_provider" src/probos/cognitive/oracle_service.py
  131:        semantic_layer: Any = None,  # AD-686 (Tier 5)
  142:        self._semantic_layer = semantic_layer
  146:    def attach_semantic_layer(self, semantic_layer: Any) -> None:
  153:        self._semantic_layer = semantic_layer
  166:    def attach_health_provider(self, health_provider: Any) -> None:
  175:        self._health_provider = health_provider
  201:        active_tiers = tiers or [
  260:        if "semantic" in active_tiers:
  262:            tier_results = await self._query_semantic(query_text, k=k_per_tier)
  470:    async def _query_semantic(

grep -n "^\s*async def index_" src/probos/knowledge/semantic.py
  123: async def index_agent(...)
  152: async def index_skill(...)
  176: async def index_workflow(...)
  201: async def index_qa_report(...)
  226: async def index_event(...)

grep -n "_semantic_layer\.index_" src/probos/runtime.py src/probos/self_mod_manager.py src/probos/routers/chat.py
  src/probos/runtime.py:2508:        await self._semantic_layer.index_agent(
  src/probos/runtime.py:3309:        await self._semantic_layer.index_skill(
  src/probos/runtime.py:3358:        await self._semantic_layer.index_qa_report(
  src/probos/self_mod_manager.py:142: await self._semantic_layer.index_agent(
  src/probos/routers/chat.py:419:    await rt._semantic_layer.index_agent(

grep -n "self\.oracle\b\|self\._oracle_service" src/probos/runtime.py
  1343:        self._oracle_service = cog.oracle_service       # legacy private alias
  1344:        self.oracle = cog.oracle_service                # AD-686 public alias

grep -n "self\._runtime" src/probos/self_mod_manager.py
  83:        self._runtime = runtime
  335:        runtime=self._runtime
```

Every concrete claim in this prompt maps to a grep hit above.
