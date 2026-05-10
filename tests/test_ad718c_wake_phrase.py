"""AD-718c — Per-agent wake phrase tests.

Boundary tests for the `wake_phrase` field on `VoiceProfile`, the parser
allow-list extension in `voice/proposal.py`, and the PUT round-trip via
`SetVoiceProfileRequest`.
"""

from __future__ import annotations

import json

import pytest

from probos.crew_profile import VoiceProfile
from probos.voice.proposal import VoiceProposalError, parse_voice_proposal
from probos.api_models import SetVoiceProfileRequest


# ── E1: VoiceProfile dataclass field round-trip ─────────────────────


def test_voice_profile_wake_phrase_roundtrip() -> None:
    """1. `VoiceProfile(wake_phrase=...)` round-trips through to/from dict."""
    vp = VoiceProfile(wake_phrase="Hey Ezri")
    assert vp.wake_phrase == "Hey Ezri"
    d = vp.to_dict()
    assert d["wake_phrase"] == "Hey Ezri"
    restored = VoiceProfile.from_dict(d)
    assert restored.wake_phrase == "Hey Ezri"


def test_voice_profile_wake_phrase_strips_whitespace() -> None:
    """2. `__post_init__` strips whitespace so " Ezri " → "Ezri"."""
    vp = VoiceProfile(wake_phrase="  Ezri  ")
    assert vp.wake_phrase == "Ezri"


def test_voice_profile_wake_phrase_length_bound() -> None:
    """3. wake_phrase > 50 chars raises ValueError."""
    with pytest.raises(ValueError, match=r"wake_phrase must be"):
        VoiceProfile(wake_phrase="x" * 51)


def test_voice_profile_wake_phrase_rejects_anchor_tokens() -> None:
    """4. wake_phrase containing &/!!/* is rejected (defense in depth)."""
    with pytest.raises(ValueError, match=r"YAML anchor"):
        VoiceProfile(wake_phrase="bad &anchor")
    with pytest.raises(ValueError, match=r"YAML anchor"):
        VoiceProfile(wake_phrase="bad !!tag")
    with pytest.raises(ValueError, match=r"YAML anchor"):
        VoiceProfile(wake_phrase="bad *alias")


# ── E2: parser allow-list extension ─────────────────────────────────


def test_parser_accepts_wake_phrase() -> None:
    """5. parse_voice_proposal accepts and forwards wake_phrase."""
    payload = json.dumps({
        "voice_name": "",
        "pitch": 1.0,
        "rate": 1.0,
        "volume": 0.8,
        "wake_phrase": "Ezri",
        "rationale": "warm",
    })
    profile, rationale = parse_voice_proposal(payload)
    assert profile.wake_phrase == "Ezri"
    assert rationale == "warm"


def test_parser_rejects_oversized_wake_phrase() -> None:
    """6. parser delegates the length bound to VoiceProfile.__post_init__."""
    payload = json.dumps({
        "voice_name": "",
        "pitch": 1.0,
        "rate": 1.0,
        "volume": 0.8,
        "wake_phrase": "x" * 51,
        "rationale": "warm",
    })
    with pytest.raises(VoiceProposalError) as exc_info:
        parse_voice_proposal(payload)
    assert exc_info.value.reason == "schema_violation"


# ── E4: SetVoiceProfileRequest carries the field ────────────────────


def test_set_voice_profile_request_round_trip() -> None:
    """7. PUT request body parses wake_phrase and defaults to "" when absent."""
    req = SetVoiceProfileRequest(
        voice_name="",
        pitch=1.0,
        rate=1.0,
        volume=0.8,
        wake_phrase="Ezri",
    )
    assert req.wake_phrase == "Ezri"
    # Default when omitted.
    req2 = SetVoiceProfileRequest()
    assert req2.wake_phrase == ""


def test_voice_profile_omits_wake_phrase_default_empty() -> None:
    """Edge: existing `from_dict` data without wake_phrase still round-trips."""
    vp = VoiceProfile.from_dict({
        "voice_name": "",
        "pitch": 0.9,
        "rate": 0.95,
        "volume": 0.8,
    })
    assert vp.wake_phrase == ""
