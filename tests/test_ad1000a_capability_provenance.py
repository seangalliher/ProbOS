"""AD-1000a: capability provenance — tool `origin` + mesh-intent visibility.

The first build slice of the Agent Customizations epic (#944). Adds the
harness-aligned tool source taxonomy (built_in / mcp / extension) and surfaces
mesh intents as the third capability axis on GET /api/agent/{id}/capabilities.

BF-287: real `IntentDescriptor`s + a real registry-like stub (no MagicMock at the
registry boundary — a phantom `.all()` would pass against a mock).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from probos.routers.agents import _mesh_intents, _tool_origin
from probos.types import IntentDescriptor


# ---------------------------------------------------------------------------
# _tool_origin — the built_in / mcp / extension taxonomy
# ---------------------------------------------------------------------------


def test_tool_origin_mcp():
    assert _tool_origin("mcp_server", "") == "mcp"
    assert _tool_origin("mcp_server", "anything") == "mcp"


def test_tool_origin_extension():
    assert _tool_origin("utility_agent", "extension") == "extension"
    assert _tool_origin("deterministic_function", "designed") == "extension"
    assert _tool_origin("infra_service", "self_designed") == "extension"
    assert _tool_origin("utility_agent", "plugin") == "extension"


def test_tool_origin_built_in_default():
    assert _tool_origin("deterministic_function", "") == "built_in"
    assert _tool_origin("infra_service", "ship_computer") == "built_in"
    assert _tool_origin("browser", "ward_room") == "built_in"


# ---------------------------------------------------------------------------
# _mesh_intents — the live reachable mesh-intent set
# ---------------------------------------------------------------------------


class _Registry:
    """Minimal real registry stub: .all() returns the seeded agents."""

    def __init__(self, agents: list[Any]) -> None:
        self._agents = agents

    def all(self) -> list[Any]:
        return list(self._agents)


def _agent(intents: list[IntentDescriptor]) -> SimpleNamespace:
    return SimpleNamespace(intent_descriptors=intents)


def test_mesh_intents_collects_and_sorts():
    reg = _Registry([
        _agent([
            IntentDescriptor(name="run_python", description="Run a script", requires_consensus=True, tier="core"),
        ]),
        _agent([
            IntentDescriptor(name="http_fetch", description="Fetch a URL", usage_hint="[MESH http_fetch url=<u>]", tier="core"),
        ]),
    ])
    runtime = SimpleNamespace(registry=reg)
    out = _mesh_intents(runtime)
    # Sorted by name: http_fetch before run_python.
    assert [d["name"] for d in out] == ["http_fetch", "run_python"]
    rp = next(d for d in out if d["name"] == "run_python")
    assert rp["requires_consensus"] is True
    assert rp["tier"] == "core"
    assert rp["origin"] == "built_in"
    assert rp["reachable"] is True
    hf = next(d for d in out if d["name"] == "http_fetch")
    assert hf["usage_hint"] == "[MESH http_fetch url=<u>]"
    assert hf["requires_consensus"] is False


def test_mesh_intents_dedupes_by_name():
    reg = _Registry([
        _agent([IntentDescriptor(name="run_python", description="A")]),
        _agent([IntentDescriptor(name="run_python", description="B (duplicate pool)")]),
    ])
    out = _mesh_intents(SimpleNamespace(registry=reg))
    assert len(out) == 1
    assert out[0]["name"] == "run_python"


def test_mesh_intents_no_registry_degrades():
    assert _mesh_intents(SimpleNamespace()) == []
    assert _mesh_intents(SimpleNamespace(registry=None)) == []


def test_mesh_intents_raising_registry_degrades():
    class _Boom:
        def all(self) -> list[Any]:
            raise RuntimeError("boom")

    assert _mesh_intents(SimpleNamespace(registry=_Boom())) == []


def test_mesh_intents_agent_without_descriptors_skipped():
    reg = _Registry([SimpleNamespace(), _agent([IntentDescriptor(name="x")])])
    out = _mesh_intents(SimpleNamespace(registry=reg))
    assert [d["name"] for d in out] == ["x"]
