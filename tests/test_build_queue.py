"""Tests for BuildQueue (AD-371)."""

from __future__ import annotations

import time

import pytest

from probos.build_queue import BuildQueue, QueuedBuild
from probos.cognitive.builder import BuildSpec


def _spec(title: str = "test", target_files: list[str] | None = None) -> BuildSpec:
    return BuildSpec(
        title=title,
        description="test description",
        target_files=target_files or [],
    )


class TestBuildQueue:
    def test_enqueue_assigns_id(self) -> None:
        """Enqueue returns a QueuedBuild with a UUID and correct status."""
        q = BuildQueue()
        build = q.enqueue(_spec("build it"))
        assert isinstance(build, QueuedBuild)
        assert len(build.id) == 12
        assert build.status == "queued"
        assert build.spec.title == "build it"
        assert build.created_at > 0

    def test_dequeue_priority_order(self) -> None:
        """Higher priority (lower number) items dequeue first."""
        q = BuildQueue()
        q.enqueue(_spec("low"), priority=10)
        q.enqueue(_spec("high"), priority=1)
        q.enqueue(_spec("mid"), priority=5)
        build = q.dequeue()
        assert build is not None
        assert build.spec.title == "high"

    def test_dequeue_fifo_same_priority(self) -> None:
        """Same priority items dequeue in FIFO order."""
        q = BuildQueue()
        b1 = q.enqueue(_spec("first"), priority=5)
        b2 = q.enqueue(_spec("second"), priority=5)
        build = q.dequeue()
        assert build is not None
        assert build.id == b1.id

    def test_dequeue_empty_returns_none(self) -> None:
        """Empty queue returns None."""
        q = BuildQueue()
        assert q.dequeue() is None

    def test_update_status_valid_transition(self) -> None:
        """queued → dispatched is valid."""
        q = BuildQueue()
        build = q.enqueue(_spec())
        ok = q.update_status(build.id, "dispatched")
        assert ok is True
        assert build.status == "dispatched"

    def test_update_status_invalid_transition(self) -> None:
        """queued → merged is invalid, returns False."""
        q = BuildQueue()
        build = q.enqueue(_spec())
        ok = q.update_status(build.id, "merged")
        assert ok is False
        assert build.status == "queued"

    def test_update_status_sets_kwargs(self) -> None:
        """update_status(..., worktree_path='/tmp/wt') sets the field."""
        q = BuildQueue()
        build = q.enqueue(_spec())
        q.update_status(build.id, "dispatched", worktree_path="/tmp/wt", builder_id="b1")
        assert build.worktree_path == "/tmp/wt"
        assert build.builder_id == "b1"

    def test_cancel_queued_build(self) -> None:
        """Cancel sets status to failed with 'cancelled' error."""
        q = BuildQueue()
        build = q.enqueue(_spec())
        ok = q.cancel(build.id)
        assert ok is True
        assert build.status == "failed"
        assert build.error == "cancelled"
        assert build.completed_at is not None

    def test_cancel_non_queued_returns_false(self) -> None:
        """Cannot cancel a build that's already dispatched."""
        q = BuildQueue()
        build = q.enqueue(_spec())
        q.update_status(build.id, "dispatched")
        ok = q.cancel(build.id)
        assert ok is False
        assert build.status == "dispatched"

    def test_has_footprint_conflict_overlap(self) -> None:
        """Detects overlapping file footprint with active builds."""
        q = BuildQueue()
        build = q.enqueue(_spec(target_files=["a.py", "b.py"]))
        q.update_status(build.id, "dispatched")
        assert q.has_footprint_conflict(["b.py", "c.py"]) is True

    def test_has_footprint_conflict_no_overlap(self) -> None:
        """No conflict when files don't overlap."""
        q = BuildQueue()
        build = q.enqueue(_spec(target_files=["a.py", "b.py"]))
        q.update_status(build.id, "dispatched")
        assert q.has_footprint_conflict(["c.py", "d.py"]) is False

    def test_get_by_status(self) -> None:
        """Returns only builds matching the requested status."""
        q = BuildQueue()
        b1 = q.enqueue(_spec("one"))
        b2 = q.enqueue(_spec("two"))
        q.update_status(b1.id, "dispatched")
        assert len(q.get_by_status("queued")) == 1
        assert q.get_by_status("queued")[0].id == b2.id
        assert len(q.get_by_status("dispatched")) == 1
        assert q.get_by_status("dispatched")[0].id == b1.id

    def test_active_count(self) -> None:
        """active_count reflects dispatched + building builds."""
        q = BuildQueue()
        b1 = q.enqueue(_spec("one"))
        b2 = q.enqueue(_spec("two"))
        assert q.active_count == 0
        q.update_status(b1.id, "dispatched")
        assert q.active_count == 1
        q.update_status(b1.id, "building")
        q.update_status(b2.id, "dispatched")
        assert q.active_count == 2

    def test_file_footprint_defaults_to_target_files(self) -> None:
        """If file_footprint not provided, uses spec.target_files."""
        q = BuildQueue()
        build = q.enqueue(_spec(target_files=["src/foo.py", "src/bar.py"]))
        assert build.file_footprint == ["src/foo.py", "src/bar.py"]
