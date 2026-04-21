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
        # Should say "conversation." not "conversation with ."
        assert "conversation. " in system or "conversation\n" in system

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
        # Standing orders may mention "the Captain" generically, but the
        # mode framing sentence should not.
        assert "conversation with the Captain" not in system

    def test_dm_compose_prompt_default_not_captain(self):
        """DM compose prompt default is neutral, not 'the Captain'."""
        ctx = {
            "context": "test",
            "mode": "dm_response",
            "_communication_context": "private_conversation",
            # No _dm_recipient set
        }
        system, _ = _build_dm_compose_prompt(ctx, [], "Keiko", "medical")
        assert "conversation with the Captain" not in system
        assert "a crew member" in system

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
        # The general branch shouldn't have "private" in its mode framing
        assert "private 1:1 conversation" not in system

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
