"""AD-526a: Recreation channel + proactive integration tests."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.events import EventType
from probos.recreation.service import RecreationService


class TestEventType:
    """Verify GAME_COMPLETED event type exists."""

    def test_game_completed_event(self):
        assert hasattr(EventType, "GAME_COMPLETED")
        assert EventType.GAME_COMPLETED.value == "game_completed"


class TestChallengePattern:
    """Verify CHALLENGE regex extraction."""

    def test_challenge_pattern_match(self):
        pattern = r'\[CHALLENGE\s+@(\w+)\s+(\w+)\]'
        text = "I challenge you! [CHALLENGE @bones tictactoe]"
        match = re.search(pattern, text)
        assert match
        assert match.group(1) == "bones"
        assert match.group(2) == "tictactoe"

    def test_challenge_pattern_strip(self):
        pattern = r'\[CHALLENGE\s+@(\w+)\s+(\w+)\]'
        text = "I challenge you! [CHALLENGE @bones tictactoe] Let's go!"
        cleaned = re.sub(pattern, '', text).strip()
        assert "[CHALLENGE" not in cleaned
        assert "I challenge you!" in cleaned

    def test_multiple_challenges(self):
        pattern = r'\[CHALLENGE\s+@(\w+)\s+(\w+)\]'
        text = "[CHALLENGE @bones tictactoe] [CHALLENGE @worf tictactoe]"
        matches = list(re.finditer(pattern, text))
        assert len(matches) == 2


class TestMovePattern:
    """Verify MOVE regex extraction."""

    def test_move_pattern_match(self):
        pattern = r'\[MOVE\s+(\S+)\]'
        text = "My turn! [MOVE 4]"
        match = re.search(pattern, text)
        assert match
        assert match.group(1) == "4"

    def test_move_pattern_strip(self):
        pattern = r'\[MOVE\s+(\S+)\]'
        text = "Playing center. [MOVE 4] Good game so far."
        cleaned = re.sub(pattern, '', text).strip()
        assert "[MOVE" not in cleaned


class TestBF120MarkdownStripping:
    """BF-120: Markdown formatting around structured tags breaks regex parsing."""

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Apply the BF-120 normalization (mirrors proactive.py implementation)."""
        text = re.sub(r'[`*]{1,3}\[', '[', text)
        text = re.sub(r'\][`*]{1,3}', ']', text)
        return text

    def test_bold_wrapped_challenge(self):
        text = "Let's play! **[CHALLENGE @Horizon tictactoe]**"
        cleaned = self._strip_markdown(text)
        pattern = r'\[CHALLENGE\s+@(\w+)\s+(\w+)\]'
        match = re.search(pattern, cleaned)
        assert match, f"Regex should match after stripping, got: {cleaned!r}"
        assert match.group(1) == "Horizon"
        assert match.group(2) == "tictactoe"

    def test_backtick_wrapped_challenge(self):
        text = "Issuing: `[CHALLENGE @Echo tictactoe]`"
        cleaned = self._strip_markdown(text)
        match = re.search(r'\[CHALLENGE\s+@(\w+)\s+(\w+)\]', cleaned)
        assert match
        assert match.group(1) == "Echo"

    def test_italic_wrapped_move(self):
        text = "My move: *[MOVE 4]*"
        cleaned = self._strip_markdown(text)
        match = re.search(r'\[MOVE\s+(\S+)\]', cleaned)
        assert match
        assert match.group(1) == "4"

    def test_bold_italic_wrapped(self):
        text = "***[CHALLENGE @Forge tictactoe]***"
        cleaned = self._strip_markdown(text)
        match = re.search(r'\[CHALLENGE\s+@(\w+)\s+(\w+)\]', cleaned)
        assert match
        assert match.group(1) == "Forge"

    def test_code_block_wrapped_notebook(self):
        text = "`[NOTEBOOK my-topic]`Content here`[/NOTEBOOK]`"
        cleaned = self._strip_markdown(text)
        assert "[NOTEBOOK my-topic]" in cleaned
        assert "[/NOTEBOOK]" in cleaned

    def test_unformatted_tag_unchanged(self):
        """Tags without markdown formatting should pass through unchanged."""
        text = "I challenge you! [CHALLENGE @bones tictactoe] Let's go!"
        cleaned = self._strip_markdown(text)
        assert cleaned == text

    def test_mixed_formatted_and_plain(self):
        text = "**[CHALLENGE @Atlas tictactoe]** and [MOVE 4]"
        cleaned = self._strip_markdown(text)
        assert re.search(r'\[CHALLENGE\s+@(\w+)\s+(\w+)\]', cleaned)
        assert re.search(r'\[MOVE\s+(\S+)\]', cleaned)


class TestRecreationServiceIntegration:
    """Integration tests for RecreationService game flow."""

    @pytest.mark.asyncio
    async def test_full_game_flow(self):
        """Play a complete game and verify lifecycle."""
        svc = RecreationService()
        game = await svc.create_game("tictactoe", "echo", "bones")
        gid = game["game_id"]

        # echo (X) plays 0, 1, 2 — bones (O) plays 3, 4
        await svc.make_move(gid, "echo", "0")
        board = svc.render_board(gid)
        assert "X" in board

        await svc.make_move(gid, "bones", "3")
        await svc.make_move(gid, "echo", "1")
        await svc.make_move(gid, "bones", "4")

        # Valid moves should be 5,6,7,8 before final move
        moves = svc.get_valid_moves(gid)
        assert "2" in moves

        result = await svc.make_move(gid, "echo", "2")
        assert result["result"]["status"] == "won"
        assert result["result"]["winner"] == "echo"
        assert len(svc.get_active_games()) == 0

    @pytest.mark.asyncio
    async def test_draw_game(self):
        """Play to a draw."""
        svc = RecreationService()
        game = await svc.create_game("tictactoe", "a", "b")
        gid = game["game_id"]
        # Board: X O X / X O O / O X X — no winner, alternating a,b
        for pos, player in [(0, "a"), (4, "b"), (2, "a"),
                             (1, "b"), (3, "a"), (6, "b"),
                             (8, "a"), (5, "b"), (7, "a")]:
            await svc.make_move(gid, player, str(pos))
        assert len(svc.get_active_games()) == 0


class TestBF122CallsignResolution:
    """BF-122: callsign was undefined in _extract_and_execute_actions recreation block.

    The recreation block at the challenge parsing section used `callsign` without
    defining it — it relied on a variable leaked from the notebook loop's try block.
    If the agent produced [CHALLENGE] without [NOTEBOOK], NameError crashed the
    entire _extract_and_execute_actions method silently (caught by DEBUG-level except).
    """

    def test_callsign_not_defined_by_notebook_loop(self):
        """Verify the bug scenario: no notebook → callsign undefined."""
        # If this code ran, `callsign` would be undefined since it's only set
        # inside the notebook `for` loop's `try` block
        callsign_defined = False
        text = "[CHALLENGE @Vega tictactoe]"
        notebook_pattern = r'\[NOTEBOOK\s+([\w-]+)\](.*?)\[/NOTEBOOK\]'
        notebook_matches = re.findall(notebook_pattern, text, re.DOTALL)
        for _topic, _content in notebook_matches:
            callsign_defined = True  # Only set if notebook match found
        # No notebook blocks → callsign never set
        assert not callsign_defined, "No notebook blocks should mean callsign is never defined"

    def test_challenge_regex_matches_standard_format(self):
        """Verify challenge regex works on typical agent output."""
        # The regex pattern from proactive.py
        pattern = r'\[CHALLENGE\s+@(\w+)\s+(\w+)\]'
        text = "I'll challenge you! [CHALLENGE @Vega tictactoe] Let's play!"
        match = re.search(pattern, text)
        assert match, "Challenge pattern should match standard format"
        assert match.group(1) == "Vega"
        assert match.group(2) == "tictactoe"


class TestBF121ReplyBlockNesting:
    """BF-121: CHALLENGE tags inside REPLY blocks are posted as text but never parsed.

    When agents wrap output in [REPLY thread_id]...[/REPLY] blocks, the reply
    extraction at line 1636 consumes the CHALLENGE tag: it posts the reply body
    (including [CHALLENGE ...]) to Ward Room as text, then strips the entire
    [REPLY]...[/REPLY] block from `text`. When the challenge regex runs later,
    the CHALLENGE tag is gone from `text` — no match, no game, no logs.
    """

    def test_reply_pattern_consumes_nested_challenge(self):
        """Demonstrate the pre-fix bug: REPLY extraction eats CHALLENGE tags."""
        reply_pattern = re.compile(
            r'\[REPLY\s+(?:thread:?\s*)?(\S+)\]\s*(.*?)\s*\[/REPLY\]',
            re.DOTALL | re.IGNORECASE,
        )
        text = "[REPLY abc123]Challenge accepted! [CHALLENGE @Vega tictactoe][/REPLY]"
        match = reply_pattern.search(text)
        assert match, "REPLY pattern should match"
        reply_body = match.group(2).strip()
        assert "[CHALLENGE" in reply_body, "CHALLENGE tag should be captured in reply body"

        # After stripping REPLY blocks, CHALLENGE is gone from text
        cleaned = reply_pattern.sub('', text).strip()
        challenge_pattern = r'\[CHALLENGE\s+@(\w+)\s+(\w+)\]'
        assert not re.search(challenge_pattern, cleaned), \
            "CHALLENGE should NOT survive REPLY block stripping"

    def test_challenge_in_reply_body_matches_regex(self):
        """Verify CHALLENGE regex works on extracted reply body."""
        reply_body = "Challenge accepted! [CHALLENGE @Horizon tictactoe] Fair warning!"
        pattern = r'\[CHALLENGE\s+@(\w+)\s+(\w+)\]'
        match = re.search(pattern, reply_body)
        assert match
        assert match.group(1) == "Horizon"
        assert match.group(2) == "tictactoe"
        # After stripping
        cleaned = re.sub(pattern, '', reply_body).strip()
        assert "[CHALLENGE" not in cleaned

    def test_move_in_reply_body_matches_regex(self):
        """Verify MOVE regex works on extracted reply body."""
        reply_body = "My turn! [MOVE 4] Good game!"
        pattern = r'\[MOVE\s+(\S+)\]'
        match = re.search(pattern, reply_body)
        assert match
        assert match.group(1) == "4"

    def test_mixed_challenge_and_reply_text(self):
        """Reply body with both conversational text and CHALLENGE tag."""
        text = "[REPLY abc123]Your analysis is sound. [CHALLENGE @Atlas tictactoe] Care to play while we wait for results?[/REPLY]"
        reply_pattern = re.compile(
            r'\[REPLY\s+(?:thread:?\s*)?(\S+)\]\s*(.*?)\s*\[/REPLY\]',
            re.DOTALL | re.IGNORECASE,
        )
        match = reply_pattern.search(text)
        assert match
        reply_body = match.group(2).strip()

        # Extract challenge from reply body (the BF-121 fix)
        challenge_pattern = r'\[CHALLENGE\s+@(\w+)\s+(\w+)\]'
        ch_match = re.search(challenge_pattern, reply_body)
        assert ch_match
        assert ch_match.group(1) == "Atlas"

        # Clean reply body after command extraction
        cleaned_body = re.sub(challenge_pattern, '', reply_body).strip()
        assert "Your analysis is sound." in cleaned_body
        assert "Care to play" in cleaned_body
        assert "[CHALLENGE" not in cleaned_body


class TestBF123WardRoomRouterExtraction:
    """BF-123: Ward Room router response path must parse CHALLENGE/MOVE tags.

    When Captain posts in Ward Room, agents respond through
    ward_room_router.handle_event() → intent_bus.send(). This path only
    extracted endorsements and DMs — CHALLENGE/MOVE tags were posted as
    raw text. The _extract_recreation_commands() method fixes this.
    """

    @pytest.fixture
    def mock_runtime(self):
        """Minimal runtime with recreation_service + callsign_registry."""
        rt = MagicMock()
        rt.recreation_service = MagicMock()
        rt.recreation_service.create_game = AsyncMock(return_value={"game_id": "game-001"})
        rt.recreation_service.get_game_by_player = MagicMock(return_value={
            "game_id": "game-001",
            "state": {"current_player": "forge"},
            "thread_id": "th-001",
        })
        rt.recreation_service.make_move = AsyncMock(return_value={
            "state": {"current_player": "echo"},
            "result": None,
        })
        rt.recreation_service.render_board = MagicMock(return_value="X| |O\n-+-+-\n |X| \n-+-+-\n | |O")
        rt.callsign_registry = MagicMock()
        rt.callsign_registry.resolve = MagicMock(return_value={
            "agent_id": "agent-echo-001",
            "agent_type": "counselor",
        })
        rt.config = MagicMock()
        rt.config.communications.recreation_min_rank = "ensign"
        rec_channel = MagicMock(id="rec-ch-001")
        rec_channel.name = "Recreation"
        rt.ward_room = AsyncMock()
        rt.ward_room.list_channels = AsyncMock(return_value=[rec_channel])
        rt.ward_room.create_thread = AsyncMock(return_value=MagicMock(id="th-new-001"))
        rt.ward_room.create_post = AsyncMock()
        return rt

    @pytest.fixture
    def router(self, mock_runtime):
        """WardRoomRouter with mocked dependencies."""
        from probos.ward_room_router import WardRoomRouter
        proactive = MagicMock()
        proactive._runtime = mock_runtime
        trust_network = MagicMock()
        trust_network.get_score = MagicMock(return_value=0.5)  # Ensign rank
        return WardRoomRouter(
            ward_room=mock_runtime.ward_room,
            registry=MagicMock(),
            intent_bus=MagicMock(),
            trust_network=trust_network,
            ontology=None,
            callsign_registry=mock_runtime.callsign_registry,
            episodic_memory=None,
            event_emitter=MagicMock(),
            event_log=MagicMock(),
            config=mock_runtime.config,
            proactive_loop=proactive,
        )

    @pytest.fixture
    def mock_agent(self):
        agent = MagicMock()
        agent.id = "agent-forge-001"
        agent.agent_type = "engineering"
        agent.working_memory = None
        return agent

    @pytest.mark.asyncio
    async def test_challenge_extracted_and_game_created(self, router, mock_agent, mock_runtime):
        """CHALLENGE tag should create a game via recreation_service."""
        text = "Let's play! [CHALLENGE @echo tictactoe] What do you say?"
        result = await router._extract_recreation_commands(mock_agent, text, "forge")
        # Tag should be stripped
        assert "[CHALLENGE" not in result
        assert "Let's play!" in result
        # Game should be created
        mock_runtime.recreation_service.create_game.assert_awaited_once_with(
            game_type="tictactoe",
            challenger="forge",
            opponent="echo",
            thread_id="th-new-001",
        )

    @pytest.mark.asyncio
    async def test_move_extracted_and_executed(self, router, mock_agent, mock_runtime):
        """MOVE tag should execute a move via recreation_service."""
        text = "Here's my move! [MOVE 5] Your turn."
        result = await router._extract_recreation_commands(mock_agent, text, "forge")
        assert "[MOVE" not in result
        assert "Here's my move!" in result
        mock_runtime.recreation_service.make_move.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_markdown_stripped_before_parsing(self, router, mock_agent, mock_runtime):
        """BF-120: Markdown-wrapped tags should still be parsed."""
        text = "Let's go! **[CHALLENGE @echo tictactoe]**"
        result = await router._extract_recreation_commands(mock_agent, text, "forge")
        assert "[CHALLENGE" not in result
        mock_runtime.recreation_service.create_game.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_recreation_service_passes_through(self, router, mock_agent):
        """Without recreation_service, text should pass through unchanged."""
        router._proactive_loop._runtime.recreation_service = None
        text = "Let's play! [CHALLENGE @echo tictactoe]"
        result = await router._extract_recreation_commands(mock_agent, text, "forge")
        assert result == text

    @pytest.mark.asyncio
    async def test_unresolved_target_skipped(self, router, mock_agent, mock_runtime):
        """Unknown callsign should skip the challenge, not crash."""
        mock_runtime.callsign_registry.resolve.return_value = None
        text = "Hello [CHALLENGE @nobody tictactoe]"
        result = await router._extract_recreation_commands(mock_agent, text, "forge")
        assert "[CHALLENGE" not in result
        mock_runtime.recreation_service.create_game.assert_not_awaited()
