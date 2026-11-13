"""BF-937 (#1678): approving a build in review answers that it is not merged, and where its candidate branch is kept.

The real route runs in the real app (``create_app``) over a real ``BuildQueue`` and a real ``BuildDispatcher``. The
worktree manager is a double that records every call, ``approve_and_merge`` is spied on, and the ways to start a
subprocess fail the case that reaches them. The answer is compared with
``ui/e2e/fixtures/bf937-queue-approve-unavailable.json``, the file the HXI test reads too. The class holds the cases the
unfixed tree fails; the functions before it pass on both. No BF-937 name is imported.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.build_dispatcher import BuildDispatcher
from probos.build_queue import BuildQueue
from probos.cognitive.builder import BuildResult, BuildSpec
from probos.runtime import ProbOSRuntime
from probos.worktree_manager import WorktreeManager

FIXTURE = Path(__file__).resolve().parents[1] / "ui" / "e2e" / "fixtures" / "bf937-queue-approve-unavailable.json"
BUILD_ID = "b7d41c09e2a1"
BRANCH = "builder-b7d41c09"  # WorktreeManager.create names the branch builder-<first 8 characters of the build id>
WORKTREE = "/work/ProbOS-builders/builder-b7d41c09"
COMMIT = "9f2c1ab"
APPROVE = "/api/build/queue/approve"


def _world(status: str = "reviewing", *, dispatcher: bool = True) -> SimpleNamespace:
    """One build in the queue (in review, or still queued), the real dispatcher over a recording manager, the real app."""
    from probos.api import create_app

    queue = BuildQueue()
    build = queue.enqueue(BuildSpec(title="Candidate build", description="a change"))
    build.id = BUILD_ID  # the queue minted another id; the fixture names this one
    if status == "reviewing":
        assert queue.update_status(BUILD_ID, "dispatched"), "premise: queued -> dispatched"
        assert queue.update_status(BUILD_ID, "building", worktree_path=WORKTREE), "premise: dispatched -> building"
        assert queue.update_status(
            BUILD_ID,
            "reviewing",
            result=BuildResult(success=True, spec=build.spec, branch_name=BRANCH, commit_hash=COMMIT),
        ), "premise: building -> reviewing"
    worktrees = MagicMock(spec=WorktreeManager)
    worktrees.merge_to_main = AsyncMock(return_value=(False, "refused"))
    worktrees.remove = AsyncMock(return_value=True)
    real = BuildDispatcher(queue=queue, worktree_mgr=worktrees)
    approve = AsyncMock(wraps=real.approve_and_merge)
    real.approve_and_merge = approve
    runtime = MagicMock(spec=ProbOSRuntime)
    runtime.build_queue = queue
    runtime.build_dispatcher = real if dispatcher else None
    runtime.emit_event = MagicMock()
    app = create_app(runtime)
    return SimpleNamespace(
        client=TestClient(app), app=app, runtime=runtime, build=build, worktrees=worktrees, approve=approve,
    )


@pytest.mark.parametrize(
    ("status", "asked"),
    [("queued", BUILD_ID), ("reviewing", "no-such-build")],
    ids=["queued", "unknown-id"],
)
def test_a_build_not_in_review_is_answered_as_before(status: str, asked: str) -> None:
    world = _world(status)

    resp = world.client.post(APPROVE, json={"build_id": asked})

    assert resp.status_code == 200
    assert resp.json() == {"status": "error", "message": f"Build {asked} not in reviewing status"}


def test_a_dispatcher_that_is_not_running_is_answered_as_before() -> None:
    world = _world("reviewing", dispatcher=False)
    assert world.build.status == "reviewing", "premise: the queue holds a build in review"

    resp = world.client.post(APPROVE, json={"build_id": BUILD_ID})

    assert resp.json() == {"status": "error", "message": "Build dispatcher not running"}


def test_reject_still_discards_the_build_in_review() -> None:
    """Control: the same app, queue and dispatcher still reject a build in review, so the cases below run in a live world."""
    world = _world()

    resp = world.client.post("/api/build/queue/reject", json={"build_id": BUILD_ID})

    assert resp.json() == {"status": "ok", "message": "Build rejected"}
    world.worktrees.remove.assert_awaited_once_with(BUILD_ID)
    assert world.build.status == "failed"


@pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-937 S1 M2: the route answers not merged, typed (#1678)")
class TestApprovingABuildInReviewAnswersNotMerged:
    def test_the_answer_is_the_typed_not_merged_result_the_hxi_test_reads(self) -> None:
        world = _world()

        resp = world.client.post(APPROVE, json={"build_id": BUILD_ID})

        assert resp.status_code == 200, "premise: the route answered"
        assert resp.headers["content-type"].startswith("application/json"), "premise: a JSON body"
        assert resp.json() == json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_nothing_is_merged_and_no_process_is_started(self, monkeypatch: pytest.MonkeyPatch) -> None:
        world = _world()

        def refuse(*args: object, **kwargs: object) -> None:
            raise AssertionError("approving a build in review must start no process")

        async def refuse_async(*args: object, **kwargs: object) -> None:
            raise AssertionError("approving a build in review must start no process")

        monkeypatch.setattr(subprocess, "Popen", refuse)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", refuse_async)

        resp = world.client.post(APPROVE, json={"build_id": BUILD_ID})

        assert resp.status_code == 200, "premise: the route answered"
        world.approve.assert_not_awaited()
        world.worktrees.merge_to_main.assert_not_awaited()
        assert world.worktrees.mock_calls == []
        assert world.build.status == "reviewing"
        world.runtime.emit_event.assert_not_called()

    def test_the_route_no_longer_describes_a_merge(self) -> None:
        world = _world()
        route = next(r for r in world.app.routes if getattr(r, "path", "") == APPROVE)

        description = route.description.lower()

        assert "merge worktree to main" not in description
        assert "not merged" in description
