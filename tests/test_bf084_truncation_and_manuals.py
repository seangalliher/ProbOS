"""BF-084: Ward Room message truncation fix + manual seeding tests."""

import pytest
import yaml
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from probos.ward_room import WardRoomService


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
async def wr(tmp_path):
    """Ward Room service with test DB."""
    svc = WardRoomService(db_path=str(tmp_path / "wr.db"))
    await svc.start()
    yield svc
    await svc.stop()


def _make_records_config(tmp_path: Path, **overrides):
    from probos.config import RecordsConfig
    defaults = {
        "repo_path": str(tmp_path / "ship-records"),
        "enabled": True,
        "auto_commit": True,
        "commit_debounce_seconds": 5.0,
        "max_episodes_per_hour": 20,
    }
    defaults.update(overrides)
    return RecordsConfig(**defaults)


@pytest.fixture
async def store(tmp_path):
    from probos.knowledge.records_store import RecordsStore
    cfg = _make_records_config(tmp_path)
    s = RecordsStore(cfg)
    await s.initialize()
    return s


# ------------------------------------------------------------------
# 1. Truncation — proactive context
# ------------------------------------------------------------------

class TestProactiveTruncation:
    @pytest.mark.asyncio
    async def test_ward_room_body_not_truncated_at_150(self, wr):
        """A 400-char message body should survive get_recent_activity at 500-char limit."""
        ch = await wr.create_channel(
            name="test-dept-bf084", channel_type="department",
            created_by="agent-aaa", department="science",
        )
        long_body = "A" * 400
        await wr.create_thread(
            channel_id=ch.id, author_id="agent-aaa",
            title="Analysis", body=long_body, author_callsign="Cortez",
        )

        activity = await wr.get_recent_activity(ch.id, since=0.0, limit=5)
        assert len(activity) >= 1
        thread_item = activity[0]
        # Body should be at least 400 chars (not truncated at 200)
        assert len(thread_item["body"]) >= 400


# ------------------------------------------------------------------
# 2. Truncation — get_recent_activity body
# ------------------------------------------------------------------

class TestGetRecentActivityLimits:
    @pytest.mark.asyncio
    async def test_body_limit_raised_to_500(self, wr):
        """Body content up to 500 chars is preserved, longer is truncated at 500."""
        ch = await wr.create_channel(
            name="test-limits-bf084", channel_type="ship",
            created_by="agent-aaa",
        )
        body_500 = "B" * 500
        body_600 = "C" * 600
        await wr.create_thread(
            channel_id=ch.id, author_id="agent-aaa",
            title="T1", body=body_500,
        )
        await wr.create_thread(
            channel_id=ch.id, author_id="agent-aaa",
            title="T2", body=body_600,
        )

        activity = await wr.get_recent_activity(ch.id, since=0.0, limit=10)
        bodies = {a["title"]: a["body"] for a in activity if a["type"] == "thread"}
        # 500-char body preserved exactly
        assert len(bodies["T1"]) == 500
        # 600-char body truncated to 500
        assert len(bodies["T2"]) == 500


# ------------------------------------------------------------------
# 3. Manual seeding — seed_manuals copies files
# ------------------------------------------------------------------

class TestSeedManuals:
    @pytest.mark.asyncio
    async def test_copies_files_with_frontmatter(self, store, tmp_path):
        """seed_manuals() copies md files with correct frontmatter."""
        manuals_dir = tmp_path / "manuals-src"
        manuals_dir.mkdir()
        (manuals_dir / "ward-room.md").write_text(
            "# Ward Room Manual\n\nThis is the manual.", encoding="utf-8",
        )

        count = await store.seed_manuals(manuals_dir)
        assert count == 1

        # Verify file exists with frontmatter
        seeded_path = store.repo_path / "manuals" / "ward-room.md"
        assert seeded_path.exists()
        text = seeded_path.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        # Parse frontmatter
        parts = text.split("---\n", 2)
        fm = yaml.safe_load(parts[1])
        assert fm["author"] == "shipyard"
        assert fm["classification"] == "ship"
        assert fm["status"] == "published"
        assert fm["topic"] == "ward-room"
        assert "manual" in fm["tags"]
        # Content preserved
        assert "# Ward Room Manual" in parts[2]

    @pytest.mark.asyncio
    async def test_empty_dir_returns_zero(self, store, tmp_path):
        """seed_manuals() on nonexistent dir returns 0, no errors."""
        missing_dir = tmp_path / "no-such-dir"
        count = await store.seed_manuals(missing_dir)
        assert count == 0

    @pytest.mark.asyncio
    async def test_overwrites_existing(self, store, tmp_path):
        """Seeding twice overwrites the manual with latest source."""
        manuals_dir = tmp_path / "manuals-src"
        manuals_dir.mkdir()
        (manuals_dir / "ops.md").write_text("Version 1", encoding="utf-8")
        await store.seed_manuals(manuals_dir)

        # Modify source
        (manuals_dir / "ops.md").write_text("Version 2", encoding="utf-8")
        count = await store.seed_manuals(manuals_dir)
        assert count == 1

        text = (store.repo_path / "manuals" / "ops.md").read_text(encoding="utf-8")
        assert "Version 2" in text
        assert "Version 1" not in text

    @pytest.mark.asyncio
    async def test_agents_can_read_seeded_manual(self, store, tmp_path):
        """After seeding, read_entry returns content (ship classification = all crew)."""
        manuals_dir = tmp_path / "manuals-src"
        manuals_dir.mkdir()
        (manuals_dir / "ward-room.md").write_text(
            "# Ward Room Manual\n\nContent here.", encoding="utf-8",
        )
        await store.seed_manuals(manuals_dir)

        result = await store.read_entry(
            "manuals/ward-room.md", reader_id="any-agent",
        )
        assert result is not None
        assert "Ward Room Manual" in result["content"]
        assert result["frontmatter"]["classification"] == "ship"
