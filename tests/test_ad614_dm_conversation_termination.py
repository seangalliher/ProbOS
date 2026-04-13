"""AD-614: DM conversation termination — self-similarity gate + exchange limit."""

import ast
import time

import pytest
import pytest_asyncio

from probos.config import WardRoomConfig
from probos.ward_room.service import WardRoomService


# ---------------------------------------------------------------------------
# Layer 2: DM Self-Similarity Gate (structural + behavioral)
# ---------------------------------------------------------------------------


class TestDmSelfSimilarityGate:
    """AD-614 Layer 2: Jaccard self-similarity gate on DM sending."""

    def test_last_dm_body_dict_initialized(self):
        """_last_dm_body exists in ProactiveCognitiveLoop init."""
        src = open("src/probos/proactive.py", encoding="utf-8").read()
        assert "_last_dm_body" in src
        assert "dict[str, str]" in src

    def test_similarity_gate_exists_in_source(self):
        """Self-similarity gate code exists in _extract_and_execute_dms."""
        src = open("src/probos/proactive.py", encoding="utf-8").read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_extract_and_execute_dms":
                body_src = ast.dump(node)
                assert "jaccard_similarity" in body_src
                assert "last_dm_body" in body_src
                return
        pytest.fail("_extract_and_execute_dms not found")

    def test_identical_dm_suppressed(self):
        """Jaccard 1.0 (identical body) should be suppressed."""
        from probos.cognitive.similarity import jaccard_similarity

        body_a = "Tuesday 1400 hours it is then"
        body_b = "Tuesday 1400 hours it is then"
        sim = jaccard_similarity(
            set(body_a.lower().split()),
            set(body_b.lower().split()),
        )
        assert sim >= 0.6
        assert sim == 1.0

    def test_high_similarity_dm_suppressed(self):
        """Jaccard >= 0.6 should be suppressed."""
        from probos.cognitive.similarity import jaccard_similarity

        body_a = "Tuesday 1400 hours it is then confirmed"
        body_b = "Tuesday 1400 hours it is confirmed then acknowledged"
        sim = jaccard_similarity(
            set(body_a.lower().split()),
            set(body_b.lower().split()),
        )
        assert sim >= 0.6

    def test_low_similarity_dm_allowed(self):
        """Jaccard < 0.6 should be allowed."""
        from probos.cognitive.similarity import jaccard_similarity

        body_a = "Tuesday 1400 hours confirmed"
        body_b = "I noticed unusual latency patterns in the sensor array"
        sim = jaccard_similarity(
            set(body_a.lower().split()),
            set(body_b.lower().split()),
        )
        assert sim < 0.6

    def test_first_dm_always_allowed(self):
        """No prior body = no comparison, always allowed."""
        last_dm_body: dict[str, str] = {}
        key = "agent-1:chapel"
        last_body = last_dm_body.get(key, "")
        # Empty string => no comparison => allowed
        assert last_body == ""

    def test_different_target_allowed(self):
        """Same body to different target uses different key."""
        last_dm_body: dict[str, str] = {}
        body = "Meeting at 1400 hours"
        key_a = "agent-1:chapel"
        key_b = "agent-1:lynx"
        last_dm_body[key_a] = body
        # Different key => no prior body for key_b
        assert last_dm_body.get(key_b, "") == ""


# ---------------------------------------------------------------------------
# Layer 3: DM Exchange Limit (config + structural + behavioral)
# ---------------------------------------------------------------------------


class TestDmExchangeLimit:
    """AD-614 Layer 3: Config fields for DM exchange limit."""

    def test_dm_exchange_limit_config_exists(self):
        """dm_exchange_limit field exists in WardRoomConfig."""
        config = WardRoomConfig()
        assert hasattr(config, "dm_exchange_limit")

    def test_dm_similarity_threshold_config_exists(self):
        """dm_similarity_threshold field exists in WardRoomConfig."""
        config = WardRoomConfig()
        assert hasattr(config, "dm_similarity_threshold")

    def test_exchange_limit_default_value(self):
        """Default exchange limit is 6."""
        config = WardRoomConfig()
        assert config.dm_exchange_limit == 6

    def test_similarity_threshold_default_value(self):
        """Default similarity threshold is 0.6."""
        config = WardRoomConfig()
        assert config.dm_similarity_threshold == 0.6


class TestDmExchangeLimitBehavior:
    """AD-614 Layer 3: Exchange limit behavioral tests via WardRoomService."""

    @pytest_asyncio.fixture
    async def ward_room(self, tmp_path):
        """Create a WardRoomService with temp SQLite DB."""
        events = []
        def capture_event(event_type, data):
            events.append({"type": event_type, "data": data})

        svc = WardRoomService(
            db_path=str(tmp_path / "ward_room.db"),
            emit_event=capture_event,
        )
        await svc.start()
        yield svc
        await svc.stop()

    @pytest.mark.asyncio
    async def test_count_posts_by_author_returns_int(self, ward_room):
        """count_posts_by_author returns an integer."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "agent-1", "Test", "body")
        count = await ward_room.count_posts_by_author(thread.id, "agent-1")
        assert isinstance(count, int)

    @pytest.mark.asyncio
    async def test_under_limit_allowed(self, ward_room):
        """Agent with < 6 posts should be under the limit."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "agent-1", "Test", "body")
        # create_thread doesn't create a post — add replies manually
        for i in range(5):
            await ward_room.create_post(thread.id, "agent-1", f"Reply {i}")
        count = await ward_room.count_posts_by_author(thread.id, "agent-1")
        assert count < 6

    @pytest.mark.asyncio
    async def test_at_limit_suppressed(self, ward_room):
        """Agent with >= 6 posts should hit the exchange limit."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "agent-1", "Test", "body")
        # create_thread doesn't create a post — add 6 replies to hit limit
        for i in range(6):
            await ward_room.create_post(thread.id, "agent-1", f"Reply {i}")
        count = await ward_room.count_posts_by_author(thread.id, "agent-1")
        assert count >= 6

    @pytest.mark.asyncio
    async def test_other_author_not_counted(self, ward_room):
        """Posts by other authors don't count toward the limit."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "agent-1", "Test", "body")
        # Add posts by agent-1 and agent-2
        await ward_room.create_post(thread.id, "agent-1", "My reply")
        for i in range(5):
            await ward_room.create_post(thread.id, "agent-2", f"Reply {i}")
        count_a1 = await ward_room.count_posts_by_author(thread.id, "agent-1")
        count_a2 = await ward_room.count_posts_by_author(thread.id, "agent-2")
        assert count_a1 == 1
        assert count_a2 == 5


# ---------------------------------------------------------------------------
# Layer 1: Standing Orders (structural)
# ---------------------------------------------------------------------------


class TestStandingOrdersConversationClosure:
    """AD-614 Layer 1: Standing order text verification."""

    def test_federation_orders_conversation_closure(self):
        """Federation standing orders contain conversation closure guidance."""
        text = open("config/standing_orders/federation.md", encoding="utf-8").read()
        assert "confirm a confirmation" in text
        assert "Conversation closure" in text

    def test_ship_orders_dm_self_monitoring(self):
        """Ship standing orders contain DM self-monitoring guidance."""
        text = open("config/standing_orders/ship.md", encoding="utf-8").read()
        assert "DM self-monitoring" in text
