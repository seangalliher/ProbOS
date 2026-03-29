"""Tests for BF-072: Path traversal prevention in Ship's Records."""

from pathlib import Path

import pytest

from probos.config import RecordsConfig
from probos.knowledge.records_store import RecordsStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(tmp_path: Path):
    return RecordsConfig(
        repo_path=str(tmp_path / "ship-records"),
        enabled=True,
        auto_commit=False,  # Skip git for unit tests
    )


@pytest.fixture
async def store(tmp_path):
    cfg = _make_config(tmp_path)
    s = RecordsStore(cfg)
    await s.initialize()
    return s


# ===========================================================================
# _safe_path() unit tests
# ===========================================================================

class TestSafePath:

    @pytest.mark.asyncio
    async def test_allows_valid_relative_path(self, store):
        result = store._safe_path("notebooks/data/analysis.md")
        assert result.is_absolute()
        assert str(store._repo_path.resolve()) in str(result)

    @pytest.mark.asyncio
    async def test_blocks_dotdot_traversal(self, store):
        with pytest.raises(ValueError, match="Path traversal denied"):
            store._safe_path("../../etc/passwd")

    @pytest.mark.asyncio
    async def test_blocks_nested_traversal(self, store):
        with pytest.raises(ValueError, match="Path traversal denied"):
            store._safe_path("notebooks/../../secret.txt")

    @pytest.mark.asyncio
    async def test_allows_subdirectory_paths(self, store):
        result = store._safe_path("captains-log/2026-03-29.md")
        assert result.is_absolute()

    @pytest.mark.asyncio
    async def test_blocks_absolute_path_outside_repo(self, store):
        """Absolute paths that escape the repo should be rejected."""
        # On Windows, /etc/passwd resolves to C:\etc\passwd which is outside repo
        # On Linux, it resolves to /etc/passwd which is outside repo
        with pytest.raises(ValueError, match="Path traversal denied"):
            store._safe_path("/etc/passwd")


# ===========================================================================
# Method-level tests — traversal rejected
# ===========================================================================

class TestMethodTraversalBlocked:

    @pytest.mark.asyncio
    async def test_write_entry_rejects_traversal(self, store):
        with pytest.raises(ValueError, match="Path traversal denied"):
            await store.write_entry(
                author="captain",
                path="../../hack.md",
                content="malicious",
                message="test",
            )

    @pytest.mark.asyncio
    async def test_read_entry_rejects_traversal(self, store):
        with pytest.raises(ValueError, match="Path traversal denied"):
            await store.read_entry("../../etc/passwd", reader_id="captain")

    @pytest.mark.asyncio
    async def test_list_entries_rejects_traversal(self, store):
        with pytest.raises(ValueError, match="Path traversal denied"):
            await store.list_entries(directory="../../")

    @pytest.mark.asyncio
    async def test_write_notebook_rejects_traversal_in_callsign(self, store):
        with pytest.raises(ValueError, match="Path traversal denied"):
            await store.write_notebook(
                callsign="../../etc",
                topic_slug="hack",
                content="malicious",
            )

    @pytest.mark.asyncio
    async def test_publish_rejects_traversal(self, store):
        with pytest.raises(ValueError, match="Path traversal denied"):
            await store.publish("../../hack.md", author="captain")

    @pytest.mark.asyncio
    async def test_get_history_rejects_traversal(self, store):
        with pytest.raises(ValueError, match="Path traversal denied"):
            await store.get_history("../../etc/passwd")


# ===========================================================================
# Valid paths still work
# ===========================================================================

class TestValidPathsWork:

    @pytest.mark.asyncio
    async def test_write_and_read_valid_path(self, store):
        """Normal write + read should still work after _safe_path addition."""
        path = await store.write_entry(
            author="numberone",
            path="notebooks/numberone/test.md",
            content="Analysis complete.",
            message="test entry",
        )
        assert path == "notebooks/numberone/test.md"

        entry = await store.read_entry(path, reader_id="numberone")
        assert entry is not None
        assert entry["content"] == "Analysis complete."

    @pytest.mark.asyncio
    async def test_list_entries_valid_directory(self, store):
        """list_entries with a valid directory should work."""
        # Write an entry first
        await store.write_entry(
            author="captain",
            path="reports/status.md",
            content="All systems nominal.",
            message="status report",
        )
        entries = await store.list_entries(directory="reports")
        assert len(entries) >= 1

    @pytest.mark.asyncio
    async def test_write_notebook_valid(self, store):
        """write_notebook with valid callsign should work."""
        path = await store.write_notebook(
            callsign="data",
            topic_slug="analysis-1",
            content="Fascinating.",
        )
        assert path == "notebooks/data/analysis-1.md"
