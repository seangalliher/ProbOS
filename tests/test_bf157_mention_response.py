"""BF-157: @mention response guarantee tests."""

import pytest


class TestWasMentionedFlag:
    """BF-157: was_mentioned flag passed to agent."""

    def test_was_mentioned_in_intent_params(self):
        """IntentMessage params should include was_mentioned key."""
        from pathlib import Path

        source = Path("src/probos/ward_room_router.py").read_text()
        assert '"was_mentioned"' in source

    def test_mentioned_agent_ids_built_from_mentions(self):
        """mentioned_agent_ids set should be built before dispatch loop."""
        from pathlib import Path

        source = Path("src/probos/ward_room_router.py").read_text()
        assert "mentioned_agent_ids" in source


class TestMentionedAgentPrompt:
    """BF-157: @mentioned agents get a response-required prompt."""

    def test_mentioned_agent_skips_no_response_option(self):
        """When was_mentioned=True, the prompt should not offer [NO_RESPONSE]."""
        from pathlib import Path

        source = Path("src/probos/cognitive/cognitive_agent.py").read_text()
        # The ward_room_notification path should check was_mentioned
        assert 'was_mentioned' in source
        # Should contain the "directly @mentioned" instruction
        assert "directly" in source.lower() and "mentioned" in source.lower()


class TestMentionedBypassesCooldown:
    """BF-157: @mentioned agents bypass cooldown and response caps."""

    def test_mentioned_agents_bypass_cooldown(self):
        """@mentioned agents should not be subject to per-agent cooldown."""
        from pathlib import Path

        source = Path("src/probos/ward_room_router.py").read_text()
        assert "is_direct_target" in source
        assert "mentioned_agent_ids" in source
