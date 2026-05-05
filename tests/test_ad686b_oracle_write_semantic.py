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
    result = await oracle.write_semantic(
        "agent", agent_type="x", intent_name="y", description="d", strategy="s",
    )
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
    ok = await oracle.write_semantic(
        "skill", intent_name="i", description="d", target_agent="t",
    )
    assert ok is True
    layer.index_skill.assert_awaited_once_with(
        intent_name="i", description="d", target_agent="t",
    )


# 4. workflow kind delegates (no external caller at HEAD; surface still ships).
@pytest.mark.asyncio
async def test_write_semantic_workflow_delegates() -> None:
    layer = MagicMock()
    layer.index_workflow = AsyncMock()
    oracle = _oracle_with_layer(layer)
    ok = await oracle.write_semantic(
        "workflow", pattern="p", intent_names=["a", "b"], hit_count=3,
    )
    assert ok is True
    layer.index_workflow.assert_awaited_once()


# 5. qa_report kind delegates.
@pytest.mark.asyncio
async def test_write_semantic_qa_report_delegates() -> None:
    layer = MagicMock()
    layer.index_qa_report = AsyncMock()
    oracle = _oracle_with_layer(layer)
    ok = await oracle.write_semantic(
        "qa_report", agent_type="ax", verdict="pass", pass_rate=0.9,
    )
    assert ok is True
    layer.index_qa_report.assert_awaited_once()


# 6. event kind delegates (no external caller at HEAD).
@pytest.mark.asyncio
async def test_write_semantic_event_delegates() -> None:
    layer = MagicMock()
    layer.index_event = AsyncMock()
    oracle = _oracle_with_layer(layer)
    ok = await oracle.write_semantic(
        "event", category="c", event="e", detail="d",
    )
    assert ok is True
    layer.index_event.assert_awaited_once()


# 7. None layer returns False + logs at debug + does NOT raise.
@pytest.mark.asyncio
async def test_write_semantic_none_layer_returns_false(
    caplog: pytest.LogCaptureFixture,
) -> None:
    oracle = OracleService(semantic_layer=None)
    with caplog.at_level(logging.DEBUG, logger="probos.cognitive.oracle_service"):
        ok = await oracle.write_semantic(
            "agent", agent_type="x", intent_name="y",
            description="d", strategy="s",
        )
    assert ok is False
    assert any("no semantic layer attached" in r.message for r in caplog.records)


# 8. Unknown kind returns False + warning + does NOT call layer.
@pytest.mark.asyncio
async def test_write_semantic_unknown_kind_returns_false(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # spec=[] so MagicMock auto-attributes don't satisfy getattr lookup.
    layer = MagicMock(spec=[])
    oracle = _oracle_with_layer(layer)
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.oracle_service"):
        ok = await oracle.write_semantic("nonexistent", foo=1)
    assert ok is False
    assert any("unknown kind" in r.message for r in caplog.records)


# 9. Delegation exception → False + warning, never propagates.
@pytest.mark.asyncio
async def test_write_semantic_delegation_exception_caught(
    caplog: pytest.LogCaptureFixture,
) -> None:
    layer = MagicMock()
    layer.index_agent = AsyncMock(side_effect=RuntimeError("layer is on fire"))
    oracle = _oracle_with_layer(layer)
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.oracle_service"):
        ok = await oracle.write_semantic(
            "agent", agent_type="x", intent_name="y",
            description="d", strategy="s",
        )
    assert ok is False
    assert any("delegation failed" in r.message for r in caplog.records)


# 10. Late-bind via attach_semantic_layer.
@pytest.mark.asyncio
async def test_write_semantic_late_bind_via_attach() -> None:
    oracle = OracleService(semantic_layer=None)
    ok_before = await oracle.write_semantic(
        "agent", agent_type="x", intent_name="y", description="d", strategy="s",
    )
    assert ok_before is False
    layer = MagicMock()
    layer.index_agent = AsyncMock()
    oracle.attach_semantic_layer(layer)
    ok_after = await oracle.write_semantic(
        "agent", agent_type="x", intent_name="y", description="d", strategy="s",
    )
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


# 12. Migration smoke — each migrated source file uses oracle.write_semantic.
def test_migrated_sites_use_oracle_write_semantic() -> None:
    """Static smoke: every migrated source file references
    `oracle.write_semantic(` and no longer calls
    `_semantic_layer.index_*` directly outside the legacy ctor field gate.
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
        assert "oracle.write_semantic(" in text, (
            f"AD-686b regression: {path.name} no longer routes through Oracle"
        )
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
