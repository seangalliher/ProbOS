"""AD-726: Boundary tests for ``DmReplyPipeline``.

Twelve tests covering: ordered execution, top-level guard, each step's
degrade path, and ``build_response`` shape both with and without a game move.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from probos.cognitive.dm import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm.reply_value import DmReply  # AD-1248


# --------------------------------------------------------------------------- #
# Minimal fakes — mirrors tests/test_ad724_dm_sanity_gate.py + AD-722a fakes. #
# --------------------------------------------------------------------------- #


@dataclass
class _FakeConfig:
    avatar_telemetry: Any | None = None


@dataclass
class _FakeRuntime:
    config: _FakeConfig = field(default_factory=_FakeConfig)
    recreation_service: Any | None = None
    callsign_registry: Any | None = None
    ward_room: Any | None = None
    episodic_memory: Any | None = None
    intent_bus: Any | None = None
    divergence_results: dict[str, Any] | None = None
    profile_store: Any | None = None


@dataclass
class _FakeAgent:
    agent_id: str = "ezri"
    agent_type: str = "counselor"
    working_memory: Any | None = None
    _marked: bool = False

    def mark_reply_emitted(self) -> None:
        self._marked = True


def _ctx(**overrides: Any) -> DmReplyContext:
    base: dict[str, Any] = {
        "runtime": _FakeRuntime(),
        "agent": _FakeAgent(),
        "agent_id": "ezri",
        "callsign": "ezri",
        "req_message": "hello",
        "reply": DmReply(body="hi there"),
        "has_image_attachment": False,
        "per_attachment": [],
        "sanity_gate": None,
        "params": {},
        "message_text": "hello",
        "sampling_state": None,
        "avatar_event_bus": None,
    }
    base.update(overrides)
    # AD-1248: callers still express the body as text; the ctx now holds the
    # canonical value, so translate here rather than at 30 call sites.
    if "response_text" in base:
        base["reply"] = DmReply(body=base.pop("response_text"))
    return DmReplyContext(**base)


# --------------------------------------------------------------------------- #
# 1. ordered execution                                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_run_executes_all_nine_steps_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = DmReplyPipeline(_ctx())
    called: list[str] = []

    async def make(name: str) -> Any:
        async def _step() -> None:
            called.append(name)
        return _step

    for name in (
        "step_1_sanity_gate_retry",
        "step_2_challenge_parse",
        "step_3_move_parse",
        "step_4_self_check_parse",
        "step_5_episodic_store",
        "step_6_working_memory_record",
        "step_7_divergence_check",
        "step_8_mark_emitted",
        "step_9_emotion_resolve",
    ):
        monkeypatch.setattr(pipeline, name, await make(name))
    await pipeline.run()
    assert called == [
        "step_1_sanity_gate_retry",
        "step_2_challenge_parse",
        "step_3_move_parse",
        "step_4_self_check_parse",
        "step_5_episodic_store",
        "step_6_working_memory_record",
        "step_7_divergence_check",
        "step_8_mark_emitted",
        "step_9_emotion_resolve",
    ]


# --------------------------------------------------------------------------- #
# 2. top-level guard                                                          #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_run_continues_when_step_1_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = DmReplyPipeline(_ctx())
    reached: list[str] = []

    async def _boom() -> None:
        raise RuntimeError("boom")

    async def _ok() -> None:
        reached.append("ok")

    monkeypatch.setattr(pipeline, "step_1_sanity_gate_retry", _boom)
    for name in (
        "step_2_challenge_parse",
        "step_3_move_parse",
        "step_4_self_check_parse",
        "step_5_episodic_store",
        "step_6_working_memory_record",
        "step_7_divergence_check",
        "step_8_mark_emitted",
        "step_9_emotion_resolve",
    ):
        monkeypatch.setattr(pipeline, name, _ok)
    await pipeline.run()
    assert len(reached) == 8  # steps 2..9 all ran


# --------------------------------------------------------------------------- #
# 3. step 1 — no sanity gate ⇒ no-op                                          #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_step_1_sanity_gate_retry_no_warnings_skips_retry() -> None:
    pipeline = DmReplyPipeline(_ctx(sanity_gate=None, response_text="clean"))
    await pipeline.step_1_sanity_gate_retry()
    assert pipeline.ctx.response_text == "clean"


# --------------------------------------------------------------------------- #
# 4. step 2 — no recreation_service ⇒ skip                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_step_2_challenge_parse_no_recreation_service_skips() -> None:
    rt = _FakeRuntime()
    # explicit: hasattr is True with value None
    rt.recreation_service = None
    pipeline = DmReplyPipeline(_ctx(runtime=rt, response_text="hi"))
    await pipeline.step_2_challenge_parse()
    assert pipeline.ctx.response_text == "hi"


# --------------------------------------------------------------------------- #
# 5. step 3 — no active game ⇒ skip; game_move_result stays None              #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_step_3_move_parse_no_active_game_skips() -> None:
    class _Gate:
        def extract_move(self, _t: str) -> str | None:
            return "A1"

        def strip_move(self, t: str) -> str:
            return t.replace("[MOVE A1]", "").strip()

    class _RecSvc:
        def get_game_by_player(self, _c: str) -> dict[str, Any] | None:
            return None

    rt = _FakeRuntime()
    rt.recreation_service = _RecSvc()
    pipeline = DmReplyPipeline(_ctx(
        runtime=rt, sanity_gate=_Gate(), response_text="play [MOVE A1]",
    ))
    await pipeline.step_3_move_parse()
    assert pipeline.ctx.game_move_result is None
    # tag still stripped
    assert pipeline.ctx.response_text == "play"


# --------------------------------------------------------------------------- #
# 6. step 5 — no episodic memory ⇒ skip                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_step_5_episodic_store_no_episodic_memory_skips() -> None:
    pipeline = DmReplyPipeline(_ctx())  # runtime has no episodic_memory
    # Should not raise.
    await pipeline.step_5_episodic_store()


# --------------------------------------------------------------------------- #
# 7. step 6 — no working memory ⇒ skip                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_step_6_working_memory_no_wm_skips() -> None:
    a = _FakeAgent(working_memory=None)
    pipeline = DmReplyPipeline(_ctx(agent=a))
    await pipeline.step_6_working_memory_record()  # no exception


# --------------------------------------------------------------------------- #
# 8. step 7 — divergence disabled ⇒ skip                                      #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_step_7_divergence_disabled_skips() -> None:
    @dataclass
    class _T:
        divergence_detection: bool = False

    rt = _FakeRuntime(config=_FakeConfig(avatar_telemetry=_T()))
    pipeline = DmReplyPipeline(_ctx(runtime=rt, response_text="x"))
    await pipeline.step_7_divergence_check()
    assert pipeline.ctx.response_text == "x"


# --------------------------------------------------------------------------- #
# 9. step 8 — no mark_reply_emitted ⇒ skip                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_step_8_mark_emitted_no_method_skips() -> None:
    class _Bare:
        agent_id = "x"
    pipeline = DmReplyPipeline(_ctx(agent=_Bare()))
    await pipeline.step_8_mark_emitted()  # no exception


# --------------------------------------------------------------------------- #
# 10. step 9 — no divergence_results ⇒ emotion stays None                     #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_step_9_emotion_no_divergence_results_emotion_stays_none() -> None:
    pipeline = DmReplyPipeline(_ctx())
    await pipeline.step_9_emotion_resolve()
    assert pipeline.ctx.emotion is None


# --------------------------------------------------------------------------- #
# 11. build_response — game move branch                                       #
# --------------------------------------------------------------------------- #


def test_build_response_includes_game_status_when_move_executed() -> None:
    pipeline = DmReplyPipeline(_ctx(response_text="hi"))
    pipeline.ctx.game_move_result = {"state": {"status": "in_progress"}}
    out = pipeline.build_response()
    assert out["gameMoveExecuted"] is True
    assert out["gameStatus"] == "in_progress"


# --------------------------------------------------------------------------- #
# 12. build_response — no game move                                           #
# --------------------------------------------------------------------------- #


def test_build_response_omits_game_keys_when_no_move() -> None:
    pipeline = DmReplyPipeline(_ctx(response_text="hi"))
    out = pipeline.build_response()
    assert "gameMoveExecuted" not in out
    assert "gameStatus" not in out
    assert out == {
        "response": "hi",
        "callsign": "ezri",
        "agentId": "ezri",
        "emotion": None,
    }
