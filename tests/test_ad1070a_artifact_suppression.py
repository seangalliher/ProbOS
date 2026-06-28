"""AD-1070a: suppress the AD-1064 ``<artifact>`` reply-tag teaching when the
conversational agentic loop (AD-1065) will handle the turn.

The Captain asked Ezri for a Word document; with ``dm_agentic`` OFF she fell back
to the AD-1064 ``<artifact name="...docx" mime="...wordprocessingml...">`` tag
wrapping *Markdown* — a markdown body mislabeled with a binary mime, not a real
.docx. When the loop IS active it offers ``run_python`` (AD-1066) which produces a
real document via python-docx, so teaching the competing reply-tag is wrong. The
gate ``_conversational_agentic_will_run`` is the single source of truth for "will
the loop handle this turn?", used both to dispatch the loop and to suppress the
reply-tag teaching.
"""

from __future__ import annotations

from types import SimpleNamespace

from probos.cognitive.cognitive_agent import CognitiveAgent


def _will_run(
    *, enabled: bool, intent: str = "direct_message",
    params: dict | None = None, runtime_present: bool = True,
) -> bool:
    rt = (
        SimpleNamespace(config=SimpleNamespace(dm_agentic=SimpleNamespace(enabled=enabled)))
        if runtime_present else None
    )
    obs = {"intent": intent, "params": params or {}}
    return CognitiveAgent._conversational_agentic_will_run(SimpleNamespace(_runtime=rt), obs)


# ── the gate helper ────────────────────────────────────────────────────────
def test_will_run_true_for_enabled_1to1_dm() -> None:
    assert _will_run(enabled=True) is True


def test_will_run_false_when_flag_off() -> None:
    assert _will_run(enabled=False) is False


def test_will_run_false_when_no_runtime() -> None:
    assert _will_run(enabled=True, runtime_present=False) is False


def test_will_run_false_for_group_chat() -> None:
    assert _will_run(enabled=True, params={"is_group_chat": True}) is False


def test_will_run_false_for_vision_turn() -> None:
    assert _will_run(enabled=True, params={"vision_messages": [{"type": "image"}]}) is False


def test_will_run_false_for_non_dm_intent() -> None:
    assert _will_run(enabled=True, intent="proactive_think") is False


# ── the suppression wiring (mirrors the _decide_via_llm conditional) ───────
def _self(*, enabled: bool):
    return SimpleNamespace(
        _runtime=SimpleNamespace(
            artifact_store=object(),
            attachment_store=object(),
            config=SimpleNamespace(dm_agentic=SimpleNamespace(enabled=enabled)),
        )
    )


def _compose_artifact(fake_self, obs) -> str:
    """Replicate the AD-1070a conditional in _decide_via_llm: teach the artifact
    reply-tag ONLY when the agentic loop will NOT handle this turn."""
    block = CognitiveAgent._conversational_artifact_block(fake_self, obs)
    composed = ""
    if block and not CognitiveAgent._conversational_agentic_will_run(fake_self, obs):
        composed += block
    return composed


def test_artifact_tag_suppressed_when_loop_will_run() -> None:
    fake_self = _self(enabled=True)
    obs = {"intent": "direct_message", "params": {}}
    # The hook itself still renders (stores are wired) ...
    assert CognitiveAgent._conversational_artifact_block(fake_self, obs) != ""
    # ... but it is NOT taught, because run_python will handle the document.
    assert _compose_artifact(fake_self, obs) == ""


def test_artifact_tag_taught_when_loop_off() -> None:
    fake_self = _self(enabled=False)
    obs = {"intent": "direct_message", "params": {}}
    taught = _compose_artifact(fake_self, obs)
    assert "<artifact" in taught  # single-pass path keeps the AD-1064 teaching


def test_artifact_tag_taught_in_group_even_when_flag_on() -> None:
    # The loop is 1:1 only; a group turn still uses the single-pass reply-tag path.
    fake_self = _self(enabled=True)
    obs = {"intent": "direct_message", "params": {"is_group_chat": True}}
    assert "<artifact" in _compose_artifact(fake_self, obs)
