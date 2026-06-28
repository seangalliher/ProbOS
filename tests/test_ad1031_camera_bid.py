"""AD-1031: camera / visual scene as a salience-gated bid (closes #973, BF-632 class).

Two-site, default-OFF, byte-identical-when-OFF change. Tests use REAL objects at
the agent/config boundary (BF-287: no MagicMock auto-attributes): a real
``CognitiveAgent`` (via the AD-1028 golden fixture builder), a real
``SystemConfig`` with the AD-1031 flag flipped, and real ``VisionObservation`` /
``VisionWorkingMemory`` to render the scene block exactly as the router does.

Test layout:
- ``test_visual_reference_score_*`` — the pure keyword/phrase helper.
- ``test_off_*`` — flag OFF (default): the agent emits NO camera bid even when
  ``params['_visual_scene']`` is present, and the AD-1028 DM golden is
  byte-identical (the byte-identity proof; the router-prepend tests in
  ``test_ad733a_vision_consumer.py`` cover the router side).
- ``test_on_*`` — flag ON: PROMINENT (referenced / changed / visual-task / empty
  sentinel) vs RECESSIVE (unchanged + non-visual) gating + ordering.
- ``test_recall_query_unaffected`` — BF-632: the recall query stays the raw
  Captain message.
"""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

from probos.cognitive.cognitive_agent import _dm_recall_query
from probos.cognitive.salience import suppress_visual_injection, visual_reference_score
from probos.config import SystemConfig
from probos.perception.working_memory import VisionObservation, VisionWorkingMemory
from tests.fixtures.ad1028_golden._capture_golden import (
    dm_observation,
    make_dm_agent,
)

_GOLDEN_DIR = Path(__file__).parent / "fixtures" / "ad1028_golden"

_SCENE_MARKER = "--- Current Visual Context ---"
_SENTINEL_A = "Camera not active or no frames described yet"
_SENTINEL_B = "Do NOT describe what you cannot see"


# ---------------------------------------------------------------------------
# Real-object helpers (BF-287)
# ---------------------------------------------------------------------------


def _render_scene(
    description: str, novelty: float
) -> tuple[str, VisionObservation]:
    """Render a populated scene block exactly as the router does.

    Mirrors ``routers/agents.py``: ``render_for_prompt()`` for ``_visual_scene``
    and ``latest()`` for ``_visual_novelty`` / ``_visual_summary``.
    """
    wm = VisionWorkingMemory(capacity=8)
    obs = VisionObservation(
        timestamp=time.time(),
        attachment_ref="sha-test",
        description=description,
        novelty_score=novelty,
        subject_identity="captain",
        session_id="s1",
    )
    wm.append(obs)
    return wm.render_for_prompt(), wm.latest()  # type: ignore[return-value]


def _empty_scene() -> str:
    """The BF-294 confabulation sentinel an empty WM renders."""
    return VisionWorkingMemory(capacity=8).render_for_prompt()


def _make_on_agent(*, novelty_min: float = 0.3):
    """A real DM agent with the AD-1031 camera-scene bid flipped ON.

    Real ``SystemConfig`` (attention budget stays OFF ⇒ unbounded budget ⇒
    nothing drops; the ContextAssembler path runs, matching production where
    perception is ON while attention is OFF).
    """
    agent = make_dm_agent()
    cfg = SystemConfig()
    cfg.memory.attention.camera_scene_bid_enabled = True
    cfg.memory.attention.camera_novelty_minimum = novelty_min
    agent._runtime = SimpleNamespace(config=cfg)
    return agent


def _dm_obs(
    *,
    captain_msg: str,
    scene: str,
    novelty: float,
    summary: str,
    has_image: bool = False,
) -> dict:
    """A ``direct_message`` observation carrying the ON-path visual params.

    ``text`` is the (already scene-free) Captain turn — the router does NOT
    prepend the scene onto ``text`` when ON. ``captain_message`` is the RAW turn
    (BF-632) used for reference detection + recall.
    """
    params: dict[str, object] = {
        "text": captain_msg,
        "captain_message": captain_msg,
        "_visual_scene": scene,
        "_visual_novelty": novelty,
        "_visual_summary": summary,
    }
    if has_image:
        params["has_image_attachment"] = True
    return {"intent": "direct_message", "params": params}


# ---------------------------------------------------------------------------
# visual_reference_score — pure helper
# ---------------------------------------------------------------------------


def test_visual_reference_score_positive_phrases() -> None:
    for msg in (
        "What do you see right now?",
        "Can you see this?",
        "Show me the report",
        "Is there anything behind me?",
        "What's on screen?",
        "Look at this image",
    ):
        assert visual_reference_score(msg) == 1.0, msg


def test_visual_reference_score_positive_keywords() -> None:
    for msg in (
        "Are you watching?",
        "Is the camera on?",
        "What am I wearing?",
        "Describe the picture",
        "Your visual feed",
    ):
        assert visual_reference_score(msg) == 1.0, msg


def test_visual_reference_score_negative() -> None:
    for msg in (
        "What is the warp core status?",
        "Tell me about the coolant variance",
        "Summarize the engineering report",
        "How are you today?",
    ):
        assert visual_reference_score(msg) == 0.0, msg


def test_visual_reference_score_word_boundary_no_false_positive() -> None:
    # "seem" contains "see"; "overlook" contains "look" — neither is a vision
    # reference. Word-boundary tokenization must NOT match them.
    assert visual_reference_score("That does not seem right") == 0.0
    assert visual_reference_score("Do not overlook the details") == 0.0


def test_visual_reference_score_empty_and_nonstring() -> None:
    assert visual_reference_score("") == 0.0
    assert visual_reference_score(None) == 0.0  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AD-1060: suppress_visual_injection — adaptive injection-frequency gate
# ---------------------------------------------------------------------------


def test_suppress_off_when_threshold_zero() -> None:
    # threshold 0 disables suppression entirely (byte-identical to AD-1031).
    assert suppress_visual_injection(
        referenced=False, is_visual_task=False, raw_novelty=0.0,
        decayed_novelty=0.0, novelty_minimum=0.3, suppress_threshold=0.0,
    ) is False


def test_suppress_when_stable_low_novelty() -> None:
    # stable background: decayed < threshold, raw < min, no ref/task -> suppress.
    assert suppress_visual_injection(
        referenced=False, is_visual_task=False, raw_novelty=0.05,
        decayed_novelty=0.08, novelty_minimum=0.3, suppress_threshold=0.15,
    ) is True


def test_no_suppress_on_visual_reference() -> None:
    # an explicit visual reference ALWAYS injects.
    assert suppress_visual_injection(
        referenced=True, is_visual_task=False, raw_novelty=0.05,
        decayed_novelty=0.08, novelty_minimum=0.3, suppress_threshold=0.15,
    ) is False


def test_no_suppress_on_visual_task() -> None:
    assert suppress_visual_injection(
        referenced=False, is_visual_task=True, raw_novelty=0.05,
        decayed_novelty=0.08, novelty_minimum=0.3, suppress_threshold=0.15,
    ) is False


def test_no_suppress_on_raw_novelty_spike() -> None:
    # a sudden change (raw >= min) injects even if the EMA is still low.
    assert suppress_visual_injection(
        referenced=False, is_visual_task=False, raw_novelty=0.5,
        decayed_novelty=0.08, novelty_minimum=0.3, suppress_threshold=0.15,
    ) is False


def test_no_suppress_when_decayed_above_threshold() -> None:
    # a still-active scene (decayed >= threshold) keeps injecting.
    assert suppress_visual_injection(
        referenced=False, is_visual_task=False, raw_novelty=0.05,
        decayed_novelty=0.2, novelty_minimum=0.3, suppress_threshold=0.15,
    ) is False


# ---------------------------------------------------------------------------
# OFF (default) — byte-identical; agent ignores _visual_scene
# ---------------------------------------------------------------------------


async def test_off_emits_no_camera_bid_even_with_visual_scene_param() -> None:
    # _runtime=None ⇒ _attention_config() is None ⇒ OFF. Even with a fully
    # populated _visual_scene in params, the agent emits NOTHING (the router
    # would have prepended it in real OFF; the agent side adds nothing).
    agent = make_dm_agent()
    scene, latest = _render_scene("A red mug on the desk.", 0.9)
    obs = _dm_obs(
        captain_msg="What do you see?",
        scene=scene,
        novelty=latest.novelty_score,
        summary=latest.description,
    )
    out = await agent._build_user_message(obs)
    assert _SCENE_MARKER not in out
    assert "[Live camera]" not in out
    assert "A red mug on the desk." not in out


async def test_off_dm_golden_byte_identical() -> None:
    # The AD-1028 DM golden (no _visual_scene in params) MUST stay byte-identical
    # with the AD-1031 gate in place — proof OFF changes nothing.
    expected = (_GOLDEN_DIR / "dm_golden.txt").read_text(encoding="utf-8")
    agent = make_dm_agent()
    actual = await agent._build_user_message(dm_observation())
    assert actual == expected


# ---------------------------------------------------------------------------
# ON — salience gating
# ---------------------------------------------------------------------------


async def test_on_unchanged_scene_nonvisual_question_is_recessive() -> None:
    # novelty 0.1 < 0.3 AND a non-visual question ⇒ RECESSIVE: full block absent,
    # a one-line "live camera" summary present-but-trailing; the answer-relevant
    # Captain content still leads. (Reproduces + fixes #973 over-narration.)
    agent = _make_on_agent()
    scene, latest = _render_scene("A red mug on the desk.", 0.1)
    obs = _dm_obs(
        captain_msg="What is the warp core status?",
        scene=scene,
        novelty=latest.novelty_score,
        summary=latest.description,
    )
    out = await agent._build_user_message(obs)
    assert _SCENE_MARKER not in out          # full scene NOT present
    assert "[Live camera]" in out            # recessive one-liner present
    assert "A red mug on the desk." in out   # summary content present
    assert "warp core" in out                # answer-relevant content present
    # Recessive trails the substantive Captain turn.
    assert out.index("[Live camera]") > out.index("Captain says:")


async def test_on_visual_reference_is_prominent_and_leads() -> None:
    # "what do you see?" ⇒ referenced ⇒ PROMINENT even at low novelty: the full
    # block is present and LEADS the prompt.
    agent = _make_on_agent()
    scene, latest = _render_scene("A red mug on the desk.", 0.1)
    obs = _dm_obs(
        captain_msg="What do you see right now?",
        scene=scene,
        novelty=latest.novelty_score,
        summary=latest.description,
    )
    out = await agent._build_user_message(obs)
    assert _SCENE_MARKER in out
    assert out.startswith(_SCENE_MARKER)  # leads (most-negative zone_floor)
    assert out.index(_SCENE_MARKER) < out.index("Captain says:")
    assert "[Live camera]" not in out  # not the recessive one-liner


async def test_on_materially_changed_frame_is_prominent() -> None:
    # novelty 0.5 ≥ 0.3 ⇒ materially changed ⇒ PROMINENT even for a non-visual
    # question.
    agent = _make_on_agent()
    scene, latest = _render_scene("A blue hat appeared.", 0.5)
    obs = _dm_obs(
        captain_msg="Tell me about the warp core.",
        scene=scene,
        novelty=latest.novelty_score,
        summary=latest.description,
    )
    out = await agent._build_user_message(obs)
    assert _SCENE_MARKER in out
    assert "A blue hat appeared." in out
    assert out.index(_SCENE_MARKER) < out.index("Captain says:")


async def test_on_image_attachment_visual_task_is_prominent() -> None:
    # has_image_attachment ⇒ visual task ⇒ PROMINENT even at low novelty with a
    # non-visual prompt (reference detection runs off captain_message, which has
    # no visual keyword here — only the attachment raises the floor).
    agent = _make_on_agent()
    scene, latest = _render_scene("A document on the desk.", 0.1)
    obs = _dm_obs(
        captain_msg="Summarize this.",
        scene=scene,
        novelty=latest.novelty_score,
        summary=latest.description,
        has_image=True,
    )
    out = await agent._build_user_message(obs)
    assert _SCENE_MARKER in out
    assert "A document on the desk." in out


async def test_on_empty_wm_sentinel_always_present() -> None:
    # Empty WM ⇒ no _visual_summary ⇒ the BF-294 confabulation sentinel must
    # ALWAYS show (prominent), even for a non-visual question at zero novelty.
    agent = _make_on_agent()
    scene = _empty_scene()
    obs = _dm_obs(
        captain_msg="What is the warp core status?",
        scene=scene,
        novelty=0.0,
        summary="",
    )
    out = await agent._build_user_message(obs)
    assert _SENTINEL_A in out
    assert _SENTINEL_B in out


async def test_on_no_visual_scene_param_emits_nothing() -> None:
    # ON but the router passed no _visual_scene (perception off / empty render)
    # ⇒ emits NOTHING (no crash, no fabricated block).
    agent = _make_on_agent()
    obs = {
        "intent": "direct_message",
        "params": {
            "text": "What do you see?",
            "captain_message": "What do you see?",
        },
    }
    out = await agent._build_user_message(obs)
    assert _SCENE_MARKER not in out
    assert "[Live camera]" not in out


# ---------------------------------------------------------------------------
# BF-632 — recall query unaffected
# ---------------------------------------------------------------------------


def test_recall_query_unaffected_by_visual_params() -> None:
    # _dm_recall_query must still return the RAW Captain message even when text
    # is polluted and the visual params are present.
    params = {
        "captain_message": "Where are my dogs?",
        "text": f"{_SCENE_MARKER}\nA dog by the door.\n\nWhere are my dogs?",
        "_visual_scene": f"{_SCENE_MARKER}\nA dog by the door.",
        "_visual_novelty": 0.9,
        "_visual_summary": "A dog by the door.",
    }
    assert _dm_recall_query(params) == "Where are my dogs?"
