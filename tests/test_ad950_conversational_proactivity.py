"""AD-950 (Natural Conversation epic #882, issue #886): conversational
proactivity hook.

Teaches the discourse OBLIGATION to advance a live conversation: on the
1:1/group ``direct_message`` reply path, an engaged turn ends with ONE forward
move (a genuine follow-up question or proposal), calibrated to engagement +
personality (NOT every turn), grounded in what was actually said (never invent).
Group chats additionally permit handing the floor to a peer by name. Default ON
via ``CommunicationsConfig.proactive_conversation_enabled``; honest-degrade
returns "" when off or off the conversational path.

BF-287 discipline: real ``CommunicationsConfig`` (NOT MagicMock) for the flag
paths; the hook is exercised via the real
``CognitiveAgent._conversational_proactivity_protocol`` bound to a
``SimpleNamespace`` self (the AD-934/935 pattern). Both renderings are audited
against the real ``_CAPABILITY_GAP_RE``.
"""

from types import SimpleNamespace

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.config import CommunicationsConfig

_HOOK = CognitiveAgent._conversational_proactivity_protocol

# A distinctive phrase that appears ONLY in the group-only paragraph, used to
# prove the conditional (present for group, absent for 1:1).
_GROUP_MARKER = "hand the floor"


def _self(*, enabled: bool | None = None):
    """SimpleNamespace self. enabled=None -> no runtime (default-ON path);
    else a real CommunicationsConfig under _runtime.config.communications."""
    if enabled is None:
        return SimpleNamespace()
    comm = CommunicationsConfig(proactive_conversation_enabled=enabled)
    return SimpleNamespace(_runtime=SimpleNamespace(config=SimpleNamespace(communications=comm)))


def _gap_clean(text: str) -> None:
    assert _CAPABILITY_GAP_RE.search(text) is None
    for banned in ("can't", "cannot", "don't have", "unable to", "not able to"):
        assert banned not in text.lower()


def test_inert_on_ward_room_and_proactive():
    """The hook is gated to intent == "direct_message"; ward-room and proactive
    branches (which also reach the append point) get "" even default-ON."""
    assert _HOOK(_self(), {"intent": "ward_room_notification", "params": {}}) == ""
    assert _HOOK(_self(), {"intent": "proactive_think", "params": {}}) == ""


def test_1to1_nonempty_and_gap_safe():
    out = _HOOK(_self(), {"intent": "direct_message", "params": {}})
    assert out  # non-empty
    _gap_clean(out)
    assert _GROUP_MARKER not in out  # 1:1 omits the peer-address paragraph


def test_1to1_teaches_forward_move():
    out = _HOOK(_self(), {"intent": "direct_message", "params": {}})
    assert "forward move" in out
    assert "follow-up" in out.lower()


def test_calibration_language_present():
    """Anti-interrogation calibration must survive any future edit (regression
    guard against AD-950 silently becoming relentless)."""
    out = _HOOK(_self(), {"intent": "direct_message", "params": {}})
    assert "NOT on every turn" in out or "not on every turn" in out.lower()
    assert "personality" in out.lower()


def test_honesty_clause_present():
    """Proactivity must not induce fabricated follow-ups."""
    out = _HOOK(_self(), {"intent": "direct_message", "params": {}})
    assert "never invent" in out.lower()


def test_group_includes_peer_address_and_gap_safe():
    out = _HOOK(_self(), {"intent": "direct_message", "params": {"is_group_chat": True}})
    # universal text AND the group-only paragraph
    assert "forward move" in out
    assert _GROUP_MARKER in out
    assert "callsign" in out.lower()
    _gap_clean(out)


def test_flag_off_returns_empty_for_both():
    off = _self(enabled=False)
    assert _HOOK(off, {"intent": "direct_message", "params": {}}) == ""
    assert _HOOK(off, {"intent": "direct_message", "params": {"is_group_chat": True}}) == ""


def test_default_on_when_config_absent():
    """Bare self (no _runtime) on the 1:1 path -> non-empty (proves the
    getattr(..., True) default-ON)."""
    out = _HOOK(_self(), {"intent": "direct_message", "params": {}})
    assert out


def test_config_default_is_on():
    assert CommunicationsConfig().proactive_conversation_enabled is True
