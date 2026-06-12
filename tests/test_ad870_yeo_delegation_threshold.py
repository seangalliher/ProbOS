"""AD-870: Yeo's four-tier delegation threshold instructions.

AD-869 built the Tier-2 ``[MESH ...]`` seam (synchronous inline read) and
AD-845 built the Tier-3 ``[CREATE_TASK ...]`` seam (async tracked task).
AD-870 teaches Yeo *when* to reach for each — the threshold rule injected
via the ``_conversational_task_protocol`` hook: answer directly (Tier 1),
do a quick read-only lookup inline (Tier 2), or write it down as a task
(Tier 3 / specialist=@ Tier 4).

The ``[MESH]`` guidance is gated on the read pool being live and the
``[CREATE_TASK]`` guidance on a work-item store being wired (honest-degrade:
Yeo is never told to use a seam the substrate cannot back). Real
``AgentRegistry`` fixtures — no MagicMock at the substrate boundary (BF-287).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.yeoman import YeomanAgent, _DEFAULT_PERSONA, _ROLE_RULES
from probos.substrate.registry import AgentRegistry


def _stub_agent(agent_id: str, pool: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=agent_id, agent_type=pool, pool=pool, capabilities=[], is_alive=True,
    )


async def _registry_with_pools(*pools: str) -> AgentRegistry:
    reg = AgentRegistry()
    for i, pool in enumerate(pools):
        await reg.register(_stub_agent(f"{pool}-{i}", pool))
    return reg


def _make_yeo(*, runtime: object) -> YeomanAgent:
    yeo = object.__new__(YeomanAgent)
    yeo.id = "yeoman-001"
    yeo.agent_type = "yeoman"
    yeo.instructions = _DEFAULT_PERSONA + _ROLE_RULES
    yeo._runtime = runtime
    return yeo


def test_threshold_teaches_create_task_when_store_wired() -> None:
    async def _run() -> None:
        reg = await _registry_with_pools(
            "directory", "filesystem", "search", "web_search", "page_reader",
        )
        runtime = SimpleNamespace(work_item_store=object(), registry=reg)
        block = _make_yeo(runtime=runtime)._conversational_task_protocol(
            {"intent": "direct_message"}
        )
        # Tier 1 (answer) + Tier 3 ([CREATE_TASK]) + rule-of-thumb.
        assert "just reply" in block
        assert "[CREATE_TASK" in block
        assert "Rule of thumb" in block
        # AD-983a: the per-intent [MESH ...] tags are NO LONGER enumerated here
        # — they moved to the base capability affordance for ALL crew
        # (see test_ad983a_capability_affordances.py).
        assert "[MESH" not in block

    asyncio.run(_run())


def test_threshold_points_at_the_capability_tags_above() -> None:
    async def _run() -> None:
        reg = await _registry_with_pools("directory")
        runtime = SimpleNamespace(work_item_store=object(), registry=reg)
        block = _make_yeo(runtime=runtime)._conversational_task_protocol(
            {"intent": "direct_message"}
        )
        # The quick-lookup tier points at the ship-capability tags rendered
        # above (by the base affordance), not its own [MESH] enumeration.
        assert "ship-capability tags listed above" in block

    asyncio.run(_run())


def test_threshold_honest_degrades_without_store() -> None:
    async def _run() -> None:
        # No store -> the only seam THIS hook teaches is gone -> "".
        # (The [MESH] affordance is independent, taught by the base hook.)
        reg = await _registry_with_pools("directory", "web_search")
        runtime = SimpleNamespace(work_item_store=None, registry=reg)
        block = _make_yeo(runtime=runtime)._conversational_task_protocol(
            {"intent": "direct_message"}
        )
        assert block == ""

    asyncio.run(_run())


def test_threshold_block_is_gap_regex_safe() -> None:
    async def _run() -> None:
        reg = await _registry_with_pools(
            "directory", "filesystem", "search", "web_search", "page_reader",
        )
        runtime = SimpleNamespace(work_item_store=object(), registry=reg)
        block = _make_yeo(runtime=runtime)._conversational_task_protocol(
            {"intent": "direct_message"}
        )
        assert _CAPABILITY_GAP_RE.search(block) is None

    asyncio.run(_run())


def test_no_runtime_degrades_to_empty() -> None:
    block = _make_yeo(runtime=None)._conversational_task_protocol(
        {"intent": "direct_message"}
    )
    assert block == ""


def test_base_hook_unaffected() -> None:
    base = object.__new__(CognitiveAgent)
    assert base._conversational_task_protocol({"intent": "direct_message"}) == ""

