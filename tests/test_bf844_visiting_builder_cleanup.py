"""BF-844 (#1314): the visiting-builder temp tree is not removed one-shot.

`BuilderAgent.perceive` hands its `probos_build_*` temp tree to the Copilot SDK
client as that client's **cwd** (`copilot_adapter.py`, `client_opts["cwd"]`).
A one-shot ``shutil.rmtree(tmp_dir, ignore_errors=True)`` cannot remove a
directory a live descendant holds on Windows, and reports nothing when it
fails.

Reproduced against the real mechanism before the fix -- a real child process
whose cwd IS the tree, with the probe asserting its own premise so that
"removal failed" could not be confused with "the setup never held it"::

    PREMISE child_alive=True
    PREMISE child_cwd_is_tmp=True
    ONESHOT_WHILE_HELD   survived=True  raised=None      <- silent
    CHILD_EXITED=True
    AFTER_CHILD_EXIT     survived=True                   <- the leak
    AFTER_remove_workdir survived=False
    CONTROL_HELD         survived=True  warned=True      <- gives up loudly

The leak outlives the holder because nothing retries: the single attempt has
already been spent by the time the descendant lets go.

Evidence limit, stated rather than glossed: `github-copilot-sdk` is not
installed in this environment (``find_spec('copilot') is None``), so the real
`CopilotClient` was never driven and it is NOT established that its descendants
outlive `adapter.stop()`. What is established is the mechanism at this call
site's exact shape. The fix is chosen to be correct either way -- when nothing
holds the tree `remove_workdir` removes it on the first attempt (measured
0.3 ms), so this can only ever behave better than the one-shot, never worse.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive import builder as builder_module
from probos.cognitive import copilot_adapter as adapter_module
from probos.cognitive.builder import BuilderAgent
from probos.execution import isolation as iso
from probos.execution.isolation import _still_present
from probos.runtime import ProbOSRuntime


class _StubbornRmtree:
    """A ``rmtree`` that refuses ``fail_times`` times, then really removes.

    Stands in deterministically for a Windows descendant holding the tree.
    ``ignore_errors=True`` means the real call reports nothing when it fails,
    so refusing silently is exactly the production failure.
    """

    def __init__(self, fail_times: int) -> None:
        self._remaining = fail_times
        self._real = shutil.rmtree
        self.calls = 0

    def __call__(self, path: Any, *args: Any, **kwargs: Any) -> None:
        self.calls += 1
        if self._remaining > 0:
            self._remaining -= 1
            return
        self._real(path, ignore_errors=True)


class _Result:
    def __init__(self, success: bool) -> None:
        self.success = success
        self.file_blocks = [{"path": "a.py", "mode": "create", "content": "x = 1\n"}] if success else []
        self.raw_output = "out"
        self.error = None if success else "boom"


class _FakeAdapter:
    """Stands in for `CopilotBuilderAdapter`; records the cwd it was given."""

    last: _FakeAdapter | None = None

    def __init__(self, *, cwd: str = "", stop_raises: bool = False, **_kw: Any) -> None:
        self.cwd = cwd
        self._stop_raises = stop_raises
        self.stopped = False
        type(self).last = self

    async def start(self) -> None:
        return None

    async def execute(self, _spec: Any, _files: Any) -> _Result:
        return _Result(success=True)

    async def stop(self) -> None:
        self.stopped = True
        if self._stop_raises:
            raise RuntimeError("SDK client would not shut down")


def _agent() -> BuilderAgent:
    return BuilderAgent(
        agent_id="builder-bf844",
        llm_client=MagicMock(),
        runtime=MagicMock(spec=ProbOSRuntime),
    )


def _install_adapter(
    monkeypatch: pytest.MonkeyPatch, *, stop_raises: bool = False
) -> type[_FakeAdapter]:
    _FakeAdapter.last = None

    def _factory(**kw: Any) -> _FakeAdapter:
        return _FakeAdapter(stop_raises=stop_raises, **kw)

    monkeypatch.setattr(adapter_module, "CopilotBuilderAdapter", _factory)
    return _FakeAdapter


async def _run_perceive(agent: BuilderAgent, target: Path) -> dict:
    return await agent.perceive(
        {
            "intent": "build_code",
            "params": {
                "title": "t",
                "description": "d",
                "target_files": [str(target)],
                "force_visiting": True,
            },
        }
    )


# ---------------------------------------------------------------------------
# 1. The tree is removed through the retrying remover, not one-shot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_held_temp_tree_is_retried_until_it_can_be_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: the first two removals are silent no-ops, as when a descendant
    # holds the tree as its cwd.
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    _install_adapter(monkeypatch)
    stubborn = _StubbornRmtree(fail_times=2)
    monkeypatch.setattr(iso.shutil, "rmtree", stubborn)
    monkeypatch.setattr(iso.time, "sleep", lambda _s: None)

    # Act
    await _run_perceive(_agent(), target)

    # Assert: the tree the SDK was given as cwd is gone, and it took more than
    # one attempt. The pre-fix one-shot would have called exactly once and left
    # the directory behind.
    assert _FakeAdapter.last is not None
    tmp_dir = Path(_FakeAdapter.last.cwd)
    assert tmp_dir.name.startswith("probos_build_"), tmp_dir
    assert not _still_present(tmp_dir)
    assert stubborn.calls >= 3, f"expected retries, got {stubborn.calls}"


@pytest.mark.asyncio
async def test_one_attempt_is_genuinely_defeated_by_the_stub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Counter-case: proves the RETRY is what does the work.

    Without this the test above would still pass if the stub were ineffective
    and the very first attempt had simply succeeded.
    """
    # Arrange
    held = tmp_path / "held"
    held.mkdir()
    (held / "payload.txt").write_text("data", encoding="utf-8")
    stubborn = _StubbornRmtree(fail_times=2)
    monkeypatch.setattr(iso.shutil, "rmtree", stubborn)

    # Act: one attempt, the pre-BF-844 shape.
    iso.shutil.rmtree(held, ignore_errors=True)

    # Assert
    assert _still_present(held)
    assert stubborn.calls == 1


@pytest.mark.asyncio
async def test_an_unremovable_temp_tree_gives_up_loudly_instead_of_silently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange: never removable -- a descendant that outlives every attempt.
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    _install_adapter(monkeypatch)
    stubborn = _StubbornRmtree(fail_times=10_000)
    monkeypatch.setattr(iso.shutil, "rmtree", stubborn)
    monkeypatch.setattr(iso.time, "sleep", lambda _s: None)

    # Act: must not raise out of a `finally` on the perceive path.
    with caplog.at_level(logging.WARNING, logger=iso.logger.name):
        await _run_perceive(_agent(), target)

    # Assert: still there, and the operator is TOLD -- from that logger, naming
    # the path. A bare "some warning happened" would pass on an unrelated record.
    assert _FakeAdapter.last is not None
    tmp_dir = Path(_FakeAdapter.last.cwd)
    assert _still_present(tmp_dir)
    ours = [
        r for r in caplog.records
        if r.name == iso.logger.name and r.levelno >= logging.WARNING
    ]
    assert ours, f"expected a warning from {iso.logger.name}; got {caplog.records!r}"
    joined = " ".join(r.getMessage() for r in ours)
    assert str(tmp_dir) in joined, "the warning must name the directory"
    assert "may remain" in joined.lower()

    # Cleanup through the stub's CAPTURED real callable. `iso.shutil is shutil`,
    # so calling `shutil.rmtree` here would re-enter the stub and leak the tree.
    stubborn._real(tmp_dir, ignore_errors=True)
    assert not _still_present(tmp_dir), "the test must not leak a probos_build_ tree"


@pytest.mark.asyncio
async def test_a_free_temp_tree_is_still_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The common path -- nothing holding the tree -- must still work."""
    # Arrange
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    _install_adapter(monkeypatch)

    # Act
    await _run_perceive(_agent(), target)

    # Assert
    assert _FakeAdapter.last is not None
    assert not _still_present(Path(_FakeAdapter.last.cwd))


# ---------------------------------------------------------------------------
# 2. The removal does not freeze the event loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_removal_does_not_stall_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `finally` runs on the loop; the ~9s retry budget must not run there.

    Measured over the removal's OWN window rather than over the whole call. A
    heartbeat-max-gap assertion passes trivially when every sample predates the
    block, so this counts heartbeat ticks that land strictly INSIDE
    ``[removal_start, removal_end]`` -- which is zero if the loop was frozen,
    and cannot be satisfied by samples taken before cleanup began.
    """
    # Arrange
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    _install_adapter(monkeypatch)

    real_rmtree = shutil.rmtree
    window: list[float] = []
    block = 0.25

    def _slow(path: Any, *a: Any, **kw: Any) -> None:
        window.append(time.perf_counter())
        time.sleep(block)
        real_rmtree(path, ignore_errors=True)
        window.append(time.perf_counter())

    monkeypatch.setattr(iso.shutil, "rmtree", _slow)

    ticks: list[float] = []

    async def _heartbeat() -> None:
        while True:
            await asyncio.sleep(0.01)
            ticks.append(time.perf_counter())

    beat = asyncio.create_task(_heartbeat())
    try:
        # Act
        await _run_perceive(_agent(), target)
    finally:
        beat.cancel()
        try:
            await beat
        except asyncio.CancelledError:
            pass

    # Premise: the removal really did block for the full window. Without this,
    # "the loop kept ticking" would be true of a removal that never blocked.
    assert len(window) == 2, f"the slow remover did not run: {window!r}"
    start, end = window
    assert end - start >= block, f"window too short to discriminate: {end - start:.3f}s"

    # Assert: the loop ran DURING the blocking removal, and the tree is gone.
    inside = [t for t in ticks if start <= t <= end]
    assert len(inside) >= 2, (
        f"event loop stalled: {len(inside)} heartbeat ticks inside a "
        f"{end - start:.3f}s removal window (expected ~{int(block / 0.01)})"
    )
    assert _FakeAdapter.last is not None
    assert not _still_present(Path(_FakeAdapter.last.cwd))


# ---------------------------------------------------------------------------
# 3. adapter.stop() failure has a stated consequence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_adapter_stop_is_reported_and_cleanup_still_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`stop()` failing means a descendant may still hold the cwd -- say so.

    It was logged at DEBUG as "(ignored)", which is invisible at the default
    level and states the opposite of the consequence: the failure is precisely
    the condition under which the removal below is expected to need its
    retries. Cleanup still proceeds, because refusing to clean up beside a
    possibly-live client guarantees the leak instead of risking it.
    """
    # Arrange
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    _install_adapter(monkeypatch, stop_raises=True)

    # Act
    with caplog.at_level(logging.WARNING, logger=builder_module.logger.name):
        obs = await _run_perceive(_agent(), target)

    # Assert: the failure surfaced at WARNING from the builder's own logger,
    # naming the tree, and the tree was still removed.
    assert _FakeAdapter.last is not None
    assert _FakeAdapter.last.stopped is True
    tmp_dir = Path(_FakeAdapter.last.cwd)
    ours = [
        r for r in caplog.records
        if r.name == builder_module.logger.name and r.levelno >= logging.WARNING
    ]
    assert ours, f"expected a WARNING from {builder_module.logger.name}; got {caplog.records!r}"
    joined = " ".join(r.getMessage() for r in ours)
    assert "adapter.stop()" in joined
    assert str(tmp_dir) in joined, "the warning must name the tree that may be held"
    assert not _still_present(tmp_dir)
    assert isinstance(obs, dict)


@pytest.mark.asyncio
async def test_a_failed_adapter_stop_does_not_abandon_the_build_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shutdown is not the work. A good result must survive a bad `stop()`."""
    # Arrange
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    _install_adapter(monkeypatch, stop_raises=True)
    agent = _agent()

    # Act
    await _run_perceive(agent, target)

    # Assert
    assert agent._transporter_result is not None
    assert agent._transporter_result["builder_source"] == "visiting"


# ---------------------------------------------------------------------------
# 4. Cleanup must not be able to destroy the work
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failing_cleanup_does_not_discard_a_successful_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The replaced one-shot could not raise; this helper deliberately can.

    `remove_workdir_off_loop` propagates a worker failure to its awaiting
    caller by design. Awaiting it bare in the `finally` therefore let a cleanup
    error escape `perceive` and discard an already-successful build -- measured
    before the guard was added:

        RAISING CLEANUP WORKER: ESCAPED RuntimeError  (result_set=True -- DESTROYED)
    """
    # Arrange
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    _install_adapter(monkeypatch)
    leaked: list[Path] = []

    def _boom(p: Any, *a: Any, **kw: Any) -> None:
        leaked.append(Path(p))
        raise RuntimeError("cleanup worker failure")

    monkeypatch.setattr(iso, "remove_workdir", _boom)
    agent = _agent()

    # Act
    with caplog.at_level(logging.WARNING, logger=builder_module.logger.name):
        obs = await agent.perceive(
            {
                "intent": "build_code",
                "params": {
                    "title": "t", "description": "d",
                    "target_files": [str(target)], "force_visiting": True,
                },
            }
        )

    # Assert: the observation survived, the result survived, and the failure was
    # reported rather than swallowed.
    assert isinstance(obs, dict)
    assert agent._transporter_result is not None
    assert agent._transporter_result["builder_source"] == "visiting"
    ours = [
        r for r in caplog.records
        if r.name == builder_module.logger.name and r.levelno >= logging.WARNING
    ]
    joined = " ".join(r.getMessage() for r in ours)
    assert "could not remove build tree" in joined
    assert "cleanup worker failure" in joined

    for p in leaked:
        shutil.rmtree(p, ignore_errors=True)


@pytest.mark.asyncio
async def test_cancellation_still_escapes_the_cleanup_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard swallows cleanup errors -- it must NOT swallow cancellation."""
    # Arrange
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    _install_adapter(monkeypatch)
    seen: list[Path] = []

    def _cancel(p: Any, *a: Any, **kw: Any) -> None:
        seen.append(Path(p))
        raise asyncio.CancelledError("shutting down")

    monkeypatch.setattr(iso, "remove_workdir", _cancel)

    # Act / Assert
    with pytest.raises(asyncio.CancelledError):
        await _run_perceive(_agent(), target)

    assert seen, "the cleanup never ran -- the test proves nothing"
    for p in seen:
        shutil.rmtree(p, ignore_errors=True)


# ---------------------------------------------------------------------------
# 5. Regression guard on the seam itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_visiting_path_removes_exactly_the_tree_it_gave_the_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pin the seam at runtime: cleanup targets the adapter's ACTUAL cwd.

    A source scan for `shutil.rmtree` would miss `from shutil import rmtree`,
    reject a comment, and fail where source is unavailable. This asserts the
    property that matters -- the retrying remover is what runs, on the tree the
    SDK was actually pointed at.
    """
    # Arrange
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    _install_adapter(monkeypatch)
    seen: list[Path] = []
    real = iso.remove_workdir

    def _spy(p: Any, *a: Any, **kw: Any) -> None:
        seen.append(Path(p))
        real(Path(p), *a, **kw)

    monkeypatch.setattr(iso, "remove_workdir", _spy)

    # Act
    await _run_perceive(_agent(), target)

    # Assert: only the SDK's own cwd is ever removed. NOT "exactly once" --
    # `remove_workdir_off_loop` documents a deliberate duplicate removal when
    # executor submission enqueues and then raises, and it is idempotent, so
    # pinning a call count would pin more than the contract offers.
    assert _FakeAdapter.last is not None
    expected = Path(_FakeAdapter.last.cwd)
    assert seen, "the retrying remover never ran on the SDK cwd"
    assert all(p == expected for p in seen), (
        f"cleanup touched something other than the SDK cwd {expected}: {seen!r}"
    )
    assert not _still_present(expected)
