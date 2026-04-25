# BF-210: Ward Room DM Recipient Never Wired — Build Prompt

**BF:** 210  
**Issue:** #295  
**Related:** AD-649 (Communication Context), AD-650 (Analytical Depth), BF-184 (Social Obligation Flags)  
**Scope:** ~15 lines across 2 files. Zero new modules.

---

## Problem

`_dm_recipient` context field is never populated anywhere in the codebase. In `compose.py` line 154, it defaults to `"the Captain"` for ALL DMs — including crew-to-crew conversations.

**Consequence 1 — Formal register override:** When Keiko (Pharmacist) DMs Chapel (Medical Chief), the compose prompt tells Keiko "You are in a 1:1 private conversation with the Captain." This triggers authority-aware formality, overriding the "warm, conversational" guidance from the `private_conversation` communication context.

**Consequence 2 — Confabulation pressure:** The "Captain" frame pushes agents to demonstrate broad competence. Keiko invents "prescription database", "treatment matrix", and "pharmaceutical protocols" — none of which exist in her ontology. Her actual capability is a single `medical_tune` function.

---

## What Already Exists

- `author_callsign` is available in Ward Room params (`ward_room_router.py` L.514): `data.get("author_callsign", "")`
- `_is_dm` flag is set in `cognitive_agent.py` L.1825: `observation["_is_dm"] = _params.get("is_dm_channel", False)`
- `_communication_context` is set to `"private_conversation"` for DMs (`cognitive_agent.py` L.1830-1831)
- `_build_ward_room_compose_prompt()` handles ALL Ward Room DMs (compose.py L.65-131). The `private_conversation` branch (L.86-94) says "You are in a private 1:1 conversation" but does NOT name the conversation partner.
- `_build_dm_compose_prompt()` (compose.py L.138-177) reads `context.get("_dm_recipient", "the Captain")` on L.154 but is NEVER called for Ward Room DMs — only `_build_ward_room_compose_prompt()` is used (mode is always `ward_room_response`).
- `_params` dict is already extracted at L.1822: `_params = observation.get("params", {})`
- `_is_dm_channel` is already extracted at L.1829

---

## Fix

Two files. No new modules, no new dependencies.

### Part A: Wire `_dm_recipient` in cognitive_agent.py

In `_execute_chain_with_intent_routing()`, after line 1825 (`observation["_is_dm"] = ...`), add:

```python
# BF-210: Wire DM conversation partner for compose register adaptation
if observation["_is_dm"]:
    observation["_dm_recipient"] = _params.get("author_callsign", "")
```

**Note:** `author_callsign` is the SENDER of the message that triggered this agent. In a DM, the sender IS the conversation partner (the person you're replying to). This is the correct field.

### Part B: Use `_dm_recipient` in compose.py Ward Room private_conversation branch

In `_build_ward_room_compose_prompt()`, find the `private_conversation` branch (line 86-94). Replace:

```python
    if _comm_context == "private_conversation":
        system_prompt += (
            "\n\nYou are in a private 1:1 conversation. "
            "Be warm, conversational, and personal — like talking to a trusted colleague. "
            "Speak in your natural voice. Share your thoughts naturally, not as a report. "
            "Show your reasoning, ask follow-up questions, and draw on "
            "recent interactions and shared context. "
            "Do NOT use structured formats, bold headers, or clinical language."
        )
```

With:

```python
    if _comm_context == "private_conversation":
        # BF-210: Name the conversation partner so the model
        # doesn't default to authority-frame formality.
        _dm_peer = context.get("_dm_recipient", "")
        _peer_label = f" with {_dm_peer}" if _dm_peer else ""
        system_prompt += (
            f"\n\nYou are in a private 1:1 conversation{_peer_label}. "
            "Be warm, conversational, and personal — like talking to a trusted colleague. "
            "Speak in your natural voice. Share your thoughts naturally, not as a report. "
            "Show your reasoning, ask follow-up questions, and draw on "
            "recent interactions and shared context. "
            "If there's another way to see this, mention it briefly. "
            "Don't just summarize — interpret. "
            "Do NOT use structured formats, bold headers, or clinical language."
        )
```

**Changes from original:**
1. Inserts conversation partner name (e.g., "with Chapel") when available
2. Graceful fallback: empty string if `_dm_recipient` not set (backward compat)
3. Adds AD-650 depth instructions ("another way to see this", "interpret") — the private_conversation branch was missing these while the general Ward Room branch already has them

### Part C: Fix `_build_dm_compose_prompt()` default (compose.py L.154)

Change the default from `"the Captain"` to empty string for consistency:

```python
# Before:
_recipient = context.get("_dm_recipient", "the Captain")

# After:
_recipient = context.get("_dm_recipient", "a crew member")
```

This ensures if `_build_dm_compose_prompt()` is ever called without `_dm_recipient` wired (e.g., future direct_message chain path), the default is neutral rather than authority-framing.

**Regression fix:** Update `tests/test_ad649_communication_context.py` line 218 to match the new default:

```python
# Before:
assert "private conversation with the Captain" in system_prompt

# After:
assert "private conversation with a crew member" in system_prompt
```

---

## Verification Checklist

1. [ ] `_dm_recipient` is set in `cognitive_agent.py` when `_is_dm` is True
2. [ ] `_dm_recipient` is extracted from `_params.get("author_callsign", "")`
3. [ ] `_build_ward_room_compose_prompt()` private_conversation branch names the conversation partner
4. [ ] Graceful fallback when `_dm_recipient` is empty (no crash, no "with ")
5. [ ] `_build_dm_compose_prompt()` default changed from `"the Captain"` to `"a crew member"`
6. [ ] AD-650 depth instructions added to private_conversation branch
7. [ ] AD-649 test `test_defaults_to_captain` updated to expect `"a crew member"` instead of `"the Captain"`
8. [ ] All existing tests pass (`pytest tests/ -x -q`)
8. [ ] No imports changed, no new modules, no new dependencies

---

## Tests (tests/test_bf210_dm_recipient.py)

```python
"""BF-210: Ward Room DM recipient wiring tests."""
import pytest
from probos.cognitive.sub_tasks.compose import (
    _build_ward_room_compose_prompt,
    _build_dm_compose_prompt,
)


class TestDMRecipientWiring:
    """Verify DM recipient is used in compose prompts."""

    def test_ward_room_private_conversation_names_peer(self):
        """Private conversation branch includes the conversation partner's name."""
        ctx = {
            "context": "test",
            "mode": "ward_room_response",
            "channel_name": "dm-chapel",
            "_communication_context": "private_conversation",
            "_dm_recipient": "Chapel",
        }
        system, _ = _build_ward_room_compose_prompt(ctx, [], "Keiko", "medical")
        assert "Chapel" in system
        assert "private" in system.lower()

    def test_ward_room_private_conversation_graceful_without_recipient(self):
        """Private conversation branch works without _dm_recipient."""
        ctx = {
            "context": "test",
            "mode": "ward_room_response",
            "channel_name": "dm-chapel",
            "_communication_context": "private_conversation",
            # No _dm_recipient set
        }
        system, _ = _build_ward_room_compose_prompt(ctx, [], "Keiko", "medical")
        assert "private" in system.lower()
        assert "with " not in system.split("conversation")[1][:5]  # No "with " before period

    def test_ward_room_private_conversation_no_captain_default(self):
        """Private conversation branch does NOT default to 'the Captain'."""
        ctx = {
            "context": "test",
            "mode": "ward_room_response",
            "channel_name": "dm-chapel",
            "_communication_context": "private_conversation",
            # No _dm_recipient — should NOT say "the Captain"
        }
        system, _ = _build_ward_room_compose_prompt(ctx, [], "Keiko", "medical")
        assert "the Captain" not in system

    def test_dm_compose_prompt_default_not_captain(self):
        """DM compose prompt default is neutral, not 'the Captain'."""
        ctx = {
            "context": "test",
            "mode": "dm_response",
            "_communication_context": "private_conversation",
            # No _dm_recipient set
        }
        system, _ = _build_dm_compose_prompt(ctx, [], "Keiko", "medical")
        assert "the Captain" not in system

    def test_dm_compose_prompt_uses_recipient_when_set(self):
        """DM compose prompt uses actual recipient when _dm_recipient is set."""
        ctx = {
            "context": "test",
            "mode": "dm_response",
            "_dm_recipient": "Chapel",
            "_communication_context": "private_conversation",
        }
        system, _ = _build_dm_compose_prompt(ctx, [], "Keiko", "medical")
        assert "Chapel" in system

    def test_private_conversation_has_depth_instructions(self):
        """Private conversation branch includes AD-650 depth instructions."""
        ctx = {
            "context": "test",
            "mode": "ward_room_response",
            "channel_name": "dm-chapel",
            "_communication_context": "private_conversation",
            "_dm_recipient": "Chapel",
        }
        system, _ = _build_ward_room_compose_prompt(ctx, [], "Keiko", "medical")
        assert "interpret" in system.lower() or "another way to see" in system.lower()


class TestRegressionBF210:
    """Ensure BF-210 doesn't break existing behavior."""

    def test_non_dm_ward_room_unchanged(self):
        """Non-DM Ward Room branches are not affected."""
        ctx = {
            "context": "test",
            "mode": "ward_room_response",
            "channel_name": "engineering",
            "_communication_context": "department_discussion",
        }
        system, _ = _build_ward_room_compose_prompt(ctx, [], "Keiko", "medical")
        assert "Ward Room thread" in system
        assert "private" not in system.lower()

    def test_private_conversation_retains_anti_format(self):
        """Private conversation branch retains anti-format instruction."""
        ctx = {
            "context": "test",
            "mode": "ward_room_response",
            "channel_name": "dm-chapel",
            "_communication_context": "private_conversation",
            "_dm_recipient": "Chapel",
        }
        system, _ = _build_ward_room_compose_prompt(ctx, [], "Keiko", "medical")
        assert "Do NOT use structured formats" in system
```

Test count: 8 tests across 2 classes.

---

## What This Does NOT Do (Out of Scope)

- **Does not strengthen capability grounding.** Confabulation is reduced by removing the Captain authority frame, but the ontology `does_not_have` field enforcement is a separate concern (AD-648 follow-up).
- **Does not add peer-vs-authority register distinction.** This fix names the peer; a future AD could tune register differently for subordinates vs peers vs superiors.
- **Does not change the one-shot DM path.** One-shot DMs go through `act()` → `direct_message`, not the chain. Separate code path.
- **Does not change ANALYZE.** The analysis step doesn't use `_dm_recipient`.

---

## Engineering Principles Compliance

- **SOLID (S):** No new responsibilities. `cognitive_agent.py` already sets DM context flags — this adds one more field to the same block.
- **SOLID (O):** Existing compose prompt extended, not replaced. Backward-compatible empty-string fallback.
- **Fail Fast:** `_params.get("author_callsign", "")` — graceful empty default. `_peer_label` only adds "with X" when non-empty.
- **DRY:** `_dm_recipient` is set once in `cognitive_agent.py`, consumed by whichever compose function is called.
- **Law of Demeter:** Uses existing `_params` dict already extracted at L.1822. No new object reaching.
