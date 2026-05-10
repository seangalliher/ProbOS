"""AD-718a D7: hardened parser boundary + safety tests for voice proposals."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from probos.crew_profile import VoiceProfile
from probos.voice.proposal import (
    VoiceProposalError,
    parse_voice_proposal,
)


def _good_payload() -> dict:
    return {
        "voice_name": "Aria",
        "pitch": 1.05,
        "rate": 0.92,
        "volume": 0.85,
        "rationale": "warm, calm cadence",
    }


def test_happy_path_returns_profile_and_rationale() -> None:
    text = json.dumps(_good_payload())
    profile, rationale = parse_voice_proposal(text)
    assert isinstance(profile, VoiceProfile)
    assert profile.voice_name == "Aria"
    assert profile.pitch == 1.05
    assert profile.rate == 0.92
    assert profile.volume == 0.85
    assert rationale == "warm, calm cadence"


def test_happy_path_with_markdown_fence() -> None:
    text = "```json\n" + json.dumps(_good_payload()) + "\n```"
    profile, rationale = parse_voice_proposal(text)
    assert isinstance(profile, VoiceProfile)
    assert rationale == "warm, calm cadence"


def test_oversized_response_rejected() -> None:
    payload = "x" * (16 * 1024 + 1)
    with pytest.raises(VoiceProposalError) as exc_info:
        parse_voice_proposal(payload)
    assert exc_info.value.reason == "response_oversized"


def test_yaml_anchor_rejected() -> None:
    text = '{"pitch": &anchor 1.0}'
    with pytest.raises(VoiceProposalError) as exc_info:
        parse_voice_proposal(text)
    assert exc_info.value.reason == "yaml_anchor_or_alias"


def test_yaml_alias_rejected() -> None:
    text = '{"pitch": *alias}'
    with pytest.raises(VoiceProposalError) as exc_info:
        parse_voice_proposal(text)
    assert exc_info.value.reason == "yaml_anchor_or_alias"


def test_yaml_tag_rejected() -> None:
    text = '{"pitch": !!python/object 1.0}'
    with pytest.raises(VoiceProposalError) as exc_info:
        parse_voice_proposal(text)
    assert exc_info.value.reason == "yaml_anchor_or_alias"


def test_deep_nesting_rejected() -> None:
    nested: object = "leaf"
    for _ in range(10):
        nested = {"k": nested}
    text = json.dumps(nested)
    with pytest.raises(VoiceProposalError) as exc_info:
        parse_voice_proposal(text)
    assert exc_info.value.reason == "depth_exceeded"


def test_pitch_out_of_bounds_rejected() -> None:
    payload = _good_payload() | {"pitch": 3.0}
    with pytest.raises(VoiceProposalError) as exc_info:
        parse_voice_proposal(json.dumps(payload))
    assert exc_info.value.reason == "schema_violation"


def test_rate_out_of_bounds_rejected() -> None:
    payload = _good_payload() | {"rate": 11.0}
    with pytest.raises(VoiceProposalError) as exc_info:
        parse_voice_proposal(json.dumps(payload))
    assert exc_info.value.reason == "schema_violation"


def test_volume_out_of_bounds_rejected() -> None:
    payload = _good_payload() | {"volume": 1.5}
    with pytest.raises(VoiceProposalError) as exc_info:
        parse_voice_proposal(json.dumps(payload))
    assert exc_info.value.reason == "schema_violation"


def test_unknown_key_rejected() -> None:
    payload = _good_payload() | {"hostile": True}
    with pytest.raises(VoiceProposalError) as exc_info:
        parse_voice_proposal(json.dumps(payload))
    assert exc_info.value.reason == "unknown_key"


def test_missing_optional_keys_use_defaults() -> None:
    text = json.dumps({"rationale": "minimal"})
    profile, rationale = parse_voice_proposal(text)
    # VoiceProfile defaults: pitch=0.9, rate=0.95, volume=0.8, voice_name="".
    assert profile == VoiceProfile()
    assert rationale == "minimal"


def test_empty_object_succeeds_with_defaults() -> None:
    profile, rationale = parse_voice_proposal("{}")
    assert profile == VoiceProfile()
    assert rationale == ""


def test_top_level_non_dict_rejected() -> None:
    with pytest.raises(VoiceProposalError) as exc_info:
        parse_voice_proposal("[1, 2, 3]")
    assert exc_info.value.reason == "parse_error"


def test_rationale_truncated_to_500_chars() -> None:
    long_rationale = "x" * 800
    text = json.dumps({"rationale": long_rationale})
    _, rationale = parse_voice_proposal(text)
    assert len(rationale) == 500


def test_rationale_must_be_string() -> None:
    text = json.dumps({"rationale": 42})
    with pytest.raises(VoiceProposalError) as exc_info:
        parse_voice_proposal(text)
    assert exc_info.value.reason == "schema_violation"


def test_no_eval_or_exec_in_module() -> None:
    """Defense-in-depth: parser module must not call exec/eval/compile/pickle."""
    src = Path("src/probos/voice/proposal.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden = {"exec", "eval", "compile"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in forbidden:
                raise AssertionError(
                    f"Forbidden builtin {func.id} called in proposal.py"
                )
            if isinstance(func, ast.Attribute) and func.attr in {"loads"}:
                # Catch pickle.loads / marshal.loads style sinks.
                value = func.value
                if isinstance(value, ast.Name) and value.id in {"pickle", "marshal"}:
                    raise AssertionError(
                        f"Forbidden sink {value.id}.{func.attr} in proposal.py"
                    )
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"pickle", "marshal"}:
                    raise AssertionError(
                        f"Forbidden import {alias.name} in proposal.py"
                    )
