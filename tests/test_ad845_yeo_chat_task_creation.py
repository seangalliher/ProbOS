"""AD-845: Yeo creates a dispatchable task from a 1:1 chat reply.

Yeo's conversational path (``is_conversation``) is pure text generation — it
never reaches the decomposer, so a new ``create_task`` intent descriptor
would never fire in chat. AD-845 teaches Yeo (via the overridable
``CognitiveAgent._conversational_task_protocol`` hook) to emit a
``[CREATE_TASK title=... | instructions=... | specialist=@callsign]`` reply
tag, and adds ``DmReplyPipeline.step_4g_create_task_parse`` which parses the
tag, resolves the specialist callsign to a live agent UUID, creates a
``dispatchable=True`` work item tagged ``yeo-delegated`` (so the AD-834/AD-839
``WorkItemRouter`` runs it automatically), and strips the tag from the
Captain-visible reply.

These tests use a REAL ``WorkItemStore`` (in-memory SQLite), a REAL
``AgentRegistry`` + ``CallsignRegistry``, and a REAL ``DmSanityGate`` — no
``MagicMock`` at the substrate boundary (Phantom-via-MagicMock trap, repo
conventions).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.cognitive.yeoman import (
    YeomanAgent,
    _DEFAULT_PERSONA,
    _ROLE_RULES,
)
from probos.crew_profile import CallsignRegistry
from probos.substrate.registry import AgentRegistry
from probos.workforce import WorkItemStore
from probos.cognitive.dm.reply_value import DmReply  # AD-1248


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------


def _stub_agent(agent_id: str, agent_type: str) -> SimpleNamespace:
    """Minimal BaseAgent stand-in for registry.register / get_by_pool.

    ``CallsignRegistry.resolve`` reads ``is_alive`` + ``id``; ``get_by_pool``
    filters on ``pool``.
    """
    return SimpleNamespace(
        id=agent_id,
        agent_type=agent_type,
        pool=agent_type,
        capabilities=[],
        is_alive=True,
    )


async def _build_callsign_registry(*pairs: tuple[str, str]) -> CallsignRegistry:
    """Build a CallsignRegistry mapping callsign->agent_type with a live
    AgentRegistry behind it. ``pairs`` are (callsign, agent_type)."""
    agent_registry = AgentRegistry()
    cr = CallsignRegistry()
    for idx, (callsign, agent_type) in enumerate(pairs):
        await agent_registry.register(_stub_agent(f"{agent_type}-{idx}", agent_type))
        cr._callsign_to_type[callsign.lower()] = agent_type
        cr._type_to_callsign[agent_type] = callsign
        cr._type_to_profile[agent_type] = {
            "display_name": callsign,
            "department": agent_type,
            "vision_capable": False,
        }
    cr.bind_registry(agent_registry)
    return cr


async def _make_store() -> WorkItemStore:
    store = WorkItemStore(db_path=":memory:")
    await store.start()
    return store


def _make_pipeline(
    *,
    runtime: SimpleNamespace,
    response_text: str,
    sanity_gate: DmSanityGate | None,
) -> DmReplyPipeline:
    ctx = DmReplyContext(
        runtime=runtime,
        agent=SimpleNamespace(id="yeoman-001", agent_type="yeoman"),
        agent_id="yeoman-001",
        callsign="Yeo",
        req_message="Go research the new Nvidia SPARK devices.",
        reply=DmReply(body=response_text),
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=sanity_gate,
        params={},
        message_text="Go research the new Nvidia SPARK devices.",
        sampling_state=None,
        avatar_event_bus=None,
    )
    return DmReplyPipeline(ctx)


_TAG = (
    "On it, Captain. [CREATE_TASK title=Nvidia SPARK analysis | "
    "instructions=Research the new Nvidia SPARK RTX devices and summarize | "
    "specialist=@Number One] I'll report back when it's done."
)


# ---------------------------------------------------------------------------
# (a) tag in reply -> dispatchable work item created, specialist resolved
# ---------------------------------------------------------------------------


def test_create_task_tag_creates_dispatchable_work_item() -> None:
    async def _run() -> None:
        store = await _make_store()
        cr = await _build_callsign_registry(("Number One", "number_one"))
        runtime = SimpleNamespace(work_item_store=store, callsign_registry=cr)
        try:
            pipeline = _make_pipeline(
                runtime=runtime, response_text=_TAG, sanity_gate=DmSanityGate(),
            )
            await pipeline.step_4g_create_task_parse()

            items = await store.list_work_items()
            assert len(items) == 1
            item = items[0]
            assert item.title == "Nvidia SPARK analysis"
            assert "Nvidia SPARK" in item.description
            assert item.metadata.get("dispatchable") is True
            assert "yeo-delegated" in item.tags
            assert item.work_type == "task"
            assert item.created_by == "captain"
            # Specialist @Number One resolved to the live number_one agent.
            assert item.assigned_to == "number_one-0"
        finally:
            await store.stop()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# (b) tag stripped from Captain-visible text
# ---------------------------------------------------------------------------


def test_create_task_tag_stripped_from_reply() -> None:
    async def _run() -> None:
        store = await _make_store()
        cr = await _build_callsign_registry(("Number One", "number_one"))
        runtime = SimpleNamespace(work_item_store=store, callsign_registry=cr)
        try:
            pipeline = _make_pipeline(
                runtime=runtime, response_text=_TAG, sanity_gate=DmSanityGate(),
            )
            await pipeline.step_4g_create_task_parse()

            text = pipeline.ctx.response_text
            assert "[CREATE_TASK" not in text
            assert "On it, Captain." in text
            assert "report back" in text
            # The created task id is surfaced to the Captain.
            assert "Task opened:" in text
        finally:
            await store.stop()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# (c) no-tag reply -> no work item, text unchanged
# ---------------------------------------------------------------------------


def test_no_tag_no_work_item_created() -> None:
    async def _run() -> None:
        store = await _make_store()
        runtime = SimpleNamespace(work_item_store=store, callsign_registry=None)
        try:
            plain = "Sure Captain, the bridge is quiet this morning."
            pipeline = _make_pipeline(
                runtime=runtime, response_text=plain, sanity_gate=DmSanityGate(),
            )
            await pipeline.step_4g_create_task_parse()

            assert pipeline.ctx.response_text == plain
            assert await store.list_work_items() == []
        finally:
            await store.stop()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# (d) work_item_store None -> honest-degrade, reply intact, no exception
# ---------------------------------------------------------------------------


def test_work_item_store_none_honest_degrade() -> None:
    async def _run() -> None:
        runtime = SimpleNamespace(work_item_store=None, callsign_registry=None)
        pipeline = _make_pipeline(
            runtime=runtime, response_text=_TAG, sanity_gate=DmSanityGate(),
        )
        # Must not raise.
        await pipeline.step_4g_create_task_parse()
        text = pipeline.ctx.response_text
        # Tag stripped (never leaks) but the conversational reply survives.
        assert "[CREATE_TASK" not in text
        assert "On it, Captain." in text
        assert "Task opened:" not in text

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# (e) unresolved specialist -> keyword-map fallback, item still created
# ---------------------------------------------------------------------------


def test_unresolved_specialist_falls_back_to_keyword_map() -> None:
    async def _run() -> None:
        store = await _make_store()
        # Callsign registry knows Number One (science) but NOT "Bogus".
        cr = await _build_callsign_registry(("Number One", "number_one"))
        runtime = SimpleNamespace(work_item_store=store, callsign_registry=cr)
        try:
            reply = (
                "[CREATE_TASK title=Sensor sweep | "
                "instructions=Research and analyze the anomaly readings | "
                "specialist=@Bogus] Opening it now."
            )
            pipeline = _make_pipeline(
                runtime=runtime, response_text=reply, sanity_gate=DmSanityGate(),
            )
            await pipeline.step_4g_create_task_parse()

            items = await store.list_work_items()
            assert len(items) == 1
            # "research/analyze" keyword-maps to science -> Number One ->
            # the live number_one agent.
            assert items[0].assigned_to == "number_one-0"
        finally:
            await store.stop()

    asyncio.run(_run())


def test_unresolved_specialist_and_no_keyword_match_creates_unassigned() -> None:
    async def _run() -> None:
        store = await _make_store()
        cr = await _build_callsign_registry(("Number One", "number_one"))
        runtime = SimpleNamespace(work_item_store=store, callsign_registry=cr)
        try:
            reply = (
                "[CREATE_TASK title=Misc errand | "
                "instructions=Tidy the ready room shelf | "
                "specialist=@Nobody] Done."
            )
            pipeline = _make_pipeline(
                runtime=runtime, response_text=reply, sanity_gate=DmSanityGate(),
            )
            await pipeline.step_4g_create_task_parse()

            items = await store.list_work_items()
            assert len(items) == 1
            # No callsign match, no department keyword -> unassigned but
            # still created and dispatchable.
            assert items[0].assigned_to is None
            assert items[0].metadata.get("dispatchable") is True
        finally:
            await store.stop()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Gap-regex safety + hook wiring
# ---------------------------------------------------------------------------


def test_yeo_task_protocol_is_gap_regex_safe() -> None:
    """The Yeo protocol text must not contain decomposer capability-gap
    tokens (BF-599 lesson: gap tokens misfire self-mod)."""
    yeo = object.__new__(YeomanAgent)
    yeo.id = "yeoman-001"
    yeo.agent_type = "yeoman"
    yeo.instructions = _DEFAULT_PERSONA + _ROLE_RULES
    yeo._runtime = SimpleNamespace(work_item_store=object())

    block = yeo._conversational_task_protocol({"intent": "direct_message"})
    assert "[CREATE_TASK" in block
    assert _CAPABILITY_GAP_RE.search(block) is None


def test_yeo_task_protocol_honest_degrades_without_store() -> None:
    """No work-item store -> empty block (Yeo is never told it can open
    tasks when the substrate to back them is absent)."""
    yeo = object.__new__(YeomanAgent)
    yeo.id = "yeoman-001"
    yeo.agent_type = "yeoman"
    yeo.instructions = _DEFAULT_PERSONA + _ROLE_RULES
    yeo._runtime = SimpleNamespace(work_item_store=None)

    assert yeo._conversational_task_protocol({"intent": "direct_message"}) == ""

    yeo._runtime = None
    assert yeo._conversational_task_protocol({"intent": "direct_message"}) == ""


def test_base_task_protocol_returns_empty() -> None:
    """The base CognitiveAgent hook is a no-op so other agents are
    unaffected."""
    base = object.__new__(CognitiveAgent)
    assert base._conversational_task_protocol({"intent": "direct_message"}) == ""
