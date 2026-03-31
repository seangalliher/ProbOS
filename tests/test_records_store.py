"""Tests for Ship's Records — Git-backed instance knowledge store (AD-434)."""

import asyncio
import inspect
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from probos.runtime import ProbOSRuntime
from probos.substrate.agent import BaseAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(tmp_path: Path, **overrides):
    """Create a RecordsConfig-like object pointing at tmp_path."""
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
def records_config(tmp_path):
    return _make_config(tmp_path)


@pytest.fixture
async def store(records_config):
    from probos.knowledge.records_store import RecordsStore
    s = RecordsStore(records_config)
    await s.initialize()
    return s


# ---------------------------------------------------------------------------
# 1. test_initialize_creates_repo
# ---------------------------------------------------------------------------

class TestInitialize:
    @pytest.mark.asyncio
    async def test_initialize_creates_repo(self, store):
        """Verify git repo + subdirectories created."""
        repo = store.repo_path
        assert repo.exists()
        assert (repo / ".git").exists()
        for subdir in ("captains-log", "notebooks", "reports", "duty-logs",
                       "operations", "manuals", "_archived"):
            assert (repo / subdir).exists(), f"Missing subdir: {subdir}"
        # .shiprecords.yaml should exist
        assert (repo / ".shiprecords.yaml").exists()


# ---------------------------------------------------------------------------
# 2-3. Write entry tests
# ---------------------------------------------------------------------------

class TestWriteEntry:
    @pytest.mark.asyncio
    async def test_write_entry_creates_file_with_frontmatter(self, store):
        """Write an entry, read back, verify YAML frontmatter fields."""
        path = await store.write_entry(
            author="bones",
            path="reports/med-report.md",
            content="Patient is stable.",
            message="Medical report",
            classification="department",
            department="medical",
            topic="med-report",
            tags=["medical", "routine"],
        )
        assert path == "reports/med-report.md"
        file_path = store.repo_path / path
        assert file_path.exists()
        raw = file_path.read_text(encoding="utf-8")
        assert raw.startswith("---")
        # Parse frontmatter
        parts = raw.split("---", 2)
        fm = yaml.safe_load(parts[1])
        assert fm["author"] == "bones"
        assert fm["classification"] == "department"
        assert fm["status"] == "draft"
        assert fm["department"] == "medical"
        assert fm["topic"] == "med-report"
        assert "medical" in fm["tags"]
        assert "Patient is stable." in parts[2]

    @pytest.mark.asyncio
    async def test_write_entry_commits_to_git(self, store):
        """Write an entry, verify git log shows the commit."""
        await store.write_entry(
            author="laforge",
            path="reports/engine-report.md",
            content="Warp core nominal.",
            message="Engine status",
        )
        history = await store.get_history("reports/engine-report.md")
        assert len(history) >= 1
        assert "Engine status" in history[0]["message"]

    @pytest.mark.asyncio
    async def test_write_entry_invalid_classification(self, store):
        """Invalid classification raises ValueError."""
        with pytest.raises(ValueError, match="Invalid classification"):
            await store.write_entry(
                author="test",
                path="reports/bad.md",
                content="...",
                message="bad",
                classification="top_secret",
            )


# ---------------------------------------------------------------------------
# 4-5. Captain's Log tests
# ---------------------------------------------------------------------------

class TestCaptainsLog:
    @pytest.mark.asyncio
    async def test_captains_log_append_only(self, store):
        """Append two entries to same day, verify both present."""
        path1 = await store.append_captains_log("First entry.")
        path2 = await store.append_captains_log("Second entry.")
        assert path1 == path2  # Same daily file
        raw = (store.repo_path / path1).read_text(encoding="utf-8")
        assert "First entry." in raw
        assert "Second entry." in raw

    @pytest.mark.asyncio
    async def test_captains_log_daily_files(self, store):
        """Verify daily file naming pattern."""
        path = await store.append_captains_log("Test entry.")
        # Should match captains-log/YYYY-MM-DD.md pattern
        assert re.match(r"captains-log/\d{4}-\d{2}-\d{2}\.md", path)


# ---------------------------------------------------------------------------
# 6. Notebook tests
# ---------------------------------------------------------------------------

class TestNotebook:
    @pytest.mark.asyncio
    async def test_write_notebook(self, store):
        """Write notebook entry, verify path is notebooks/{callsign}/{topic}.md."""
        path = await store.write_notebook(
            callsign="bones",
            topic_slug="treatment-outcomes",
            content="Observed improvement in patient recovery times.",
            department="medical",
            tags=["treatment-outcomes"],
        )
        assert path == "notebooks/bones/treatment-outcomes.md"
        assert (store.repo_path / path).exists()


# ---------------------------------------------------------------------------
# 7-9. Classification access control tests
# ---------------------------------------------------------------------------

class TestClassification:
    @pytest.mark.asyncio
    async def test_read_entry_classification_private(self, store):
        """Private doc readable by author, denied for others."""
        await store.write_entry(
            author="bones",
            path="notebooks/bones/private-notes.md",
            content="Private medical notes.",
            message="Private notes",
            classification="private",
        )
        # Author can read
        result = await store.read_entry("notebooks/bones/private-notes.md", reader_id="bones")
        assert result is not None
        assert "Private medical notes." in result["content"]
        # Others cannot
        result = await store.read_entry("notebooks/bones/private-notes.md", reader_id="laforge")
        assert result is None

    @pytest.mark.asyncio
    async def test_read_entry_classification_department(self, store):
        """Department doc readable by same dept, denied for other dept."""
        await store.write_entry(
            author="bones",
            path="reports/dept-report.md",
            content="Department report.",
            message="Dept report",
            classification="department",
            department="medical",
        )
        # Same department can read
        result = await store.read_entry(
            "reports/dept-report.md", reader_id="ogawa", reader_department="medical"
        )
        assert result is not None
        # Different department cannot
        result = await store.read_entry(
            "reports/dept-report.md", reader_id="laforge", reader_department="engineering"
        )
        assert result is None
        # Author can always read their own
        result = await store.read_entry("reports/dept-report.md", reader_id="bones")
        assert result is not None

    @pytest.mark.asyncio
    async def test_read_entry_classification_ship(self, store):
        """Ship doc readable by all."""
        await store.write_entry(
            author="captain",
            path="reports/ship-wide.md",
            content="Ship-wide announcement.",
            message="Ship announcement",
            classification="ship",
        )
        result = await store.read_entry("reports/ship-wide.md", reader_id="anyone")
        assert result is not None

    @pytest.mark.asyncio
    async def test_read_entry_not_found(self, store):
        """Non-existent entry returns None."""
        result = await store.read_entry("nonexistent.md", reader_id="captain")
        assert result is None


# ---------------------------------------------------------------------------
# 10-11. List entries tests
# ---------------------------------------------------------------------------

class TestListEntries:
    @pytest.mark.asyncio
    async def test_list_entries_with_filters(self, store):
        """List with author, status, tag filters."""
        await store.write_entry(
            author="bones", path="reports/r1.md", content="R1",
            message="R1", status="draft", tags=["medical"],
        )
        await store.write_entry(
            author="laforge", path="reports/r2.md", content="R2",
            message="R2", status="published", tags=["engineering"],
        )
        # Filter by author
        results = await store.list_entries(author="bones")
        assert len(results) >= 1
        assert all(e["frontmatter"]["author"] == "bones" for e in results)
        # Filter by status
        results = await store.list_entries(status="published")
        assert all(e["frontmatter"]["status"] == "published" for e in results)
        # Filter by tags
        results = await store.list_entries(tags=["medical"])
        assert all("medical" in e["frontmatter"].get("tags", []) for e in results)

    @pytest.mark.asyncio
    async def test_list_entries_excludes_archived(self, store):
        """Entries in _archived/ not returned."""
        # Create a file in _archived
        archived_path = store.repo_path / "_archived" / "old.md"
        archived_path.write_text("---\nauthor: test\n---\nOld content.", encoding="utf-8")
        results = await store.list_entries()
        paths = [e["path"] for e in results]
        assert not any(p.startswith("_archived/") for p in paths)


# ---------------------------------------------------------------------------
# 12-13. Publish tests
# ---------------------------------------------------------------------------

class TestPublish:
    @pytest.mark.asyncio
    async def test_publish_changes_status(self, store):
        """Publish a draft, verify status changed to 'published'."""
        await store.write_entry(
            author="bones", path="reports/draft.md", content="Draft content.",
            message="Draft", status="draft",
        )
        await store.publish("reports/draft.md", author="bones")
        result = await store.read_entry("reports/draft.md", reader_id="bones")
        assert result["frontmatter"]["status"] == "published"

    @pytest.mark.asyncio
    async def test_publish_permission_denied(self, store):
        """Non-author/non-captain cannot publish."""
        await store.write_entry(
            author="bones", path="reports/draft2.md", content="Draft.",
            message="Draft2",
        )
        with pytest.raises(PermissionError):
            await store.publish("reports/draft2.md", author="laforge")

    @pytest.mark.asyncio
    async def test_publish_captain_can_publish(self, store):
        """Captain can publish anyone's doc."""
        await store.write_entry(
            author="bones", path="reports/draft3.md", content="Draft.",
            message="Draft3",
        )
        await store.publish("reports/draft3.md", author="captain")
        result = await store.read_entry("reports/draft3.md", reader_id="captain")
        assert result["frontmatter"]["status"] == "published"

    @pytest.mark.asyncio
    async def test_publish_not_found(self, store):
        """Publish non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            await store.publish("nonexistent.md", author="captain")


# ---------------------------------------------------------------------------
# 14-15. Search tests
# ---------------------------------------------------------------------------

class TestSearch:
    @pytest.mark.asyncio
    async def test_search_keyword(self, store):
        """Search returns matching documents ranked by relevance."""
        await store.write_entry(
            author="bones", path="reports/warp.md",
            content="Warp core temperature is elevated.",
            message="Warp report",
        )
        await store.write_entry(
            author="laforge", path="reports/shields.md",
            content="Shield harmonics within normal range.",
            message="Shield report",
        )
        results = await store.search("warp temperature")
        assert len(results) >= 1
        assert results[0]["path"] == "reports/warp.md"

    @pytest.mark.asyncio
    async def test_search_respects_classification(self, store):
        """Search with scope='department' doesn't return fleet docs."""
        await store.write_entry(
            author="admiral", path="reports/fleet-wide.md",
            content="Fleet operations update.",
            message="Fleet update", classification="fleet",
        )
        # Scope=department (level 1) should not see fleet (level 3)
        results = await store.search("fleet operations", scope="department")
        fleet_paths = [r["path"] for r in results if r["path"] == "reports/fleet-wide.md"]
        assert len(fleet_paths) == 0


# ---------------------------------------------------------------------------
# 16. History tests
# ---------------------------------------------------------------------------

class TestHistory:
    @pytest.mark.asyncio
    async def test_get_history(self, store):
        """Write multiple versions, verify history returns commits."""
        await store.write_entry(
            author="bones", path="reports/evolving.md",
            content="Version 1", message="v1",
        )
        await store.write_entry(
            author="bones", path="reports/evolving.md",
            content="Version 2", message="v2",
        )
        history = await store.get_history("reports/evolving.md")
        assert len(history) >= 2


# ---------------------------------------------------------------------------
# 17. Stats tests
# ---------------------------------------------------------------------------

class TestStats:
    @pytest.mark.asyncio
    async def test_get_stats(self, store):
        """Verify document counts and commit count."""
        await store.write_entry(
            author="bones", path="reports/stats-test.md",
            content="Test.", message="Stats test",
        )
        stats = await store.get_stats()
        assert stats["total_documents"] >= 1
        assert stats["total_commits"] >= 1
        assert isinstance(stats["directories"], dict)
        assert stats["repo_path"] == str(store.repo_path)


# ---------------------------------------------------------------------------
# 18-19. Parse document tests
# ---------------------------------------------------------------------------

class TestParseDocument:
    def test_parse_document_with_frontmatter(self):
        """Valid YAML frontmatter parsed correctly."""
        from probos.knowledge.records_store import RecordsStore
        store = RecordsStore.__new__(RecordsStore)
        raw = "---\nauthor: bones\nstatus: draft\n---\n\nBody content here."
        fm, content = store._parse_document(raw)
        assert fm["author"] == "bones"
        assert fm["status"] == "draft"
        assert content == "Body content here."

    def test_parse_document_without_frontmatter(self):
        """Plain markdown returns empty frontmatter."""
        from probos.knowledge.records_store import RecordsStore
        store = RecordsStore.__new__(RecordsStore)
        raw = "Just plain markdown content."
        fm, content = store._parse_document(raw)
        assert fm == {}
        assert content == "Just plain markdown content."


# ---------------------------------------------------------------------------
# 20. Meta-test: no duplicate count_for_agent (reused from BF-039 concern)
# ---------------------------------------------------------------------------

class TestMetaIntegrity:
    def test_no_duplicate_method_definitions(self):
        """Verify no duplicate method definitions in records_store.py."""
        from probos.knowledge import records_store
        source = inspect.getsource(records_store)
        methods = re.findall(r'def (\w+)\(', source)
        # Check for duplicates
        seen = set()
        duplicates = []
        for m in methods:
            if m in seen:
                duplicates.append(m)
            seen.add(m)
        assert not duplicates, f"Duplicate method definitions: {duplicates}"


# ---------------------------------------------------------------------------
# 21. Runtime integration test
# ---------------------------------------------------------------------------

class TestRuntimeIntegration:
    def test_runtime_has_records_store_property(self):
        """Verify Runtime class has records_store property."""
        from probos.runtime import ProbOSRuntime
        assert hasattr(ProbOSRuntime, 'records_store')

    def test_config_has_records_field(self):
        """Verify SystemConfig has records field."""
        from probos.config import SystemConfig
        cfg = SystemConfig()
        assert hasattr(cfg, 'records')
        assert cfg.records.enabled is True


# ---------------------------------------------------------------------------
# 22. Proactive notebook tag extraction test
# ---------------------------------------------------------------------------

class TestProactiveNotebookTag:
    @pytest.mark.asyncio
    async def test_proactive_notebook_tag_extraction(self):
        """Proactive thought with [NOTEBOOK topic]...[/NOTEBOOK] creates a notebook entry."""
        from probos.proactive import ProactiveCognitiveLoop

        rt = MagicMock(spec=ProbOSRuntime)
        rt._records_store = AsyncMock()
        rt._records_store.write_notebook = AsyncMock(return_value="notebooks/bones/analysis.md")
        rt._ontology = None
        rt.ontology = None
        rt.ward_room = MagicMock()
        rt.ward_room.get_endorsements_for = AsyncMock(return_value=[])
        rt.trust_network = MagicMock()
        rt.trust_network.get_score = MagicMock(return_value=0.9)
        rt.ward_room_router = MagicMock()
        rt.ward_room_router.extract_endorsements = MagicMock(return_value=(None, []))

        loop = ProactiveCognitiveLoop(interval=60)
        loop._runtime = rt

        agent = MagicMock(spec=BaseAgent)
        agent.id = "test-agent"
        agent.callsign = "Bones"
        agent.agent_type = "medical"

        text = (
            "I noticed elevated readings in sickbay.\n"
            "[NOTEBOOK treatment-analysis]"
            "Detailed analysis of treatment outcomes over the past 24 hours.\n"
            "Recovery rates improved by 12% after protocol adjustment."
            "[/NOTEBOOK]"
        )

        cleaned, actions = await loop._extract_and_execute_actions(agent, text)

        # Notebook write should have been called
        rt._records_store.write_notebook.assert_called_once()
        call_kwargs = rt._records_store.write_notebook.call_args
        assert call_kwargs.kwargs.get("callsign") == "Bones" or call_kwargs[1].get("callsign") == "Bones"
        assert "treatment-analysis" in str(call_kwargs)
        # NOTEBOOK tags should be removed from output text
        assert "[NOTEBOOK" not in cleaned
        assert "[/NOTEBOOK]" not in cleaned
        # Action should be recorded
        assert any(a["type"] == "notebook_write" for a in actions)
