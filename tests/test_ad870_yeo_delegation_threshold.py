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


def test_threshold_teaches_all_four_tiers_when_fully_wired() -> None:
    async def _run() -> None:
        reg = await _registry_with_pools(
            "directory", "filesystem", "search", "web_search", "page_reader",
        )
        runtime = SimpleNamespace(work_item_store=object(), registry=reg)
        block = _make_yeo(runtime=runtime)._conversational_task_protocol(
            {"intent": "direct_message"}
        )
        # Tier 1 (answer), Tier 2 ([MESH]), Tier 3 ([CREATE_TASK]) all taught.
        assert "just reply" in block
        assert "[MESH list_directory path=<dir>]" in block
        assert "[MESH web_search query=<terms>]" in block
        assert "[MESH read_page url=<url>]" in block
        assert "[CREATE_TASK" in block
        assert "Rule of thumb" in block

    asyncio.run(_run())


def test_mesh_guidance_lists_only_live_read_pools() -> None:
    async def _run() -> None:
        # Only directory + filesystem pools live -> web/page intents absent.
        reg = await _registry_with_pools("directory", "filesystem")
        runtime = SimpleNamespace(work_item_store=object(), registry=reg)
        block = _make_yeo(runtime=runtime)._conversational_task_protocol(
            {"intent": "direct_message"}
        )
        assert "[MESH list_directory path=<dir>]" in block
        assert "[MESH read_file path=<file>]" in block
        assert "web_search" not in block
        assert "read_page" not in block

    asyncio.run(_run())


def test_threshold_honest_degrades_with_no_seams() -> None:
    async def _run() -> None:
        # No store and an empty registry -> no seam to teach -> "".
        reg = await _registry_with_pools()
        runtime = SimpleNamespace(work_item_store=None, registry=reg)
        block = _make_yeo(runtime=runtime)._conversational_task_protocol(
            {"intent": "direct_message"}
        )
        assert block == ""

    asyncio.run(_run())


def test_threshold_teaches_mesh_only_when_store_absent() -> None:
    async def _run() -> None:
        reg = await _registry_with_pools("directory")
        runtime = SimpleNamespace(work_item_store=None, registry=reg)
        block = _make_yeo(runtime=runtime)._conversational_task_protocol(
            {"intent": "direct_message"}
        )
        assert "[MESH list_directory path=<dir>]" in block
        assert "[CREATE_TASK" not in block

    asyncio.run(_run())


def test_threshold_teaches_create_task_only_when_no_read_pools() -> None:
    async def _run() -> None:
        # Store wired but registry empty -> CREATE_TASK taught, no [MESH].
        reg = await _registry_with_pools()
        runtime = SimpleNamespace(work_item_store=object(), registry=reg)
        block = _make_yeo(runtime=runtime)._conversational_task_protocol(
            {"intent": "direct_message"}
        )
        assert "[CREATE_TASK" in block
        assert "[MESH" not in block

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


def test_registry_get_by_pool_raises_degrades_to_create_task() -> None:
    class _BoomRegistry:
        def get_by_pool(self, pool: str):  # noqa: ANN001, D401
            raise RuntimeError("registry boom")

    runtime = SimpleNamespace(work_item_store=object(), registry=_BoomRegistry())
    block = _make_yeo(runtime=runtime)._conversational_task_protocol(
        {"intent": "direct_message"}
    )
    # MESH guidance is skipped (read-intent build degraded) but CREATE_TASK
    # still taught; never raises.
    assert "[MESH" not in block
    assert "[CREATE_TASK" in block


def test_base_hook_unaffected() -> None:
    base = object.__new__(CognitiveAgent)
    assert base._conversational_task_protocol({"intent": "direct_message"}) == ""
