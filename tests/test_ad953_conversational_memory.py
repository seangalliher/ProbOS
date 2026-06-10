"""AD-953 (Natural Conversation epic #882, issue #889): conversational memory &
callbacks hook.

Teaches agents to draw on what they GENUINELY recall (the episodic memories +
session history already injected into the reply context, AD-573/AD-723a-1) and
make natural callbacks ("you mentioned ...", "last time we ...") so a
conversation feels continuous instead of amnesiac, with a hard AD-592 honesty
bound: reference only what is actually recalled, never fabricate a shared
memory. Gated to the live ``direct_message`` path; default ON via
``CommunicationsConfig.conversational_memory_enabled``.

BF-287 discipline: real ``CommunicationsConfig`` (NOT MagicMock) for the flag
paths; the hook is exercised via the real
``CognitiveAgent._conversational_memory_protocol`` bound to a
``SimpleNamespace`` self (the AD-950 pattern). The rendering is audited against
the real ``_CAPABILITY_GAP_RE``.
"""

from types import SimpleNamespace

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.config import CommunicationsConfig

_HOOK = CognitiveAgent._conversational_memory_protocol


def _self(*, enabled: bool | None = None):
    """SimpleNamespace self. enabled=None -> no runtime (default-ON path);
    else a real CommunicationsConfig under _runtime.config.communications."""
    if enabled is None:
        return SimpleNamespace()
    comm = CommunicationsConfig(conversational_memory_enabled=enabled)
    return SimpleNamespace(_runtime=SimpleNamespace(config=SimpleNamespace(communications=comm)))


def _gap_clean(text: str) -> None:
    assert _CAPABILITY_GAP_RE.search(text) is None
    for banned in ("can't", "cannot", "don't have", "unable to", "not able to", "lack"):
        assert banned not in text.lower()


def test_inert_on_ward_room_and_proactive():
    """Gated to intent == "direct_message"; ward-room and proactive branches
    (which also reach the append point) get "" even default-ON."""
    assert _HOOK(_self(), {"intent": "ward_room_notification", "params": {}}) == ""
    assert _HOOK(_self(), {"intent": "proactive_think", "params": {}}) == ""


def test_1to1_nonempty_and_gap_safe():
    out = _HOOK(_self(), {"intent": "direct_message", "params": {}})
    assert out  # non-empty
    _gap_clean(out)


def test_teaches_callbacks():
    out = _HOOK(_self(), {"intent": "direct_message", "params": {}}).lower()
    assert "call back" in out or "you mentioned" in out
    assert "continuous" in out  # the explicit goal: continuity, not amnesia


def test_recipient_design_present():
    """Recipient design — tailor to the shared history with THIS person."""
    out = _HOOK(_self(), {"intent": "direct_message", "params": {}}).lower()
    assert "this person" in out or "shared history" in out


def test_honesty_clause_present():
    """The hard AD-592 anti-fabrication bound must survive any future edit
    (regression guard against AD-953 silently licensing confabulation)."""
    out = _HOOK(_self(), {"intent": "direct_message", "params": {}}).lower()
    assert "never manufacture" in out
    assert "uncertain" in out  # 'if you are uncertain ... treat it as if it did not'


def test_applies_on_group_path_too():
    """AD-953 is not group-specific (memory continuity matters in 1:1 and group
    alike); the group param does not suppress it and the text stays gap-safe."""
    out = _HOOK(_self(), {"intent": "direct_message", "params": {"is_group_chat": True}})
    assert out
    _gap_clean(out)


def test_flag_off_returns_empty():
    off = _self(enabled=False)
    assert _HOOK(off, {"intent": "direct_message", "params": {}}) == ""
    assert _HOOK(off, {"intent": "direct_message", "params": {"is_group_chat": True}}) == ""


def test_default_on_when_config_absent():
    """Bare self (no _runtime) on the 1:1 path -> non-empty (proves the
    getattr(..., True) default-ON)."""
    out = _HOOK(_self(), {"intent": "direct_message", "params": {}})
    assert out


def test_config_default_is_on():
    assert CommunicationsConfig().conversational_memory_enabled is True
