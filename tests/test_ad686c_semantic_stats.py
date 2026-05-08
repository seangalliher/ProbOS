"""AD-686c: tests for OracleService.semantic_stats()."""
from __future__ import annotations

from typing import Any


def _oracle():
    from probos.cognitive.oracle_service import OracleService
    # Construct via __new__ to avoid heavy ctor wiring; only the attach + stats
    # surfaces are under test.
    o = OracleService.__new__(OracleService)
    o._semantic_layer = None  # type: ignore[attr-defined]
    return o


def test_semantic_stats_returns_disabled_when_no_layer() -> None:
    o = _oracle()
    assert o.semantic_stats() == {"enabled": False}


def test_semantic_stats_returns_layer_payload() -> None:
    class _Layer:
        def stats(self) -> dict[str, Any]:
            return {"enabled": True, "agents": 12, "skills": 5}
    o = _oracle()
    o.attach_semantic_layer(_Layer())
    out = o.semantic_stats()
    assert out["enabled"] is True
    assert out["agents"] == 12
    assert out["skills"] == 5


def test_semantic_stats_handles_layer_exception_gracefully() -> None:
    class _BadLayer:
        def stats(self):
            raise RuntimeError("layer down")
    o = _oracle()
    o.attach_semantic_layer(_BadLayer())
    out = o.semantic_stats()
    assert out == {"enabled": True, "error": "stats_unavailable"}


def test_semantic_stats_normalizes_non_dict_payload() -> None:
    class _Weird:
        def stats(self):
            return "not a dict"
    o = _oracle()
    o.attach_semantic_layer(_Weird())
    assert o.semantic_stats() == {"enabled": True}
