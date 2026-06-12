"""BF-622: never display internal visual-context scaffolding in a reply.

The AD-978 / AD-733a scene block is prepended to the LLM INPUT so an agent can
describe what it sees. It must NEVER appear in a stored/displayed REPLY — it
leaked once when a degraded LLM proxy echoed its own input prompt back as the
completion. ``strip_visual_context_block`` removes that delimited block before
persist; the group (thread_fanout) and 1:1 (agents.py) reply paths call it,
guarded on the marker so normal replies are untouched.

The highest-value guard here is the round-trip test: the strip regex must match
the EXACT delimiters ``render_for_prompt`` emits (single source of truth), so a
delimiter change can't silently break the strip.
"""
from __future__ import annotations

from probos.perception.working_memory import (
    VisionObservation,
    VisionWorkingMemory,
    strip_visual_context_block,
)


def test_strips_the_real_render_for_prompt_block_roundtrip():
    # The actual scaffolding the agent receives (empty ring -> BF-294 sentinel).
    wm = VisionWorkingMemory()
    scaffolding = wm.render_for_prompt()
    assert "Current Visual Context" in scaffolding  # the guard substring fires
    # A reply that is ONLY the echoed scaffolding strips to empty.
    assert strip_visual_context_block(scaffolding) == ""


def test_strips_block_from_a_populated_ring_render():
    wm = VisionWorkingMemory()
    wm.append(VisionObservation(
        timestamp=1000.0, attachment_ref="sha", description="the Captain at a desk",
        novelty_score=0.9, subject_identity="captain",
    ))
    block = wm.render_for_prompt()
    assert "Current Visual Context" in block
    assert strip_visual_context_block(block) == ""


def test_keeps_prose_strips_only_the_block():
    text = (
        "--- Current Visual Context ---\n"
        "Most recent observation (1s ago):\n  a desk\n"
        "--- End Visual Context ---\n\n"
        "Hello Captain, good to see you."
    )
    out = strip_visual_context_block(text)
    assert out == "Hello Captain, good to see you."
    assert "Visual Context" not in out


def test_normal_reply_without_block_is_unchanged_except_trim():
    text = "Aye, Captain. On it."
    assert strip_visual_context_block(text) == "Aye, Captain. On it."


def test_only_block_strips_to_empty():
    text = (
        "--- Current Visual Context ---\n"
        "Camera not active or no frames described yet. Do NOT describe what you cannot see.\n"
        "--- End Visual Context ---"
    )
    assert strip_visual_context_block(text) == ""


def test_block_in_the_middle_is_removed():
    text = (
        "Before. "
        "--- Current Visual Context ---\nstuff\n--- End Visual Context --- "
        "After."
    )
    out = strip_visual_context_block(text)
    assert "Current Visual Context" not in out
    assert "Before." in out and "After." in out


def test_non_string_returns_empty():
    assert strip_visual_context_block(None) == ""  # type: ignore[arg-type]
    assert strip_visual_context_block("") == ""


def test_apply_sites_guard_substring_matches_render_marker():
    # The thread_fanout / agents.py guard is `"Current Visual Context" in text`.
    # Prove that substring is actually present in the rendered block so the
    # guard fires for both the empty-ring sentinel and a populated render.
    assert "Current Visual Context" in VisionWorkingMemory().render_for_prompt()
