"""Tests for AD-550 — Notebook Deduplication (Read-Before-Write)."""

import asyncio
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from probos.config import RecordsConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(tmp_path: Path, **overrides):
    """Create a RecordsConfig-like object pointing at tmp_path."""
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
def records_config(tmp_path):
    return _make_config(tmp_path)


@pytest.fixture
async def store(records_config):
    from probos.knowledge.records_store import RecordsStore
    s = RecordsStore(records_config)
    await s.initialize()
    return s


def _write_notebook_file(store, callsign: str, topic_slug: str, content: str,
                         updated: str | None = None, created: str | None = None,
                         revision: int | None = None):
    """Write a notebook file directly to disk for test setup."""
    now = updated or datetime.now(timezone.utc).isoformat()
    fm: dict = {
        "author": callsign,
        "classification": "department",
        "status": "draft",
        "created": created or now,
        "updated": now,
        "topic": topic_slug,
    }
    if revision is not None:
        fm["revision"] = revision
    fm_yaml = yaml.dump(fm, default_flow_style=False, sort_keys=False)
    full = f"---\n{fm_yaml}---\n\n{content}"
    path = store.repo_path / "notebooks" / callsign / f"{topic_slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(full, encoding="utf-8")


# ===========================================================================
# Jaccard utility tests (3 tests)
# ===========================================================================

class TestJaccardSimilarity:
    def test_jaccard_identical_text(self):
        from probos.knowledge.records_store import _jaccard_similarity
        assert _jaccard_similarity("hello world foo bar", "hello world foo bar") == 1.0

    def test_jaccard_completely_different(self):
        from probos.knowledge.records_store import _jaccard_similarity
        assert _jaccard_similarity("alpha beta gamma", "delta epsilon zeta") == 0.0

    def test_jaccard_partial_overlap(self):
        from probos.knowledge.records_store import _jaccard_similarity
        # "hello world" and "hello there" share {"hello"}, union {"hello", "world", "there"}
        result = _jaccard_similarity("hello world", "hello there")
        assert abs(result - 1 / 3) < 0.01

    def test_jaccard_empty_text(self):
        from probos.knowledge.records_store import _jaccard_similarity
        assert _jaccard_similarity("", "hello") == 0.0
        assert _jaccard_similarity("hello", "") == 0.0
        assert _jaccard_similarity("", "") == 0.0


# ===========================================================================
# Update-in-place tests (4 tests)
# ===========================================================================

class TestUpdateInPlace:
    @pytest.mark.asyncio
    async def test_write_entry_preserves_created_on_overwrite(self, store):
        """Write twice to same path, second write preserves first created timestamp."""
        await store.write_entry(
            author="TestAgent", path="notebooks/TestAgent/topic-a.md",
            content="First write", message="first",
        )
        # Read the created timestamp
        raw1 = (store.repo_path / "notebooks/TestAgent/topic-a.md").read_text(encoding="utf-8")
        fm1, _ = store._parse_document(raw1)
        created1 = fm1["created"]

        # Wait slightly to ensure different timestamp
        await asyncio.sleep(0.01)

        await store.write_entry(
            author="TestAgent", path="notebooks/TestAgent/topic-a.md",
            content="Second write", message="second",
        )
        raw2 = (store.repo_path / "notebooks/TestAgent/topic-a.md").read_text(encoding="utf-8")
        fm2, _ = store._parse_document(raw2)

        assert fm2["created"] == created1, "created timestamp should be preserved"

    @pytest.mark.asyncio
    async def test_write_entry_increments_revision(self, store):
        """Write twice, revision goes from absent to 2."""
        await store.write_entry(
            author="TestAgent", path="notebooks/TestAgent/rev-test.md",
            content="v1", message="first",
        )
        raw1 = (store.repo_path / "notebooks/TestAgent/rev-test.md").read_text(encoding="utf-8")
        fm1, _ = store._parse_document(raw1)
        # First write has no revision
        assert "revision" not in fm1

        await store.write_entry(
            author="TestAgent", path="notebooks/TestAgent/rev-test.md",
            content="v2", message="second",
        )
        raw2 = (store.repo_path / "notebooks/TestAgent/rev-test.md").read_text(encoding="utf-8")
        fm2, _ = store._parse_document(raw2)
        assert fm2["revision"] == 2

    @pytest.mark.asyncio
    async def test_write_entry_updates_updated_timestamp(self, store):
        """Second write has later updated than first."""
        await store.write_entry(
            author="TestAgent", path="notebooks/TestAgent/ts-test.md",
            content="First", message="first",
        )
        raw1 = (store.repo_path / "notebooks/TestAgent/ts-test.md").read_text(encoding="utf-8")
        fm1, _ = store._parse_document(raw1)

        await asyncio.sleep(0.01)

        await store.write_entry(
            author="TestAgent", path="notebooks/TestAgent/ts-test.md",
            content="Second", message="second",
        )
        raw2 = (store.repo_path / "notebooks/TestAgent/ts-test.md").read_text(encoding="utf-8")
        fm2, _ = store._parse_document(raw2)

        assert fm2["updated"] >= fm1["updated"]

    @pytest.mark.asyncio
    async def test_write_entry_new_file_has_no_revision(self, store):
        """First write to new path has no revision field."""
        await store.write_entry(
            author="TestAgent", path="notebooks/TestAgent/fresh.md",
            content="Brand new", message="new",
        )
        raw = (store.repo_path / "notebooks/TestAgent/fresh.md").read_text(encoding="utf-8")
        fm, _ = store._parse_document(raw)
        assert "revision" not in fm


# ===========================================================================
# check_notebook_similarity tests (8 tests)
# ===========================================================================

class TestCheckNotebookSimilarity:
    @pytest.mark.asyncio
    async def test_suppress_identical_same_topic(self, store):
        """Existing entry, same topic, high similarity, within staleness → suppress."""
        _write_notebook_file(store, "Chapel", "vitals-baseline",
                             "Establishing baseline monitoring parameters for all crew members")
        result = await store.check_notebook_similarity(
            callsign="Chapel", topic_slug="vitals-baseline",
            new_content="Establishing baseline monitoring parameters for all crew members",
        )
        assert result["action"] == "suppress"
        assert result["similarity"] >= 0.8
        assert result["existing_path"] == "notebooks/Chapel/vitals-baseline.md"

    @pytest.mark.asyncio
    async def test_allow_update_same_topic_different_content(self, store):
        """Existing entry, same topic, low similarity → update."""
        _write_notebook_file(store, "Chapel", "vitals-baseline",
                             "Establishing baseline monitoring parameters for crew")
        result = await store.check_notebook_similarity(
            callsign="Chapel", topic_slug="vitals-baseline",
            new_content="Detected anomalous latency spikes in engineering subsystems requiring investigation",
        )
        assert result["action"] == "update"
        assert result["similarity"] < 0.8
        assert result["existing_content"] is not None

    @pytest.mark.asyncio
    async def test_allow_update_stale_entry(self, store):
        """Existing entry older than staleness_hours even if identical → update."""
        old_time = (datetime.now(timezone.utc) - timedelta(hours=100)).isoformat()
        _write_notebook_file(store, "Chapel", "vitals-baseline",
                             "establishing baseline", updated=old_time)
        result = await store.check_notebook_similarity(
            callsign="Chapel", topic_slug="vitals-baseline",
            new_content="establishing baseline",
            staleness_hours=72.0,
        )
        assert result["action"] == "update"
        assert "stale" in result["reason"]

    @pytest.mark.asyncio
    async def test_suppress_cross_topic_similar_content(self, store):
        """Different topic_slug but similar content to existing entry → suppress."""
        _write_notebook_file(store, "Chapel", "crew-wellness",
                             "All crew members reporting normal wellness indicators and vitals")
        result = await store.check_notebook_similarity(
            callsign="Chapel", topic_slug="health-status",
            new_content="All crew members reporting normal wellness indicators and vitals",
        )
        assert result["action"] == "suppress"
        assert "crew-wellness" in result["reason"]
        assert result["existing_path"] == "notebooks/Chapel/crew-wellness.md"

    @pytest.mark.asyncio
    async def test_allow_write_no_existing_entries(self, store):
        """No matching entries → write."""
        result = await store.check_notebook_similarity(
            callsign="Chapel", topic_slug="new-topic",
            new_content="Brand new observation about warp core efficiency",
        )
        assert result["action"] == "write"
        assert result["existing_path"] is None

    @pytest.mark.asyncio
    async def test_scan_cap_limits_entries_checked(self, store):
        """With > 20 entries, only checks 20 most recent."""
        # Create 25 entries with unique content
        for i in range(25):
            ts = (datetime.now(timezone.utc) - timedelta(hours=i)).isoformat()
            _write_notebook_file(store, "Chapel", f"topic-{i:03d}",
                                 f"unique content for topic number {i}", updated=ts)

        # The matching entry is at position 22 (old), should be outside scan window
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=23)).isoformat()
        _write_notebook_file(store, "Chapel", "ancient-match",
                             "target content to match exactly here", updated=old_ts)

        result = await store.check_notebook_similarity(
            callsign="Chapel", topic_slug="new-query",
            new_content="target content to match exactly here",
            max_scan_entries=20,
        )
        # The ancient-match should be outside the 20-entry scan window
        # because there are 25 more recent entries
        assert result["action"] == "write"

    @pytest.mark.asyncio
    async def test_returns_existing_content_on_update(self, store):
        """action=update result includes existing entry content."""
        _write_notebook_file(store, "Data", "analysis-log",
                             "Previous analysis of sensor readings")
        result = await store.check_notebook_similarity(
            callsign="Data", topic_slug="analysis-log",
            new_content="Completely different new analysis of a different subsystem",
        )
        assert result["action"] == "update"
        assert result["existing_content"] == "Previous analysis of sensor readings"

    @pytest.mark.asyncio
    async def test_empty_content_handling(self, store):
        """Empty new content → write (don't crash)."""
        result = await store.check_notebook_similarity(
            callsign="Chapel", topic_slug="empty-test",
            new_content="",
        )
        assert result["action"] == "write"


# ===========================================================================
# Proactive engine integration tests (5 tests)
# ===========================================================================

class TestProactiveNotebookDedup:
    """Tests for AD-550 dedup gate wired into the proactive notebook handler."""

    def _make_proactive_loop(self, runtime=None):
        from probos.proactive import ProactiveCognitiveLoop
        loop = ProactiveCognitiveLoop(
            interval=60,
            cooldown=30,
            on_event=MagicMock(),
        )
        if runtime:
            loop.set_runtime(runtime)
        return loop

    def _make_runtime(self, records_store=None, dedup_enabled=True,
                      threshold=0.8, staleness=72.0, max_scan=20):
        rt = MagicMock()
        rt._records_store = records_store
        rt.ontology = None
        rt.trust_network.get_score.return_value = 0.7  # COMMANDER rank
        config = MagicMock()
        rc = MagicMock()
        rc.notebook_dedup_enabled = dedup_enabled
        rc.notebook_similarity_threshold = threshold
        rc.notebook_staleness_hours = staleness
        rc.notebook_max_scan_entries = max_scan
        config.records = rc
        config.communications.dm_min_rank = "ensign"
        rt.config = config
        rt.ward_room_router = None  # AD-550: Not needed for notebook dedup tests
        return rt

    @pytest.mark.asyncio
    async def test_notebook_write_suppressed_when_similar(self):
        """Mock dedup returning suppress → write_notebook NOT called."""
        records = AsyncMock()
        records.check_notebook_similarity = AsyncMock(return_value={
            "action": "suppress",
            "reason": "content unchanged from recent entry",
            "existing_path": "notebooks/Chapel/vitals.md",
            "existing_content": "old content",
            "similarity": 0.95,
        })
        rt = self._make_runtime(records_store=records)
        loop = self._make_proactive_loop(rt)

        agent = MagicMock()
        agent.callsign = "Chapel"
        agent.agent_type = "medical"

        text = "[NOTEBOOK vitals-baseline]Establishing baseline monitoring[/NOTEBOOK]"
        result_text, actions = await loop._extract_and_execute_actions(agent, text)

        records.write_notebook.assert_not_called()
        suppressed = [a for a in actions if a["type"] == "notebook_suppressed"]
        assert len(suppressed) == 1
        assert suppressed[0]["topic"] == "vitals-baseline"

    @pytest.mark.asyncio
    async def test_notebook_write_proceeds_when_fresh(self):
        """Mock dedup returning write → write_notebook called normally."""
        records = AsyncMock()
        records.check_notebook_similarity = AsyncMock(return_value={
            "action": "write",
            "reason": "no_existing_entry",
            "existing_path": None,
            "existing_content": None,
            "similarity": 0.0,
        })
        rt = self._make_runtime(records_store=records)
        loop = self._make_proactive_loop(rt)

        agent = MagicMock()
        agent.callsign = "Chapel"
        agent.agent_type = "medical"

        text = "[NOTEBOOK new-observation]Fresh data about warp field harmonics[/NOTEBOOK]"
        _, actions = await loop._extract_and_execute_actions(agent, text)

        records.write_notebook.assert_called_once()
        written = [a for a in actions if a["type"] == "notebook_write"]
        assert len(written) == 1

    @pytest.mark.asyncio
    async def test_notebook_dedup_failure_falls_through(self):
        """Mock dedup raising exception → write_notebook still called."""
        records = AsyncMock()
        records.check_notebook_similarity = AsyncMock(side_effect=RuntimeError("DB error"))
        rt = self._make_runtime(records_store=records)
        loop = self._make_proactive_loop(rt)

        agent = MagicMock()
        agent.callsign = "Chapel"
        agent.agent_type = "medical"

        text = "[NOTEBOOK fallback-test]Content that should still be written[/NOTEBOOK]"
        _, actions = await loop._extract_and_execute_actions(agent, text)

        records.write_notebook.assert_called_once()
        written = [a for a in actions if a["type"] == "notebook_write"]
        assert len(written) == 1

    @pytest.mark.asyncio
    async def test_suppressed_notebook_appears_in_actions(self):
        """Suppressed write produces notebook_suppressed action entry."""
        records = AsyncMock()
        records.check_notebook_similarity = AsyncMock(return_value={
            "action": "suppress",
            "reason": "similar content exists at notebooks/Chapel/other.md",
            "existing_path": "notebooks/Chapel/other.md",
            "existing_content": "overlapping content",
            "similarity": 0.88,
        })
        rt = self._make_runtime(records_store=records)
        loop = self._make_proactive_loop(rt)

        agent = MagicMock()
        agent.callsign = "Chapel"
        agent.agent_type = "medical"

        text = "[NOTEBOOK duplicate-topic]overlapping content[/NOTEBOOK]"
        _, actions = await loop._extract_and_execute_actions(agent, text)

        suppressed = [a for a in actions if a["type"] == "notebook_suppressed"]
        assert len(suppressed) == 1
        assert suppressed[0]["reason"] == "similar content exists at notebooks/Chapel/other.md"
        assert suppressed[0]["callsign"] == "Chapel"

    @pytest.mark.asyncio
    async def test_dedup_disabled_skips_check(self):
        """notebook_dedup_enabled=False → no dedup check, direct write."""
        records = AsyncMock()
        rt = self._make_runtime(records_store=records, dedup_enabled=False)
        loop = self._make_proactive_loop(rt)

        agent = MagicMock()
        agent.callsign = "Chapel"
        agent.agent_type = "medical"

        text = "[NOTEBOOK skip-dedup]Content written without dedup[/NOTEBOOK]"
        _, actions = await loop._extract_and_execute_actions(agent, text)

        records.check_notebook_similarity.assert_not_called()
        records.write_notebook.assert_called_once()


# ===========================================================================
# Self-monitoring context tests (3 tests)
# ===========================================================================

class TestSelfMonitoringContext:
    """Tests for AD-550 enhanced notebook context in self-monitoring."""

    def _make_proactive_loop(self, runtime):
        from probos.proactive import ProactiveCognitiveLoop
        loop = ProactiveCognitiveLoop(
            interval=60, cooldown=30, on_event=MagicMock(),
        )
        loop.set_runtime(runtime)
        return loop

    def _make_agent(self, callsign="Chapel", department="medical"):
        from probos.crew_profile import Rank
        agent = MagicMock()
        agent.callsign = callsign
        agent.id = f"{callsign.lower()}-001"
        agent.agent_type = callsign.lower()
        agent.department = department
        agent.rank = Rank.COMMANDER  # AUTONOMOUS tier → notebooks enabled
        return agent

    def _make_rt(self, records):
        rt = MagicMock()
        rt._records_store = records
        rt._start_time_wall = time.time()
        rt._lifecycle_state = "first_boot"
        # Ward room — needed by posts section, mock as None to skip
        rt.ward_room = None
        # Episodic memory — needed by memory_state section
        rt.episodic_memory = None
        # Trust network — needed by rank derivation (AD-552 fix)
        rt.trust_network = MagicMock()
        rt.trust_network.get_score = MagicMock(return_value=0.75)  # COMMANDER rank
        return rt

    @pytest.mark.asyncio
    async def test_notebook_index_includes_content_preview(self):
        """Context includes first 150 chars of each entry."""
        long_content = "A" * 200
        records = AsyncMock()
        records.list_entries = AsyncMock(return_value=[
            {"path": "notebooks/Chapel/vitals.md", "frontmatter": {
                "topic": "vitals", "updated": datetime.now(timezone.utc).isoformat(),
            }},
        ])
        records.read_entry = AsyncMock(return_value={
            "frontmatter": {"topic": "vitals"},
            "content": long_content,
            "path": "notebooks/Chapel/vitals.md",
        })
        records.search = AsyncMock(return_value=[])

        rt = self._make_rt(records)
        loop = self._make_proactive_loop(rt)
        agent = self._make_agent()

        ctx = await loop._build_self_monitoring_context(agent, "Chapel", rt)

        assert "notebook_index" in ctx
        entry = ctx["notebook_index"][0]
        assert "preview" in entry
        assert len(entry["preview"]) <= 150

    @pytest.mark.asyncio
    async def test_notebook_index_includes_recency(self):
        """Context includes human-readable recency."""
        two_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        records = AsyncMock()
        records.list_entries = AsyncMock(return_value=[
            {"path": "notebooks/Data/analysis.md", "frontmatter": {
                "topic": "analysis", "updated": two_hours_ago,
            }},
        ])
        records.read_entry = AsyncMock(return_value={
            "frontmatter": {"topic": "analysis"},
            "content": "Some analysis content",
            "path": "notebooks/Data/analysis.md",
        })
        records.search = AsyncMock(return_value=[])

        rt = self._make_rt(records)
        loop = self._make_proactive_loop(rt)
        agent = self._make_agent(callsign="Data", department="science")

        ctx = await loop._build_self_monitoring_context(agent, "Data", rt)

        assert "notebook_index" in ctx
        entry = ctx["notebook_index"][0]
        assert "recency" in entry
        assert "h ago" in entry["recency"]

    @pytest.mark.asyncio
    async def test_notebook_index_includes_entry_count(self):
        """Context includes total entry/topic counts."""
        now = datetime.now(timezone.utc).isoformat()
        records = AsyncMock()
        records.list_entries = AsyncMock(return_value=[
            {"path": "notebooks/Data/topic-a.md", "frontmatter": {"topic": "topic-a", "updated": now}},
            {"path": "notebooks/Data/topic-b.md", "frontmatter": {"topic": "topic-b", "updated": now}},
            {"path": "notebooks/Data/topic-c.md", "frontmatter": {"topic": "topic-c", "updated": now}},
        ])
        records.read_entry = AsyncMock(return_value={
            "frontmatter": {"topic": "topic-a"}, "content": "content", "path": "p",
        })
        records.search = AsyncMock(return_value=[])

        rt = self._make_rt(records)
        loop = self._make_proactive_loop(rt)
        agent = self._make_agent(callsign="Data", department="science")

        ctx = await loop._build_self_monitoring_context(agent, "Data", rt)

        assert "notebook_summary" in ctx
        assert ctx["notebook_summary"]["total_entries"] == 3
        assert ctx["notebook_summary"]["total_topics"] == 3


# ===========================================================================
# Configuration tests (2 tests)
# ===========================================================================

class TestRecordsConfigDedup:
    def test_records_config_dedup_defaults(self):
        """Default values match spec (threshold 0.8, staleness 72h, scan 20)."""
        config = RecordsConfig(repo_path="/tmp/test")
        assert config.notebook_dedup_enabled is True
        assert config.notebook_similarity_threshold == 0.8
        assert config.notebook_staleness_hours == 72.0
        assert config.notebook_max_scan_entries == 20

    def test_dedup_uses_configured_threshold(self, tmp_path):
        """Custom threshold propagates to check_notebook_similarity."""
        config = RecordsConfig(
            repo_path=str(tmp_path),
            notebook_similarity_threshold=0.9,
            notebook_staleness_hours=48.0,
            notebook_max_scan_entries=10,
        )
        assert config.notebook_similarity_threshold == 0.9
        assert config.notebook_staleness_hours == 48.0
        assert config.notebook_max_scan_entries == 10
