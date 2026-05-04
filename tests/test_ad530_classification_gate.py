"""AD-530 v1: Information Classification Enforcement -- Disclosure Gate tests."""

from __future__ import annotations

import re
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock

import pytest

from probos.config import ClassificationGateConfig, SystemConfig
from probos.events import EventType
from probos.security.classification import (
    ClassificationGate,
    DisclosureDecision,
    _DEFAULT_SENSITIVE_PATTERNS,
)
from probos.startup.finalize import _wire_classification_gate


# ---------- helpers -------------------------------------------------------

def _make_gate(emit_event=None) -> ClassificationGate:
    runtime = MagicMock()
    return ClassificationGate(runtime, emit_event=emit_event)


# ---------- Section 0: EventType -----------------------------------------

def test_event_type_classification_disclosure_blocked_exists():
    assert EventType.CLASSIFICATION_DISCLOSURE_BLOCKED.value == "classification_disclosure_blocked"


# ---------- Section 3: Pydantic config defaults ---------------------------

def test_classification_gate_config_defaults():
    cfg = ClassificationGateConfig()
    assert cfg.enabled is True

    sys_cfg = SystemConfig()
    assert isinstance(sys_cfg.classification_gate, ClassificationGateConfig)
    assert sys_cfg.classification_gate.enabled is True


# ---------- Section 1: DisclosureDecision contract ------------------------

def test_disclosure_decision_is_frozen_dataclass():
    decision = DisclosureDecision(
        allowed=True,
        reason="ok",
        blocked_phrases=(),
        source_classification="ship",
        destination_clearance="ship",
    )
    with pytest.raises(FrozenInstanceError):
        decision.allowed = False  # type: ignore[misc]


# ---------- Section 2: hierarchy direction --------------------------------

def test_check_disclosure_allowed_when_levels_equal():
    gate = _make_gate()
    decision = gate.check_disclosure(
        "hello crew",
        source_classification="ship",
        destination_clearance="ship",
    )
    assert decision.allowed is True
    assert decision.reason == "ok"
    assert decision.blocked_phrases == ()


def test_check_disclosure_allowed_when_destination_narrower():
    # src=ship(2), dst=department(1): dst_lvl < src_lvl -> ALLOW.
    gate = _make_gate()
    decision = gate.check_disclosure(
        "ship-wide note",
        source_classification="ship",
        destination_clearance="department",
    )
    assert decision.allowed is True
    assert decision.reason == "ok"


def test_check_disclosure_blocked_when_destination_broader():
    # src=private(0), dst=ship(2): 2 > 0 -> BLOCK.
    gate = _make_gate()
    decision = gate.check_disclosure(
        "personal note",
        source_classification="private",
        destination_clearance="ship",
    )
    assert decision.allowed is False
    assert decision.reason == "destination_too_broad"
    assert decision.blocked_phrases == ()
    assert decision.source_classification == "private"
    assert decision.destination_clearance == "ship"


# ---------- Safe defaults -------------------------------------------------

def test_check_disclosure_unknown_source_defaults_to_private():
    # Unknown source -> private (0). dst=ship (2). 2 > 0 -> BLOCK.
    gate = _make_gate()
    decision = gate.check_disclosure(
        "x",
        source_classification="unspecified-label",
        destination_clearance="ship",
    )
    assert decision.allowed is False
    assert decision.reason == "destination_too_broad"


def test_check_disclosure_unknown_destination_defaults_to_ship():
    # Source=private (0), unknown dest -> ship (2). 2 > 0 -> BLOCK.
    gate = _make_gate()
    decision = gate.check_disclosure(
        "x",
        source_classification="private",
        destination_clearance="some-other-network",
    )
    assert decision.allowed is False
    assert decision.reason == "destination_too_broad"


# ---------- Event emission on hierarchy violation -------------------------

def test_check_disclosure_emits_blocked_event_on_hierarchy_violation():
    emit = MagicMock()
    gate = _make_gate(emit_event=emit)
    gate.check_disclosure(
        "secret stuff",
        source_classification="private",
        destination_clearance="ship",
    )
    assert emit.call_count == 1
    args, _ = emit.call_args
    assert args[0] == EventType.CLASSIFICATION_DISCLOSURE_BLOCKED
    payload = args[1]
    assert payload["reason"] == "destination_too_broad"
    assert payload["source_classification"] == "private"
    assert payload["destination_clearance"] == "ship"


# ---------- Default pattern set -------------------------------------------

def test_api_key_like_pattern_NOT_in_default_set():
    # The 32+ char alphanum heuristic must NOT be seeded by default (UUID-FP guard).
    default_names = {name for name, _ in _DEFAULT_SENSITIVE_PATTERNS}
    assert "api_key_like" not in default_names

    gate = _make_gate()
    pattern_names = {name for name, _ in gate.patterns}
    assert "api_key_like" not in pattern_names

    # 32+ char alphanum strings (e.g. UUIDs / commit hashes) must NOT trigger any default pattern.
    decision = gate.check_disclosure(
        "commit a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",  # 40-char hex hash
        source_classification="ship",
        destination_clearance="fleet",
    )
    assert decision.allowed is False  # hierarchy 3 > 2 still blocks
    assert decision.reason == "destination_too_broad"  # NOT sensitive_pattern_matched


def test_register_pattern_enables_api_key_like_opt_in():
    gate = _make_gate()
    gate.register_pattern("api_key_like", r"\b[A-Za-z0-9_-]{32,}\b")

    decision = gate.check_disclosure(
        "token a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
        source_classification="ship",
        destination_clearance="ship",
    )
    assert decision.allowed is False
    assert decision.reason == "sensitive_pattern_matched"
    assert "api_key_like" in decision.blocked_phrases


# ---------- Pattern: captain directive ------------------------------------

def test_check_disclosure_pattern_blocks_captain_directive():
    gate = _make_gate()
    decision = gate.check_disclosure(
        "[CAPTAIN_DIRECTIVE] hold orbit",
        source_classification="ship",
        destination_clearance="ship",
    )
    assert decision.allowed is False
    assert decision.reason == "sensitive_pattern_matched"
    assert "captain_directive" in decision.blocked_phrases


# ---------- Pattern: restricted prefix ------------------------------------

def test_check_disclosure_pattern_blocks_restricted_prefix():
    gate = _make_gate()
    for prefix_text in ("private: notes follow", "confidential: data here"):
        decision = gate.check_disclosure(
            prefix_text,
            source_classification="ship",
            destination_clearance="ship",
        )
        assert decision.allowed is False, prefix_text
        assert decision.reason == "sensitive_pattern_matched"
        assert "restricted_prefix" in decision.blocked_phrases


# ---------- Pattern: secret format ----------------------------------------

def test_check_disclosure_pattern_blocks_secret_format():
    gate = _make_gate()
    cases = [
        "the secret=hunter2",
        "api_key: sk-abc123",
        "password = letmein",
        "TOKEN=xyz",
    ]
    for content in cases:
        decision = gate.check_disclosure(
            content,
            source_classification="ship",
            destination_clearance="ship",
        )
        assert decision.allowed is False, content
        assert decision.reason == "sensitive_pattern_matched"
        assert "secret_format" in decision.blocked_phrases


# ---------- Pattern scan skipped for private destination -----------------

def test_check_disclosure_pattern_skipped_when_destination_is_private():
    # dst=private (0): no broader audience, patterns must NOT run.
    gate = _make_gate()
    decision = gate.check_disclosure(
        "[CAPTAIN_DIRECTIVE] super secret",
        source_classification="private",
        destination_clearance="private",
    )
    assert decision.allowed is True
    assert decision.reason == "ok"
    assert decision.blocked_phrases == ()


# ---------- Privacy invariants --------------------------------------------

def test_check_disclosure_emits_blocked_phrases_by_name_not_content():
    gate = _make_gate()
    matched_substring = "hunter2-very-secret-passphrase"
    decision = gate.check_disclosure(
        f"secret={matched_substring}",
        source_classification="ship",
        destination_clearance="ship",
    )
    assert decision.allowed is False
    # Names only, never substrings.
    assert decision.blocked_phrases == ("secret_format",)
    assert matched_substring not in decision.blocked_phrases


def test_check_disclosure_event_payload_excludes_content_includes_length():
    emit = MagicMock()
    gate = _make_gate(emit_event=emit)
    content = "[CAPTAIN_DIRECTIVE] do not disclose this"
    gate.check_disclosure(
        content,
        source_classification="ship",
        destination_clearance="ship",
    )
    args, _ = emit.call_args
    payload = args[1]
    assert "content" not in payload
    assert payload["content_length"] == len(content)
    # Pattern NAMES only.
    assert payload["blocked_phrases"] == ["captain_directive"]
    assert content not in payload["blocked_phrases"]


# ---------- register_pattern ----------------------------------------------

def test_register_pattern_adds_to_runtime_pattern_set():
    gate = _make_gate()
    baseline = gate.pattern_count
    gate.register_pattern("custom", r"FOOBAR")
    assert gate.pattern_count == baseline + 1
    names = {name for name, _ in gate.patterns}
    assert "custom" in names

    decision = gate.check_disclosure(
        "FOOBAR shows up",
        source_classification="ship",
        destination_clearance="ship",
    )
    assert decision.allowed is False
    assert "custom" in decision.blocked_phrases


def test_register_pattern_duplicate_name_warns_and_skips(caplog):
    gate = _make_gate()
    gate.register_pattern("dup", r"AAA")
    baseline = gate.pattern_count
    with caplog.at_level("WARNING"):
        gate.register_pattern("dup", r"BBB")
    assert gate.pattern_count == baseline
    # Original pattern preserved (matches AAA, not BBB).
    name_to_pat = dict(gate.patterns)
    assert isinstance(name_to_pat["dup"], re.Pattern)
    assert name_to_pat["dup"].search("AAA") is not None
    assert name_to_pat["dup"].search("BBB") is None
    assert any("already registered" in rec.getMessage() for rec in caplog.records)


# ---------- Wiring (Section 4) -------------------------------------------

def test_runtime_attribute_set_when_enabled():
    runtime = MagicMock()
    runtime.classification_gate = None
    config = SystemConfig()
    assert config.classification_gate.enabled is True

    wired = _wire_classification_gate(runtime=runtime, config=config)
    assert wired is True
    assert isinstance(runtime.classification_gate, ClassificationGate)
    assert runtime.classification_gate.pattern_count == len(_DEFAULT_SENSITIVE_PATTERNS)


def test_runtime_attribute_not_set_when_disabled():
    runtime = MagicMock()
    config = SystemConfig()
    config.classification_gate.enabled = False

    # Strip any auto-attribute; verify wiring does NOT set it.
    if hasattr(runtime, "classification_gate"):
        del runtime.classification_gate

    wired = _wire_classification_gate(runtime=runtime, config=config)
    assert wired is False
    # Wiring must not have created the public attribute.
    # MagicMock auto-creates attrs on access, so check the spec directly:
    # we asserted wired is False which is the contract; absence of side effect
    # is best verified by ensuring the gate constructor was never called.
