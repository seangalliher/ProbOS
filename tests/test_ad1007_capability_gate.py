"""AD-1007: per-agent mesh-capability gate — enforcement + agent-precedence.

The Captain's rule (2026-06-14): disabling a capability BLOCKS the agent, and an
explicit per-agent decision WINS over the role/ship default in both directions
(agent-disable beats role-enable; agent-grant beats role-disable).

This exercises the three-state resolver, the ``capabilities/set`` capability
branch, the ``get_agent_capabilities`` surface, and the two enforcement points
(conversational ``[MESH]`` at ``step_4h`` + the agentic-loop mesh-tool filter).

BF-287: real ``IntentGrantStore`` (cache-only) + real ``DmSanityGate`` /
``ToolRegistry`` / ``IntentBus`` + real route handlers — no MagicMock at the
substrate boundary.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from probos.api_models import SetCapability
from probos.cognitive.intent_grants import IntentAccessGrant, IntentGrantStore
from probos.routers.agents import get_agent_capabilities, set_agent_capability
from probos.cognitive.dm.reply_value import DmReply  # AD-1248


# ---------------------------------------------------------------------------
# helpers (BF-287 — real registry/agents, no mocks)
# ---------------------------------------------------------------------------


def _intent(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name, description=f"{name} desc", usage_hint="",
        requires_consensus=False, tier="domain",
    )


class _Registry:
    def __init__(self, agents: list[SimpleNamespace]) -> None:
        self._agents = {a.id: a for a in agents}

    def get(self, agent_id: str):
        return self._agents.get(agent_id)

    def all(self):
        return list(self._agents.values())


async def _runtime_with_store(agents, store) -> SimpleNamespace:
    return SimpleNamespace(
        registry=_Registry(agents),
        intent_grant_store=store,
        emit_event=lambda *a, **k: None,
    )


def _ezri_serving(*intent_names: str) -> SimpleNamespace:
    return SimpleNamespace(id="ezri", intent_descriptors=[_intent(n) for n in intent_names])


# ---------------------------------------------------------------------------
# resolve_sync — three-state agent-precedence
# ---------------------------------------------------------------------------


async def test_resolve_no_opinion_when_no_decision():
    store = IntentGrantStore(db_path="")
    await store.start()
    assert store.resolve_sync("ezri", "web_search") == "no_opinion"
    await store.stop()


async def test_resolve_granted_and_restricted():
    store = IntentGrantStore(db_path="")
    await store.start()
    await store.issue_grant("ezri", "web_search")
    assert store.resolve_sync("ezri", "web_search") == "granted"
    store2 = IntentGrantStore(db_path="")
    await store2.start()
    await store2.issue_grant("ezri", "web_search", is_restriction=True)
    assert store2.resolve_sync("ezri", "web_search") == "restricted"
    await store.stop()
    await store2.stop()


async def test_resolve_most_recent_wins():
    # Defensive conflict path: when both a grant and a restriction are active,
    # the most-recent decision wins (the endpoint revokes the opposite first, so
    # this only matters if both somehow coexist). Controlled issued_at.
    store = IntentGrantStore(db_path="")
    await store.start()
    store._cache.append(IntentAccessGrant(
        id="g1", agent_id="ezri", intent_name="web_search", is_restriction=False, issued_at=100.0))
    store._cache.append(IntentAccessGrant(
        id="r1", agent_id="ezri", intent_name="web_search", is_restriction=True, issued_at=200.0))
    assert store.resolve_sync("ezri", "web_search") == "restricted"  # later restriction wins
    # Reverse recency: later grant wins.
    store2 = IntentGrantStore(db_path="")
    await store2.start()
    store2._cache.append(IntentAccessGrant(
        id="r2", agent_id="ezri", intent_name="web_search", is_restriction=True, issued_at=100.0))
    store2._cache.append(IntentAccessGrant(
        id="g2", agent_id="ezri", intent_name="web_search", is_restriction=False, issued_at=200.0))
    assert store2.resolve_sync("ezri", "web_search") == "granted"
    await store.stop()
    await store2.stop()


async def test_resolve_tie_is_failsafe_restricted():
    store = IntentGrantStore(db_path="")
    await store.start()
    store._cache.append(IntentAccessGrant(
        id="g", agent_id="ezri", intent_name="web_search", is_restriction=False, issued_at=100.0))
    store._cache.append(IntentAccessGrant(
        id="r", agent_id="ezri", intent_name="web_search", is_restriction=True, issued_at=100.0))
    assert store.resolve_sync("ezri", "web_search") == "restricted"
    await store.stop()


async def test_resolve_is_per_agent_and_intent():
    store = IntentGrantStore(db_path="")
    await store.start()
    await store.issue_grant("ezri", "web_search", is_restriction=True)
    assert store.resolve_sync("ezri", "web_search") == "restricted"
    assert store.resolve_sync("yeo", "web_search") == "no_opinion"
    assert store.resolve_sync("ezri", "read_page") == "no_opinion"
    await store.stop()


# ---------------------------------------------------------------------------
# capabilities/set — capability branch
# ---------------------------------------------------------------------------


async def test_set_capability_disable_issues_restriction():
    store = IntentGrantStore(db_path="")
    await store.start()
    rt = await _runtime_with_store([_ezri_serving("web_search")], store)
    req = SetCapability(kind="capability", id="web_search", enabled=False, reason="paused")
    out = await set_agent_capability("ezri", req, rt)
    assert out["enabled"] is False
    assert store.resolve_sync("ezri", "web_search") == "restricted"
    await store.stop()


async def test_set_capability_enable_issues_grant():
    store = IntentGrantStore(db_path="")
    await store.start()
    rt = await _runtime_with_store([_ezri_serving("web_search")], store)
    await set_agent_capability("ezri", SetCapability(kind="capability", id="web_search", enabled=True), rt)
    assert store.resolve_sync("ezri", "web_search") == "granted"
    await store.stop()


async def test_set_capability_revokes_opposite_first():
    # disable, then enable -> only ONE active decision remains (the grant), so
    # resolution is unambiguous (agent-precedence, latest decision).
    store = IntentGrantStore(db_path="")
    await store.start()
    rt = await _runtime_with_store([_ezri_serving("web_search")], store)
    await set_agent_capability("ezri", SetCapability(kind="capability", id="web_search", enabled=False), rt)
    await set_agent_capability("ezri", SetCapability(kind="capability", id="web_search", enabled=True), rt)
    active = store.get_active_grants_sync("ezri", "web_search")
    assert len(active) == 1
    assert active[0].is_restriction is False
    assert store.resolve_sync("ezri", "web_search") == "granted"
    await store.stop()


async def test_set_capability_unknown_capability_404():
    store = IntentGrantStore(db_path="")
    await store.start()
    rt = await _runtime_with_store([_ezri_serving("web_search")], store)
    with pytest.raises(HTTPException) as exc:
        await set_agent_capability("ezri", SetCapability(kind="capability", id="not_a_real_intent", enabled=False), rt)
    assert exc.value.status_code == 404
    await store.stop()


async def test_set_capability_store_unavailable_503():
    rt = SimpleNamespace(
        registry=_Registry([_ezri_serving("web_search")]),
        intent_grant_store=None,
        emit_event=lambda *a, **k: None,
    )
    with pytest.raises(HTTPException) as exc:
        await set_agent_capability("ezri", SetCapability(kind="capability", id="web_search", enabled=False), rt)
    assert exc.value.status_code == 503


async def test_set_capability_unknown_agent_404():
    store = IntentGrantStore(db_path="")
    await store.start()
    rt = await _runtime_with_store([_ezri_serving("web_search")], store)
    with pytest.raises(HTTPException) as exc:
        await set_agent_capability("ghost", SetCapability(kind="capability", id="web_search", enabled=False), rt)
    assert exc.value.status_code == 404
    await store.stop()


# ---------------------------------------------------------------------------
# get_agent_capabilities — surfaces the per-agent enablement state
# ---------------------------------------------------------------------------


async def test_get_capabilities_surfaces_restriction_state():
    store = IntentGrantStore(db_path="")
    await store.start()
    await store.issue_grant("ezri", "web_search", is_restriction=True)
    rt = await _runtime_with_store([_ezri_serving("web_search", "read_page")], store)
    body = await get_agent_capabilities("ezri", rt)
    mesh = {mi["id"]: mi for mi in body["mesh_intents"]}
    assert mesh["web_search"]["granted"] is False
    assert mesh["web_search"]["source"] == "restriction"
    # an untouched capability reads as role-default enabled
    assert mesh["read_page"]["granted"] is True
    assert mesh["read_page"]["source"] == "role_default"
    await store.stop()


# ---------------------------------------------------------------------------
# enforcement — conversational [MESH] gate (step_4h)
# ---------------------------------------------------------------------------


def _dm_ctx(*, runtime, response_text):
    from probos.cognitive.dm import DmReplyContext
    from probos.cognitive.dm_sanity_gate import DmSanityGate
    return DmReplyContext(
        runtime=runtime, agent=SimpleNamespace(agent_id="ezri"), agent_id="ezri",
        callsign="ezri", req_message="hi", reply=DmReply(body=response_text),
        has_image_attachment=False, per_attachment=[], sanity_gate=DmSanityGate(),
        params={}, message_text="hi", sampling_state=None, avatar_event_bus=None,
    )


class _RecordingBus:
    def __init__(self) -> None:
        self.sent = []

    async def send(self, intent):
        self.sent.append(intent)
        return SimpleNamespace(result="ok")


async def test_step4h_blocks_restricted_capability():
    from probos.cognitive.dm import DmReplyPipeline
    store = IntentGrantStore(db_path="")
    await store.start()
    await store.issue_grant("ezri", "web_search", is_restriction=True)
    bus = _RecordingBus()
    rt = SimpleNamespace(intent_grant_store=store, intent_bus=bus)
    ctx = _dm_ctx(runtime=rt, response_text="On it. [MESH web_search query=warp theory]")
    await DmReplyPipeline(ctx).step_4h_mesh_read_parse()
    assert "[MESH" not in ctx.response_text  # tag stripped
    assert "not authorized to use web_search" in ctx.response_text
    assert bus.sent == []  # never dispatched
    await store.stop()


async def test_step4h_allows_unrestricted_capability():
    # No restriction -> the AD-1007 gate does NOT fire. With intent_bus=None the
    # step degrades on the AD-869 path (proving it passed the capability gate).
    from probos.cognitive.dm import DmReplyPipeline
    store = IntentGrantStore(db_path="")
    await store.start()
    rt = SimpleNamespace(intent_grant_store=store, intent_bus=None)
    ctx = _dm_ctx(runtime=rt, response_text="On it. [MESH web_search query=warp theory]")
    await DmReplyPipeline(ctx).step_4h_mesh_read_parse()
    assert "not authorized" not in ctx.response_text  # gate did not block
    await store.stop()


# ---------------------------------------------------------------------------
# enforcement — agentic-loop mesh-tool filter
# ---------------------------------------------------------------------------


async def test_agentic_loop_filters_restricted_mesh_tool(monkeypatch):
    from probos.cognitive.agentic_dispatch import (
        WorkItemAgenticExecutor,
    )
    from probos.mesh.intent import IntentBus
    from probos.mesh.signal import SignalManager
    from probos.tools.permissions import ToolPermissionStore
    from probos.tools.registry import ToolRegistry

    captured: dict = {}

    class _CaptureLoop:
        # This test asserts on the tool set handed to ``run``; how the loop is
        # CONSTRUCTED is incidental to it. ``WorkItemAgenticExecutor`` passes a
        # growing set of behaviour kwargs (AD-1146 structured_tool_messages,
        # AD-1147 parallel_tool_calls_*, AD-1148 tool_result_*), so accept and
        # ignore them rather than pinning a signature this test does not test.
        def __init__(self, *, llm_client, tool_executor, event_emit_fn, **_loop_kwargs):
            pass

        async def run(self, *, system_prompt, user_message, tools, context):
            captured["tools"] = tools
            return SimpleNamespace(final_text="done", stopped_reason="complete", tool_calls=[])

    monkeypatch.setattr(
        "probos.cognitive.swe_harness.agentic_loop.AgenticLoop", _CaptureLoop,
    )

    store = IntentGrantStore(db_path="")
    await store.start()
    await store.issue_grant("ezri", "web_search", is_restriction=True)
    perm = ToolPermissionStore()
    await perm.start()
    rt = SimpleNamespace(
        tool_registry=ToolRegistry(),
        tool_permission_store=perm,
        intent_bus=IntentBus(SignalManager(reap_interval=1.0)),
        intent_grant_store=store,
        attachment_store=None,
        emit_event=None,
    )
    executor = WorkItemAgenticExecutor(llm_client=object())
    await executor.run(
        agent_id="ezri", instructions="x", task_text="do it", runtime=rt,
        department="counseling", rank="ensign",
    )
    blob = json.dumps(captured["tools"])
    assert "web_search" not in blob   # restricted -> filtered out of the loop
    assert "http_fetch" in blob       # unrestricted mesh tool remains
    await store.stop()
    await perm.stop()
