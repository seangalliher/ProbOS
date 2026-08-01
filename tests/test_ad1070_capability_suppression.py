"""AD-1070: retire the scattered single-pass reply-tag teaching in favor of ONE
loop-native self-description, injected only when the conversational agentic loop
(AD-1065) will handle the turn.

Two teaching-side changes (mirrors ``test_ad1070a_artifact_suppression.py``):

1. The AD-983a ``_conversational_capability_block`` (the AD-869 ``[MESH ...]``
   read-only seam) is SUPPRESSED when the loop will run -- its ``run_python`` /
   ``search_capabilities`` tools supersede the read teaching.
2. A new ``_conversational_agentic_self_description`` block unifies the per-tag
   grounding into ONE affirmative block that appears ONLY when the loop runs
   (AD-1070 taught a fixed four-tool list; AD-1177 replaced that enumeration
   with deference to the model's tool array -- see test_ad1177_crew_agency.py).

Default-OFF guarantee (load-bearing): with ``dm_agentic.enabled=False`` (the
default) the gate ``_conversational_agentic_will_run`` returns False, so the new
``and not ...`` is a no-op (capability block still renders) AND the
self-description returns "" -> the composed prompt is BYTE-IDENTICAL to HEAD.

BF-287: real config at the boundary -- a real ``SystemConfig`` with
``dm_agentic.enabled`` toggled, plus real registry / descriptor objects (never
MagicMock, which auto-creates phantom attributes). Follows the AD-912 / AD-1065 /
AD-1070a unbound-method-with-``SimpleNamespace``-self pattern; the real
``capability_affordances`` method is bound so the full affordance -> capability
block render chain is exercised.
"""

from __future__ import annotations

import types
from types import SimpleNamespace

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.config import DmAgenticConfig, SystemConfig


# ── real fixtures (BF-287: real SystemConfig, real registry objects) ────────
def _descriptor(name: str, hint: str) -> SimpleNamespace:
    """A real intent descriptor carrying a read-only [MESH ...] usage hint."""
    return SimpleNamespace(name=name, usage_hint=hint)


def _registry_with_reads() -> SimpleNamespace:
    """A live registry whose single agent declares read-only [MESH ...] hints,
    so ``capability_affordances`` returns a non-empty map and the AD-983a
    capability block renders (real objects, not MagicMock)."""
    agent = SimpleNamespace(
        intent_descriptors=[
            _descriptor("web_search", "[MESH web_search query=<terms>]"),
            _descriptor("read_file", "[MESH read_file path=<path>]"),
        ]
    )
    return SimpleNamespace(all=lambda: [agent])


def _self(
    *, enabled: bool, registry: SimpleNamespace | None = None,
) -> SimpleNamespace:
    """Unbound-method-with-``SimpleNamespace``-self self, with a REAL
    ``SystemConfig`` at the config boundary (dm_agentic toggled, BF-287). The
    real ``capability_affordances`` is bound so the capability block renders off
    the live registry rather than a stub."""
    runtime = SimpleNamespace(
        registry=registry if registry is not None else _registry_with_reads(),
        config=SystemConfig(dm_agentic=DmAgenticConfig(enabled=enabled)),
        artifact_store=object(),
        attachment_store=object(),
    )
    fake = SimpleNamespace(_runtime=runtime)
    fake.capability_affordances = types.MethodType(
        CognitiveAgent.capability_affordances, fake
    )
    # _conversational_agentic_self_description calls self._conversational_agentic_will_run
    # internally, so bind the real gate too (real methods on a real-config self).
    fake._conversational_agentic_will_run = types.MethodType(
        CognitiveAgent._conversational_agentic_will_run, fake
    )
    return fake


def _obs(*, intent: str = "direct_message", params: dict | None = None) -> dict:
    return {"intent": intent, "params": params or {}}


def _cap_block(fake_self: SimpleNamespace, obs: dict) -> str:
    return CognitiveAgent._conversational_capability_block(fake_self, obs)


def _self_desc(fake_self: SimpleNamespace, obs: dict) -> str:
    return CognitiveAgent._conversational_agentic_self_description(fake_self, obs)


def _will_run(fake_self: SimpleNamespace, obs: dict) -> bool:
    return CognitiveAgent._conversational_agentic_will_run(fake_self, obs)


def _compose_capability(fake_self: SimpleNamespace, obs: dict) -> str:
    """Replicate the AD-1070 assembly conditional in ``_decide_via_llm``: teach
    the [MESH] capability block ONLY when the agentic loop will NOT run."""
    block = _cap_block(fake_self, obs)
    composed = ""
    if block and not _will_run(fake_self, obs):
        composed += block
    return composed


# ── gate anchor (real SystemConfig boundary) ───────────────────────────────
def test_will_run_true_for_enabled_1to1_dm() -> None:
    assert _will_run(_self(enabled=True), _obs()) is True


def test_will_run_false_when_flag_off() -> None:
    assert _will_run(_self(enabled=False), _obs()) is False


# ── (a) capability block SUPPRESSED when the loop will run ──────────────────
def test_capability_block_suppressed_when_loop_will_run() -> None:
    fake_self = _self(enabled=True)
    obs = _obs()
    # The hook itself still renders (live reads are reachable) ...
    assert _cap_block(fake_self, obs) != ""
    # ... but it is NOT taught: search_capabilities / run_python supersede it.
    assert _compose_capability(fake_self, obs) == ""


# ── (b) capability block STILL RENDERS when the loop will NOT run ───────────
def test_capability_block_taught_when_flag_off() -> None:
    fake_self = _self(enabled=False)
    obs = _obs()
    taught = _compose_capability(fake_self, obs)
    assert "[MESH" in taught  # single-pass path keeps the AD-869 read teaching


def test_capability_block_taught_in_group_even_when_flag_on() -> None:
    # The loop is 1:1 only; a group turn keeps the single-pass read teaching.
    fake_self = _self(enabled=True)
    obs = _obs(params={"is_group_chat": True})
    assert "[MESH" in _compose_capability(fake_self, obs)


def test_capability_block_taught_for_vision_even_when_flag_on() -> None:
    # Vision turns are single-pass; the read teaching stays.
    fake_self = _self(enabled=True)
    obs = _obs(params={"vision_messages": [{"type": "image"}]})
    assert "[MESH" in _compose_capability(fake_self, obs)


# ── (c) unified self-description: "" when off, teaches the loop when on ─────
def test_self_description_empty_when_loop_off() -> None:
    assert _self_desc(_self(enabled=False), _obs()) == ""


def test_self_description_empty_in_group_even_when_flag_on() -> None:
    fake_self = _self(enabled=True)
    assert _self_desc(fake_self, _obs(params={"is_group_chat": True})) == ""


def test_self_description_empty_for_vision_even_when_flag_on() -> None:
    fake_self = _self(enabled=True)
    assert _self_desc(fake_self, _obs(params={"vision_messages": [{"type": "image"}]})) == ""


def test_self_description_teaches_loop_native_tools_when_loop_will_run() -> None:
    # AD-1177: the block no longer enumerates a fixed tool subset -- AD-1070's
    # four-name list drifted as the assembly grew to eleven groups, so the prose
    # now defers to the model's tool array. ``run_python`` and
    # ``search_capabilities`` stay named because each is an *act* the model must
    # know to perform. The full drift guard lives in test_ad1177_crew_agency.py.
    fake_self = _self(enabled=True)
    desc = _self_desc(fake_self, _obs())
    assert desc != ""
    for tool in ("run_python", "search_capabilities"):
        assert tool in desc
    assert "authoritative list of what you hold" in desc


# ── (d) self-description text is gap-regex clean (AD-957 / AD-596) ──────────
def test_self_description_is_capability_gap_clean() -> None:
    fake_self = _self(enabled=True)
    desc = _self_desc(fake_self, _obs())
    assert desc != ""
    assert _CAPABILITY_GAP_RE.search(desc) is None


# ── byte-identical-when-off guarantee (the load-bearing gate) ──────────────
def test_byte_identical_when_off_capability_kept_and_self_desc_empty() -> None:
    """Default-OFF: with dm_agentic OFF the new ``and not ...`` gate is a no-op
    (capability block appended exactly as before) AND the self-description adds
    "" -> the teaching-side output equals pre-AD-1070 HEAD (capability block
    only)."""
    fake_self = _self(enabled=False)
    obs = _obs()
    # Capability block is appended exactly as before (gate is a no-op) ...
    assert _compose_capability(fake_self, obs) == _cap_block(fake_self, obs)
    assert _cap_block(fake_self, obs) != ""
    # ... and the unified self-description contributes nothing.
    assert _self_desc(fake_self, obs) == ""
