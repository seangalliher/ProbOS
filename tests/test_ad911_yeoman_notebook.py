"""AD-911: Yeoman notebook persistence from 1:1 Captain DMs.

Before AD-911, a ``[NOTEBOOK slug]...[/NOTEBOOK]`` block emitted by an agent
in a 1:1 Captain chat was discarded as plain text — the ``DmReplyPipeline``
had no notebook extractor (only the proactive / Ward-Room path persisted
notebooks). So when the Captain asked Yeo to "save this to your notebook",
nothing was written. AD-911:

1. Adds an overridable ``CognitiveAgent._conversational_notebook_protocol``
   hook (base returns "") that ``YeomanAgent`` overrides to teach the
   ``[NOTEBOOK ...]`` reply tag — honest-degrade: "" when no records store.
2. Adds ``ProactiveLoop.extract_and_execute_notebooks`` (lean writer reusing
   the AD-550 dedup gate) and a ``DmReplyPipeline.step_4i_notebook_parse``
   that persists a Captain-requested note. (AD-912 later generalized the
   pipeline step + the base hook from Yeoman-only to all crew agents; see
   ``test_ad912_crew_notebook_generalization.py``.)

Real ``RecordsStore`` (tmp_path) + real ``ProactiveCognitiveLoop`` + real
``DmReplyContext`` — no MagicMock at the substrate boundary (BF-287).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.cognitive.yeoman import YeomanAgent, _DEFAULT_PERSONA, _ROLE_RULES
from probos.config import RecordsConfig
from probos.proactive import ProactiveCognitiveLoop


# ---------------------------------------------------------------------------
# Fixtures / helpers (substrate-honest: real store, real loop, real ctx)
# ---------------------------------------------------------------------------


def _make_yeo(*, runtime: object) -> YeomanAgent:
    """Construct a YeomanAgent bypassing the singleton guard (mirrors the
    AD-870 test helper)."""
    yeo = object.__new__(YeomanAgent)
    yeo.id = "yeoman-001"
    yeo.agent_type = "yeoman"
    yeo.instructions = _DEFAULT_PERSONA + _ROLE_RULES
    yeo._runtime = runtime
    return yeo


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


def _make_pipeline(*, runtime: object, agent: object, response_text: str) -> DmReplyPipeline:
    ctx = DmReplyContext(
        runtime=runtime,
        agent=agent,
        agent_id=getattr(agent, "id", "yeoman-001"),
        callsign="Yeo",
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
# Conversational notebook protocol hook
# ===========================================================================


def test_base_hook_returns_empty() -> None:
    # LSP / Open-Closed: non-overriding agents are byte-unaffected.
    assert CognitiveAgent._conversational_notebook_protocol(object(), {}) == ""


def test_yeoman_hook_teaches_tag_when_store_wired() -> None:
    runtime = SimpleNamespace(_records_store=object())
    block = _make_yeo(runtime=runtime)._conversational_notebook_protocol(
        {"intent": "direct_message"}
    )
    assert "[NOTEBOOK" in block
    assert "[/NOTEBOOK]" in block
    assert "topic-slug" in block


def test_yeoman_hook_honest_degrades_without_store() -> None:
    runtime = SimpleNamespace(_records_store=None)
    block = _make_yeo(runtime=runtime)._conversational_notebook_protocol(
        {"intent": "direct_message"}
    )
    assert block == ""


def test_yeoman_hook_no_runtime_returns_empty() -> None:
    block = _make_yeo(runtime=None)._conversational_notebook_protocol(
        {"intent": "direct_message"}
    )
    assert block == ""


def test_notebook_protocol_is_gap_regex_safe() -> None:
    runtime = SimpleNamespace(_records_store=object())
    block = _make_yeo(runtime=runtime)._conversational_notebook_protocol(
        {"intent": "direct_message"}
    )
    assert not _CAPABILITY_GAP_RE.search(block)


# ===========================================================================
# extract_and_execute_notebooks (lean writer)
# ===========================================================================


def test_extract_persists_notebook_and_strips_markers(tmp_path) -> None:
    async def _run() -> None:
        store = await _make_records_store(tmp_path)
        loop = _make_loop(store)
        agent = SimpleNamespace(
            callsign="Yeo", agent_type="yeoman", agent_id="yeoman-001",
        )
        text = (
            "On it, Captain. [NOTEBOOK spacex-ipo-trade-setup]\n"
            "## SpaceX IPO Trade\nEntry at 200, target 280.\n"
            "[/NOTEBOOK] Saved."
        )
        cleaned, actions = await loop.extract_and_execute_notebooks(agent, text)

        # Marker removed from the Captain-visible reply.
        assert "[NOTEBOOK" not in cleaned
        assert "[/NOTEBOOK]" not in cleaned
        assert "On it, Captain." in cleaned and "Saved." in cleaned
        # One write action recorded.
        assert len(actions) == 1
        assert actions[0]["type"] == "notebook_write"
        assert actions[0]["topic"] == "spacex-ipo-trade-setup"
        # Durably persisted to disk.
        nb = store.repo_path / "notebooks" / "Yeo" / "spacex-ipo-trade-setup.md"
        assert nb.is_file()
        assert "Entry at 200" in nb.read_text(encoding="utf-8")

    asyncio.run(_run())


def test_extract_no_marker_is_noop(tmp_path) -> None:
    async def _run() -> None:
        store = await _make_records_store(tmp_path)
        loop = _make_loop(store)
        agent = SimpleNamespace(callsign="Yeo", agent_type="yeoman")
        text = "Just a normal reply, Captain."
        cleaned, actions = await loop.extract_and_execute_notebooks(agent, text)
        assert cleaned == text
        assert actions == []

    asyncio.run(_run())


def test_extract_no_records_store_leaves_text_untouched() -> None:
    async def _run() -> None:
        loop = ProactiveCognitiveLoop()
        loop._runtime = SimpleNamespace(_records_store=None)
        agent = SimpleNamespace(callsign="Yeo", agent_type="yeoman")
        text = "Sure. [NOTEBOOK x]content[/NOTEBOOK]"
        cleaned, actions = await loop.extract_and_execute_notebooks(agent, text)
        assert cleaned == text  # untouched — cannot persist, so don't strip
        assert actions == []

    asyncio.run(_run())


def test_extract_skips_empty_block(tmp_path) -> None:
    async def _run() -> None:
        store = await _make_records_store(tmp_path)
        loop = _make_loop(store)
        agent = SimpleNamespace(callsign="Yeo", agent_type="yeoman")
        text = "Here: [NOTEBOOK empty-slug]   [/NOTEBOOK] done."
        cleaned, actions = await loop.extract_and_execute_notebooks(agent, text)
        assert "[NOTEBOOK" not in cleaned  # marker still stripped
        assert actions == []  # but nothing written for an empty block

    asyncio.run(_run())


# ===========================================================================
# Pipeline step: step_4i_notebook_parse
# ===========================================================================


def test_step_registered_in_pipeline_run_order() -> None:
    # The step must exist and be wired so episodes/text reflect the cleanup.
    assert hasattr(DmReplyPipeline, "step_4i_notebook_parse")


def test_step_persists_for_yeoman(tmp_path) -> None:
    async def _run() -> None:
        store = await _make_records_store(tmp_path)
        loop = _make_loop(store)
        runtime = SimpleNamespace(proactive_loop=loop)
        agent = SimpleNamespace(
            id="yeoman-001", agent_type="yeoman", callsign="Yeo",
        )
        text = "Done. [NOTEBOOK trade-notes]\nBuy SpaceX at IPO.\n[/NOTEBOOK]"
        pipeline = _make_pipeline(
            runtime=runtime, agent=agent, response_text=text,
        )
        await pipeline.step_4i_notebook_parse()
        assert "[NOTEBOOK" not in pipeline.ctx.response_text
        nb = store.repo_path / "notebooks" / "Yeo" / "trade-notes.md"
        assert nb.is_file()
        assert "Buy SpaceX at IPO" in nb.read_text(encoding="utf-8")

    asyncio.run(_run())


def test_step_persists_for_non_yeoman_crew_agent(tmp_path) -> None:
    # AD-912: generalized from Yeoman-only — a non-Yeoman crew agent's
    # Captain-requested note is now persisted too (was unwrap-only in AD-911).
    async def _run() -> None:
        store = await _make_records_store(tmp_path)
        loop = _make_loop(store)
        runtime = SimpleNamespace(proactive_loop=loop)
        agent = SimpleNamespace(
            id="counselor-001", agent_type="counselor", callsign="Counselor",
        )
        text = "Noted. [NOTEBOOK feelings]\nThe crew is tired.\n[/NOTEBOOK]"
        pipeline = _make_pipeline(
            runtime=runtime, agent=agent, response_text=text,
        )
        await pipeline.step_4i_notebook_parse()
        # Block removed from the Captain-visible reply (content -> notebook);
        # the surrounding confirmation text remains.
        assert "[NOTEBOOK" not in pipeline.ctx.response_text
        assert "Noted." in pipeline.ctx.response_text
        # Durably persisted under the counselor's callsign.
        nb = store.repo_path / "notebooks" / "Counselor" / "feelings.md"
        assert nb.is_file()
        assert "The crew is tired." in nb.read_text(encoding="utf-8")

    asyncio.run(_run())


def test_step_noop_without_marker(tmp_path) -> None:
    async def _run() -> None:
        store = await _make_records_store(tmp_path)
        loop = _make_loop(store)
        runtime = SimpleNamespace(proactive_loop=loop)
        agent = SimpleNamespace(
            id="yeoman-001", agent_type="yeoman", callsign="Yeo",
        )
        text = "Just a normal reply."
        pipeline = _make_pipeline(
            runtime=runtime, agent=agent, response_text=text,
        )
        await pipeline.step_4i_notebook_parse()
        assert pipeline.ctx.response_text == text

    asyncio.run(_run())
