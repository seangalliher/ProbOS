"""BF-212: Crew-vs-crew game move notification tests."""
import pytest
from probos.ward_room.models import extract_mentions


class TestGameMoveNotification:
    """Verify game move board posts @mention the next player."""

    def test_extract_mentions_finds_callsign_in_board_post(self):
        """extract_mentions detects @callsign in game move board post."""
        msg = "```\nX | . | .\n. | O | .\n. | . | .\n```\nYour move, @Lyra"
        mentions = extract_mentions(msg)
        assert "Lyra" in mentions

    def test_extract_mentions_no_mention_in_game_over(self):
        """Game-over posts should NOT contain @mentions."""
        msg = "Game over! Winner: Chapel"
        mentions = extract_mentions(msg)
        assert len(mentions) == 0

    def test_board_post_format_in_progress(self):
        """In-progress board post uses 'Your move, @next' format."""
        _next = "Lyra"
        board = "X | . | .\n. | O | .\n. | . | ."
        body = f"```\n{board}\n```\nYour move, @{_next}"
        assert f"@{_next}" in body
        mentions = extract_mentions(body)
        assert _next in mentions

    def test_board_post_format_game_over(self):
        """Game-over post does not @mention anyone."""
        winner = "Chapel"
        body = f"Game over! Winner: {winner}"
        assert "@" not in body
        mentions = extract_mentions(body)
        assert len(mentions) == 0
