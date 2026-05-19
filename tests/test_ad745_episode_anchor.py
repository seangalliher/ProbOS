"""AD-745: episode-anchor tests (AD-541b integration)."""
from __future__ import annotations

import pytest

from probos.cognitive.dm.action_dispatcher import ActionDispatcher
from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.config import SystemConfig


class _FakeSession:
    session_id = "s-1"
    last_url = "https://example.com/page"
    aborted = False


class _FakeBT:
    def __init__(self) -> None:
        self._session = _FakeSession()

    def get_session(self, agent_id: str):
        return self._session

    async def invoke(self, params, context=None):
        class _R:
            output = {"ok": True}
            error = None
        return _R()


class _FakeEpisodic:
    def __init__(self) -> None:
        self.stored: list = []

    async def store(self, ep) -> None:
        self.stored.append(ep)


def _runtime():
    cfg = SystemConfig()
    cfg.browser_tool.action_dispatch_enabled = True

    class _RT:
        config = cfg
        action_dispatcher = ActionDispatcher()
        browser_tool = _FakeBT()
        episodic_memory = _FakeEpisodic()

    return _RT()


def _pipeline(rt, reply: str) -> DmReplyPipeline:
    ctx = DmReplyContext(
        runtime=rt, agent=object(), agent_id="counselor", callsign="Counselor",
        req_message="hi", response_text=reply, has_image_attachment=False,
        per_attachment=[], sanity_gate=None,
        params={"thread_id": "tt", "dm_turn_id": "td"},
        message_text="hi", sampling_state=None, avatar_event_bus=None,
    )
    return DmReplyPipeline(ctx)


@pytest.mark.asyncio
async def test_episode_anchor_written_for_dispatched_action() -> None:
    """AD-541b: every dispatched action writes an Episode with the
    ``agent_action_executed`` anchor."""
    rt = _runtime()
    reply = '[ACTION: {"verb":"screenshot","args":{}}]'
    pipe = _pipeline(rt, reply)
    await pipe.step_4e_action_dispatch()

    assert rt.episodic_memory.stored, "no episode stored"
    ep = rt.episodic_memory.stored[-1]
    assert ep.anchors is not None
    assert ep.anchors.channel == "action"
    assert ep.anchors.trigger_type == "agent_action_executed"
    assert ep.anchors.trigger_agent == "counselor"
    assert ep.source == "action_dispatch"


@pytest.mark.asyncio
async def test_episode_outcome_carries_args_hash() -> None:
    """Outcomes include verb + args_hash + tier_classified (audit trail)."""
    rt = _runtime()
    reply = '[ACTION: {"verb":"click","args":{"selector":"#x"},"intent":"x button"}]'
    pipe = _pipeline(rt, reply)
    await pipe.step_4e_action_dispatch()

    ep = rt.episodic_memory.stored[-1]
    assert ep.outcomes and len(ep.outcomes) == 1
    outcome = ep.outcomes[0]
    assert outcome["intent"] == "agent_action_executed"
    assert outcome["verb"] == "click"
    assert isinstance(outcome["args_hash"], str)
    assert len(outcome["args_hash"]) == 64  # sha256 hex
    assert outcome["tier_classified"] == 2


@pytest.mark.asyncio
async def test_ad731_invariant_no_bytes_in_outcomes() -> None:
    """AD-731: outcomes carry SHA refs (None pre-execution), never bytes."""
    rt = _runtime()
    reply = '[ACTION: {"verb":"state","args":{}}]'
    pipe = _pipeline(rt, reply)
    await pipe.step_4e_action_dispatch()

    ep = rt.episodic_memory.stored[-1]
    outcome = ep.outcomes[0]
    # before/after frame ref slots exist; v1 pre-execution snapshot is
    # None for tier-1; the keys exist for the audit pipeline.
    assert "before_frame_ref" in outcome
    assert "after_frame_ref" in outcome
    # Whatever the values are, they must not be raw bytes.
    assert not isinstance(outcome["before_frame_ref"], (bytes, bytearray))
    assert not isinstance(outcome["after_frame_ref"], (bytes, bytearray))

    # Source-scan: action_parser + agent_actions router contain no b64encode.
    from pathlib import Path
    for fname in (
        "src/probos/cognitive/dm/action_parser.py",
        "src/probos/cognitive/dm/action_dispatcher.py",
        "src/probos/routers/agent_actions.py",
    ):
        src = Path(fname).read_text(encoding="utf-8")
        assert "b64encode(" not in src
        assert "base64.b64encode" not in src
