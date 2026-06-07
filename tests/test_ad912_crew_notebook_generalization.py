"""AD-912: Generalize 1:1 notebook persistence from Yeoman-only to all crew.

AD-911 let the Yeoman durably save a Captain-requested note from a 1:1 chat
(``[NOTEBOOK slug]...[/NOTEBOOK]``), but scoped both the teaching hook and the
``DmReplyPipeline`` persistence to ``agent_type == "yeoman"``. Notebooks are a
universal agent capability on the proactive / Ward-Room path, so AD-912 brings
the 1:1 path to parity:

1. ``CognitiveAgent._conversational_notebook_protocol`` (the base hook) now
   teaches the tag to ANY agent that has a records store wired (honest-degrade
   to "" without one), instead of returning "" by default.
2. ``YeomanAgent`` drops its now-redundant override and inherits the base hook.
3. ``DmReplyPipeline.step_4i_notebook_parse`` persists for ANY agent (not just
   the Yeoman), with a final safety-net unwrap so a raw block never leaks when
   persistence is unavailable.

Real ``RecordsStore`` (tmp_path) + real ``ProactiveCognitiveLoop`` + real
``DmReplyContext`` \u2014 no MagicMock at the substrate boundary (BF-287).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.cognitive.yeoman import YeomanAgent
from probos.config import RecordsConfig
from probos.proactive import ProactiveCognitiveLoop


# ---------------------------------------------------------------------------
# Helpers (substrate-honest: real store, real loop, real ctx)
# ---------------------------------------------------------------------------


def _hook(runtime: object) -> str:
    """Call the base notebook hook with an arbitrary (non-Yeoman) self that
    only carries a ``_runtime`` \u2014 exercises the generalized base behaviour."""
    return CognitiveAgent._conversational_notebook_protocol(
        SimpleNamespace(_runtime=runtime), {"intent": "direct_message"},
    )


async def _make_records_store(tmp_path: Path):
    from probos.knowledge.records_store import RecordsStore

    cfg = RecordsConfig(
        repo_path=str(tmp_path / "ship-records"),
        enabled=True,
        auto_commit=False,
        commit_debounce_seconds=5.0,
        max_episodes_per_hour=20,
    )
    store = RecordsStore(cfg)
    await store.initialize()
    return store


def _make_loop(store) -> ProactiveCognitiveLoop:
    loop = ProactiveCognitiveLoop()
    loop._runtime = SimpleNamespace(
        _records_store=store, ontology=None, config=None,
    )
    return loop


def _make_pipeline(*, runtime, agent, response_text: str) -> DmReplyPipeline:
    ctx = DmReplyContext(
        runtime=runtime,
        agent=agent,
        agent_id=getattr(agent, "id", "agent-001"),
        callsign=getattr(agent, "callsign", "Agent"),
        req_message="Save this to your notebook",
        response_text=response_text,
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=None,
        params={},
        message_text="Save this to your notebook",
        sampling_state=None,
        avatar_event_bus=None,
    )
    return DmReplyPipeline(ctx)


# ===========================================================================
# Base hook now teaches any crew agent (not just the Yeoman)
# ===========================================================================


def test_base_hook_teaches_any_agent_with_store() -> None:
    block = _hook(SimpleNamespace(_records_store=object()))
    assert "[NOTEBOOK" in block
    assert "[/NOTEBOOK]" in block
    assert "topic-slug" in block


def test_base_hook_honest_degrades_without_store() -> None:
    assert _hook(SimpleNamespace(_records_store=None)) == ""


def test_base_hook_honest_degrades_without_runtime() -> None:
    assert _hook(None) == ""


def test_base_hook_no_runtime_attr_returns_empty() -> None:
    # An object with no ``_runtime`` at all (LSP safety) still degrades.
    assert CognitiveAgent._conversational_notebook_protocol(object(), {}) == ""


def test_base_hook_text_is_gap_regex_safe() -> None:
    block = _hook(SimpleNamespace(_records_store=object()))
    assert not _CAPABILITY_GAP_RE.search(block)


def test_yeoman_inherits_base_hook() -> None:
    # AD-912 removed Yeo's override; the inherited base hook still teaches him.
    assert (
        YeomanAgent._conversational_notebook_protocol
        is CognitiveAgent._conversational_notebook_protocol
    )


# ===========================================================================
# Pipeline step persists for any crew agent
# ===========================================================================


def test_step_persists_for_engineer(tmp_path) -> None:
    async def _run() -> None:
        store = await _make_records_store(tmp_path)
        loop = _make_loop(store)
        runtime = SimpleNamespace(proactive_loop=loop)
        agent = SimpleNamespace(
            id="eng-001", agent_type="engineer", callsign="Scott",
        )
        text = (
            "Aye, Captain. [NOTEBOOK warp-core-tuning]\n"
            "Realign the dilithium matrix at 0300.\n[/NOTEBOOK] Logged."
        )
        pipeline = _make_pipeline(
            runtime=runtime, agent=agent, response_text=text,
        )
        await pipeline.step_4i_notebook_parse()
        assert "[NOTEBOOK" not in pipeline.ctx.response_text
        assert "Aye, Captain." in pipeline.ctx.response_text
        nb = store.repo_path / "notebooks" / "Scott" / "warp-core-tuning.md"
        assert nb.is_file()
        assert "dilithium matrix" in nb.read_text(encoding="utf-8")

    asyncio.run(_run())


def test_step_safety_net_unwraps_when_loop_unwired(tmp_path) -> None:
    # No proactive loop -> cannot persist, but the Captain must never see a
    # raw block: the safety-net unwrap keeps the inner text and drops the tags.
    async def _run() -> None:
        runtime = SimpleNamespace(proactive_loop=None)
        agent = SimpleNamespace(
            id="sci-001", agent_type="science", callsign="Spock",
        )
        text = "Fascinating. [NOTEBOOK anomaly]\nSensor ghost at 0400.\n[/NOTEBOOK]"
        pipeline = _make_pipeline(
            runtime=runtime, agent=agent, response_text=text,
        )
        await pipeline.step_4i_notebook_parse()
        assert "[NOTEBOOK" not in pipeline.ctx.response_text
        assert "Sensor ghost at 0400." in pipeline.ctx.response_text

    asyncio.run(_run())


def test_step_noop_without_marker(tmp_path) -> None:
    async def _run() -> None:
        store = await _make_records_store(tmp_path)
        loop = _make_loop(store)
        runtime = SimpleNamespace(proactive_loop=loop)
        agent = SimpleNamespace(
            id="eng-001", agent_type="engineer", callsign="Scott",
        )
        text = "Just a normal status report, Captain."
        pipeline = _make_pipeline(
            runtime=runtime, agent=agent, response_text=text,
        )
        await pipeline.step_4i_notebook_parse()
        assert pipeline.ctx.response_text == text

    asyncio.run(_run())
