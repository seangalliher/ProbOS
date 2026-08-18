"""BF-296: DmReplyPipeline parses [DM @callsign]...[/DM] markers in
Captain-bound replies and dispatches them as outbound DMs.

Captain log 2026-05-17: Ezri tried to DM Atlas from within a Captain
chat — the [DM @Atlas]...[/DM] marker leaked through to the displayed
reply because DmReplyPipeline had no extractor. AD-453 already implemented
the extraction logic in ProactiveCognitiveLoop.extract_and_execute_dms; BF-296
exposes it as a public method and wires it into a new pipeline sub-step
(step_4b_dm_outbound_parse).
"""

from __future__ import annotations

import asyncio
import inspect

from probos.cognitive.dm.reply_value import DmReply  # AD-1248


def test_bf296_step_4b_present_in_pipeline_tuple() -> None:
    """The new sub-step must be wired into the run() iteration tuple
    between step_4_self_check_parse and step_5_episodic_store.

    AD-933 extracted the 17-step tuple out of ``run()`` into
    ``_full_steps()`` (the single source of truth ``run()`` now executes), so
    the tuple — and this structural guard — live in ``_full_steps``.
    """
    from probos.cognitive.dm import reply_pipeline as rp

    src = inspect.getsource(rp.DmReplyPipeline._full_steps)
    assert "self.step_4b_dm_outbound_parse," in src, (
        "BF-296: step_4b_dm_outbound_parse must appear in the _full_steps() tuple."
    )
    # Ordering: must come after self_check_parse and before episodic_store.
    sc_idx = src.find("self.step_4_self_check_parse,")
    bf_idx = src.find("self.step_4b_dm_outbound_parse,")
    ep_idx = src.find("self.step_5_episodic_store,")
    assert sc_idx < bf_idx < ep_idx, (
        "BF-296: ordering must be self_check → dm_outbound → episodic_store."
    )


def test_bf296_method_calls_proactive_extract_helper() -> None:
    """The method must delegate to ProactiveLoop.extract_and_execute_dms
    (public name — was renamed from the private _ variant)."""
    from probos.cognitive.dm import reply_pipeline as rp

    src = inspect.getsource(rp.DmReplyPipeline.step_4b_dm_outbound_parse)
    assert "extract_and_execute_dms" in src, (
        "step_4b must call extract_and_execute_dms on proactive_loop."
    )
    # Honest-degrade when proactive_loop missing.
    assert "proactive_loop" in src and (
        "getattr" in src or "hasattr" in src
    ), "step_4b must honest-degrade when proactive_loop is unavailable."


def test_bf296_proactive_extract_is_public() -> None:
    """ProactiveCognitiveLoop.extract_and_execute_dms is the public API
    (was private _extract_and_execute_dms in AD-453, renamed public BF-296)."""
    from probos import proactive

    assert hasattr(proactive.ProactiveCognitiveLoop, "extract_and_execute_dms"), (
        "BF-296: ProactiveCognitiveLoop must expose public extract_and_execute_dms."
    )


def test_bf296_step_4b_strips_marker_when_proactive_loop_available() -> None:
    """End-to-end shape: when proactive_loop is present, the step delegates
    to it and adopts the cleaned text it returns."""
    from probos.cognitive.dm import reply_pipeline as rp
    from types import SimpleNamespace

    captured: dict = {}

    class _FakeProactive:
        async def extract_and_execute_dms(self, agent, text):
            captured["agent"] = agent
            captured["text"] = text
            # Simulate stripping the marker and dispatching 1 action.
            return ("Cleaned reply.", [{"action": "dm", "target": "atlas"}])

    runtime = SimpleNamespace(proactive_loop=_FakeProactive())
    agent = SimpleNamespace(agent_id="counselor-1")

    ctx = rp.DmReplyContext(
        runtime=runtime,
        agent=agent,
        agent_id="counselor-1",
        callsign="ezri",
        req_message="check on Atlas",
        reply=DmReply(body=(
            "On it.\n[DM @Atlas]\nAtlas, just checking in.\n[/DM]\nDone."
        )),
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=None,
        params={},
        message_text="check on Atlas",
        sampling_state=None,
        avatar_event_bus=None,
    )

    pipeline = rp.DmReplyPipeline(ctx)
    asyncio.run(pipeline.step_4b_dm_outbound_parse())

    assert captured["agent"] is agent
    assert "[DM @Atlas]" in captured["text"]  # raw marker was passed
    assert ctx.response_text == "Cleaned reply."


def test_bf296_step_4b_honest_degrade_when_no_proactive_loop() -> None:
    """No proactive_loop → leave response_text untouched (marker stays so
    Captain at least sees the agent's intent rather than silent drop)."""
    from probos.cognitive.dm import reply_pipeline as rp
    from types import SimpleNamespace

    runtime = SimpleNamespace(proactive_loop=None)
    agent = SimpleNamespace(agent_id="counselor-1")

    original = "On it.\n[DM @Atlas]\nbody\n[/DM]\nDone."
    ctx = rp.DmReplyContext(
        runtime=runtime,
        agent=agent,
        agent_id="counselor-1",
        callsign="ezri",
        req_message="x",
        reply=DmReply(body=original),
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=None,
        params={},
        message_text="x",
        sampling_state=None,
        avatar_event_bus=None,
    )

    pipeline = rp.DmReplyPipeline(ctx)
    asyncio.run(pipeline.step_4b_dm_outbound_parse())

    assert ctx.response_text == original
