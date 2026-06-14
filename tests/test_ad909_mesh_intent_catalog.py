"""AD-909: universal mesh read-intents in the persistent tool catalog.

The three mesh reads (web_search / read_page / http_fetch) must be registered
into the PERSISTENT ToolRegistry at startup so they appear in GET /api/tools and
the AD-885 lens, and so a Captain ``is_restriction`` can turn one off per-agent.

BF-287: real ToolRegistry + real ToolPermissionStore + real IntentBus at the
substrate boundary — no MagicMock (a phantom ``.get``/``.resolve_permission``
would pass against a mock but fail in production).
"""
from __future__ import annotations

import pytest

from probos.cognitive.agentic_dispatch import (
    _MESH_TOOL_SPECS,
    register_mesh_intent_tools,
)
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.startup.finalize import _wire_mesh_intent_tools
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission
from probos.tools.registry import ToolRegistry

_MESH_IDS = ["web_search", "read_page", "http_fetch"]


def _bus() -> IntentBus:
    return IntentBus(SignalManager(reap_interval=1.0))


class _Runtime:
    """Minimal real runtime holder (BF-287: not a MagicMock)."""

    def __init__(self, tool_registry=None, intent_bus=None) -> None:
        self.tool_registry = tool_registry
        self.intent_bus = intent_bus


# ---------------------------------------------------------------------------
# catalog presence
# ---------------------------------------------------------------------------


def test_mesh_specs_are_the_three_universal_reads():
    ids = [spec[0] for spec in _MESH_TOOL_SPECS]
    assert set(_MESH_IDS).issubset(set(ids))


def test_register_seeds_catalog_with_mesh_provider():
    reg = ToolRegistry()
    ids = register_mesh_intent_tools(reg, _bus(), provider="mesh")
    for tid in _MESH_IDS:
        assert tid in ids
        r = reg.get(tid)
        assert r is not None, f"{tid} absent from catalog"
        assert r.provider == "mesh"
        assert "mesh" in r.tags
        assert tid in r.tags


def test_default_provider_preserves_dispatch_tag():
    # The per-dispatch caller (AD-856) keeps provider="AD-856".
    reg = ToolRegistry()
    register_mesh_intent_tools(reg, _bus())
    assert reg.get("web_search").provider == "AD-856"


def test_mesh_tools_appear_in_list_tools():
    reg = ToolRegistry()
    register_mesh_intent_tools(reg, _bus(), provider="mesh")
    listed = {r.tool_id for r in reg.list_tools()}
    assert set(_MESH_IDS).issubset(listed)


# ---------------------------------------------------------------------------
# idempotency
# ---------------------------------------------------------------------------


def test_register_is_idempotent():
    reg = ToolRegistry()
    register_mesh_intent_tools(reg, _bus(), provider="mesh")
    n1 = reg.count()
    register_mesh_intent_tools(reg, _bus(), provider="mesh")
    assert reg.count() == n1  # no duplicates


def test_first_registration_wins_provider():
    # Startup runs first (provider="mesh"); a later dispatch call (default
    # "AD-856") must NOT overwrite the existing catalog entry.
    reg = ToolRegistry()
    register_mesh_intent_tools(reg, _bus(), provider="mesh")
    register_mesh_intent_tools(reg, _bus())  # dispatch path, default provider
    assert reg.get("web_search").provider == "mesh"


# ---------------------------------------------------------------------------
# READ-for-all default + is_restriction off-switch (acceptance #2)
# ---------------------------------------------------------------------------


def test_read_for_all_default_without_store():
    reg = ToolRegistry()
    register_mesh_intent_tools(reg, _bus(), provider="mesh")
    # Empty default_permissions -> ship-wide READ for any rank.
    assert reg.resolve_permission("ensign-7", "web_search", agent_rank="ensign") == ToolPermission.READ


@pytest.mark.asyncio
async def test_restriction_denies_one_agent_others_unaffected(tmp_path):
    reg = ToolRegistry()
    register_mesh_intent_tools(reg, _bus(), provider="mesh")
    store = ToolPermissionStore(db_path=str(tmp_path / "perms.db"))
    await store.start()
    try:
        reg.set_permission_store(store)
        # Captain restricts web_search for agent A (off-switch = NONE).
        await store.issue_grant(
            "agent-a", "web_search", ToolPermission.NONE, is_restriction=True,
            reason="captain off-switch",
        )
        # A is denied; B (no restriction) still has the READ-for-all default.
        assert reg.resolve_permission("agent-a", "web_search", agent_rank="ensign") == ToolPermission.NONE
        assert reg.resolve_permission("agent-b", "web_search", agent_rank="ensign") == ToolPermission.READ
        # The restriction is scoped to web_search only.
        assert reg.resolve_permission("agent-a", "read_page", agent_rank="ensign") == ToolPermission.READ
    finally:
        await store.stop()


# ---------------------------------------------------------------------------
# startup helper (_wire_mesh_intent_tools)
# ---------------------------------------------------------------------------


def test_wire_helper_seeds_with_mesh_provider():
    reg = ToolRegistry()
    rt = _Runtime(tool_registry=reg, intent_bus=_bus())
    ids = _wire_mesh_intent_tools(runtime=rt)
    assert set(_MESH_IDS).issubset(set(ids))
    assert reg.get("http_fetch").provider == "mesh"


def test_wire_helper_honest_degrade_no_registry():
    rt = _Runtime(tool_registry=None, intent_bus=_bus())
    assert _wire_mesh_intent_tools(runtime=rt) == []


def test_wire_helper_honest_degrade_no_intent_bus():
    rt = _Runtime(tool_registry=ToolRegistry(), intent_bus=None)
    assert _wire_mesh_intent_tools(runtime=rt) == []
