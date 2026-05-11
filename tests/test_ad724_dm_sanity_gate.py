"""AD-724: Tests for the DM sanity gate.

Behavior-preservation tests for migrated regex (BF-120, BF-119, AD-572)
plus new log-only check tests (length floor, repetition, orphaned tags).
"""

from __future__ import annotations

import logging
import re

import pytest

from probos.cognitive.dm_sanity_gate import (
    DmSanityGate,
    DmSanityGateConfig,
)


@pytest.fixture
def gate() -> DmSanityGate:
    return DmSanityGate(DmSanityGateConfig())


# --- Migration behavior preservation (6 tests) ---

def test_strip_markdown_handles_double_asterisks(gate: DmSanityGate) -> None:
    raw = "**[CHALLENGE @ezri tictactoe]**"
    out = gate.strip_markdown(raw)
    assert out == "[CHALLENGE @ezri tictactoe]"
    # Byte-identity with HEAD inline behavior
    legacy = re.sub(r'\][`*]{1,3}', ']', re.sub(r'[`*]{1,3}\[', '[', raw))
    assert out == legacy


def test_strip_markdown_handles_backticks(gate: DmSanityGate) -> None:
    raw = "`[MOVE A1]`"
    out = gate.strip_markdown(raw)
    assert out == "[MOVE A1]"
    legacy = re.sub(r'\][`*]{1,3}', ']', re.sub(r'[`*]{1,3}\[', '[', raw))
    assert out == legacy


def test_strip_markdown_empty_input_returns_empty(gate: DmSanityGate) -> None:
    assert gate.strip_markdown("") == ""


def test_extract_challenge_well_formed(gate: DmSanityGate) -> None:
    text = "Hey, [CHALLENGE @ezri tictactoe] right now?"
    assert gate.extract_challenge(text) == ("ezri", "tictactoe")


def test_extract_challenge_returns_none_when_absent(gate: DmSanityGate) -> None:
    assert gate.extract_challenge("Just a normal reply.") is None


def test_extract_move_well_formed_and_strip(gate: DmSanityGate) -> None:
    text = "Playing [MOVE B2] now."
    assert gate.extract_move(text) == "B2"
    legacy = re.sub(r'\[MOVE\s+\S+\]', '', text).strip()
    assert gate.strip_move(text) == legacy


# --- New length-floor check (2 tests) ---

def test_length_floor_logs_when_too_short(
    gate: DmSanityGate, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.dm_sanity_gate"):
        result = gate.check_length_floor("agent-1", "hi")
    assert result is not None
    assert result[0] == "length_floor"
    assert any("length floor breached" in r.message for r in caplog.records)


def test_length_floor_silent_above_threshold(
    gate: DmSanityGate, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.dm_sanity_gate"):
        result = gate.check_length_floor("agent-1", "a normal reply")
    assert result is None
    assert caplog.records == []


# --- New repetition check (3 tests) ---

def test_repetition_first_reply_is_not_flagged(gate: DmSanityGate) -> None:
    result = gate.process("a-1", "Hello Captain.")
    assert all(w[0] != "repetition" for w in result.warnings)


def test_repetition_identical_prefix_flagged(gate: DmSanityGate) -> None:
    gate.process("a-1", "Hello Captain, I am ready to assist.")
    result = gate.process("a-1", "Hello Captain, I am ready to assist.")
    rep = [w for w in result.warnings if w[0] == "repetition"]
    assert rep, "expected a repetition warning on second identical reply"
    assert "decoder loop" in rep[0][1]


def test_repetition_state_is_per_agent(gate: DmSanityGate) -> None:
    gate.process("a-1", "Hello Captain, identical message text here.")
    result = gate.process("a-2", "Hello Captain, identical message text here.")
    assert all(w[0] != "repetition" for w in result.warnings)


# --- New orphaned-tag check (2 tests) ---

def test_orphaned_challenge_flagged(gate: DmSanityGate) -> None:
    result = gate.check_orphaned_tags("Hey [CHALLENGE @ezri")
    assert result is not None
    assert result[0] == "orphaned_tag"
    assert "CHALLENGE" in result[1]
    # Well-formed tag is NOT flagged
    assert gate.check_orphaned_tags("[CHALLENGE @ezri tictactoe]") is None


def test_empty_brackets_flagged(gate: DmSanityGate) -> None:
    result = gate.check_orphaned_tags("Result: []")
    assert result == ("orphaned_tag", "empty []")


# --- Orchestration end-to-end (1 test) ---

def test_process_disabled_config_still_strips_markdown_but_skips_checks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gate = DmSanityGate(DmSanityGateConfig(enabled=False))
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.dm_sanity_gate"):
        result = gate.process("a-1", "**[CHALLENGE @x y]**")
    assert result.cleaned_text == "[CHALLENGE @x y]"
    assert result.warnings == []
